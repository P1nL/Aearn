"""Durable LearningTrack teaching-session authority routes."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, BackgroundTasks, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.core.errors import error_response
from app.db.connection import connect
from app.models.teaching_sessions import OpenTeachingSessionRequest, TeachingSessionActionRequest
from app.services.learning.teaching_contracts import TeachingControlStimulus
from app.services.learning.teaching_sessions import TeachingSessionService, TeachingSessionServiceError
from app.services.tutor.cutover import runtime_gate_error
from app.services.tutor.interactive_worker import enqueue_tutor_interactive_dispatch

router = APIRouter(prefix="/api/learning-tracks", tags=["teaching-sessions"])


@router.get("/{track_id}/teaching-sessions", response_model=None)
def list_teaching_sessions(track_id: str, request: Request, user_id: str = Query(min_length=1)) -> JSONResponse:
    return _read(request, user_id, lambda service: service.list_sessions(user_id=user_id, track_id=track_id))


@router.get("/{track_id}/teaching-sessions/{knowledge_key}", response_model=None)
def read_current_teaching_session(
    track_id: str, knowledge_key: str, request: Request, user_id: str = Query(min_length=1),
) -> JSONResponse:
    return _read(
        request, user_id,
        lambda service: service.current(user_id=user_id, track_id=track_id, knowledge_key=knowledge_key),
    )


@router.post("/{track_id}/teaching-sessions/{knowledge_key}/open", response_model=None)
def open_teaching_session(
    track_id: str, knowledge_key: str, payload: OpenTeachingSessionRequest, request: Request,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    unavailable = _require_verified(request, str(payload.user_id))
    if unavailable is not None:
        return unavailable
    response = _call(
        request,
        lambda service: service.open(
            user_id=str(payload.user_id), track_id=track_id, knowledge_key=knowledge_key,
            conversation_id=str(payload.conversation_id) if payload.conversation_id is not None else None,
            expected_track_version=payload.expected_track_version,
            expected_progress_version=payload.expected_progress_version,
            expected_assignment_version=payload.expected_assignment_version,
            mode=payload.mode, idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
    )
    if isinstance(response, JSONResponse):
        return response
    _schedule_pending_run(response, background_tasks)
    code = status.HTTP_201_CREATED if response.get("created") and not response.get("idempotent_replayed") else status.HTTP_200_OK
    return JSONResponse(status_code=code, content=jsonable_encoder(response))


@router.post("/{track_id}/teaching-sessions/{session_id}/actions", response_model=None)
def mutate_teaching_session(
    track_id: str, session_id: str, payload: TeachingSessionActionRequest, request: Request,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    unavailable = _require_verified(request, str(payload.user_id))
    if unavailable is not None:
        return unavailable
    safe_payload: dict[str, object] = {
        key: value for key, value in {
            "target_mode": payload.target_mode.value if payload.target_mode is not None else None,
            "target_knowledge_key": payload.target_knowledge_key,
            "reason_code": payload.reason_code,
        }.items() if value is not None
    }
    control = TeachingControlStimulus(
        control_key=payload.control_key, client_action_id=payload.client_action_id,
        expected_session_version=payload.expected_session_version,
        expected_track_version=payload.expected_track_version,
        expected_progress_version=payload.expected_progress_version,
        expected_assignment_version=payload.expected_assignment_version,
        safe_payload=safe_payload,
    )
    response = _call(
        request,
        lambda service: service.action(
            user_id=str(payload.user_id), track_id=track_id, session_id=session_id,
            control=control, target_mode=payload.target_mode, admit_run=payload.admit_run,
            idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
    )
    if isinstance(response, JSONResponse):
        return response
    _schedule_pending_run(response, background_tasks)
    return JSONResponse(status_code=200, content=jsonable_encoder(response))


def _schedule_pending_run(response: dict[str, object], background_tasks: BackgroundTasks) -> None:
    pending = response.get("pending_run")
    if not isinstance(pending, dict):
        return
    job_id = pending.get("dispatch_job_id")
    if isinstance(job_id, str) and job_id:
        background_tasks.add_task(enqueue_tutor_interactive_dispatch, job_id, runtime_kind="harness_v1")


def _read(request: Request, user_id: str, action: Callable[[TeachingSessionService], dict[str, object]]) -> JSONResponse:
    unavailable = _require_verified(request, user_id)
    if unavailable is not None:
        return unavailable
    response = _call(request, action)
    return response if isinstance(response, JSONResponse) else JSONResponse(status_code=200, content=jsonable_encoder(response))


def _require_verified(request: Request, user_id: str) -> JSONResponse | None:
    gate = runtime_gate_error(user_id=user_id)
    if gate is None:
        return None
    return error_response(
        request, code=gate.code, message=gate.message, status_code=gate.status_code,
        details=gate.details, recoverable=gate.recoverable,
    )


def _call(
    request: Request, action: Callable[[TeachingSessionService], dict[str, object]],
) -> dict[str, object] | JSONResponse:
    with connect() as conn:
        service = TeachingSessionService(conn)
        try:
            return action(service)
        except TeachingSessionServiceError as exc:
            conn.rollback()
            return error_response(
                request, code=exc.code, message=exc.message, status_code=exc.status_code,
                details=exc.details, recoverable=exc.recoverable,
            )


def _idempotency_key(request: Request, fallback: str) -> str:
    header = request.headers.get("Idempotency-Key")
    return header.strip() if isinstance(header, str) and header.strip() else fallback
