"""Pure C16 seams: fake SQL/producer ports, no PG or live authority claims."""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, Iterator
from uuid import uuid4

import pytest
from psycopg.pq import TransactionStatus

from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash
from app.services.learning.item_supply.generation_contracts import GenerationReceiptV2, GenerationResultV2, ProviderReceiptV2, ProviderUsageV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.persistent_pack_contracts import PersistentPackTaskRef
from app.services.learning.item_supply.pipeline import ItemSupplyPipeline, PreparedGeneration
from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending, PrivateSlotRef
from app.services.learning.item_supply.private_enhancement_service import (
    RECOVERY_BUSINESS, RECOVERY_MAPPING, RECOVERY_ROOT, RECOVERY_SCOPE, RECOVERY_SLOT,
    RECOVERY_TASK, RECOVERY_USER, PreparedPrivateSlotGeneration, PrivateEnhancementService,
)
from app.services.learning.item_supply.private_generation_durability import C14_GAP_BINDING, LOST_C14_CANDIDATE, generation_context
from app.services.learning.item_supply.private_native_pack_executor import PrivateNativePackExecutor
from tests.learning.test_item_supply_generation import SyntheticAuthority, make_request


class OfflineConnection:
    """TOP/savepoint behavior only; actual SQL guards belong to Main's PG tests."""
    def __init__(self) -> None:
        self.autocommit = False
        self.info = SimpleNamespace(transaction_status=TransactionStatus.IDLE)
        self.top = 0
        self.subxid = 0
        self.ready = True
        self.fail_capture = False
        self.fail_commit = False
        self.fees: Any = None
        self.output: Any = None
        self.events: list[Any] = []
        self.calls: list[tuple[str, Any]] = []

    @contextmanager
    def transaction(self) -> Iterator[None]:
        outer = self.info.transaction_status == TransactionStatus.IDLE
        if outer:
            self.top += 1
        self.subxid += 1
        before = self.fees, self.output
        self.info.transaction_status = TransactionStatus.INTRANS
        try:
            yield
            if outer and self.fail_commit:
                raise ValueError('offline outer commit failure')
        except Exception:
            self.fees, self.output = before
            self.events.append(('rollback' if outer else 'savepoint-rollback', self.top))
            raise
        else:
            self.events.append(('commit' if outer else 'release', self.top))
        finally:
            self.info.transaction_status = TransactionStatus.IDLE if outer else TransactionStatus.INTRANS

    def execute(self, sql: str, params: Any = ()) -> Any:
        assert self.info.transaction_status == TransactionStatus.INTRANS
        self.calls.append((sql, params))
        if 'private_generation_durability_ready()' in sql:
            row: Any = {'ready': self.ready}
        elif 'private_generation_output_capture(' in sql:
            assert self.fees is not None
            if self.fail_capture:
                raise ValueError('offline capture failure; not public exception data')
            if self.output is None:
                self.output = dict(id=uuid4(), payload=params[1].obj, candidate=params[0], top=self.top, xmin=self.subxid)
            assert self.output['payload'] == params[1].obj
            row = {'id': self.output['id']}
        elif 'private_generation_output_committed(' in sql:
            if self.output is None or self.output['top'] == self.top:
                raise PrivateNativePending('offline_output_not_committed')
            assert self.output['payload'] == params[1].obj and self.output['candidate'] == params[0]
            row = {'id': self.output['id']}
        elif 'private_pack_auxiliary_committed(' in sql:
            row = {'ok': True}
        elif 'runtime_settlements' in sql:
            row = {'id': uuid4()} if self.fees else None
        elif 'private_initial_author_persistence_gap_issue(' in sql:
            assert params == (RECOVERY_TASK, RECOVERY_USER, 1, RECOVERY_SCOPE, C14_GAP_BINDING)
            row = {'id': uuid4()}
        else:
            pytest.fail('unexpected offline SQL: '+sql)
        return SimpleNamespace(fetchone=lambda: row)


