from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import JSONResponse

from app.core.errors import error_response
from app.db.connection import connect
from app.models.onboarding import PlanConfirmRequest, PlanGenerateRequest
from app.services.curriculum.catalog import get_course
from app.services.curriculum.dynamic_plan_generation import (
    DynamicPlanGenerationError,
    build_dynamic_plan_draft,
)
from app.services.curriculum.plan_generator import validate_generation_input
from app.services.repositories.plan_repository import (
    EntityNotFoundError,
    IdempotencyConflictError,
    PlanDraftError,
    confirm_plan,
    default_confirm_key,
    get_plan_detail,
    request_hash,
)
from app.services.repositories.user_repository import get_user
from app.services.tutor.cutover import require_legacy_runtime


router = APIRouter(prefix="/api/plans", tags=["plans"], dependencies=[Depends(require_legacy_runtime)])


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

    try:
        dynamic_plan = build_dynamic_plan_draft(payload, user, course)
    except DynamicPlanGenerationError as exc:
        return error_response(
            request,
            code=exc.code,
            message=exc.message,
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
                if exc.code == "PLAN_DRAFT_INVALID"
                else status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            details=exc.details,
        )

    return {
        "plan_draft": dynamic_plan.plan_draft.model_dump(mode="json"),
        "agent_notes": dynamic_plan.agent_notes,
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
def read_plan(
    plan_id: str,
    request: Request,
    user_id: str | None = Query(default=None, min_length=1),
) -> dict[str, object] | JSONResponse:
    with connect() as conn:
        plan = get_plan_detail(conn, plan_id, user_id=user_id)
    if plan is None:
        return error_response(
            request,
            code="PLAN_NOT_FOUND",
            message="学习计划不存在",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"plan_id": plan_id},
        )
    return plan
