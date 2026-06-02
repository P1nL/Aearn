"""LangGraph-based review conversation orchestration.

Owns flow decisions for review start, due-state validation routing,
exercise result handling, FSRS update coordination, and review coach feedback.

Services/repositories still own session creation, attempt writes,
ReviewState updates, ReviewLog writes, idempotency, and public response envelopes.
"""
from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.agents.graphs.graph_runtime_contracts import (
    GraphFallback,
    GraphRunResult,
    IntentType,
    build_fallback,
    build_run_result,
    make_intent,
)


class ReviewOrchInput(TypedDict, total=False):
    session_id: str
    user_id: str
    knowledge_point_id: str
    action: str  # "start", "submit", "warmup", "message"
    is_due: bool
    has_active_session: bool
    attempt_result: str | None  # "passed", "failed", "partial"
    fsrs_rating: str | None  # "Again", "Hard", "Good", "Easy"
    explanation_ready: bool
    coach_feedback_requested: bool
    # Output fields
    next_action: str
    intent_type: str
    intent_payload: dict[str, Any]


_VALID_FSRS_RATINGS = {"Again", "Hard", "Good", "Easy"}


# --- Node functions ---


def _orch_classify(state: ReviewOrchInput) -> dict[str, Any]:
    """Entry node: routing is done via conditional edges."""
    return {}


def _orch_reject_not_due(state: ReviewOrchInput) -> dict[str, Any]:
    """Knowledge point is not due for review."""
    return {
        "next_action": "reject_not_due",
        "intent_type": "none",
        "intent_payload": {
            "reason": "knowledge point not due for review",
            "knowledge_point_id": state.get("knowledge_point_id", ""),
        },
    }


def _orch_start_session(state: ReviewOrchInput) -> dict[str, Any]:
    """Start a new review session."""
    return {
        "next_action": "start_session",
        "intent_type": "persistence",
        "intent_payload": {
            "target": "review_session",
            "user_id": state.get("user_id", ""),
            "knowledge_point_id": state.get("knowledge_point_id", ""),
        },
    }


def _orch_reuse_session(state: ReviewOrchInput) -> dict[str, Any]:
    """Reuse existing active review session."""
    return {
        "next_action": "reuse_session",
        "intent_type": "none",
        "intent_payload": {
            "session_id": state.get("session_id", ""),
        },
    }


def _orch_submit_result(state: ReviewOrchInput) -> dict[str, Any]:
    """Process exercise submission and trigger FSRS update."""
    rating = state.get("fsrs_rating") or "Good"
    if rating not in _VALID_FSRS_RATINGS:
        rating = "Good"
    return {
        "next_action": "submit_and_update",
        "intent_type": "persistence",
        "intent_payload": {
            "target": "attempt_and_fsrs",
            "session_id": state.get("session_id", ""),
            "fsrs_rating": rating,
            "attempt_result": state.get("attempt_result", ""),
        },
    }


def _orch_coach_feedback(state: ReviewOrchInput) -> dict[str, Any]:
    """Route to review coach for feedback generation."""
    return {
        "next_action": "coach_feedback",
        "intent_type": "tool_call",
        "intent_payload": {
            "tool": "review_coach",
            "session_id": state.get("session_id", ""),
            "attempt_result": state.get("attempt_result", ""),
        },
    }


def _orch_warmup(state: ReviewOrchInput) -> dict[str, Any]:
    """Handle warmup question response."""
    return {
        "next_action": "warmup",
        "intent_type": "tool_call",
        "intent_payload": {
            "tool": "evaluate_warmup",
            "session_id": state.get("session_id", ""),
        },
    }


def _orch_continue(state: ReviewOrchInput) -> dict[str, Any]:
    """Default: continue review conversation."""
    return {
        "next_action": "continue",
        "intent_type": "none",
        "intent_payload": {},
    }


# --- Routing ---


