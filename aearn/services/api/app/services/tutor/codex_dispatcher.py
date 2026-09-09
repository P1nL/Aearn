"""Codex-sidecar dispatcher for already-admitted Tutor plan-drafting runs."""
from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
import logging
from time import perf_counter
from typing import Protocol, cast
from uuid import uuid4

from psycopg import Connection
from app.core.safe_diagnostics import log_safe_event

from app.agents.harness.contracts import (
    TutorCheckpointReason,
    TutorContinuationKind,
    TutorDecision,
    TutorPlanningIntentConfidence,
    TutorPlanningIntentHint,
    TutorPlanningIntentReasonCode,
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
from app.core.teaching_safety import check_teaching_output
from app.db.connection import connect
from app.services.learning.contracts import LearningScopeKind
from app.services.learning.plan_tools import (
    LearningPlanToolStatus,
    PlanningDirectionAction,
)
from app.services.learning.planning_intent import PlanningIntentResolver

from app.services.learning.planning_facts import (
    PLANNING_DIRECTION_SWITCH_REOPEN_FIELDS,
    PlanningFactField,
    PostgresPlanningFactRepository,
)
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

_DIRECTION_INTAKE_TIMEOUT_SECONDS = 45.0
_DIRECTION_INTAKE_MAX_VISIBLE_TEXT_CHARS = 2_000
_DIRECTION_INTAKE_MAX_REASONING_TEXT_CHARS = 16_000
_DIRECTION_BOUND_CODES = frozenset(
    {
        "runtime_turn_time_exhausted",
        "runtime_text_budget_exhausted",
        "tool_deadline_exhausted",
        "tool_call_budget_exhausted",
        "tool_output_budget_exhausted",
        "tool_repair_budget_exhausted",
        "tool_conflict_budget_exhausted",
        "runtime_tool_budget_exhausted",
        "runtime_item_budget_exhausted",
        "runtime_raw_notification_runaway",
        "runtime_pending_bytes_exhausted",
        "runtime_event_backpressure_exhausted",
    }
)
_DIRECTION_PROTOCOL_FATAL_CODES = frozenset(
    {
        "planning_direction_action_conflict",
        "planning_direction_action_duplicate",
        "planning_direction_action_required",
        "planning_direction_context_read_duplicate",
        "planning_direction_context_read_required",
        "planning_direction_intake_draft_forbidden",
        "planning_direction_protocol_invalid",
        "unknown_learning_plan_tool",
    }
)
_DIRECTION_CLARIFICATION_PROMPT = (
    "你刚才的最新输入可能与当前计划方向不一致：这是对当前目标的补充、"
    "一个临时问题，还是你希望切换学习方向？"
)

_BASE_INSTRUCTIONS = """你是 Aearn 的计划草拟 Runtime。只处理当前服务端绑定的 plan_drafting Turn。
每个 Turn 先调用一次 aearn_planning_context_read，不提交 direction_action，只读取当前服务端权威事实。读取后立即再次调用同一工具，并恰好提交一个 closed direction_action：continue_mainline、answer_and_refocus、clarify_direction 或 confirmed_switch。不要继续递归讨论方向，也不要在 action 被接受后重复读取、改判或提交冲突 action。
最新 learner input、显式用户控制和 aearn_planning_context_read 返回的当前服务端事实高于旧消息、摘要、先前建议与 persistent Codex thread 的联想。旧 thread 只能帮助解释，不能无确认地补全网站、图片、HTML 或任何已被最新输入拒绝的旧方向。
按语义关系选择 action，不使用关键词列表，也不把分类名写入公开输出：continue_mainline 表示相关延伸、约束或示例；answer_and_refocus 表示可简短回答的临时岔题，先回答，再明确连接回当前计划主线和下一步；clarify_direction 表示无法判断是相关素材、临时岔题还是切换；confirmed_switch 只用于学习者明确否定旧方向并给出新方向。不得忽略岔题、回答后丢失主线，或把所有新主题都强制拉回旧方向。
若选择 clarify_direction，提交 action 后结束；Aearn 使用固定的单一方向澄清问题，忽略任意模型自拟问题。若选择 confirmed_switch，提交 action 后结束且不得提交 draft；Aearn 只会通过既有 append-only lineage 重新打开语言、目标、层级和相关经验，你不能自行写入、撤回或替换 fact。
若选择 continue_mainline 或 answer_and_refocus 且工具返回 awaiting_user，读取 data.next_missing_fact。continue_mainline 只需结束，Aearn 使用 exact_question；answer_and_refocus 的 final_answer 可包含一个简短、learner-safe 的前置回答，但必须以逐字 exact_question 作为唯一问题结束。不得改写字段含义、补充括号示例、添加选项或提出第二个问题。
若缺失 language_id，首次 read 会给出 data.language_candidates。只有选择 continue_mainline 且存在高或中置信语义匹配时，第二次调用才可同时提交 planning-intent-hint-v2，并只能列出 1..3 个当前 canonical language_id。语言证据不足时选择 clarify_direction。不得请求完整目录、提供标签/课程 UUID/自定义选项或默认推荐；语义候选永远需要学习者确认。language_id 始终表示要学习的编程语言或课程，不表示教学内容使用的自然语言。
事实完整时，只有 accepted continue_mainline 才可调用 aearn_learning_plan_draft。草拟工具成功前不得给出完成性回答。你只能草拟，不能确认计划、创建 LearningTrack、选择 Runtime、修改用户或数据库范围，也不能执行命令、访问网络或输出内部控制面。
禁止调用 Codex 内置 request_user_input、MCP elicitation 或任何客户端交互请求。工具返回 repairable_invalid 或 conflict 时按安全 issue 修复，但 direction action 自身不得重试、重复或重分类。
最终回答只面向学习者，不能包含工具参数、provider 诊断、路径、凭据或内部 ID。"""


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
            primed_context = registry.prime_context()
            if primed_context.status is LearningPlanToolStatus.AWAITING_USER:
                registry.configure_direction_intake(
                    max_wall_seconds=_DIRECTION_INTAKE_TIMEOUT_SECONDS,
                )
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
                typed_request_pending = registry.requires_server_terminalization
                if typed_request_pending and event.kind is RuntimeEventKind.TURN_COMPLETED:
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
                        typed_request_pending
                        and event.kind is RuntimeEventKind.MESSAGE_COMPLETED
                        and event.phase in {None, "final_answer"}
                    ),
                )
                log_safe_event(
                    logger, "codex_runtime_projection", level=logging.INFO,
                    run_id=run_id, action_category=event.kind.value,
                    projection_sequence=receipt.projection_sequence,
                    source_delta_count=receipt.source_delta_count,
                    duration_ms=max(0, round((perf_counter() - projection_started) * 1_000)),
                    state=receipt.projection_status.value,
                )

            result = self._host.run_turn(
                RuntimeTurnRequest(
                    thread=thread,
                    input=(RuntimeInput(input_text),),
                    tools=registry,
                    effort=(
                        "low"
                        if registry.intake_mode
                        else None
                    ),
                    timeout_seconds=(
                        _DIRECTION_INTAKE_TIMEOUT_SECONDS
                        if registry.intake_mode
                        else None
                    ),
                    max_visible_text_chars=(
                        _DIRECTION_INTAKE_MAX_VISIBLE_TEXT_CHARS
                        if registry.intake_mode
                        else None
                    ),
                    max_reasoning_text_chars=(
                        _DIRECTION_INTAKE_MAX_REASONING_TEXT_CHARS
                        if registry.intake_mode
                        else None
                    ),
                ),
                control_reader=control_reader.read,
                initial_input_revision=leased.input_revision,
                event_observer=project_live_event,
                poll_interval_s=0.2,
                timeout_s=(
                    _DIRECTION_INTAKE_TIMEOUT_SECONDS + 15
                    if registry.intake_mode
                    else self._settings.codex_runtime_turn_timeout_seconds + 30
                ),
            )
            result = _ensure_terminal_event(result)
            log_safe_event(
                logger, "codex_planning_runtime_result", level=logging.INFO,
                run_id=run_id, conversation_id=leased.conversation_id,
                code=result.safe_error_code, state=result.terminal_status.value,
                termination_reason=result.metrics.termination_reason,
                visible_chars=result.metrics.message_text_chars,
                reasoning_chars=result.metrics.reasoning_text_chars,
                total_text_chars=result.metrics.visible_text_chars,
                effective_max_visible_chars=result.metrics.effective_max_visible_text_chars,
                effective_max_reasoning_chars=result.metrics.effective_max_reasoning_text_chars,
                effective_max_total_chars=result.metrics.effective_max_total_text_chars,
                effective_timeout_seconds=result.metrics.effective_timeout_seconds,
                tool_count=registry.call_count, tool_repair_count=registry.repair_count,
                runtime_generation=thread.generation,
            )
            terminal_event, terminal_sequence = _runtime_terminal_event(result)
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
            direction_action = registry.planning_direction_action
            receipt_source = "model_candidate"
            if direction_action is None:
                direction_action = PlanningDirectionAction.CLARIFY_DIRECTION
                receipt_source = _direction_fallback_source(registry, result)
            elif (
                direction_action is PlanningDirectionAction.CONTINUE_MAINLINE
                and not registry.intake_mode
                and not registry.draft_completed
            ):
                direction_action = PlanningDirectionAction.CLARIFY_DIRECTION
                receipt_source = "server_fallback_action_postcondition"
            server_terminalized = (
                registry.intake_mode
                or receipt_source != "model_candidate"
                or direction_action
                in {
                    PlanningDirectionAction.CLARIFY_DIRECTION,
                    PlanningDirectionAction.CONFIRMED_SWITCH,
                    PlanningDirectionAction.ANSWER_AND_REFOCUS,
                }
            )
            if server_terminalized and not _direction_server_terminalization_allowed(
                registry,
                result,
            ):
                failed_result = _direction_failure_result(registry, result)
                occurred_at = datetime.now(UTC)
                for index, event in enumerate(failed_result.events, start=1):
                    projector.project_event(
                        event,
                        sequence=event.sequence or index,
                        occurred_at=occurred_at,
                        defer_public_message=(
                            event.kind is RuntimeEventKind.MESSAGE_COMPLETED
                            and event.phase in {None, "final_answer"}
                        ),
                    )
                return _run_result(
                    repository.read_run_state(user_id=user_id, run_id=run_id)
                )
            if server_terminalized:
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
                continuation_kind = TutorContinuationKind.PLANNING_INPUT
                planning_intent_hint = None
                facts = PostgresPlanningFactRepository(conn)
                receipt_action = direction_action
                with conn.transaction():
                    if direction_action is PlanningDirectionAction.CONFIRMED_SWITCH:
                        facts.record_input(
                            user_id=user_id,
                            run_id=run_id,
                            conversation_id=current.conversation_id,
                            message_id=_read_input_message_id(
                                conn,
                                run_id=run_id,
                                input_revision=current.input_revision,
                            ),
                            input_revision=current.input_revision,
                            content=_read_input_text(
                                conn,
                                run_id=run_id,
                                input_revision=current.input_revision,
                            ),
                            reopen_fields=tuple(
                                field.value
                                for field in PLANNING_DIRECTION_SWITCH_REOPEN_FIELDS
                            ),
                            intent_resolution_enabled=(
                                self._settings.tutor_planning_intent_enabled
                            ),
                        )
                        missing = facts.missing_fields_for_run(
                            user_id=user_id,
                            run_id=run_id,
                        )
                        if not missing:
                            raise RuntimeError(
                                "confirmed planning switch left no missing direction fact"
                            )
                        awaiting_field = _next_switch_field(missing)
                        if awaiting_field is PlanningFactField.LANGUAGE_ID:
                            deterministic = PlanningIntentResolver(conn).resolve_for_run(
                                user_id=user_id,
                                run_id=run_id,
                                expected_input_revision=current.input_revision,
                            )
                            if deterministic.resolution not in {"shortlist", "conflict"}:
                                continuation_kind = TutorContinuationKind.CLARIFICATION
                                prompt = _confirmed_switch_language_clarification()
                            else:
                                prompt = _confirmed_switch_prompt(awaiting_field)
                        else:
                            prompt = _confirmed_switch_prompt(awaiting_field)
                    elif direction_action is PlanningDirectionAction.CLARIFY_DIRECTION:
                        continuation_kind = TutorContinuationKind.CLARIFICATION
                        prompt = _direction_clarification_prompt()
                    else:
                        if awaiting_field is None:
                            continuation_kind = TutorContinuationKind.CLARIFICATION
                            prompt = _direction_clarification_prompt()
                            receipt_action = PlanningDirectionAction.CLARIFY_DIRECTION
                            receipt_source = "server_fallback_action_postcondition"
                        elif direction_action is PlanningDirectionAction.ANSWER_AND_REFOCUS:
                            candidate = _answer_and_refocus_prompt(result, awaiting_field)
                            if candidate is None:
                                continuation_kind = TutorContinuationKind.CLARIFICATION
                                prompt = _direction_clarification_prompt()
                                receipt_action = PlanningDirectionAction.CLARIFY_DIRECTION
                                receipt_source = (
                                    "server_fallback_action_postcondition"
                                )
                            else:
                                prompt = candidate
                        else:
                            prompt = _planning_input_prompt(awaiting_field)
                        if (
                            continuation_kind is TutorContinuationKind.PLANNING_INPUT
                            and awaiting_field is PlanningFactField.LANGUAGE_ID
                            and self._settings.tutor_planning_intent_enabled
                        ):
                            planning_intent_hint = _planning_intent_hint(registry)
                            deterministic = PlanningIntentResolver(conn).resolve_for_run(
                                user_id=user_id,
                                run_id=run_id,
                                expected_input_revision=current.input_revision,
                            )
                            if (
                                planning_intent_hint is None
                                and deterministic.resolution
                                not in {"shortlist", "conflict"}
                            ):
                                continuation_kind = TutorContinuationKind.CLARIFICATION
                                prompt = _language_implementation_clarification()
                    if continuation_kind is TutorContinuationKind.PLANNING_INPUT:
                        if awaiting_field is None:
                            raise RuntimeError("Tutor planning request field is missing")
                        facts.record_question_asked(run=current, field=awaiting_field)
                    typed_result = TutorRunResult(
                        run_id=run_id,
                        status=TutorRunStatus.COMPLETED,
                        input_revision=current.input_revision,
                        iteration_count=current.iteration_count + 1,
                        model_call_count=current.model_call_count + 1,
                        capability_call_count=(
                            current.capability_call_count + registry.call_count
                        ),
                        effect_count=current.effect_count,
                        terminal_outcome=TutorTerminalOutcome.COMPLETED,
                        public_message=prompt,
                        completion_reason=TutorTurnCompletionReason.AWAITING_USER,
                    )
                    projection_repository.discard_streaming_text_items_for_server_terminalization(
                        binding_id=binding.binding_id,
                        fence=final_fence,
                        thread_id=terminal_event.thread_id,
                        turn_id=terminal_event.turn_id,
                        sequence=terminal_sequence,
                        occurred_at=occurred_at,
                    )
                    repository.record_interaction_request(
                        user_id=user_id,
                        lease=lease,
                        decision=TutorDecision(
                            public_message=prompt,
                            question_key=(
                                cast(TutorPlanningQuestionKey, awaiting_field.value)
                                if continuation_kind
                                is TutorContinuationKind.PLANNING_INPUT
                                and awaiting_field is not None
                                else None
                            ),
                            planning_intent_hint=planning_intent_hint,
                            checkpoint_reason=TutorCheckpointReason.CAPABILITY_RESULT,
                            continuation_kind=continuation_kind,
                        ),
                        result=typed_result,
                        created_at=occurred_at,
                        intent_resolution_enabled=(
                            self._settings.tutor_planning_intent_enabled
                        ),
                    )
                    message = conn.execute(
                        "SELECT tutor_message_id FROM tutor_run_public_processes "
                        "WHERE run_id = %s",
                        (run_id,),
                    ).fetchone()
                    if message is None or message.get("tutor_message_id") is None:
                        raise RuntimeError(
                            "Tutor typed planning request message is missing"
                        )
                    projection_repository.finalize_typed_request_binding(
                        binding_id=binding.binding_id,
                        user_id=user_id,
                        message_id=str(message["tutor_message_id"]),
                        occurred_at=occurred_at,
                    )
                    facts_fingerprint = _planning_facts_fingerprint(
                        conn,
                        user_id=user_id,
                        run_id=run_id,
                    )
                    repository.record_planning_direction_resolution(
                        user_id=user_id,
                        run_id=run_id,
                        input_revision=current.input_revision,
                        direction_action=receipt_action.value,
                        result_kind=continuation_kind.value,
                        source=receipt_source,
                        question_key=(
                            awaiting_field.value
                            if continuation_kind
                            is TutorContinuationKind.PLANNING_INPUT
                            and awaiting_field is not None
                            else None
                        ),
                        facts_fingerprint=facts_fingerprint,
                        public_message_hash=_sha256_text(prompt),
                    )
                    projector.project_event(
                        terminal_event,
                        sequence=terminal_sequence,
                        occurred_at=occurred_at,
                    )
                return _run_result(
                    repository.read_run_state(user_id=user_id, run_id=run_id)
                )
            projector.project_result(result, occurred_at=datetime.now(UTC))
            state = repository.read_run_state(user_id=user_id, run_id=run_id)
            if (
                state.terminal_outcome is TutorTerminalOutcome.COMPLETED
                and direction_action is PlanningDirectionAction.CONTINUE_MAINLINE
                and registry.draft_completed
            ):
                _record_completed_draft_direction_receipt(
                    conn,
                    repository=repository,
                    binding_id=binding.binding_id,
                    user_id=user_id,
                    run_id=run_id,
                    input_revision=current.input_revision,
                )
                state = repository.read_run_state(user_id=user_id, run_id=run_id)
            return _run_result(state)


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


