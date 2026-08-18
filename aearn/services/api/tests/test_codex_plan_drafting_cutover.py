from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Iterator
from uuid import uuid4

import pytest

import app.services.tutor.interactive as interactive_module
from app.agents.harness.contracts import (
    TutorPolicySnapshot,
    TutorRunResult,
    TutorRunStatus,
    TutorTerminalOutcome,
)
from app.agents.runtime.contracts import (
    RuntimeEvent,
    RuntimeEventKind,
    RuntimeHealthSnapshot,
    RuntimeHealthStatus,
    RuntimeInput,
    RuntimeTerminalStatus,
    RuntimeThreadHandle,
    RuntimeThreadRequest,
    RuntimeTurnRequest,
    RuntimeTurnResult,
)
from app.agents.runtime.worker_host import (
    RuntimeTurnControlDirective,
    _run_controlled_turn,
)
from app.core.config import DEEPSEEK_V4_FLASH_MODEL, Settings
from app.services.learning.contracts import LearningScope, LearningScopeKind
from app.services.learning.plan_repository import PostgresLearningPlanSessionRepository
from app.services.learning.track_repository import PostgresLearningTrackRepository
from app.services.tutor.codex_dispatcher import CodexTutorRunDispatcher
from app.services.tutor.interactive import TutorRuntimeDispatchRouter
from app.services.tutor.persistence import PostgresTutorRepository
from app.services.tutor.public_api import TutorPublicApiError, TutorPublicService
from app.services.tutor.queue_control import PostgresTutorQueueController
from app.services.tutor.runtime_selection import (
    PostgresTutorCodexRuntimeReadinessRepository,
    TutorCodexRuntimeUnavailable,
    TutorRuntimeSelectionPolicy,
)


_NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
_VERSION = "0.142.0-cometix"


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "codex_runtime_enabled": True,
        "codex_runtime_allowed_versions": _VERSION,
        "tutor_codex_plan_drafting_enabled": True,
        "tutor_codex_runtime_health_max_age_seconds": 90,
        "deepseek_model": DEEPSEEK_V4_FLASH_MODEL,
    }
    values.update(overrides)
    return Settings(**values)


def _record_ready(conn, *, observed_at: datetime = _NOW) -> None:  # type: ignore[no-untyped-def]
    PostgresTutorCodexRuntimeReadinessRepository(conn).record(
        worker_id=f"test-codex:{uuid4().hex}",
        status=RuntimeHealthStatus.READY.value,
        generation=7,
        runtime_version=_VERSION,
        model=DEEPSEEK_V4_FLASH_MODEL,
        model_provider="aearn_deepseek",
        protocol="responses",
        safe_error_code=None,
        observed_at=observed_at,
    )


def test_runtime_selection_is_exact_fail_closed_and_scope_bounded(tutor_persistence) -> None:  # type: ignore[no-untyped-def]
    conn = tutor_persistence.connection
    conn.execute("DELETE FROM tutor_codex_runtime_health")
    policy = TutorRuntimeSelectionPolicy(conn, settings=_settings(), now_provider=lambda: _NOW)

    assert policy.select(scope_kind=LearningScopeKind.GENERAL).runtime_kind == "harness_v1"
    with pytest.raises(TutorCodexRuntimeUnavailable, match="runtime_readiness_missing"):
        policy.select(scope_kind=LearningScopeKind.PLAN_DRAFTING)

    _record_ready(conn)
    selected = policy.select(scope_kind=LearningScopeKind.PLAN_DRAFTING)
    assert selected.runtime_kind == "codex_sidecar_v1"
    assert selected.reason_code == "codex_plan_drafting_admitted"

    disabled = TutorRuntimeSelectionPolicy(
        conn,
        settings=_settings(tutor_codex_plan_drafting_enabled=False),
        now_provider=lambda: _NOW,
    )
    assert disabled.select(scope_kind=LearningScopeKind.PLAN_DRAFTING).runtime_kind == "harness_v1"
    assert disabled.select(
        scope_kind=LearningScopeKind.PLAN_DRAFTING,
        conversation_runtime_kind="codex_sidecar_v1",
    ).runtime_kind == "codex_sidecar_v1"

    conn.execute("DELETE FROM tutor_codex_runtime_health")
    _record_ready(conn, observed_at=_NOW - timedelta(seconds=91))
    with pytest.raises(TutorCodexRuntimeUnavailable, match="runtime_readiness_stale"):
        policy.select(scope_kind=LearningScopeKind.PLAN_DRAFTING)


