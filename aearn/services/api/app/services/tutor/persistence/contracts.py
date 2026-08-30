"""Tutor PostgreSQL persistence 的异常、记录与 acceptance contracts。"""
# ruff: noqa: F403, F405
from __future__ import annotations

from ._dependencies import *

def _safe_key(value: str, *, label: str) -> None:
    if not _SAFE_KEY.fullmatch(value):
        raise ValueError(f"{label} must be a stable bounded identifier")


class TutorPersistenceError(ValueError):
    """Base error with intentionally safe, stable messages."""


class TutorRunNotFound(TutorPersistenceError):
    pass


class TutorIdempotencyConflict(TutorPersistenceError):
    pass


class TutorTerminalStateConflict(TutorPersistenceError):
    pass


class TutorLeaseConflict(TutorPersistenceError):
    pass


class TutorCatalogEvidenceError(TutorPersistenceError):
    pass


class TutorCursorInvalid(TutorPersistenceError):
    pass


class TutorInteractionRequestConflict(TutorPersistenceError):
    pass


class TutorInteractionRequestNotFound(TutorPersistenceError):
    pass


@dataclass(frozen=True)
class TutorDurableEvent:
    event_id: str
    run_id: str
    event_sequence: int
    event_key: str
    kind: str
    input_revision: int
    payload: dict[str, object]
    created_at: datetime


@dataclass(frozen=True)
class TutorInputAcceptance:
    run_id: str
    message_id: str
    input_revision: int
    event: TutorDurableEvent
    replayed: bool
    dispatch_job_id: str | None = None


@dataclass(frozen=True)
class TutorRunReadState:
    """Learner-safe run lifecycle facts for the Child 06 public adapter."""

    snapshot: TutorRunSnapshot
    terminal_outcome: TutorTerminalOutcome | None
    diagnostic_code: str | None
    created_at: datetime
    updated_at: datetime
    interaction_protocol_version: TutorInteractionProtocolVersion = TutorInteractionProtocolVersion.LEGACY_V1
    retry_of_turn_id: str | None = None
    retry_root_turn_id: str | None = None
    response_to_request_id: str | None = None
    completion_reason: TutorTurnCompletionReason | None = None


@dataclass(frozen=True)
class TutorPublicProcessState:
    """Server-owned public process projection; never contains trace/provider data."""

    run_id: str
    conversation_id: str
    display_state: str
    steps: tuple[dict[str, object], ...]
    elapsed_seconds: int
    created_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True)
class TutorConversationSummary:
    conversation_id: str
    title: str | None
    last_public_activity_at: datetime
    active_run_id: str | None
    active_run_status: str | None
    active_run_continuation_kind: TutorContinuationKind | None


@dataclass(frozen=True)
class TutorQueuedInput:
    item_id: str
    user_id: str
    conversation_id: str
    content: str
    state: str
    position: int
    version: int
    claimed_turn_id: str | None
    claimed_input_revision: int | None
    claimed_mode: str | None
    created_at: datetime
    updated_at: datetime

    def as_public_dict(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "state": self.state,
            "position": self.position,
            "version": self.version,
            "content": self.content,
            "created_at": self.created_at.astimezone(UTC).isoformat(),
            "updated_at": self.updated_at.astimezone(UTC).isoformat(),
        }


@dataclass(frozen=True)
class TutorQueueAcceptance:
    turn: "TutorInteractiveTurnAcceptance" | None
    queued_item: TutorQueuedInput | None
    control_version: int


@dataclass(frozen=True)
class TutorInteractionRequestRecord:
    request_id: str
    item_id: str
    user_id: str
    conversation_id: str
    source_turn_id: str
    kind: TutorInteractionRequestKind
    actor: TutorInteractionRequestActor
    state: TutorInteractionRequestState
    version: int
    schema_version: str
    catalog_version: str | None
    question_key: str | None
    descriptor: dict[str, object]
    presentation: dict[str, object]
    answer_turn_id: str | None
    answer_message_id: str | None
    created_at: datetime
    resolved_at: datetime | None
    public_item: dict[str, object]


@dataclass(frozen=True)
class TutorInteractionResponseAcceptance:
    request: TutorInteractionRequestRecord
    turn: "TutorInteractiveTurnAcceptance" | None
    planning_facts: dict[str, object]
    replayed: bool


@dataclass(frozen=True)
class TutorInteractiveTurnAcceptance:
    """Atomic fresh-run acceptance for a normal learner turn."""

    run: TutorRunSnapshot
    acceptance: TutorInputAcceptance
    replaced_run_id: str | None
    process: TutorPublicProcessState | None
    replaced_process: TutorPublicProcessState | None


@dataclass(frozen=True)
class TutorPublicForegroundRun:
    """Minimal server-authoritative foreground run projection for one conversation."""

    run_id: str
    status: str
    continuation_kind: TutorContinuationKind | None


