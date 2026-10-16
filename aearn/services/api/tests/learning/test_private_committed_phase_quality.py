"""C19 fixed committed-B DATA and pure receiver ports, never live acceptance."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from psycopg.pq import TransactionStatus

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.parameter_profiles import freeze_profile
from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending, PrivateNativePublicationV1
from app.services.learning.item_supply.private_enhancement_service import RECOVERY_SLOT
from app.services.learning.item_supply.private_generation_persistence import JOB_ID, OUTPUT_ID, PREPARATION_ID
from app.services.learning.item_supply.private_generation_persistence_phase import PHASE_KEY
from app.services.learning.item_supply.private_native_admission_facts import PreparedPrivateReview
from app.services.learning.item_supply import private_native_committed_progress as progress
from tests.learning.test_private_generation_persistence_phase import fixture as phase_ports


def fixture(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Seed already-committed records directly; do not invoke A/B or old caps."""
    from app.services.learning.item_supply.private_generation_persistence import PrivateGenerationPersistenceOwner
    from app.services.learning.item_supply.private_generation_persistence_phase import PrivateGenerationPersistencePhaseOwner, IssuedPrivateGenerationPersistencePhase

    f = phase_ports(monkeypatch)
    s, conn = f.state, f.conn
    s.now = datetime.fromisoformat('2026-10-16T13:00:00+08:00')
    with f.top():
        profile = f.executor._profile(f.spec,f.request.materials,phase_kind='persistence_quality')
    bound_at = datetime.fromisoformat('2026-10-16T12:38:11.896977+08:00')
    parent = datetime.fromisoformat('2026-10-16T14:18:11.896977+08:00')
    s.new_job = progress.COMMITTED_WRITER_ID
    s.writer = JobLeaseV1(job_id=s.new_job,visibility='private',owner_id=f.task.user_id,owner_epoch=1,
        lease_owner='private.persistence.'+OUTPUT_ID.hex,generation=1,state_version=3,
        expires_at=datetime.fromisoformat('2026-10-16T13:38:12.081065+08:00'),parent_deadline=parent,
        profile=freeze_profile(profile,bound_at=bound_at,ancestor_deadline=parent),retry_policy=f.lease.retry_policy)
    frozen = s.writer.model_copy(update={'state_version':2})
    s.phase = True
    s.batch = dict(id=uuid4(),root_id=f.ref.root_id,window_id=uuid4(),global_limit_ids=[uuid4()],user_limit_ids=[uuid4()],
        provider_key='deepseek',model='deepseek-flash',valid_until=bound_at+timedelta(hours=2))
    source,receipt = f.result.source,f.result.receipt
    assert source is not None and receipt is not None
    digest = canonical_hash(dict(source=source.model_dump(mode='json'),receipt=receipt.model_dump(mode='json')))
    s.artifact = dict(id=progress.COMMITTED_ARTIFACT_ID,job_id=s.new_job,lease_generation=1,lease_state_version=2,
        candidate_id=progress.COMMITTED_CANDIDATE_ID,version_id=progress.COMMITTED_VERSION_ID,
        artifact_key='generation.'+PREPARATION_ID.hex,mode='live',source_hash=source.source_hash,content_hash=source.content_hash,
        source_json=source.model_dump(mode='json'),receipt_json=receipt.model_dump(mode='json'),request_json=f.request.model_dump(mode='json'),
        artifact_hash=digest,storage_key='private.native.'+f.ref.business_item_id.hex,storage_version=1,
        public_json=source.public.model_dump(mode='json'),private_json=source.private.model_dump(mode='json'))
    s.checkpoint = dict(id=progress.COMMITTED_CHECKPOINT_ID,stage='generating',attempt=1,status='completed',
        lease_generation=1,receipt_hash=digest,safe_reason='candidate_staged')

    def journal(identity: Any, key: str, body: Any) -> Any:
        return dict(id=identity,pack_task_id=f.task.pack_task_id,user_id=f.task.user_id,epoch=1,scope_id=f.task.scope_id,
            intent_hash=f.task.intent_hash,record_kind='private_status',operation_key=key,payload_json=body,payload_hash=canonical_hash(body))

    output = s.output['payload_json']
    s.bridge = journal(progress.COMMITTED_BINDING_ID,PHASE_KEY,dict(schema_version='private_generation_persistence_phase_v1',
        output_id=str(OUTPUT_ID),preparation_id=str(PREPARATION_ID),output_hash=s.output['payload_hash'],generation_job_id=str(JOB_ID),
        generation_request_hash=canonical_hash(f.request.model_dump(mode='json')),generation_profile_hash=f.request.profile.profile_hash,
        ref=f.ref.model_dump(mode='json'),writer_job_id=str(s.new_job),batch_id=str(s.batch['id']),lease=frozen.model_dump(mode='json'),
        source_origin_id=str(uuid4()),bound_top_xid='269090',bound_at=bound_at.isoformat(),valid_until=s.writer.expires_at.isoformat(),
        **{'original_'+key:output[key] for key in ('binding_id','started_id','consumed_id','settlement_id')}))
    s.complete = journal(progress.COMMITTED_COMPLETION_ID,PHASE_KEY+'.complete',dict(schema_version='private_generation_persistence_complete_v1',
        binding_id=str(s.bridge['id']),output_id=str(OUTPUT_ID),writer_job_id=str(s.new_job),artifact_id=str(s.artifact['id']),
        artifact_hash=digest,candidate_id=str(s.artifact['candidate_id']),version_id=str(s.artifact['version_id']),
        checkpoint_id=str(s.checkpoint['id']),source_origin_id=str(uuid4()),completed_top_xid=progress.COMMITTED_OUTPUT_TOP,
        completed_at='2026-10-16T12:42:00+08:00'))
    # Synthetic full DATA has its own digest; production pins the actual digest.
    monkeypatch.setattr(progress,'COMMITTED_COMPLETION_HASH',s.complete['payload_hash'])
    conn.top = int(progress.COMMITTED_OUTPUT_TOP)
    s.reservation = s.typed_receipt = False
    execute = conn.execute

    def read(sql: str, params: Any = ()) -> Any:
        if sql.startswith('SELECT (EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence'):
            assert conn.info.transaction_status == TransactionStatus.INTRANS
            used = s.quality or s.reservation or s.typed_receipt or s.review_started or s.writer.state_version != 3
            return SimpleNamespace(fetchone=lambda: {'started':used})
        return execute(sql,params)

    monkeypatch.setattr(conn,'execute',read)

    def forbidden(*a: Any, **kw: Any) -> Any:
        pytest.fail('quality-only path must not use a persistence owner/cap, A/B, claim or enqueue')

    f.service._generation_persistence = f.service._generation_persistence_phase = None
    f.owner = None
    monkeypatch.setattr(f.service,'generation_persistence_owner',forbidden)
    monkeypatch.setattr(f.service,'generation_persistence_phase_owner',forbidden)
    for owner in (PrivateGenerationPersistenceOwner,PrivateGenerationPersistencePhaseOwner):
        for method in ('issue','require','persist','committed_artifact'):
            monkeypatch.setattr(owner,method,forbidden)
    monkeypatch.setattr(IssuedPrivateGenerationPersistencePhase,'__init__',forbidden)
    f.facts.pipeline.runtime.enqueue = forbidden
    f.facts.pipeline.runtime.claim = forbidden
    monkeypatch.setattr(f.repo,'store_generation',forbidden)
    return f


