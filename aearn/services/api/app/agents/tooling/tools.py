from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from agents import Tool, function_tool

from app.agents.graphs.graph_runtime_contracts import GraphIntent, IntentType, make_intent


ALLOWED_TRANSITIONS: dict[str, list[str]] = {
    "documentation_reading": ["concept_qna", "readiness_check", "concept_check"],
    "concept_intro": ["concept_qna", "readiness_check", "concept_check"],
    "concept_qna": ["concept_intro", "readiness_check", "concept_check"],
    "readiness_check": ["concept_check", "practice_support", "concept_qna"],
    "concept_check": ["concept_repair", "practice_support"],
    "concept_repair": ["concept_check", "practice_support"],
    "practice_support": [],
}
MAX_TOOL_INTENTS = 20


@dataclass
class LearningToolContext:
    session_id: str
    exercise_id: str | None
    current_stage: str
    user_id: str | None = None
    knowledge_point_id: str | None = None
    exercise: Mapping[str, object] | None = None
    latest_attempt: Mapping[str, object] | None = None
    stage_state: Mapping[str, object] | None = None
    profile_summary: str = ""
    run_code_fn: Callable[[Mapping[str, object], str], dict[str, object]] | None = None


@dataclass
class AgentSideEffects:
    stage_updates: list[dict[str, object]] = field(default_factory=list)
    diagnosis_updates: list[dict[str, object]] = field(default_factory=list)
    attempt_records: list[dict[str, object]] = field(default_factory=list)
    profile_updates: list[dict[str, object]] = field(default_factory=list)
    typed_intents: list[GraphIntent] = field(default_factory=list)

    def has_stage_change(self) -> bool:
        return len(self.stage_updates) > 0

    def final_stage(self, current: str) -> str:
        if not self.stage_updates:
            return current
        return str(self.stage_updates[-1].get("new_stage", current))


def build_teaching_tools(
    messages: Sequence[Mapping[str, str]],
    *,
    side_effects: AgentSideEffects | None = None,
    context: LearningToolContext | None = None,
) -> list[Tool]:
    evidence = extract_learning_evidence(messages)
    if evidence is None:
        return []

    current_context = summarize_current_learning_context(evidence)
    latest_attempt = summarize_latest_visible_attempt(evidence)
    tools: list[Tool] = []

    @function_tool(
        name_override="get_current_learning_context",
        description_override="Return a bounded, safe summary of the current Aearn learning context.",
    )
    def get_current_learning_context() -> dict[str, object]:
        return current_context

    @function_tool(
        name_override="get_latest_visible_attempt_summary",
        description_override="Return visible, non-secret facts about the learner's latest attempt.",
    )
    def get_latest_visible_attempt_summary() -> dict[str, object]:
        return latest_attempt

    tools.extend([get_current_learning_context, get_latest_visible_attempt_summary])

    note_summary = summarize_note_context(evidence)
    if note_summary:

        @function_tool(
            name_override="get_current_note_summary",
            description_override="Return a bounded summary of the current note context without full note bodies.",
        )
        def get_current_note_summary() -> dict[str, object]:
            return note_summary

        tools.append(get_current_note_summary)

    if side_effects is not None and context is not None:
        tools.extend(_build_write_tools(side_effects, context))

    return tools


