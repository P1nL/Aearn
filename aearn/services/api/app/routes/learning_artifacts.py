from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, TypeVar
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Header, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from psycopg import Connection

from app.core.config import get_settings
from app.core.errors import error_response
from app.db.connection import connect
from app.services.learning.artifacts.contracts import (
    TutorArtifactActionRequest,
    TutorArtifactActionResponseV1,
    TutorArtifactAttemptDetailV2,
    TutorArtifactCompleteDemoAction,
    TutorArtifactKind,
)
from app.services.learning.artifacts.execution_results import (
    ExecutionResultArtifactProjector,
)
from app.services.learning.artifacts.owner_adapters import ArtifactOwnerAdapterRegistry
from app.services.learning.artifacts.repository import LearningArtifactWriteResult
from app.services.learning.artifacts.service import (
    LearningArtifactService,
    LearningArtifactServiceError,
)
from app.services.learning.artifacts.teaching_owner_adapters import (
    LearningItemArtifactOwnerAdapter,
    TeachingPracticeArtifactOwnerAdapter,
)
from app.services.learning.practice.service import (
    ExerciseGateService,
    ExerciseGateServiceError,
)
from app.services.learning.reviews.service import ReviewService, ReviewServiceError
from app.services.tutor.continuation import (
    ContinuationIntentConflict,
    ContinuationIntentError,
    ContinuationIntentNotFound,
    ContinuationIntentStale,
    TutorContinuationDispatcher,
    TutorContinuationIntentProducer,
)
from app.services.tutor.cutover import runtime_gate_error
from app.services.tutor.interactive_worker import enqueue_tutor_interactive_dispatch
from app.services.tutor.thread_turn_cutover import thread_turn_v2_gate_error


router = APIRouter(prefix="/api/tutor", tags=["tutor-artifacts"])
T = TypeVar("T")
_IDEMPOTENCY_KEY_HEADER = Header(
    alias="Idempotency-Key",
    min_length=1,
    max_length=160,
    pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$",
)


@dataclass(frozen=True, slots=True)
class _ArtifactAttemptObservation:
    detail: TutorArtifactAttemptDetailV2
    dispatch_job_id: str | None = None
    source_write: LearningArtifactWriteResult | None = None


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
    background_tasks: BackgroundTasks,
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
    dispatch_job_id: str | None = None
    with connect() as conn:
        service = build_learning_artifact_service(conn)
        try:
            response = service.act(
                conversation_id=str(conversation_id),
                artifact_id=str(artifact_id),
                request=action_request,
            )
            occurred_at = datetime.now(UTC)
            if action_request.action.action == "run":
                active_attempt = response.artifact.active_attempt
                if active_attempt is not None:
                    observation = _observe_artifact_attempt(
                        conn=conn,
                        service=service,
                        user_id=action_request.user_id,
                        conversation_id=response.artifact.conversation_id,
                        artifact_id=response.artifact.id,
                        attempt_id=active_attempt.attempt_id,
                        occurred_at=occurred_at,
                    )
                    dispatch_job_id = observation.dispatch_job_id
                    if observation.source_write is not None:
                        response = observation.source_write
            else:
                producer = TutorContinuationIntentProducer(conn)
                if isinstance(action_request.action, TutorArtifactCompleteDemoAction):
                    intent = producer.record_demonstration_completion(
                        user_id=action_request.user_id,
                        conversation_id=response.artifact.conversation_id,
                        artifact_id=response.artifact.id,
                        artifact_event_id=response.artifact_event_id,
                        artifact_event_sequence=response.artifact_event_sequence,
                        occurred_at=occurred_at,
                    )
                else:
                    intent = producer.record_artifact_action(
                        user_id=action_request.user_id,
                        conversation_id=response.artifact.conversation_id,
                        artifact_id=response.artifact.id,
                        artifact_event_id=response.artifact_event_id,
                        artifact_event_sequence=response.artifact_event_sequence,
                        action_kind=action_request.action.action,
                        occurred_at=occurred_at,
                    )
                if intent.consumed_run_id is None:
                    dispatched = TutorContinuationDispatcher(
                        conn,
                        settings=get_settings(),
                    ).dispatch_next(
                        user_id=action_request.user_id,
                        conversation_id=response.artifact.conversation_id,
                        claimant_id=f"artifact-route:{response.artifact_event_id}",
                        now=occurred_at,
                    )
                    dispatch_job_id = (
                        dispatched.dispatch_job_id if dispatched is not None else None
                    )
        except LearningArtifactServiceError as exc:
            conn.rollback()
            return _service_error(request, exc)
        except (ExerciseGateServiceError, ReviewServiceError) as exc:
            conn.rollback()
            return _domain_error(request, exc)
        except ContinuationIntentError as exc:
            conn.rollback()
            return _continuation_error(request, exc)
        conn.commit()
    if dispatch_job_id is not None:
        background_tasks.add_task(
            enqueue_tutor_interactive_dispatch,
            dispatch_job_id,
            runtime_kind="harness_v1",
        )
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
    background_tasks: BackgroundTasks,
    user_id: str = Query(min_length=1, max_length=160),
) -> JSONResponse:
    unavailable = _require_tutor_route(request, user_id)
    if unavailable is not None:
        return unavailable
    dispatch_job_id: str | None = None
    with connect() as conn:
        service = build_learning_artifact_service(conn)
        try:
            observation = _observe_artifact_attempt(
                conn=conn,
                service=service,
                user_id=user_id,
                conversation_id=str(conversation_id),
                artifact_id=str(artifact_id),
                attempt_id=str(attempt_id),
                occurred_at=datetime.now(UTC),
            )
            dispatch_job_id = observation.dispatch_job_id
        except LearningArtifactServiceError as exc:
            conn.rollback()
            return _service_error(request, exc)
        except (ExerciseGateServiceError, ReviewServiceError) as exc:
            conn.rollback()
            return _domain_error(request, exc)
        except ContinuationIntentError as exc:
            conn.rollback()
            return _continuation_error(request, exc)
        conn.commit()
    if dispatch_job_id is not None:
        background_tasks.add_task(
            enqueue_tutor_interactive_dispatch,
            dispatch_job_id,
            runtime_kind="harness_v1",
        )
    return _success(observation.detail)