def adopt(f: Any) -> Any:
    return f.executor.adopt_committed_phase_quality(task_ref=f.task,completion_id=progress.COMMITTED_COMPLETION_ID)


def test_fixed_committed_b_issues_only_flat_quality_and_rechecks_source(monkeypatch: pytest.MonkeyPatch) -> None:
    f = fixture(monkeypatch)
    before = deepcopy((f.state.output,f.state.bridge,f.state.complete,f.state.artifact,f.state.checkpoint))
    with f.top():
        cap = adopt(f)
        assert not hasattr(cap,'persistence') and cap.writer_lease.job_id == progress.COMMITTED_WRITER_ID
        assert cap.request.profile != cap.writer_lease.profile and cap.request == f.request
        assert f.progress.require_committed_phase_quality(cap).state_version == 3
        f.state.source_current = False
        with pytest.raises(PrivateNativePending,match='current_source_required'):
            f.progress.require_committed_phase_quality(cap)
    assert (f.state.output,f.state.bridge,f.state.complete,f.state.artifact,f.state.checkpoint) == before
    assert not f.service._prepared and not f.service._results and not f.service._started
    assert not f.executor._initial_authors and not f.executor._initial_success


@pytest.mark.parametrize('denial',['completion_id','completion_hash','same_top','existing_c','expired','short_window'])
def test_quality_only_factual_denials(monkeypatch: pytest.MonkeyPatch, denial: str) -> None:
    f = fixture(monkeypatch)
    if denial == 'completion_hash':
        f.state.complete['payload_hash'] = '0'*64
    elif denial == 'same_top':
        f.conn.top = int(progress.COMMITTED_OUTPUT_TOP)-1
    elif denial == 'existing_c':
        f.state.reservation = True
    elif denial == 'expired':
        f.state.now = f.state.writer.expires_at
    elif denial == 'short_window':
        f.state.now = f.state.writer.expires_at-timedelta(seconds=715)
    with f.top(),pytest.raises(PrivateNativePending):
        f.executor.adopt_committed_phase_quality(task_ref=f.task,
            completion_id=uuid4() if denial=='completion_id' else progress.COMMITTED_COMPLETION_ID)
    assert not f.executor._initial_reviews and not f.facts._started