def test_public_service_freezes_codex_only_for_new_plan_drafting(tutor_persistence) -> None:  # type: ignore[no-untyped-def]
    conn = tutor_persistence.connection
    conn.execute("DELETE FROM tutor_codex_runtime_health")
    _record_ready(conn, observed_at=datetime.now(UTC))
    user = conn.execute(
        "INSERT INTO users (display_name) VALUES (%s) RETURNING id",
        (f"Codex Cutover {uuid4().hex[:10]}",),
    ).fetchone()
    assert user is not None
    user_id = str(user["id"])
    service = TutorPublicService(conn, settings=_settings())

    response = service.accept_first_turn(
        user_id=user_id,
        content="我想制定 Python 自动化学习计划。",
        idempotency_key=f"codex-plan-{uuid4().hex}",
        learning_scope=LearningScope(scope_kind=LearningScopeKind.PLAN_DRAFTING),
    )
    row = conn.execute(
        "SELECT runtime_kind FROM tutor_runs WHERE id = %s",
        (response["run_id"],),
    ).fetchone()
    assert row == {"runtime_kind": "codex_sidecar_v1"}
    assert "runtime_kind" not in response

    conn.execute("DELETE FROM tutor_codex_runtime_health")
    general = service.accept_first_turn(
        user_id=user_id,
        content="解释一下 Python 闭包。",
        idempotency_key=f"harness-general-{uuid4().hex}",
    )
    general_row = conn.execute(
        "SELECT runtime_kind FROM tutor_runs WHERE id = %s",
        (general["run_id"],),
    ).fetchone()
    assert general_row == {"runtime_kind": "harness_v1"}


def test_plan_drafting_unhealthy_admission_creates_no_conversation(tutor_persistence) -> None:  # type: ignore[no-untyped-def]
    conn = tutor_persistence.connection
    conn.execute("DELETE FROM tutor_codex_runtime_health")
    user = conn.execute(
        "INSERT INTO users (display_name) VALUES (%s) RETURNING id",
        (f"Codex Unavailable {uuid4().hex[:10]}",),
    ).fetchone()
    assert user is not None
    user_id = str(user["id"])
    before = conn.execute(
        "SELECT count(*)::int AS count FROM tutor_conversations WHERE user_id = %s",
        (user_id,),
    ).fetchone()
    with pytest.raises(TutorPublicApiError) as captured:
        TutorPublicService(conn, settings=_settings()).accept_first_turn(
            user_id=user_id,
            content="制定学习计划。",
            idempotency_key=f"unavailable-{uuid4().hex}",
            learning_scope=LearningScope(scope_kind=LearningScopeKind.PLAN_DRAFTING),
        )
    assert captured.value.code == "TUTOR_RUNTIME_UNAVAILABLE"
    assert captured.value.status_code == 503
    after = conn.execute(
        "SELECT count(*)::int AS count FROM tutor_conversations WHERE user_id = %s",
        (user_id,),
    ).fetchone()
    assert before == after


