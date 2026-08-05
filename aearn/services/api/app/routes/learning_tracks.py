"""Verified-only HTTP routes for the LearningTrack domain."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.core.errors import error_response
from app.db.connection import connect
from app.models.learning_tracks import (
    ActivateLearningPlanRevisionRequest,
    CreateLearningTrackRequest,
    ProposeLearningPlanRevisionRequest,
)
from app.services.learning.track_service import LearningTrackService, LearningTrackServiceError
from app.services.tutor.cutover import runtime_gate_error


router = APIRouter(prefix="/api/learning-tracks", tags=["learning-tracks"])


@router.get("", response_model=None)
def list_learning_tracks(request: Request, user_id: str = Query(min_length=1)) -> JSONResponse:
    unavailable = _require_verified(request, user_id)
    if unavailable is not None:
        return unavailable
    response = _call(request, lambda service: service.list_tracks(user_id=user_id))
    return response if isinstance(response, JSONResponse) else JSONResponse(status_code=200, content=jsonable_encoder(response))


@router.post("", response_model=None)
def create_learning_track(payload: CreateLearningTrackRequest, request: Request) -> JSONResponse:
    unavailable = _require_verified(request, payload.user_id)
    if unavailable is not None:
        return unavailable
    response = _call(
        request,
        lambda service: service.create_track(
            user_id=payload.user_id,
            language_id=payload.language_id,
            goal_text=payload.goal_text,
            target_level=payload.target_level,
            plan=payload.plan.to_domain(),
            conversation_id=payload.conversation_id,
            idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
        commit=True,
    )
    if isinstance(response, JSONResponse):
        return response
    code = status.HTTP_200_OK if bool(response.get("idempotent_replayed")) else status.HTTP_201_CREATED
    return JSONResponse(status_code=code, content=jsonable_encoder(response))


@router.get("/{track_id}", response_model=None)
def read_learning_track(track_id: str, request: Request, user_id: str = Query(min_length=1)) -> JSONResponse:
    unavailable = _require_verified(request, user_id)
    if unavailable is not None:
        return unavailable
    response = _call(request, lambda service: service.read_track(user_id=user_id, track_id=track_id))
    return response if isinstance(response, JSONResponse) else JSONResponse(status_code=200, content=jsonable_encoder(response))


@router.get("/{track_id}/roadmap", response_model=None)
def read_learning_track_roadmap(track_id: str, request: Request, user_id: str = Query(min_length=1)) -> JSONResponse:
    unavailable = _require_verified(request, user_id)
    if unavailable is not None:
        return unavailable
    response = _call(request, lambda service: service.read_roadmap(user_id=user_id, track_id=track_id))
    return response if isinstance(response, JSONResponse) else JSONResponse(status_code=200, content=jsonable_encoder(response))


@router.get("/{track_id}/plan-revisions", response_model=None)
def list_learning_plan_revisions(track_id: str, request: Request, user_id: str = Query(min_length=1)) -> JSONResponse:
    unavailable = _require_verified(request, user_id)
    if unavailable is not None:
        return unavailable
    response = _call(request, lambda service: service.list_revisions(user_id=user_id, track_id=track_id))
    return response if isinstance(response, JSONResponse) else JSONResponse(status_code=200, content=jsonable_encoder(response))


@router.post("/{track_id}/plan-revisions", response_model=None)
def propose_learning_plan_revision(
    track_id: str,
    payload: ProposeLearningPlanRevisionRequest,
    request: Request,
) -> JSONResponse:
    unavailable = _require_verified(request, payload.user_id)
    if unavailable is not None:
        return unavailable
    response = _call(
        request,
        lambda service: service.propose_revision(
            user_id=payload.user_id,
            track_id=track_id,
            expected_track_version=payload.expected_track_version,
            plan=payload.plan.to_domain(),
            idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
        commit=True,
    )
    if isinstance(response, JSONResponse):
        return response
    code = status.HTTP_200_OK if bool(response.get("idempotent_replayed")) else status.HTTP_201_CREATED
    return JSONResponse(status_code=code, content=jsonable_encoder(response))


@router.post("/{track_id}/plan-revisions/{revision_id}/activate", response_model=None)
def activate_learning_plan_revision(
    track_id: str,
    revision_id: str,
    payload: ActivateLearningPlanRevisionRequest,
    request: Request,
) -> JSONResponse:
    unavailable = _require_verified(request, payload.user_id)
    if unavailable is not None:
        return unavailable
    response = _call(
        request,
        lambda service: service.activate_revision(
            user_id=payload.user_id,
            track_id=track_id,
            revision_id=revision_id,
            expected_track_version=payload.expected_track_version,
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
    action: Callable[[LearningTrackService], dict[str, object]],
    *,
    commit: bool = False,
) -> dict[str, object] | JSONResponse:
    with connect() as conn:
        service = LearningTrackService(conn)
        try:
            response = action(service)
        except LearningTrackServiceError as exc:
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
