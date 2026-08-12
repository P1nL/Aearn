"""PostgreSQL job lifecycle for the privileged executor process only."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from aearn_shared.execution import (
    ExecutionHealthV1,
    ExecutionJobClaimV1,
    ExecutionJobState,
    ExecutionJobV1,
    SafeExecutionResultV1,
    SafeExecutionStatus,
)
from psycopg import Connection

from aearn_executor.runtime import (
    ClaimedExecutionJob,
    ExecutionJobStoreError,
    LaunchReservation,
)

_TERMINAL_STATES = frozenset(
    {
        ExecutionJobState.COMPLETED.value,
        ExecutionJobState.TIMED_OUT.value,
        ExecutionJobState.CANCELLED.value,
        ExecutionJobState.UNAVAILABLE.value,
        ExecutionJobState.LAUNCH_UNCERTAIN.value,
        ExecutionJobState.FAILED.value,
    }
)


class PostgresExecutionJobStore:
    """Durable queue owner. A broker may wake this service but cannot replace this table."""

    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn

    def claim_next(
        self,
        *,
        executor_id: str,
        now: datetime,
        lease_seconds: int,
    ) -> ClaimedExecutionJob | None:
        """Claim pending work or safely reclaim an expired, unreserved lease."""

        expiry = _utc(now) + timedelta(seconds=lease_seconds)
        with self._conn.transaction():
            row = self._conn.execute(
                """
                SELECT jobs.*, intents.cancelled_at AS intent_cancelled_at,
                       runs.cancelled_at AS run_cancelled_at
                FROM tutor_execution_jobs AS jobs
                JOIN tutor_execution_intents AS intents ON intents.id = jobs.intent_id
                LEFT JOIN tutor_runs AS runs ON runs.id = jobs.run_id
                WHERE (
                  (jobs.state = 'pending'
                   AND (jobs.lease_expires_at IS NULL OR jobs.lease_expires_at <= %s))
                  OR (
                    jobs.state = 'claimed'
                    AND jobs.launch_token IS NULL
                    AND jobs.lease_expires_at IS NOT NULL
                    AND jobs.lease_expires_at <= %s
                  )
                )
                ORDER BY jobs.created_at ASC
                FOR UPDATE OF jobs SKIP LOCKED
                LIMIT 1
                """,
                (_utc(now), _utc(now)),
            ).fetchone()
            if row is None:
                return None
            if _is_cancelled(row):
                self._terminalize_locked(
                    row=row,
                    executor_id=executor_id,
                    lease_generation=_as_int(row.get("lease_generation")),
                    result=SafeExecutionResultV1(
                        status=SafeExecutionStatus.CANCELLED,
                        diagnostic_code="execution_cancelled_before_claim",
                    ),
                    state=ExecutionJobState.CANCELLED,
                    now=now,
                    cleanup_state="not_required",
                )
                return None
            generation = _as_int(row.get("lease_generation")) + 1
            updated = self._conn.execute(
                """
                UPDATE tutor_execution_jobs
                SET state = 'claimed', lease_owner_id = %s, lease_generation = %s,
                    lease_expires_at = %s
                WHERE id = %s
                  AND (
                    (state = 'pending' AND (lease_expires_at IS NULL OR lease_expires_at <= %s))
                    OR (
                      state = 'claimed'
                      AND launch_token IS NULL
                      AND lease_expires_at IS NOT NULL
                      AND lease_expires_at <= %s
                    )
                  )
                RETURNING *
                """,
                (executor_id, generation, expiry, row["id"], _utc(now), _utc(now)),
            ).fetchone()
            if updated is None:
                return None
            self._append_attempt_locked(
                job_id=str(updated["id"]),
                executor_id=executor_id,
                lease_generation=generation,
                launch_generation=_as_int(updated.get("launch_generation")),
                stage="claimed",
                lock_fingerprint=str(updated["lock_fingerprint"]),
                code="job_reclaimed" if str(row["state"]) == ExecutionJobState.CLAIMED.value else "job_claimed",
            )
            job = _job_from_row(updated)
            return ClaimedExecutionJob(
                job=job,
                claim=ExecutionJobClaimV1(
                    job_id=job.job_id,
                    executor_id=executor_id,
                    lease_generation=generation,
                    lease_expires_at=expiry,
                ),
            )

    def claim_reserved_for_recovery(
        self,
        *,
        executor_id: str,
        now: datetime,
        lease_seconds: int,
    ) -> ClaimedExecutionJob | None:
        """Adopt only an existing reserved launch; it never reopens pending work."""

        expiry = _utc(now) + timedelta(seconds=lease_seconds)
        with self._conn.transaction():
            row = self._conn.execute(
                """
                SELECT *
                FROM tutor_execution_jobs
                WHERE state = 'launch_reserved'
                  AND (lease_expires_at IS NULL OR lease_expires_at <= %s)
                ORDER BY launch_reserved_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """,
                (_utc(now),),
            ).fetchone()
            if row is None:
                return None
            generation = _as_int(row.get("lease_generation")) + 1
            updated = self._conn.execute(
                """
                UPDATE tutor_execution_jobs
                SET lease_owner_id = %s, lease_generation = %s, lease_expires_at = %s
                WHERE id = %s AND state = 'launch_reserved'
                RETURNING *
                """,
                (executor_id, generation, expiry, row["id"]),
            ).fetchone()
            if updated is None:
                return None
            job = _job_from_row(updated)
            return ClaimedExecutionJob(
                job=job,
                claim=ExecutionJobClaimV1(
                    job_id=job.job_id,
                    executor_id=executor_id,
                    lease_generation=generation,
                    lease_expires_at=expiry,
                ),
            )

    def reserve_launch(self, *, claimed: ClaimedExecutionJob, now: datetime) -> LaunchReservation | None:
        """Allocate the sole immutable launch token before any external action."""

        with self._conn.transaction():
            row = self._lock_job_for_claim(claimed.claim)
            if _is_cancelled(row):
                self._terminalize_locked(
                    row=row,
                    executor_id=claimed.claim.executor_id,
                    lease_generation=claimed.claim.lease_generation,
                    result=SafeExecutionResultV1(
                        status=SafeExecutionStatus.CANCELLED,
                        diagnostic_code="execution_cancelled_before_launch",
                    ),
                    state=ExecutionJobState.CANCELLED,
                    now=now,
                    cleanup_state="not_required",
                )
                return None
            if str(row["state"]) != ExecutionJobState.CLAIMED.value or row.get("launch_token") is not None:
                raise ExecutionJobStoreError("launch reservation is no longer eligible")
            token = uuid4().hex
            updated = self._conn.execute(
                """
                UPDATE tutor_execution_jobs
                SET state = 'launch_reserved', launch_token = %s,
                    launch_generation = %s, launch_reserved_at = %s
                WHERE id = %s
                  AND state = 'claimed'
                  AND launch_token IS NULL
                  AND lease_owner_id = %s
                  AND lease_generation = %s
                  AND lease_expires_at > %s
                RETURNING *
                """,
                (
                    token,
                    claimed.claim.lease_generation,
                    _utc(now),
                    row["id"],
                    claimed.claim.executor_id,
                    claimed.claim.lease_generation,
                    _utc(now),
                ),
            ).fetchone()
            if updated is None:
                raise ExecutionJobStoreError("launch reservation failed or executor lease expired")
            self._append_attempt_locked(
                job_id=str(updated["id"]),
                executor_id=claimed.claim.executor_id,
                lease_generation=claimed.claim.lease_generation,
                launch_generation=claimed.claim.lease_generation,
                stage="launch_reserved",
                lock_fingerprint=str(updated["lock_fingerprint"]),
                code="launch_reserved",
            )
            job = _job_from_row(updated)
            return LaunchReservation(job=job, claim=claimed.claim)

    def mark_running(self, *, reservation: LaunchReservation, now: datetime) -> ExecutionJobV1:
        with self._conn.transaction():
            row = self._lock_job_for_claim(reservation.claim)
            if str(row["state"]) != ExecutionJobState.LAUNCH_RESERVED.value:
                raise ExecutionJobStoreError("launch is not reserved")
            if str(row.get("launch_token") or "") != str(reservation.job.launch_token or ""):
                raise ExecutionJobStoreError("launch token changed")
            updated = self._conn.execute(
                """
                UPDATE tutor_execution_jobs
                SET state = 'running', started_at = COALESCE(started_at, %s)
                WHERE id = %s
                RETURNING *
                """,
                (_utc(now), row["id"]),
            ).fetchone()
            if updated is None:
                raise ExecutionJobStoreError("running transition failed")
            self._append_attempt_locked(
                job_id=str(updated["id"]),
                executor_id=reservation.claim.executor_id,
                lease_generation=reservation.claim.lease_generation,
                launch_generation=_as_int(updated.get("launch_generation")),
                stage="running",
                lock_fingerprint=str(updated["lock_fingerprint"]),
                code="container_running",
            )
            return _job_from_row(updated)

    def mark_unavailable(self, *, claimed: ClaimedExecutionJob, code: str, now: datetime) -> None:
        with self._conn.transaction():
            row = self._lock_job_for_claim(claimed.claim)
            self._terminalize_locked(
                row=row,
                executor_id=claimed.claim.executor_id,
                lease_generation=claimed.claim.lease_generation,
                result=SafeExecutionResultV1(status=SafeExecutionStatus.UNAVAILABLE, diagnostic_code=code),
                state=ExecutionJobState.UNAVAILABLE,
                now=now,
                cleanup_state="not_required",
            )

    def mark_launch_uncertain(self, *, reservation: LaunchReservation, now: datetime) -> None:
        with self._conn.transaction():
            row = self._lock_job_for_claim(reservation.claim)
            self._terminalize_locked(
                row=row,
                executor_id=reservation.claim.executor_id,
                lease_generation=reservation.claim.lease_generation,
                result=SafeExecutionResultV1(
                    status=SafeExecutionStatus.FAILED,
                    diagnostic_code="launch_uncertain",
                ),
                state=ExecutionJobState.LAUNCH_UNCERTAIN,
                now=now,
                cleanup_state="pending",
            )

    def complete(
        self,
        *,
        reservation: LaunchReservation,
        result: SafeExecutionResultV1,
        now: datetime,
    ) -> None:
        with self._conn.transaction():
            row = self._lock_job_for_claim(reservation.claim)
            state = _terminal_state_for_result(result)
            self._terminalize_locked(
                row=row,
                executor_id=reservation.claim.executor_id,
                lease_generation=reservation.claim.lease_generation,
                result=result,
                state=state,
                now=now,
                cleanup_state="pending",
            )

    def record_cleanup(self, *, reservation: LaunchReservation, succeeded: bool, now: datetime) -> None:
        with self._conn.transaction():
            row = self._lock_job_for_claim(reservation.claim, allow_terminal=True)
            if succeeded:
                self._conn.execute(
                    "UPDATE tutor_execution_jobs SET cleanup_state = 'completed' WHERE id = %s",
                    (row["id"],),
                )
                self._append_attempt_locked(
                    job_id=str(row["id"]),
                    executor_id=reservation.claim.executor_id,
                    lease_generation=reservation.claim.lease_generation,
                    launch_generation=_as_int(row.get("launch_generation")),
                    stage="cleanup",
                    lock_fingerprint=str(row["lock_fingerprint"]),
                    code="cleanup_completed",
                    cleanup_state="completed",
                )
                return
            self._terminalize_locked(
                row=row,
                executor_id=reservation.claim.executor_id,
                lease_generation=reservation.claim.lease_generation,
                result=SafeExecutionResultV1(status=SafeExecutionStatus.FAILED, diagnostic_code="cleanup_failed"),
                state=ExecutionJobState.FAILED,
                now=now,
                cleanup_state="failed",
            )

    def cancellation_requested(self, *, job_id: str) -> bool:
        row = self._conn.execute(
            """
            SELECT jobs.cancellation_requested_at, intents.cancelled_at AS intent_cancelled_at,
                   runs.cancelled_at AS run_cancelled_at
            FROM tutor_execution_jobs AS jobs
            JOIN tutor_execution_intents AS intents ON intents.id = jobs.intent_id
            JOIN tutor_runs AS runs ON runs.id = jobs.run_id
            WHERE jobs.id = %s
            """,
            (job_id,),
        ).fetchone()
        return row is not None and _is_cancelled(row)

    def record_health(self, health: ExecutionHealthV1) -> None:
        self._conn.execute(
            """
            INSERT INTO tutor_executor_health (
              executor_id, service_version, registry_fingerprint, verified_runtime_ids_json,
              status, availability_code, last_heartbeat_at
            )
            VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s)
            ON CONFLICT (executor_id) DO UPDATE SET
              service_version = EXCLUDED.service_version,
              registry_fingerprint = EXCLUDED.registry_fingerprint,
              verified_runtime_ids_json = EXCLUDED.verified_runtime_ids_json,
              status = EXCLUDED.status,
              availability_code = EXCLUDED.availability_code,
              last_heartbeat_at = EXCLUDED.last_heartbeat_at
            """,
            (
                health.executor_id,
                health.service_version,
                health.registry_fingerprint,
                json.dumps(list(health.verified_runtime_ids)),
                health.status,
                health.availability_code,
                health.last_heartbeat_at,
            ),
        )

    def quarantine(self, *, health: ExecutionHealthV1, code: str, now: datetime) -> None:
        self.record_health(
            ExecutionHealthV1(
                executor_id=health.executor_id,
                service_version=health.service_version,
                registry_fingerprint=health.registry_fingerprint,
                status="quarantined",
                verified_runtime_ids=(),
                availability_code=code,
                last_heartbeat_at=_utc(now),
            )
        )

    def _lock_job_for_claim(
        self,
        claim: ExecutionJobClaimV1,
        *,
        allow_terminal: bool = False,
    ) -> Mapping[str, object]:
        row = self._conn.execute(
            """
            SELECT jobs.*, intents.cancelled_at AS intent_cancelled_at,
                   runs.cancelled_at AS run_cancelled_at
            FROM tutor_execution_jobs AS jobs
            JOIN tutor_execution_intents AS intents ON intents.id = jobs.intent_id
            JOIN tutor_runs AS runs ON runs.id = jobs.run_id
            WHERE jobs.id = %s
              AND jobs.lease_owner_id = %s
              AND jobs.lease_generation = %s
            FOR UPDATE OF jobs
            """,
            (claim.job_id, claim.executor_id, claim.lease_generation),
        ).fetchone()
        if row is None:
            raise ExecutionJobStoreError("executor lease is no longer current")
        if not allow_terminal and str(row["state"]) in _TERMINAL_STATES:
            raise ExecutionJobStoreError("execution job is already terminal")
        return row

    def _terminalize_locked(
        self,
        *,
        row: Mapping[str, object],
        executor_id: str,
        lease_generation: int,
        result: SafeExecutionResultV1,
        state: ExecutionJobState,
        now: datetime,
        cleanup_state: str,
    ) -> None:
        payload = result.model_dump(mode="json")
        result_hash = _fingerprint(payload)
        self._conn.execute(
            """
            UPDATE tutor_execution_jobs
            SET state = %s,
                result_json = %s::jsonb,
                result_hash = %s,
                safe_diagnostic_code = %s,
                cleanup_state = %s,
                terminal_at = COALESCE(terminal_at, %s)
            WHERE id = %s
            """,
            (state.value, json.dumps(payload), result_hash, result.diagnostic_code, cleanup_state, _utc(now), row["id"]),
        )
        self._append_attempt_locked(
            job_id=str(row["id"]),
            executor_id=executor_id,
            lease_generation=lease_generation,
            launch_generation=_as_int(row.get("launch_generation")),
            stage="terminal",
            lock_fingerprint=str(row["lock_fingerprint"]),
            code=result.diagnostic_code,
            result_hash=result_hash,
            cleanup_state=cleanup_state,
            duration_ms=result.duration_ms,
            output_bytes=len(result.stdout.encode("utf-8")) + len(result.stderr.encode("utf-8")),
        )

    def _append_attempt_locked(
        self,
        *,
        job_id: str,
        executor_id: str,
        lease_generation: int,
        launch_generation: int,
        stage: str,
        lock_fingerprint: str,
        code: str,
        result_hash: str | None = None,
        cleanup_state: str = "pending",
        duration_ms: int = 0,
        output_bytes: int = 0,
    ) -> None:
        sequence_row = self._conn.execute(
            "SELECT COALESCE(MAX(attempt_sequence), 0) + 1 AS next_sequence FROM tutor_execution_attempts WHERE job_id = %s",
            (job_id,),
        ).fetchone()
        sequence = _as_int(sequence_row["next_sequence"] if sequence_row else 1)
        self._conn.execute(
            """
            INSERT INTO tutor_execution_attempts (
              job_id, attempt_sequence, executor_id, lease_generation, launch_generation,
              stage, lock_fingerprint, safe_diagnostic_code, duration_ms, output_bytes,
              cleanup_state, result_hash
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                job_id,
                sequence,
                executor_id,
                lease_generation,
                launch_generation,
                stage,
                lock_fingerprint,
                code,
                duration_ms,
                output_bytes,
                cleanup_state,
                result_hash,
            ),
        )


