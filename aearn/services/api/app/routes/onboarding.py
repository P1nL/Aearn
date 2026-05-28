import asyncio
import uuid
from collections.abc import AsyncGenerator, Iterable

from fastapi import APIRouter, Header, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.errors import error_response, request_id_from
from app.db.connection import connect
from app.services.onboarding_conversation import (
    OnboardingPlanDraftError,
    OnboardingSessionNotFoundError,
    build_plan_draft_from_slots,
    create_onboarding_session,
    detect_plan_proposal,
    extract_slots,
    learning_route_args_from_plan_draft,
    list_onboarding_messages,
    load_onboarding_context,
    load_stashed_plan_draft,
    persist_extracted_slots,
    prepare_onboarding_message,
    route_card_ready_generation,
    safe_generation_exceptions,
    stash_plan_draft,
    start_onboarding_generation,
    store_onboarding_agent_message,
    update_onboarding_status,
)
from app.services.llm_client import LLMCallError, LLMConfigurationError, LLMInvalidResponseError
from app.services.plan_repository import (
    EntityNotFoundError,
    IdempotencyConflictError,
    PlanDraftError,
    confirm_plan,
    default_confirm_key,
    request_hash,
)
from app.services.sse import SSEWriter, chunk_tool_call_arguments, stream_response


router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


@router.post("/messages", response_model=None)
async def create_onboarding_message(
    request: Request,
) -> StreamingResponse:
    request_id = request_id_from(request)
    body = await request.json()

    user_id = str(body.get("user_id") or "")
    content = str(body.get("content") or "")
    client_message_id = str(body.get("client_message_id") or "")
    onboarding_session_id = body.get("onboarding_session_id")

    if not user_id or not content or not client_message_id:
        return stream_response(
            _error_stream(
                code="VALIDATION_ERROR",
                message="建档对话请求缺少必要字段（user_id, content, client_message_id）",
                request_id=request_id,
            )
        )

    return stream_response(
        _onboarding_message_stream(
            request,
            user_id=user_id,
            content=content,
            client_message_id=client_message_id,
            onboarding_session_id=str(onboarding_session_id) if onboarding_session_id else None,
            request_id=request_id,
        )
    )


@router.get("/sessions/{session_id}/messages", response_model=None)
def read_onboarding_messages(
    session_id: str, request: Request
) -> dict[str, object] | JSONResponse:
    """Return persisted onboarding messages so session resume can rehydrate cards."""
    with connect() as conn:
        try:
            rows = list_onboarding_messages(conn, conversation_id=session_id)
        except OnboardingSessionNotFoundError as exc:
            return error_response(
                request,
                code=exc.code,
                message=exc.message,
                status_code=404,
                details={"onboarding_session_id": session_id},
            )
    return {
        "onboarding_session_id": session_id,
        "messages": rows,
    }


