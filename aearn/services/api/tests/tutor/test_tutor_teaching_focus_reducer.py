from __future__ import annotations

from app.services.learning.teaching_contracts import (
    TeachingCheckpointState,
    TeachingFocus,
    TeachingObjective,
    TeachingPauseReason,
    TeachingSessionMode,
    TeachingStepDecision,
)
from app.services.learning.teaching_loop import build_teaching_action_shelf, reduce_teaching_checkpoint


def _state() -> TeachingCheckpointState:
    return TeachingCheckpointState(
        objective=TeachingObjective(
            objective_id="knowledge:python.variables", summary="Variables",
            source_handles=("knowledge:python.variables",),
        ),
        active_focus=TeachingFocus(
            focus_id="knowledge:python.variables", focus_kind="knowledge", summary="Variables",
            source_handles=("knowledge:python.variables",),
        ),
        recommended_action_key="continue",
    )


def test_focus_reducer_pushes_bounded_interruption_and_resumes_parent() -> None:
    child = reduce_teaching_checkpoint(
        state=_state(), mode=TeachingSessionMode.GUIDED, stimulus_id="stimulus-1", source_message_id="message-1",
        step=TeachingStepDecision(
            action="answer_question", objective_id="knowledge:python.variables", focus_id="stimulus:stimulus-1",
            source_handles=("knowledge:python.variables",), public_message="先回答当前问题。",
            focus_resolution="push_child", pause_kind="soft_pause",
        ),
    )
    assert child.active_focus is not None and child.active_focus.focus_id == "stimulus:stimulus-1"
    assert [item.focus_id for item in child.suspended_focuses] == ["knowledge:python.variables"]
    assert child.unresolved_questions[0].source_message_id == "message-1"

    resumed = reduce_teaching_checkpoint(
        state=child, mode=TeachingSessionMode.GUIDED, stimulus_id="stimulus-2", source_message_id=None,
        step=TeachingStepDecision(
            action="summarize_progress", objective_id="knowledge:python.variables",
            focus_id="knowledge:python.variables", source_handles=("knowledge:python.variables",),
            public_message="这个问题已回答，现在返回变量主线。",
            focus_resolution="resolve_and_resume_parent", pause_kind="soft_pause",
        ),
    )
    assert resumed.active_focus is not None and resumed.active_focus.focus_id == "knowledge:python.variables"
    assert resumed.suspended_focuses == ()
    assert resumed.unresolved_questions == ()


def test_composer_response_recommendation_suppresses_continue_without_hiding_secondary_controls() -> None:
    state = reduce_teaching_checkpoint(
        state=_state(), mode=TeachingSessionMode.GUIDED, stimulus_id="stimulus-check", source_message_id=None,
        step=TeachingStepDecision(
            action="check_understanding", objective_id="knowledge:python.variables",
            focus_id="knowledge:python.variables", source_handles=("knowledge:python.variables",),
            public_message="预测下一行输出，并指出理由。", focus_resolution="stay", pause_kind="soft_pause",
            teaching_moves=("guided_derivation", "prediction"), learner_response_mode="composer",
        ),
    )
    assert state.recommended_action_key == "respond_in_composer"
    shelf = build_teaching_action_shelf(
        session_id="session-1", session_version=2, checkpoint_id="checkpoint-2",
        mode=TeachingSessionMode.GUIDED, state=state, track_version=1,
        progress_version=1, assignment_version=1, runtime_active=False,
        blocking_request=False, progress_status="in_progress", next_knowledge_key=None,
    )
    assert shelf.primary_action is None
    assert [item.key for item in shelf.secondary_actions] == ["change_example", "pause"]


def test_free_reading_escalation_and_action_shelf_are_server_owned() -> None:
    state = reduce_teaching_checkpoint(
        state=_state(), mode=TeachingSessionMode.FREE_READING, stimulus_id="stimulus-free", source_message_id="message-free",
        step=TeachingStepDecision(
            action="answer_question", objective_id="knowledge:python.variables",
            focus_id="knowledge:python.variables", source_handles=("knowledge:python.variables",),
            public_message="先给出有限回答。", focus_resolution="stay", pause_kind="soft_pause",
            escalation_hint="这个问题可以转为连续引导讲解。",
        ),
    )
    shelf = build_teaching_action_shelf(
        session_id="session-1", session_version=2, checkpoint_id="checkpoint-2",
        mode=TeachingSessionMode.FREE_READING, state=state, track_version=1,
        progress_version=1, assignment_version=1, runtime_active=False,
        blocking_request=False, progress_status="in_progress", next_knowledge_key=None,
    )
    assert shelf.state == "free_reading"
    assert shelf.primary_action is not None and shelf.primary_action.key == "escalate_guided"
    assert len(shelf.secondary_actions) <= 3

    runtime = build_teaching_action_shelf(
        session_id="session-1", session_version=2, checkpoint_id="checkpoint-2",
        mode=TeachingSessionMode.GUIDED, state=state, track_version=1,
        progress_version=1, assignment_version=1, runtime_active=True,
        blocking_request=False, progress_status="in_progress", next_knowledge_key=None,
    )
    assert runtime.state == "runtime_active"
    assert runtime.primary_action is None and runtime.secondary_actions == ()

    paused = build_teaching_action_shelf(
        session_id="session-1", session_version=3, checkpoint_id="checkpoint-3",
        mode=TeachingSessionMode.FREE_READING,
        state=state.model_copy(update={"pause_reason": TeachingPauseReason.SESSION_PAUSE}),
        track_version=1, progress_version=1, assignment_version=1,
        runtime_active=False, blocking_request=False, progress_status="in_progress",
        next_knowledge_key=None,
    )
    assert paused.primary_action is not None and paused.primary_action.key == "resume"

    evidence = build_teaching_action_shelf(
        session_id="session-1", session_version=4, checkpoint_id="checkpoint-4",
        mode=TeachingSessionMode.GUIDED,
        state=state.model_copy(update={"pause_reason": TeachingPauseReason.EVIDENCE_PAUSE}),
        track_version=1, progress_version=1, assignment_version=1,
        runtime_active=False, blocking_request=False, progress_status="in_progress",
        next_knowledge_key=None,
    )
    assert evidence.primary_action is not None and evidence.primary_action.key == "open_evidence"
    assert evidence.primary_action.target_kind == "navigation"
