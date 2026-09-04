from __future__ import annotations

from app.agents.harness.contracts import (
    TutorDecision,
    TutorProviderResult,
    TutorSkillReference,
    TutorTerminalOutcome,
)
from app.core.config import Settings
from app.services.learning.contracts import LearningScope, LearningScopeKind, LearningTaskKind
from app.services.learning.teaching_contracts import (
    TeachingControlStimulus, TeachingSessionMode, TeachingStepDecision,
)
from app.services.learning.teaching_sessions import TeachingSessionService, TeachingSessionServiceError
from app.services.tutor.interactive import TutorInteractiveRunDispatcher
from app.services.tutor.persistence import PostgresTutorRepository
from app.services.tutor.public_api import TutorPublicService
from app.services.tutor.public_thinking_stream import TutorPublicThinkingSink
from tests.support.teaching_session_support import connection, create_teaching_scope, database_available

import pytest

pytestmark = pytest.mark.skipif(not database_available(), reason="PostgreSQL is not available")


class _TeachingProvider:
    def __init__(
        self, *, unavailable: bool = False, free_reading: bool = False, invalid_handle: bool = False,
        invalid_focus: bool = False, completion: bool = False,
        action_override: str | None = None,
        public_message_override: str | None = None,
        teaching_moves: tuple[str, ...] | None = ("targeted_explanation", "worked_example"),
        learner_response_mode: str | None = "none",
        interaction_intent: str | None = None,
        artifact_handle: str | None = None,
        include_interaction: bool = True,
        expected_current_input: str | None = None,
        before_teaching_step=None,  # type: ignore[no-untyped-def]
    ) -> None:
        self.calls = 0
        self.unavailable = unavailable
        self.free_reading = free_reading
        self.invalid_handle = invalid_handle
        self.invalid_focus = invalid_focus
        self.completion = completion
        self.action_override = action_override
        self.public_message_override = public_message_override
        self.teaching_moves = teaching_moves
        self.learner_response_mode = learner_response_mode
        self.interaction_intent = interaction_intent
        self.artifact_handle = artifact_handle
        self.include_interaction = include_interaction
        self.expected_current_input = expected_current_input
        self.before_teaching_step = before_teaching_step

    def decide(self, *, run, context, thinking_sink: TutorPublicThinkingSink | None = None):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.expected_current_input is not None:
            assert context.current_input is not None
            assert context.current_input.content == self.expected_current_input
        if self.unavailable:
            return TutorProviderResult.model_unavailable(safe_code="MODEL_UNAVAILABLE")
        if self.calls == 1:
            assert any(item["section"] == "teaching_session" for item in context.as_prompt_context())
            return TutorProviderResult(
                decision=TutorDecision(
                    skill_references=(TutorSkillReference("tutor.lesson-teaching", "1.2.1"),),
                )
            )
        if self.before_teaching_step is not None:
            self.before_teaching_step()
        public_message = self.public_message_override or (
            "你已完成变量知识点。这里先总结关键结论，并停在当前知识点等待你的下一步选择。"
            if self.completion
            else "先回答你当前阅读中的问题，并保持自由阅读。"
            if self.free_reading
            else "变量让名称引用一个值。先看一个最小赋值例子。"
        )
        interaction = None
        if self.include_interaction and self.learner_response_mode is not None:
            interaction = {
                "mode": self.learner_response_mode,
                "intent": self.interaction_intent or (
                    "none" if self.learner_response_mode == "none" else "text_answer"
                ),
                "artifact_handle": self.artifact_handle,
            }
        step = TeachingStepDecision(
            action=self.action_override or ("summarize_progress" if self.completion else "answer_question" if self.free_reading else "explain_concept"),
            objective_id="knowledge:python.variables",
            focus_id="knowledge:invented" if self.invalid_focus else "knowledge:python.variables",
            source_handles=(("knowledge:unknown",) if self.invalid_handle else ("knowledge:python.variables",)),
            public_message=public_message,
            focus_resolution="replace_objective" if self.invalid_focus else "stay",
            pause_kind="completion_pause" if self.completion else "soft_pause",
            escalation_hint=("如需连续讲解，可显式转为引导。" if self.free_reading else None),
            teaching_moves=self.teaching_moves,
            learner_response_mode=(self.learner_response_mode if not self.include_interaction else None),
            interaction=interaction,
        )
        thinking = "当前教学单元组合互补动作，并在服务端权威边界停顿。"
        if thinking_sink is not None:
            thinking_sink.begin_attempt(1)
            thinking_sink.append_text(1, thinking)
            thinking_sink.complete_attempt(1)
        return TutorProviderResult(
            decision=TutorDecision(
                public_message=step.public_message, public_thinking_text=thinking,
                terminal_outcome=TutorTerminalOutcome.COMPLETED, teaching_step=step,
            )
        )


def _open_guided(conn):  # type: ignore[no-untyped-def]
    scope = create_teaching_scope(conn)
    opened = TeachingSessionService(conn).open(
        user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), knowledge_key="python.variables",
        conversation_id=str(scope["conversation_id"]), expected_track_version=1,
        expected_progress_version=1, expected_assignment_version=1,
        mode=TeachingSessionMode.GUIDED, idempotency_key="teaching-loop-open",
    )
    pending = opened["pending_run"]
    assert isinstance(pending, dict)
    return scope, opened, str(pending["run_id"])


