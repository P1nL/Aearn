"""Offline seams for the original PRIVATE author successor, never live IO."""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, Iterator
from uuid import UUID, uuid4

import pytest
from psycopg.pq import TransactionStatus

from app.services.learning.item_supply.persistent_pack_contracts import PersistentPackTaskRef
from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending
from app.services.learning.item_supply.private_enhancement_service import (
    CONTINUATION_FIRST_FAILURE, CONTINUATION_KEY, PRIVATE_JOURNAL, RECOVERY_BUSINESS,
    RECOVERY_KEY, RECOVERY_MAPPING, RECOVERY_SCOPE, RECOVERY_SLOT, RECOVERY_TASK,
    RECOVERY_USER, IssuedPrivateInitialAuthorRecovery, PrivateEnhancementService,
)
from app.services.learning.item_supply.private_native_pack_executor import (
    PrivateNativePackExecutor, PrivatePhaseOutcome,
)


def _task() -> PersistentPackTaskRef:
    return PersistentPackTaskRef(pack_task_id=RECOVERY_TASK, user_id=RECOVERY_USER,
        epoch=1, scope_id=RECOVERY_SCOPE, mapping_receipt_id=RECOVERY_MAPPING,
        demand_id=uuid4(), intent_hash='a'*64, public_task_id=uuid4())


def _row(value: Any) -> Any:
    return SimpleNamespace(fetchone=lambda: value)


@pytest.fixture
def issued(monkeypatch: pytest.MonkeyPatch) -> Any:
    service: Any = object.__new__(PrivateEnhancementService)
    task, approval, origin = _task(), uuid4(), uuid4()
    records: dict[str, Any] = {}
    calls: list[Any] = []
    state: dict[str, Any] = {'predecessor': CONTINUATION_FIRST_FAILURE, 'duplicate': False}
    now = datetime.now(UTC)

    def event(actual: Any, kind: str, payload: Any, *, key: str) -> UUID:
        assert actual == task and kind == 'private_status'
        records[key] = payload
        calls.append(('event', key))
        return approval

    def execute(sql: str, params: Any) -> Any:
        calls.append((sql, params))
        if 'continuation_predecessor' in sql:
            assert params == (CONTINUATION_FIRST_FAILURE, task.pack_task_id, task.user_id, 1, task.scope_id)
            return _row(None if state['predecessor'] is None else {'id': state['predecessor']})
        if 'first_claim' in sql:
            return _row({'job_id': params[1]})
        if 'SELECT payload_json' in sql:
            payload = records.get(params[-1])
            return _row(None if payload is None else {'payload_json': payload})
        if sql.startswith('SELECT id FROM '+PRIVATE_JOURNAL):
            return _row({'id': approval} if state['duplicate'] or params[-1] in records else None)
        pytest.fail('unexpected offline query: '+sql)

    service.conn = SimpleNamespace(execute=execute)
    service.core = SimpleNamespace(_task=lambda actual: SimpleNamespace(enhancement='prefer_private',
        slots=(SimpleNamespace(slot_id=RECOVERY_SLOT, logical_item_id=RECOVERY_BUSINESS, slot='practice-1'),)),
        _private_event=event)
    service.development_accounting_enabled = True
    service._recoveries, service._recovery_sources = {}, {}
    source = SimpleNamespace(origin_id=lambda: origin, source_deadline=now+timedelta(hours=1))
    monkeypatch.setattr(service, '_guard', lambda: now)
    monkeypatch.setattr(service, '_continuation_receivers', lambda: calls.append('558-receivers'))
    monkeypatch.setattr(service, '_recovery_source', lambda actual: source)
    cap = service.issue_initial_author_continuation(task_ref=task, slot_id=RECOVERY_SLOT,
        predecessor_failure_id=CONTINUATION_FIRST_FAILURE)
    return SimpleNamespace(service=service, task=task, cap=cap, records=records,
        calls=calls, state=state, approval=approval, origin=origin, source=source)


