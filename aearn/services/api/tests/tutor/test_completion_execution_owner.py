"""Offline real-owner tests. The connection seam is not a PostgreSQL compiler."""
from __future__ import annotations

import copy
import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from psycopg import Connection
from psycopg.pq import TransactionStatus

from app.agents.harness.context_builder import TutorContextBuilder
from app.agents.harness.contracts import (
    TutorCapabilityRequest, TutorCapabilityResult, TutorCapabilityStatus,
    TutorContextInput, TutorContextSource, TutorDecision, TutorEffectProposal,
    TutorEffectResult, TutorEffectStatus, TutorLease, TutorPlanDraftV110PayloadField,
    TutorPolicySnapshot, TutorProviderAttemptOutcome, TutorProviderAttemptReceipt,
    TutorProviderResult, TutorRunSnapshot, TutorRunStatus, TutorTerminalOutcome,
    TutorContinuationKind, TutorDecisionGateResult, TutorDecisionGateStatus,
    TutorCheckpointReason,
)
from app.agents.runtime.contracts import (
    RuntimeEvent, RuntimeEventKind, RuntimePlanningStepResult, RuntimeTerminalStatus,
    RuntimeThreadHandle, RuntimeToolResult, RuntimeTurnResult,
)
from app.services.llm.http_execution import current_http_execution
from app.services.llm.http_execution import LLMHTTPExecutionError
from app.services.llm.contracts import LLMUsage
from app.services.tutor.completion_execution import (
    COMPLETION_POLICY_VERSION, CompletionExecutionError, CompletionExecutionOwner,
    completion_admission_policy, decode_result, encode_result, validate_completion_batch_settings,
    CompletionTutorProviderResult,
    CompletionNestedHTTPOutcome,
)
from app.services.tutor.persistence.repository import PostgresTutorRepository
from app.services.tutor.ports import (
    AllowTutorDecisionGate, DefaultDenyCapabilityGateway, DefaultDenyEffectCommitter,
    FixedClock, InMemoryTutorCompactionPublisher, InMemoryTutorContextLoader,
    InMemoryTutorRunStore,
)
from app.services.tutor.run_loop import TutorRunLoop
from app.services.tutor.provider_gateway import PrimaryTutorProviderGateway
from app.services.tutor.decision_protocol import TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION
from app.core.config import Settings
from app.services.llm.llm_client import LLMJsonResponse

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)


class CommitUnconfirmed(RuntimeError):
    pass