def test_one_stimulus_commits_one_teaching_step_checkpoint_receipt_and_pause() -> None:
    with connection() as conn:
        scope, opened, run_id = _open_guided(conn)
    provider = _TeachingProvider()
    result = TutorInteractiveRunDispatcher(
        settings=Settings(llm_type="disabled", tutor_thread_turn_v2_enabled=True),
        provider_factory=lambda settings: provider,
    ).dispatch(user_id=str(scope["user_id"]), run_id=run_id)
    assert result.terminal_outcome is TutorTerminalOutcome.COMPLETED
    assert provider.calls == 2

    with connection() as conn:
        service = TeachingSessionService(conn)
        current = service.current(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), knowledge_key="python.variables",
        )
        assert current["session_version"] == 2
        assert current["checkpoint"]["pause_reason"] == "soft_pause"
        assert current["action_shelf"]["primary_action"]["key"] == "continue"
        receipt = conn.execute("SELECT * FROM tutor_teaching_action_receipts WHERE run_id=%s", (run_id,)).fetchone()
        assert receipt is not None and receipt["action"] == "explain_concept"
        assert receipt["teaching_moves_json"] == ["targeted_explanation", "worked_example"]
        assert receipt["learner_response_mode"] == "none"
        assert receipt["schema_version"] == "teaching_action_receipt_v2"
        assert receipt["policy_version"] == "lesson_teaching_policy_v2"
        assert "public_message" not in receipt
        messages = conn.execute(
            "SELECT content FROM tutor_messages WHERE conversation_id=%s AND role='tutor'",
            (scope["conversation_id"],),
        ).fetchall()
        assert [row["content"] for row in messages] == ["变量让名称引用一个值。先看一个最小赋值例子。"]
        runs = conn.execute(
            "SELECT count(*) AS count FROM tutor_runs WHERE conversation_id=%s",
            (scope["conversation_id"],),
        ).fetchone()
        assert runs is not None and runs["count"] == 1
        assert opened["teaching_session"]["session_version"] == 1


def test_composer_response_unit_projects_no_continue_and_keeps_composer_as_next_step() -> None:
    with connection() as conn:
        scope, _opened, run_id = _open_guided(conn)
    provider = _TeachingProvider(
        action_override="check_understanding",
        public_message_override="预测 `value += 1` 执行后会输出什么，并指出你的判断依据。",
        teaching_moves=("guided_derivation", "prediction"),
        learner_response_mode="composer",
    )
    result = TutorInteractiveRunDispatcher(
        settings=Settings(llm_type="disabled", tutor_thread_turn_v2_enabled=True),
        provider_factory=lambda settings: provider,
    ).dispatch(user_id=str(scope["user_id"]), run_id=run_id)
    assert result.terminal_outcome is TutorTerminalOutcome.COMPLETED

    with connection() as conn:
        current = TeachingSessionService(conn).current(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), knowledge_key="python.variables",
        )
        assert current["checkpoint"]["recommended_action_key"] == "respond_in_composer"
        assert current["action_shelf"]["primary_action"] is None
        assert "continue" not in current["allowed_actions"]
        assert current["allowed_actions"] == ["change_example", "pause"]


@pytest.mark.parametrize(
    ("teaching_moves", "learner_response_mode", "action"),
    [
        (None, None, "explain_concept"),
        (("targeted_explanation",), "none", "explain_concept"),
        (("targeted_explanation", "targeted_explanation"), "none", "explain_concept"),
        (("targeted_explanation", "worked_example"), "composer", "explain_concept"),
    ],
)
def test_selected_v12_gate_rejects_missing_invalid_or_mismatched_unit_fields(
    teaching_moves: tuple[str, ...] | None,
    learner_response_mode: str | None,
    action: str,
) -> None:
    with connection() as conn:
        scope, _opened, run_id = _open_guided(conn)
    result = TutorInteractiveRunDispatcher(
        settings=Settings(llm_type="disabled", tutor_thread_turn_v2_enabled=True),
        provider_factory=lambda settings: _TeachingProvider(
            action_override=action,
            teaching_moves=teaching_moves,
            learner_response_mode=learner_response_mode,
            include_interaction=learner_response_mode is not None,
        ),
    ).dispatch(user_id=str(scope["user_id"]), run_id=run_id)
    assert result.terminal_outcome is TutorTerminalOutcome.BLOCKED_POLICY

    with connection() as conn:
        assert conn.execute(
            "SELECT count(*) AS count FROM tutor_teaching_action_receipts WHERE run_id=%s", (run_id,),
        ).fetchone()["count"] == 0
        assert conn.execute(
            "SELECT count(*) AS count FROM tutor_messages WHERE conversation_id=%s AND role='tutor'",
            (scope["conversation_id"],),
        ).fetchone()["count"] == 0


