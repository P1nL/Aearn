from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast

from app.agents.guardrails import assert_safe_teaching_output, build_teaching_guardrails
from app.agents.sdk_runtime import (
    AgentsSDKRunner,
    build_agent,
    build_run_config,
    iter_streamed_text,
    split_chat_messages,
    stream_text_deltas,
)
from app.agents.structured_judgement import (
    FieldPolicy,
    JudgementPolicy,
    StructuredJudgement,
    coerce_structured_judgements,
    normalize_judgements,
)
from app.core.config import Settings, get_settings
from app.services.llm_client import LLMCallError, LLMConfigurationError, LLMInvalidResponseError


EXERCISE_COACH_AGENT_NAME = "Aearn Exercise Coach"
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
EXPLANATION_RESULTS = {"passed", "partial", "failed"}
EXPLANATION_CHECK_JUDGEMENT_POLICY = JudgementPolicy(
    fields=[
        FieldPolicy(
            name="explanation_sufficiency",
            required=True,
            fallback_question="请再说明关键代码为什么要这样写。",
        ),
        FieldPolicy(
            name="feedback_grounding",
            required=False,
            fallback_question="请把反馈和你刚才的解释对应起来。",
            blocks_on=("ambiguous", "unsupported"),
        ),
        FieldPolicy(
            name="next_action",
            required=False,
            fallback_question="请明确下一步是重试、补充解释还是进入变体复习。",
            blocks_on=("ambiguous", "unsupported"),
        ),
    ],
    default_fallback_question="请再补一句能证明你理解关键代码行为的话。",
)
SAFE_GENERATION_EXCEPTIONS = (
    LLMCallError,
    LLMConfigurationError,
    LLMInvalidResponseError,
    TypeError,
    ValueError,
)


@dataclass(frozen=True)
class ExerciseCoachJsonResponse:
    content: dict[str, object]
    model: str


class ExerciseCoachClient(Protocol):
    @property
    def model(self) -> str: ...

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float = 0.2,
    ) -> ExerciseCoachJsonResponse: ...


