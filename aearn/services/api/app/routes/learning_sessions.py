from fastapi import APIRouter, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.core.errors import error_response, request_id_from
from app.db.connection import connect
from app.models.learning_sessions import (
    CheckExplanationRequest,
    ExplainErrorRequest,
    HintRequest,
    RunExerciseRequest,
    StartLearningSessionRequest,
    SubmitExerciseRequest,
)
from app.services.learning_session_repository import (
    EvaluationConflictError,
    EntityNotFoundError,
    InvalidLearningSessionRequestError,
    SessionStateConflictError,
    check_learning_attempt_explanation,
    explain_learning_attempt_error,
    request_learning_hint,
    run_learning_session_exercise,
    start_learning_session,
    submit_learning_session_exercise,
)
from app.services.dashboard_repository import (
    EntityNotFoundError as ResumeEntityNotFoundError,
    get_resume_context,
)
from app.services.plan_repository import IdempotencyConflictError


router = APIRouter(prefix="/api/learning-sessions", tags=["learning-sessions"])


@router.get("/resume", response_model=None)
def read_resume_context(
    request: Request,
    user_id: str = Query(min_length=1),
    plan_id: str = Query(min_length=1),
) -> dict[str, object] | JSONResponse:
    with connect() as conn:
        try:
            response = get_resume_context(conn, user_id=user_id, plan_id=plan_id)
        except ResumeEntityNotFoundError as exc:
            return error_response(
                request,
                code=exc.code,
                message=exc.message,
                status_code=status.HTTP_404_NOT_FOUND,
                details={"user_id": user_id, "plan_id": plan_id},
            )
    return JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(response))


@router.post("/start", response_model=None)
def create_learning_session(
    payload: StartLearningSessionRequest,
    request: Request,
) -> dict[str, object] | JSONResponse:
    with connect() as conn:
        try:
            response, reused = start_learning_session(
                conn,
                user_id=payload.user_id,
                plan_id=payload.plan_id,
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
                details={
                    "user_id": payload.user_id,
                    "plan_id": payload.plan_id,
                    "knowledge_point_id": payload.knowledge_point_id,
                },
            )
        conn.commit()
    return JSONResponse(
        status_code=status.HTTP_200_OK if reused else status.HTTP_201_CREATED,
        content=jsonable_encoder(response),
    )


@router.post("/{session_id}/exercises/{exercise_id}/run", response_model=None)
async def run_learning_session(
    session_id: str,
    exercise_id: str,
    request: Request,
) -> dict[str, object] | JSONResponse:
    body = await request.json()
    try:
        payload = RunExerciseRequest.model_validate(body)
    except ValueError as exc:
        return error_response(
            request,
            code="VALIDATION_ERROR",
            message="运行请求结构不合法",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"reason": str(exc)},
        )

    with connect() as conn:
        try:
            response, replayed = run_learning_session_exercise(
                conn,
                session_id=session_id,
                exercise_id=exercise_id,
                code=payload.code,
                filled_blanks=payload.filled_blanks,
                run_mode=payload.run_mode,
                runtime_profile_id=payload.runtime_profile_id,
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
                details={"session_id": session_id, "exercise_id": exercise_id},
            )
        except SessionStateConflictError as exc:
            conn.rollback()
            return error_response(
                request,
                code="ATTEMPT_STATE_CONFLICT",
                message="当前会话状态不允许运行该练习",
                status_code=status.HTTP_409_CONFLICT,
                details={"reason": str(exc)},
                recoverable=False,
            )
        except IdempotencyConflictError as exc:
            conn.rollback()
            return error_response(
                request,
                code="IDEMPOTENCY_CONFLICT",
                message="同一运行幂等键对应不同请求体",
                status_code=status.HTTP_409_CONFLICT,
                details={"reason": str(exc)},
                recoverable=False,
            )
        conn.commit()
    if replayed:
        response["idempotency_replayed"] = True
    return JSONResponse(
        status_code=status.HTTP_200_OK if replayed else status.HTTP_201_CREATED,
        content=jsonable_encoder(response),
    )


@router.post("/{session_id}/exercises/{exercise_id}/hint", response_model=None)
async def get_learning_hint(
    session_id: str,
    exercise_id: str,
    request: Request,
) -> dict[str, object] | JSONResponse:
    body = await request.json()
    try:
        payload = HintRequest.model_validate(body)
    except ValueError as exc:
        return error_response(
            request,
            code="VALIDATION_ERROR",
            message="提示请求结构不合法",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"reason": str(exc)},
        )

    with connect() as conn:
        try:
            response, replayed = request_learning_hint(
                conn,
                session_id=session_id,
                exercise_id=exercise_id,
                attempt_id=payload.attempt_id,
                current_code=payload.current_code,
                blank_id=payload.blank_id,
                hint_level=payload.hint_level,
                request_body=body,
            )
        except EntityNotFoundError as exc:
            conn.rollback()
            return error_response(
                request,
                code=exc.code,
                message=exc.message,
                status_code=status.HTTP_404_NOT_FOUND,
                details={"session_id": session_id, "exercise_id": exercise_id, "attempt_id": payload.attempt_id},
            )
        except InvalidLearningSessionRequestError as exc:
            conn.rollback()
            return error_response(
                request,
                code="VALIDATION_ERROR",
                message="提示请求参数不合法",
                status_code=status.HTTP_400_BAD_REQUEST,
                details={"reason": str(exc)},
            )
        except IdempotencyConflictError as exc:
            conn.rollback()
            return error_response(
                request,
                code="IDEMPOTENCY_CONFLICT",
                message="同一提示幂等键对应不同请求体",
                status_code=status.HTTP_409_CONFLICT,
                details={"reason": str(exc)},
                recoverable=False,
            )
        conn.commit()
    if replayed:
        response["idempotency_replayed"] = True
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=jsonable_encoder(response),
    )