def fixture(monkeypatch: pytest.MonkeyPatch, *, known: bool = True, run: bool = True) -> Any:
    request, payload = make_request()
    source = LearningItemSourceV1.model_validate(payload)
    sources = (SyntheticAuthority().authorize(request.materials[0]),)
    usage = ProviderUsageV2(state='known', input_tokens=17, output_tokens=11, total_tokens=28) if known else ProviderUsageV2(state='unknown')
    provider_receipt = ProviderReceiptV2(provider='fixture', provider_version='fixture.v2', configured_model='fixture',
        model='fixture', prompt_version='fixture.v1', run_id=uuid4(), request_attempt_bound=1,
        actual_requests=1 if known else None, usage=usage, mode='provider')
    result = GenerationResultV2(state='staged', safe_reason='staged', source=source,
        receipt=GenerationReceiptV2(candidate_id=request.candidate_id, scope_hash=request.scope_hash,
            source_hash=source.source_hash, content_hash=source.content_hash, provider=provider_receipt, sources=sources))
    ref = PrivateSlotRef(pack_task_id=RECOVERY_TASK, slot_id=RECOVERY_SLOT, business_item_id=RECOVERY_BUSINESS,
        root_id=RECOVERY_ROOT, mapping_receipt_id=RECOVERY_MAPPING, user_id=RECOVERY_USER, epoch=1,
        scope_id=RECOVERY_SCOPE, goal_scope_id=uuid4(), slot='practice')
    lease = JobLeaseV1(job_id=uuid4(), visibility='private', owner_id=RECOVERY_USER, owner_epoch=1,
        lease_owner='offline.c16', generation=1, state_version=1, profile=request.profile,
        expires_at=request.profile.parent_deadline_at, parent_deadline=request.profile.parent_deadline_at)
    prepared = PreparedPrivateSlotGeneration(ref, PreparedGeneration(lease, ref.scope_id, request, uuid4(), sources, 1, 'live', ('fixture', 'fixture')))
    service: Any = object.__new__(PrivateEnhancementService)
    conn, provider = OfflineConnection(), object()
    now = datetime.now(UTC)
    service.conn = conn
    service._prepared = {request.candidate_id: (prepared, canonical_hash(generation_context(prepared)), provider)}
    service._started, service._results, service._observed_generation_outputs, service._recovery_bindings = set(), {}, {}, {}

    def settle(**kwargs: Any) -> None:
        assert conn.info.transaction_status == TransactionStatus.INTRANS
        conn.fees = kwargs
        conn.events.append(('settled', conn.top))

    pipeline: Any = object.__new__(ItemSupplyPipeline)
    pipeline.budget = SimpleNamespace(settle=settle)

    def produce(original: Any, actual_provider: Any) -> Any:
        assert conn.info.transaction_status == TransactionStatus.IDLE
        assert original is prepared.original and actual_provider is provider
        conn.events.append(('producer-port', conn.top))
        return result

    def persist(original: Any, actual_result: Any, **kwargs: Any) -> Any:
        assert original is prepared.original and actual_result is result
        assert conn.output is not None and conn.output['top'] != conn.top
        conn.events.append(('artifact-port', conn.top))
        return SimpleNamespace(artifact_id=uuid4())

    service.facts_owner = SimpleNamespace(_guard=lambda *args: now,
        source_authority=SimpleNamespace(assert_current=lambda *args: None),
        pipeline=SimpleNamespace(run_generation=produce, settle_generation=pipeline.settle_generation, commit_generation=persist))
    monkeypatch.setattr(service, '_guard', lambda: now)
    monkeypatch.setattr(service, '_generation_source_front', lambda ref: nullcontext(None))
    monkeypatch.setattr(service, '_prepared_recovery', lambda p: None)
    if run:
        assert service.run_generation(prepared) is result
        assert service._observed_generation_outputs[request.candidate_id].result is result
    return SimpleNamespace(service=service, conn=conn, p=prepared, result=result)


@pytest.mark.parametrize('known', [True, False])
def test_capture_same_top_settlement_then_separate_artifact(monkeypatch: pytest.MonkeyPatch, known: bool) -> None:
    f = fixture(monkeypatch, known=known)
    with f.conn.transaction():
        f.service.settle_generation(f.p, f.result)
        outcome = f.service.capture_generation_output(f.p, f.result)
        assert outcome.status == 'captured' and outcome.output_id == f.conn.output['id']
        assert f.conn.output['xmin'] != f.conn.top  # A released subtransaction is not a commit.
        assert f.conn.output['payload']['context']['scope_id'] == str(RECOVERY_SCOPE)
        assert f.conn.output['payload']['context']['producer_binding'] == ['fixture', 'fixture']
        with pytest.raises(PrivateNativePending, match='output_not_committed'), f.conn.transaction():
            f.service.persist_generation(f.p, f.result)
    assert f.conn.fees['usage_state'] == ('known' if known else 'unknown')
    assert (f.conn.fees['actual'] is None) is (not known)
    assert (f.conn.fees['receipt_hash'] is None) is (not known)
    with f.conn.transaction():
        # Exact same output can be read back, not a new paid request or key.
        assert f.service.capture_generation_output(f.p, f.result).output_id == outcome.output_id
        assert f.service.persist_generation(f.p, f.result) is not None
    assert sum(e[0] == 'producer-port' for e in f.conn.events) == 1