def test_continue_rejects_repeated_recent_unit_but_allows_changed_strategy() -> None:
    with connection() as conn:
        scope, _opened, first_run_id = _open_guided(conn)
    first = TutorInteractiveRunDispatcher(
        settings=Settings(llm_type="disabled", tutor_thread_turn_v2_enabled=True),
        provider_factory=lambda settings: _TeachingProvider(),
    ).dispatch(user_id=str(scope["user_id"]), run_id=first_run_id)
    assert first.terminal_outcome is TutorTerminalOutcome.COMPLETED

    with connection() as conn:
        service = TeachingSessionService(conn)
        current = service.current(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), knowledge_key="python.variables",
        )
        repeated = service.action(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), session_id=str(current["session_id"]),
            control=TeachingControlStimulus(
                control_key="continue", client_action_id="repeat-unit-continue",
                expected_session_version=int(current["session_version"]), expected_track_version=int(current["track_version"]),
                expected_progress_version=int(current["progress_version"]), expected_assignment_version=int(current["assignment_version"]),
            ),
            target_mode=None, admit_run=True, idempotency_key="repeat-unit-continue",
        )
        repeated_run = str(repeated["pending_run"]["run_id"])

    denied = TutorInteractiveRunDispatcher(
        settings=Settings(llm_type="disabled", tutor_thread_turn_v2_enabled=True),
        provider_factory=lambda settings: _TeachingProvider(),
    ).dispatch(user_id=str(scope["user_id"]), run_id=repeated_run)
    assert denied.terminal_outcome is TutorTerminalOutcome.BLOCKED_POLICY
    assert denied.diagnostic_code == "teaching_unit_not_advanced"

    with connection() as conn:
        service = TeachingSessionService(conn)
        current = service.current(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), knowledge_key="python.variables",
        )
        changed = service.action(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), session_id=str(current["session_id"]),
            control=TeachingControlStimulus(
                control_key="continue", client_action_id="changed-unit-continue",
                expected_session_version=int(current["session_version"]), expected_track_version=int(current["track_version"]),
                expected_progress_version=int(current["progress_version"]), expected_assignment_version=int(current["assignment_version"]),
            ),
            target_mode=None, admit_run=True, idempotency_key="changed-unit-continue",
        )
        changed_run = str(changed["pending_run"]["run_id"])

    approved = TutorInteractiveRunDispatcher(
        settings=Settings(llm_type="disabled", tutor_thread_turn_v2_enabled=True),
        provider_factory=lambda settings: _TeachingProvider(
            action_override="show_example",
            public_message_override="把变量看作贴在值上的标签；现在换到列表元素，预测重新赋值后哪个引用会变化。",
            teaching_moves=("worked_example", "prediction"),
            learner_response_mode="none",
        ),
    ).dispatch(user_id=str(scope["user_id"]), run_id=changed_run)
    assert approved.terminal_outcome is TutorTerminalOutcome.COMPLETED

    with connection() as conn:
        assert conn.execute(
            "SELECT count(*) AS count FROM tutor_teaching_action_receipts WHERE teaching_session_id=(SELECT teaching_session_id FROM tutor_run_teaching_scopes WHERE run_id=%s)",
            (first_run_id,),
        ).fetchone()["count"] == 2
        assert conn.execute(
            "SELECT count(*) AS count FROM tutor_messages WHERE conversation_id=%s AND role='tutor'",
            (scope["conversation_id"],),
        ).fetchone()["count"] == 2


def test_teaching_action_receipt_is_append_only_exported_redacted_and_reset_child_first() -> None:
    import json

    import psycopg

    from app.services.repositories.local_user_data_repository import export_user_data, reset_user_data
    from app.services.tutor.cutover import HarnessCutoverService

    with connection() as conn:
        scope, _opened, run_id = _open_guided(conn)
    result = TutorInteractiveRunDispatcher(
        settings=Settings(llm_type="disabled", tutor_thread_turn_v2_enabled=True),
        provider_factory=lambda settings: _TeachingProvider(),
    ).dispatch(user_id=str(scope["user_id"]), run_id=run_id)
    assert result.terminal_outcome is TutorTerminalOutcome.COMPLETED

    with connection() as conn:
        exported = export_user_data(conn, str(scope["user_id"]))
        assert exported["summary"]["counts"]["teaching_action_receipts"] == 1
        receipts = exported["teaching_action_receipt_summaries"]
        assert len(receipts) == 1 and receipts[0]["action"] == "explain_concept"
        assert receipts[0]["teaching_moves_json"] == ["targeted_explanation", "worked_example"]
        assert receipts[0]["learner_response_mode"] == "none"
        assert receipts[0]["schema_version"] == "teaching_action_receipt_v2"
        serialized = json.dumps(receipts, ensure_ascii=False, sort_keys=True)
        assert "变量让名称引用一个值" not in serialized
        assert "public_message" not in serialized
        assert "provider" not in serialized.casefold()
        inventory = HarnessCutoverService(conn)._inventory(str(scope["user_id"]))
        assert inventory.target_counts["tutor_teaching_action_receipts"] == 1
        receipt_id = receipts[0]["id"]
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(
                    "UPDATE tutor_teaching_action_receipts SET policy_version='lesson_teaching_policy_v2' WHERE id=%s",
                    (receipt_id,),
                )
        reset = reset_user_data(conn, str(scope["user_id"]))
        assert reset["summary"]["counts"]["teaching_action_receipts"] == 0
        assert conn.execute(
            "SELECT count(*) AS count FROM tutor_teaching_action_receipts WHERE user_id=%s",
            (scope["user_id"],),
        ).fetchone()["count"] == 0


