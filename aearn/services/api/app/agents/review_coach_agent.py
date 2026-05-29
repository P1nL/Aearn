from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from app.agents.agent_domain_contexts import build_review_runtime_context
from app.agents.agent_runtime_context import limit_text, parse_fenced_json_object, strip_json_fence
from app.agents.guardrails import assert_safe_teaching_output, build_teaching_guardrails
from app.agents.sdk_runtime import (
    AgentsSDKRunner,
    build_agent,
    build_run_config,
    iter_streamed_text,
    split_chat_messages,
    stream_text_deltas,
)
from app.core.config import Settings, get_settings
from app.services.llm_client import LLMCallError, LLMConfigurationError, LLMInvalidResponseError


REVIEW_COACH_AGENT_NAME = "Aearn Review Coach"


@dataclass(frozen=True)
class ReviewCoachContext:
    knowledge_point_id: str
    knowledge_point_title: str
    knowledge_point_description: str
    weak_points_json: Sequence[str]
    mastery_score: float | None
    due_at: str | None
    forget_risk: str
    last_fsrs_rating: str | None
    review_exercise_id: str
    review_exercise_title: str
    review_exercise_type: str
    review_exercise_prompt: str
    runtime_language: str
    runtime_tier: str
    visible_tests: Sequence[Mapping[str, object]]
    latest_attempt: Mapping[str, object] | None = None


@dataclass(frozen=True)
class ReviewCoachJsonResponse:
    content: dict[str, object]
    model: str


class ReviewCoachClient(Protocol):
    @property
    def model(self) -> str: ...

    def complete_json(
        self,
        context: ReviewCoachContext,
        *,
        temperature: float = 0.2,
    ) -> ReviewCoachJsonResponse: ...


class AgentsSDKReviewCoachClient:
    def __init__(
        self,
        settings: Settings,
        *,
        runner: AgentsSDKRunner | None = None,
    ) -> None:
        self._settings = settings
        self._run_config = build_run_config(settings)
        self._runner = runner

    @property
    def model(self) -> str:
        return str(self._settings.llm_model or "")

    def complete_json(
        self,
        context: ReviewCoachContext,
        *,
        temperature: float = 0.2,
    ) -> ReviewCoachJsonResponse:
        messages = _build_messages(context)
        instructions, input_text = split_chat_messages(messages)
        input_guardrails, output_guardrails = build_teaching_guardrails()
        agent = build_agent(
            name=REVIEW_COACH_AGENT_NAME,
            instructions=instructions,
            model=self.model,
            temperature=temperature,
            tools=[],
            input_guardrails=input_guardrails,
            output_guardrails=output_guardrails,
        )
        runner = self._runner
        if runner is None:
            from agents import Runner

            runner = cast(AgentsSDKRunner, Runner)

        chunks = iter_streamed_text(
            lambda: stream_text_deltas(
                runner=runner,
                agent=agent,
                input_text=input_text,
                run_config=self._run_config,
                max_turns=2,
            )
        )
        content = "".join(chunks).strip()
        return ReviewCoachJsonResponse(content=_parse_json_object(content), model=self.model)


def build_review_coach_client(
    settings: Settings | None = None,
    *,
    runner: AgentsSDKRunner | None = None,
) -> ReviewCoachClient | None:
    effective_settings = settings or get_settings()
    if not effective_settings.openai_compatible_configured:
        return None
    try:
        return AgentsSDKReviewCoachClient(effective_settings, runner=runner)
    except LLMConfigurationError:
        return None


def build_sdk_review_coach_response(
    context: ReviewCoachContext,
    *,
    settings: Settings | None = None,
    client: ReviewCoachClient | None = None,
) -> dict[str, object] | None:
    resolved_client = _resolve_client(settings=settings, client=client)
    if resolved_client is None:
        return None

    try:
        result = resolved_client.complete_json(context, temperature=0.2)
        response = _validate_review_coach_response(result.content)
    except SAFE_GENERATION_EXCEPTIONS:
        return None

    response["generation_source"] = "llm"
    response["generation_model"] = result.model
    return response


SAFE_GENERATION_EXCEPTIONS = (
    LLMCallError,
    LLMConfigurationError,
    LLMInvalidResponseError,
    TypeError,
    ValueError,
)


def _resolve_client(
    *,
    settings: Settings | None,
    client: ReviewCoachClient | None,
) -> ReviewCoachClient | None:
    if client is not None:
        return client
    effective_settings = settings or get_settings()
    if not effective_settings.openai_compatible_configured:
        return None
    try:
        return AgentsSDKReviewCoachClient(effective_settings)
    except LLMConfigurationError:
        return None


