from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Callable
from typing import TypeVar

from fastapi import APIRouter, BackgroundTasks, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.config import get_settings
from app.core.errors import error_response, request_id_from
from app.db.connection import connect
from app.models.tutor import (
    CorrectTutorMemoryRequest,
    CreateTutorConversationRequest,
    TutorInputRequest,
    TutorMutationRequest,
    UpdateTutorPreferencesRequest,
)
from app.services.streaming.sse import sse_event, stream_response
from app.services.tutor.interactive import TutorRunDispatcher, build_tutor_run_dispatcher
from app.services.tutor.cutover import runtime_gate_error
from app.services.tutor.public_api import TutorPublicApiError, TutorPublicService, TutorPublicSseEvent


router = APIRouter(prefix="/api/tutor", tags=["tutor"])
T = TypeVar("T")
logger = logging.getLogger(__name__)


@router.post("/conversations/first-turn", response_model=None)
def create_first_conversation_turn(
    payload: TutorInputRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    """Atomically create a draft conversation and its first finite TurnRun."""

    unavailable = _require_tutor_route(request, payload.user_id)
    if unavailable is not None:
        return unavailable
    response = _call_service(
        request,
        lambda service: service.accept_first_turn(
            user_id=payload.user_id,
            content=payload.content,
            idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
        commit=True,
    )
    if isinstance(response, JSONResponse):
        return response
    _schedule_interactive_dispatch(
        background_tasks=background_tasks,
        dispatcher=build_tutor_run_dispatcher(get_settings()),
        user_id=payload.user_id,
        response=response,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK if bool(response.get("idempotent_replayed")) else status.HTTP_202_ACCEPTED,
        content=jsonable_encoder(response),
    )


@router.get("/conversations", response_model=None)
def list_conversations(
    request: Request,
    user_id: str = Query(min_length=1),
    limit: int = Query(default=8, ge=1, le=40),
    cursor: str | None = Query(default=None, min_length=1, max_length=2048),
) -> JSONResponse:
    unavailable = _require_tutor_route(request, user_id)
    if unavailable is not None:
        return unavailable
    response = _call_service(
        request,
        lambda service: service.list_conversations(user_id=user_id, limit=limit, cursor=cursor),
    )
    return response if isinstance(response, JSONResponse) else JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(response))


@router.get("/conversations/{conversation_id}/history", response_model=None)
def read_conversation_history(
    conversation_id: str,
    request: Request,
    user_id: str = Query(min_length=1),
    limit: int = Query(default=40, ge=1, le=40),
    cursor: str | None = Query(default=None, min_length=1, max_length=2048),
) -> JSONResponse:
    unavailable = _require_tutor_route(request, user_id)
    if unavailable is not None:
        return unavailable
    response = _call_service(
        request,
        lambda service: service.read_conversation_history(
            user_id=user_id,
            conversation_id=conversation_id,
            limit=limit,
            cursor=cursor,
        ),
    )
    return response if isinstance(response, JSONResponse) else JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(response))


