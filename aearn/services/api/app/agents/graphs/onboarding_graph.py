"""LangGraph-based onboarding conversation orchestration.

Owns flow decisions for slot collection, StructuredJudgement routing,
clarification, route generation, route revision, and plan confirmation gating.

Services still own durable writes, idempotency, route-card persistence,
and public response shape.
"""
from __future__ import annotations

from collections.abc import Sequence
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


class OnboardingOrchInput(TypedDict, total=False):
    conversation_id: str
    user_id: str
    status: str
    user_text: str
    plan_ready: bool
    has_stashed_draft: bool
    revising: bool
    language: str | None
    target_level: str | None
    goal_text: str | None
    missing_slot_question: str | None
    core_slots_changed: bool
    # Output fields
    next_action: str
    intent_type: str
    intent_payload: dict[str, Any]


_CONFIRM_TRIGGERS = ["确认", "开始学习", "就这样", "可以", "没问题", "confirm"]
_REVISION_TRIGGERS = ["改", "换", "调整", "修改", "重新", "revise", "change"]


def _text_matches(text: str, triggers: Sequence[str]) -> bool:
    lowered = text.lower()
    return any(t in lowered for t in triggers)


# --- Node functions ---


def _orch_classify(state: OnboardingOrchInput) -> dict[str, Any]:
    """Entry node: routing is done via conditional edges."""
    return {}


def _orch_clarify(state: OnboardingOrchInput) -> dict[str, Any]:
    """Slots are incomplete, need clarification."""
    return {
        "next_action": "clarify",
        "intent_type": "feedback_request",
        "intent_payload": {
            "question": state.get("missing_slot_question") or "",
        },
    }


def _orch_generate_route(state: OnboardingOrchInput) -> dict[str, Any]:
    """All required slots filled, trigger route generation."""
    return {
        "next_action": "generate_route",
        "intent_type": "tool_call",
        "intent_payload": {
            "tool": "build_plan_draft",
            "language": state.get("language"),
            "target_level": state.get("target_level"),
            "goal_text": state.get("goal_text"),
        },
    }


def _orch_revise_route(state: OnboardingOrchInput) -> dict[str, Any]:
    """User wants to revise the existing route."""
    return {
        "next_action": "revise_route",
        "intent_type": "tool_call",
        "intent_payload": {
            "tool": "rebuild_plan_draft",
            "language": state.get("language"),
            "target_level": state.get("target_level"),
            "goal_text": state.get("goal_text"),
        },
    }


def _orch_await_confirm(state: OnboardingOrchInput) -> dict[str, Any]:
    """Route card is shown, waiting for user confirmation."""
    return {
        "next_action": "await_confirm",
        "intent_type": "feedback_request",
        "intent_payload": {
            "message": "路线卡片已展示，等待用户确认或修改。",
        },
    }


def _orch_confirm_plan(state: OnboardingOrchInput) -> dict[str, Any]:
    """User confirmed the stashed route draft."""
    return {
        "next_action": "confirm_plan",
        "intent_type": "persistence",
        "intent_payload": {
            "target": "confirm_plan",
            "conversation_id": state.get("conversation_id", ""),
            "user_id": state.get("user_id", ""),
        },
    }


def _orch_continue_chat(state: OnboardingOrchInput) -> dict[str, Any]:
    """Default: continue normal onboarding chat."""
    return {
        "next_action": "continue_chat",
        "intent_type": "none",
        "intent_payload": {},
    }


# --- Routing ---


def _route_onboarding(state: OnboardingOrchInput) -> str:
    """Main routing decision for onboarding orchestration."""
    plan_ready = state.get("plan_ready", False)
    has_draft = state.get("has_stashed_draft", False)
    user_text = state.get("user_text", "")
    revising = state.get("revising", False)
    core_changed = state.get("core_slots_changed", False)

    required_filled = bool(
        state.get("language")
        and state.get("target_level")
        and state.get("goal_text")
    )

    if has_draft and not revising and not core_changed:
        if _text_matches(user_text, _REVISION_TRIGGERS):
            return "revise_route"
        if _text_matches(user_text, _CONFIRM_TRIGGERS):
            return "confirm_plan"
        return "await_confirm"

    if plan_ready and required_filled:
        if has_draft and (revising or core_changed):
            return "revise_route"
        return "generate_route"

    if not plan_ready:
        return "clarify"

    return "continue_chat"