def _build_messages(context: ReviewCoachContext) -> list[dict[str, str]]:
    evidence = {
        "learner_message": "Generate concise review-session guidance grounded in the due review context. Do not provide the full solution.",
        "task": "review_coach",
        "due_review": {
            "knowledge_point": {
                "id": context.knowledge_point_id,
                "title": _bounded_text(context.knowledge_point_title, 160),
                "description": _bounded_text(context.knowledge_point_description, 500),
                "weak_points": [_bounded_text(item, 120) for item in context.weak_points_json[:8]],
                "mastery_score": context.mastery_score,
                "due_at": context.due_at,
                "forget_risk": context.forget_risk,
                "last_fsrs_rating": context.last_fsrs_rating,
            }
        },
        "runtime_context": build_review_runtime_context(
            knowledge_point_id=context.knowledge_point_id,
            knowledge_point_title=context.knowledge_point_title,
            weak_points=context.weak_points_json,
            due_at=context.due_at,
            forget_risk=context.forget_risk,
            last_fsrs_rating=context.last_fsrs_rating,
            latest_attempt=context.latest_attempt,
        ),
        "review_exercise": {
            "id": context.review_exercise_id,
            "title": _bounded_text(context.review_exercise_title, 160),
            "exercise_type": _bounded_text(context.review_exercise_type, 40),
            "prompt_summary": _bounded_text(context.review_exercise_prompt, 500),
            "runtime_language": _bounded_text(context.runtime_language, 40),
            "runtime_tier": _bounded_text(context.runtime_tier, 60),
            "visible_tests": [_visible_test_evidence(item) for item in context.visible_tests[:8]],
        },
        "latest_attempt": _latest_attempt_evidence(context.latest_attempt),
        "output_schema": {
            "initial_agent_message": "short review kickoff text",
            "variant_reason": "short reason for the review variant",
            "coaching_text": "optional short coaching text",
        },
    }
    return [
        {
            "role": "system",
            "content": (
                "你是 Aearn 的复习教练 Agent。只输出可以安全展示给学习者的 JSON 对象，"
                "不要输出 Markdown，不要泄露隐藏测试、参考答案、provider 原始错误或完整代码。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
        },
    ]


def _validate_review_coach_response(payload: Mapping[str, object]) -> dict[str, object]:
    initial_agent_message = _required_str(payload, "initial_agent_message", max_length=240)
    variant_reason = _required_str(payload, "variant_reason", max_length=260)
    coaching_text = _optional_str(payload, "coaching_text", max_length=320)
    assert_safe_teaching_output(initial_agent_message)
    assert_safe_teaching_output(variant_reason)
    if coaching_text:
        assert_safe_teaching_output(coaching_text)
    response: dict[str, object] = {
        "initial_agent_message": initial_agent_message,
        "variant_reason": variant_reason,
    }
    if coaching_text:
        response["coaching_text"] = coaching_text
    return response


def _latest_attempt_evidence(latest_attempt: Mapping[str, object] | None) -> dict[str, object]:
    if latest_attempt is None:
        return {"available": False}

    return {
        "available": True,
        "attempt_id": _bounded_text(latest_attempt.get("attempt_id"), 80),
        "attempt_type": _bounded_text(latest_attempt.get("attempt_type"), 40),
        "runtime_status": _bounded_text(latest_attempt.get("runtime_status"), 60),
        "test_pass_rate": latest_attempt.get("test_pass_rate"),
        "passed_test_count": latest_attempt.get("passed_test_count"),
        "total_test_count": latest_attempt.get("total_test_count"),
        "error_message": _bounded_text(latest_attempt.get("error_message"), 360),
        "error_cause": _bounded_text(latest_attempt.get("error_cause"), 120),
        "explanation_text": _bounded_text(latest_attempt.get("explanation_text"), 240),
        "hint_usage_count": latest_attempt.get("hint_usage_count"),
        "error_count": latest_attempt.get("error_count"),
        "score": latest_attempt.get("score"),
        "fsrs_rating": _bounded_text(latest_attempt.get("fsrs_rating"), 40),
    }


def _visible_test_evidence(test_case: Mapping[str, object]) -> dict[str, object]:
    return {
        "case_type": _bounded_text(test_case.get("case_type"), 40),
        "weight": test_case.get("weight"),
        "is_critical": bool(test_case.get("is_critical", False)),
        "timeout_ms": test_case.get("timeout_ms"),
        "order_index": test_case.get("order_index"),
    }


def _required_str(payload: Mapping[str, object], key: str, *, max_length: int) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise LLMInvalidResponseError(f"Review coach field {key} must be a string")
    stripped = value.strip()
    if not stripped:
        raise LLMInvalidResponseError(f"Review coach field {key} must not be blank")
    return _bounded_text(stripped, max_length)


def _optional_str(payload: Mapping[str, object], key: str, *, max_length: int) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise LLMInvalidResponseError(f"Review coach field {key} must be a string")
    stripped = value.strip()
    if not stripped:
        return None
    return _bounded_text(stripped, max_length)


def _parse_json_object(content: str) -> dict[str, object]:
    return parse_fenced_json_object(
        content,
        invalid_message="Review coach output is not valid JSON",
        object_message="Review coach output must be a JSON object",
    )


def _strip_json_fence(content: str) -> str:
    return strip_json_fence(content)


def _bounded_text(value: object, max_length: int) -> str:
    return limit_text(value, max_length)