def test_issued_successor_uses_predecessor_key_and_original_claim(issued: Any) -> None:
    service, cap = issued.service, issued.cap
    key = CONTINUATION_KEY+'.'+CONTINUATION_FIRST_FAILURE.hex
    assert service._initial_author_key(cap) == key
    payload = issued.records[key+'.approval']
    assert payload['schema_version'] == 'private_initial_author_continuation_approval_v1'
    assert payload['authorization_key'] == CONTINUATION_KEY
    assert payload['predecessor_failure_id'] == str(CONTINUATION_FIRST_FAILURE)
    assert payload['item_key'] == 'private-native.'+RECOVERY_BUSINESS.hex
    assert payload['version'] == 'v1' and payload['storage_version'] == 1
    assert service._recoveries[issued.approval][0] is cap
    assert service._recovery_sources[issued.approval] is issued.source
    job, batch = uuid4(), uuid4()
    lease = SimpleNamespace(job_id=job)
    controls: list[Any] = []
    service.facts_owner = SimpleNamespace(pipeline=SimpleNamespace(runtime=SimpleNamespace(
        _lease=lambda row, visibility: lease if visibility == 'private' else pytest.fail('not PRIVATE'),
        _control=lambda actual, **kw: controls.append(actual))))
    assert service.claim_initial_author_recovery(cap, job_id=job, batch_id=batch) is lease
    sql, params = next(c for c in issued.calls if isinstance(c, tuple) and 'first_claim' in c[0])
    assert 'private_initial_author_continuation_first_claim' in sql
    assert params == (issued.approval, job, batch, issued.origin, 'private.initial.author.continuation.'+issued.approval.hex)
    assert controls == [lease]
    old = IssuedPrivateInitialAuthorRecovery(service, issued.task, RECOVERY_SLOT, uuid4())
    assert service._initial_author_key(old) == RECOVERY_KEY
    assert service._initial_author_protocol(old) == 'recovery'


@pytest.mark.parametrize('mutation', ['copy', 'predecessor', 'protocol', 'slot', 'scope', 'payload', 'registry'])
def test_successor_requires_original_cap_and_binding(issued: Any, mutation: str) -> None:
    service, cap = issued.service, issued.cap
    if mutation == 'copy':
        cap = replace(cap)
    elif mutation == 'predecessor':
        object.__setattr__(cap, 'predecessor_failure_id', uuid4())
    elif mutation == 'protocol':
        object.__setattr__(cap, 'authorization_key', RECOVERY_KEY)
    elif mutation == 'slot':
        object.__setattr__(cap, 'slot_id', uuid4())
    elif mutation == 'scope':
        object.__setattr__(cap, 'task', cap.task.model_copy(update={'scope_id': uuid4()}))
    elif mutation == 'payload':
        issued.records[service._initial_author_key(cap)+'.approval']['storage_version'] = 2
    else:
        service._recoveries.clear()
    with pytest.raises(PrivateNativePending, match='original_issued_cap_required'):
        service._require_initial_recovery(cap)
    assert not any(isinstance(c, tuple) and 'first_claim' in c[0] for c in issued.calls)


@pytest.mark.parametrize('denial', ['predecessor', 'duplicate'])
def test_new_approval_does_not_bypass_committed_predecessor_or_once(issued: Any, denial: str) -> None:
    issued.records.clear()
    issued.state[denial] = None if denial == 'predecessor' else True
    before = sum(isinstance(c, tuple) and c[0] == 'event' for c in issued.calls)
    with pytest.raises(PrivateNativePending, match='committed_predecessor_required|successor_already_issued'):
        issued.service.issue_initial_author_continuation(task_ref=issued.task, slot_id=RECOVERY_SLOT,
            predecessor_failure_id=CONTINUATION_FIRST_FAILURE)
    assert sum(isinstance(c, tuple) and c[0] == 'event' for c in issued.calls) == before


def test_persisted_continuation_binding_cannot_restore_prepared_registry(issued: Any) -> None:
    service = issued.service
    prepared = SimpleNamespace(ref=SimpleNamespace(pack_task_id=RECOVERY_TASK),
        original=SimpleNamespace(request=SimpleNamespace(candidate_id=uuid4())))
    service._recovery_bindings = {}

    def execute(sql: str, params: Any) -> Any:
        assert 'private_initial_author_continuation_binding_v1' in sql
        return _row({'id': uuid4()})

    service.conn = SimpleNamespace(execute=execute)
    with pytest.raises(PrivateNativePending, match='original_prepared_registry_required'):
        service._prepared_recovery(prepared)