def _planning_intent_hint(
    registry: LearningPlanRuntimeToolRegistry,
) -> TutorPlanningIntentHint | None:
    payload = registry.planning_intent_hint
    if payload is None:
        return None
    raw_candidates = payload.get("candidate_language_ids")
    if not isinstance(raw_candidates, list | tuple):
        return None
    try:
        return TutorPlanningIntentHint(
            schema_version="planning-intent-hint-v2",
            candidate_language_ids=tuple(str(item) for item in raw_candidates),
            confidence=cast(TutorPlanningIntentConfidence, str(payload.get("confidence") or "")),
            reason_code=cast(TutorPlanningIntentReasonCode, str(payload.get("reason_code") or "")),
        )
    except ValueError:
        return None


def _final_answer_text(result: RuntimeTurnResult, *, fallback: str = "") -> str:
    for event in reversed(result.events):
        if (
            event.kind is RuntimeEventKind.MESSAGE_COMPLETED
            and event.phase in {None, "final_answer"}
            and event.visible_text
        ):
            return event.visible_text.strip()
    return fallback


def _direction_fallback_source(
    registry: LearningPlanRuntimeToolRegistry,
    result: RuntimeTurnResult,
) -> str:
    if registry.direction_protocol_invalid:
        return "server_fallback_invalid_direction"
    return "server_fallback_missing_direction"


