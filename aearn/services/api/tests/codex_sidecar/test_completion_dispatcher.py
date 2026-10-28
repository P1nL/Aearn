"""Dispatcher CPU tests with the real completion owner and codec, no PostgreSQL.

The small SQL connection is a transaction/state transcript, not a substitute for
SQL596/598 trigger or independent-connection acceptance (owned by Main).
"""
from __future__ import annotations

import asyncio
import copy
import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from psycopg.pq import TransactionStatus

from app.agents.harness.contracts import (
    TutorExecutionProfile, TutorLease, TutorPolicySnapshot, TutorRunSnapshot,
    TutorRunStatus, TutorTerminalOutcome,
)
from app.agents.runtime import learning_plan_tools as tool_module
from app.agents.runtime.contracts import (
    RuntimeEvent, RuntimeEventKind, RuntimeHealthSnapshot, RuntimeHealthStatus,
    RuntimePlanningStepResult, RuntimeTerminalStatus, RuntimeThreadHandle, RuntimeTurnResult,
)
from app.core.config import Settings
from app.services.tutor import codex_dispatcher as dispatcher_module
from app.services.tutor.codex_dispatcher import CodexTutorRunDispatcher
from app.services.tutor.completion_execution import (
    CompletionExecutionError, decode_result, encode_result,
)
from app.services.learning.plan_tools import LearningPlanToolStatus
from tests.codex_sidecar.test_codex_learning_plan_tools import FakeService, _call, _result, _valid_modules


class Rows:
    def __init__(self, row=None):
        self.row = copy.deepcopy(row)

    def fetchone(self):
        return self.row


