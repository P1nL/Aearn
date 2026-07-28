"""Target-only PostgreSQL persistence for the feature-disabled Tutor Harness.

The repository is deliberately isolated from routes, workers, and legacy Graph
composition. It accepts a caller-owned psycopg connection and opens a local
transaction/savepoint only for operations that must be atomic.
"""
from __future__ import annotations

import hashlib
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
    TutorCapabilityRequest,
    TutorCapabilityResult,
    TutorCheckpoint,
    TutorCompactionRequest,
    TutorCompactionTrigger,
    TutorEffectProposal,
    TutorEffectResult,
    TutorEffectStatus,
    TutorLease,
    TutorPolicySnapshot,
    TutorRunResult,
    TutorRunOrigin,
    TutorRunSnapshot,
    TutorRunStatus,
    TutorTerminalOutcome,
    payload_mapping_from_fields,
)
from app.agents.harness.skill_catalog import SkillCatalogSnapshot
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
              policy_version, policy_fingerprint, catalog_digest
            )
            VALUES (%s, %s, %s, %s, 'queued', %s::jsonb, %s, %s, %s)
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
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("tutor run insert failed")
        return _snapshot_from_row(row)

    def load_snapshot(self, *, user_id: str, run_id: str) -> TutorRunSnapshot | None:
        row = self._conn.execute(
            "SELECT * FROM tutor_runs WHERE id = %s AND user_id = %s",
            (run_id, user_id),
        ).fetchone()
        return _snapshot_from_row(row) if row is not None else None

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
            if _is_terminal(run):
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
            row = self._conn.execute(
                """
                UPDATE tutor_runs
                SET active_lease_expires_at = %s
                WHERE id = %s
                  AND user_id = %s
                  AND active_lease_owner_id = %s
                  AND active_lease_generation = %s
                  AND active_lease_expires_at > %s
                  AND terminal_outcome IS NULL
                RETURNING id, active_lease_owner_id, active_lease_generation, active_lease_expires_at
                """,
                (new_expiry, lease.run_id, user_id, lease.owner_id, lease.generation, now),
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

    def request_cancellation(self, *, user_id: str, run_id: str, now: datetime) -> None:
        row = self._conn.execute(
            """
            UPDATE tutor_runs
            SET cancelled_at = COALESCE(cancelled_at, %s)
            WHERE id = %s AND user_id = %s AND terminal_outcome IS NULL
            RETURNING id
            """,
            (now, run_id, user_id),
        ).fetchone()
        if row is None and self.load_snapshot(user_id=user_id, run_id=run_id) is None:
            raise TutorRunNotFound("tutor run not found")

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
            _assert_not_terminal(run)
            _assert_not_cancelled(run)
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
                SET input_revision = input_revision + 1
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
            if (_is_terminal(run) or run.get("cancelled_at") is not None) and kind != "terminal_result":
                raise TutorTerminalStateConflict("terminal or cancelled Tutor run cannot append a non-terminal event")
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
            run = self._lock_run(user_id=user_id, run_id=run_id)
            _assert_not_terminal(run)
            _assert_not_cancelled(run)
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
            run = self._lock_run(user_id=user_id, run_id=run_id)
            _assert_active_lease(run, lease=lease, now=datetime.now(UTC))
            _assert_not_terminal(run)
            _assert_not_cancelled(run)
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
            run = self._lock_run(user_id=user_id, run_id=run_id)
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
            run = self._lock_run(user_id=user_id, run_id=checkpoint.run_id)
            _assert_active_lease(run, lease=lease, now=checkpoint.created_at)
            _assert_not_terminal(run)
            _assert_not_cancelled(run)
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
            run = self._lock_run(user_id=user_id, run_id=request.run_id)
            _assert_active_lease(run, lease=lease, now=created_at)
            _assert_not_terminal(run)
            _assert_not_cancelled(run)
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
        with self._conn.transaction():
            run = self._lock_run(user_id=user_id, run_id=result.run_id)
            if _is_terminal(run):
                return _result_from_row(run)
            _assert_active_lease(run, lease=lease, now=checkpoint.created_at)
            if checkpoint.input_revision != _as_int(run["input_revision"], 0) or result.input_revision != checkpoint.input_revision:
                raise TutorLeaseConflict("terminal lifecycle revision is stale")
            trace = self._persist_checkpoint_and_outbox_locked(run=run, checkpoint=checkpoint, envelope=envelope)
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
                    terminal_at = %s
                WHERE id = %s AND user_id = %s AND terminal_outcome IS NULL
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
            run = self._lock_run(user_id=user_id, run_id=result.run_id)
            _assert_active_lease(run, lease=lease, now=created_at)
            _assert_not_terminal(run)
            _assert_not_cancelled(run)
            if result.input_revision != _as_int(run["input_revision"], 0):
                raise TutorLeaseConflict("waiting result revision is stale")
            event = self._append_event_locked(
                run_id=result.run_id,
                event_key=f"waiting:{result.input_revision}:{result.iteration_count}:{result.model_call_count}",
                kind="waiting_for_input",
                input_revision=result.input_revision,
                payload={
                    "kind": "waiting_for_input",
                    "status": result.status.value,
                    "run_id": result.run_id,
                    "input_revision": result.input_revision,
                    "count": result.iteration_count,
                },
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
            self._conn.execute(
                """
                UPDATE tutor_runs
                SET status = %s, iteration_count = %s, model_call_count = %s,
                    capability_call_count = %s, effect_count = %s
                WHERE id = %s AND user_id = %s
                """,
                (
                    result.status.value,
                    result.iteration_count,
                    result.model_call_count,
                    result.capability_call_count,
                    result.effect_count,
                    result.run_id,
                    user_id,
                ),
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
        event = self._append_event_locked(
            run_id=str(run["id"]),
            event_key=f"checkpoint:{checkpoint.input_revision}:{checkpoint.reason.value}:{checkpoint.status.value}",
            kind=event_kind,
            input_revision=checkpoint.input_revision,
            payload={
                **safe_checkpoint,
                "kind": event_kind,
                "run_id": str(run["id"]),
                "catalog_digest": str(run["catalog_digest"]),
                "policy_version": str(run["policy_version"]),
            },
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
        _safe_key(request.idempotency_key, label="curation idempotency key")
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
              priority, retention_until, stale_after, state, idempotency_key, envelope_json, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, 'pending', %s, %s::jsonb, %s)
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
                envelope.priority,
                retention_until,
                stale_after,
                request.idempotency_key,
                _json(payload),
                created_at,
            ),
        ).fetchone()
        if row is None:
            row = self._conn.execute(
                "SELECT * FROM tutor_memory_curation_outbox WHERE idempotency_key = %s FOR UPDATE",
                (request.idempotency_key,),
            ).fetchone()
            if row is None:
                raise RuntimeError("curation outbox replay row is missing")
            if (
                str(row["run_id"]) != str(run["id"])
                or str(row["conversation_id"]) != str(run["conversation_id"])
                or _as_int(row["input_revision"], -1) != request.input_revision
                or str(row["trigger"]) != request.trigger.value
                or _as_int(row["event_from_sequence"], -1) != event_sequence
                or _as_int(row["event_to_sequence"], -1) != event_sequence
                or str(row["trace_id"]) != trace_id
                or _as_list(row.get("source_ids_json")) != safe_source_ids
                or _as_list(row.get("source_hashes_json")) != safe_source_hashes
                or str(row["policy_version"]) != str(run["policy_version"])
                or str(row["memory_setting_version"]) != envelope.memory_setting_version
                or _as_int(row["priority"], -1) != envelope.priority
            ):
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
    }


def _compaction_payload(request: TutorCompactionRequest, *, status: str) -> dict[str, object]:
    return {
        "kind": "compaction_request",
        "status": status,
        "idempotency_key": request.idempotency_key,
        "run_id": request.run_id,
        "conversation_id": request.conversation_id,
        "input_revision": request.input_revision,
        "trigger": request.trigger.value,
        "source_ids": list(request.source_ids),
        "source_hashes": list(request.source_hashes),
        "token_budget": request.token_budget,
        "consumed_tokens": request.consumed_tokens,
    }


def _assert_not_terminal(run: Mapping[str, object]) -> None:
    if _is_terminal(run):
        raise TutorTerminalStateConflict("Tutor run is terminal")


def _assert_not_cancelled(run: Mapping[str, object]) -> None:
    if run.get("cancelled_at") is not None:
        raise TutorTerminalStateConflict("Tutor run is cancelled")


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