def _job_from_row(row: Mapping[str, object]) -> ExecutionJobV1:
    result_value = row.get("result_json")
    result = SafeExecutionResultV1.model_validate(result_value) if isinstance(result_value, Mapping) else None
    lease_expires_at = _datetime_or_none(row.get("lease_expires_at"))
    cancellation_requested_at = _datetime_or_none(row.get("cancellation_requested_at"))
    raw_owner = str(row.get("owner_kind") or "tutor_effect")
    owner_kind: Literal["tutor_effect", "exercise_attempt", "model_review_validation"] = (
        "exercise_attempt"
        if raw_owner == "exercise_attempt"
        else "model_review_validation"
        if raw_owner == "model_review_validation"
        else "tutor_effect"
    )
    return ExecutionJobV1(
        job_id=str(row["id"]),
        effect_id=str(row["effect_key"]) if row.get("effect_key") else None,
        intent_proof_id=str(row["intent_id"]),
        user_id=str(row["user_id"]),
        owner_kind=owner_kind,
        conversation_id=str(row["conversation_id"]) if row.get("conversation_id") else None,
        run_id=str(row["run_id"]) if row.get("run_id") else None,
        exercise_attempt_id=str(row["exercise_attempt_id"]) if row.get("exercise_attempt_id") else None,
        model_review_validation_id=str(row["model_review_validation_id"])
        if row.get("model_review_validation_id")
        else None,
        runtime_id=str(row["runtime_id"]),
        lock_fingerprint=str(row["lock_fingerprint"]),
        state=ExecutionJobState(str(row["state"])),
        lease_owner_id=str(row["lease_owner_id"]) if row.get("lease_owner_id") else None,
        lease_generation=_as_int(row.get("lease_generation")),
        lease_expires_at=lease_expires_at,
        launch_token=str(row["launch_token"]) if row.get("launch_token") else None,
        launch_generation=_as_int(row.get("launch_generation")),
        cancellation_requested_at=cancellation_requested_at,
        result=result,
        safe_diagnostic_code=str(row["safe_diagnostic_code"]) if row.get("safe_diagnostic_code") else None,
    )


def _terminal_state_for_result(result: SafeExecutionResultV1) -> ExecutionJobState:
    if result.status is SafeExecutionStatus.SUCCESS:
        return ExecutionJobState.COMPLETED
    if result.status is SafeExecutionStatus.TIMEOUT:
        return ExecutionJobState.TIMED_OUT
    if result.status is SafeExecutionStatus.CANCELLED:
        return ExecutionJobState.CANCELLED
    if result.status in {SafeExecutionStatus.UNAVAILABLE, SafeExecutionStatus.UNSUPPORTED}:
        return ExecutionJobState.UNAVAILABLE
    return ExecutionJobState.FAILED


def _is_cancelled(row: Mapping[str, object]) -> bool:
    return any(
        row.get(key) is not None
        for key in ("cancellation_requested_at", "intent_cancelled_at", "run_cancelled_at")
    )


def _fingerprint(value: object) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _datetime_or_none(value: object) -> datetime | None:
    return value if isinstance(value, datetime) else None


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if not isinstance(value, (int, float, str)):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