class CpuConnection:
    """Only the SQL branches actually used by the production owner, fail closed."""
    def __init__(self):
        self.now = datetime.now(UTC)
        self.autocommit = True
        self.info = SimpleNamespace(transaction_status=TransactionStatus.IDLE)
        self.depth = 0
        self.commits = 0
        self.run = dict(
            id="run", user_id="user", conversation_id="conversation", input_revision=1,
            policy_json={"execution_profile": "completion_driven_v1"},
            policy_version="tutor_completion_driven_v1", policy_fingerprint="policy",
            active_lease_owner_id="owner", active_lease_generation=1,
            active_lease_expires_at=self.now + timedelta(hours=2), terminal_outcome=None,
            cancelled_at=None, superseded_by_run_id=None, model_call_count=0,
            iteration_count=0, capability_call_count=0, effect_count=0,
        )
        self.batches = []
        self.steps = []
        self.bindings = []
        self.calls = []
        self.stop_after_record = False

    @contextmanager
    def transaction(self):
        before = copy.deepcopy((self.run, self.batches, self.steps, self.bindings))
        self.depth += 1
        self.info.transaction_status = TransactionStatus.INTRANS
        try:
            yield
        except BaseException:
            self.run, self.batches, self.steps, self.bindings = before
            raise
        else:
            self.commits += 1
        finally:
            self.depth -= 1
            self.info.transaction_status = TransactionStatus.INTRANS if self.depth else TransactionStatus.IDLE

    def execute(self, statement, params=()):
        sql = " ".join(statement.split())
        self.calls.append((sql, params))
        if sql == "SELECT clock_timestamp() AS now":
            return Rows({"now": self.now})
        if sql.startswith("SELECT * FROM tutor_runs"):
            return Rows(self.run)
        if sql.startswith("SELECT * FROM tutor_run_execution_batches"):
            return Rows(self.batches[-1] if self.batches else None)
        if sql.startswith("SELECT id FROM tutor_run_step_attempts"):
            return Rows(next((s for s in self.steps if s["state"] in {"prepared", "dispatched", "outcome_unknown"}), None))
        if sql.startswith("INSERT INTO tutor_run_execution_batches"):
            names = ("run_id", "user_id", "conversation_id", "input_revision", "predecessor_batch_id",
                     "batch_index", "owner_id", "owner_generation", "policy_fingerprint", "issued_at", "expires_at")
            row = dict(zip(names, params, strict=True), id=str(uuid4()), decision_count=0, http_attempt_count=0)
            self.batches.append(row)
            return Rows(row)
        if sql.startswith("SELECT * FROM tutor_run_step_attempts"):
            if "WHERE id=" in sql:
                found = next((s for s in self.steps if s["id"] == params[0]), None)
            elif "step_key=" in sql:
                found = next((s for s in reversed(self.steps) if s["step_key"] == params[1]), None)
            else:
                found = next((s for s in self.steps if s["state"] in {"prepared", "dispatched", "result_recorded", "outcome_unknown"}), None)
            return Rows(found)
        if sql.startswith("INSERT INTO tutor_run_step_attempts"):
            names = ("run_id", "user_id", "conversation_id", "input_revision", "batch_id", "step_key", "kind",
                     "decision_iteration", "attempt_number", "predecessor_attempt_id", "owner_id", "owner_generation",
                     "request_json", "dependencies_json", "capability_count_before", "effect_count_before", "prepared_at")
            row = dict(zip(names, params, strict=True), id=str(uuid4()), state="prepared", observable_http_count=0,
                       result_type=None, result_json=None)
            row["request_json"] = json.loads(row["request_json"])
            row["dependencies_json"] = json.loads(row["dependencies_json"])
            self.steps.append(row)
            return Rows(row)
        if sql.startswith("UPDATE tutor_run_step_attempts"):
            row = next(s for s in self.steps if s["id"] == params[-1])
            if "SET state='dispatched'" in sql:
                row["state"] = "dispatched"
                next(b for b in self.batches if b["id"] == row["batch_id"])["decision_count"] += 1
            elif "SET state=%s,result_type=" in sql:
                row.update(state=params[0], result_type=params[1], result_json=json.loads(params[2]))
            elif "SET state='accepted'" in sql:
                row.update(state="accepted", accepted_owner_id=params[0], accepted_owner_generation=params[1],
                           acceptance_batch_id=params[2])
            elif "SET state='not_sent'" in sql:
                row["state"] = "not_sent"
            elif "SET state='outcome_unknown'" in sql:
                row["state"] = "outcome_unknown"
            else:
                raise AssertionError(sql)
            return Rows(row)
        if sql.startswith("UPDATE tutor_runs SET model_call_count="):
            self.run["model_call_count"] = max(self.run["model_call_count"], params[0])
            self.run["iteration_count"] = max(self.run["iteration_count"], params[1])
            return Rows()
        if sql.startswith("UPDATE tutor_runs SET capability_call_count="):
            self.run["capability_call_count"] = max(self.run["capability_call_count"], params[0])
            self.run["effect_count"] = max(self.run["effect_count"], params[1])
            return Rows()
        if sql.startswith("SELECT result_type, result_json FROM tutor_run_step_attempts"):
            return Rows(next((s for s in reversed(self.steps) if s["state"] == "accepted"), None))
        if sql.startswith("SELECT * FROM tutor_run_runtime_bindings WHERE step_attempt_id="):
            if self.stop_after_record:
                self.stop_after_record = False
                raise RuntimeError("crash after durable result")
            return Rows(next((b for b in self.bindings if b["step_attempt_id"] == params[0]), None))
        if sql.startswith("SELECT content FROM tutor_run_inputs"):
            return Rows({"content": "Learn Python"})
        raise AssertionError(sql)


class Repository:
    def __init__(self, conn):
        self.conn = conn

    def load_snapshot(self, **_):
        r = self.conn.run
        return TutorRunSnapshot(
            run_id=r["id"], user_id=r["user_id"], conversation_id=r["conversation_id"], input_revision=1,
            origin="interactive", status=TutorRunStatus.COMPLETED if r["terminal_outcome"] else TutorRunStatus.RUNNING,
            runtime_kind="codex_sidecar_v1", interaction_protocol_version="thread_turn_v2",
            policy=TutorPolicySnapshot(deadline=self.conn.now + timedelta(seconds=2400),
                                       execution_profile=TutorExecutionProfile.COMPLETION_DRIVEN_V1),
            **{k: r[k] for k in ("iteration_count", "model_call_count", "capability_call_count", "effect_count")},
        )

    def read_run_state(self, **_):
        return SimpleNamespace(snapshot=self.load_snapshot(), terminal_outcome=self.conn.run["terminal_outcome"],
                               completion_reason=None, diagnostic_code=None)


