from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from app.agents.runtime.agent_runtime_context import limit_text
from app.agents.runtime.guardrails import assert_safe_teaching_output, build_teaching_guardrails
from app.agents.runtime.sdk_runtime import (
    AgentsSDKRunner,
    build_agent,
    build_run_config,
    iter_streamed_text,
    split_chat_messages,
    stream_text_deltas,
)
from app.agents.runtime.structured_judgement import (
    FieldPolicy,
    JudgementPolicy,
    StructuredJudgement,
    coerce_structured_judgements,
    normalize_judgements,
)
from app.core.config import Settings, get_settings
from app.services.llm.llm_client import (
    LLMCallError,
    LLMConfigurationError,
    LLMInvalidResponseError,
    LLMJsonResponse,
    OpenAICompatibleClient,
)


CONCEPT_AGENT_NAME = "Aearn Concept Check Agent"
CONCEPT_RESULTS = {"correct", "incorrect", "unclear", "skipped"}
CONFIDENCE_LEVELS = {"high", "medium", "low"}
ANSWER_LEAKAGE_REVIEW_STATUSES = {"clear", "revised"}
CONCEPT_CHECK_JUDGEMENT_POLICY = JudgementPolicy(
    fields=[
        FieldPolicy(
            name="answer_correctness",
            required=True,
            fallback_question="请直接说明你的选择，并补一句为什么。",
        ),
        FieldPolicy(
            name="confidence",
            required=True,
            fallback_question="请再补一句判断依据，让我确认你不是在猜。",
        ),
        FieldPolicy(
            name="misconception",
            required=False,
            fallback_question="请说明你觉得最容易混淆的点是什么。",
            blocks_on=("ambiguous", "unsupported"),
        ),
        FieldPolicy(
            name="repair_check",
            required=False,
            fallback_question="请再用一个更小的判断题确认当前概念。",
            blocks_on=("ambiguous", "unsupported"),
        ),
    ],
    default_fallback_question="请再用一句更具体的话说明你的判断依据。",
)
SAFE_GENERATION_EXCEPTIONS = (
    LLMCallError,
    LLMConfigurationError,
    LLMInvalidResponseError,
    TypeError,
    ValueError,
)


@dataclass(frozen=True)
class ConceptJsonResponse:
    content: dict[str, object]
    model: str


class ConceptClient(Protocol):
    @property
    def model(self) -> str: ...

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float = 0.2,
    ) -> ConceptJsonResponse: ...


class LLMJsonConceptClient(Protocol):
    @property
    def model(self) -> str: ...

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float | None = None,
    ) -> LLMJsonResponse: ...


class DirectConceptClient:
    def __init__(
        self,
        settings: Settings,
        *,
        json_client: LLMJsonConceptClient | None = None,
        runner: object | None = None,
    ) -> None:
        del runner
        self._settings = settings
        self._json_client = json_client or OpenAICompatibleClient(settings)

    @property
    def model(self) -> str:
        return str(self._json_client.model or self._settings.llm_model or "")

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float = 0.2,
    ) -> ConceptJsonResponse:
        result = self._json_client.complete_json(messages, temperature=temperature)
        return ConceptJsonResponse(content=result.content, model=result.model or self.model)