class OfflineConnection:
    """Execute the actual owner's SQL against deterministic rows/transaction cuts.

    SQL constraints remain separate shape checks/Main PG acceptance. This seam
    models commits and receipt identities, not PostgreSQL's parser/trigger engine.
    """
    def __init__(self) -> None:
        self.autocommit = True
        self.info = SimpleNamespace(transaction_status=TransactionStatus.IDLE)
        self.now = NOW
        self.run: dict[str, Any] = {
            'id': 'run', 'user_id': 'user', 'conversation_id': 'conversation', 'input_revision': 0,
            'policy_json': {'execution_profile': 'completion_driven_v1'},
            'policy_version': COMPLETION_POLICY_VERSION, 'policy_fingerprint': 'a' * 64,
            'active_lease_owner_id': 'owner', 'active_lease_generation': 1,
            'active_lease_expires_at': NOW + timedelta(seconds=30),
            'terminal_outcome': None, 'cancelled_at': None, 'superseded_by_run_id': None,
            'iteration_count': 0, 'model_call_count': 0, 'capability_call_count': 0, 'effect_count': 0,
        }
        self.batches: dict[str, dict[str, Any]] = {}
        self.steps: dict[str, dict[str, Any]] = {}
        self.actions: dict[str, dict[str, Any]] = {}
        self.receipts: dict[tuple[object, ...], tuple[object, ...]] = {}
        self.material_reviews: dict[tuple[object, ...], dict[str, object]] = {}
        self.business: dict[str, object] = {}
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.rows: list[dict[str, Any]] = []
        self.commit_failure: tuple[str, bool] | None = None
        self.lock_delay = 0

    @contextmanager
    def transaction(self):
        before = copy.deepcopy((self.run, self.batches, self.steps, self.actions, self.receipts, self.business, self.material_reviews))
        start = len(self.calls)
        self.info.transaction_status = TransactionStatus.INTRANS
        try:
            yield
        except BaseException:
            self.run, self.batches, self.steps, self.actions, self.receipts, self.business, self.material_reviews = before
            raise
        else:
            if self.commit_failure is not None and any(self.commit_failure[0] in q for q, _ in self.calls[start:]):
                _, committed = self.commit_failure
                self.commit_failure = None
                if not committed:
                    self.run, self.batches, self.steps, self.actions, self.receipts, self.business, self.material_reviews = before
                raise CommitUnconfirmed('private payload must not reach a diagnostic')
        finally:
            self.info.transaction_status = TransactionStatus.IDLE

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> OfflineConnection:
        q = ' '.join(sql.split())
        self.calls.append((q, params))
        self.rows = []
        if q.startswith('SELECT clock_timestamp()'):
            self.rows = [{'now': self.now}]
        elif q.startswith('SELECT') and 'FROM tutor_runs' in q:
            if params[:2] == ('run', 'user') or params == ('run',):
                if 'FOR UPDATE' in q and self.lock_delay:
                    self.now += timedelta(seconds=self.lock_delay)
                    self.lock_delay = 0
                self.rows = [copy.deepcopy(self.run)]
                if 'clock_timestamp() AS checked_at' in q:
                    self.rows[0].update(status='running', checked_at=self.now)
        elif q.startswith('SELECT') and 'FROM tutor_run_execution_batches' in q:
            self.rows = sorted(self.batches.values(), key=lambda b: b['batch_index'], reverse=True)[:1]
        elif q.startswith('SELECT') and 'FROM tutor_run_step_attempts' in q:
            rows = list(self.steps.values())
            if 'WHERE id=%s' in q:
                rows = [s for s in rows if (s['id'], s['run_id'], s['user_id'], s['conversation_id']) == params]
            elif 'step_key=%s' in q:
                rows = sorted([s for s in rows if s['step_key'] == params[1]], key=lambda s: s['attempt_number'], reverse=True)[:1]
            elif "request_json->'progress_identity'" in q:
                rows = [s for s in rows if s['state'] in ('accepted', 'rejected')
                        and s['request_json'].get('progress_identity') == json.loads(params[1])
                        and s['dependencies_json'] == json.loads(params[2])]
            elif "'result_recorded'" in q:
                rows = [s for s in rows if s['state'] in ('prepared', 'dispatched', 'result_recorded', 'outcome_unknown')]
            else:
                rows = [s for s in rows if s['state'] in ('prepared', 'dispatched', 'outcome_unknown')]
            self.rows = copy.deepcopy(rows)
        elif q.startswith('INSERT INTO tutor_run_execution_batches'):
            names = ('run_id', 'user_id', 'conversation_id', 'input_revision', 'predecessor_batch_id',
                     'batch_index', 'owner_id', 'owner_generation', 'policy_fingerprint', 'issued_at', 'expires_at')
            row = dict(zip(names, params, strict=True))
            row.update(id=f'batch-{len(self.batches)+1}', decision_count=0, http_attempt_count=0)
            self.batches[row['id']] = row
            self.rows = [row]
        elif q.startswith('INSERT INTO tutor_run_step_attempts'):
            if any(s['state'] in ('prepared', 'dispatched', 'result_recorded', 'outcome_unknown') for s in self.steps.values()):
                raise RuntimeError('active-step uniqueness')
            names = ('run_id', 'user_id', 'conversation_id', 'input_revision', 'batch_id', 'step_key', 'kind',
                     'decision_iteration', 'attempt_number', 'predecessor_attempt_id', 'owner_id', 'owner_generation',
                     'request_json', 'dependencies_json', 'capability_count_before', 'effect_count_before', 'prepared_at')
            row = dict(zip(names, params, strict=True))
            for name in ('request_json', 'dependencies_json'):
                row[name] = json.loads(row[name])
            row.update(id=f'step-{len(self.steps)+1}', state='prepared', observable_http_count=0,
                       http_batch_ids_json=[], result_type=None, result_json=None, result_recorded_at=None)
            self.steps[row['id']] = row
            self.rows = [row]
        elif q.startswith('UPDATE tutor_run_step_attempts'):
            row = self.steps[params[-1]]
            if "state='dispatched'" in q:
                row['state'] = 'dispatched'
                self.batches[row['batch_id']]['decision_count'] += 1
            elif 'SET state=%s,result_type=' in q:
                row.update(state=params[0], result_type=params[1], result_json=json.loads(params[2]), result_recorded_at=self.now)
            elif 'observable_http_count=observable_http_count+1' in q:
                batch = self.batches[params[0]]
                if batch['http_attempt_count'] >= 16:
                    raise RuntimeError('batch HTTP bound')
                row['observable_http_count'] += 1
                row['http_batch_ids_json'].append(params[0])
                batch['http_attempt_count'] += 1
            elif "state='accepted'" in q:
                row.update(state='accepted', accepted_owner_id=params[0], accepted_owner_generation=params[1], acceptance_batch_id=params[2])
            elif "state='not_sent'" in q:
                row['state'] = 'not_sent'
            elif "state='rejected'" in q:
                row.update(state='rejected', diagnostic_code=params[0])
            elif "state='outcome_unknown'" in q:
                row['state'] = 'outcome_unknown'
            else:
                raise AssertionError(q)
            self.rows = [copy.deepcopy(row)]
        elif q.startswith('UPDATE tutor_runs SET model_call_count=GREATEST'):
            self.run['model_call_count'] = max(self.run['model_call_count'], params[0])
            self.run['iteration_count'] = max(self.run['iteration_count'], params[1])
        elif q.startswith('UPDATE tutor_runs SET capability_call_count=GREATEST'):
            self.run['capability_call_count'] = max(self.run['capability_call_count'], params[0])
            self.run['effect_count'] = max(self.run['effect_count'], params[1])
        elif q.startswith('SELECT a.id,r.receipt_json'):
            if params[-1] in self.actions:
                self.rows = [self.actions[params[-1]]]
        elif q.startswith('INSERT INTO tutor_provider_attempt_receipts'):
            identity = (params[0], params[3], params[4], params[5])
            if identity not in self.receipts:
                self.receipts[identity] = params[:-1]
                self.rows = [{'id': f'receipt-{len(self.receipts)}'}]
        elif q.startswith('SELECT id FROM tutor_provider_attempt_receipts'):
            identity = (params[0], params[3], params[4], params[5])
            if self.receipts.get(identity) == params:
                self.rows = [{'id': 'original-receipt'}]
        elif q.startswith('SELECT * FROM rag_material_semantic_reviews'):
            if params in self.material_reviews:
                self.rows = [self.material_reviews[params]]
        elif q.startswith('INSERT INTO rag_material_semantic_reviews'):
            identity = (params[2], params[3], params[4], params[5])
            self.material_reviews[identity] = {'selection_handle': params[6], 'candidate_digest': params[9],
                'request_binding_hash': params[12], 'review_status': 'dispatched', 'reviewer_model': None, 'usage_json': None}
        else:
            raise AssertionError(q)
        return self

    def fetchone(self) -> dict[str, Any] | None:
        return copy.deepcopy(self.rows[0]) if self.rows else None


