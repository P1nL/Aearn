from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from typing import Literal, Protocol

from app.core.config import Settings, get_settings
from pydantic import BaseModel, ConfigDict, Field

from app.services.llm.llm_client import (
    LLMCallError,
    LLMConfigurationError,
    LLMInvalidResponseError,
    LLMJsonResponse,
    OpenAICompatibleClient,
)


ALLOWED_ERROR_CAUSES = {
    "python_syntax_error",
    "syntax_error",
    "selector_error",
    "event_binding_error",
    "state_scope_error",
    "return_value_error",
    "edge_case_error",
    "boundary_condition_error",
    "type_error",
    "async_order_error",
    "test_misread",
    "ai_over_trust",
    "undefined_reference",
    "timeout_loop",
    "runtime_error",
}
ALLOWED_NEXT_ACTIONS = {"retry_same", "show_hint", "explain_error", "review_variant", "schedule_review", "advance_next"}


class JsonCompletionClient(Protocol):
    @property
    def model(self) -> str: ...

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float = 0.2,
        output_schema: Mapping[str, object] | None = None,
        schema_name: str | None = None,
    ) -> LLMJsonResponse: ...


class _StrictErrorExplanationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class LLMErrorExplanationKnowledgePoint(_StrictErrorExplanationModel):
    id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=240)


class LLMErrorExplanationOutput(_StrictErrorExplanationModel):
    error_cause: Literal[
        "python_syntax_error",
        "syntax_error",
        "selector_error",
        "event_binding_error",
        "state_scope_error",
        "return_value_error",
        "edge_case_error",
        "boundary_condition_error",
        "type_error",
        "async_order_error",
        "test_misread",
        "ai_over_trust",
        "undefined_reference",
        "timeout_loop",
        "runtime_error",
    ]
    explanation: str = Field(min_length=1, max_length=900)
    fix_suggestion: str = Field(min_length=1, max_length=700)
    related_knowledge_points: tuple[LLMErrorExplanationKnowledgePoint, ...] = Field(max_length=16)
    next_action: Literal[
        "retry_same",
        "show_hint",
        "explain_error",
        "review_variant",
        "schedule_review",
        "advance_next",
    ]


def llm_error_explanation_output_schema() -> dict[str, object]:
    return LLMErrorExplanationOutput.model_json_schema()


def canonical_llm_error_explanation_example() -> dict[str, object]:
    return {
        "error_cause": "boundary_condition_error",
        "explanation": "当前判断把一个合法边界值也归入了越界分支，因此该输入没有返回预期结果。",
        "fix_suggestion": "只调整边界比较条件，然后重新运行同一组可见测试；不要一次重写整个函数。",
        "related_knowledge_points": [],
        "next_action": "retry_same",
    }


def build_llm_error_explanation(
    exercise: Mapping[str, object],
    *,
    error_message: str,
    stderr: str,
    failed_tests: Sequence[Mapping[str, object]],
    current_code: str,
    related_knowledge_points: Sequence[Mapping[str, object]],
    settings: Settings | None = None,
    client: JsonCompletionClient | None = None,
) -> dict[str, object] | None:
    effective_settings = settings or get_settings()
    if client is None:
        if not effective_settings.openai_compatible_configured:
            return None
        try:
            client = OpenAICompatibleClient(effective_settings)
        except LLMConfigurationError:
            return None

    messages = _build_messages(
        exercise,
        error_message=error_message,
        stderr=stderr,
        failed_tests=failed_tests,
        current_code=current_code,
        related_knowledge_points=related_knowledge_points,
    )
    try:
        result = client.complete_json(
            messages,
            temperature=0.2,
            output_schema=llm_error_explanation_output_schema(),
            schema_name="llm_error_explanation_v1",
        )
        response = _validate_response(
            result.content,
            related_knowledge_points=related_knowledge_points,
            forbidden_tokens=_hidden_case_ids(failed_tests),
        )
    except (LLMCallError, LLMConfigurationError, LLMInvalidResponseError, TypeError, ValueError):
        return None

    response["generation_source"] = "llm"
    response["generation_model"] = result.model
    return response


def _build_messages(
    exercise: Mapping[str, object],
    *,
    error_message: str,
    stderr: str,
    failed_tests: Sequence[Mapping[str, object]],
    current_code: str,
    related_knowledge_points: Sequence[Mapping[str, object]],
) -> list[dict[str, str]]:
    evidence = {
        "exercise": _exercise_evidence(exercise),
        "error_message": _limit_text(error_message, 1200),
        "stderr": _limit_text(stderr, 1600),
        "failed_tests": _sanitize_failed_tests(failed_tests),
        "current_code": _limit_text(current_code, 5000),
        "related_knowledge_points": _knowledge_points_evidence(related_knowledge_points),
        "allowed_error_causes": sorted(ALLOWED_ERROR_CAUSES),
        "allowed_next_actions": sorted(ALLOWED_NEXT_ACTIONS),
    }
    return [
        {
            "role": "system",
            "content": (
                "你是 Aearn 的编程学习错因解释器。只根据给定 evidence 解释错误；不要推测不存在的运行结果；"
                "不要输出隐藏测试源码、参考答案或完整修复代码。只输出 JSON，不要 Markdown。"
                f"合法输出示例：{json.dumps(canonical_llm_error_explanation_example(), ensure_ascii=False, separators=(',', ':'))}"
            ),
        },
        {
            "role": "user",
            "content": (
                "根据以下 evidence 输出 JSON，字段必须是 error_cause, explanation, fix_suggestion, "
                "related_knowledge_points, next_action。"
                "error_cause 必须使用已知错因标签；next_action 优先使用 retry_same。"
                "related_knowledge_points 只能使用 evidence 里给出的 id/title。\n"
                f"{json.dumps(evidence, ensure_ascii=False)}"
            ),
        },
    ]