def _build_write_tools(
    side_effects: AgentSideEffects,
    ctx: LearningToolContext,
) -> list[Tool]:
    tools: list[Tool] = []

    @function_tool(
        name_override="update_learning_stage",
        description_override=(
            "Transition the learning session to a new stage. "
            "Returns success or error if the transition is not allowed."
        ),
    )
    def update_learning_stage(new_stage: str, reason: str) -> dict[str, object]:
        return do_update_learning_stage(side_effects, ctx, new_stage, reason)

    @function_tool(
        name_override="record_diagnosis",
        description_override=(
            "Record a structured diagnosis of the learner's current state: "
            "stuck points, misconceptions, and recommended next action."
        ),
    )
    def record_diagnosis(
        stuck_point: str = "",
        misconceptions: str = "",
        recommended_action: str = "",
        concepts_explained: str = "",
    ) -> dict[str, object]:
        return do_record_diagnosis(
            side_effects,
            stuck_point=stuck_point,
            misconceptions=misconceptions,
            recommended_action=recommended_action,
            concepts_explained=concepts_explained,
        )

    @function_tool(
        name_override="trigger_code_run",
        description_override=(
            "Execute the learner's code against the current exercise and return "
            "structured results including stdout, stderr, and test pass/fail."
        ),
    )
    def trigger_code_run(code: str) -> dict[str, object]:
        return do_trigger_code_run(ctx, code, side_effects=side_effects)

    @function_tool(
        name_override="record_attempt",
        description_override=(
            "Record a code attempt (run or submit) for the current exercise."
        ),
    )
    def record_attempt(code: str, action: str = "run") -> dict[str, object]:
        return do_record_attempt(side_effects, ctx, code, action)

    tools.extend([update_learning_stage, record_diagnosis, trigger_code_run, record_attempt])

    @function_tool(
        name_override="update_learner_profile",
        description_override=(
            "Record a cross-session observation about the learner: weak points, "
            "error patterns, or learning preferences. These persist across sessions."
        ),
    )
    def update_learner_profile(
        observation_type: str,
        content: str,
        confidence: str = "ambiguous",
        key: str = "",
        value: str = "",
    ) -> dict[str, object]:
        return do_update_learner_profile(
            side_effects, ctx,
            observation_type=observation_type,
            content=content,
            confidence=confidence,
            key=key,
            value=value,
        )

    tools.append(update_learner_profile)

    if ctx.knowledge_point_id:
        @function_tool(
            name_override="search_teaching_materials",
            description_override=(
                "Search indexed teaching materials (outlines, examples, documentation) "
                "for the current knowledge point. Returns relevant chunks with sources."
            ),
        )
        def search_teaching_materials(query: str, top_k: int = 3) -> dict[str, object]:
            return do_search_teaching_materials(ctx, query, top_k)

        tools.append(search_teaching_materials)

    return tools


def do_update_learning_stage(
    side_effects: AgentSideEffects,
    ctx: LearningToolContext,
    new_stage: str,
    reason: str,
) -> dict[str, object]:
    current = side_effects.final_stage(ctx.current_stage)
    allowed = ALLOWED_TRANSITIONS.get(current, [])
    if new_stage not in allowed:
        return {
            "success": False,
            "error": f"Cannot transition from '{current}' to '{new_stage}'",
            "allowed_transitions": allowed,
        }
    side_effects.stage_updates.append({
        "new_stage": new_stage,
        "previous_stage": current,
        "reason": reason,
    })
    _append_tool_intent(
        side_effects,
        IntentType.STAGE_UPDATE,
        "learning_session",
        {
            "previous_stage": current,
            "new_stage": new_stage,
            "reason": reason,
        },
    )
    return {"success": True, "previous_stage": current, "new_stage": new_stage}


def do_record_diagnosis(
    side_effects: AgentSideEffects,
    *,
    stuck_point: str = "",
    misconceptions: str = "",
    recommended_action: str = "",
    concepts_explained: str = "",
) -> dict[str, object]:
    entry: dict[str, object] = {
        k: v
        for k, v in {
            "stuck_point": stuck_point,
            "misconceptions": misconceptions,
            "recommended_action": recommended_action,
            "concepts_explained": concepts_explained,
        }.items()
        if v
    }
    side_effects.diagnosis_updates.append(entry)
    _append_tool_intent(side_effects, IntentType.SIDE_EFFECT, "diagnosis", entry)
    return {"recorded": True, "fields": list(entry.keys())}


def do_trigger_code_run(
    ctx: LearningToolContext,
    code: str,
    *,
    side_effects: AgentSideEffects | None = None,
) -> dict[str, object]:
    if ctx.run_code_fn is None or ctx.exercise is None:
        if side_effects is not None:
            _append_tool_intent(
                side_effects,
                IntentType.TOOL_CALL,
                "trigger_code_run",
                {
                    "success": False,
                    "code_length": len(code),
                    "reason": "unavailable",
                },
            )
        return {"success": False, "error": "Code execution not available for this session"}
    result = ctx.run_code_fn(ctx.exercise, code)
    if side_effects is not None:
        _append_tool_intent(
            side_effects,
            IntentType.TOOL_CALL,
            "trigger_code_run",
            {
                "success": True,
                "code_length": len(code),
                "runtime_status": result.get("runtime_status", "unknown"),
                "test_pass_rate": result.get("test_pass_rate", 0.0),
            },
        )
    return {
        "success": True,
        "runtime_status": result.get("runtime_status", "unknown"),
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "test_pass_rate": result.get("test_pass_rate", 0.0),
        "test_results": result.get("test_results", []),
    }


