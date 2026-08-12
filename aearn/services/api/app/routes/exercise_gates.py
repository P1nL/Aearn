"""Verified-only Lesson Gate and module diagnostic HTTP routes."""
from __future__ import annotations

import json
from collections.abc import Callable

from fastapi import APIRouter, BackgroundTasks, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.core.errors import error_response
from app.db.connection import connect
from app.models.exercise_gates import (
    ConfirmModuleDiagnosticSkipRequest,
    CreateModuleDiagnosticRequest,
    LessonGateAttemptRequest,
    LessonGateHintRequest,
    ModelReviewEvidenceRequest,
    ModuleDiagnosticAttemptRequest,
    PrepareLessonGateRequest,
)
from app.services.learning.practice.model_review_authoring import dispatch_model_review_authoring_run
from app.services.learning.practice.service import ExerciseGateService, ExerciseGateServiceError
from app.services.tutor.cutover import runtime_gate_error


router = APIRouter(prefix="/api/learning-tracks", tags=["exercise-gates"])


@router.get("/{track_id}/lessons/{knowledge_key}/gates", response_model=None)
def read_lesson_gates(
    track_id: str,
    knowledge_key: str,
    request: Request,
    user_id: str = Query(min_length=1),
) -> JSONResponse:
    return _read(
        request,
        user_id,
        lambda service: service.read_gates(
            user_id=user_id,
            track_id=track_id,
            knowledge_key=knowledge_key,
        ),
    )