class _FakeCodexHost:
    def __init__(self) -> None:
        self.thread_requests: list[RuntimeThreadRequest] = []
        self.turn_requests: list[RuntimeTurnRequest] = []

    def health_snapshot(self, *, timeout_s: float = 20.0) -> RuntimeHealthSnapshot:
        del timeout_s
        return RuntimeHealthSnapshot(
            RuntimeHealthStatus.READY,
            7,
            version=_VERSION,
            model=DEEPSEEK_V4_FLASH_MODEL,
            model_provider="aearn_deepseek",
        )

    def start_thread(
        self,
        request: RuntimeThreadRequest,
        *,
        timeout_s: float = 30.0,
    ) -> RuntimeThreadHandle:
        del timeout_s
        self.thread_requests.append(request)
        return RuntimeThreadHandle("thread-cutover", 7)

    def run_turn(
        self,
        request: RuntimeTurnRequest,
        *,
        control_reader,  # type: ignore[no-untyped-def]
        initial_input_revision: int,
        poll_interval_s: float = 0.2,
        timeout_s: float = 330.0,
    ) -> RuntimeTurnResult:
        del control_reader, initial_input_revision, poll_interval_s, timeout_s
        self.turn_requests.append(request)
        text = "我已根据当前信息准备计划草稿；请在右侧检查后由 Aearn 确认。"
        events = (
            RuntimeEvent(RuntimeEventKind.TURN_STARTED, "thread-cutover", "turn-cutover"),
            RuntimeEvent(
                RuntimeEventKind.MESSAGE_COMPLETED,
                "thread-cutover",
                "turn-cutover",
                item_id="message-final",
                visible_text=text,
                content_sha256=__import__("hashlib").sha256(text.encode("utf-8")).hexdigest(),
            ),
            RuntimeEvent(
                RuntimeEventKind.TURN_COMPLETED,
                "thread-cutover",
                "turn-cutover",
                terminal_status=RuntimeTerminalStatus.COMPLETED,
            ),
        )
        return RuntimeTurnResult(
            request.thread,
            "turn-cutover",
            RuntimeTerminalStatus.COMPLETED,
            events,
        )

    def current_generation(self) -> int:
        return 7