# --- Graph builder ---


def build_onboarding_orchestration_graph() -> StateGraph:
    """Build the onboarding orchestration decision graph."""
    graph = StateGraph(OnboardingOrchInput)

    graph.add_node("classify", _orch_classify)
    graph.add_node("clarify", _orch_clarify)
    graph.add_node("generate_route", _orch_generate_route)
    graph.add_node("revise_route", _orch_revise_route)
    graph.add_node("await_confirm", _orch_await_confirm)
    graph.add_node("confirm_plan", _orch_confirm_plan)
    graph.add_node("continue_chat", _orch_continue_chat)

    graph.set_entry_point("classify")

    graph.add_conditional_edges("classify", _route_onboarding, {
        "clarify": "clarify",
        "generate_route": "generate_route",
        "revise_route": "revise_route",
        "await_confirm": "await_confirm",
        "confirm_plan": "confirm_plan",
        "continue_chat": "continue_chat",
    })

    for node in (
        "clarify",
        "generate_route",
        "revise_route",
        "await_confirm",
        "confirm_plan",
        "continue_chat",
    ):
        graph.add_edge(node, END)

    return graph


_compiled_onboarding_graph = None


def compile_onboarding_orchestration_graph():
    """Compile and cache the onboarding orchestration graph."""
    global _compiled_onboarding_graph  # noqa: PLW0603
    if _compiled_onboarding_graph is None:
        _compiled_onboarding_graph = build_onboarding_orchestration_graph().compile()
    return _compiled_onboarding_graph


def invoke_onboarding_orchestration(
    *,
    conversation_id: str,
    user_id: str,
    status: str,
    user_text: str,
    plan_ready: bool,
    has_stashed_draft: bool,
    revising: bool,
    language: str | None,
    target_level: str | None,
    goal_text: str | None,
    missing_slot_question: str | None,
    core_slots_changed: bool,
) -> dict[str, Any]:
    """Invoke the onboarding orchestration graph and return the decision."""
    compiled = compile_onboarding_orchestration_graph()
    input_state: OnboardingOrchInput = {
        "conversation_id": conversation_id,
        "user_id": user_id,
        "status": status,
        "user_text": user_text,
        "plan_ready": plan_ready,
        "has_stashed_draft": has_stashed_draft,
        "revising": revising,
        "language": language,
        "target_level": target_level,
        "goal_text": goal_text,
        "missing_slot_question": missing_slot_question,
        "core_slots_changed": core_slots_changed,
    }
    result = compiled.invoke(input_state)
    return {
        "next_action": result.get("next_action", "continue_chat"),
        "intent_type": result.get("intent_type", "none"),
        "intent_payload": result.get("intent_payload", {}),
    }


# --- Shared contract adapters ---


def onboarding_result_to_run_result(result: dict[str, Any]) -> GraphRunResult:
    """Convert onboarding orchestration output to a shared GraphRunResult."""
    intents = []
    next_action = result.get("next_action", "continue_chat")
    intent_type_str = result.get("intent_type", "none")

    if intent_type_str == "tool_call":
        intents.append(make_intent(
            IntentType.TOOL_CALL,
            str(result.get("intent_payload", {}).get("tool", "unknown")),
            result.get("intent_payload", {}),
        ))
    elif intent_type_str == "persistence":
        intents.append(make_intent(
            IntentType.PERSISTENCE,
            str(result.get("intent_payload", {}).get("target", "onboarding")),
            result.get("intent_payload", {}),
        ))
    elif intent_type_str == "feedback_request":
        intents.append(make_intent(
            IntentType.FEEDBACK_REQUEST,
            "onboarding_clarification",
            result.get("intent_payload", {}),
        ))

    return build_run_result(
        next_stage=next_action,
        intents=intents,
        diagnostics="",
        safe_context={"action": next_action},
    )


def onboarding_error_to_fallback(error: Exception, *, fallback_action: str) -> GraphFallback:
    """Convert an onboarding graph error to a safe GraphFallback."""
    return build_fallback(
        reason=str(error),
        fallback_stage=fallback_action,
        safe_message="建档编排异常，回退到服务层。",
        recoverable=True,
    )
