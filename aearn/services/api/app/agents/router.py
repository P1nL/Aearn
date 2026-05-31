"""Agent routing and handoff registry.

Provides rule-based routing to select the appropriate specialized agent
for a given message context, and an agent registry for handoff declarations.
"""
from __future__ import annotations

from collections.abc import Sequence


TEACHING_STAGES = {"concept_intro", "concept_qna", "readiness_check"}
DIAGNOSIS_STAGES = {"concept_check", "concept_repair"}
PRACTICE_STAGES = {"practice_support"}

HINT_KEYWORDS = {"提示", "hint", "帮我", "不会", "卡住", "stuck", "help", "怎么做", "不懂"}
PRACTICE_KEYWORDS = {"练习", "做题", "开始练", "practice", "exercise", "code"}
EXPLAIN_KEYWORDS = {"为什么", "解释", "explain", "why", "概念", "原理", "什么是"}


def route_message(
    *,
    session_stage: str,
    user_message: str,
    session_type: str = "learning",
) -> str:
    """Determine which agent should handle this message.

    Returns agent name: 'teaching', 'exercise_coach', 'diagnosis', or 'review_coach'.
    """
    if session_type == "review":
        return "review_coach"

    lowered = user_message.lower()

    if session_stage in DIAGNOSIS_STAGES:
        return "diagnosis"

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