def _direction_server_terminalization_allowed(
    registry: LearningPlanRuntimeToolRegistry,
    result: RuntimeTurnResult,
) -> bool:
    if result.safe_error_code in _DIRECTION_BOUND_CODES:
        return False
    if result.terminal_status is RuntimeTerminalStatus.INTERRUPTED:
        return False
    if result.terminal_status is RuntimeTerminalStatus.UNAVAILABLE:
        return False
    if result.terminal_status is RuntimeTerminalStatus.FAILED:
        return False
    for item in registry.results:
        if item.code in _DIRECTION_BOUND_CODES:
            return False
        if item.status in {
            LearningPlanToolStatus.CONFLICT,
            LearningPlanToolStatus.POLICY_BLOCKED,
            LearningPlanToolStatus.UNAVAILABLE,
        }:
            return False
        if (
            item.status is LearningPlanToolStatus.FATAL
            and item.code not in _DIRECTION_BOUND_CODES
            and item.code not in _DIRECTION_PROTOCOL_FATAL_CODES
        ):
            return False
    return True


def _direction_failure_result(
    registry: LearningPlanRuntimeToolRegistry,
    result: RuntimeTurnResult,
) -> RuntimeTurnResult:
    safe_error_code = result.safe_error_code
    if safe_error_code is None:
        for item in reversed(registry.results):
            if item.status in {
                LearningPlanToolStatus.CONFLICT,
                LearningPlanToolStatus.POLICY_BLOCKED,
                LearningPlanToolStatus.UNAVAILABLE,
                LearningPlanToolStatus.FATAL,
            }:
                safe_error_code = item.code
                break
    safe_error_code = safe_error_code or "planning_direction_resolution_failed"
    terminal_status = result.terminal_status
    if terminal_status is RuntimeTerminalStatus.COMPLETED:
        terminal_status = RuntimeTerminalStatus.UNAVAILABLE
    events = tuple(
        RuntimeEvent(
            RuntimeEventKind.TURN_COMPLETED,
            event.thread_id,
            event.turn_id,
            terminal_status=terminal_status,
            safe_code=safe_error_code,
            sequence=event.sequence,
        )
        if event.kind is RuntimeEventKind.TURN_COMPLETED
        else event
        for event in result.events
    )
    return RuntimeTurnResult(
        result.thread,
        result.turn_id,
        terminal_status,
        events,
        safe_error_code,
        result.metrics,
    )