class Projection:
    """Dispatcher projection port; actual projection gates have separate CPU tests."""
    def __init__(self, conn):
        self.conn = conn

    def active_conversation_thread(self, **_):
        return SimpleNamespace(external_thread_id="thread", thread_binding_id="conversation-thread")

    def mark_conversation_thread_resumed(self, **_):
        pass

    def bind_run(self, **kwargs):
        assert not any(b["state"] == "running" for b in self.conn.bindings)
        row = dict(id=str(uuid4()), state="running", step_attempt_id=kwargs["step_attempt_id"], connection_generation=1)
        self.conn.bindings.append(row)
        return SimpleNamespace(binding_id=row["id"])

    def project(self, *, binding_id, event, complete_business_run=False, **_):
        row = next(b for b in self.conn.bindings if b["id"] == binding_id)
        if event.kind == "turn_completed":
            row["state"] = event.terminal_status
            if complete_business_run:
                assert self.conn.depth > 0
                assert next(s for s in self.conn.steps if s["id"] == row["step_attempt_id"])["state"] == "accepted"
                self.conn.run["terminal_outcome"] = TutorTerminalOutcome.COMPLETED
        return SimpleNamespace(projection_status=SimpleNamespace(value="applied"), projection_sequence=event.sequence,
                               source_delta_count=1)


class Service(FakeService):
    def __init__(self):
        super().__init__(
            _result(LearningPlanToolStatus.COMPLETED, "planning_context_ready",
                    data={"facts_fingerprint": "facts", "facts_revision": 1}),
            _result(LearningPlanToolStatus.COMPLETED, "learning_plan_draft_completed",
                    data={"content_hash": "draft-hash"}),
        )
        self.saved = None

    def draft(self, tool_input):
        self.saved = super().draft(tool_input)
        return self.saved

    def recover_committed_draft(self):
        return self.saved


class Host:
    def __init__(self, conn):
        self.conn = conn
        self.turns = 0
        self.resumes = 0

    def health_snapshot(self, **_):
        return RuntimeHealthSnapshot(RuntimeHealthStatus.READY, 1, version="cpu-version")

    def current_generation(self):
        return 1

    def resume_thread(self, thread_id, **_):
        self.resumes += 1
        return RuntimeThreadHandle(thread_id, 1)

    def run_turn(self, request, *, event_observer, **_):
        assert self.conn.depth == 0
        assert self.conn.steps[-1]["state"] == "dispatched"
        assert request.completion_driven
        assert request.timeout_seconds == 900
        self.turns += 1
        registry = request.tools
        if self.turns == 1:
            assert asyncio.run(registry.invoke(_call("aearn_planning_context_read", {}))).success
            assert asyncio.run(registry.invoke(_call("aearn_planning_context_read", {"direction_action": "continue_mainline"}))).success
            assert asyncio.run(registry.invoke(_call("aearn_learning_plan_draft", {"modules": _valid_modules()}))).success
        else:
            assert registry.draft_completed
        turn_id = f"turn-{self.turns}"
        events = [RuntimeEvent(RuntimeEventKind.TURN_STARTED, "thread", turn_id)]
        if self.turns > 1:
            events.append(RuntimeEvent(RuntimeEventKind.MESSAGE_COMPLETED, "thread", turn_id,
                                       item_id="answer", visible_text="计划草案已准备好，请确认。", phase="final_answer"))
        events.append(RuntimeEvent(RuntimeEventKind.TURN_COMPLETED, "thread", turn_id,
                                   terminal_status=RuntimeTerminalStatus.COMPLETED))
        events = tuple(replace(event, sequence=i) for i, event in enumerate(events, 1))
        for event in events:
            event_observer(event, event.sequence)
        return RuntimeTurnResult(request.thread, turn_id, RuntimeTerminalStatus.COMPLETED, events)


@pytest.fixture
def cpu_dispatcher(monkeypatch):
    conn = CpuConnection()
    service = Service()
    host = Host(conn)
    repository = Repository(conn)
    fence = SimpleNamespace(facts_fingerprint="facts", facts_revision=1)
    monkeypatch.setattr(tool_module, "build_expected_learning_plan_tool_fence", lambda *a, **kw: fence)
    monkeypatch.setattr(tool_module, "PostgresLearningPlanToolFence", lambda *a, **kw: object())
    monkeypatch.setattr(tool_module, "LearningPlanToolService", lambda *a, **kw: service)
    monkeypatch.setattr(dispatcher_module, "build_expected_learning_plan_tool_fence", lambda *a, **kw: fence)
    monkeypatch.setattr(dispatcher_module, "PostgresTutorRuntimeProjectionRepository", Projection)
    monkeypatch.setattr(dispatcher_module, "_read_input_text", lambda *a, **kw: "Learn Python")
    monkeypatch.setattr(dispatcher_module, "_record_completed_draft_direction_receipt", lambda *a, **kw: None)
    dispatcher = CodexTutorRunDispatcher(settings=Settings(tutor_completion_driven_enabled=True), host=host)
    return conn, repository, host, service, dispatcher