class AgentsSDKConceptClient:
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
    ) -> ConceptJsonResponse:
        instructions, input_text = split_chat_messages(messages)
        input_guardrails, output_guardrails = build_teaching_guardrails()
        agent = build_agent(
            name=CONCEPT_AGENT_NAME,
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
        return ConceptJsonResponse(content=_parse_json_object(content), model=self.model)


def build_sdk_concept_intro(
    *,
    knowledge_point: Mapping[str, object],
    lesson_outline: Sequence[Mapping[str, object]],
    lesson_sources: Sequence[Mapping[str, object]],
    learner_questions: Sequence[str] | None = None,
    settings: Settings | None = None,
    client: ConceptClient | None = None,
) -> dict[str, object] | None:
    resolved_client = _resolve_client(settings=settings, client=client)
    if resolved_client is None:
        return None
    messages = _build_intro_messages(
        knowledge_point=knowledge_point,
        lesson_outline=lesson_outline,
        lesson_sources=lesson_sources,
        learner_questions=learner_questions or [],
    )
    try:
        result = resolved_client.complete_json(messages, temperature=0.2)
        return _validate_intro_payload(result.content)
    except SAFE_GENERATION_EXCEPTIONS:
        return None


def build_sdk_concept_check_result(
    *,
    knowledge_point: Mapping[str, object],
    lesson_outline: Sequence[Mapping[str, object]],
    lesson_sources: Sequence[Mapping[str, object]],
    active_intro: Mapping[str, object],
    active_check: Mapping[str, object],
    learner_answer: str,
    attempt_count: int,
    previous_misconceptions: Sequence[str],
    conversation_context: Mapping[str, object],
    settings: Settings | None = None,
    client: ConceptClient | None = None,
) -> dict[str, object] | None:
    resolved_client = _resolve_client(settings=settings, client=client)
    if resolved_client is None:
        return None
    messages = _build_check_messages(
        knowledge_point=knowledge_point,
        lesson_outline=lesson_outline,
        lesson_sources=lesson_sources,
        active_intro=active_intro,
        active_check=active_check,
        learner_answer=learner_answer,
        attempt_count=attempt_count,
        previous_misconceptions=previous_misconceptions,
        conversation_context=conversation_context,
    )
    try:
        result = resolved_client.complete_json(messages, temperature=0.1)
        return _validate_check_result_payload(result.content)
    except SAFE_GENERATION_EXCEPTIONS:
        return None


def _resolve_client(
    *,
    settings: Settings | None,
    client: ConceptClient | None,
) -> ConceptClient | None:
    if client is not None:
        return client
    effective_settings = settings or get_settings()
    if not effective_settings.openai_compatible_configured:
        return None
    try:
        if effective_settings.llm_provider_type == "deepseek":
            return DirectConceptClient(effective_settings)
        return AgentsSDKConceptClient(effective_settings)
    except LLMConfigurationError:
        return None


def _build_intro_messages(
    *,
    knowledge_point: Mapping[str, object],
    lesson_outline: Sequence[Mapping[str, object]],
    lesson_sources: Sequence[Mapping[str, object]],
    learner_questions: Sequence[str],
) -> list[dict[str, str]]:
    evidence = {
        "task": "generate_concept_intro",
        "knowledge_point": _knowledge_point_evidence(knowledge_point),
        "lesson_outline": [_outline_item(item) for item in lesson_outline[:6]],
        "lesson_sources": [_source_item(item) for item in lesson_sources[:4]],
        "learner_questions": [limit_text(item, 240) for item in learner_questions[:6] if item.strip()],
        "output_schema": {
            "summary": "1-2 sentence concept summary",
            "example": {
                "title": "short title",
                "body": "easy example or tiny code-like example",
                "takeaway": "what the learner should notice",
            },
            "check": {
                "type": "single_choice",
                "question": "natural-language judgment question",
                "options": [{"id": "A", "text": "option text"}],
                "expected_focus": "core relationship being tested",
            },
        },
    }
    return _json_messages(
        "你是 Aearn 的概念开场卡生成器。只输出 JSON，不要 Markdown。必须生成简短概念摘要、一个低门槛例子和一个 2-4 选项的单选判断题。如 learner_questions 不为空，判断题要优先覆盖学习者刚才问过或引用过的卡点。不得暴露完整练习答案、hidden tests、solution_reference、raw prompt、provider errors 或密钥。",
        evidence,
    )


def _build_check_messages(
    *,
    knowledge_point: Mapping[str, object],
    lesson_outline: Sequence[Mapping[str, object]],
    lesson_sources: Sequence[Mapping[str, object]],
    active_intro: Mapping[str, object],
    active_check: Mapping[str, object],
    learner_answer: str,
    attempt_count: int,
    previous_misconceptions: Sequence[str],
    conversation_context: Mapping[str, object],
) -> list[dict[str, str]]:
    evidence = {
        "task": "judge_concept_check",
        "knowledge_point": _knowledge_point_evidence(knowledge_point),
        "lesson_outline": [_outline_item(item) for item in lesson_outline[:6]],
        "lesson_sources": [_source_item(item) for item in lesson_sources[:4]],
        "active_intro": dict(active_intro),
        "active_check": dict(active_check),
        "learner_answer": limit_text(learner_answer, 1200),
        "attempt_count": attempt_count,
        "previous_misconceptions": [limit_text(item, 160) for item in previous_misconceptions[:4]],
        "conversation_context": dict(conversation_context),
        "output_schema": {
            "result": "correct | incorrect | unclear",
            "confidence": "high | medium | low",
            "explanation": "short learner-facing explanation",
            "next_prompt": "what the learner should answer next",
            "actions": [{"id": "start_practice", "label": "开始练习"}],
            "repair_check": {
                "type": "single_choice",
                "question": "optional narrower follow-up check",
                "options": [{"id": "A", "text": "option text"}],
                "expected_focus": "optional focus",
            },
            "judgements": {
                "answer_correctness": {
                    "status": "confirmed | ambiguous | missing | unsupported",
                    "clarification_question": "question when not confirmed",
                },
                "confidence": {
                    "status": "confirmed | ambiguous | missing | unsupported",
                    "clarification_question": "question when not confirmed",
                },
                "misconception": {
                    "status": "confirmed | ambiguous | missing | unsupported",
                    "clarification_question": "optional question",
                },
                "repair_check": {
                    "status": "confirmed | ambiguous | missing | unsupported",
                    "clarification_question": "optional question",
                },
            },
            "answer_leakage_review": {
                "status": "clear | revised",
                "revealed_target_answer": False,
                "next_prompt_requires_same_answer": False,
                "reason": "short self-check explanation",
            },
        },
        "judgement_rules": {
            "unclear_only_when": [
                "learner did not answer the current check",
                "learner says they do not know or are unsure",
                "answer is unrelated to the current check",
                "natural-language stance cannot be determined",
                "answer contains conflicting positions",
            ],
            "partial_or_incomplete_answer": "incorrect, not unclear; explain the missing point",
            "directionally_correct_core_rule": "do not repeatedly ask for the same concrete value; use transfer/practice when needed",
        },
        "answer_leakage_rules": {
            "self_check_required": True,
            "if_explanation_reveals_target_answer": "final next_prompt must not ask learner to repeat that same answer",
            "allowed_revisions": ["transfer check", "reason check", "guided practice offer"],
            "backend_will_not_rewrite_answer": True,
        },
    }
    return _json_messages(
        "你是 Aearn 的概念判断器。只输出 JSON，不要 Markdown。根据学习者自然语言回答判断 correct、incorrect 或 unclear。unclear 只用于未回答、不知道/不确定、无关、立场无法判断或自相矛盾；漏选、部分正确、理由不完整但方向明确时必须判 incorrect 并指出缺失点，不能继续泛化追问。学习者已答中核心规则时，不得因为没有复述某个具体数值而无限追问。必须同时输出 judgements，逐字段说明 answer_correctness、confidence、misconception、repair_check 是否 confirmed、ambiguous、missing 或 unsupported。incorrect 时指出一个误解；如果仍需要修复，给出更窄的 2-4 选项判断题。最终输出前必须自检 answer_leakage_review：如果 explanation 已透露 next_prompt 要求的具体值、选项或代码片段，必须把 next_prompt 改成迁移题、原因题或练习邀请，并将 status 置为 revised。不得解锁练习，不得输出 hidden tests、solution_reference、raw prompt、provider errors 或密钥。",
        evidence,
    )


def _json_messages(system: str, evidence: Mapping[str, object]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
        },
    ]


