from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from app.agents.runtime.agent_domain_contexts import build_onboarding_plan_runtime_context
from app.agents.runtime.agent_runtime_context import limit_text, parse_fenced_json_object, strip_json_fence
from app.agents.runtime.guardrails import assert_safe_teaching_output, build_teaching_guardrails
from app.agents.runtime.sdk_runtime import (
    AgentsSDKRunner,
    build_agent,
    build_run_config,
    iter_streamed_text,
    split_chat_messages,
    stream_text_deltas,
)
from app.core.config import Settings, get_settings
from app.models.onboarding import PlanDraft, PlanGenerateRequest
from app.services.llm.llm_client import LLMCallError, LLMConfigurationError, LLMInvalidResponseError


ONBOARDING_PLAN_AGENT_NAME = "Aearn Onboarding Plan"

_PLAN_EXPANSION_PATTERNS = (
    re.compile(r"\bCodeDraft\b", re.IGNORECASE),
    re.compile(r"CodeDraftPage", re.IGNORECASE),
    re.compile(r"/api/code-drafts", re.IGNORECASE),
    re.compile(r"publishDrawer", re.IGNORECASE),
    re.compile(r"任意学科"),
    re.compile(r"通用学习"),
    re.compile(r"general subject", re.IGNORECASE),
    re.compile(r"any subject", re.IGNORECASE),
    re.compile(r"non-programming", re.IGNORECASE),
)
_UNSUPPORTED_RUNTIME_PROMISE_PATTERNS = (
    re.compile(r"(Java|C\+\+).{0,32}(can|could|will|now|currently).{0,24}(run|compile)", re.IGNORECASE),
    re.compile(r"(Java|C\+\+).{0,32}(实时运行|真实运行|可运行|完整沙箱)"),
    re.compile(r"(真实编译|完整编译沙箱|compile-and-run support is available)", re.IGNORECASE),
)


@dataclass(frozen=True)
class OnboardingPlanContext:
    user_id: str
    goal_text: str
    mode: str
    user_profile: Mapping[str, object]
    course: Mapping[str, object]
    materials: Sequence[Mapping[str, object]]
    clarification_answers: Sequence[Mapping[str, object]]
    deterministic_plan_draft: Mapping[str, object]


@dataclass(frozen=True)
class OnboardingPlanJsonResponse:
    content: dict[str, object]
    model: str


class OnboardingPlanClient(Protocol):
    @property
    def model(self) -> str: ...

    def complete_json(
        self,
        context: OnboardingPlanContext,
        *,
        temperature: float | None = None,
    ) -> OnboardingPlanJsonResponse: ...