def _dispatch(cpu):
    conn, repository, _host, _service, dispatcher = cpu
    run = repository.load_snapshot()
    lease = TutorLease(run.run_id, conn.run["active_lease_owner_id"], conn.run["active_lease_expires_at"],
                       generation=conn.run["active_lease_generation"])
    return dispatcher._dispatch_completion(conn=conn, repository=repository, run=run, lease=lease)


def test_real_dispatcher_two_native_steps_one_run_no_fabricated_http(cpu_dispatcher):
    conn, _repo, host, service, _dispatcher = cpu_dispatcher
    result = _dispatch(cpu_dispatcher)
    assert result.run_id == "run"
    assert result.terminal_outcome is TutorTerminalOutcome.COMPLETED
    assert result.model_call_count == 2  # Logical native decisions, not HTTP count.
    assert result.capability_call_count == 3  # Cold registry rebuild never clears committed tool usage.
    assert host.turns == 2 and service.draft_calls == 1
    assert [s["state"] for s in conn.steps] == ["accepted", "accepted"]
    assert all(s["observable_http_count"] == 0 for s in conn.steps)
    assert all(b["http_attempt_count"] == 0 for b in conn.batches)
    assert all(decode_result(s["result_type"], s["result_json"]).model_http_request_count is None for s in conn.steps)


def test_cold_result_recovery_uses_fresh_batch_without_resending_model_or_draft(cpu_dispatcher):
    conn, _repo, host, service, _dispatcher = cpu_dispatcher
    conn.stop_after_record = True
    with pytest.raises(RuntimeError, match="crash after durable result"):
        _dispatch(cpu_dispatcher)
    assert conn.steps[0]["state"] == "result_recorded"
    old_batch = conn.steps[0]["batch_id"]
    conn.batches[0]["expires_at"] = conn.now - timedelta(seconds=1)
    conn.run.update(active_lease_owner_id="fresh-owner", active_lease_generation=2)
    result = _dispatch(cpu_dispatcher)
    assert result.terminal_outcome is TutorTerminalOutcome.COMPLETED
    assert host.turns == 2 and service.draft_calls == 1
    assert conn.steps[0]["acceptance_batch_id"] != old_batch
    assert conn.steps[0]["accepted_owner_id"] == "fresh-owner"
    assert len(conn.steps) == 2


@pytest.mark.parametrize("state", ["dispatched", "outcome_unknown"])
def test_unresolved_native_step_refuses_any_resend(cpu_dispatcher, state):
    conn, _repo, host, service, _dispatcher = cpu_dispatcher
    conn.stop_after_record = True
    with pytest.raises(RuntimeError):
        _dispatch(cpu_dispatcher)
    conn.steps[0]["state"] = state
    turns = host.turns
    resumes = host.resumes
    with pytest.raises(CompletionExecutionError, match="completion_unresolved_attempt"):
        _dispatch(cpu_dispatcher)
    assert host.turns == turns and host.resumes == resumes and service.draft_calls == 1


def test_private_native_codec_roundtrip_preserves_result_not_fake_run_terminal():
    native = RuntimeTurnResult(RuntimeThreadHandle("thread", 1), "turn", RuntimeTerminalStatus.COMPLETED, ())
    result = RuntimePlanningStepResult(native, {"direction_action": "continue_mainline"}, (), 0, 0)
    kind, payload = encode_result(result)
    assert kind == "runtime_planning_step_result_v1"
    assert decode_result(kind, json.loads(payload)) == result
    assert "terminal_outcome" not in json.loads(payload)


@pytest.mark.parametrize("missing", [True, False])
def test_recorded_draft_missing_or_changed_blocks_cold_recovery_without_replay(cpu_dispatcher, missing):
    conn, _repo, host, service, _dispatcher = cpu_dispatcher
    conn.stop_after_record = True
    with pytest.raises(RuntimeError, match="crash after durable result"):
        _dispatch(cpu_dispatcher)
    service.saved = None if missing else service.saved.model_copy(update={"data": {"content_hash": "other-draft"}})
    with pytest.raises(ValueError, match="learning_plan_saved_result_stale"):
        _dispatch(cpu_dispatcher)
    assert host.turns == 1 and service.draft_calls == 1
    assert conn.steps[0]["state"] == "result_recorded"


