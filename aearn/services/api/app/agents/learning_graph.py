"""LangGraph-based learning conversation state machine.

This module defines the AgentState schema and learning graph skeleton
that will eventually replace the imperative orchestration in learning_conversation.py.

Enabled via LANGGRAPH_ENABLED=true environment variable.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.agents.graph_runtime_contracts import (
    GraphFallback,
    GraphRunResult,
    IntentType,
    build_fallback,
    build_checkpoint_thread_state,
    build_run_result,
    make_intent,
)


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
    rag_context: dict[str, Any]
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


# --- Orchestration graph ---
# Single-step decision graph that replaces _determine_transition().
# Each invocation makes one routing decision based on current stage + user text.


class OrchestrationInput(TypedDict, total=False):
    session_id: str
    user_id: str
    learning_stage: str
    learning_stage_state: dict[str, Any]
    user_text: str
    knowledge_point: dict[str, Any]
    lesson_outline: list[dict[str, Any]]
    memory_snapshot: dict[str, Any]
    rag_context: dict[str, Any]
    # Output fields set by nodes
    next_stage: str
    tool_name: str | None
    tool_names: list[str]
    learner_content: str
    next_state: dict[str, Any]


_PRACTICE_TRIGGERS = [
    "开始练习", "给我题", "进入练习", "引导练习", "做题",
    "我准备好了", "直接练习", "practice", "exercise",
]

_HISTORY_TRIGGERS = ["历史对话", "学习对话", "回看", "查看对话", "history"]

_QUESTION_TOKENS = ["为什么", "怎么", "什么", "区别", "如何"]

_CONCEPT_HELP_TRIGGERS = [
    "30 秒", "30秒", "讲清", "解释一下", "最小例子",
    "行为变化", "举个例子", "给我例子", "不知道怎么开始",
]

_CONCEPT_HELP_CHOICES = {
    "1", "2", "3", "一", "二", "三",
    "选1", "选2", "选3", "第1个", "第2个", "第3个",
}

_REASON_TOKENS = [
    "因为", "所以", "作用", "原因", "重要", "会",
    "影响", "共享", "保存", "触发", "because", "so",
]

_CONCEPT_TOKENS_EXTRA = [
    "事件", "状态", "回调", "DOM", "作用域", "返回值", "stdout", "函数", "断言",
]


def _text_matches(text: str, triggers: Sequence[str]) -> bool:
    lowered = text.lower()
    return any(t in lowered for t in triggers)


def _is_question(text: str) -> bool:
    lowered = text.lower()
    return "?" in lowered or "？" in lowered or _text_matches(text, _QUESTION_TOKENS)


def _is_concept_help(text: str) -> bool:
    choice = text.lower().strip().strip(" \t\r\n。.!！?？、")
    if choice in _CONCEPT_HELP_CHOICES:
        return True
    return _text_matches(text, _CONCEPT_HELP_TRIGGERS)


def _passes_feynman(
    text: str,
    knowledge_point: Mapping[str, Any],
    lesson_outline: Sequence[Mapping[str, Any]],
) -> bool:
    stripped = text.strip()
    if len(stripped) < 28:
        return False
    concept_tokens = [str(knowledge_point.get("title") or "")]
    concept_tokens.extend(
        str(item.get("title") or "")
        for item in lesson_outline
        if isinstance(item, Mapping)
    )
    concept_tokens.extend(_CONCEPT_TOKENS_EXTRA)
    lowered = stripped.lower()
    has_reason = any(t.lower() in lowered for t in _REASON_TOKENS)
    has_concept = any(t and t.lower() in lowered for t in concept_tokens)
    return has_reason and has_concept


def _subpoint_ids(lesson_outline: Sequence[Mapping[str, Any]]) -> list[str]:
    return [
        str(item.get("id"))
        for item in lesson_outline
        if isinstance(item, Mapping) and item.get("id")
    ]


def _build_concept_summary(
    knowledge_point: Mapping[str, Any],
    lesson_outline: Sequence[Mapping[str, Any]],
) -> str:
    items = [
        f"{item.get('title')}：{item.get('note')}"
        for item in lesson_outline[:3]
        if isinstance(item, Mapping)
    ]
    return "；".join(items) or str(knowledge_point.get("title") or "当前知识点")


def _practice_unlock_reason(stage: str, state: Mapping[str, Any]) -> str:
    if stage == "practice_offer":
        return "concept_check_passed"
    if _as_int(state.get("concept_check_attempts"), 0) >= 2 or state.get("repair_limit_reached") is True:
        return "concept_check_repair_limit"
    if stage in {"concept_check", "concept_repair"}:
        return "concept_check_skipped"
    return "early_request"


# --- Orchestration node functions ---


def _orch_classify(state: OrchestrationInput) -> dict[str, Any]:
    """Entry node: pass through, routing is done via conditional edges."""
    return {}


def _orch_practice_support(state: OrchestrationInput) -> dict[str, Any]:
    """Already in practice_support, no transition needed."""
    current_state = dict(state.get("learning_stage_state") or {})
    return {
        "next_stage": "practice_support",
        "tool_name": None,
        "learner_content": "",
        "next_state": current_state,
    }


def _orch_history(state: OrchestrationInput) -> dict[str, Any]:
    """User requests history."""
    current_state = dict(state.get("learning_stage_state") or {})
    return {
        "next_stage": state.get("learning_stage", "concept_intro"),
        "tool_name": "show_learning_history",
        "tool_names": ["show_learning_history"],
        "learner_content": "",
        "next_state": current_state,
    }


def _orch_practice_request(state: OrchestrationInput) -> dict[str, Any]:
    """User requests practice unlock."""
    current_state = dict(state.get("learning_stage_state") or {})
    stage = state.get("learning_stage", "concept_intro")
    outline = state.get("lesson_outline") or []
    kp = state.get("knowledge_point") or {}
    unlock_reason = _practice_unlock_reason(stage, current_state)
    current_state.update({
        "covered_subpoint_ids": _subpoint_ids(outline),
        "feynman_status": "pending",
        "practice_unlock_reason": unlock_reason,
        "learning_incomplete": unlock_reason != "concept_check_passed",
        "concept_summary": _build_concept_summary(kp, outline),
    })
    if unlock_reason == "concept_check_skipped":
        current_state["concept_check_result"] = "skipped"
    tool_names = ["show_code_exercise"]
    if unlock_reason in {"concept_check_skipped", "concept_check_repair_limit"}:
        tool_names = ["show_concept_check_result", "show_code_exercise"]
    return {
        "next_stage": "practice_support",
        "tool_name": "show_code_exercise",
        "tool_names": tool_names,
        "learner_content": "",
        "next_state": current_state,
    }


def _orch_concept_check_answer(state: OrchestrationInput) -> dict[str, Any]:
    """User answers concept check/repair question."""
    current_state = dict(state.get("learning_stage_state") or {})
    stage = state.get("learning_stage", "concept_check")
    outline = state.get("lesson_outline") or []
    kp = state.get("knowledge_point") or {}
    current_state.update({
        "covered_subpoint_ids": _subpoint_ids(outline),
        "practice_unlock_reason": None,
        "learning_incomplete": True,
        "concept_summary": _build_concept_summary(kp, outline),
    })
    return {
        "next_stage": stage,
        "tool_name": "show_concept_check_result",
        "tool_names": ["show_concept_check_result"],
        "learner_content": state.get("user_text", ""),
        "next_state": current_state,
    }


def _orch_concept_qna(state: OrchestrationInput) -> dict[str, Any]:
    """User asks a question during concept intro."""
    current_state = dict(state.get("learning_stage_state") or {})
    outline = state.get("lesson_outline") or []
    kp = state.get("knowledge_point") or {}
    current_state.update({
        "covered_subpoint_ids": _subpoint_ids(outline),
        "feynman_status": "pending",
        "practice_unlock_reason": None,
        "learning_incomplete": True,
        "concept_summary": _build_concept_summary(kp, outline),
    })
    return {
        "next_stage": "concept_qna",
        "tool_name": None,
        "learner_content": "",
        "next_state": current_state,
    }


def _orch_readiness_check(state: OrchestrationInput) -> dict[str, Any]:
    """User provides a statement during concept intro (not a question)."""
    current_state = dict(state.get("learning_stage_state") or {})
    outline = state.get("lesson_outline") or []
    kp = state.get("knowledge_point") or {}
    current_state.update({
        "covered_subpoint_ids": _subpoint_ids(outline),
        "feynman_status": "pending",
        "practice_unlock_reason": None,
        "learning_incomplete": True,
        "concept_summary": _build_concept_summary(kp, outline),
    })
    return {
        "next_stage": "readiness_check",
        "tool_name": None,
        "learner_content": "",
        "next_state": current_state,
    }


def _orch_feynman_pass(state: OrchestrationInput) -> dict[str, Any]:
    """User passes feynman check."""
    current_state = dict(state.get("learning_stage_state") or {})
    outline = state.get("lesson_outline") or []
    kp = state.get("knowledge_point") or {}
    current_state.update({
        "covered_subpoint_ids": _subpoint_ids(outline),
        "feynman_status": "passed",
        "practice_unlock_reason": "feynman_passed",
        "learning_incomplete": False,
        "concept_summary": _build_concept_summary(kp, outline),
    })
    return {
        "next_stage": "practice_support",
        "tool_name": "show_code_exercise",
        "tool_names": ["show_code_exercise"],
        "learner_content": "",
        "next_state": current_state,
    }


def _orch_feynman_fail(state: OrchestrationInput) -> dict[str, Any]:
    """User fails feynman check."""
    current_state = dict(state.get("learning_stage_state") or {})
    kp = state.get("knowledge_point") or {}
    outline = state.get("lesson_outline") or []
    current_state.update({
        "feynman_status": "failed",
        "learning_incomplete": True,
        "concept_summary": _build_concept_summary(kp, outline),
    })
    return {
        "next_stage": "readiness_check",
        "tool_name": "show_learning_history",
        "tool_names": ["show_learning_history"],
        "learner_content": "",
        "next_state": current_state,
    }


def _orch_passthrough(state: OrchestrationInput) -> dict[str, Any]:
    """Default: no transition change."""
    current_state = dict(state.get("learning_stage_state") or {})
    return {
        "next_stage": state.get("learning_stage", "concept_intro"),
        "tool_name": None,
        "learner_content": "",
        "next_state": current_state,
    }


# --- Orchestration routing ---


def _route_orchestration(state: OrchestrationInput) -> str:
    """Main routing decision for the orchestration graph."""
    stage = state.get("learning_stage", "concept_intro")
    user_text = state.get("user_text", "")

    if stage == "practice_support":
        return "practice_support"

    if _text_matches(user_text, _HISTORY_TRIGGERS):
        return "history"

    if _text_matches(user_text, _PRACTICE_TRIGGERS):
        return "practice_request"

    if stage in {"concept_check", "concept_repair"}:
        return "concept_check_answer"

    if stage in {"concept_intro", "concept_qna"}:
        if _is_question(user_text) or _is_concept_help(user_text):
            return "concept_qna"
        return "readiness_check"

    if stage == "readiness_check":
        kp = state.get("knowledge_point") or {}
        outline = state.get("lesson_outline") or []
        if _passes_feynman(user_text, kp, outline):
            return "feynman_pass"
        return "feynman_fail"

    return "passthrough"


# --- Orchestration graph builder ---


def build_orchestration_graph() -> StateGraph:
    """Build the single-step orchestration decision graph."""
    graph = StateGraph(OrchestrationInput)

    graph.add_node("classify", _orch_classify)
    graph.add_node("practice_support", _orch_practice_support)
    graph.add_node("history", _orch_history)
    graph.add_node("practice_request", _orch_practice_request)
    graph.add_node("concept_check_answer", _orch_concept_check_answer)
    graph.add_node("concept_qna", _orch_concept_qna)
    graph.add_node("readiness_check", _orch_readiness_check)
    graph.add_node("feynman_pass", _orch_feynman_pass)
    graph.add_node("feynman_fail", _orch_feynman_fail)
    graph.add_node("passthrough", _orch_passthrough)

    graph.set_entry_point("classify")

    graph.add_conditional_edges("classify", _route_orchestration, {
        "practice_support": "practice_support",
        "history": "history",
        "practice_request": "practice_request",
        "concept_check_answer": "concept_check_answer",
        "concept_qna": "concept_qna",
        "readiness_check": "readiness_check",
        "feynman_pass": "feynman_pass",
        "feynman_fail": "feynman_fail",
        "passthrough": "passthrough",
    })

    for node in (
        "practice_support", "history", "practice_request",
        "concept_check_answer", "concept_qna", "readiness_check",
        "feynman_pass", "feynman_fail", "passthrough",
    ):
        graph.add_edge(node, END)

    return graph


_compiled_orchestration_graph = None


def compile_orchestration_graph():
    """Compile and cache the orchestration graph."""
    global _compiled_orchestration_graph  # noqa: PLW0603
    if _compiled_orchestration_graph is None:
        _compiled_orchestration_graph = build_orchestration_graph().compile()
    return _compiled_orchestration_graph


def invoke_orchestration(
    *,
    session_id: str,
    user_id: str,
    learning_stage: str,
    learning_stage_state: Mapping[str, Any],
    user_text: str,
    knowledge_point: Mapping[str, Any],
    lesson_outline: Sequence[Mapping[str, Any]],
    memory_snapshot: Mapping[str, Any] | None = None,
    rag_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Invoke the orchestration graph and return the decision."""
    compiled = compile_orchestration_graph()
    input_state: OrchestrationInput = {
        "session_id": session_id,
        "user_id": user_id,
        "learning_stage": learning_stage,
        "learning_stage_state": dict(learning_stage_state),
        "user_text": user_text,
        "knowledge_point": dict(knowledge_point) if isinstance(knowledge_point, Mapping) else {},
        "lesson_outline": [dict(item) for item in lesson_outline if isinstance(item, Mapping)],
        "memory_snapshot": dict(memory_snapshot or {}),
        "rag_context": dict(rag_context or {}),
    }
    thread_state = build_checkpoint_thread_state(
        session_id=session_id,
        user_id=user_id,
        session_type="learning",
        checkpoint_ns="learning_orchestration",
    )
    result = compiled.invoke(input_state, thread_state.to_config())
    raw_result = {
        "next_stage": result.get("next_stage", learning_stage),
        "tool_name": result.get("tool_name"),
        "tool_names": result.get("tool_names", []),
        "learner_content": result.get("learner_content", ""),
        "next_state": result.get("next_state", dict(learning_stage_state)),
    }
    return {
        **raw_result,
        "run_result": graph_result_to_run_result(raw_result),
    }


