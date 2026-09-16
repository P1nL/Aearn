from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Iterator, Mapping
from uuid import uuid4

import pytest

import app.services.tutor.interactive as interactive_module
from app.agents.harness.contracts import (
    TutorPolicySnapshot,
    TutorRunResult,
    TutorRunSnapshot,
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
    RuntimeToolCall,
    RuntimeTurnRequest,
    RuntimeTurnResult,
)
from app.agents.runtime.tutor_projection import TutorRuntimeEventProjector
from app.agents.runtime.worker_host import (
    RuntimeTurnControlDirective,
    _run_controlled_turn,
)
from app.core.config import DEEPSEEK_V4_FLASH_MODEL, Settings
from app.services.learning.contracts import LearningScope, LearningScopeKind
from app.services.learning.plan_repository import PostgresLearningPlanSessionRepository
from app.services.learning.plan_tools import PlanningDirectionAction
from app.services.learning.planning_facts import PlanningFactField, PostgresPlanningFactRepository
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
_DIRECTION_CLARIFICATION = (
    "你刚才的最新输入可能与当前计划方向不一致：这是对当前目标的补充、"
    "一个临时问题，还是你希望切换学习方向？"
)


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


def _valid_draft_modules() -> list[dict[str, object]]:
    return [
        {
            "stable_key": "foundations",
            "title": "Python 基础",
            "nodes": [
                {
                    "stable_key": "python.variables",
                    "title": "变量与数据流",
                    "required_capabilities": ["python"],
                }
            ],
        },
        {
            "stable_key": "automation",
            "title": "自动化实践",
            "nodes": [
                {
                    "stable_key": "python.files",
                    "title": "文件自动化",
                    "prerequisites": ["python.variables"],
                    "required_capabilities": ["python"],
                }
            ],
        },
    ]


def _direction_receipt(conn, run_id: str) -> dict[str, object]:  # type: ignore[no-untyped-def]
    rows = conn.execute(
        """
        SELECT payload_json
        FROM tutor_run_events
        WHERE run_id = %s AND kind = 'planning_direction_resolved'
        ORDER BY event_sequence
        """,
        (run_id,),
    ).fetchall()
    assert len(rows) == 1
    payload = rows[0]["payload_json"]
    assert isinstance(payload, dict)
    return payload