def _validate_intro_payload(payload: Mapping[str, object]) -> dict[str, object]:
    summary = _required_str(payload, "summary", max_length=420)
    example = _required_mapping(payload, "example")
    check = _required_mapping(payload, "check")
    response: dict[str, object] = {
        "summary": summary,
        "example": {
            "title": _required_str(example, "title", max_length=120),
            "body": _required_str(example, "body", max_length=900),
            "takeaway": _required_str(example, "takeaway", max_length=260),
        },
        "check": _validate_single_choice_check(check),
    }
    _assert_payload_safe(response)
    return response


def _validate_check_result_payload(payload: Mapping[str, object]) -> dict[str, object]:
    result = str(payload.get("result") or "").strip().lower()
    if result not in CONCEPT_RESULTS:
        raise LLMInvalidResponseError("Concept check result is invalid")
    confidence = str(payload.get("confidence") or "").strip().lower()
    if confidence not in CONFIDENCE_LEVELS:
        confidence = "low"
    response: dict[str, object] = {
        "result": result,
        "confidence": confidence,
        "explanation": _required_str(payload, "explanation", max_length=700),
        "next_prompt": _required_str(payload, "next_prompt", max_length=500),
        "actions": _validate_actions(payload.get("actions")),
        "answer_leakage_review": _validate_answer_leakage_review(
            _required_mapping(payload, "answer_leakage_review")
        ),
    }
    repair_check = payload.get("repair_check")
    if isinstance(repair_check, Mapping):
        response["repair_check"] = _validate_single_choice_check(repair_check)
    else:
        response["repair_check"] = None
    _assert_payload_safe(response)
    return attach_concept_check_judgement(response, payload.get("judgements"), require_explicit=True)