# --- Shared contract adapters ---


def graph_result_to_run_result(result: Mapping[str, Any]) -> GraphRunResult:
    """Convert raw learning graph output to a shared GraphRunResult."""
    intents = []
    next_stage = str(
        result.get("next_stage")
        or result.get("learning_stage")
        or result.get("current_node")
        or ""
    )
    next_state = result.get("next_state")
    learner_content = str(result.get("learner_content") or "")
    if isinstance(next_state, Mapping):
        intents.append(make_intent(
            IntentType.STAGE_UPDATE,
            "learning_session",
            {
                "learning_stage": next_stage,
                "learning_stage_state": dict(next_state),
                "learner_content": learner_content,
            },
        ))
    tool_names = _result_tool_names(result)
    for tool_name in tool_names:
        intents.append(make_intent(
            IntentType.TOOL_CALL,
            str(tool_name),
            {
                "name": str(tool_name),
                "learner_content": learner_content,
            },
        ))
    next_action = result.get("next_action")
    if next_action:
        intents.append(make_intent(IntentType.STAGE_UPDATE, "learning_session", {"next_action": next_action}))
    for effect in result.get("side_effects") or []:
        if isinstance(effect, dict):
            intents.append(make_intent(IntentType.SIDE_EFFECT, str(effect.get("type", "unknown")), effect))
    return build_run_result(
        next_stage=next_stage,
        intents=intents,
        diagnostics="",
        safe_context={"current_node": result.get("current_node", "")},
    )


def graph_error_to_fallback(error: Exception, *, fallback_stage: str) -> GraphFallback:
    """Convert a graph execution error to a safe GraphFallback."""
    return build_fallback(
        reason=str(error),
        fallback_stage=fallback_stage,
        safe_message="图执行异常，回退到服务层编排。",
        recoverable=True,
    )


def _result_tool_names(result: Mapping[str, Any]) -> list[str]:
    tool_names = result.get("tool_names")
    if isinstance(tool_names, Sequence) and not isinstance(tool_names, (str, bytes)):
        return [str(item) for item in tool_names if str(item).strip()]
    tool_name = result.get("tool_name")
    return [str(tool_name)] if tool_name else []
