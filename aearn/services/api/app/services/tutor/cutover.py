"""Server-authoritative one-time legacy-to-Tutor cutover gate.

This module deliberately does not reuse the ordinary local-user reset path.
The normal reset keeps learner preferences and uses compatibility cleanup; this
cutover is explicit, verified, and records only a safe receipt.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from psycopg import Connection

from app.db.connection import connect


CUTOVER_VERSION = "harness_clean_slate_v1"
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$")
_CHECKPOINT_TABLES = ("checkpoints", "checkpoint_blobs", "checkpoint_writes")
_LEGACY_PROFILE_FIELDS = (
    "learning_style",
    "teaching_preference",
    "encouragement_preference",
    "profession",
    "background_context",
)


class CutoverError(ValueError):
    """Stable learner-safe error used by status, confirmation, and gates."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        recoverable: bool = True,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.recoverable = recoverable
        self.details = dict(details or {})


class CutoverRuntimeBlocked(Exception):
    def __init__(self, error: CutoverError) -> None:
        super().__init__(error.message)
        self.error = error


@dataclass(frozen=True)
class CheckpointInventory:
    state: Literal["not_configured", "scoped", "unresolved"]
    table_counts: dict[str, int]
    configured_tables: tuple[str, ...]
    thread_ids: tuple[str, ...]


@dataclass(frozen=True)
class CutoverInventory:
    legacy_counts: dict[str, int]
    legacy_profile_fields: dict[str, bool]
    target_counts: dict[str, int]
    checkpoints: CheckpointInventory

    @property
    def has_legacy_data(self) -> bool:
        return any(self.legacy_counts.values()) or any(self.legacy_profile_fields.values())

    @property
    def has_target_state(self) -> bool:
        return any(self.target_counts.values())


_LEGACY_COUNT_SQL: tuple[tuple[str, str], ...] = (
    ("learning_plans", "SELECT count(*)::int AS count FROM learning_plans WHERE user_id = %s"),
    ("plan_modules", """SELECT count(*)::int AS count FROM plan_modules JOIN learning_plans ON learning_plans.id = plan_modules.plan_id WHERE learning_plans.user_id = %s"""),
    ("knowledge_points", """SELECT count(*)::int AS count FROM knowledge_points JOIN plan_modules ON plan_modules.id = knowledge_points.module_id JOIN learning_plans ON learning_plans.id = plan_modules.plan_id WHERE learning_plans.user_id = %s"""),
    ("exercises", """SELECT count(*)::int AS count FROM exercises JOIN knowledge_points ON knowledge_points.id = exercises.knowledge_point_id JOIN plan_modules ON plan_modules.id = knowledge_points.module_id JOIN learning_plans ON learning_plans.id = plan_modules.plan_id WHERE learning_plans.user_id = %s"""),
    ("code_blanks", """SELECT count(*)::int AS count FROM code_blanks JOIN exercises ON exercises.id = code_blanks.exercise_id JOIN knowledge_points ON knowledge_points.id = exercises.knowledge_point_id JOIN plan_modules ON plan_modules.id = knowledge_points.module_id JOIN learning_plans ON learning_plans.id = plan_modules.plan_id WHERE learning_plans.user_id = %s"""),
    ("test_cases", """SELECT count(*)::int AS count FROM test_cases JOIN exercises ON exercises.id = test_cases.exercise_id JOIN knowledge_points ON knowledge_points.id = exercises.knowledge_point_id JOIN plan_modules ON plan_modules.id = knowledge_points.module_id JOIN learning_plans ON learning_plans.id = plan_modules.plan_id WHERE learning_plans.user_id = %s"""),
    ("teaching_chunks", """SELECT count(*)::int AS count FROM teaching_chunks JOIN knowledge_points ON knowledge_points.id = teaching_chunks.knowledge_point_id JOIN plan_modules ON plan_modules.id = knowledge_points.module_id JOIN learning_plans ON learning_plans.id = plan_modules.plan_id WHERE learning_plans.user_id = %s"""),
    ("learning_sessions", "SELECT count(*)::int AS count FROM learning_sessions WHERE user_id = %s"),
    ("attempts", "SELECT count(*)::int AS count FROM attempts WHERE user_id = %s"),
    ("review_states", "SELECT count(*)::int AS count FROM review_states WHERE user_id = %s"),
    ("review_logs", "SELECT count(*)::int AS count FROM review_logs WHERE user_id = %s"),
    ("review_seed_banks", "SELECT count(*)::int AS count FROM review_seed_banks WHERE user_id = %s"),
    ("exercise_variant_cache", "SELECT count(*)::int AS count FROM exercise_variant_cache WHERE user_id = %s"),
    ("notes", "SELECT count(*)::int AS count FROM notes WHERE user_id = %s"),
    ("onboarding_conversations", "SELECT count(*)::int AS count FROM onboarding_conversations WHERE user_id = %s"),
    ("onboarding_messages", """SELECT count(*)::int AS count FROM onboarding_messages JOIN onboarding_conversations ON onboarding_conversations.id = onboarding_messages.conversation_id WHERE onboarding_conversations.user_id = %s"""),
    ("learning_messages", """SELECT count(*)::int AS count FROM learning_messages JOIN learning_sessions ON learning_sessions.id = learning_messages.session_id WHERE learning_sessions.user_id = %s"""),
    ("review_messages", """SELECT count(*)::int AS count FROM review_messages JOIN learning_sessions ON learning_sessions.id = review_messages.review_session_id WHERE learning_sessions.user_id = %s"""),
    ("learner_profiles", "SELECT count(*)::int AS count FROM learner_profiles WHERE user_id = %s"),
    ("idempotency_records", "SELECT count(*)::int AS count FROM idempotency_records WHERE user_id = %s"),
)

