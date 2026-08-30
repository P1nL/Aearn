"""Tutor persistence 的 dispatch 职责实现。"""
# ruff: noqa: F403, F405
from __future__ import annotations

from ._namespace import *
from ._mixin import PersistenceMixin


class DispatchPersistenceMixin(PersistenceMixin):
    """由 PostgresTutorRepository 组合的内部职责 mixin。"""

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
        runtime_kind: Literal["harness_v1", "codex_sidecar_v1"] | None = None,
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
            if runtime_kind is not None:
                query += " AND runs.runtime_kind = %s"
                params.append(runtime_kind)
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