def do_record_attempt(
    side_effects: AgentSideEffects,
    ctx: LearningToolContext,
    code: str,
    action: str,
) -> dict[str, object]:
    if action not in ("run", "submit"):
        return {"success": False, "error": f"Invalid action: {action}. Must be 'run' or 'submit'."}
    attempt_id = str(uuid.uuid4())
    side_effects.attempt_records.append({
        "attempt_id": attempt_id,
        "exercise_id": ctx.exercise_id,
        "code": code,
        "action": action,
    })
    _append_tool_intent(
        side_effects,
        IntentType.PERSISTENCE,
        "attempt",
        {
            "attempt_id": attempt_id,
            "exercise_id": ctx.exercise_id or "",
            "action": action,
            "code_length": len(code),
        },
    )
    return {"success": True, "attempt_id": attempt_id}


def do_update_learner_profile(
    side_effects: AgentSideEffects,
    ctx: LearningToolContext,
    *,
    observation_type: str,
    content: str,
    confidence: str = "ambiguous",
    key: str = "",
    value: str = "",
) -> dict[str, object]:
    valid_types = {"weak_point", "error_pattern", "learning_preference", "pace_indicator"}
    if observation_type not in valid_types:
        return {"success": False, "error": f"Invalid type: {observation_type}. Must be one of {sorted(valid_types)}"}
    valid_confidence = {"confirmed", "ambiguous"}
    if confidence not in valid_confidence:
        confidence = "ambiguous"
    entry: dict[str, object] = {
        "type": observation_type,
        "content": content,
        "confidence": confidence,
        "session_id": ctx.session_id,
    }
    if key:
        entry["key"] = key
    if value:
        entry["value"] = value
    side_effects.profile_updates.append(entry)
    _append_tool_intent(
        side_effects,
        IntentType.PROFILE_UPDATE,
        "learner_profile",
        {
            "type": observation_type,
            "content": content,
            "confidence": confidence,
            "key": key,
            "value": value,
            "session_id": ctx.session_id,
        },
    )
    return {"success": True, "recorded_type": observation_type}


def _append_tool_intent(
    side_effects: AgentSideEffects,
    intent_type: IntentType,
    target: str,
    payload: Mapping[str, object],
) -> None:
    if len(side_effects.typed_intents) >= MAX_TOOL_INTENTS:
        return
    side_effects.typed_intents.append(make_intent(intent_type, target, payload))


def do_search_teaching_materials(
    ctx: LearningToolContext,
    query: str,
    top_k: int = 3,
) -> dict[str, object]:
    if not ctx.knowledge_point_id:
        return {"success": False, "error": "No knowledge point context available"}
    try:
        from app.db.connection import connect
        from app.services.curriculum.teaching_chunks import search_chunks

        with connect() as conn:
            results = search_chunks(conn, ctx.knowledge_point_id, query, top_k=min(top_k, 5))
        return {"success": True, "results": results, "count": len(results)}
    except Exception as exc:
        return {"success": False, "error": f"Search failed: {exc}", "results": []}


def extract_learning_evidence(messages: Sequence[Mapping[str, str]]) -> dict[str, object] | None:
    for message in reversed(messages):
        if str(message.get("role", "")).lower() != "user":
            continue
        payload = _extract_json_object(str(message.get("content", "")))
        if payload is not None and "learner_message" in payload:
            return payload
    return None