@router.post("/conversations", response_model=None)
def create_or_resume_conversation(
    payload: CreateTutorConversationRequest,
    request: Request,
) -> JSONResponse:
    unavailable = _require_tutor_route(request, payload.user_id)
    if unavailable is not None:
        return unavailable
    response = _call_service(
        request,
        lambda service: service.create_or_resume_conversation(
            user_id=payload.user_id,
            conversation_id=payload.conversation_id,
            idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
        commit=True,
    )
    if isinstance(response, JSONResponse):
        return response
    status_code = (
        status.HTTP_200_OK
        if bool(response.get("idempotent_replayed")) or not bool(response.get("created"))
        else status.HTTP_201_CREATED
    )
    return JSONResponse(status_code=status_code, content=jsonable_encoder(response))


@router.post("/conversations/{conversation_id}/inputs", response_model=None)
def create_conversation_input(
    conversation_id: str,
    payload: TutorInputRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    unavailable = _require_tutor_route(request, payload.user_id)
    if unavailable is not None:
        return unavailable
    response = _call_service(
        request,
        lambda service: service.accept_conversation_input(
            user_id=payload.user_id,
            conversation_id=conversation_id,
            content=payload.content,
            idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
        commit=True,
    )
    if isinstance(response, JSONResponse):
        return response
    _schedule_interactive_dispatch(
        background_tasks=background_tasks,
        dispatcher=build_tutor_run_dispatcher(get_settings()),
        user_id=payload.user_id,
        response=response,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK if bool(response.get("idempotent_replayed")) else status.HTTP_202_ACCEPTED,
        content=jsonable_encoder(response),
    )


@router.post("/runs/{run_id}/inputs", response_model=None)
def create_run_input(
    run_id: str,
    payload: TutorInputRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    unavailable = _require_tutor_route(request, payload.user_id)
    if unavailable is not None:
        return unavailable
    response = _call_service(
        request,
        lambda service: service.accept_run_input(
            user_id=payload.user_id,
            run_id=run_id,
            content=payload.content,
            idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
        commit=True,
    )
    if isinstance(response, JSONResponse):
        return response
    _schedule_interactive_dispatch(
        background_tasks=background_tasks,
        dispatcher=build_tutor_run_dispatcher(get_settings()),
        user_id=payload.user_id,
        response=response,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK if bool(response.get("idempotent_replayed")) else status.HTTP_202_ACCEPTED,
        content=jsonable_encoder(response),
    )


@router.get("/runs/{run_id}", response_model=None)
def read_run(
    run_id: str,
    request: Request,
    user_id: str = Query(min_length=1),
) -> JSONResponse:
    unavailable = _require_tutor_route(request, user_id)
    if unavailable is not None:
        return unavailable
    response = _call_service(request, lambda service: service.read_run(user_id=user_id, run_id=run_id))
    return response if isinstance(response, JSONResponse) else JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(response))


@router.get("/runs/{run_id}/events", response_model=None)
async def stream_run_events(
    run_id: str,
    request: Request,
    user_id: str = Query(min_length=1),
) -> JSONResponse | StreamingResponse:
    unavailable = _require_tutor_route(request, user_id)
    if unavailable is not None:
        return unavailable
    try:
        after_sequence = _parse_last_event_id(request.headers.get("Last-Event-ID"))
    except TutorPublicApiError as exc:
        return _public_error(request, exc)

    preflight = _call_service(request, lambda service: service.read_run(user_id=user_id, run_id=run_id))
    if isinstance(preflight, JSONResponse):
        return preflight
    return stream_response(
        _event_stream(
            request=request,
            user_id=user_id,
            run_id=run_id,
            after_sequence=after_sequence,
        )
    )


@router.get("/activity", response_model=None)
def list_activity(
    request: Request,
    user_id: str = Query(min_length=1),
    limit: int = Query(default=50, ge=1, le=100),
) -> JSONResponse:
    unavailable = _require_tutor_route(request, user_id)
    if unavailable is not None:
        return unavailable
    response = _call_service(request, lambda service: service.list_activity(user_id=user_id, limit=limit))
    return response if isinstance(response, JSONResponse) else JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(response))


@router.get("/inbox", response_model=None)
def list_inbox(
    request: Request,
    user_id: str = Query(min_length=1),
    include_dismissed: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=100),
) -> JSONResponse:
    unavailable = _require_tutor_route(request, user_id)
    if unavailable is not None:
        return unavailable
    response = _call_service(
        request,
        lambda service: service.list_inbox(
            user_id=user_id,
            include_dismissed=include_dismissed,
            limit=limit,
        ),
    )
    return response if isinstance(response, JSONResponse) else JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(response))


@router.post("/inbox/{inbox_id}/read", response_model=None)
def mark_inbox_read(
    inbox_id: str,
    payload: TutorMutationRequest,
    request: Request,
) -> JSONResponse:
    unavailable = _require_tutor_route(request, payload.user_id)
    if unavailable is not None:
        return unavailable
    response = _call_service(
        request,
        lambda service: service.mark_inbox_read(
            user_id=payload.user_id,
            inbox_id=inbox_id,
            idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
        commit=True,
    )
    return response if isinstance(response, JSONResponse) else JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(response))


@router.post("/inbox/{inbox_id}/dismiss", response_model=None)
def dismiss_inbox(
    inbox_id: str,
    payload: TutorMutationRequest,
    request: Request,
) -> JSONResponse:
    unavailable = _require_tutor_route(request, payload.user_id)
    if unavailable is not None:
        return unavailable
    response = _call_service(
        request,
        lambda service: service.dismiss_inbox(
            user_id=payload.user_id,
            inbox_id=inbox_id,
            idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
        commit=True,
    )
    return response if isinstance(response, JSONResponse) else JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(response))


@router.get("/memory", response_model=None)
def list_memory(
    request: Request,
    user_id: str = Query(min_length=1),
    include_inactive: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=100),
) -> JSONResponse:
    unavailable = _require_tutor_route(request, user_id)
    if unavailable is not None:
        return unavailable
    response = _call_service(
        request,
        lambda service: service.list_memory(
            user_id=user_id,
            include_inactive=include_inactive,
            limit=limit,
        ),
    )
    return response if isinstance(response, JSONResponse) else JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(response))