def setup_owner():
    conn = OfflineConnection()
    policy = completion_admission_policy(TutorPolicySnapshot(
        deadline=NOW + timedelta(seconds=300), max_capability_calls=2, max_effects=2,
        context_token_budget=100,
    ), now=NOW)
    run = TutorRunSnapshot('run', 'conversation', 'user', 0, policy, 'interactive')
    lease = TutorLease('run', 'owner', NOW + timedelta(seconds=30), 1)
    owner = CompletionExecutionOwner(cast(Connection[dict[str, object]], conn))
    return conn, run, lease, owner


def prepare(owner, run, lease, *, dependencies=None):
    batch = owner.ensure_batch(run=run, lease=lease)
    step = owner.prepare_step(run=run, lease=lease, batch=batch, step_key='decision-1',
                              kind='provider_decision', request={'context': 'private'}, dependencies=dependencies or {})
    return batch, step


def final_result(*, attempts=()):
    return TutorProviderResult(TutorDecision(public_message='完成。', terminal_outcome=TutorTerminalOutcome.COMPLETED), attempts=attempts)


def test_real_sidecar_data_roundtrips_without_fabricated_business_completion():
    runtime = RuntimeTurnResult(RuntimeThreadHandle('thread', 2), 'turn', RuntimeTerminalStatus.COMPLETED,
        (RuntimeEvent(RuntimeEventKind.TURN_COMPLETED, 'thread', turn_id='turn', terminal_status=RuntimeTerminalStatus.COMPLETED),))
    dto = RuntimePlanningStepResult(runtime, {'draft_completed': False, 'revision': 4},
                                   ({'success': True, 'content': RuntimeToolResult(True, '真实工具结果').content},), 1, 0)
    kind, payload = encode_result(dto)
    assert kind == 'runtime_planning_step_result_v1'
    assert decode_result(kind, json.loads(payload)) == dto
    assert dto.model_http_request_count is None and not dto.model_usage_available
    malformed = json.loads(payload)
    malformed['unknown_field'] = 'not accepted'
    with pytest.raises(CompletionExecutionError, match='shape_invalid'):
        decode_result(kind, malformed)


@pytest.mark.parametrize('size', [20, 200])
def test_typed_plan_transport_is_not_truncated_by_parent_dataclass_codec(size):
    argument = TutorPlanDraftV110PayloadField('profile_json', json.dumps('完整依据' * size, ensure_ascii=True))
    result = TutorProviderResult(TutorDecision(capability_requests=(TutorCapabilityRequest(
        'draft-request', 'learning.plan.draft', (argument,), '1.1.0'),)))
    kind, payload = encode_result(result)
    restored = decode_result(kind, json.loads(payload))
    assert restored == result
    assert isinstance(restored.decision.capability_requests[0].arguments[0], TutorPlanDraftV110PayloadField)


@pytest.mark.parametrize('autocommit,status', [(False, TransactionStatus.IDLE), (True, TransactionStatus.INTRANS)])
def test_owner_rejects_implicit_outer_transaction(autocommit, status):
    conn, run, lease, owner = setup_owner()
    conn.autocommit = autocommit
    conn.info.transaction_status = status
    with pytest.raises(CompletionExecutionError, match='prior_commit_required'):
        owner.ensure_batch(run=run, lease=lease)
    assert conn.calls == []


@pytest.mark.parametrize('field,value', [('input_revision', 1), ('active_lease_generation', 2),
    ('terminal_outcome', 'completed'), ('cancelled_at', NOW), ('superseded_by_run_id', 'new-run')])
def test_owner_requires_exact_current_scope(field, value):
    conn, run, lease, owner = setup_owner()
    conn.run[field] = value
    with pytest.raises(CompletionExecutionError, match='current_owner_required'):
        owner.ensure_batch(run=run, lease=lease)
    assert not conn.batches


def test_postlock_clock_not_caller_now_controls_authority():
    conn, run, lease, owner = setup_owner()
    conn.lock_delay = 31
    with pytest.raises(CompletionExecutionError, match='current_owner_required'):
        owner.ensure_batch(run=run, lease=lease, now=NOW)


def test_original_result_can_be_recorded_late_but_only_fresh_owner_accepts():
    conn, run, lease, owner = setup_owner()
    old_batch, step = prepare(owner, run, lease)
    step = owner.mark_dispatched(run=run, lease=lease, step=step)
    conn.now += timedelta(seconds=2401)
    conn.run.update(active_lease_owner_id='new-owner', active_lease_generation=2,
                    active_lease_expires_at=conn.now + timedelta(seconds=30))
    saved = owner.record_result(run=run, lease=lease, step=step, result=final_result())
    assert saved.state == 'result_recorded'
    with pytest.raises(CompletionExecutionError, match='current_owner_required'):
        owner.accept_result(run=run, lease=lease, step=saved, batch=old_batch, dependencies={}, validate=lambda: None, consume=lambda: None)
    fresh = TutorLease('run', 'new-owner', conn.now + timedelta(seconds=30), 2)
    batch = owner.ensure_batch(run=run, lease=fresh, minimum_http_attempts=0)
    assert batch.predecessor_batch_id == old_batch.id
    assert owner.accept_result(run=run, lease=fresh, step=saved, batch=batch, dependencies={},
                               validate=lambda: None, consume=lambda: 'accepted') == 'accepted'
    assert conn.steps[step.id]['acceptance_batch_id'] == batch.id