def test_provider_unavailable_preserves_checkpoint_and_does_not_auto_admit() -> None:
    with connection() as conn:
        scope, _opened, run_id = _open_guided(conn)
    provider = _TeachingProvider(unavailable=True)
    result = TutorInteractiveRunDispatcher(
        settings=Settings(llm_type="disabled", tutor_thread_turn_v2_enabled=True),
        provider_factory=lambda settings: provider,
    ).dispatch(user_id=str(scope["user_id"]), run_id=run_id)
    assert result.terminal_outcome is TutorTerminalOutcome.MODEL_UNAVAILABLE
    assert provider.calls == 1
    with connection() as conn:
        current = TeachingSessionService(conn).current(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), knowledge_key="python.variables",
        )
        assert current["session_version"] == 1
        assert conn.execute(
            "SELECT count(*) AS count FROM tutor_teaching_action_receipts WHERE run_id=%s", (run_id,),
        ).fetchone()["count"] == 0
        assert conn.execute(
            "SELECT count(*) AS count FROM tutor_runs WHERE conversation_id=%s", (scope["conversation_id"],),
        ).fetchone()["count"] == 1
        state = PostgresTutorRepository(conn).read_run_state(user_id=str(scope["user_id"]), run_id=run_id)
        assert state.terminal_outcome is TutorTerminalOutcome.MODEL_UNAVAILABLE


@pytest.mark.parametrize(
    (
        "latest_input",
        "public_message",
        "action",
        "teaching_moves",
        "response_mode",
        "question_count",
        "forbidden_fragment",
    ),
    [
        (
            "先问一个临时问题：DNS 是什么？然后继续变量练习。",
            "DNS 把域名解析到网络地址。现在回到变量：用一个变量保存解析结果的字符串。",
            "answer_question",
            ("targeted_explanation", "micro_transfer"),
            "none",
            0,
            "是否切换",
        ),
        (
            "我也在考虑去学烘焙。",
            "这是临时聊聊职业兴趣，还是你想停止变量学习并切换当前方向？",
            "wait_for_input",
            ("misconception_contrast", "prediction"),
            "composer",
            1,
            "继续解释变量",
        ),
        (
            "能用变量记录厨师作品的数量吗？",
            "可以，这正是变量的同主题例子：用作品数量作为当前值继续练习赋值。",
            "explain_concept",
            ("targeted_explanation", "worked_example"),
            "none",
            0,
            "是否切换",
        ),
        (
            "停止变量方向，改学网络编程。",
            "已停止重复变量步骤。请从当前路线选择网络编程对应目标后告诉我。",
            "wait_for_input",
            ("misconception_contrast", "micro_transfer"),
            "composer",
            0,
            "是否确认切换",
        ),
    ],
)
def test_learner_direction_drift_preserves_current_input_and_teaching_authority(
    latest_input: str,
    public_message: str,
    action: str,
    teaching_moves: tuple[str, ...],
    response_mode: str,
    question_count: int,
    forbidden_fragment: str,
) -> None:
    with connection() as conn:
        scope = create_teaching_scope(conn)
        opened = TeachingSessionService(conn).open(
            user_id=str(scope["user_id"]),
            track_id=str(scope["track_id"]),
            knowledge_key="python.variables",
            conversation_id=str(scope["conversation_id"]),
            expected_track_version=1,
            expected_progress_version=1,
            expected_assignment_version=1,
            mode=TeachingSessionMode.FREE_READING,
            idempotency_key=f"direction-drift-open-{abs(hash(latest_input))}",
        )
        assert opened["pending_run"] is None
        accepted = TutorPublicService(
            conn,
            settings=Settings(llm_type="disabled"),
        ).accept_conversation_input(
            user_id=str(scope["user_id"]),
            conversation_id=str(scope["conversation_id"]),
            content=latest_input,
            idempotency_key=f"direction-drift-input-{abs(hash(latest_input))}",
            learning_scope=LearningScope(
                scope_kind=LearningScopeKind.LEARNING_TRACK,
                learning_track_id=str(scope["track_id"]),
                task_kind=LearningTaskKind.LESSON_TEACHING,
                knowledge_key="python.variables",
            ),
        )
        run_id = str(accepted["run"]["run_id"])

    provider = _TeachingProvider(
        free_reading=True,
        action_override=action,
        public_message_override=public_message,
        teaching_moves=teaching_moves,
        learner_response_mode=response_mode,
        expected_current_input=latest_input,
    )
    result = TutorInteractiveRunDispatcher(
        settings=Settings(llm_type="disabled", tutor_thread_turn_v2_enabled=True),
        provider_factory=lambda settings: provider,
    ).dispatch(user_id=str(scope["user_id"]), run_id=run_id)

    assert result.terminal_outcome is TutorTerminalOutcome.COMPLETED
    assert public_message.count("？") == question_count
    assert forbidden_fragment not in public_message
    with connection() as conn:
        current = TeachingSessionService(conn).current(
            user_id=str(scope["user_id"]),
            track_id=str(scope["track_id"]),
            knowledge_key="python.variables",
        )
        assert current["mode"] == "free_reading"
        receipt = conn.execute(
            "SELECT objective_id,focus_id FROM tutor_teaching_action_receipts WHERE run_id=%s",
            (run_id,),
        ).fetchone()
        assert receipt == {
            "objective_id": "knowledge:python.variables",
            "focus_id": "knowledge:python.variables",
        }
        persisted = conn.execute(
            "SELECT content FROM tutor_messages WHERE conversation_id=%s AND role='tutor' ORDER BY created_at DESC,id DESC LIMIT 1",
            (scope["conversation_id"],),
        ).fetchone()
        assert persisted == {"content": public_message}