@pytest.mark.parametrize('change',['copy','nested'])
def test_flat_cap_identity_and_full_data_seal(monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    f = fixture(monkeypatch)
    with f.top():
        cap = adopt(f)
    if change == 'copy':
        cap = replace(cap)
    else:
        object.__setattr__(cap.request.profile,'profile_hash','0'*64)
    with f.top(),pytest.raises(PrivateNativePending,match='original_cap_required'):
        f.progress.require_committed_phase_quality(cap)


def test_quality_only_probe_replacement_idle_once_and_retirement(monkeypatch: pytest.MonkeyPatch) -> None:
    f = fixture(monkeypatch)
    sent: list[Any] = []

    def validate(**kw: Any) -> Any:
        assert kw['lease'].job_id == progress.COMMITTED_WRITER_ID
        f.state.quality = True
        f.state.writer = f.state.writer.model_copy(update={'state_version':4})
        return uuid4(),object()

    def prepare(**kw: Any) -> Any:
        assert kw['resources'].requests == 7 and kw['lease'].profile != f.request.profile
        p = PreparedPrivateReview(kw['ref'],SimpleNamespace(artifact_id=kw['artifact_id'],lease=kw['lease']),
            kw['spec'],f.request,kw['policy'],uuid4())
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
        sent.append(p)
        return object()

    monkeypatch.setattr(f.facts,'validate',validate)
    monkeypatch.setattr(f.facts,'prepare_review',prepare)
    monkeypatch.setattr(f.facts,'run_review',run)
    with pytest.raises(LookupError,match='probe C'),f.top():
        old = adopt(f)
        old_prepared = f.executor.prepare_committed_phase_review(old)
        raise LookupError('probe C')
    with pytest.raises(PrivateNativePending,match='aux_not_committed'):
        f.executor.run_initial_recovery_review(old_prepared)
    assert not sent
    with f.top():
        cap = adopt(f)
        with pytest.raises(PrivateNativePending,match='executor_handoff_required'):
            f.executor.prepare_committed_phase_review(old)
        prepared = f.executor.prepare_committed_phase_review(cap)
        # Own validation is not an everlasting 'no quality' precondition.
        assert f.progress.require_committed_phase_quality(cap).state_version == 4
    with pytest.raises(PrivateNativePending,match='live_work_required'):
        f.executor.run_initial_recovery_review(old_prepared)
    assert f.executor.run_initial_recovery_review(prepared).status == 'revision_pending'
    assert sent == [prepared] and RECOVERY_SLOT not in f.executor._durable_initial_quality
    assert not f.executor._initial_authors and not f.executor._initial_success


@pytest.mark.parametrize(('fixed_writer','remaining'),[(True,714),(True,715),(True,716),(False,700)])
def test_original_run_review_checks_fixed_writer_window_at_last_preio(
        monkeypatch: pytest.MonkeyPatch, fixed_writer: bool, remaining: int) -> None:
    from app.services.learning.item_supply import private_native_admission_facts as module
    from app.services.learning.item_supply import private_development_model_accounting as accounting
    from app.services.learning.item_supply.blind_protocol import SINGLE_CHOICE_BLIND_PROTOCOL
    from app.services.learning.item_supply.diagnostic_policy import AutonomousEvidencePolicyV3
    from app.services.learning.item_supply.finite_candidate_validation import prepare_finite_candidate_validation
    from app.services.learning.item_supply.pipeline import PreparedReview
    from app.services.learning.item_supply.review_contracts_v2 import CandidateBindingV2

    f = fixture(monkeypatch)
    if not fixed_writer:
        f.state.new_job = uuid4()
        f.state.writer = f.state.writer.model_copy(update={'job_id':f.state.new_job})
        f.state.artifact['job_id'] = f.state.new_job
    f.state.writer = f.state.writer.model_copy(update={'state_version':4})
    lease,source = f.state.writer,f.result.source
    f.state.now = lease.expires_at-timedelta(seconds=750)
    policy = AutonomousEvidencePolicyV3()
    validation = prepare_finite_candidate_validation(source,spec=f.spec,materials=f.request.materials).static_facts.validation
    binding = CandidateBindingV2(candidate_key=str(f.state.artifact['candidate_id']),version_key=str(f.state.artifact['version_id']),
        source_hash=source.source_hash,content_hash=source.content_hash,policy_hash=policy.policy_hash,
        profile_hash=lease.profile.profile_hash,runtime_key=source.blueprint.runtime_profile_id or 'static-exact-v1',
        risk_tier=source.blueprint.publication_policy.risk_tier)
    original = PreparedReview(lease,f.ref.scope_id,f.state.artifact['id'],source,validation,binding,
        'deepseek.item_author',uuid4(),'live',(1,)*7)
    prepared = PreparedPrivateReview(f.ref,original,f.spec,f.request,policy,uuid4())
    solver = SimpleNamespace(blind_protocol=SINGLE_CHOICE_BLIND_PROTOCOL)
    f.facts._committed_reviews = {}
    f.facts._prepared = {prepared.preparation_id:(prepared,f.facts._seal(prepared),object(),solver,())}
    f.facts._results = {}
    assert module.PrivateNativeAdmissionFactsOwner._require(f.facts,prepared) is not None
    assert (lease.expires_at-f.state.now).total_seconds() > 715
    events: list[str] = []
    senders: list[str] = []
    f.facts.pipeline._fence_source = lambda *a: events.append('artifact-source')
    monkeypatch.setattr(f.facts,'current_source_front',lambda ref: f.service._fresh_recovery_source(f.task))
    execute = f.conn.execute

    def read(sql: str, params: Any = ()) -> Any:
        if 'private_pack_auxiliary_committed(' in sql:
            assert params == (f.task.pack_task_id,prepared.preparation_id)
            events.append('committed-aux')
            return SimpleNamespace(fetchone=lambda: {'ok':True})
        return execute(sql,params)

    def source_current(*args: Any) -> None:
        assert f.conn.info.transaction_status == TransactionStatus.INTRANS
        events.append('source-current')
        f.state.now = lease.expires_at-timedelta(seconds=remaining+1 if fixed_writer else remaining)

    original_batch = accounting.accounting_batch_for_lease

    def batch(*args: Any, **kw: Any) -> Any:
        assert fixed_writer and f.conn.info.transaction_status == TransactionStatus.INTRANS
        events.append('accounting')
        projection = original_batch(*args,**kw)
        assert projection is not None and 'batch_id' in projection and 'id' not in projection
        f.state.now = lease.expires_at-timedelta(seconds=remaining)
        return projection

    def clock(connection: Any, now: Any) -> Any:
        assert connection is f.conn
        events.append('clock')
        return f.state.now

    class SenderReached(Exception):
        pass

    def blind(*args: Any, **kw: Any) -> Any:
        assert f.conn.info.transaction_status == TransactionStatus.IDLE
        assert prepared.preparation_id in f.facts._started
        senders.append('blind')
        raise SenderReached  # No provider is invoked by the offline seam.

    monkeypatch.setattr(f.conn,'execute',read)
    monkeypatch.setattr(f.facts.source_authority,'assert_current',source_current)
    monkeypatch.setattr(accounting,'accounting_batch_for_lease',batch)
    monkeypatch.setattr(module,'server_clock',clock)
    monkeypatch.setattr(module,'blind_solve_candidate',blind)
    if fixed_writer and remaining <= 715:
        with pytest.raises(PrivateNativePending,match='remaining_window_required'):
            module.PrivateNativeAdmissionFactsOwner.run_review(f.facts,prepared)
        assert not senders and prepared.preparation_id not in f.facts._started
        assert not f.facts._results
    else:
        with pytest.raises(SenderReached):
            module.PrivateNativeAdmissionFactsOwner.run_review(f.facts,prepared)
        assert senders == ['blind']
    assert f.conn.info.transaction_status == TransactionStatus.IDLE
    if fixed_writer:
        assert events.index('source-current') < events.index('accounting') < len(events)-1
        assert events[-1] == 'clock'
    else:
        assert 'accounting' not in events


@pytest.mark.parametrize('kind',['opaque_handle','wrong_version','wrong_content'])
def test_publisher_uses_version_domain_not_storage_handle(monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    from app.services.learning.item_bank import private_native_publication as publication

    f = fixture(monkeypatch)
    q: Any = SimpleNamespace(ref=f.ref,version_id=progress.COMMITTED_VERSION_ID,source=f.result.source,
        request=f.request,source_receipts=f.result.receipt.sources,spec=f.spec,receipt_id=uuid4(),receipt_hash='a'*64,
        checked_at=f.state.now,valid_until=f.state.writer.expires_at,bundle=SimpleNamespace(author_identity='deepseek.item_author'))
    raw_handle = 'lip:v2:'+str(uuid4())
    row = dict(id=q.version_id,handle=raw_handle,public_json=q.source.public.model_dump(mode='json'),private_json=q.source.private.model_dump(mode='json'))
    if kind == 'wrong_version':
        row['id'] = uuid4()
    elif kind == 'wrong_content':
        row['private_json'] = {}
    written: list[Any] = []

    def execute(sql: str, params: Any = ()) -> Any:
        if sql.startswith('SELECT * FROM tutor_item_supply_private_versions'):
            assert params == (q.version_id,q.ref.user_id,q.ref.epoch,q.ref.scope_id)
            return SimpleNamespace(fetchone=lambda: row)
        assert sql.startswith('INSERT INTO '+publication.PUBLICATIONS)
        written.append(params[9].obj)
        assert params[11].obj['item_handle'] == 'lip:v2:'+str(q.version_id)
        return SimpleNamespace(fetchone=lambda: None)

    monkeypatch.setattr(f.conn,'execute',execute)
    monkeypatch.setattr(f.facts,'verify',lambda value: value)
    monkeypatch.setattr(publication,'server_clock',lambda *args: f.state.now)
    monkeypatch.setattr(publication,'PostgresExerciseGateRepository',lambda conn:
        SimpleNamespace(ensure_exercise_authority=lambda *args, **kw: str(uuid4())))
    owner = publication.PrivateNativePublicationOwner(f.conn,f.service.settings,facts_owner=f.facts,enabled=True)
    with f.top():
        if kind != 'opaque_handle':
            with pytest.raises(PrivateNativePending,match='actual_version_required'):
                owner.publish_internal(q)
            assert not written
        else:
            receipt = owner.publish_internal(q)
            assert receipt.item_handle == 'lip:v2:'+str(q.version_id) and row['handle'] == raw_handle
            assert written[0]['item_handle'] == receipt.item_handle
            with pytest.raises(ValueError):
                PrivateNativePublicationV1.model_validate_json(receipt.model_dump_json().replace(receipt.item_handle,raw_handle))
