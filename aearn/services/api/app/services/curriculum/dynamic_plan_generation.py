from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.agents.onboarding.plan_generation_agent import (
    AUTHORITATIVE_DOCS,
    PlanGenerationClient,
    build_plan_generation_context,
    build_sdk_plan_generation_response,
)
from app.core.config import Settings
from app.models.onboarding import PlanDraft, PlanGenerateRequest
from app.services.curriculum.plan_generator import (
    build_plan_draft_with_modules,
    has_supported_mvp_runtime,
)


@dataclass(frozen=True)
class DynamicPlanDraftResult:
    plan_draft: PlanDraft
    agent_notes: list[str]


class DynamicPlanGenerationError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def build_dynamic_plan_draft(
    payload: PlanGenerateRequest,
    user: Mapping[str, object],
    course: Mapping[str, object],
    *,
    settings: Settings | None = None,
    client: PlanGenerationClient | None = None,
) -> DynamicPlanDraftResult:
    language = str(course.get("language") or payload.language or "")
    if not AUTHORITATIVE_DOCS.get(language):
        raise DynamicPlanGenerationError(
            "PLAN_GENERATION_UNAVAILABLE",
            "动态路线生成缺少该语言的权威文档配置。",
            {"reason": "authoritative_docs_missing", "language": language},
        )

    context = build_plan_generation_context(payload, course)
    dynamic_result = build_sdk_plan_generation_response(
        context,
        settings=settings,
        client=client,
    )
    if dynamic_result is None:
        raise DynamicPlanGenerationError(
            "PLAN_GENERATION_UNAVAILABLE",
            "动态路线生成不可用，请检查模型、PLAN_GENERATION_ENABLED 和 EXA_API_KEY 配置。",
            {"reason": "dynamic_result_unavailable_or_invalid", "language": language},
        )

    plan_draft = build_plan_draft_with_modules(
        payload,
        user,
        course,
        dynamic_result.modules,
        extra_source_attribution=dynamic_result.source_attribution,
    )
    if not has_supported_mvp_runtime(plan_draft):
        raise DynamicPlanGenerationError(
            "PLAN_DRAFT_INVALID",
            "该课程当前的运行时还不在 MVP 支持范围。",
            {
                "reason": "runtime_not_supported",
                "runtime_tier": plan_draft.runtime_boundary.runtime_tier,
            },
        )

    return DynamicPlanDraftResult(
        plan_draft=plan_draft,
        agent_notes=[
            plan_draft.runtime_boundary.notice,
            "学习路线已根据权威文档和用户目标动态生成。",
        ],
    )