# The other Tutor rows are descendants of these user-scoped roots. Shared
# tutor_catalog_snapshots and tutor_executor_health intentionally stay out.
_TARGET_COUNT_SQL: tuple[tuple[str, str], ...] = (
    ("tutor_conversations", "SELECT count(*)::int AS count FROM tutor_conversations WHERE user_id = %s"),
    ("tutor_runs", "SELECT count(*)::int AS count FROM tutor_runs WHERE user_id = %s"),
    ("tutor_execution_intents", "SELECT count(*)::int AS count FROM tutor_execution_intents WHERE user_id = %s"),
    ("tutor_execution_jobs", "SELECT count(*)::int AS count FROM tutor_execution_jobs WHERE user_id = %s"),
    ("tutor_proactive_preferences", "SELECT count(*)::int AS count FROM tutor_proactive_preferences WHERE user_id = %s"),
    ("tutor_proactive_signals", "SELECT count(*)::int AS count FROM tutor_proactive_signals WHERE user_id = %s"),
    ("tutor_proactive_candidates", "SELECT count(*)::int AS count FROM tutor_proactive_candidates WHERE user_id = %s"),
    ("tutor_curation_jobs", "SELECT count(*)::int AS count FROM tutor_curation_jobs WHERE user_id = %s"),
    ("tutor_scheduler_audit", "SELECT count(*)::int AS count FROM tutor_scheduler_audit WHERE user_id = %s"),
    ("tutor_plan_revisions", "SELECT count(*)::int AS count FROM tutor_plan_revisions WHERE user_id = %s"),
    ("tutor_active_plans", "SELECT count(*)::int AS count FROM tutor_active_plans WHERE user_id = %s"),
    ("tutor_plan_revision_actions", "SELECT count(*)::int AS count FROM tutor_plan_revision_actions WHERE user_id = %s"),
    ("tutor_memory_preferences", "SELECT count(*)::int AS count FROM tutor_memory_preferences WHERE user_id = %s"),
    ("tutor_memory_entries", "SELECT count(*)::int AS count FROM tutor_memory_entries WHERE user_id = %s"),
    ("tutor_context_summaries", "SELECT count(*)::int AS count FROM tutor_context_summaries WHERE user_id = %s"),
    ("tutor_curation_projection_receipts", "SELECT count(*)::int AS count FROM tutor_curation_projection_receipts WHERE user_id = %s"),
    ("tutor_activity_records", "SELECT count(*)::int AS count FROM tutor_activity_records WHERE user_id = %s"),
    ("tutor_inbox_items", "SELECT count(*)::int AS count FROM tutor_inbox_items WHERE user_id = %s"),
    ("tutor_api_idempotency_records", "SELECT count(*)::int AS count FROM tutor_api_idempotency_records WHERE user_id = %s"),
    ("tutor_learning_tracks", "SELECT count(*)::int AS count FROM tutor_learning_tracks WHERE user_id = %s"),
    ("tutor_track_plan_revisions", "SELECT count(*)::int AS count FROM tutor_track_plan_revisions WHERE user_id = %s"),
    ("tutor_track_active_plans", "SELECT count(*)::int AS count FROM tutor_track_active_plans WHERE user_id = %s"),
    ("tutor_track_plan_modules", "SELECT count(*)::int AS count FROM tutor_track_plan_modules WHERE user_id = %s"),
    ("tutor_track_plan_nodes", "SELECT count(*)::int AS count FROM tutor_track_plan_nodes WHERE user_id = %s"),
    ("tutor_track_node_progress", "SELECT count(*)::int AS count FROM tutor_track_node_progress WHERE user_id = %s"),
    ("tutor_track_plan_migrations", "SELECT count(*)::int AS count FROM tutor_track_plan_migrations WHERE user_id = %s"),
    ("tutor_mastery_evidence", "SELECT count(*)::int AS count FROM tutor_mastery_evidence WHERE user_id = %s"),
    ("tutor_mastery_states", "SELECT count(*)::int AS count FROM tutor_mastery_states WHERE user_id = %s"),
    ("tutor_conversation_learning_scopes", "SELECT count(*)::int AS count FROM tutor_conversation_learning_scopes WHERE user_id = %s"),
    ("tutor_run_learning_scopes", "SELECT count(*)::int AS count FROM tutor_run_learning_scopes WHERE user_id = %s"),
)


