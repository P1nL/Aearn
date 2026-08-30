from __future__ import annotations

import json

import pytest

from app.agents.harness.context_builder import TutorContextBuilder, TutorContextBuilderConfig
from app.agents.harness.contracts import (
    TutorContextError,
    TutorContextSection,
    TutorDecision,
    TutorProviderResult,
    TutorSkillReference,
    TutorTerminalOutcome,
)
from app.agents.harness.provider_request import build_tutor_provider_messages
from app.core.config import Settings
from app.services.learning.teaching_contracts import (
    TeachingControlStimulus,
    TeachingSessionMode,
    TeachingStepDecision,
)
from app.services.learning.teaching_sessions import TeachingSessionService
from app.services.tutor.interactive import (
    PostgresTutorContextLoader,
    PostgresTutorLearningContextLoader,
    TutorInteractiveRunDispatcher,
)
from app.services.tutor.learner_state import TutorLearnerStateRepository
from app.services.tutor.persistence import PostgresTutorRepository
from app.services.tutor.ports import SequenceTutorProvider
from tests.support.teaching_session_support import connection, create_teaching_scope, database_available

pytestmark = pytest.mark.skipif(not database_available(), reason="PostgreSQL is not available")


def test_required_teaching_context_contains_exact_session_stimulus_and_handles() -> None:
    with connection() as conn:
        scope = create_teaching_scope(conn)
        opened = TeachingSessionService(conn).open(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), knowledge_key="python.variables",
            conversation_id=str(scope["conversation_id"]), expected_track_version=1,
            expected_progress_version=1, expected_assignment_version=1,
            mode=TeachingSessionMode.GUIDED, idempotency_key="teaching-context-open",
        )
        pending = opened["pending_run"]
        assert isinstance(pending, dict)
        run_id = str(pending["run_id"])
        snapshot = PostgresTutorRepository(conn).load_snapshot(user_id=str(scope["user_id"]), run_id=run_id)
        assert snapshot is not None and snapshot.input_revision == 0
        loader = PostgresTutorLearningContextLoader(
            conn=conn,
            base_loader=PostgresTutorContextLoader(
                conn=conn, learner_state=TutorLearnerStateRepository(conn),
            ),
        )
        context_input = loader.load_context(snapshot, input_revision=0)
        assert context_input.current_input is None
        assert len(context_input.teaching_session) == 1
        teaching = context_input.teaching_session[0].content
        assert isinstance(teaching, dict)
        assert teaching["stimulus"]["kind"] == "teaching_control"
        assert teaching["session"]["session_id"] == opened["teaching_session"]["session_id"]
        assert "knowledge:python.variables" in teaching["allowed_source_handles"]
        selection = TutorContextBuilder(
            config=TutorContextBuilderConfig(max_source_characters=4000),
        ).build(context_input, token_budget=5000)
        section = next(item for item in selection.checkpoint_metadata.sections if item.section is TutorContextSection.TEACHING_SESSION)
        assert section.selected_count == 1 and section.skipped_count == 0


def test_required_teaching_context_fails_closed_before_provider_when_unrepresentable() -> None:
    with connection() as conn:
        scope = create_teaching_scope(conn)
        opened = TeachingSessionService(conn).open(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), knowledge_key="python.variables",
            conversation_id=str(scope["conversation_id"]), expected_track_version=1,
            expected_progress_version=1, expected_assignment_version=1,
            mode=TeachingSessionMode.GUIDED, idempotency_key="teaching-context-budget",
        )
        pending = opened["pending_run"]
        assert isinstance(pending, dict)
        snapshot = PostgresTutorRepository(conn).load_snapshot(
            user_id=str(scope["user_id"]), run_id=str(pending["run_id"]),
        )
        assert snapshot is not None
        loader = PostgresTutorLearningContextLoader(
            conn=conn,
            base_loader=PostgresTutorContextLoader(conn=conn, learner_state=TutorLearnerStateRepository(conn)),
        )
        context_input = loader.load_context(snapshot, input_revision=0)
        with pytest.raises(TutorContextError) as error:
            TutorContextBuilder(
                config=TutorContextBuilderConfig(max_source_characters=80),
            ).build(context_input, token_budget=40)
        assert error.value.safe_code == "TUTOR_TEACHING_SESSION_UNREPRESENTABLE"


