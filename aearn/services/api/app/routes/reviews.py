import asyncio
from collections.abc import AsyncGenerator, Iterable
from datetime import datetime

from fastapi import APIRouter, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.errors import (
    MODEL_UNAVAILABLE_MESSAGE,
    error_response,
    model_unavailable_response,
    request_id_from,
)
from app.db.connection import connect
from app.models.reviews import StartReviewSessionRequest, SubmitReviewExerciseResultRequest
from app.services.plan_repository import IdempotencyConflictError
from app.services.review_conversation import (
    ReviewSessionNotFoundError,
    prepare_review_message,
    safe_generation_exceptions,
    start_review_generation,
    store_review_agent_message,
)
from app.services.review_repository import (
    EntityNotFoundError,
    ReviewNotDueError,
    ReviewSessionConflictError,
    get_today_reviews,
    start_review_session,
    submit_review_exercise_result,
)
from app.services.llm_client import LLMCallError, LLMConfigurationError, LLMInvalidResponseError
from app.services.sse import SSEWriter, stream_response


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
        except (LLMCallError, LLMConfigurationError, LLMInvalidResponseError) as exc:
            conn.rollback()
            return model_unavailable_response(
                request,
                details={"reason": exc.__class__.__name__},
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


@router.post("/{session_id}/messages", response_model=None)
async def create_review_message(
    session_id: str,
    request: Request,
) -> StreamingResponse:
    request_id = request_id_from(request)
    body = await request.json()

    content = str(body.get("content") or "")
    client_message_id = str(body.get("client_message_id") or "")

    if not content or not client_message_id:
        return stream_response(
            _review_error_stream(
                code="VALIDATION_ERROR",
                message="复习对话请求缺少必要字段（content, client_message_id）",
                request_id=request_id,
            )
        )

    return stream_response(
        _review_message_stream(
            request,
            session_id=session_id,
            content=content,
            client_message_id=client_message_id,
            request_id=request_id,
        )
    )


async def _review_message_stream(
    request: Request,
    *,
    session_id: str,
    content: str,
    client_message_id: str,
    request_id: str,
) -> AsyncGenerator[str, None]:
    writer = SSEWriter()
    try:
        with connect() as conn:
            try:
                prepared = prepare_review_message(
                    conn,
                    session_id=session_id,
                    content=content,
                    client_message_id=client_message_id,
                )
            except ReviewSessionNotFoundError as exc:
                conn.rollback()
                yield writer.error(
                    code=exc.code,
                    message=exc.message,
                    request_id=request_id,
                    details={"session_id": session_id},
                )
                return
            conn.commit()

        # Idempotency replay
        if prepared.stored_content is not None:
            yield writer.event(
                "agent_message",
                _review_agent_message_event(
                    request_id=request_id,
                    session_id=session_id,
                    message_id=prepared.message_id,
                    delta=prepared.stored_content,
                    content=prepared.stored_content,
                ),
            )
            yield writer.event(
                "done",
                {
                    "request_id": request_id,
                    "session_id": session_id,
                    "message_id": prepared.message_id,
                    "generation_source": "replay",
                    "generation_model": "",
                    "result_ref": {"type": "ReviewMessage", "id": prepared.message_id},
                },
            )
            return

        full_text = ""

        try:
            generation = start_review_generation(prepared.context, user_content=content)
            generation_source = generation.generation_source
            generation_model = generation.generation_model
            async for delta in _review_iter_chunks(request, generation.chunks):
                full_text += delta
                yield writer.event(
                    "agent_message",
                    _review_agent_message_event(
                        request_id=request_id,
                        session_id=session_id,
                        message_id=prepared.message_id,
                        delta=delta,
                        content=full_text,
                    ),
                )
        except safe_generation_exceptions() as exc:
            yield writer.error(
                code="MODEL_UNAVAILABLE",
                message=MODEL_UNAVAILABLE_MESSAGE,
                request_id=request_id,
                details={"reason": exc.__class__.__name__},
                recoverable=True,
            )
            return

        if not full_text.strip():
            yield writer.error(
                code="MODEL_UNAVAILABLE",
                message=MODEL_UNAVAILABLE_MESSAGE,
                request_id=request_id,
                details={"reason": "empty_model_output"},
                recoverable=True,
            )
            return

        # Persist agent message
        with connect() as conn:
            store_review_agent_message(
                conn,
                session_id=session_id,
                content=full_text.strip(),
            )
            conn.commit()

        yield writer.event(
            "done",
            {
                "request_id": request_id,
                "session_id": session_id,
                "message_id": prepared.message_id,
                "generation_source": generation_source,
                "generation_model": generation_model,
                "result_ref": {"type": "ReviewMessage", "id": prepared.message_id},
            },
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        yield writer.error(
            code="INTERNAL_ERROR",
            message="复习对话流式响应失败",
            request_id=request_id,
            recoverable=True,
        )


async def _review_error_stream(
    *,
    code: str,
    message: str,
    request_id: str,
    details: dict[str, object] | None = None,
) -> AsyncGenerator[str, None]:
    yield SSEWriter().error(
        code=code,
        message=message,
        request_id=request_id,
        details=details,
    )


async def _review_iter_chunks(request: Request, chunks: Iterable[str]) -> AsyncGenerator[str, None]:
    for delta in chunks:
        if await request.is_disconnected():
            return
        if not delta:
            continue
        yield delta
        await asyncio.sleep(0)


def _review_agent_message_event(
    *,
    request_id: str,
    session_id: str,
    message_id: str,
    delta: str,
    content: str,
) -> dict[str, object]:
    return {
        "request_id": request_id,
        "session_id": session_id,
        "message_id": message_id,
        "delta": delta,
        "content": content,
    }