def _planning_input_prompt(field: PlanningFactField) -> str:
    return planning_question_prompt(field)


def _answer_and_refocus_prompt(
    result: RuntimeTurnResult,
    field: PlanningFactField,
) -> str | None:
    exact_question = planning_question_prompt(field)
    candidate = _final_answer_text(result)
    if (
        not candidate
        or candidate == exact_question
        or len(candidate) > 1_200
        or not candidate.endswith(exact_question)
        or _question_count(candidate) != 1
        or check_teaching_output(candidate).blocked
    ):
        return None
    return candidate


def _direction_clarification_prompt() -> str:
    return _DIRECTION_CLARIFICATION_PROMPT


def _language_implementation_clarification() -> str:
    return "你希望使用哪种实现语言、框架变体或运行环境？"


def _confirmed_switch_prompt(field: PlanningFactField) -> str:
    return f"已停止旧方向。{planning_question_prompt(field)}"


def _confirmed_switch_language_clarification() -> str:
    return "已停止旧方向。新方向需要使用哪种实现语言、框架变体或运行环境？"


def _planning_facts_fingerprint(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    run_id: str,
) -> str:
    session = conn.execute(
        """
        SELECT sessions.id::text AS id
        FROM tutor_learning_plan_sessions AS sessions
        JOIN tutor_runs AS runs
          ON runs.conversation_id = sessions.conversation_id
         AND runs.user_id = sessions.user_id
        JOIN tutor_run_learning_scopes AS scopes
          ON scopes.run_id = runs.id
         AND scopes.user_id = runs.user_id
         AND scopes.conversation_id = runs.conversation_id
        WHERE sessions.user_id = %s
          AND runs.id = %s
          AND runs.origin = 'interactive'
          AND sessions.status IN ('collecting', 'draft_ready')
          AND scopes.scope_kind = 'plan_drafting'
          AND scopes.task_kind = 'plan_drafting'
        """,
        (user_id, run_id),
    ).fetchone()
    if session is None:
        raise RuntimeError("planning session is missing for direction receipt")
    _values, fingerprint, _revision, _missing = (
        PostgresPlanningFactRepository(conn).profile_fact_state(
            user_id=user_id,
            session_id=str(session["id"]),
        )
    )
    return fingerprint