@router.patch("/memory/{entry_id}", response_model=None)
def correct_memory(
    entry_id: str,
    payload: CorrectTutorMemoryRequest,
    request: Request,
) -> JSONResponse:
    unavailable = _require_tutor_route(request, payload.user_id)
    if unavailable is not None:
        return unavailable
    response = _call_service(
        request,
        lambda service: service.correct_memory(
            user_id=payload.user_id,
            entry_id=entry_id,
            statement=payload.statement,
            idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
        commit=True,
    )
    return response if isinstance(response, JSONResponse) else JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(response))


@router.delete("/memory/{entry_id}", response_model=None)
def delete_memory(
    entry_id: str,
    payload: TutorMutationRequest,
    request: Request,
) -> JSONResponse:
    unavailable = _require_tutor_route(request, payload.user_id)
    if unavailable is not None:
        return unavailable
    response = _call_service(
        request,
        lambda service: service.delete_memory(
            user_id=payload.user_id,
            entry_id=entry_id,
            idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
        commit=True,
    )
    return response if isinstance(response, JSONResponse) else JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(response))


@router.get("/plans/revisions", response_model=None)
def list_plan_revisions(
    request: Request,
    user_id: str = Query(min_length=1),
    limit: int = Query(default=50, ge=1, le=100),
) -> JSONResponse:
    unavailable = _require_tutor_route(request, user_id)
    if unavailable is not None:
        return unavailable
    response = _call_service(request, lambda service: service.list_plan_revisions(user_id=user_id, limit=limit))
    return response if isinstance(response, JSONResponse) else JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(response))


@router.post("/plans/rollback", response_model=None)
def rollback_plan(
    payload: TutorMutationRequest,
    request: Request,
) -> JSONResponse:
    unavailable = _require_tutor_route(request, payload.user_id)
    if unavailable is not None:
        return unavailable
    response = _call_service(
        request,
        lambda service: service.rollback_plan(
            user_id=payload.user_id,
            idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
        commit=True,
    )
    return response if isinstance(response, JSONResponse) else JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(response))


@router.get("/preferences", response_model=None)
def read_preferences(
    request: Request,
    user_id: str = Query(min_length=1),
) -> JSONResponse:
    unavailable = _require_tutor_route(request, user_id)
    if unavailable is not None:
        return unavailable
    response = _call_service(request, lambda service: service.read_preferences(user_id=user_id))
    return response if isinstance(response, JSONResponse) else JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(response))


@router.patch("/preferences", response_model=None)
def update_preferences(
    payload: UpdateTutorPreferencesRequest,
    request: Request,
) -> JSONResponse:
    unavailable = _require_tutor_route(request, payload.user_id)
    if unavailable is not None:
        return unavailable
    response = _call_service(
        request,
        lambda service: service.update_preferences(
            user_id=payload.user_id,
            inferred_memory_enabled=payload.inferred_memory_enabled,
            expected_memory_setting_version=payload.expected_memory_setting_version,
            proactive_paused=payload.proactive_paused,
            idempotency_key=_idempotency_key(request, payload.client_action_id),
        ),
        commit=True,
    )
    return response if isinstance(response, JSONResponse) else JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(response))