def test_free_reading_question_is_reactive_and_does_not_switch_mode() -> None:
    with connection() as conn:
        scope = create_teaching_scope(conn)
        opened = TeachingSessionService(conn).open(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), knowledge_key="python.variables",
            conversation_id=str(scope["conversation_id"]), expected_track_version=1,
            expected_progress_version=1, expected_assignment_version=1,
            mode=TeachingSessionMode.FREE_READING, idempotency_key="free-reading-open",
        )
        assert opened["pending_run"] is None
        accepted = TutorPublicService(conn, settings=Settings(llm_type="disabled")).accept_conversation_input(
            user_id=str(scope["user_id"]), conversation_id=str(scope["conversation_id"]),
            content="变量和赋值有什么区别？", idempotency_key="free-reading-question",
            learning_scope=LearningScope(
                scope_kind=LearningScopeKind.LEARNING_TRACK, learning_track_id=str(scope["track_id"]),
                task_kind=LearningTaskKind.LESSON_TEACHING, knowledge_key="python.variables",
            ),
        )
        run_id = str(accepted["run"]["run_id"])
    provider = _TeachingProvider(free_reading=True)
    result = TutorInteractiveRunDispatcher(
        settings=Settings(llm_type="disabled", tutor_thread_turn_v2_enabled=True),
        provider_factory=lambda settings: provider,
    ).dispatch(user_id=str(scope["user_id"]), run_id=run_id)
    assert result.terminal_outcome is TutorTerminalOutcome.COMPLETED
    with connection() as conn:
        current = TeachingSessionService(conn).current(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), knowledge_key="python.variables",
        )
        assert current["mode"] == "free_reading"
        assert current["action_shelf"]["primary_action"]["key"] == "escalate_guided"
        assert conn.execute(
            "SELECT count(*) AS count FROM tutor_runs WHERE conversation_id=%s", (scope["conversation_id"],),
        ).fetchone()["count"] == 1
        service = TeachingSessionService(conn)
        with pytest.raises(TeachingSessionServiceError) as invalid_continue:
            service.action(
                user_id=str(scope["user_id"]), track_id=str(scope["track_id"]),
                session_id=str(current["session_id"]),
                control=TeachingControlStimulus(
                    control_key="continue", client_action_id="free-reading-continue-denied",
                    expected_session_version=2, expected_track_version=1,
                    expected_progress_version=1, expected_assignment_version=1,
                ),
                target_mode=None, admit_run=True, idempotency_key="free-reading-continue-denied",
            )
        assert invalid_continue.value.code == "TEACHING_ACTION_INVALID"
        escalated = service.action(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]),
            session_id=str(current["session_id"]),
            control=TeachingControlStimulus(
                control_key="escalate_guided", client_action_id="free-reading-escalate",
                expected_session_version=2, expected_track_version=1,
                expected_progress_version=1, expected_assignment_version=1,
            ),
            target_mode=None, admit_run=False, idempotency_key="free-reading-escalate",
        )
        assert escalated["teaching_session"]["mode"] == "guided"
        assert escalated["pending_run"]["stimulus_kind"] == "teaching_control"
        assert conn.execute(
            "SELECT count(*) AS count FROM tutor_runs WHERE conversation_id=%s", (scope["conversation_id"],),
        ).fetchone()["count"] == 2


def test_unknown_teaching_handle_fails_closed_without_message_or_checkpoint() -> None:
    with connection() as conn:
        scope, _opened, run_id = _open_guided(conn)
    provider = _TeachingProvider(invalid_handle=True)
    result = TutorInteractiveRunDispatcher(
        settings=Settings(llm_type="disabled", tutor_thread_turn_v2_enabled=True),
        provider_factory=lambda settings: provider,
    ).dispatch(user_id=str(scope["user_id"]), run_id=run_id)
    assert result.terminal_outcome is TutorTerminalOutcome.BLOCKED_POLICY
    with connection() as conn:
        current = TeachingSessionService(conn).current(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), knowledge_key="python.variables",
        )
        assert current["session_version"] == 1
        assert conn.execute(
            "SELECT count(*) AS count FROM tutor_teaching_action_receipts WHERE run_id=%s", (run_id,),
        ).fetchone()["count"] == 0
        assert conn.execute(
            "SELECT count(*) AS count FROM tutor_messages WHERE conversation_id=%s AND role='tutor'",
            (scope["conversation_id"],),
        ).fetchone()["count"] == 0


def test_provider_cannot_replace_focus_with_an_unlisted_identity() -> None:
    with connection() as conn:
        scope, _opened, run_id = _open_guided(conn)
    result = TutorInteractiveRunDispatcher(
        settings=Settings(llm_type="disabled", tutor_thread_turn_v2_enabled=True),
        provider_factory=lambda settings: _TeachingProvider(invalid_focus=True),
    ).dispatch(user_id=str(scope["user_id"]), run_id=run_id)
    assert result.terminal_outcome is TutorTerminalOutcome.BLOCKED_POLICY
    with connection() as conn:
        current = TeachingSessionService(conn).current(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), knowledge_key="python.variables",
        )
        assert current["session_version"] == 1
        assert conn.execute(
            "SELECT count(*) AS count FROM tutor_teaching_action_receipts WHERE run_id=%s", (run_id,),
        ).fetchone()["count"] == 0


