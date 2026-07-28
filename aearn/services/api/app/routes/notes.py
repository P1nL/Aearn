import asyncio
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.errors import MODEL_UNAVAILABLE_MESSAGE, error_response, model_unavailable_response, request_id_from
from app.db.connection import connect
from app.models.notes import AgentDraftRequest, CreateNoteRequest, UpdateNoteRequest
from app.services.repositories.note_repository import (
    EntityNotFoundError,
    create_note,
    generate_agent_draft_stream,
    list_notes,
    load_note_for_agent_draft,
    update_agent_draft,
    update_agent_draft_content,
    update_note,
)
from app.services.llm.llm_client import LLMCallError, LLMConfigurationError, LLMInvalidResponseError
from app.services.streaming.sse import SSEWriter, stream_response, wants_stream
from app.services.tutor.cutover import require_legacy_runtime


router = APIRouter(prefix="/api/notes", tags=["notes"], dependencies=[Depends(require_legacy_runtime)])


@router.get("", response_model=None)
def get_notes(
    request: Request,
    user_id: str = Query(min_length=1),
    knowledge_point_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, object] | JSONResponse:
    with connect() as conn:
        try:
            response = list_notes(
                conn,
                user_id=user_id,
                knowledge_point_id=knowledge_point_id,
                limit=limit,
            )
        except EntityNotFoundError as exc:
            return error_response(
                request,
                code=exc.code,
                message=exc.message,
                status_code=status.HTTP_404_NOT_FOUND,
                details={
                    "user_id": user_id,
                    "knowledge_point_id": knowledge_point_id,
                },
            )
    return JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(response))


@router.post("", response_model=None)
def post_note(
    payload: CreateNoteRequest,
    request: Request,
) -> dict[str, object] | JSONResponse:
    with connect() as conn:
        try:
            note, reused = create_note(
                conn,
                user_id=payload.user_id,
                knowledge_point_id=payload.knowledge_point_id,
                title=payload.title,
                content_markdown=payload.content_markdown,
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
                    "knowledge_point_id": payload.knowledge_point_id,
                },
            )
        conn.commit()
    return JSONResponse(
        status_code=status.HTTP_200_OK if reused else status.HTTP_201_CREATED,
        content=jsonable_encoder({"note": note}),
    )


@router.patch("/{note_id}", response_model=None)
def patch_note(
    note_id: str,
    payload: UpdateNoteRequest,
    request: Request,
) -> dict[str, object] | JSONResponse:
    with connect() as conn:
        try:
            note = update_note(
                conn,
                note_id=note_id,
                user_id=payload.user_id,
                title=payload.title,
                content_markdown=payload.content_markdown,
                is_user_edited=payload.is_user_edited,
            )
        except EntityNotFoundError as exc:
            conn.rollback()
            return error_response(
                request,
                code=exc.code,
                message=exc.message,
                status_code=status.HTTP_404_NOT_FOUND,
                details={"note_id": note_id},
            )
        conn.commit()
    return JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder({"note": note}))


@router.post("/{note_id}/agent-draft", response_model=None)
def post_note_agent_draft(
    note_id: str,
    payload: AgentDraftRequest,
    request: Request,
) -> dict[str, object] | JSONResponse | StreamingResponse:
    if wants_stream(request):
        return stream_response(
            _agent_draft_stream(
                note_id=note_id,
                payload=payload,
                request_id=request_id_from(request),
            )
        )

    with connect() as conn:
        try:
            note = update_agent_draft(
                conn,
                note_id=note_id,
                user_id=payload.user_id,
                style=payload.style,
                focus=payload.focus,
                session_id=payload.source.session_id if payload.source is not None else None,
                attempt_id=payload.source.attempt_id if payload.source is not None else None,
            )
        except EntityNotFoundError as exc:
            conn.rollback()
            return error_response(
                request,
                code=exc.code,
                message=exc.message,
                status_code=status.HTTP_404_NOT_FOUND,
                details={"note_id": note_id, "user_id": payload.user_id},
            )
        except (LLMCallError, LLMConfigurationError, LLMInvalidResponseError) as exc:
            conn.rollback()
            return model_unavailable_response(
                request,
                details={"reason": exc.__class__.__name__},
            )
        conn.commit()
    return JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder({"note": note}))


async def _agent_draft_stream(
    *,
    note_id: str,
    payload: AgentDraftRequest,
    request_id: str,
) -> AsyncGenerator[str, None]:
    writer = SSEWriter()
    session_id = payload.source.session_id if payload.source is not None and payload.source.session_id else ""
    attempt_id = payload.source.attempt_id if payload.source is not None else None
    try:
        yield writer.event(
            "tool_status",
            {
                "request_id": request_id,
                "session_id": session_id,
                "node": "note_agent_draft",
                "tool": "llm_generate",
                "status": "running",
                "message": "Agent 正在生成笔记补全",
            },
        )

        full_text = ""
        with connect() as conn:
            try:
                note = load_note_for_agent_draft(conn, note_id=note_id, user_id=payload.user_id)
                for delta in generate_agent_draft_stream(
                    conn,
                    note,
                    style=payload.style,
                    focus=payload.focus,
                    session_id=session_id or None,
                    attempt_id=attempt_id,
                ):
                    full_text += delta
                    yield writer.event(
                        "agent_message",
                        {
                            "request_id": request_id,
                            "session_id": session_id,
                            "message_id": f"{note_id}-agent-draft",
                            "delta": delta,
                            "content": full_text,
                            "next_action": "show_hint",
                        },
                    )
                update_agent_draft_content(conn, note_id=note_id, draft=full_text.strip())
            except EntityNotFoundError as exc:
                conn.rollback()
                yield writer.error(
                    code=exc.code,
                    message=exc.message,
                    request_id=request_id,
                    details={"note_id": note_id, "user_id": payload.user_id},
                )
                return
            except (LLMCallError, LLMConfigurationError, LLMInvalidResponseError) as exc:
                conn.rollback()
                yield writer.error(
                    code="MODEL_UNAVAILABLE",
                    message=MODEL_UNAVAILABLE_MESSAGE,
                    request_id=request_id,
                    details={"reason": exc.__class__.__name__},
                    recoverable=True,
                )
                return
            conn.commit()

        yield writer.done(
            request_id=request_id,
            session_id=session_id,
            result_ref={"type": "Note", "id": note_id},
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        yield writer.error(
            code="INTERNAL_ERROR",
            message="笔记补全流式响应失败",
            request_id=request_id,
            recoverable=True,
        )