def test_original_stage_and_failed_settlement_keep_exact_attempt_binding(
        issued: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    service, cap = issued.service, issued.cap
    key = service._initial_author_key(cap)
    now, candidate, binding, reservation, settlement, consumed, started, job = (
        datetime.now(UTC), uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), uuid4())
    work = SimpleNamespace(task=issued.task, ref=object(), lease=object(),
        slot=SimpleNamespace(slot_id=RECOVERY_SLOT, logical_item_id=RECOVERY_BUSINESS))
    executor: Any = object.__new__(PrivateNativePackExecutor)
    executor.service, executor.conn = service, service.conn
    executor.facts = SimpleNamespace(_guard=lambda *args: now)
    work.lease = SimpleNamespace(job_id=job)
    executor._stage(work, 'author', subject='v1', started=True, recovery=cap)
    event = issued.records[key+'.author.started']
    assert event['schema_version'] == 'private_native_stage_v1' and event['receipt_id'] is None
    with pytest.raises(PrivateNativePending, match='committed_once_no_paid_replay'):
        executor._stage(work, 'author', subject='v1', started=True, recovery=cap)

    prepared = SimpleNamespace(ref=SimpleNamespace(pack_task_id=RECOVERY_TASK), original=SimpleNamespace(
        request=SimpleNamespace(candidate_id=candidate, materials=('material',)), sources=('receipt',),
        reservation_id=reservation, lease=SimpleNamespace(job_id=job, generation=1)))
    result = SimpleNamespace(state='failed', source=None, receipt=None, safe_reason='provider_failed')
    service._results, service._started = {candidate: result}, {candidate}
    source = SimpleNamespace(require=lambda: None, source_deadline=now+timedelta(hours=1), origin_id=lambda: issued.origin)
    service.facts_owner = SimpleNamespace(_guard=lambda *args: now,
        source_authority=SimpleNamespace(assert_current=lambda *args: None))
    monkeypatch.setattr(service, '_require_generation', lambda actual: None)
    monkeypatch.setattr(service, '_prepared_recovery', lambda actual: (cap, binding))
    monkeypatch.setattr(service, '_recovery_source', lambda actual: source)
    committed = True

    def execute(sql: str, params: Any) -> Any:
        assert 'xmin::text::bigint<>(txid_current() %% 4294967296)' in sql
        if 'runtime_settlements' in sql:
            assert params == (reservation, job, 1, 'generation.'+candidate.hex)
            return _row({'id': settlement} if committed else None)
        assert params == (key+'.consumed', RECOVERY_TASK)
        return _row({'id': consumed, 'payload_json': {'binding_id': str(binding), 'started_id': str(started)}})

    service.conn = SimpleNamespace(execute=execute)
    service.persist_generation_failure(prepared, result)
    payload = issued.records[key+'.failure']
    assert payload == dict(schema_version='private_initial_author_continuation_failure_v1',
        binding_id=str(binding), consumed_id=str(consumed), started_id=str(started), job_id=str(job),
        candidate_id=str(candidate), reservation_id=str(reservation), settlement_id=str(settlement),
        state='failed', safe_reason='provider_failed', receipt=None, source_origin_id=str(issued.origin), recorded_at=now.isoformat())
    committed = False
    with pytest.raises(PrivateNativePending, match='committed_settlement_consume_required'):
        service.persist_generation_failure(prepared, result)


