"""Deterministic teaching focus reducer and server-owned Action Shelf projection."""
from __future__ import annotations

from typing import Literal

from app.services.learning.teaching_contracts import (
    TeachingAction,
    TeachingActionDescriptor,
    TeachingActionShelfV1,
    TeachingCheckpointState,
    TeachingFocus,
    TeachingFocusResolution,
    TeachingPauseReason,
    TeachingQuestion,
    TeachingSessionMode,
    TeachingStepDecision,
)

_MAX_FOCUS_DEPTH = 4
_MAX_QUESTIONS = 8


def reduce_teaching_checkpoint(
    *, state: TeachingCheckpointState, step: TeachingStepDecision,
    mode: TeachingSessionMode, stimulus_id: str, source_message_id: str | None,
) -> TeachingCheckpointState:
    if step.objective_id != state.objective.objective_id:
        raise ValueError("teaching objective is stale")
    active = state.active_focus
    suspended = list(state.suspended_focuses)
    questions = list(state.unresolved_questions)
    candidate = TeachingFocus(
        focus_id=step.focus_id,
        focus_kind="question" if step.focus_resolution is TeachingFocusResolution.PUSH_CHILD else "knowledge",
        summary=_focus_summary(step.action),
        source_handles=step.source_handles or (f"stimulus:{stimulus_id}",),
    )
    if step.focus_resolution is TeachingFocusResolution.PUSH_CHILD:
        if active is not None and active.focus_id != candidate.focus_id:
            suspended.append(active)
        suspended = suspended[-_MAX_FOCUS_DEPTH:]
        active = candidate
        questions = [item for item in questions if item.question_id != candidate.focus_id]
        questions.append(
            TeachingQuestion(
                question_id=candidate.focus_id,
                summary="当前学习者问题",
                state="open",
                source_message_id=source_message_id,
            )
        )
    elif step.focus_resolution is TeachingFocusResolution.RESOLVE_AND_RESUME_PARENT:
        parent = next((item for item in reversed(suspended) if item.focus_id == step.focus_id), None)
        if parent is None:
            raise ValueError("parent teaching focus is unavailable")
        resolved_focus_id = active.focus_id if active is not None else None
        active = parent
        suspended = [item for item in suspended if item.focus_id != parent.focus_id]
        questions = [item for item in questions if item.question_id != resolved_focus_id]
    elif step.focus_resolution is TeachingFocusResolution.REPLACE_OBJECTIVE:
        active, suspended = candidate, []
        questions = [item for item in questions if item.question_id == candidate.focus_id]
    elif step.focus_resolution is TeachingFocusResolution.ABANDON_BRANCH:
        active = suspended.pop() if suspended else TeachingFocus(
            focus_id=state.objective.objective_id,
            focus_kind="knowledge",
            summary=state.objective.summary,
            source_handles=state.objective.source_handles,
        )
        questions = [item for item in questions if item.question_id != step.focus_id]
    elif step.focus_resolution is TeachingFocusResolution.STAY:
        if active is None:
            active = candidate
    elif step.focus_resolution is TeachingFocusResolution.WAIT:
        pass
    else:  # pragma: no cover - closed enum
        raise ValueError("unsupported focus resolution")
    covered = list(state.covered_concepts)
    if step.action in {TeachingAction.EXPLAIN_CONCEPT, TeachingAction.SUMMARIZE_PROGRESS}:
        concept = state.objective.objective_id.removeprefix("knowledge:")
        if concept not in covered:
            covered.append(concept)
    recommended = _recommended_action(step=step, mode=mode, has_parent=bool(suspended))
    return TeachingCheckpointState(
        objective=state.objective,
        active_focus=active,
        suspended_focuses=tuple(suspended[-_MAX_FOCUS_DEPTH:]),
        unresolved_questions=tuple(questions[-_MAX_QUESTIONS:]),
        covered_concepts=tuple(covered[-32:]),
        evidence_cursors=state.evidence_cursors,
        pause_reason=step.pause_kind,
        recommended_action_key=recommended,
    )