def test_rejected_business_consumption_rolls_back_step_acceptance(cpu_dispatcher, monkeypatch):
    conn, _repo, host, _service, dispatcher = cpu_dispatcher
    conn.stop_after_record = True
    with pytest.raises(RuntimeError):
        _dispatch(cpu_dispatcher)
    # Force the final consumption after known DATA to return a nonterminal run.
    monkeypatch.setattr(dispatcher_module, "_completion_should_continue", lambda *a: False)
    from app.agents.harness.contracts import TutorRunResult
    monkeypatch.setattr(dispatcher, "_finish_runtime_result", lambda **kw: TutorRunResult(
        "run", TutorRunStatus.RUNNING, 1, 1, 1, 3, 0))
    with pytest.raises(CompletionExecutionError, match="completion_sidecar_acceptance_rejected"):
        _dispatch(cpu_dispatcher)
    assert conn.steps[0]["state"] == "result_recorded"
    assert "acceptance_batch_id" not in conn.steps[0]
    assert host.turns == 1


def test_legacy_binding_recovery_does_not_enter_completion_owner_or_resend(cpu_dispatcher, monkeypatch):
    conn, repository, host, _service, _dispatcher = cpu_dispatcher
    lease = TutorLease("run", "owner", conn.run["active_lease_expires_at"])
    original_snapshot = repository.load_snapshot()
    legacy = replace(original_snapshot, policy=replace(original_snapshot.policy, execution_profile=None), lease=lease)
    monkeypatch.setattr(repository, "load_snapshot", lambda **kw: legacy)
    monkeypatch.setattr(repository, "acquire_lease", lambda **kw: lease, raising=False)
    monkeypatch.setattr(dispatcher_module, "PostgresTutorRepository", lambda c: repository)
    from app.services.learning.contracts import LearningScopeKind
    monkeypatch.setattr(dispatcher_module, "PostgresLearningTrackRepository", lambda c: SimpleNamespace(
        read_run_scope=lambda **kw: SimpleNamespace(scope_kind=LearningScopeKind.PLAN_DRAFTING)))

    class LegacyProjection:
        def next_event_sequence(self, **kw):
            return 12

        def project(self, *, event, **kw):
            assert event.sequence == 12
            assert event.safe_code == "runtime_dispatch_recovered"
            conn.run["terminal_outcome"] = TutorTerminalOutcome.MODEL_UNAVAILABLE

    monkeypatch.setattr(dispatcher_module, "PostgresTutorRuntimeProjectionRepository", lambda c: LegacyProjection())
    execute = conn.execute
    def legacy_execute(sql, params=()):
        if sql == "SELECT * FROM tutor_run_runtime_bindings WHERE run_id = %s":
            return Rows(dict(id="legacy-binding", external_thread_id="thread", external_turn_id="turn", connection_generation=1))
        return execute(sql, params)
    monkeypatch.setattr(conn, "execute", legacy_execute)
    def forbidden_owner(*args):
        raise AssertionError("legacy must not construct a completion owner")
    monkeypatch.setattr(dispatcher_module, "CompletionExecutionOwner", forbidden_owner)
    from contextlib import nullcontext
    dispatcher = CodexTutorRunDispatcher(settings=Settings(), host=host, connection_factory=lambda: nullcontext(conn))
    result = dispatcher.dispatch(user_id="user", run_id="run")
    assert result.terminal_outcome is TutorTerminalOutcome.MODEL_UNAVAILABLE
    assert host.turns == host.resumes == 0
    assert not conn.steps and not conn.batches



