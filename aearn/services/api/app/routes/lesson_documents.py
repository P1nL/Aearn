"""Verified-only LessonDocument HTTP routes."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, BackgroundTasks, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.core.errors import error_response
from app.db.connection import connect
from app.models.lesson_documents import (
    ActivateLessonMigrationRequest,
    PrepareLessonDocumentRequest,
    StartLessonDocumentRequest,
    ResolveLessonDocumentReferenceRequest,
)
from app.services.learning.lesson_authoring import dispatch_lesson_authoring_run
from app.services.learning.lesson_references import (
    LessonDocumentReferenceError,
    LessonDocumentReferenceResolver,
)
from app.services.learning.lesson_service import LessonDocumentService, LessonDocumentServiceError
from app.services.tutor.cutover import runtime_gate_error


router = APIRouter(prefix="/api/learning-tracks", tags=["lesson-documents"])


@router.get("/{track_id}/lessons/{knowledge_key}", response_model=None)
def read_lesson_document(
    track_id: str, knowledge_key: str, request: Request,
    user_id: str = Query(min_length=1),
) -> JSONResponse:
    unavailable = _require_verified(request, user_id)
    if unavailable is not None:
        return unavailable
    response = _call(request, lambda service: service.read(user_id=user_id, track_id=track_id, knowledge_key=knowledge_key))
    return response if isinstance(response, JSONResponse) else JSONResponse(status_code=200, content=jsonable_encoder(response))


@router.post("/{track_id}/lesson-references/{conversation_id}/resolve", response_model=None)
def resolve_lesson_document_reference(
    track_id: str,
    conversation_id: str,
    payload: ResolveLessonDocumentReferenceRequest,
    request: Request,
) -> JSONResponse:
    unavailable = _require_verified(request, payload.user_id)
    if unavailable is not None:
        return unavailable
    with connect() as conn:
        try:
            response = LessonDocumentReferenceResolver(conn).resolve(
                user_id=payload.user_id,
                conversation_id=conversation_id,
                track_id=track_id,
                knowledge_key=payload.knowledge_key,
                source=payload.source,
            )
        except LessonDocumentReferenceError as exc:
            conn.rollback()
            return error_response(
                request,
                code=exc.code,
                message=exc.message,
                status_code=exc.status_code,
                recoverable=exc.recoverable,
            )
    return JSONResponse(status_code=200, content=jsonable_encoder(response))


@router.post("/{track_id}/lessons/{knowledge_key}/prepare", response_model=None)
def prepare_lesson_document(
    track_id: str, knowledge_key: str, payload: PrepareLessonDocumentRequest,
    request: Request, background_tasks: BackgroundTasks,
) -> JSONResponse:
    return _prepare_or_refresh(track_id, knowledge_key, payload, request, background_tasks, run_kind="prepare")


@router.post("/{track_id}/lessons/{knowledge_key}/refresh", response_model=None)
def refresh_lesson_document(
    track_id: str, knowledge_key: str, payload: PrepareLessonDocumentRequest,
    request: Request, background_tasks: BackgroundTasks,
) -> JSONResponse:
    return _prepare_or_refresh(track_id, knowledge_key, payload, request, background_tasks, run_kind="refresh")


@router.post("/{track_id}/lessons/{knowledge_key}/start", response_model=None)
def start_lesson_document(
    track_id: str, knowledge_key: str, payload: StartLessonDocumentRequest, request: Request,
) -> JSONResponse:
    unavailable = _require_verified(request, payload.user_id)
    if unavailable is not None:
        return unavailable
    response = _call(
        request,
        lambda service: service.start(
            user_id=payload.user_id, track_id=track_id, knowledge_key=knowledge_key,
            assignment_id=payload.assignment_id,
            expected_assignment_version=payload.expected_assignment_version,
            expected_progress_version=payload.expected_progress_version,
            idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
    )
    return response if isinstance(response, JSONResponse) else JSONResponse(status_code=200, content=jsonable_encoder(response))


@router.post("/{track_id}/lessons/{knowledge_key}/migrations/{assignment_id}/activate", response_model=None)
def activate_lesson_migration(
    track_id: str, knowledge_key: str, assignment_id: str,
    payload: ActivateLessonMigrationRequest, request: Request,
) -> JSONResponse:
    unavailable = _require_verified(request, payload.user_id)
    if unavailable is not None:
        return unavailable
    response = _call(
        request,
        lambda service: service.activate_migration(
            user_id=payload.user_id, track_id=track_id, knowledge_key=knowledge_key,
            assignment_id=assignment_id,
            expected_assignment_version=payload.expected_assignment_version,
            idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
    )
    return response if isinstance(response, JSONResponse) else JSONResponse(status_code=200, content=jsonable_encoder(response))


def _prepare_or_refresh(
    track_id: str, knowledge_key: str, payload: PrepareLessonDocumentRequest,
    request: Request, background_tasks: BackgroundTasks, *, run_kind: str,
) -> JSONResponse:
    unavailable = _require_verified(request, payload.user_id)
    if unavailable is not None:
        return unavailable
    response = _call(
        request,
        lambda service: service.prepare(
            user_id=payload.user_id, track_id=track_id, knowledge_key=knowledge_key,
            expected_track_version=payload.expected_track_version,
            expected_progress_version=payload.expected_progress_version,
            idempotency_key=_idempotency_key(request, payload.client_action_id),
            run_kind=run_kind,
        ),
    )
    if isinstance(response, JSONResponse):
        return response
    if bool(response.pop("should_dispatch", False)):
        run = response.get("authoring_run")
        if isinstance(run, dict) and isinstance(run.get("run_id"), str):
            background_tasks.add_task(dispatch_lesson_authoring_run, run["run_id"])
    code = status.HTTP_202_ACCEPTED if response.get("status") == "preparing" and not response.get("idempotent_replayed") else status.HTTP_200_OK
    return JSONResponse(status_code=code, content=jsonable_encoder(response))


def _require_verified(request: Request, user_id: str) -> JSONResponse | None:
    gate = runtime_gate_error(user_id=user_id)
    if gate is None:
        return None
    return error_response(
        request, code=gate.code, message=gate.message, status_code=gate.status_code,
        details=gate.details, recoverable=gate.recoverable,
    )


def _call(
    request: Request,
    action: Callable[[LessonDocumentService], dict[str, object]],
) -> dict[str, object] | JSONResponse:
    with connect() as conn:
        service = LessonDocumentService(conn)
        try:
            return action(service)
        except LessonDocumentServiceError as exc:
            conn.rollback()
            return error_response(
                request, code=exc.code, message=exc.message, status_code=exc.status_code,
                details=exc.details, recoverable=exc.recoverable,
            )


def _idempotency_key(request: Request, fallback: str) -> str:
    header = request.headers.get("Idempotency-Key")
    return header.strip() if isinstance(header, str) and header.strip() else fallback
