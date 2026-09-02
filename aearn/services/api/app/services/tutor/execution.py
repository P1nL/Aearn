"""API-side intent, durable-job, and safe-result boundary for Tutor execution.

This module intentionally owns no container client and never starts external
runtime work. Its effect handler runs in the Child 02 transaction solely to
validate a server-issued proof and insert or replay one durable job.
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Literal
from uuid import uuid4

from psycopg import Connection

from aearn_shared.execution import (
    ExecutionAction,
    ExecutionBudgetV1,
    ExecutionEffectProposalV1,
    ExecutionIntentProofV1,
    ExecutionJobState,
    ExecutionJobV1,
    RuntimeCatalogRegistryV1,
    SafeExecutionResultV1,
    SafeExecutionResultV2,
    SafeExecutionStatus,
    load_runtime_catalog_registry,
    parse_safe_execution_result,
    runtime_id_for_profile,
)
from app.agents.harness.contracts import (
    TutorEffectProposal,
    TutorEffectResult,
    TutorEffectStatus,
    TutorRunSnapshot,
    payload_mapping_from_fields,
)
from app.core.config import get_settings
from app.services.runners.runtime_contracts import RuntimeExecutionResult


EXECUTION_EFFECT_TYPE = "runner.execute"
_EXECUTOR_HEALTH_MAX_AGE_SECONDS = 90


class ExecutionSubmissionError(ValueError):
    """A stable internal denial/unavailability code with no raw diagnostics."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ExecutionAvailability:
    available: bool
    code: str
    runtime_id: str | None = None


