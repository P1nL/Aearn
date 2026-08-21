"""Codex-sidecar dispatcher for already-admitted Tutor plan-drafting runs."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
import logging
from time import perf_counter
from typing import Protocol, cast
from uuid import uuid4

from psycopg import Connection

from app.agents.harness.contracts import (
    TutorCheckpointReason,
    TutorContinuationKind,
    TutorDecision,
    TutorPlanningQuestionKey,
    TutorRunResult,
    TutorRunSnapshot,
    TutorRunStatus,
    TutorTerminalOutcome,
    TutorTurnCompletionReason,
)
from app.agents.runtime.codex_config import CODEX_WIRE_API, CodexRuntimeConfig
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
from app.agents.runtime.learning_plan_tools import LearningPlanRuntimeToolRegistry
from app.agents.runtime.tutor_projection import TutorRuntimeEventProjector
from app.agents.runtime.worker_host import (
    RuntimeTurnControlDirective,
    get_codex_runtime_worker_host,
)
from app.core.config import Settings
from app.db.connection import connect
from app.services.learning.contracts import LearningScopeKind
from app.services.learning.plan_tools import LearningPlanToolStatus

from app.services.learning.planning_facts import PlanningFactField, PostgresPlanningFactRepository
from app.services.learning.planning_questions import planning_question_prompt
from app.services.learning.track_repository import PostgresLearningTrackRepository
from app.services.tutor.persistence import (
    PostgresTutorRepository,
    TutorLease,
    TutorRunReadState,
)
from app.services.tutor.runtime_projection import (
    PostgresTutorRuntimeProjectionRepository,
    TutorRuntimeProjectionFence,
)

logger = logging.getLogger(__name__)

_BASE_INSTRUCTIONS = """你是 Aearn 的计划草拟 Runtime。只处理当前服务端绑定的 plan_drafting Turn。
每个 Turn 必须先调用 aearn_planning_context_read 获取服务端权威事实；事实完整时可调用 aearn_learning_plan_draft 提交 typed draft。
禁止调用 Codex 内置 request_user_input、MCP elicitation 或任何客户端交互请求，也禁止自行定义问题、选项或一次批量询问多个字段。
工具返回 awaiting_user 时，读取 data.next_missing_fact。final_answer 可先用一句简短中文确认已知事实，然后必须逐字使用 exact_question 作为唯一问题并结束当前 Turn；不得改写字段含义、补充括号示例、添加选项或提出第二个问题。language_id 始终表示要学习的编程语言或课程，不表示教学内容使用的自然语言。Aearn 会根据服务端 catalog 创建持久化 generated UI。学习者回答后会进入同一 Codex thread 的新 Turn，届时重新调用 aearn_planning_context_read 并继续第一个缺失字段。
你只能草拟，不能确认计划、创建 LearningTrack、选择 Runtime、修改用户或数据库范围，也不能执行命令、访问网络或输出内部控制面。
工具返回 repairable_invalid 或 conflict 时按安全 issue 修复。
最终回答只面向学习者，不能包含 reasoning、工具参数、provider 诊断、路径、凭据或内部 ID。"""


class CodexRuntimeHostPort(Protocol):
    def health_snapshot(self, *, timeout_s: float = 20.0) -> RuntimeHealthSnapshot: ...
    def start_thread(
        self,
        request: RuntimeThreadRequest,
        *,
        timeout_s: float = 30.0,
    ) -> RuntimeThreadHandle: ...
    def resume_thread(
        self,
        thread_id: str,
        *,
        timeout_s: float = 30.0,
    ) -> RuntimeThreadHandle: ...
    def compact_thread(
        self,
        thread: RuntimeThreadHandle,
        *,
        timeout_s: float = 30.0,
    ) -> None: ...
    def run_turn(
        self,
        request: RuntimeTurnRequest,
        *,
        control_reader: Callable[[str, int], RuntimeTurnControlDirective],
        initial_input_revision: int,
        event_observer: Callable[[RuntimeEvent, int], None] | None = None,
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
            registry.prime_context()
            config = CodexRuntimeConfig.from_settings(self._settings)
            projection_repository = PostgresTutorRuntimeProjectionRepository(conn)
            conversation_thread = projection_repository.active_conversation_thread(
                user_id=user_id,
                conversation_id=leased.conversation_id,
            )
            migration_mode = "native"
            if conversation_thread is None:
                legacy_binding_count = _legacy_runtime_binding_count(
                    conn,
                    user_id=user_id,
                    conversation_id=leased.conversation_id,
                )
                migration_mode = "legacy_reseed" if legacy_binding_count else "native"
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
                conversation_thread = projection_repository.create_conversation_thread(
                    user_id=user_id,
                    conversation_id=leased.conversation_id,
                    runtime_version=health.version,
                    protocol_version=CODEX_WIRE_API,
                    external_thread_id=thread.thread_id,
                    migration_mode=migration_mode,
                    occurred_at=datetime.now(UTC),
                )
            else:
                thread = self._host.resume_thread(
                    conversation_thread.external_thread_id,
                    timeout_s=self._settings.codex_runtime_startup_timeout_seconds
                    + self._settings.codex_runtime_request_timeout_seconds,
                )
                projection_repository.mark_conversation_thread_resumed(
                    thread_binding_id=conversation_thread.thread_binding_id,
                    user_id=user_id,
                    occurred_at=datetime.now(UTC),
                )
            fence = TutorRuntimeProjectionFence(
                input_revision=leased.input_revision,
                lease_owner_id=lease.owner_id,
                lease_generation=lease.generation,
                connection_generation=thread.generation,
            )
            binding = projection_repository.bind_run(
                user_id=user_id,
                run_id=run_id,
                fence=fence,
                runtime_version=health.version,
                protocol_version=CODEX_WIRE_API,
                external_thread_id=thread.thread_id,
                occurred_at=datetime.now(UTC),
                conversation_runtime_thread_id=conversation_thread.thread_binding_id,
            )
            input_text = _read_input_text(
                conn,
                run_id=run_id,
                input_revision=leased.input_revision,
            )
            if migration_mode == "legacy_reseed":
                input_text = _legacy_reseed_input(
                    conn,
                    user_id=user_id,
                    conversation_id=leased.conversation_id,
                    current_input=input_text,
                )
            control_reader = _CodexControlReader(
                conn=conn,
                repository=repository,
                user_id=user_id,
                run_id=run_id,
                lease=lease,
                lease_duration_seconds=leased.policy.lease_duration_seconds,
            )
            def project_live_event(event: RuntimeEvent, sequence: int) -> None:
                current = repository.load_snapshot(user_id=user_id, run_id=run_id)
                if current is None:
                    raise RuntimeError("Tutor Codex run disappeared during projection")
                awaiting_field = _awaiting_planning_field(registry)
                if awaiting_field is not None and event.kind is RuntimeEventKind.TURN_COMPLETED:
                    return
                projection_started = perf_counter()
                receipt = TutorRuntimeEventProjector(
                    projection_repository,
                    binding_id=binding.binding_id,
                    fence=TutorRuntimeProjectionFence(
                        input_revision=current.input_revision,
                        lease_owner_id=lease.owner_id,
                        lease_generation=lease.generation,
                        connection_generation=thread.generation,
                    ),
                ).project_event(
                    event,
                    sequence=sequence,
                    occurred_at=datetime.now(UTC),
                    defer_public_message=(
                        awaiting_field is not None
                        and event.kind is RuntimeEventKind.MESSAGE_COMPLETED
                        and event.phase in {None, "final_answer"}
                    ),
                )
                logger.info(
                    "codex_runtime_projection",
                    extra={
                        "run_id": run_id,
                        "runtime_event_kind": event.kind.value,
                        "runtime_projection_sequence": receipt.projection_sequence,
                        "runtime_source_delta_count": receipt.source_delta_count,
                        "runtime_projection_duration_ms": max(
                            0, round((perf_counter() - projection_started) * 1_000)
                        ),
                        "runtime_projection_status": receipt.projection_status.value,
                    },
                )

            result = self._host.run_turn(
                RuntimeTurnRequest(
                    thread=thread,
                    input=(RuntimeInput(input_text),),
                    tools=registry,
                ),
                control_reader=control_reader.read,
                initial_input_revision=leased.input_revision,
                event_observer=project_live_event,
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
            projector = TutorRuntimeEventProjector(
                projection_repository,
                binding_id=binding.binding_id,
                fence=final_fence,
            )
            awaiting_field = _awaiting_planning_field(registry)
            if (
                awaiting_field is not None
                and result.terminal_status is RuntimeTerminalStatus.COMPLETED
            ):
                occurred_at = datetime.now(UTC)
                for index, event in enumerate(result.events, start=1):
                    if event.kind is RuntimeEventKind.TURN_COMPLETED:
                        continue
                    projector.project_event(
                        event,
                        sequence=event.sequence or index,
                        occurred_at=occurred_at,
                        defer_public_message=(
                            event.kind is RuntimeEventKind.MESSAGE_COMPLETED
                            and event.phase in {None, "final_answer"}
                        ),
                    )
                prompt = planning_question_prompt(awaiting_field)
                PostgresPlanningFactRepository(conn).record_question_asked(
                    run=current,
                    field=awaiting_field,
                )
                typed_result = TutorRunResult(
                    run_id=run_id,
                    status=TutorRunStatus.COMPLETED,
                    input_revision=current.input_revision,
                    iteration_count=current.iteration_count + 1,
                    model_call_count=current.model_call_count + 1,
                    capability_call_count=current.capability_call_count + registry.call_count,
                    effect_count=current.effect_count,
                    terminal_outcome=TutorTerminalOutcome.COMPLETED,
                    public_message=prompt,
                    completion_reason=TutorTurnCompletionReason.AWAITING_USER,
                )
                repository.record_interaction_request(
                    user_id=user_id,
                    lease=lease,
                    decision=TutorDecision(
                        public_message=prompt,
                        question_key=cast(TutorPlanningQuestionKey, awaiting_field.value),
                        checkpoint_reason=TutorCheckpointReason.CAPABILITY_RESULT,
                        continuation_kind=TutorContinuationKind.PLANNING_INPUT,
                    ),
                    result=typed_result,
                    created_at=occurred_at,
                    intent_resolution_enabled=self._settings.tutor_planning_intent_enabled,
                )
                message = conn.execute(
                    "SELECT tutor_message_id FROM tutor_run_public_processes WHERE run_id = %s",
                    (run_id,),
                ).fetchone()
                if message is None or message.get("tutor_message_id") is None:
                    raise RuntimeError("Tutor typed planning request message is missing")
                projection_repository.finalize_typed_request_binding(
                    binding_id=binding.binding_id,
                    user_id=user_id,
                    message_id=str(message["tutor_message_id"]),
                    occurred_at=occurred_at,
                )
                for index, event in enumerate(result.events, start=1):
                    if event.kind is RuntimeEventKind.TURN_COMPLETED:
                        projector.project_event(
                            event,
                            sequence=event.sequence or index,
                            occurred_at=occurred_at,
                        )
                return _run_result(repository.read_run_state(user_id=user_id, run_id=run_id))
            projector.project_result(result, occurred_at=datetime.now(UTC))
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
    leased: TutorRunSnapshot,
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
        sequence=projection_repository.next_event_sequence(binding_id=str(binding["id"])),
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


def _awaiting_planning_field(
    registry: LearningPlanRuntimeToolRegistry,
) -> PlanningFactField | None:
    result = registry.planning_context_result
    if result is None or result.status is not LearningPlanToolStatus.AWAITING_USER:
        return None
    missing = result.data.get("missing_facts")
    if not isinstance(missing, list | tuple) or not missing:
        return None
    try:
        return PlanningFactField(str(missing[0]))
    except ValueError:
        return None


def _legacy_runtime_binding_count(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    conversation_id: str,
) -> int:
    row = conn.execute(
        """
        SELECT count(*)::int AS count
        FROM tutor_run_runtime_bindings
        WHERE user_id = %s AND conversation_id = %s
        """,
        (user_id, conversation_id),
    ).fetchone()
    return _as_int(row.get("count")) if row is not None else 0


def _legacy_reseed_input(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    conversation_id: str,
    current_input: str,
) -> str:
    message_rows = conn.execute(
        """
        SELECT messages.role, messages.content
        FROM tutor_messages AS messages
        JOIN tutor_conversations AS conversations ON conversations.id = messages.conversation_id
        WHERE messages.conversation_id = %s AND conversations.user_id = %s
          AND messages.role IN ('learner', 'tutor')
        ORDER BY messages.created_at DESC, messages.id DESC
        LIMIT 12
        """,
        (conversation_id, user_id),
    ).fetchall()
    fact_rows = conn.execute(
        """
        SELECT DISTINCT ON (field_key) field_key, value_json, revision
        FROM tutor_planning_intake_facts
        WHERE user_id = %s AND conversation_id = %s AND state = 'confirmed'
        ORDER BY field_key, revision DESC, id DESC
        """,
        (user_id, conversation_id),
    ).fetchall()
    history_lines = [
        f"{str(row['role'])}: {str(row['content'])}"
        for row in reversed(message_rows)
    ]
    fact_lines = [
        f"{str(row['field_key'])}={row['value_json']} (revision={_as_int(row['revision'])})"
        for row in fact_rows
    ]
    recovery = (
        "这是 Aearn 对旧 run 级 Runtime thread 的一次性受控恢复。"
        "以下学习者可见历史与服务端 confirmed facts 仅用于恢复语境；"
        "开始工作后必须再次调用 aearn_planning_context_read，以服务端返回为最终权威。\n"
        "[confirmed facts]\n"
        + ("\n".join(fact_lines) if fact_lines else "(none)")
        + "\n[learner-visible history]\n"
        + ("\n".join(history_lines) if history_lines else "(none)")
    )
    prefix = recovery[: max(0, 19_500 - len(current_input))]
    if not prefix:
        return current_input
    return f"{prefix}\n[current input]\n{current_input}"


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
        sequence=max(
            (event.sequence or index for index, event in enumerate(result.events, start=1)),
            default=0,
        )
        + 1,
    )
    return RuntimeTurnResult(
        result.thread,
        result.turn_id,
        result.terminal_status,
        (*result.events, terminal),
        result.safe_error_code,
    )


def _run_result(state: TutorRunReadState) -> TutorRunResult:
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