class HarnessCutoverService:
    """Owns preview, confirmation, exact deletion, and the shared runtime gate."""

    def __init__(
        self,
        conn: Connection[dict[str, object]],
        *,
        failure_injector: Callable[[str], None] | None = None,
    ) -> None:
        self._conn = conn
        self._failure_injector = failure_injector

    def get_decision(self, *, user_id: str) -> dict[str, object]:
        normalized_user_id = _uuid_identifier(user_id)
        with self._conn.transaction():
            self._lock_active_user(normalized_user_id, for_update=True)
            record = self._ensure_record_locked(normalized_user_id)
            if str(record["state"]) == "verified":
                return self._verified_response(record, idempotent_replayed=False)
            inventory = self._inventory(normalized_user_id)
            summary = self._public_summary(inventory)
            if inventory.has_target_state:
                self._mark_blocked_locked(record, state="blocked_target_state", code="CUTOVER_TARGET_STATE_PRESENT")
                return self._blocked_response("blocked_target_state", "CUTOVER_TARGET_STATE_PRESENT", summary)
            if inventory.checkpoints.state == "unresolved":
                self._mark_blocked_locked(record, state="blocked_checkpoint_scope", code="CUTOVER_CHECKPOINT_SCOPE_UNRESOLVED")
                return self._blocked_response("blocked_checkpoint_scope", "CUTOVER_CHECKPOINT_SCOPE_UNRESOLVED", summary)
            summary_hash = _summary_hash(self._canonical_summary(normalized_user_id, inventory))
            if not inventory.has_legacy_data:
                self._mark_verified_locked(record, summary_hash=summary_hash, idempotency_key=None, request_hash=None)
                return self._verified_response(self._load_record_locked(normalized_user_id), idempotent_replayed=False)
            if (
                str(record["state"]) != "summary_ready"
                or str(record.get("summary_hash") or "") != summary_hash
                or not isinstance(record.get("preview_nonce"), str)
            ):
                self._refresh_preview_locked(record, summary_hash=summary_hash)
                record = self._load_record_locked(normalized_user_id)
            return {
                "cutover_version": CUTOVER_VERSION,
                "rollout_active": True,
                "state": "summary_ready",
                "summary_version": _int_or_zero(record["summary_version"]),
                "preview_nonce": str(record["preview_nonce"]),
                "summary_hash": str(record["summary_hash"]),
                "summary": summary,
                "next_action": "confirm_cutover",
            }


    def confirm(
        self,
        *,
        user_id: str,
        cutover_version: str,
        summary_version: int,
        preview_nonce: str,
        summary_hash: str,
        client_action_id: str,
        confirm: bool,
    ) -> dict[str, object]:
        normalized_user_id = _uuid_identifier(user_id)
        normalized_key = _idempotency_key(client_action_id)
        if cutover_version != CUTOVER_VERSION:
            raise CutoverError(
                "CUTOVER_SUMMARY_STALE",
                "切换预览版本已更新，请重新获取数据摘要。",
                status_code=409,
                details={"cutover_version": CUTOVER_VERSION},
            )
        if not confirm:
            raise CutoverError(
                "CUTOVER_CONFIRMATION_REQUIRED",
                "清理旧学习记录需要明确确认。",
                status_code=400,
                recoverable=False,
                details={"field": "confirm"},
            )
        request_hash = _summary_hash(
            {
                "user_id": normalized_user_id,
                "cutover_version": cutover_version,
                "summary_version": summary_version,
                "preview_nonce": preview_nonce,
                "summary_hash": summary_hash,
                "client_action_id": normalized_key,
                "confirm": True,
            }
        )
        try:
            with self._conn.transaction():
                response, pending_error = self._confirm_locked(
                    user_id=normalized_user_id,
                    summary_version=summary_version,
                    preview_nonce=preview_nonce,
                    summary_hash=summary_hash,
                    idempotency_key=normalized_key,
                    request_hash=request_hash,
                )
            if pending_error is not None:
                raise pending_error
            assert response is not None
            return response
        except CutoverError:
            raise
        except Exception as exc:
            self._record_verification_failure(
                user_id=normalized_user_id,
                idempotency_key=normalized_key,
                request_hash=request_hash,
            )
            raise CutoverError(
                "CUTOVER_VERIFICATION_FAILED",
                "无法验证旧学习记录是否已完整清理；两种学习流程均保持锁定。",
                status_code=409,
                recoverable=True,
                details={"cutover_version": CUTOVER_VERSION},
            ) from exc

    def assert_runtime_allowed(self, *, user_id: str) -> None:
        """Authorize Tutor traffic only for a verified cutover receipt."""

        normalized_user_id = _uuid_identifier(user_id)
        with self._conn.transaction():
            record = self._runtime_record_locked(normalized_user_id)
            if record is not None and str(record["state"]) == "verified":
                return
            if record is None:
                inventory = self._inventory(normalized_user_id)
                if inventory.has_target_state:
                    raise self._gate_error("CUTOVER_TARGET_STATE_PRESENT")
                if inventory.checkpoints.state == "unresolved":
                    raise self._gate_error("CUTOVER_CHECKPOINT_SCOPE_UNRESOLVED")
                raise self._gate_error("CUTOVER_REQUIRED")
            self._raise_state_gate_error(str(record["state"]))

    def _runtime_record_locked(self, user_id: str) -> Mapping[str, object] | None:
        self._lock_active_user(user_id, for_update=False)
        return self._conn.execute(
            """
            SELECT state, failure_code
            FROM harness_cutovers
            WHERE user_id = %s AND cutover_version = %s
            """,
            (user_id, CUTOVER_VERSION),
        ).fetchone()

    def _raise_state_gate_error(self, state: str) -> None:
        if state == "blocked_target_state":
            raise self._gate_error("CUTOVER_TARGET_STATE_PRESENT")
        if state == "blocked_checkpoint_scope":
            raise self._gate_error("CUTOVER_CHECKPOINT_SCOPE_UNRESOLVED")
        if state == "verification_failed":
            raise self._gate_error("CUTOVER_VERIFICATION_FAILED")
        raise self._gate_error("CUTOVER_REQUIRED")

    def _confirm_locked(
        self,
        *,
        user_id: str,
        summary_version: int,
        preview_nonce: str,
        summary_hash: str,
        idempotency_key: str,
        request_hash: str,
    ) -> tuple[dict[str, object] | None, CutoverError | None]:
        user = self._lock_active_user(user_id, for_update=True)
        record = self._ensure_record_locked(user_id)
        prior_key = record.get("confirmation_idempotency_key")
        prior_hash = record.get("confirmation_request_hash")
        if isinstance(prior_key, str) and prior_key == idempotency_key:
            if str(prior_hash or "") != request_hash:
                return None, self._confirmation_conflict()
            if str(record["state"]) == "verified":
                return self._verified_response(record, idempotent_replayed=True), None
        if str(record["state"]) == "verified":
            return self._verified_response(record, idempotent_replayed=False), None

        inventory = self._inventory(user_id)
        if inventory.has_target_state:
            self._mark_blocked_locked(
                record,
                state="blocked_target_state",
                code="CUTOVER_TARGET_STATE_PRESENT",
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
            return None, self._block_error("CUTOVER_TARGET_STATE_PRESENT")
        if inventory.checkpoints.state == "unresolved":
            self._mark_blocked_locked(
                record,
                state="blocked_checkpoint_scope",
                code="CUTOVER_CHECKPOINT_SCOPE_UNRESOLVED",
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
            return None, self._block_error("CUTOVER_CHECKPOINT_SCOPE_UNRESOLVED")

        canonical_hash = _summary_hash(self._canonical_summary(user_id, inventory))
        if not inventory.has_legacy_data:
            self._mark_verified_locked(
                record,
                summary_hash=canonical_hash,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
            return self._verified_response(self._load_record_locked(user_id), idempotent_replayed=False), None

        matches_preview = (
            str(record["state"]) == "summary_ready"
            and _int_or_zero(record["summary_version"]) == summary_version
            and secrets.compare_digest(str(record.get("preview_nonce") or ""), preview_nonce)
            and secrets.compare_digest(str(record.get("summary_hash") or ""), summary_hash)
            and secrets.compare_digest(summary_hash, canonical_hash)
        )
        if not matches_preview:
            self._refresh_preview_locked(record, summary_hash=canonical_hash)
            return None, CutoverError(
                "CUTOVER_SUMMARY_STALE",
                "学习记录已变化，请确认最新的清理摘要。",
                status_code=409,
                details={"cutover_version": CUTOVER_VERSION, "summary": self._public_summary(inventory)},
            )

        retained = _retained_snapshot(user)
        checkpoint_thread_ids = inventory.checkpoints.thread_ids
        self._delete_exact_legacy_scope(user_id)
        self._trip_failpoint("after_legacy_delete")
        self._delete_owned_checkpoints(inventory.checkpoints)
        self._trip_failpoint("before_verification")
        self._verify_deleted_scope(
            user_id=user_id,
            retained=retained,
            checkpoint_thread_ids=checkpoint_thread_ids,
        )
        self._mark_verified_locked(
            record,
            summary_hash=canonical_hash,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        return self._verified_response(self._load_record_locked(user_id), idempotent_replayed=False), None

    def _lock_active_user(self, user_id: str, *, for_update: bool) -> Mapping[str, object]:
        lock = " FOR UPDATE" if for_update else " FOR KEY SHARE"
        row = self._conn.execute(
            f"""
            SELECT id, display_name, preferred_time_slots, reminder_preference,
                   learning_style, teaching_preference, encouragement_preference,
                   profession, background_context
            FROM users
            WHERE id = %s AND deleted_at IS NULL{lock}
            """,
            (user_id,),
        ).fetchone()
        if row is None:
            raise CutoverError(
                "USER_NOT_FOUND",
                "用户不存在。",
                status_code=404,
                details={"user_id": user_id},
            )
        return row

    def _ensure_record_locked(self, user_id: str) -> Mapping[str, object]:
        self._conn.execute(
            """
            INSERT INTO harness_cutovers (user_id, cutover_version, state)
            VALUES (%s, %s, 'required')
            ON CONFLICT (user_id, cutover_version) DO NOTHING
            """,
            (user_id, CUTOVER_VERSION),
        )
        return self._load_record_locked(user_id)

    def _load_record_locked(self, user_id: str) -> Mapping[str, object]:
        row = self._conn.execute(
            """
            SELECT * FROM harness_cutovers
            WHERE user_id = %s AND cutover_version = %s
            FOR UPDATE
            """,
            (user_id, CUTOVER_VERSION),
        ).fetchone()
        if row is None:
            raise RuntimeError("cutover receipt was not created")
        return row

    def _inventory(self, user_id: str, *, checkpoint_thread_ids: tuple[str, ...] | None = None) -> CutoverInventory:
        legacy_counts = {name: self._count(query, user_id) for name, query in _LEGACY_COUNT_SQL}
        row = self._conn.execute(
            """
            SELECT learning_style, teaching_preference, encouragement_preference,
                   profession, background_context
            FROM users WHERE id = %s AND deleted_at IS NULL
            """,
            (user_id,),
        ).fetchone()
        if row is None:
            raise CutoverError("USER_NOT_FOUND", "用户不存在。", status_code=404, details={"user_id": user_id})
        fields = {name: row.get(name) is not None for name in _LEGACY_PROFILE_FIELDS}
        target_counts = {name: self._count(query, user_id) for name, query in _TARGET_COUNT_SQL}
        thread_ids = checkpoint_thread_ids if checkpoint_thread_ids is not None else self._legacy_thread_ids(user_id)
        return CutoverInventory(
            legacy_counts=legacy_counts,
            legacy_profile_fields=fields,
            target_counts=target_counts,
            checkpoints=self._checkpoint_inventory(thread_ids),
        )

    def _legacy_thread_ids(self, user_id: str) -> tuple[str, ...]:
        rows = self._conn.execute(
            "SELECT id::text AS id FROM learning_sessions WHERE user_id = %s ORDER BY id",
            (user_id,),
        ).fetchall()
        return tuple(f"aearn:learning:{row['id']}" for row in rows)


    def _checkpoint_inventory(self, thread_ids: tuple[str, ...]) -> CheckpointInventory:
        # Inspect catalog and to_regclass; never create or guess checkpoint tables.
        regclass_row = self._conn.execute(
            """
            SELECT to_regclass('public.checkpoints')::text AS checkpoints,
                   to_regclass('public.checkpoint_blobs')::text AS checkpoint_blobs,
                   to_regclass('public.checkpoint_writes')::text AS checkpoint_writes
            """
        ).fetchone()
        catalog_rows = self._conn.execute(
            """
            SELECT n.nspname AS schema_name, c.relname AS table_name,
                   EXISTS (
                     SELECT 1 FROM pg_attribute a
                     WHERE a.attrelid = c.oid AND a.attname = 'thread_id' AND NOT a.attisdropped
                   ) AS has_thread_id
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r', 'p') AND c.relname = ANY(%s)
            ORDER BY c.relname, n.nspname
            """,
            (list(_CHECKPOINT_TABLES),),
        ).fetchall()
        if not catalog_rows:
            return CheckpointInventory("not_configured", {name: 0 for name in _CHECKPOINT_TABLES}, (), thread_ids)
        by_table = {str(row["table_name"]): row for row in catalog_rows}
        if (
            len(by_table) != len(catalog_rows)
            or any(str(row["schema_name"]) != "public" or not bool(row["has_thread_id"]) for row in catalog_rows)
            or any((regclass_row or {}).get(name) is None for name in by_table)
        ):
            return CheckpointInventory("unresolved", {name: 0 for name in _CHECKPOINT_TABLES}, tuple(sorted(by_table)), thread_ids)

        counts: dict[str, int] = {name: 0 for name in _CHECKPOINT_TABLES}
        for table_name in sorted(by_table):
            other_namespace = self._conn.execute(
                f"SELECT 1 FROM public.{table_name} WHERE thread_id IS NULL OR thread_id NOT LIKE 'aearn:learning:%' LIMIT 1"
            ).fetchone()
            if other_namespace is not None:
                return CheckpointInventory("unresolved", counts, tuple(sorted(by_table)), thread_ids)
            unknown_learning_thread = self._conn.execute(
                f"""
                SELECT 1
                FROM public.{table_name} AS checkpoints
                WHERE checkpoints.thread_id LIKE 'aearn:learning:%'
                  AND NOT EXISTS (
                    SELECT 1 FROM learning_sessions
                    WHERE ('aearn:learning:' || learning_sessions.id::text) = checkpoints.thread_id
                  )
                LIMIT 1
                """
            ).fetchone()
            if unknown_learning_thread is not None:
                return CheckpointInventory("unresolved", counts, tuple(sorted(by_table)), thread_ids)
            if thread_ids:
                counts[table_name] = self._count(
                    f"SELECT count(*)::int AS count FROM public.{table_name} WHERE thread_id = ANY(%s)",
                    list(thread_ids),
                )
        return CheckpointInventory("scoped", counts, tuple(sorted(by_table)), thread_ids)

    def _delete_exact_legacy_scope(self, user_id: str) -> None:
        # Exact ownership only; ordinary reset's JSON/text LIKE behavior is never reused.
        self._conn.execute("DELETE FROM idempotency_records WHERE user_id = %s", (user_id,))
        self._conn.execute(
            """DELETE FROM learning_messages USING learning_sessions
               WHERE learning_messages.session_id = learning_sessions.id
                 AND learning_sessions.user_id = %s""",
            (user_id,),
        )
        self._conn.execute(
            """DELETE FROM review_messages USING learning_sessions
               WHERE review_messages.review_session_id = learning_sessions.id
                 AND learning_sessions.user_id = %s""",
            (user_id,),
        )
        self._conn.execute(
            """DELETE FROM onboarding_messages USING onboarding_conversations
               WHERE onboarding_messages.conversation_id = onboarding_conversations.id
                 AND onboarding_conversations.user_id = %s""",
            (user_id,),
        )
        for table_name in ("review_logs", "review_states", "review_seed_banks", "exercise_variant_cache", "notes", "attempts"):
            self._conn.execute(f"DELETE FROM {table_name} WHERE user_id = %s", (user_id,))
        self._conn.execute(
            """UPDATE knowledge_points SET last_session_id = NULL
               FROM plan_modules, learning_plans
               WHERE knowledge_points.module_id = plan_modules.id
                 AND plan_modules.plan_id = learning_plans.id
                 AND learning_plans.user_id = %s""",
            (user_id,),
        )
        self._conn.execute("DELETE FROM learning_sessions WHERE user_id = %s", (user_id,))
        self._conn.execute(
            """DELETE FROM teaching_chunks USING knowledge_points, plan_modules, learning_plans
               WHERE teaching_chunks.knowledge_point_id = knowledge_points.id
                 AND knowledge_points.module_id = plan_modules.id
                 AND plan_modules.plan_id = learning_plans.id
                 AND learning_plans.user_id = %s""",
            (user_id,),
        )
        for child_table in ("test_cases", "code_blanks"):
            self._conn.execute(
                f"""DELETE FROM {child_table} USING exercises, knowledge_points, plan_modules, learning_plans
                   WHERE {child_table}.exercise_id = exercises.id
                     AND exercises.knowledge_point_id = knowledge_points.id
                     AND knowledge_points.module_id = plan_modules.id
                     AND plan_modules.plan_id = learning_plans.id
                     AND learning_plans.user_id = %s""",
                (user_id,),
            )
        self._conn.execute(
            """DELETE FROM exercises USING knowledge_points, plan_modules, learning_plans
               WHERE exercises.knowledge_point_id = knowledge_points.id
                 AND knowledge_points.module_id = plan_modules.id
                 AND plan_modules.plan_id = learning_plans.id
                 AND learning_plans.user_id = %s""",
            (user_id,),
        )
        self._conn.execute("UPDATE learning_plans SET current_module_id = NULL WHERE user_id = %s", (user_id,))
        self._conn.execute(
            """DELETE FROM knowledge_points USING plan_modules, learning_plans
               WHERE knowledge_points.module_id = plan_modules.id
                 AND plan_modules.plan_id = learning_plans.id
                 AND learning_plans.user_id = %s""",
            (user_id,),
        )
        self._conn.execute(
            """DELETE FROM plan_modules USING learning_plans
               WHERE plan_modules.plan_id = learning_plans.id AND learning_plans.user_id = %s""",
            (user_id,),
        )
        self._conn.execute("DELETE FROM learning_plans WHERE user_id = %s", (user_id,))
        self._conn.execute("DELETE FROM learner_profiles WHERE user_id = %s", (user_id,))
        self._conn.execute("DELETE FROM onboarding_conversations WHERE user_id = %s", (user_id,))
        self._conn.execute(
            """UPDATE users
               SET learning_style = NULL, teaching_preference = NULL,
                   encouragement_preference = NULL, profession = NULL,
                   background_context = NULL
               WHERE id = %s AND deleted_at IS NULL""",
            (user_id,),
        )

    def _delete_owned_checkpoints(self, inventory: CheckpointInventory) -> None:
        if inventory.state == "not_configured" or not inventory.thread_ids:
            return
        if inventory.state != "scoped":
            raise RuntimeError("checkpoint scope must be resolved before deletion")
        for table_name in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            if table_name in inventory.configured_tables:
                self._conn.execute(
                    f"DELETE FROM public.{table_name} WHERE thread_id = ANY(%s)",
                    (list(inventory.thread_ids),),
                )

    def _verify_deleted_scope(
        self,
        *,
        user_id: str,
        retained: Mapping[str, object],
        checkpoint_thread_ids: tuple[str, ...],
    ) -> None:
        after = self._inventory(user_id, checkpoint_thread_ids=checkpoint_thread_ids)
        if after.has_legacy_data:
            raise RuntimeError("legacy rows remained after cutover deletion")
        if after.has_target_state:
            raise RuntimeError("target state changed during cutover")
        if after.checkpoints.state == "unresolved" or any(after.checkpoints.table_counts.values()):
            raise RuntimeError("checkpoint scope could not be verified after deletion")
        current = self._lock_active_user(user_id, for_update=False)
        if _retained_snapshot(current) != dict(retained):
            raise RuntimeError("retained user settings changed during cutover")

    def _mark_blocked_locked(
        self,
        record: Mapping[str, object],
        *,
        state: Literal["blocked_target_state", "blocked_checkpoint_scope"],
        code: str,
        idempotency_key: str | None = None,
        request_hash: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            UPDATE harness_cutovers
            SET state = %s, failure_code = %s, failure_at = now(), preview_nonce = NULL,
                confirmation_idempotency_key = COALESCE(%s, confirmation_idempotency_key),
                confirmation_request_hash = COALESCE(%s, confirmation_request_hash)
            WHERE user_id = %s AND cutover_version = %s
            """,
            (state, code, idempotency_key, request_hash, record["user_id"], CUTOVER_VERSION),
        )

    def _refresh_preview_locked(self, record: Mapping[str, object], *, summary_hash: str) -> None:
        self._conn.execute(
            """
            UPDATE harness_cutovers
            SET state = 'summary_ready', summary_hash = %s, preview_nonce = %s,
                summary_version = summary_version + 1,
                confirmation_idempotency_key = NULL, confirmation_request_hash = NULL,
                confirmed_at = NULL, failure_code = NULL, failure_at = NULL
            WHERE user_id = %s AND cutover_version = %s
            """,
            (summary_hash, secrets.token_urlsafe(24), record["user_id"], CUTOVER_VERSION),
        )


    def _mark_verified_locked(
        self,
        record: Mapping[str, object],
        *,
        summary_hash: str,
        idempotency_key: str | None,
        request_hash: str | None,
    ) -> None:
        self._conn.execute(
            """
            UPDATE harness_cutovers
            SET state = 'verified', summary_hash = %s, preview_nonce = NULL,
                confirmation_idempotency_key = COALESCE(%s, confirmation_idempotency_key),
                confirmation_request_hash = COALESCE(%s, confirmation_request_hash),
                confirmed_at = CASE WHEN %s::text IS NULL THEN confirmed_at ELSE now() END,
                verified_at = COALESCE(verified_at, now()),
                failure_code = NULL, failure_at = NULL
            WHERE user_id = %s AND cutover_version = %s
            """,
            (summary_hash, idempotency_key, request_hash, idempotency_key, record["user_id"], CUTOVER_VERSION),
        )

    def _record_verification_failure(self, *, user_id: str, idempotency_key: str, request_hash: str) -> None:
        # The destructive transaction has rolled back. Persist only a safe receipt
        # in a separate short transaction so both runtime paths remain blocked.
        with self._conn.transaction():
            self._lock_active_user(user_id, for_update=True)
            record = self._ensure_record_locked(user_id)
            self._conn.execute(
                """
                UPDATE harness_cutovers
                SET state = 'verification_failed', preview_nonce = NULL,
                    confirmation_idempotency_key = %s, confirmation_request_hash = %s,
                    confirmed_at = now(), failure_code = 'CUTOVER_VERIFICATION_FAILED', failure_at = now()
                WHERE user_id = %s AND cutover_version = %s
                """,
                (idempotency_key, request_hash, record["user_id"], CUTOVER_VERSION),
            )

    def _public_summary(self, inventory: CutoverInventory) -> dict[str, object]:
        return {
            "legacy_categories": [
                {"id": name, "count": count}
                for name, count in inventory.legacy_counts.items()
                if count > 0
            ],
            "legacy_profile_fields": [
                {"id": name, "will_clear": True}
                for name, present in inventory.legacy_profile_fields.items()
                if present
            ],
            "checkpoint": {
                "state": inventory.checkpoints.state,
                "record_count": sum(inventory.checkpoints.table_counts.values()),
            },
            "retained_categories": ["local_identity", "notification_preferences"],
            "target_state_present": inventory.has_target_state,
        }

    def _canonical_summary(self, user_id: str, inventory: CutoverInventory) -> dict[str, object]:
        return {
            "cutover_version": CUTOVER_VERSION,
            "user_id": user_id,
            "legacy_counts": inventory.legacy_counts,
            "legacy_profile_fields": inventory.legacy_profile_fields,
            "target_counts": inventory.target_counts,
            "checkpoint": {
                "state": inventory.checkpoints.state,
                "table_counts": inventory.checkpoints.table_counts,
                "thread_count": len(inventory.checkpoints.thread_ids),
            },
        }

    def _verified_response(self, record: Mapping[str, object], *, idempotent_replayed: bool) -> dict[str, object]:
        return {
            "cutover_version": CUTOVER_VERSION,
            "rollout_active": True,
            "state": "verified",
            "verified_at": _iso(record.get("verified_at")),
            "idempotent_replayed": idempotent_replayed,
            "next_action": "enter_tutor",
        }

    def _blocked_response(self, state: str, code: str, summary: Mapping[str, object]) -> dict[str, object]:
        return {
            "cutover_version": CUTOVER_VERSION,
            "rollout_active": True,
            "state": state,
            "code": code,
            "summary": dict(summary),
            "next_action": "resolve_cutover_block",
        }

    def _gate_error(self, code: str) -> CutoverError:
        if code == "CUTOVER_REQUIRED":
            return CutoverError(
                code,
                "需要先完成受控切换，当前学习入口暂不可用。",
                status_code=409,
                recoverable=False,
                details={"cutover_version": CUTOVER_VERSION},
            )
        return self._block_error(code)

    def _block_error(self, code: str) -> CutoverError:
        messages = {
            "CUTOVER_TARGET_STATE_PRESENT": "检测到预切换 Tutor 数据，系统未删除任何记录。",
            "CUTOVER_CHECKPOINT_SCOPE_UNRESOLVED": "无法安全确认历史运行状态归属，系统未删除任何记录。",
            "CUTOVER_VERIFICATION_FAILED": "无法验证旧学习记录是否已完整清理；两种学习流程均保持锁定。",
        }
        return CutoverError(
            code,
            messages[code],
            status_code=409,
            recoverable=code != "CUTOVER_TARGET_STATE_PRESENT",
            details={"cutover_version": CUTOVER_VERSION},
        )

    def _confirmation_conflict(self) -> CutoverError:
        return CutoverError(
            "CUTOVER_CONFIRMATION_CONFLICT",
            "同一确认标识不能用于不同的切换请求。",
            status_code=409,
            recoverable=False,
            details={"cutover_version": CUTOVER_VERSION},
        )

    def _count(self, query: str, parameter: object) -> int:
        row = self._conn.execute(query, (parameter,)).fetchone()
        return _int_or_zero(row["count"]) if row is not None else 0

    def _trip_failpoint(self, stage: str) -> None:
        if self._failure_injector is not None:
            self._failure_injector(stage)


def runtime_gate_error(*, user_id: str) -> CutoverError | None:
    """Return a stable gate error for a short-lived non-legacy route check."""

    with connect() as conn:
        try:
            HarnessCutoverService(conn).assert_runtime_allowed(user_id=user_id)
        except CutoverError as exc:
            conn.rollback()
            return exc
    return None


def _uuid_identifier(value: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise CutoverError(
            "VALIDATION_ERROR",
            "user_id 必须是 UUID。",
            status_code=400,
            details={"field": "user_id"},
        ) from exc


def _idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not _IDEMPOTENCY_KEY.fullmatch(normalized):
        raise CutoverError(
            "VALIDATION_ERROR",
            "确认标识格式不合法。",
            status_code=400,
            details={"field": "client_action_id"},
        )
    return normalized


def _summary_hash(value: Mapping[str, object]) -> str:
    encoded = json.dumps(_json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _json_value(value: object) -> object:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    return value


def _retained_snapshot(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "display_name": _json_value(row.get("display_name")),
        "preferred_time_slots": _json_value(row.get("preferred_time_slots")),
        "reminder_preference": _json_value(row.get("reminder_preference")),
    }


def _iso(value: object) -> str | None:
    if not isinstance(value, datetime):
        return None
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).isoformat()


def _int_or_zero(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str | bytes | bytearray):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0
