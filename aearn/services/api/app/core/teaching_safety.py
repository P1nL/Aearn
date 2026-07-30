"""Pure, SDK-independent safety utilities for learner-facing teaching data."""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


REDACTED_FIELDS = frozenset(
    {
        "solution_reference",
        "hidden_tests",
        "hidden_test_source",
        "raw_prompt",
        "system_prompt",
        "provider_payload",
        "api_key",
        "secret",
        "auth_token",
        "stack_trace",
        "traceback",
    }
)

REDACTED_CONTENT_MARKERS = (
    "solution_reference",
    "solution reference",
    "hidden_test",
    "hidden test",
    "raw_prompt",
    "raw prompt",
    "system prompt",
    "api_key",
    "api key",
    "secret_key",
    "secret key",
    "auth_token",
    "auth token",
    "provider payload",
    "provider error",
)

DIRECT_ANSWER_REDIRECT_CONTEXT = "学习者请求跳过过程，需要继续用局部提示引导。"

_HIDDEN_CASE_PATTERN = re.compile(r"\bhidden_(?!summary\b)[A-Za-z0-9][A-Za-z0-9_.-]*", re.IGNORECASE)
_API_KEY_PATTERN = re.compile(r"\b(?:sk|sess|key)-[A-Za-z0-9_-]{12,}\b", re.IGNORECASE)
_INTERNAL_REFERENCE_TOKENS = (
    "solution_reference",
    "reference_answer",
    "secret solution",
)
_REFERENCE_OUTPUT_TOKENS = (
    *_INTERNAL_REFERENCE_TOKENS,
    "reference answer",
    "参考答案",
    "标准答案",
)
_PROVIDER_ERROR_TOKENS = (
    "provider raw",
    "invalid_api_key",
    "authorization: bearer",
    "openai_api_key",
    "deepseek_api_key",
    "api key",
)
_PROMPT_LEAK_OUTPUT_TOKENS = (
    "raw prompt",
    "system prompt",
    "developer prompt",
    "sdk/internal event name",
    "response_policy",
    "diagnosis_first",
    "max_follow_up_questions",
    "direct_answer_requested",
    "direct_answer_handling",
    "stage_strategy",
    "forbidden_outputs",
    "allowed_outputs",
    "learner_message",
    "learning_context",
    "lesson_outline",
    "concept_progress",
    "conversation_context",
    "recent_safe_messages",
    "rag_context",
    "runtime_boundary",
    "latest_attempt",
    "learner_profile",
    "official_docs_grounding",
)
_PROMPT_LEAK_OUTPUT_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9])_policy\b", re.IGNORECASE),
    re.compile(r"\bpolicy\s*(?:要求|规则|规定)", re.IGNORECASE),
    re.compile(r"(?:符合|根据|按照|满足|遵守)\s*policy\s*(?:要求|规则|规定)?", re.IGNORECASE),
    re.compile(r"(?:内部|系统|安全)\s*策略\s*(?:要求|规则|规定)", re.IGNORECASE),
)
_DIRECT_ANSWER_OUTPUT_PATTERNS = (
    re.compile(r"完整答案如下", re.IGNORECASE),
    re.compile(r"完整代码如下", re.IGNORECASE),
    re.compile(r"直接答案如下", re.IGNORECASE),
    re.compile(r"最终答案如下", re.IGNORECASE),
    re.compile(r"here is the complete solution", re.IGNORECASE),
    re.compile(r"complete solution\s*:", re.IGNORECASE),
)
_DIRECT_ANSWER_REQUEST_PATTERNS = (
    re.compile(r"直接.*(答案|完整代码|给我代码)"),
    re.compile(r"给我.*(完整代码|完整答案|标准答案|参考答案)"),
    re.compile(r"(完整答案|标准答案|参考答案)"),
    re.compile(r"把.*(完整)?代码.*(写完|补完|给我)"),
    re.compile(r"\b(?:complete|full)\s+(?:answer|solution|code)\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class TeachingGuardrailCheck:
    blocked: bool
    category: str
    reason: str


def redact_value(value: object) -> object:
    """Return a bounded recursive representation without sensitive values."""
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, Mapping):
        return redact_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [redact_value(item) for item in value[:20]]
    return value


def redact_mapping(
    mapping: Mapping[Any, object],
    *,
    max_keys: int = 50,
) -> dict[str, object]:
    """Recursively redact at most ``max_keys`` mapping entries."""
    result: dict[str, object] = {}
    for index, (raw_key, value) in enumerate(mapping.items()):
        if index >= max_keys:
            break
        key = str(raw_key)
        if key.lower() in REDACTED_FIELDS:
            result[key] = "[REDACTED]"
            continue
        result[key] = redact_value(value)
    return result


def check_teaching_request(text: str) -> TeachingGuardrailCheck:
    return _check_text(text, include_direct_answer_request=False, include_reference_output_tokens=False)


def check_teaching_output(text: str) -> TeachingGuardrailCheck:
    check = _check_text(text, include_direct_answer_request=False, include_reference_output_tokens=True)
    if check.blocked:
        return check
    normalized = text.lower()
    for token in _PROMPT_LEAK_OUTPUT_TOKENS:
        if token in normalized:
            return TeachingGuardrailCheck(True, "prompt_leak", "prompt or internal-context marker appeared in text")
    for pattern in _PROMPT_LEAK_OUTPUT_PATTERNS:
        if pattern.search(text):
            return TeachingGuardrailCheck(True, "prompt_leak", "prompt or internal-context marker appeared in text")
    for pattern in _DIRECT_ANSWER_OUTPUT_PATTERNS:
        if pattern.search(text):
            return TeachingGuardrailCheck(True, "direct_answer", "model output appears to provide a complete answer")
    return TeachingGuardrailCheck(False, "", "")


def detect_direct_answer_request(text: str) -> bool:
    return any(pattern.search(text) for pattern in _DIRECT_ANSWER_REQUEST_PATTERNS)


def limit_text(value: object, max_length: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_length:
        return text
    return f"{text[:max_length]}..."


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


def _check_text(
    text: str,
    *,
    include_direct_answer_request: bool,
    include_reference_output_tokens: bool,
) -> TeachingGuardrailCheck:
    normalized = text.lower()
    hidden_match = _HIDDEN_CASE_PATTERN.search(text)
    if hidden_match is not None:
        return TeachingGuardrailCheck(True, "hidden_test", "hidden test identifier appeared in text")
    for token in _INTERNAL_REFERENCE_TOKENS:
        if token.lower() in normalized:
            return TeachingGuardrailCheck(True, "reference_answer", "reference-answer wording appeared in text")
    if include_reference_output_tokens:
        for token in _REFERENCE_OUTPUT_TOKENS:
            if token.lower() in normalized:
                return TeachingGuardrailCheck(True, "reference_answer", "reference-answer wording appeared in text")
    for token in _PROVIDER_ERROR_TOKENS:
        if token.lower() in normalized:
            return TeachingGuardrailCheck(True, "provider_error", "provider or API-key wording appeared in text")
    if _API_KEY_PATTERN.search(text):
        return TeachingGuardrailCheck(True, "provider_error", "key-like token appeared in text")
    if include_direct_answer_request and detect_direct_answer_request(text):
        return TeachingGuardrailCheck(True, "direct_answer_request", "learner requested a complete answer")
    return TeachingGuardrailCheck(False, "", "")


def _redact_string(value: str) -> str:
    lowered = value.lower()
    if any(marker in lowered for marker in REDACTED_CONTENT_MARKERS):
        return "[REDACTED: contains sensitive content]"
    return value
