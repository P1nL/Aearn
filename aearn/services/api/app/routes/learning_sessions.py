import asyncio
from collections.abc import AsyncGenerator, Iterable, Mapping
from typing import Any

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
from app.agents.guardrails import assert_safe_teaching_output
from app.models.learning_sessions import (
    CheckExplanationRequest,
    ExplainErrorRequest,
    HintRequest,
    LearningMessageRequest,
    RunExerciseRequest,
    StartLearningSessionRequest,
    SubmitExerciseRequest,
)
from app.services.learning_conversation import (
    build_learning_agent_tool_runtime,
    build_learning_message_response,
    create_learning_message_response,
    deterministic_learning_message_text,
    list_learning_history,
    prepare_learning_message,
    prepare_learning_message_for_generation,
    precompute_learning_message_transition,
    safe_generation_exceptions,
    start_learning_message_generation,
    store_learning_message_response,
)
from app.services.graph_event_stream import build_learning_graph_stream_events
from app.services.learning_session_repository import (
    ConceptIntroGenerationError,
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
from app.services.llm_client import LLMCallError, LLMConfigurationError, LLMInvalidResponseError
from app.services.dashboard_repository import (
    EntityNotFoundError as ResumeEntityNotFoundError,
    get_resume_context,
)
from app.services.plan_repository import IdempotencyConflictError
from app.services.sse import SSEWriter, chunk_tool_call_arguments, stream_response, wants_stream


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
        except ConceptIntroGenerationError:
            conn.rollback()
            return error_response(
                request,
                code="CONCEPT_INTRO_GENERATION_FAILED",
                message="概念开场生成失败，请重试当前知识点。",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                details={"reason": "concept_intro_generation_failed"},
                recoverable=True,
            )
        conn.commit()
    return JSONResponse(
        status_code=status.HTTP_200_OK if reused else status.HTTP_201_CREATED,
        content=jsonable_encoder(response),
    )


@router.get("/history", response_model=None)
def read_learning_history(
    request: Request,
    user_id: str = Query(min_length=1),
    knowledge_point_id: str = Query(min_length=1),
    active_session_id: str | None = Query(default=None),
) -> dict[str, object] | JSONResponse:
    with connect() as conn:
        try:
            response = list_learning_history(
                conn,
                user_id=user_id,
                knowledge_point_id=knowledge_point_id,
                active_session_id=active_session_id,
            )
        except EntityNotFoundError as exc:
            return error_response(
                request,
                code=exc.code,
                message=exc.message,
                status_code=status.HTTP_404_NOT_FOUND,
                details={"user_id": user_id, "knowledge_point_id": knowledge_point_id},
            )
    return JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(response))


@router.post("/{session_id}/messages", response_model=None)
async def create_learning_session_message(
    session_id: str,
    request: Request,
) -> dict[str, object] | JSONResponse | StreamingResponse:
    request_id = request_id_from(request)
    body = await request.json()
    try:
        payload = LearningMessageRequest.model_validate(body)
    except ValueError as exc:
        if wants_stream(request):
            return stream_response(
                _error_stream(
                    code="VALIDATION_ERROR",
                    message="学习对话请求结构不合法",
                    request_id=request_id,
                    details={"reason": str(exc)},
                )
            )
        return error_response(
            request,
            code="VALIDATION_ERROR",
            message="学习对话请求结构不合法",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"reason": str(exc)},
        )

    if wants_stream(request):
        return stream_response(
            _learning_message_stream(
                request,
                session_id=session_id,
                payload=payload,
                request_body=body,
                request_id=request_id,
            )
        )

    with connect() as conn:
        try:
            response, replayed = create_learning_message_response(
                conn,
                user_id=payload.user_id,
                session_id=session_id,
                content=payload.content,
                client_message_id=payload.client_message_id,
                request_body=body,
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
        except IdempotencyConflictError as exc:
            conn.rollback()
            return error_response(
                request,
                code="IDEMPOTENCY_CONFLICT",
                message="同一学习对话幂等键对应不同请求体",
                status_code=status.HTTP_409_CONFLICT,
                details={"reason": str(exc)},
                recoverable=False,
            )
        except safe_generation_exceptions() as exc:
            conn.rollback()
            return model_unavailable_response(
                request,
                details={"reason": exc.__class__.__name__},
            )
        conn.commit()
    if replayed:
        response["idempotency_replayed"] = True
    return JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(response))