@pytest.mark.parametrize('committed', [False, True])
def test_result_commit_unknown_is_read_back_never_redispatched(committed):
    conn, run, lease, owner = setup_owner()
    _, step = prepare(owner, run, lease)
    step = owner.mark_dispatched(run=run, lease=lease, step=step)
    conn.commit_failure = ('SET state=%s,result_type=', committed)
    with pytest.raises(CommitUnconfirmed):
        owner.record_result(run=run, lease=lease, step=step, result=final_result())
    saved = owner.pending_step(run=run, lease=lease)
    assert saved.state == ('result_recorded' if committed else 'dispatched')
    if not committed:
        with pytest.raises(CompletionExecutionError, match='dispatch_fenced'):
            owner.mark_dispatched(run=run, lease=lease, step=saved)
    else:
        assert saved.result == final_result()
        assert owner.record_result(run=run, lease=lease, step=step, result=final_result()) == saved


def test_accept_consumer_and_acceptance_share_one_atomic_boundary():
    conn, run, lease, owner = setup_owner()
    batch, step = prepare(owner, run, lease)
    step = owner.mark_dispatched(run=run, lease=lease, step=step)
    step = owner.record_result(run=run, lease=lease, step=step, result=final_result())
    def failed_consumer():
        conn.business['published'] = True
        raise RuntimeError('consumer failed')
    with pytest.raises(RuntimeError, match='consumer failed'):
        owner.accept_result(run=run, lease=lease, step=step, batch=batch, dependencies={},
                            validate=lambda: None, consume=failed_consumer)
    assert conn.steps[step.id]['state'] == 'result_recorded' and not conn.business
    conn.commit_failure = ("state='accepted'", True)
    with pytest.raises(CommitUnconfirmed):
        owner.accept_result(run=run, lease=lease, step=step, batch=batch, dependencies={},
                            validate=lambda: None, consume=lambda: conn.business.update(published=True))
    assert conn.business == {'published': True}
    assert owner.pending_step(run=run, lease=lease) is None
    with pytest.raises(CompletionExecutionError, match='not_consumable'):
        owner.accept_result(run=run, lease=lease, step=step, batch=batch, dependencies={},
                            validate=lambda: None, consume=lambda: pytest.fail('duplicate consumer'))


def test_prepared_proven_not_sent_can_have_one_exact_successor():
    conn, run, lease, owner = setup_owner()
    batch, step = prepare(owner, run, lease)
    owner.mark_not_sent(run=run, lease=lease, step=step)
    successor = owner.prepare_step(run=run, lease=lease, batch=batch, step_key=step.step_key,
                                  kind=step.kind, request=step.request, dependencies=step.dependencies)
    assert successor.attempt_number == 2 and successor.decision_iteration == 1
    owner.mark_dispatched(run=run, lease=lease, step=successor)
    assert conn.batches[batch.id]['decision_count'] == 1
    owner.mark_unknown(run=run, lease=lease, step=successor)
    with pytest.raises(CompletionExecutionError, match='unresolved_attempt'):
        owner.prepare_step(run=run, lease=lease, batch=batch, step_key=step.step_key,
                           kind=step.kind, request=step.request, dependencies=step.dependencies)


def test_observable_http_is_appended_once_to_actual_current_batch():
    conn, run, lease, owner = setup_owner()
    batch, step = prepare(owner, run, lease)
    step = owner.mark_dispatched(run=run, lease=lease, step=step)
    owner.record_http_attempt(run=run, lease=lease, step=step, batch=batch)
    step = owner.record_result(run=run, lease=lease, step=step, result=final_result())
    conn.now += timedelta(seconds=2300)
    conn.run['active_lease_expires_at'] = conn.now + timedelta(seconds=30)
    successor = owner.ensure_batch(run=run, lease=lease, minimum_seconds=600)
    owner.record_http_attempt(run=run, lease=lease, step=step, batch=successor)
    assert conn.steps[step.id]['http_batch_ids_json'] == [batch.id, successor.id]
    assert [b['http_attempt_count'] for b in conn.batches.values()] == [1, 1]


class RowStore(InMemoryTutorRunStore):
    def __init__(self, conn, run):
        super().__init__([run])
        self.conn = conn

    def load_snapshot(self, run_id):
        snapshot = super().load_snapshot(run_id)
        return replace(snapshot, **{name: self.conn.run[name] for name in (
            'iteration_count', 'model_call_count', 'capability_call_count', 'effect_count')})

    def acquire_lease(self, run_id, *, owner_id, now, duration_seconds):
        lease = super().acquire_lease(run_id, owner_id=owner_id, now=now, duration_seconds=duration_seconds)
        if lease is not None:
            self.conn.run.update(active_lease_owner_id=owner_id, active_lease_generation=lease.generation,
                                 active_lease_expires_at=lease.expires_at)
        return lease

    def heartbeat_lease(self, lease, *, now, duration_seconds):
        if (self.conn.run['active_lease_owner_id'], self.conn.run['active_lease_generation']) != (lease.owner_id, lease.generation):
            return None
        renewed = replace(lease, expires_at=now + timedelta(seconds=duration_seconds))
        self._leases[lease.run_id] = renewed
        self.conn.run['active_lease_expires_at'] = renewed.expires_at
        return renewed