@pytest.mark.parametrize('mutation', ['copy', 'nested', 'rehash', 'prepared_copy', 'context_swap', 'reservation', 'mode', 'registry'])
def test_capture_rejects_changed_original_observation(monkeypatch: pytest.MonkeyPatch, mutation: str) -> None:
    f = fixture(monkeypatch)
    with f.conn.transaction():
        f.service.settle_generation(f.p, f.result)
    if mutation == 'copy':
        f.result = f.result.model_copy(deep=True)
    elif mutation in ('nested', 'rehash'):
        f.result.source.public.__dict__['instruction_markdown'] += '\nChanged after original return.'
        if mutation == 'rehash':
            f.result.receipt.__dict__['source_hash'] = f.result.source.source_hash
            f.result.receipt.__dict__['content_hash'] = f.result.source.content_hash
    elif mutation == 'prepared_copy':
        f.p = replace(f.p)
    elif mutation == 'context_swap':
        object.__setattr__(f.p.original, 'lease', f.p.original.lease.model_copy(deep=True))
    elif mutation == 'reservation':
        object.__setattr__(f.p.original, 'reservation_id', uuid4())
    elif mutation == 'mode':
        object.__setattr__(f.p.original, 'mode', 'synthetic')
    else:
        f.service._observed_generation_outputs.clear()
    with f.conn.transaction():
        assert f.service.capture_generation_output(f.p, f.result).status == 'capture_failed'
    assert f.conn.fees is not None and f.conn.output is None
    assert not any('private_generation_output_capture(' in sql for sql, _ in f.conn.calls)


def test_old_c14_candidate_never_backfills(monkeypatch: pytest.MonkeyPatch) -> None:
    f = fixture(monkeypatch, run=False)
    object.__setattr__(f.p.original.request, 'candidate_id', LOST_C14_CANDIDATE)
    monkeypatch.setattr(f.service, '_require_generation', lambda p: object())
    with pytest.raises(PrivateNativePending, match='historical_output_backfill_denied'):
        f.service.run_generation(f.p)
    with f.conn.transaction():
        assert f.service.capture_generation_output(f.p, f.result).status == 'capture_failed'
    assert not any(e[0] == 'producer-port' for e in f.conn.events)
    assert f.conn.output is None


@pytest.mark.parametrize('entry', ['prepare', 'run'])
def test_missing_receivers_deny_before_paid_call(monkeypatch: pytest.MonkeyPatch, entry: str) -> None:
    f = fixture(monkeypatch, run=False)
    f.conn.ready = False
    with pytest.raises(PrivateNativePending, match='560_receivers_required'):
        if entry == 'prepare':
            with f.conn.transaction():
                f.service.prepare_generation(ref=f.p.ref, lease=f.p.original.lease, spec=None,
                    materials=(), limits=None, provider=None)
        else:
            f.service.run_generation(f.p)
    assert not f.service._started and not f.service._observed_generation_outputs
    assert not any(e[0] == 'producer-port' for e in f.conn.events)


def test_capture_requires_caller_top_not_an_implicit_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    f = fixture(monkeypatch)
    calls = len(f.conn.calls)
    assert f.service.capture_generation_output(f.p, f.result).status == 'capture_failed'
    assert len(f.conn.calls) == calls and f.conn.output is None


@pytest.mark.parametrize('fail_capture', [False, True])
def test_ordinary_executor_commits_fee_before_stopping_or_artifact(monkeypatch: pytest.MonkeyPatch, fail_capture: bool) -> None:
    f = fixture(monkeypatch)
    f.conn.fail_capture = fail_capture
    executor: Any = object.__new__(PrivateNativePackExecutor)
    executor.service, executor.conn, executor._review = f.service, f.conn, {}
    work = SimpleNamespace(task=SimpleNamespace(pack_task_id=RECOVERY_TASK), slot=SimpleNamespace(slot_id=RECOVERY_SLOT),
        spec=SimpleNamespace(public_template=SimpleNamespace(version='v1')))
    monkeypatch.setattr(executor, '_refresh', lambda original: original)
    monkeypatch.setattr(executor, '_stage', lambda *args, **kw: f.conn.events.append(('stage', f.conn.top)))
    outcome = executor._finish_initial_generation(work, f.p, f.result)
    assert f.conn.fees is not None and f.conn.info.transaction_status == TransactionStatus.IDLE
    if fail_capture:
        assert outcome.status == 'preparing' and outcome.reason == 'private_generation_output_capture_failed'
        assert f.conn.output is None and not executor._review
        assert not any(e[0] == 'artifact-port' for e in f.conn.events)
    else:
        assert outcome.status == 'review_pending'
        captured_top = f.conn.output['top']
        assert f.conn.events.index(('commit', captured_top)) < next(i for i, e in enumerate(f.conn.events) if e[0] == 'artifact-port')