def build_learning_artifact_owner_adapters() -> ArtifactOwnerAdapterRegistry:
    """Return the exact registered owner adapters; no fallback owner exists."""

    return ArtifactOwnerAdapterRegistry(
        (
            LearningItemArtifactOwnerAdapter(),
            TeachingPracticeArtifactOwnerAdapter(),
        )
    )


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


def _observe_artifact_attempt(
    *,
    conn: Connection[dict[str, object]],
    service: LearningArtifactService,
    user_id: str,
    conversation_id: str,
    artifact_id: str,
    attempt_id: str,
    occurred_at: datetime,
) -> _ArtifactAttemptObservation:
    artifact = service.read_artifact(
        user_id=user_id,
        conversation_id=conversation_id,
        artifact_id=artifact_id,
    )
    detail = service.read_attempt_detail(
        user_id=user_id,
        conversation_id=conversation_id,
        artifact_id=artifact_id,
        attempt_id=attempt_id,
    )
    settings = get_settings()
    if (
        artifact.artifact_kind is TutorArtifactKind.TEST_RESULT
        or not settings.tutor_learning_artifacts_enabled
    ):
        return _ArtifactAttemptObservation(detail=detail)
    if detail.status != "terminal":
        if detail.attempt_type == "review_submit":
            ReviewService(conn).observe_artifact_attempt(
                user_id=user_id,
                conversation_id=conversation_id,
                artifact_id=artifact_id,
                attempt_id=attempt_id,
            )
        else:
            ExerciseGateService(conn).observe_artifact_attempt(
                user_id=user_id,
                conversation_id=conversation_id,
                artifact_id=artifact_id,
                attempt_id=attempt_id,
            )
        detail = service.read_attempt_detail(
            user_id=user_id,
            conversation_id=conversation_id,
            artifact_id=artifact_id,
            attempt_id=attempt_id,
        )
    if detail.status != "terminal":
        return _ArtifactAttemptObservation(detail=detail)
    projection = ExecutionResultArtifactProjector(
        conn,
        enabled=lambda: settings.tutor_learning_artifacts_enabled,
        clock=lambda: occurred_at,
    ).project(
        user_id=user_id,
        conversation_id=conversation_id,
        source_artifact_id=artifact_id,
        attempt_id=attempt_id,
    )
    dispatch_job_id: str | None = None
    if settings.tutor_thread_turn_v2_enabled:
        intent = TutorContinuationIntentProducer(conn).record_result_evaluation(
            user_id=user_id,
            conversation_id=conversation_id,
            result_artifact_id=projection.result_artifact.artifact.id,
            result_artifact_event_id=projection.result_artifact.artifact_event_id,
            result_artifact_event_sequence=(
                projection.result_artifact.artifact_event_sequence
            ),
            attempt_id=attempt_id,
            occurred_at=occurred_at,
        )
        if intent.consumed_run_id is None:
            dispatched = TutorContinuationDispatcher(
                conn,
                settings=settings,
            ).dispatch_next(
                user_id=user_id,
                conversation_id=conversation_id,
                claimant_id=(
                    f"result-evaluation:{projection.result_artifact.artifact_event_id}"
                ),
                now=occurred_at,
            )
            dispatch_job_id = (
                dispatched.dispatch_job_id if dispatched is not None else None
            )
    return _ArtifactAttemptObservation(
        detail=service.read_attempt_detail(
            user_id=user_id,
            conversation_id=conversation_id,
            artifact_id=artifact_id,
            attempt_id=attempt_id,
        ),
        dispatch_job_id=dispatch_job_id,
        source_write=projection.source_artifact,
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


def _continuation_error(
    request: Request,
    error: ContinuationIntentError,
) -> JSONResponse:
    if isinstance(error, ContinuationIntentNotFound):
        code = "LEARNING_ARTIFACT_NOT_FOUND"
        message = "Learning Artifact continuation scope was not found."
        status_code = status.HTTP_404_NOT_FOUND
        recoverable = False
    elif isinstance(error, ContinuationIntentConflict) and "idempotency" in str(
        error
    ).casefold():
        code = "IDEMPOTENCY_CONFLICT"
        message = "The continuation identity was reused with a different request."
        status_code = status.HTTP_409_CONFLICT
        recoverable = False
    else:
        assert isinstance(error, (ContinuationIntentConflict, ContinuationIntentStale))
        code = "TEACHING_AUTHORITY_CONFLICT"
        message = "Teaching continuation authority is stale or already claimed."
        status_code = status.HTTP_409_CONFLICT
        recoverable = True
    return error_response(
        request,
        code=code,
        message=message,
        status_code=status_code,
        recoverable=recoverable,
    )


def _domain_error(
    request: Request,
    error: ExerciseGateServiceError | ReviewServiceError,
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