@dataclass(frozen=True)
class TutorConversationTimelineRecord:
    """One server-authoritative public timeline row before route serialization."""

    kind: str
    item_id: str
    created_at: datetime
    sort_rank: int
    role: str | None = None
    content: str | None = None
    public_thinking_text: str = ""
    public_thinking_steps: tuple[str, ...] = ()
    runtime_output: dict[str, object] | None = None
    context_references: tuple[dict[str, object], ...] = ()
    process: TutorPublicProcessState | None = None
    turn_id: str | None = None
    error_code: str | None = None
    error_recoverable: bool = False
    in_reply_to_item_id: str | None = None
    request: TutorInteractionRequestRecord | None = None


@dataclass(frozen=True)
class TutorConversationEvent:
    event_id: str
    conversation_id: str
    sequence: int
    event_key: str
    kind: TutorConversationEventKind
    turn_id: str | None
    item_id: str | None
    item_kind: str | None
    payload: dict[str, object]
    occurred_at: datetime
    cursor: str


@dataclass(frozen=True)
class TutorInteractiveDispatchJob:
    job_id: str
    run_id: str
    user_id: str
    conversation_id: str
    state: TutorDispatchJobState
    attempt_count: int
    max_attempts: int
    available_at: datetime
    lease_owner_id: str | None
    lease_generation: int
    lease_expires_at: datetime | None
    last_error_code: str | None
    completed_at: datetime | None
    dead_at: datetime | None


@dataclass(frozen=True)
class TutorConversationSnapshot:
    conversation_id: str
    title: str | None
    control_version: int
    control_state: str
    queue_paused: bool
    queue_pause_reason: str | None
    pending_count: int
    max_pending: int
    active_turn: dict[str, object] | None
    active_thinking: dict[str, object] | None
    active_runtime_output: dict[str, object] | None
    pending_requests: tuple[dict[str, object], ...]
    queue: tuple[dict[str, object], ...]
    timeline: tuple[TutorConversationTimelineRecord, ...]
    next_cursor: str | None
    has_more: bool
    stream_cursor: str
    snapshot_version: str = TUTOR_CONVERSATION_SNAPSHOT_VERSION


@dataclass(frozen=True)
class TutorSkillSelectionEvidence:
    run_id: str
    input_revision: int
    skill_id: str
    skill_version: str
    manifest_hash: str
    instruction_hash: str
    evaluation_hash: str
    event: TutorDurableEvent
    replayed: bool


@dataclass(frozen=True)
class TutorCapabilityInvocationReceipt:
    invocation_id: str
    event: TutorDurableEvent
    replayed: bool


@dataclass(frozen=True)
class TutorEffectCommitReceipt:
    result: TutorEffectResult
    event: TutorDurableEvent
    replayed: bool
    committer_invoked: bool


@dataclass(frozen=True)
class TutorProviderAttemptRecord:
    receipt_id: str
    run_id: str
    input_revision: int
    decision_iteration: int
    attempt: TutorProviderAttemptReceipt
    created_at: datetime


@dataclass(frozen=True)
class TutorTraceRecord:
    trace_id: str
    run_id: str
    kind: str
    event_from_sequence: int
    event_to_sequence: int
    payload: dict[str, object]
    created_at: datetime


@dataclass(frozen=True)
class TutorCurationEnvelope:
    request: TutorCompactionRequest
    memory_setting_version: str = _DEFAULT_MEMORY_SETTING_VERSION
    priority: int = 0
    retention_until: datetime | None = None
    stale_after: datetime | None = None

    def __post_init__(self) -> None:
        _safe_key(self.memory_setting_version, label="memory setting version")
        if self.priority < 0 or self.priority > 100:
            raise ValueError("curation priority must be within 0..100")


@dataclass(frozen=True)
class TutorCurationOutboxReceipt:
    outbox_id: str
    idempotency_key: str
    state: str
    replayed: bool


@dataclass(frozen=True)
class TutorCurationProposalReceipt:
    proposal_id: str
    outbox_id: str
    kind: str
    state: str
    replayed: bool


EffectHandler = Callable[[Connection[dict[str, object]], TutorRunSnapshot, TutorEffectProposal], TutorEffectResult]
Failpoint = Callable[[str], None]