def test_outer_commit_failure_is_not_reported_as_durable(monkeypatch: pytest.MonkeyPatch) -> None:
    f = fixture(monkeypatch)
    f.conn.fail_commit = True
    with pytest.raises(ValueError, match='outer commit failure'):
        with f.conn.transaction():
            f.service.settle_generation(f.p, f.result)
            assert f.service.capture_generation_output(f.p, f.result).status == 'captured'
    assert f.conn.fees is None and f.conn.output is None


def test_gap_calls_only_fixed_factual_issuer_not_expired_source(monkeypatch: pytest.MonkeyPatch) -> None:
    f = fixture(monkeypatch, run=False)
    task = PersistentPackTaskRef(pack_task_id=RECOVERY_TASK, user_id=RECOVERY_USER, epoch=1, scope_id=RECOVERY_SCOPE,
        mapping_receipt_id=RECOVERY_MAPPING, demand_id=uuid4(), intent_hash='a'*64, public_task_id=uuid4())
    f.service.development_accounting_enabled = True
    f.service.core = SimpleNamespace(_task=lambda actual: SimpleNamespace(enhancement='prefer_private', slots=(
        SimpleNamespace(slot_id=RECOVERY_SLOT, logical_item_id=RECOVERY_BUSINESS, slot='practice-1'),)))
    monkeypatch.setattr(f.service, '_recovery_source', lambda actual: pytest.fail('gap must not refresh expired author SOURCE'))
    with f.conn.transaction():
        assert f.service.issue_initial_author_persistence_gap(task, C14_GAP_BINDING) is not None
        with pytest.raises(PrivateNativePending, match='exact_persistence_gap_required'):
            f.service.issue_initial_author_persistence_gap(task, uuid4())
    assert not f.service._started and not f.service._observed_generation_outputs


def test_recovery_finish_requires_committed_matching_output(monkeypatch: pytest.MonkeyPatch) -> None:
    f = fixture(monkeypatch)
    key = f.p.original.request.candidate_id
    work = SimpleNamespace(task=SimpleNamespace(pack_task_id=RECOVERY_TASK), slot=SimpleNamespace(slot_id=RECOVERY_SLOT),
        spec=SimpleNamespace(public_template=SimpleNamespace(version='v1')))
    executor: Any = object.__new__(PrivateNativePackExecutor)
    executor.service, executor.conn = f.service, f.conn
    executor._initial_authors = {key: (f.p, object(), work)}
    executor._initial_finished, executor._initial_success, executor._review = set(), {}, {}
    monkeypatch.setattr(f.service, '_fresh_recovery_source', lambda actual: nullcontext())
    monkeypatch.setattr(executor, '_refresh', lambda actual: actual)
    monkeypatch.setattr(executor, '_stage', lambda *args, **kw: None)
    with f.conn.transaction():
        f.service.settle_generation(f.p, f.result)
    with pytest.raises(PrivateNativePending, match='output_not_committed'):
        executor.finish_initial_author_recovery(f.p, f.result)
    assert not executor._initial_finished and f.conn.fees is not None
    with f.conn.transaction():
        assert f.service.capture_generation_output(f.p, f.result).status == 'captured'
    assert executor.finish_initial_author_recovery(f.p, f.result).status == 'review_pending'
    assert executor._initial_success[key][0] is f.p


def test_capture_does_not_require_old_source_or_lease_current(monkeypatch: pytest.MonkeyPatch) -> None:
    f = fixture(monkeypatch)
    with f.conn.transaction():
        f.service.settle_generation(f.p, f.result)
        monkeypatch.setattr(f.service, '_guard', lambda: pytest.fail('not current author permission'))
        monkeypatch.setattr(f.service, '_recovery_source', lambda task: pytest.fail('no author SOURCE refresh'))
        assert f.service.capture_generation_output(f.p, f.result).status == 'captured'


def test_synthetic_generation_does_not_require_capture_receiver(monkeypatch: pytest.MonkeyPatch) -> None:
    f = fixture(monkeypatch, run=False)
    object.__setattr__(f.p.original, 'mode', 'synthetic')
    _, _, provider = f.service._prepared[f.p.original.request.candidate_id]
    f.service._prepared[f.p.original.request.candidate_id] = (f.p, canonical_hash(generation_context(f.p)), provider)
    f.conn.ready = False
    assert f.service.run_generation(f.p) is f.result
    assert not f.service._observed_generation_outputs
    with f.conn.transaction():
        f.service.settle_generation(f.p, f.result)
        assert f.service.capture_generation_output(f.p, f.result).status == 'not_applicable'
    assert not any('private_generation_' in sql for sql, _ in f.conn.calls)
