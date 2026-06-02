import asyncio
from collections.abc import AsyncGenerator, Iterable
from datetime import datetime

from fastapi import APIRouter, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from psycopg import Connection

from app.agents.graph_runtime_contracts import GraphRunResult, IntentType, validate_run_result_for_boundary
from app.agents.review_graph import invoke_review_orchestration, review_result_to_run_result
from app.core.config import get_settings
from app.core.errors import (
    MODEL_UNAVAILABLE_MESSAGE,
    error_response,
    model_unavailable_response,
    request_id_from,
)
from app.db.connection import connect
from app.models.reviews import ReviewWarmupResultRequest, StartReviewSessionRequest, SubmitReviewExerciseResultRequest
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
    InvalidReviewRequestError,
    ReviewNotDueError,
    ReviewSessionConflictError,
    get_today_reviews,
    record_review_warmup_result,
    start_review_session,
    submit_review_exercise_result,
)
from app.services.review_seed_bank import ReviewSeedBankGenerationError
from app.services.llm_client import LLMCallError, LLMConfigurationError, LLMInvalidResponseError
from app.services.sse import SSEWriter, stream_response


router = APIRouter(prefix="/api/reviews", tags=["reviews"])

REVIEW_GRAPH_ALLOWED_INTENT_TARGETS = {
    IntentType.PERSISTENCE: ("review_session", "attempt_and_fsrs"),
    IntentType.TOOL_CALL: ("review_coach", "evaluate_warmup"),
}


def _review_graph_decision(
    *,
    session_id: str = "",
    user_id: str,
    knowledge_point_id: str,
    action: str,
    is_due: bool = True,
    has_active_session: bool = False,
    attempt_result: str | None = None,
    fsrs_rating: str | None = None,
    explanation_ready: bool = False,
    coach_feedback_requested: bool = False,
) -> str | None:
    run_result = _review_graph_run_result(
        session_id=session_id,
        user_id=user_id,
        knowledge_point_id=knowledge_point_id,
        action=action,
        is_due=is_due,
        has_active_session=has_active_session,
        attempt_result=attempt_result,
        fsrs_rating=fsrs_rating,
        explanation_ready=explanation_ready,
        coach_feedback_requested=coach_feedback_requested,
    )
    return run_result.next_stage if run_result is not None else None


def _review_graph_run_result(
    *,
    session_id: str = "",
    user_id: str,
    knowledge_point_id: str,
    action: str,
    is_due: bool = True,
    has_active_session: bool = False,
    attempt_result: str | None = None,
    fsrs_rating: str | None = None,
    explanation_ready: bool = False,
    coach_feedback_requested: bool = False,
) -> GraphRunResult | None:
    if not get_settings().langgraph_enabled:
        return None
    try:
        result = invoke_review_orchestration(
            session_id=session_id,
            user_id=user_id,
            knowledge_point_id=knowledge_point_id,
            action=action,
            is_due=is_due,
            has_active_session=has_active_session,
            attempt_result=attempt_result,
            fsrs_rating=fsrs_rating,
            explanation_ready=explanation_ready,
            coach_feedback_requested=coach_feedback_requested,
        )
    except Exception:
        return None
    run_result = review_result_to_run_result(result)
    if validate_run_result_for_boundary(
        run_result,
        allowed_intent_targets=REVIEW_GRAPH_ALLOWED_INTENT_TARGETS,
    ):
        return None
    return run_result