def _exercise_evidence(exercise: Mapping[str, object]) -> dict[str, object]:
    runtime_profile = exercise.get("runtime_profile", {})
    code_blanks = exercise.get("code_blanks", [])
    if not isinstance(code_blanks, Sequence) or isinstance(code_blanks, (str, bytes)):
        code_blanks = []
    return {
        "title": _limit_text(str(exercise.get("title", "")), 160),
        "exercise_type": str(exercise.get("exercise_type", "")),
        "prompt_markdown": _limit_text(str(exercise.get("prompt_markdown", "")), 1200),
        "runtime_profile": {
            "language": str(runtime_profile.get("language", "")) if isinstance(runtime_profile, Mapping) else "",
            "runtime_tier": str(runtime_profile.get("runtime_tier", "")) if isinstance(runtime_profile, Mapping) else "",
        },
        "code_blanks": [
            {
                "blank_key": str(blank.get("blank_key", "")),
                "expected_concept": str(blank.get("expected_concept", "")),
                "is_core": bool(blank.get("is_core", False)),
            }
            for blank in code_blanks
            if isinstance(blank, Mapping)
        ][:8],
    }


def _sanitize_failed_tests(failed_tests: Sequence[Mapping[str, object]]) -> list[dict[str, str]]:
    sanitized: list[dict[str, str]] = []
    for test in failed_tests[:8]:
        case_type = str(test.get("case_type", ""))
        sanitized.append(
            {
                "case_type": case_type,
                "message": _limit_text(str(test.get("message", "")), 500),
            }
        )
    return sanitized


def _knowledge_points_evidence(related_knowledge_points: Sequence[Mapping[str, object]]) -> list[dict[str, str]]:
    return [
        {
            "id": str(item.get("id", "")),
            "title": str(item.get("title", "")),
        }
        for item in related_knowledge_points
        if isinstance(item, Mapping)
    ]


def _validate_response(
    payload: Mapping[str, object],
    *,
    related_knowledge_points: Sequence[Mapping[str, object]],
    forbidden_tokens: Sequence[str],
) -> dict[str, object]:
    try:
        parsed = LLMErrorExplanationOutput.model_validate(dict(payload))
    except ValueError as exc:
        raise LLMInvalidResponseError("LLM returned invalid error explanation contract") from exc
    error_cause = parsed.error_cause
    explanation = parsed.explanation
    fix_suggestion = parsed.fix_suggestion
    next_action = parsed.next_action
    allowed_knowledge_points = {
        (item["id"], item["title"])
        for item in _knowledge_points_evidence(related_knowledge_points)
    }
    authored_knowledge_points = tuple(
        (item.id, item.title) for item in parsed.related_knowledge_points
    )
    if any(item not in allowed_knowledge_points for item in authored_knowledge_points):
        raise LLMInvalidResponseError("LLM returned an ungrounded knowledge point")
    _reject_forbidden_output(
        [
            error_cause,
            explanation,
            fix_suggestion,
            next_action,
            *(value for item in authored_knowledge_points for value in item),
        ],
        forbidden_tokens,
    )
    if "```" in explanation or "```" in fix_suggestion:
        raise LLMInvalidResponseError("LLM returned code fence content")

    return {
        "error_cause": error_cause,
        "explanation": explanation,
        "fix_suggestion": fix_suggestion,
        "related_knowledge_points": _knowledge_points_evidence(related_knowledge_points),
        "next_action": next_action,
    }


def _hidden_case_ids(failed_tests: Sequence[Mapping[str, object]]) -> list[str]:
    tokens: list[str] = []
    for test in failed_tests:
        if str(test.get("case_type", "")).lower() != "hidden":
            continue
        case_id = str(test.get("case_id", "")).strip()
        if case_id:
            tokens.append(case_id)
    return tokens


def _reject_forbidden_output(values: Sequence[str], forbidden_tokens: Sequence[str]) -> None:
    combined = "\n".join(values).lower()
    for token in forbidden_tokens:
        if token.lower() in combined:
            raise LLMInvalidResponseError("LLM output leaked hidden test identifier")


def _limit_text(value: str, max_length: int) -> str:
    stripped = value.strip()
    if len(stripped) <= max_length:
        return stripped
    return f"{stripped[:max_length]}..."
