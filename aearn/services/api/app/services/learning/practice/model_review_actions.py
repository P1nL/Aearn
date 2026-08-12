"""Controlled Action adapter and verifier for model review publication validation."""
from __future__ import annotations

from datetime import UTC, datetime

from psycopg import Connection

from app.agents.harness.actions import (
    ActionAuthorityKind,
    ActionAuthorityReference,
    ActionDescriptor,
    ActionExecutionResult,
    ActionExecutionStatus,
    ActionInvocation,
    ActionVerificationResult,
    ActionVerificationStatus,
)
from app.services.learning.practice.model_review_repository import (
    ModelReviewRepositoryError,
    PostgresModelReviewRepository,
)


class ModelReviewValidationActionAdapter:
    """Create/replay a durable validation job and project only opaque authority."""

    def __init__(self, conn: Connection[dict[str, object]], *, clock=None) -> None:
        self._conn = conn
        self._repository = PostgresModelReviewRepository(conn)
        self._clock = clock or (lambda: datetime.now(UTC))

    def execute(self, invocation: ActionInvocation) -> ActionExecutionResult:
        candidate_id = str(invocation.arguments.get("candidate_id") or "")
        candidate_hash = str(invocation.arguments.get("candidate_hash") or "")
        profile = str(invocation.arguments.get("validation_profile_version") or "")
        row = self._conn.execute(
            """
            SELECT * FROM tutor_model_review_validation_runs
            WHERE candidate_id = %s AND user_id = %s AND candidate_hash = %s
              AND validation_profile_version = %s
            """,
            (candidate_id, invocation.user_id, candidate_hash, profile),
        ).fetchone()
        if row is None:
            return _failed("model_review_validation_scope_missing")
        validation = self._repository.read_validation(
            validation_id=str(row["id"]), user_id=invocation.user_id
        )
        candidate = self._repository.read_candidate(
            candidate_id=candidate_id, user_id=invocation.user_id
        )
        if validation.state == "verified" and validation.authority_hash:
            return _success(validation.validation_id, validation.authority_hash)
        if validation.state in {"failed", "stale"}:
            return _failed("model_review_validation_failed")
        try:
            job = self._repository.create_or_replay_validation_job(
                validation=validation,
                invocation=invocation,
                candidate=candidate,
                now=self._clock(),
            )
        except Exception as exc:
            code = getattr(exc, "code", "model_review_executor_unavailable")
            return ActionExecutionResult(
                status=ActionExecutionStatus.RETRYABLE_FAILED,
                safe_summary="Model review validation executor is not ready.",
                diagnostic_code=str(code),
            )
        if job.state.value not in {"completed", "timed_out", "cancelled", "unavailable", "launch_uncertain", "failed"}:
            return ActionExecutionResult(
                status=ActionExecutionStatus.RETRYABLE_FAILED,
                safe_summary="Model review validation is still running.",
                diagnostic_code="model_review_validation_pending",
            )
        try:
            authority_hash, _receipt_hash = self._repository.verify_terminal_job(
                validation=validation,
                candidate=candidate,
                job=job,
                now=self._clock(),
            )
        except (ModelReviewRepositoryError, ValueError):
            return _failed("model_review_validation_failed")
        return _success(validation.validation_id, authority_hash)


class ModelReviewPublicationVerifier:
    """Independently check candidate identity and the complete validation receipt set."""

    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn

    def verify(
        self,
        *,
        descriptor: ActionDescriptor,
        invocation: ActionInvocation,
        execution: ActionExecutionResult,
    ) -> ActionVerificationResult:
        authority = execution.authority
        if authority is None or authority.kind is not ActionAuthorityKind.MODEL_REVIEW_VALIDATION:
            return _verification_failed(descriptor, authority, "model_review_validation_authority_missing")
        row = self._conn.execute(
            """
            SELECT validations.state, validations.candidate_hash, validations.authority_hash,
                   count(checks.id)::int AS check_count,
                   count(checks.id) FILTER (WHERE checks.status = 'passed')::int AS passed_count
            FROM tutor_model_review_validation_runs AS validations
            LEFT JOIN tutor_model_review_validation_checks AS checks
              ON checks.validation_run_id = validations.id AND checks.user_id = validations.user_id
            WHERE validations.id = %s AND validations.user_id = %s AND validations.track_id = %s
            GROUP BY validations.id
            """,
            (authority.reference_id, invocation.user_id, _track_id(self._conn, invocation.run_id, invocation.user_id)),
        ).fetchone()
        output = execution.output or {}
        if (
            row is None
            or str(row["state"]) != "verified"
            or str(row["candidate_hash"]) != str(invocation.arguments.get("candidate_hash") or "")
            or str(row.get("authority_hash") or "") != str(authority.reference_hash or "")
            or _as_int(row.get("check_count")) != 9
            or _as_int(row.get("passed_count")) != 9
            or str(output.get("validation_id") or "") != authority.reference_id
            or str(output.get("authority_hash") or "") != str(authority.reference_hash or "")
        ):
            return _verification_failed(descriptor, authority, "model_review_validation_authority_mismatch")
        try:
            descriptor.output_model.model_validate(output)
        except ValueError:
            return _verification_failed(descriptor, authority, "action_output_invalid")
        return ActionVerificationResult(
            status=ActionVerificationStatus.VERIFIED,
            verifier_id=descriptor.verifier_id,
            verifier_version=descriptor.verifier_version,
            authority=authority,
            safe_summary="Model review publication authority verified.",
        )


def _success(validation_id: str, authority_hash: str) -> ActionExecutionResult:
    authority = ActionAuthorityReference(
        kind=ActionAuthorityKind.MODEL_REVIEW_VALIDATION,
        reference_id=validation_id,
        reference_hash=authority_hash,
    )
    return ActionExecutionResult(
        status=ActionExecutionStatus.SUCCEEDED,
        authority=authority,
        output={
            "status": "completed",
            "validation_id": validation_id,
            "check_summary_code": "all_checks_passed",
            "authority_hash": authority_hash,
        },
        safe_summary="Model review candidate passed controlled validation.",
    )


def _failed(code: str) -> ActionExecutionResult:
    return ActionExecutionResult(
        status=ActionExecutionStatus.PERMANENT_FAILED,
        safe_summary="Model review validation failed safely.",
        diagnostic_code=code,
    )


def _verification_failed(
    descriptor: ActionDescriptor,
    authority: ActionAuthorityReference | None,
    code: str,
) -> ActionVerificationResult:
    return ActionVerificationResult(
        status=ActionVerificationStatus.FAILED,
        verifier_id=descriptor.verifier_id,
        verifier_version=descriptor.verifier_version,
        authority=authority,
        safe_summary="Model review validation authority could not be verified.",
        diagnostic_code=code,
    )


def _track_id(conn: Connection[dict[str, object]], run_id: str, user_id: str) -> str:
    row = conn.execute(
        "SELECT learning_track_id FROM tutor_run_learning_scopes WHERE run_id = %s AND user_id = %s",
        (run_id, user_id),
    ).fetchone()
    return str(row["learning_track_id"]) if row and row.get("learning_track_id") else "00000000-0000-0000-0000-000000000000"


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    try:
        return int(str(value or 0))
    except (TypeError, ValueError):
        return 0