@pytest.mark.parametrize('protocol', ['recovery', 'continuation'])
def test_original_preio_commits_exact_consume_before_idle_once(
        monkeypatch: pytest.MonkeyPatch, protocol: str) -> None:
    from tests.learning.test_private_generation_durability import fixture as durability_fixture

    # Reuse real typed live preparation/result and the original observation
    # registry. Only the SQL/source/producer ports below remain offline seams.
    fixture = durability_fixture(monkeypatch, run=False)
    service, prepared, result = fixture.service, fixture.p, fixture.result
    candidate = prepared.original.request.candidate_id
    now, binding, origin = datetime.now(UTC), uuid4(), uuid4()
    events: list[str] = []
    conn = SimpleNamespace(autocommit=False, info=SimpleNamespace(transaction_status=TransactionStatus.IDLE))

    @contextmanager
    def transaction() -> Iterator[None]:
        conn.info.transaction_status = TransactionStatus.INTRANS
        try:
            yield
        finally:
            conn.info.transaction_status = TransactionStatus.IDLE
            events.append('commit')

    def execute(sql: str, params: Any = ()) -> Any:
        if 'private_generation_durability_ready()' in sql:
            assert conn.info.transaction_status == TransactionStatus.INTRANS
            events.append('ready')
            return _row({'ready': True})
        if '_consume(' in sql:
            assert 'private_initial_author_'+protocol+'_consume' in sql
            assert params == (binding, origin)
            assert conn.info.transaction_status == TransactionStatus.INTRANS
            events.append('consume')
        else:
            assert 'private_pack_auxiliary_committed' in sql
        return _row({'ok': True})

    conn.transaction, conn.execute = transaction, execute
    cap = IssuedPrivateInitialAuthorRecovery(service, _task(), RECOVERY_SLOT, uuid4(),
        CONTINUATION_KEY if protocol == 'continuation' else RECOVERY_KEY,
        CONTINUATION_FIRST_FAILURE if protocol == 'continuation' else None)
    service.conn, service._started, service._results = conn, set(), {}
    service._recovery_bindings = {candidate: (prepared, cap, binding)}

    @contextmanager
    def source_front(ref: Any) -> Iterator[Any]:
        yield SimpleNamespace(require=lambda: events.append('current'), origin_id=lambda: origin,
            source_deadline=now+timedelta(hours=1))

    def run(original: Any, provider: Any) -> Any:
        assert original is prepared.original
        assert provider is service._prepared[candidate][2]
        assert conn.info.transaction_status == TransactionStatus.IDLE
        assert events[-3:] == ['consume', 'current', 'commit']
        assert candidate in service._started
        events.append('pipeline')
        return result

    service.facts_owner = SimpleNamespace(_guard=lambda *args: now,
        source_authority=SimpleNamespace(assert_current=lambda *args: events.append('source-pair')),
        pipeline=SimpleNamespace(run_generation=run))
    monkeypatch.setattr(service, '_guard', lambda: now)
    monkeypatch.setattr(service, '_select_initial_recovery_source', lambda actual: None)
    monkeypatch.setattr(service, '_generation_source_front', source_front)
    monkeypatch.setattr(service, '_prepared_recovery', lambda actual: (cap, binding))
    assert service.run_generation(prepared) is result
    observed = service._observed_generation_outputs[candidate]
    assert observed.prepared is prepared and observed.result is result
    assert events.index('ready') < events.index('consume')
    with pytest.raises(PrivateNativePending, match='idle_once_required'):
        service.run_generation(prepared)
    assert events.count('consume') == events.count('pipeline') == 1