class AgentsSDKOnboardingPlanClient:
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
        context: OnboardingPlanContext,
        *,
        temperature: float | None = None,
    ) -> OnboardingPlanJsonResponse:
        messages = _build_messages(context)
        instructions, input_text = split_chat_messages(messages)
        input_guardrails, output_guardrails = build_teaching_guardrails()
        agent = build_agent(
            name=ONBOARDING_PLAN_AGENT_NAME,
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
        return OnboardingPlanJsonResponse(content=_parse_json_object(content), model=self.model)


def build_onboarding_plan_client(
    settings: Settings | None = None,
    *,
    runner: AgentsSDKRunner | None = None,
) -> OnboardingPlanClient | None:
    effective_settings = settings or get_settings()
    if not effective_settings.openai_compatible_configured:
        return None
    try:
        return AgentsSDKOnboardingPlanClient(effective_settings, runner=runner)
    except LLMConfigurationError:
        return None


def build_onboarding_plan_context(
    payload: PlanGenerateRequest,
    user: Mapping[str, object],
    course: Mapping[str, object],
    deterministic_plan_draft: PlanDraft,
) -> OnboardingPlanContext:
    draft_payload = deterministic_plan_draft.model_dump(mode="json")
    return OnboardingPlanContext(
        user_id=payload.user_id,
        goal_text=str(draft_payload["goal_text"]),
        mode=payload.mode,
        user_profile=_safe_user_profile(user, payload),
        course=_safe_course_context(course),
        materials=tuple(material.model_dump(mode="json") for material in payload.materials),
        clarification_answers=tuple(answer.model_dump(mode="json") for answer in payload.clarification_answers),
        deterministic_plan_draft=draft_payload,
    )


def build_sdk_onboarding_plan_response(
    context: OnboardingPlanContext,
    *,
    settings: Settings | None = None,
    client: OnboardingPlanClient | None = None,
) -> dict[str, object] | None:
    resolved_client = _resolve_client(settings=settings, client=client)
    if resolved_client is None:
        return None

    try:
        result = resolved_client.complete_json(context, temperature=None)
        response = _validate_onboarding_plan_response(result.content, context)
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


def assert_safe_onboarding_plan_output(text: str) -> None:
    assert_safe_teaching_output(text)
    for pattern in (*_PLAN_EXPANSION_PATTERNS, *_UNSUPPORTED_RUNTIME_PROMISE_PATTERNS):
        if pattern.search(text):
            raise LLMInvalidResponseError("Onboarding Plan output leaked disallowed plan wording")


def _resolve_client(
    *,
    settings: Settings | None,
    client: OnboardingPlanClient | None,
) -> OnboardingPlanClient | None:
    if client is not None:
        return client
    effective_settings = settings or get_settings()
    if not effective_settings.openai_compatible_configured:
        return None
    try:
        return AgentsSDKOnboardingPlanClient(effective_settings)
    except LLMConfigurationError:
        return None


def _build_messages(context: OnboardingPlanContext) -> list[dict[str, str]]:
    evidence = {
        "learner_message": "Draft an Aearn programming-language learning plan from the supplied course template only.",
        "task": "onboarding_plan_draft",
        "user_goal": {
            "mode": context.mode,
            "goal_text": _bounded_text(context.goal_text, 500),
            "materials": [_bounded_mapping(material, 360) for material in context.materials[:4]],
            "clarification_answers": [_bounded_mapping(answer, 240) for answer in context.clarification_answers[:8]],
        },
        "user_profile": _bounded_mapping(context.user_profile, 300),
        "course": context.course,
        "runtime_context": build_onboarding_plan_runtime_context(
            goal_text=context.goal_text,
            mode=context.mode,
            user_profile=context.user_profile,
            course=context.course,
            materials=context.materials,
            clarification_answers=context.clarification_answers,
            deterministic_plan_draft=context.deterministic_plan_draft,
        ),
        "safe_base_plan_draft": context.deterministic_plan_draft,
        "output_schema": {
            "plan_draft": "PlanDraft JSON object using only supplied template module and knowledge_point temp_ids",
            "agent_notes": ["short visible note about goal clarification or runtime boundary"],
        },
    }
    return [
        {
            "role": "system",
            "content": (
                "你是 Aearn 的建档学习计划 Agent。只输出 JSON 对象。"
                "必须使用 safe_base_plan_draft 中的 user_id、draft_id、language_course_id、language、runtime_boundary、mode、target_level 和 deadline。"
                "modules 与 knowledge_points 只能从 safe_base_plan_draft 的模板中选择或重排，不能新增非编程课程、不能承诺 Java/C++ 真实运行沙箱。"
                "不得输出 provider 原始错误、隐藏测试、参考答案、CodeDraft、publishDrawer 或任意学科学习路线。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(evidence, ensure_ascii=False, separators=(",", ":"), default=str),
        },
    ]


def _validate_onboarding_plan_response(
    payload: Mapping[str, object],
    context: OnboardingPlanContext,
) -> dict[str, object]:
    plan_payload = payload.get("plan_draft")
    if not isinstance(plan_payload, Mapping):
        raise LLMInvalidResponseError("Onboarding plan output must include plan_draft object")

    candidate = PlanDraft.model_validate(plan_payload)
    deterministic = PlanDraft.model_validate(context.deterministic_plan_draft)
    _validate_candidate_against_template(candidate, deterministic)

    candidate_payload = candidate.model_dump(mode="json")
    _assert_safe_text_tree(candidate_payload)
    agent_notes = _validate_agent_notes(payload.get("agent_notes"))
    return {"plan_draft": candidate, "agent_notes": agent_notes}


def _validate_candidate_against_template(candidate: PlanDraft, deterministic: PlanDraft) -> None:
    candidate_payload = candidate.model_dump(mode="json")
    deterministic_payload = deterministic.model_dump(mode="json")

    for key in (
        "draft_id",
        "user_id",
        "language_course_id",
        "language",
        "target_level",
        "mode",
        "deadline",
        "runtime_boundary",
    ):
        if candidate_payload.get(key) != deterministic_payload.get(key):
            raise LLMInvalidResponseError(f"Onboarding plan draft changed server-owned field {key}")

    template_modules = {str(module["temp_id"]): module for module in deterministic_payload["modules"]}
    if not candidate.modules:
        raise LLMInvalidResponseError("Onboarding plan draft must include modules")
    if not any(not module.is_skippable for module in candidate.modules):
        raise LLMInvalidResponseError("Onboarding plan draft must keep at least one core module")

    for module in candidate_payload["modules"]:
        if not isinstance(module, Mapping):
            raise LLMInvalidResponseError("Onboarding plan module is invalid")
        template_module = template_modules.get(str(module.get("temp_id")))
        if not isinstance(template_module, Mapping):
            raise LLMInvalidResponseError("Onboarding plan draft used unsupported module template")
        _validate_template_module(module, template_module)


def _validate_template_module(module: Mapping[str, object], template_module: Mapping[str, object]) -> None:
    for key in ("title", "description", "is_skippable", "is_adjustable", "estimated_sessions", "source"):
        if module.get(key) != template_module.get(key):
            raise LLMInvalidResponseError(f"Onboarding plan module changed template field {key}")

    knowledge_points = module.get("knowledge_points")
    if not isinstance(knowledge_points, list) or not knowledge_points:
        raise LLMInvalidResponseError("Onboarding plan module must include knowledge points")
    template_points = template_module.get("knowledge_points")
    if not isinstance(template_points, list):
        raise LLMInvalidResponseError("Onboarding plan template knowledge points are invalid")
    template_by_id = {
        str(item.get("temp_id")): item for item in template_points if isinstance(item, Mapping) and item.get("temp_id")
    }

    for knowledge_point in knowledge_points:
        if not isinstance(knowledge_point, Mapping):
            raise LLMInvalidResponseError("Onboarding plan knowledge point is invalid")
        template_point = template_by_id.get(str(knowledge_point.get("temp_id")))
        if not isinstance(template_point, Mapping):
            raise LLMInvalidResponseError("Onboarding plan draft used unsupported knowledge point template")
        for key in ("title", "description", "skill_tags", "source", "exercise_refs"):
            if knowledge_point.get(key) != template_point.get(key):
                raise LLMInvalidResponseError(f"Onboarding plan knowledge point changed template field {key}")


def _validate_agent_notes(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise LLMInvalidResponseError("Onboarding plan agent_notes must be a list")

    notes: list[str] = []
    for item in value[:4]:
        if not isinstance(item, str):
            raise LLMInvalidResponseError("Onboarding plan agent note must be a string")
        note = _bounded_text(item, 260)
        if not note:
            continue
        assert_safe_onboarding_plan_output(note)
        notes.append(note)
    return notes


def _parse_json_object(content: str) -> dict[str, object]:
    return parse_fenced_json_object(
        content,
        invalid_message="Onboarding plan output is not valid JSON",
        object_message="Onboarding plan output must be a JSON object",
    )


def _strip_json_fence(content: str) -> str:
    return strip_json_fence(content)


def _safe_user_profile(user: Mapping[str, object], payload: PlanGenerateRequest) -> dict[str, object]:
    return {
        "id": str(user.get("id") or payload.user_id),
        "display_name": _bounded_text(user.get("display_name"), 80),
        "learning_style": _bounded_text(user.get("learning_style"), 80),
        "teaching_preference": _bounded_text(user.get("teaching_preference"), 80),
        "encouragement_preference": _bounded_text(user.get("encouragement_preference"), 80),
        "profession": _bounded_text(payload.profession or user.get("profession"), 120),
        "background_context": _bounded_text(user.get("background_context"), 320),
    }


def _safe_course_context(course: Mapping[str, object]) -> dict[str, object]:
    runtime_profile = course.get("runtime_profile")
    if not isinstance(runtime_profile, Mapping):
        runtime_profile = {}
    return {
        "id": str(course["id"]),
        "slug": _bounded_text(course.get("slug"), 120),
        "language": _bounded_text(course.get("language"), 40),
        "title": _bounded_text(course.get("title"), 160),
        "description": _bounded_text(course.get("description"), 500),
        "level": _bounded_text(course.get("level"), 80),
        "runtime_profile": {
            "id": _bounded_text(runtime_profile.get("id"), 120),
            "runtime_tier": _bounded_text(runtime_profile.get("runtime_tier"), 80),
            "language": _bounded_text(runtime_profile.get("language"), 40),
            "runner": _bounded_text(runtime_profile.get("runner"), 80),
            "supports_realtime_preview": bool(runtime_profile.get("supports_realtime_preview")),
            "supports_stdout": bool(runtime_profile.get("supports_stdout")),
            "supports_tests": bool(runtime_profile.get("supports_tests")),
            "compile_required": bool(runtime_profile.get("compile_required")),
            "sandbox_policy": _bounded_text(runtime_profile.get("sandbox_policy"), 120),
        },
        "supported_exercise_types_json": _string_list(course.get("supported_exercise_types_json"))[:8],
    }


def _bounded_mapping(mapping: Mapping[str, object], max_value_length: int) -> dict[str, object]:
    bounded: dict[str, object] = {}
    for key, value in mapping.items():
        if isinstance(value, str):
            bounded[str(key)] = _bounded_text(value, max_value_length)
        elif isinstance(value, list):
            bounded[str(key)] = [_bounded_text(item, max_value_length) for item in value[:8]]
        else:
            bounded[str(key)] = value
    return bounded


def _assert_safe_text_tree(value: object) -> None:
    if isinstance(value, str):
        assert_safe_onboarding_plan_output(value)
        return
    if isinstance(value, Mapping):
        for child in value.values():
            _assert_safe_text_tree(child)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            _assert_safe_text_tree(child)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _bounded_text(value: object, max_length: int) -> str:
    return limit_text(value, max_length)