def _review_start_graph_facts(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    knowledge_point_id: str,
) -> dict[str, object] | None:
    state = conn.execute(
        """
        SELECT
          rs.plan_id::text AS plan_id,
          (
            rs.due_at IS NOT NULL
            AND rs.due_at <= now()
            AND rs.suspended_at IS NULL
            AND lp.status = 'active'
            AND lp.deleted_at IS NULL
          ) AS is_due
        FROM review_states rs
        JOIN learning_plans lp ON lp.id = rs.plan_id
        JOIN knowledge_points kp ON kp.id = rs.knowledge_point_id
        WHERE rs.user_id = %s
          AND rs.knowledge_point_id = %s
          AND kp.deleted_at IS NULL
        LIMIT 1
        """,
        (user_id, knowledge_point_id),
    ).fetchone()
    if state is None:
        return None
    session = conn.execute(
        """
        SELECT id::text AS id
        FROM learning_sessions
        WHERE user_id = %s
          AND plan_id = %s
          AND entry_point = %s
          AND session_type = 'review'
          AND status = 'active'
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (user_id, state["plan_id"], knowledge_point_id),
    ).fetchone()
    return {
        "is_due": bool(state["is_due"]),
        "has_active_session": session is not None,
        "session_id": str(session["id"]) if session is not None else "",
    }


def _review_session_graph_ids(
    conn: Connection[dict[str, object]],
    *,
    session_id: str,
    user_id: str | None = None,
) -> tuple[str, str] | None:
    row = conn.execute(
        """
        SELECT user_id::text AS user_id, entry_point::text AS knowledge_point_id
        FROM learning_sessions
        WHERE id = %s AND session_type = 'review'
        LIMIT 1
        """,
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    if user_id is not None and str(row["user_id"]) != user_id:
        raise EntityNotFoundError("SESSION_NOT_FOUND", "复习会话不存在")
    return str(row["user_id"]), str(row["knowledge_point_id"])


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
            graph_facts = _review_start_graph_facts(
                conn,
                user_id=payload.user_id,
                knowledge_point_id=payload.knowledge_point_id,
            )
            if graph_facts is not None:
                graph_action = _review_graph_decision(
                    session_id=str(graph_facts["session_id"]),
                    user_id=payload.user_id,
                    knowledge_point_id=payload.knowledge_point_id,
                    action="start",
                    is_due=bool(graph_facts["is_due"]),
                    has_active_session=bool(graph_facts["has_active_session"]),
                )
                if graph_action == "reject_not_due":
                    return error_response(
                        request,
                        code="REVIEW_NOT_DUE",
                        message="当前知识点未到复习时间",
                        status_code=status.HTTP_409_CONFLICT,
                        details={
                            "reason": "review is not due",
                            "knowledge_point_id": payload.knowledge_point_id,
                        },
                        recoverable=True,
                    )
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
        except ReviewSeedBankGenerationError:
            conn.commit()
            return error_response(
                request,
                code="REVIEW_SEED_BANK_GENERATION_FAILED",
                message="无法生成安全的复习材料，请稍后重试",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                details={"knowledge_point_id": payload.knowledge_point_id},
                recoverable=True,
            )
        conn.commit()
    return JSONResponse(
        status_code=status.HTTP_200_OK if reused else status.HTTP_201_CREATED,
        content=jsonable_encoder(response),
    )


@router.post("/{session_id}/warmup-result", response_model=None)
async def submit_review_warmup_result(
    session_id: str,
    request: Request,
) -> dict[str, object] | JSONResponse:
    body = await request.json()
    try:
        payload = ReviewWarmupResultRequest.model_validate(body)
    except ValueError as exc:
        return error_response(
            request,
            code="VALIDATION_ERROR",
            message="复习热身请求结构不合法",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"reason": str(exc)},
        )

    with connect() as conn:
        try:
            graph_ids = _review_session_graph_ids(conn, session_id=session_id, user_id=payload.user_id)
            if graph_ids is not None:
                graph_user_id, graph_knowledge_point_id = graph_ids
                _review_graph_decision(
                    session_id=session_id,
                    user_id=graph_user_id,
                    knowledge_point_id=graph_knowledge_point_id,
                    action="warmup",
                )
            response = record_review_warmup_result(
                conn,
                user_id=payload.user_id,
                session_id=session_id,
                action=payload.action,
                answer=payload.answer,
            )
        except EntityNotFoundError as exc:
            conn.rollback()
            return error_response(
                request,
                code=exc.code,
                message=exc.message,
                status_code=status.HTTP_404_NOT_FOUND,
                details={"session_id": session_id},
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
        conn.commit()
    return JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(response))


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
            graph_ids = _review_session_graph_ids(conn, session_id=session_id, user_id=payload.user_id)
            if graph_ids is not None:
                graph_user_id, graph_knowledge_point_id = graph_ids
                _review_graph_decision(
                    session_id=session_id,
                    user_id=graph_user_id,
                    knowledge_point_id=graph_knowledge_point_id,
                    action="submit",
                    explanation_ready=payload.explanation_check is not None,
                )
            response, replayed = submit_review_exercise_result(
                conn,
                user_id=payload.user_id,
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
                review_ai_patch_answer=payload.review_ai_patch or payload.review_ai_patch_answer,
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
        except InvalidReviewRequestError as exc:
            conn.rollback()
            return error_response(
                request,
                code="VALIDATION_ERROR",
                message="复习提交请求结构不合法",
                status_code=status.HTTP_400_BAD_REQUEST,
                details={"reason": str(exc)},
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
    user_id = str(body.get("user_id") or "") or None

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
            user_id=user_id,
            request_id=request_id,
        )
    )


async def _review_message_stream(
    request: Request,
    *,
    session_id: str,
    content: str,
    client_message_id: str,
    user_id: str | None,
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
                    user_id=user_id,
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
            _review_graph_decision(
                session_id=session_id,
                user_id=prepared.context.user_id,
                knowledge_point_id=prepared.context.knowledge_point_id,
                action="message",
                coach_feedback_requested=True,
            )
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
