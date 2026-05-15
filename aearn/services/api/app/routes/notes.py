from fastapi import APIRouter, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.core.errors import error_response
from app.db.connection import connect
from app.models.notes import AgentDraftRequest, CreateNoteRequest, UpdateNoteRequest
from app.services.note_repository import (
    EntityNotFoundError,
    create_note,
    list_notes,
    update_agent_draft,
    update_note,
)


router = APIRouter(prefix="/api/notes", tags=["notes"])


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
) -> dict[str, object] | JSONResponse:
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
        conn.commit()
    return JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder({"note": note}))
