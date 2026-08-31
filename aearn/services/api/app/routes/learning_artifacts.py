from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, TypeVar
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from psycopg import Connection

from app.core.config import get_settings
from app.core.errors import error_response
from app.db.connection import connect
from app.services.learning.artifacts.contracts import (
    TutorArtifactActionRequest,
    TutorArtifactActionResponseV1,
)
from app.services.learning.artifacts.owner_adapters import ArtifactOwnerAdapterRegistry
from app.services.learning.artifacts.repository import LearningArtifactWriteResult
from app.services.learning.artifacts.service import (
    LearningArtifactService,
    LearningArtifactServiceError,
)
from app.services.tutor.cutover import runtime_gate_error
from app.services.tutor.thread_turn_cutover import thread_turn_v2_gate_error


router = APIRouter(prefix="/api/tutor", tags=["tutor-artifacts"])
T = TypeVar("T")
_IDEMPOTENCY_KEY_HEADER = Header(
    alias="Idempotency-Key",
    min_length=1,
    max_length=160,
    pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$",
)


@router.get(
    "/conversations/{conversation_id}/artifacts/{artifact_id}",
    response_model=None,
)
def read_learning_artifact(
    conversation_id: UUID,
    artifact_id: UUID,
    request: Request,
    user_id: str = Query(min_length=1, max_length=160),
) -> JSONResponse:
    unavailable = _require_tutor_route(request, user_id)
    if unavailable is not None:
        return unavailable
    response = _call_service(
        request,
        lambda service: service.read_artifact(
            user_id=user_id,
            conversation_id=str(conversation_id),
            artifact_id=str(artifact_id),
        ),
    )
    return _success(response)


@router.post(
    "/conversations/{conversation_id}/artifacts/{artifact_id}/actions",
    response_model=None,
)
def act_on_learning_artifact(
    conversation_id: UUID,
    artifact_id: UUID,
    payload: TutorArtifactActionRequest,
    request: Request,
    idempotency_key: Annotated[str | None, _IDEMPOTENCY_KEY_HEADER] = None,
) -> JSONResponse:
    unavailable = _require_tutor_route(request, payload.user_id, mutation=True)
    if unavailable is not None:
        return unavailable
    action_request = (
        payload
        if idempotency_key is None
        else TutorArtifactActionRequest.model_validate(
            {
                **payload.model_dump(mode="json", exclude_none=False),
                "client_action_id": idempotency_key,
            }
        )
    )
    response = _call_service(
        request,
        lambda service: service.act(
            conversation_id=str(conversation_id),
            artifact_id=str(artifact_id),
            request=action_request,
        ),
        commit=True,
    )
    if isinstance(response, JSONResponse):
        return response
    return _success(_project_action_response(response))


@router.get(
    "/conversations/{conversation_id}/artifacts/{artifact_id}/attempts/{attempt_id}",
    response_model=None,
)
def read_learning_artifact_attempt(
    conversation_id: UUID,
    artifact_id: UUID,
    attempt_id: UUID,
    request: Request,
    user_id: str = Query(min_length=1, max_length=160),
) -> JSONResponse:
    unavailable = _require_tutor_route(request, user_id)
    if unavailable is not None:
        return unavailable
    response = _call_service(
        request,
        lambda service: service.read_attempt_detail(
            user_id=user_id,
            conversation_id=str(conversation_id),
            artifact_id=str(artifact_id),
            attempt_id=str(attempt_id),
        ),
    )
    return _success(response)


def build_learning_artifact_owner_adapters() -> ArtifactOwnerAdapterRegistry:
    """Return the exact registered owner adapters; no fallback owner exists."""

    return ArtifactOwnerAdapterRegistry()


def build_learning_artifact_service(
    conn: Connection[dict[str, object]],
) -> LearningArtifactService:
    return LearningArtifactService(
        conn,
        owner_adapters=build_learning_artifact_owner_adapters(),
        enabled=lambda: get_settings().tutor_learning_artifacts_enabled,
    )


def _call_service(
    request: Request,
    action: Callable[[LearningArtifactService], T],
    *,
    commit: bool = False,
) -> T | JSONResponse:
    with connect() as conn:
        service = build_learning_artifact_service(conn)
        try:
            response = action(service)
        except LearningArtifactServiceError as exc:
            conn.rollback()
            return _service_error(request, exc)
        if commit:
            conn.commit()
    return response


def _project_action_response(
    result: LearningArtifactWriteResult,
) -> TutorArtifactActionResponseV1:
    return TutorArtifactActionResponseV1(
        artifact=result.artifact,
        artifact_event_id=result.artifact_event_id,
        artifact_event_sequence=result.artifact_event_sequence,
        idempotent_replayed=result.idempotent_replayed,
    )


def _require_tutor_route(
    request: Request,
    user_id: str,
    *,
    mutation: bool = False,
) -> JSONResponse | None:
    gate_error = runtime_gate_error(user_id=user_id)
    if gate_error is None and mutation:
        gate_error = thread_turn_v2_gate_error(settings=get_settings())
    if gate_error is None:
        return None
    return error_response(
        request,
        code=gate_error.code,
        message=gate_error.message,
        status_code=gate_error.status_code,
        details=gate_error.details,
        recoverable=gate_error.recoverable,
    )


def _service_error(
    request: Request,
    error: LearningArtifactServiceError,
) -> JSONResponse:
    return error_response(
        request,
        code=error.code,
        message=error.message,
        status_code=error.status_code,
        details=error.details,
        recoverable=error.recoverable,
    )


def _success(payload: object) -> JSONResponse:
    if isinstance(payload, JSONResponse):
        return payload
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=jsonable_encoder(payload),
    )


__all__ = (
    "build_learning_artifact_owner_adapters",
    "build_learning_artifact_service",
    "router",
)