class ExecutionIntentRepository:
    """Narrow API-side persistence adapter; it has no external runtime control."""

    def __init__(
        self,
        conn: Connection[dict[str, object]],
        *,
        registry: RuntimeCatalogRegistryV1 | None = None,
        executor_enabled: Callable[[], bool] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._conn = conn
        self._registry = registry or default_runtime_registry()
        self._executor_enabled = executor_enabled or (lambda: get_settings().tutor_executor_enabled)
        self._clock = clock or (lambda: datetime.now(UTC))

    def for_transaction(self, conn: Connection[dict[str, object]]) -> "ExecutionIntentRepository":
        """Bind handler work to the Child 02 transaction connection explicitly."""

        if conn is self._conn:
            return self
        return ExecutionIntentRepository(
            conn,
            registry=self._registry,
            executor_enabled=self._executor_enabled,
            clock=self._clock,
        )

    def issue_intent(
        self,
        *,
        user_id: str,
        run_id: str,
        source_message_id: str,
        exercise_id: str,
        action: ExecutionAction,
        budget: ExecutionBudgetV1,
        expires_in_seconds: int = 120,
        now: datetime | None = None,
    ) -> ExecutionIntentProofV1:
        """Issue an opaque interactive proof after validating trusted scope facts."""

        if expires_in_seconds < 1 or expires_in_seconds > 900:
            raise ValueError("execution proof expiry must be within 1..900 seconds")
        issued_at = _utc(now or self._clock())
        with self._conn.transaction():
            run = self._conn.execute(
                """
                SELECT id, user_id, conversation_id, origin, input_revision, cancelled_at,
                       terminal_outcome, catalog_digest, policy_fingerprint, policy_json, effect_count
                FROM tutor_runs
                WHERE id = %s AND user_id = %s
                FOR UPDATE
                """,
                (run_id, user_id),
            ).fetchone()
            if run is None:
                raise ExecutionSubmissionError("run_not_found")
            if str(run["origin"]) != "interactive":
                raise ExecutionSubmissionError("execution_origin_denied")
            if run.get("cancelled_at") is not None or run.get("terminal_outcome") is not None:
                raise ExecutionSubmissionError("run_not_active")
            source = self._conn.execute(
                """
                SELECT messages.id
                FROM tutor_run_input_events AS inputs
                JOIN tutor_messages AS messages
                  ON messages.id = inputs.message_id
                 AND messages.conversation_id = %s
                WHERE inputs.run_id = %s
                  AND inputs.message_id = %s
                  AND inputs.input_revision = %s
                """,
                (run["conversation_id"], run["id"], source_message_id, run["input_revision"]),
            ).fetchone()
            if source is None:
                raise ExecutionSubmissionError("source_scope_denied")
            exercise = self._conn.execute(
                """
                SELECT exercises.id
                FROM exercises
                WHERE exercises.id = %s
                  AND exercises.archived_at IS NULL
                  AND exercises.deleted_at IS NULL
                """,
                (exercise_id,),
            ).fetchone()
            if exercise is None:
                raise ExecutionSubmissionError("exercise_scope_denied")
            max_effects = _policy_max_effects(run.get("policy_json"))
            active_reservations = self._conn.execute(
                """
                SELECT count(*) AS count
                FROM tutor_execution_intents
                WHERE run_id = %s
                  AND consumed_at IS NULL
                  AND cancelled_at IS NULL
                  AND expires_at > %s
                """,
                (run["id"], issued_at),
            ).fetchone()
            active_reservation_count = _as_int(active_reservations.get("count") if active_reservations else 0)
            reserved_effect_count = _as_int(run.get("effect_count")) + active_reservation_count
            if max_effects < budget.max_execution_count or reserved_effect_count + budget.max_execution_count > max_effects:
                raise ExecutionSubmissionError("execution_budget_exhausted")
            proof = ExecutionIntentProofV1(
                proof_id=str(uuid4()),
                user_id=str(run["user_id"]),
                conversation_id=str(run["conversation_id"]),
                run_id=str(run["id"]),
                source_message_id=str(source["id"]),
                exercise_id=str(exercise["id"]),
                input_revision=_as_int(run["input_revision"]),
                origin="interactive",
                action=action,
                catalog_digest=str(run["catalog_digest"]),
                policy_fingerprint=str(run["policy_fingerprint"]),
                budget_fingerprint=budget.fingerprint,
                issued_at=issued_at,
                expires_at=issued_at + timedelta(seconds=expires_in_seconds),
            )
            self._conn.execute(
                """
                INSERT INTO tutor_execution_intents (
                  id, user_id, conversation_id, run_id, source_message_id, exercise_id,
                  input_revision, origin, action, catalog_digest, policy_fingerprint,
                  budget_fingerprint, budget_execution_count, issued_at, expires_at
                )
                VALUES (
                  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    proof.proof_id,
                    proof.user_id,
                    proof.conversation_id,
                    proof.run_id,
                    proof.source_message_id,
                    proof.exercise_id,
                    proof.input_revision,
                    proof.origin,
                    proof.action.value,
                    proof.catalog_digest,
                    proof.policy_fingerprint,
                    proof.budget_fingerprint,
                    budget.max_execution_count,
                    proof.issued_at,
                    proof.expires_at,
                ),
            )
        return proof

    def create_or_replay_exercise_job(
        self,
        *,
        user_id: str,
        attempt_id: str,
        submission_id: str,
        exercise_version_id: str,
        action: ExecutionAction,
        now: datetime | None = None,
    ) -> ExecutionJobV1:
        """Attach an exercise Attempt to the existing durable executor queue."""

        current = _utc(now or self._clock())
        existing = self._conn.execute(
            """
            SELECT jobs.*
            FROM tutor_exercise_execution_links AS links
            JOIN tutor_execution_jobs AS jobs ON jobs.id = links.execution_job_id
            WHERE links.attempt_id = %s AND links.user_id = %s
            """,
            (attempt_id, user_id),
        ).fetchone()
        if existing is not None:
            return _job_from_row(existing)
        source = self._conn.execute(
            """
            SELECT attempts.id, attempts.user_id, attempts.exercise_version_id,
                   submissions.id AS submission_id, submissions.content_hash,
                   versions.language_id, versions.runtime_profile_key, versions.content_hash,
                   rubrics.rubric_hash
            FROM tutor_exercise_attempts AS attempts
            JOIN tutor_exercise_attempt_submissions AS submissions
              ON (submissions.attempt_id, submissions.user_id, submissions.exercise_version_id) =
                 (attempts.id, attempts.user_id, attempts.exercise_version_id)
            JOIN tutor_exercise_versions AS versions ON versions.id = attempts.exercise_version_id
            JOIN tutor_exercise_private_rubrics AS rubrics ON rubrics.exercise_version_id = versions.id
            WHERE attempts.id = %s AND attempts.user_id = %s
              AND submissions.id = %s AND versions.id = %s
            FOR UPDATE OF attempts
            """,
            (attempt_id, user_id, submission_id, exercise_version_id),
        ).fetchone()
        if source is None:
            raise ExecutionSubmissionError("exercise_attempt_scope_denied")
        runtime_id = runtime_id_for_profile(
            runtime_tier=str(source["runtime_profile_key"]),
            language=str(source["language_id"]),
        )
        if runtime_id is None:
            raise ExecutionSubmissionError("trusted_runtime_unsupported")
        availability = self.availability_for_runtime(runtime_id, now=current)
        if not availability.available:
            raise ExecutionSubmissionError(availability.code)
        lock = self._registry.lock_for(runtime_id)
        if lock is None:
            raise ExecutionSubmissionError("runtime_lock_unavailable")
        intent_id = str(uuid4())
        job_id = str(uuid4())
        self._conn.execute(
            """
            INSERT INTO tutor_execution_intents (
              id, user_id, conversation_id, run_id, source_message_id, exercise_id,
              input_revision, origin, action, catalog_digest, policy_fingerprint,
              budget_fingerprint, budget_execution_count, issued_at, expires_at,
              consumed_at, consumed_by_effect_id, source_kind, exercise_attempt_id,
              exercise_submission_id, exercise_version_id
            ) VALUES (
              %s, %s, NULL, NULL, NULL, NULL, NULL, 'exercise_gate', %s, %s, %s,
              %s, 1, %s, %s, %s, NULL, 'exercise_submission', %s, %s, %s
            )
            """,
            (
                intent_id,
                user_id,
                action.value,
                self._registry.catalog_fingerprint,
                str(source["content_hash"]),
                _reference_hash("exercise-gate-budget-v1"),
                current,
                current + timedelta(seconds=120),
                current,
                attempt_id,
                submission_id,
                exercise_version_id,
            ),
        )
        row = self._conn.execute(
            """
            INSERT INTO tutor_execution_jobs (
              id, effect_record_id, effect_key, intent_id, user_id, conversation_id,
              run_id, runtime_id, lock_fingerprint, source_reference_hash,
              test_reference_hash, state, owner_kind, exercise_attempt_id
            ) VALUES (
              %s, NULL, NULL, %s, %s, NULL, NULL, %s, %s, %s, %s,
              'pending', 'exercise_attempt', %s
            ) RETURNING *
            """,
            (
                job_id,
                intent_id,
                user_id,
                runtime_id,
                lock.fingerprint,
                _reference_hash(submission_id),
                _reference_hash(str(source["rubric_hash"])),
                attempt_id,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("exercise execution job insert failed")
        self._conn.execute(
            """
            INSERT INTO tutor_exercise_execution_links (
              attempt_id, user_id, execution_intent_id, execution_job_id
            ) VALUES (%s, %s, %s, %s)
            """,
            (attempt_id, user_id, intent_id, job_id),
        )
        return _job_from_row(row)

    def read_exercise_safe_result(self, *, user_id: str, attempt_id: str) -> SafeExecutionResultV2 | None:
        row = self._conn.execute(
            """
            SELECT jobs.result_json
            FROM tutor_exercise_execution_links AS links
            JOIN tutor_execution_jobs AS jobs ON jobs.id = links.execution_job_id
            WHERE links.attempt_id = %s AND links.user_id = %s
            """,
            (attempt_id, user_id),
        ).fetchone()
        if row is None:
            raise ExecutionSubmissionError("execution_job_not_found")
        result = row.get("result_json")
        if not isinstance(result, Mapping):
            return None
        return _parse_stored_safe_result(result)

    def availability_for_runtime(self, runtime_id: str, *, now: datetime | None = None) -> ExecutionAvailability:
        """Read cached executor health only; this path never contacts the runtime engine."""

        if not self._executor_enabled():
            return ExecutionAvailability(False, "executor_feature_disabled", runtime_id)
        lock = self._registry.lock_for(runtime_id)
        if lock is None:
            return ExecutionAvailability(False, "runtime_lock_unavailable", runtime_id)
        current = _utc(now or self._clock())
        health = self._conn.execute(
            """
            SELECT status, registry_fingerprint, verified_runtime_ids_json,
                   availability_code, last_heartbeat_at
            FROM tutor_executor_health
            WHERE status = 'available'
              AND registry_fingerprint = %s
            ORDER BY last_heartbeat_at DESC
            LIMIT 1
            """,
            (self._registry.fingerprint,),
        ).fetchone()
        if health is None:
            return ExecutionAvailability(False, "executor_health_unavailable", runtime_id)
        heartbeat = health.get("last_heartbeat_at")
        if not isinstance(heartbeat, datetime) or _utc(heartbeat) < current - timedelta(seconds=_EXECUTOR_HEALTH_MAX_AGE_SECONDS):
            return ExecutionAvailability(False, "executor_health_stale", runtime_id)
        verified = health.get("verified_runtime_ids_json")
        verified_ids = tuple(str(item) for item in verified) if isinstance(verified, list | tuple) else ()
        if runtime_id not in verified_ids:
            return ExecutionAvailability(False, "runtime_health_unavailable", runtime_id)
        return ExecutionAvailability(True, "executor_available", runtime_id)

    def create_or_replay_job(
        self,
        *,
        run: TutorRunSnapshot,
        proposal: TutorEffectProposal,
        proof_id: str,
        now: datetime | None = None,
    ) -> ExecutionJobV1:
        """Create one job inside the caller-owned effect transaction, without launching it."""

        current = _utc(now or self._clock())
        proof = self._conn.execute(
            """
            SELECT *
            FROM tutor_execution_intents
            WHERE id = %s
            FOR UPDATE
            """,
            (proof_id,),
        ).fetchone()
        if proof is None:
            raise ExecutionSubmissionError("intent_proof_missing")
        run_evidence = self._conn.execute(
            """
            SELECT catalog_digest, policy_fingerprint
            FROM tutor_runs
            WHERE id = %s AND user_id = %s AND conversation_id = %s
            """,
            (run.run_id, run.user_id, run.conversation_id),
        ).fetchone()
        if run_evidence is None or not _proof_matches_run(
            proof=proof,
            run=run,
            proposal=proposal,
            run_evidence=run_evidence,
            now=current,
        ):
            raise ExecutionSubmissionError("intent_proof_denied")

        runtime = self._trusted_runtime_for_exercise(str(proof["exercise_id"]))
        availability = self.availability_for_runtime(runtime, now=current)
        if not availability.available:
            raise ExecutionSubmissionError(availability.code)
        lock = self._registry.lock_for(runtime)
        if lock is None:
            raise ExecutionSubmissionError("runtime_lock_unavailable")

        effect = self._conn.execute(
            """
            SELECT id
            FROM tutor_effects
            WHERE run_id = %s AND effect_id = %s AND effect_type = %s
            """,
            (run.run_id, proposal.effect_id, EXECUTION_EFFECT_TYPE),
        ).fetchone()
        if effect is None:
            raise ExecutionSubmissionError("effect_reservation_missing")
        existing = self._conn.execute(
            """
            SELECT * FROM tutor_execution_jobs
            WHERE effect_record_id = %s
            """,
            (effect["id"],),
        ).fetchone()
        if existing is not None:
            if str(existing["intent_id"]) != str(proof["id"]):
                raise ExecutionSubmissionError("execution_job_identity_conflict")
            return _job_from_row(existing)
        if run.effect_count >= run.policy.max_effects:
            raise ExecutionSubmissionError("execution_budget_exhausted")
        if proof.get("consumed_at") is not None or proof.get("consumed_by_effect_id") is not None:
            raise ExecutionSubmissionError("intent_proof_consumed")

        job_id = str(uuid4())
        source_reference_hash = _reference_hash(str(proof["source_message_id"]))
        test_reference_hash = _reference_hash(str(proof["exercise_id"]))
        row = self._conn.execute(
            """
            INSERT INTO tutor_execution_jobs (
              id, effect_record_id, effect_key, intent_id, user_id, conversation_id,
              run_id, runtime_id, lock_fingerprint, source_reference_hash,
              test_reference_hash, state
            )
            VALUES (
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending'
            )
            RETURNING *
            """,
            (
                job_id,
                effect["id"],
                proposal.effect_id,
                proof["id"],
                proof["user_id"],
                proof["conversation_id"],
                proof["run_id"],
                runtime,
                lock.fingerprint,
                source_reference_hash,
                test_reference_hash,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("execution job insert failed")
        consumed = self._conn.execute(
            """
            UPDATE tutor_execution_intents
            SET consumed_at = %s, consumed_by_effect_id = %s
            WHERE id = %s AND consumed_at IS NULL AND consumed_by_effect_id IS NULL
            RETURNING id
            """,
            (current, effect["id"], proof["id"]),
        ).fetchone()
        if consumed is None:
            raise ExecutionSubmissionError("intent_proof_consumption_failed")
        return _job_from_row(row)

    def request_cancellation(self, *, user_id: str, run_id: str, job_id: str, now: datetime | None = None) -> None:
        """Idempotently record cancellation; an executor observes it after claim."""

        with self._conn.transaction():
            row = self._conn.execute(
                """
                UPDATE tutor_execution_jobs AS jobs
                SET cancellation_requested_at = COALESCE(jobs.cancellation_requested_at, %s)
                FROM tutor_runs AS runs
                WHERE jobs.id = %s
                  AND jobs.run_id = runs.id
                  AND runs.user_id = %s
                  AND jobs.run_id = %s
                  AND jobs.state NOT IN (
                    'completed', 'timed_out', 'cancelled', 'unavailable', 'launch_uncertain', 'failed'
                  )
                RETURNING jobs.id
                """,
                (_utc(now or self._clock()), job_id, user_id, run_id),
            ).fetchone()
            if row is None:
                found = self._conn.execute(
                    """
                    SELECT jobs.id
                    FROM tutor_execution_jobs AS jobs
                    JOIN tutor_runs AS runs ON runs.id = jobs.run_id
                    WHERE jobs.id = %s AND jobs.run_id = %s AND runs.user_id = %s
                    """,
                    (job_id, run_id, user_id),
                ).fetchone()
                if found is None:
                    raise ExecutionSubmissionError("execution_job_not_found")

    def read_safe_result(self, *, user_id: str, run_id: str, job_id: str) -> SafeExecutionResultV2 | None:
        row = self._conn.execute(
            """
            SELECT jobs.result_json
            FROM tutor_execution_jobs AS jobs
            JOIN tutor_runs AS runs ON runs.id = jobs.run_id
            WHERE jobs.id = %s AND jobs.run_id = %s AND runs.user_id = %s
            """,
            (job_id, run_id, user_id),
        ).fetchone()
        if row is None:
            raise ExecutionSubmissionError("execution_job_not_found")
        result = row.get("result_json")
        if not isinstance(result, Mapping):
            return None
        return _parse_stored_safe_result(result)

    def _trusted_runtime_for_exercise(self, exercise_id: str) -> str:
        row = self._conn.execute(
            """
            SELECT runtime_profiles.runtime_tier, runtime_profiles.language
            FROM exercises
            JOIN runtime_profiles ON runtime_profiles.id = exercises.runtime_profile_id
            WHERE exercises.id = %s
              AND exercises.archived_at IS NULL
              AND exercises.deleted_at IS NULL
              AND runtime_profiles.archived_at IS NULL
            """,
            (exercise_id,),
        ).fetchone()
        if row is None:
            raise ExecutionSubmissionError("trusted_runtime_unavailable")
        runtime = runtime_id_for_profile(runtime_tier=str(row["runtime_tier"]), language=str(row["language"]))
        if runtime is None:
            raise ExecutionSubmissionError("trusted_runtime_unsupported")
        return runtime


class ExecutionEffectHandler:
    """Child 02 in-transaction handler that only persists one execution job."""

    def __init__(self, repository: ExecutionIntentRepository) -> None:
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
        try:
            request = ExecutionEffectProposalV1.model_validate(payload)
            job = self._repository.for_transaction(conn).create_or_replay_job(
                run=run,
                proposal=proposal,
                proof_id=request.intent_proof_id,
            )
        except (ExecutionSubmissionError, ValueError):
            return TutorEffectResult(effect_id=proposal.effect_id, status=TutorEffectStatus.DENIED)
        return TutorEffectResult(effect_id=proposal.effect_id, status=TutorEffectStatus.COMMITTED, commit_id=job.job_id)


def build_execution_effect_handlers(repository: ExecutionIntentRepository) -> dict[str, ExecutionEffectHandler]:
    """Explicit composition helper; callers still retain the feature-disabled gate."""

    return {EXECUTION_EFFECT_TYPE: ExecutionEffectHandler(repository)}


def safe_result_to_runtime_execution_result(
    result: SafeExecutionResultV1 | SafeExecutionResultV2,
) -> RuntimeExecutionResult:
    """Pure adapter to the existing runner-result authority without invoking a legacy runner."""

    result = parse_safe_execution_result(result)
    status = result.status
    runtime_status = {
        SafeExecutionStatus.SUCCESS: "success",
        SafeExecutionStatus.COMPILE_ERROR: "compile_error",
        SafeExecutionStatus.RUNTIME_ERROR: "runtime_error",
        SafeExecutionStatus.TIMEOUT: "timeout",
        SafeExecutionStatus.CANCELLED: "runtime_error",
        SafeExecutionStatus.UNSUPPORTED: "unsupported",
        SafeExecutionStatus.UNAVAILABLE: "unsupported",
        SafeExecutionStatus.FAILED: "runtime_error",
    }[status]
    total = result.total_test_count
    passed = result.passed_test_count
    pass_rate = 0.0 if total == 0 else round(passed / total, 4)
    tests: list[dict[str, object]] = [
        {
            "case_id": item.case_id,
            "case_type": "visible" if item.visible else "hidden",
            "passed": item.passed,
            "weight": 1.0,
            "is_critical": False,
            "duration_ms": item.duration_ms,
            "message": item.message,
        }
        for item in result.test_feedback
    ]
    success = status is SafeExecutionStatus.SUCCESS and (total == 0 or passed == total)
    return RuntimeExecutionResult(
        runtime_status=runtime_status,
        stdout=result.stdout,
        stderr=result.stderr,
        test_pass_rate=pass_rate,
        passed_test_count=passed,
        total_test_count=total,
        test_results=tests,
        error_message=None if success else _safe_error_message(status),
        next_action="advance_next" if success else "retry_same",
        preview_html=None,
        core_blank_gate=success,
        any_blank_passed=passed > 0,
        logic_pass=success,
        presentation=(
            result.presentation.model_dump(mode="json")
            if result.presentation.kind == "table_result_v1"
            else None
        ),
    )


@lru_cache
def default_runtime_registry() -> RuntimeCatalogRegistryV1:
    root = _executor_infra_root()
    return load_runtime_catalog_registry(
        catalog_path=root / "runtime-catalog.json",
        image_locks_path=root / "image-locks.json",
    )


def _executor_infra_root() -> Path:
    for ancestor in Path(__file__).resolve().parents:
        candidate = ancestor / "infra" / "executor"
        if candidate.is_dir():
            return candidate
    raise RuntimeError("executor infrastructure registry is missing")


def _proof_matches_run(
    *,
    proof: Mapping[str, object],
    run: TutorRunSnapshot,
    proposal: TutorEffectProposal,
    run_evidence: Mapping[str, object],
    now: datetime,
) -> bool:
    expires_at = proof.get("expires_at")
    return (
        str(proof.get("user_id")) == run.user_id
        and str(proof.get("conversation_id")) == run.conversation_id
        and str(proof.get("run_id")) == run.run_id
        and str(proof.get("origin")) == "interactive"
        and _as_int(proof.get("input_revision")) == run.input_revision == proposal.expected_input_revision
        and str(proof.get("catalog_digest")) == str(run_evidence.get("catalog_digest"))
        and str(proof.get("policy_fingerprint")) == str(run_evidence.get("policy_fingerprint"))
        and proof.get("cancelled_at") is None
        and proof.get("consumed_at") is None
        and proof.get("consumed_by_effect_id") is None
        and isinstance(expires_at, datetime)
        and _utc(expires_at) > now
    )


def _job_from_row(row: Mapping[str, object]) -> ExecutionJobV1:
    result_json = row.get("result_json")
    result = _parse_stored_safe_result(result_json) if isinstance(result_json, Mapping) else None
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
        intent_proof_id=str(row["intent_id"]),
        user_id=str(row["user_id"]),
        runtime_id=str(row["runtime_id"]),
        owner_kind=owner_kind,
        effect_id=str(row["effect_key"]) if row.get("effect_key") else None,
        conversation_id=str(row["conversation_id"]) if row.get("conversation_id") else None,
        run_id=str(row["run_id"]) if row.get("run_id") else None,
        exercise_attempt_id=str(row["exercise_attempt_id"]) if row.get("exercise_attempt_id") else None,
        model_review_validation_id=str(row["model_review_validation_id"])
        if row.get("model_review_validation_id")
        else None,
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


def _reference_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _parse_stored_safe_result(value: Mapping[str, object]) -> SafeExecutionResultV2:
    try:
        return parse_safe_execution_result(value)
    except (TypeError, ValueError) as exc:
        raise ExecutionSubmissionError("stored_result_invalid") from exc


def _policy_max_effects(value: object) -> int:
    if not isinstance(value, Mapping):
        return 0
    return _as_int(value.get("max_effects"))


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


def _safe_error_message(status: SafeExecutionStatus) -> str:
    if status is SafeExecutionStatus.TIMEOUT:
        return "Execution reached its time limit."
    if status is SafeExecutionStatus.CANCELLED:
        return "Execution was cancelled."
    if status in {SafeExecutionStatus.UNAVAILABLE, SafeExecutionStatus.UNSUPPORTED}:
        return "This execution runtime is not available."
    return "Execution did not complete successfully."