def test_teaching_step_provider_contract_is_strict_and_message_bound() -> None:
    from datetime import UTC, datetime

    from app.agents.harness.contracts import TutorPolicySnapshot, TutorRunSnapshot
    from app.services.tutor.decision_protocol import (
        TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
        TutorDecisionValidationError,
        parse_tutor_provider_items,
        tutor_provider_output_schema,
    )

    run = TutorRunSnapshot(
        run_id="teaching-provider-run", conversation_id="teaching-provider-conversation",
        user_id="teaching-provider-user", origin="interactive", input_revision=0,
        policy=TutorPolicySnapshot(deadline=datetime(2030, 1, 1, tzinfo=UTC)),
    )
    payload = {
        "schema_version": TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
        "message": {
            "type": "agent_message", "public_thinking_text": "只处理一个教学目的。",
            "text": "先解释变量绑定。", "conversation_title": "变量绑定",
        },
        "action": {
            "type": "teaching_step", "action": "explain_concept",
            "objective_id": "knowledge:python.variables", "focus_id": "knowledge:python.variables",
            "source_handles": ["knowledge:python.variables"], "public_message": "先解释变量绑定。",
            "focus_resolution": "stay", "pause_kind": "soft_pause", "escalation_hint": None,
            "teaching_moves": ["targeted_explanation", "worked_example"],
            "interaction": {"mode": "none", "intent": "none", "artifact_handle": None},
        },
    }
    decision = parse_tutor_provider_items(payload, run=run)
    assert decision.teaching_step is not None
    assert decision.teaching_step.teaching_moves is not None
    assert [move.value for move in decision.teaching_step.teaching_moves] == ["targeted_explanation", "worked_example"]
    assert decision.teaching_step.learner_response_mode is not None
    assert decision.teaching_step.learner_response_mode.value == "none"
    assert decision.teaching_step.interaction is not None
    assert decision.teaching_step.interaction.intent.value == "none"
    assert decision.terminal_outcome is TutorTerminalOutcome.COMPLETED
    teaching_schema = tutor_provider_output_schema()["$defs"]["TutorProviderTeachingStepItem"]
    assert teaching_schema["required"][-1] == "interaction"
    assert "learner_response_mode" not in teaching_schema["properties"]
    assert len(teaching_schema["properties"]["interaction"]["anyOf"]) == 8

    legacy_v2_action = {
        key: value for key, value in payload["action"].items() if key != "interaction"
    }
    legacy_v2_action["learner_response_mode"] = "none"
    legacy_v2 = {**payload, "schema_version": "tutor_provider_items_v4", "action": legacy_v2_action}
    legacy_v2_decision = parse_tutor_provider_items(legacy_v2, run=run)
    assert legacy_v2_decision.teaching_step is not None
    assert legacy_v2_decision.teaching_step.interaction is None
    assert legacy_v2_decision.teaching_step.learner_response_mode is not None

    legacy_v1 = {
        **legacy_v2,
        "action": {
            key: value
            for key, value in legacy_v2_action.items()
            if key not in {"teaching_moves", "learner_response_mode"}
        },
    }
    legacy_v1_decision = parse_tutor_provider_items(legacy_v1, run=run)
    assert legacy_v1_decision.teaching_step is not None
    assert legacy_v1_decision.teaching_step.teaching_moves is None
    assert legacy_v1_decision.teaching_step.learner_response_mode is None

    payload["action"]["unknown"] = True
    with pytest.raises(TutorDecisionValidationError):
        parse_tutor_provider_items(payload, run=run)
    del payload["action"]["unknown"]
    payload["action"]["public_message"] = "另一段内容"
    with pytest.raises(TutorDecisionValidationError):
        parse_tutor_provider_items(payload, run=run)


def test_stale_session_after_provider_is_cancelled_without_publication() -> None:
    with connection() as conn:
        scope, opened, run_id = _open_guided(conn)
        session_id = str(opened["teaching_session"]["session_id"])

    def make_stale() -> None:
        with connection() as stale_conn:
            TeachingSessionService(stale_conn).action(
                user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), session_id=session_id,
                control=TeachingControlStimulus(
                    control_key="switch_mode", client_action_id="stale-switch",
                    expected_session_version=1, expected_track_version=1,
                    expected_progress_version=1, expected_assignment_version=1,
                    safe_payload={"target_mode": "free_reading"},
                ),
                target_mode=TeachingSessionMode.FREE_READING, admit_run=False,
                idempotency_key="stale-switch",
            )

    provider = _TeachingProvider(before_teaching_step=make_stale)
    result = TutorInteractiveRunDispatcher(
        settings=Settings(llm_type="disabled", tutor_thread_turn_v2_enabled=True),
        provider_factory=lambda settings: provider,
    ).dispatch(user_id=str(scope["user_id"]), run_id=run_id)
    assert result.terminal_outcome is TutorTerminalOutcome.CANCELLED
    assert result.diagnostic_code == "teaching_authority_stale"
    with connection() as conn:
        current = TeachingSessionService(conn).current(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), knowledge_key="python.variables",
        )
        assert current["session_version"] == 2 and current["mode"] == "free_reading"
        assert conn.execute(
            "SELECT count(*) AS count FROM tutor_teaching_action_receipts WHERE run_id=%s", (run_id,),
        ).fetchone()["count"] == 0
        assert conn.execute(
            "SELECT count(*) AS count FROM tutor_messages WHERE conversation_id=%s AND role='tutor'",
            (scope["conversation_id"],),
        ).fetchone()["count"] == 0


