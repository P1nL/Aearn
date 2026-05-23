from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from agents import Tool, function_tool


def build_teaching_tools(messages: Sequence[Mapping[str, str]]) -> list[Tool]:
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

    return tools


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
