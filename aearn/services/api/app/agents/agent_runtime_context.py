from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from app.agents.guardrails import (
    check_teaching_output,
    check_teaching_request,
    detect_direct_answer_request,
)
from app.services.llm_client import LLMInvalidResponseError


DIRECT_ANSWER_REDIRECT_CONTEXT = "学习者请求跳过过程，需要继续用局部提示引导。"


@dataclass(frozen=True)
class SafeMessage:
    id: str
    role: str
    content: str
    created_at: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ContextRefreshDecision:
    refresh: bool
    reason: str


def limit_text(value: object, max_length: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_length:
        return text
    return f"{text[:max_length]}..."


def int_or_zero(value: object) -> int:
    if value is None:
        return 0
    try:
        return int(cast(Any, value))
    except (TypeError, ValueError):
        return 0


def extract_json_object(content: str) -> dict[str, object] | None:
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


def strip_json_fence(content: str) -> str:
    stripped = content.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_fenced_json_object(content: str, *, invalid_message: str, object_message: str) -> dict[str, object]:
    try:
        parsed = json.loads(strip_json_fence(content))
    except json.JSONDecodeError as exc:
        raise LLMInvalidResponseError(invalid_message) from exc
    if not isinstance(parsed, dict):
        raise LLMInvalidResponseError(object_message)
    return parsed


def redacted_context_text(category: str) -> str:
    if category == "hidden_test":
        return "存在不可展示的内部验证信息。"
    if category == "reference_answer":
        return "存在不可展示的内部解法信息。"
    if category == "provider_error":
        return "存在不可展示的模型服务或密钥信息。"
    if category == "direct_answer":
        return "存在不可展示的完整解法内容。"
    return "存在不可展示的内部信息。"


def sanitize_message_content(*, role: str, content: str, max_length: int = 1200) -> str:
    limited = limit_text(content, max_length)
    if not limited:
        return ""
    if role == "user" and detect_direct_answer_request(limited):
        return DIRECT_ANSWER_REDIRECT_CONTEXT

    check = check_teaching_request(limited) if role == "user" else check_teaching_output(limited)
    if check.blocked:
        return redacted_context_text(check.category)
    if detect_direct_answer_request(limited):
        return DIRECT_ANSWER_REDIRECT_CONTEXT
    return limited


def sanitize_summary_text(value: object, *, max_length: int = 240) -> str:
    text = limit_text(value, max_length)
    if not text:
        return ""
    if detect_direct_answer_request(text):
        return DIRECT_ANSWER_REDIRECT_CONTEXT
    check = check_teaching_output(text)
    if check.blocked:
        return redacted_context_text(check.category)
    return text


def sanitize_summary_list(value: object, *, max_item_length: int = 160, max_items: int = 8) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    result: list[str] = []
    for item in value:
        text = sanitize_summary_text(item, max_length=max_item_length)
        if text:
            result.append(text)
    return result[:max_items]


def normalize_summary_confidence(value: object) -> str:
    text = str(value or "").lower()
    if text in {"low", "medium", "high"}:
        return text
    return "low"


def should_refresh_summary(
    state: Mapping[str, object],
    *,
    message_count: int,
    stage: str,
    threshold: int,
) -> ContextRefreshDecision:
    if not state:
        return ContextRefreshDecision(True, "missing_state")
    if not isinstance(state.get("safe_summary"), Mapping):
        return ContextRefreshDecision(True, "missing_safe_summary")
    refreshed_count = int_or_zero(state.get("message_count_at_refresh"))
    if max(0, message_count - refreshed_count) >= threshold:
        return ContextRefreshDecision(True, "message_threshold")
    refreshed_stage = state.get("learning_stage")
    if refreshed_stage and str(refreshed_stage) != stage:
        return ContextRefreshDecision(True, "stage_changed")
    return ContextRefreshDecision(False, "fresh")


def safe_messages_from_records(
    records: Sequence[Mapping[str, object]],
    *,
    max_content_length: int = 1200,
) -> list[SafeMessage]:
    messages: list[SafeMessage] = []
    for record in records:
        role = str(record.get("role") or "")
        content = sanitize_message_content(
            role=role,
            content=str(record.get("content") or ""),
            max_length=max_content_length,
        )
        if not content:
            continue
        messages.append(
            SafeMessage(
                id=str(record.get("id") or ""),
                role="assistant" if role == "agent" else "user",
                content=content,
                created_at=_isoformat(record.get("created_at")),
            )
        )
    return messages


def build_runtime_context_block(
    *,
    safe_summary: Mapping[str, object],
    recent_messages: Sequence[Mapping[str, object]],
    current_focus_key: str,
    fallback_focus_key: str | None = None,
    strategy_key: str | None = None,
    avoid_key: str | None = None,
) -> dict[str, object]:
    current_focus = safe_summary.get(current_focus_key) or (
        safe_summary.get(fallback_focus_key) if fallback_focus_key else ""
    )
    return {
        "safe_summary": dict(safe_summary),
        "recent_safe_messages": [dict(message) for message in recent_messages],
        "current_diagnosis": current_focus or "",
        "last_agent_strategy": safe_summary.get(strategy_key) if strategy_key else "",
        "avoid_repeating": safe_summary.get(avoid_key) if avoid_key else [],
    }


def _isoformat(value: object) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None