@router.post("/{track_id}/lessons/{knowledge_key}/gates/{gate_key}/prepare", response_model=None)
def prepare_lesson_gate(
    track_id: str,
    knowledge_key: str,
    gate_key: str,
    payload: PrepareLessonGateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    response = _write(
        request,
        payload.user_id,
        lambda service: service.prepare_gate(
            user_id=payload.user_id,
            track_id=track_id,
            knowledge_key=knowledge_key,
            gate_key=gate_key,
            expected_track_version=payload.expected_track_version,
            expected_progress_version=payload.expected_progress_version,
            idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
    )
    if response.status_code not in {status.HTTP_200_OK, status.HTTP_202_ACCEPTED}:
        return response
    try:
        body = json.loads(bytes(response.body))
    except (TypeError, ValueError):
        return response
    if not isinstance(body, dict):
        return response
    should_dispatch = bool(body.pop("should_dispatch", False))
    if should_dispatch:
        run = body.get("review_authoring_run")
        if isinstance(run, dict) and isinstance(run.get("run_id"), str):
            background_tasks.add_task(dispatch_model_review_authoring_run, run["run_id"])
    code = status.HTTP_202_ACCEPTED if body.get("status") == "preparing" else response.status_code
    return JSONResponse(status_code=code, content=body)


@router.post("/{track_id}/lessons/{knowledge_key}/gates/{gate_key}/hints", response_model=None)
def request_lesson_gate_hint(
    track_id: str,
    knowledge_key: str,
    gate_key: str,
    payload: LessonGateHintRequest,
    request: Request,
) -> JSONResponse:
    return _write(
        request,
        payload.user_id,
        lambda service: service.hint(
            user_id=payload.user_id,
            track_id=track_id,
            knowledge_key=knowledge_key,
            gate_key=gate_key,
            expected_gate_version=payload.expected_gate_version,
            idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
    )


@router.post("/{track_id}/lessons/{knowledge_key}/gates/{gate_key}/evidence", response_model=None)
def read_model_review_evidence(
    track_id: str,
    knowledge_key: str,
    gate_key: str,
    payload: ModelReviewEvidenceRequest,
    request: Request,
) -> JSONResponse:
    return _write(
        request,
        payload.user_id,
        lambda service: service.model_review_evidence(
            user_id=payload.user_id,
            track_id=track_id,
            knowledge_key=knowledge_key,
            gate_key=gate_key,
            expected_gate_version=payload.expected_gate_version,
            idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
    )


@router.post("/{track_id}/lessons/{knowledge_key}/gates/{gate_key}/attempts", response_model=None)
def create_lesson_gate_attempt(
    track_id: str,
    knowledge_key: str,
    gate_key: str,
    payload: LessonGateAttemptRequest,
    request: Request,
) -> JSONResponse:
    return _write(
        request,
        payload.user_id,
        lambda service: service.attempt_gate(
            user_id=payload.user_id,
            track_id=track_id,
            knowledge_key=knowledge_key,
            gate_key=gate_key,
            attempt_type=payload.attempt_type,
            submission=payload.submission,
            review_submission=payload.review_submission.model_dump(mode="json")
            if payload.review_submission is not None
            else None,
            expected_track_version=payload.expected_track_version,
            expected_progress_version=payload.expected_progress_version,
            expected_assignment_version=payload.expected_assignment_version,
            expected_gate_version=payload.expected_gate_version,
            idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
        accepted_if_pending=True,
    )


@router.get("/{track_id}/lessons/{knowledge_key}/attempts/{attempt_id}", response_model=None)
def read_lesson_gate_attempt(
    track_id: str,
    knowledge_key: str,
    attempt_id: str,
    request: Request,
    user_id: str = Query(min_length=1),
) -> JSONResponse:
    return _read(
        request,
        user_id,
        lambda service: service.read_attempt(
            user_id=user_id,
            track_id=track_id,
            knowledge_key=knowledge_key,
            attempt_id=attempt_id,
        ),
    )


@router.post("/{track_id}/modules/{module_key}/diagnostics", response_model=None)
def create_module_diagnostic(
    track_id: str,
    module_key: str,
    payload: CreateModuleDiagnosticRequest,
    request: Request,
) -> JSONResponse:
    return _write(
        request,
        payload.user_id,
        lambda service: service.create_diagnostic(
            user_id=payload.user_id,
            track_id=track_id,
            module_key=module_key,
            expected_track_version=payload.expected_track_version,
            idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
    )


@router.get("/{track_id}/modules/{module_key}/diagnostics/{session_id}", response_model=None)
def read_module_diagnostic(
    track_id: str,
    module_key: str,
    session_id: str,
    request: Request,
    user_id: str = Query(min_length=1),
) -> JSONResponse:
    return _read(
        request,
        user_id,
        lambda service: service.read_diagnostic(
            user_id=user_id,
            track_id=track_id,
            module_key=module_key,
            session_id=session_id,
        ),
    )


@router.post(
    "/{track_id}/modules/{module_key}/diagnostics/{session_id}/items/{item_id}/attempts",
    response_model=None,
)
def create_module_diagnostic_attempt(
    track_id: str,
    module_key: str,
    session_id: str,
    item_id: str,
    payload: ModuleDiagnosticAttemptRequest,
    request: Request,
) -> JSONResponse:
    return _write(
        request,
        payload.user_id,
        lambda service: service.attempt_diagnostic(
            user_id=payload.user_id,
            track_id=track_id,
            module_key=module_key,
            session_id=session_id,
            item_id=item_id,
            submission=payload.submission,
            expected_track_version=payload.expected_track_version,
            expected_session_version=payload.expected_session_version,
            idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
        accepted_if_pending=True,
    )


@router.post("/{track_id}/modules/{module_key}/diagnostics/{session_id}/confirm-skip", response_model=None)
def confirm_module_diagnostic_skip(
    track_id: str,
    module_key: str,
    session_id: str,
    payload: ConfirmModuleDiagnosticSkipRequest,
    request: Request,
) -> JSONResponse:
    return _write(
        request,
        payload.user_id,
        lambda service: service.confirm_diagnostic_skip(
            user_id=payload.user_id,
            track_id=track_id,
            module_key=module_key,
            session_id=session_id,
            expected_track_version=payload.expected_track_version,
            expected_session_version=payload.expected_session_version,
            idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
    )


def _read(
    request: Request,
    user_id: str,
    action: Callable[[ExerciseGateService], dict[str, object]],
) -> JSONResponse:
    unavailable = _require_verified(request, user_id)
    if unavailable is not None:
        return unavailable
    result = _call(request, action)
    return result if isinstance(result, JSONResponse) else JSONResponse(status_code=200, content=jsonable_encoder(result))


def _write(
    request: Request,
    user_id: str,
    action: Callable[[ExerciseGateService], dict[str, object]],
    *,
    accepted_if_pending: bool = False,
) -> JSONResponse:
    unavailable = _require_verified(request, user_id)
    if unavailable is not None:
        return unavailable
    result = _call(request, action)
    if isinstance(result, JSONResponse):
        return result
    code = status.HTTP_202_ACCEPTED if accepted_if_pending and result.get("status") == "pending" else status.HTTP_200_OK
    return JSONResponse(status_code=code, content=jsonable_encoder(result))


def _require_verified(request: Request, user_id: str) -> JSONResponse | None:
    gate = runtime_gate_error(user_id=user_id)
    if gate is None:
        return None
    return error_response(
        request,
        code=gate.code,
        message=gate.message,
        status_code=gate.status_code,
        details=gate.details,
        recoverable=gate.recoverable,
    )


def _call(
    request: Request,
    action: Callable[[ExerciseGateService], dict[str, object]],
) -> dict[str, object] | JSONResponse:
    with connect() as conn:
        service = ExerciseGateService(conn)
        try:
            return action(service)
        except ExerciseGateServiceError as exc:
            conn.rollback()
            return error_response(
                request,
                code=exc.code,
                message=exc.message,
                status_code=exc.status_code,
                details=exc.details,
                recoverable=exc.recoverable,
            )


def _idempotency_key(request: Request, fallback: str) -> str:
    header = request.headers.get("Idempotency-Key")
    return header.strip() if isinstance(header, str) and header.strip() else fallback
