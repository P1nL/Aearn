"""Verified-only HTTP routes for track-scoped ReviewSession."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.core.errors import error_response
from app.db.connection import connect
from app.models.review_sessions import (
    CreateReviewSessionRequest,
    FinalizeReviewSessionRequest,
    ReviewAttemptRequest,
    ReviewHintRequest,
    ReviewWarmupRequest,
)
from app.services.learning.reviews.service import ReviewService, ReviewServiceError
from app.services.tutor.cutover import runtime_gate_error


router = APIRouter(prefix="/api/learning-tracks", tags=["reviews"])


@router.get("/{track_id}/reviews", response_model=None)
def read_review_queue(
    track_id: str,
    request: Request,
    user_id: str = Query(min_length=1),
) -> JSONResponse:
    return _read(
        request,
        user_id,
        lambda service: service.read_queue(user_id=user_id, track_id=track_id),
    )


@router.post("/{track_id}/reviews/sessions", response_model=None)
def create_review_session(
    track_id: str,
    payload: CreateReviewSessionRequest,
    request: Request,
) -> JSONResponse:
    return _write(
        request,
        payload.user_id,
        lambda service: service.create_session(
            user_id=payload.user_id,
            track_id=track_id,
            knowledge_key=payload.knowledge_key,
            expected_track_version=payload.expected_track_version,
            expected_schedule_version=payload.expected_schedule_version,
            max_items=payload.max_items,
            idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
        created=True,
    )


@router.get("/{track_id}/reviews/sessions/{session_id}", response_model=None)
def read_review_session(
    track_id: str,
    session_id: str,
    request: Request,
    user_id: str = Query(min_length=1),
) -> JSONResponse:
    return _read(
        request,
        user_id,
        lambda service: service.read_session(
            user_id=user_id,
            track_id=track_id,
            session_id=session_id,
        ),
    )


@router.post("/{track_id}/reviews/sessions/{session_id}/warmup", response_model=None)
def record_review_warmup(
    track_id: str,
    session_id: str,
    payload: ReviewWarmupRequest,
    request: Request,
) -> JSONResponse:
    return _write(
        request,
        payload.user_id,
        lambda service: service.warmup(
            user_id=payload.user_id,
            track_id=track_id,
            session_id=session_id,
            response_kind=payload.response_kind,
            confidence=payload.confidence,
            expected_session_version=payload.expected_session_version,
            idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
    )


@router.post(
    "/{track_id}/reviews/sessions/{session_id}/items/{item_id}/hints",
    response_model=None,
)
def request_review_hint(
    track_id: str,
    session_id: str,
    item_id: str,
    payload: ReviewHintRequest,
    request: Request,
) -> JSONResponse:
    return _write(
        request,
        payload.user_id,
        lambda service: service.hint(
            user_id=payload.user_id,
            track_id=track_id,
            session_id=session_id,
            item_id=item_id,
            hint_level=payload.hint_level,
            expected_session_version=payload.expected_session_version,
            expected_item_version=payload.expected_item_version,
            idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
    )


@router.post(
    "/{track_id}/reviews/sessions/{session_id}/items/{item_id}/attempts",
    response_model=None,
)
def create_review_attempt(
    track_id: str,
    session_id: str,
    item_id: str,
    payload: ReviewAttemptRequest,
    request: Request,
) -> JSONResponse:
    return _write(
        request,
        payload.user_id,
        lambda service: service.attempt_item(
            user_id=payload.user_id,
            track_id=track_id,
            session_id=session_id,
            item_id=item_id,
            submission=payload.submission,
            review_submission=(
                payload.review_submission.model_dump(mode="json")
                if payload.review_submission is not None
                else None
            ),
            expected_session_version=payload.expected_session_version,
            expected_item_version=payload.expected_item_version,
            idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
        accepted_if_pending=True,
    )


@router.get(
    "/{track_id}/reviews/sessions/{session_id}/attempts/{attempt_id}",
    response_model=None,
)
def read_review_attempt(
    track_id: str,
    session_id: str,
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
            session_id=session_id,
            attempt_id=attempt_id,
        ),
    )


@router.post("/{track_id}/reviews/sessions/{session_id}/finalize", response_model=None)
def finalize_review_session(
    track_id: str,
    session_id: str,
    payload: FinalizeReviewSessionRequest,
    request: Request,
) -> JSONResponse:
    return _write(
        request,
        payload.user_id,
        lambda service: service.finalize_session(
            user_id=payload.user_id,
            track_id=track_id,
            session_id=session_id,
            expected_session_version=payload.expected_session_version,
            idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
    )


def _read(
    request: Request,
    user_id: str,
    action: Callable[[ReviewService], dict[str, object]],
) -> JSONResponse:
    unavailable = _require_verified(request, user_id)
    if unavailable is not None:
        return unavailable
    result = _call(request, action)
    return result if isinstance(result, JSONResponse) else JSONResponse(
        status_code=200,
        content=jsonable_encoder(result),
    )


def _write(
    request: Request,
    user_id: str,
    action: Callable[[ReviewService], dict[str, object]],
    *,
    created: bool = False,
    accepted_if_pending: bool = False,
) -> JSONResponse:
    unavailable = _require_verified(request, user_id)
    if unavailable is not None:
        return unavailable
    result = _call(request, action)
    if isinstance(result, JSONResponse):
        return result
    if accepted_if_pending and result.get("status") == "pending":
        code = status.HTTP_202_ACCEPTED
    elif created and not bool(result.get("idempotent_replayed")):
        code = status.HTTP_201_CREATED
    else:
        code = status.HTTP_200_OK
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
    action: Callable[[ReviewService], dict[str, object]],
) -> dict[str, object] | JSONResponse:
    with connect() as conn:
        service = ReviewService(conn)
        try:
            return action(service)
        except ReviewServiceError as exc:
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