def build_teaching_action_shelf(
    *, session_id: str, session_version: int, checkpoint_id: str,
    mode: TeachingSessionMode, state: TeachingCheckpointState,
    track_version: int, progress_version: int, assignment_version: int,
    runtime_active: bool, blocking_request: bool, progress_status: str,
    next_knowledge_key: str | None,
) -> TeachingActionShelfV1:
    versions = {
        "session": session_version, "track": track_version,
        "progress": progress_version, "assignment": assignment_version,
    }
    if runtime_active:
        return TeachingActionShelfV1(
            teaching_session_id=session_id, session_version=session_version,
            checkpoint_id=checkpoint_id, state="runtime_active",
        )
    if blocking_request:
        return TeachingActionShelfV1(
            teaching_session_id=session_id, session_version=session_version,
            checkpoint_id=checkpoint_id, state="blocking_request",
        )
    if progress_status == "completed" or state.pause_reason is TeachingPauseReason.COMPLETION_PAUSE:
        primary = (
            _action("enter_next_knowledge", "进入下一知识点", "primary", versions, target_id=next_knowledge_key)
            if next_knowledge_key is not None else None
        )
        return TeachingActionShelfV1(
            teaching_session_id=session_id, session_version=session_version,
            checkpoint_id=checkpoint_id, state="completion", primary_action=primary,
            secondary_actions=(
                _navigation("view_feedback", "查看练习反馈"),
                _navigation("start_review", "开始复习"),
                _navigation("return_roadmap", "返回路线"),
            ),
        )
    if state.pause_reason is TeachingPauseReason.SESSION_PAUSE:
        return TeachingActionShelfV1(
            teaching_session_id=session_id, session_version=session_version,
            checkpoint_id=checkpoint_id, state="ready",
            primary_action=_action("resume", "恢复学习", "primary", versions),
            secondary_actions=(_navigation("return_roadmap", "返回路线"),),
        )
    if state.pause_reason is TeachingPauseReason.EVIDENCE_PAUSE:
        return TeachingActionShelfV1(
            teaching_session_id=session_id, session_version=session_version,
            checkpoint_id=checkpoint_id, state="ready",
            primary_action=_navigation("open_evidence", "查看练习状态", emphasis="primary"),
            secondary_actions=(_action("pause", "稍后继续", "quiet", versions),),
        )
    if mode is TeachingSessionMode.FREE_READING:
        primary = (
            _action("escalate_guided", "转为引导讲解", "primary", versions)
            if state.recommended_action_key == "escalate_guided" else None
        )
        return TeachingActionShelfV1(
            teaching_session_id=session_id, session_version=session_version,
            checkpoint_id=checkpoint_id, state="free_reading", primary_action=primary,
            secondary_actions=(_navigation("continue_reading", "继续阅读"),),
        )
    secondary = [_action("change_example", "换个例子", "secondary", versions)]
    if state.suspended_focuses:
        secondary.append(_action("return_focus", "返回主线", "secondary", versions))
    secondary.append(_action("pause", "暂停", "quiet", versions))
    return TeachingActionShelfV1(
        teaching_session_id=session_id, session_version=session_version,
        checkpoint_id=checkpoint_id, state="ready",
        primary_action=_action("continue", "继续", "primary", versions),
        secondary_actions=tuple(secondary[:3]),
    )


def _recommended_action(*, step: TeachingStepDecision, mode: TeachingSessionMode, has_parent: bool) -> str:
    if step.pause_kind is TeachingPauseReason.COMPLETION_PAUSE:
        return "enter_next_knowledge"
    if mode is TeachingSessionMode.FREE_READING:
        return "escalate_guided" if step.escalation_hint is not None else "continue_reading"
    if has_parent and step.focus_resolution in {TeachingFocusResolution.STAY, TeachingFocusResolution.WAIT}:
        return "return_focus"
    if step.pause_kind is TeachingPauseReason.EVIDENCE_PAUSE:
        return "open_evidence"
    if step.pause_kind in {TeachingPauseReason.AUTHORITY_PAUSE, TeachingPauseReason.SESSION_PAUSE}:
        return "resume"
    return "continue"


def _focus_summary(action: TeachingAction) -> str:
    return {
        TeachingAction.ORIENT: "定位当前学习目标",
        TeachingAction.EXPLAIN_CONCEPT: "解释当前概念",
        TeachingAction.ANSWER_QUESTION: "回答当前问题",
        TeachingAction.SHOW_EXAMPLE: "查看当前示例",
        TeachingAction.COMPARE_EXAMPLES: "比较当前示例",
        TeachingAction.CHECK_UNDERSTANDING: "检查当前理解",
        TeachingAction.RECOMMEND_PRACTICE: "选择下一练习",
        TeachingAction.EXPLAIN_FEEDBACK: "解释当前反馈",
        TeachingAction.REMEDIATE_PREREQUISITE: "补充当前前置知识",
        TeachingAction.SUMMARIZE_PROGRESS: "总结当前学习进展",
        TeachingAction.RECOMMEND_PAUSE: "建议暂停",
        TeachingAction.WAIT_FOR_INPUT: "等待学习者输入",
    }[action]


def _action(
    key: str, label: str, emphasis: Literal["primary", "secondary", "quiet"],
    versions: dict[str, int], *, target_id: str | None = None,
) -> TeachingActionDescriptor:
    return TeachingActionDescriptor(
        key=key, label=label, emphasis=emphasis, target_kind="teaching_control",
        target_id=target_id, expected_versions=versions,
    )


def _navigation(
    key: str, label: str, *, emphasis: Literal["primary", "secondary", "quiet"] = "secondary",
) -> TeachingActionDescriptor:
    return TeachingActionDescriptor(
        key=key, label=label, emphasis=emphasis, target_kind="navigation",
    )