class _FakeCodexHost:
    def __init__(
        self,
        *,
        direction_action: PlanningDirectionAction | None = (
            PlanningDirectionAction.CONTINUE_MAINLINE
        ),
        planning_intent_hint: Mapping[str, object] | None = None,
        extra_direction_action: PlanningDirectionAction | None = None,
        final_text: str = (
            "我已根据当前信息准备计划草稿；请在右侧检查后由 Aearn 确认。"
        ),
        safe_error_code: str | None = None,
        include_reasoning: bool = False,
        completed_reasoning_text: str = "先核对最新输入与当前服务端事实。",
        streaming_reasoning_text: str | None = None,
        streaming_final_answer_text: str | None = None,
    ) -> None:
        self.direction_action = direction_action
        self.planning_intent_hint = (
            dict(planning_intent_hint)
            if planning_intent_hint is not None
            else None
        )
        self.extra_direction_action = extra_direction_action
        self.final_text = final_text
        self.safe_error_code = safe_error_code
        self.include_reasoning = include_reasoning
        self.completed_reasoning_text = completed_reasoning_text
        self.streaming_reasoning_text = streaming_reasoning_text
        self.streaming_final_answer_text = streaming_final_answer_text
        self.thread_requests: list[RuntimeThreadRequest] = []
        self.resumed_thread_ids: list[str] = []
        self.turn_requests: list[RuntimeTurnRequest] = []
        self.turn_count = 0

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

    def resume_thread(
        self,
        thread_id: str,
        *,
        timeout_s: float = 30.0,
    ) -> RuntimeThreadHandle:
        del timeout_s
        self.resumed_thread_ids.append(thread_id)
        return RuntimeThreadHandle(thread_id, 7)

    def compact_thread(
        self,
        thread: RuntimeThreadHandle,
        *,
        timeout_s: float = 30.0,
    ) -> None:
        del thread, timeout_s

    def run_turn(
        self,
        request: RuntimeTurnRequest,
        *,
        control_reader,  # type: ignore[no-untyped-def]
        initial_input_revision: int,
        event_observer=None,  # type: ignore[no-untyped-def]
        poll_interval_s: float = 0.2,
        timeout_s: float = 330.0,
    ) -> RuntimeTurnResult:
        del control_reader, initial_input_revision, poll_interval_s, timeout_s
        self.turn_requests.append(request)
        self.turn_count += 1
        turn_id = f"turn-cutover-{self.turn_count}"
        read_result = asyncio.run(
            request.tools.invoke(
                RuntimeToolCall(
                    request.thread.thread_id,
                    turn_id,
                    f"context-read-{self.turn_count}",
                    "aearn_planning_context_read",
                    {"schema_version": "aearn-learning-plan-tools-v1"},
                )
            )
        )
        action_result = None
        if self.direction_action is not None:
            follow_up: dict[str, object] = {
                "schema_version": "aearn-learning-plan-tools-v1",
                "direction_action": self.direction_action.value,
            }
            if self.planning_intent_hint is not None:
                follow_up["planning_intent_hint"] = self.planning_intent_hint
            action_result = asyncio.run(
                request.tools.invoke(
                    RuntimeToolCall(
                        request.thread.thread_id,
                        turn_id,
                        f"direction-action-{self.turn_count}",
                        "aearn_planning_context_read",
                        follow_up,
                    )
                )
            )
        if self.extra_direction_action is not None:
            asyncio.run(
                request.tools.invoke(
                    RuntimeToolCall(
                        request.thread.thread_id,
                        turn_id,
                        f"extra-direction-action-{self.turn_count}",
                        "aearn_planning_context_read",
                        {
                            "schema_version": "aearn-learning-plan-tools-v1",
                            "direction_action": self.extra_direction_action.value,
                        },
                    )
                )
            )
        if action_result is not None:
            action_payload = json.loads(action_result.content)
            if (
                self.direction_action is PlanningDirectionAction.CONTINUE_MAINLINE
                and action_payload.get("status") == "completed"
            ):
                asyncio.run(
                    request.tools.invoke(
                        RuntimeToolCall(
                            request.thread.thread_id,
                            turn_id,
                            f"draft-{self.turn_count}",
                            "aearn_learning_plan_draft",
                            {"modules": _valid_draft_modules()},
                        )
                    )
                )
        del read_result
        events: list[RuntimeEvent] = [
            RuntimeEvent(RuntimeEventKind.TURN_STARTED, "thread-cutover", turn_id)
        ]
        if self.include_reasoning:
            reasoning_text = self.completed_reasoning_text
            events.extend(
                [
                    RuntimeEvent(
                        RuntimeEventKind.REASONING_STARTED,
                        "thread-cutover",
                        turn_id,
                        item_id=f"reasoning-{self.turn_count}",
                    ),
                    RuntimeEvent(
                        RuntimeEventKind.REASONING_DELTA,
                        "thread-cutover",
                        turn_id,
                        item_id=f"reasoning-{self.turn_count}",
                        visible_text=reasoning_text,
                        content_sha256=__import__("hashlib").sha256(
                            reasoning_text.encode("utf-8")
                        ).hexdigest(),
                    ),
                    RuntimeEvent(
                        RuntimeEventKind.REASONING_COMPLETED,
                        "thread-cutover",
                        turn_id,
                        item_id=f"reasoning-{self.turn_count}",
                    ),
                ]
            )
        if self.streaming_reasoning_text is not None:
            events.extend(
                [
                    RuntimeEvent(
                        RuntimeEventKind.REASONING_STARTED,
                        "thread-cutover",
                        turn_id,
                        item_id=f"reasoning-streaming-{self.turn_count}",
                    ),
                    RuntimeEvent(
                        RuntimeEventKind.REASONING_DELTA,
                        "thread-cutover",
                        turn_id,
                        item_id=f"reasoning-streaming-{self.turn_count}",
                        visible_text=self.streaming_reasoning_text,
                        content_sha256=__import__("hashlib").sha256(
                            self.streaming_reasoning_text.encode("utf-8")
                        ).hexdigest(),
                    ),
                ]
            )
        if self.streaming_final_answer_text is not None:
            events.extend(
                [
                    RuntimeEvent(
                        RuntimeEventKind.MESSAGE_STARTED,
                        "thread-cutover",
                        turn_id,
                        item_id=f"message-final-{self.turn_count}",
                        phase="final_answer",
                    ),
                    RuntimeEvent(
                        RuntimeEventKind.MESSAGE_DELTA,
                        "thread-cutover",
                        turn_id,
                        item_id=f"message-final-{self.turn_count}",
                        visible_text=self.streaming_final_answer_text,
                        content_sha256=__import__("hashlib").sha256(
                            self.streaming_final_answer_text.encode("utf-8")
                        ).hexdigest(),
                        phase="final_answer",
                    ),
                ]
            )
        terminal = RuntimeTerminalStatus.COMPLETED
        if self.safe_error_code is None:
            text = self.final_text
            events.append(
                RuntimeEvent(
                    RuntimeEventKind.MESSAGE_COMPLETED,
                    "thread-cutover",
                    turn_id,
                    item_id=f"message-final-{self.turn_count}",
                    visible_text=text,
                    content_sha256=__import__("hashlib").sha256(
                        text.encode("utf-8")
                    ).hexdigest(),
                    phase="final_answer",
                )
            )
        else:
            terminal = RuntimeTerminalStatus.UNAVAILABLE
        events.append(
            RuntimeEvent(
                RuntimeEventKind.TURN_COMPLETED,
                "thread-cutover",
                turn_id,
                terminal_status=terminal,
                safe_code=self.safe_error_code,
            )
        )
        if event_observer is not None:
            for sequence, event in enumerate(events, start=1):
                event_observer(event, sequence)
        return RuntimeTurnResult(
            request.thread,
            turn_id,
            terminal,
            tuple(events),
            self.safe_error_code,
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
    accepted = repository.accept_input(
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
    PostgresPlanningFactRepository(conn).record_input(
        user_id=tutor_persistence.user_id,
        run_id=run.run_id,
        conversation_id=conversation_id,
        message_id=accepted.message_id,
        input_revision=accepted.input_revision,
        content="",
        explicit_facts={
            "language_id": "python",
            "goal_text": "构建可靠的自动化工具",
            "target_level": "intermediate",
            "weekly_minutes": 240,
            "experience_level": "beginner",
            "teaching_preferences": ["examples_first", "practice_heavy"],
            "pace_constraints": "每周安排四次专注学习",
        },
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
    instructions = str(host.thread_requests[0].base_instructions)
    assert "禁止调用 Codex 内置 request_user_input" in instructions
    assert "data.next_missing_fact" in instructions
    assert "逐字 exact_question" in instructions
    assert "language_id 始终表示要学习的编程语言或课程" in instructions
    assert "不表示教学内容使用的自然语言" in instructions
    assert "最新 learner input" in instructions
    assert "persistent Codex thread" in instructions
    assert "continue_mainline" in instructions
    assert "answer_and_refocus" in instructions
    assert "clarify_direction" in instructions
    assert "confirmed_switch" in instructions
    assert "不使用关键词列表" in instructions
    assert "固定的单一方向澄清问题" in instructions
    assert "中文、英文" not in instructions
    assert "英文" not in instructions
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
    receipt = _direction_receipt(conn, run.run_id)
    assert receipt["direction_action"] == "continue_mainline"
    assert receipt["result_kind"] == "plan_draft"
    assert receipt["source"] == "model_candidate"
    assert "learner_text" not in receipt
    assert "rationale" not in receipt
    messages = conn.execute(
        "SELECT role, content FROM tutor_messages WHERE conversation_id = %s ORDER BY created_at, id",
        (conversation_id,),
    ).fetchall()
    assert [row["role"] for row in messages] == ["learner", "tutor"]
    assert "Aearn 确认" in str(messages[-1]["content"])


def test_codex_dispatcher_reuses_one_conversation_thread_for_fresh_runs(
    tutor_persistence,
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
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

    def create_run(content: str):  # type: ignore[no-untyped-def]
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
            idempotency_key=f"codex-thread-reuse-{uuid4().hex}",
            content=content,
            received_at=datetime.now(UTC),
        )
        PostgresLearningTrackRepository(conn).snapshot_run_scope(
            user_id=tutor_persistence.user_id,
            run_id=run.run_id,
            explicit_scope=LearningScope(scope_kind=LearningScopeKind.PLAN_DRAFTING),
        )
        return run, accepted

    @contextmanager
    def same_connection():  # type: ignore[no-untyped-def]
        yield conn

    host = _FakeCodexHost()
    dispatcher = CodexTutorRunDispatcher(
        settings=_settings(codex_runtime_home_directory=str(tmp_path / "runtime-home")),
        host=host,
        connection_factory=same_connection,
        manage_autocommit=False,
    )
    first, first_input = create_run("请先给我一个 Python 学习建议。")
    PostgresPlanningFactRepository(conn).record_input(
        user_id=tutor_persistence.user_id,
        run_id=first.run_id,
        conversation_id=conversation_id,
        message_id=first_input.message_id,
        input_revision=first_input.input_revision,
        content="",
        explicit_facts={
            "language_id": "python",
            "goal_text": "构建可靠的自动化工具",
            "target_level": "intermediate",
            "weekly_minutes": 240,
            "experience_level": "beginner",
            "teaching_preferences": ["examples_first", "practice_heavy"],
            "pace_constraints": "每周安排四次专注学习",
        },
    )
    dispatcher.dispatch(user_id=tutor_persistence.user_id, run_id=first.run_id)
    latest_direction = "停止旧网站方向，改为学习 Python 自动化。"
    second, second_input = create_run(latest_direction)
    facts = PostgresPlanningFactRepository(conn)
    facts.record_input(
        user_id=tutor_persistence.user_id,
        run_id=second.run_id,
        conversation_id=conversation_id,
        message_id=second_input.message_id,
        input_revision=second_input.input_revision,
        content=latest_direction,
    )
    host.direction_action = PlanningDirectionAction.CONFIRMED_SWITCH
    host.final_text = "已切换到新的学习方向。"
    dispatcher.dispatch(user_id=tutor_persistence.user_id, run_id=second.run_id)

    assert len(host.thread_requests) == 1
    assert host.resumed_thread_ids == ["thread-cutover"]
    assert tuple(item.text for item in host.turn_requests[1].input) == (latest_direction,)
    instructions = str(host.thread_requests[0].base_instructions)
    assert "最新 learner input" in instructions
    assert "旧 thread 只能帮助解释" in instructions
    assert "不能无确认地补全网站、图片、HTML" in instructions
    thread_rows = conn.execute(
        "SELECT external_thread_id, migration_mode FROM tutor_conversation_runtime_threads WHERE user_id = %s AND conversation_id = %s",
        (tutor_persistence.user_id, conversation_id),
    ).fetchall()
    assert thread_rows == [{"external_thread_id": "thread-cutover", "migration_mode": "native"}]
    binding_rows = conn.execute(
        """
        SELECT external_thread_id, external_turn_id
        FROM tutor_run_runtime_bindings
        WHERE user_id = %s AND conversation_id = %s
        ORDER BY created_at, id
        """,
        (tutor_persistence.user_id, conversation_id),
    ).fetchall()
    assert [str(row["external_thread_id"]) for row in binding_rows] == [
        "thread-cutover",
        "thread-cutover",
    ]
    assert len({str(row["external_turn_id"]) for row in binding_rows}) == 2
    switch_request = conn.execute(
        """
        SELECT kind, question_key, descriptor_json
        FROM tutor_interaction_requests
        WHERE source_turn_id = %s
        """,
        (second.run_id,),
    ).fetchone()
    assert switch_request is not None
    assert switch_request["kind"] == "planning_input"
    assert switch_request["question_key"] == "goal_text"
    assert switch_request["descriptor_json"]["prompt"] == "你希望通过这次学习完成什么具体目标？"
    session = conn.execute(
        "SELECT id::text AS id FROM tutor_learning_plan_sessions WHERE user_id = %s AND conversation_id = %s",
        (tutor_persistence.user_id, conversation_id),
    ).fetchone()
    assert session is not None
    values, _fingerprint, _revision, missing = facts.profile_fact_state(
        user_id=tutor_persistence.user_id,
        session_id=str(session["id"]),
    )
    assert values[PlanningFactField.LANGUAGE_ID] == "python"
    assert PlanningFactField.GOAL_TEXT in missing
    assert PlanningFactField.TARGET_LEVEL in missing
    assert PlanningFactField.EXPERIENCE_LEVEL in missing
    assert values[PlanningFactField.WEEKLY_MINUTES] == 240
    assert values[PlanningFactField.TEACHING_PREFERENCES] == [
        "examples_first",
        "practice_heavy",
    ]
    assert values[PlanningFactField.PACE_CONSTRAINTS] == (
        "每周安排四次专注学习"
    )
    switch_receipt = _direction_receipt(conn, second.run_id)
    assert switch_receipt["direction_action"] == "confirmed_switch"
    assert switch_receipt["result_kind"] == "planning_input"
    assert switch_receipt["question_key"] == "goal_text"


def test_codex_missing_facts_create_server_typed_request(
    tutor_persistence,
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
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
    accepted = repository.accept_input(
        user_id=tutor_persistence.user_id,
        run_id=run.run_id,
        idempotency_key=f"codex-typed-request-{uuid4().hex}",
        content="我想学习 Python，而且目前是零基础。",
        received_at=datetime.now(UTC),
    )
    PostgresLearningTrackRepository(conn).snapshot_run_scope(
        user_id=tutor_persistence.user_id,
        run_id=run.run_id,
        explicit_scope=LearningScope(scope_kind=LearningScopeKind.PLAN_DRAFTING),
    )
    PostgresPlanningFactRepository(conn).record_input(
        user_id=tutor_persistence.user_id,
        run_id=run.run_id,
        conversation_id=conversation_id,
        message_id=accepted.message_id,
        input_revision=accepted.input_revision,
        content="我想学习 Python，而且目前是零基础。",
        explicit_facts={"language_id": "python", "experience_level": "new"},
    )

    @contextmanager
    def same_connection():  # type: ignore[no-untyped-def]
        yield conn

    answer_and_refocus = (
        "DNS 是把域名映射到网络地址的系统。我们回到学习计划主线："
        "你希望通过这次学习完成什么具体目标？"
    )
    result = CodexTutorRunDispatcher(
        settings=_settings(codex_runtime_home_directory=str(tmp_path / "runtime-home")),
        host=_FakeCodexHost(
            direction_action=PlanningDirectionAction.ANSWER_AND_REFOCUS,
            final_text=answer_and_refocus,
        ),
        connection_factory=same_connection,
        manage_autocommit=False,
    ).dispatch(user_id=tutor_persistence.user_id, run_id=run.run_id)

    assert result.terminal_outcome is TutorTerminalOutcome.COMPLETED
    assert result.completion_reason is not None
    request = conn.execute(
        """
        SELECT question_key, state, descriptor_json
        FROM tutor_interaction_requests
        WHERE source_turn_id = %s
        """,
        (run.run_id,),
    ).fetchone()
    assert request is not None
    assert request["question_key"] == "goal_text"
    assert request["state"] == "pending"
    assert request["descriptor_json"]["prompt"] == "你希望通过这次学习完成什么具体目标？"
    tutor_message = conn.execute(
        "SELECT content FROM tutor_messages WHERE conversation_id = %s AND role = 'tutor'",
        (conversation_id,),
    ).fetchone()
    assert tutor_message == {"content": answer_and_refocus}
    assert answer_and_refocus.count("？") == 1
    binding = conn.execute(
        "SELECT state, final_message_id FROM tutor_run_runtime_bindings WHERE run_id = %s",
        (run.run_id,),
    ).fetchone()
    assert binding is not None and binding["state"] == "completed"
    text_items = conn.execute(
        "SELECT channel, state, public_message_id FROM tutor_runtime_text_items WHERE run_id = %s",
        (run.run_id,),
    ).fetchall()
    assert text_items == [
        {
            "channel": "final_answer",
            "state": "completed",
            "public_message_id": binding["final_message_id"],
        }
    ]
    answer_receipt = _direction_receipt(conn, run.run_id)
    assert answer_receipt["direction_action"] == "answer_and_refocus"
    assert answer_receipt["result_kind"] == "planning_input"
    assert answer_receipt["question_key"] == "goal_text"


def test_codex_non_language_missing_fact_can_request_one_direction_clarification(
    tutor_persistence,
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    conn = tutor_persistence.connection
    _repository, _conversation_id, run = _create_codex_run_missing_goal(
        conn,
        user_id=tutor_persistence.user_id,
        catalog_digest=tutor_persistence.catalog.digest,
        content="我也在考虑烘焙。",
    )

    @contextmanager
    def same_connection():  # type: ignore[no-untyped-def]
        yield conn

    clarification = "这是临时聊聊职业兴趣，还是你希望切换当前学习方向？"
    result = CodexTutorRunDispatcher(
        settings=_settings(codex_runtime_home_directory=str(tmp_path / "runtime-home")),
        host=_FakeCodexHost(
            direction_action=PlanningDirectionAction.CLARIFY_DIRECTION,
            final_text=clarification,
        ),
        connection_factory=same_connection,
        manage_autocommit=False,
    ).dispatch(user_id=tutor_persistence.user_id, run_id=run.run_id)

    assert result.terminal_outcome is TutorTerminalOutcome.COMPLETED
    request = conn.execute(
        """
        SELECT kind, question_key, descriptor_json, presentation_json
        FROM tutor_interaction_requests
        WHERE source_turn_id = %s
        """,
        (run.run_id,),
    ).fetchone()
    assert request is not None
    assert request["kind"] == "clarification"
    assert request["question_key"] is None
    assert request["descriptor_json"]["prompt"] == _DIRECTION_CLARIFICATION
    assert request["presentation_json"]["field_key"] is None
    assert _DIRECTION_CLARIFICATION.count("？") == 1
    clarify_receipt = _direction_receipt(conn, run.run_id)
    assert clarify_receipt["direction_action"] == "clarify_direction"
    assert clarify_receipt["result_kind"] == "clarification"
    assert clarify_receipt["source"] == "model_candidate"


def test_codex_semantic_language_hint_persists_python_only_request(
    tutor_persistence,
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    conn = tutor_persistence.connection
    repository, conversation_id, run = _create_codex_run_missing_language(
        conn,
        user_id=tutor_persistence.user_id,
        catalog_digest=tutor_persistence.catalog.digest,
        content="我想做langchain架构的agent",
    )

    @contextmanager
    def same_connection():  # type: ignore[no-untyped-def]
        yield conn

    host = _FakeCodexHost(
        planning_intent_hint={
            "schema_version": "planning-intent-hint-v2",
            "candidate_language_ids": ["python"],
            "confidence": "high",
            "reason_code": "technology_ecosystem_match",
        },
        final_text="你想学习哪门编程语言？",
    )
    result = CodexTutorRunDispatcher(
        settings=_settings(codex_runtime_home_directory=str(tmp_path / "runtime-home")),
        host=host,
        connection_factory=same_connection,
        manage_autocommit=False,
    ).dispatch(user_id=tutor_persistence.user_id, run_id=run.run_id)

    assert result.terminal_outcome is TutorTerminalOutcome.COMPLETED
    request = conn.execute(
        "SELECT kind, question_key, presentation_json FROM tutor_interaction_requests WHERE source_turn_id = %s",
        (run.run_id,),
    ).fetchone()
    assert request is not None
    assert request["kind"] == "planning_input"
    assert request["question_key"] == "language_id"
    presentation = request["presentation_json"]
    assert presentation["options"] == [
        {"value": "python", "label": presentation["options"][0]["label"]}
    ]
    assert presentation["recommended"] is None
    assert presentation["selection_scope"] == "intent_shortlist"
    assert presentation["selection_reason_code"] == "semantic_technology_ecosystem_match"
    assert presentation["intent_policy_version"] == "planning-language-intent-v2"
    assert "confidence" not in str(presentation)
    assert repository.load_snapshot(user_id=tutor_persistence.user_id, run_id=run.run_id) is not None
    language_receipt = _direction_receipt(conn, run.run_id)
    assert language_receipt["direction_action"] == "continue_mainline"
    assert language_receipt["result_kind"] == "planning_input"
    assert language_receipt["question_key"] == "language_id"


def test_codex_insufficient_language_evidence_persists_targeted_clarification(
    tutor_persistence,
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    conn = tutor_persistence.connection
    _repository, _conversation_id, run = _create_codex_run_missing_language(
        conn,
        user_id=tutor_persistence.user_id,
        catalog_digest=tutor_persistence.catalog.digest,
        content="我想做一个 Agent",
    )

    @contextmanager
    def same_connection():  # type: ignore[no-untyped-def]
        yield conn

    clarification = "你希望使用哪种实现语言，或者目标框架需要哪种运行环境？"
    result = CodexTutorRunDispatcher(
        settings=_settings(codex_runtime_home_directory=str(tmp_path / "runtime-home")),
        host=_FakeCodexHost(
            direction_action=PlanningDirectionAction.CLARIFY_DIRECTION,
            final_text=clarification,
        ),
        connection_factory=same_connection,
        manage_autocommit=False,
    ).dispatch(user_id=tutor_persistence.user_id, run_id=run.run_id)

    assert result.terminal_outcome is TutorTerminalOutcome.COMPLETED
    request = conn.execute(
        "SELECT kind, question_key, descriptor_json, presentation_json FROM tutor_interaction_requests WHERE source_turn_id = %s",
        (run.run_id,),
    ).fetchone()
    assert request is not None
    assert request["kind"] == "clarification"
    assert request["question_key"] is None
    assert request["descriptor_json"]["prompt"] == _DIRECTION_CLARIFICATION
    assert request["presentation_json"]["type"] == "text"
    fact = conn.execute(
        "SELECT value_json FROM tutor_planning_intake_facts WHERE source_run_id = %s AND field_key = 'language_id'",
        (run.run_id,),
    ).fetchone()
    assert fact is None


def test_codex_typed_response_fresh_turn_continues_with_next_server_question(
    tutor_persistence,
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
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
    accepted = repository.accept_input(
        user_id=tutor_persistence.user_id,
        run_id=run.run_id,
        idempotency_key=f"codex-continuous-source-{uuid4().hex}",
        content="我想学习 Python，而且目前是零基础。",
        received_at=datetime.now(UTC),
    )
    PostgresLearningTrackRepository(conn).snapshot_run_scope(
        user_id=tutor_persistence.user_id,
        run_id=run.run_id,
        explicit_scope=LearningScope(scope_kind=LearningScopeKind.PLAN_DRAFTING),
    )
    facts = PostgresPlanningFactRepository(conn)
    facts.record_input(
        user_id=tutor_persistence.user_id,
        run_id=run.run_id,
        conversation_id=conversation_id,
        message_id=accepted.message_id,
        input_revision=accepted.input_revision,
        content="",
        explicit_facts={"language_id": "python", "experience_level": "new"},
    )

    @contextmanager
    def same_connection():  # type: ignore[no-untyped-def]
        yield conn

    host = _FakeCodexHost()
    dispatcher = CodexTutorRunDispatcher(
        settings=_settings(codex_runtime_home_directory=str(tmp_path / "runtime-home")),
        host=host,
        connection_factory=same_connection,
        manage_autocommit=False,
    )
    dispatcher.dispatch(user_id=tutor_persistence.user_id, run_id=run.run_id)
    first_request = conn.execute(
        "SELECT item_id::text AS item_id, version, question_key FROM tutor_interaction_requests WHERE source_turn_id = %s",
        (run.run_id,),
    ).fetchone()
    assert first_request is not None and first_request["question_key"] == "goal_text"

    response = repository.respond_to_interaction_request(
        user_id=tutor_persistence.user_id,
        conversation_id=conversation_id,
        item_id=str(first_request["item_id"]),
        expected_version=int(first_request["version"]),
        response={
            "kind": "planning_input",
            "question_key": "goal_text",
            "catalog_version": "tutor_planning_questions_v1",
            "value": "构建可靠的自动化工具",
        },
        idempotency_key=f"codex-continuous-answer-{uuid4().hex}",
        catalog_digest=tutor_persistence.catalog.digest,
        policy=run.policy,
        received_at=datetime.now(UTC),
    )
    assert response.turn is not None
    PostgresLearningTrackRepository(conn).inherit_run_scope(
        user_id=tutor_persistence.user_id,
        run_id=response.turn.run.run_id,
        source_run_id=run.run_id,
    )
    facts.record_input(
        user_id=tutor_persistence.user_id,
        run_id=response.turn.run.run_id,
        conversation_id=conversation_id,
        message_id=response.turn.acceptance.message_id,
        input_revision=response.turn.acceptance.input_revision,
        content="",
        explicit_facts=response.planning_facts,
    )

    dispatcher.dispatch(user_id=tutor_persistence.user_id, run_id=response.turn.run.run_id)
    next_request = conn.execute(
        "SELECT question_key, state FROM tutor_interaction_requests WHERE source_turn_id = %s",
        (response.turn.run.run_id,),
    ).fetchone()
    assert next_request == {"question_key": "pace_constraints", "state": "pending"}
    assert host.resumed_thread_ids == ["thread-cutover"]


def test_codex_missing_direction_marker_ignores_stale_model_question(
    tutor_persistence,
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    conn = tutor_persistence.connection
    _repository, _conversation_id, run = _create_codex_run_missing_goal(
        conn,
        user_id=tutor_persistence.user_id,
        catalog_digest=tutor_persistence.catalog.digest,
        content="我想做厨师",
    )

    @contextmanager
    def same_connection():  # type: ignore[no-untyped-def]
        yield conn

    stale_question = "你希望通过这次学习完成什么具体目标？"
    host = _FakeCodexHost(
        direction_action=None,
        final_text=stale_question,
    )
    result = CodexTutorRunDispatcher(
        settings=_settings(
            codex_runtime_home_directory=str(tmp_path / "runtime-home")
        ),
        host=host,
        connection_factory=same_connection,
        manage_autocommit=False,
    ).dispatch(user_id=tutor_persistence.user_id, run_id=run.run_id)

    assert result.terminal_outcome is TutorTerminalOutcome.COMPLETED
    request = conn.execute(
        """
        SELECT kind, question_key, descriptor_json
        FROM tutor_interaction_requests
        WHERE source_turn_id = %s
        """,
        (run.run_id,),
    ).fetchone()
    assert request is not None
    assert request["kind"] == "clarification"
    assert request["question_key"] is None
    assert request["descriptor_json"]["prompt"] == _DIRECTION_CLARIFICATION
    assert request["descriptor_json"]["prompt"] != stale_question
    receipt = _direction_receipt(conn, run.run_id)
    assert receipt["direction_action"] == "clarify_direction"
    assert receipt["source"] == "server_fallback_missing_direction"
    assert host.turn_requests[0].effort == "low"
    assert host.turn_requests[0].timeout_seconds == 180.0
    assert host.turn_requests[0].max_visible_text_chars == 2_000
    assert host.turn_requests[0].max_reasoning_text_chars == 16_000


def test_codex_conflicting_direction_action_falls_back_to_fixed_clarification(
    tutor_persistence,
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    conn = tutor_persistence.connection
    _repository, _conversation_id, run = _create_codex_run_missing_goal(
        conn,
        user_id=tutor_persistence.user_id,
        catalog_digest=tutor_persistence.catalog.digest,
        content="先问网络问题，但也许要换方向。",
    )

    @contextmanager
    def same_connection():  # type: ignore[no-untyped-def]
        yield conn

    CodexTutorRunDispatcher(
        settings=_settings(
            codex_runtime_home_directory=str(tmp_path / "runtime-home")
        ),
        host=_FakeCodexHost(
            direction_action=PlanningDirectionAction.CONTINUE_MAINLINE,
            extra_direction_action=PlanningDirectionAction.CONFIRMED_SWITCH,
            final_text="你希望通过这次学习完成什么具体目标？",
        ),
        connection_factory=same_connection,
        manage_autocommit=False,
    ).dispatch(user_id=tutor_persistence.user_id, run_id=run.run_id)

    request = conn.execute(
        "SELECT kind, descriptor_json FROM tutor_interaction_requests WHERE source_turn_id = %s",
        (run.run_id,),
    ).fetchone()
    assert request is not None
    assert request["kind"] == "clarification"
    assert request["descriptor_json"]["prompt"] == _DIRECTION_CLARIFICATION
    receipt = _direction_receipt(conn, run.run_id)
    assert receipt["source"] == "server_fallback_invalid_direction"


def test_codex_direction_timeout_returns_runtime_error_without_clarification(
    tutor_persistence,
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    conn = tutor_persistence.connection
    _repository, _conversation_id, run = _create_codex_run_missing_goal(
        conn,
        user_id=tutor_persistence.user_id,
        catalog_digest=tutor_persistence.catalog.digest,
        content="一个没有明确关系的新主题。",
    )

    @contextmanager
    def same_connection():  # type: ignore[no-untyped-def]
        yield conn

    result = CodexTutorRunDispatcher(
        settings=_settings(
            codex_runtime_home_directory=str(tmp_path / "runtime-home")
        ),
        host=_FakeCodexHost(
            direction_action=None,
            safe_error_code="runtime_turn_time_exhausted",
        ),
        connection_factory=same_connection,
        manage_autocommit=False,
    ).dispatch(user_id=tutor_persistence.user_id, run_id=run.run_id)

    assert result.terminal_outcome is TutorTerminalOutcome.MODEL_UNAVAILABLE
    request = conn.execute(
        "SELECT kind, descriptor_json FROM tutor_interaction_requests WHERE source_turn_id = %s",
        (run.run_id,),
    ).fetchone()
    assert request is None
    assert conn.execute(
        "SELECT code FROM tutor_runtime_public_errors WHERE run_id = %s", (run.run_id,),
    ).fetchone() == {"code": "TUTOR_RUNTIME_UNAVAILABLE"}


def test_codex_text_budget_error_discards_unfinished_text_without_reasking_confirmed_python(
    tutor_persistence,
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    conn = tutor_persistence.connection
    repository, conversation_id, run = _create_codex_run_missing_goal(
        conn,
        user_id=tutor_persistence.user_id,
        catalog_digest=tutor_persistence.catalog.digest,
        content="继续学习已确认的 Python。",
    )

    @contextmanager
    def same_connection():  # type: ignore[no-untyped-def]
        yield conn

    completed_reasoning = "已完成推理" * 49
    unfinished_reasoning = "未完成推理" * 280
    unfinished_final_answer = "未完成回答" * 71
    assert len(unfinished_reasoning) == 1_400
    assert len(unfinished_final_answer) == 355
    assert (
        len(completed_reasoning)
        + len(unfinished_reasoning)
        + len(unfinished_final_answer)
        == 2_000
    )
    result = CodexTutorRunDispatcher(
        settings=_settings(
            codex_runtime_home_directory=str(tmp_path / "runtime-home")
        ),
        host=_FakeCodexHost(
            direction_action=None,
            safe_error_code="runtime_text_budget_exhausted",
            include_reasoning=True,
            completed_reasoning_text=completed_reasoning,
            streaming_reasoning_text=unfinished_reasoning,
            streaming_final_answer_text=unfinished_final_answer,
        ),
        connection_factory=same_connection,
        manage_autocommit=False,
    ).dispatch(user_id=tutor_persistence.user_id, run_id=run.run_id)

    assert result.terminal_outcome is TutorTerminalOutcome.MODEL_UNAVAILABLE
    request = conn.execute(
        "SELECT kind, question_key, descriptor_json "
        "FROM tutor_interaction_requests WHERE source_turn_id = %s",
        (run.run_id,),
    ).fetchone()
    assert request is None
    assert conn.execute(
        "SELECT count(*)::int AS count FROM tutor_run_events "
        "WHERE run_id = %s AND kind = 'planning_direction_resolved'", (run.run_id,),
    ).fetchone() == {"count": 0}
    assert conn.execute(
        "SELECT code, recoverable FROM tutor_runtime_public_errors WHERE run_id = %s", (run.run_id,),
    ).fetchone() == {"code": "TUTOR_RUNTIME_UNAVAILABLE", "recoverable": True}

    binding = conn.execute(
        "SELECT state, final_message_id FROM tutor_run_runtime_bindings WHERE run_id = %s",
        (run.run_id,),
    ).fetchone()
    assert binding is not None
    assert binding["state"] == "unavailable"
    assert binding["final_message_id"] is None
    text_items = conn.execute(
        """
        SELECT channel, state, text, content_hash, completed_at, public_message_id
        FROM tutor_runtime_text_items
        WHERE run_id = %s
        ORDER BY created_at, id
        """,
        (run.run_id,),
    ).fetchall()
    assert len(text_items) == 3
    assert text_items[0]["channel"] == "reasoning"
    assert text_items[0]["state"] == "completed"
    assert text_items[0]["text"] == completed_reasoning
    assert text_items[0]["content_hash"] is not None
    assert text_items[0]["completed_at"] is not None
    assert text_items[0]["public_message_id"] == binding["final_message_id"]
    for item, channel in zip(
        text_items[1:],
        ("reasoning", "final_answer"),
        strict=True,
    ):
        assert item["channel"] == channel
        assert item["state"] == "discarded"
        assert item["text"] == ""
        assert item["content_hash"] is None
        assert item["completed_at"] is not None
        assert item["public_message_id"] is None
    assert not [item for item in text_items if item["state"] == "streaming"]
    conversation_events = repository.conversation_events_after(
        user_id=tutor_persistence.user_id,
        conversation_id=conversation_id,
        cursor=None,
    )
    discard_indexes = [
        index
        for index, event in enumerate(conversation_events)
        if event.kind == "turn_output"
        and event.payload.get("operation") == "discard"
    ]
    assert len(discard_indexes) == 2
    assert {
        conversation_events[index].payload["channel"]
        for index in discard_indexes
    } == {"reasoning", "final_answer"}
    assert all(
        "text" not in conversation_events[index].payload
        for index in discard_indexes
    )
    assert conn.execute(
        "SELECT count(*)::int AS count FROM tutor_messages "
        "WHERE conversation_id = %s AND role = 'tutor'", (conversation_id,),
    ).fetchone() == {"count": 0}
    terminal_receipt = conn.execute(
        """
        SELECT projection_status, safe_code
        FROM tutor_runtime_item_receipts
        WHERE run_id = %s AND event_kind = 'turn_completed'
        """,
        (run.run_id,),
    ).fetchone()
    assert terminal_receipt == {
        "projection_status": "applied",
        "safe_code": "runtime_text_budget_exhausted",
    }


def test_codex_server_terminal_receipt_failure_rolls_back_clarification_cleanup(
    tutor_persistence,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # type: ignore[no-untyped-def]
    conn = tutor_persistence.connection
    _repository, conversation_id, run = _create_codex_run_missing_goal(
        conn,
        user_id=tutor_persistence.user_id,
        catalog_digest=tutor_persistence.catalog.digest,
        content="一个没有明确关系的新主题。",
    )

    @contextmanager
    def same_connection():  # type: ignore[no-untyped-def]
        yield conn

    original_project_event = TutorRuntimeEventProjector.project_event

    def fail_terminal_projection(
        self: TutorRuntimeEventProjector,
        event: RuntimeEvent,
        *,
        sequence: int,
        occurred_at: datetime,
        defer_public_message: bool = False,
    ):  # type: ignore[no-untyped-def]
        if event.kind is RuntimeEventKind.TURN_COMPLETED:
            raise RuntimeError("forced terminal receipt failure")
        return original_project_event(
            self,
            event,
            sequence=sequence,
            occurred_at=occurred_at,
            defer_public_message=defer_public_message,
        )

    monkeypatch.setattr(
        TutorRuntimeEventProjector,
        "project_event",
        fail_terminal_projection,
    )
    unfinished_reasoning = "仍在生成的推理"
    with pytest.raises(RuntimeError, match="forced terminal receipt failure"):
        CodexTutorRunDispatcher(
            settings=_settings(
                codex_runtime_home_directory=str(tmp_path / "runtime-home")
            ),
            host=_FakeCodexHost(
                direction_action=None,
                streaming_reasoning_text=unfinished_reasoning,
            ),
            connection_factory=same_connection,
            manage_autocommit=False,
        ).dispatch(user_id=tutor_persistence.user_id, run_id=run.run_id)

    assert conn.execute(
        "SELECT count(*)::int AS count FROM tutor_interaction_requests "
        "WHERE source_turn_id = %s",
        (run.run_id,),
    ).fetchone() == {"count": 0}
    assert conn.execute(
        "SELECT count(*)::int AS count FROM tutor_run_events "
        "WHERE run_id = %s AND kind = 'planning_direction_resolved'",
        (run.run_id,),
    ).fetchone() == {"count": 0}
    assert conn.execute(
        "SELECT count(*)::int AS count FROM tutor_messages "
        "WHERE conversation_id = %s AND role = 'tutor'",
        (conversation_id,),
    ).fetchone() == {"count": 0}
    binding = conn.execute(
        "SELECT state, final_message_id FROM tutor_run_runtime_bindings "
        "WHERE run_id = %s",
        (run.run_id,),
    ).fetchone()
    assert binding == {"state": "running", "final_message_id": None}
    text_item = conn.execute(
        """
        SELECT state, text, content_hash, completed_at, public_message_id
        FROM tutor_runtime_text_items
        WHERE run_id = %s AND channel = 'reasoning'
        """,
        (run.run_id,),
    ).fetchone()
    assert text_item is not None
    assert text_item["state"] == "streaming"
    assert text_item["text"] == unfinished_reasoning
    assert text_item["content_hash"] is not None
    assert text_item["completed_at"] is None
    assert text_item["public_message_id"] is None
    assert conn.execute(
        "SELECT count(*)::int AS count FROM tutor_runtime_item_receipts "
        "WHERE run_id = %s AND event_kind = 'turn_completed'",
        (run.run_id,),
    ).fetchone() == {"count": 0}
    run_row = conn.execute(
        "SELECT status, terminal_outcome FROM tutor_runs WHERE id = %s",
        (run.run_id,),
    ).fetchone()
    assert run_row == {"status": "running", "terminal_outcome": None}


@pytest.mark.parametrize(
    "safe_error_code",
    ["runtime_connection_failed", "runtime_control_failed"],
)
def test_codex_non_direction_runtime_failure_does_not_create_clarification_success(
    safe_error_code: str,
    tutor_persistence,
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    conn = tutor_persistence.connection
    _repository, conversation_id, run = _create_codex_run_missing_goal(
        conn,
        user_id=tutor_persistence.user_id,
        catalog_digest=tutor_persistence.catalog.digest,
        content="一个需要重新判断方向的输入。",
    )

    @contextmanager
    def same_connection():  # type: ignore[no-untyped-def]
        yield conn

    result = CodexTutorRunDispatcher(
        settings=_settings(
            codex_runtime_home_directory=str(tmp_path / "runtime-home")
        ),
        host=_FakeCodexHost(
            direction_action=PlanningDirectionAction.CLARIFY_DIRECTION,
            safe_error_code=safe_error_code,
        ),
        connection_factory=same_connection,
        manage_autocommit=False,
    ).dispatch(user_id=tutor_persistence.user_id, run_id=run.run_id)

    assert result.terminal_outcome is TutorTerminalOutcome.MODEL_UNAVAILABLE
    assert conn.execute(
        "SELECT count(*)::int AS count FROM tutor_interaction_requests "
        "WHERE source_turn_id = %s",
        (run.run_id,),
    ).fetchone() == {"count": 0}
    assert conn.execute(
        "SELECT count(*)::int AS count FROM tutor_run_events "
        "WHERE run_id = %s AND kind = 'planning_direction_resolved'",
        (run.run_id,),
    ).fetchone() == {"count": 0}
    assert conn.execute(
        "SELECT count(*)::int AS count FROM tutor_messages "
        "WHERE conversation_id = %s AND role = 'tutor'",
        (conversation_id,),
    ).fetchone() == {"count": 0}
    binding = conn.execute(
        "SELECT state FROM tutor_run_runtime_bindings WHERE run_id = %s",
        (run.run_id,),
    ).fetchone()
    assert binding == {"state": "unavailable"}


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


def _create_codex_run_missing_goal(
    conn,  # type: ignore[no-untyped-def]
    *,
    user_id: str,
    catalog_digest: str,
    content: str,
) -> tuple[PostgresTutorRepository, str, TutorRunSnapshot]:
    repository = PostgresTutorRepository(conn)
    conversation_id = repository.create_conversation(user_id=user_id)
    PostgresLearningTrackRepository(conn).bind_conversation_scope(
        user_id=user_id,
        conversation_id=conversation_id,
        scope=LearningScope(scope_kind=LearningScopeKind.PLAN_DRAFTING),
    )
    PostgresLearningPlanSessionRepository(conn).create_session(
        user_id=user_id,
        conversation_id=conversation_id,
        preferred_language_id="python",
    )
    run = repository.create_run(
        user_id=user_id,
        conversation_id=conversation_id,
        catalog_digest=catalog_digest,
        policy=TutorPolicySnapshot(
            deadline=datetime.now(UTC) + timedelta(minutes=5),
            max_iterations=3,
            max_model_calls=2,
            max_capability_calls=3,
            max_effects=0,
            context_token_budget=512,
        ),
        origin="interactive",
        interaction_protocol_version="thread_turn_v2",
        runtime_kind="codex_sidecar_v1",
    )
    accepted = repository.accept_input(
        user_id=user_id,
        run_id=run.run_id,
        idempotency_key=f"codex-goal-source-{uuid4().hex}",
        content=content,
        received_at=datetime.now(UTC),
    )
    PostgresLearningTrackRepository(conn).snapshot_run_scope(
        user_id=user_id,
        run_id=run.run_id,
        explicit_scope=LearningScope(scope_kind=LearningScopeKind.PLAN_DRAFTING),
    )
    PostgresPlanningFactRepository(conn).record_input(
        user_id=user_id,
        run_id=run.run_id,
        conversation_id=conversation_id,
        message_id=accepted.message_id,
        input_revision=accepted.input_revision,
        content=content,
        explicit_facts={
            "language_id": "python",
            "target_level": "beginner",
            "weekly_minutes": 240,
            "experience_level": "new",
            "teaching_preferences": [],
            "pace_constraints": "每周四次练习",
        },
    )
    return repository, conversation_id, run


def _create_codex_run_missing_language(
    conn,  # type: ignore[no-untyped-def]
    *,
    user_id: str,
    catalog_digest: str,
    content: str,
) -> tuple[PostgresTutorRepository, str, TutorRunSnapshot]:
    repository = PostgresTutorRepository(conn)
    conversation_id = repository.create_conversation(user_id=user_id)
    PostgresLearningTrackRepository(conn).bind_conversation_scope(
        user_id=user_id,
        conversation_id=conversation_id,
        scope=LearningScope(scope_kind=LearningScopeKind.PLAN_DRAFTING),
    )
    PostgresLearningPlanSessionRepository(conn).create_session(
        user_id=user_id,
        conversation_id=conversation_id,
        preferred_language_id=None,
    )
    run = repository.create_run(
        user_id=user_id,
        conversation_id=conversation_id,
        catalog_digest=catalog_digest,
        policy=TutorPolicySnapshot(
            deadline=datetime.now(UTC) + timedelta(minutes=5),
            max_iterations=3,
            max_model_calls=2,
            max_capability_calls=3,
            max_effects=0,
            context_token_budget=512,
        ),
        origin="interactive",
        interaction_protocol_version="thread_turn_v2",
        runtime_kind="codex_sidecar_v1",
    )
    accepted = repository.accept_input(
        user_id=user_id,
        run_id=run.run_id,
        idempotency_key=f"codex-language-source-{uuid4().hex}",
        content=content,
        received_at=datetime.now(UTC),
    )
    PostgresLearningTrackRepository(conn).snapshot_run_scope(
        user_id=user_id,
        run_id=run.run_id,
        explicit_scope=LearningScope(scope_kind=LearningScopeKind.PLAN_DRAFTING),
    )
    PostgresPlanningFactRepository(conn).record_input(
        user_id=user_id,
        run_id=run.run_id,
        conversation_id=conversation_id,
        message_id=accepted.message_id,
        input_revision=accepted.input_revision,
        content=content,
        explicit_facts={
            "goal_text": "构建可靠的 Agent",
            "target_level": "beginner",
            "weekly_minutes": 240,
            "experience_level": "new",
            "teaching_preferences": [],
            "pace_constraints": "每周四次练习",
        },
    )
    return repository, conversation_id, run


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
