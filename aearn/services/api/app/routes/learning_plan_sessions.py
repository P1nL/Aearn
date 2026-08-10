"""Verified-only HTTP routes for conversational learning-plan sessions."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.core.errors import error_response
from app.db.connection import connect
from app.models.learning_plan_sessions import (
    CancelLearningPlanSessionRequest,
    ConfirmLearningPlanSessionRequest,
    CreateLearningPlanSessionRequest,
)
from app.services.learning.plan_service import (
    LearningPlanSessionService,
    LearningPlanSessionServiceError,
)
from app.services.tutor.cutover import runtime_gate_error


router = APIRouter(prefix="/api/learning-plan-sessions", tags=["learning-plan-sessions"])


@router.post("", response_model=None)
def create_learning_plan_session(payload: CreateLearningPlanSessionRequest, request: Request) -> JSONResponse:
    unavailable = _require_verified(request, payload.user_id)
    if unavailable is not None:
        return unavailable
    response = _call(
        request,
        lambda service: service.create_session(
            user_id=payload.user_id,
            preferred_language_id=payload.preferred_language_id,
            idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
        commit=True,
    )
    if isinstance(response, JSONResponse):
        return response
    code = status.HTTP_200_OK if bool(response.get("idempotent_replayed")) or bool(response.get("resumed")) else status.HTTP_201_CREATED
    return JSONResponse(status_code=code, content=jsonable_encoder(response))


@router.get("/current", response_model=None)
def current_learning_plan_session(request: Request, user_id: str = Query(min_length=1)) -> JSONResponse:
    unavailable = _require_verified(request, user_id)
    if unavailable is not None:
        return unavailable
    response = _call(request, lambda service: service.current_session(user_id=user_id))
    return response if isinstance(response, JSONResponse) else JSONResponse(status_code=200, content=jsonable_encoder(response))


@router.get("/{session_id}", response_model=None)
def read_learning_plan_session(
    session_id: str,
    request: Request,
    user_id: str = Query(min_length=1),
) -> JSONResponse:
    unavailable = _require_verified(request, user_id)
    if unavailable is not None:
        return unavailable
    response = _call(
        request,
        lambda service: service.read_session(user_id=user_id, session_id=session_id),
    )
    return response if isinstance(response, JSONResponse) else JSONResponse(status_code=200, content=jsonable_encoder(response))


@router.post("/{session_id}/cancel", response_model=None)
def cancel_learning_plan_session(
    session_id: str,
    payload: CancelLearningPlanSessionRequest,
    request: Request,
) -> JSONResponse:
    unavailable = _require_verified(request, payload.user_id)
    if unavailable is not None:
        return unavailable
    response = _call(
        request,
        lambda service: service.cancel_session(
            user_id=payload.user_id,
            session_id=session_id,
            expected_session_version=payload.expected_session_version,
            idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
        commit=True,
    )
    return response if isinstance(response, JSONResponse) else JSONResponse(status_code=200, content=jsonable_encoder(response))


@router.post("/{session_id}/confirm", response_model=None)
def confirm_learning_plan_session(
    session_id: str,
    payload: ConfirmLearningPlanSessionRequest,
    request: Request,
) -> JSONResponse:
    unavailable = _require_verified(request, payload.user_id)
    if unavailable is not None:
        return unavailable
    response = _call(
        request,
        lambda service: service.confirm_session(
            user_id=payload.user_id,
            session_id=session_id,
            expected_session_version=payload.expected_session_version,
            draft_id=payload.draft_id,
            draft_version=payload.draft_version,
            content_hash=payload.content_hash,
            idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
        commit=True,
    )
    return response if isinstance(response, JSONResponse) else JSONResponse(status_code=200, content=jsonable_encoder(response))


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
    action: Callable[[LearningPlanSessionService], dict[str, object]],
    *,
    commit: bool = False,
) -> dict[str, object] | JSONResponse:
    with connect() as conn:
        service = LearningPlanSessionService(conn)
        try:
            response = action(service)
        except LearningPlanSessionServiceError as exc:
            conn.rollback()
            return error_response(
                request,
                code=exc.code,
                message=exc.message,
                status_code=exc.status_code,
                details=exc.details,
                recoverable=exc.recoverable,
            )
        if commit:
            conn.commit()
    return response


def _idempotency_key(request: Request, fallback: str) -> str:
    header = request.headers.get("Idempotency-Key")
    return header.strip() if isinstance(header, str) and header.strip() else fallback