@pytest.mark.parametrize(('terminal', 'live', 'expected'), [
    (None, False, 'preparing'), ('failure', False, 'quality_failed'),
    ('artifact', False, 'preparing'), ('artifact', True, 'revision_pending'),
    ('published', False, 'revision_pending'), ('review_failed', False, 'revision_pending'),
])
def test_initial_terminal_allows_only_live_quality_or_verified_completed_stage(
        monkeypatch: pytest.MonkeyPatch, terminal: str | None, live: bool, expected: str) -> None:
    from app.services.learning.item_supply import native_type_exposure

    executor: Any = object.__new__(PrivateNativePackExecutor)
    task, now = _task(), datetime.now(UTC)
    first = SimpleNamespace(slot_id=RECOVERY_SLOT, slot='practice-1')
    other = SimpleNamespace(slot_id=uuid4(), slot='practice-2')
    queries: list[str] = []
    resumed: list[Any] = []

    def execute(sql: str, params: Any) -> Any:
        queries.append(sql)
        if 'continuation_terminal(id)' in sql:
            return _row({'status': terminal})
        if 'SELECT started.id' in sql:
            assert "COALESCE(item_supply_internal.private_initial_author_continuation_terminal(started.id),'')" in sql
            assert "NOT IN ('artifact','published','review_failed')" in sql
            return _row(None)
        if 'SELECT DISTINCT slot_id' in sql:
            return SimpleNamespace(fetchall=lambda: [{'slot_id': RECOVERY_SLOT}] if terminal == 'published' else [])
        if 'SELECT id FROM '+PRIVATE_JOURNAL in sql:
            return _row({'id': uuid4()})
        pytest.fail('unexpected offline query: '+sql)

    executor.conn = SimpleNamespace(autocommit=False, info=SimpleNamespace(transaction_status=TransactionStatus.IDLE),
        transaction=nullcontext, execute=execute)
    base_pack = SimpleNamespace(selected=(SimpleNamespace(version_id=uuid4()),))
    public = SimpleNamespace(require_pack=lambda cap: base_pack, resolve_content=lambda *a, **kw: object(),
        source_deadline=lambda content: now+timedelta(days=1))
    versions = {slot: SimpleNamespace(published_version_id=uuid4()) for slot in
        ('practice-1', 'practice-2', 'assessment-1', 'assessment-2', 'guided-remediation')}
    executor.service = SimpleNamespace(_guard=lambda: now, _continuation_receivers=lambda: None,
        core=SimpleNamespace(_task=lambda ref: SimpleNamespace(enhancement='prefer_private', slots=(first, other)),
            _versions=lambda ref: versions),
        type_owner=SimpleNamespace(resolve_mapping=lambda identity: SimpleNamespace(target_id='python-kc-binding-v1')),
        base_fallback_owner=lambda: SimpleNamespace(resolve=lambda ref: None),
        base_service=SimpleNamespace(type_owner=public, _attempt=lambda *a, **kw: SimpleNamespace(ready=SimpleNamespace(capability=object()))),
        exposure_owner=SimpleNamespace(snapshot_complete=lambda: SimpleNamespace(exposure=object())))
    executor.relation_repair = SimpleNamespace(pending=lambda ref: None)
    executor._initial_success = {uuid4(): (object(), SimpleNamespace(task=task, slot=first), uuid4())} if live else {}
    executor._review, executor._failed, executor._investigation = {}, {}, {}
    monkeypatch.setattr(native_type_exposure, '_protected', lambda *args: None)

    def recover(actual: Any, slot: Any, retained: Any) -> Any:
        resumed.append(slot)
        return PrivatePhaseOutcome(task.pack_task_id, 'revision_pending')

    monkeypatch.setattr(executor, '_recover_committed_progress', recover)
    outcome = executor.run_next_phase(task)
    assert outcome.status == expected
    if expected == 'revision_pending':
        assert resumed == [other if terminal == 'published' else first]
    else:
        assert not resumed and not any('SELECT started.id' in sql for sql in queries)


@pytest.mark.parametrize('live', [False, True])
def test_committed_initial_result_never_reconstructs_prepared(
        monkeypatch: pytest.MonkeyPatch, live: bool) -> None:
    executor: Any = object.__new__(PrivateNativePackExecutor)
    task, artifact, job = _task(), uuid4(), uuid4()
    slot = SimpleNamespace(slot_id=RECOVERY_SLOT)
    work = SimpleNamespace(task=task, slot=slot, lease=SimpleNamespace(job_id=job))
    event = {'receipt_id': str(artifact), 'job_id': str(job), 'stage': 'author'}
    executor.conn = SimpleNamespace(transaction=nullcontext, execute=lambda *a: _row({
        'operation_key': CONTINUATION_KEY+'.'+CONTINUATION_FIRST_FAILURE.hex+'.author.result', 'payload_json': event}))
    executor.service = SimpleNamespace(_guard=lambda: None)
    executor._initial_success = {uuid4(): (object(), work, artifact)} if live else {}
    executor._review = {}
    monkeypatch.setattr(executor, '_phase', lambda *a: pytest.fail('cannot restore initial author from JSON'))
    outcome = executor._recover_committed_progress(task, slot, uuid4())
    assert outcome.status == ('review_pending' if live else 'preparing')
    assert executor._review == ({RECOVERY_SLOT: (work, artifact)} if live else {})