class AgentsSDKExerciseCoachClient:
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
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float = 0.2,
    ) -> ExerciseCoachJsonResponse:
        instructions, input_text = split_chat_messages(messages)
        input_guardrails, output_guardrails = build_teaching_guardrails()
        agent = build_agent(
            name=EXERCISE_COACH_AGENT_NAME,
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
        return ExerciseCoachJsonResponse(content=_parse_json_object(content), model=self.model)


def build_sdk_hint_response(
    exercise: Mapping[str, object],
    *,
    blank: Mapping[str, object],
    hint_level: str,
    current_code: str,
    hint_usage_count: int,
    settings: Settings | None = None,
    client: ExerciseCoachClient | None = None,
) -> dict[str, object] | None:
    resolved_client = _resolve_client(settings=settings, client=client)
    if resolved_client is None:
        return None
    messages = _build_hint_messages(
        exercise,
        blank=blank,
        hint_level=hint_level,
        current_code=current_code,
        hint_usage_count=hint_usage_count,
    )
    try:
        result = resolved_client.complete_json(messages, temperature=0.2)
        content = _required_str(result.content, "content", max_length=700)
        assert_safe_teaching_output(content)
    except SAFE_GENERATION_EXCEPTIONS:
        return None

    return {
        "hint": {
            "hint_level": hint_level,
            "content": content,
        },
        "hint_usage_count": hint_usage_count,
        "affected_score": _affected_score_for_hint(hint_level),
        "next_action": "retry_same",
    }


def build_sdk_error_explanation(
    exercise: Mapping[str, object],
    *,
    error_message: str,
    stderr: str,
    failed_tests: Sequence[Mapping[str, object]],
    current_code: str,
    related_knowledge_points: Sequence[Mapping[str, object]],
    settings: Settings | None = None,
    client: ExerciseCoachClient | None = None,
) -> dict[str, object] | None:
    resolved_client = _resolve_client(settings=settings, client=client)
    if resolved_client is None:
        return None
    forbidden_tokens = _hidden_case_ids(failed_tests)
    messages = _build_error_messages(
        exercise,
        error_message=error_message,
        stderr=stderr,
        failed_tests=failed_tests,
        current_code=current_code,
        related_knowledge_points=related_knowledge_points,
    )
    try:
        result = resolved_client.complete_json(messages, temperature=0.2)
        response = _validate_error_response(
            result.content,
            related_knowledge_points=related_knowledge_points,
            forbidden_tokens=forbidden_tokens,
        )
    except SAFE_GENERATION_EXCEPTIONS:
        return None

    response["generation_source"] = "llm"
    response["generation_model"] = result.model
    return response


def build_sdk_explanation_check_response(
    exercise: Mapping[str, object],
    *,
    explanation: str,
    focus: str,
    round_number: int,
    settings: Settings | None = None,
    client: ExerciseCoachClient | None = None,
) -> dict[str, object] | None:
    resolved_client = _resolve_client(settings=settings, client=client)
    if resolved_client is None:
        return None
    messages = _build_explanation_check_messages(
        exercise,
        explanation=explanation,
        focus=focus,
        round_number=round_number,
    )
    try:
        result = resolved_client.complete_json(messages, temperature=0.1)
        response = _validate_explanation_check_response(
            result.content,
            round_number=round_number,
        )
    except SAFE_GENERATION_EXCEPTIONS:
        return None
    return response


def _resolve_client(
    *,
    settings: Settings | None,
    client: ExerciseCoachClient | None,
) -> ExerciseCoachClient | None:
    if client is not None:
        return client
    effective_settings = settings or get_settings()
    if not effective_settings.openai_compatible_configured:
        return None
    try:
        return AgentsSDKExerciseCoachClient(effective_settings)
    except LLMConfigurationError:
        return None


def _build_hint_messages(
    exercise: Mapping[str, object],
    *,
    blank: Mapping[str, object],
    hint_level: str,
    current_code: str,
    hint_usage_count: int,
) -> list[dict[str, str]]:
    evidence = {
        "learner_message": f"Generate a {hint_level} hint for the current blank without giving a complete answer.",
        "task": "hint",
        "exercise": _exercise_evidence(exercise),
        "blank": _blank_evidence(blank),
        "hint_level": hint_level,
        "hint_usage_count": hint_usage_count,
        "current_code_excerpt": _current_code_excerpt(current_code, str(blank.get("blank_key", ""))),
        "output_schema": {
            "content": "short hint text only",
        },
    }
    return _json_messages(
        "你是 Aearn 的练习提示 Coach。只输出 JSON，不要 Markdown。提示必须短、分层、可执行；"
        "nudge 不给代码形状，concept 解释概念，code_shape 只能给局部结构，不要补完整题。",
        evidence,
    )


def _build_error_messages(
    exercise: Mapping[str, object],
    *,
    error_message: str,
    stderr: str,
    failed_tests: Sequence[Mapping[str, object]],
    current_code: str,
    related_knowledge_points: Sequence[Mapping[str, object]],
) -> list[dict[str, str]]:
    evidence = {
        "learner_message": "Explain the failed run using only visible runtime facts.",
        "task": "explain_error",
        "exercise": _exercise_evidence(exercise),
        "error_message": _limit_text(error_message, 800),
        "stderr": _limit_text(stderr, 1000),
        "failed_tests": _failed_tests_evidence(failed_tests),
        "current_code_excerpt": _current_code_excerpt(current_code, ""),
        "related_knowledge_points": _knowledge_points_evidence(related_knowledge_points),
        "allowed_error_causes": sorted(ALLOWED_ERROR_CAUSES),
        "allowed_next_actions": sorted(ALLOWED_NEXT_ACTIONS),
        "output_schema": {
            "error_cause": "one allowed error cause",
            "explanation": "grounded short explanation",
            "fix_suggestion": "one actionable next fix",
            "next_action": "usually retry_same",
        },
    }
    return _json_messages(
        "你是 Aearn 的错因解释 Coach。只根据 evidence 输出 JSON；不要推测不存在的运行结果；"
        "不要输出隐藏测试、参考答案、provider 错误、完整修复代码或 Markdown。",
        evidence,
    )


def _build_explanation_check_messages(
    exercise: Mapping[str, object],
    *,
    explanation: str,
    focus: str,
    round_number: int,
) -> list[dict[str, str]]:
    evidence = {
        "learner_message": "Check whether the learner explanation shows understanding.",
        "task": "check_explanation",
        "exercise": _exercise_evidence(exercise),
        "learner_explanation": _limit_text(explanation, 1200),
        "focus": focus,
        "round_number": round_number,
        "output_schema": {
            "result": "passed, partial, or failed",
            "feedback": "short feedback grounded in the explanation",
            "judgements": {
                "explanation_sufficiency": {
                    "status": "confirmed | ambiguous | missing | unsupported",
                    "clarification_question": "question when not confirmed",
                },
                "feedback_grounding": {
                    "status": "confirmed | ambiguous | missing | unsupported",
                    "clarification_question": "optional question",
                },
                "next_action": {
                    "status": "confirmed | ambiguous | missing | unsupported",
                    "clarification_question": "optional question",
                },
            },
        },
    }
    return _json_messages(
        "你是 Aearn 的解释检查 Coach。只输出 JSON，不要 Markdown。"
        "只判断学习者是否理解关键代码、边界条件或 AI 改动原因，不要给完整答案。"
        "必须输出 judgements，逐字段说明 explanation_sufficiency、feedback_grounding、next_action 是否 confirmed、ambiguous、missing 或 unsupported。",
        evidence,
    )


def _json_messages(system_prompt: str, evidence: Mapping[str, object]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
        },
    ]