class OneToken:
    def estimate_tokens(self, value):
        return 1


class ReceiptLifecycle:
    def __init__(self, conn):
        self.conn = conn
        self.repo = object.__new__(PostgresTutorRepository)
        self.repo._conn = cast(Connection[dict[str, object]], conn)

    def persist_provider_attempts(self, **kwargs):
        self.repo.record_provider_attempts(**kwargs)

    def persist_terminal(self, *, result, **_kwargs):
        self.conn.business['terminal'] = result
        return result


class Provider:
    def __init__(self, conn, result):
        self.conn, self.result, self.calls = conn, result, 0

    def decide(self, *, run, context):
        assert self.conn.info.transaction_status == TransactionStatus.IDLE
        self.calls += 1
        execution = current_http_execution()
        assert execution is not None
        execution.before_send()
        execution.on_attempt(1)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def setup_loop(result):
    conn, run, _, owner = setup_owner()
    store = RowStore(conn, run)
    provider = Provider(conn, result)
    contexts = InMemoryTutorContextLoader({('run', 0): TutorContextInput('run', 'conversation', 0,
        current_input=TutorContextSource('message', '必要输入'), current_input_required=True)})
    lifecycle = ReceiptLifecycle(conn)
    loop = TutorRunLoop(store=store, context_loader=contexts,
        context_builder=TutorContextBuilder(estimator=OneToken()), provider=provider,
        capability_gateway=DefaultDenyCapabilityGateway(), effect_committer=DefaultDenyEffectCommitter(),
        clock=FixedClock(NOW), compaction_publisher=InMemoryTutorCompactionPublisher(),
        decision_gate=AllowTutorDecisionGate(), lifecycle=lifecycle, completion_owner=owner)
    return conn, loop, provider


@pytest.mark.parametrize('usage', [None, LLMUsage(input_tokens=20, cached_input_tokens=3, output_tokens=7, total_tokens=27)])
def test_loop_restores_original_usage_after_result_committed_before_receipt(usage):
    attempts = (TutorProviderAttemptReceipt(1, TutorProviderAttemptOutcome.ACCEPTED, 'test', 'responses', usage=usage),)
    conn, loop, provider = setup_loop(final_result(attempts=attempts))
    conn.commit_failure = ('SET state=%s,result_type=', True)
    first = loop.run(run_id='run', lease_owner_id='owner')
    assert first.diagnostic_code == 'completion_boundary_unconfirmed'
    assert len(conn.steps) == 1 and not conn.receipts
    second = loop.run(run_id='run', lease_owner_id='owner')
    assert second.terminal_outcome is TutorTerminalOutcome.COMPLETED
    assert provider.calls == 1 and len(conn.receipts) == 1
    assert second.model_call_count == 1
    receipt = conn.receipts[('run', 0, 1, 1)]
    assert receipt[-1] is (usage is not None)
    assert receipt[11:18] == ((20, 3, 17, 7, 27, 27, None) if usage else (None,) * 7)


@pytest.mark.parametrize('committed', [False, True])
def test_receipt_commit_unknown_replays_exact_receipt_identity_without_provider(committed):
    attempts = (TutorProviderAttemptReceipt(1, TutorProviderAttemptOutcome.ACCEPTED, 'test', 'responses'),)
    conn, loop, provider = setup_loop(final_result(attempts=attempts))
    conn.commit_failure = ('INSERT INTO tutor_provider_attempt_receipts', committed)
    first = loop.run(run_id='run', lease_owner_id='owner')
    assert first.diagnostic_code == 'completion_boundary_unconfirmed'
    assert first.capability_call_count == 0
    assert len(conn.receipts) == int(committed)
    result = loop.run(run_id='run', lease_owner_id='owner')
    assert result.terminal_outcome is TutorTerminalOutcome.COMPLETED
    assert len(conn.receipts) == 1 and provider.calls == 1


def test_loop_general_provider_exception_fences_dispatch_without_second_call():
    conn, loop, provider = setup_loop(RuntimeError('provider-private-text'))
    first = loop.run(run_id='run', lease_owner_id='owner')
    assert first.diagnostic_code == 'completion_boundary_unconfirmed'
    assert next(iter(conn.steps.values()))['state'] == 'dispatched'
    second = loop.run(run_id='run', lease_owner_id='owner')
    assert second.diagnostic_code == 'completion_outcome_unknown' and provider.calls == 1


def test_capability_receipt_recovery_never_reexecutes_side_effect_or_double_counts():
    request = TutorCapabilityRequest('stable-action', 'safe-capability')
    conn, loop, provider = setup_loop(TutorProviderResult(TutorDecision(
        capability_requests=(request,), terminal_outcome=TutorTerminalOutcome.COMPLETED)))
    class Gateway:
        calls = 0
        def dispatch(self, *, run, request):
            if request.request_id not in conn.actions:
                self.calls += 1
                conn.actions[request.request_id] = {'id': 'action', 'receipt_json': {'status': 'verified'}}
                raise CommitUnconfirmed('capability committed; acknowledgement lost')
            return TutorCapabilityResult(request.request_id, TutorCapabilityStatus.COMPLETED)
    gateway = Gateway()
    loop._capability_gateway = gateway
    first = loop.run(run_id='run', lease_owner_id='owner')
    assert first.diagnostic_code == 'completion_boundary_unconfirmed'
    assert first.capability_call_count == 1
    second = loop.run(run_id='run', lease_owner_id='owner')
    assert second.terminal_outcome is TutorTerminalOutcome.COMPLETED
    assert gateway.calls == provider.calls == 1 and second.capability_call_count == 1