def test_progress_authority_refresh_creates_successor_and_commits_completion_pause() -> None:
    with connection() as conn:
        scope = create_teaching_scope(conn)
        first = TeachingSessionService(conn).open(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), knowledge_key="python.variables",
            conversation_id=str(scope["conversation_id"]), expected_track_version=1,
            expected_progress_version=1, expected_assignment_version=1,
            mode=TeachingSessionMode.FREE_READING, idempotency_key="completion-refresh-initial",
        )
        first_session_id = str(first["teaching_session"]["session_id"])
        conn.execute(
            """UPDATE tutor_track_node_progress
               SET status='completed',started_at=COALESCE(started_at,now()),completed_at=now(),version=version+1
               WHERE track_id=%s AND knowledge_key='python.variables'""",
            (scope["track_id"],),
        )
        conn.commit()

    with connection() as conn:
        refreshed = TeachingSessionService(conn).open(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), knowledge_key="python.variables",
            conversation_id=str(scope["conversation_id"]), expected_track_version=1,
            expected_progress_version=2, expected_assignment_version=1,
            mode=TeachingSessionMode.GUIDED, idempotency_key="completion-refresh-guided",
        )
        pending = refreshed["pending_run"]
        assert isinstance(pending, dict)
        run_id = str(pending["run_id"])
        successor_id = str(refreshed["teaching_session"]["session_id"])
        assert successor_id != first_session_id
        predecessor = conn.execute(
            "SELECT status FROM tutor_teaching_sessions WHERE id=%s",
            (first_session_id,),
        ).fetchone()
        successor = conn.execute(
            "SELECT predecessor_session_id FROM tutor_teaching_sessions WHERE id=%s",
            (successor_id,),
        ).fetchone()
        assert predecessor is not None and predecessor["status"] == "blocked"
        assert successor is not None and str(successor["predecessor_session_id"]) == first_session_id

    provider = _TeachingProvider(completion=True)
    result = TutorInteractiveRunDispatcher(
        settings=Settings(llm_type="disabled", tutor_thread_turn_v2_enabled=True),
        provider_factory=lambda settings: provider,
    ).dispatch(user_id=str(scope["user_id"]), run_id=run_id)
    assert result.terminal_outcome is TutorTerminalOutcome.COMPLETED
    with connection() as conn:
        current = TeachingSessionService(conn).current(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), knowledge_key="python.variables",
        )
        assert current["session_id"] == successor_id
        assert current["status"] == "completed"
        assert current["checkpoint"]["pause_reason"] == "completion_pause"
        assert current["action_shelf"]["state"] == "completion"
        reopened = TeachingSessionService(conn).open(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]),
            knowledge_key="python.variables", conversation_id=str(scope["conversation_id"]),
            expected_track_version=1, expected_progress_version=2,
            expected_assignment_version=1, mode=TeachingSessionMode.GUIDED,
            idempotency_key="completion-reload-open",
        )
        assert reopened["created"] is False
        assert reopened["pending_run"] is None
        assert reopened["teaching_session"]["session_id"] == successor_id
        assert reopened["teaching_session"]["status"] == "completed"
        assert reopened["teaching_session"]["action_shelf"]["state"] == "completion"
        assert conn.execute(
            "SELECT count(*) AS count FROM tutor_runs WHERE conversation_id=%s",
            (scope["conversation_id"],),
        ).fetchone()["count"] == 1


