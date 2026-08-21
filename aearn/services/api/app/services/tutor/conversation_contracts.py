"""Versioned learner-safe contracts for Tutor conversation threads and turns."""
from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.agents.harness.contracts import MAX_TUTOR_PUBLIC_THINKING_TEXT_LENGTH
from app.services.tutor.public_thinking_stream import PUBLIC_THINKING_CHUNK_MAX_LENGTH


TUTOR_CONVERSATION_EVENT_PROJECTION_VERSION = "tutor_conversation_event_v2"
TUTOR_CONVERSATION_SNAPSHOT_VERSION = "tutor_conversation_snapshot_v3"
TUTOR_CONVERSATION_STREAM_CURSOR_VERSION = 2
TUTOR_PUBLIC_THINKING_STREAM_VERSION = "tutor_public_thinking_stream_v1"
TUTOR_RUNTIME_ITEM_STREAM_VERSION = "tutor_runtime_item_stream_v1"
TUTOR_RUNTIME_OUTPUT_VERSION = "tutor_runtime_output_v1"


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
    TURN_OUTPUT = "turn_output"
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
    input_revision: int = Field(default=0, ge=0)
    retry_of_turn_id: str | None = Field(default=None, min_length=1, max_length=120)
    retry_root_turn_id: str | None = Field(default=None, min_length=1, max_length=120)
    completion_reason: Literal["awaiting_user", "awaiting_approval", "awaiting_authority"] | None = None
    created_at: str = Field(min_length=1, max_length=80)
    updated_at: str = Field(min_length=1, max_length=80)


class TutorPublicProcessStep(_StrictPublicModel):
    key: str = Field(min_length=1, max_length=120)
    state: Literal["completed", "current"]
    label: str = Field(min_length=1, max_length=160)


class TutorRuntimeOutputItem(_StrictPublicModel):
    item_id: str = Field(min_length=1, max_length=120)
    text: str = Field(max_length=1_000_000)
    state: Literal["streaming", "completed"]
    last_sequence: int = Field(ge=0)


class TutorRuntimeOutput(_StrictPublicModel):
    output_version: Literal["tutor_runtime_output_v1"]
    input_revision: int = Field(ge=0)
    generation: int = Field(ge=1)
    reasoning_items: list[TutorRuntimeOutputItem] = Field(default_factory=list, max_length=64)
    final_answer_item: TutorRuntimeOutputItem | None = None


class TutorPublicMessageItem(_StrictPublicModel):
    kind: Literal["message"]
    id: str = Field(min_length=1, max_length=120)
    turn_id: str | None = Field(default=None, min_length=1, max_length=120)
    role: Literal["learner", "tutor"]
    content: str = Field(max_length=16_000)
    public_thinking_text: str = Field(default="", max_length=MAX_TUTOR_PUBLIC_THINKING_TEXT_LENGTH)
    public_thinking_steps: list[str] = Field(default_factory=list, max_length=4)
    runtime_output: TutorRuntimeOutput | None = None
    context_references: list[dict[str, object]] = Field(default_factory=list, max_length=6)
    in_reply_to_item_id: str | None = Field(default=None, min_length=1, max_length=120)
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


class TutorPublicOption(_StrictPublicModel):
    value: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=160)


class TutorPublicTextPresentation(_StrictPublicModel):
    type: Literal["text"]
    field_key: str | None = Field(default=None, min_length=1, max_length=120)
    minimum_length: int = Field(ge=1, le=16_000)
    maximum_length: int = Field(ge=1, le=16_000)
    multiline: bool


class TutorPublicIntegerPresentation(_StrictPublicModel):
    type: Literal["integer"]
    field_key: str = Field(min_length=1, max_length=120)
    minimum: int
    maximum: int
    step: int = Field(ge=1)
    recommended: int | None = None
    unit: str = Field(min_length=1, max_length=80)


class TutorPublicSingleSelectPresentation(_StrictPublicModel):
    type: Literal["single_select"]
    field_key: str = Field(min_length=1, max_length=120)
    options: list[TutorPublicOption] = Field(min_length=1, max_length=24)
    recommended: str | None = Field(default=None, min_length=1, max_length=120)
    selection_scope: Literal[
        "explicit_shortlist",
        "intent_shortlist",
        "conflict_shortlist",
        "full_catalog",
    ] | None = None
    selection_reason_code: str | None = Field(default=None, min_length=1, max_length=120)
    intent_policy_version: str | None = Field(default=None, min_length=1, max_length=160)


class TutorPublicMultiSelectPresentation(_StrictPublicModel):
    type: Literal["multi_select"]
    field_key: str = Field(min_length=1, max_length=120)
    options: list[TutorPublicOption] = Field(min_length=1, max_length=24)
    recommended: list[str] = Field(default_factory=list, max_length=4)
    maximum_selections: int = Field(ge=1, le=4)


class TutorPublicApprovalPresentation(_StrictPublicModel):
    type: Literal["approval"]
    proposal_id: str = Field(min_length=1, max_length=160)
    authority_key: str = Field(min_length=1, max_length=160)
    risk_level: Literal["low", "medium", "high"]
    summary: str = Field(min_length=1, max_length=1_200)