__all__ = (
    'annotations',
    'base64',
    'hashlib',
    'hmac',
    'json',
    're',
    'Callable',
    'Mapping',
    'Sequence',
    'dataclass',
    'UTC',
    'datetime',
    'timedelta',
    'Final',
    'Literal',
    'cast',
    'uuid4',
    'Connection',
    'ValidationError',
    'EffectDescriptor',
    'default_effect_descriptors',
    'is_exact_semver',
    'MAX_TUTOR_PUBLIC_THINKING_STEP_LENGTH',
    'MAX_TUTOR_PUBLIC_THINKING_STEPS',
    'MAX_TUTOR_PUBLIC_THINKING_TEXT_LENGTH',
    'TutorCapabilityRequest',
    'TutorCapabilityResult',
    'TutorCapabilityStatus',
    'TutorCheckpoint',
    'TutorCompactionRequest',
    'TutorCompactionTrigger',
    'TutorContextBudgetMode',
    'TutorContextBudgetPolicy',
    'TutorContinuationKind',
    'TutorDecision',
    'TutorEffectProposal',
    'TutorEffectResult',
    'TutorEffectStatus',
    'TutorLease',
    'TutorPolicySnapshot',
    'TutorProviderAttemptOutcome',
    'TutorProviderAttemptReceipt',
    'TutorProviderContextCapability',
    'TutorRunResult',
    'TutorRunOrigin',
    'TutorRunSnapshot',
    'TutorRunStatus',
    'TutorTerminalOutcome',
    'TutorTurnCompletionReason',
    'normalize_tutor_conversation_title',
    'payload_mapping_from_fields',
    'CatalogSkillReference',
    'SkillCatalogSnapshot',
    'get_settings',
    'check_teaching_output',
    'sanitize_summary_text',
    'TeachingAuthoritySnapshot',
    'TeachingCheckpointState',
    'TeachingSessionMode',
    'teaching_canonical_hash',
    'reduce_teaching_checkpoint',
    'LLMUsage',
    'TUTOR_CONVERSATION_EVENT_PROJECTION_VERSION',
    'TUTOR_CONVERSATION_SNAPSHOT_VERSION',
    'TUTOR_CONVERSATION_STREAM_CURSOR_VERSION',
    'TUTOR_PUBLIC_THINKING_STREAM_VERSION',
    'TUTOR_RUNTIME_OUTPUT_VERSION',
    'TutorConversationEventKind',
    'TutorDispatchJobState',
    'TutorInteractionProtocolVersion',
    'TutorPublicTurn',
    'validate_public_item',
    'public_turn_status',
    'validate_conversation_event_payload',
    'PLANNING_QUESTION_CATALOG_VERSION',
    'build_planning_question_presentation',
    'format_planning_question_value',
    'validate_planning_question_value',
    'PlanningIntentResolver',
    'TUTOR_AUTHORITY_RECEIPT_SCHEMA_VERSION',
    'TUTOR_INTERACTION_REQUEST_SCHEMA_VERSION',
    'TutorInteractionRequestActor',
    'TutorInteractionRequestKind',
    'TutorInteractionRequestState',
    'actor_for_request',
    'canonical_payload_hash',
    'completion_reason_for_request',
    'public_item_kind',
    'TutorLifecycleConflict',
    'TutorLifecyclePersistence',
    'TutorRunStore',
    'PUBLIC_THINKING_CHUNK_MAX_LENGTH',
    'TutorPublicThinkingSink',
    'TutorSafeProjection',
    'TutorSkillSelection',
    '_DEFAULT_MEMORY_SETTING_VERSION',
    '_DEFAULT_RETENTION_DAYS',
    '_DEFAULT_STALE_DAYS',
    '_SAFE_KEY',
    '_SHA256',
    '_TERMINAL_STATUSES',
    '_PROPOSAL_KINDS',
    '_PROPOSAL_STATES',
    '_DURABLE_EVENT_KINDS',
    '_TRACE_KINDS',
    '_PUBLIC_PROCESS_VERSION',
    '_PUBLIC_PROCESS_STATES',
    '_PUBLIC_PROCESS_STEP_KEYS',
    '_PUBLIC_PROCESS_STEP_STATES',
    '_PUBLIC_PROCESS_STEP_LABELS',
    '_MAX_PUBLIC_PROCESS_ELAPSED_SECONDS',
    '_CURSOR_VERSION',
    '_CONVERSATION_EVENT_CURSOR_KIND',
    '_DISPATCH_JOB_LEASE_SECONDS',
    '_DISPATCH_JOB_MAX_ATTEMPTS',
    '_QUEUE_MAX_PENDING',
    '_safe_key',
    'TutorPersistenceError',
    'TutorRunNotFound',
    'TutorIdempotencyConflict',
    'TutorTerminalStateConflict',
    'TutorLeaseConflict',
    'TutorCatalogEvidenceError',
    'TutorCursorInvalid',
    'TutorInteractionRequestConflict',
    'TutorInteractionRequestNotFound',
    'TutorDurableEvent',
    'TutorInputAcceptance',
    'TutorRunReadState',
    'TutorPublicProcessState',
    'TutorConversationSummary',
    'TutorQueuedInput',
    'TutorQueueAcceptance',
    'TutorInteractionRequestRecord',
    'TutorInteractionResponseAcceptance',
    'TutorInteractiveTurnAcceptance',
    'TutorPublicForegroundRun',
    'TutorConversationTimelineRecord',
    'TutorConversationEvent',
    'TutorInteractiveDispatchJob',
    'TutorConversationSnapshot',
    'TutorSkillSelectionEvidence',
    'TutorCapabilityInvocationReceipt',
    'TutorEffectCommitReceipt',
    'TutorProviderAttemptRecord',
    'TutorTraceRecord',
    'TutorCurationEnvelope',
    'TutorCurationOutboxReceipt',
    'TutorCurationProposalReceipt',
    'EffectHandler',
    'Failpoint',
)
