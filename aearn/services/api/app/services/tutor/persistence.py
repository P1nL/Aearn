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
from typing import Final, cast
from uuid import uuid4

from psycopg import Connection
from pydantic import ValidationError

from app.agents.harness.capabilities import EffectDescriptor, default_effect_descriptors, is_exact_semver
from app.agents.harness.contracts import (
    MAX_TUTOR_PUBLIC_THINKING_STEP_LENGTH,
    MAX_TUTOR_PUBLIC_THINKING_STEPS,
    TutorCapabilityRequest,
    TutorCapabilityResult,
    TutorCapabilityStatus,
    TutorCheckpoint,
    TutorCompactionRequest,
    TutorCompactionTrigger,
    TutorContextBudgetMode,
    TutorContextBudgetPolicy,
    TutorContinuationKind,
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
    normalize_tutor_conversation_title,
    payload_mapping_from_fields,
)
from app.agents.harness.skill_catalog import CatalogSkillReference, SkillCatalogSnapshot
from app.core.config import get_settings
from app.core.teaching_safety import sanitize_summary_text
from app.services.llm.contracts import LLMUsage
from app.services.tutor.ports import TutorLifecycleConflict, TutorLifecyclePersistence, TutorRunStore
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
_PUBLIC_PROCESS_STATES: Final[frozenset[str]] = frozenset({"thinking", "completed", "superseded", "unavailable"})
_PUBLIC_PROCESS_STEP_KEYS: Final[frozenset[str]] = frozenset(
    {
        "input_received",
        "context_prepared",
        "authorized_resource_checked",
        "learning_reply_generated",
        "replaced_by_newer_input",
    }
)
_PUBLIC_PROCESS_STEP_STATES: Final[frozenset[str]] = frozenset({"completed", "current"})
_PUBLIC_PROCESS_STEP_LABELS: Final[dict[str, str]] = {
    "input_received": "已接收你的问题",
    "context_prepared": "已整理最近的对话与学习目标",
    "authorized_resource_checked": "已查阅已授权的学习资料",
    "learning_reply_generated": "已完成一次受控学习建议生成",
    "replaced_by_newer_input": "已根据你的新消息更新本轮处理",
}
_MAX_PUBLIC_PROCESS_ELAPSED_SECONDS: Final[int] = 3_600
_CURSOR_VERSION: Final[int] = 1


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


@dataclass(frozen=True)
class TutorRunReadState:
    """Learner-safe run lifecycle facts for the Child 06 public adapter."""

    snapshot: TutorRunSnapshot
    terminal_outcome: TutorTerminalOutcome | None
    diagnostic_code: str | None
    created_at: datetime
    updated_at: datetime


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
    public_thinking_steps: tuple[str, ...] = ()
    context_references: tuple[dict[str, object], ...] = ()
    process: TutorPublicProcessState | None = None


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
    ) -> TutorRunSnapshot:
        if origin not in {"interactive", "proactive"}:
            raise ValueError("Tutor run origin is invalid")
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
              policy_version, policy_fingerprint, catalog_digest, continuation_kind
            )
            VALUES (%s, %s, %s, %s, 'queued', %s::jsonb, %s, %s, %s, %s)
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
                messages.public_thinking_steps_json AS public_thinking_steps_json,
                NULL::uuid AS process_run_id
              FROM tutor_messages AS messages
              JOIN tutor_conversations AS conversations ON conversations.id = messages.conversation_id
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
                '[]'::jsonb AS public_thinking_steps_json,
                processes.run_id AS process_run_id
              FROM tutor_run_public_processes AS processes
              JOIN tutor_conversations AS conversations ON conversations.id = processes.conversation_id
              WHERE processes.conversation_id = %s
                AND processes.user_id = %s
                AND conversations.visibility = 'learner'
                AND conversations.kind = 'interactive'
                AND conversations.status = 'active'
            )
            SELECT * FROM timeline
        """
        params: list[object] = [conversation_id, user_id, conversation_id, user_id]
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
                        public_thinking_steps=(
                            _public_thinking_steps_from_value(
                                row.get("public_thinking_steps_json")
                            )
                            if role == "tutor"
                            else ()
                        ),
                        context_references=references_by_message.get(str(row["item_id"]), ()),
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

    def accept_input(
        self,
        *,
        user_id: str,
        run_id: str,
        idempotency_key: str,
        content: str,
        body_hash: str | None = None,
        source: str = "learner",
        received_at: datetime | None = None,
    ) -> TutorInputAcceptance:
        _safe_key(idempotency_key, label="input idempotency key")
        _safe_key(source, label="input source")
        raw_content = str(content)
        if not raw_content or len(raw_content) > 16_000:
            raise ValueError("learner message must be non-empty and bounded")
        actual_hash = _sha256_text(raw_content)
        if body_hash is not None and body_hash != actual_hash:
            raise TutorIdempotencyConflict("input body hash does not match learner message")
        accepted_at = received_at or datetime.now(UTC)
        event_key = f"input:{idempotency_key}"
        with self._conn.transaction():
            run = self._lock_run(user_id=user_id, run_id=run_id)
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
                return TutorInputAcceptance(
                    run_id=run_id,
                    message_id=str(existing["message_id"]),
                    input_revision=_as_int(existing["input_revision"], 0),
                    event=event,
                    replayed=True,
                )
            _assert_not_cancelled(run)
            _assert_not_superseded(run)
            _assert_not_terminal(run)
            message = self._conn.execute(
                """
                INSERT INTO tutor_messages (conversation_id, role, content, created_at)
                VALUES (%s, 'learner', %s, %s)
                RETURNING id
                """,
                (run["conversation_id"], raw_content, accepted_at),
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
                RETURNING input_revision
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
            return TutorInputAcceptance(
                run_id=run_id,
                message_id=str(message["id"]),
                input_revision=revision,
                event=event,
                replayed=False,
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
        with self._conn.transaction():
            _conversation, run = self._lock_run_with_conversation(
                user_id=user_id,
                run_id=run_id,
                learner_only=False,
            )
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
                event = self._event_by_key_locked(run_id=run_id, event_key=event_key)
                if event is None:
                    raise RuntimeError("effect replay event is missing")
                return TutorEffectCommitReceipt(
                    result=TutorEffectResult(
                        effect_id=proposal.effect_id,
                        status=TutorEffectStatus(str(existing["status"])),
                        commit_id=str(existing["commit_id"]) if existing.get("commit_id") else None,
                    ),
                    event=event,
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

            provisional = self._conn.execute(
                """
                INSERT INTO tutor_effects (
                  run_id, effect_id, idempotency_key, effect_type, expected_input_revision,
                  payload_hash, lease_owner_id, lease_generation, status, safe_outcome_json, safe_outcome_hash
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'proposed', %s::jsonb, %s)
                RETURNING id
                """,
                (
                    run_id,
                    proposal.effect_id,
                    idempotency_key,
                    proposal.effect_type,
                    proposal.expected_input_revision,
                    payload_hash,
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
            del trace
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
                RETURNING id
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
        row = self._conn.execute(
            """
            INSERT INTO tutor_messages (
              conversation_id, role, content, public_thinking_steps_json, created_at
            )
            VALUES (%s, 'tutor', %s, %s::jsonb, %s)
            RETURNING id
            """,
            (
                run["conversation_id"],
                public_message,
                _json(list(result.public_thinking_steps)),
                created_at,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("Tutor public message insert failed")
        return str(row["id"])

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


def _optional_text(row: Mapping[str, object], key: str) -> str | None:
    value = row.get(key)
    return str(value) if value is not None else None


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
