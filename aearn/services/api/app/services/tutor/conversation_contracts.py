"""Versioned learner-safe contracts for Tutor conversation threads and turns."""
from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


TUTOR_CONVERSATION_EVENT_PROJECTION_VERSION = "tutor_conversation_event_v1"
TUTOR_CONVERSATION_SNAPSHOT_VERSION = "tutor_conversation_snapshot_v1"
TUTOR_CONVERSATION_STREAM_CURSOR_VERSION = 1


class TutorInteractionProtocolVersion(StrEnum):
    LEGACY_V1 = "legacy_v1"
    THREAD_TURN_V2 = "thread_turn_v2"


class TutorPublicTurnStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


class TutorPublicProcessDisplayState(StrEnum):
    THINKING = "thinking"
    WAITING_INPUT = "waiting_input"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_AUTHORITY = "waiting_authority"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    SUPERSEDED = "superseded"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class TutorConversationEventKind(StrEnum):
    TURN_CREATED = "turn_created"
    TURN_UPDATED = "turn_updated"
    ITEM_ADDED = "item_added"
    ITEM_UPDATED = "item_updated"
    CONTROL_UPDATED = "control_updated"
    DISPATCH_DELAYED = "dispatch_delayed"
    DISPATCH_DEAD = "dispatch_dead"


class TutorDispatchJobState(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    RETRY_WAIT = "retry_wait"
    COMPLETED = "completed"
    DEAD = "dead"


class _StrictPublicModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TutorPublicTurn(_StrictPublicModel):
    turn_id: str = Field(min_length=1, max_length=120)
    conversation_id: str = Field(min_length=1, max_length=120)
    interaction_protocol_version: TutorInteractionProtocolVersion
    status: TutorPublicTurnStatus
    retry_of_turn_id: str | None = Field(default=None, min_length=1, max_length=120)
    retry_root_turn_id: str | None = Field(default=None, min_length=1, max_length=120)
    created_at: str = Field(min_length=1, max_length=80)
    updated_at: str = Field(min_length=1, max_length=80)


class TutorPublicProcessStep(_StrictPublicModel):
    key: str = Field(min_length=1, max_length=120)
    state: Literal["completed", "current"]
    label: str = Field(min_length=1, max_length=160)


class TutorPublicMessageItem(_StrictPublicModel):
    kind: Literal["message"]
    id: str = Field(min_length=1, max_length=120)
    turn_id: str | None = Field(default=None, min_length=1, max_length=120)
    role: Literal["learner", "tutor"]
    content: str = Field(max_length=16_000)
    public_thinking_steps: list[str] = Field(default_factory=list, max_length=4)
    context_references: list[dict[str, object]] = Field(default_factory=list, max_length=6)
    created_at: str = Field(min_length=1, max_length=80)


class TutorPublicProcessItem(_StrictPublicModel):
    kind: Literal["process"]
    id: str = Field(min_length=1, max_length=120)
    turn_id: str = Field(min_length=1, max_length=120)
    run_id: str = Field(min_length=1, max_length=120)
    display_state: TutorPublicProcessDisplayState
    steps: list[TutorPublicProcessStep] = Field(default_factory=list, max_length=16)
    elapsed_seconds: int = Field(ge=0, le=3_600)
    created_at: str = Field(min_length=1, max_length=80)
    finished_at: str | None = Field(default=None, min_length=1, max_length=80)


class TutorPublicElicitationItem(_StrictPublicModel):
    kind: Literal["elicitation"]
    id: str = Field(min_length=1, max_length=120)
    turn_id: str = Field(min_length=1, max_length=120)
    state: Literal["pending", "resolved", "cancelled"]
    prompt: str = Field(min_length=1, max_length=1_200)
    created_at: str = Field(min_length=1, max_length=80)


class TutorPublicApprovalItem(_StrictPublicModel):
    kind: Literal["approval"]
    id: str = Field(min_length=1, max_length=120)
    turn_id: str = Field(min_length=1, max_length=120)
    state: Literal["pending", "approved", "declined", "cancelled"]
    prompt: str = Field(min_length=1, max_length=1_200)
    created_at: str = Field(min_length=1, max_length=80)


class TutorPublicErrorItem(_StrictPublicModel):
    kind: Literal["error"]
    id: str = Field(min_length=1, max_length=120)
    turn_id: str | None = Field(default=None, min_length=1, max_length=120)
    code: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=400)
    recoverable: bool
    created_at: str = Field(min_length=1, max_length=80)


