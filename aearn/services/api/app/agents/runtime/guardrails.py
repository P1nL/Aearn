from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from agents import (
    Agent,
    GuardrailFunctionOutput,
    InputGuardrail,
    OutputGuardrail,
    RunContextWrapper,
    input_guardrail,
    output_guardrail,
)

from app.services.llm.llm_client import LLMInvalidResponseError


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
    for pattern in _DIRECT_ANSWER_OUTPUT_PATTERNS:
        if pattern.search(text):
            return TeachingGuardrailCheck(True, "direct_answer", "model output appears to provide a complete answer")
    return TeachingGuardrailCheck(False, "", "")


def detect_direct_answer_request(text: str) -> bool:
    return any(pattern.search(text) for pattern in _DIRECT_ANSWER_REQUEST_PATTERNS)


def assert_safe_teaching_request(text: str) -> None:
    check = check_teaching_request(text)
    if check.blocked:
        raise LLMInvalidResponseError(f"Teaching request guardrail blocked {check.category}")


def assert_safe_teaching_output(text: str) -> None:
    check = check_teaching_output(text)
    if check.blocked:
        raise LLMInvalidResponseError(f"Teaching output guardrail blocked {check.category}")


def build_teaching_guardrails() -> tuple[list[InputGuardrail[Any]], list[OutputGuardrail[Any]]]:
    @input_guardrail(name="aearn_teaching_input_guardrail")
    def teaching_input_guardrail(
        context: RunContextWrapper[Any],
        agent: Agent[Any],
        input_data: str | list[Any],
    ) -> GuardrailFunctionOutput:
        del context, agent
        text = _extract_learner_message(_stringify_input(input_data))
        check = check_teaching_request(text)
        return GuardrailFunctionOutput(
            output_info={"category": check.category, "reason": check.reason},
            tripwire_triggered=check.blocked,
        )

    @output_guardrail(name="aearn_teaching_output_guardrail")
    def teaching_output_guardrail(
        context: RunContextWrapper[Any],
        agent: Agent[Any],
        output_data: Any,
    ) -> GuardrailFunctionOutput:
        del context, agent
        check = check_teaching_output(str(output_data or ""))
        return GuardrailFunctionOutput(
            output_info={"category": check.category, "reason": check.reason},
            tripwire_triggered=check.blocked,
        )

    return [teaching_input_guardrail], [teaching_output_guardrail]


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
    if include_direct_answer_request:
        if detect_direct_answer_request(text):
            return TeachingGuardrailCheck(True, "direct_answer_request", "learner requested a complete answer")
    return TeachingGuardrailCheck(False, "", "")


def _stringify_input(input_data: str | list[Any]) -> str:
    if isinstance(input_data, str):
        return input_data
    return json.dumps(input_data, ensure_ascii=False, default=str)


def _extract_learner_message(text: str) -> str:
    payload = _extract_json_object(text)
    if isinstance(payload, Mapping):
        learner_message = payload.get("learner_message")
        if isinstance(learner_message, str) and learner_message.strip():
            return learner_message
    return text


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
