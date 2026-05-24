import asyncio
from collections.abc import AsyncGenerator, Iterable

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.core.errors import request_id_from
from app.db.connection import connect
from app.services.onboarding_conversation import (
    OnboardingSessionNotFoundError,
    create_onboarding_session,
    deterministic_onboarding_generation,
    prepare_onboarding_message,
    safe_generation_exceptions,
    start_onboarding_generation,
    store_onboarding_agent_message,
)
from app.services.sse import SSEWriter, stream_response, wants_stream


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

        # Generate response
        generation = start_onboarding_generation(prepared.context, user_content=content)
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
            fallback = deterministic_onboarding_generation(prepared.context, user_content=content)
            generation_source = fallback.generation_source
            generation_model = fallback.generation_model
            async for delta in _iter_generation_chunks(request, fallback.chunks):
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

        if not full_text.strip():
            fallback = deterministic_onboarding_generation(prepared.context, user_content=content)
            generation_source = fallback.generation_source
            generation_model = fallback.generation_model
            async for delta in _iter_generation_chunks(request, fallback.chunks):
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

        # Persist agent message
        with connect() as conn:
            store_onboarding_agent_message(
                conn,
                conversation_id=prepared.conversation_id,
                content=full_text.strip(),
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
