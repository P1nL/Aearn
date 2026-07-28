"""Target-only immutable Tutor learner state and effect handlers.

This module owns Child 05 plan revisions, learner memory, activity/inbox state,
and curation projection receipts. It deliberately has no route, SSE, Desktop,
legacy-plan, review, FSRS, attempt, or provider dependency.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from psycopg import Connection
from pydantic import ValidationError

from app.agents.harness.capabilities import (
    TUTOR_ACTIVITY_RECORD_EFFECT_TYPE,
    TUTOR_MEMORY_RECORD_EFFECT_TYPE,
    TUTOR_PLAN_ACTIVATE_EFFECT_TYPE,
    TUTOR_PLAN_ROLLBACK_EFFECT_TYPE,
    TutorActivityRecordProposalV1,
    TutorObjectiveMemoryRecordProposalV1,
    TutorPlanActivateProposalV1,
    TutorPlanRollbackProposalV1,
    contains_forbidden_execution_target,
)
from app.agents.harness.contracts import (
    TutorEffectProposal,
    TutorEffectResult,
    TutorEffectStatus,
    TutorRunSnapshot,
    payload_mapping_from_fields,
)


_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
MemoryState = Literal["active", "corrected", "deleted", "expired"]
InboxState = Literal["unread", "read", "dismissed"]
CurationReceiptState = Literal["committed", "no_action", "stale", "failed"]
CurationTargetKind = Literal["context_summary", "memory_entry", "none"]


class TutorLearnerStateError(ValueError):
    """Stable target-domain validation failure without provider diagnostics."""


class TutorLearnerStateNotFound(TutorLearnerStateError):
    pass


class TutorLearnerStateConflict(TutorLearnerStateError):
    pass


@dataclass(frozen=True)
class TutorPlanRevision:
    revision_id: str
    user_id: str
    predecessor_revision_id: str | None
    title: str
    outline: tuple[str, ...]
    learner_reason: str
    policy_version: str
    created_at: datetime
    diff: tuple[dict[str, object], ...] = ()
    evidence_ids: tuple[str, ...] = ()
    evidence_hashes: tuple[str, ...] = ()


@dataclass(frozen=True)
class TutorMemoryPreference:
    user_id: str
    inferred_memory_enabled: bool
    setting_version: str
    version: int


@dataclass(frozen=True)
class TutorMemoryEntry:
    entry_id: str
    user_id: str
    memory_kind: Literal["objective_fact", "inference"]
    state: MemoryState
    category: str
    statement: str
    confidence: str | None
    provenance_kind: str
    replaced_entry_id: str | None
    policy_version: str | None
    memory_setting_version: str | None
    retention_until: datetime | None
    stale_after: datetime | None
    created_at: datetime
    evidence_ids: tuple[str, ...] = ()
    evidence_hashes: tuple[str, ...] = ()


@dataclass(frozen=True)
class TutorActivityRecord:
    activity_id: str
    user_id: str
    category: str
    learner_reason: str
    created_at: datetime
    evidence_ids: tuple[str, ...] = ()
    evidence_hashes: tuple[str, ...] = ()


@dataclass(frozen=True)
class TutorInboxItem:
    inbox_id: str
    user_id: str
    activity_id: str
    message: str
    state: InboxState
    read_at: datetime | None
    dismissed_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class TutorCurationSource:
    job_id: str
    outbox_id: str
    run_id: str
    user_id: str
    lease_owner_id: str
    lease_generation: int
    policy_version: str
    memory_setting_version: str
    envelope: dict[str, object]
    source_ids: tuple[str, ...]
    source_hashes: tuple[str, ...]
    retention_until: datetime
    stale_after: datetime


@dataclass(frozen=True)
class TutorCurationProjectionReceipt:
    receipt_id: str
    proposal_id: str
    state: CurationReceiptState
    target_kind: CurationTargetKind
    target_id: str | None
    code: str


class TutorLearnerStateRepository:
    """Transaction-aware target-only repository used by effects and future adapters."""

    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn

    def for_transaction(self, conn: Connection[dict[str, object]]) -> "TutorLearnerStateRepository":
        return self if conn is self._conn else TutorLearnerStateRepository(conn)

    def activate_plan_from_effect(
        self,
        *,
        run: TutorRunSnapshot,
        proposal: TutorEffectProposal,
        request: TutorPlanActivateProposalV1,
        now: datetime | None = None,
    ) -> str:
        created_at = _utc(now)
        self._lock_user(run.user_id)
        active = self._conn.execute(
            """
            SELECT revision_id::text AS revision_id
            FROM tutor_active_plans
            WHERE user_id = %s
            FOR UPDATE
            """,
            (run.user_id,),
        ).fetchone()
        predecessor_revision_id = _optional_text(active, "revision_id")
        effect_record_id = self._proposed_effect_id(run=run, proposal=proposal)
        revision_id = str(uuid4())
        content = {"title": request.title, "outline": list(request.outline)}
        diff = [item.model_dump(mode="json", exclude_none=True) for item in request.diff]
        content_hash = _hash({"content": content, "diff": diff, "reason": request.change_reason})
        self._conn.execute(
            """
            INSERT INTO tutor_plan_revisions (
              id, user_id, predecessor_revision_id, source_run_id, source_effect_record_id,
              title, outline_json, diff_json, learner_reason, evidence_ids_json,
              evidence_hashes_json, policy_version, content_hash, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb,
                    %s::jsonb, %s, %s, %s)
            """,
            (
                revision_id,
                run.user_id,
                predecessor_revision_id,
                run.run_id,
                effect_record_id,
                request.title,
                _json(list(request.outline)),
                _json(diff),
                request.change_reason,
                _json(list(request.evidence_ids)),
                _json(list(request.evidence_hashes)),
                request.policy_version,
                content_hash,
                created_at,
            ),
        )
        self._conn.execute(
            """
            INSERT INTO tutor_active_plans (user_id, revision_id, updated_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id)
            DO UPDATE SET revision_id = EXCLUDED.revision_id, updated_at = EXCLUDED.updated_at
            """,
            (run.user_id, revision_id, created_at),
        )
        self._conn.execute(
            """
            INSERT INTO tutor_plan_revision_actions (
              user_id, action, current_revision_id, target_revision_id, predecessor_revision_id,
              source_run_id, source_effect_record_id, learner_reason, evidence_ids_json,
              evidence_hashes_json, policy_version, created_at
            )
            VALUES (%s, 'activate', %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
            """,
            (
                run.user_id,
                predecessor_revision_id,
                revision_id,
                predecessor_revision_id,
                run.run_id,
                effect_record_id,
                request.change_reason,
                _json(list(request.evidence_ids)),
                _json(list(request.evidence_hashes)),
                request.policy_version,
                created_at,
            ),
        )
        return revision_id

    def rollback_plan_from_effect(
        self,
        *,
        run: TutorRunSnapshot,
        proposal: TutorEffectProposal,
        request: TutorPlanRollbackProposalV1,
        now: datetime | None = None,
    ) -> str:
        created_at = _utc(now)
        self._lock_user(run.user_id)
        active = self._conn.execute(
            """
            SELECT active.revision_id::text AS current_revision_id,
                   revisions.predecessor_revision_id::text AS predecessor_revision_id
            FROM tutor_active_plans AS active
            JOIN tutor_plan_revisions AS revisions
              ON revisions.id = active.revision_id AND revisions.user_id = active.user_id
            WHERE active.user_id = %s
            FOR UPDATE OF active, revisions
            """,
            (run.user_id,),
        ).fetchone()
        if active is None or active.get("predecessor_revision_id") is None:
            raise TutorLearnerStateConflict("plan_rollback_unavailable")
        current_revision_id = str(active["current_revision_id"])
        target_revision_id = str(active["predecessor_revision_id"])
        effect_record_id = self._proposed_effect_id(run=run, proposal=proposal)
        self._conn.execute(
            "UPDATE tutor_active_plans SET revision_id = %s, updated_at = %s WHERE user_id = %s",
            (target_revision_id, created_at, run.user_id),
        )
        self._conn.execute(
            """
            INSERT INTO tutor_plan_revision_actions (
              user_id, action, current_revision_id, target_revision_id, predecessor_revision_id,
              source_run_id, source_effect_record_id, learner_reason, evidence_ids_json,
              evidence_hashes_json, policy_version, created_at
            )
            VALUES (%s, 'rollback', %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
            """,
            (
                run.user_id,
                current_revision_id,
                target_revision_id,
                target_revision_id,
                run.run_id,
                effect_record_id,
                request.reason,
                _json(list(request.evidence_ids)),
                _json(list(request.evidence_hashes)),
                request.policy_version,
                created_at,
            ),
        )
        return target_revision_id

    def rollback_plan_from_user_action(
        self,
        *,
        user_id: str,
        idempotency_key: str,
        reason: str = "Learner requested a plan rollback.",
        now: datetime | None = None,
    ) -> str:
        """Move only to the active revision's recorded predecessor.

        Public learner controls are not model effects.  They preserve the same
        immutable plan/action boundary while recording a user-control audit row
        with no fabricated run/effect linkage.  Route-level idempotency owns
        replay behavior for this method.
        """

        changed_at = _utc(now)
        action_key = _identifier(idempotency_key, label="plan rollback idempotency key")
        learner_reason = _learner_text(reason, label="plan rollback reason", maximum=160)
        evidence_hash = _hash({"user_id": user_id, "action": "plan_rollback", "key": action_key})
        evidence_id = f"user-control:{evidence_hash[:24]}"
        with self._conn.transaction():
            self._lock_user(user_id)
            active = self._conn.execute(
                """
                SELECT active.revision_id::text AS current_revision_id,
                       revisions.predecessor_revision_id::text AS predecessor_revision_id
                FROM tutor_active_plans AS active
                JOIN tutor_plan_revisions AS revisions
                  ON revisions.id = active.revision_id AND revisions.user_id = active.user_id
                WHERE active.user_id = %s
                FOR UPDATE OF active, revisions
                """,
                (user_id,),
            ).fetchone()
            if active is None or active.get("predecessor_revision_id") is None:
                raise TutorLearnerStateConflict("plan_rollback_unavailable")
            current_revision_id = str(active["current_revision_id"])
            target_revision_id = str(active["predecessor_revision_id"])
            self._conn.execute(
                "UPDATE tutor_active_plans SET revision_id = %s, updated_at = %s WHERE user_id = %s",
                (target_revision_id, changed_at, user_id),
            )
            self._conn.execute(
                """
                INSERT INTO tutor_plan_revision_actions (
                  user_id, action, current_revision_id, target_revision_id, predecessor_revision_id,
                  source_run_id, source_effect_record_id, learner_reason, evidence_ids_json,
                  evidence_hashes_json, policy_version, created_at
                )
                VALUES (%s, 'rollback', %s, %s, %s, NULL, NULL, %s, %s::jsonb, %s::jsonb, 'user_control_v1', %s)
                """,
                (
                    user_id,
                    current_revision_id,
                    target_revision_id,
                    target_revision_id,
                    learner_reason,
                    _json([evidence_id]),
                    _json([evidence_hash]),
                    changed_at,
                ),
            )
            return target_revision_id

    def record_objective_memory_from_effect(
        self,
        *,
        run: TutorRunSnapshot,
        proposal: TutorEffectProposal,
        request: TutorObjectiveMemoryRecordProposalV1,
        now: datetime | None = None,
    ) -> str:
        return self._insert_objective_memory(
            user_id=run.user_id,
            category=request.category,
            statement=request.fact,
            evidence_ids=request.evidence_ids,
            evidence_hashes=request.evidence_hashes,
            policy_version=request.policy_version,
            provenance_kind="effect",
            source_run_id=run.run_id,
            source_effect_record_id=self._proposed_effect_id(run=run, proposal=proposal),
            replaced_entry_id=None,
            created_at=_utc(now),
        )

    def record_activity_from_effect(
        self,
        *,
        run: TutorRunSnapshot,
        proposal: TutorEffectProposal,
        request: TutorActivityRecordProposalV1,
        now: datetime | None = None,
    ) -> str:
        created_at = _utc(now)
        activity_id = str(uuid4())
        effect_record_id = self._proposed_effect_id(run=run, proposal=proposal)
        content_hash = _hash(
            {
                "category": request.category,
                "reason": request.reason,
                "evidence_ids": list(request.evidence_ids),
                "evidence_hashes": list(request.evidence_hashes),
                "inbox_message": request.inbox_message,
            }
        )
        self._conn.execute(
            """
            INSERT INTO tutor_activity_records (
              id, user_id, source_run_id, source_effect_record_id, category, learner_reason,
              evidence_ids_json, evidence_hashes_json, policy_version, content_hash, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s)
            """,
            (
                activity_id,
                run.user_id,
                run.run_id,
                effect_record_id,
                request.category,
                request.reason,
                _json(list(request.evidence_ids)),
                _json(list(request.evidence_hashes)),
                request.policy_version,
                content_hash,
                created_at,
            ),
        )
        if request.inbox_message is not None:
            self._conn.execute(
                """
                INSERT INTO tutor_inbox_items (user_id, activity_id, message, state, created_at, updated_at)
                VALUES (%s, %s, %s, 'unread', %s, %s)
                """,
                (run.user_id, activity_id, request.inbox_message, created_at, created_at),
            )
        return activity_id
    def memory_preference_for_user(self, *, user_id: str) -> TutorMemoryPreference:
        row = self._conn.execute(
            """
            SELECT user_id::text AS user_id, inferred_memory_enabled, setting_version, version
            FROM tutor_memory_preferences
            WHERE user_id = %s
            """,
            (user_id,),
        ).fetchone()
        if row is None:
            return TutorMemoryPreference(
                user_id=user_id,
                inferred_memory_enabled=False,
                setting_version="memory_settings_v1",
                version=1,
            )
        return _memory_preference_from_row(row)

    def set_inferred_memory_preference(
        self,
        *,
        user_id: str,
        enabled: bool,
        expected_setting_version: str | None = None,
        now: datetime | None = None,
    ) -> TutorMemoryPreference:
        changed_at = _utc(now)
        with self._conn.transaction():
            self._lock_user(user_id)
            row = self._conn.execute(
                """
                SELECT user_id::text AS user_id, inferred_memory_enabled, setting_version, version
                FROM tutor_memory_preferences
                WHERE user_id = %s
                FOR UPDATE
                """,
                (user_id,),
            ).fetchone()
            if row is None:
                if expected_setting_version not in {None, "memory_settings_v1"}:
                    raise TutorLearnerStateConflict("memory_setting_version_conflict")
                inserted = self._conn.execute(
                    """
                    INSERT INTO tutor_memory_preferences (
                      user_id, inferred_memory_enabled, setting_version, version, created_at, updated_at
                    )
                    VALUES (%s, %s, 'memory_settings_v1', 1, %s, %s)
                    RETURNING user_id::text AS user_id, inferred_memory_enabled, setting_version, version
                    """,
                    (user_id, enabled, changed_at, changed_at),
                ).fetchone()
                if inserted is None:
                    raise RuntimeError("memory preference insert failed")
                return _memory_preference_from_row(inserted)
            current = _memory_preference_from_row(row)
            if expected_setting_version is not None and expected_setting_version != current.setting_version:
                raise TutorLearnerStateConflict("memory_setting_version_conflict")
            if current.inferred_memory_enabled == enabled:
                return current
            next_version = current.version + 1
            next_setting_version = f"memory_settings_v{next_version}"
            updated = self._conn.execute(
                """
                UPDATE tutor_memory_preferences
                SET inferred_memory_enabled = %s, setting_version = %s, version = %s, updated_at = %s
                WHERE user_id = %s
                RETURNING user_id::text AS user_id, inferred_memory_enabled, setting_version, version
                """,
                (enabled, next_setting_version, next_version, changed_at, user_id),
            ).fetchone()
            if updated is None:
                raise RuntimeError("memory preference update failed")
            return _memory_preference_from_row(updated)

    def record_objective_fact(
        self,
        *,
        user_id: str,
        category: str,
        statement: str,
        evidence_ids: Sequence[str],
        evidence_hashes: Sequence[str],
        policy_version: str | None = None,
        provenance_kind: Literal["learner_control", "trusted_service"] = "trusted_service",
        replaced_entry_id: str | None = None,
        now: datetime | None = None,
    ) -> str:
        created_at = _utc(now)
        with self._conn.transaction():
            self._lock_user(user_id)
            return self._insert_objective_memory(
                user_id=user_id,
                category=_identifier(category, label="memory category"),
                statement=_learner_text(statement, label="memory statement", maximum=180),
                evidence_ids=_evidence_ids(evidence_ids),
                evidence_hashes=_evidence_hashes(evidence_hashes),
                policy_version=_optional_identifier(policy_version, label="memory policy version"),
                provenance_kind=provenance_kind,
                source_run_id=None,
                source_effect_record_id=None,
                replaced_entry_id=replaced_entry_id,
                created_at=created_at,
            )

    def correct_memory_entry(
        self,
        *,
        user_id: str,
        entry_id: str,
        statement: str,
        evidence_ids: Sequence[str],
        evidence_hashes: Sequence[str],
        now: datetime | None = None,
    ) -> str:
        corrected_at = _utc(now)
        with self._conn.transaction():
            entry = self._conn.execute(
                """
                SELECT id::text AS id, category, state
                FROM tutor_memory_entries
                WHERE id = %s AND user_id = %s
                FOR UPDATE
                """,
                (entry_id, user_id),
            ).fetchone()
            if entry is None:
                raise TutorLearnerStateNotFound("memory_entry_not_found")
            if str(entry["state"]) != "active":
                raise TutorLearnerStateConflict("memory_entry_not_active")
            self._conn.execute(
                "UPDATE tutor_memory_entries SET state = 'corrected', updated_at = %s WHERE id = %s AND user_id = %s",
                (corrected_at, entry_id, user_id),
            )
            return self._insert_objective_memory(
                user_id=user_id,
                category=_identifier(str(entry["category"]), label="memory category"),
                statement=_learner_text(statement, label="corrected memory statement", maximum=180),
                evidence_ids=_evidence_ids(evidence_ids),
                evidence_hashes=_evidence_hashes(evidence_hashes),
                policy_version=None,
                provenance_kind="learner_control",
                source_run_id=None,
                source_effect_record_id=None,
                replaced_entry_id=entry_id,
                created_at=corrected_at,
            )

    def delete_memory_entry(self, *, user_id: str, entry_id: str, now: datetime | None = None) -> None:
        deleted_at = _utc(now)
        with self._conn.transaction():
            row = self._conn.execute(
                """
                UPDATE tutor_memory_entries
                SET state = 'deleted', deleted_at = %s, updated_at = %s
                WHERE id = %s AND user_id = %s AND state = 'active'
                RETURNING id
                """,
                (deleted_at, deleted_at, entry_id, user_id),
            ).fetchone()
            if row is None:
                found = self._conn.execute(
                    "SELECT id FROM tutor_memory_entries WHERE id = %s AND user_id = %s",
                    (entry_id, user_id),
                ).fetchone()
                if found is None:
                    raise TutorLearnerStateNotFound("memory_entry_not_found")
                raise TutorLearnerStateConflict("memory_entry_not_active")

    def curation_source_for_job(
        self,
        *,
        job_id: str,
        user_id: str,
        lease_owner_id: str,
        lease_generation: int,
        now: datetime,
    ) -> tuple[TutorCurationSource | None, str]:
        row = self._conn.execute(
            """
            SELECT
              jobs.id::text AS job_id,
              jobs.outbox_id::text AS outbox_id,
              jobs.user_id::text AS user_id,
              jobs.policy_version AS job_policy_version,
              jobs.memory_setting_version AS job_memory_setting_version,
              jobs.state AS job_state,
              jobs.lease_owner_id,
              jobs.lease_generation,
              jobs.lease_expires_at,
              outbox.run_id::text AS run_id,
              outbox.state AS outbox_state,
              outbox.policy_version AS outbox_policy_version,
              outbox.memory_setting_version AS outbox_memory_setting_version,
              outbox.input_revision AS outbox_input_revision,
              outbox.retention_until,
              outbox.stale_after,
              outbox.envelope_json,
              outbox.source_ids_json,
              outbox.source_hashes_json,
              runs.input_revision AS run_input_revision,
              preferences.inferred_memory_enabled,
              preferences.setting_version AS preference_setting_version
            FROM tutor_curation_jobs AS jobs
            JOIN tutor_memory_curation_outbox AS outbox ON outbox.id = jobs.outbox_id
            JOIN tutor_runs AS runs ON runs.id = outbox.run_id
            LEFT JOIN tutor_memory_preferences AS preferences ON preferences.user_id = jobs.user_id
            WHERE jobs.id = %s AND jobs.user_id = %s
            """,
            (job_id, user_id),
        ).fetchone()
        if row is None:
            return None, "curation_job_not_found"
        lease_expires_at = _as_datetime(row.get("lease_expires_at"))
        if (
            str(row["job_state"]) != "leased"
            or str(row.get("lease_owner_id") or "") != lease_owner_id
            or _as_int(row.get("lease_generation"), 0) != lease_generation
            or lease_expires_at is None
            or lease_expires_at <= now
        ):
            return None, "curation_job_lease_stale"
        if str(row["outbox_state"]) != "pending":
            return None, "outbox_not_pending"
        stale_after = _as_datetime(row.get("stale_after"))
        retention_until = _as_datetime(row.get("retention_until"))
        if stale_after is None or retention_until is None or stale_after <= now:
            return None, "outbox_stale"
        if str(row["job_policy_version"]) != str(row["outbox_policy_version"]):
            return None, "outbox_policy_version_stale"
        if str(row["job_memory_setting_version"]) != str(row["outbox_memory_setting_version"]):
            return None, "outbox_memory_setting_stale"
        if _as_int(row.get("outbox_input_revision"), -1) != _as_int(row.get("run_input_revision"), -1):
            return None, "outbox_source_revision_stale"
        if not bool(row.get("inferred_memory_enabled")):
            return None, "memory_preference_disabled"
        if str(row.get("preference_setting_version") or "") != str(row["outbox_memory_setting_version"]):
            return None, "memory_setting_version_stale"
        return (
            TutorCurationSource(
                job_id=str(row["job_id"]),
                outbox_id=str(row["outbox_id"]),
                run_id=str(row["run_id"]),
                user_id=str(row["user_id"]),
                lease_owner_id=str(row["lease_owner_id"]),
                lease_generation=_as_int(row["lease_generation"], 0),
                policy_version=str(row["outbox_policy_version"]),
                memory_setting_version=str(row["outbox_memory_setting_version"]),
                envelope=_mapping(row.get("envelope_json")),
                source_ids=_string_tuple(row.get("source_ids_json")),
                source_hashes=_string_tuple(row.get("source_hashes_json")),
                retention_until=retention_until,
                stale_after=stale_after,
            ),
            "eligible",
        )

    def commit_context_summary_projection(
        self,
        *,
        source: TutorCurationSource,
        proposal_id: str,
        summary: str,
        code: str,
        now: datetime | None = None,
    ) -> TutorCurationProjectionReceipt:
        created_at = _utc(now)
        safe_summary = _learner_text(summary, label="context summary", maximum=280)
        self._assert_curation_proposal_scope(source=source, proposal_id=proposal_id, now=created_at)
        content_hash = _hash({"summary": safe_summary, "proposal_id": proposal_id})
        existing = self._conn.execute(
            "SELECT id::text AS id, content_hash FROM tutor_context_summaries WHERE proposal_id = %s",
            (proposal_id,),
        ).fetchone()
        if existing is None:
            row = self._conn.execute(
                """
                INSERT INTO tutor_context_summaries (
                  user_id, run_id, outbox_id, proposal_id, summary, policy_version,
                  memory_setting_version, retention_until, stale_after, content_hash, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id::text AS id
                """,
                (
                    source.user_id,
                    source.run_id,
                    source.outbox_id,
                    proposal_id,
                    safe_summary,
                    source.policy_version,
                    source.memory_setting_version,
                    source.retention_until,
                    source.stale_after,
                    content_hash,
                    created_at,
                ),
            ).fetchone()
            if row is None:
                raise RuntimeError("context summary insert failed")
            target_id = str(row["id"])
        else:
            if str(existing["content_hash"]) != content_hash:
                raise TutorLearnerStateConflict("context_summary_identity_conflict")
            target_id = str(existing["id"])
        return self.record_curation_projection_receipt(
            source=source,
            proposal_id=proposal_id,
            state="committed",
            target_kind="context_summary",
            target_id=target_id,
            code=code,
            now=created_at,
        )

    def commit_inference_memory_projection(
        self,
        *,
        source: TutorCurationSource,
        proposal_id: str,
        category: str,
        statement: str,
        confidence: Literal["low", "medium", "high"],
        code: str,
        now: datetime | None = None,
    ) -> TutorCurationProjectionReceipt:
        created_at = _utc(now)
        safe_category = _identifier(category, label="inferred memory category")
        safe_statement = _learner_text(statement, label="inferred memory statement", maximum=180)
        self._assert_curation_proposal_scope(source=source, proposal_id=proposal_id, now=created_at)
        content_hash = _hash(
            {
                "category": safe_category,
                "statement": safe_statement,
                "confidence": confidence,
                "proposal_id": proposal_id,
            }
        )
        existing = self._conn.execute(
            "SELECT id::text AS id, content_hash FROM tutor_memory_entries WHERE source_proposal_id = %s",
            (proposal_id,),
        ).fetchone()
        if existing is None:
            row = self._conn.execute(
                """
                INSERT INTO tutor_memory_entries (
                  user_id, memory_kind, state, category, statement, confidence, provenance_kind,
                  source_run_id, source_effect_record_id, source_outbox_id, source_proposal_id,
                  replaced_entry_id, evidence_ids_json, evidence_hashes_json, policy_version,
                  memory_setting_version, retention_until, stale_after, content_hash, created_at, updated_at
                )
                VALUES (%s, 'inference', 'active', %s, %s, %s, 'curator', %s, NULL, %s, %s,
                        NULL, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id::text AS id
                """,
                (
                    source.user_id,
                    safe_category,
                    safe_statement,
                    confidence,
                    source.run_id,
                    source.outbox_id,
                    proposal_id,
                    _json(list(source.source_ids)),
                    _json(list(source.source_hashes)),
                    source.policy_version,
                    source.memory_setting_version,
                    source.retention_until,
                    source.stale_after,
                    content_hash,
                    created_at,
                    created_at,
                ),
            ).fetchone()
            if row is None:
                raise RuntimeError("inferred memory insert failed")
            target_id = str(row["id"])
        else:
            if str(existing["content_hash"]) != content_hash:
                raise TutorLearnerStateConflict("inferred_memory_identity_conflict")
            target_id = str(existing["id"])
        return self.record_curation_projection_receipt(
            source=source,
            proposal_id=proposal_id,
            state="committed",
            target_kind="memory_entry",
            target_id=target_id,
            code=code,
            now=created_at,
        )

    def record_curation_projection_receipt(
        self,
        *,
        source: TutorCurationSource,
        proposal_id: str,
        state: CurationReceiptState,
        target_kind: CurationTargetKind,
        target_id: str | None,
        code: str,
        now: datetime | None = None,
    ) -> TutorCurationProjectionReceipt:
        if state == "committed":
            if target_kind == "none" or target_id is None:
                raise ValueError("committed curation receipt requires a target")
        elif target_kind != "none" or target_id is not None:
            raise ValueError("non-committed curation receipt cannot retain a target")
        stable_code = _identifier(code, label="curation receipt code")
        created_at = _utc(now)
        self._assert_curation_proposal_scope(
            source=source,
            proposal_id=proposal_id,
            allowed_proposal_states=(("pending",) if state == "committed" else (state,)),
            now=created_at,
        )
        existing = self._conn.execute(
            """
            SELECT id::text AS id, state, target_kind, target_id::text AS target_id, code
            FROM tutor_curation_projection_receipts
            WHERE proposal_id = %s
            """,
            (proposal_id,),
        ).fetchone()
        if existing is not None:
            if (
                str(existing["state"]) != state
                or str(existing["target_kind"]) != target_kind
                or _optional_text(existing, "target_id") != target_id
                or str(existing["code"]) != stable_code
            ):
                raise TutorLearnerStateConflict("curation_projection_receipt_conflict")
            return _curation_receipt_from_row(existing, proposal_id=proposal_id)
        row = self._conn.execute(
            """
            INSERT INTO tutor_curation_projection_receipts (
              user_id, run_id, outbox_id, proposal_id, state, target_kind, target_id, code, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id::text AS id, state, target_kind, target_id::text AS target_id, code
            """,
            (
                source.user_id,
                source.run_id,
                source.outbox_id,
                proposal_id,
                state,
                target_kind,
                target_id,
                stable_code,
                created_at,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("curation projection receipt insert failed")
        return _curation_receipt_from_row(row, proposal_id=proposal_id)
    def active_plan_for_user(self, *, user_id: str) -> TutorPlanRevision | None:
        row = self._conn.execute(
            """
            SELECT revisions.id::text AS id, revisions.user_id::text AS user_id,
                   revisions.predecessor_revision_id::text AS predecessor_revision_id,
                    revisions.title, revisions.outline_json, revisions.diff_json,
                    revisions.learner_reason, revisions.evidence_ids_json,
                    revisions.evidence_hashes_json, revisions.policy_version, revisions.created_at
            FROM tutor_active_plans AS active
            JOIN tutor_plan_revisions AS revisions
              ON revisions.id = active.revision_id AND revisions.user_id = active.user_id
            WHERE active.user_id = %s
            """,
            (user_id,),
        ).fetchone()
        return _plan_revision_from_row(row) if row is not None else None

    def list_plan_revisions(self, *, user_id: str, limit: int = 50) -> tuple[TutorPlanRevision, ...]:
        if limit < 1 or limit > 100:
            raise ValueError("plan revision list limit must be within 1..100")
        rows = self._conn.execute(
            """
            SELECT id::text AS id, user_id::text AS user_id,
                   predecessor_revision_id::text AS predecessor_revision_id,
                   title, outline_json, diff_json, learner_reason,
                   evidence_ids_json, evidence_hashes_json, policy_version, created_at
            FROM tutor_plan_revisions
            WHERE user_id = %s
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            (user_id, limit),
        ).fetchall()
        return tuple(_plan_revision_from_row(row) for row in rows)

    def list_memory_entries(
        self,
        *,
        user_id: str,
        include_inactive: bool = False,
        limit: int = 50,
    ) -> tuple[TutorMemoryEntry, ...]:
        if limit < 1 or limit > 100:
            raise ValueError("memory list limit must be within 1..100")
        rows = self._conn.execute(
            """
            SELECT id::text AS id, user_id::text AS user_id, memory_kind, state, category,
                   statement, confidence, provenance_kind, replaced_entry_id::text AS replaced_entry_id,
                   policy_version, memory_setting_version, evidence_ids_json, evidence_hashes_json,
                   retention_until, stale_after, created_at
            FROM tutor_memory_entries
            WHERE user_id = %s AND (%s OR state = 'active')
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            (user_id, include_inactive, limit),
        ).fetchall()
        return tuple(_memory_entry_from_row(row) for row in rows)

    def memory_entry_for_user(self, *, user_id: str, entry_id: str) -> TutorMemoryEntry:
        row = self._conn.execute(
            """
            SELECT id::text AS id, user_id::text AS user_id, memory_kind, state, category,
                   statement, confidence, provenance_kind, replaced_entry_id::text AS replaced_entry_id,
                   policy_version, memory_setting_version, evidence_ids_json, evidence_hashes_json,
                   retention_until, stale_after, created_at
            FROM tutor_memory_entries
            WHERE user_id = %s AND id = %s
            """,
            (user_id, entry_id),
        ).fetchone()
        if row is None:
            raise TutorLearnerStateNotFound("memory_entry_not_found")
        return _memory_entry_from_row(row)

    def list_activity_records(self, *, user_id: str, limit: int = 50) -> tuple[TutorActivityRecord, ...]:
        if limit < 1 or limit > 100:
            raise ValueError("activity list limit must be within 1..100")
        rows = self._conn.execute(
            """
            SELECT id::text AS id, user_id::text AS user_id, category, learner_reason,
                   evidence_ids_json, evidence_hashes_json, created_at
            FROM tutor_activity_records
            WHERE user_id = %s
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            (user_id, limit),
        ).fetchall()
        return tuple(_activity_from_row(row) for row in rows)

    def list_inbox_items(
        self,
        *,
        user_id: str,
        include_dismissed: bool = False,
        limit: int = 50,
    ) -> tuple[TutorInboxItem, ...]:
        if limit < 1 or limit > 100:
            raise ValueError("inbox list limit must be within 1..100")
        rows = self._conn.execute(
            """
            SELECT id::text AS id, user_id::text AS user_id, activity_id::text AS activity_id,
                   message, state, read_at, dismissed_at, created_at
            FROM tutor_inbox_items
            WHERE user_id = %s AND (%s OR state <> 'dismissed')
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            (user_id, include_dismissed, limit),
        ).fetchall()
        return tuple(_inbox_from_row(row) for row in rows)

    def mark_inbox_read(self, *, user_id: str, inbox_id: str, now: datetime | None = None) -> TutorInboxItem:
        changed_at = _utc(now)
        with self._conn.transaction():
            row = self._conn.execute(
                """
                UPDATE tutor_inbox_items
                SET state = 'read', read_at = %s, updated_at = %s
                WHERE id = %s AND user_id = %s AND state = 'unread'
                RETURNING id::text AS id, user_id::text AS user_id, activity_id::text AS activity_id,
                          message, state, read_at, dismissed_at, created_at
                """,
                (changed_at, changed_at, inbox_id, user_id),
            ).fetchone()
            if row is None:
                found = self._conn.execute(
                    "SELECT id FROM tutor_inbox_items WHERE id = %s AND user_id = %s",
                    (inbox_id, user_id),
                ).fetchone()
                if found is None:
                    raise TutorLearnerStateNotFound("inbox_item_not_found")
                raise TutorLearnerStateConflict("inbox_item_not_unread")
            return _inbox_from_row(row)

    def dismiss_inbox_item(self, *, user_id: str, inbox_id: str, now: datetime | None = None) -> TutorInboxItem:
        changed_at = _utc(now)
        with self._conn.transaction():
            row = self._conn.execute(
                """
                UPDATE tutor_inbox_items
                SET state = 'dismissed', dismissed_at = %s, updated_at = %s
                WHERE id = %s AND user_id = %s AND state = 'unread'
                RETURNING id::text AS id, user_id::text AS user_id, activity_id::text AS activity_id,
                          message, state, read_at, dismissed_at, created_at
                """,
                (changed_at, changed_at, inbox_id, user_id),
            ).fetchone()
            if row is None:
                found = self._conn.execute(
                    "SELECT id FROM tutor_inbox_items WHERE id = %s AND user_id = %s",
                    (inbox_id, user_id),
                ).fetchone()
                if found is None:
                    raise TutorLearnerStateNotFound("inbox_item_not_found")
                raise TutorLearnerStateConflict("inbox_item_not_unread")
            return _inbox_from_row(row)

    def _insert_objective_memory(
        self,
        *,
        user_id: str,
        category: str,
        statement: str,
        evidence_ids: Sequence[str],
        evidence_hashes: Sequence[str],
        policy_version: str | None,
        provenance_kind: Literal["effect", "learner_control", "trusted_service"],
        source_run_id: str | None,
        source_effect_record_id: str | None,
        replaced_entry_id: str | None,
        created_at: datetime,
    ) -> str:
        normalized_ids = _evidence_ids(evidence_ids)
        normalized_hashes = _evidence_hashes(evidence_hashes)
        _validate_evidence_pair(normalized_ids, normalized_hashes)
        entry_id = str(uuid4())
        content_hash = _hash(
            {
                "category": category,
                "statement": statement,
                "evidence_ids": list(normalized_ids),
                "evidence_hashes": list(normalized_hashes),
                "policy_version": policy_version,
                "provenance_kind": provenance_kind,
                "replaced_entry_id": replaced_entry_id,
            }
        )
        row = self._conn.execute(
            """
            INSERT INTO tutor_memory_entries (
              id, user_id, memory_kind, state, category, statement, confidence, provenance_kind,
              source_run_id, source_effect_record_id, source_outbox_id, source_proposal_id,
              replaced_entry_id, evidence_ids_json, evidence_hashes_json, policy_version,
              memory_setting_version, retention_until, stale_after, content_hash, created_at, updated_at
            )
            VALUES (%s, %s, 'objective_fact', 'active', %s, %s, NULL, %s, %s, %s, NULL, NULL,
                    %s, %s::jsonb, %s::jsonb, %s, NULL, NULL, NULL, %s, %s, %s)
            RETURNING id::text AS id
            """,
            (
                entry_id,
                user_id,
                category,
                statement,
                provenance_kind,
                source_run_id,
                source_effect_record_id,
                replaced_entry_id,
                _json(list(normalized_ids)),
                _json(list(normalized_hashes)),
                policy_version,
                content_hash,
                created_at,
                created_at,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("objective memory insert failed")
        return str(row["id"])

    def _lock_user(self, user_id: str) -> None:
        row = self._conn.execute("SELECT id FROM users WHERE id = %s FOR UPDATE", (user_id,)).fetchone()
        if row is None:
            raise TutorLearnerStateNotFound("learner_user_not_found")

    def _proposed_effect_id(self, *, run: TutorRunSnapshot, proposal: TutorEffectProposal) -> str:
        row = self._conn.execute(
            """
            SELECT id::text AS id
            FROM tutor_effects
            WHERE run_id = %s AND effect_id = %s AND effect_type = %s AND status = 'proposed'
            FOR UPDATE
            """,
            (run.run_id, proposal.effect_id, proposal.effect_type),
        ).fetchone()
        if row is None:
            raise TutorLearnerStateConflict("effect_reservation_missing")
        return str(row["id"])

    def _assert_curation_proposal_scope(
        self,
        *,
        source: TutorCurationSource,
        proposal_id: str,
        now: datetime,
        allowed_proposal_states: Sequence[str] = ("pending",),
    ) -> None:
        row = self._conn.execute(
            """
            SELECT
              proposals.id::text AS proposal_id,
              proposals.state AS proposal_state,
              proposals.policy_version AS proposal_policy_version,
              proposals.memory_setting_version AS proposal_memory_setting_version,
              outbox.state AS outbox_state,
              outbox.input_revision AS outbox_input_revision,
              outbox.stale_after,
              runs.input_revision AS run_input_revision,
              preferences.inferred_memory_enabled,
              preferences.setting_version AS preference_setting_version,
              jobs.state AS job_state,
              jobs.lease_owner_id,
              jobs.lease_generation,
              jobs.lease_expires_at
            FROM tutor_curation_proposals AS proposals
            JOIN tutor_memory_curation_outbox AS outbox
              ON outbox.id = proposals.outbox_id
            JOIN tutor_runs AS runs ON runs.id = outbox.run_id
            JOIN tutor_curation_jobs AS jobs ON jobs.outbox_id = outbox.id
            LEFT JOIN tutor_memory_preferences AS preferences ON preferences.user_id = runs.user_id
            WHERE proposals.id = %s
              AND proposals.outbox_id = %s
              AND outbox.run_id = %s
              AND runs.user_id = %s
            FOR UPDATE OF proposals, outbox, runs
            """,
            (proposal_id, source.outbox_id, source.run_id, source.user_id),
        ).fetchone()
        if row is None:
            raise TutorLearnerStateConflict("curation_proposal_scope_stale")
        if str(row["proposal_state"]) not in set(allowed_proposal_states) or str(row["outbox_state"]) not in {
            "pending", "no_action", "stale", "failed"
        }:
            raise TutorLearnerStateConflict("curation_proposal_not_current")
        lease_expires_at = _as_datetime(row.get("lease_expires_at"))
        if (
            str(row["job_state"]) != "leased"
            or str(row.get("lease_owner_id") or "") != source.lease_owner_id
            or _as_int(row.get("lease_generation"), 0) != source.lease_generation
            or lease_expires_at is None
            or lease_expires_at <= now
        ):
            raise TutorLearnerStateConflict("curation_job_lease_stale")
        stale_after = _as_datetime(row.get("stale_after"))
        if (
            str(row["proposal_policy_version"]) != source.policy_version
            or str(row["proposal_memory_setting_version"]) != source.memory_setting_version
            or _as_int(row.get("outbox_input_revision"), -1) != _as_int(row.get("run_input_revision"), -1)
            or stale_after is None
            or stale_after <= now
            or not bool(row.get("inferred_memory_enabled"))
            or str(row.get("preference_setting_version") or "") != source.memory_setting_version
        ):
            raise TutorLearnerStateConflict("curation_source_stale")


class TutorLearnerStateEffectHandler:
    """Decode exact descriptor payloads and write only inside the effect CAS transaction."""

    def __init__(self, repository: TutorLearnerStateRepository) -> None:
        self._repository = repository

    def __call__(
        self,
        conn: Connection[dict[str, object]],
        run: TutorRunSnapshot,
        proposal: TutorEffectProposal,
    ) -> TutorEffectResult:
        payload = payload_mapping_from_fields(proposal.payload)
        if payload is None:
            return TutorEffectResult(effect_id=proposal.effect_id, status=TutorEffectStatus.DENIED)
        repository = self._repository.for_transaction(conn)
        try:
            if proposal.effect_type == TUTOR_PLAN_ACTIVATE_EFFECT_TYPE:
                commit_id = repository.activate_plan_from_effect(
                    run=run,
                    proposal=proposal,
                    request=TutorPlanActivateProposalV1.model_validate(payload),
                )
            elif proposal.effect_type == TUTOR_PLAN_ROLLBACK_EFFECT_TYPE:
                commit_id = repository.rollback_plan_from_effect(
                    run=run,
                    proposal=proposal,
                    request=TutorPlanRollbackProposalV1.model_validate(payload),
                )
            elif proposal.effect_type == TUTOR_MEMORY_RECORD_EFFECT_TYPE:
                commit_id = repository.record_objective_memory_from_effect(
                    run=run,
                    proposal=proposal,
                    request=TutorObjectiveMemoryRecordProposalV1.model_validate(payload),
                )
            elif proposal.effect_type == TUTOR_ACTIVITY_RECORD_EFFECT_TYPE:
                commit_id = repository.record_activity_from_effect(
                    run=run,
                    proposal=proposal,
                    request=TutorActivityRecordProposalV1.model_validate(payload),
                )
            else:
                return TutorEffectResult(effect_id=proposal.effect_id, status=TutorEffectStatus.DENIED)
        except (TutorLearnerStateError, ValidationError, ValueError, TypeError):
            return TutorEffectResult(effect_id=proposal.effect_id, status=TutorEffectStatus.DENIED)
        return TutorEffectResult(effect_id=proposal.effect_id, status=TutorEffectStatus.COMMITTED, commit_id=commit_id)


def build_learner_state_effect_handlers(
    repository: TutorLearnerStateRepository,
) -> dict[str, TutorLearnerStateEffectHandler]:
    """Compose the four reviewed Child 05 handlers without enabling product traffic."""

    handler = TutorLearnerStateEffectHandler(repository)
    return {
        TUTOR_PLAN_ACTIVATE_EFFECT_TYPE: handler,
        TUTOR_PLAN_ROLLBACK_EFFECT_TYPE: handler,
        TUTOR_MEMORY_RECORD_EFFECT_TYPE: handler,
        TUTOR_ACTIVITY_RECORD_EFFECT_TYPE: handler,
    }


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(UTC)
    return current.replace(tzinfo=UTC) if current.tzinfo is None else current.astimezone(UTC)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: object) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _identifier(value: object, *, label: str) -> str:
    normalized = str(value or "").strip()
    if not _SAFE_IDENTIFIER.fullmatch(normalized):
        raise ValueError(f"{label} must be a stable bounded identifier")
    return normalized


def _optional_identifier(value: object, *, label: str) -> str | None:
    return None if value is None else _identifier(value, label=label)


def _learner_text(value: object, *, label: str, maximum: int) -> str:
    normalized = " ".join(str(value or "").split())
    if not normalized or len(normalized) > maximum or contains_forbidden_execution_target(normalized):
        raise ValueError(f"{label} must be bounded learner-safe text")
    return normalized


def _evidence_ids(values: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(_identifier(value, label="evidence id") for value in values)
    if not 1 <= len(normalized) <= 4 or len(set(normalized)) != len(normalized):
        raise ValueError("evidence ids must contain one to four unique values")
    return normalized


def _evidence_hashes(values: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(str(value).lower() for value in values)
    if (
        not 1 <= len(normalized) <= 4
        or len(set(normalized)) != len(normalized)
        or any(not _SHA256.fullmatch(value) for value in normalized)
    ):
        raise ValueError("evidence hashes must contain one to four unique SHA-256 values")
    return normalized


def _validate_evidence_pair(ids: Sequence[str], hashes: Sequence[str]) -> None:
    if len(ids) != len(hashes):
        raise ValueError("evidence ids and hashes must have equal lengths")


def _mapping(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return _mapping(decoded)
    return {}


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str))


def _mapping_tuple(value: object) -> tuple[dict[str, object], ...]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(dict(item) for item in value if isinstance(item, Mapping))


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return _utc(value)
    if isinstance(value, str):
        try:
            return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _as_int(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _optional_text(row: Mapping[str, object] | None, key: str) -> str | None:
    if row is None or row.get(key) is None:
        return None
    return str(row[key])


def _memory_preference_from_row(row: Mapping[str, object]) -> TutorMemoryPreference:
    return TutorMemoryPreference(
        user_id=str(row["user_id"]),
        inferred_memory_enabled=bool(row["inferred_memory_enabled"]),
        setting_version=str(row["setting_version"]),
        version=_as_int(row["version"], 1),
    )


def _plan_revision_from_row(row: Mapping[str, object]) -> TutorPlanRevision:
    return TutorPlanRevision(
        revision_id=str(row["id"]),
        user_id=str(row["user_id"]),
        predecessor_revision_id=_optional_text(row, "predecessor_revision_id"),
        title=str(row["title"]),
        outline=_string_tuple(row.get("outline_json")),
        learner_reason=str(row["learner_reason"]),
        policy_version=str(row["policy_version"]),
        created_at=_as_datetime(row["created_at"]) or datetime.now(UTC),
        diff=_mapping_tuple(row.get("diff_json")),
        evidence_ids=_string_tuple(row.get("evidence_ids_json")),
        evidence_hashes=_string_tuple(row.get("evidence_hashes_json")),
    )


def _memory_entry_from_row(row: Mapping[str, object]) -> TutorMemoryEntry:
    kind = str(row["memory_kind"])
    state = str(row["state"])
    if kind not in {"objective_fact", "inference"} or state not in {"active", "corrected", "deleted", "expired"}:
        raise TutorLearnerStateConflict("stored_memory_entry_invalid")
    return TutorMemoryEntry(
        entry_id=str(row["id"]),
        user_id=str(row["user_id"]),
        memory_kind=kind,  # type: ignore[arg-type]
        state=state,  # type: ignore[arg-type]
        category=str(row["category"]),
        statement=str(row["statement"]),
        confidence=_optional_text(row, "confidence"),
        provenance_kind=str(row["provenance_kind"]),
        replaced_entry_id=_optional_text(row, "replaced_entry_id"),
        policy_version=_optional_text(row, "policy_version"),
        memory_setting_version=_optional_text(row, "memory_setting_version"),
        retention_until=_as_datetime(row.get("retention_until")),
        stale_after=_as_datetime(row.get("stale_after")),
        created_at=_as_datetime(row["created_at"]) or datetime.now(UTC),
        evidence_ids=_string_tuple(row.get("evidence_ids_json")),
        evidence_hashes=_string_tuple(row.get("evidence_hashes_json")),
    )


def _activity_from_row(row: Mapping[str, object]) -> TutorActivityRecord:
    return TutorActivityRecord(
        activity_id=str(row["id"]),
        user_id=str(row["user_id"]),
        category=str(row["category"]),
        learner_reason=str(row["learner_reason"]),
        created_at=_as_datetime(row["created_at"]) or datetime.now(UTC),
        evidence_ids=_string_tuple(row.get("evidence_ids_json")),
        evidence_hashes=_string_tuple(row.get("evidence_hashes_json")),
    )


def _inbox_from_row(row: Mapping[str, object]) -> TutorInboxItem:
    state = str(row["state"])
    if state not in {"unread", "read", "dismissed"}:
        raise TutorLearnerStateConflict("stored_inbox_item_invalid")
    return TutorInboxItem(
        inbox_id=str(row["id"]),
        user_id=str(row["user_id"]),
        activity_id=str(row["activity_id"]),
        message=str(row["message"]),
        state=state,  # type: ignore[arg-type]
        read_at=_as_datetime(row.get("read_at")),
        dismissed_at=_as_datetime(row.get("dismissed_at")),
        created_at=_as_datetime(row["created_at"]) or datetime.now(UTC),
    )


def _curation_receipt_from_row(
    row: Mapping[str, object],
    *,
    proposal_id: str,
) -> TutorCurationProjectionReceipt:
    state = str(row["state"])
    target_kind = str(row["target_kind"])
    if state not in {"committed", "no_action", "stale", "failed"} or target_kind not in {
        "context_summary",
        "memory_entry",
        "none",
    }:
        raise TutorLearnerStateConflict("stored_curation_receipt_invalid")
    return TutorCurationProjectionReceipt(
        receipt_id=str(row["id"]),
        proposal_id=proposal_id,
        state=state,  # type: ignore[arg-type]
        target_kind=target_kind,  # type: ignore[arg-type]
        target_id=_optional_text(row, "target_id"),
        code=str(row["code"]),
    )
