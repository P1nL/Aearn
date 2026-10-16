"""C17 fixed-case offline ports only; no real DB/output files/provider IO."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, Iterator
from uuid import uuid4

import pytest
from psycopg.pq import TransactionStatus

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.finite_candidate_factory import build_finite_candidate_spec, build_finite_generation_request
from app.services.learning.item_supply.generation_contracts import GenerationReceiptV2, GenerationResultV2, ProviderReceiptV2, ProviderUsageV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
from app.services.learning.item_supply.persistent_pack_contracts import PersistentPackTaskRef
from app.services.learning.item_supply.persistent_pack_current_source import IssuedCurrentPackSourceBinding, _seal
from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending, PrivateSlotRef
from app.services.learning.item_supply.private_enhancement_service import (
    RECOVERY_BUSINESS, RECOVERY_MAPPING, RECOVERY_ROOT, RECOVERY_SCOPE, RECOVERY_SLOT,
    RECOVERY_TASK, RECOVERY_USER, PrivateEnhancementService,
)
from app.services.learning.item_supply.private_generation_persistence import OUTPUT_ID, PREPARATION_ID, JOB_ID
from app.services.learning.item_supply.private_native_admission_facts import PrivateNativeAdmissionFactsOwner, PreparedPrivateReview
from app.services.learning.item_supply.private_native_committed_progress import PrivateNativeCommittedProgressOwner
from app.services.learning.item_supply.private_native_pack_executor import PrivateNativePackExecutor, PrivatePhaseOutcome
from tests.learning.test_item_supply_generation import make_request, SyntheticAuthority
from tests.learning.test_item_supply_shared_validation import _candidate
from tests.learning.test_item_supply_finite_candidate_validation import _source


class OfflineConnection:
    def __init__(self, state: Any) -> None:
        self.state = state
        self.autocommit = False
        self.info = SimpleNamespace(transaction_status=TransactionStatus.IDLE)
        self.top = 0
        self.sql: list[str] = []

    @contextmanager
    def transaction(self) -> Iterator[None]:
        outer = self.info.transaction_status == TransactionStatus.IDLE
        if outer:
            self.top += 1
        before = self.state.artifact, self.state.checkpoint, self.state.done, self.state.review_started
        self.info.transaction_status = TransactionStatus.INTRANS
        try:
            yield
        except Exception:
            self.state.artifact, self.state.checkpoint, self.state.done, self.state.review_started = before
            raise
        finally:
            self.info.transaction_status = TransactionStatus.IDLE if outer else TransactionStatus.INTRANS

    def execute(self, sql: str, params: Any = ()) -> Any:
        assert self.info.transaction_status == TransactionStatus.INTRANS
        self.sql.append(sql)
        s = self.state
        row: Any
        if 'private_generation_durability_ready()' in sql:
            row = {'ready': True}
        elif 'pg_current_xact_id()' in sql:
            row = dict(top_xid=str(self.top), isolation='read committed', read_only='off')
        elif 'SELECT id,payload_json,payload_hash' in sql:
            row = s.output
        elif 'private_generation_output_committed(' in sql:
            assert params[0] == PREPARATION_ID and params[1].obj == s.output['payload_json']['capture']
            if s.output['payload_json']['captured_top_xid'] == str(self.top):
                raise PrivateNativePending('offline_output_same_top')
            row = {'id': OUTPUT_ID}
        elif 'private_initial_author_continuation_bound(' in sql:
            assert params == (s.binding_id, s.origin_id)
            row = {'id': s.binding_id, 'payload_json': {'valid_until': s.bound_until.isoformat()}}
        elif 'private_native_source_current(' in sql:
            row = {'ok': s.source_current}
        elif 'private_initial_author_continuation_terminal(id)' in sql:
            row = {'status': 'artifact'}
        elif 'SELECT operation_key,payload_json' in sql:
            row = dict(operation_key=s.started['operation_key'][:-len('.started')]+'.result', payload_json=s.done['payload_json'])
        elif 'SELECT id,operation_key,payload_json' in sql:
            row = s.started
        elif 'FROM tutor_item_supply_private_generation_artifacts a' in sql:
            if s.expire_on_artifact_read:
                s.now = s.bound_until
            row = s.artifact
        elif 'FROM tutor_item_supply_private_checkpoints' in sql:
            row = s.checkpoint
        elif "payload_json->>'stage'='review'" in sql:
            row = {'id': uuid4()} if s.review_started else None
        elif sql.startswith('SELECT id FROM tutor_item_supply_private_persistent_pack_journal'):
            row = None if str(params[-1]).startswith('private.stage.') and not s.review_started else {'id': uuid4()}
        elif 'FROM tutor_item_supply_private_native_quality_evidence' in sql:
            row = {'id': uuid4()} if s.quality else None
        elif 'SELECT id,payload_json' in sql:
            row = s.done
        else:
            pytest.fail('unexpected offline SQL: '+sql)
        return SimpleNamespace(fetchone=lambda: row)


def fixture(monkeypatch: pytest.MonkeyPatch) -> Any:
    from app.services.learning.item_supply import private_generation_persistence as persistence_module
    from app.services.learning.item_supply import private_development_model_accounting as accounting_module
    from app.services.learning.item_supply import private_finite_factory

    now = datetime.now(UTC)
    base, _ = make_request()
    original, materials, original_source = _candidate('python-kc-binding-v1')
    spec = build_finite_candidate_spec(target_id=original.target_id, variant_id=original.allocation.variant_id,
        seed=original.seed, item_key='private-native.'+RECOVERY_BUSINESS.hex, version='v1', materials=materials,
        runtime_profile_hash=None, scorer_version=original.coverage_blueprint.scope.scorer_version,
        assistance_policy_hash=original.coverage_blueprint.scope.assistance_policy_hash, policy_version=original.coverage_blueprint.policy_version,
        difficulty_profile=original.blueprint.difficulty_profile, publication_policy=original.blueprint.publication_policy,
        public_spec_version=original.blueprint.version, allocation=original.allocation)
    source = _source(spec, original_source.private.content.model_dump(mode='json'))
    values = base.profile.values.model_copy(update=dict(request_timeout_ms=100000, stage_deadline_ms=6000000, parent_deadline_ms=6000000))
    profile = base.profile.model_copy(update=dict(values=values, bound_at=now, parent_deadline_at=now+timedelta(minutes=100)))
    request = build_finite_generation_request(spec, candidate_id=PREPARATION_ID, profile=profile, limits=base.limits, materials=materials)
    sources = tuple(SyntheticAuthority().authorize(m) for m in materials)
    provider = ProviderReceiptV2(provider='deepseek', provider_version='offline', configured_model='deepseek-flash',
        model='deepseek-flash', prompt_version='offline', run_id=uuid4(), request_attempt_bound=1, actual_requests=1,
        usage=ProviderUsageV2(state='known', input_tokens=17, output_tokens=11, total_tokens=28), mode='provider')
    result = GenerationResultV2(state='staged', safe_reason='staged', source=source, receipt=GenerationReceiptV2(
        candidate_id=PREPARATION_ID, scope_hash=request.scope_hash, source_hash=source.source_hash, content_hash=source.content_hash,
        provider=provider, sources=sources))
    lease = JobLeaseV1(job_id=JOB_ID, visibility='private', owner_id=RECOVERY_USER, owner_epoch=1,
        lease_owner='offline.original.continuation', generation=1, state_version=2,
        expires_at=now+timedelta(hours=1), parent_deadline=profile.parent_deadline_at, profile=profile)
    task = PersistentPackTaskRef(pack_task_id=RECOVERY_TASK, user_id=RECOVERY_USER, epoch=1, scope_id=RECOVERY_SCOPE,
        mapping_receipt_id=RECOVERY_MAPPING, demand_id=uuid4(), public_task_id=uuid4(), intent_hash='a'*64)
    ref = PrivateSlotRef(pack_task_id=RECOVERY_TASK, user_id=RECOVERY_USER, epoch=1, scope_id=RECOVERY_SCOPE,
        mapping_receipt_id=RECOVERY_MAPPING, slot_id=RECOVERY_SLOT, business_item_id=RECOVERY_BUSINESS,
        root_id=RECOVERY_ROOT, goal_scope_id=uuid4(), slot='practice')
    state = SimpleNamespace(now=now, artifact=None, checkpoint=None, done=None, source_current=True,
        review_started=False, quality=False, binding_id=uuid4(), origin_id=uuid4(), writes=[], fail_result=False,
        bound_until=lease.expires_at, expire_on_artifact_read=False)
    state.started = dict(id=uuid4(), operation_key='p7.private.initial-author.continuation.20261016.offline.author.started',
        payload_json=dict(schema_version='private_native_stage_v1', job_id=str(JOB_ID), slot_id=str(RECOVERY_SLOT),
            stage='author', status='started', subject_hash=canonical_hash('v1'), receipt_id=None))
    capture = dict(schema_version='private_generation_capture_v1', context=dict(ref=ref.model_dump(mode='json'),
        request=request.model_dump(mode='json'), lease=lease.model_dump(mode='json'), scope_id=str(RECOVERY_SCOPE),
        reservation_id=str(uuid4()), sources=[s.model_dump(mode='json') for s in sources], attempt_bound=1, mode='live',
        producer_binding=['deepseek', 'deepseek-flash']), result=result.model_dump(mode='json'))
    payload = dict(schema_version='private_generation_output_v1', preparation_id=str(PREPARATION_ID), capture=capture,
        binding_id=str(state.binding_id), started_id=str(state.started['id']), captured_top_xid='0')
    state.output = dict(id=OUTPUT_ID, payload_json=payload, payload_hash=canonical_hash(payload))
    conn = OfflineConnection(state)
    service: Any = object.__new__(PrivateEnhancementService)
    facts: Any = object.__new__(PrivateNativeAdmissionFactsOwner)
    core: Any = object.__new__(PersistentPackTaskOwner)
    service.conn, service.settings, service.facts_owner, service.core = conn, object(), facts, core
    facts.conn, facts.settings = conn, service.settings
    core.conn, core.settings = conn, service.settings
    core.user_id, core.epoch = RECOVERY_USER, 1
    slot = SimpleNamespace(slot_id=RECOVERY_SLOT, logical_item_id=RECOVERY_BUSINESS, slot='practice-1')
    record = SimpleNamespace(ref=task, enhancement='prefer_private', slots=(slot,))
    core._task = lambda actual: record
    core._versions = lambda actual: {'practice-1': SimpleNamespace(published_version_id=uuid4())}
    public = SimpleNamespace(current_source_binding=None, resolve_content=lambda *a, **kw: SimpleNamespace(spec=original))
    core.type_owner = public
    service.base_service = SimpleNamespace(type_owner=public)
    selector = IssuedCurrentPackSourceBinding(core, uuid4(), task, 'a'*64, 'b'*64, 'c'*64,
        now+timedelta(days=1), materials, (), SimpleNamespace(model_dump=lambda **kw: {}))
    core._current_source_bindings = {selector.binding_id: (selector, _seal(selector))}
    monkeypatch.setattr(IssuedCurrentPackSourceBinding, 'require', lambda actual: None)
    monkeypatch.setattr(IssuedCurrentPackSourceBinding, 'origin_id', lambda actual: state.origin_id)
    monkeypatch.setattr(service, '_guard', lambda: state.now)

    def source_binding(actual: Any) -> Any:
        assert actual == task and public.current_source_binding is selector
        return selector

    @contextmanager
    def source_front(actual: Any) -> Iterator[Any]:
        assert conn.info.transaction_status == TransactionStatus.INTRANS
        public.current_source_binding = selector
        try:
            yield selector
        finally:
            public.current_source_binding = None

    @contextmanager
    def top() -> Iterator[None]:
        with conn.transaction(), source_front(task):
            yield

    monkeypatch.setattr(service, '_recovery_source', source_binding)
    monkeypatch.setattr(service, '_fresh_recovery_source', source_front)

    def guard(actual_ref: Any, actual_lease: Any) -> Any:
        assert actual_ref == ref and actual_lease.job_id == JOB_ID
        if state.now >= actual_lease.expires_at:
            raise PrivateNativePending('offline_original_writer_expired')
        return state.now

    monkeypatch.setattr(facts, '_guard', guard)
    facts.source_authority = SimpleNamespace(connection=conn, assert_current=lambda *args: None)
    runtime = SimpleNamespace(refresh_lease=lambda frozen, **kw: lease, _control=lambda *a, **kw: {'attempt_count': 1},
        next_stage=lambda actual: 'validating' if state.checkpoint else 'generating')

    def store(**kw: Any) -> Any:
        assert kw['private_slot_ref'] == ref and kw['request'] == request and kw['result'] == result
        state.writes.append('artifact')
        state.artifact = dict(id=uuid4(), candidate_id=uuid4(), version_id=uuid4(), mode='live',
            artifact_key='generation.'+PREPARATION_ID.hex, storage_key='private.native.'+RECOVERY_BUSINESS.hex, storage_version=1,
            source_json=source.model_dump(mode='json'), receipt_json=result.receipt.model_dump(mode='json'), request_json=request.model_dump(mode='json'),
            source_hash=source.source_hash, content_hash=source.content_hash,
            artifact_hash=canonical_hash(dict(source=source.model_dump(mode='json'), receipt=result.receipt.model_dump(mode='json'))),
            public_json=source.public.model_dump(mode='json'), private_json=source.private.model_dump(mode='json'))
        return state.artifact

    def checkpoint(actual: Any, value: Any, **kw: Any) -> None:
        state.writes.append('checkpoint')
        state.checkpoint = dict(stage=value.stage, attempt=value.attempt, status=value.status,
            lease_generation=1, receipt_hash=value.receipt_hash, safe_reason=value.safe_reason)

    def event(actual: Any, kind: str, body: Any, *, key: str) -> Any:
        if body['stage'] == 'review':
            state.review_started = body['status'] == 'started'
            state.writes.append('review.'+body['status'])
            return uuid4()
        assert key == state.started['operation_key'][:-len('.started')]+'.result'
        if state.fail_result:
            raise PrivateNativePending('offline_result_insert_failed')
        state.writes.append('author.result')
        state.done = dict(id=uuid4(), payload_json=body)
        return state.done['id']

    runtime.checkpoint = checkpoint
    core._private_event = event
    facts.pipeline = SimpleNamespace(conn=conn, generation_enabled=True, runtime=runtime, artifacts=SimpleNamespace(store_generation=store),
        _provider_binding=lambda *args: ('deepseek', 'deepseek-flash'))
    def batch(*a: Any, **kw: Any) -> Any:
        return {'valid_until': now+timedelta(hours=2)}
    monkeypatch.setattr(persistence_module, 'accounting_batch_for_lease', batch)
    monkeypatch.setattr(accounting_module, 'accounting_batch_for_lease', batch)
    monkeypatch.setattr(private_finite_factory, 'build_private_generation_request', lambda *a, **kw:
        build_finite_generation_request(kw['spec'], candidate_id=kw['candidate_id'], profile=kw['lease'].profile,
            limits=kw['limits'], materials=kw['materials']))
    service._generation_persistence = None
    for name in ('_prepared', '_results', '_observed_generation_outputs', '_recoveries', '_recovery_bindings'):
        setattr(service, name, {})
    service._started = set()
    owner = service.generation_persistence_owner()
    progress = PrivateNativeCommittedProgressOwner(facts)
    return SimpleNamespace(service=service, facts=facts, conn=conn, state=state, owner=owner, progress=progress,
        task=task, ref=ref, lease=lease, request=request, result=result, spec=spec, selector=selector, top=top, slot=slot)


def persist(f: Any) -> Any:
    with f.top():
        cap = f.owner.issue(task_ref=f.task, output_id=OUTPUT_ID)
        artifact_id = f.owner.persist(cap)
        with pytest.raises(PrivateNativePending, match='distinct_artifact_top_required'), f.conn.transaction():
            f.owner.committed_artifact(cap)
    return cap, artifact_id


def test_fixed_db_output_persists_and_observes_without_sender_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    f = fixture(monkeypatch)
    cap, artifact_id = persist(f)
    assert f.state.writes == ['artifact', 'checkpoint', 'author.result']
    with f.top():
        current, artifact = f.owner.committed_artifact(cap)
        assert artifact['id'] == artifact_id and current.lease.job_id == JOB_ID
        assert f.owner.persist(cap) == artifact_id  # Exact readback, no second writer.
    assert f.state.writes == ['artifact', 'checkpoint', 'author.result']
    assert all(not getattr(f.service, name) for name in
        ('_prepared', '_started', '_results', '_observed_generation_outputs', '_recoveries', '_recovery_bindings'))


@pytest.mark.parametrize('denial', ['wrong_id', 'wrong_candidate', 'same_top', 'source', 'expired', 'postwait_expired'])
def test_issue_fails_closed_before_writer(monkeypatch: pytest.MonkeyPatch, denial: str) -> None:
    f = fixture(monkeypatch)
    with f.top(), pytest.raises(PrivateNativePending):
        identity = OUTPUT_ID
        if denial == 'wrong_id':
            identity = uuid4()
        elif denial == 'wrong_candidate':
            f.state.output['payload_json']['capture']['context']['request']['candidate_id'] = 'eeebd057-3e04-4a61-8979-201446e20221'
            f.state.output['payload_hash'] = canonical_hash(f.state.output['payload_json'])
        elif denial == 'same_top':
            f.state.output['payload_json']['captured_top_xid'] = str(f.conn.top)
            f.state.output['payload_hash'] = canonical_hash(f.state.output['payload_json'])
        elif denial == 'source':
            f.state.source_current = False
        elif denial == 'postwait_expired':
            f.state.expire_on_artifact_read = True
        else:
            f.state.now = f.lease.expires_at
        f.owner.issue(task_ref=f.task, output_id=identity)
    assert not f.state.writes


@pytest.mark.parametrize('mutation', ['copy', 'nested', 'owner'])
def test_distinct_cap_identity_and_full_data_seal(monkeypatch: pytest.MonkeyPatch, mutation: str) -> None:
    f = fixture(monkeypatch)
    with f.top():
        cap = f.owner.issue(task_ref=f.task, output_id=OUTPUT_ID)
        if mutation == 'copy':
            cap = replace(cap)
        elif mutation == 'nested':
            cap.result.source.public.__dict__['instruction_markdown'] += ' changed'
        else:
            cap = replace(cap, owner=object())
        with pytest.raises(PrivateNativePending, match='original_cap_required'):
            f.owner.persist(cap)
    assert not f.state.writes


def test_atomic_group_rollback_preserves_original_output(monkeypatch: pytest.MonkeyPatch) -> None:
    f = fixture(monkeypatch)
    original = f.state.output
    f.state.fail_result = True
    with f.top():
        cap = f.owner.issue(task_ref=f.task, output_id=OUTPUT_ID)
        with pytest.raises(PrivateNativePending, match='result_insert_failed'):
            f.owner.persist(cap)
        assert f.state.artifact is f.state.checkpoint is f.state.done is None
    assert f.state.output is original


def test_outer_rollback_observation_cannot_authorize_quality(monkeypatch: pytest.MonkeyPatch) -> None:
    f = fixture(monkeypatch)
    with pytest.raises(ValueError, match='probe'), f.top():
        cap = f.owner.issue(task_ref=f.task, output_id=OUTPUT_ID)
        f.owner.persist(cap)
        raise ValueError('probe rollback')
    with f.top(), pytest.raises(PrivateNativePending, match='committed_generation_required'):
        f.progress.issue_initial_quality(cap)


def test_partial_artifact_bundle_is_not_a_repair_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    f = fixture(monkeypatch)
    persist(f)
    f.state.done = None
    with f.top(), pytest.raises(PrivateNativePending, match='partial_generation_denied'):
        f.owner.issue(task_ref=f.task, output_id=OUTPUT_ID)


def executor_fixture(f: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    from app.services.learning.item_supply import private_native_pack_executor as module

    executor: Any = object.__new__(PrivateNativePackExecutor)
    executor.service, executor.conn, executor.facts = f.service, f.conn, f.facts
    executor.settings, executor.runtime, executor.progress = f.service.settings, f.facts.pipeline.runtime, f.progress
    executor.provider = SimpleNamespace(provider_key='deepseek', configured_model='deepseek-flash')
    executor._initial_success, executor._initial_authors, executor._initial_reviews = {}, {}, {}
    executor._durable_initial_quality, executor._review = {}, {}
    f.facts._started = set()
    calls: list[str] = []
    monkeypatch.setattr(module, 'BoundedOpenAIReviewClient', lambda *a, **kw: object())
    monkeypatch.setattr(module, 'JsonBlindSolverV2', lambda *a, **kw: object())
    monkeypatch.setattr(module, 'JsonReviewerV2', lambda *a, **kw: object())
    monkeypatch.setattr(f.service, '_select_initial_recovery_source', lambda cap: pytest.fail('no sender cap restored'))

    def validate(**kw: Any) -> Any:
        assert kw['ref'] == f.ref and kw['lease'].job_id == JOB_ID and kw['artifact_id'] == f.state.artifact['id']
        calls.append('original-validate')
        return uuid4(), object()

    def prepare(**kw: Any) -> Any:
        calls.append('original-quality-prepare')
        assert kw['resources'].requests == 7
        return PreparedPrivateReview(kw['ref'], SimpleNamespace(artifact_id=kw['artifact_id'], lease=kw['lease']),
            kw['spec'], f.request, kw['policy'], uuid4())

    def run(p: Any) -> Any:
        assert f.conn.info.transaction_status == TransactionStatus.IDLE
        assert f.service.base_service.type_owner.current_source_binding is f.selector
        assert p.preparation_id not in f.facts._started
        f.facts._started.add(p.preparation_id)
        calls.append('original-quality-run-port')
        f.service.base_service.type_owner.current_source_binding = None
        return object()

    def settle(p: Any) -> None:
        assert f.conn.info.transaction_status == TransactionStatus.INTRANS
        calls.append('original-quality-settle')

    def write(p: Any, result: Any) -> Any:
        assert f.conn.info.transaction_status == TransactionStatus.INTRANS
        assert f.service.base_service.type_owner.current_source_binding is f.selector
        calls.append('original-quality-write')
        return uuid4(), uuid4()

    def finish(*args: Any, **kw: Any) -> Any:
        assert kw['recovery'] is True
        calls.append('original-admission-or-investigation')
        return PrivatePhaseOutcome(RECOVERY_TASK, 'revision_pending', reason='offline-original-finish-port')

    monkeypatch.setattr(f.facts, 'validate', validate)
    monkeypatch.setattr(f.facts, 'prepare_review', prepare)
    monkeypatch.setattr(f.facts, 'run_review', run)
    monkeypatch.setattr(f.facts, 'settle_review', settle)
    monkeypatch.setattr(f.facts, 'persist_review', write)
    monkeypatch.setattr(executor, '_finish_review', finish)
    return executor, calls


@pytest.mark.parametrize('entry', ['explicit', 'run_review', 'write_failed', 'commit_failed', 'replaced'])
def test_quality_handoff_uses_original_new_quality_not_sender(
        monkeypatch: pytest.MonkeyPatch, entry: str) -> None:
    f = fixture(monkeypatch)
    cap, artifact_id = persist(f)
    executor, calls = executor_fixture(f, monkeypatch)
    with f.top():
        handoff = executor.adopt_persisted_initial(cap)
        assert handoff.artifact_id == artifact_id
        if entry != 'run_review':
            prepared = executor.prepare_durable_initial_review(handoff)
    other_slot = uuid4()
    other_handoff = replace(handoff)
    executor._durable_initial_quality[other_slot] = other_handoff
    original_transaction = f.conn.transaction
    original_write = f.facts.persist_review

    def write(p: Any, result: Any) -> Any:
        assert executor._durable_initial_quality[RECOVERY_SLOT] is handoff
        value = original_write(p, result)
        if entry == 'write_failed':
            raise LookupError('offline review write failed')
        if entry == 'replaced':
            executor._durable_initial_quality[RECOVERY_SLOT] = other_handoff
        return value

    @contextmanager
    def transaction() -> Iterator[None]:
        with original_transaction():
            yield
            if 'original-quality-write' in calls:
                expected = other_handoff if entry == 'replaced' else handoff
                assert executor._durable_initial_quality[RECOVERY_SLOT] is expected
                if entry == 'commit_failed':
                    raise LookupError('offline review commit failed')

    monkeypatch.setattr(f.facts, 'persist_review', write)
    monkeypatch.setattr(f.conn, 'transaction', transaction)
    if entry in ('write_failed', 'commit_failed'):
        with pytest.raises(LookupError, match='offline review .* failed'):
            executor.run_initial_recovery_review(prepared)
        assert executor._durable_initial_quality[RECOVERY_SLOT] is handoff
        assert executor._initial_reviews[RECOVERY_SLOT][0] is prepared
        assert executor._review[RECOVERY_SLOT][1] == artifact_id
        assert 'original-admission-or-investigation' not in calls
    elif entry == 'run_review':
        outcome = executor._run_review(RECOVERY_SLOT)
    else:
        outcome = executor.run_initial_recovery_review(prepared)
        with pytest.raises(PrivateNativePending, match='live_work_required'):
            executor.run_initial_recovery_review(prepared)
    assert executor._durable_initial_quality[other_slot] is other_handoff
    assert f.conn.info.transaction_status == TransactionStatus.IDLE
    if entry not in ('write_failed', 'commit_failed'):
        assert outcome.reason == 'offline-original-finish-port'
        assert calls == ['original-validate', 'original-quality-prepare', 'original-quality-run-port',
            'original-quality-settle', 'original-quality-write', 'original-admission-or-investigation']
        if entry == 'replaced':
            assert executor._durable_initial_quality[RECOVERY_SLOT] is other_handoff
        else:
            assert RECOVERY_SLOT not in executor._durable_initial_quality
            child_lease = f.lease.model_copy(update={'job_id': uuid4()})
            executor._review[RECOVERY_SLOT] = (SimpleNamespace(task=f.task, slot=f.slot, spec=f.spec,
                materials=f.request.materials, ref=f.ref, lease=child_lease), uuid4())

            def child_query(sql: str, params: Any = ()) -> Any:
                assert "payload_json->>'job_id'=%s" in sql and params[-1] == str(child_lease.job_id)
                return SimpleNamespace(fetchone=lambda: None)

            def child_phase(*args: Any) -> Any:
                raise LookupError('original child quality phase reached')

            monkeypatch.setattr(f.conn, 'transaction', original_transaction)
            monkeypatch.setattr(f.conn, 'execute', child_query)
            monkeypatch.setattr(executor, '_phase', child_phase)
            with pytest.raises(LookupError, match='original child quality phase reached'):
                executor._run_review(RECOVERY_SLOT)
    assert not executor._initial_authors and not executor._initial_success
    assert not f.service._prepared and not f.service._results and not f.service._started


def test_quality_opaque_started_and_short_window_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    f = fixture(monkeypatch)
    cap, _ = persist(f)
    executor, calls = executor_fixture(f, monkeypatch)
    with f.top():
        f.state.review_started = True
        with pytest.raises(PrivateNativePending, match='existing_stage_no_replay'):
            executor.adopt_persisted_initial(cap)
        f.state.review_started = False
        handoff = executor.adopt_persisted_initial(cap)
        with pytest.raises(PrivateNativePending, match='original_handoff_required'):
            f.progress.require_initial_quality(replace(handoff))
        f.state.now = f.lease.expires_at-timedelta(seconds=700)
        with pytest.raises(PrivateNativePending, match='quality_current_work_required'):
            executor.prepare_durable_initial_review(handoff)
    assert not calls


def test_executor_initial_result_and_terminal_need_explicit_handoff(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.learning.item_supply import native_type_exposure

    f = fixture(monkeypatch)
    cap, _ = persist(f)
    executor, _ = executor_fixture(f, monkeypatch)
    monkeypatch.setattr(f.service, '_continuation_receivers', lambda: None)
    assert executor.run_next_phase(f.task).status == 'preparing'
    assert executor._recover_committed_progress(f.task, f.slot, uuid4()).status == 'preparing'
    public = f.service.base_service.type_owner
    checks: list[str] = []

    def current(name: str, value: Any) -> Any:
        assert f.conn.info.transaction_status == TransactionStatus.INTRANS
        assert public.current_source_binding is f.selector, name+' requires fresh SOURCE'
        checks.append(name)
        return value

    def mapping(identity: Any) -> Any:
        assert identity == f.task.mapping_receipt_id
        return current('mapping', SimpleNamespace(target_id='python-kc-binding-v1'))

    record = f.service.core._task(f.task)

    def task_record(task: Any) -> Any:
        assert task == f.task
        mapping(task.mapping_receipt_id)
        return current('task', record)

    monkeypatch.setattr(f.service.core, '_task', task_record)
    f.service.type_owner = SimpleNamespace(resolve_mapping=mapping)
    with f.top():
        executor.adopt_persisted_initial(cap)
    assert public.current_source_binding is None
    checks.clear()
    pack = SimpleNamespace(selected=(SimpleNamespace(version_id=uuid4()),))
    monkeypatch.setattr(f.service, 'base_fallback_owner', lambda:
        SimpleNamespace(resolve=lambda task: current('fallback', None)))
    f.service.base_service._attempt = lambda *a, **kw: current('base', SimpleNamespace(ready=SimpleNamespace(capability=object())))
    public.require_pack = lambda cap: current('pack', pack)
    public.source_deadline = lambda content: current('deadline', f.state.now+timedelta(days=1))
    f.service.exposure_owner = SimpleNamespace(snapshot_complete=lambda: current('union', SimpleNamespace(exposure=object())))
    monkeypatch.setattr(native_type_exposure, '_protected', lambda *args: current('protected', None))
    monkeypatch.setattr(f.service.core, '_versions', lambda task:
        current('versions', {str(i): SimpleNamespace(published_version_id=uuid4()) for i in range(5)}))
    executor.relation_repair = SimpleNamespace(pending=lambda task: current('repair', None))
    original_execute = f.conn.execute

    def execute(sql: str, params: Any = ()) -> Any:
        if sql.startswith('SELECT started.id'):
            return current('unresolved', SimpleNamespace(fetchone=lambda: None))
        if sql.startswith('SELECT DISTINCT slot_id'):
            return current('publications', SimpleNamespace(fetchall=lambda: []))
        return original_execute(sql, params)

    def review(slot: Any) -> Any:
        assert slot == RECOVERY_SLOT
        assert f.conn.info.transaction_status == TransactionStatus.IDLE
        assert public.current_source_binding is None
        return PrivatePhaseOutcome(RECOVERY_TASK, 'review_pending')

    monkeypatch.setattr(f.conn, 'execute', execute)
    monkeypatch.setattr(executor, '_run_review', review)
    assert executor.run_next_phase(f.task).status == 'review_pending'
    assert {'mapping', 'task', 'fallback', 'base', 'pack', 'union', 'protected',
        'unresolved', 'versions', 'repair', 'publications', 'deadline'} <= set(checks)
    assert public.current_source_binding is None
    resumed = executor._recover_committed_progress(f.task, f.slot, uuid4())
    assert resumed.reason == 'original_private_durable_quality_handoff'
    assert not executor._initial_success and not executor._initial_authors