def test_actual_dispatcher_typed_question_finishes_only_through_original_owner(cpu_dispatcher, monkeypatch):
    conn, repository, host, service, _dispatcher = cpu_dispatcher
    from app.agents.runtime.learning_plan_tools import LearningPlanRuntimeToolRegistry
    from app.agents.harness.contracts import TutorTurnCompletionReason
    from tests.codex_sidecar.test_codex_learning_plan_tools import _awaiting_data
    service.read_result = _result(LearningPlanToolStatus.AWAITING_USER, "planning_facts_missing",
                                  data={**_awaiting_data("goal_text"), "facts_fingerprint": "facts", "facts_revision": 1})
    typed = []
    asked = []
    monkeypatch.setattr(dispatcher_module, "PostgresPlanningFactRepository", lambda c: SimpleNamespace(
        record_question_asked=lambda **kw: asked.append(kw)))
    monkeypatch.setattr(dispatcher_module, "_planning_facts_fingerprint", lambda *a, **kw: "facts")
    monkeypatch.setattr(repository, "record_planning_direction_resolution", lambda **kw: None, raising=False)
    def record_request(**kwargs):
        assert conn.depth > 0 and conn.steps[0]["state"] == "accepted"
        typed.append(kwargs["result"])
        conn.run["terminal_outcome"] = TutorTerminalOutcome.COMPLETED
    monkeypatch.setattr(repository, "record_interaction_request", record_request, raising=False)
    execute = conn.execute
    def typed_execute(sql, params=()):
        if sql.startswith("SELECT tutor_message_id FROM tutor_run_public_processes"):
            return Rows({"tutor_message_id": "typed-message"})
        return execute(sql, params)
    monkeypatch.setattr(conn, "execute", typed_execute)

    class TypedProjection(Projection):
        def discard_streaming_text_items_for_server_terminalization(self, **kwargs):
            assert conn.steps[0]["state"] == "accepted"

        def finalize_typed_request_binding(self, **kwargs):
            assert kwargs["message_id"] == "typed-message"
            conn.bindings[0].update(state="completed", final_message_id="typed-message")

    monkeypatch.setattr(dispatcher_module, "PostgresTutorRuntimeProjectionRepository", TypedProjection)
    def typed_turn(request, *, event_observer, **kwargs):
        assert conn.depth == 0
        assert isinstance(request.tools, LearningPlanRuntimeToolRegistry)
        assert request.tools.intake_mode
        host.turns += 1
        assert asyncio.run(request.tools.invoke(_call("aearn_planning_context_read", {}))).success
        assert asyncio.run(request.tools.invoke(_call("aearn_planning_context_read", {"direction_action": "continue_mainline"}))).success
        events = (
            RuntimeEvent(RuntimeEventKind.TURN_STARTED, "thread", "typed-turn", sequence=1),
            RuntimeEvent(RuntimeEventKind.TURN_COMPLETED, "thread", "typed-turn", sequence=2,
                         terminal_status=RuntimeTerminalStatus.COMPLETED),
        )
        for event in events:
            event_observer(event, event.sequence)
        return RuntimeTurnResult(request.thread, "typed-turn", RuntimeTerminalStatus.COMPLETED, events)
    monkeypatch.setattr(host, "run_turn", typed_turn)
    result = _dispatch(cpu_dispatcher)
    assert result.terminal_outcome is TutorTerminalOutcome.COMPLETED
    assert typed[0].completion_reason is TutorTurnCompletionReason.AWAITING_USER
    assert typed[0].model_call_count == 1 and typed[0].capability_call_count == 2
    assert typed[0].public_message and len(asked) == 1
    assert host.turns == 1 and service.draft_calls == 0



def test_cold_registry_preserves_protocol_rejection_instead_of_restoring_write_rights(cpu_dispatcher):
    conn, repository, _host, service, _dispatcher = cpu_dispatcher
    from app.agents.runtime.learning_plan_tools import LearningPlanRuntimeToolRegistry
    registry = LearningPlanRuntimeToolRegistry.from_postgres(
        conn, run=repository.load_snapshot(), runtime_generation=1, runtime_generation_reader=lambda: 1)
    asyncio.run(registry.invoke(_call("aearn_planning_context_read", {})))
    asyncio.run(registry.invoke(_call("aearn_planning_context_read", {"direction_action": "continue_mainline"})))
    asyncio.run(registry.invoke(_call("aearn_learning_plan_draft", {"modules": _valid_modules()})))
    # A duplicate direction after committing the draft invalidates the protocol.
    asyncio.run(registry.invoke(_call("aearn_planning_context_read", {"direction_action": "continue_mainline"})))
    assert registry.direction_protocol_invalid and not registry.draft_completed
    assert registry.continuation_state["direction_protocol_invalid"] is True
    recovered = LearningPlanRuntimeToolRegistry.from_postgres(
        conn, run=repository.load_snapshot(), runtime_generation=1, runtime_generation_reader=lambda: 1,
        committed_state=registry.continuation_state, recover_committed_draft=True)
    assert recovered.direction_protocol_invalid and not recovered.draft_completed
    assert recovered.planning_direction_action is None
    assert service.draft_calls == 1


