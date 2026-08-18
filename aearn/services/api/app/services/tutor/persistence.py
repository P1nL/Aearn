"""Target-only PostgreSQL persistence for the feature-disabled Tutor Harness.

The repository is deliberately isolated from routes, workers, and legacy Graph
composition. It accepts a caller-owned psycopg connection and opens a local
transaction/savepoint only for operations that must be atomic.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal, cast
from uuid import uuid4

from psycopg import Connection
from pydantic import ValidationError

from app.agents.harness.capabilities import EffectDescriptor, default_effect_descriptors, is_exact_semver
from app.agents.harness.contracts import (
    MAX_TUTOR_PUBLIC_THINKING_STEP_LENGTH,
    MAX_TUTOR_PUBLIC_THINKING_STEPS,
    MAX_TUTOR_PUBLIC_THINKING_TEXT_LENGTH,
    TutorCapabilityRequest,
    TutorCapabilityResult,
    TutorCapabilityStatus,
    TutorCheckpoint,
    TutorCompactionRequest,
    TutorCompactionTrigger,
    TutorContextBudgetMode,
    TutorContextBudgetPolicy,
    TutorContinuationKind,
    TutorDecision,
    TutorEffectProposal,
    TutorEffectResult,
    TutorEffectStatus,
    TutorLease,
    TutorPolicySnapshot,
    TutorProviderAttemptOutcome,
    TutorProviderAttemptReceipt,
    TutorProviderContextCapability,
    TutorRunResult,
    TutorRunOrigin,
    TutorRunSnapshot,
    TutorRunStatus,
    TutorTerminalOutcome,
    TutorTurnCompletionReason,
    normalize_tutor_conversation_title,
    payload_mapping_from_fields,
)
from app.agents.harness.skill_catalog import CatalogSkillReference, SkillCatalogSnapshot
from app.core.config import get_settings
from app.core.teaching_safety import check_teaching_output, sanitize_summary_text
from app.services.llm.contracts import LLMUsage
from app.services.tutor.conversation_contracts import (
    TUTOR_CONVERSATION_EVENT_PROJECTION_VERSION,
    TUTOR_CONVERSATION_SNAPSHOT_VERSION,
    TUTOR_CONVERSATION_STREAM_CURSOR_VERSION,
    TUTOR_PUBLIC_THINKING_STREAM_VERSION,
    TutorConversationEventKind,
    TutorDispatchJobState,
    TutorInteractionProtocolVersion,
    TutorPublicTurn,
    validate_public_item,
    public_turn_status,
    validate_conversation_event_payload,
)
from app.services.learning.planning_questions import (
    PLANNING_QUESTION_CATALOG_VERSION,
    build_planning_question_presentation,
    format_planning_question_value,
    validate_planning_question_value,
)
from app.services.tutor.interaction_requests import (
    TUTOR_AUTHORITY_RECEIPT_SCHEMA_VERSION,
    TUTOR_INTERACTION_REQUEST_SCHEMA_VERSION,
    TutorInteractionRequestActor,
    TutorInteractionRequestKind,
    TutorInteractionRequestState,
    actor_for_request,
    canonical_payload_hash,
    completion_reason_for_request,
    public_item_kind,
)
from app.services.tutor.ports import TutorLifecycleConflict, TutorLifecyclePersistence, TutorRunStore
from app.services.tutor.public_thinking_stream import (
    PUBLIC_THINKING_CHUNK_MAX_LENGTH,
    TutorPublicThinkingSink,
)
from app.services.tutor.safe_projection import TutorSafeProjection
from app.services.tutor.skill_selection import TutorSkillSelection


_DEFAULT_MEMORY_SETTING_VERSION: Final[str] = "memory_settings_v1"
_DEFAULT_RETENTION_DAYS: Final[int] = 30
_DEFAULT_STALE_DAYS: Final[int] = 7
_SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TERMINAL_STATUSES = frozenset(outcome.value for outcome in TutorTerminalOutcome)
_PROPOSAL_KINDS = frozenset({"context_summary", "memory_entry"})
_PROPOSAL_STATES = frozenset({"pending", "no_action", "stale", "failed"})
# Replay/export treats persisted discriminator columns as untrusted historical data.
# Keep the Child 02 vocabulary closed until a later child extends persistence and
# its safe-projection contract together.
_DURABLE_EVENT_KINDS: Final[frozenset[str]] = frozenset(
    {
        "input_accepted",
        "skill_selected",
        "capability_invoked",
        "compaction_requested",
        "waiting_for_input",
        "interaction_request",
        "curation_proposal_recorded",
        "effect_result",
        "checkpoint_saved",
        "terminal_result",
    }
)
_TRACE_KINDS: Final[frozenset[str]] = frozenset(
    {"checkpoint", "terminal_checkpoint", "compaction_request", "waiting_result"}
)
_PUBLIC_PROCESS_VERSION: Final[str] = "tutor_public_process_v1"
_PUBLIC_PROCESS_STATES: Final[frozenset[str]] = frozenset(
    {
        "thinking",
        "waiting_input",
        "waiting_approval",
        "waiting_authority",
        "completed",
        "interrupted",
        "superseded",
        "unavailable",
        "failed",
    }
)
_PUBLIC_PROCESS_STEP_KEYS: Final[frozenset[str]] = frozenset(
    {
        "input_received",
        "context_prepared",
        "authorized_resource_checked",
        "runtime_started",
        "domain_tool_running",
        "domain_tool_completed",
        "learning_reply_generated",
        "replaced_by_newer_input",
    }
)
_PUBLIC_PROCESS_STEP_STATES: Final[frozenset[str]] = frozenset({"completed", "current"})
_PUBLIC_PROCESS_STEP_LABELS: Final[dict[str, str]] = {
    "input_received": "已接收你的问题",
    "context_prepared": "已整理最近的对话与学习目标",
    "authorized_resource_checked": "已查阅已授权的学习资料",
    "runtime_started": "已启动受控 Agent Runtime",
    "domain_tool_running": "正在执行受控学习工具",
    "domain_tool_completed": "已完成受控学习工具",
    "learning_reply_generated": "已完成一次受控学习建议生成",
    "replaced_by_newer_input": "已根据你的新消息更新本轮处理",
}
_MAX_PUBLIC_PROCESS_ELAPSED_SECONDS: Final[int] = 3_600
_CURSOR_VERSION: Final[int] = 1
_CONVERSATION_EVENT_CURSOR_KIND: Final[str] = "conversation-events"
_DISPATCH_JOB_LEASE_SECONDS: Final[int] = 420
_DISPATCH_JOB_MAX_ATTEMPTS: Final[int] = 5
_QUEUE_MAX_PENDING: Final[int] = 10


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


class PostgresTutorRepository:
    """Scoped target persistence with transaction-level lifecycle methods."""

    def __init__(
        self,
        conn: Connection[dict[str, object]],
        *,
        projector: TutorSafeProjection | None = None,
        failpoint: Failpoint | None = None,
        effect_handlers: Mapping[str, EffectHandler] | None = None,
        effect_descriptors: Sequence[EffectDescriptor] | None = None,
    ) -> None:
        self._conn = conn
        self._projector = projector or TutorSafeProjection()
        self._failpoint = failpoint
        self._effect_handlers = dict(effect_handlers or {})
        # This value is server configuration, never exposed in API payloads or logs.
        self._cursor_signing_key = hashlib.sha256(
            get_settings().tutor_cursor_signing_key.encode("utf-8")
        ).digest()
        descriptors = tuple(default_effect_descriptors() if effect_descriptors is None else effect_descriptors)
        self._effect_descriptors = {descriptor.effect_type: descriptor for descriptor in descriptors}
        if len(self._effect_descriptors) != len(descriptors):
            raise ValueError("effect descriptors must have unique effect types")
        for effect_type in self._effect_handlers:
            _safe_key(effect_type, label="registered effect type")

    def create_conversation(self, *, user_id: str, conversation_id: str | None = None) -> str:
        conversation_id = conversation_id or str(uuid4())
        row = self._conn.execute(
            """
            INSERT INTO tutor_conversations (id, user_id, status)
            SELECT %s, users.id, 'active'
            FROM users
            WHERE users.id = %s
            RETURNING id
            """,
            (conversation_id, user_id),
        ).fetchone()
        if row is None:
            raise TutorRunNotFound("tutor user not found")
        return str(row["id"])

    def resolve_learner_conversation(self, *, user_id: str, conversation_id: str) -> str:
        row = self._conn.execute(
            """
            SELECT id
            FROM tutor_conversations
            WHERE id = %s
              AND user_id = %s
              AND visibility = 'learner'
              AND kind = 'interactive'
              AND status = 'active'
            """,
            (conversation_id, user_id),
        ).fetchone()
        if row is None:
            raise TutorRunNotFound("tutor conversation not found")
        return str(row["id"])

    def create_or_resume_learner_conversation(
        self,
        *,
        user_id: str,
        conversation_id: str | None = None,
    ) -> tuple[str, bool]:
        if conversation_id is not None:
            return self.resolve_learner_conversation(user_id=user_id, conversation_id=conversation_id), False
        return self.create_conversation(user_id=user_id), True

    def record_catalog_snapshot(self, catalog: SkillCatalogSnapshot) -> str:
        catalog_payload = {
            "catalog_digest": catalog.digest,
            "skills": [
                {
                    "skill_id": skill.manifest.id,
                    "skill_version": skill.manifest.version,
                    "manifest_hash": skill.manifest_hash,
                    "instruction_hash": skill.instruction_hash,
                    "evaluation_hash": skill.evaluation_hash,
                    "required_capability_ids": list(skill.manifest.requires_capabilities),
                    "allowed_effect_types": list(skill.manifest.allowed_effect_types),
                    "policy_tags": list(skill.manifest.policy_tags),
                }
                for skill in catalog.skills
            ],
        }
        safe_catalog = self._projector.project(catalog_payload)
        existing = self._conn.execute(
            "SELECT manifest_json FROM tutor_catalog_snapshots WHERE digest = %s",
            (catalog.digest,),
        ).fetchone()
        if existing is not None:
            if self._projector.export(existing["manifest_json"]) != safe_catalog:
                raise TutorCatalogEvidenceError("catalog digest conflicts with stored evidence")
            return catalog.digest
        self._conn.execute(
            """
            INSERT INTO tutor_catalog_snapshots (digest, manifest_json, redaction_version)
            VALUES (%s, %s::jsonb, %s)
            """,
            (catalog.digest, _json(safe_catalog), self._projector.version),
        )
        return catalog.digest

    def create_run(
        self,
        *,
        user_id: str,
        conversation_id: str,
        catalog_digest: str,
        policy: TutorPolicySnapshot,
        run_id: str | None = None,
        origin: TutorRunOrigin,
        policy_version: str = "tutor_policy_v1",
        policy_fingerprint: str | None = None,
        continuation_kind: TutorContinuationKind | None = None,
        interaction_protocol_version: TutorInteractionProtocolVersion = TutorInteractionProtocolVersion.LEGACY_V1,
        retry_of_turn_id: str | None = None,
        retry_root_turn_id: str | None = None,
        response_to_request_id: str | None = None,
        runtime_kind: Literal["harness_v1", "codex_sidecar_v1"] = "harness_v1",
    ) -> TutorRunSnapshot:
        if origin not in {"interactive", "proactive"}:
            raise ValueError("Tutor run origin is invalid")
        protocol_version = TutorInteractionProtocolVersion(str(interaction_protocol_version))
        if retry_of_turn_id is None and retry_root_turn_id is not None:
            raise ValueError("retry root requires retry predecessor")
        _safe_key(policy_version, label="policy version")
        run_id = run_id or str(uuid4())
        policy_payload = _policy_payload(policy)
        fingerprint = policy_fingerprint or _sha256_json(policy_payload)
        if not _SHA256.fullmatch(fingerprint):
            raise ValueError("policy fingerprint must be SHA-256")
        conversation = self._conn.execute(
            "SELECT id FROM tutor_conversations WHERE id = %s AND user_id = %s",
            (conversation_id, user_id),
        ).fetchone()
        if conversation is None:
            raise TutorRunNotFound("tutor conversation not found")
        catalog = self._conn.execute(
            "SELECT digest FROM tutor_catalog_snapshots WHERE digest = %s",
            (catalog_digest,),
        ).fetchone()
        if catalog is None:
            raise TutorCatalogEvidenceError("catalog snapshot is not persisted")
        row = self._conn.execute(
            """
            INSERT INTO tutor_runs (
              id, user_id, conversation_id, origin, status, policy_json,
              policy_version, policy_fingerprint, catalog_digest, continuation_kind,
              interaction_protocol_version, retry_of_turn_id, retry_root_turn_id,
              response_to_request_id, runtime_kind
            )
            VALUES (%s, %s, %s, %s, 'queued', %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                run_id,
                user_id,
                conversation_id,
                origin,
                _json(self._projector.project(policy_payload)),
                policy_version,
                fingerprint,
                catalog_digest,
                continuation_kind.value if continuation_kind is not None else None,
                protocol_version.value,
                retry_of_turn_id,
                retry_root_turn_id,
                response_to_request_id,
                runtime_kind,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("tutor run insert failed")
        return _snapshot_from_row(row)

    def find_or_create_interactive_run(
        self,
        *,
        user_id: str,
        conversation_id: str,
        catalog_digest: str,
        policy: TutorPolicySnapshot,
        policy_version: str = "tutor_interactive_policy_v1",
    ) -> tuple[TutorRunSnapshot, bool]:
        """Serialize one learner conversation to at most one reusable run.

        The conversation row lock makes a second input merge into the existing
        non-terminal interactive run rather than creating a competing stream.
        """

        with self._conn.transaction():
            conversation = self._conn.execute(
                """
                SELECT id
                FROM tutor_conversations
                WHERE id = %s
                  AND user_id = %s
                  AND visibility = 'learner'
                  AND kind = 'interactive'
                  AND status = 'active'
                FOR UPDATE
                """,
                (conversation_id, user_id),
            ).fetchone()
            if conversation is None:
                raise TutorRunNotFound("tutor conversation not found")
            existing = self._conn.execute(
                """
                SELECT *
                FROM tutor_runs
                WHERE user_id = %s
                  AND conversation_id = %s
                  AND origin = 'interactive'
                  AND terminal_outcome IS NULL
                  AND cancelled_at IS NULL
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                FOR UPDATE
                """,
                (user_id, conversation_id),
            ).fetchone()
            if existing is not None:
                return _snapshot_from_row(existing), False
            return (
                self.create_run(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    catalog_digest=catalog_digest,
                    policy=policy,
                    origin="interactive",
                    policy_version=policy_version,
                ),
                True,
            )

    def create_first_interactive_turn(
        self,
        *,
        user_id: str,
        catalog_digest: str,
        policy: TutorPolicySnapshot,
        idempotency_key: str,
        content: str,
        received_at: datetime,
        conversation_id: str | None = None,
        policy_version: str = "tutor_interactive_policy_v1",
    ) -> TutorInteractiveTurnAcceptance:
        """Create a learner-visible conversation only together with its first turn.

        The caller's enclosing idempotency transaction owns replay.  This method
        still keeps the conversation, fresh run, learner message/input receipt,
        and initial public process in one database transaction so a failed first
        send cannot leave an empty conversation behind.
        """

        with self._conn.transaction():
            resolved_conversation_id = self.create_conversation(
                user_id=user_id,
                conversation_id=conversation_id,
            )
            self._trip_failpoint("after_first_turn_conversation")
            conversation = self._lock_learner_conversation(
                user_id=user_id,
                conversation_id=resolved_conversation_id,
            )
            return self._create_interactive_turn_locked(
                conversation=conversation,
                user_id=user_id,
                catalog_digest=catalog_digest,
                policy=policy,
                idempotency_key=idempotency_key,
                content=content,
                received_at=received_at,
                policy_version=policy_version,
            )

    def create_interactive_turn(
        self,
        *,
        user_id: str,
        conversation_id: str,
        catalog_digest: str,
        policy: TutorPolicySnapshot,
        idempotency_key: str,
        content: str,
        received_at: datetime,
        policy_version: str = "tutor_interactive_policy_v1",
    ) -> TutorInteractiveTurnAcceptance:
        """Accept one normal message as a fresh finite TurnRun.

        A conversation row lock serializes replacement, and the old foreground
        run is made terminal before the new run is inserted.  The replacement
        audit link is attached after insertion because it is an immediate FK.
        """

        with self._conn.transaction():
            conversation = self._lock_learner_conversation(
                user_id=user_id,
                conversation_id=conversation_id,
            )
            return self._create_interactive_turn_locked(
                conversation=conversation,
                user_id=user_id,
                catalog_digest=catalog_digest,
                policy=policy,
                idempotency_key=idempotency_key,
                content=content,
                received_at=received_at,
                policy_version=policy_version,
            )

    def _create_interactive_turn_locked(
        self,
        *,
        conversation: Mapping[str, object],
        user_id: str,
        catalog_digest: str,
        policy: TutorPolicySnapshot,
        idempotency_key: str,
        content: str,
        received_at: datetime,
        policy_version: str,
    ) -> TutorInteractiveTurnAcceptance:
        conversation_id = str(conversation["id"])
        pending_request = self._conn.execute(
            """
            SELECT id FROM tutor_interaction_requests
            WHERE user_id = %s AND conversation_id = %s AND state = 'pending'
            FOR UPDATE
            """,
            (user_id, conversation_id),
        ).fetchone()
        if pending_request is not None:
            raise TutorInteractionRequestConflict("Tutor interaction request must be resolved before a normal input")
        foreground = self._conn.execute(
            """
            SELECT *
            FROM tutor_runs
            WHERE user_id = %s
              AND conversation_id = %s
              AND origin = 'interactive'
              AND terminal_outcome IS NULL
              AND cancelled_at IS NULL
              AND superseded_by_run_id IS NULL
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            FOR UPDATE
            """,
            (user_id, conversation_id),
        ).fetchone()
        next_run_id = str(uuid4())
        replaced_run_id: str | None = None
        replaced_process: TutorPublicProcessState | None = None
        if foreground is not None:
            replaced_run_id = str(foreground["id"])
            replaced = self._conn.execute(
                """
                UPDATE tutor_runs
                SET status = 'cancelled',
                    cancelled_at = COALESCE(cancelled_at, %s),
                    terminal_outcome = COALESCE(terminal_outcome, 'cancelled'),
                    terminal_diagnostic_code = COALESCE(terminal_diagnostic_code, 'superseded'),
                    terminal_at = COALESCE(terminal_at, %s),
                    active_lease_owner_id = NULL,
                    active_lease_expires_at = NULL
                WHERE id = %s
                  AND user_id = %s
                  AND terminal_outcome IS NULL
                  AND cancelled_at IS NULL
                  AND superseded_by_run_id IS NULL
                RETURNING *
                """,
                (received_at, received_at, replaced_run_id, user_id),
            ).fetchone()
            if replaced is None:
                raise TutorTerminalStateConflict("foreground Tutor run changed before replacement")
            self._freeze_public_process_locked(
                run=replaced,
                display_state="superseded",
                step_key="replaced_by_newer_input",
                occurred_at=received_at,
            )
            self._append_event_locked(
                run_id=replaced_run_id,
                event_key=f"terminal:superseded:{_as_int(replaced['input_revision'], 0)}",
                kind="terminal_result",
                input_revision=_as_int(replaced["input_revision"], 0),
                payload={
                    "kind": "terminal_result",
                    "status": "cancelled",
                    "run_id": replaced_run_id,
                    "input_revision": _as_int(replaced["input_revision"], 0),
                },
            )
            replaced_process = self.read_public_process(user_id=user_id, run_id=replaced_run_id)

        run = self.create_run(
            user_id=user_id,
            conversation_id=conversation_id,
            catalog_digest=catalog_digest,
            policy=policy,
            run_id=next_run_id,
            origin="interactive",
            policy_version=policy_version,
            interaction_protocol_version=TutorInteractionProtocolVersion.THREAD_TURN_V2,
        )
        self._trip_failpoint("after_fresh_turn_run")
        if replaced_run_id is not None:
            linked = self._conn.execute(
                """
                UPDATE tutor_runs
                SET superseded_by_run_id = %s
                WHERE id = %s AND user_id = %s
                RETURNING id
                """,
                (run.run_id, replaced_run_id, user_id),
            ).fetchone()
            if linked is None:
                raise TutorRunNotFound("superseded Tutor run disappeared")
        acceptance = self.accept_input(
            user_id=user_id,
            run_id=run.run_id,
            idempotency_key=idempotency_key,
            content=content,
            received_at=received_at,
        )
        fresh_run = self._lock_run(user_id=user_id, run_id=run.run_id)
        self._ensure_public_process_locked(run=fresh_run, occurred_at=received_at)
        self._trip_failpoint("after_fresh_turn_input")
        process = self.read_public_process(user_id=user_id, run_id=run.run_id)
        return TutorInteractiveTurnAcceptance(
            run=self.load_snapshot(user_id=user_id, run_id=run.run_id) or run,
            acceptance=acceptance,
            replaced_run_id=replaced_run_id,
            process=process,
            replaced_process=replaced_process,
        )

    def read_interaction_request(
        self,
        *,
        user_id: str,
        conversation_id: str,
        item_id: str,
    ) -> TutorInteractionRequestRecord:
        row = self._conn.execute(
            """
            SELECT * FROM tutor_interaction_requests
            WHERE user_id = %s AND conversation_id = %s AND item_id = %s
            """,
            (user_id, conversation_id, item_id),
        ).fetchone()
        if row is None:
            raise TutorInteractionRequestNotFound("Tutor interaction request not found")
        return _interaction_request_from_row(row)

    def read_pending_interaction_requests(
        self,
        *,
        user_id: str,
        conversation_id: str,
    ) -> tuple[TutorInteractionRequestRecord, ...]:
        rows = self._conn.execute(
            """
            SELECT * FROM tutor_interaction_requests
            WHERE user_id = %s AND conversation_id = %s AND state = 'pending'
            ORDER BY created_at, item_id
            """,
            (user_id, conversation_id),
        ).fetchall()
        return tuple(_interaction_request_from_row(row) for row in rows)

    def respond_to_interaction_request(
        self,
        *,
        user_id: str,
        conversation_id: str,
        item_id: str,
        expected_version: int,
        response: Mapping[str, object],
        idempotency_key: str,
        catalog_digest: str,
        policy: TutorPolicySnapshot,
        received_at: datetime,
    ) -> TutorInteractionResponseAcceptance:
        if expected_version < 1:
            raise TutorInteractionRequestConflict("Tutor interaction request version is invalid")
        with self._conn.transaction():
            conversation = self._lock_learner_conversation(
                user_id=user_id,
                conversation_id=conversation_id,
            )
            request_row = self._conn.execute(
                """
                SELECT * FROM tutor_interaction_requests
                WHERE user_id = %s AND conversation_id = %s AND item_id = %s
                FOR UPDATE
                """,
                (user_id, conversation_id, item_id),
            ).fetchone()
            if request_row is None:
                raise TutorInteractionRequestNotFound("Tutor interaction request not found")
            kind = TutorInteractionRequestKind(str(request_row["kind"]))
            if TutorInteractionRequestActor(str(request_row["actor"])) is not TutorInteractionRequestActor.LEARNER:
                raise TutorInteractionRequestConflict("authority request has no learner mutation")
            normalized, content, planning_facts, denied = self._normalize_learner_request_response(
                request_row=request_row,
                response=response,
            )
            response_hash = canonical_payload_hash(normalized)
            if str(request_row["state"]) != TutorInteractionRequestState.PENDING.value:
                if (
                    str(request_row.get("response_hash") or "") == response_hash
                    and request_row.get("answer_turn_id") is not None
                ):
                    return TutorInteractionResponseAcceptance(
                        request=_interaction_request_from_row(request_row),
                        turn=self._resolved_request_turn_locked(request_row=request_row),
                        planning_facts=planning_facts,
                        replayed=True,
                    )
                raise TutorInteractionRequestConflict("Tutor interaction request is already resolved")
            if _as_int(request_row.get("version"), 0) != expected_version:
                raise TutorInteractionRequestConflict("Tutor interaction request version is stale")
            descriptor = _as_mapping(request_row.get("descriptor_json"))
            if canonical_payload_hash(descriptor) != str(request_row["descriptor_hash"]):
                raise TutorInteractionRequestConflict("Tutor interaction request authority changed")
            turn = self._create_response_turn_locked(
                conversation=conversation,
                request_row=request_row,
                user_id=user_id,
                catalog_digest=catalog_digest,
                policy=policy,
                idempotency_key=idempotency_key,
                content=content,
                source="interaction_request_response",
                role="learner",
                received_at=received_at,
            )
            next_state = (
                TutorInteractionRequestState.DENIED.value
                if denied and kind is TutorInteractionRequestKind.APPROVAL
                else TutorInteractionRequestState.ANSWERED.value
            )
            updated = self._conn.execute(
                """
                UPDATE tutor_interaction_requests
                SET state = %s, version = version + 1, response_hash = %s,
                    answer_turn_id = %s, answer_message_id = %s, resolved_at = %s
                WHERE id = %s AND user_id = %s AND conversation_id = %s
                  AND state = 'pending' AND version = %s
                RETURNING *
                """,
                (
                    next_state,
                    response_hash,
                    turn.run.run_id,
                    turn.acceptance.message_id,
                    received_at,
                    request_row["id"],
                    user_id,
                    conversation_id,
                    expected_version,
                ),
            ).fetchone()
            if updated is None:
                raise TutorInteractionRequestConflict("Tutor interaction request changed before response")
            source_run = self._lock_run(user_id=user_id, run_id=str(request_row["source_turn_id"]))
            self._append_item_reference_event_locked(
                run=source_run,
                event_key=f"item:request:{item_id}:resolved:{expected_version + 1}",
                kind=TutorConversationEventKind.ITEM_UPDATED,
                item_id=item_id,
                item_kind=public_item_kind(kind),
                occurred_at=received_at,
            )
            self._increment_control_version_locked(
                user_id=user_id,
                conversation_id=conversation_id,
                event_key=f"control:request:{item_id}:resolved:{expected_version + 1}",
                occurred_at=received_at,
                turn_id=turn.run.run_id,
            )
            return TutorInteractionResponseAcceptance(
                request=_interaction_request_from_row(updated),
                turn=turn,
                planning_facts=planning_facts,
                replayed=False,
            )

    def accept_authority_receipt(
        self,
        *,
        user_id: str,
        conversation_id: str,
        item_id: str,
        expected_version: int,
        issuer: str,
        subject: str,
        scope: Mapping[str, object],
        request_hash: str,
        result_hash: str,
        verification_result: str,
        receipt_identity: str,
        catalog_digest: str,
        policy: TutorPolicySnapshot,
        received_at: datetime,
    ) -> TutorInteractionResponseAcceptance:
        _safe_key(issuer, label="authority issuer")
        _safe_key(subject, label="authority subject")
        _safe_key(receipt_identity, label="authority receipt identity")
        if not _SHA256.fullmatch(request_hash) or not _SHA256.fullmatch(result_hash):
            raise TutorInteractionRequestConflict("authority receipt hashes are invalid")
        if verification_result not in {"verified", "ambiguous", "rejected"}:
            raise TutorInteractionRequestConflict("authority receipt verification result is invalid")
        with self._conn.transaction():
            conversation = self._lock_learner_conversation(user_id=user_id, conversation_id=conversation_id)
            request_row = self._conn.execute(
                """
                SELECT * FROM tutor_interaction_requests
                WHERE user_id = %s AND conversation_id = %s AND item_id = %s
                FOR UPDATE
                """,
                (user_id, conversation_id, item_id),
            ).fetchone()
            if request_row is None:
                raise TutorInteractionRequestNotFound("Tutor interaction request not found")
            if TutorInteractionRequestActor(str(request_row["actor"])) is not TutorInteractionRequestActor.AUTHORITY:
                raise TutorInteractionRequestConflict("learner request cannot accept an authority receipt")
            expected_scope = _as_mapping(request_row.get("authority_scope_json"))
            if canonical_payload_hash(scope) != canonical_payload_hash(expected_scope):
                raise TutorInteractionRequestConflict("authority receipt scope does not match the request")
            if subject != str(request_row["id"]) or request_hash != str(request_row["authority_request_hash"]):
                raise TutorInteractionRequestConflict("authority receipt identity does not match the request")
            receipt_body = {
                "schema_version": TUTOR_AUTHORITY_RECEIPT_SCHEMA_VERSION,
                "issuer": issuer,
                "subject": subject,
                "scope": dict(scope),
                "request_hash": request_hash,
                "result_hash": result_hash,
                "verification_result": verification_result,
            }
            receipt_hash = canonical_payload_hash(receipt_body)
            if str(request_row["state"]) != TutorInteractionRequestState.PENDING.value:
                if (
                    str(request_row.get("receipt_identity") or "") == receipt_identity
                    and str(request_row.get("receipt_hash") or "") == receipt_hash
                    and request_row.get("answer_turn_id") is not None
                ):
                    return TutorInteractionResponseAcceptance(
                        request=_interaction_request_from_row(request_row),
                        turn=self._resolved_request_turn_locked(request_row=request_row),
                        planning_facts={},
                        replayed=True,
                    )
                raise TutorInteractionRequestConflict("authority request is already resolved")
            if _as_int(request_row.get("version"), 0) != expected_version:
                raise TutorInteractionRequestConflict("authority request version is stale")
            if verification_result != "verified":
                updated = self._conn.execute(
                    """
                    UPDATE tutor_interaction_requests
                    SET version = version + 1, authority_issuer = %s, authority_subject = %s,
                        authority_result_hash = %s, authority_verification_result = %s
                    WHERE id = %s AND state = 'pending' AND version = %s
                    RETURNING *
                    """,
                    (issuer, subject, result_hash, verification_result, request_row["id"], expected_version),
                ).fetchone()
                if updated is None:
                    raise TutorInteractionRequestConflict("authority request changed before verification")
                return TutorInteractionResponseAcceptance(
                    request=_interaction_request_from_row(updated),
                    turn=None,
                    planning_facts={},
                    replayed=False,
                )
            turn = self._create_response_turn_locked(
                conversation=conversation,
                request_row=request_row,
                user_id=user_id,
                catalog_digest=catalog_digest,
                policy=policy,
                idempotency_key=f"authority:{receipt_identity}",
                content="已接收并验证受信结果。",
                source="authority_receipt",
                role="tutor",
                received_at=received_at,
            )
            updated = self._conn.execute(
                """
                UPDATE tutor_interaction_requests
                SET state = 'answered', version = version + 1,
                    authority_issuer = %s, authority_subject = %s,
                    authority_result_hash = %s, authority_verification_result = 'verified',
                    receipt_identity = %s, receipt_hash = %s,
                    answer_turn_id = %s, answer_message_id = %s, resolved_at = %s
                WHERE id = %s AND state = 'pending' AND version = %s
                RETURNING *
                """,
                (
                    issuer,
                    subject,
                    result_hash,
                    receipt_identity,
                    receipt_hash,
                    turn.run.run_id,
                    turn.acceptance.message_id,
                    received_at,
                    request_row["id"],
                    expected_version,
                ),
            ).fetchone()
            if updated is None:
                raise TutorInteractionRequestConflict("authority request changed before receipt commit")
            source_run = self._lock_run(user_id=user_id, run_id=str(request_row["source_turn_id"]))
            request_kind = TutorInteractionRequestKind(str(request_row["kind"]))
            self._append_item_reference_event_locked(
                run=source_run,
                event_key=f"item:request:{item_id}:authority:{expected_version + 1}",
                kind=TutorConversationEventKind.ITEM_UPDATED,
                item_id=item_id,
                item_kind=public_item_kind(request_kind),
                occurred_at=received_at,
            )
            self._increment_control_version_locked(
                user_id=user_id,
                conversation_id=conversation_id,
                event_key=f"control:request:{item_id}:authority:{expected_version + 1}",
                occurred_at=received_at,
                turn_id=turn.run.run_id,
            )
            return TutorInteractionResponseAcceptance(
                request=_interaction_request_from_row(updated),
                turn=turn,
                planning_facts={},
                replayed=False,
            )

    def _normalize_learner_request_response(
        self,
        *,
        request_row: Mapping[str, object],
        response: Mapping[str, object],
    ) -> tuple[dict[str, object], str, dict[str, object], bool]:
        kind = TutorInteractionRequestKind(str(request_row["kind"]))
        response_kind = str(response.get("kind") or "")
        if response_kind != kind.value:
            raise TutorInteractionRequestConflict("Tutor response kind does not match the request")
        if kind is TutorInteractionRequestKind.CLARIFICATION:
            answer = str(response.get("answer_text") or "").strip()
            if not answer or len(answer) > 16_000:
                raise TutorInteractionRequestConflict("clarification answer is invalid")
            return {"kind": kind.value, "answer_text": answer}, answer, {}, False
        if kind is TutorInteractionRequestKind.PLANNING_INPUT:
            question_key = str(response.get("question_key") or "")
            catalog_version = str(response.get("catalog_version") or "")
            if question_key != str(request_row.get("question_key") or ""):
                raise TutorInteractionRequestConflict("planning response question key does not match")
            normalized = validate_planning_question_value(
                self._conn,
                question_key=question_key,
                catalog_version=catalog_version,
                value=response.get("value"),
            )
            safe = {
                "kind": kind.value,
                "question_key": question_key,
                "catalog_version": catalog_version,
                "value": normalized,
            }
            content = format_planning_question_value(
                presentation=_as_mapping(request_row.get("presentation_json")),
                value=normalized,
            )
            return safe, content, {question_key: normalized}, False
        if kind is TutorInteractionRequestKind.APPROVAL:
            decision = str(response.get("decision") or "")
            proposal_identity = str(response.get("proposal_identity") or "")
            if decision not in {"approve", "deny"}:
                raise TutorInteractionRequestConflict("approval decision is invalid")
            if proposal_identity != str(request_row.get("proposal_identity") or ""):
                raise TutorInteractionRequestConflict("approval proposal identity does not match")
            reason = " ".join(str(response.get("reason") or "").split())
            if len(reason) > 400:
                raise TutorInteractionRequestConflict("approval reason is too long")
            safe = {
                "kind": kind.value,
                "proposal_identity": proposal_identity,
                "decision": decision,
                "reason": reason or None,
            }
            content = "已批准该操作。" if decision == "approve" else "已拒绝该操作。"
            if reason:
                content = f"{content} 原因：{reason}"
            return safe, content, {}, decision == "deny"
        raise TutorInteractionRequestConflict("authority request has no learner response")

    def _create_response_turn_locked(
        self,
        *,
        conversation: Mapping[str, object],
        request_row: Mapping[str, object],
        user_id: str,
        catalog_digest: str,
        policy: TutorPolicySnapshot,
        idempotency_key: str,
        content: str,
        source: str,
        role: str,
        received_at: datetime,
    ) -> TutorInteractiveTurnAcceptance:
        conversation_id = str(conversation["id"])
        self._conn.execute(
            "UPDATE tutor_conversations SET queue_paused = false, queue_pause_reason = NULL WHERE id = %s AND user_id = %s AND queue_pause_reason = 'pending_request'",
            (conversation_id, user_id),
        )
        foreground = self._conn.execute(
            """
            SELECT id FROM tutor_runs
            WHERE user_id = %s AND conversation_id = %s AND origin = 'interactive'
              AND terminal_outcome IS NULL AND cancelled_at IS NULL AND superseded_by_run_id IS NULL
            FOR UPDATE
            """,
            (user_id, conversation_id),
        ).fetchone()
        if foreground is not None:
            raise TutorInteractionRequestConflict("conversation already has an active Tutor turn")
        run = self.create_run(
            user_id=user_id,
            conversation_id=conversation_id,
            catalog_digest=catalog_digest,
            policy=policy,
            origin="interactive",
            policy_version="tutor_interaction_response_policy_v1",
            interaction_protocol_version=TutorInteractionProtocolVersion.THREAD_TURN_V2,
            response_to_request_id=str(request_row["id"]),
        )
        acceptance = self.accept_input(
            user_id=user_id,
            run_id=run.run_id,
            idempotency_key=idempotency_key,
            content=content,
            source=source,
            role=role,
            received_at=received_at,
        )
        fresh = self._lock_run(user_id=user_id, run_id=run.run_id)
        self._ensure_public_process_locked(run=fresh, occurred_at=received_at)
        return TutorInteractiveTurnAcceptance(
            run=self.load_snapshot(user_id=user_id, run_id=run.run_id) or run,
            acceptance=acceptance,
            replaced_run_id=None,
            process=self.read_public_process(user_id=user_id, run_id=run.run_id),
            replaced_process=None,
        )

    def _resolved_request_turn_locked(
        self,
        *,
        request_row: Mapping[str, object],
    ) -> TutorInteractiveTurnAcceptance:
        run_id = str(request_row.get("answer_turn_id") or "")
        message_id = str(request_row.get("answer_message_id") or "")
        run_row = self._conn.execute("SELECT * FROM tutor_runs WHERE id = %s", (run_id,)).fetchone()
        input_row = self._conn.execute(
            """
            SELECT * FROM tutor_run_input_events
            WHERE run_id = %s AND message_id = %s
            """,
            (run_id, message_id),
        ).fetchone()
        if run_row is None or input_row is None:
            raise TutorInteractionRequestConflict("resolved request answer turn is missing")
        event = self._event_by_key_locked(
            run_id=run_id,
            event_key=f"input:{input_row['idempotency_key']}",
        )
        if event is None:
            raise TutorInteractionRequestConflict("resolved request input event is missing")
        dispatch = self._conn.execute(
            "SELECT id FROM tutor_interactive_dispatch_jobs WHERE run_id = %s",
            (run_id,),
        ).fetchone()
        acceptance = TutorInputAcceptance(
            run_id=run_id,
            message_id=message_id,
            input_revision=_as_int(input_row.get("input_revision"), 1),
            event=event,
            replayed=True,
            dispatch_job_id=str(dispatch["id"]) if dispatch is not None else None,
        )
        snapshot = _snapshot_from_row(run_row)
        return TutorInteractiveTurnAcceptance(
            run=snapshot,
            acceptance=acceptance,
            replaced_run_id=None,
            process=self.read_public_process(user_id=str(run_row["user_id"]), run_id=run_id),
            replaced_process=None,
        )

    def _lock_conversation(
        self,
        *,
        user_id: str,
        conversation_id: str,
        learner_only: bool = False,
    ) -> Mapping[str, object]:
        clauses = ["id = %s", "user_id = %s", "status = 'active'"]
        if learner_only:
            clauses.extend(("visibility = 'learner'", "kind = 'interactive'"))
        row = self._conn.execute(
            f"SELECT * FROM tutor_conversations WHERE {' AND '.join(clauses)} FOR UPDATE",
            (conversation_id, user_id),
        ).fetchone()
        if row is None:
            raise TutorRunNotFound("tutor conversation not found")
        return row

    def _lock_learner_conversation(self, *, user_id: str, conversation_id: str) -> Mapping[str, object]:
        return self._lock_conversation(user_id=user_id, conversation_id=conversation_id, learner_only=True)

    def _lock_run_with_conversation(
        self,
        *,
        user_id: str,
        run_id: str,
        learner_only: bool = False,
    ) -> tuple[Mapping[str, object], Mapping[str, object]]:
        """Lock a run's conversation before its run row to serialize latest-input-wins.

        Normal turns lock the conversation then the foreground run. Every later
        unsafe write follows the same ordering, so a newly accepted turn either
        replaces the old run first or waits behind a write that is already
        authoritative; it cannot race a stale post-provider write around it.
        """

        reference = self._conn.execute(
            "SELECT conversation_id FROM tutor_runs WHERE id = %s AND user_id = %s",
            (run_id, user_id),
        ).fetchone()
        if reference is None:
            raise TutorRunNotFound("tutor run not found")
        conversation = self._lock_conversation(
            user_id=user_id,
            conversation_id=str(reference["conversation_id"]),
            learner_only=learner_only,
        )
        run = self._lock_run(user_id=user_id, run_id=run_id)
        if str(run["conversation_id"]) != str(conversation["id"]):
            raise TutorPersistenceError("Tutor run conversation scope is inconsistent")
        return conversation, run

    def _touch_conversation_public_activity_locked(
        self,
        *,
        user_id: str,
        conversation_id: str,
        occurred_at: datetime,
    ) -> None:
        updated = self._conn.execute(
            """
            UPDATE tutor_conversations
            SET last_public_activity_at = GREATEST(last_public_activity_at, %s)
            WHERE id = %s AND user_id = %s
            RETURNING id
            """,
            (occurred_at, conversation_id, user_id),
        ).fetchone()
        if updated is None:
            raise TutorRunNotFound("tutor conversation not found")

    def _increment_control_version_locked(
        self,
        *,
        user_id: str,
        conversation_id: str,
        event_key: str,
        occurred_at: datetime,
        turn_id: str | None,
    ) -> int:
        row = self._conn.execute(
            """
            UPDATE tutor_conversations
            SET control_version = control_version + 1
            WHERE id = %s AND user_id = %s
            RETURNING control_version
            """,
            (conversation_id, user_id),
        ).fetchone()
        if row is None:
            raise TutorRunNotFound("tutor conversation not found")
        version = max(1, _as_int(row.get("control_version"), 1))
        self._append_conversation_event_locked(
            user_id=user_id,
            conversation_id=conversation_id,
            event_key=event_key,
            kind=TutorConversationEventKind.CONTROL_UPDATED,
            payload={"control_version": version},
            occurred_at=occurred_at,
        )
        return version

    def _ensure_public_process_locked(
        self,
        *,
        run: Mapping[str, object],
        occurred_at: datetime,
    ) -> None:
        if str(run.get("origin")) != "interactive":
            return
        inserted = self._conn.execute(
            """
            INSERT INTO tutor_run_public_processes (
              run_id, user_id, conversation_id, projection_version,
              display_state, current_step_key, started_at, last_public_activity_at
            )
            VALUES (%s, %s, %s, %s, 'thinking', 'input_received', %s, %s)
            ON CONFLICT (run_id) DO NOTHING
            RETURNING run_id
            """,
            (
                run["id"],
                run["user_id"],
                run["conversation_id"],
                _PUBLIC_PROCESS_VERSION,
                occurred_at,
                occurred_at,
            ),
        ).fetchone()
        if inserted is None:
            return
        self._conn.execute(
            """
            INSERT INTO tutor_run_public_process_steps (run_id, ordinal, step_key, state, occurred_at)
            VALUES (%s, 1, 'input_received', 'completed', %s)
            ON CONFLICT (run_id, ordinal) DO NOTHING
            """,
            (run["id"], occurred_at),
        )
        self._touch_conversation_public_activity_locked(
            user_id=str(run["user_id"]),
            conversation_id=str(run["conversation_id"]),
            occurred_at=occurred_at,
        )
        self._append_item_reference_event_locked(
            run=run,
            event_key=f"item:process:{run['id']}:added",
            kind=TutorConversationEventKind.ITEM_ADDED,
            item_id=str(run["id"]),
            item_kind="process",
            occurred_at=occurred_at,
        )

    def _append_public_process_step_locked(
        self,
        *,
        run_id: str,
        step_key: str,
        state: str,
        occurred_at: datetime,
    ) -> bool:
        if step_key not in _PUBLIC_PROCESS_STEP_KEYS or state not in _PUBLIC_PROCESS_STEP_STATES:
            raise ValueError("public process step is not allowlisted")
        existing = self._conn.execute(
            """
            SELECT id
            FROM tutor_run_public_process_steps
            WHERE run_id = %s AND step_key = %s
            ORDER BY ordinal DESC
            LIMIT 1
            """,
            (run_id, step_key),
        ).fetchone()
        if existing is not None:
            return False
        ordinal_row = self._conn.execute(
            "SELECT COALESCE(MAX(ordinal), 0) + 1 AS ordinal FROM tutor_run_public_process_steps WHERE run_id = %s",
            (run_id,),
        ).fetchone()
        ordinal = _as_int(ordinal_row["ordinal"] if ordinal_row is not None else 1, 1)
        self._conn.execute(
            """
            INSERT INTO tutor_run_public_process_steps (run_id, ordinal, step_key, state, occurred_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (run_id, ordinal, step_key, state, occurred_at),
        )
        return True

    def _advance_public_process_locked(
        self,
        *,
        run: Mapping[str, object],
        step_key: str,
        occurred_at: datetime,
    ) -> None:
        if step_key not in _PUBLIC_PROCESS_STEP_KEYS:
            raise ValueError("public process step is not allowlisted")
        process = self._conn.execute(
            "SELECT * FROM tutor_run_public_processes WHERE run_id = %s FOR UPDATE",
            (run["id"],),
        ).fetchone()
        if process is None or str(process["display_state"]) != "thinking":
            return
        self._append_public_process_step_locked(
            run_id=str(run["id"]),
            step_key=step_key,
            state="completed",
            occurred_at=occurred_at,
        )
        self._conn.execute(
            """
            UPDATE tutor_run_public_processes
            SET current_step_key = %s,
                last_public_activity_at = GREATEST(last_public_activity_at, %s)
            WHERE run_id = %s
            """,
            (step_key, occurred_at, run["id"]),
        )
        self._touch_conversation_public_activity_locked(
            user_id=str(run["user_id"]),
            conversation_id=str(run["conversation_id"]),
            occurred_at=occurred_at,
        )
        self._append_item_reference_event_locked(
            run=run,
            event_key=f"item:process:{run['id']}:step:{step_key}",
            kind=TutorConversationEventKind.ITEM_UPDATED,
            item_id=str(run["id"]),
            item_kind="process",
            occurred_at=occurred_at,
        )

    def _freeze_public_process_locked(
        self,
        *,
        run: Mapping[str, object],
        display_state: str,
        step_key: str | None,
        occurred_at: datetime,
        tutor_message_id: str | None = None,
    ) -> None:
        if display_state not in _PUBLIC_PROCESS_STATES or display_state == "thinking":
            raise ValueError("public process terminal state is invalid")
        if step_key is not None and step_key not in _PUBLIC_PROCESS_STEP_KEYS:
            raise ValueError("public process step is not allowlisted")
        process = self._conn.execute(
            "SELECT * FROM tutor_run_public_processes WHERE run_id = %s FOR UPDATE",
            (run["id"],),
        ).fetchone()
        # Older records must remain message-only history; do not manufacture a card.
        if process is None:
            return
        if str(process["display_state"]) == "thinking":
            if step_key is not None:
                self._append_public_process_step_locked(
                    run_id=str(run["id"]),
                    step_key=step_key,
                    state="completed",
                    occurred_at=occurred_at,
                )
            self._conn.execute(
                """
                UPDATE tutor_run_public_processes
                SET display_state = %s,
                    current_step_key = COALESCE(%s, current_step_key),
                    tutor_message_id = COALESCE(%s, tutor_message_id),
                    last_public_activity_at = GREATEST(last_public_activity_at, %s),
                    finished_at = %s
                WHERE run_id = %s
                """,
                (display_state, step_key, tutor_message_id, occurred_at, occurred_at, run["id"]),
            )
        elif tutor_message_id is not None:
            self._conn.execute(
                """
                UPDATE tutor_run_public_processes
                SET tutor_message_id = COALESCE(tutor_message_id, %s)
                WHERE run_id = %s
                """,
                (tutor_message_id, run["id"]),
            )
        self._touch_conversation_public_activity_locked(
            user_id=str(run["user_id"]),
            conversation_id=str(run["conversation_id"]),
            occurred_at=occurred_at,
        )
        self._append_item_reference_event_locked(
            run=run,
            event_key=f"item:process:{run['id']}:state:{display_state}",
            kind=TutorConversationEventKind.ITEM_UPDATED,
            item_id=str(run["id"]),
            item_kind="process",
            occurred_at=occurred_at,
        )

    def _write_conversation_title_once_locked(
        self,
        *,
        user_id: str,
        conversation_id: str,
        candidate: str | None,
    ) -> None:
        if candidate is None:
            return
        try:
            title = normalize_tutor_conversation_title(candidate)
        except ValueError:
            return
        self._conn.execute(
            """
            UPDATE tutor_conversations
            SET title = %s
            WHERE id = %s AND user_id = %s AND title IS NULL
            """,
            (title, conversation_id, user_id),
        )

    def read_public_process(self, *, user_id: str, run_id: str, now: datetime | None = None) -> TutorPublicProcessState | None:
        row = self._conn.execute(
            """
            SELECT processes.*
            FROM tutor_run_public_processes AS processes
            JOIN tutor_runs AS runs ON runs.id = processes.run_id
            WHERE processes.run_id = %s AND runs.user_id = %s
            """,
            (run_id, user_id),
        ).fetchone()
        return self._public_process_state_from_row(row, now=now) if row is not None else None

    def _public_process_state_from_row(
        self,
        row: Mapping[str, object],
        *,
        now: datetime | None = None,
    ) -> TutorPublicProcessState:
        run_id = str(row["run_id"])
        started_at = _as_datetime(row.get("started_at")) or datetime.now(UTC)
        finished_at = _as_datetime(row.get("finished_at"))
        effective_end = finished_at or now or datetime.now(UTC)
        elapsed_seconds = max(0, min(_MAX_PUBLIC_PROCESS_ELAPSED_SECONDS, int((effective_end - started_at).total_seconds())))
        steps = self._conn.execute(
            """
            SELECT step_key, state, occurred_at
            FROM tutor_run_public_process_steps
            WHERE run_id = %s
            ORDER BY ordinal ASC
            """,
            (run_id,),
        ).fetchall()
        public_steps: list[dict[str, object]] = []
        for step in steps:
            key = str(step.get("step_key") or "")
            if key not in _PUBLIC_PROCESS_STEP_KEYS:
                continue
            state = str(step.get("state") or "completed")
            public_steps.append(
                {
                    "key": key,
                    "state": state if state in _PUBLIC_PROCESS_STEP_STATES else "completed",
                    "label": _PUBLIC_PROCESS_STEP_LABELS[key],
                }
            )
        display_state = str(row.get("display_state") or "unavailable")
        return TutorPublicProcessState(
            run_id=run_id,
            conversation_id=str(row["conversation_id"]),
            display_state=display_state if display_state in _PUBLIC_PROCESS_STATES else "unavailable",
            steps=tuple(public_steps),
            elapsed_seconds=elapsed_seconds,
            created_at=started_at,
            finished_at=finished_at,
        )

    def list_public_conversations(
        self,
        *,
        user_id: str,
        limit: int,
        cursor: str | None = None,
    ) -> tuple[tuple[TutorConversationSummary, ...], str | None, bool]:
        if limit < 1 or limit > 40:
            raise ValueError("conversation page limit is invalid")
        after = self._decode_public_cursor(
            cursor=cursor,
            kind="conversation-list",
            user_id=user_id,
            conversation_id=None,
        ) if cursor else None
        query = """
            SELECT conversations.id AS conversation_id,
                   conversations.title,
                   conversations.last_public_activity_at,
                   foreground.id AS active_run_id,
                   foreground.status AS active_run_status,
                   foreground.continuation_kind AS active_run_continuation_kind
            FROM tutor_conversations AS conversations
            LEFT JOIN LATERAL (
              SELECT runs.id, runs.status, runs.continuation_kind
              FROM tutor_runs AS runs
              WHERE runs.user_id = conversations.user_id
                AND runs.conversation_id = conversations.id
                AND runs.origin = 'interactive'
                AND runs.terminal_outcome IS NULL
                AND runs.cancelled_at IS NULL
                AND runs.superseded_by_run_id IS NULL
              ORDER BY runs.created_at DESC, runs.id DESC
              LIMIT 1
            ) AS foreground ON TRUE
            WHERE conversations.user_id = %s
              AND conversations.visibility = 'learner'
              AND conversations.kind = 'interactive'
              AND conversations.status = 'active'
              AND (
                EXISTS (SELECT 1 FROM tutor_messages AS messages WHERE messages.conversation_id = conversations.id)
                OR EXISTS (SELECT 1 FROM tutor_run_public_processes AS processes WHERE processes.conversation_id = conversations.id)
              )
        """
        params: list[object] = [user_id]
        if after is not None:
            query += """
              AND (
                conversations.last_public_activity_at < %s
                OR (
                  conversations.last_public_activity_at = %s
                  AND conversations.id < %s::uuid
                )
              )
            """
            params.extend((after["created_at"], after["created_at"], after["item_id"]))
        query += """
            ORDER BY conversations.last_public_activity_at DESC, conversations.id DESC
            LIMIT %s
        """
        params.append(limit + 1)
        rows = self._conn.execute(query, tuple(params)).fetchall()
        page_rows = rows[:limit]
        items: list[TutorConversationSummary] = []
        for row in page_rows:
            continuation_value = row.get("active_run_continuation_kind")
            try:
                continuation_kind = TutorContinuationKind(str(continuation_value)) if continuation_value is not None else None
            except ValueError:
                continuation_kind = None
            items.append(
                TutorConversationSummary(
                    conversation_id=str(row["conversation_id"]),
                    title=str(row["title"]) if row.get("title") is not None else None,
                    last_public_activity_at=_as_datetime(row.get("last_public_activity_at")) or datetime.now(UTC),
                    active_run_id=str(row["active_run_id"]) if row.get("active_run_id") is not None else None,
                    active_run_status=str(row["active_run_status"]) if row.get("active_run_status") is not None else None,
                    active_run_continuation_kind=continuation_kind,
                )
            )
        has_more = len(rows) > limit
        next_cursor = (
            self._encode_public_cursor(
                kind="conversation-list",
                user_id=user_id,
                conversation_id=None,
                created_at=items[-1].last_public_activity_at,
                sort_rank=0,
                item_id=items[-1].conversation_id,
            )
            if has_more and items
            else None
        )
        return tuple(items), next_cursor, has_more

    def read_public_foreground_run(
        self,
        *,
        user_id: str,
        conversation_id: str,
    ) -> TutorPublicForegroundRun | None:
        self.resolve_learner_conversation(user_id=user_id, conversation_id=conversation_id)
        row = self._conn.execute(
            """
            SELECT id, status, continuation_kind
            FROM tutor_runs
            WHERE user_id = %s
              AND conversation_id = %s
              AND origin = 'interactive'
              AND terminal_outcome IS NULL
              AND cancelled_at IS NULL
              AND superseded_by_run_id IS NULL
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (user_id, conversation_id),
        ).fetchone()
        if row is None:
            return None
        raw_kind = row.get("continuation_kind")
        try:
            continuation_kind = TutorContinuationKind(str(raw_kind)) if raw_kind is not None else None
        except ValueError:
            continuation_kind = None
        return TutorPublicForegroundRun(
            run_id=str(row["id"]),
            status=str(row["status"]),
            continuation_kind=continuation_kind,
        )

    def read_public_history(
        self,
        *,
        user_id: str,
        conversation_id: str,
        limit: int,
        cursor: str | None = None,
        now: datetime | None = None,
        include_errors: bool = False,
    ) -> tuple[tuple[TutorConversationTimelineRecord, ...], str | None, bool]:
        if limit < 1 or limit > 40:
            raise ValueError("history page limit is invalid")
        self.resolve_learner_conversation(user_id=user_id, conversation_id=conversation_id)
        after = self._decode_public_cursor(
            cursor=cursor,
            kind="conversation-history",
            user_id=user_id,
            conversation_id=conversation_id,
        ) if cursor else None
        timeline = """
            WITH timeline AS (
              SELECT
                'message'::text AS kind,
                messages.id AS item_id,
                messages.created_at AS created_at,
                CASE WHEN messages.role = 'learner' THEN 10 ELSE 30 END AS sort_rank,
                messages.role AS role,
                messages.content AS content,
                messages.public_thinking_text AS public_thinking_text,
                messages.public_thinking_steps_json AS public_thinking_steps_json,
                NULL::uuid AS process_run_id,
                COALESCE(input_events.run_id, tutor_process.run_id) AS turn_id,
                NULL::text AS error_code,
                NULL::boolean AS error_recoverable,
                replied_requests.item_id AS in_reply_to_item_id,
                NULL::uuid AS interaction_request_id
              FROM tutor_messages AS messages
              JOIN tutor_conversations AS conversations ON conversations.id = messages.conversation_id
              LEFT JOIN tutor_run_input_events AS input_events ON input_events.message_id = messages.id
              LEFT JOIN tutor_runs AS response_runs ON response_runs.id = input_events.run_id
              LEFT JOIN tutor_interaction_requests AS replied_requests
                ON replied_requests.id = response_runs.response_to_request_id
              LEFT JOIN tutor_run_public_processes AS tutor_process ON tutor_process.tutor_message_id = messages.id
              WHERE conversations.id = %s
                AND conversations.user_id = %s
                AND conversations.visibility = 'learner'
                AND conversations.kind = 'interactive'
                AND conversations.status = 'active'
              UNION ALL
              SELECT
                'process'::text AS kind,
                processes.run_id AS item_id,
                processes.started_at AS created_at,
                20 AS sort_rank,
                NULL::text AS role,
                NULL::text AS content,
                ''::text AS public_thinking_text,
                '[]'::jsonb AS public_thinking_steps_json,
                processes.run_id AS process_run_id,
                processes.run_id AS turn_id,
                NULL::text AS error_code,
                NULL::boolean AS error_recoverable,
                NULL::uuid AS in_reply_to_item_id,
                NULL::uuid AS interaction_request_id
              FROM tutor_run_public_processes AS processes
              JOIN tutor_conversations AS conversations ON conversations.id = processes.conversation_id
              WHERE processes.conversation_id = %s
                AND processes.user_id = %s
                AND conversations.visibility = 'learner'
                AND conversations.kind = 'interactive'
                AND conversations.status = 'active'
              UNION ALL
              SELECT
                CASE WHEN requests.kind = 'approval' THEN 'approval' ELSE 'elicitation' END AS kind,
                requests.item_id AS item_id,
                requests.created_at AS created_at,
                35 AS sort_rank,
                NULL::text AS role,
                NULL::text AS content,
                ''::text AS public_thinking_text,
                '[]'::jsonb AS public_thinking_steps_json,
                NULL::uuid AS process_run_id,
                requests.source_turn_id AS turn_id,
                NULL::text AS error_code,
                NULL::boolean AS error_recoverable,
                NULL::uuid AS in_reply_to_item_id,
                requests.id AS interaction_request_id
              FROM tutor_interaction_requests AS requests
              JOIN tutor_conversations AS conversations ON conversations.id = requests.conversation_id
              WHERE requests.conversation_id = %s
                AND requests.user_id = %s
                AND conversations.visibility = 'learner'
                AND conversations.kind = 'interactive'
                AND conversations.status = 'active'
        """
        params: list[object] = [
            conversation_id, user_id,
            conversation_id, user_id,
            conversation_id, user_id,
        ]
        if include_errors:
            timeline += """
              UNION ALL
              SELECT
                'error'::text AS kind,
                jobs.id AS item_id,
                jobs.dead_at AS created_at,
                40 AS sort_rank,
                NULL::text AS role,
                NULL::text AS content,
                ''::text AS public_thinking_text,
                '[]'::jsonb AS public_thinking_steps_json,
                NULL::uuid AS process_run_id,
                jobs.run_id AS turn_id,
                'TUTOR_DISPATCH_FAILED'::text AS error_code,
                true AS error_recoverable,
                NULL::uuid AS in_reply_to_item_id,
                NULL::uuid AS interaction_request_id
              FROM tutor_interactive_dispatch_jobs AS jobs
              JOIN tutor_conversations AS conversations ON conversations.id = jobs.conversation_id
              WHERE jobs.conversation_id = %s
                AND jobs.user_id = %s
                AND jobs.state = 'dead'
                AND conversations.visibility = 'learner'
                AND conversations.kind = 'interactive'
                AND conversations.status = 'active'
              UNION ALL
              SELECT
                'error'::text AS kind,
                errors.id AS item_id,
                errors.created_at AS created_at,
                40 AS sort_rank,
                NULL::text AS role,
                NULL::text AS content,
                ''::text AS public_thinking_text,
                '[]'::jsonb AS public_thinking_steps_json,
                NULL::uuid AS process_run_id,
                errors.run_id AS turn_id,
                errors.code AS error_code,
                errors.recoverable AS error_recoverable,
                NULL::uuid AS in_reply_to_item_id,
                NULL::uuid AS interaction_request_id
              FROM tutor_runtime_public_errors AS errors
              JOIN tutor_conversations AS conversations ON conversations.id = errors.conversation_id
              WHERE errors.conversation_id = %s
                AND errors.user_id = %s
                AND conversations.visibility = 'learner'
                AND conversations.kind = 'interactive'
                AND conversations.status = 'active'
            """
            params.extend((conversation_id, user_id, conversation_id, user_id))
        timeline += """
            )
            SELECT * FROM timeline
        """
        if after is not None:
            timeline += """
            WHERE (
              created_at < %s
              OR (
                created_at = %s
                AND (
                  sort_rank < %s
                  OR (sort_rank = %s AND item_id < %s::uuid)
                )
              )
            )
            """
            params.extend(
                (
                    after["created_at"],
                    after["created_at"],
                    after["sort_rank"],
                    after["sort_rank"],
                    after["item_id"],
                )
            )
        timeline += " ORDER BY created_at DESC, sort_rank DESC, item_id DESC LIMIT %s"
        params.append(limit + 1)
        rows = self._conn.execute(timeline, tuple(params)).fetchall()
        page_rows = rows[:limit]
        from app.services.learning.context_references import PostgresTutorContextReferenceRepository

        learner_message_ids = [
            str(row["item_id"])
            for row in page_rows
            if str(row.get("kind") or "") == "message" and str(row.get("role") or "") == "learner"
        ]
        references_by_message = PostgresTutorContextReferenceRepository(self._conn).read_for_messages(
            user_id=user_id,
            conversation_id=conversation_id,
            message_ids=learner_message_ids,
        )
        records: list[TutorConversationTimelineRecord] = []
        for row in page_rows:
            kind = str(row["kind"])
            created_at = _as_datetime(row.get("created_at")) or datetime.now(UTC)
            if kind == "message":
                role = str(row.get("role") or "")
                if role not in {"learner", "tutor"}:
                    continue
                records.append(
                    TutorConversationTimelineRecord(
                        kind="message",
                        item_id=str(row["item_id"]),
                        created_at=created_at,
                        sort_rank=_as_int(row.get("sort_rank"), 0),
                        role=role,
                        content=str(row.get("content") or ""),
                        public_thinking_text=(
                            _public_thinking_text_from_values(
                                row.get("public_thinking_text"),
                                row.get("public_thinking_steps_json"),
                            )
                            if role == "tutor"
                            else ""
                        ),
                        public_thinking_steps=(
                            _public_thinking_steps_from_value(
                                row.get("public_thinking_steps_json")
                            )
                            if role == "tutor"
                            else ()
                        ),
                        context_references=references_by_message.get(str(row["item_id"]), ()),
                        turn_id=str(row["turn_id"]) if row.get("turn_id") is not None else None,
                        in_reply_to_item_id=_optional_string(row.get("in_reply_to_item_id")),
                    )
                )
                continue
            if kind in {"elicitation", "approval"}:
                request_id = _optional_string(row.get("interaction_request_id"))
                if request_id is None:
                    continue
                request_row = self._conn.execute(
                    "SELECT * FROM tutor_interaction_requests WHERE id = %s AND user_id = %s",
                    (request_id, user_id),
                ).fetchone()
                if request_row is not None:
                    request = _interaction_request_from_row(request_row)
                    records.append(
                        TutorConversationTimelineRecord(
                            kind=kind,
                            item_id=request.item_id,
                            created_at=created_at,
                            sort_rank=_as_int(row.get("sort_rank"), 0),
                            turn_id=request.source_turn_id,
                            request=request,
                        )
                    )
                continue
            if kind == "error":
                records.append(
                    TutorConversationTimelineRecord(
                        kind="error",
                        item_id=str(row["item_id"]),
                        created_at=created_at,
                        sort_rank=_as_int(row.get("sort_rank"), 0),
                        turn_id=_optional_string(row.get("turn_id")),
                        error_code=str(row.get("error_code") or "TUTOR_DISPATCH_FAILED"),
                        error_recoverable=row.get("error_recoverable") is True,
                    )
                )
                continue
            if kind == "process":
                process_run_id = str(row.get("process_run_id") or "")
                process = self.read_public_process(user_id=user_id, run_id=process_run_id, now=now)
                if process is not None:
                    records.append(
                        TutorConversationTimelineRecord(
                            kind="process",
                            item_id=process.run_id,
                            created_at=created_at,
                            sort_rank=_as_int(row.get("sort_rank"), 0),
                            process=process,
                            turn_id=process.run_id,
                        )
                    )
        has_more = len(rows) > limit
        next_cursor = (
            self._encode_public_cursor(
                kind="conversation-history",
                user_id=user_id,
                conversation_id=conversation_id,
                created_at=records[-1].created_at,
                sort_rank=records[-1].sort_rank,
                item_id=records[-1].item_id,
            )
            if has_more and records
            else None
        )
        return tuple(records), next_cursor, has_more

    def _encode_public_cursor(
        self,
        *,
        kind: str,
        user_id: str,
        conversation_id: str | None,
        created_at: datetime,
        sort_rank: int,
        item_id: str,
    ) -> str:
        payload = {
            "v": _CURSOR_VERSION,
            "k": kind,
            "u": user_id,
            "c": conversation_id,
            "t": created_at.astimezone(UTC).isoformat(),
            "r": sort_rank,
            "i": item_id,
        }
        encoded = _base64url_encode(_json(payload).encode("utf-8"))
        signature = hmac.new(self._cursor_signing_key, encoded.encode("ascii"), hashlib.sha256).digest()
        return f"{encoded}.{_base64url_encode(signature)}"

    def _decode_public_cursor(
        self,
        *,
        cursor: str,
        kind: str,
        user_id: str,
        conversation_id: str | None,
    ) -> dict[str, object]:
        parts = cursor.split(".")
        if len(parts) != 2 or not all(parts):
            raise TutorCursorInvalid("cursor is invalid")
        encoded, supplied_signature = parts
        expected_signature = _base64url_encode(
            hmac.new(self._cursor_signing_key, encoded.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise TutorCursorInvalid("cursor is invalid")
        try:
            payload = _as_mapping(json.loads(_base64url_decode(encoded).decode("utf-8")))
            parsed_created_at = _as_datetime(payload.get("t"))
            parsed_rank = _as_int(payload.get("r"), -1)
            item_id = str(payload.get("i") or "")
            valid = (
                _as_int(payload.get("v"), -1) == _CURSOR_VERSION
                and str(payload.get("k") or "") == kind
                and str(payload.get("u") or "") == user_id
                and payload.get("c") == conversation_id
                and parsed_created_at is not None
                and parsed_rank >= 0
                and bool(item_id)
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            valid = False
            parsed_created_at = None
            parsed_rank = -1
            item_id = ""
        if not valid or parsed_created_at is None:
            raise TutorCursorInvalid("cursor is invalid")
        return {"created_at": parsed_created_at, "sort_rank": parsed_rank, "item_id": item_id}

    def read_conversation_snapshot(
        self,
        *,
        user_id: str,
        conversation_id: str,
        limit: int = 40,
        cursor: str | None = None,
        now: datetime | None = None,
    ) -> TutorConversationSnapshot:
        conversation = self._conn.execute(
            """
            SELECT *
            FROM tutor_conversations
            WHERE id = %s AND user_id = %s
              AND visibility = 'learner' AND kind = 'interactive' AND status = 'active'
            FOR SHARE
            """,
            (conversation_id, user_id),
        ).fetchone()
        if conversation is None:
            raise TutorRunNotFound("tutor conversation not found")
        timeline, next_cursor, has_more = self.read_public_history(
            user_id=user_id,
            conversation_id=conversation_id,
            limit=limit,
            cursor=cursor,
            now=now,
            include_errors=True,
        )
        active = self._conn.execute(
            """
            SELECT *
            FROM tutor_runs
            WHERE user_id = %s AND conversation_id = %s AND origin = 'interactive'
              AND terminal_outcome IS NULL AND cancelled_at IS NULL AND superseded_by_run_id IS NULL
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (user_id, conversation_id),
        ).fetchone()
        pending_requests = self.read_pending_interaction_requests(
            user_id=user_id,
            conversation_id=conversation_id,
        )
        queue_rows = self._conn.execute(
            "SELECT * FROM tutor_queued_inputs WHERE user_id = %s AND conversation_id = %s AND state = 'pending' ORDER BY position, created_at, id",
            (user_id, conversation_id),
        ).fetchall()
        queued_inputs = tuple(_queued_input_from_row(row) for row in queue_rows)
        queue_paused = bool(conversation.get("queue_paused"))
        control_state = (
            "waiting" if pending_requests else
            "running" if active is not None else
            "queue_paused" if queue_paused else
            "idle"
        )
        current_sequence = max(0, _as_int(conversation.get("next_public_event_sequence"), 1) - 1)
        return TutorConversationSnapshot(
            conversation_id=conversation_id,
            title=str(conversation["title"]) if conversation.get("title") is not None else None,
            control_version=max(1, _as_int(conversation.get("control_version"), 1)),
            control_state=control_state,
            queue_paused=queue_paused,
            queue_pause_reason=_optional_string(conversation.get("queue_pause_reason")),
            pending_count=len(queued_inputs),
            max_pending=_QUEUE_MAX_PENDING,
            active_turn=self._public_turn_from_row(active) if active is not None else None,
            active_thinking=(
                self._public_active_thinking_from_row(active)
                if active is not None
                else None
            ),
            pending_requests=tuple(item.public_item for item in pending_requests),
            queue=tuple(item.as_public_dict() for item in queued_inputs),
            timeline=timeline,
            next_cursor=next_cursor,
            has_more=has_more,
            stream_cursor=self._encode_conversation_event_cursor(
                user_id=user_id,
                conversation_id=conversation_id,
                sequence=current_sequence,
            ),
        )

    def append_conversation_event(
        self,
        *,
        user_id: str,
        conversation_id: str,
        event_key: str,
        kind: TutorConversationEventKind | str,
        payload: Mapping[str, object],
        occurred_at: datetime,
        turn_id: str | None = None,
        item_id: str | None = None,
        item_kind: str | None = None,
    ) -> TutorConversationEvent:
        with self._conn.transaction():
            return self._append_conversation_event_locked(
                user_id=user_id,
                conversation_id=conversation_id,
                event_key=event_key,
                kind=kind,
                payload=payload,
                occurred_at=occurred_at,
                turn_id=turn_id,
                item_id=item_id,
                item_kind=item_kind,
            )

    def begin_public_thinking_stream(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        decision_iteration: int,
        generation: int,
        provider_attempt: int,
        occurred_at: datetime,
    ) -> None:
        if decision_iteration < 1 or generation < 1 or provider_attempt < 1:
            raise ValueError("public thinking stream identity is invalid")
        with self._conn.transaction():
            _conversation, run = self._lock_run_with_conversation(
                user_id=snapshot.user_id,
                run_id=snapshot.run_id,
                learner_only=False,
            )
            _assert_active_lease(run, lease=lease, now=occurred_at)
            _assert_not_terminal(run)
            _assert_not_cancelled(run)
            _assert_not_superseded(run)
            if snapshot.input_revision != _as_int(run.get("input_revision"), 0):
                raise TutorLeaseConflict("public thinking stream revision is stale")
            existing = self._conn.execute(
                "SELECT * FROM tutor_turn_public_thinking_streams WHERE run_id = %s FOR UPDATE",
                (snapshot.run_id,),
            ).fetchone()
            if existing is not None and generation <= _as_int(existing.get("generation"), 0):
                raise TutorIdempotencyConflict("public thinking generation did not advance")
            if existing is None:
                self._conn.execute(
                    """
                    INSERT INTO tutor_turn_public_thinking_streams (
                      run_id, user_id, conversation_id, input_revision, decision_iteration,
                      generation, provider_attempt, state, thinking_text, next_chunk_sequence,
                      created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'active', '', 1, %s, %s)
                    """,
                    (
                        snapshot.run_id, snapshot.user_id, snapshot.conversation_id,
                        snapshot.input_revision, decision_iteration, generation,
                        provider_attempt, occurred_at, occurred_at,
                    ),
                )
            else:
                self._conn.execute(
                    """
                    UPDATE tutor_turn_public_thinking_streams
                    SET input_revision = %s, decision_iteration = %s, generation = %s,
                        provider_attempt = %s, state = 'active', thinking_text = '',
                        next_chunk_sequence = 1, last_public_event_sequence = NULL,
                        completed_at = NULL, discarded_at = NULL, accepted_at = NULL,
                        updated_at = %s
                    WHERE run_id = %s
                    """,
                    (
                        snapshot.input_revision, decision_iteration, generation,
                        provider_attempt, occurred_at, snapshot.run_id,
                    ),
                )
            event = self._append_conversation_event_locked(
                user_id=snapshot.user_id,
                conversation_id=snapshot.conversation_id,
                event_key=f"turn-output:{snapshot.run_id}:{generation}:reset",
                kind=TutorConversationEventKind.TURN_OUTPUT,
                turn_id=snapshot.run_id,
                payload={
                    "output_version": TUTOR_PUBLIC_THINKING_STREAM_VERSION,
                    "input_revision": snapshot.input_revision,
                    "generation": generation,
                    "operation": "reset",
                    "chunk_sequence": 0,
                },
                occurred_at=occurred_at,
            )
            self._conn.execute(
                "UPDATE tutor_turn_public_thinking_streams SET last_public_event_sequence = %s WHERE run_id = %s",
                (event.sequence, snapshot.run_id),
            )

    def append_public_thinking_text(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        generation: int,
        provider_attempt: int,
        text: str,
        occurred_at: datetime,
    ) -> None:
        if not text or len(text) > PUBLIC_THINKING_CHUNK_MAX_LENGTH:
            raise ValueError("public thinking chunk is empty or oversized")
        with self._conn.transaction():
            _conversation, run = self._lock_run_with_conversation(
                user_id=snapshot.user_id, run_id=snapshot.run_id, learner_only=False
            )
            _assert_active_lease(run, lease=lease, now=occurred_at)
            _assert_not_terminal(run)
            _assert_not_cancelled(run)
            _assert_not_superseded(run)
            if snapshot.input_revision != _as_int(run.get("input_revision"), 0):
                raise TutorLeaseConflict("public thinking stream revision is stale")
            stream = self._lock_public_thinking_stream(
                snapshot=snapshot, generation=generation, provider_attempt=provider_attempt
            )
            if str(stream.get("state")) != "active":
                raise TutorTerminalStateConflict("public thinking stream is not active")
            current_text = str(stream.get("thinking_text") or "")
            cumulative = current_text + text
            if len(cumulative) > MAX_TUTOR_PUBLIC_THINKING_TEXT_LENGTH:
                raise TutorTerminalStateConflict("public thinking stream exceeded its bound")
            if check_teaching_output(cumulative).blocked:
                raise TutorTerminalStateConflict("public thinking stream failed teaching safety")
            chunk_sequence = _as_int(stream.get("next_chunk_sequence"), 1)
            event = self._append_conversation_event_locked(
                user_id=snapshot.user_id,
                conversation_id=snapshot.conversation_id,
                event_key=f"turn-output:{snapshot.run_id}:{generation}:{chunk_sequence}:append",
                kind=TutorConversationEventKind.TURN_OUTPUT,
                turn_id=snapshot.run_id,
                payload={
                    "output_version": TUTOR_PUBLIC_THINKING_STREAM_VERSION,
                    "input_revision": snapshot.input_revision,
                    "generation": generation,
                    "operation": "append",
                    "chunk_sequence": chunk_sequence,
                    "text": text,
                },
                occurred_at=occurred_at,
            )
            updated = self._conn.execute(
                """
                UPDATE tutor_turn_public_thinking_streams
                SET thinking_text = %s, next_chunk_sequence = %s,
                    last_public_event_sequence = %s, updated_at = %s
                WHERE run_id = %s AND generation = %s AND state = 'active'
                RETURNING run_id
                """,
                (
                    cumulative, chunk_sequence + 1, event.sequence, occurred_at,
                    snapshot.run_id, generation,
                ),
            ).fetchone()
            if updated is None:
                raise TutorLifecycleConflict("public thinking append lost generation ownership")

    def complete_public_thinking_stream(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        generation: int,
        provider_attempt: int,
        occurred_at: datetime,
    ) -> None:
        self._finish_public_thinking_stream(
            snapshot=snapshot, lease=lease, generation=generation,
            provider_attempt=provider_attempt, state="complete", operation="complete",
            occurred_at=occurred_at,
        )

    def discard_public_thinking_stream(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        generation: int,
        provider_attempt: int,
        occurred_at: datetime,
    ) -> None:
        self._finish_public_thinking_stream(
            snapshot=snapshot, lease=lease, generation=generation,
            provider_attempt=provider_attempt, state="discarded", operation="discard",
            occurred_at=occurred_at,
        )

    def _finish_public_thinking_stream(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        generation: int,
        provider_attempt: int,
        state: Literal["complete", "discarded"],
        operation: Literal["complete", "discard"],
        occurred_at: datetime,
    ) -> None:
        with self._conn.transaction():
            _conversation, run = self._lock_run_with_conversation(
                user_id=snapshot.user_id, run_id=snapshot.run_id, learner_only=False
            )
            _assert_active_lease(run, lease=lease, now=occurred_at)
            _assert_not_terminal(run)
            _assert_not_cancelled(run)
            _assert_not_superseded(run)
            if snapshot.input_revision != _as_int(run.get("input_revision"), 0):
                raise TutorLeaseConflict("public thinking stream revision is stale")
            stream = self._lock_public_thinking_stream(
                snapshot=snapshot, generation=generation, provider_attempt=provider_attempt
            )
            current_state = str(stream.get("state") or "")
            if current_state == state:
                return
            allowed_states = {"active", "complete"} if state == "discarded" else {"active"}
            if current_state not in allowed_states:
                raise TutorTerminalStateConflict("public thinking stream transition is invalid")
            if state == "complete" and not str(stream.get("thinking_text") or "").strip():
                raise TutorTerminalStateConflict("public thinking stream cannot complete empty")
            chunk_sequence = _as_int(stream.get("next_chunk_sequence"), 1)
            event = self._append_conversation_event_locked(
                user_id=snapshot.user_id,
                conversation_id=snapshot.conversation_id,
                event_key=f"turn-output:{snapshot.run_id}:{generation}:{chunk_sequence}:{operation}",
                kind=TutorConversationEventKind.TURN_OUTPUT,
                turn_id=snapshot.run_id,
                payload={
                    "output_version": TUTOR_PUBLIC_THINKING_STREAM_VERSION,
                    "input_revision": snapshot.input_revision,
                    "generation": generation,
                    "operation": operation,
                    "chunk_sequence": chunk_sequence,
                },
                occurred_at=occurred_at,
            )
            completed_at = occurred_at if state == "complete" else None
            discarded_at = occurred_at if state == "discarded" else None
            updated = self._conn.execute(
                """
                UPDATE tutor_turn_public_thinking_streams
                SET state = %s, next_chunk_sequence = %s, last_public_event_sequence = %s,
                    completed_at = COALESCE(completed_at, %s), discarded_at = %s,
                    accepted_at = NULL, updated_at = %s
                WHERE run_id = %s AND generation = %s
                RETURNING run_id
                """,
                (
                    state, chunk_sequence + 1, event.sequence, completed_at, discarded_at,
                    occurred_at, snapshot.run_id, generation,
                ),
            ).fetchone()
            if updated is None:
                raise TutorLifecycleConflict("public thinking completion lost generation ownership")

    def _lock_public_thinking_stream(
        self,
        *,
        snapshot: TutorRunSnapshot,
        generation: int,
        provider_attempt: int,
    ) -> Mapping[str, object]:
        stream = self._conn.execute(
            "SELECT * FROM tutor_turn_public_thinking_streams WHERE run_id = %s FOR UPDATE",
            (snapshot.run_id,),
        ).fetchone()
        if stream is None:
            raise TutorLifecycleConflict("public thinking stream row is missing")
        if (
            str(stream.get("user_id")) != snapshot.user_id
            or str(stream.get("conversation_id")) != snapshot.conversation_id
            or _as_int(stream.get("input_revision"), -1) != snapshot.input_revision
            or _as_int(stream.get("generation"), -1) != generation
            or _as_int(stream.get("provider_attempt"), -1) != provider_attempt
        ):
            raise TutorLifecycleConflict("public thinking stream scope or generation is stale")
        return stream

    def conversation_events_after(
        self,
        *,
        user_id: str,
        conversation_id: str,
        cursor: str | None,
        limit: int = 100,
    ) -> tuple[TutorConversationEvent, ...]:
        if limit < 1 or limit > 200:
            raise ValueError("conversation event replay limit is invalid")
        conversation = self._conn.execute(
            """
            SELECT next_public_event_sequence
            FROM tutor_conversations
            WHERE id = %s AND user_id = %s
              AND visibility = 'learner' AND kind = 'interactive' AND status = 'active'
            """,
            (conversation_id, user_id),
        ).fetchone()
        if conversation is None:
            raise TutorRunNotFound("tutor conversation not found")
        after_sequence = (
            self._decode_conversation_event_cursor(
                cursor=cursor,
                user_id=user_id,
                conversation_id=conversation_id,
            )
            if cursor
            else 0
        )
        current_sequence = max(0, _as_int(conversation.get("next_public_event_sequence"), 1) - 1)
        if after_sequence > current_sequence:
            raise TutorCursorInvalid("conversation event cursor is ahead of the authoritative sequence")
        minimum = self._conn.execute(
            "SELECT MIN(event_sequence) AS minimum FROM tutor_conversation_events WHERE conversation_id = %s",
            (conversation_id,),
        ).fetchone()
        minimum_sequence = _as_int(minimum.get("minimum") if minimum is not None else None, 0)
        if minimum_sequence > 0 and after_sequence < minimum_sequence - 1:
            raise TutorCursorInvalid("conversation event cursor is older than the retained event window")
        rows = self._conn.execute(
            """
            SELECT *
            FROM tutor_conversation_events
            WHERE user_id = %s AND conversation_id = %s AND event_sequence > %s
            ORDER BY event_sequence ASC
            LIMIT %s
            """,
            (user_id, conversation_id, after_sequence, limit),
        ).fetchall()
        return tuple(
            _conversation_event_from_row(
                row,
                cursor=self._encode_conversation_event_cursor(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    sequence=_as_int(row.get("event_sequence"), 0),
                ),
            )
            for row in rows
        )

    def read_interactive_dispatch_job(self, *, user_id: str, job_id: str) -> TutorInteractiveDispatchJob:
        row = self._conn.execute(
            "SELECT * FROM tutor_interactive_dispatch_jobs WHERE id = %s AND user_id = %s",
            (job_id, user_id),
        ).fetchone()
        if row is None:
            raise TutorRunNotFound("interactive dispatch job not found")
        return _interactive_dispatch_job_from_row(row)

    def claim_interactive_dispatch_jobs(
        self,
        *,
        owner_id: str,
        now: datetime,
        limit: int = 1,
        job_id: str | None = None,
        lease_seconds: int = _DISPATCH_JOB_LEASE_SECONDS,
    ) -> tuple[TutorInteractiveDispatchJob, ...]:
        _safe_key(owner_id, label="dispatch owner")
        if limit < 1 or limit > 50 or lease_seconds < 1:
            raise ValueError("interactive dispatch claim bounds are invalid")
        with self._conn.transaction():
            self._conn.execute(
                """
                UPDATE tutor_interactive_dispatch_jobs AS jobs
                SET state = 'completed', completed_at = %s,
                    lease_owner_id = NULL, lease_expires_at = NULL,
                    last_error_code = COALESCE(last_error_code, 'run_not_active')
                FROM tutor_runs AS runs
                WHERE jobs.run_id = runs.id
                  AND jobs.state IN ('pending', 'retry_wait', 'leased')
                  AND (
                    runs.terminal_outcome IS NOT NULL
                    OR runs.cancelled_at IS NOT NULL
                    OR runs.superseded_by_run_id IS NOT NULL
                  )
                """,
                (now,),
            )
            query = """
                WITH candidates AS (
                  SELECT jobs.id
                  FROM tutor_interactive_dispatch_jobs AS jobs
                  JOIN tutor_runs AS runs ON runs.id = jobs.run_id
                  WHERE (
                    (jobs.state IN ('pending', 'retry_wait') AND jobs.available_at <= %s)
                    OR (jobs.state = 'leased' AND jobs.lease_expires_at <= %s)
                  )
                    AND runs.terminal_outcome IS NULL
                    AND runs.cancelled_at IS NULL
                    AND runs.superseded_by_run_id IS NULL
            """
            params: list[object] = [now, now]
            if job_id is not None:
                query += " AND jobs.id = %s::uuid"
                params.append(job_id)
            query += """
                  ORDER BY jobs.available_at, jobs.created_at, jobs.id
                  LIMIT %s
                  FOR UPDATE OF jobs SKIP LOCKED
                )
                UPDATE tutor_interactive_dispatch_jobs AS jobs
                SET state = 'leased', lease_owner_id = %s,
                    lease_generation = jobs.lease_generation + 1,
                    lease_expires_at = %s,
                    attempt_count = jobs.attempt_count + 1,
                    completed_at = NULL, dead_at = NULL
                FROM candidates
                WHERE jobs.id = candidates.id
                RETURNING jobs.*
            """
            params.extend((limit, owner_id, now + timedelta(seconds=lease_seconds)))
            rows = self._conn.execute(query, tuple(params)).fetchall()
        return tuple(_interactive_dispatch_job_from_row(row) for row in rows)

    def complete_interactive_dispatch_job(
        self,
        *,
        job_id: str,
        owner_id: str,
        lease_generation: int,
        completed_at: datetime,
    ) -> bool:
        with self._conn.transaction():
            row = self._conn.execute(
                """
                UPDATE tutor_interactive_dispatch_jobs
                SET state = 'completed', completed_at = %s,
                    lease_owner_id = NULL, lease_expires_at = NULL,
                    last_error_code = NULL
                WHERE id = %s AND state = 'leased'
                  AND lease_owner_id = %s AND lease_generation = %s
                RETURNING id
                """,
                (completed_at, job_id, owner_id, lease_generation),
            ).fetchone()
        return row is not None

    def retry_interactive_dispatch_job(
        self,
        *,
        job_id: str,
        owner_id: str,
        lease_generation: int,
        error_code: str,
        failed_at: datetime,
    ) -> TutorInteractiveDispatchJob | None:
        _safe_key(error_code, label="dispatch error code")
        with self._conn.transaction():
            reference = self._conn.execute(
                """
                SELECT user_id, conversation_id, run_id
                FROM tutor_interactive_dispatch_jobs
                WHERE id = %s AND state = 'leased'
                  AND lease_owner_id = %s AND lease_generation = %s
                """,
                (job_id, owner_id, lease_generation),
            ).fetchone()
            if reference is None:
                return None
            self._lock_conversation(
                user_id=str(reference["user_id"]),
                conversation_id=str(reference["conversation_id"]),
                learner_only=False,
            )
            run = self._lock_run(user_id=str(reference["user_id"]), run_id=str(reference["run_id"]))
            job = self._conn.execute(
                """
                SELECT * FROM tutor_interactive_dispatch_jobs
                WHERE id = %s AND state = 'leased'
                  AND lease_owner_id = %s AND lease_generation = %s
                FOR UPDATE
                """,
                (job_id, owner_id, lease_generation),
            ).fetchone()
            if job is None:
                return None
            attempt = _as_int(job.get("attempt_count"), 0)
            maximum = _as_int(job.get("max_attempts"), _DISPATCH_JOB_MAX_ATTEMPTS)
            if attempt >= maximum:
                updated_job = self._conn.execute(
                    """
                    UPDATE tutor_interactive_dispatch_jobs
                    SET state = 'dead', dead_at = %s, last_error_code = %s,
                        lease_owner_id = NULL, lease_expires_at = NULL
                    WHERE id = %s AND state = 'leased'
                      AND lease_owner_id = %s AND lease_generation = %s
                    RETURNING *
                    """,
                    (failed_at, error_code, job_id, owner_id, lease_generation),
                ).fetchone()
                if updated_job is None:
                    return None
                terminal_run = run
                if (
                    run.get("terminal_outcome") is None
                    and run.get("cancelled_at") is None
                    and run.get("superseded_by_run_id") is None
                ):
                    terminal_run = self._conn.execute(
                        """
                        UPDATE tutor_runs
                        SET status = 'failed', terminal_outcome = 'failed',
                            terminal_diagnostic_code = 'dispatch_retry_exhausted', terminal_at = %s,
                            active_lease_owner_id = NULL, active_lease_expires_at = NULL
                        WHERE id = %s AND user_id = %s
                          AND terminal_outcome IS NULL AND cancelled_at IS NULL
                          AND superseded_by_run_id IS NULL
                        RETURNING *
                        """,
                        (failed_at, run["id"], run["user_id"]),
                    ).fetchone() or run
                    self._append_event_locked(
                        run_id=str(run["id"]),
                        event_key=f"terminal:dispatch-dead:{_as_int(terminal_run.get('input_revision'), 0)}",
                        kind="terminal_result",
                        input_revision=_as_int(terminal_run.get("input_revision"), 0),
                        payload={
                            "kind": "terminal_result",
                            "status": "failed",
                            "run_id": str(run["id"]),
                            "input_revision": _as_int(terminal_run.get("input_revision"), 0),
                        },
                    )
                    self._freeze_public_process_locked(
                        run=terminal_run,
                        display_state="failed",
                        step_key=None,
                        occurred_at=failed_at,
                    )
                    self._append_turn_event_locked(
                        run=terminal_run,
                        kind=TutorConversationEventKind.TURN_UPDATED,
                        event_key=f"turn:{run['id']}:dispatch-dead",
                        occurred_at=failed_at,
                    )
                self._append_conversation_event_locked(
                    user_id=str(reference["user_id"]),
                    conversation_id=str(reference["conversation_id"]),
                    event_key=f"dispatch:{job_id}:dead:{lease_generation}",
                    kind=TutorConversationEventKind.DISPATCH_DEAD,
                    turn_id=str(reference["run_id"]),
                    item_id=job_id,
                    item_kind="error",
                    payload={
                        "code": "TUTOR_DISPATCH_FAILED",
                        "recoverable": True,
                        "attempt": max(1, attempt),
                    },
                    occurred_at=failed_at,
                )
                return _interactive_dispatch_job_from_row(updated_job)
            backoff_seconds = min(300, 2 ** min(max(1, attempt), 8))
            updated_job = self._conn.execute(
                """
                UPDATE tutor_interactive_dispatch_jobs
                SET state = 'retry_wait', available_at = %s, last_error_code = %s,
                    lease_owner_id = NULL, lease_expires_at = NULL
                WHERE id = %s AND state = 'leased'
                  AND lease_owner_id = %s AND lease_generation = %s
                RETURNING *
                """,
                (
                    failed_at + timedelta(seconds=backoff_seconds),
                    error_code,
                    job_id,
                    owner_id,
                    lease_generation,
                ),
            ).fetchone()
            if updated_job is None:
                return None
            if _protocol_version_from_row(run) is TutorInteractionProtocolVersion.THREAD_TURN_V2:
                self._append_conversation_event_locked(
                    user_id=str(reference["user_id"]),
                    conversation_id=str(reference["conversation_id"]),
                    event_key=f"dispatch:{job_id}:delayed:{lease_generation}",
                    kind=TutorConversationEventKind.DISPATCH_DELAYED,
                    turn_id=str(reference["run_id"]),
                    payload={
                        "code": "TUTOR_DISPATCH_DELAYED",
                        "recoverable": True,
                        "attempt": max(1, attempt),
                    },
                    occurred_at=failed_at,
                )
            return _interactive_dispatch_job_from_row(updated_job)

    def _ensure_interactive_dispatch_job_locked(
        self,
        *,
        run: Mapping[str, object],
        available_at: datetime,
    ) -> TutorInteractiveDispatchJob | None:
        if (
            str(run.get("origin") or "") != "interactive"
            or _protocol_version_from_row(run) is not TutorInteractionProtocolVersion.THREAD_TURN_V2
        ):
            return None
        row = self._conn.execute(
            """
            INSERT INTO tutor_interactive_dispatch_jobs (
              run_id, user_id, conversation_id, state, max_attempts, available_at
            )
            VALUES (%s, %s, %s, 'pending', %s, %s)
            ON CONFLICT (run_id) DO UPDATE
            SET state = 'pending', available_at = EXCLUDED.available_at,
                attempt_count = 0,
                lease_owner_id = NULL, lease_expires_at = NULL,
                lease_generation = tutor_interactive_dispatch_jobs.lease_generation + 1,
                last_error_code = NULL, completed_at = NULL, dead_at = NULL
            RETURNING *
            """,
            (
                run["id"],
                run["user_id"],
                run["conversation_id"],
                _DISPATCH_JOB_MAX_ATTEMPTS,
                available_at,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("interactive dispatch job insert failed")
        return _interactive_dispatch_job_from_row(row)

    def _append_turn_event_locked(
        self,
        *,
        run: Mapping[str, object],
        kind: TutorConversationEventKind,
        event_key: str,
        occurred_at: datetime,
    ) -> TutorConversationEvent | None:
        if (
            str(run.get("origin") or "") != "interactive"
            or _protocol_version_from_row(run) is not TutorInteractionProtocolVersion.THREAD_TURN_V2
        ):
            return None
        return self._append_conversation_event_locked(
            user_id=str(run["user_id"]),
            conversation_id=str(run["conversation_id"]),
            event_key=event_key,
            kind=kind,
            turn_id=str(run["id"]),
            payload={"turn": self._public_turn_from_row(run)},
            occurred_at=occurred_at,
        )

    def _append_item_reference_event_locked(
        self,
        *,
        run: Mapping[str, object],
        event_key: str,
        kind: TutorConversationEventKind,
        item_id: str,
        item_kind: str,
        occurred_at: datetime,
    ) -> TutorConversationEvent | None:
        if (
            str(run.get("origin") or "") != "interactive"
            or _protocol_version_from_row(run) is not TutorInteractionProtocolVersion.THREAD_TURN_V2
        ):
            return None
        return self._append_conversation_event_locked(
            user_id=str(run["user_id"]),
            conversation_id=str(run["conversation_id"]),
            event_key=event_key,
            kind=kind,
            turn_id=str(run["id"]),
            item_id=item_id,
            item_kind=item_kind,
            payload={
                "item": {
                    "item_id": item_id,
                    "item_kind": item_kind,
                    "turn_id": str(run["id"]),
                }
            },
            occurred_at=occurred_at,
        )

    def _append_conversation_event_locked(
        self,
        *,
        user_id: str,
        conversation_id: str,
        event_key: str,
        kind: TutorConversationEventKind | str,
        payload: Mapping[str, object],
        occurred_at: datetime,
        turn_id: str | None = None,
        item_id: str | None = None,
        item_kind: str | None = None,
    ) -> TutorConversationEvent:
        _safe_key(event_key, label="conversation event key")
        normalized_kind = TutorConversationEventKind(str(kind))
        safe_payload = validate_conversation_event_payload(normalized_kind, payload)
        _validate_conversation_event_identity(
            kind=normalized_kind,
            payload=safe_payload,
            turn_id=turn_id,
            item_id=item_id,
            item_kind=item_kind,
        )
        payload_hash = _sha256_json(safe_payload)
        conversation = self._lock_conversation(
            user_id=user_id,
            conversation_id=conversation_id,
            learner_only=False,
        )
        existing = self._conn.execute(
            """
            SELECT * FROM tutor_conversation_events
            WHERE conversation_id = %s AND event_key = %s
            """,
            (conversation_id, event_key),
        ).fetchone()
        if existing is not None:
            if (
                str(existing.get("payload_hash") or "") != payload_hash
                or str(existing.get("kind") or "") != normalized_kind.value
                or _optional_string(existing.get("turn_id")) != turn_id
                or _optional_string(existing.get("item_id")) != item_id
                or _optional_string(existing.get("item_kind")) != item_kind
            ):
                raise TutorIdempotencyConflict("conversation event key conflicts with different public facts")
            return _conversation_event_from_row(
                existing,
                cursor=self._encode_conversation_event_cursor(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    sequence=_as_int(existing.get("event_sequence"), 0),
                ),
            )
        sequence = max(1, _as_int(conversation.get("next_public_event_sequence"), 1))
        advanced = self._conn.execute(
            """
            UPDATE tutor_conversations
            SET next_public_event_sequence = next_public_event_sequence + 1
            WHERE id = %s AND user_id = %s AND next_public_event_sequence = %s
            RETURNING id
            """,
            (conversation_id, user_id, sequence),
        ).fetchone()
        if advanced is None:
            raise TutorIdempotencyConflict("conversation public event sequence changed before append")
        row = self._conn.execute(
            """
            INSERT INTO tutor_conversation_events (
              user_id, conversation_id, event_sequence, event_key, kind,
              turn_id, item_id, item_kind, projection_version,
              payload_json, payload_hash, occurred_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            RETURNING *
            """,
            (
                user_id,
                conversation_id,
                sequence,
                event_key,
                normalized_kind.value,
                turn_id,
                item_id,
                item_kind,
                TUTOR_CONVERSATION_EVENT_PROJECTION_VERSION,
                _json(safe_payload),
                payload_hash,
                occurred_at,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("conversation event insert failed")
        return _conversation_event_from_row(
            row,
            cursor=self._encode_conversation_event_cursor(
                user_id=user_id,
                conversation_id=conversation_id,
                sequence=sequence,
            ),
        )

    def _public_active_thinking_from_row(
        self,
        run: Mapping[str, object],
    ) -> dict[str, object] | None:
        row = self._conn.execute(
            """
            SELECT *
            FROM tutor_turn_public_thinking_streams
            WHERE run_id = %s AND user_id = %s AND conversation_id = %s
              AND input_revision = %s AND state IN ('active', 'complete')
            """,
            (run["id"], run["user_id"], run["conversation_id"], run["input_revision"]),
        ).fetchone()
        if row is None:
            return None
        return {
            "turn_id": str(row["run_id"]),
            "input_revision": _as_int(row.get("input_revision"), 0),
            "generation": _as_int(row.get("generation"), 1),
            "state": str(row.get("state") or "active"),
            "text": str(row.get("thinking_text") or ""),
            "complete": str(row.get("state") or "") == "complete",
            "last_event_sequence": _as_int(row.get("last_public_event_sequence"), 0),
        }

    def _public_turn_from_row(self, row: Mapping[str, object]) -> dict[str, object]:
        turn = TutorPublicTurn(
            turn_id=str(row["id"]),
            conversation_id=str(row["conversation_id"]),
            interaction_protocol_version=_protocol_version_from_row(row),
            status=public_turn_status(
                terminal_outcome=_optional_string(row.get("terminal_outcome")),
                cancelled=row.get("cancelled_at") is not None,
                superseded=row.get("superseded_by_run_id") is not None,
            ),
            input_revision=_as_int(row.get("input_revision"), 0),
            retry_of_turn_id=_optional_string(row.get("retry_of_turn_id")),
            retry_root_turn_id=_optional_string(row.get("retry_root_turn_id")),
            completion_reason=cast(
                Literal["awaiting_user", "awaiting_approval", "awaiting_authority"] | None,
                _optional_string(row.get("completion_reason")),
            ),
            created_at=(_as_datetime(row.get("created_at")) or datetime.now(UTC)).astimezone(UTC).isoformat(),
            updated_at=(_as_datetime(row.get("updated_at")) or datetime.now(UTC)).astimezone(UTC).isoformat(),
        )
        return dict(turn.model_dump(mode="json", exclude_none=True))

    def _encode_conversation_event_cursor(
        self,
        *,
        user_id: str,
        conversation_id: str,
        sequence: int,
    ) -> str:
        if sequence < 0:
            raise ValueError("conversation event cursor sequence must be non-negative")
        payload = {
            "v": TUTOR_CONVERSATION_STREAM_CURSOR_VERSION,
            "k": _CONVERSATION_EVENT_CURSOR_KIND,
            "u": user_id,
            "c": conversation_id,
            "s": sequence,
        }
        encoded = _base64url_encode(_json(payload).encode("utf-8"))
        signature = hmac.new(self._cursor_signing_key, encoded.encode("ascii"), hashlib.sha256).digest()
        return f"{encoded}.{_base64url_encode(signature)}"

    def _decode_conversation_event_cursor(
        self,
        *,
        cursor: str,
        user_id: str,
        conversation_id: str,
    ) -> int:
        parts = cursor.split(".")
        if len(parts) != 2 or not all(parts):
            raise TutorCursorInvalid("conversation event cursor is invalid")
        encoded, supplied_signature = parts
        expected_signature = _base64url_encode(
            hmac.new(self._cursor_signing_key, encoded.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise TutorCursorInvalid("conversation event cursor is invalid")
        try:
            payload = _as_mapping(json.loads(_base64url_decode(encoded).decode("utf-8")))
            sequence = _as_int(payload.get("s"), -1)
            valid = (
                _as_int(payload.get("v"), -1) == TUTOR_CONVERSATION_STREAM_CURSOR_VERSION
                and str(payload.get("k") or "") == _CONVERSATION_EVENT_CURSOR_KIND
                and str(payload.get("u") or "") == user_id
                and str(payload.get("c") or "") == conversation_id
                and sequence >= 0
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            valid = False
            sequence = -1
        if not valid:
            raise TutorCursorInvalid("conversation event cursor is invalid")
        return sequence

    def load_snapshot(self, *, user_id: str, run_id: str) -> TutorRunSnapshot | None:
        row = self._conn.execute(
            "SELECT * FROM tutor_runs WHERE id = %s AND user_id = %s",
            (run_id, user_id),
        ).fetchone()
        return _snapshot_from_row(row) if row is not None else None

    def read_run_state(self, *, user_id: str, run_id: str) -> TutorRunReadState:
        row = self._conn.execute(
            "SELECT * FROM tutor_runs WHERE id = %s AND user_id = %s",
            (run_id, user_id),
        ).fetchone()
        if row is None:
            raise TutorRunNotFound("tutor run not found")
        terminal_value = row.get("terminal_outcome")
        terminal_outcome = TutorTerminalOutcome(str(terminal_value)) if terminal_value is not None else None
        diagnostic = str(row["terminal_diagnostic_code"]) if row.get("terminal_diagnostic_code") is not None else None
        return TutorRunReadState(
            snapshot=_snapshot_from_row(row),
            terminal_outcome=terminal_outcome,
            diagnostic_code=diagnostic,
            created_at=_as_datetime(row.get("created_at")) or datetime.now(UTC),
            updated_at=_as_datetime(row.get("updated_at")) or datetime.now(UTC),
            interaction_protocol_version=_protocol_version_from_row(row),
            retry_of_turn_id=str(row["retry_of_turn_id"]) if row.get("retry_of_turn_id") is not None else None,
            retry_root_turn_id=str(row["retry_root_turn_id"]) if row.get("retry_root_turn_id") is not None else None,
            response_to_request_id=(
                str(row["response_to_request_id"])
                if row.get("response_to_request_id") is not None
                else None
            ),
            completion_reason=(
                TutorTurnCompletionReason(str(row["completion_reason"]))
                if row.get("completion_reason") is not None
                else None
            ),
        )

    def acquire_lease(
        self,
        *,
        user_id: str,
        run_id: str,
        owner_id: str,
        now: datetime,
        duration_seconds: int,
    ) -> TutorLease | None:
        _safe_key(owner_id, label="lease owner")
        if duration_seconds <= 0:
            raise ValueError("lease duration must be positive")
        with self._conn.transaction():
            run = self._lock_run(user_id=user_id, run_id=run_id)
            if _is_terminal(run) or run.get("cancelled_at") is not None or run.get("superseded_by_run_id") is not None:
                return None
            expires_at = _as_datetime(run.get("active_lease_expires_at"))
            current_owner = str(run.get("active_lease_owner_id") or "")
            if expires_at is not None and expires_at > now and current_owner and current_owner != owner_id:
                return None
            generation = _as_int(run.get("active_lease_generation"), 0) + 1
            new_expiry = now + timedelta(seconds=duration_seconds)
            row = self._conn.execute(
                """
                UPDATE tutor_runs
                SET status = 'leased', active_lease_owner_id = %s,
                    active_lease_generation = %s, active_lease_expires_at = %s
                WHERE id = %s AND user_id = %s
                RETURNING id, active_lease_owner_id, active_lease_generation, active_lease_expires_at
                """,
                (owner_id, generation, new_expiry, run_id, user_id),
            ).fetchone()
            if row is None:
                return None
            return TutorLease(
                run_id=str(row["id"]),
                owner_id=str(row["active_lease_owner_id"]),
                generation=_as_int(row["active_lease_generation"], 1),
                expires_at=_as_datetime(row["active_lease_expires_at"]) or new_expiry,
            )

    def heartbeat_lease(
        self,
        *,
        user_id: str,
        lease: TutorLease,
        now: datetime,
        duration_seconds: int,
    ) -> TutorLease | None:
        if duration_seconds <= 0:
            raise ValueError("lease duration must be positive")
        new_expiry = now + timedelta(seconds=duration_seconds)
        with self._conn.transaction():
            # Permit a late heartbeat only while the exact owner/generation CAS
            # still matches. A replacement claim increments the generation, so
            # an obsolete worker can never renew after another owner takes over.
            row = self._conn.execute(
                """
                UPDATE tutor_runs
                SET active_lease_expires_at = %s
                WHERE id = %s
                  AND user_id = %s
                  AND active_lease_owner_id = %s
                  AND active_lease_generation = %s
                  AND terminal_outcome IS NULL
                  AND cancelled_at IS NULL
                  AND superseded_by_run_id IS NULL
                RETURNING id, active_lease_owner_id, active_lease_generation, active_lease_expires_at
                """,
                (new_expiry, lease.run_id, user_id, lease.owner_id, lease.generation),
            ).fetchone()
            if row is None:
                return None
            return TutorLease(
                run_id=str(row["id"]),
                owner_id=str(row["active_lease_owner_id"]),
                generation=_as_int(row["active_lease_generation"], 1),
                expires_at=_as_datetime(row["active_lease_expires_at"]) or new_expiry,
            )

    def current_input_revision(self, *, user_id: str, run_id: str) -> int:
        row = self._conn.execute(
            "SELECT input_revision FROM tutor_runs WHERE id = %s AND user_id = %s",
            (run_id, user_id),
        ).fetchone()
        if row is None:
            raise TutorRunNotFound("tutor run not found")
        return _as_int(row["input_revision"], 0)

    def is_cancelled(self, *, user_id: str, run_id: str) -> bool:
        row = self._conn.execute(
            "SELECT cancelled_at FROM tutor_runs WHERE id = %s AND user_id = %s",
            (run_id, user_id),
        ).fetchone()
        if row is None:
            raise TutorRunNotFound("tutor run not found")
        return row.get("cancelled_at") is not None

    def is_superseded(self, *, user_id: str, run_id: str) -> bool:
        row = self._conn.execute(
            "SELECT superseded_by_run_id FROM tutor_runs WHERE id = %s AND user_id = %s",
            (run_id, user_id),
        ).fetchone()
        if row is None:
            raise TutorRunNotFound("tutor run not found")
        return row.get("superseded_by_run_id") is not None

    def request_cancellation(self, *, user_id: str, run_id: str, now: datetime) -> None:
        """Terminally cancel one run without allowing a post-provider public write.

        This uses the same conversation-then-run lock order as normal replacement
        and terminal persistence.  A cancellation therefore cannot slip between
        the stale check and the Tutor-message write of an in-flight run.
        """

        with self._conn.transaction():
            conversation, run = self._lock_run_with_conversation(
                user_id=user_id,
                run_id=run_id,
                learner_only=False,
            )
            if _is_terminal(run):
                return
            updated = self._conn.execute(
                """
                UPDATE tutor_runs
                SET status = 'cancelled',
                    cancelled_at = COALESCE(cancelled_at, %s),
                    terminal_outcome = 'cancelled',
                    terminal_diagnostic_code = COALESCE(terminal_diagnostic_code, 'cancelled'),
                    terminal_at = COALESCE(terminal_at, %s),
                    active_lease_owner_id = NULL,
                    active_lease_expires_at = NULL
                WHERE id = %s AND user_id = %s AND terminal_outcome IS NULL
                RETURNING *
                """,
                (now, now, run_id, user_id),
            ).fetchone()
            if updated is None:
                return
            if str(updated.get("origin")) == "interactive" and str(conversation.get("visibility")) == "learner":
                self._freeze_public_process_locked(
                    run=updated,
                    display_state="unavailable",
                    step_key=None,
                    occurred_at=now,
                )
            self._append_event_locked(
                run_id=run_id,
                event_key=f"terminal:cancelled:{_as_int(updated['input_revision'], 0)}",
                kind="terminal_result",
                input_revision=_as_int(updated["input_revision"], 0),
                payload={
                    "kind": "terminal_result",
                    "status": "cancelled",
                    "run_id": run_id,
                    "input_revision": _as_int(updated["input_revision"], 0),
                },
            )
            self._append_turn_event_locked(
                run=updated,
                kind=TutorConversationEventKind.TURN_UPDATED,
                event_key=f"turn:{run_id}:cancelled",
                occurred_at=now,
            )

    def accept_input(
        self,
        *,
        user_id: str,
        run_id: str,
        idempotency_key: str,
        content: str,
        body_hash: str | None = None,
        source: str = "learner",
        role: str = "learner",
        received_at: datetime | None = None,
        ensure_dispatch: bool = True,
    ) -> TutorInputAcceptance:
        _safe_key(idempotency_key, label="input idempotency key")
        _safe_key(source, label="input source")
        if role not in {"learner", "tutor"} or (role == "tutor" and source not in {"authority_receipt", "retry"}):
            raise ValueError("Tutor input role is invalid")
        raw_content = str(content)
        if not raw_content or len(raw_content) > 16_000:
            raise ValueError("learner message must be non-empty and bounded")
        actual_hash = _sha256_text(raw_content)
        if body_hash is not None and body_hash != actual_hash:
            raise TutorIdempotencyConflict("input body hash does not match learner message")
        accepted_at = received_at or datetime.now(UTC)
        event_key = f"input:{idempotency_key}"
        with self._conn.transaction():
            _conversation, run = self._lock_run_with_conversation(
                user_id=user_id,
                run_id=run_id,
                learner_only=False,
            )
            existing = self._conn.execute(
                """
                SELECT input_revision, message_id, body_hash
                FROM tutor_run_input_events
                WHERE run_id = %s AND idempotency_key = %s
                """,
                (run_id, idempotency_key),
            ).fetchone()
            if existing is not None:
                if str(existing["body_hash"]) != actual_hash:
                    raise TutorIdempotencyConflict("input idempotency key has a different body hash")
                event = self._event_by_key_locked(run_id=run_id, event_key=event_key)
                if event is None:
                    raise RuntimeError("input replay event is missing")
                dispatch = self._conn.execute(
                    "SELECT id FROM tutor_interactive_dispatch_jobs WHERE run_id = %s",
                    (run_id,),
                ).fetchone()
                return TutorInputAcceptance(
                    run_id=run_id,
                    message_id=str(existing["message_id"]),
                    input_revision=_as_int(existing["input_revision"], 0),
                    event=event,
                    replayed=True,
                    dispatch_job_id=str(dispatch["id"]) if dispatch is not None else None,
                )
            _assert_not_cancelled(run)
            _assert_not_superseded(run)
            _assert_not_terminal(run)
            message = self._conn.execute(
                """
                INSERT INTO tutor_messages (conversation_id, role, content, created_at)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (run["conversation_id"], role, raw_content, accepted_at),
            ).fetchone()
            if message is None:
                raise RuntimeError("tutor learner message insert failed")
            updated = self._conn.execute(
                """
                UPDATE tutor_runs
                SET input_revision = input_revision + 1,
                    status = CASE
                      WHEN status = 'waiting_for_input' AND continuation_kind IS NOT NULL THEN 'queued'
                      ELSE status
                    END,
                    continuation_kind = CASE
                      WHEN status = 'waiting_for_input' AND continuation_kind IS NOT NULL THEN NULL
                      ELSE continuation_kind
                    END
                WHERE id = %s AND user_id = %s AND input_revision = %s
                RETURNING *
                """,
                (run_id, user_id, _as_int(run["input_revision"], 0)),
            ).fetchone()
            if updated is None:
                raise TutorIdempotencyConflict("input revision changed before acceptance")
            revision = _as_int(updated["input_revision"], 0)
            self._conn.execute(
                """
                INSERT INTO tutor_run_input_events (
                  run_id, conversation_id, message_id, input_revision,
                  idempotency_key, body_hash, source, accepted_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    run_id,
                    run["conversation_id"],
                    message["id"],
                    revision,
                    idempotency_key,
                    actual_hash,
                    source,
                    accepted_at,
                ),
            )
            event = self._append_event_locked(
                run_id=run_id,
                event_key=event_key,
                kind="input_accepted",
                input_revision=revision,
                payload={
                    "kind": "input_accepted",
                    "status": "accepted",
                    "run_id": run_id,
                    "conversation_id": str(run["conversation_id"]),
                    "message_id": str(message["id"]),
                    "input_revision": revision,
                    "request_hash": actual_hash,
                },
            )
            self._touch_conversation_public_activity_locked(
                user_id=user_id,
                conversation_id=str(run["conversation_id"]),
                occurred_at=accepted_at,
            )
            dispatch_job = (
                self._ensure_interactive_dispatch_job_locked(run=updated, available_at=accepted_at)
                if ensure_dispatch
                else None
            )
            self._trip_failpoint("after_interactive_dispatch_job")
            if _protocol_version_from_row(updated) is TutorInteractionProtocolVersion.THREAD_TURN_V2:
                self._append_turn_event_locked(
                    run=updated,
                    kind=(
                        TutorConversationEventKind.TURN_CREATED
                        if revision == 1
                        else TutorConversationEventKind.TURN_UPDATED
                    ),
                    event_key=(
                        f"turn:{run_id}:created"
                        if revision == 1
                        else f"turn:{run_id}:input:{revision}"
                    ),
                    occurred_at=accepted_at,
                )
                self._append_item_reference_event_locked(
                    run=updated,
                    event_key=f"item:message:{message['id']}:added",
                    kind=TutorConversationEventKind.ITEM_ADDED,
                    item_id=str(message["id"]),
                    item_kind="message",
                    occurred_at=accepted_at,
                )
            return TutorInputAcceptance(
                run_id=run_id,
                message_id=str(message["id"]),
                input_revision=revision,
                event=event,
                replayed=False,
                dispatch_job_id=dispatch_job.job_id if dispatch_job is not None else None,
            )

    def append_safe_event(
        self,
        *,
        user_id: str,
        run_id: str,
        event_key: str,
        kind: str,
        input_revision: int,
        payload: Mapping[str, object],
    ) -> TutorDurableEvent:
        _safe_key(event_key, label="event key")
        _safe_key(kind, label="event kind")
        if kind not in _DURABLE_EVENT_KINDS:
            raise ValueError("event kind is not part of the Child 02 durable vocabulary")
        if input_revision < 0:
            raise ValueError("event input revision must be non-negative")
        with self._conn.transaction():
            run = self._lock_run(user_id=user_id, run_id=run_id)
            if (
                _is_terminal(run)
                or run.get("cancelled_at") is not None
                or run.get("superseded_by_run_id") is not None
            ) and kind != "terminal_result":
                raise TutorTerminalStateConflict("terminal, cancelled, or superseded Tutor run cannot append a non-terminal event")
            return self._append_event_locked(
                run_id=run_id,
                event_key=event_key,
                kind=kind,
                input_revision=input_revision,
                payload=payload,
            )

    def events_after(
        self,
        *,
        user_id: str,
        run_id: str,
        after_sequence: int,
        limit: int = 100,
    ) -> tuple[TutorDurableEvent, ...]:
        if after_sequence < 0 or limit < 1 or limit > 200:
            raise ValueError("event replay cursor or limit is invalid")
        rows = self._conn.execute(
            """
            SELECT events.*
            FROM tutor_run_events AS events
            JOIN tutor_runs AS runs ON runs.id = events.run_id
            WHERE events.run_id = %s
              AND runs.user_id = %s
              AND events.event_sequence > %s
            ORDER BY events.event_sequence ASC
            LIMIT %s
            """,
            (run_id, user_id, after_sequence, limit),
        ).fetchall()
        return tuple(_event_from_row(row, projector=self._projector) for row in rows)

    def public_tutor_message(
        self,
        *,
        user_id: str,
        run_id: str,
        message_id: str,
    ) -> str | None:
        """Load only a scoped, already-guarded Tutor public message."""

        row = self._conn.execute(
            """
            SELECT messages.content
            FROM tutor_runs AS runs
            JOIN tutor_messages AS messages
              ON messages.conversation_id = runs.conversation_id
            WHERE runs.id = %s
              AND runs.user_id = %s
              AND messages.id = %s
              AND messages.role = 'tutor'
            """,
            (run_id, user_id, message_id),
        ).fetchone()
        if row is None:
            return None
        return sanitize_summary_text(str(row["content"]), max_length=1_200) or None

    def record_skill_selection(
        self,
        *,
        user_id: str,
        run_id: str,
        input_revision: int,
        selection: TutorSkillSelection,
    ) -> TutorSkillSelectionEvidence:
        if input_revision < 0 or not is_exact_semver(selection.reference.version):
            raise TutorCatalogEvidenceError("Skill selection must use exact reviewed SemVer")
        event_key = f"skill-selection:{input_revision}"
        with self._conn.transaction():
            _conversation, run = self._lock_run_with_conversation(
                user_id=user_id,
                run_id=run_id,
                learner_only=False,
            )
            _assert_not_terminal(run)
            _assert_not_cancelled(run)
            _assert_not_superseded(run)
            if input_revision != _as_int(run["input_revision"], 0):
                raise TutorIdempotencyConflict("Skill selection revision is no longer current")
            evaluation_hash = self._catalog_evaluation_hash(
                digest=str(run["catalog_digest"]),
                skill_id=selection.reference.skill_id,
                skill_version=selection.reference.version,
                manifest_hash=selection.manifest_hash,
                instruction_hash=selection.instruction_hash,
            )
            existing = self._conn.execute(
                """
                SELECT *
                FROM tutor_run_skill_selections
                WHERE run_id = %s AND input_revision = %s
                """,
                (run_id, input_revision),
            ).fetchone()
            if existing is not None:
                evidence = _selection_from_row(existing)
                if (
                    evidence[2] != selection.reference.skill_id
                    or evidence[3] != selection.reference.version
                    or evidence[4] != selection.manifest_hash
                    or evidence[5] != selection.instruction_hash
                    or evidence[6] != evaluation_hash
                ):
                    raise TutorIdempotencyConflict("Skill selection conflicts with durable evidence")
                event = self._event_by_key_locked(run_id=run_id, event_key=event_key)
                if event is None:
                    raise RuntimeError("Skill selection event is missing")
                return TutorSkillSelectionEvidence(*evidence, event=event, replayed=True)
            self._conn.execute(
                """
                INSERT INTO tutor_run_skill_selections (
                  run_id, input_revision, skill_id, skill_version,
                  manifest_hash, instruction_hash, evaluation_hash
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    run_id,
                    input_revision,
                    selection.reference.skill_id,
                    selection.reference.version,
                    selection.manifest_hash,
                    selection.instruction_hash,
                    evaluation_hash,
                ),
            )
            event = self._append_event_locked(
                run_id=run_id,
                event_key=event_key,
                kind="skill_selected",
                input_revision=input_revision,
                payload={
                    "kind": "skill_selected",
                    "run_id": run_id,
                    "input_revision": input_revision,
                    "catalog_digest": str(run["catalog_digest"]),
                    "skill_id": selection.reference.skill_id,
                    "skill_version": selection.reference.version,
                    "manifest_hash": selection.manifest_hash,
                    "instruction_hash": selection.instruction_hash,
                    "evaluation_hash": evaluation_hash,
                },
            )
            self._advance_public_process_locked(
                run=run,
                step_key="context_prepared",
                occurred_at=event.created_at,
            )
            return TutorSkillSelectionEvidence(
                run_id=run_id,
                input_revision=input_revision,
                skill_id=selection.reference.skill_id,
                skill_version=selection.reference.version,
                manifest_hash=selection.manifest_hash,
                instruction_hash=selection.instruction_hash,
                evaluation_hash=evaluation_hash,
                event=event,
                replayed=False,
            )

    def load_skill_selection(
        self,
        *,
        user_id: str,
        run_id: str,
        input_revision: int,
    ) -> TutorSkillSelection | None:
        if input_revision < 0:
            raise ValueError("Skill selection revision must be non-negative")
        row = self._conn.execute(
            """
            SELECT selections.skill_id, selections.skill_version,
                   selections.manifest_hash, selections.instruction_hash
            FROM tutor_run_skill_selections AS selections
            JOIN tutor_runs AS runs ON runs.id = selections.run_id
            WHERE selections.run_id = %s
              AND selections.input_revision = %s
              AND runs.user_id = %s
            """,
            (run_id, input_revision, user_id),
        ).fetchone()
        if row is None:
            return None
        try:
            return TutorSkillSelection(
                reference=CatalogSkillReference(
                    skill_id=str(row["skill_id"]),
                    version=str(row["skill_version"]),
                ),
                manifest_hash=str(row["manifest_hash"]),
                instruction_hash=str(row["instruction_hash"]),
            )
        except ValueError as exc:
            raise TutorCatalogEvidenceError("stored Skill selection is invalid") from exc

    def record_capability_invocation(
        self,
        *,
        user_id: str,
        run_id: str,
        lease: TutorLease,
        input_revision: int,
        request: TutorCapabilityRequest,
        result: TutorCapabilityResult,
        capability_version: str,
        catalog_digest: str,
        policy_fingerprint: str,
        duration_ms: int = 0,
    ) -> TutorCapabilityInvocationReceipt:
        if input_revision < 0 or duration_ms < 0 or not is_exact_semver(capability_version):
            raise ValueError("capability receipt metadata is invalid")
        if not _SHA256.fullmatch(catalog_digest) or not _SHA256.fullmatch(policy_fingerprint):
            raise ValueError("capability receipt hash is invalid")
        invocation_key = f"capability:{request.request_id}"
        if result.request_id != request.request_id:
            raise TutorPersistenceError("capability result does not match its request")
        request_hash = _payload_fields_hash(request.arguments)
        result_hash = _payload_fields_hash(result.safe_result)
        with self._conn.transaction():
            _conversation, run = self._lock_run_with_conversation(
                user_id=user_id,
                run_id=run_id,
                learner_only=False,
            )
            _assert_active_lease(run, lease=lease, now=datetime.now(UTC))
            _assert_not_terminal(run)
            _assert_not_cancelled(run)
            _assert_not_superseded(run)
            if input_revision != _as_int(run["input_revision"], 0):
                raise TutorLeaseConflict("capability receipt revision is stale")
            if catalog_digest != str(run["catalog_digest"]) or policy_fingerprint != str(run["policy_fingerprint"]):
                raise TutorCatalogEvidenceError("capability receipt catalog or policy evidence is stale")
            existing = self._conn.execute(
                "SELECT * FROM tutor_capability_invocations WHERE run_id = %s AND invocation_key = %s",
                (run_id, invocation_key),
            ).fetchone()
            if existing is not None:
                if (
                    _as_int(existing["input_revision"], -1) != input_revision
                    or str(existing["capability_id"]) != request.capability_id
                    or str(existing["capability_version"]) != capability_version
                    or str(existing["catalog_digest"]) != catalog_digest
                    or str(existing["policy_fingerprint"]) != policy_fingerprint
                    or str(existing["request_hash"]) != request_hash
                    or str(existing["result_hash"]) != result_hash
                    or str(existing["status"]) != result.status.value
                    or str(existing.get("diagnostic_code") or "") != str(result.diagnostic_code or "")
                ):
                    raise TutorIdempotencyConflict("capability invocation conflicts with a prior receipt")
                event = self._event_by_id(str(existing["event_id"]))
                if event is None:
                    raise RuntimeError("capability receipt event is missing")
                return TutorCapabilityInvocationReceipt(str(existing["id"]), event, True)
            selected = self._conn.execute(
                """
                SELECT skill_id, skill_version, manifest_hash, instruction_hash, evaluation_hash
                FROM tutor_run_skill_selections
                WHERE run_id = %s AND input_revision = %s
                """,
                (run_id, input_revision),
            ).fetchone()
            if selected is None:
                raise TutorCatalogEvidenceError("capability receipt requires an exact selected Skill")
            skill_evidence = self._catalog_skill_evidence(
                digest=str(run["catalog_digest"]),
                skill_id=str(selected["skill_id"]),
                skill_version=str(selected["skill_version"]),
                manifest_hash=str(selected["manifest_hash"]),
                instruction_hash=str(selected["instruction_hash"]),
                evaluation_hash=str(selected["evaluation_hash"]),
            )
            if request.capability_id not in _as_list(skill_evidence.get("required_capability_ids")):
                raise TutorCatalogEvidenceError("capability is not declared by the selected Skill")
            event = self._append_event_locked(
                run_id=run_id,
                event_key=invocation_key,
                kind="capability_invoked",
                input_revision=input_revision,
                payload={
                    "kind": "capability_invoked",
                    "run_id": run_id,
                    "input_revision": input_revision,
                    "capability_id": request.capability_id,
                    "capability_version": capability_version,
                    "catalog_digest": catalog_digest,
                    "policy_fingerprint": policy_fingerprint,
                    "status": result.status.value,
                    "diagnostic_code": result.diagnostic_code or "none",
                    "request_hash": request_hash,
                    "result_hash": result_hash,
                    "duration_ms": duration_ms,
                },
            )
            row = self._conn.execute(
                """
                INSERT INTO tutor_capability_invocations (
                  run_id, event_id, input_revision, invocation_key,
                  capability_id, capability_version, catalog_digest, policy_fingerprint,
                  skill_id, skill_version, manifest_hash, instruction_hash,
                  lease_owner_id, lease_generation, status, diagnostic_code,
                  request_hash, result_hash, duration_ms
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    run_id,
                    event.event_id,
                    input_revision,
                    invocation_key,
                    request.capability_id,
                    capability_version,
                    catalog_digest,
                    policy_fingerprint,
                    selected["skill_id"],
                    selected["skill_version"],
                    selected["manifest_hash"],
                    selected["instruction_hash"],
                    lease.owner_id,
                    lease.generation,
                    result.status.value,
                    result.diagnostic_code,
                    request_hash,
                    result_hash,
                    duration_ms,
                ),
            ).fetchone()
            if row is None:
                raise RuntimeError("capability receipt insert failed")
            if result.status is TutorCapabilityStatus.COMPLETED:
                self._advance_public_process_locked(
                    run=run,
                    step_key="authorized_resource_checked",
                    occurred_at=event.created_at,
                )
            return TutorCapabilityInvocationReceipt(str(row["id"]), event, False)

    def commit_effect_if_current(
        self,
        *,
        user_id: str,
        run_id: str,
        lease: TutorLease,
        proposal: TutorEffectProposal,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> TutorEffectCommitReceipt:
        _safe_key(idempotency_key, label="effect idempotency key")
        effective_now = now or datetime.now(UTC)
        payload_hash = _payload_fields_hash(proposal.payload)
        event_key = f"effect:{proposal.effect_id}"
        logical_action_key: str | None = None
        with self._conn.transaction():
            _conversation, run = self._lock_run_with_conversation(
                user_id=user_id,
                run_id=run_id,
                learner_only=False,
            )
            retry_root = _optional_string(run.get("retry_root_turn_id")) or str(run["id"])
            logical_action_key = _sha256_json({
                "user_id": user_id,
                "conversation_id": str(run["conversation_id"]),
                "retry_root_turn_id": retry_root,
                "effect_type": proposal.effect_type,
                "payload_hash": payload_hash,
            })
            existing = self._conn.execute(
                "SELECT * FROM tutor_effects WHERE run_id = %s AND effect_id = %s",
                (run_id, proposal.effect_id),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["idempotency_key"]) != idempotency_key
                    or str(existing["effect_type"]) != proposal.effect_type
                    or _as_int(existing["expected_input_revision"], -1) != proposal.expected_input_revision
                    or str(existing["payload_hash"]) != payload_hash
                ):
                    raise TutorIdempotencyConflict("effect identity conflicts with a prior request")
                replay_event = self._event_by_key_locked(run_id=run_id, event_key=event_key)
                if replay_event is None:
                    raise RuntimeError("effect replay event is missing")
                return TutorEffectCommitReceipt(
                    result=TutorEffectResult(
                        effect_id=proposal.effect_id,
                        status=TutorEffectStatus(str(existing["status"])),
                        commit_id=str(existing["commit_id"]) if existing.get("commit_id") else None,
                    ),
                    event=replay_event,
                    replayed=True,
                    committer_invoked=False,
                )

            if run.get("superseded_by_run_id") is not None:
                raise TutorTerminalStateConflict("superseded Tutor run cannot record an effect")
            is_current = (
                not _is_terminal(run)
                and run.get("cancelled_at") is None
                and _as_int(run["input_revision"], 0) == proposal.expected_input_revision
                and _lease_matches(run, lease=lease, now=effective_now)
            )
            if not is_current:
                result = TutorEffectResult(effect_id=proposal.effect_id, status=TutorEffectStatus.STALE_REJECTED)
                event = self._record_effect_result_locked(
                    run=run,
                    lease=lease,
                    proposal=proposal,
                    idempotency_key=idempotency_key,
                    payload_hash=payload_hash,
                    result=result,
                    event_key=event_key,
                    input_revision=_as_int(run["input_revision"], 0),
                )
                return TutorEffectCommitReceipt(result=result, event=event, replayed=False, committer_invoked=False)

            handler = self._effect_handlers.get(proposal.effect_type)
            descriptor = self._effect_descriptors.get(proposal.effect_type)
            payload = payload_mapping_from_fields(proposal.payload)
            descriptor_valid = False
            if descriptor is not None and payload is not None:
                try:
                    descriptor.proposal_model.model_validate(payload)
                    descriptor_valid = True
                except (ValidationError, TypeError, ValueError):
                    descriptor_valid = False
            if (
                handler is None
                or descriptor is None
                or not descriptor_valid
                or not self._selected_skill_allows_effect(
                    run=run,
                    input_revision=proposal.expected_input_revision,
                    effect_type=proposal.effect_type,
                )
            ):
                result = TutorEffectResult(effect_id=proposal.effect_id, status=TutorEffectStatus.DENIED)
                event = self._record_effect_result_locked(
                    run=run,
                    lease=lease,
                    proposal=proposal,
                    idempotency_key=idempotency_key,
                    payload_hash=payload_hash,
                    result=result,
                    event_key=event_key,
                    input_revision=proposal.expected_input_revision,
                )
                return TutorEffectCommitReceipt(result=result, event=event, replayed=False, committer_invoked=False)

            self._conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
                ("tutor-effect-logical", logical_action_key),
            )
            prior_logical = self._conn.execute(
                "SELECT * FROM tutor_effects WHERE logical_action_key = %s ORDER BY created_at, id LIMIT 1 FOR UPDATE",
                (logical_action_key,),
            ).fetchone()
            if prior_logical is not None and str(prior_logical.get("status")) == "committed":
                result = TutorEffectResult(
                    effect_id=proposal.effect_id,
                    status=TutorEffectStatus.COMMITTED,
                    commit_id=_optional_string(prior_logical.get("commit_id")),
                )
                event = self._append_event_locked(
                    run_id=run_id,
                    event_key=event_key,
                    kind="effect_result",
                    input_revision=proposal.expected_input_revision,
                    payload={
                        "kind": "effect_result",
                        "status": "committed",
                        "effect_id": proposal.effect_id,
                        "logical_replay": True,
                    },
                )
                return TutorEffectCommitReceipt(result=result, event=event, replayed=True, committer_invoked=False)
            if prior_logical is not None:
                raise TutorTerminalStateConflict("logical effect authority is ambiguous")

            provisional = self._conn.execute(
                """
                INSERT INTO tutor_effects (
                  run_id, effect_id, idempotency_key, effect_type, expected_input_revision,
                  payload_hash, logical_action_key, lease_owner_id, lease_generation, status, safe_outcome_json, safe_outcome_hash
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'proposed', %s::jsonb, %s)
                RETURNING id
                """,
                (
                    run_id,
                    proposal.effect_id,
                    idempotency_key,
                    proposal.effect_type,
                    proposal.expected_input_revision,
                    payload_hash,
                    logical_action_key,
                    lease.owner_id,
                    lease.generation,
                    _json(self._projector.project({"effect_id": proposal.effect_id, "status": "proposed"})),
                    self._projector.fingerprint({"effect_id": proposal.effect_id, "status": "proposed"}),
                ),
            ).fetchone()
            if provisional is None:
                raise RuntimeError("effect reservation insert failed")
            result = handler(self._conn, _snapshot_from_row(run), proposal)
            if result.effect_id != proposal.effect_id:
                raise TutorPersistenceError("effect handler returned a mismatched effect id")
            event = self._record_effect_result_locked(
                run=run,
                lease=lease,
                proposal=proposal,
                idempotency_key=idempotency_key,
                payload_hash=payload_hash,
                result=result,
                event_key=event_key,
                input_revision=proposal.expected_input_revision,
                existing_effect_id=str(provisional["id"]),
                increment_effect_counter=True,
            )
            return TutorEffectCommitReceipt(result=result, event=event, replayed=False, committer_invoked=True)

    def persist_safe_checkpoint(
        self,
        *,
        user_id: str,
        lease: TutorLease,
        checkpoint: TutorCheckpoint,
        envelope: TutorCurationEnvelope,
    ) -> TutorTraceRecord:
        if checkpoint.run_id != lease.run_id or envelope.request.run_id != checkpoint.run_id:
            raise ValueError("lifecycle checkpoint scope is inconsistent")
        if envelope.request.trigger is not TutorCompactionTrigger.SAFE_CHECKPOINT:
            raise ValueError("safe checkpoint requires a safe-checkpoint curation trigger")
        with self._conn.transaction():
            _conversation, run = self._lock_run_with_conversation(
                user_id=user_id,
                run_id=checkpoint.run_id,
                learner_only=False,
            )
            _assert_active_lease(run, lease=lease, now=checkpoint.created_at)
            _assert_not_terminal(run)
            _assert_not_cancelled(run)
            _assert_not_superseded(run)
            if checkpoint.input_revision != _as_int(run["input_revision"], 0):
                raise TutorLeaseConflict("checkpoint revision is stale")
            return self._persist_checkpoint_and_outbox_locked(run=run, checkpoint=checkpoint, envelope=envelope)

    def persist_context_high_water(
        self,
        *,
        user_id: str,
        lease: TutorLease,
        request: TutorCompactionRequest,
        envelope: TutorCurationEnvelope,
        created_at: datetime,
    ) -> TutorTraceRecord:
        if request.run_id != lease.run_id or envelope.request != request:
            raise ValueError("compaction lifecycle scope is inconsistent")
        if request.trigger is not TutorCompactionTrigger.CONTEXT_HIGH_WATER:
            raise ValueError("context high-water lifecycle requires its matching trigger")
        with self._conn.transaction():
            _conversation, run = self._lock_run_with_conversation(
                user_id=user_id,
                run_id=request.run_id,
                learner_only=False,
            )
            _assert_active_lease(run, lease=lease, now=created_at)
            _assert_not_terminal(run)
            _assert_not_cancelled(run)
            _assert_not_superseded(run)
            if request.input_revision != _as_int(run["input_revision"], 0):
                raise TutorLeaseConflict("compaction revision is stale")
            event = self._append_event_locked(
                run_id=request.run_id,
                event_key=f"compaction:{request.idempotency_key}",
                kind="compaction_requested",
                input_revision=request.input_revision,
                payload=_compaction_payload(request, status="pending"),
            )
            self._trip_failpoint("after_event")
            trace = self._insert_trace_locked(
                run_id=request.run_id,
                kind="compaction_request",
                event_sequence=event.event_sequence,
                payload=self._projector.compaction(_compaction_payload(request, status="pending")),
                created_at=created_at,
            )
            self._trip_failpoint("after_trace")
            self._upsert_outbox_locked(run=run, envelope=envelope, trace_id=trace.trace_id, event_sequence=event.event_sequence, created_at=created_at)
            self._trip_failpoint("after_outbox")
            return trace

    def record_provider_attempts(
        self,
        *,
        snapshot: TutorRunSnapshot,
        decision_iteration: int,
        attempts: tuple[TutorProviderAttemptReceipt, ...],
        created_at: datetime,
    ) -> None:
        if decision_iteration < 1:
            raise ValueError("provider decision_iteration must be positive")
        if not attempts:
            return
        if len({attempt.attempt_index for attempt in attempts}) != len(attempts):
            raise ValueError("provider attempt indexes must be unique")

        with self._conn.transaction():
            run = self._conn.execute(
                """
                SELECT id, user_id, conversation_id, input_revision
                FROM tutor_runs
                WHERE id = %s AND user_id = %s
                """,
                (snapshot.run_id, snapshot.user_id),
            ).fetchone()
            if run is None:
                raise TutorRunNotFound("tutor run not found")
            if str(run["conversation_id"]) != snapshot.conversation_id:
                raise TutorIdempotencyConflict("provider attempt run scope conflicts with persisted conversation")
            if snapshot.input_revision > _as_int(run["input_revision"], -1):
                raise TutorIdempotencyConflict("provider attempt input revision exceeds persisted run revision")

            for attempt in attempts:
                usage = attempt.usage
                values = (
                    snapshot.run_id,
                    snapshot.user_id,
                    snapshot.conversation_id,
                    snapshot.input_revision,
                    decision_iteration,
                    attempt.attempt_index,
                    attempt.provider_type,
                    attempt.model,
                    attempt.protocol,
                    attempt.outcome.value,
                    attempt.diagnostic_code,
                    usage.input_tokens if usage is not None else None,
                    usage.cached_input_tokens if usage is not None else None,
                    usage.uncached_input_tokens if usage is not None else None,
                    usage.output_tokens if usage is not None else None,
                    usage.total_tokens if usage is not None else None,
                    usage.calculated_total_tokens if usage is not None else None,
                    usage.reasoning_tokens if usage is not None else None,
                    usage is not None and usage.usage_available,
                )
                inserted = self._conn.execute(
                    """
                    INSERT INTO tutor_provider_attempt_receipts (
                      run_id, user_id, conversation_id, input_revision,
                      decision_iteration, attempt_index, provider_type, model, protocol,
                      outcome, diagnostic_code, input_tokens, cached_input_tokens,
                      uncached_input_tokens, output_tokens, reported_total_tokens,
                      calculated_total_tokens, reasoning_tokens, usage_available, created_at
                    )
                    VALUES (
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (run_id, input_revision, decision_iteration, attempt_index) DO NOTHING
                    RETURNING id
                    """,
                    (*values, created_at),
                ).fetchone()
                if inserted is not None:
                    continue
                replay = self._conn.execute(
                    """
                    SELECT id
                    FROM tutor_provider_attempt_receipts
                    WHERE run_id = %s
                      AND user_id = %s
                      AND conversation_id = %s
                      AND input_revision = %s
                      AND decision_iteration = %s
                      AND attempt_index = %s
                      AND provider_type IS NOT DISTINCT FROM %s
                      AND model IS NOT DISTINCT FROM %s
                      AND protocol IS NOT DISTINCT FROM %s
                      AND outcome IS NOT DISTINCT FROM %s
                      AND diagnostic_code IS NOT DISTINCT FROM %s
                      AND input_tokens IS NOT DISTINCT FROM %s
                      AND cached_input_tokens IS NOT DISTINCT FROM %s
                      AND uncached_input_tokens IS NOT DISTINCT FROM %s
                      AND output_tokens IS NOT DISTINCT FROM %s
                      AND reported_total_tokens IS NOT DISTINCT FROM %s
                      AND calculated_total_tokens IS NOT DISTINCT FROM %s
                      AND reasoning_tokens IS NOT DISTINCT FROM %s
                      AND usage_available IS NOT DISTINCT FROM %s
                    """,
                    values,
                ).fetchone()
                if replay is None:
                    raise TutorIdempotencyConflict(
                        "provider attempt receipt identity conflicts with different safe facts"
                    )

    def list_provider_attempt_receipts(
        self,
        *,
        user_id: str,
        run_id: str,
    ) -> tuple[TutorProviderAttemptRecord, ...]:
        run = self._conn.execute(
            "SELECT id FROM tutor_runs WHERE id = %s AND user_id = %s",
            (run_id, user_id),
        ).fetchone()
        if run is None:
            raise TutorRunNotFound("tutor run not found")
        rows = self._conn.execute(
            """
            SELECT *
            FROM tutor_provider_attempt_receipts
            WHERE run_id = %s AND user_id = %s
            ORDER BY decision_iteration, attempt_index, created_at, id
            """,
            (run_id, user_id),
        ).fetchall()
        return tuple(_provider_attempt_record_from_row(row) for row in rows)

    def complete_run(
        self,
        *,
        user_id: str,
        lease: TutorLease,
        checkpoint: TutorCheckpoint,
        result: TutorRunResult,
        envelope: TutorCurationEnvelope,
    ) -> TutorRunResult:
        if result.run_id != lease.run_id or checkpoint.run_id != lease.run_id or envelope.request.run_id != lease.run_id:
            raise ValueError("terminal lifecycle scope is inconsistent")
        if envelope.request.trigger is not TutorCompactionTrigger.TERMINAL:
            raise ValueError("terminal lifecycle requires a terminal curation trigger")
        if result.terminal_outcome is None:
            raise ValueError("terminal lifecycle requires a terminal result")
        conversation_ref = self._conn.execute(
            "SELECT conversation_id FROM tutor_runs WHERE id = %s AND user_id = %s",
            (result.run_id, user_id),
        ).fetchone()
        if conversation_ref is None:
            raise TutorRunNotFound("tutor run not found")
        with self._conn.transaction():
            conversation = self._lock_conversation(
                user_id=user_id,
                conversation_id=str(conversation_ref["conversation_id"]),
                learner_only=False,
            )
            run = self._lock_run(user_id=user_id, run_id=result.run_id)
            if _is_terminal(run):
                return _result_from_row(run)
            if run.get("cancelled_at") is not None or run.get("superseded_by_run_id") is not None:
                display_state = "superseded" if run.get("superseded_by_run_id") is not None else "unavailable"
                step_key = "replaced_by_newer_input" if display_state == "superseded" else None
                self._freeze_public_process_locked(
                    run=run,
                    display_state=display_state,
                    step_key=step_key,
                    occurred_at=checkpoint.created_at,
                )
                updated = self._conn.execute(
                    """
                    UPDATE tutor_runs
                    SET status = 'cancelled',
                        terminal_outcome = 'cancelled',
                        terminal_diagnostic_code = CASE
                          WHEN superseded_by_run_id IS NULL THEN COALESCE(terminal_diagnostic_code, 'cancelled')
                          ELSE COALESCE(terminal_diagnostic_code, 'superseded')
                        END,
                        terminal_at = COALESCE(terminal_at, %s),
                        active_lease_owner_id = NULL,
                        active_lease_expires_at = NULL
                    WHERE id = %s AND user_id = %s AND terminal_outcome IS NULL
                    RETURNING *
                    """,
                    (checkpoint.created_at, result.run_id, user_id),
                ).fetchone()
                if updated is None:
                    latest = self._lock_run(user_id=user_id, run_id=result.run_id)
                    return _result_from_row(latest)
                self._append_event_locked(
                    run_id=result.run_id,
                    event_key=f"terminal:cancelled:{_as_int(updated['input_revision'], 0)}",
                    kind="terminal_result",
                    input_revision=_as_int(updated["input_revision"], 0),
                    payload={
                        "kind": "terminal_result",
                        "status": "cancelled",
                        "run_id": result.run_id,
                        "input_revision": _as_int(updated["input_revision"], 0),
                    },
                )
                self._append_turn_event_locked(
                    run=updated,
                    kind=TutorConversationEventKind.TURN_UPDATED,
                    event_key=f"turn:{result.run_id}:cancelled",
                    occurred_at=checkpoint.created_at,
                )
                return _result_from_row(updated)
            _assert_active_lease(run, lease=lease, now=checkpoint.created_at)
            if checkpoint.input_revision != _as_int(run["input_revision"], 0) or result.input_revision != checkpoint.input_revision:
                raise TutorLeaseConflict("terminal lifecycle revision is stale")
            terminal_message_id = self._record_public_message_locked(
                run=run,
                result=result,
                created_at=checkpoint.created_at,
            )
            trace = self._persist_checkpoint_and_outbox_locked(
                run=run,
                checkpoint=checkpoint,
                envelope=envelope,
                terminal_message_id=terminal_message_id,
            )
            self._trip_failpoint("before_terminal_update")
            updated = self._conn.execute(
                """
                UPDATE tutor_runs
                SET status = %s,
                    iteration_count = %s,
                    model_call_count = %s,
                    capability_call_count = %s,
                    effect_count = %s,
                    terminal_outcome = %s,
                    terminal_diagnostic_code = %s,
                    terminal_at = %s,
                    active_lease_owner_id = NULL,
                    active_lease_expires_at = NULL
                WHERE id = %s
                  AND user_id = %s
                  AND terminal_outcome IS NULL
                  AND cancelled_at IS NULL
                  AND superseded_by_run_id IS NULL
                RETURNING *
                """,
                (
                    result.status.value,
                    result.iteration_count,
                    result.model_call_count,
                    result.capability_call_count,
                    result.effect_count,
                    result.terminal_outcome.value,
                    result.diagnostic_code,
                    checkpoint.created_at,
                    result.run_id,
                    user_id,
                ),
            ).fetchone()
            if updated is None:
                latest = self._lock_run(user_id=user_id, run_id=result.run_id)
                return _result_from_row(latest)
            if str(run.get("origin")) == "interactive" and str(conversation.get("visibility")) == "learner":
                if result.terminal_outcome is TutorTerminalOutcome.COMPLETED:
                    if terminal_message_id is not None:
                        self._write_conversation_title_once_locked(
                            user_id=user_id,
                            conversation_id=str(run["conversation_id"]),
                            candidate=result.conversation_title,
                        )
                    self._freeze_public_process_locked(
                        run=run,
                        display_state="completed",
                        step_key="learning_reply_generated",
                        occurred_at=checkpoint.created_at,
                        tutor_message_id=terminal_message_id,
                    )
                else:
                    self._freeze_public_process_locked(
                        run=run,
                        display_state="unavailable",
                        step_key=None,
                        occurred_at=checkpoint.created_at,
                    )
            self._append_turn_event_locked(
                run=updated,
                kind=TutorConversationEventKind.TURN_UPDATED,
                event_key=f"turn:{result.run_id}:terminal:{result.terminal_outcome.value}",
                occurred_at=checkpoint.created_at,
            )
            del trace
            return result

    def record_interaction_request(
        self,
        *,
        user_id: str,
        lease: TutorLease,
        decision: "TutorDecision",
        result: TutorRunResult,
        created_at: datetime,
    ) -> TutorRunResult:
        if decision.continuation_kind is None:
            raise ValueError("typed request requires a continuation kind")
        if (
            result.status is not TutorRunStatus.COMPLETED
            or result.terminal_outcome is not TutorTerminalOutcome.COMPLETED
            or result.completion_reason is None
        ):
            raise ValueError("typed request must complete its source turn")
        kind = TutorInteractionRequestKind(decision.continuation_kind.value)
        actor = actor_for_request(kind)
        expected_reason = completion_reason_for_request(kind)
        if result.completion_reason is not expected_reason:
            raise ValueError("typed request completion reason does not match request kind")
        prompt = sanitize_summary_text(decision.public_message or "", max_length=1_200)
        if not prompt:
            raise TutorInteractionRequestConflict("typed request requires a learner-safe prompt")
        with self._conn.transaction():
            conversation, run = self._lock_run_with_conversation(
                user_id=user_id,
                run_id=result.run_id,
                learner_only=False,
            )
            if _protocol_version_from_row(run) is not TutorInteractionProtocolVersion.THREAD_TURN_V2:
                raise TutorInteractionRequestConflict("typed request requires thread_turn_v2")
            existing = self._conn.execute(
                "SELECT * FROM tutor_interaction_requests WHERE source_turn_id = %s FOR UPDATE",
                (result.run_id,),
            ).fetchone()
            if existing is not None:
                return _result_from_row(run)
            _assert_active_lease(run, lease=lease, now=created_at)
            _assert_not_terminal(run)
            _assert_not_cancelled(run)
            _assert_not_superseded(run)
            if result.input_revision != _as_int(run.get("input_revision"), 0):
                raise TutorLeaseConflict("typed request result revision is stale")
            pending = self._conn.execute(
                """
                SELECT id FROM tutor_interaction_requests
                WHERE user_id = %s AND conversation_id = %s AND state = 'pending'
                FOR UPDATE
                """,
                (user_id, run["conversation_id"]),
            ).fetchone()
            if pending is not None:
                raise TutorInteractionRequestConflict("conversation already has a pending request")
            public_message_id = self._record_public_message_locked(
                run=run,
                result=result,
                created_at=created_at,
            )
            if public_message_id is None:
                raise TutorInteractionRequestConflict("typed request requires a learner-safe public message")
            request_id = str(uuid4())
            item_id = str(uuid4())
            catalog_version: str | None = None
            question_key: str | None = None
            proposal_identity: str | None = None
            authority_key: str | None = None
            risk_level: str | None = None
            authority_request_hash: str | None = None
            authority_scope: dict[str, object] | None = None
            descriptor: dict[str, object] = {
                "prompt": prompt,
                "public_thinking_text": result.public_thinking_text,
                "required": True,
                "kind": kind.value,
                "actor": actor.value,
                "source_turn_id": result.run_id,
            }
            if kind is TutorInteractionRequestKind.PLANNING_INPUT:
                question_key = str(decision.question_key or "")
                presentation = build_planning_question_presentation(
                    self._conn,
                    question_key=question_key,
                )
                catalog_version = PLANNING_QUESTION_CATALOG_VERSION
                descriptor.update(
                    {"question_key": question_key, "catalog_version": catalog_version}
                )
            elif kind is TutorInteractionRequestKind.CLARIFICATION:
                presentation = {
                    "type": "text",
                    "field_key": None,
                    "minimum_length": 1,
                    "maximum_length": 16_000,
                    "multiline": True,
                }
            elif kind is TutorInteractionRequestKind.APPROVAL:
                proposal_identity = f"proposal:{canonical_payload_hash({'run_id': result.run_id, 'input_revision': result.input_revision, 'model_call_count': result.model_call_count, 'prompt': prompt})}"
                authority_key = "tutor.approval"
                risk_level = "medium"
                descriptor.update(
                    {
                        "proposal_identity": proposal_identity,
                        "authority_key": authority_key,
                        "risk_level": risk_level,
                    }
                )
                presentation = {
                    "type": "approval",
                    "proposal_id": proposal_identity,
                    "authority_key": authority_key,
                    "risk_level": risk_level,
                    "summary": prompt,
                }
            else:
                authority_key = f"tutor.{kind.value}"
                authority_scope = {
                    "conversation_id": str(run["conversation_id"]),
                    "source_turn_id": result.run_id,
                    "kind": kind.value,
                }
                authority_request_hash = canonical_payload_hash(
                    {
                        "request_id": request_id,
                        "kind": kind.value,
                        "scope": authority_scope,
                    }
                )
                descriptor.update(
                    {
                        "authority_key": authority_key,
                        "authority_subject": request_id,
                        "request_hash": authority_request_hash,
                    }
                )
                presentation = {
                    "type": "text",
                    "field_key": None,
                    "minimum_length": 1,
                    "maximum_length": 1,
                    "multiline": False,
                }
            descriptor_hash = canonical_payload_hash(descriptor)
            request_row = self._conn.execute(
                """
                INSERT INTO tutor_interaction_requests (
                  id, item_id, user_id, conversation_id, source_turn_id,
                  kind, actor, schema_version, catalog_version, question_key,
                  descriptor_json, presentation_json, descriptor_hash,
                  proposal_identity, authority_key, risk_level,
                  authority_subject, authority_scope_json, authority_request_hash,
                  state, version, created_at
                ) VALUES (
                  %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s,
                  %s::jsonb, %s::jsonb, %s,
                  %s, %s, %s,
                  %s, %s::jsonb, %s,
                  'pending', 1, %s
                )
                RETURNING *
                """,
                (
                    request_id,
                    item_id,
                    user_id,
                    run["conversation_id"],
                    result.run_id,
                    kind.value,
                    actor.value,
                    TUTOR_INTERACTION_REQUEST_SCHEMA_VERSION,
                    catalog_version,
                    question_key,
                    _json(descriptor),
                    _json(presentation),
                    descriptor_hash,
                    proposal_identity,
                    authority_key,
                    risk_level,
                    request_id if actor is TutorInteractionRequestActor.AUTHORITY else None,
                    _json(authority_scope) if authority_scope is not None else None,
                    authority_request_hash,
                    created_at,
                ),
            ).fetchone()
            if request_row is None:
                raise RuntimeError("Tutor interaction request insert failed")
            self._conn.execute(
                "UPDATE tutor_conversations SET queue_paused = true, queue_pause_reason = 'pending_request' WHERE id = %s AND user_id = %s",
                (run["conversation_id"], user_id),
            )
            request_event = self._append_event_locked(
                run_id=result.run_id,
                event_key=f"interaction-request:{request_id}",
                kind="interaction_request",
                input_revision=result.input_revision,
                payload={
                    "kind": "interaction_request",
                    "request_id": request_id,
                    "item_id": item_id,
                    "request_kind": kind.value,
                    "actor": actor.value,
                    "input_revision": result.input_revision,
                },
            )
            self._append_event_locked(
                run_id=result.run_id,
                event_key=f"terminal:request:{request_id}",
                kind="terminal_result",
                input_revision=result.input_revision,
                payload={
                    "kind": "terminal_result",
                    "status": "completed",
                    "run_id": result.run_id,
                    "input_revision": result.input_revision,
                    "request_id": request_id,
                    "item_id": item_id,
                },
            )
            updated = self._conn.execute(
                """
                UPDATE tutor_runs
                SET status = 'completed', iteration_count = %s, model_call_count = %s,
                    capability_call_count = %s, effect_count = %s,
                    terminal_outcome = 'completed', terminal_at = %s,
                    completion_reason = %s, continuation_kind = NULL,
                    active_lease_owner_id = NULL, active_lease_expires_at = NULL
                WHERE id = %s AND user_id = %s
                  AND active_lease_owner_id = %s AND active_lease_generation = %s
                  AND terminal_outcome IS NULL AND cancelled_at IS NULL
                  AND superseded_by_run_id IS NULL
                RETURNING *
                """,
                (
                    result.iteration_count,
                    result.model_call_count,
                    result.capability_call_count,
                    result.effect_count,
                    created_at,
                    result.completion_reason.value,
                    result.run_id,
                    user_id,
                    lease.owner_id,
                    lease.generation,
                ),
            ).fetchone()
            if updated is None:
                raise TutorLeaseConflict("typed request result lease was lost")
            self._freeze_public_process_locked(
                run=updated,
                display_state="completed",
                step_key="learning_reply_generated",
                occurred_at=created_at,
                tutor_message_id=public_message_id,
            )
            self._append_item_reference_event_locked(
                run=updated,
                event_key=f"item:request:{item_id}:added",
                kind=TutorConversationEventKind.ITEM_ADDED,
                item_id=item_id,
                item_kind=public_item_kind(kind),
                occurred_at=created_at,
            )
            self._append_turn_event_locked(
                run=updated,
                kind=TutorConversationEventKind.TURN_UPDATED,
                event_key=f"turn:{result.run_id}:request:{request_id}",
                occurred_at=created_at,
            )
            self._increment_control_version_locked(
                user_id=user_id,
                conversation_id=str(conversation["id"]),
                event_key=f"control:request:{item_id}:pending",
                occurred_at=created_at,
                turn_id=result.run_id,
            )
            self._write_conversation_title_once_locked(
                user_id=user_id,
                conversation_id=str(conversation["id"]),
                candidate=result.conversation_title,
            )
            del request_event
            return result

    def record_waiting_result(
        self,
        *,
        user_id: str,
        lease: TutorLease,
        result: TutorRunResult,
        created_at: datetime,
    ) -> TutorRunResult:
        if result.status is not TutorRunStatus.WAITING_FOR_INPUT:
            raise ValueError("only waiting-for-input result may use this lifecycle operation")
        with self._conn.transaction():
            _conversation, run = self._lock_run_with_conversation(
                user_id=user_id,
                run_id=result.run_id,
                learner_only=False,
            )
            _assert_active_lease(run, lease=lease, now=created_at)
            _assert_not_terminal(run)
            _assert_not_cancelled(run)
            _assert_not_superseded(run)
            if result.continuation_kind is None:
                raise TutorTerminalStateConflict("waiting input requires a persisted continuation kind")
            persisted_kind = run.get("continuation_kind")
            if persisted_kind is not None and str(persisted_kind) != result.continuation_kind.value:
                raise TutorTerminalStateConflict("waiting continuation kind conflicts with persisted run state")
            if result.input_revision != _as_int(run["input_revision"], 0):
                raise TutorLeaseConflict("waiting result revision is stale")
            public_message_id = self._record_public_message_locked(
                run=run,
                result=result,
                created_at=created_at,
            )
            event_payload: dict[str, object] = {
                "kind": "waiting_for_input",
                "status": result.status.value,
                "run_id": result.run_id,
                "input_revision": result.input_revision,
                "count": result.iteration_count,
            }
            if public_message_id is not None:
                event_payload["message_id"] = public_message_id
            event = self._append_event_locked(
                run_id=result.run_id,
                event_key=f"waiting:{result.input_revision}:{result.iteration_count}:{result.model_call_count}",
                kind="waiting_for_input",
                input_revision=result.input_revision,
                payload=event_payload,
            )
            self._insert_trace_locked(
                run_id=result.run_id,
                kind="waiting_result",
                event_sequence=event.event_sequence,
                payload={
                    "kind": "waiting_result",
                    "status": result.status.value,
                    "input_revision": result.input_revision,
                },
                created_at=created_at,
            )
            updated = self._conn.execute(
                """
                UPDATE tutor_runs
                SET status = %s, iteration_count = %s, model_call_count = %s,
                    capability_call_count = %s, effect_count = %s,
                    continuation_kind = COALESCE(continuation_kind, %s),
                    active_lease_owner_id = NULL, active_lease_expires_at = NULL
                WHERE id = %s
                  AND user_id = %s
                  AND active_lease_owner_id = %s
                  AND active_lease_generation = %s
                  AND terminal_outcome IS NULL
                  AND cancelled_at IS NULL
                  AND superseded_by_run_id IS NULL
                RETURNING *
                """,
                (
                    result.status.value,
                    result.iteration_count,
                    result.model_call_count,
                    result.capability_call_count,
                    result.effect_count,
                    result.continuation_kind.value,
                    result.run_id,
                    user_id,
                    lease.owner_id,
                    lease.generation,
                ),
            ).fetchone()
            if updated is None:
                raise TutorLeaseConflict("waiting result lease was lost")
            self._conn.execute(
                """
                UPDATE tutor_run_public_processes
                SET display_state = 'waiting_input',
                    last_public_activity_at = GREATEST(last_public_activity_at, %s)
                WHERE run_id = %s AND display_state IN (
                  'thinking', 'waiting_input', 'waiting_approval', 'waiting_authority'
                )
                """,
                (created_at, result.run_id),
            )
            self._append_item_reference_event_locked(
                run=updated,
                event_key=f"item:process:{result.run_id}:waiting:{result.input_revision}",
                kind=TutorConversationEventKind.ITEM_UPDATED,
                item_id=result.run_id,
                item_kind="process",
                occurred_at=created_at,
            )
            self._append_turn_event_locked(
                run=updated,
                kind=TutorConversationEventKind.TURN_UPDATED,
                event_key=f"turn:{result.run_id}:waiting:{result.input_revision}",
                occurred_at=created_at,
            )
            return result

    def record_curation_proposal(
        self,
        *,
        user_id: str,
        outbox_id: str,
        kind: str,
        state: str,
        payload: Mapping[str, object],
        confidence: str,
        policy_version: str,
        memory_setting_version: str,
        created_at: datetime | None = None,
    ) -> TutorCurationProposalReceipt:
        if kind not in _PROPOSAL_KINDS or state not in _PROPOSAL_STATES:
            raise ValueError("curation proposal kind or state is invalid")
        if confidence not in {"low", "medium", "high"}:
            raise ValueError("curation proposal confidence is invalid")
        _safe_key(policy_version, label="proposal policy version")
        _safe_key(memory_setting_version, label="proposal memory setting version")
        created_at = created_at or datetime.now(UTC)
        safe_payload = self._projector.project({**dict(payload), "kind": kind, "confidence": confidence})
        payload_hash = self._projector.fingerprint(safe_payload)
        with self._conn.transaction():
            outbox = self._conn.execute(
                """
                SELECT outbox.*, runs.user_id, runs.input_revision AS run_input_revision
                FROM tutor_memory_curation_outbox AS outbox
                JOIN tutor_runs AS runs ON runs.id = outbox.run_id
                WHERE outbox.id = %s AND runs.user_id = %s
                FOR UPDATE OF outbox, runs
                """,
                (outbox_id, user_id),
            ).fetchone()
            if outbox is None:
                raise TutorRunNotFound("curation outbox record not found")
            run = self._lock_run(user_id=user_id, run_id=str(outbox["run_id"]))
            current_state = state
            stale_after = _as_datetime(outbox.get("stale_after"))
            if (
                str(outbox["policy_version"]) != policy_version
                or str(outbox["memory_setting_version"]) != memory_setting_version
                or _as_int(outbox["input_revision"], -1) != _as_int(run["input_revision"], -1)
                or (stale_after is not None and stale_after <= created_at)
            ):
                current_state = "stale"
            existing = self._conn.execute(
                "SELECT * FROM tutor_curation_proposals WHERE outbox_id = %s",
                (outbox_id,),
            ).fetchone()
            if existing is not None:
                existing_state = str(existing["state"])
                if current_state == "stale" and existing_state == "pending":
                    self._conn.execute(
                        "UPDATE tutor_curation_proposals SET state = 'stale' WHERE id = %s",
                        (existing["id"],),
                    )
                    self._conn.execute(
                        "UPDATE tutor_memory_curation_outbox SET state = 'stale' WHERE id = %s",
                        (outbox_id,),
                    )
                    existing_state = "stale"
                if (
                    str(existing["kind"]) != kind
                    or str(existing["payload_hash"]) != payload_hash
                    or str(existing["confidence"]) != confidence
                    or str(existing["policy_version"]) != policy_version
                    or str(existing["memory_setting_version"]) != memory_setting_version
                    or existing_state != current_state
                ):
                    raise TutorIdempotencyConflict("outbox already has a different proposal envelope")
                return TutorCurationProposalReceipt(
                    proposal_id=str(existing["id"]),
                    outbox_id=outbox_id,
                    kind=str(existing["kind"]),
                    state=existing_state,
                    replayed=True,
                )
            if current_state != str(outbox["state"]):
                self._conn.execute(
                    "UPDATE tutor_memory_curation_outbox SET state = %s WHERE id = %s",
                    (current_state, outbox_id),
                )
            event = self._append_event_locked(
                run_id=str(outbox["run_id"]),
                event_key=f"proposal:{outbox_id}",
                kind="curation_proposal_recorded",
                input_revision=_as_int(outbox["input_revision"], 0),
                payload={
                    "kind": "curation_proposal_recorded",
                    "outbox_id": outbox_id,
                    "state": current_state,
                    "code": kind,
                    "input_revision": _as_int(outbox["input_revision"], 0),
                    "policy_version": policy_version,
                    "memory_setting_version": memory_setting_version,
                    "payload_hash": payload_hash,
                },
            )
            provenance = self._projector.project(
                {
                    "outbox_id": outbox_id,
                    "run_id": str(outbox["run_id"]),
                    "event_from_sequence": _as_int(outbox["event_from_sequence"], 0),
                    "event_to_sequence": _as_int(outbox["event_to_sequence"], 0),
                    "source_ids": _as_list(outbox.get("source_ids_json")),
                    "source_hashes": _as_list(outbox.get("source_hashes_json")),
                }
            )
            row = self._conn.execute(
                """
                INSERT INTO tutor_curation_proposals (
                  outbox_id, event_id, kind, state, event_from_sequence, event_to_sequence,
                  provenance_json, payload_json, payload_hash, confidence,
                  policy_version, memory_setting_version, retention_until, stale_after, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    outbox_id,
                    event.event_id,
                    kind,
                    current_state,
                    _as_int(outbox["event_from_sequence"], 0),
                    _as_int(outbox["event_to_sequence"], 0),
                    _json(provenance),
                    _json(safe_payload),
                    payload_hash,
                    confidence,
                    policy_version,
                    memory_setting_version,
                    outbox["retention_until"],
                    outbox["stale_after"],
                    created_at,
                ),
            ).fetchone()
            if row is None:
                raise RuntimeError("curation proposal insert failed")
            return TutorCurationProposalReceipt(
                proposal_id=str(row["id"]), outbox_id=outbox_id, kind=kind, state=current_state, replayed=False
            )

    def export_diagnostics(self, *, user_id: str, run_id: str) -> dict[str, object]:
        """Return diagnostic evidence only; canonical message content is never read."""
        run = self._conn.execute(
            "SELECT id FROM tutor_runs WHERE id = %s AND user_id = %s",
            (run_id, user_id),
        ).fetchone()
        if run is None:
            raise TutorRunNotFound("tutor run not found")
        safe_run = self._projector.export({"run_id": run_id})
        events = self._conn.execute(
            "SELECT * FROM tutor_run_events WHERE run_id = %s ORDER BY event_sequence ASC",
            (run_id,),
        ).fetchall()
        traces = self._conn.execute(
            "SELECT * FROM tutor_run_traces WHERE run_id = %s ORDER BY event_from_sequence ASC, created_at ASC",
            (run_id,),
        ).fetchall()
        outbox = self._conn.execute(
            "SELECT * FROM tutor_memory_curation_outbox WHERE run_id = %s ORDER BY created_at ASC",
            (run_id,),
        ).fetchall()
        proposals = self._conn.execute(
            """
            SELECT proposals.*
            FROM tutor_curation_proposals AS proposals
            JOIN tutor_memory_curation_outbox AS outbox ON outbox.id = proposals.outbox_id
            WHERE outbox.run_id = %s
            ORDER BY proposals.created_at ASC
            """,
            (run_id,),
        ).fetchall()
        exported_outbox: list[dict[str, object]] = []
        for row in outbox:
            header = self._projector.export({"outbox_id": str(row["id"]), "state": row["state"]})
            exported_outbox.append(
                {
                    "outbox_id": str(header.get("outbox_id") or "invalid_outbox"),
                    "state": str(header.get("state") or "invalid_state"),
                    "envelope": self._projector.export(row.get("envelope_json")),
                    "source_ids": self._projector.export({"source_ids": _as_list(row.get("source_ids_json"))}),
                    "source_hashes": self._projector.export({"source_hashes": _as_list(row.get("source_hashes_json"))}),
                }
            )
        exported_proposals: list[dict[str, object]] = []
        for row in proposals:
            header = self._projector.export(
                {
                    "proposal_id": str(row["id"]),
                    "outbox_id": str(row["outbox_id"]),
                    "kind": row["kind"],
                    "state": row["state"],
                }
            )
            exported_proposals.append(
                {
                    "proposal_id": str(header.get("proposal_id") or "invalid_proposal"),
                    "outbox_id": str(header.get("outbox_id") or "invalid_outbox"),
                    "kind": str(header.get("kind") or "invalid_proposal"),
                    "state": str(header.get("state") or "invalid_state"),
                    "provenance": self._projector.export(row.get("provenance_json")),
                    "payload": self._projector.export(row.get("payload_json")),
                }
            )
        return {
            "redaction_version": self._projector.version,
            "run_id": str(safe_run.get("run_id") or "invalid_run"),
            "events": [
                {
                    "event_id": event.event_id,
                    "event_sequence": event.event_sequence,
                    "kind": event.kind,
                    "input_revision": event.input_revision,
                    "payload": event.payload,
                }
                for event in (_event_from_row(row, projector=self._projector) for row in events)
            ],
            "traces": [
                {
                    "trace_id": trace.trace_id,
                    "kind": trace.kind,
                    "event_from_sequence": trace.event_from_sequence,
                    "event_to_sequence": trace.event_to_sequence,
                    "payload": trace.payload,
                }
                for trace in (_trace_from_row(row, projector=self._projector) for row in traces)
            ],
            "outbox": exported_outbox,
            "proposals": exported_proposals,
        }

    def as_run_store(self, *, user_id: str) -> "PostgresTutorRunStore":
        return PostgresTutorRunStore(repository=self, user_id=user_id)

    def _lock_run(self, *, user_id: str, run_id: str) -> Mapping[str, object]:
        row = self._conn.execute(
            "SELECT * FROM tutor_runs WHERE id = %s AND user_id = %s FOR UPDATE",
            (run_id, user_id),
        ).fetchone()
        if row is None:
            raise TutorRunNotFound("tutor run not found")
        return row

    def _append_event_locked(
        self,
        *,
        run_id: str,
        event_key: str,
        kind: str,
        input_revision: int,
        payload: Mapping[str, object],
    ) -> TutorDurableEvent:
        _safe_key(event_key, label="event key")
        _safe_key(kind, label="event kind")
        if kind not in _DURABLE_EVENT_KINDS:
            raise ValueError("event kind is not part of the Child 02 durable vocabulary")
        safe_payload = self._projector.project(payload)
        payload_hash = self._projector.fingerprint(safe_payload)
        existing = self._event_by_key_locked(run_id=run_id, event_key=event_key)
        if existing is not None:
            if existing.kind != kind or existing.input_revision != input_revision or self._projector.fingerprint(existing.payload) != payload_hash:
                raise TutorIdempotencyConflict("event key conflicts with a different safe payload")
            return existing
        sequence = self._conn.execute(
            """
            UPDATE tutor_runs
            SET next_event_sequence = next_event_sequence + 1
            WHERE id = %s
            RETURNING next_event_sequence - 1 AS event_sequence
            """,
            (run_id,),
        ).fetchone()
        if sequence is None:
            raise TutorRunNotFound("tutor run not found")
        row = self._conn.execute(
            """
            INSERT INTO tutor_run_events (
              run_id, event_sequence, event_key, kind, input_revision, payload_json, payload_hash
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
            RETURNING *
            """,
            (
                run_id,
                _as_int(sequence["event_sequence"], 0),
                event_key,
                kind,
                input_revision,
                _json(safe_payload),
                payload_hash,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("tutor event insert failed")
        return _event_from_row(row, projector=self._projector)

    def _event_by_key_locked(self, *, run_id: str, event_key: str) -> TutorDurableEvent | None:
        row = self._conn.execute(
            "SELECT * FROM tutor_run_events WHERE run_id = %s AND event_key = %s",
            (run_id, event_key),
        ).fetchone()
        return _event_from_row(row, projector=self._projector) if row is not None else None

    def _event_by_id(self, event_id: str) -> TutorDurableEvent | None:
        row = self._conn.execute("SELECT * FROM tutor_run_events WHERE id = %s", (event_id,)).fetchone()
        return _event_from_row(row, projector=self._projector) if row is not None else None

    def _catalog_skill_evidence(
        self,
        *,
        digest: str,
        skill_id: str,
        skill_version: str,
        manifest_hash: str,
        instruction_hash: str,
        evaluation_hash: str | None = None,
    ) -> Mapping[str, object]:
        row = self._conn.execute(
            "SELECT manifest_json FROM tutor_catalog_snapshots WHERE digest = %s",
            (digest,),
        ).fetchone()
        if row is None:
            raise TutorCatalogEvidenceError("catalog snapshot is missing")
        manifest = _as_mapping(row.get("manifest_json"))
        skills = manifest.get("skills")
        if not isinstance(skills, list):
            raise TutorCatalogEvidenceError("catalog snapshot evidence is invalid")
        for item in skills:
            if not isinstance(item, Mapping):
                continue
            if str(item.get("skill_id")) != skill_id or str(item.get("skill_version")) != skill_version:
                continue
            if str(item.get("manifest_hash")) != manifest_hash or str(item.get("instruction_hash")) != instruction_hash:
                raise TutorCatalogEvidenceError("Skill hash does not match persisted catalog evidence")
            stored_evaluation_hash = str(item.get("evaluation_hash") or "")
            if not _SHA256.fullmatch(stored_evaluation_hash):
                raise TutorCatalogEvidenceError("catalog evaluation hash is invalid")
            if evaluation_hash is not None and stored_evaluation_hash != evaluation_hash:
                raise TutorCatalogEvidenceError("Skill evaluation hash does not match persisted catalog evidence")
            return {str(key): value for key, value in item.items()}
        raise TutorCatalogEvidenceError("Skill is not present in persisted catalog evidence")

    def _catalog_evaluation_hash(
        self,
        *,
        digest: str,
        skill_id: str,
        skill_version: str,
        manifest_hash: str,
        instruction_hash: str,
    ) -> str:
        evidence = self._catalog_skill_evidence(
            digest=digest,
            skill_id=skill_id,
            skill_version=skill_version,
            manifest_hash=manifest_hash,
            instruction_hash=instruction_hash,
        )
        return str(evidence["evaluation_hash"])

    def _selected_skill_allows_effect(
        self,
        *,
        run: Mapping[str, object],
        input_revision: int,
        effect_type: str,
    ) -> bool:
        selected = self._conn.execute(
            """
            SELECT skill_id, skill_version, manifest_hash, instruction_hash, evaluation_hash
            FROM tutor_run_skill_selections
            WHERE run_id = %s AND input_revision = %s
            """,
            (run["id"], input_revision),
        ).fetchone()
        if selected is None:
            return False
        evidence = self._catalog_skill_evidence(
            digest=str(run["catalog_digest"]),
            skill_id=str(selected["skill_id"]),
            skill_version=str(selected["skill_version"]),
            manifest_hash=str(selected["manifest_hash"]),
            instruction_hash=str(selected["instruction_hash"]),
            evaluation_hash=str(selected["evaluation_hash"]),
        )
        return effect_type in _as_list(evidence.get("allowed_effect_types"))

    def _record_effect_result_locked(
        self,
        *,
        run: Mapping[str, object],
        lease: TutorLease,
        proposal: TutorEffectProposal,
        idempotency_key: str,
        payload_hash: str,
        result: TutorEffectResult,
        event_key: str,
        input_revision: int,
        existing_effect_id: str | None = None,
        increment_effect_counter: bool = False,
    ) -> TutorDurableEvent:
        safe_outcome = self._projector.project(
            {
                "effect_id": result.effect_id,
                "effect_type": proposal.effect_type,
                "status": result.status.value,
                "commit_id": result.commit_id or "none",
                "input_revision": input_revision,
                "lease_generation": lease.generation,
            }
        )
        outcome_hash = self._projector.fingerprint(safe_outcome)
        if existing_effect_id is None:
            row = self._conn.execute(
                """
                INSERT INTO tutor_effects (
                  run_id, effect_id, idempotency_key, effect_type, expected_input_revision,
                  payload_hash, lease_owner_id, lease_generation, status, commit_id,
                  safe_outcome_json, safe_outcome_hash
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                RETURNING id
                """,
                (
                    run["id"],
                    proposal.effect_id,
                    idempotency_key,
                    proposal.effect_type,
                    proposal.expected_input_revision,
                    payload_hash,
                    lease.owner_id,
                    lease.generation,
                    result.status.value,
                    result.commit_id,
                    _json(safe_outcome),
                    outcome_hash,
                ),
            ).fetchone()
            if row is None:
                raise RuntimeError("effect receipt insert failed")
        else:
            row = self._conn.execute(
                """
                UPDATE tutor_effects
                SET status = %s, commit_id = %s, safe_outcome_json = %s::jsonb, safe_outcome_hash = %s
                WHERE id = %s
                RETURNING id
                """,
                (result.status.value, result.commit_id, _json(safe_outcome), outcome_hash, existing_effect_id),
            ).fetchone()
            if row is None:
                raise RuntimeError("effect receipt update failed")
        event = self._append_event_locked(
            run_id=str(run["id"]),
            event_key=event_key,
            kind="effect_result",
            input_revision=input_revision,
            payload={
                "kind": "effect_result",
                "run_id": str(run["id"]),
                "input_revision": input_revision,
                "effect_id": proposal.effect_id,
                "effect_type": proposal.effect_type,
                "status": result.status.value,
                "commit_id": result.commit_id or "none",
                "payload_hash": payload_hash,
                "lease_generation": lease.generation,
            },
        )
        if increment_effect_counter:
            self._conn.execute(
                "UPDATE tutor_runs SET effect_count = effect_count + 1 WHERE id = %s",
                (run["id"],),
            )
        return event

    def _persist_checkpoint_and_outbox_locked(
        self,
        *,
        run: Mapping[str, object],
        checkpoint: TutorCheckpoint,
        envelope: TutorCurationEnvelope,
        terminal_message_id: str | None = None,
    ) -> TutorTraceRecord:
        metadata = checkpoint.metadata.as_dict()
        safe_checkpoint = self._projector.checkpoint(
            metadata=metadata,
            status=checkpoint.status.value,
            reason=checkpoint.reason.value,
            input_revision=checkpoint.input_revision,
        )
        metadata_hash = self._projector.fingerprint(safe_checkpoint)
        checkpoint_row = self._conn.execute(
            """
            INSERT INTO tutor_run_checkpoints (
              run_id, input_revision, reason, status, metadata_json, metadata_hash, created_at
            )
            VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)
            ON CONFLICT (run_id, input_revision, reason, status) DO NOTHING
            RETURNING id
            """,
            (
                run["id"],
                checkpoint.input_revision,
                checkpoint.reason.value,
                checkpoint.status.value,
                _json(safe_checkpoint),
                metadata_hash,
                checkpoint.created_at,
            ),
        ).fetchone()
        if checkpoint_row is None:
            checkpoint_row = self._conn.execute(
                """
                SELECT id FROM tutor_run_checkpoints
                WHERE run_id = %s AND input_revision = %s AND reason = %s AND status = %s
                """,
                (run["id"], checkpoint.input_revision, checkpoint.reason.value, checkpoint.status.value),
            ).fetchone()
        if checkpoint_row is None:
            raise RuntimeError("checkpoint receipt is missing")
        event_kind = "terminal_result" if checkpoint.reason.value == "terminal" else "checkpoint_saved"
        event_payload: dict[str, object] = {
            **safe_checkpoint,
            "kind": event_kind,
            "run_id": str(run["id"]),
            "catalog_digest": str(run["catalog_digest"]),
            "policy_version": str(run["policy_version"]),
        }
        if terminal_message_id is not None:
            event_payload["message_id"] = terminal_message_id
        event = self._append_event_locked(
            run_id=str(run["id"]),
            event_key=f"checkpoint:{checkpoint.input_revision}:{checkpoint.reason.value}:{checkpoint.status.value}",
            kind=event_kind,
            input_revision=checkpoint.input_revision,
            payload=event_payload,
        )
        self._trip_failpoint("after_event")
        trace = self._insert_trace_locked(
            run_id=str(run["id"]),
            kind="terminal_checkpoint" if event_kind == "terminal_result" else "checkpoint",
            event_sequence=event.event_sequence,
            payload=safe_checkpoint,
            created_at=checkpoint.created_at,
        )
        self._trip_failpoint("after_trace")
        self._upsert_outbox_locked(
            run=run,
            envelope=envelope,
            trace_id=trace.trace_id,
            event_sequence=event.event_sequence,
            created_at=checkpoint.created_at,
        )
        self._trip_failpoint("after_outbox")
        return trace

    def _accept_public_thinking_stream_locked(
        self,
        *,
        run: Mapping[str, object],
        result: TutorRunResult,
        accepted_at: datetime,
    ) -> None:
        stream = self._conn.execute(
            "SELECT * FROM tutor_turn_public_thinking_streams WHERE run_id = %s FOR UPDATE",
            (run["id"],),
        ).fetchone()
        if stream is None:
            return
        if (
            str(stream.get("state") or "") != "complete"
            or _as_int(stream.get("input_revision"), -1) != result.input_revision
            or _as_int(stream.get("decision_iteration"), -1) != result.model_call_count
            or str(stream.get("thinking_text") or "") != result.public_thinking_text
        ):
            raise TutorTerminalStateConflict(
                "public thinking stream does not match the authoritative Tutor result"
            )
        updated = self._conn.execute(
            """
            UPDATE tutor_turn_public_thinking_streams
            SET state = 'accepted', accepted_at = %s, updated_at = %s
            WHERE run_id = %s AND state = 'complete'
            RETURNING run_id
            """,
            (accepted_at, accepted_at, run["id"]),
        ).fetchone()
        if updated is None:
            raise TutorLifecycleConflict("public thinking stream acceptance lost ownership")

    def _record_public_message_locked(
        self,
        *,
        run: Mapping[str, object],
        result: TutorRunResult,
        created_at: datetime,
    ) -> str | None:
        public_message = sanitize_summary_text(result.public_message or "", max_length=1_200)
        if not public_message:
            return None
        self._accept_public_thinking_stream_locked(
            run=run,
            result=result,
            accepted_at=created_at,
        )
        row = self._conn.execute(
            """
            INSERT INTO tutor_messages (
              conversation_id, role, content, public_thinking_text,
              public_thinking_steps_json, created_at
            )
            VALUES (%s, 'tutor', %s, %s, '[]'::jsonb, %s)
            RETURNING id
            """,
            (
                run["conversation_id"],
                public_message,
                result.public_thinking_text,
                created_at,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("Tutor public message insert failed")
        message_id = str(row["id"])
        self._append_item_reference_event_locked(
            run=run,
            event_key=f"item:message:{message_id}:added",
            kind=TutorConversationEventKind.ITEM_ADDED,
            item_id=message_id,
            item_kind="message",
            occurred_at=created_at,
        )
        return message_id

    def _insert_trace_locked(
        self,
        *,
        run_id: str,
        kind: str,
        event_sequence: int,
        payload: Mapping[str, object],
        created_at: datetime,
    ) -> TutorTraceRecord:
        _safe_key(kind, label="trace kind")
        if kind not in _TRACE_KINDS:
            raise ValueError("trace kind is not part of the Child 02 durable vocabulary")
        safe_payload = self._projector.project(payload)
        trace_hash = self._projector.fingerprint(safe_payload)
        existing = self._conn.execute(
            """
            SELECT * FROM tutor_run_traces
            WHERE run_id = %s AND event_from_sequence = %s
              AND event_to_sequence = %s AND kind = %s
            """,
            (run_id, event_sequence, event_sequence, kind),
        ).fetchone()
        if existing is not None:
            if str(existing["trace_hash"]) != trace_hash:
                raise TutorIdempotencyConflict("trace identity conflicts with a different safe payload")
            return _trace_from_row(existing, projector=self._projector)
        row = self._conn.execute(
            """
            INSERT INTO tutor_run_traces (
              run_id, event_from_sequence, event_to_sequence, kind,
              trace_json, trace_hash, redaction_version, created_at
            )
            VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s)
            RETURNING *
            """,
            (
                run_id,
                event_sequence,
                event_sequence,
                kind,
                _json(safe_payload),
                trace_hash,
                self._projector.version,
                created_at,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("trace insert failed")
        return _trace_from_row(row, projector=self._projector)

    def _upsert_outbox_locked(
        self,
        *,
        run: Mapping[str, object],
        envelope: TutorCurationEnvelope,
        trace_id: str,
        event_sequence: int,
        created_at: datetime,
    ) -> TutorCurationOutboxReceipt:
        request = envelope.request
        if request.run_id != str(run["id"]) or request.conversation_id != str(run["conversation_id"]):
            raise TutorPersistenceError("curation request does not match target run scope")
        _safe_key(request.curation_idempotency_key, label="curation idempotency key")
        raw_source_ids = list(request.source_ids)
        expected_source_hashes = [str(value).lower() for value in request.source_hashes]
        safe_sources = self._projector.export(
            {"source_ids": raw_source_ids, "source_hashes": expected_source_hashes}
        )
        safe_source_ids = _as_list(safe_sources.get("source_ids"))
        safe_source_hashes = _as_list(safe_sources.get("source_hashes"))
        if safe_source_ids != raw_source_ids or safe_source_hashes != expected_source_hashes:
            raise TutorPersistenceError("curation request source evidence is unsafe or malformed")
        retention_until = envelope.retention_until or (created_at + timedelta(days=_DEFAULT_RETENTION_DAYS))
        stale_after = envelope.stale_after or (created_at + timedelta(days=_DEFAULT_STALE_DAYS))
        if stale_after > retention_until:
            raise ValueError("curation stale boundary cannot exceed retention")
        payload = self._projector.compaction(
            {
                **_compaction_payload(request, status="pending"),
                "source_ids": safe_source_ids,
                "source_hashes": safe_source_hashes,
                "trace_id": trace_id,
                "event_from_sequence": event_sequence,
                "event_to_sequence": event_sequence,
                "policy_version": str(run["policy_version"]),
                "memory_setting_version": envelope.memory_setting_version,
                "priority": envelope.priority,
                "retention_until": retention_until,
                "stale_after": stale_after,
            }
        )
        row = self._conn.execute(
            """
            INSERT INTO tutor_memory_curation_outbox (
              run_id, conversation_id, input_revision, trigger,
              event_from_sequence, event_to_sequence, trace_id,
              source_ids_json, source_hashes_json, policy_version, memory_setting_version,
              projection_kind, summary_schema_version, summary_policy_version,
              summary_source_hash, prior_summary_id, prior_summary_hash,
              covered_through_created_at, covered_through_message_id,
              priority, retention_until, stale_after, state, idempotency_key, envelope_json, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, 'pending', %s, %s::jsonb, %s)
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING id, idempotency_key, state
            """,
            (
                run["id"],
                run["conversation_id"],
                request.input_revision,
                request.trigger.value,
                event_sequence,
                event_sequence,
                trace_id,
                _json(safe_source_ids),
                _json(safe_source_hashes),
                run["policy_version"],
                envelope.memory_setting_version,
                request.projection_kind,
                request.summary_schema_version,
                request.summary_policy_version,
                request.summary_source_hash,
                request.prior_summary_id,
                request.prior_summary_hash,
                request.covered_through_created_at,
                request.covered_through_message_id,
                envelope.priority,
                retention_until,
                stale_after,
                request.curation_idempotency_key,
                _json(payload),
                created_at,
            ),
        ).fetchone()
        if row is None:
            row = self._conn.execute(
                "SELECT * FROM tutor_memory_curation_outbox WHERE idempotency_key = %s FOR UPDATE",
                (request.curation_idempotency_key,),
            ).fetchone()
            if row is None:
                raise RuntimeError("curation outbox replay row is missing")
            common_conflict = (
                str(row["run_id"]) != str(run["id"])
                or str(row["conversation_id"]) != str(run["conversation_id"])
                or _as_int(row["input_revision"], -1) != request.input_revision
                or _as_list(row.get("source_ids_json")) != safe_source_ids
                or _as_list(row.get("source_hashes_json")) != safe_source_hashes
                or str(row["policy_version"]) != str(run["policy_version"])
                or str(row["memory_setting_version"]) != envelope.memory_setting_version
                or str(row.get("projection_kind") or "memory_or_summary") != request.projection_kind
                or _as_int(row["priority"], -1) != envelope.priority
            )
            structured_conflict = request.projection_kind == "context_summary" and (
                _optional_text(row, "summary_schema_version") != request.summary_schema_version
                or _optional_text(row, "summary_policy_version") != request.summary_policy_version
                or _optional_text(row, "summary_source_hash") != request.summary_source_hash
                or _optional_text(row, "prior_summary_id") != request.prior_summary_id
                or _optional_text(row, "prior_summary_hash") != request.prior_summary_hash
                or _as_datetime(row.get("covered_through_created_at")) != request.covered_through_created_at
                or _optional_text(row, "covered_through_message_id") != request.covered_through_message_id
            )
            legacy_conflict = request.projection_kind == "memory_or_summary" and (
                str(row["trigger"]) != request.trigger.value
                or _as_int(row["event_from_sequence"], -1) != event_sequence
                or _as_int(row["event_to_sequence"], -1) != event_sequence
                or str(row["trace_id"]) != trace_id
            )
            if common_conflict or structured_conflict or legacy_conflict:
                raise TutorIdempotencyConflict("curation idempotency key conflicts with durable evidence")
            return TutorCurationOutboxReceipt(
                outbox_id=str(row["id"]), idempotency_key=str(row["idempotency_key"]), state=str(row["state"]), replayed=True
            )
        return TutorCurationOutboxReceipt(
            outbox_id=str(row["id"]), idempotency_key=str(row["idempotency_key"]), state=str(row["state"]), replayed=False
        )

    def _trip_failpoint(self, stage: str) -> None:
        if self._failpoint is not None:
            self._failpoint(stage)


class PostgresTutorSkillSelectionStore:
    """Durable exact-Skill evidence adapter shared by catalog gates and effects."""

    def __init__(self, *, repository: PostgresTutorRepository, user_id: str) -> None:
        self._repository = repository
        self._user_id = user_id

    def get(self, *, run_id: str, input_revision: int) -> TutorSkillSelection | None:
        return self._repository.load_skill_selection(
            user_id=self._user_id,
            run_id=run_id,
            input_revision=input_revision,
        )

    def record(
        self,
        *,
        run_id: str,
        input_revision: int,
        selection: TutorSkillSelection,
    ) -> None:
        self._repository.record_skill_selection(
            user_id=self._user_id,
            run_id=run_id,
            input_revision=input_revision,
            selection=selection,
        )


class PostgresTutorPublicThinkingSink(TutorPublicThinkingSink):
    """Short-transaction public thinking writer fenced by run lease and revision."""

    def __init__(
        self,
        *,
        repository: PostgresTutorRepository,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        decision_iteration: int,
        now: Callable[[], datetime],
    ) -> None:
        self._repository = repository
        self._snapshot = snapshot
        self._lease = lease
        self._decision_iteration = decision_iteration
        self._now = now
        self._generation_counter = 0
        self._generation: int | None = None
        self._attempt_index: int | None = None

    def begin_attempt(self, attempt_index: int) -> None:
        self._start_generation(attempt_index)

    def append_text(self, attempt_index: int, text: str) -> None:
        generation = self._require_current(attempt_index)
        occurred_at = self._renew_lease()
        try:
            self._repository.append_public_thinking_text(
                snapshot=self._snapshot,
                lease=self._lease,
                generation=generation,
                provider_attempt=attempt_index,
                text=text,
                occurred_at=occurred_at,
            )
        except TutorPersistenceError as exc:
            raise TutorLifecycleConflict("public thinking append lost lifecycle ownership") from exc

    def complete_attempt(self, attempt_index: int) -> None:
        generation = self._require_current(attempt_index)
        occurred_at = self._renew_lease()
        try:
            self._repository.complete_public_thinking_stream(
                snapshot=self._snapshot,
                lease=self._lease,
                generation=generation,
                provider_attempt=attempt_index,
                occurred_at=occurred_at,
            )
        except TutorPersistenceError as exc:
            raise TutorLifecycleConflict("public thinking completion lost lifecycle ownership") from exc

    def reset_attempt(self, attempt_index: int) -> None:
        self._start_generation(attempt_index)

    def discard_attempt(self, attempt_index: int) -> None:
        generation = self._require_current(attempt_index)
        self._discard(generation=generation, attempt_index=attempt_index)

    def discard_current(self) -> None:
        if self._generation is None or self._attempt_index is None:
            return
        self._discard(generation=self._generation, attempt_index=self._attempt_index)

    def _start_generation(self, attempt_index: int) -> None:
        if attempt_index < 1:
            raise ValueError("provider attempt index must be positive")
        self._generation_counter += 1
        generation = self._decision_iteration * 10_000 + self._generation_counter
        occurred_at = self._renew_lease()
        try:
            self._repository.begin_public_thinking_stream(
                snapshot=self._snapshot,
                lease=self._lease,
                decision_iteration=self._decision_iteration,
                generation=generation,
                provider_attempt=attempt_index,
                occurred_at=occurred_at,
            )
        except TutorPersistenceError as exc:
            raise TutorLifecycleConflict("public thinking generation lost lifecycle ownership") from exc
        self._generation = generation
        self._attempt_index = attempt_index

    def _discard(self, *, generation: int, attempt_index: int) -> None:
        occurred_at = self._renew_lease()
        try:
            self._repository.discard_public_thinking_stream(
                snapshot=self._snapshot,
                lease=self._lease,
                generation=generation,
                provider_attempt=attempt_index,
                occurred_at=occurred_at,
            )
        except TutorPersistenceError as exc:
            raise TutorLifecycleConflict("public thinking discard lost lifecycle ownership") from exc

    def _renew_lease(self) -> datetime:
        occurred_at = self._now()
        renewed = self._repository.heartbeat_lease(
            user_id=self._snapshot.user_id,
            lease=self._lease,
            now=occurred_at,
            duration_seconds=self._snapshot.policy.lease_duration_seconds,
        )
        if renewed is None:
            raise TutorLifecycleConflict("public thinking stream lease is unavailable")
        self._lease = renewed
        return occurred_at

    def _require_current(self, attempt_index: int) -> int:
        if self._generation is None or self._attempt_index != attempt_index:
            raise TutorLifecycleConflict("public thinking callback used a stale provider attempt")
        return self._generation


class PostgresTutorLifecycle(TutorLifecyclePersistence):
    """Adapter that gives ``TutorRunLoop`` one atomic persistence boundary."""

    def __init__(
        self,
        *,
        repository: PostgresTutorRepository,
        memory_setting_version: str = _DEFAULT_MEMORY_SETTING_VERSION,
        priority: int = 0,
    ) -> None:
        self._repository = repository
        self._memory_setting_version = memory_setting_version
        self._priority = priority

    def create_public_thinking_sink(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        decision_iteration: int,
        now: Callable[[], datetime],
    ) -> TutorPublicThinkingSink:
        return PostgresTutorPublicThinkingSink(
            repository=self._repository,
            snapshot=snapshot,
            lease=lease,
            decision_iteration=decision_iteration,
            now=now,
        )

    def persist_provider_attempts(
        self,
        *,
        snapshot: TutorRunSnapshot,
        decision_iteration: int,
        attempts: tuple[TutorProviderAttemptReceipt, ...],
        created_at: datetime,
    ) -> None:
        try:
            self._repository.record_provider_attempts(
                snapshot=snapshot,
                decision_iteration=decision_iteration,
                attempts=attempts,
                created_at=created_at,
            )
        except TutorPersistenceError as exc:
            raise TutorLifecycleConflict("Tutor provider attempt persistence conflicted") from exc

    def persist_safe_checkpoint(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        checkpoint: TutorCheckpoint,
        compaction_request: TutorCompactionRequest,
    ) -> None:
        try:
            self._repository.persist_safe_checkpoint(
                user_id=snapshot.user_id,
                lease=lease,
                checkpoint=checkpoint,
                envelope=self._envelope(compaction_request, created_at=checkpoint.created_at),
            )
        except (TutorLeaseConflict, TutorTerminalStateConflict) as exc:
            raise TutorLifecycleConflict("Tutor checkpoint lifecycle lost ownership") from exc

    def persist_context_high_water(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        request: TutorCompactionRequest,
        created_at: datetime,
    ) -> None:
        try:
            self._repository.persist_context_high_water(
                user_id=snapshot.user_id,
                lease=lease,
                request=request,
                envelope=self._envelope(request, created_at=created_at),
                created_at=created_at,
            )
        except (TutorLeaseConflict, TutorTerminalStateConflict) as exc:
            raise TutorLifecycleConflict("Tutor compaction lifecycle lost ownership") from exc

    def persist_terminal(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        checkpoint: TutorCheckpoint,
        result: TutorRunResult,
        compaction_request: TutorCompactionRequest,
    ) -> TutorRunResult:
        try:
            return self._repository.complete_run(
                user_id=snapshot.user_id,
                lease=lease,
                checkpoint=checkpoint,
                result=result,
                envelope=self._envelope(compaction_request, created_at=checkpoint.created_at),
            )
        except (TutorLeaseConflict, TutorTerminalStateConflict) as exc:
            raise TutorLifecycleConflict("Tutor terminal lifecycle lost ownership") from exc

    def persist_interaction_request(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        decision: "TutorDecision",
        result: TutorRunResult,
        created_at: datetime,
    ) -> TutorRunResult:
        try:
            return self._repository.record_interaction_request(
                user_id=snapshot.user_id,
                lease=lease,
                decision=decision,
                result=result,
                created_at=created_at,
            )
        except (
            TutorInteractionRequestConflict,
            TutorLeaseConflict,
            TutorTerminalStateConflict,
        ) as exc:
            raise TutorLifecycleConflict("Tutor interaction-request lifecycle lost ownership") from exc

    def persist_waiting_result(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        result: TutorRunResult,
        created_at: datetime,
    ) -> TutorRunResult:
        try:
            return self._repository.record_waiting_result(
                user_id=snapshot.user_id,
                lease=lease,
                result=result,
                created_at=created_at,
            )
        except (TutorLeaseConflict, TutorTerminalStateConflict) as exc:
            raise TutorLifecycleConflict("Tutor waiting lifecycle lost ownership") from exc

    def _envelope(self, request: TutorCompactionRequest, *, created_at: datetime) -> TutorCurationEnvelope:
        return TutorCurationEnvelope(
            request=request,
            memory_setting_version=self._memory_setting_version,
            priority=self._priority,
            retention_until=created_at + timedelta(days=_DEFAULT_RETENTION_DAYS),
            stale_after=created_at + timedelta(days=_DEFAULT_STALE_DAYS),
        )


class PostgresTutorRunStore(TutorRunStore):
    """User-scoped ``TutorRunStore`` adapter; pair it with ``PostgresTutorLifecycle``."""

    def __init__(self, *, repository: PostgresTutorRepository, user_id: str) -> None:
        self._repository = repository
        self._user_id = user_id

    def load_snapshot(self, run_id: str) -> TutorRunSnapshot | None:
        return self._repository.load_snapshot(user_id=self._user_id, run_id=run_id)

    def acquire_lease(self, run_id: str, *, owner_id: str, now: datetime, duration_seconds: int) -> TutorLease | None:
        return self._repository.acquire_lease(
            user_id=self._user_id,
            run_id=run_id,
            owner_id=owner_id,
            now=now,
            duration_seconds=duration_seconds,
        )

    def heartbeat_lease(self, lease: TutorLease, *, now: datetime, duration_seconds: int) -> TutorLease | None:
        return self._repository.heartbeat_lease(
            user_id=self._user_id,
            lease=lease,
            now=now,
            duration_seconds=duration_seconds,
        )

    def current_input_revision(self, run_id: str) -> int:
        return self._repository.current_input_revision(user_id=self._user_id, run_id=run_id)

    def is_cancelled(self, run_id: str) -> bool:
        return self._repository.is_cancelled(user_id=self._user_id, run_id=run_id)

    def is_superseded(self, run_id: str) -> bool:
        return self._repository.is_superseded(user_id=self._user_id, run_id=run_id)

    def save_checkpoint(self, checkpoint: TutorCheckpoint) -> None:
        raise RuntimeError("PostgresTutorRunStore requires PostgresTutorLifecycle for checkpoint persistence")

    def record_result(self, result: TutorRunResult) -> None:
        raise RuntimeError("PostgresTutorRunStore requires PostgresTutorLifecycle for result persistence")


def _protocol_version_from_row(row: Mapping[str, object]) -> TutorInteractionProtocolVersion:
    raw = str(row.get("interaction_protocol_version") or TutorInteractionProtocolVersion.LEGACY_V1.value)
    try:
        return TutorInteractionProtocolVersion(raw)
    except ValueError:
        return TutorInteractionProtocolVersion.LEGACY_V1


def _validate_conversation_event_identity(
    *,
    kind: TutorConversationEventKind,
    payload: Mapping[str, object],
    turn_id: str | None,
    item_id: str | None,
    item_kind: str | None,
) -> None:
    if (item_id is None) != (item_kind is None):
        raise ValueError("conversation event item identity is incomplete")
    if kind in {TutorConversationEventKind.TURN_CREATED, TutorConversationEventKind.TURN_UPDATED}:
        turn = _as_mapping(payload.get("turn"))
        if _optional_string(turn.get("turn_id")) != turn_id or item_id is not None:
            raise ValueError("conversation turn event identity does not match its payload")
        return
    if kind in {TutorConversationEventKind.ITEM_ADDED, TutorConversationEventKind.ITEM_UPDATED}:
        item = _as_mapping(payload.get("item"))
        if (
            _optional_string(item.get("turn_id")) != turn_id
            or _optional_string(item.get("item_id")) != item_id
            or _optional_string(item.get("item_kind")) != item_kind
        ):
            raise ValueError("conversation item event identity does not match its payload")
        return
    if kind is TutorConversationEventKind.TURN_OUTPUT:
        if turn_id is None or item_id is not None:
            raise ValueError("conversation turn-output event requires only a turn identity")
        return
    if kind is TutorConversationEventKind.CONTROL_UPDATED:
        if turn_id is not None or item_id is not None:
            raise ValueError("conversation control event cannot reference a turn or item")
        return
    if turn_id is None:
        raise ValueError("conversation dispatch event requires a turn")
    if kind is TutorConversationEventKind.DISPATCH_DELAYED and item_id is not None:
        raise ValueError("delayed dispatch event cannot reference an item")
    if kind is TutorConversationEventKind.DISPATCH_DEAD and (item_id is None or item_kind != "error"):
        raise ValueError("dead dispatch event requires its public error item identity")


def _conversation_event_from_row(
    row: Mapping[str, object],
    *,
    cursor: str,
) -> TutorConversationEvent:
    kind = TutorConversationEventKind(str(row["kind"]))
    payload = validate_conversation_event_payload(kind, _as_mapping(row.get("payload_json")))
    return TutorConversationEvent(
        event_id=str(row["id"]),
        conversation_id=str(row["conversation_id"]),
        sequence=_as_int(row.get("event_sequence"), 0),
        event_key=str(row["event_key"]),
        kind=kind,
        turn_id=_optional_string(row.get("turn_id")),
        item_id=_optional_string(row.get("item_id")),
        item_kind=_optional_string(row.get("item_kind")),
        payload=payload,
        occurred_at=_as_datetime(row.get("occurred_at")) or datetime.now(UTC),
        cursor=cursor,
    )


def _interactive_dispatch_job_from_row(row: Mapping[str, object]) -> TutorInteractiveDispatchJob:
    return TutorInteractiveDispatchJob(
        job_id=str(row["id"]),
        run_id=str(row["run_id"]),
        user_id=str(row["user_id"]),
        conversation_id=str(row["conversation_id"]),
        state=TutorDispatchJobState(str(row["state"])),
        attempt_count=_as_int(row.get("attempt_count"), 0),
        max_attempts=_as_int(row.get("max_attempts"), _DISPATCH_JOB_MAX_ATTEMPTS),
        available_at=_as_datetime(row.get("available_at")) or datetime.now(UTC),
        lease_owner_id=_optional_string(row.get("lease_owner_id")),
        lease_generation=_as_int(row.get("lease_generation"), 0),
        lease_expires_at=_as_datetime(row.get("lease_expires_at")),
        last_error_code=_optional_string(row.get("last_error_code")),
        completed_at=_as_datetime(row.get("completed_at")),
        dead_at=_as_datetime(row.get("dead_at")),
    )


def _trace_from_row(row: Mapping[str, object], *, projector: TutorSafeProjection) -> TutorTraceRecord:
    created_at = _as_datetime(row.get("created_at")) or datetime.now(UTC)
    header = projector.export(
        {
            "trace_id": str(row.get("id") or ""),
            "run_id": str(row.get("run_id") or ""),
            "kind": row.get("kind"),
            "event_from_sequence": _as_int(row.get("event_from_sequence"), 0),
            "event_to_sequence": _as_int(row.get("event_to_sequence"), 0),
        }
    )
    trace_kind = str(header.get("kind") or "")
    return TutorTraceRecord(
        trace_id=str(header.get("trace_id") or "invalid_trace"),
        run_id=str(header.get("run_id") or "invalid_run"),
        kind=trace_kind if trace_kind in _TRACE_KINDS else "invalid_trace",
        event_from_sequence=_as_int(header.get("event_from_sequence"), 0),
        event_to_sequence=_as_int(header.get("event_to_sequence"), 0),
        payload=projector.export(row.get("trace_json")),
        created_at=created_at,
    )


def _event_from_row(row: Mapping[str, object], *, projector: TutorSafeProjection) -> TutorDurableEvent:
    created_at = _as_datetime(row.get("created_at")) or datetime.now(UTC)
    header = projector.export(
        {
            "event_id": str(row.get("id") or ""),
            "run_id": str(row.get("run_id") or ""),
            "event_sequence": _as_int(row.get("event_sequence"), 0),
            "event_key": row.get("event_key"),
            "kind": row.get("kind"),
            "input_revision": _as_int(row.get("input_revision"), 0),
        }
    )
    event_kind = str(header.get("kind") or "")
    return TutorDurableEvent(
        event_id=str(header.get("event_id") or "invalid_event"),
        run_id=str(header.get("run_id") or "invalid_run"),
        event_sequence=_as_int(header.get("event_sequence"), 0),
        event_key=str(header.get("event_key") or "invalid_event_key"),
        kind=event_kind if event_kind in _DURABLE_EVENT_KINDS else "invalid_event",
        input_revision=_as_int(header.get("input_revision"), 0),
        payload=projector.export(row.get("payload_json")),
        created_at=created_at,
    )

def _provider_attempt_record_from_row(row: Mapping[str, object]) -> TutorProviderAttemptRecord:
    usage = None
    if bool(row.get("usage_available")):
        usage = LLMUsage(
            input_tokens=_as_optional_int(row.get("input_tokens")),
            cached_input_tokens=_as_optional_int(row.get("cached_input_tokens")),
            output_tokens=_as_optional_int(row.get("output_tokens")),
            total_tokens=_as_optional_int(row.get("reported_total_tokens")),
            reasoning_tokens=_as_optional_int(row.get("reasoning_tokens")),
        )
    return TutorProviderAttemptRecord(
        receipt_id=str(row["id"]),
        run_id=str(row["run_id"]),
        input_revision=_as_int(row.get("input_revision"), 0),
        decision_iteration=_as_int(row.get("decision_iteration"), 0),
        attempt=TutorProviderAttemptReceipt(
            attempt_index=_as_int(row.get("attempt_index"), 0),
            outcome=TutorProviderAttemptOutcome(str(row["outcome"])),
            provider_type=str(row["provider_type"]),
            protocol=str(row["protocol"]),
            model=str(row["model"]) if row.get("model") is not None else None,
            usage=usage,
            diagnostic_code=(
                str(row["diagnostic_code"])
                if row.get("diagnostic_code") is not None
                else None
            ),
        ),
        created_at=_as_datetime(row.get("created_at")) or datetime.now(UTC),
    )


def _selection_from_row(row: Mapping[str, object]) -> tuple[str, int, str, str, str, str, str]:
    return (
        str(row["run_id"]),
        _as_int(row["input_revision"], 0),
        str(row["skill_id"]),
        str(row["skill_version"]),
        str(row["manifest_hash"]),
        str(row["instruction_hash"]),
        str(row["evaluation_hash"]),
    )


def _queued_input_from_row(row: Mapping[str, object]) -> TutorQueuedInput:
    return TutorQueuedInput(
        item_id=str(row["id"]),
        user_id=str(row["user_id"]),
        conversation_id=str(row["conversation_id"]),
        content=str(row.get("content") or ""),
        state=str(row.get("state") or "pending"),
        position=_as_int(row.get("position"), 1),
        version=_as_int(row.get("version"), 1),
        claimed_turn_id=_optional_string(row.get("claimed_turn_id")),
        claimed_input_revision=(
            _as_int(row.get("claimed_input_revision"), 0)
            if row.get("claimed_input_revision") is not None
            else None
        ),
        claimed_mode=_optional_string(row.get("claimed_mode")),
        created_at=_as_datetime(row.get("created_at")) or datetime.now(UTC),
        updated_at=_as_datetime(row.get("updated_at")) or datetime.now(UTC),
    )


def _interaction_request_from_row(row: Mapping[str, object]) -> TutorInteractionRequestRecord:
    kind = TutorInteractionRequestKind(str(row["kind"]))
    actor = TutorInteractionRequestActor(str(row["actor"]))
    state = TutorInteractionRequestState(str(row["state"]))
    descriptor = _as_mapping(row.get("descriptor_json"))
    presentation = _as_mapping(row.get("presentation_json"))
    prompt = sanitize_summary_text(str(descriptor.get("prompt") or ""), max_length=1_200)
    allowed_actions: list[str]
    if state is not TutorInteractionRequestState.PENDING or actor is TutorInteractionRequestActor.AUTHORITY:
        allowed_actions = []
    elif kind is TutorInteractionRequestKind.APPROVAL:
        allowed_actions = ["approve", "deny"]
    else:
        allowed_actions = ["respond"]
    resolved_at = _as_datetime(row.get("resolved_at"))
    public_item = validate_public_item(
        {
            "kind": public_item_kind(kind),
            "id": str(row["item_id"]),
            "request_id": str(row["id"]),
            "turn_id": str(row["source_turn_id"]),
            "request_kind": kind.value,
            "actor": actor.value,
            "state": state.value,
            "version": _as_int(row.get("version"), 1),
            "required": True,
            "prompt": prompt,
            "public_thinking_text": _public_thinking_text_from_values(
                descriptor.get("public_thinking_text"),
                (),
            ),
            "presentation": presentation,
            "allowed_actions": allowed_actions,
            "answer_turn_id": _optional_string(row.get("answer_turn_id")),
            "created_at": (_as_datetime(row.get("created_at")) or datetime.now(UTC)).astimezone(UTC).isoformat(),
            "resolved_at": resolved_at.astimezone(UTC).isoformat() if resolved_at is not None else None,
        }
    )
    return TutorInteractionRequestRecord(
        request_id=str(row["id"]),
        item_id=str(row["item_id"]),
        user_id=str(row["user_id"]),
        conversation_id=str(row["conversation_id"]),
        source_turn_id=str(row["source_turn_id"]),
        kind=kind,
        actor=actor,
        state=state,
        version=_as_int(row.get("version"), 1),
        schema_version=str(row.get("schema_version") or TUTOR_INTERACTION_REQUEST_SCHEMA_VERSION),
        catalog_version=_optional_string(row.get("catalog_version")),
        question_key=_optional_string(row.get("question_key")),
        descriptor=descriptor,
        presentation=presentation,
        answer_turn_id=_optional_string(row.get("answer_turn_id")),
        answer_message_id=_optional_string(row.get("answer_message_id")),
        created_at=_as_datetime(row.get("created_at")) or datetime.now(UTC),
        resolved_at=resolved_at,
        public_item=public_item,
    )


def _snapshot_from_row(row: Mapping[str, object]) -> TutorRunSnapshot:
    policy_data = _as_mapping(row.get("policy_json"))
    deadline = _as_datetime(policy_data.get("deadline"))
    if deadline is None:
        raise TutorPersistenceError("stored Tutor policy is invalid")
    policy = TutorPolicySnapshot(
        deadline=deadline,
        max_iterations=_as_int(policy_data.get("max_iterations"), 0),
        max_model_calls=_as_int(policy_data.get("max_model_calls"), 0),
        max_capability_calls=_as_int(policy_data.get("max_capability_calls"), 0),
        max_effects=_as_int(policy_data.get("max_effects"), 0),
        context_token_budget=_as_int(policy_data.get("context_token_budget"), 1),
        lease_duration_seconds=_as_int(policy_data.get("lease_duration_seconds"), 1),
        context_budget_policy=_context_budget_policy_from_payload(policy_data.get("context_budget_policy")),
    )
    origin = str(row.get("origin") or "")
    if origin not in {"interactive", "proactive"}:
        raise TutorPersistenceError("stored Tutor run origin is invalid")
    expires_at = _as_datetime(row.get("active_lease_expires_at"))
    owner_id = row.get("active_lease_owner_id")
    generation = _as_int(row.get("active_lease_generation"), 0)
    lease = (
        TutorLease(run_id=str(row["id"]), owner_id=str(owner_id), generation=generation, expires_at=expires_at)
        if owner_id and expires_at is not None and generation > 0
        else None
    )
    return TutorRunSnapshot(
        run_id=str(row["id"]),
        conversation_id=str(row["conversation_id"]),
        user_id=str(row["user_id"]),
        input_revision=_as_int(row["input_revision"], 0),
        policy=policy,
        origin=cast(TutorRunOrigin, origin),
        status=TutorRunStatus(str(row["status"])),
        lease=lease,
        iteration_count=_as_int(row.get("iteration_count"), 0),
        model_call_count=_as_int(row.get("model_call_count"), 0),
        capability_call_count=_as_int(row.get("capability_call_count"), 0),
        effect_count=_as_int(row.get("effect_count"), 0),
        cancelled=row.get("cancelled_at") is not None,
        continuation_kind=(
            TutorContinuationKind(str(row["continuation_kind"]))
            if row.get("continuation_kind") is not None
            else None
        ),
        interaction_protocol_version=_protocol_version_from_row(row).value,
        runtime_kind=cast(
            Literal["harness_v1", "codex_sidecar_v1"],
            str(row.get("runtime_kind") or "harness_v1"),
        ),
    )


def _result_from_row(row: Mapping[str, object]) -> TutorRunResult:
    raw_outcome = row.get("terminal_outcome")
    outcome = TutorTerminalOutcome(str(raw_outcome)) if raw_outcome else None
    return TutorRunResult(
        run_id=str(row["id"]),
        status=TutorRunStatus(str(row["status"])),
        input_revision=_as_int(row["input_revision"], 0),
        iteration_count=_as_int(row.get("iteration_count"), 0),
        model_call_count=_as_int(row.get("model_call_count"), 0),
        capability_call_count=_as_int(row.get("capability_call_count"), 0),
        effect_count=_as_int(row.get("effect_count"), 0),
        terminal_outcome=outcome,
        completion_reason=(
            TutorTurnCompletionReason(str(row["completion_reason"]))
            if row.get("completion_reason") is not None
            else None
        ),
        diagnostic_code=str(row["terminal_diagnostic_code"]) if row.get("terminal_diagnostic_code") else None,
    )


def _policy_payload(policy: TutorPolicySnapshot) -> dict[str, object]:
    return {
        "deadline": policy.deadline,
        "max_iterations": policy.max_iterations,
        "max_model_calls": policy.max_model_calls,
        "max_capability_calls": policy.max_capability_calls,
        "max_effects": policy.max_effects,
        "context_token_budget": policy.context_token_budget,
        "lease_duration_seconds": policy.lease_duration_seconds,
        "context_budget_policy": (
            _context_budget_policy_payload(policy.context_budget_policy)
            if policy.context_budget_policy is not None
            else None
        ),
    }


def _context_budget_policy_payload(policy: TutorContextBudgetPolicy) -> dict[str, object]:
    capability = policy.capability
    return {
        "capability": {
            "context_window_tokens": capability.context_window_tokens,
            "max_output_reserve_tokens": capability.max_output_reserve_tokens,
            "protocol_reserve_tokens": capability.protocol_reserve_tokens,
            "safety_margin_tokens": capability.safety_margin_tokens,
            "maximum_dynamic_target_tokens": capability.maximum_dynamic_target_tokens,
            "capability_version": capability.capability_version,
        },
        "mode_targets": {
            mode.value: target for mode, target in policy.mode_targets
        },
        "warning_ratio": policy.warning_ratio,
        "critical_ratio": policy.critical_ratio,
        "max_expansions": policy.max_expansions,
        "estimator_version": policy.estimator_version,
        "policy_version": policy.policy_version,
        "fixed_mode": policy.fixed_mode.value if policy.fixed_mode is not None else None,
    }


def _context_budget_policy_from_payload(value: object) -> TutorContextBudgetPolicy | None:
    payload = _as_mapping(value)
    if not payload:
        return None
    capability_data = _as_mapping(payload.get("capability"))
    mode_target_data = _as_mapping(payload.get("mode_targets"))
    try:
        capability = TutorProviderContextCapability(
            context_window_tokens=_as_int(capability_data.get("context_window_tokens"), 0),
            max_output_reserve_tokens=_as_int(capability_data.get("max_output_reserve_tokens"), 0),
            protocol_reserve_tokens=_as_int(capability_data.get("protocol_reserve_tokens"), 0),
            safety_margin_tokens=_as_int(capability_data.get("safety_margin_tokens"), 0),
            maximum_dynamic_target_tokens=_as_int(capability_data.get("maximum_dynamic_target_tokens"), 0),
            capability_version=str(capability_data.get("capability_version") or ""),
        )
        fixed_mode_value = payload.get("fixed_mode")
        return TutorContextBudgetPolicy(
            capability=capability,
            mode_targets=tuple(
                (
                    mode,
                    _as_int(mode_target_data.get(mode.value), 0),
                )
                for mode in TutorContextBudgetMode
            ),
            warning_ratio=_as_float(payload.get("warning_ratio"), 0.0),
            critical_ratio=_as_float(payload.get("critical_ratio"), 0.0),
            max_expansions=_as_int(payload.get("max_expansions"), 0),
            estimator_version=str(payload.get("estimator_version") or ""),
            policy_version=str(payload.get("policy_version") or ""),
            fixed_mode=(
                TutorContextBudgetMode(str(fixed_mode_value))
                if fixed_mode_value is not None
                else None
            ),
        )
    except (TypeError, ValueError) as exc:
        raise TutorPersistenceError("stored Tutor context budget policy is invalid") from exc


def _compaction_payload(request: TutorCompactionRequest, *, status: str) -> dict[str, object]:
    return {
        "kind": "compaction_request",
        "status": status,
        "idempotency_key": request.idempotency_key,
        "curation_idempotency_key": request.curation_idempotency_key,
        "run_id": request.run_id,
        "conversation_id": request.conversation_id,
        "input_revision": request.input_revision,
        "trigger": request.trigger.value,
        "projection_kind": request.projection_kind,
        "source_ids": list(request.source_ids),
        "source_hashes": list(request.source_hashes),
        "token_budget": request.token_budget,
        "consumed_tokens": request.consumed_tokens,
        "summary_schema_version": request.summary_schema_version,
        "summary_policy_version": request.summary_policy_version,
        "summary_source_hash": request.summary_source_hash,
        "prior_summary_id": request.prior_summary_id,
        "prior_summary_hash": request.prior_summary_hash,
        "covered_through_created_at": request.covered_through_created_at,
        "covered_through_message_id": request.covered_through_message_id,
    }


def _assert_not_terminal(run: Mapping[str, object]) -> None:
    if _is_terminal(run):
        raise TutorTerminalStateConflict("Tutor run is terminal")


def _assert_not_cancelled(run: Mapping[str, object]) -> None:
    if run.get("cancelled_at") is not None:
        raise TutorTerminalStateConflict("Tutor run is cancelled")


def _assert_not_superseded(run: Mapping[str, object]) -> None:
    if run.get("superseded_by_run_id") is not None:
        raise TutorTerminalStateConflict("Tutor run is superseded")


def _is_terminal(run: Mapping[str, object]) -> bool:
    return str(run.get("status") or "") in _TERMINAL_STATUSES or run.get("terminal_outcome") is not None


def _assert_active_lease(run: Mapping[str, object], *, lease: TutorLease, now: datetime) -> None:
    if not _lease_matches(run, lease=lease, now=now):
        raise TutorLeaseConflict("Tutor lease is stale or unavailable")


def _lease_matches(run: Mapping[str, object], *, lease: TutorLease, now: datetime) -> bool:
    expiry = _as_datetime(run.get("active_lease_expires_at"))
    return (
        str(run.get("active_lease_owner_id") or "") == lease.owner_id
        and _as_int(run.get("active_lease_generation"), 0) == lease.generation
        and expiry is not None
        and expiry > now
    )


def _payload_fields_hash(fields: Sequence[object]) -> str:
    serializable: list[dict[str, str]] = []
    for field in fields:
        key = getattr(field, "key", "")
        value = getattr(field, "value", "")
        serializable.append({"key": str(key), "value": str(value)})
    return _sha256_json(serializable)


def _safe_key(value: str, *, label: str) -> None:
    if not _SAFE_KEY.fullmatch(value):
        raise ValueError(f"{label} must be a stable bounded identifier")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))


def _public_thinking_text_from_values(text_value: object, steps_value: object) -> str:
    if isinstance(text_value, str):
        text = text_value.strip()
        if text:
            if len(text) > MAX_TUTOR_PUBLIC_THINKING_TEXT_LENGTH:
                text = text[:MAX_TUTOR_PUBLIC_THINKING_TEXT_LENGTH]
            if not check_teaching_output(text).blocked:
                return text
    return "\n\n".join(_public_thinking_steps_from_value(steps_value))


def _public_thinking_steps_from_value(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    steps: list[str] = []
    for raw_step in value[:MAX_TUTOR_PUBLIC_THINKING_STEPS]:
        if not isinstance(raw_step, str):
            continue
        step = sanitize_summary_text(
            raw_step,
            max_length=MAX_TUTOR_PUBLIC_THINKING_STEP_LENGTH,
        )
        if step:
            steps.append(step)
    return tuple(steps)


def _as_mapping(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return _as_mapping(decoded)
    return {}


def _as_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return []
        return _as_list(decoded)
    return []


def _as_int(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default

def _as_float(value: object, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float | str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None


def _optional_text(row: Mapping[str, object], key: str) -> str | None:
    return _optional_string(row.get(key))


def _as_optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return None
