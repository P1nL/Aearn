from datetime import datetime

from fastapi import APIRouter, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.core.errors import error_response, request_id_from
from app.db.connection import connect
from app.models.reviews import StartReviewSessionRequest, SubmitReviewExerciseResultRequest
from app.services.plan_repository import IdempotencyConflictError
from app.services.review_repository import (
    EntityNotFoundError,
    ReviewNotDueError,
    ReviewSessionConflictError,
    get_today_reviews,
    start_review_session,
    submit_review_exercise_result,
)


router = APIRouter(prefix="/api/reviews", tags=["reviews"])


@router.get("/today", response_model=None)
def list_today_reviews(
    request: Request,
    user_id: str = Query(min_length=1),
    due_before: datetime | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, object] | JSONResponse:
    with connect() as conn:
        try:
            response = get_today_reviews(
                conn,
                user_id=user_id,
                due_before=due_before,
                limit=limit,
            )
        except EntityNotFoundError as exc:
            return error_response(
                request,
                code=exc.code,
                message=exc.message,
                status_code=status.HTTP_404_NOT_FOUND,
                details={"user_id": user_id},
            )
    return JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(response))


@router.post("/start", response_model=None)
def create_review_session(
    payload: StartReviewSessionRequest,
    request: Request,
) -> dict[str, object] | JSONResponse:
    with connect() as conn:
        try:
            response, reused = start_review_session(
                conn,
                user_id=payload.user_id,
                knowledge_point_id=payload.knowledge_point_id,
                request_id=request_id_from(request),
            )
        except EntityNotFoundError as exc:
            conn.rollback()
            return error_response(
                request,
                code=exc.code,
                message=exc.message,
                status_code=status.HTTP_404_NOT_FOUND,
                details={"user_id": payload.user_id, "knowledge_point_id": payload.knowledge_point_id},
            )
        except ReviewNotDueError as exc:
            conn.rollback()
            return error_response(
                request,
                code="REVIEW_NOT_DUE",
                message="当前知识点未到复习时间",
                status_code=status.HTTP_409_CONFLICT,
                details={"reason": str(exc), "knowledge_point_id": payload.knowledge_point_id},
                recoverable=True,
            )
        conn.commit()
    return JSONResponse(
        status_code=status.HTTP_200_OK if reused else status.HTTP_201_CREATED,
        content=jsonable_encoder(response),
    )


@router.post("/{session_id}/exercise-result", response_model=None)
async def submit_review_result(
    session_id: str,
    request: Request,
) -> dict[str, object] | JSONResponse:
    body = await request.json()
    try:
        payload = SubmitReviewExerciseResultRequest.model_validate(body)
    except ValueError as exc:
        return error_response(
            request,
            code="VALIDATION_ERROR",
            message="复习提交请求结构不合法",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"reason": str(exc)},
        )

    with connect() as conn:
        try:
            response, replayed = submit_review_exercise_result(
                conn,
                session_id=session_id,
                exercise_id=payload.exercise_id,
                attempt_id=payload.attempt_id,
                code=payload.code,
                filled_blanks=payload.filled_blanks,
                submit_version=payload.submit_version,
                explanation=payload.explanation,
                hint_usage_count=payload.hint_usage_count,
                error_count=payload.error_count,
                explanation_check=payload.explanation_check,
                provided_code_hash=payload.code_hash,
                request_id=request_id_from(request),
                request_body=body,
            )
        except EntityNotFoundError as exc:
            conn.rollback()
            return error_response(
                request,
                code=exc.code,
                message=exc.message,
                status_code=status.HTTP_404_NOT_FOUND,
                details={"session_id": session_id, "exercise_id": payload.exercise_id, "attempt_id": payload.attempt_id},
            )
        except ReviewSessionConflictError as exc:
            conn.rollback()
            return error_response(
                request,
                code="SESSION_CONFLICT",
                message="复习会话状态冲突",
                status_code=status.HTTP_409_CONFLICT,
                details={"reason": str(exc)},
                recoverable=False,
            )
        except IdempotencyConflictError as exc:
            conn.rollback()
            return error_response(
                request,
                code="IDEMPOTENCY_CONFLICT",
                message="同一复习提交幂等键对应不同请求体",
                status_code=status.HTTP_409_CONFLICT,
                details={"reason": str(exc)},
                recoverable=False,
            )
        conn.commit()
    if replayed:
        response["idempotency_replayed"] = True
    return JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(response))