def test_completed_review_uses_original_committed_progress_not_initial_registry(
        monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.learning.item_supply import private_native_pack_executor as module
    from app.services.learning.item_supply.generation_contracts import GenerationRequestV2

    executor: Any = object.__new__(PrivateNativePackExecutor)
    task, receipt, artifact, job = _task(), uuid4(), uuid4(), uuid4()
    slot, work = SimpleNamespace(slot_id=RECOVERY_SLOT), SimpleNamespace(ref=object(), lease=object())
    spec, old_ref = object(), SimpleNamespace(parent_version_id=None)
    peer = {'spec': spec, 'ref': old_ref, 'artifact_id': str(artifact)}
    calls: list[Any] = []

    def execute(sql: str, params: Any) -> Any:
        if 'SELECT operation_key,payload_json' in sql:
            return _row({'operation_key': 'private.stage.existing.review.result', 'payload_json': {
                'stage': 'review', 'receipt_id': str(receipt), 'job_id': str(job)}})
        if 'SELECT request_json' in sql:
            return _row({'request_json': {}})
        if 'SELECT payload_json' in sql:
            return _row({'payload_json': peer})
        pytest.fail('unexpected offline query: '+sql)

    cap = SimpleNamespace(validation_id=uuid4(), blind_id=uuid4())
    prepared, result = object(), object()
    executor.conn = SimpleNamespace(transaction=nullcontext, execute=execute)
    executor.service = SimpleNamespace(_guard=lambda: None)
    executor._initial_success = {}

    def issue_review(**kwargs: Any) -> Any:
        assert kwargs == {'ref': work.ref, 'lease': work.lease, 'review_id': receipt}
        calls.append('original-committed-issuer')
        return cap

    def adopt(actual: Any) -> Any:
        assert actual is cap
        calls.append('original-adoption')
        return prepared, result

    def finish(actual_work: Any, actual_prepared: Any, actual_result: Any, **kwargs: Any) -> Any:
        assert (actual_work, actual_prepared, actual_result) == (work, prepared, result)
        assert kwargs == {'validation_id': cap.validation_id, 'blind_id': cap.blind_id, 'review_id': receipt}
        calls.append('normal-finish-review')
        return PrivatePhaseOutcome(task.pack_task_id, 'revision_pending')

    executor.progress = SimpleNamespace(issue_review=issue_review)
    executor.facts = SimpleNamespace(adopt_committed_review=adopt)
    monkeypatch.setattr(module, 'checked_model', lambda value, model: value)
    monkeypatch.setattr(GenerationRequestV2, 'model_validate_json', lambda value: SimpleNamespace(materials=('original',)))
    monkeypatch.setattr(executor, '_phase', lambda *args: work)
    monkeypatch.setattr(executor, '_finish_review', finish)
    assert executor._recover_committed_progress(task, slot, uuid4()).status == 'revision_pending'
    assert calls == ['original-committed-issuer', 'original-adoption', 'normal-finish-review']


@pytest.mark.parametrize('live', [False, True])
def test_continuation_unfinished_review_uses_live_original_work_only(
        monkeypatch: pytest.MonkeyPatch, live: bool) -> None:
    executor: Any = object.__new__(PrivateNativePackExecutor)
    task, artifact, job = _task(), uuid4(), uuid4()
    work = SimpleNamespace(task=task, slot=SimpleNamespace(slot_id=RECOVERY_SLOT), lease=SimpleNamespace(job_id=job))
    author, prepared = object(), object()

    def execute(sql: str, params: Any) -> Any:
        assert 'private_initial_author_continuation_claim_v1' in sql
        assert params == (task.pack_task_id, RECOVERY_KEY+'.claim', str(job))
        return _row({'id': uuid4()})

    executor.conn = SimpleNamespace(transaction=nullcontext, execute=execute)
    executor.service = SimpleNamespace(_fresh_recovery_source=lambda actual: nullcontext())
    executor._review = {RECOVERY_SLOT: (work, artifact)}
    executor._initial_success = {uuid4(): (author, work, artifact)} if live else {}
    monkeypatch.setattr(executor, '_phase', lambda *a: pytest.fail('no replacement lease for unfinished initial quality'))
    monkeypatch.setattr(executor, 'prepare_initial_recovery_review', lambda actual:
        prepared if actual is author else pytest.fail('not original author'))
    monkeypatch.setattr(executor, 'run_initial_recovery_review', lambda actual:
        PrivatePhaseOutcome(task.pack_task_id, 'published') if actual is prepared else pytest.fail('not original prepared'))
    assert executor._run_review(RECOVERY_SLOT).status == ('published' if live else 'preparing')