TutorPublicRequestPresentation = Annotated[
    TutorPublicTextPresentation
    | TutorPublicIntegerPresentation
    | TutorPublicSingleSelectPresentation
    | TutorPublicMultiSelectPresentation
    | TutorPublicApprovalPresentation,
    Field(discriminator="type"),
]


class TutorPublicElicitationItem(_StrictPublicModel):
    kind: Literal["elicitation"]
    id: str = Field(min_length=1, max_length=120)
    request_id: str = Field(min_length=1, max_length=120)
    turn_id: str = Field(min_length=1, max_length=120)
    request_kind: Literal["clarification", "planning_input", "capability_result", "external_result"]
    actor: Literal["learner", "authority"]
    state: Literal["pending", "answered", "cancelled", "expired"]
    version: int = Field(ge=1)
    required: Literal[True]
    prompt: str = Field(min_length=1, max_length=1_200)
    public_thinking_text: str = Field(default="", max_length=MAX_TUTOR_PUBLIC_THINKING_TEXT_LENGTH)
    presentation: TutorPublicRequestPresentation
    allowed_actions: list[Literal["respond"]] = Field(default_factory=list, max_length=1)
    answer_turn_id: str | None = Field(default=None, min_length=1, max_length=120)
    created_at: str = Field(min_length=1, max_length=80)
    resolved_at: str | None = Field(default=None, min_length=1, max_length=80)


class TutorPublicApprovalItem(_StrictPublicModel):
    kind: Literal["approval"]
    id: str = Field(min_length=1, max_length=120)
    request_id: str = Field(min_length=1, max_length=120)
    turn_id: str = Field(min_length=1, max_length=120)
    request_kind: Literal["approval"]
    actor: Literal["learner"]
    state: Literal["pending", "answered", "denied", "cancelled", "expired"]
    version: int = Field(ge=1)
    required: Literal[True]
    prompt: str = Field(min_length=1, max_length=1_200)
    public_thinking_text: str = Field(default="", max_length=MAX_TUTOR_PUBLIC_THINKING_TEXT_LENGTH)
    presentation: TutorPublicApprovalPresentation
    allowed_actions: list[Literal["approve", "deny"]] = Field(default_factory=list, max_length=2)
    answer_turn_id: str | None = Field(default=None, min_length=1, max_length=120)
    created_at: str = Field(min_length=1, max_length=80)
    resolved_at: str | None = Field(default=None, min_length=1, max_length=80)


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


class TutorTurnOutputAppendPayload(_StrictPublicModel):
    output_version: Literal["tutor_public_thinking_stream_v1"]
    input_revision: int = Field(ge=0)
    generation: int = Field(ge=1)
    operation: Literal["append"]
    chunk_sequence: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=PUBLIC_THINKING_CHUNK_MAX_LENGTH)


class TutorTurnOutputStatePayload(_StrictPublicModel):
    output_version: Literal["tutor_public_thinking_stream_v1"]
    input_revision: int = Field(ge=0)
    generation: int = Field(ge=1)
    operation: Literal["reset", "complete", "discard"]
    chunk_sequence: int = Field(ge=0)


class TutorRuntimeItemAppendPayload(_StrictPublicModel):
    output_version: Literal["tutor_runtime_item_stream_v1"]
    input_revision: int = Field(ge=0)
    generation: int = Field(ge=1)
    operation: Literal["append"]
    chunk_sequence: int = Field(ge=1)
    item_id: str = Field(min_length=1, max_length=120)
    channel: Literal["reasoning", "final_answer"]
    text: str = Field(min_length=1, max_length=16_000)


class TutorRuntimeItemCompletePayload(_StrictPublicModel):
    output_version: Literal["tutor_runtime_item_stream_v1"]
    input_revision: int = Field(ge=0)
    generation: int = Field(ge=1)
    operation: Literal["complete"]
    chunk_sequence: int = Field(ge=1)
    item_id: str = Field(min_length=1, max_length=120)
    channel: Literal["reasoning", "final_answer"]
    text: str = Field(max_length=1_000_000)


class TutorRuntimeItemStatePayload(_StrictPublicModel):
    output_version: Literal["tutor_runtime_item_stream_v1"]
    input_revision: int = Field(ge=0)
    generation: int = Field(ge=1)
    operation: Literal["reset", "discard"]
    chunk_sequence: int = Field(ge=0)
    item_id: str = Field(min_length=1, max_length=120)
    channel: Literal["reasoning", "final_answer"]


TutorTurnOutputPayload = (
    TutorTurnOutputAppendPayload
    | TutorTurnOutputStatePayload
    | TutorRuntimeItemAppendPayload
    | TutorRuntimeItemCompletePayload
    | TutorRuntimeItemStatePayload
)


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
    TutorConversationEventKind.TURN_OUTPUT: TypeAdapter(TutorTurnOutputPayload),
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