def _exercise_evidence(exercise: Mapping[str, object]) -> dict[str, object]:
    runtime_profile = _mapping(exercise.get("runtime_profile"))
    code_blanks = _sequence(exercise.get("code_blanks"))
    test_cases = _sequence(exercise.get("test_cases"))
    visible_tests = []
    non_visible_count = 0
    for item in test_cases[:10]:
        test_case = _mapping(item)
        if not test_case:
            continue
        case_type = str(test_case.get("case_type") or "")
        if case_type == "hidden":
            non_visible_count += 1
            continue
        visible_tests.append(
            {
                "case_type": case_type,
                "is_critical": bool(test_case.get("is_critical", False)),
                "weight": test_case.get("weight"),
            }
        )

    return {
        "id": _limit_text(str(exercise.get("id", "")), 80),
        "title": _limit_text(str(exercise.get("title", "")), 160),
        "exercise_type": _limit_text(str(exercise.get("exercise_type", "")), 60),
        "prompt_summary": _limit_text(str(exercise.get("prompt_markdown", "")), 700),
        "requires_explanation": bool(exercise.get("requires_explanation", False)),
        "runtime_profile": {
            "language": _limit_text(str(runtime_profile.get("language", "")), 40),
            "runtime_tier": _limit_text(str(runtime_profile.get("runtime_tier", "")), 80),
        },
        "code_blanks": [_blank_evidence(_mapping(blank)) for blank in code_blanks[:8] if _mapping(blank)],
        "visible_tests": visible_tests[:8],
        "non_visible_test_count": non_visible_count,
    }


def _blank_evidence(blank: Mapping[str, object]) -> dict[str, object]:
    return {
        "blank_key": _limit_text(str(blank.get("blank_key", "")), 80),
        "placeholder": _limit_text(str(blank.get("placeholder", "")), 120),
        "expected_concept": _limit_text(str(blank.get("expected_concept", "")), 180),
        "is_core": bool(blank.get("is_core", False)),
    }


def _failed_tests_evidence(failed_tests: Sequence[Mapping[str, object]]) -> list[dict[str, str]]:
    sanitized: list[dict[str, str]] = []
    for test in failed_tests[:8]:
        case_type = str(test.get("case_type") or "")
        message = "A non-visible test failed." if case_type == "hidden" else str(test.get("message") or "")
        sanitized.append(
            {
                "case_type": _limit_text(case_type, 40),
                "message": _limit_text(message, 360),
            }
        )
    return sanitized


def _knowledge_points_evidence(items: Sequence[Mapping[str, object]]) -> list[dict[str, str]]:
    return [
        {
            "id": _limit_text(str(item.get("id", "")), 80),
            "title": _limit_text(str(item.get("title", "")), 160),
        }
        for item in items
        if isinstance(item, Mapping)
    ]


def _validate_error_response(
    payload: Mapping[str, object],
    *,
    related_knowledge_points: Sequence[Mapping[str, object]],
    forbidden_tokens: Sequence[str],
) -> dict[str, object]:
    error_cause = _required_str(payload, "error_cause", max_length=80)
    if error_cause not in ALLOWED_ERROR_CAUSES:
        raise LLMInvalidResponseError("SDK coach returned unsupported error_cause")
    explanation = _required_str(payload, "explanation", max_length=900)
    fix_suggestion = _required_str(payload, "fix_suggestion", max_length=700)
    next_action = _required_str(payload, "next_action", max_length=40)
    if next_action not in ALLOWED_NEXT_ACTIONS:
        raise LLMInvalidResponseError("SDK coach returned unsupported next_action")
    _reject_forbidden_output([error_cause, explanation, fix_suggestion, next_action], forbidden_tokens)
    assert_safe_teaching_output(explanation)
    assert_safe_teaching_output(fix_suggestion)
    return {
        "error_cause": error_cause,
        "explanation": explanation,
        "fix_suggestion": fix_suggestion,
        "related_knowledge_points": _knowledge_points_evidence(related_knowledge_points),
        "next_action": next_action,
    }