def test_teaching_control_context_includes_prior_same_session_messages() -> None:
    with connection() as conn:
        scope = create_teaching_scope(conn)
        conn.execute(
            "INSERT INTO tutor_messages (conversation_id,role,content) VALUES (%s,'tutor','旧分段消息不得进入当前教学连续性。')",
            (scope["conversation_id"],),
        )
        opened = TeachingSessionService(conn).open(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), knowledge_key="python.variables",
            conversation_id=str(scope["conversation_id"]), expected_track_version=1,
            expected_progress_version=1, expected_assignment_version=1,
            mode=TeachingSessionMode.GUIDED, idempotency_key="teaching-context-continuity-open",
        )
        pending = opened["pending_run"]
        assert isinstance(pending, dict)
        first_run_id = str(pending["run_id"])

    first_message = "变量让名称引用一个值。先看一个最小赋值例子。"
    provider = SequenceTutorProvider((
        TutorProviderResult(
            decision=TutorDecision(
                skill_references=(TutorSkillReference("tutor.lesson-teaching", "1.1.0"),),
            ),
        ),
        TutorProviderResult(
            decision=TutorDecision(
                public_message=first_message,
                public_thinking_text="先建立一个最小概念，再等待下一步。",
                terminal_outcome=TutorTerminalOutcome.COMPLETED,
                teaching_step=TeachingStepDecision(
                    action="explain_concept",
                    objective_id="knowledge:python.variables",
                    focus_id="knowledge:python.variables",
                    source_handles=("knowledge:python.variables",),
                    public_message=first_message,
                    focus_resolution="stay",
                    pause_kind="soft_pause",
                    escalation_hint=None,
                    teaching_moves=("targeted_explanation", "worked_example"),
                    learner_response_mode="none",
                ),
            ),
        ),
    ))
    result = TutorInteractiveRunDispatcher(
        settings=Settings(llm_type="disabled", tutor_thread_turn_v2_enabled=True),
        provider_factory=lambda settings: provider,
    ).dispatch(user_id=str(scope["user_id"]), run_id=first_run_id)
    assert result.terminal_outcome is TutorTerminalOutcome.COMPLETED

    with connection() as conn:
        service = TeachingSessionService(conn)
        current = service.current(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), knowledge_key="python.variables",
        )
        continued = service.action(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]),
            session_id=str(current["session_id"]),
            control=TeachingControlStimulus(
                control_key="continue",
                client_action_id="teaching-context-continuity-continue",
                expected_session_version=int(current["session_version"]),
                expected_track_version=int(current["track_version"]),
                expected_progress_version=int(current["progress_version"]),
                expected_assignment_version=int(current["assignment_version"]),
            ),
            target_mode=None,
            admit_run=True,
            idempotency_key="teaching-context-continuity-continue",
        )
        next_pending = continued["pending_run"]
        assert isinstance(next_pending, dict)
        next_run_id = str(next_pending["run_id"])
        snapshot = PostgresTutorRepository(conn).load_snapshot(
            user_id=str(scope["user_id"]), run_id=next_run_id,
        )
        assert snapshot is not None and snapshot.input_revision == 0
        context_input = PostgresTutorLearningContextLoader(
            conn=conn,
            base_loader=PostgresTutorContextLoader(
                conn=conn, learner_state=TutorLearnerStateRepository(conn),
            ),
        ).load_context(snapshot, input_revision=0)

        assert context_input.current_input is None
        teaching_context = context_input.teaching_session[0].content
        assert isinstance(teaching_context, dict)
        serialized_teaching_context = json.dumps(
            teaching_context, ensure_ascii=False, separators=(",", ":"),
        )
        assert len(serialized_teaching_context) <= 1200
        assert teaching_context["recent_teaching_units"] == [{
            "action": "explain_concept",
            "focus_id": "knowledge:python.variables",
            "teaching_moves": ["targeted_explanation", "worked_example"],
            "learner_response_mode": "none",
            "public_message_hash": teaching_context["recent_teaching_units"][0]["public_message_hash"],
            "schema_version": "teaching_action_receipt_v2",
        }]
        assert first_message not in serialized_teaching_context
        assert [source.content for source in context_input.recent_messages] == [
            {"role": "assistant", "content": first_message},
        ]
        selection = TutorContextBuilder(
            config=TutorContextBuilderConfig(max_source_characters=4000),
        ).build(context_input, token_budget=5000)
        recent = [
            item for item in selection.items
            if item.section is TutorContextSection.RECENT_MESSAGES
        ]
        assert len(recent) == 1
        assert first_message in recent[0].content
        provider_messages = build_tutor_provider_messages(run=snapshot, context=selection)
        system = provider_messages[0]["content"]
        assert "recent_messages are bounded learner-visible continuity" in system
        assert "instead of restarting or substantially paraphrasing" in system
        assert "First select exact tutor.lesson-teaching@1.1.0" in system
        assert "recent_teaching_units" in system
        assert "learner_response_mode=composer" in system