def _route_review(state: ReviewOrchInput) -> str:
    """Main routing decision for review orchestration."""
    action = state.get("action", "")

    if action == "start":
        if not state.get("is_due", False):
            return "reject_not_due"
        if state.get("has_active_session", False):
            return "reuse_session"
        return "start_session"

    if action == "submit":
        return "submit_result"

    if action == "warmup":
        return "warmup"

    if action == "message":
        if state.get("coach_feedback_requested", False):
            return "coach_feedback"
        return "continue"

    return "continue"


# --- Graph builder ---


def build_review_orchestration_graph() -> StateGraph:
    """Build the review orchestration decision graph."""
    graph = StateGraph(ReviewOrchInput)

    graph.add_node("classify", _orch_classify)
    graph.add_node("reject_not_due", _orch_reject_not_due)
    graph.add_node("start_session", _orch_start_session)
    graph.add_node("reuse_session", _orch_reuse_session)
    graph.add_node("submit_result", _orch_submit_result)
    graph.add_node("coach_feedback", _orch_coach_feedback)
    graph.add_node("warmup", _orch_warmup)
    graph.add_node("continue", _orch_continue)

    graph.set_entry_point("classify")

    graph.add_conditional_edges("classify", _route_review, {
        "reject_not_due": "reject_not_due",
        "start_session": "start_session",
        "reuse_session": "reuse_session",
        "submit_result": "submit_result",
        "coach_feedback": "coach_feedback",
        "warmup": "warmup",
        "continue": "continue",
    })

    for node in (
        "reject_not_due", "start_session", "reuse_session",
        "submit_result", "coach_feedback", "warmup", "continue",
    ):
        graph.add_edge(node, END)

    return graph


_compiled_review_graph = None


def compile_review_orchestration_graph():
    """Compile and cache the review orchestration graph."""
    global _compiled_review_graph  # noqa: PLW0603
    if _compiled_review_graph is None:
        _compiled_review_graph = build_review_orchestration_graph().compile()
    return _compiled_review_graph


def invoke_review_orchestration(
    *,
    session_id: str = "",
    user_id: str,
    knowledge_point_id: str,
    action: str,
    is_due: bool = True,
    has_active_session: bool = False,
    attempt_result: str | None = None,
    fsrs_rating: str | None = None,
    explanation_ready: bool = False,
    coach_feedback_requested: bool = False,
) -> dict[str, Any]:
    """Invoke the review orchestration graph and return the decision."""
    compiled = compile_review_orchestration_graph()
    input_state: ReviewOrchInput = {
        "session_id": session_id,
        "user_id": user_id,
        "knowledge_point_id": knowledge_point_id,
        "action": action,
        "is_due": is_due,
        "has_active_session": has_active_session,
        "attempt_result": attempt_result,
        "fsrs_rating": fsrs_rating,
        "explanation_ready": explanation_ready,
        "coach_feedback_requested": coach_feedback_requested,
    }
    result = compiled.invoke(input_state)
    return {
        "next_action": result.get("next_action", "continue"),
        "intent_type": result.get("intent_type", "none"),
        "intent_payload": result.get("intent_payload", {}),
    }


# --- Shared contract adapters ---


def review_result_to_run_result(result: dict[str, Any]) -> GraphRunResult:
    """Convert review orchestration output to a shared GraphRunResult."""
    intents = []
    next_action = result.get("next_action", "continue")
    intent_type_str = result.get("intent_type", "none")

    if intent_type_str == "persistence":
        intents.append(make_intent(
            IntentType.PERSISTENCE,
            str(result.get("intent_payload", {}).get("target", "review")),
            result.get("intent_payload", {}),
        ))
    elif intent_type_str == "tool_call":
        intents.append(make_intent(
            IntentType.TOOL_CALL,
            str(result.get("intent_payload", {}).get("tool", "unknown")),
            result.get("intent_payload", {}),
        ))

    return build_run_result(
        next_stage=next_action,
        intents=intents,
        diagnostics="",
        safe_context={"action": next_action},
    )


def review_error_to_fallback(error: Exception, *, fallback_action: str) -> GraphFallback:
    """Convert a review graph error to a safe GraphFallback."""
    return build_fallback(
        reason=str(error),
        fallback_stage=fallback_action,
        safe_message="复习编排异常，回退到服务层。",
        recoverable=True,
    )
