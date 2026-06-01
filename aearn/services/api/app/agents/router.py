"""Agent routing and handoff registry.

Provides rule-based routing to select the appropriate specialized agent
for a given message context, and an agent registry for handoff declarations.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence


TEACHING_STAGES = {"concept_intro", "concept_qna", "readiness_check"}
DIAGNOSIS_STAGES = {"concept_check", "concept_repair"}
PRACTICE_STAGES = {"practice_support"}

HINT_KEYWORDS = {"提示", "hint", "帮我", "不会", "卡住", "stuck", "help", "怎么做", "不懂"}
PRACTICE_KEYWORDS = {"练习", "做题", "开始练", "practice", "exercise", "code", "代码", "运行", "提交", "试一下"}
EXPLAIN_KEYWORDS = {"为什么", "解释", "explain", "why", "概念", "原理", "什么是"}
REPEATED_CONFUSION_KEYWORDS = {"一直", "又", "还是", "反复", "总是", "again", "still", "keeps", "repeated"}


def route_message(
    *,
    session_stage: str,
    user_message: str,
    session_type: str = "learning",
    latest_attempt: Mapping[str, object] | None = None,
    learner_profile_summary: str = "",
    tool_context: Mapping[str, object] | None = None,
) -> str:
    """Determine which agent should handle this message.

    Returns agent name: 'teaching', 'exercise_coach', 'diagnosis', or 'review_coach'.
    """
    if session_type == "review":
        return "review_coach"

    lowered = user_message.lower()
    recent_error = _has_recent_error(latest_attempt)
    repeated_confusion = _has_keyword(lowered, REPEATED_CONFUSION_KEYWORDS)
    profile_has_weak_signal = _profile_has_weak_signal(learner_profile_summary)
    exercise_available = _exercise_available(tool_context)

    if session_stage in DIAGNOSIS_STAGES:
        return "diagnosis"

    if recent_error and (repeated_confusion or _has_keyword(lowered, EXPLAIN_KEYWORDS | HINT_KEYWORDS)):
        return "diagnosis"

    if repeated_confusion and profile_has_weak_signal:
        return "diagnosis"

    if exercise_available and _has_keyword(lowered, PRACTICE_KEYWORDS):
        return "exercise_coach"

    if session_stage in PRACTICE_STAGES:
        if _has_keyword(lowered, EXPLAIN_KEYWORDS):
            return "teaching"
        return "exercise_coach"

    if session_stage in TEACHING_STAGES:
        if _has_keyword(lowered, PRACTICE_KEYWORDS):
            return "exercise_coach"
        return "teaching"

    return "teaching"


def get_handoff_targets(agent_name: str) -> list[str]:
    """Return the list of agents this agent can hand off to."""
    handoff_map: dict[str, list[str]] = {
        "teaching": ["exercise_coach", "diagnosis"],
        "exercise_coach": ["teaching", "diagnosis"],
        "diagnosis": ["teaching", "exercise_coach"],
        "review_coach": ["teaching"],
    }
    return handoff_map.get(agent_name, [])


def get_agent_description(agent_name: str) -> str:
    """Return a short description for handoff declarations."""
    descriptions: dict[str, str] = {
        "teaching": "Concept introduction, explanation, and Socratic dialogue",
        "exercise_coach": "Code hints, error explanation, and submission guidance",
        "diagnosis": "Identifying misconceptions and assessing understanding",
        "review_coach": "Spaced repetition warmup and review feedback",
    }
    return descriptions.get(agent_name, "General learning assistant")


def build_routing_context(
    agent_name: str,
    handoff_targets: Sequence[str],
) -> str:
    """Build routing instructions to append to an agent's system prompt."""
    if not handoff_targets:
        return ""
    lines = ["你可以将对话转交给以下专门 agent："]
    for target in handoff_targets:
        desc = get_agent_description(target)
        lines.append(f"- {target}: {desc}")
    lines.append("当学习者的需求超出你的专长时，使用 handoff 转交。")
    return "\n".join(lines)


def _has_keyword(text: str, keywords: set[str]) -> bool:
    return any(kw in text for kw in keywords)


def _has_recent_error(latest_attempt: Mapping[str, object] | None) -> bool:
    if not isinstance(latest_attempt, Mapping):
        return False
    runtime_status = str(latest_attempt.get("runtime_status") or "").lower()
    if runtime_status and runtime_status not in {"success", "unsupported"}:
        return True
    return _int_or_zero(latest_attempt.get("error_count")) >= 2


def _profile_has_weak_signal(summary: str) -> bool:
    lowered = summary.lower()
    return any(marker in lowered for marker in ("薄弱点", "错误模式", "weak", "error_pattern", "常见错误"))


def _exercise_available(tool_context: Mapping[str, object] | None) -> bool:
    if not isinstance(tool_context, Mapping):
        return False
    return bool(tool_context.get("exercise_available") or tool_context.get("exercise_id"))


def _int_or_zero(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0