def test_completion_pause_requires_explicit_latest_roadmap_transition() -> None:
    import json
    from uuid import uuid4

    from app.services.learning.teaching_contracts import canonical_hash

    with connection() as conn:
        scope = create_teaching_scope(conn)
        opened = TeachingSessionService(conn).open(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), knowledge_key="python.variables",
            conversation_id=str(scope["conversation_id"]), expected_track_version=1,
            expected_progress_version=1, expected_assignment_version=1,
            mode=TeachingSessionMode.FREE_READING, idempotency_key="completion-open",
        )
        session = opened["teaching_session"]
        revision = conn.execute(
            "SELECT revision_id FROM tutor_track_active_plans WHERE track_id=%s", (scope["track_id"],),
        ).fetchone()
        assert revision is not None
        suffix = uuid4().hex
        standard = conn.execute(
            """INSERT INTO tutor_lesson_documents (
                 document_kind,knowledge_key,language_id,schema_version,content_standard_version,generator_version,
                 policy_version,source_set_hash,title,coverage_keys_json,blocks_json,content_hash
               ) VALUES ('standard','python.functions','python','lesson_document_v1','programming_language_lesson_v1',
                 %s,'teaching-test-v1',%s,'Functions','["python.functions"]'::jsonb,'[]'::jsonb,%s) RETURNING id""",
            (f"next-{suffix}", suffix.ljust(64, "0")[:64], ("a" + suffix).ljust(64, "0")[:64]),
        ).fetchone()
        assert standard is not None
        document = conn.execute(
            """INSERT INTO tutor_lesson_documents (
                 document_kind,user_id,track_id,knowledge_key,language_id,active_plan_revision_id,standard_document_id,
                 schema_version,content_standard_version,generator_version,policy_version,source_set_hash,profile_hash,
                 title,coverage_keys_json,blocks_json,content_hash
               ) VALUES ('personalized',%s,%s,'python.functions','python',%s,%s,'lesson_document_v1',
                 'programming_language_lesson_v1',%s,'teaching-test-v1',%s,%s,'Functions for learner',
                 '["python.functions"]'::jsonb,'[]'::jsonb,%s) RETURNING id""",
            (scope["user_id"], scope["track_id"], revision["revision_id"], standard["id"], f"next-{suffix}",
             ("b" + suffix).ljust(64, "0")[:64], ("c" + suffix).ljust(64, "0")[:64],
             ("d" + suffix).ljust(64, "0")[:64]),
        ).fetchone()
        assert document is not None
        conn.execute(
            """INSERT INTO tutor_lesson_assignments (
                 user_id,track_id,knowledge_key,document_id,source_plan_revision_id,assignment_version,status,
                 expected_progress_version,content_hash,activated_at
               ) VALUES (%s,%s,'python.functions',%s,%s,1,'active',2,%s,now())""",
            (scope["user_id"], scope["track_id"], document["id"], revision["revision_id"], ("e" + suffix).ljust(64, "0")[:64]),
        )
        conn.execute(
            """UPDATE tutor_track_node_progress
               SET status='completed',started_at=COALESCE(started_at,now()),completed_at=now(),version=version+1
               WHERE track_id=%s AND knowledge_key='python.variables'""",
            (scope["track_id"],),
        )
        conn.execute(
            "UPDATE tutor_track_node_progress SET status='available',version=version+1 WHERE track_id=%s AND knowledge_key='python.functions'",
            (scope["track_id"],),
        )
        checkpoint = conn.execute(
            "SELECT * FROM tutor_teaching_session_checkpoints WHERE id=%s", (session["checkpoint_id"],),
        ).fetchone()
        assert checkpoint is not None
        state = dict(checkpoint["state_json"])
        state["pause_reason"] = "completion_pause"
        state["recommended_action_key"] = "enter_next_knowledge"
        authority = dict(checkpoint["authority_snapshot_json"])
        authority["progress_version"] = 2
        source_hash = canonical_hash({"state": state, "authority": authority, "session_version": 2})
        next_checkpoint = conn.execute(
            """INSERT INTO tutor_teaching_session_checkpoints (
                 teaching_session_id,user_id,conversation_id,predecessor_checkpoint_id,session_version,
                 state_json,authority_snapshot_json,source_hash
               ) VALUES (%s,%s,%s,%s,2,%s::jsonb,%s::jsonb,%s) RETURNING id""",
            (session["session_id"], scope["user_id"], scope["conversation_id"], session["checkpoint_id"],
             json.dumps(state), json.dumps(authority), source_hash),
        ).fetchone()
        assert next_checkpoint is not None
        conn.execute(
            """UPDATE tutor_teaching_sessions SET status='completed',current_checkpoint_id=%s,version=2,
                 completed_at=now(),last_activity_at=now() WHERE id=%s""",
            (next_checkpoint["id"], session["session_id"]),
        )
        conn.commit()

        completed = TeachingSessionService(conn).current(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), knowledge_key="python.variables",
        )
        assert completed["status"] == "completed"
        assert completed["action_shelf"]["primary_action"]["key"] == "enter_next_knowledge"
        assert conn.execute(
            "SELECT count(*) AS count FROM tutor_runs WHERE conversation_id=%s", (scope["conversation_id"],),
        ).fetchone()["count"] == 0

        with pytest.raises(TeachingSessionServiceError) as wrong_candidate:
            TeachingSessionService(conn).action(
                user_id=str(scope["user_id"]), track_id=str(scope["track_id"]),
                session_id=str(session["session_id"]),
                control=TeachingControlStimulus(
                    control_key="enter_next_knowledge", client_action_id="enter-wrong-candidate",
                    expected_session_version=2, expected_track_version=1,
                    expected_progress_version=2, expected_assignment_version=1,
                    safe_payload={"target_knowledge_key": "python.variables"},
                ),
                target_mode=None, admit_run=False, idempotency_key="enter-wrong-candidate",
            )
        assert wrong_candidate.value.code == "TEACHING_AUTHORITY_CONFLICT"
        assert conn.execute(
            "SELECT current_knowledge_key,version FROM tutor_learning_tracks WHERE id=%s",
            (scope["track_id"],),
        ).fetchone() == {"current_knowledge_key": "python.variables", "version": 1}

        transitioned = TeachingSessionService(conn).action(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]),
            session_id=str(session["session_id"]),
            control=TeachingControlStimulus(
                control_key="enter_next_knowledge", client_action_id="enter-functions",
                expected_session_version=2, expected_track_version=1,
                expected_progress_version=2, expected_assignment_version=1,
                safe_payload={"target_knowledge_key": "python.functions"},
            ),
            target_mode=None, admit_run=False, idempotency_key="enter-functions",
        )
        assert transitioned["transitioned"] is True
        assert transitioned["next_teaching_session"]["knowledge_key"] == "python.functions"
        assert transitioned["pending_run"]["stimulus_kind"] == "teaching_control"
        track = conn.execute(
            "SELECT current_knowledge_key,version FROM tutor_learning_tracks WHERE id=%s", (scope["track_id"],),
        ).fetchone()
        assert track is not None and track["current_knowledge_key"] == "python.functions" and track["version"] == 2
        assert conn.execute(
            "SELECT count(*) AS count FROM tutor_conversations WHERE id=%s", (scope["conversation_id"],),
        ).fetchone()["count"] == 1