def _validate_answer_leakage_review(value: Mapping[str, object]) -> dict[str, object]:
    status = str(value.get("status") or "").strip().lower()
    if status not in ANSWER_LEAKAGE_REVIEW_STATUSES:
        raise LLMInvalidResponseError("Concept check answer_leakage_review status is invalid")
    revealed_target_answer = value.get("revealed_target_answer")
    next_prompt_requires_same_answer = value.get("next_prompt_requires_same_answer")
    if not isinstance(revealed_target_answer, bool) or not isinstance(next_prompt_requires_same_answer, bool):
        raise LLMInvalidResponseError("Concept check answer_leakage_review booleans are invalid")
    return {
        "status": status,
        "revealed_target_answer": revealed_target_answer,
        "next_prompt_requires_same_answer": next_prompt_requires_same_answer,
        "reason": _required_str(value, "reason", max_length=260),
    }


def attach_concept_check_judgement(
    candidate: Mapping[str, object],
    raw_judgements: object | None = None,
    *,
    require_explicit: bool = False,
) -> dict[str, object]:
    response = dict(candidate)
    judgement_payload = raw_judgements if raw_judgements is not None else response.get("judgements")
    if isinstance(judgement_payload, Mapping):
        judgements = coerce_structured_judgements(judgement_payload, CONCEPT_CHECK_JUDGEMENT_POLICY)
    elif require_explicit:
        judgements = coerce_structured_judgements({}, CONCEPT_CHECK_JUDGEMENT_POLICY)
    else:
        judgements = _legacy_concept_check_judgements(response)
    normalized = normalize_judgements(
        _concept_check_judgement_values(response),
        judgements,
        CONCEPT_CHECK_JUDGEMENT_POLICY,
    )
    response["judgements"] = _serialize_judgements(judgements)
    response["judgement_ready"] = normalized.ready
    response["judgement_cleared_fields"] = list(normalized.cleared_fields)
    response["judgement_blocking_fields"] = list(normalized.blocking_fields)
    response["clarification_question"] = normalized.clarification_question
    return response


def _concept_check_judgement_values(candidate: Mapping[str, object]) -> dict[str, object]:
    result = str(candidate.get("result") or "")
    return {
        "answer_correctness": result,
        "confidence": candidate.get("confidence"),
        "misconception": candidate.get("explanation") if result == "incorrect" else None,
        "repair_check": candidate.get("repair_check"),
    }