def _validate_explanation_check_response(
    payload: Mapping[str, object],
    *,
    round_number: int,
) -> dict[str, object]:
    result = _required_str(payload, "result", max_length=40)
    if result not in EXPLANATION_RESULTS:
        raise LLMInvalidResponseError("SDK coach returned unsupported explanation-check result")
    feedback = _required_str(payload, "feedback", max_length=800)
    assert_safe_teaching_output(feedback)
    score = {"passed": 2, "partial": 1, "failed": 0}[result]
    follow_up_required = result != "passed" and round_number < 2
    response: dict[str, object] = {
        "result": result,
        "score": score,
        "score_breakdown": {"explanation_check": score},
        "follow_up_required": follow_up_required,
        "feedback": feedback,
        "next_action": "advance_next" if result == "passed" else "retry_same" if round_number < 2 else "review_variant",
    }
    return attach_explanation_check_judgement(response, payload.get("judgements"), require_explicit=True)


def attach_explanation_check_judgement(
    candidate: Mapping[str, object],
    raw_judgements: object | None = None,
    *,
    require_explicit: bool = False,
) -> dict[str, object]:
    response = dict(candidate)
    judgement_payload = raw_judgements if raw_judgements is not None else response.get("judgements")
    if isinstance(judgement_payload, Mapping):
        judgements = coerce_structured_judgements(judgement_payload, EXPLANATION_CHECK_JUDGEMENT_POLICY)
    elif require_explicit:
        judgements = coerce_structured_judgements({}, EXPLANATION_CHECK_JUDGEMENT_POLICY)
    else:
        judgements = _legacy_explanation_check_judgements()
    normalized = normalize_judgements(
        _explanation_check_judgement_values(response),
        judgements,
        EXPLANATION_CHECK_JUDGEMENT_POLICY,
    )
    response["judgements"] = _serialize_judgements(judgements)
    response["judgement_ready"] = normalized.ready
    response["judgement_cleared_fields"] = list(normalized.cleared_fields)
    response["judgement_blocking_fields"] = list(normalized.blocking_fields)
    response["clarification_question"] = normalized.clarification_question
    return response


def _explanation_check_judgement_values(candidate: Mapping[str, object]) -> dict[str, object]:
    return {
        "explanation_sufficiency": candidate.get("result"),
        "feedback_grounding": candidate.get("feedback"),
        "next_action": candidate.get("next_action"),
    }


def _legacy_explanation_check_judgements() -> dict[str, StructuredJudgement]:
    return {
        "explanation_sufficiency": StructuredJudgement(status="confirmed"),
        "feedback_grounding": StructuredJudgement(status="confirmed"),
        "next_action": StructuredJudgement(status="confirmed"),
    }


def _serialize_judgements(
    judgements: Mapping[str, StructuredJudgement],
) -> dict[str, dict[str, object]]:
    return {
        name: judgement.model_dump(exclude_none=True)
        for name, judgement in judgements.items()
    }


def _required_str(payload: Mapping[str, object], key: str, *, max_length: int) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise LLMInvalidResponseError(f"SDK coach field {key} must be a string")
    stripped = value.strip()
    if not stripped:
        raise LLMInvalidResponseError(f"SDK coach field {key} must not be blank")
    return _limit_text(stripped, max_length)


def _parse_json_object(content: str) -> dict[str, object]:
    try:
        parsed = json.loads(_strip_json_fence(content))
    except json.JSONDecodeError as exc:
        raise LLMInvalidResponseError("SDK coach output is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise LLMInvalidResponseError("SDK coach output must be a JSON object")
    return parsed


def _strip_json_fence(content: str) -> str:
    stripped = content.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


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
            raise LLMInvalidResponseError("SDK coach output leaked hidden test identifier")


def _current_code_excerpt(current_code: str, anchor: str) -> str:
    normalized = current_code.strip()
    if not normalized:
        return ""
    max_length = 480
    anchor_index = normalized.find(anchor) if anchor else -1
    if anchor_index < 0:
        return _limit_text(normalized, max_length)
    start = max(0, anchor_index - 220)
    end = min(len(normalized), anchor_index + len(anchor) + 220)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(normalized) else ""
    return f"{prefix}{normalized[start:end]}{suffix}"


def _affected_score_for_hint(hint_level: str) -> dict[str, object]:
    if hint_level == "nudge":
        return {"max_result": "easy", "score_penalty_hint": 0}
    if hint_level == "concept":
        return {"max_result": "passed", "score_penalty_hint": 1}
    return {"max_result": "passed", "score_penalty_hint": 2}


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return value
    return []


def _limit_text(value: str, max_length: int) -> str:
    stripped = value.strip()
    if len(stripped) <= max_length:
        return stripped
    return f"{stripped[:max_length]}..."