TutorPublicItem = Annotated[
    TutorPublicMessageItem
    | TutorPublicProcessItem
    | TutorPublicElicitationItem
    | TutorPublicApprovalItem
    | TutorPublicErrorItem,
    Field(discriminator="kind"),
]
_TUTOR_PUBLIC_ITEM_ADAPTER: TypeAdapter[TutorPublicItem] = TypeAdapter(TutorPublicItem)


class TutorPublicItemReference(_StrictPublicModel):
    item_id: str = Field(min_length=1, max_length=120)
    item_kind: Literal["message", "process", "elicitation", "approval", "error"]
    turn_id: str | None = Field(default=None, min_length=1, max_length=120)


class TutorTurnEventPayload(_StrictPublicModel):
    turn: TutorPublicTurn


class TutorItemEventPayload(_StrictPublicModel):
    item: TutorPublicItemReference


class TutorControlEventPayload(_StrictPublicModel):
    control_version: int = Field(ge=1)


class TutorDispatchEventPayload(_StrictPublicModel):
    code: Literal["TUTOR_DISPATCH_DELAYED", "TUTOR_DISPATCH_FAILED"]
    recoverable: bool
    attempt: int = Field(ge=1, le=100)


_EVENT_PAYLOAD_ADAPTERS: Mapping[TutorConversationEventKind, TypeAdapter[object]] = {
    TutorConversationEventKind.TURN_CREATED: TypeAdapter(TutorTurnEventPayload),
    TutorConversationEventKind.TURN_UPDATED: TypeAdapter(TutorTurnEventPayload),
    TutorConversationEventKind.ITEM_ADDED: TypeAdapter(TutorItemEventPayload),
    TutorConversationEventKind.ITEM_UPDATED: TypeAdapter(TutorItemEventPayload),
    TutorConversationEventKind.CONTROL_UPDATED: TypeAdapter(TutorControlEventPayload),
    TutorConversationEventKind.DISPATCH_DELAYED: TypeAdapter(TutorDispatchEventPayload),
    TutorConversationEventKind.DISPATCH_DEAD: TypeAdapter(TutorDispatchEventPayload),
}


def validate_public_item(payload: object) -> dict[str, object]:
    item = _TUTOR_PUBLIC_ITEM_ADAPTER.validate_python(payload)
    dumped = item.model_dump(mode="json", exclude_none=False)
    return dict(dumped)


def validate_conversation_event_payload(
    kind: TutorConversationEventKind | str,
    payload: object,
) -> dict[str, object]:
    normalized_kind = TutorConversationEventKind(str(kind))
    validated = _EVENT_PAYLOAD_ADAPTERS[normalized_kind].validate_python(payload)
    if not isinstance(validated, BaseModel):
        raise TypeError("conversation event payload did not produce a model")
    return dict(validated.model_dump(mode="json", exclude_none=True))


def public_turn_status(*, terminal_outcome: str | None, cancelled: bool, superseded: bool) -> TutorPublicTurnStatus:
    if terminal_outcome == "completed":
        return TutorPublicTurnStatus.COMPLETED
    if terminal_outcome == "cancelled" or cancelled or superseded:
        return TutorPublicTurnStatus.INTERRUPTED
    if terminal_outcome is not None:
        return TutorPublicTurnStatus.FAILED
    return TutorPublicTurnStatus.IN_PROGRESS