@router.post("/{session_id}/exercises/{exercise_id}/run", response_model=None)
async def run_learning_session(
    session_id: str,
    exercise_id: str,
    request: Request,
) -> dict[str, object] | JSONResponse | StreamingResponse:
    request_id = request_id_from(request)
    body = await request.json()
    try:
        payload = RunExerciseRequest.model_validate(body)
    except ValueError as exc:
        if wants_stream(request):
            return stream_response(
                _error_stream(
                    code="VALIDATION_ERROR",
                    message="运行请求结构不合法",
                    request_id=request_id,
                    details={"reason": str(exc)},
                )
            )
        return error_response(
            request,
            code="VALIDATION_ERROR",
            message="运行请求结构不合法",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"reason": str(exc)},
        )

    if wants_stream(request):
        return stream_response(
            _run_learning_session_stream(
                request,
                session_id=session_id,
                exercise_id=exercise_id,
                payload=payload,
                request_body=body,
                request_id=request_id,
            )
        )

    with connect() as conn:
        try:
            response, replayed = run_learning_session_exercise(
                conn,
                user_id=payload.user_id,
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
        except (LLMCallError, LLMConfigurationError, LLMInvalidResponseError) as exc:
            conn.rollback()
            return model_unavailable_response(
                request,
                details={"reason": exc.__class__.__name__},
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
                user_id=payload.user_id,
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
        except (LLMCallError, LLMConfigurationError, LLMInvalidResponseError) as exc:
            conn.rollback()
            return model_unavailable_response(
                request,
                details={"reason": exc.__class__.__name__},
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
                user_id=payload.user_id,
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
        except (LLMCallError, LLMConfigurationError, LLMInvalidResponseError) as exc:
            conn.rollback()
            return model_unavailable_response(
                request,
                details={"reason": exc.__class__.__name__},
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
                user_id=payload.user_id,
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
        except (LLMCallError, LLMConfigurationError, LLMInvalidResponseError) as exc:
            conn.rollback()
            return model_unavailable_response(
                request,
                details={"reason": exc.__class__.__name__},
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
) -> dict[str, object] | JSONResponse | StreamingResponse:
    request_id = request_id_from(request)
    body = await request.json()
    try:
        payload = SubmitExerciseRequest.model_validate(body)
    except ValueError as exc:
        if wants_stream(request):
            return stream_response(
                _error_stream(
                    code="VALIDATION_ERROR",
                    message="提交请求结构不合法",
                    request_id=request_id,
                    details={"reason": str(exc)},
                )
            )
        return error_response(
            request,
            code="VALIDATION_ERROR",
            message="提交请求结构不合法",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"reason": str(exc)},
        )

    if wants_stream(request):
        return stream_response(
            _submit_learning_session_stream(
                request,
                session_id=session_id,
                exercise_id=exercise_id,
                payload=payload,
                request_body=body,
                request_id=request_id,
            )
        )

    with connect() as conn:
        try:
            response, replayed = submit_learning_session_exercise(
                conn,
                user_id=payload.user_id,
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


async def _error_stream(
    *,
    code: str,
    message: str,
    request_id: str,
    details: dict[str, object] | None = None,
    recoverable: bool = True,
) -> AsyncGenerator[str, None]:
    yield SSEWriter().error(
        code=code,
        message=message,
        request_id=request_id,
        details=details,
        recoverable=recoverable,
    )


async def _learning_message_stream(
    request: Request,
    *,
    session_id: str,
    payload: LearningMessageRequest,
    request_body: Mapping[str, object],
    request_id: str,
) -> AsyncGenerator[str, None]:
    writer = SSEWriter()
    try:
        with connect() as conn:
            try:
                prepared = prepare_learning_message(
                    conn,
                    user_id=payload.user_id,
                    session_id=session_id,
                    content=payload.content,
                    client_message_id=payload.client_message_id,
                    request_body=request_body,
                )
            except EntityNotFoundError as exc:
                conn.rollback()
                yield writer.error(
                    code=exc.code,
                    message=exc.message,
                    request_id=request_id,
                    details={"session_id": session_id},
                )
                return
            except IdempotencyConflictError as exc:
                conn.rollback()
                yield writer.error(
                    code="IDEMPOTENCY_CONFLICT",
                    message="同一学习对话幂等键对应不同请求体",
                    request_id=request_id,
                    details={"reason": str(exc)},
                    recoverable=False,
                )
                return
            conn.commit()

        if prepared.stored_response is not None:
            stored_message = prepared.stored_response.get("agent_message", {})
            if not isinstance(stored_message, Mapping):
                yield writer.error(
                    code="INTERNAL_ERROR",
                    message="学习对话回放数据不可用",
                    request_id=request_id,
                    recoverable=True,
                )
                return
            stored_content = str(stored_message.get("content") or "")
            yield writer.event(
                "agent_message",
                _agent_message_event(
                    request_id=request_id,
                    session_id=session_id,
                    message_id=prepared.message_id,
                    delta=stored_content,
                    content=stored_content,
                ),
            )
            async for frame in _tool_call_events(writer, prepared.stored_response.get("tool_calls")):
                yield frame
            yield _learning_message_done_event(
                writer,
                request_id=request_id,
                session_id=session_id,
                message_id=prepared.message_id,
                generation_source=str(prepared.stored_response.get("generation_source") or "llm"),
                generation_model=str(prepared.stored_response.get("generation_model") or ""),
            )
            return

        with connect() as conn:
            prepared = prepare_learning_message_for_generation(
                conn,
                prepared,
                user_content=payload.content,
            )
            conn.commit()

        if prepared.context.graph_memory_snapshot or "langgraph_runtime" in prepared.context.conversation_context:
            for event in build_learning_graph_stream_events(
                request_id=request_id,
                session_id=session_id,
                conversation_context=prepared.context.conversation_context,
                graph_memory_snapshot=prepared.context.graph_memory_snapshot,
                rag_context=prepared.context.rag_context,
            ):
                yield writer.event(event.event_type, dict(event.payload))

        full_text = ""
        try:
            prepared = precompute_learning_message_transition(prepared)
            side_effects, tool_context = build_learning_agent_tool_runtime(prepared.context)
            deterministic = deterministic_learning_message_text(prepared)
            if deterministic is None:
                generation = start_learning_message_generation(
                    prepared.context,
                    user_content=payload.content,
                    side_effects=side_effects,
                    tool_context=tool_context,
                )
                generation_source = generation.generation_source
                generation_model = generation.generation_model
                chunks = _iter_generation_chunks(request, generation.chunks)
            else:
                full_text, generation_source, generation_model = deterministic
                chunks = _iter_generation_chunks(request, [full_text])
            async for delta in chunks:
                candidate_text = full_text + delta if deterministic is None else delta
                assert_safe_teaching_output(candidate_text)
                full_text = candidate_text
                yield writer.event(
                    "agent_message",
                    _agent_message_event(
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
                next_action="retry_same",
            )
            return

        if not full_text.strip():
            yield writer.error(
                code="MODEL_UNAVAILABLE",
                message=MODEL_UNAVAILABLE_MESSAGE,
                request_id=request_id,
                details={"reason": "empty_model_output"},
                recoverable=True,
                next_action="retry_same",
            )
            return

        with connect() as conn:
            response = build_learning_message_response(
                prepared,
                content=full_text.strip(),
                generation_source=generation_source,
                generation_model=generation_model,
            )
            response = store_learning_message_response(conn, prepared, response, side_effects=side_effects)
            conn.commit()

        async for frame in _tool_call_events(writer, response.get("tool_calls")):
            yield frame
        yield _learning_message_done_event(
            writer,
            request_id=request_id,
            session_id=session_id,
            message_id=prepared.message_id,
            generation_source=generation_source,
            generation_model=generation_model,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        yield writer.error(
            code="INTERNAL_ERROR",
            message="学习对话流式响应失败",
            request_id=request_id,
            recoverable=True,
        )


async def _iter_generation_chunks(request: Request, chunks: Iterable[str]) -> AsyncGenerator[str, None]:
    for delta in chunks:
        if await request.is_disconnected():
            return
        if not delta:
            continue
        yield delta
        await asyncio.sleep(0)


async def _tool_call_events(writer: SSEWriter, tool_calls: object) -> AsyncGenerator[str, None]:
    if not isinstance(tool_calls, list):
        return
    for tool_call in tool_calls:
        if not isinstance(tool_call, Mapping):
            continue
        tool_call_id = str(tool_call.get("id") or "")
        tool_name = str(tool_call.get("name") or "")
        args = tool_call.get("args")
        if not tool_call_id or not tool_name or not isinstance(args, Mapping):
            continue
        yield writer.tool_call_start(tool_call_id=tool_call_id, name=tool_name)
        for chunk in chunk_tool_call_arguments(dict(args)):
            yield writer.tool_call_delta(tool_call_id=tool_call_id, arguments_delta=chunk)
            await asyncio.sleep(0)
        yield writer.tool_call_done(tool_call_id=tool_call_id, arguments=dict(args))


def _agent_message_event(
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
        "next_action": "retry_same",
    }


def _learning_message_done_event(
    writer: SSEWriter,
    *,
    request_id: str,
    session_id: str,
    message_id: str,
    generation_source: str,
    generation_model: str,
) -> str:
    return writer.event(
        "done",
        {
            "request_id": request_id,
            "session_id": session_id,
            "message_id": message_id,
            "generation_source": generation_source,
            "generation_model": generation_model,
            "result_ref": {
                "type": "LearningConversationMessage",
                "id": message_id,
            },
        },
    )


async def _run_learning_session_stream(
    request: Request,
    *,
    session_id: str,
    exercise_id: str,
    payload: RunExerciseRequest,
    request_body: Mapping[str, object],
    request_id: str,
) -> AsyncGenerator[str, None]:
    writer = SSEWriter()
    try:
        yield writer.event(
            "tool_status",
            {
                "request_id": request_id,
                "session_id": session_id,
                "node": "run_exercise",
                "tool": "runner_service",
                "status": "running",
                "message": "正在执行代码运行请求",
            },
        )
        if await request.is_disconnected():
            return

        with connect() as conn:
            try:
                response, replayed = run_learning_session_exercise(
                    conn,
                    user_id=payload.user_id,
                    session_id=session_id,
                    exercise_id=exercise_id,
                    code=payload.code,
                    filled_blanks=payload.filled_blanks,
                    run_mode=payload.run_mode,
                    runtime_profile_id=payload.runtime_profile_id,
                    provided_code_hash=payload.code_hash,
                    request_id=request_id,
                    request_body=request_body,
                )
            except EntityNotFoundError as exc:
                conn.rollback()
                yield writer.error(
                    code=exc.code,
                    message=exc.message,
                    request_id=request_id,
                    details={"session_id": session_id, "exercise_id": exercise_id},
                )
                return
            except SessionStateConflictError as exc:
                conn.rollback()
                yield writer.error(
                    code="ATTEMPT_STATE_CONFLICT",
                    message="当前会话状态不允许运行该练习",
                    request_id=request_id,
                    details={"reason": str(exc)},
                    recoverable=False,
                )
                return
            except IdempotencyConflictError as exc:
                conn.rollback()
                yield writer.error(
                    code="IDEMPOTENCY_CONFLICT",
                    message="同一运行幂等键对应不同请求体",
                    request_id=request_id,
                    details={"reason": str(exc)},
                    recoverable=False,
                )
                return
            conn.commit()

        if replayed:
            response["idempotency_replayed"] = True
        yield writer.event("runner_result", _runner_result_from_response(response, request_id, session_id))
        yield writer.done(
            request_id=request_id,
            session_id=session_id,
            result_ref={"type": "Attempt", "id": response["attempt_id"]},
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        yield writer.error(
            code="INTERNAL_ERROR",
            message="运行流式响应失败",
            request_id=request_id,
            recoverable=True,
        )


async def _submit_learning_session_stream(
    request: Request,
    *,
    session_id: str,
    exercise_id: str,
    payload: SubmitExerciseRequest,
    request_body: Mapping[str, object],
    request_id: str,
) -> AsyncGenerator[str, None]:
    writer = SSEWriter()
    try:
        yield writer.event(
            "tool_status",
            {
                "request_id": request_id,
                "session_id": session_id,
                "node": "submit_pipeline",
                "tool": "submit_exercise",
                "status": "running",
                "message": "正在提交并评分",
            },
        )
        if await request.is_disconnected():
            return

        with connect() as conn:
            try:
                response, replayed = submit_learning_session_exercise(
                    conn,
                    user_id=payload.user_id,
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
                    request_id=request_id,
                    request_body=request_body,
                )
                runner_result = _load_attempt_runner_result(
                    conn,
                    attempt_id=str(response["attempt_id"]),
                    request_id=request_id,
                    session_id=session_id,
                    next_action=str(response["next_action"]),
                )
            except EntityNotFoundError as exc:
                conn.rollback()
                yield writer.error(
                    code=exc.code,
                    message=exc.message,
                    request_id=request_id,
                    details={"session_id": session_id, "exercise_id": exercise_id, "attempt_id": payload.attempt_id},
                )
                return
            except SessionStateConflictError as exc:
                conn.rollback()
                yield writer.error(
                    code="ATTEMPT_STATE_CONFLICT",
                    message="当前尝试不允许提交评分",
                    request_id=request_id,
                    details={"reason": str(exc)},
                    recoverable=False,
                )
                return
            except IdempotencyConflictError as exc:
                conn.rollback()
                yield writer.error(
                    code="IDEMPOTENCY_CONFLICT",
                    message="同一提交幂等键对应不同请求体",
                    request_id=request_id,
                    details={"reason": str(exc)},
                    recoverable=False,
                )
                return
            conn.commit()

        if replayed:
            response["idempotency_replayed"] = True
        yield writer.event("runner_result", runner_result)
        yield writer.event(
            "evaluation_result",
            {
                "request_id": request_id,
                "session_id": session_id,
                "attempt_id": response["attempt_id"],
                "code_completion_result": response["code_completion_result"],
            },
        )
        yield writer.done(
            request_id=request_id,
            session_id=session_id,
            result_ref={"type": "Attempt", "id": response["attempt_id"]},
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        yield writer.error(
            code="INTERNAL_ERROR",
            message="提交流式响应失败",
            request_id=request_id,
            recoverable=True,
        )


def _runner_result_from_response(
    response: Mapping[str, Any],
    request_id: str,
    session_id: str,
) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "session_id": session_id,
        "attempt_id": response["attempt_id"],
        "runtime_status": response["runtime_status"],
        "preview_url": response.get("preview_url") or response.get("preview_html"),
        "stdout": response.get("stdout") or "",
        "stderr": response.get("stderr") or "",
        "test_pass_rate": response.get("test_pass_rate") or 0,
        "test_results": response.get("test_results") or [],
        "next_action": response.get("next_action") or "retry_same",
    }


def _load_attempt_runner_result(
    conn: Any,
    *,
    attempt_id: str,
    request_id: str,
    session_id: str,
    next_action: str,
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT id, runtime_status, stdout, stderr, test_pass_rate, test_results_json
        FROM attempts
        WHERE id = %s
        LIMIT 1
        """,
        (attempt_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError("submit attempt could not be reloaded for SSE runner_result")
    test_results = row.get("test_results_json") or []
    if not isinstance(test_results, list):
        test_results = []
    return {
        "request_id": request_id,
        "session_id": session_id,
        "attempt_id": str(row["id"]),
        "runtime_status": row["runtime_status"],
        "preview_url": None,
        "stdout": row.get("stdout") or "",
        "stderr": row.get("stderr") or "",
        "test_pass_rate": row.get("test_pass_rate") or 0,
        "test_results": test_results,
        "next_action": next_action,
    }