def test_nested_action_without_terminal_receipt_is_unknown_and_not_replayed():
    request = TutorCapabilityRequest('stable-action', 'safe-capability')
    conn, loop, _ = setup_loop(TutorProviderResult(TutorDecision(capability_requests=(request,))))
    conn.actions['stable-action'] = {'id': 'active-action', 'receipt_json': None}
    result = loop.run(run_id='run', lease_owner_id='owner')
    assert result.diagnostic_code == 'completion_action_outcome_unknown'
    assert next(iter(conn.steps.values()))['state'] == 'result_recorded'
    assert not conn.business


def test_terminal_nested_http_unknown_receipt_is_not_mistaken_for_known_failure():
    request = TutorCapabilityRequest('stable-action', 'safe-capability')
    conn, loop, _ = setup_loop(TutorProviderResult(TutorDecision(capability_requests=(request,))))
    conn.actions['stable-action'] = {'id': 'unknown-action', 'receipt_json': {'status': 'permanent_failed'},
                                     'diagnostic_code': 'completion_http_unknown_transport_timeout'}
    assert loop.run(run_id='run', lease_owner_id='owner').diagnostic_code == 'completion_action_outcome_unknown'
    assert not conn.business


def test_effect_after_commit_recovers_receipt_and_preserves_monotonic_counter():
    proposal = TutorEffectProposal('stable-effect', 'save_note', 0)
    conn, loop, provider = setup_loop(TutorProviderResult(TutorDecision(
        effect_proposals=(proposal,), terminal_outcome=TutorTerminalOutcome.COMPLETED)))
    class Committer:
        calls = 0
        def commit(self, *, run, proposal):
            if 'effect' not in conn.business:
                self.calls += 1
                conn.business['effect'] = 'original-receipt'
                conn.run['effect_count'] += 1
                raise CommitUnconfirmed('effect committed; acknowledgement lost')
            return TutorEffectResult(proposal.effect_id, TutorEffectStatus.COMMITTED, 'original-receipt')
    committer = Committer()
    loop._effect_committer = committer
    first = loop.run(run_id='run', lease_owner_id='owner')
    assert first.diagnostic_code == 'completion_boundary_unconfirmed' and first.effect_count == 1
    assert conn.run['effect_count'] == 1
    second = loop.run(run_id='run', lease_owner_id='owner')
    assert second.terminal_outcome is TutorTerminalOutcome.COMPLETED
    assert second.effect_count == 1 and committer.calls == provider.calls == 1


def test_schema_has_only_two_scoped_tables_and_unknown_never_loses_exclusivity():
    sql = (Path(__file__).parents[2] / 'app/db/schema/596_tutor_completion_execution.sql').read_text(encoding='utf-8')
    assert sql.count('CREATE TABLE IF NOT EXISTS ') == 2
    assert "UNIQUE (id,run_id,user_id,conversation_id)" in sql
    assert 'runtime_planning_step_result_v1' in sql
    assert "'prepared','dispatched','result_recorded','outcome_unknown'" in sql
    assert "OLD.state IN ('accepted','rejected','not_sent','outcome_unknown')" in sql
    assert sql.count('tutor_learning_track_purge_allowed(OLD.user_id)') == 2
    assert 'completion fresh acceptance batch required' in sql
    assert 'completion cumulative counters cannot decrease' in sql
    assert 'http_batch_ids_json' in sql and 'http_attempt_count=http_attempt_count+1' in sql
    assert 'COMMIT;' not in sql
    assert "jsonb_path_exists(result_json, '$.nested_http_outcomes[*] ? (@.outcome_unknown == true)')" in sql


@pytest.mark.parametrize('name', ['tutor_completion_batch_timeout_seconds', 'tutor_completion_max_decisions',
                                'tutor_completion_max_http_requests', 'tutor_completion_result_reserve_seconds'])
def test_batch_settings_are_fixed_contract_not_silently_ignored_overrides(name):
    values = dict(tutor_completion_batch_timeout_seconds=2400, tutor_completion_max_decisions=8,
                  tutor_completion_max_http_requests=16, tutor_completion_result_reserve_seconds=60)
    validate_completion_batch_settings(SimpleNamespace(**values))
    values[name] -= 1
    with pytest.raises(CompletionExecutionError, match='batch_settings_unsupported'):
        validate_completion_batch_settings(SimpleNamespace(**values))
    with pytest.raises(CompletionExecutionError, match='batch_settings_unsupported'):
        completion_admission_policy(TutorPolicySnapshot(deadline=NOW), now=NOW, settings=SimpleNamespace(**values))


