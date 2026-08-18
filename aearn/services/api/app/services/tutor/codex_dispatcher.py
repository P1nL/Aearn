"""Codex-sidecar dispatcher for already-admitted Tutor plan-drafting runs."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from psycopg import Connection

from app.agents.harness.contracts import TutorRunResult
from app.agents.runtime.codex_config import CODEX_WIRE_API, CodexRuntimeConfig
from app.agents.runtime.contracts import (
    RuntimeEvent,
    RuntimeEventKind,
    RuntimeHealthStatus,
    RuntimeInput,
    RuntimeTerminalStatus,
    RuntimeThreadHandle,
    RuntimeThreadRequest,
    RuntimeTurnRequest,
    RuntimeTurnResult,
)
from app.agents.runtime.learning_plan_tools import LearningPlanRuntimeToolRegistry
from app.agents.runtime.tutor_projection import TutorRuntimeEventProjector
from app.agents.runtime.worker_host import (
    RuntimeTurnControlDirective,
    get_codex_runtime_worker_host,
)
from app.core.config import Settings
from app.db.connection import connect
from app.services.learning.contracts import LearningScopeKind
from app.services.learning.track_repository import PostgresLearningTrackRepository
from app.services.tutor.persistence import PostgresTutorRepository, TutorLease
from app.services.tutor.runtime_projection import (
    PostgresTutorRuntimeProjectionRepository,
    TutorRuntimeProjectionFence,
)

_BASE_INSTRUCTIONS = """你是 Aearn 的计划草拟 Runtime。只处理当前服务端绑定的 plan_drafting Turn。
先调用 aearn_planning_context_read 获取服务端权威事实；事实完整时可调用 aearn_learning_plan_draft 提交 typed draft。
你只能草拟，不能确认计划、创建 LearningTrack、选择 Runtime、修改用户或数据库范围，也不能执行命令、访问网络或输出内部控制面。
工具返回 repairable_invalid 或 conflict 时按安全 issue 修复；awaiting_user 时用简洁中文询问缺失信息。
最终回答只面向学习者，不能包含 reasoning、工具参数、provider 诊断、路径、凭据或内部 ID。"""


class CodexRuntimeHostPort(Protocol):
    def health_snapshot(self, *, timeout_s: float = 20.0): ...  # type: ignore[no-untyped-def]
    def start_thread(self, request: RuntimeThreadRequest, *, timeout_s: float = 30.0): ...  # type: ignore[no-untyped-def]
    def run_turn(
        self,
        request: RuntimeTurnRequest,
        *,
        control_reader,  # type: ignore[no-untyped-def]
        initial_input_revision: int,
        poll_interval_s: float = 0.2,
        timeout_s: float = 330.0,
    ) -> RuntimeTurnResult: ...
    def current_generation(self) -> int: ...


class CodexTutorRunDispatcher:
    """Run one frozen Codex Tutor turn without composing the Harness loop."""

    def __init__(
        self,
        *,
        settings: Settings,
        host: CodexRuntimeHostPort | None = None,
        connection_factory: Callable[
            [], AbstractContextManager[Connection[dict[str, object]]]
        ] = connect,
        manage_autocommit: bool = True,
    ) -> None:
        self._settings = settings
        self._host = host or get_codex_runtime_worker_host()
        self._connection_factory = connection_factory
        self._manage_autocommit = manage_autocommit

    def dispatch(self, *, user_id: str, run_id: str) -> TutorRunResult:
        with self._connection_factory() as conn:
            if self._manage_autocommit:
                conn.autocommit = True
            repository = PostgresTutorRepository(conn)
            initial = repository.load_snapshot(user_id=user_id, run_id=run_id)
            if initial is None:
                raise ValueError("Tutor run was not found")
            if initial.runtime_kind != "codex_sidecar_v1":
                raise ValueError("Tutor run is not assigned to Codex Runtime")
            scope = PostgresLearningTrackRepository(conn).read_run_scope(
                user_id=user_id,
                run_id=run_id,
            )
            if scope.scope_kind is not LearningScopeKind.PLAN_DRAFTING:
                raise ValueError("Codex Tutor run scope is not plan_drafting")

            lease_owner_id = f"tutor-codex:{uuid4().hex}"
            started_at = datetime.now(UTC)
            lease = repository.acquire_lease(
                user_id=user_id,
                run_id=run_id,
                owner_id=lease_owner_id,
                now=started_at,
                duration_seconds=initial.policy.lease_duration_seconds,
            )
            if lease is None:
                state = repository.read_run_state(user_id=user_id, run_id=run_id)
                if state.terminal_outcome is not None:
                    return _run_result(state)
                raise RuntimeError("Tutor Codex lease is unavailable")
            leased = repository.load_snapshot(user_id=user_id, run_id=run_id)
            if leased is None or leased.lease != lease:
                raise RuntimeError("Tutor Codex lease snapshot is unavailable")

            existing_binding = conn.execute(
                "SELECT * FROM tutor_run_runtime_bindings WHERE run_id = %s",
                (run_id,),
            ).fetchone()
            if existing_binding is not None:
                return _terminalize_recovered_binding(
                    repository=repository,
                    projection_repository=PostgresTutorRuntimeProjectionRepository(conn),
                    user_id=user_id,
                    run_id=run_id,
                    leased=leased,
                    lease=lease,
                    binding=existing_binding,
                )

            health = self._host.health_snapshot(
                timeout_s=self._settings.codex_runtime_startup_timeout_seconds + 5
            )
            if health.status is not RuntimeHealthStatus.READY or health.generation < 1:
                raise RuntimeError(health.safe_error_code or "codex_runtime_unavailable")
            if not health.version:
                raise RuntimeError("codex_runtime_version_missing")

            registry = LearningPlanRuntimeToolRegistry.from_postgres(
                conn,
                run=leased,
                runtime_generation=health.generation,
                runtime_generation_reader=self._host.current_generation,
            )
            config = CodexRuntimeConfig.from_settings(self._settings)
            thread = self._host.start_thread(
                RuntimeThreadRequest(
                    cwd=str((config.home_root / "workspace").resolve()),
                    tools=registry.definitions,
                    base_instructions=_BASE_INSTRUCTIONS,
                    ephemeral=False,
                ),
                timeout_s=self._settings.codex_runtime_startup_timeout_seconds
                + self._settings.codex_runtime_request_timeout_seconds,
            )
            fence = TutorRuntimeProjectionFence(
                input_revision=leased.input_revision,
                lease_owner_id=lease.owner_id,
                lease_generation=lease.generation,
                connection_generation=thread.generation,
            )
            projection_repository = PostgresTutorRuntimeProjectionRepository(conn)
            binding = projection_repository.bind_run(
                user_id=user_id,
                run_id=run_id,
                fence=fence,
                runtime_version=health.version,
                protocol_version=CODEX_WIRE_API,
                external_thread_id=thread.thread_id,
                occurred_at=datetime.now(UTC),
            )
            input_text = _read_input_text(
                conn,
                run_id=run_id,
                input_revision=leased.input_revision,
            )
            control_reader = _CodexControlReader(
                conn=conn,
                repository=repository,
                user_id=user_id,
                run_id=run_id,
                lease=lease,
                lease_duration_seconds=leased.policy.lease_duration_seconds,
            )
            result = self._host.run_turn(
                RuntimeTurnRequest(
                    thread=thread,
                    input=(RuntimeInput(input_text),),
                    tools=registry,
                ),
                control_reader=control_reader.read,
                initial_input_revision=leased.input_revision,
                poll_interval_s=0.2,
                timeout_s=self._settings.codex_runtime_turn_timeout_seconds + 30,
            )
            result = _ensure_terminal_event(result)
            current = repository.load_snapshot(user_id=user_id, run_id=run_id)
            if current is None:
                raise RuntimeError("Tutor Codex run disappeared")
            final_fence = TutorRuntimeProjectionFence(
                input_revision=current.input_revision,
                lease_owner_id=lease.owner_id,
                lease_generation=lease.generation,
                connection_generation=thread.generation,
            )
            TutorRuntimeEventProjector(
                projection_repository,
                binding_id=binding.binding_id,
                fence=final_fence,
            ).project_result(result, occurred_at=datetime.now(UTC))
            return _run_result(repository.read_run_state(user_id=user_id, run_id=run_id))


class _CodexControlReader:
    def __init__(
        self,
        *,
        conn: Connection[dict[str, object]],
        repository: PostgresTutorRepository,
        user_id: str,
        run_id: str,
        lease: TutorLease,
        lease_duration_seconds: int,
    ) -> None:
        self._conn = conn
        self._repository = repository
        self._user_id = user_id
        self._run_id = run_id
        self._lease = lease
        self._lease_duration_seconds = lease_duration_seconds
        self._next_heartbeat_at = datetime.now(UTC) + timedelta(
            seconds=max(1, lease_duration_seconds // 3)
        )

    def read(self, _turn_id: str, applied_revision: int) -> RuntimeTurnControlDirective:
        now = datetime.now(UTC)
        row = self._conn.execute(
            """
            SELECT input_revision, terminal_outcome, cancelled_at, superseded_by_run_id,
                   active_lease_owner_id, active_lease_generation
            FROM tutor_runs
            WHERE id = %s AND user_id = %s
            """,
            (self._run_id, self._user_id),
        ).fetchone()
        if row is None or _should_interrupt(row, lease=self._lease):
            return RuntimeTurnControlDirective(applied_revision, interrupt=True)
        if now >= self._next_heartbeat_at:
            renewed = self._repository.heartbeat_lease(
                user_id=self._user_id,
                lease=self._lease,
                now=now,
                duration_seconds=self._lease_duration_seconds,
            )
            if renewed is None:
                return RuntimeTurnControlDirective(applied_revision, interrupt=True)
            self._lease = renewed
            self._next_heartbeat_at = now + timedelta(
                seconds=max(1, self._lease_duration_seconds // 3)
            )
        revision = _as_int(row.get("input_revision"))
        if revision <= applied_revision:
            return RuntimeTurnControlDirective(applied_revision)
        rows = self._conn.execute(
            """
            SELECT inputs.input_revision, messages.content
            FROM tutor_run_input_events AS inputs
            JOIN tutor_messages AS messages ON messages.id = inputs.message_id
            WHERE inputs.run_id = %s
              AND inputs.input_revision > %s
              AND inputs.input_revision <= %s
            ORDER BY inputs.input_revision
            """,
            (self._run_id, applied_revision, revision),
        ).fetchall()
        expected = revision - applied_revision
        if len(rows) != expected:
            return RuntimeTurnControlDirective(applied_revision, interrupt=True)
        return RuntimeTurnControlDirective(
            input_revision=revision,
            steer_input=tuple(RuntimeInput(str(item["content"])) for item in rows),
        )


def _terminalize_recovered_binding(
    *,
    repository: PostgresTutorRepository,
    projection_repository: PostgresTutorRuntimeProjectionRepository,
    user_id: str,
    run_id: str,
    leased,  # type: ignore[no-untyped-def]
    lease: TutorLease,
    binding: Mapping[str, object],
) -> TutorRunResult:
    generation = _as_int(binding.get("connection_generation"))
    thread_id = str(binding.get("external_thread_id") or "")
    turn_id = str(binding.get("external_turn_id") or "")
    fence = TutorRuntimeProjectionFence(
        input_revision=leased.input_revision,
        lease_owner_id=lease.owner_id,
        lease_generation=lease.generation,
        connection_generation=generation,
    )
    event = RuntimeEvent(
        RuntimeEventKind.TURN_COMPLETED,
        thread_id,
        turn_id or None,
        terminal_status=RuntimeTerminalStatus.UNAVAILABLE,
        safe_code="runtime_dispatch_recovered",
    )
    result = RuntimeTurnResult(
        thread=RuntimeThreadHandle(thread_id, generation),
        turn_id=turn_id,
        terminal_status=RuntimeTerminalStatus.UNAVAILABLE,
        events=(event,),
        safe_error_code="runtime_dispatch_recovered",
    )
    TutorRuntimeEventProjector(
        projection_repository,
        binding_id=str(binding["id"]),
        fence=fence,
    ).project_result(result, occurred_at=datetime.now(UTC))
    return _run_result(repository.read_run_state(user_id=user_id, run_id=run_id))


def _should_interrupt(row: Mapping[str, object], *, lease: TutorLease) -> bool:
    return (
        row.get("terminal_outcome") is not None
        or row.get("cancelled_at") is not None
        or row.get("superseded_by_run_id") is not None
        or str(row.get("active_lease_owner_id") or "") != lease.owner_id
        or _as_int(row.get("active_lease_generation")) != lease.generation
    )


def _read_input_text(
    conn: Connection[dict[str, object]],
    *,
    run_id: str,
    input_revision: int,
) -> str:
    row = conn.execute(
        """
        SELECT messages.content
        FROM tutor_run_input_events AS inputs
        JOIN tutor_messages AS messages ON messages.id = inputs.message_id
        WHERE inputs.run_id = %s AND inputs.input_revision = %s
        """,
        (run_id, input_revision),
    ).fetchone()
    if row is None:
        raise RuntimeError("Tutor Codex input is missing")
    return str(row["content"])


def _ensure_terminal_event(result: RuntimeTurnResult) -> RuntimeTurnResult:
    if any(event.kind is RuntimeEventKind.TURN_COMPLETED for event in result.events):
        return result
    terminal = RuntimeEvent(
        RuntimeEventKind.TURN_COMPLETED,
        result.thread.thread_id,
        result.turn_id or None,
        terminal_status=result.terminal_status,
        safe_code=result.safe_error_code,
    )
    return RuntimeTurnResult(
        result.thread,
        result.turn_id,
        result.terminal_status,
        (*result.events, terminal),
        result.safe_error_code,
    )


def _run_result(state) -> TutorRunResult:  # type: ignore[no-untyped-def]
    snapshot = state.snapshot
    return TutorRunResult(
        run_id=snapshot.run_id,
        status=snapshot.status,
        input_revision=snapshot.input_revision,
        iteration_count=snapshot.iteration_count,
        model_call_count=snapshot.model_call_count,
        capability_call_count=snapshot.capability_call_count,
        effect_count=snapshot.effect_count,
        terminal_outcome=state.terminal_outcome,
        completion_reason=state.completion_reason,
        diagnostic_code=state.diagnostic_code,
    )


def _as_int(value: object) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0