@pytest.mark.parametrize("guard", ["calls", "repairs", "conflicts"])
def test_continuation_keeps_original_tool_guards_without_new_write_rights(cpu_dispatcher, guard):
    from app.agents.runtime.learning_plan_tools import LearningPlanRuntimeToolRegistry, LearningPlanToolBudget
    conn, repository, _host, service, _dispatcher = cpu_dispatcher
    budget = LearningPlanToolBudget(max_calls=3 if guard == "calls" else 6, max_repairs=1)
    registry = LearningPlanRuntimeToolRegistry.from_postgres(
        conn, run=repository.load_snapshot(), runtime_generation=1, runtime_generation_reader=lambda: 1,
        budget=budget)
    asyncio.run(registry.invoke(_call("aearn_planning_context_read", {})))
    asyncio.run(registry.invoke(_call("aearn_planning_context_read", {"direction_action": "continue_mainline"})))
    if guard == "calls":
        arguments = {"modules": _valid_modules()}
    elif guard == "repairs":
        arguments = {"modules": []}
    else:
        arguments = {"modules": _valid_modules()}
        service.draft_result = _result(LearningPlanToolStatus.CONFLICT, "learning_plan_draft_conflict")
    asyncio.run(registry.invoke(_call("aearn_learning_plan_draft", arguments)))
    checkpoint = registry.continuation_state
    recovered = LearningPlanRuntimeToolRegistry.from_postgres(
        conn, run=repository.load_snapshot(), runtime_generation=1, runtime_generation_reader=lambda: 1,
        committed_state=checkpoint, recover_committed_draft=guard == "calls", budget=budget)
    # Cumulative guards survive, but this step has not charged a new invocation.
    assert recovered.call_count == recovered.repair_count == 0
    result = asyncio.run(recovered.invoke(_call("aearn_learning_plan_draft", arguments)))
    assert result.safe_code == {
        "calls": "tool_call_budget_exhausted", "repairs": "tool_repair_budget_exhausted",
        "conflicts": "tool_conflict_budget_exhausted",
    }[guard]
    assert recovered.continuation_state["tool_call_count"] >= checkpoint["tool_call_count"]
    assert service.draft_calls == (2 if guard == "conflicts" else 1 if guard == "calls" else 0)


def test_recovered_draft_callback_rechecks_current_original_owner(cpu_dispatcher):
    from app.agents.runtime.learning_plan_tools import LearningPlanRuntimeToolRegistry
    conn, repository, _host, service, _dispatcher = cpu_dispatcher
    registry = LearningPlanRuntimeToolRegistry.from_postgres(
        conn, run=repository.load_snapshot(), runtime_generation=1, runtime_generation_reader=lambda: 1)
    asyncio.run(registry.invoke(_call("aearn_planning_context_read", {})))
    asyncio.run(registry.invoke(_call("aearn_planning_context_read", {"direction_action": "continue_mainline"})))
    asyncio.run(registry.invoke(_call("aearn_learning_plan_draft", {"modules": _valid_modules()})))
    recovered = LearningPlanRuntimeToolRegistry.from_postgres(
        conn, run=repository.load_snapshot(), runtime_generation=1, runtime_generation_reader=lambda: 1,
        committed_state=registry.continuation_state, recover_committed_draft=True)
    service.saved = _result(LearningPlanToolStatus.CONFLICT, "tool_input_revision_stale")
    result = asyncio.run(recovered.invoke(_call("aearn_learning_plan_draft", {"modules": _valid_modules()})))
    assert result.safe_code == "tool_input_revision_stale"
    assert service.draft_calls == 1  # No append/regeneration, nor stale success from a cached receipt.



def test_new_input_during_native_turn_cannot_accept_old_result_or_send_next_step(cpu_dispatcher, monkeypatch):
    conn, _repository, host, service, _dispatcher = cpu_dispatcher
    original_turn = host.run_turn
    def input_changes(*args, **kwargs):
        result = original_turn(*args, **kwargs)
        conn.run["input_revision"] = 2
        return result
    monkeypatch.setattr(host, "run_turn", input_changes)
    with pytest.raises(CompletionExecutionError, match="completion_current_owner_required"):
        _dispatch(cpu_dispatcher)
    assert conn.steps[0]["state"] == "result_recorded"  # Late original DATA only.
    assert conn.steps[0].get("acceptance_batch_id") is None
    assert host.turns == service.draft_calls == len(conn.steps) == 1