def test_changed_required_input_rejects_saved_result_but_still_restores_original_usage():
    attempts = (TutorProviderAttemptReceipt(1, TutorProviderAttemptOutcome.ACCEPTED, 'test', 'responses'),)
    conn, loop, provider = setup_loop(final_result(attempts=attempts))
    conn.commit_failure = ('SET state=%s,result_type=', True)
    loop.run(run_id='run', lease_owner_id='owner')
    loop._context_loader = InMemoryTutorContextLoader({('run', 0): TutorContextInput('run', 'conversation', 0,
        current_input=TutorContextSource('message', 'different required bytes'), current_input_required=True)})
    result = loop.run(run_id='run', lease_owner_id='owner')
    assert result.diagnostic_code == 'completion_dependencies_changed'
    assert len(conn.receipts) == 1 and provider.calls == 1
    assert next(iter(conn.steps.values()))['state'] == 'rejected'


@pytest.mark.parametrize('protocol', ['legacy_v1', 'thread_turn_v2'])
def test_rejected_continuation_consumer_rolls_back_step_acceptance(protocol):
    result = TutorProviderResult(TutorDecision(public_message='请提供输入。', continuation_kind=TutorContinuationKind.CLARIFICATION,
                                              checkpoint_reason=TutorCheckpointReason.CAPABILITY_RESULT))
    conn, loop, _ = setup_loop(result)
    original = loop._store._snapshots['run']
    loop._store._snapshots['run'] = replace(original, interaction_protocol_version=protocol)
    class Rejected(ReceiptLifecycle):
        def persist_interaction_request(self, *, result, **_kwargs):
            conn.business['partial'] = True
            return replace(result, status=TutorRunStatus.CANCELLED, terminal_outcome=TutorTerminalOutcome.CANCELLED, completion_reason=None)
        def persist_waiting_result(self, *, result, **_kwargs):
            conn.business['partial'] = True
            return replace(result, status=TutorRunStatus.CANCELLED, terminal_outcome=TutorTerminalOutcome.CANCELLED, continuation_kind=None)
    loop._lifecycle = Rejected(conn)
    outcome = loop.run(run_id='run', lease_owner_id='owner')
    assert outcome.diagnostic_code == 'completion_consumption_rejected'
    assert next(iter(conn.steps.values()))['state'] == 'result_recorded'
    assert not conn.business


def test_repeated_rebuild_without_progress_never_gets_another_model_call():
    conn, loop, provider = setup_loop(final_result())
    class Rebuild:
        def validate(self, **kwargs):
            return TutorDecisionGateResult(TutorDecisionGateStatus.REBUILD_CONTEXT)
    loop._decision_gate = Rebuild()
    result = loop.run(run_id='run', lease_owner_id='owner')
    assert result.diagnostic_code == 'completion_no_progress'
    assert provider.calls == 1 and len(conn.steps) == 1


@pytest.mark.parametrize('enabled', [False, True])
def test_primary_gateway_requires_explicit_profile_flag_and_sends_real_stage_arguments(enabled):
    _, run, _, _ = setup_owner()
    settings = Settings(llm_type='disabled', tutor_completion_driven_enabled=enabled,
                        tutor_default_context_window_tokens=65536, tutor_default_output_reserve_tokens=16384)
    class Client:
        model = 'offline-primary'
        calls = []
        def complete_json(self, messages, **kwargs):
            self.calls.append(kwargs)
            return LLMJsonResponse(content={
                'schema_version': TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
                'message': {'type': 'agent_message', 'text': '完成。', 'public_thinking_text': '完成当前检查。', 'conversation_title': None},
                'action': {'type': 'turn_completed'},
            }, model=self.model)
    client = Client()
    context = TutorContextBuilder(estimator=OneToken()).build(
        TutorContextInput('run', 'conversation', 0, current_input_required=True,
                          current_input=TutorContextSource('message', 'required input')), token_budget=100)
    result = PrimaryTutorProviderGateway(settings=settings, client=client).decide(run=run, context=context)
    if enabled:
        assert result.decision is not None
        assert len(client.calls) == 1
        assert client.calls[0]['completion_stage'] == 'tutor_decision'
        assert client.calls[0]['max_tokens'] == 16384
        assert client.calls[0]['timeout_seconds'] == 300
    else:
        assert result.safe_code == 'completion_feature_disabled' and client.calls == []