def test_codex_dispatcher_projects_without_harness_loop(tutor_persistence, tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = tutor_persistence.connection
    repository = PostgresTutorRepository(conn)
    conversation_id = repository.create_conversation(user_id=tutor_persistence.user_id)
    PostgresLearningTrackRepository(conn).bind_conversation_scope(
        user_id=tutor_persistence.user_id,
        conversation_id=conversation_id,
        scope=LearningScope(scope_kind=LearningScopeKind.PLAN_DRAFTING),
    )
    PostgresLearningPlanSessionRepository(conn).create_session(
        user_id=tutor_persistence.user_id,
        conversation_id=conversation_id,
        preferred_language_id="python",
    )
    run = repository.create_run(
        user_id=tutor_persistence.user_id,
        conversation_id=conversation_id,
        catalog_digest=tutor_persistence.catalog.digest,
        policy=TutorPolicySnapshot(
            deadline=datetime.now(UTC) + timedelta(minutes=5),
            max_iterations=3,
            max_model_calls=2,
            max_capability_calls=2,
            max_effects=0,
            context_token_budget=512,
        ),
        origin="interactive",
        interaction_protocol_version="thread_turn_v2",
        runtime_kind="codex_sidecar_v1",
    )
    repository.accept_input(
        user_id=tutor_persistence.user_id,
        run_id=run.run_id,
        idempotency_key=f"codex-dispatch-{uuid4().hex}",
        content="请生成 Python 自动化学习计划。",
        received_at=datetime.now(UTC),
    )
    PostgresLearningTrackRepository(conn).snapshot_run_scope(
        user_id=tutor_persistence.user_id,
        run_id=run.run_id,
        explicit_scope=LearningScope(scope_kind=LearningScopeKind.PLAN_DRAFTING),
    )

    @contextmanager
    def same_connection():  # type: ignore[no-untyped-def]
        yield conn

    host = _FakeCodexHost()
    result = CodexTutorRunDispatcher(
        settings=_settings(codex_runtime_home_directory=str(tmp_path / "runtime-home")),
        host=host,
        connection_factory=same_connection,
        manage_autocommit=False,
    ).dispatch(user_id=tutor_persistence.user_id, run_id=run.run_id)

    assert result.terminal_outcome is TutorTerminalOutcome.COMPLETED
    assert len(host.thread_requests) == 1
    assert {tool.name for tool in host.thread_requests[0].tools} == {
        "aearn_planning_context_read",
        "aearn_learning_plan_draft",
    }
    assert len(host.turn_requests) == 1
    binding = conn.execute(
        "SELECT state, runtime_kind, protocol_version FROM tutor_run_runtime_bindings WHERE run_id = %s",
        (run.run_id,),
    ).fetchone()
    assert binding == {
        "state": "completed",
        "runtime_kind": "codex_sidecar_v1",
        "protocol_version": "responses",
    }
    messages = conn.execute(
        "SELECT role, content FROM tutor_messages WHERE conversation_id = %s ORDER BY created_at, id",
        (conversation_id,),
    ).fetchall()
    assert [row["role"] for row in messages] == ["learner", "tutor"]
    assert "Aearn 确认" in str(messages[-1]["content"])


def test_retry_and_dispatch_claim_preserve_codex_runtime(tutor_persistence) -> None:  # type: ignore[no-untyped-def]
    conn = tutor_persistence.connection
    repository = PostgresTutorRepository(conn)
    conversation_id = repository.create_conversation(user_id=tutor_persistence.user_id)
    run = repository.create_run(
        user_id=tutor_persistence.user_id,
        conversation_id=conversation_id,
        catalog_digest=tutor_persistence.catalog.digest,
        policy=TutorPolicySnapshot(
            deadline=datetime.now(UTC) + timedelta(minutes=5),
            max_iterations=3,
            max_model_calls=2,
            max_capability_calls=2,
            max_effects=0,
            context_token_budget=512,
        ),
        origin="interactive",
        interaction_protocol_version="thread_turn_v2",
        runtime_kind="codex_sidecar_v1",
    )
    accepted = repository.accept_input(
        user_id=tutor_persistence.user_id,
        run_id=run.run_id,
        idempotency_key=f"codex-retry-source-{uuid4().hex}",
        content="生成学习计划",
        received_at=datetime.now(UTC),
    )
    PostgresLearningTrackRepository(conn).snapshot_run_scope(
        user_id=tutor_persistence.user_id,
        run_id=run.run_id,
        explicit_scope=LearningScope(scope_kind=LearningScopeKind.PLAN_DRAFTING),
    )
    fresh = repository._lock_run(user_id=tutor_persistence.user_id, run_id=run.run_id)
    repository._ensure_public_process_locked(run=fresh, occurred_at=datetime.now(UTC))

    claims = repository.claim_interactive_dispatch_jobs(
        owner_id="codex-claim-test",
        now=datetime.now(UTC),
        job_id=accepted.dispatch_job_id,
        runtime_kind="codex_sidecar_v1",
    )
    assert len(claims) == 1
    assert repository.claim_interactive_dispatch_jobs(
        owner_id="harness-claim-test",
        now=datetime.now(UTC),
        job_id=accepted.dispatch_job_id,
        runtime_kind="harness_v1",
    ) == ()
    repository.complete_interactive_dispatch_job(
        job_id=claims[0].job_id,
        owner_id="codex-claim-test",
        lease_generation=claims[0].lease_generation,
        completed_at=datetime.now(UTC),
    )
    conn.execute(
        """
        UPDATE tutor_runs
        SET status = 'failed', terminal_outcome = 'failed',
            terminal_diagnostic_code = 'runtime_failed', terminal_at = now(),
            active_lease_owner_id = NULL, active_lease_expires_at = NULL
        WHERE id = %s
        """,
        (run.run_id,),
    )
    retried, _control_version = PostgresTutorQueueController(conn).retry(
        user_id=tutor_persistence.user_id,
        conversation_id=conversation_id,
        turn_id=run.run_id,
        expected_control_version=1,
        catalog_digest=tutor_persistence.catalog.digest,
        policy=run.policy,
        occurred_at=datetime.now(UTC),
    )
    assert retried.run.runtime_kind == "codex_sidecar_v1"
    assert retried.run.run_id != run.run_id


@dataclass
class _RecordingDispatcher:
    outcome: TutorTerminalOutcome
    calls: list[tuple[str, str]] = field(default_factory=list)

    def dispatch(self, *, user_id: str, run_id: str) -> TutorRunResult:
        self.calls.append((user_id, run_id))
        return TutorRunResult(
            run_id=run_id,
            status=TutorRunStatus.COMPLETED,
            input_revision=1,
            iteration_count=0,
            model_call_count=0,
            capability_call_count=0,
            effect_count=0,
            terminal_outcome=self.outcome,
        )


def test_dispatch_router_uses_only_frozen_runtime_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = {"value": "harness_v1"}

    @contextmanager
    def fake_connect() -> Iterator[object]:
        yield object()

    class FakeRepository:
        def __init__(self, _conn: object) -> None:
            pass

        def load_snapshot(self, *, user_id: str, run_id: str):  # type: ignore[no-untyped-def]
            del user_id, run_id
            return SimpleNamespace(runtime_kind=runtime["value"])

    monkeypatch.setattr(interactive_module, "connect", fake_connect)
    monkeypatch.setattr(interactive_module, "PostgresTutorRepository", FakeRepository)
    harness = _RecordingDispatcher(TutorTerminalOutcome.COMPLETED)
    codex = _RecordingDispatcher(TutorTerminalOutcome.COMPLETED)
    router = TutorRuntimeDispatchRouter(harness=harness, codex=codex)

    router.dispatch(user_id="user", run_id="run-harness")
    runtime["value"] = "codex_sidecar_v1"
    router.dispatch(user_id="user", run_id="run-codex")

    assert harness.calls == [("user", "run-harness")]
    assert codex.calls == [("user", "run-codex")]


class _ControlledRuntime:
    def __init__(self) -> None:
        self._events: asyncio.Queue[RuntimeEvent] = asyncio.Queue()
        self._finished = asyncio.Event()
        self.steers: list[tuple[str, tuple[str, ...]]] = []
        self.interrupts: list[str] = []
        self.terminal = RuntimeTerminalStatus.COMPLETED

    async def run_turn(self, request: RuntimeTurnRequest) -> RuntimeTurnResult:
        turn_id = "turn-1"
        started = RuntimeEvent(
            RuntimeEventKind.TURN_STARTED,
            request.thread.thread_id,
            turn_id,
        )
        await self._events.put(started)
        await self._finished.wait()
        terminal = RuntimeEvent(
            RuntimeEventKind.TURN_COMPLETED,
            request.thread.thread_id,
            turn_id,
            terminal_status=self.terminal,
        )
        await self._events.put(terminal)
        return RuntimeTurnResult(
            request.thread,
            turn_id,
            self.terminal,
            (started, terminal),
        )

    async def steer(
        self,
        thread: RuntimeThreadHandle,
        turn_id: str,
        input: tuple[RuntimeInput, ...],
    ) -> None:
        del thread
        self.steers.append((turn_id, tuple(item.text for item in input)))
        self._finished.set()

    async def interrupt(self, thread: RuntimeThreadHandle, turn_id: str) -> None:
        del thread
        self.interrupts.append(turn_id)
        self.terminal = RuntimeTerminalStatus.INTERRUPTED
        self._finished.set()

    async def events(self):  # type: ignore[no-untyped-def]
        while True:
            yield await self._events.get()


def test_controlled_runtime_maps_revision_to_steer() -> None:
    runtime = _ControlledRuntime()
    calls = 0

    def control(_turn_id: str, applied_revision: int) -> RuntimeTurnControlDirective:
        nonlocal calls
        calls += 1
        if calls == 1:
            return RuntimeTurnControlDirective(
                input_revision=applied_revision + 1,
                steer_input=(RuntimeInput("补充：每周学习 5 小时。"),),
            )
        return RuntimeTurnControlDirective(applied_revision)

    request = RuntimeTurnRequest(
        thread=RuntimeThreadHandle("thread-1", 1),
        input=(RuntimeInput("制定计划"),),
        tools=SimpleNamespace(),  # type: ignore[arg-type]
    )
    result = asyncio.run(
        _run_controlled_turn(
            runtime,  # type: ignore[arg-type]
            request,
            control_reader=control,
            initial_input_revision=1,
            poll_interval_s=0.001,
        )
    )
    assert runtime.steers == [("turn-1", ("补充：每周学习 5 小时。",))]
    assert result.terminal_status is RuntimeTerminalStatus.COMPLETED


def test_controlled_runtime_maps_cancel_to_interrupt() -> None:
    runtime = _ControlledRuntime()
    request = RuntimeTurnRequest(
        thread=RuntimeThreadHandle("thread-2", 1),
        input=(RuntimeInput("制定计划"),),
        tools=SimpleNamespace(),  # type: ignore[arg-type]
    )
    result = asyncio.run(
        _run_controlled_turn(
            runtime,  # type: ignore[arg-type]
            request,
            control_reader=lambda _turn_id, revision: RuntimeTurnControlDirective(
                revision,
                interrupt=True,
            ),
            initial_input_revision=1,
            poll_interval_s=0.001,
        )
    )
    assert runtime.interrupts == ["turn-1"]
    assert result.terminal_status is RuntimeTerminalStatus.INTERRUPTED