@router.post("/{session_id}/attempts/{attempt_id}/explain-error", response_model=None)
async def explain_learning_error(
    session_id: str,
    attempt_id: str,
    request: Request,
) -> dict[str, object] | JSONResponse:
    body = await request.json()
    try:
        payload = ExplainErrorRequest.model_validate(body)
    except ValueError as exc:
        return error_response(
            request,
            code="VALIDATION_ERROR",
            message="错因解释请求结构不合法",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"reason": str(exc)},
        )

    with connect() as conn:
        try:
            response, replayed = explain_learning_attempt_error(
                conn,
                session_id=session_id,
                attempt_id=attempt_id,
                error_message=payload.error_message or "",
                stderr=payload.stderr or "",
                failed_tests=[item.model_dump() for item in payload.failed_tests],
                current_code=payload.current_code,
                request_body=body,
            )
        except EntityNotFoundError as exc:
            conn.rollback()
            return error_response(
                request,
                code=exc.code,
                message=exc.message,
                status_code=status.HTTP_404_NOT_FOUND,
                details={"session_id": session_id, "attempt_id": attempt_id},
            )
        except InvalidLearningSessionRequestError as exc:
            conn.rollback()
            return error_response(
                request,
                code="VALIDATION_ERROR",
                message="错因解释缺少必要上下文",
                status_code=status.HTTP_400_BAD_REQUEST,
                details={"reason": str(exc)},
            )
        conn.commit()
    if replayed:
        response["idempotency_replayed"] = True
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=jsonable_encoder(response),
    )


@router.post("/{session_id}/attempts/{attempt_id}/check-explanation", response_model=None)
async def check_learning_explanation(
    session_id: str,
    attempt_id: str,
    request: Request,
) -> dict[str, object] | JSONResponse:
    body = await request.json()
    try:
        payload = CheckExplanationRequest.model_validate(body)
    except ValueError as exc:
        return error_response(
            request,
            code="VALIDATION_ERROR",
            message="解释检查请求结构不合法",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"reason": str(exc)},
        )

    with connect() as conn:
        try:
            response, replayed = check_learning_attempt_explanation(
                conn,
                session_id=session_id,
                attempt_id=attempt_id,
                explanation=payload.explanation,
                focus=payload.focus,
                round_number=payload.round,
                request_body=body,
            )
        except EntityNotFoundError as exc:
            conn.rollback()
            return error_response(
                request,
                code=exc.code,
                message=exc.message,
                status_code=status.HTTP_404_NOT_FOUND,
                details={"session_id": session_id, "attempt_id": attempt_id},
            )
        except EvaluationConflictError as exc:
            conn.rollback()
            return error_response(
                request,
                code="EVALUATION_CONFLICT",
                message="解释检查轮次超过上限",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"reason": str(exc)},
                recoverable=False,
            )
        except IdempotencyConflictError as exc:
            conn.rollback()
            return error_response(
                request,
                code="IDEMPOTENCY_CONFLICT",
                message="同一解释检查轮次对应不同请求体",
                status_code=status.HTTP_409_CONFLICT,
                details={"reason": str(exc)},
                recoverable=False,
            )
        conn.commit()
    if replayed:
        response["idempotency_replayed"] = True
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=jsonable_encoder(response),
    )


@router.post("/{session_id}/exercises/{exercise_id}/submit", response_model=None)
async def submit_learning_session(
    session_id: str,
    exercise_id: str,
    request: Request,
) -> dict[str, object] | JSONResponse:
    body = await request.json()
    try:
        payload = SubmitExerciseRequest.model_validate(body)
    except ValueError as exc:
        return error_response(
            request,
            code="VALIDATION_ERROR",
            message="提交请求结构不合法",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"reason": str(exc)},
        )

    with connect() as conn:
        try:
            response, replayed = submit_learning_session_exercise(
                conn,
                session_id=session_id,
                exercise_id=exercise_id,
                attempt_id=payload.attempt_id,
                code=payload.code,
                filled_blanks=payload.filled_blanks,
                submit_version=payload.submit_version,
                explanation=payload.explanation,
                hint_usage_count=payload.hint_usage_count,
                error_count=payload.error_count,
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
                details={"session_id": session_id, "exercise_id": exercise_id, "attempt_id": payload.attempt_id},
            )
        except SessionStateConflictError as exc:
            conn.rollback()
            return error_response(
                request,
                code="ATTEMPT_STATE_CONFLICT",
                message="当前尝试不允许提交评分",
                status_code=status.HTTP_409_CONFLICT,
                details={"reason": str(exc)},
                recoverable=False,
            )
        except IdempotencyConflictError as exc:
            conn.rollback()
            return error_response(
                request,
                code="IDEMPOTENCY_CONFLICT",
                message="同一提交幂等键对应不同请求体",
                status_code=status.HTTP_409_CONFLICT,
                details={"reason": str(exc)},
                recoverable=False,
            )
        conn.commit()
    if replayed:
        response["idempotency_replayed"] = True
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=jsonable_encoder(response),
    )