def summarize_current_learning_context(evidence: Mapping[str, object]) -> dict[str, object]:
    knowledge_point = _mapping(evidence.get("knowledge_point"))
    exercise = _mapping(evidence.get("exercise"))
    runtime_profile = _mapping(exercise.get("runtime_profile"))
    code_blanks = _sequence(exercise.get("code_blanks"))

    return {
        "current_stage": _bounded_text(evidence.get("current_stage"), 120),
        "knowledge_point": {
            "id": _bounded_text(knowledge_point.get("id"), 80),
            "title": _bounded_text(knowledge_point.get("title"), 160),
            "status": _bounded_text(knowledge_point.get("status"), 40),
            "weak_points": _bounded_str_list(knowledge_point.get("weak_points"), limit=8),
            "last_exercise_result": knowledge_point.get("last_exercise_result"),
            "last_exercise_score": knowledge_point.get("last_exercise_score"),
        },
        "exercise": {
            "id": _bounded_text(exercise.get("id"), 80),
            "title": _bounded_text(exercise.get("title"), 160),
            "exercise_type": _bounded_text(exercise.get("exercise_type"), 40),
            "prompt_summary": _bounded_text(exercise.get("prompt_markdown"), 500),
            "difficulty": exercise.get("difficulty"),
            "runtime_profile": {
                "language": _bounded_text(runtime_profile.get("language"), 40),
                "runtime_tier": _bounded_text(runtime_profile.get("runtime_tier"), 60),
            },
            "code_blank_concepts": [
                {
                    "blank_key": _bounded_text(blank.get("blank_key"), 80),
                    "placeholder": _bounded_text(blank.get("placeholder"), 160),
                    "expected_concept": _bounded_text(blank.get("expected_concept"), 160),
                    "is_core": bool(blank.get("is_core", False)),
                }
                for blank in (_mapping(item) for item in code_blanks)
                if blank
            ][:8],
            "has_starter_code": bool(exercise.get("starter_code")),
        },
    }


def summarize_latest_visible_attempt(evidence: Mapping[str, object]) -> dict[str, object]:
    latest_attempt = _mapping(evidence.get("latest_attempt"))
    if not latest_attempt:
        return {"available": False}

    visible_results = []
    for item in _sequence(latest_attempt.get("visible_results"))[:8]:
        result = _mapping(item)
        if not result:
            continue
        visible_results.append(
            {
                "case_type": _bounded_text(result.get("case_type"), 40),
                "passed": bool(result.get("passed", False)),
                "message": _bounded_text(result.get("message"), 240),
            }
        )

    completion_result = _mapping(latest_attempt.get("completion_result"))
    hidden_summary = _mapping(latest_attempt.get("hidden_summary"))

    return {
        "available": True,
        "attempt_type": _bounded_text(latest_attempt.get("attempt_type"), 40),
        "runtime_status": _bounded_text(latest_attempt.get("runtime_status"), 60),
        "test_pass_rate": latest_attempt.get("test_pass_rate"),
        "passed_test_count": latest_attempt.get("passed_test_count"),
        "total_test_count": latest_attempt.get("total_test_count"),
        "visible_results": visible_results,
        "non_visible_test_counts": {
            "total": hidden_summary.get("total", 0),
            "failed": hidden_summary.get("failed", 0),
        },
        "error_message": _bounded_text(latest_attempt.get("error_message"), 360),
        "error_cause": _bounded_text(latest_attempt.get("error_cause"), 120),
        "hint_usage_count": latest_attempt.get("hint_usage_count"),
        "error_count": latest_attempt.get("error_count"),
        "completion_result": {
            "result": _bounded_text(completion_result.get("result"), 40),
            "feedback": _bounded_text(completion_result.get("feedback"), 360),
            "next_action": _bounded_text(completion_result.get("next_action"), 40),
        },
    }


def summarize_note_context(evidence: Mapping[str, object]) -> dict[str, object]:
    note = _mapping(evidence.get("note_summary"))
    if not note:
        return {}
    return {
        "available": True,
        "title": _bounded_text(note.get("title"), 160),
        "updated_at": _bounded_text(note.get("updated_at"), 80),
        "summary": _bounded_text(note.get("summary"), 500),
    }


def _extract_json_object(content: str) -> dict[str, object] | None:
    decoder = json.JSONDecoder()
    for index, char in enumerate(content):
        if char != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(content[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return value
    return []


def _bounded_str_list(value: object, *, limit: int) -> list[str]:
    return [_bounded_text(item, 120) for item in _sequence(value)[:limit]]


def _bounded_text(value: object, max_length: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_length:
        return text
    return f"{text[:max_length]}..."