def _record_completed_draft_direction_receipt(
    conn: Connection[dict[str, object]],
    *,
    repository: PostgresTutorRepository,
    binding_id: str,
    user_id: str,
    run_id: str,
    input_revision: int,
) -> None:
    row = conn.execute(
        """
        SELECT bindings.final_message_id::text AS message_id, messages.content
        FROM tutor_run_runtime_bindings AS bindings
        JOIN tutor_messages AS messages ON messages.id = bindings.final_message_id
        WHERE bindings.id = %s AND bindings.user_id = %s AND bindings.run_id = %s
        """,
        (binding_id, user_id, run_id),
    ).fetchone()
    if row is None or not str(row.get("content") or ""):
        raise RuntimeError("completed planning draft message is missing")
    repository.record_planning_direction_resolution(
        user_id=user_id,
        run_id=run_id,
        input_revision=input_revision,
        direction_action=PlanningDirectionAction.CONTINUE_MAINLINE.value,
        result_kind="plan_draft",
        source="model_candidate",
        facts_fingerprint=_planning_facts_fingerprint(
            conn,
            user_id=user_id,
            run_id=run_id,
        ),
        public_message_hash=_sha256_text(str(row["content"])),
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _next_switch_field(missing: tuple[PlanningFactField, ...]) -> PlanningFactField:
    for field in (PlanningFactField.LANGUAGE_ID, PlanningFactField.GOAL_TEXT):
        if field in missing:
            return field
    return missing[0]


def _question_count(value: str) -> int:
    return value.count("？") + value.count("?")


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
    row = _read_input_row(conn, run_id=run_id, input_revision=input_revision)
    return str(row["content"])


def _read_input_message_id(
    conn: Connection[dict[str, object]],
    *,
    run_id: str,
    input_revision: int,
) -> str:
    row = _read_input_row(conn, run_id=run_id, input_revision=input_revision)
    return str(row["message_id"])


def _read_input_row(
    conn: Connection[dict[str, object]],
    *,
    run_id: str,
    input_revision: int,
) -> Mapping[str, object]:
    row = conn.execute(
        """
        SELECT messages.id::text AS message_id, messages.content
        FROM tutor_run_input_events AS inputs
        JOIN tutor_messages AS messages ON messages.id = inputs.message_id
        WHERE inputs.run_id = %s AND inputs.input_revision = %s
        """,
        (run_id, input_revision),
    ).fetchone()
    if row is None:
        raise RuntimeError("Tutor Codex input is missing")
    return row


def _runtime_terminal_event(result: RuntimeTurnResult) -> tuple[RuntimeEvent, int]:
    for index, event in enumerate(result.events, start=1):
        if event.kind is RuntimeEventKind.TURN_COMPLETED:
            return event, event.sequence or index
    raise RuntimeError("Tutor Codex Runtime result is missing a terminal event")


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
