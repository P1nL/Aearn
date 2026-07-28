"""PostgreSQL source of truth for target-only proactive scheduling and curation leases."""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Literal

from psycopg import Connection

from app.agents.harness.contracts import TutorPolicySnapshot
from app.services.tutor.persistence import TutorCatalogEvidenceError, TutorLeaseConflict, TutorRunNotFound
from app.services.tutor.proactive import (
    PersistedProactiveSignal,
    ProactiveRunReservation,
    SchedulerDecision,
    SchedulerState,
    SchedulerUsage,
    TutorCurationJob,
    TutorProactiveCandidate,
    TutorProactivePreference,
    TutorProactiveSignal,
)
from app.services.tutor.safe_projection import TutorSafeProjection


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PostgresTutorProactiveRepository:
    """Durable PostgreSQL rows are authoritative; broker delivery is only a wake-up."""

    def __init__(self, conn: Connection[dict[str, object]], *, projector: TutorSafeProjection | None = None) -> None:
        self._conn = conn
        self._projector = projector or TutorSafeProjection()

    def upsert_preference(self, *, preference: TutorProactivePreference, now: datetime) -> TutorProactivePreference:
        with self._conn.transaction():
            row = self._conn.execute(
                """
                INSERT INTO tutor_proactive_preferences (
                  user_id, enabled, hard_paused, policy_version, setting_version, created_at, updated_at
                )
                SELECT users.id, %s, %s, %s, %s, %s, %s
                FROM users
                WHERE users.id = %s
                ON CONFLICT (user_id) DO UPDATE
                SET enabled = EXCLUDED.enabled,
                    hard_paused = EXCLUDED.hard_paused,
                    policy_version = EXCLUDED.policy_version,
                    setting_version = EXCLUDED.setting_version,
                    updated_at = EXCLUDED.updated_at
                RETURNING user_id::text AS user_id, enabled, hard_paused, policy_version, setting_version
                """,
                (
                    preference.enabled,
                    preference.hard_paused,
                    preference.policy_version,
                    preference.setting_version,
                    now,
                    now,
                    preference.user_id,
                ),
            ).fetchone()
        if row is None:
            raise TutorRunNotFound("proactive preference user not found")
        return _preference_from_row(row)

    def preference_for_user(self, *, user_id: str) -> TutorProactivePreference:
        row = self._conn.execute(
            """
            SELECT user_id::text AS user_id, enabled, hard_paused, policy_version, setting_version
            FROM tutor_proactive_preferences
            WHERE user_id = %s
            """,
            (user_id,),
        ).fetchone()
        return _preference_from_row(row) if row is not None else TutorProactivePreference(user_id=user_id)

    def record_signal(self, *, signal: TutorProactiveSignal, now: datetime) -> PersistedProactiveSignal:
        safe_reference = self._projector.project(dict(signal.source_reference))
        with self._conn.transaction():
            existing = self._conn.execute(
                """
                SELECT *
                FROM tutor_proactive_signals
                WHERE user_id = %s AND source_type = %s AND source_id = %s AND source_hash = %s
                FOR UPDATE
                """,
                (signal.user_id, signal.source_type, signal.source_id, signal.source_hash),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["signal_kind"]) != signal.signal_kind
                    or str(existing["dedupe_key"]) != signal.dedupe_key
                    or _as_int(existing.get("dedupe_window_seconds"), -1) != signal.dedupe_window_seconds
                    or str(existing["policy_version"]) != signal.policy_version
                ):
                    raise ValueError("proactive signal identity conflicts with immutable facts")
                self._conn.execute(
                    "UPDATE tutor_proactive_signals SET last_seen_at = %s WHERE id = %s",
                    (now, existing["id"]),
                )
                return PersistedProactiveSignal(
                    signal_id=str(existing["id"]),
                    signal=signal,
                    disposition=str(existing["disposition"]),
                    disposition_code=_optional_str(existing.get("disposition_code")),
                    replayed=True,
                )
            row = self._conn.execute(
                """
                INSERT INTO tutor_proactive_signals (
                  user_id, signal_kind, source_type, source_id, source_hash, occurred_at,
                  dedupe_key, dedupe_bucket_at, dedupe_window_seconds, source_reference_json,
                  policy_version, disposition, created_at, last_seen_at
                )
                SELECT users.id, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, 'received', %s, %s
                FROM users
                WHERE users.id = %s
                RETURNING id::text AS id
                """,
                (
                    signal.signal_kind,
                    signal.source_type,
                    signal.source_id,
                    signal.source_hash,
                    signal.occurred_at,
                    signal.dedupe_key,
                    signal.dedupe_bucket_at,
                    signal.dedupe_window_seconds,
                    _json(safe_reference),
                    signal.policy_version,
                    now,
                    now,
                    signal.user_id,
                ),
            ).fetchone()
        if row is None:
            raise TutorRunNotFound("proactive signal user not found")
        return PersistedProactiveSignal(
            signal_id=str(row["id"]),
            signal=signal,
            disposition="received",
            disposition_code=None,
            replayed=False,
        )

    def create_or_replay_candidate(
        self,
        *,
        signal: PersistedProactiveSignal,
        decision: SchedulerDecision,
        policy_fingerprint: str,
        now: datetime,
    ) -> TutorProactiveCandidate:
        with self._conn.transaction():
            current = self._conn.execute(
                "SELECT * FROM tutor_proactive_candidates WHERE signal_id = %s FOR UPDATE",
                (signal.signal_id,),
            ).fetchone()
            if current is not None:
                return _candidate_from_row(current)
            state: SchedulerState = "pending" if decision.allowed else "no_action"
            code = None if decision.allowed else decision.code
            row = self._conn.execute(
                """
                INSERT INTO tutor_proactive_candidates (
                  signal_id, user_id, candidate_kind, dedupe_key, dedupe_bucket_at,
                  policy_version, policy_fingerprint, state, no_action_code, not_before,
                  created_at, updated_at, terminal_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        CASE WHEN %s = 'no_action' THEN %s ELSE NULL END)
                ON CONFLICT (user_id, dedupe_key, dedupe_bucket_at) DO NOTHING
                RETURNING *
                """,
                (
                    signal.signal_id,
                    signal.signal.user_id,
                    signal.signal.signal_kind,
                    signal.signal.dedupe_key,
                    signal.signal.dedupe_bucket_at,
                    signal.signal.policy_version,
                    policy_fingerprint,
                    state,
                    code,
                    now,
                    now,
                    now,
                    state,
                    now,
                ),
            ).fetchone()
            if row is None:
                duplicate = self._conn.execute(
                    """
                    SELECT * FROM tutor_proactive_candidates
                    WHERE user_id = %s AND dedupe_key = %s AND dedupe_bucket_at = %s
                    FOR UPDATE
                    """,
                    (signal.signal.user_id, signal.signal.dedupe_key, signal.signal.dedupe_bucket_at),
                ).fetchone()
                if duplicate is None:
                    raise RuntimeError("proactive candidate dedupe lookup failed")
                candidate = _candidate_from_row(duplicate)
                self._conn.execute(
                    """
                    UPDATE tutor_proactive_signals
                    SET disposition = 'suppressed', disposition_code = 'dedupe_window', last_seen_at = %s
                    WHERE id = %s
                    """,
                    (now, signal.signal_id),
                )
                self._append_audit(
                    queue="proactive",
                    user_id=signal.signal.user_id,
                    decision="no_action",
                    code="dedupe_window",
                    details={"signal_id": signal.signal_id},
                    now=now,
                    candidate_id=candidate.candidate_id,
                )
                return candidate
            candidate = _candidate_from_row(row)
            self._conn.execute(
                """
                UPDATE tutor_proactive_signals
                SET disposition = %s, disposition_code = %s, last_seen_at = %s
                WHERE id = %s
                """,
                ("accepted" if decision.allowed else "no_action", code, now, signal.signal_id),
            )
            self._append_audit(
                queue="proactive",
                user_id=candidate.user_id,
                decision="allowed" if decision.allowed else "no_action",
                code=decision.code,
                details={"signal_id": signal.signal_id, "state": candidate.state},
                now=now,
                candidate_id=candidate.candidate_id,
            )
            return candidate

    def proactive_usage(self, *, user_id: str, now: datetime, circuit_window_seconds: int) -> SchedulerUsage:
        return self._usage_for_queue(
            table="tutor_proactive_candidates",
            started_column="run_started_at",
            user_id=user_id,
            now=now,
            circuit_window_seconds=circuit_window_seconds,
        )

    def curation_usage(self, *, user_id: str, now: datetime, circuit_window_seconds: int) -> SchedulerUsage:
        return self._usage_for_queue(
            table="tutor_curation_jobs",
            started_column="processor_started_at",
            user_id=user_id,
            now=now,
            circuit_window_seconds=circuit_window_seconds,
        )

    def claim_next_candidate(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
        max_retry_attempts: int,
        retry_backoff_seconds: int,
    ) -> TutorProactiveCandidate | None:
        with self._conn.transaction():
            self._recover_expired_candidates(
                now=now,
                max_retry_attempts=max_retry_attempts,
                retry_backoff_seconds=retry_backoff_seconds,
            )
            row = self._conn.execute(
                """
                SELECT *
                FROM tutor_proactive_candidates
                WHERE state = 'pending' AND not_before <= %s
                ORDER BY not_before ASC, created_at ASC, id ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """,
                (now,),
            ).fetchone()
            if row is None:
                return None
            claimed = self._conn.execute(
                """
                UPDATE tutor_proactive_candidates
                SET state = 'leased',
                    attempt_count = attempt_count + 1,
                    lease_owner_id = %s,
                    lease_generation = lease_generation + 1,
                    lease_expires_at = %s,
                    updated_at = %s
                WHERE id = %s
                RETURNING *
                """,
                (worker_id, now + timedelta(seconds=lease_seconds), now, row["id"]),
            ).fetchone()
            if claimed is None:
                raise RuntimeError("proactive candidate claim failed")
            candidate = _candidate_from_row(claimed)
            self._append_audit(
                queue="proactive",
                user_id=candidate.user_id,
                decision="leased",
                code="candidate_claimed",
                details={"lease_generation": candidate.lease_generation, "attempt_count": candidate.attempt_count},
                now=now,
                candidate_id=candidate.candidate_id,
            )
            return candidate

    def mark_candidate_terminal(
        self,
        *,
        candidate: TutorProactiveCandidate,
        state: Literal["completed", "no_action", "failed"],
        code: str,
        now: datetime,
        run_id: str | None = None,
    ) -> None:
        self._require_candidate_lease(candidate)
        with self._conn.transaction():
            row = self._conn.execute(
                """
                UPDATE tutor_proactive_candidates
                SET state = %s,
                    no_action_code = CASE WHEN %s = 'no_action' THEN %s ELSE no_action_code END,
                    last_error_code = CASE WHEN %s = 'failed' THEN %s ELSE NULL END,
                    run_id = COALESCE(%s, run_id),
                    lease_owner_id = NULL,
                    lease_expires_at = NULL,
                    terminal_at = %s,
                    updated_at = %s
                WHERE id = %s
                  AND state = 'leased'
                  AND lease_owner_id = %s
                  AND lease_generation = %s
                RETURNING user_id::text AS user_id
                """,
                (
                    state,
                    state,
                    code,
                    state,
                    code,
                    run_id,
                    now,
                    now,
                    candidate.candidate_id,
                    candidate.lease_owner_id,
                    candidate.lease_generation,
                ),
            ).fetchone()
            if row is None:
                raise TutorLeaseConflict("proactive candidate lease is stale")
            self._append_audit(
                queue="proactive",
                user_id=str(row["user_id"]),
                decision=state,
                code=code,
                details={"run_id": run_id} if run_id else {},
                now=now,
                candidate_id=candidate.candidate_id,
            )

    def retry_candidate(
        self,
        *,
        candidate: TutorProactiveCandidate,
        code: str,
        now: datetime,
        max_retry_attempts: int,
        retry_backoff_seconds: int,
    ) -> None:
        self._require_candidate_lease(candidate)
        with self._conn.transaction():
            row = self._conn.execute(
                """
                UPDATE tutor_proactive_candidates
                SET state = CASE WHEN attempt_count >= %s THEN 'failed' ELSE 'pending' END,
                    last_error_code = %s,
                    lease_owner_id = NULL,
                    lease_expires_at = NULL,
                    not_before = CASE WHEN attempt_count >= %s THEN not_before ELSE %s END,
                    terminal_at = CASE WHEN attempt_count >= %s THEN %s ELSE NULL END,
                    updated_at = %s
                WHERE id = %s
                  AND state = 'leased'
                  AND lease_owner_id = %s
                  AND lease_generation = %s
                RETURNING state, user_id::text AS user_id
                """,
                (
                    max_retry_attempts,
                    code,
                    max_retry_attempts,
                    now + timedelta(seconds=retry_backoff_seconds),
                    max_retry_attempts,
                    now,
                    now,
                    candidate.candidate_id,
                    candidate.lease_owner_id,
                    candidate.lease_generation,
                ),
            ).fetchone()
            if row is None:
                raise TutorLeaseConflict("proactive candidate lease is stale")
            state = str(row["state"])
            self._append_audit(
                queue="proactive",
                user_id=str(row["user_id"]),
                decision="failed" if state == "failed" else "retry",
                code=code,
                details={"attempt_count": candidate.attempt_count},
                now=now,
                candidate_id=candidate.candidate_id,
            )

    def reserve_proactive_run(
        self,
        *,
        candidate: TutorProactiveCandidate,
        catalog_digest: str,
        policy: TutorPolicySnapshot,
        policy_version: str,
        policy_fingerprint: str,
        now: datetime,
    ) -> ProactiveRunReservation:
        self._require_candidate_lease(candidate)
        if not _SHA256.fullmatch(catalog_digest) or not _SHA256.fullmatch(policy_fingerprint):
            raise ValueError("proactive run evidence requires SHA-256 digests")
        with self._conn.transaction():
            current = self._conn.execute(
                "SELECT * FROM tutor_proactive_candidates WHERE id = %s FOR UPDATE",
                (candidate.candidate_id,),
            ).fetchone()
            if current is None:
                raise TutorRunNotFound("proactive candidate not found")
            if (
                str(current["state"]) != "leased"
                or str(current.get("lease_owner_id") or "") != candidate.lease_owner_id
                or _as_int(current.get("lease_generation"), -1) != candidate.lease_generation
            ):
                raise TutorLeaseConflict("proactive candidate lease is stale")
            existing_run_id = _optional_str(current.get("run_id"))
            if existing_run_id is not None:
                run = self._conn.execute(
                    "SELECT conversation_id::text AS conversation_id FROM tutor_runs WHERE id = %s",
                    (existing_run_id,),
                ).fetchone()
                if run is None:
                    raise TutorRunNotFound("reserved proactive run not found")
                return ProactiveRunReservation(
                    run_id=existing_run_id,
                    conversation_id=str(run["conversation_id"]),
                    replayed=True,
                )
            catalog = self._conn.execute(
                "SELECT digest FROM tutor_catalog_snapshots WHERE digest = %s",
                (catalog_digest,),
            ).fetchone()
            if catalog is None:
                raise TutorCatalogEvidenceError("catalog snapshot is not persisted")
            conversation = self._conn.execute(
                """
                INSERT INTO tutor_conversations (user_id, status, visibility, kind, created_at, updated_at)
                VALUES (%s, 'active', 'internal', 'proactive', %s, %s)
                RETURNING id::text AS id
                """,
                (candidate.user_id, now, now),
            ).fetchone()
            if conversation is None:
                raise RuntimeError("proactive conversation insert failed")
            run = self._conn.execute(
                """
                INSERT INTO tutor_runs (
                  user_id, conversation_id, origin, status, policy_json,
                  policy_version, policy_fingerprint, catalog_digest, created_at, updated_at
                )
                VALUES (%s, %s, 'proactive', 'queued', %s::jsonb, %s, %s, %s, %s, %s)
                RETURNING id::text AS id
                """,
                (
                    candidate.user_id,
                    conversation["id"],
                    _json(self._projector.project(_policy_payload(policy))),
                    policy_version,
                    policy_fingerprint,
                    catalog_digest,
                    now,
                    now,
                ),
            ).fetchone()
            if run is None:
                raise RuntimeError("proactive run insert failed")
            linked = self._conn.execute(
                """
                UPDATE tutor_proactive_candidates
                SET run_id = %s, run_started_at = %s, updated_at = %s
                WHERE id = %s
                  AND state = 'leased'
                  AND lease_owner_id = %s
                  AND lease_generation = %s
                RETURNING id
                """,
                (
                    run["id"],
                    now,
                    now,
                    candidate.candidate_id,
                    candidate.lease_owner_id,
                    candidate.lease_generation,
                ),
            ).fetchone()
            if linked is None:
                raise TutorLeaseConflict("proactive candidate changed before run reservation")
            self._append_audit(
                queue="proactive",
                user_id=candidate.user_id,
                decision="reserved",
                code="proactive_run_reserved",
                details={"run_id": str(run["id"]), "conversation_id": str(conversation["id"])},
                now=now,
                candidate_id=candidate.candidate_id,
            )
            return ProactiveRunReservation(
                run_id=str(run["id"]),
                conversation_id=str(conversation["id"]),
                replayed=False,
            )

    def _recover_expired_candidates(
        self, *, now: datetime, max_retry_attempts: int, retry_backoff_seconds: int
    ) -> None:
        rows = self._conn.execute(
            """
            UPDATE tutor_proactive_candidates
            SET state = CASE WHEN attempt_count >= %s THEN 'failed' ELSE 'pending' END,
                last_error_code = 'lease_expired',
                lease_owner_id = NULL,
                lease_expires_at = NULL,
                not_before = CASE WHEN attempt_count >= %s THEN not_before ELSE %s END,
                terminal_at = CASE WHEN attempt_count >= %s THEN %s ELSE NULL END,
                updated_at = %s
            WHERE state = 'leased' AND lease_expires_at <= %s
            RETURNING id::text AS id, user_id::text AS user_id, state, attempt_count
            """,
            (
                max_retry_attempts,
                max_retry_attempts,
                now + timedelta(seconds=retry_backoff_seconds),
                max_retry_attempts,
                now,
                now,
                now,
            ),
        ).fetchall()
        for row in rows:
            self._append_audit(
                queue="proactive",
                user_id=str(row["user_id"]),
                decision="failed" if str(row["state"]) == "failed" else "retry",
                code="lease_expired",
                details={"attempt_count": _as_int(row.get("attempt_count"), 0)},
                now=now,
                candidate_id=str(row["id"]),
            )


    def seed_curation_jobs(self, *, now: datetime, limit: int) -> tuple[TutorCurationJob, ...]:
        with self._conn.transaction():
            rows = self._conn.execute(
                """
                SELECT outbox.*, runs.user_id::text AS user_id
                FROM tutor_memory_curation_outbox AS outbox
                JOIN tutor_runs AS runs ON runs.id = outbox.run_id
                LEFT JOIN tutor_curation_jobs AS jobs ON jobs.outbox_id = outbox.id
                WHERE jobs.id IS NULL
                  AND outbox.state = 'pending'
                ORDER BY outbox.priority DESC, outbox.created_at ASC, outbox.id ASC
                FOR UPDATE OF outbox SKIP LOCKED
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
            jobs: list[TutorCurationJob] = []
            for outbox in rows:
                stale_after = _as_datetime(outbox.get("stale_after"))
                state: SchedulerState = "stale" if stale_after is None or stale_after <= now else "pending"
                code = "outbox_stale" if state == "stale" else None
                inserted = self._conn.execute(
                    """
                    INSERT INTO tutor_curation_jobs (
                      outbox_id, run_id, user_id, policy_version, memory_setting_version, state,
                      no_action_code, not_before, created_at, updated_at, terminal_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            CASE WHEN %s = 'stale' THEN %s ELSE NULL END)
                    ON CONFLICT (outbox_id) DO NOTHING
                    RETURNING *
                    """,
                    (
                        outbox["id"],
                        outbox["run_id"],
                        outbox["user_id"],
                        outbox["policy_version"],
                        outbox["memory_setting_version"],
                        state,
                        code,
                        now,
                        now,
                        now,
                        state,
                        now,
                    ),
                ).fetchone()
                if inserted is None:
                    inserted = self._conn.execute(
                        "SELECT * FROM tutor_curation_jobs WHERE outbox_id = %s",
                        (outbox["id"],),
                    ).fetchone()
                if inserted is None:
                    raise RuntimeError("curation job insert failed")
                job = _curation_job_from_row(inserted)
                jobs.append(job)
                self._append_audit(
                    queue="curation",
                    user_id=job.user_id,
                    decision="stale" if state == "stale" else "seeded",
                    code=code or "curation_job_seeded",
                    details={"outbox_id": job.outbox_id},
                    now=now,
                    curation_job_id=job.job_id,
                )
            return tuple(jobs)

    def claim_next_curation_job(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
        max_retry_attempts: int,
        retry_backoff_seconds: int,
    ) -> TutorCurationJob | None:
        with self._conn.transaction():
            self._recover_expired_curation_jobs(
                now=now,
                max_retry_attempts=max_retry_attempts,
                retry_backoff_seconds=retry_backoff_seconds,
            )
            row = self._conn.execute(
                """
                SELECT *
                FROM tutor_curation_jobs
                WHERE state = 'pending' AND not_before <= %s
                ORDER BY not_before ASC, created_at ASC, id ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """,
                (now,),
            ).fetchone()
            if row is None:
                return None
            claimed = self._conn.execute(
                """
                UPDATE tutor_curation_jobs
                SET state = 'leased',
                    attempt_count = attempt_count + 1,
                    lease_owner_id = %s,
                    lease_generation = lease_generation + 1,
                    lease_expires_at = %s,
                    updated_at = %s
                WHERE id = %s
                RETURNING *
                """,
                (worker_id, now + timedelta(seconds=lease_seconds), now, row["id"]),
            ).fetchone()
            if claimed is None:
                raise RuntimeError("curation job claim failed")
            job = _curation_job_from_row(claimed)
            self._append_audit(
                queue="curation",
                user_id=job.user_id,
                decision="leased",
                code="curation_job_claimed",
                details={"lease_generation": job.lease_generation, "attempt_count": job.attempt_count},
                now=now,
                curation_job_id=job.job_id,
            )
            return job

    def curation_job_current(self, *, job: TutorCurationJob, now: datetime) -> SchedulerDecision:
        row = self._conn.execute(
            """
            SELECT
              outbox.state AS outbox_state,
              outbox.policy_version AS outbox_policy_version,
              outbox.memory_setting_version AS outbox_memory_setting_version,
              outbox.stale_after,
              outbox.input_revision,
              runs.input_revision AS run_input_revision
            FROM tutor_curation_jobs AS jobs
            JOIN tutor_memory_curation_outbox AS outbox ON outbox.id = jobs.outbox_id
            JOIN tutor_runs AS runs ON runs.id = outbox.run_id
            WHERE jobs.id = %s AND jobs.user_id = %s
            """,
            (job.job_id, job.user_id),
        ).fetchone()
        if row is None:
            return SchedulerDecision(False, "outbox_not_found", "curation")
        if str(row["outbox_state"]) != "pending":
            return SchedulerDecision(False, "outbox_not_pending", "curation")
        stale_after = _as_datetime(row.get("stale_after"))
        if stale_after is None or stale_after <= now:
            return SchedulerDecision(False, "outbox_stale", "curation")
        if str(row["outbox_policy_version"]) != job.policy_version:
            return SchedulerDecision(False, "outbox_policy_version_stale", "curation")
        if str(row["outbox_memory_setting_version"]) != job.memory_setting_version:
            return SchedulerDecision(False, "outbox_memory_setting_stale", "curation")
        if _as_int(row.get("input_revision"), -1) != _as_int(row.get("run_input_revision"), -1):
            return SchedulerDecision(False, "outbox_source_revision_stale", "curation")
        return SchedulerDecision(True, "eligible", "curation")

    def mark_curation_processor_started(self, *, job: TutorCurationJob, now: datetime) -> None:
        self._require_curation_lease(job)
        with self._conn.transaction():
            row = self._conn.execute(
                """
                UPDATE tutor_curation_jobs
                SET processor_started_at = COALESCE(processor_started_at, %s), updated_at = %s
                WHERE id = %s
                  AND state = 'leased'
                  AND lease_owner_id = %s
                  AND lease_generation = %s
                RETURNING user_id::text AS user_id
                """,
                (now, now, job.job_id, job.lease_owner_id, job.lease_generation),
            ).fetchone()
            if row is None:
                raise TutorLeaseConflict("curation job lease is stale")
            self._append_audit(
                queue="curation",
                user_id=str(row["user_id"]),
                decision="processor_started",
                code="curation_processor_started",
                details={},
                now=now,
                curation_job_id=job.job_id,
            )

    def mark_curation_terminal(
        self,
        *,
        job: TutorCurationJob,
        state: Literal["completed", "no_action", "failed", "stale"],
        code: str,
        now: datetime,
    ) -> None:
        self._require_curation_lease(job)
        with self._conn.transaction():
            row = self._conn.execute(
                """
                UPDATE tutor_curation_jobs
                SET state = %s,
                    no_action_code = CASE WHEN %s IN ('no_action', 'stale') THEN %s ELSE no_action_code END,
                    last_error_code = CASE WHEN %s = 'failed' THEN %s ELSE NULL END,
                    lease_owner_id = NULL,
                    lease_expires_at = NULL,
                    terminal_at = %s,
                    updated_at = %s
                WHERE id = %s
                  AND state = 'leased'
                  AND lease_owner_id = %s
                  AND lease_generation = %s
                RETURNING user_id::text AS user_id
                """,
                (
                    state,
                    state,
                    code,
                    state,
                    code,
                    now,
                    now,
                    job.job_id,
                    job.lease_owner_id,
                    job.lease_generation,
                ),
            ).fetchone()
            if row is None:
                raise TutorLeaseConflict("curation job lease is stale")
            self._append_audit(
                queue="curation",
                user_id=str(row["user_id"]),
                decision=state,
                code=code,
                details={},
                now=now,
                curation_job_id=job.job_id,
            )

    def retry_curation_job(
        self,
        *,
        job: TutorCurationJob,
        code: str,
        now: datetime,
        max_retry_attempts: int,
        retry_backoff_seconds: int,
    ) -> None:
        self._require_curation_lease(job)
        with self._conn.transaction():
            row = self._conn.execute(
                """
                UPDATE tutor_curation_jobs
                SET state = CASE WHEN attempt_count >= %s THEN 'failed' ELSE 'pending' END,
                    last_error_code = %s,
                    lease_owner_id = NULL,
                    lease_expires_at = NULL,
                    not_before = CASE WHEN attempt_count >= %s THEN not_before ELSE %s END,
                    terminal_at = CASE WHEN attempt_count >= %s THEN %s ELSE NULL END,
                    updated_at = %s
                WHERE id = %s
                  AND state = 'leased'
                  AND lease_owner_id = %s
                  AND lease_generation = %s
                RETURNING state, user_id::text AS user_id
                """,
                (
                    max_retry_attempts,
                    code,
                    max_retry_attempts,
                    now + timedelta(seconds=retry_backoff_seconds),
                    max_retry_attempts,
                    now,
                    now,
                    job.job_id,
                    job.lease_owner_id,
                    job.lease_generation,
                ),
            ).fetchone()
            if row is None:
                raise TutorLeaseConflict("curation job lease is stale")
            self._append_audit(
                queue="curation",
                user_id=str(row["user_id"]),
                decision="failed" if str(row["state"]) == "failed" else "retry",
                code=code,
                details={"attempt_count": job.attempt_count},
                now=now,
                curation_job_id=job.job_id,
            )

    def _recover_expired_curation_jobs(
        self, *, now: datetime, max_retry_attempts: int, retry_backoff_seconds: int
    ) -> None:
        rows = self._conn.execute(
            """
            UPDATE tutor_curation_jobs
            SET state = CASE WHEN attempt_count >= %s THEN 'failed' ELSE 'pending' END,
                last_error_code = 'lease_expired',
                lease_owner_id = NULL,
                lease_expires_at = NULL,
                not_before = CASE WHEN attempt_count >= %s THEN not_before ELSE %s END,
                terminal_at = CASE WHEN attempt_count >= %s THEN %s ELSE NULL END,
                updated_at = %s
            WHERE state = 'leased' AND lease_expires_at <= %s
            RETURNING id::text AS id, user_id::text AS user_id, state, attempt_count
            """,
            (
                max_retry_attempts,
                max_retry_attempts,
                now + timedelta(seconds=retry_backoff_seconds),
                max_retry_attempts,
                now,
                now,
                now,
            ),
        ).fetchall()
        for row in rows:
            self._append_audit(
                queue="curation",
                user_id=str(row["user_id"]),
                decision="failed" if str(row["state"]) == "failed" else "retry",
                code="lease_expired",
                details={"attempt_count": _as_int(row.get("attempt_count"), 0)},
                now=now,
                curation_job_id=str(row["id"]),
            )

    def _usage_for_queue(
        self,
        *,
        table: Literal["tutor_proactive_candidates", "tutor_curation_jobs"],
        started_column: Literal["run_started_at", "processor_started_at"],
        user_id: str,
        now: datetime,
        circuit_window_seconds: int,
    ) -> SchedulerUsage:
        day_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
        day_end = day_start + timedelta(days=1)
        row = self._conn.execute(
            f"""
            SELECT
              count(*) FILTER (WHERE state = 'leased' AND lease_expires_at > %s)::int AS active_leases,
              count(*) FILTER (WHERE {started_column} >= %s AND {started_column} < %s)::int AS started_today,
              count(*) FILTER (WHERE state = 'failed' AND terminal_at >= %s)::int AS failed_in_window,
              max(terminal_at) FILTER (WHERE state = 'completed') AS last_completed_at
            FROM {table}
            WHERE user_id = %s
            """,
            (now, day_start, day_end, now - timedelta(seconds=circuit_window_seconds), user_id),
        ).fetchone()
        if row is None:
            return SchedulerUsage(0, 0, 0, None)
        return SchedulerUsage(
            active_leases=_as_int(row.get("active_leases"), 0),
            started_today=_as_int(row.get("started_today"), 0),
            failed_in_circuit_window=_as_int(row.get("failed_in_window"), 0),
            last_completed_at=_as_datetime(row.get("last_completed_at")),
        )

    @staticmethod
    def _require_candidate_lease(candidate: TutorProactiveCandidate) -> None:
        if candidate.lease_owner_id is None or candidate.lease_generation <= 0:
            raise TutorLeaseConflict("proactive candidate lease is missing")

    @staticmethod
    def _require_curation_lease(job: TutorCurationJob) -> None:
        if job.lease_owner_id is None or job.lease_generation <= 0:
            raise TutorLeaseConflict("curation job lease is missing")

    def _append_audit(
        self,
        *,
        queue: Literal["proactive", "curation"],
        user_id: str,
        decision: str,
        code: str,
        details: Mapping[str, object],
        now: datetime,
        candidate_id: str | None = None,
        curation_job_id: str | None = None,
    ) -> None:
        safe_details = self._projector.project(dict(details))
        self._conn.execute(
            """
            INSERT INTO tutor_scheduler_audit (
              user_id, queue, candidate_id, curation_job_id, decision, code, details_json, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
            """,
            (user_id, queue, candidate_id, curation_job_id, decision, code, _json(safe_details), now),
        )


def _preference_from_row(row: Mapping[str, object]) -> TutorProactivePreference:
    return TutorProactivePreference(
        user_id=str(row["user_id"]),
        enabled=bool(row["enabled"]),
        hard_paused=bool(row["hard_paused"]),
        policy_version=str(row["policy_version"]),
        setting_version=str(row["setting_version"]),
    )


def _candidate_from_row(row: Mapping[str, object]) -> TutorProactiveCandidate:
    return TutorProactiveCandidate(
        candidate_id=str(row["id"]),
        signal_id=str(row["signal_id"]),
        user_id=str(row["user_id"]),
        candidate_kind=str(row["candidate_kind"]),
        dedupe_key=str(row["dedupe_key"]),
        dedupe_bucket_at=_as_datetime(row.get("dedupe_bucket_at")) or datetime.now(UTC),
        policy_version=str(row["policy_version"]),
        policy_fingerprint=str(row["policy_fingerprint"]),
        state=str(row["state"]),  # type: ignore[arg-type]
        no_action_code=_optional_str(row.get("no_action_code")),
        not_before=_as_datetime(row.get("not_before")) or datetime.now(UTC),
        attempt_count=_as_int(row.get("attempt_count"), 0),
        lease_owner_id=_optional_str(row.get("lease_owner_id")),
        lease_generation=_as_int(row.get("lease_generation"), 0),
        lease_expires_at=_as_datetime(row.get("lease_expires_at")),
        run_id=_optional_str(row.get("run_id")),
        run_started_at=_as_datetime(row.get("run_started_at")),
        terminal_at=_as_datetime(row.get("terminal_at")),
    )


def _curation_job_from_row(row: Mapping[str, object]) -> TutorCurationJob:
    return TutorCurationJob(
        job_id=str(row["id"]),
        outbox_id=str(row["outbox_id"]),
        user_id=str(row["user_id"]),
        policy_version=str(row["policy_version"]),
        memory_setting_version=str(row["memory_setting_version"]),
        state=str(row["state"]),  # type: ignore[arg-type]
        no_action_code=_optional_str(row.get("no_action_code")),
        not_before=_as_datetime(row.get("not_before")) or datetime.now(UTC),
        attempt_count=_as_int(row.get("attempt_count"), 0),
        lease_owner_id=_optional_str(row.get("lease_owner_id")),
        lease_generation=_as_int(row.get("lease_generation"), 0),
        lease_expires_at=_as_datetime(row.get("lease_expires_at")),
        processor_started_at=_as_datetime(row.get("processor_started_at")),
        terminal_at=_as_datetime(row.get("terminal_at")),
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


def _json(value: object) -> str:
    return json.dumps(value, default=_json_default, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.astimezone(UTC) if parsed.tzinfo else None
    return None


def _as_int(value: object, default: int) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None
