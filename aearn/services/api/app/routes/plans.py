from fastapi import APIRouter, Header, Request, status
from fastapi.responses import JSONResponse

from app.agents.onboarding_plan_agent import build_onboarding_plan_context, build_sdk_onboarding_plan_response
from app.agents.plan_generation_agent import (
    build_plan_generation_context,
    build_sdk_plan_generation_response,
)
from app.core.errors import error_response
from app.db.connection import connect
from app.models.onboarding import PlanConfirmRequest, PlanDraft, PlanGenerateRequest
from app.services.catalog import get_course
from app.services.plan_generator import (
    build_plan_draft,
    has_supported_mvp_runtime,
    validate_generation_input,
)
from app.services.plan_repository import (
    EntityNotFoundError,
    IdempotencyConflictError,
    PlanDraftError,
    confirm_plan,
    default_confirm_key,
    get_plan_detail,
    request_hash,
)
from app.services.user_repository import get_user


router = APIRouter(prefix="/api/plans", tags=["plans"])


@router.post("/generate", response_model=None)
def generate_plan(payload: PlanGenerateRequest, request: Request) -> dict[str, object] | JSONResponse:
    input_error = validate_generation_input(payload)
    if input_error is not None:
        return error_response(
            request,
            code="VALIDATION_ERROR",
            message=input_error,
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"mode": payload.mode},
        )

    with connect() as conn:
        user = get_user(conn, payload.user_id)
        if user is None:
            return error_response(
                request,
                code="USER_NOT_FOUND",
                message="用户不存在",
                status_code=status.HTTP_404_NOT_FOUND,
                details={"user_id": payload.user_id},
            )
        course = get_course(conn, payload.course_id, language=payload.language)
        if course is None:
            return error_response(
                request,
                code="COURSE_NOT_FOUND",
                message="课程不存在",
                status_code=status.HTTP_404_NOT_FOUND,
                details={"course_id": payload.course_id, "language": payload.language},
            )

    deterministic_plan_draft = build_plan_draft(payload, user, course)
    plan_draft = deterministic_plan_draft
    agent_notes = _deterministic_agent_notes(deterministic_plan_draft)

    # 尝试动态生成学习路线
    dynamic_modules = build_sdk_plan_generation_response(
        build_plan_generation_context(payload, course)
    )
    if dynamic_modules is not None:
        plan_draft = deterministic_plan_draft.model_copy(
            update={
                "modules": dynamic_modules,
                "source_attribution": [
                    *deterministic_plan_draft.source_attribution,
                    "Dynamic generation: agent_generated",
                ],
            }
        )
        agent_notes = [
            deterministic_plan_draft.runtime_boundary.notice,
            "学习路线已根据权威文档和用户目标动态生成。",
        ]
    else:
        # Fallback: 使用现有 onboarding plan agent 微调静态模板
        sdk_response = build_sdk_onboarding_plan_response(
            build_onboarding_plan_context(payload, user, course, deterministic_plan_draft)
        )
        if sdk_response is not None:
            sdk_plan_draft = sdk_response.get("plan_draft")
            if isinstance(sdk_plan_draft, PlanDraft):
                plan_draft = sdk_plan_draft.model_copy(
                    update={
                        "source_attribution": _merge_unique_strings(
                            deterministic_plan_draft.source_attribution,
                            sdk_plan_draft.source_attribution,
                        )
                    }
                )
                agent_notes = _merge_unique_strings(
                    _deterministic_agent_notes(deterministic_plan_draft),
                    _string_list(sdk_response.get("agent_notes")),
                )
    if plan_draft.language in {"javascript", "html_css", "python"} and not has_supported_mvp_runtime(plan_draft):
        return error_response(
            request,
            code="PLAN_DRAFT_INVALID",
            message="计划草稿缺少第一版可运行能力",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details={"runtime_tier": plan_draft.runtime_boundary.runtime_tier},
        )

    return {
        "plan_draft": plan_draft.model_dump(mode="json"),
        "agent_notes": agent_notes,
        "next_action": "advance_next",
    }


@router.post("", status_code=status.HTTP_201_CREATED, response_model=None)
async def create_plan(
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, object] | JSONResponse:
    body = await request.json()
    try:
        payload = PlanConfirmRequest.model_validate(body)
    except ValueError as exc:
        return error_response(
            request,
            code="PLAN_DRAFT_INVALID",
            message="plan_draft 结构不合法",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details={"reason": str(exc)},
        )

    key = idempotency_key or default_confirm_key(payload.user_id, payload.plan_draft.draft_id)
    body_hash = request_hash(body)
    with connect() as conn:
        try:
            response, replayed = confirm_plan(
                conn,
                user_id=payload.user_id,
                plan_draft=payload.plan_draft,
                idempotency_key=key,
                request_hash=body_hash,
            )
        except EntityNotFoundError as exc:
            conn.rollback()
            return error_response(
                request,
                code=exc.code,
                message=exc.message,
                status_code=status.HTTP_404_NOT_FOUND,
                details={"user_id": payload.user_id, "course_id": payload.plan_draft.language_course_id},
            )
        except PlanDraftError as exc:
            conn.rollback()
            return error_response(
                request,
                code="PLAN_DRAFT_INVALID",
                message="plan_draft 未通过校验",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"reason": str(exc)},
            )
        except IdempotencyConflictError as exc:
            conn.rollback()
            return error_response(
                request,
                code="IDEMPOTENCY_CONFLICT",
                message="同一幂等键对应不同请求体",
                status_code=status.HTTP_409_CONFLICT,
                details={"reason": str(exc)},
                recoverable=False,
            )
        conn.commit()
    if replayed:
        response["idempotency_replayed"] = True
    return response


@router.get("/{plan_id}", response_model=None)
def read_plan(plan_id: str, request: Request) -> dict[str, object] | JSONResponse:
    with connect() as conn:
        plan = get_plan_detail(conn, plan_id)
    if plan is None:
        return error_response(
            request,
            code="PLAN_NOT_FOUND",
            message="学习计划不存在",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"plan_id": plan_id},
        )
    return plan


def _deterministic_agent_notes(plan_draft: PlanDraft) -> list[str]:
    return [
        plan_draft.runtime_boundary.notice,
        "M2 uses deterministic course templates; full runner sessions start in M3.",
    ]


def _merge_unique_strings(primary: list[str], secondary: list[str]) -> list[str]:
    merged: list[str] = []
    for item in [*primary, *secondary]:
        text = str(item or "").strip()
        if text and text not in merged:
            merged.append(text)
    return merged


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]
