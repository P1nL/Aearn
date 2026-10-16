"""C18 original ports against transactional in-memory DB facts; no live IO."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from typing import Any, Iterator
from uuid import uuid4

import pytest
from psycopg.pq import TransactionStatus

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.parameter_profiles import freeze_profile
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.pipeline_repository import PipelineArtifactRepository, PipelineRepositoryError
from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending
from app.services.learning.item_supply.private_enhancement_service import RECOVERY_SLOT
from app.services.learning.item_supply.private_generation_persistence import OUTPUT_ID, PREPARATION_ID, JOB_ID
from app.services.learning.item_supply.private_generation_persistence_phase import PHASE_KEY
from app.services.learning.item_supply.private_native_admission_facts import PreparedPrivateReview
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from tests.learning.test_private_generation_persistence import fixture as original_fixture, executor_fixture


def fixture(monkeypatch: pytest.MonkeyPatch) -> Any:
    from app.services.learning.item_supply import private_generation_persistence_phase as module
    from app.services.learning.item_supply import pipeline_repository
    from app.services.learning.item_supply import private_development_model_accounting

    f = original_fixture(monkeypatch)
    s, conn = f.state, f.conn
    s.now += timedelta(hours=3)  # Both original writer deadlines expired.
    s.bridge = s.complete = s.writer = s.batch = None
    s.phase = False
    s.prepareds = {}
    s.ready = True
    s.fail_complete = False
    s.new_job = uuid4()
    s.events = []
    s.transaction_depth = 0
    output = s.output['payload_json']
    output.update(consumed_id=str(uuid4()), settlement_id=str(uuid4()), request_hash=canonical_hash(output['capture']['context']['request']))
    output['capture']['context']['lease'] = f.lease.model_dump(mode='json')
    s.output['payload_hash'] = canonical_hash(output)
    f.service._generation_persistence_phase = None
    f.service.development_accounting_enabled = True
    monkeypatch.setattr(f.service, '_generation_output_ready', lambda: None)
    original_transaction = conn.transaction

    @contextmanager
    def transaction() -> Iterator[None]:
        before = deepcopy((s.bridge, s.complete, s.writer, s.batch, s.phase, s.quality, s.prepareds))
        s.transaction_depth += 1
        try:
            with original_transaction():
                yield
        except Exception:
            s.bridge, s.complete, s.writer, s.batch, s.phase, s.quality, s.prepareds = before
            raise
        finally:
            s.transaction_depth -= 1

    monkeypatch.setattr(conn, 'transaction', transaction)
    runtime = f.facts.pipeline.runtime

    def guard(ref: Any, lease: Any) -> Any:
        assert ref == f.ref and lease.job_id == s.new_job and s.phase
        if s.now >= min(lease.expires_at, lease.parent_deadline):
            raise PrivateNativePending('offline_current_writer_expired')
        assert f.service.base_service.type_owner.current_source_binding is f.selector
        return s.now

    monkeypatch.setattr(f.facts, '_guard', guard)
    authority: Any = object.__new__(RagSourceAuthority)
    authority._current = SimpleNamespace(conn=conn)
    authority.assert_current = lambda material, receipt: None
    f.facts.source_authority = authority
    executor, calls = executor_fixture(f, monkeypatch)
    executor.development_accounting_enabled = True
    f.service._executor = executor
    f.service.base_service.type_owner.resolve_content = lambda *a, **kw: SimpleNamespace(spec=f.spec)
    f.service.base_fallback_owner = lambda: SimpleNamespace(resolve=lambda task: f.selector, require=lambda cap: cap.require())

    def record_wait(**kw: Any) -> None:
        assert s.phase and kw['lease'] == s.writer
        assert f.service.base_service.type_owner.current_source_binding is f.selector
        s.events.append('wait')

    monkeypatch.setattr(f.service, 'record_wait_window', record_wait)

    def bind_phase(**kw: Any) -> Any:
        assert s.events[-1] == 'accounting'
        s.phase = True
        s.events.append('phase')
        return f.ref

    monkeypatch.setattr(f.service, 'bind_slot_phase', bind_phase)

    class Accounting:
        def __init__(self, connection: Any, *, enabled: bool) -> None:
            assert connection is conn and enabled

        def prepare_batch(self, **kw: Any) -> Any:
            assert s.transaction_depth == 1, '551 nominal limits must be inserted in the caller TOP, not a SAVEPOINT'
            s.events.append('batch')
            s.batch = dict(id=uuid4(), root_id=kw['root_id'], window_id=uuid4(), global_limit_ids=[uuid4()],
                user_limit_ids=[uuid4()], provider_key=kw['provider_key'], model=kw['model'], valid_until=kw['valid_until'])
            return SimpleNamespace(batch_id=s.batch['id'], valid_until=s.batch['valid_until'])

        def bind_job(self, **kw: Any) -> None:
            assert s.events[-1] == 'first_claim' and kw['parent_job_id'] is None
            assert kw['lease'] == s.writer and not s.phase
            s.events.append('accounting')

    monkeypatch.setattr(module, 'PrivateDevelopmentModelAccountingOwner', Accounting)

    def accounting_projection(*a: Any, **kw: Any) -> Any:
        if s.batch is None:
            return None
        return dict(namespace='private', batch_id=s.batch['id'], root_id=s.batch['root_id'], window_id=s.batch['window_id'],
            global_limit_ids=s.batch['global_limit_ids'], user_limit_ids=s.batch['user_limit_ids'],
            provider_key=s.batch['provider_key'], model=s.batch['model'], valid_until=s.batch['valid_until'],
            mode=private_development_model_accounting.MODE, cumulative_caps_enforced=False)

    monkeypatch.setattr(module, 'accounting_batch_for_lease', accounting_projection)
    monkeypatch.setattr(private_development_model_accounting, 'accounting_batch_for_lease', accounting_projection)

    def enqueue(**kw: Any) -> Any:
        assert s.transaction_depth == 1
        assert s.events[-1] == 'batch' and kw['stage_key'] == PHASE_KEY and kw['parent_job_id'] is None
        assert kw['profile'].profile_key.agent_role == 'native.private.persistent.persistence_quality.python-kc-binding-v1'
        assert kw['profile'].profile_key.prompt_version == 'private-durable-persistence-quality-v1'
        s.events.append('enqueue')
        s.profile = freeze_profile(kw['profile'], bound_at=s.now)
        return s.new_job

    runtime.enqueue = enqueue
    runtime.claim = lambda **kw: pytest.fail('root-wide claim forbidden')
    runtime._lease = lambda row, visibility: s.writer

    def control(lease: Any, **kw: Any) -> Any:
        assert lease.job_id == s.new_job and s.writer is not None
        assert lease.model_dump(exclude={'state_version'}) == s.writer.model_dump(exclude={'state_version'})
        if s.now >= s.writer.expires_at:
            raise PrivateNativePending('offline_current_writer_expired')
        return {'scope_id': f.ref.scope_id, 'attempt_count': 1}

    runtime._control = control
    runtime.refresh_lease = lambda lease, **kw: (control(lease), s.writer)[1]
    runtime.next_stage = lambda lease: 'validating' if s.checkpoint is not None else 'generating'

    def checkpoint(lease: Any, value: Any, **kw: Any) -> None:
        assert s.artifact is not None and lease == s.writer and s.checkpoint is None
        s.checkpoint = dict(id=uuid4(), stage=value.stage, attempt=value.attempt, status=value.status,
            lease_generation=lease.generation, receipt_hash=value.receipt_hash, safe_reason=value.safe_reason)
        s.writer = s.writer.model_copy(update={'state_version': 3})
        s.events.append('checkpoint')

    runtime.checkpoint = checkpoint

    class Storage:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        def store_candidate(self, **kw: Any) -> Any:
            assert kw['candidate_key'] == 'private.native.'+f.ref.business_item_id.hex
            return uuid4()

        def store_version(self, **kw: Any) -> Any:
            assert kw['version'] == 1
            return SimpleNamespace(id=uuid4())

    monkeypatch.setattr(pipeline_repository, 'PostgresPrivateSupplyStorage', Storage)
    repo = PipelineArtifactRepository(conn)
    repo.runtime = runtime
    f.facts.pipeline.artifacts = repo

    def journal(key: str, body: Any) -> Any:
        return dict(id=uuid4(), pack_task_id=f.task.pack_task_id, user_id=f.task.user_id, epoch=f.task.epoch,
            scope_id=f.task.scope_id, intent_hash=f.task.intent_hash, record_kind='private_status', operation_key=key,
            payload_json=body, payload_hash=canonical_hash(body))

    original_execute = conn.execute

    def execute(sql: str, params: Any = ()) -> Any:
        assert conn.info.transaction_status == TransactionStatus.INTRANS
        conn.sql.append(sql)
        row: Any = None
        if 'private_generation_persistence_phase_ready()' in sql:
            row = {'ready': s.ready}
        elif sql.startswith('SELECT max(profile_version)'):
            row = {'v': 0}
        elif 'private_generation_persistence_phase_first_claim(' in sql:
            assert params == (OUTPUT_ID, s.new_job, s.batch['id'], s.origin_id)
            if s.bridge is not None:
                raise PrivateNativePending('offline_phase_already_bound')
            assert s.events[-1] == 'enqueue'
            s.writer = JobLeaseV1(job_id=s.new_job, visibility='private', owner_id=f.task.user_id, owner_epoch=1,
                lease_owner='private.persistence.'+OUTPUT_ID.hex, generation=1, state_version=2,
                expires_at=s.now+timedelta(hours=1), parent_deadline=s.profile.parent_deadline_at,
                profile=s.profile, retry_policy=f.lease.retry_policy)
            body = dict(schema_version='private_generation_persistence_phase_v1', output_id=str(OUTPUT_ID),
                preparation_id=str(PREPARATION_ID), output_hash=s.output['payload_hash'], generation_job_id=str(JOB_ID),
                generation_request_hash=canonical_hash(f.request.model_dump(mode='json')),
                generation_profile_hash=f.request.profile.profile_hash, ref=f.ref.model_dump(mode='json'),
                writer_job_id=str(s.new_job), batch_id=str(s.batch['id']), lease=s.writer.model_dump(mode='json'),
                source_origin_id=str(s.origin_id), bound_top_xid=str(conn.top), bound_at=s.now.isoformat(), valid_until=s.writer.expires_at.isoformat(),
                **{'original_'+name: output[name] for name in ('binding_id', 'started_id', 'consumed_id', 'settlement_id')})
            s.bridge = journal(PHASE_KEY, body)
            s.events.append('first_claim')
            row = {'job_id': s.new_job}
        elif 'private_generation_persistence_phase_bound(' in sql or 'private_generation_persistence_phase_committed(' in sql:
            if s.bridge is None or params != (s.bridge['id'], s.origin_id):
                raise PrivateNativePending('offline_binding_absent')
            if s.bridge['payload_json']['bound_top_xid'] == str(conn.top):
                raise PrivateNativePending('offline_binding_same_top')
            control(s.writer)
            row = s.bridge
            if 'phase_committed(' in sql:
                if s.complete is None:
                    raise PrivateNativePending('offline_completion_absent')
                if s.complete['payload_json']['completed_top_xid'] == str(conn.top):
                    raise PrivateNativePending('offline_completion_same_top')
                row = s.complete
        elif 'private_generation_persistence_phase_complete(' in sql:
            assert params == (s.bridge['id'], s.artifact['id'], s.origin_id)
            assert s.checkpoint is not None and s.writer.state_version == 3
            if s.fail_complete:
                raise PrivateNativePending('offline_completion_failed')
            if s.complete is None:
                s.complete = journal(PHASE_KEY+'.complete', dict(schema_version='private_generation_persistence_complete_v1',
                    binding_id=str(s.bridge['id']), output_id=str(OUTPUT_ID), writer_job_id=str(s.new_job),
                    artifact_id=str(s.artifact['id']), artifact_hash=s.artifact['artifact_hash'], candidate_id=str(s.artifact['candidate_id']),
                    version_id=str(s.artifact['version_id']), checkpoint_id=str(s.checkpoint['id']), source_origin_id=str(s.origin_id),
                    completed_top_xid=str(conn.top), completed_at=s.now.isoformat()))
            row = {'id': s.complete['id']}
        elif sql.startswith('SELECT * FROM tutor_item_supply_private_persistent_pack_journal'):
            row = s.output if params[-1].startswith('private.generation.output.') else s.bridge if params[-1] == PHASE_KEY else s.complete
        elif sql.startswith('SELECT scope_hash'):
            row = {'scope_hash': f.request.scope_hash}
        elif "SELECT payload_json->'ref' AS ref" in sql:
            assert s.phase and str(s.new_job) in params
            row = {'ref': f.ref.model_dump(mode='json')}
        elif sql.startswith('SELECT id FROM tutor_item_supply_private_generation_artifacts WHERE job_id='):
            row = s.artifact or s.checkpoint
        elif sql.startswith('INSERT INTO tutor_item_supply_private_generation_artifacts '):
            assert s.phase and s.bridge is not None and s.bridge['payload_json']['bound_top_xid'] != str(conn.top)
            assert params[3] == s.new_job and params[4:6] == (1, 2) and s.artifact is None
            source, receipt, request = (p.obj for p in params[-3:])
            assert request == output['capture']['context']['request'] and source == output['capture']['result']['source']
            assert receipt == output['capture']['result']['receipt']
            s.artifact = dict(id=uuid4(), job_id=params[3], lease_generation=1, lease_state_version=2,
                candidate_id=params[6], version_id=params[7], artifact_key=params[8], source_hash=params[9], content_hash=params[10],
                mode=params[11], source_json=source, receipt_json=receipt, request_json=request,
                artifact_hash=canonical_hash(dict(source=source, receipt=receipt)), storage_key='private.native.'+f.ref.business_item_id.hex,
                storage_version=1, public_json=source['public'], private_json=source['private'])
            s.events.append('artifact')
            row = s.artifact
        elif 'FROM tutor_item_supply_private_generation_artifacts a' in sql:
            row = s.artifact
        elif 'FROM tutor_item_supply_private_checkpoints' in sql:
            row = s.checkpoint
        else:
            return original_execute(sql, params)
        return SimpleNamespace(fetchone=lambda: row, fetchall=lambda: [] if row is None else [row])

    monkeypatch.setattr(conn, 'execute', execute)
    owner = f.service.generation_persistence_phase_owner()
    f.owner, f.executor, f.calls, f.repo = owner, executor, calls, repo
    return f


def issued(f: Any) -> Any:
    with f.top():
        return f.owner.issue(task_ref=f.task, output_id=OUTPUT_ID)


def stored(f: Any, cap: Any) -> Any:
    with f.top():
        return f.owner.persist(cap)


def test_current_uses_accounting_batch_projection_not_raw_row(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.learning.item_supply import private_generation_persistence_phase as module

    f = fixture(monkeypatch)
    cap = issued(f)
    with f.top():
        projection = module.accounting_batch_for_lease(f.conn, cap.writer_lease, now=f.state.now)
        assert projection is not None and 'id' not in projection
        assert str(projection['batch_id']) == f.state.bridge['payload_json']['batch_id']
        assert f.owner.require(cap).lease.job_id == f.state.new_job
        monkeypatch.setattr(module, 'accounting_batch_for_lease', lambda *a, **kw: projection | {'batch_id': uuid4()})
        with pytest.raises(PrivateNativePending, match='original_accounting_required'):
            f.owner.require(cap)


def test_issue_551_batch_and_enqueue_stay_in_caller_top(monkeypatch: pytest.MonkeyPatch) -> None:
    f = fixture(monkeypatch)
    with pytest.raises(LookupError, match='caller A rollback'), f.top():
        cap = f.owner.issue(task_ref=f.task, output_id=OUTPUT_ID)
        assert f.state.transaction_depth == 1 and cap.bridge_id == f.state.bridge['id']
        assert f.state.events == ['batch', 'enqueue', 'first_claim', 'accounting', 'phase', 'wait']
        raise LookupError('caller A rollback')
    assert f.state.transaction_depth == 0
    assert f.state.bridge is None and f.state.batch is None and f.state.writer is None and not f.state.phase


def test_a_b_c_probes_use_db_facts_and_keep_generation_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    f = fixture(monkeypatch)
    original = deepcopy(f.state.output)
    with pytest.raises(LookupError, match='probe A'), f.top():
        abandoned = f.owner.issue(task_ref=f.task, output_id=OUTPUT_ID)
        with pytest.raises(PrivateNativePending, match='binding_same_top'):
            f.owner.persist(abandoned)
        raise LookupError('probe A')
    assert f.state.bridge is None and f.state.writer is None
    cap = issued(f)
    assert f.state.events[-6:] == ['batch', 'enqueue', 'first_claim', 'accounting', 'phase', 'wait']
    assert cap.generation_lease.expires_at < f.state.now and cap.generation_lease.parent_deadline < f.state.now
    assert cap.request.profile != cap.writer_lease.profile and cap.request == f.request
    with f.top(), pytest.raises(PrivateNativePending, match='binding_absent'):
        f.owner.require(abandoned)
    with f.top(), pytest.raises(PrivateNativePending, match='already_bound'):
        f.owner.issue(task_ref=f.task, output_id=OUTPUT_ID)
    with pytest.raises(LookupError, match='probe B'), f.top():
        f.owner.persist(cap)
        with pytest.raises(PrivateNativePending, match='completion_same_top'):
            f.owner.committed_artifact(cap)
        raise LookupError('probe B')
    with f.top(), pytest.raises(PrivateNativePending, match='completion_absent'):
        f.owner.committed_artifact(cap)
    assert f.state.artifact is None and f.state.checkpoint is None and f.state.writer.state_version == 2
    artifact_id = stored(f, cap)
    with f.top():
        current, artifact = f.owner.committed_artifact(cap)
        assert artifact['id'] == artifact_id and current.lease.state_version == 3
        assert artifact['request_json'] == original['payload_json']['capture']['context']['request']
        assert f.owner.persist(cap) == artifact_id
    assert f.state.output == original and f.state.done is None
    assert not f.service._prepared and not f.service._results and not f.service._started
    assert not any('continuation_bound(' in sql for sql in f.conn.sql)


@pytest.mark.parametrize('denial', ['wrong_output', 'not_ready', 'copied_cap', 'nested_capture', 'expired', 'partial', 'completion_failure'])
def test_exact_phase_denials_preserve_output(monkeypatch: pytest.MonkeyPatch, denial: str) -> None:
    f = fixture(monkeypatch)
    original = deepcopy(f.state.output)
    if denial in ('wrong_output', 'not_ready'):
        f.state.ready = denial != 'not_ready'
        with f.top(), pytest.raises(PrivateNativePending):
            f.owner.issue(task_ref=f.task, output_id=uuid4() if denial == 'wrong_output' else OUTPUT_ID)
        assert not f.state.events
    else:
        cap = issued(f)
        if denial == 'copied_cap':
            cap = replace(cap)
        elif denial == 'nested_capture':
            cap.capture['context']['producer_binding'][0] = 'changed'
        elif denial == 'expired':
            f.state.now = cap.writer_lease.expires_at
        elif denial == 'partial':
            f.state.artifact = {'id': uuid4()}
        elif denial == 'completion_failure':
            f.state.fail_complete = True
        with f.top(), pytest.raises(PrivateNativePending):
            f.owner.persist(cap)
        assert f.state.complete is None and f.state.checkpoint is None
        if denial != 'partial':
            assert f.state.artifact is None
    assert f.state.output == original


def test_pipeline_profile_exception_requires_exact_phase_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    f = fixture(monkeypatch)
    cap = issued(f)
    with f.top():
        current = f.owner.require(cap)
        args = dict(lease=current.lease, scope_id=cap.ref.scope_id, request=cap.request, result=cap.result,
            artifact_key='generation.'+PREPARATION_ID.hex, now=f.state.now, mode='live', source_authority=f.facts.source_authority,
            private_slot_ref=cap.ref)
        with pytest.raises(PipelineRepositoryError, match='PIPELINE_REQUEST_MISMATCH'):
            f.repo.store_generation(**args)
        with pytest.raises(PrivateNativePending, match='original_cap_required'):
            f.repo.store_generation(**args, persistence_phase=replace(cap))
        changed = cap.request.model_copy(update={'profile': cap.writer_lease.profile})
        with pytest.raises(PipelineRepositoryError, match='EXACT_DATA_REQUIRED'):
            f.repo.store_generation(**(args | {'request': changed}), persistence_phase=cap)
        assert f.state.artifact is None
    stored(f, cap)


def test_quality_probe_replaced_without_old_sender_or_old_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    f = fixture(monkeypatch)
    cap = issued(f)
    stored(f, cap)
    executor = f.executor
    paid: list[Any] = []

    def validate(**kw: Any) -> Any:
        assert kw['lease'].job_id == f.state.new_job and kw['artifact_id'] == f.state.artifact['id']
        f.state.quality = True
        return uuid4(), object()

    def prepare(**kw: Any) -> Any:
        assert kw['resources'].requests == 7
        original = SimpleNamespace(artifact_id=kw['artifact_id'], lease=kw['lease'], source=f.result.source,
            binding=SimpleNamespace(profile_hash=kw['lease'].profile.profile_hash))
        p = PreparedPrivateReview(kw['ref'], original, kw['spec'], f.request, kw['policy'], uuid4())
        assert p.request.profile != p.original.lease.profile
        f.state.prepareds[p.preparation_id] = f.conn.top
        return p

    def run(p: Any) -> Any:
        assert f.conn.info.transaction_status == TransactionStatus.IDLE
        with f.top():
            if p.preparation_id not in f.state.prepareds or f.state.prepareds[p.preparation_id] == f.conn.top:
                raise PrivateNativePending('offline_original_aux_not_committed')
        assert f.conn.info.transaction_status == TransactionStatus.IDLE
        assert p.preparation_id not in f.facts._started
        f.facts._started.add(p.preparation_id)
        paid.append(p)
        return object()

    monkeypatch.setattr(f.facts, 'validate', validate)
    monkeypatch.setattr(f.facts, 'prepare_review', prepare)
    monkeypatch.setattr(f.facts, 'run_review', run)
    with pytest.raises(LookupError, match='probe C'), f.top():
        old_handoff = executor.adopt_persisted_phase(cap)
        old_prepared = executor.prepare_persistence_phase_review(old_handoff)
        raise LookupError('probe C')
    with pytest.raises(PrivateNativePending, match='aux_not_committed'):
        executor.run_initial_recovery_review(old_prepared)
    assert not paid
    with f.top():
        handoff = executor.adopt_persisted_phase(cap)
        assert handoff is not old_handoff
        with pytest.raises(PrivateNativePending, match='executor_handoff_required'):
            executor.prepare_persistence_phase_review(old_handoff)
        prepared = executor.prepare_persistence_phase_review(handoff)
    with pytest.raises(PrivateNativePending, match='live_work_required'):
        executor.run_initial_recovery_review(old_prepared)
    outcome = executor.run_initial_recovery_review(prepared)
    assert outcome.reason == 'offline-original-finish-port' and paid == [prepared]
    assert RECOVERY_SLOT not in executor._durable_initial_quality
    assert not executor._initial_success and not executor._initial_authors
    assert prepared.original.binding.profile_hash == cap.writer_lease.profile.profile_hash
    assert prepared.request == cap.request and cap.request.profile == cap.generation_lease.profile