async def _event_stream(
    *,
    request: Request,
    user_id: str,
    run_id: str,
    after_sequence: int,
) -> AsyncGenerator[str, None]:
    cursor = after_sequence
    request_id = request_id_from(request)
    while True:
        try:
            with connect() as conn:
                service = TutorPublicService(conn, settings=get_settings())
                events = service.replay_events(
                    user_id=user_id,
                    run_id=run_id,
                    after_sequence=cursor,
                    limit=100,
                )
                state = service.read_run(user_id=user_id, run_id=run_id)
        except TutorPublicApiError as exc:
            yield _sse_error_frame(request_id=request_id, error=exc)
            return

        for event in events:
            yield _sse_frame(request_id=request_id, event=event)
            cursor = event.sequence
            if event.terminal:
                return

        if state.get("terminal_outcome") is not None:
            return
        if await request.is_disconnected():
            return
        await asyncio.sleep(0.25)


def _sse_frame(*, request_id: str, event: TutorPublicSseEvent) -> str:
    data = dict(event.data)
    if event.event_type == "error":
        error = data.get("error")
        if isinstance(error, dict):
            error.setdefault("request_id", request_id)
    else:
        data.setdefault("request_id", request_id)
    return sse_event(event.event_type, data, event_id=str(event.sequence))


def _sse_error_frame(*, request_id: str, error: TutorPublicApiError) -> str:
    return sse_event(
        "error",
        {
            "error": {
                "code": error.code,
                "message": error.message,
                "details": error.details,
                "request_id": request_id,
                "recoverable": error.recoverable,
            }
        },
    )


def _parse_last_event_id(value: str | None) -> int:
    if value is None or not value.strip():
        return 0
    normalized = value.strip()
    if not normalized.isdecimal():
        raise TutorPublicApiError(
            "SSE_CURSOR_INVALID",
            "Last-Event-ID must be a non-negative decimal run cursor.",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"last_event_id": normalized[:160]},
        )
    return int(normalized)


def _require_tutor_route(request: Request, user_id: str) -> JSONResponse | None:
    gate_error = runtime_gate_error(user_id=user_id)
    if gate_error is not None:
        return error_response(
            request,
            code=gate_error.code,
            message=gate_error.message,
            status_code=gate_error.status_code,
            details=gate_error.details,
            recoverable=gate_error.recoverable,
        )
    return None


def _idempotency_key(request: Request, fallback: str) -> str:
    return request.headers.get("Idempotency-Key", fallback)


def _schedule_interactive_dispatch(
    *,
    background_tasks: BackgroundTasks,
    dispatcher: TutorRunDispatcher,
    user_id: str,
    response: dict[str, object],
) -> None:
    """Start only newly accepted inputs after their transaction has committed."""

    if bool(response.get("idempotent_replayed")):
        return
    run_id = response.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        return
    background_tasks.add_task(_dispatch_interactive_run, dispatcher, user_id, run_id)


def _dispatch_interactive_run(dispatcher: TutorRunDispatcher, user_id: str, run_id: str) -> None:
    """Keep post-response failures out of the learner-facing accepted-input reply."""

    try:
        dispatcher.dispatch(user_id=user_id, run_id=run_id)
    except Exception:
        logger.exception("Tutor interactive dispatcher failed for run_id=%s", run_id)


def _call_service(
    request: Request,
    action: Callable[[TutorPublicService], dict[str, object]],
    *,
    commit: bool = False,
) -> dict[str, object] | JSONResponse:
    with connect() as conn:
        service = TutorPublicService(conn, settings=get_settings())
        try:
            response = action(service)
        except TutorPublicApiError as exc:
            conn.rollback()
            return _public_error(request, exc)
        if commit:
            conn.commit()
    return response


def _public_error(request: Request, error: TutorPublicApiError) -> JSONResponse:
    return error_response(
        request,
        code=error.code,
        message=error.message,
        status_code=error.status_code,
        details=error.details,
        recoverable=error.recoverable,
    )