@router.post(
    "/{conversation_id}/confirm_plan",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
)
async def confirm_onboarding_plan(
    conversation_id: str,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, object] | JSONResponse:
    """Persist the stashed PlanDraft for the given onboarding conversation."""

    body = await request.json()
    user_id = str(body.get("user_id") or "")
    if not user_id:
        return error_response(
            request,
            code="VALIDATION_ERROR",
            message="缺少 user_id",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"conversation_id": conversation_id},
        )

    with connect() as conn:
        try:
            context = load_onboarding_context(
                conn, conversation_id=conversation_id, user_id=user_id
            )
        except OnboardingSessionNotFoundError as exc:
            return error_response(
                request,
                code=exc.code,
                message=exc.message,
                status_code=status.HTTP_404_NOT_FOUND,
                details={"conversation_id": conversation_id},
            )

        if context.user_id != user_id:
            return error_response(
                request,
                code="USER_MISMATCH",
                message="该建档会话不属于当前用户",
                status_code=status.HTTP_403_FORBIDDEN,
                details={"conversation_id": conversation_id},
            )

        plan_draft = load_stashed_plan_draft(conn, conversation_id=conversation_id)
        if plan_draft is None:
            return error_response(
                request,
                code="PLAN_DRAFT_NOT_READY",
                message="计划草稿尚未生成，请先完成对话流程",
                status_code=status.HTTP_404_NOT_FOUND,
                details={"conversation_id": conversation_id},
            )

        # Make sure the stashed draft belongs to the requesting user; rebuild
        # under the right user_id if not, so confirm_plan accepts it.
        if plan_draft.user_id != user_id:
            plan_draft = plan_draft.model_copy(update={"user_id": user_id})

        key = idempotency_key or default_confirm_key(user_id, plan_draft.draft_id)
        body_hash = request_hash(
            {"user_id": user_id, "plan_draft": plan_draft.model_dump(mode="json")}
        )
        try:
            response, replayed = confirm_plan(
                conn,
                user_id=user_id,
                plan_draft=plan_draft,
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
                details={"user_id": user_id},
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

        update_onboarding_status(
            conn, conversation_id=conversation_id, status="confirmed"
        )
        conn.commit()

    if replayed:
        response["idempotency_replayed"] = True
    return response


async def _onboarding_message_stream(
    request: Request,
    *,
    user_id: str,
    content: str,
    client_message_id: str,
    onboarding_session_id: str | None,
    request_id: str,
) -> AsyncGenerator[str, None]:
    writer = SSEWriter()
    try:
        with connect() as conn:
            # Create session if needed
            if onboarding_session_id is None:
                onboarding_session_id = create_onboarding_session(conn, user_id=user_id)
                conn.commit()
                yield writer.event(
                    "session_created",
                    {
                        "request_id": request_id,
                        "onboarding_session_id": onboarding_session_id,
                    },
                )

            try:
                prepared = prepare_onboarding_message(
                    conn,
                    conversation_id=onboarding_session_id,
                    user_id=user_id,
                    content=content,
                    client_message_id=client_message_id,
                )
            except OnboardingSessionNotFoundError as exc:
                conn.rollback()
                yield writer.error(
                    code=exc.code,
                    message=exc.message,
                    request_id=request_id,
                    details={"onboarding_session_id": onboarding_session_id},
                )
                return
            conn.commit()

        # Idempotency replay
        if prepared.stored_content is not None:
            yield writer.event(
                "agent_message",
                _agent_message_event(
                    request_id=request_id,
                    session_id=prepared.conversation_id,
                    message_id=prepared.message_id,
                    delta=prepared.stored_content,
                    content=prepared.stored_content,
                ),
            )
            for stored_tool_call in prepared.stored_tool_calls:
                tool_call_id = stored_tool_call.get("id")
                name = stored_tool_call.get("name")
                arguments = stored_tool_call.get("args")
                if (
                    isinstance(tool_call_id, str)
                    and isinstance(name, str)
                    and isinstance(arguments, dict)
                ):
                    async for tool_event in _tool_call_events(
                        writer,
                        tool_call_id=tool_call_id,
                        name=name,
                        arguments=arguments,
                    ):
                        yield tool_event
            yield writer.event(
                "done",
                {
                    "request_id": request_id,
                    "session_id": prepared.conversation_id,
                    "message_id": prepared.message_id,
                    "generation_source": "replay",
                    "generation_model": "",
                    "result_ref": {"type": "OnboardingMessage", "id": prepared.message_id},
                },
            )
            return

        # Extract slots before generating user-visible text. If this turn is
        # route-ready, the visible route must come from the tool call card.
        with connect() as conn_refresh:
            refreshed = load_onboarding_context(
                conn_refresh, conversation_id=prepared.conversation_id, user_id=user_id
            )

        try:
            slots = await asyncio.to_thread(extract_slots, refreshed)
        except (LLMCallError, LLMConfigurationError, LLMInvalidResponseError):
            yield _model_unavailable_error(
                writer,
                request_id=request_id,
                conversation_id=prepared.conversation_id,
            )
            return

        with connect() as conn_persist:
            persist_extracted_slots(
                conn_persist,
                conversation_id=prepared.conversation_id,
                slots=slots,
            )
            conn_persist.commit()

        # Reload so detect_plan_proposal sees the freshly persisted slots
        # alongside any previously stashed plan_draft.
        with connect() as conn_reload:
            refreshed = load_onboarding_context(
                conn_reload, conversation_id=prepared.conversation_id, user_id=user_id
            )

        tool_calls_for_metadata: list[dict[str, object]] = []
        plan_error_payload: dict[str, str] | None = None
        learning_route_args: dict[str, object] | None = None
        route_tool_call_id: str | None = None
        if detect_plan_proposal(refreshed, slots):
            try:
                with connect() as conn_plan:
                    plan_draft = build_plan_draft_from_slots(
                        conn_plan, slots=slots, user_id=user_id
                    )
                    stash_plan_draft(
                        conn_plan,
                        conversation_id=prepared.conversation_id,
                        plan_draft=plan_draft,
                        slots=slots,
                    )
                    conn_plan.commit()
            except OnboardingPlanDraftError as exc:
                plan_error_payload = {"code": exc.code, "message": exc.message}
            except Exception as exc:  # noqa: BLE001 - never crash the stream
                plan_error_payload = {
                    "code": "PLAN_DRAFT_INVALID",
                    "message": f"无法生成计划草稿：{exc}",
                }
            else:
                learning_route_args = learning_route_args_from_plan_draft(
                    plan_draft,
                    slots=slots,
                )
                route_tool_call_id = f"tc_{uuid.uuid4().hex[:12]}"

        if plan_error_payload is not None:
            yield writer.error(
                code=plan_error_payload["code"],
                message=plan_error_payload["message"],
                request_id=request_id,
                details={"onboarding_session_id": prepared.conversation_id},
                recoverable=True,
            )
            return

        try:
            generation = (
                route_card_ready_generation()
                if learning_route_args is not None
                else start_onboarding_generation(refreshed, user_content=content)
            )
        except (LLMCallError, LLMConfigurationError, LLMInvalidResponseError):
            yield _model_unavailable_error(
                writer,
                request_id=request_id,
                conversation_id=prepared.conversation_id,
            )
            return
        full_text = ""
        generation_source = generation.generation_source
        generation_model = generation.generation_model

        try:
            async for delta in _iter_generation_chunks(request, generation.chunks):
                full_text += delta
                yield writer.event(
                    "agent_message",
                    _agent_message_event(
                        request_id=request_id,
                        session_id=prepared.conversation_id,
                        message_id=prepared.message_id,
                        delta=delta,
                        content=full_text,
                    ),
                )
        except safe_generation_exceptions():
            if full_text:
                yield writer.error(
                    code="GENERATION_INTERRUPTED",
                    message="建档对话流式响应中断，请重试",
                    request_id=request_id,
                    recoverable=True,
                )
                return
            yield _model_unavailable_error(
                writer,
                request_id=request_id,
                conversation_id=prepared.conversation_id,
            )
            return

        if not full_text.strip():
            yield _model_unavailable_error(
                writer,
                request_id=request_id,
                conversation_id=prepared.conversation_id,
            )
            return

        if learning_route_args is not None and route_tool_call_id is not None:
            async for tool_event in _tool_call_events(
                writer,
                tool_call_id=route_tool_call_id,
                name="show_learning_route",
                arguments=learning_route_args,
            ):
                yield tool_event
            tool_calls_for_metadata.append(
                {
                    "id": route_tool_call_id,
                    "name": "show_learning_route",
                    "args": learning_route_args,
                    "status": "done",
                }
            )

        # Persist agent message (and any resolved tool calls in metadata)
        with connect() as conn:
            store_onboarding_agent_message(
                conn,
                conversation_id=prepared.conversation_id,
                content=full_text.strip(),
                metadata={"tool_calls": tool_calls_for_metadata}
                if tool_calls_for_metadata
                else None,
            )
            conn.commit()

        yield writer.event(
            "done",
            {
                "request_id": request_id,
                "session_id": prepared.conversation_id,
                "message_id": prepared.message_id,
                "generation_source": generation_source,
                "generation_model": generation_model,
                "result_ref": {"type": "OnboardingMessage", "id": prepared.message_id},
            },
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        yield writer.error(
            code="INTERNAL_ERROR",
            message="建档对话流式响应失败",
            request_id=request_id,
            recoverable=True,
        )


async def _tool_call_events(
    writer: SSEWriter,
    *,
    tool_call_id: str,
    name: str,
    arguments: dict[str, object],
) -> AsyncGenerator[str, None]:
    yield writer.tool_call_start(tool_call_id=tool_call_id, name=name)
    for chunk in chunk_tool_call_arguments(arguments):
        yield writer.tool_call_delta(tool_call_id=tool_call_id, arguments_delta=chunk)
        await asyncio.sleep(0)
    yield writer.tool_call_done(tool_call_id=tool_call_id, arguments=arguments)


def _model_unavailable_error(
    writer: SSEWriter,
    *,
    request_id: str,
    conversation_id: str,
) -> str:
    return writer.error(
        code="MODEL_UNAVAILABLE",
        message="模型服务暂时不可用，请检查模型配置或稍后重试。",
        request_id=request_id,
        details={"onboarding_session_id": conversation_id},
        recoverable=True,
    )


async def _error_stream(
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


async def _iter_generation_chunks(request: Request, chunks: Iterable[str]) -> AsyncGenerator[str, None]:
    for delta in chunks:
        if await request.is_disconnected():
            return
        if not delta:
            continue
        yield delta
        await asyncio.sleep(0)


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
    }