def _legacy_concept_check_judgements(
    candidate: Mapping[str, object],
) -> dict[str, StructuredJudgement]:
    result = str(candidate.get("result") or "")
    repair_check = candidate.get("repair_check")
    repair_judgement = (
        StructuredJudgement(status="confirmed")
        if isinstance(repair_check, Mapping)
        else StructuredJudgement(status="missing")
    )
    return {
        "answer_correctness": StructuredJudgement(status="confirmed"),
        "confidence": StructuredJudgement(status="confirmed"),
        "misconception": StructuredJudgement(
            status="confirmed" if result == "incorrect" else "missing",
        ),
        "repair_check": repair_judgement,
    }


def _serialize_judgements(
    judgements: Mapping[str, StructuredJudgement],
) -> dict[str, dict[str, object]]:
    return {
        name: judgement.model_dump(exclude_none=True)
        for name, judgement in judgements.items()
    }


def _validate_single_choice_check(value: Mapping[str, object]) -> dict[str, object]:
    check_type = str(value.get("type") or "single_choice").strip()
    if check_type != "single_choice":
        raise LLMInvalidResponseError("Concept check type must be single_choice")
    options = _validate_options(value.get("options"))
    return {
        "type": "single_choice",
        "question": _required_str(value, "question", max_length=420),
        "options": options,
        "expected_focus": _required_str(value, "expected_focus", max_length=260),
    }


def _validate_options(value: object) -> list[dict[str, str]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise LLMInvalidResponseError("Concept check options must be a list")
    if len(value) < 2 or len(value) > 4:
        raise LLMInvalidResponseError("Concept check option count must be 2-4")
    options: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise LLMInvalidResponseError("Concept check option must be an object")
        option_id = _required_str(item, "id", max_length=12)
        if option_id in seen_ids:
            raise LLMInvalidResponseError("Concept check option ids must be unique")
        seen_ids.add(option_id)
        options.append({"id": option_id, "text": _required_str(item, "text", max_length=240)})
    return options


def _validate_actions(value: object) -> list[dict[str, str]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    actions: list[dict[str, str]] = []
    for item in value[:4]:
        if not isinstance(item, Mapping):
            continue
        action_id = str(item.get("id") or "").strip()
        label = str(item.get("label") or "").strip()
        if action_id and label:
            actions.append({"id": limit_text(action_id, 40), "label": limit_text(label, 80)})
    return actions


def _required_mapping(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise LLMInvalidResponseError(f"Concept payload missing object field {key}")
    return value


def _required_str(payload: Mapping[str, object], key: str, *, max_length: int) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise LLMInvalidResponseError(f"Concept payload missing text field {key}")
    return limit_text(value, max_length)


def _assert_payload_safe(value: object) -> None:
    if isinstance(value, Mapping):
        for item in value.values():
            _assert_payload_safe(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            _assert_payload_safe(item)
        return
    if isinstance(value, str):
        assert_safe_teaching_output(value)


def _knowledge_point_evidence(value: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": str(value.get("id") or ""),
        "title": limit_text(value.get("title"), 160),
        "description": limit_text(value.get("description"), 500),
        "module_title": limit_text(value.get("module_title"), 160),
        "course_title": limit_text(value.get("course_title"), 160),
    }


def _outline_item(value: Mapping[str, object]) -> dict[str, str]:
    return {
        "id": str(value.get("id") or ""),
        "title": limit_text(value.get("title"), 120),
        "note": limit_text(value.get("note"), 500),
    }


def _source_item(value: Mapping[str, object]) -> dict[str, str]:
    return {
        "title": limit_text(value.get("title"), 160),
        "url": limit_text(value.get("url"), 300),
    }


def _parse_json_object(content: str) -> dict[str, object]:
    try:
        parsed = json.loads(_strip_json_fence(content))
    except json.JSONDecodeError as exc:
        raise LLMInvalidResponseError("Concept model returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise LLMInvalidResponseError("Concept model response must be a JSON object")
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