@pytest.mark.parametrize('nested_usage', [None, LLMUsage(input_tokens=9, output_tokens=2, total_tokens=11)])
@pytest.mark.parametrize('commit_unknown', [False, True])
def test_actual_material_consumer_unknown_survives_gateway_loop_and_private_owner(monkeypatch, nested_usage, commit_unknown):
    from app.services.learning import material_selection as material
    from app.services.learning.material_semantics import PrimaryMaterialSemanticReviewer
    from tests.tutor.test_tutor_plan_wire_contract import _arguments, _candidate, _valid_parts

    conn, loop, _ = setup_loop(final_result())
    settings = Settings(llm_type='disabled', tutor_completion_driven_enabled=True,
                        tutor_default_context_window_tokens=65536, tutor_default_output_reserve_tokens=16384)
    tutor_usage = LLMUsage(input_tokens=20, cached_input_tokens=3, output_tokens=7, total_tokens=27)
    payload = _candidate('learning.plan.draft', _arguments(_valid_parts()))
    class Client:
        model = 'original-tutor-model'
        def __init__(self):
            self.stages = []
        def complete_json(self, messages, **kwargs):
            assert conn.autocommit and conn.info.transaction_status == TransactionStatus.IDLE
            execution = current_http_execution()
            execution.before_send()
            execution.physical_attempts += 1
            execution.on_attempt(execution.physical_attempts)
            self.stages.append(kwargs['completion_stage'])
            if kwargs['completion_stage'] == 'tutor_decision':
                return LLMJsonResponse(content=payload, model=self.model, usage=tutor_usage)
            error = LLMHTTPExecutionError('transport_timeout', outcome_unknown=True,
                                          physical_attempts=execution.physical_attempts)
            error.model, error.usage = 'separate-semantic-model', nested_usage
            raise error
    client = Client()
    consumer = object.__new__(material.PostgresMaterialPlanningConsumer)
    consumer._conn = conn
    consumer._plans = SimpleNamespace(active_session_for_run=lambda **kwargs: {'current_draft_id': None},
                                      draft_for_session=lambda **kwargs: {})
    ref = SimpleNamespace(draft=SimpleNamespace(session_id='session', draft_id='parent'))
    selection = SimpleNamespace(selection_digest='a' * 64, handle='selection', draft=SimpleNamespace(content_hash='b' * 64))
    consumer._feedback = lambda run, session: (ref, selection)
    consumer._semantic_reviewer = PrimaryMaterialSemanticReviewer(settings, client)
    # Only pure fixture authority/plan reads are supplied. The actual consumer
    # still performs its own lease/revision checks, reservation and UNKNOWN path.
    monkeypatch.setattr(material, 'material_review_authority', lambda selection, parent: {'meaning': 'SQL filtering'})
    signals = []
    def validate_material(run, context, decision, attempt):
        try:
            return consumer.review_decision(run, decision, attempt)
        except material.MaterialSemanticReviewOutcomeUnknown as exc:
            signals.append(exc)
            raise
    gateway = PrimaryTutorProviderGateway(settings=settings, client=client).with_decision_validator(validate_material)
    loop._provider = gateway
    if commit_unknown:
        conn.commit_failure = ('SET state=%s,result_type=', True)
    result = loop.run(run_id='run', lease_owner_id='owner')
    assert result.diagnostic_code == ('completion_boundary_unconfirmed' if commit_unknown else 'completion_outcome_unknown')
    step_row = next(iter(conn.steps.values()))
    assert step_row['state'] == 'outcome_unknown'
    saved = decode_result(step_row['result_type'], step_row['result_json'])
    assert isinstance(saved, CompletionTutorProviderResult)
    assert saved.attempts[0].model == 'original-tutor-model' and saved.attempts[0].usage == tutor_usage
    assert saved.attempts[0].attempt_index == 1
    assert saved.nested_http_outcomes[0].model == 'separate-semantic-model'
    assert saved.nested_http_outcomes[0].usage == nested_usage
    assert saved.nested_http_outcomes[0].current_scope_http_attempts == 2
    assert len(signals) == 1 and signals[0].outcome_unknown and not signals[0].from_dispatched_receipt
    assert saved.nested_http_outcomes[0].request_binding_hash == signals[0].request_binding_hash
    assert ('run', 0, step_row['decision_iteration'], 1) in conn.material_reviews
    assert step_row['observable_http_count'] == 2
    assert next(iter(conn.batches.values()))['http_attempt_count'] == 2
    loop.run(run_id='run', lease_owner_id='owner')
    assert client.stages == ['tutor_decision', 'material_semantic_review']
    assert len(conn.material_reviews) == len(conn.receipts) == 1
    assert conn.receipts[('run', 0, 1, 1)][11:18] == (20, 3, 17, 7, 27, 27, None)
    assert next(iter(conn.material_reviews.values()))['review_status'] == 'dispatched'
    # The actual cold same-binding consumer also emits its typed UNKNOWN without
    # requiring a reviewer. A current-scope zero is not a historical HTTP zero.
    from app.services.tutor.decision_protocol import parse_tutor_provider_items
    consumer._semantic_reviewer = None
    cold = replace(loop._store.load_snapshot('run'), model_call_count=step_row['decision_iteration'] - 1,
                   lease=TutorLease('run', 'owner', conn.run['active_lease_expires_at'], conn.run['active_lease_generation']))
    with pytest.raises(material.MaterialSemanticReviewOutcomeUnknown) as cold_stop:
        consumer.review_decision(cold, parse_tutor_provider_items(payload, run=cold), 1)
    assert cold_stop.value.from_dispatched_receipt and cold_stop.value.physical_attempts == 0
    assert cold_stop.value.request_binding_hash == saved.nested_http_outcomes[0].request_binding_hash
    assert client.stages == ['tutor_decision', 'material_semantic_review']
    assert step_row['observable_http_count'] == 2 and len(conn.material_reviews) == 1


def test_owner_never_downgrades_typed_nested_unknown_if_caller_omits_boolean():
    conn, run, lease, owner = setup_owner()
    batch, step = prepare(owner, run, lease)
    step = owner.mark_dispatched(run=run, lease=lease, step=step)
    result = CompletionTutorProviderResult(decision=None, terminal_outcome=TutorTerminalOutcome.MODEL_UNAVAILABLE,
        nested_http_outcomes=(CompletionNestedHTTPOutcome('material_semantic_review', 'a' * 64, 0, True, None, None),))
    saved = owner.record_result(run=run, lease=lease, step=step, result=result)
    assert saved.state == 'outcome_unknown' and saved.result == result
    with pytest.raises(CompletionExecutionError, match='not_consumable'):
        owner.accept_result(run=run, lease=lease, step=saved, batch=batch, dependencies={},
                            validate=lambda: None, consume=lambda: pytest.fail('UNKNOWN consumed'))
