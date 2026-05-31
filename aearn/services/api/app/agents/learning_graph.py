"""LangGraph-based learning conversation state machine.

This module defines the AgentState schema and learning graph skeleton
that will eventually replace the imperative orchestration in learning_conversation.py.

Enabled via LANGGRAPH_ENABLED=true environment variable.
"""
from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph


class LearningStageState(TypedDict, total=False):
    covered_subpoint_ids: list[str]
    feynman_status: str
    practice_unlock_reason: str | None
    learning_incomplete: bool
    concept_summary: str
    active_concept_intro: dict[str, Any] | None
    active_concept_check: dict[str, Any] | None
    concept_check_attempts: int
    concept_check_result: str | None
    previous_misconceptions: list[str]


class AgentState(TypedDict, total=False):
    request_id: str
    user_id: str
    plan_id: str
    session_id: str
    session_type: str
    learning_stage: str
    learning_stage_state: LearningStageState
    knowledge_point: dict[str, Any]
    lesson_outline: list[dict[str, Any]]
    lesson_sources: list[dict[str, Any]]
    exercise: dict[str, Any] | None
    runtime_result: dict[str, Any] | None
    code_completion_result: dict[str, Any] | None
    hint_state: dict[str, Any]
    explanation_state: dict[str, Any]
    memory_snapshot: dict[str, Any]
    messages: list[dict[str, str]]
    side_effects: list[dict[str, Any]]
    next_action: str | None
    errors: list[str]
    current_node: str


# --- Node functions ---

def context_assembler(state: AgentState) -> dict[str, Any]:
    """Load knowledge point context into state."""
    return {
        "current_node": "context_assembler",
        "memory_snapshot": state.get("memory_snapshot", {}),
    }


def concept_intro(state: AgentState) -> dict[str, Any]:
    """Generate concept introduction based on lesson outline."""
    return {
        "current_node": "concept_intro",
        "learning_stage": "concept_intro",
    }


def concept_check(state: AgentState) -> dict[str, Any]:
    """Evaluate user's understanding of the concept."""
    stage_state = dict(state.get("learning_stage_state", {}))
    attempts = _as_int(stage_state.get("concept_check_attempts"), 0) + 1
    stage_state["concept_check_attempts"] = attempts
    return {
        "current_node": "concept_check",
        "learning_stage": "concept_check",
        "learning_stage_state": stage_state,
    }


def _as_int(value: object, default: int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def concept_repair(state: AgentState) -> dict[str, Any]:
    """Repair misconceptions with simpler examples."""
    return {
        "current_node": "concept_repair",
        "learning_stage": "concept_repair",
    }


def practice_offer(state: AgentState) -> dict[str, Any]:
    """Offer transition to practice mode."""
    stage_state = dict(state.get("learning_stage_state", {}))
    stage_state["practice_unlock_reason"] = stage_state.get("practice_unlock_reason") or "concept_check_passed"
    return {
        "current_node": "practice_offer",
        "learning_stage": "practice_support",
        "learning_stage_state": stage_state,
    }


def select_exercise(state: AgentState) -> dict[str, Any]:
    """Select an appropriate exercise for the knowledge point."""
    return {
        "current_node": "select_exercise",
        "learning_stage": "practice_support",
    }


def persist_side_effects(state: AgentState) -> dict[str, Any]:
    """Drain side_effects queue and commit to database."""
    return {
        "current_node": "persist_side_effects",
        "side_effects": [],
    }


# --- Routing functions ---

def route_after_context(state: AgentState) -> str:
    """Route after context assembly based on current learning stage."""
    stage = state.get("learning_stage", "concept_intro")
    if stage in ("practice_support",):
        return "select_exercise"
    if stage in ("concept_check",):
        return "concept_check"
    if stage in ("concept_repair",):
        return "concept_repair"
    return "concept_intro"


def route_after_check(state: AgentState) -> str:
    """Route after concept check based on result."""
    stage_state = state.get("learning_stage_state", {})
    result = stage_state.get("concept_check_result")
    if result == "correct":
        return "practice_offer"
    if result == "incorrect":
        attempts = int(stage_state.get("concept_check_attempts", 0))
        if attempts >= 3:
            return "practice_offer"
        return "concept_repair"
    return "practice_offer"


def route_after_repair(state: AgentState) -> str:
    """Route after concept repair."""
    stage_state = state.get("learning_stage_state", {})
    result = stage_state.get("concept_check_result")
    if result == "correct":
        return "practice_offer"
    attempts = int(stage_state.get("concept_check_attempts", 0))
    if attempts >= 3:
        return "practice_offer"
    return "concept_check"


# --- Graph builder ---

def build_learning_graph() -> StateGraph:
    """Build the learning conversation state graph."""
    graph = StateGraph(AgentState)

    graph.add_node("context_assembler", context_assembler)
    graph.add_node("concept_intro", concept_intro)
    graph.add_node("concept_check", concept_check)
    graph.add_node("concept_repair", concept_repair)
    graph.add_node("practice_offer", practice_offer)
    graph.add_node("select_exercise", select_exercise)
    graph.add_node("persist_side_effects", persist_side_effects)

    graph.set_entry_point("context_assembler")

    graph.add_conditional_edges("context_assembler", route_after_context, {
        "concept_intro": "concept_intro",
        "concept_check": "concept_check",
        "concept_repair": "concept_repair",
        "select_exercise": "select_exercise",
    })

    graph.add_edge("concept_intro", "concept_check")

    graph.add_conditional_edges("concept_check", route_after_check, {
        "practice_offer": "practice_offer",
        "concept_repair": "concept_repair",
    })

    graph.add_conditional_edges("concept_repair", route_after_repair, {
        "practice_offer": "practice_offer",
        "concept_check": "concept_check",
    })

    graph.add_edge("practice_offer", "select_exercise")
    graph.add_edge("select_exercise", "persist_side_effects")
    graph.add_edge("persist_side_effects", END)

    return graph


def compile_learning_graph():
    """Compile the learning graph for execution."""
    graph = build_learning_graph()
    return graph.compile()
