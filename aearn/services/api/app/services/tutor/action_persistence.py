"""PostgreSQL lifecycle and safe receipt store for controlled Tutor actions."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime

from psycopg import Connection

from app.agents.harness.actions import (
    ActionAuthorityKind,
    ActionAuthorityReference,
    ActionDescriptor,
    ActionExecutionResult,
    ActionInvocation,
    ActionLifecycleStatus,
    ActionReceipt,
    ActionRecoveryDirective,
    ActionRecoveryKind,
    ActionVerificationResult,
    ActionVerificationStatus,
    allowed_action_transition,
)
from app.services.tutor.action_runtime import ActionRuntimeError, ActionRuntimeUsage
from app.services.tutor.safe_projection import TutorSafeProjection


class PostgresActionReceiptStore:
    """Persist orchestration metadata while retaining domain-owner references only."""

    def __init__(
        self,
        conn: Connection[dict[str, object]],
        *,
        projector: TutorSafeProjection | None = None,
    ) -> None:
        self._conn = conn
        self._projector = projector or TutorSafeProjection()

    def usage(self, *, run_id: str) -> ActionRuntimeUsage:
        row = self._conn.execute(
            """
            SELECT
              (SELECT count(*) FROM tutor_action_invocations WHERE run_id = %s) AS actions,
              (SELECT count(*) FROM tutor_action_verifications WHERE run_id = %s) AS verifications,
              (
                SELECT count(*)
                FROM tutor_action_receipts
                WHERE run_id = %s
                  AND recovery_kind IN ('retry', 'rebuild_context', 'request_clarification')
              ) AS recoveries
            """,
            (run_id, run_id, run_id),
        ).fetchone()
        if row is None:
            return ActionRuntimeUsage()
        return ActionRuntimeUsage(
            actions=_as_int(row["actions"]),
            verifications=_as_int(row["verifications"]),
            recoveries=_as_int(row["recoveries"]),
        )

    def find_by_idempotency(self, invocation: ActionInvocation) -> ActionReceipt | None:
        row = self._conn.execute(
            """
            SELECT invocations.*, receipts.receipt_json, receipts.receipt_hash
            FROM tutor_action_invocations AS invocations
            LEFT JOIN tutor_action_receipts AS receipts ON receipts.invocation_id = invocations.id
            WHERE invocations.run_id = %s AND invocations.idempotency_key = %s
            """,
            (invocation.run_id, invocation.idempotency_key),
        ).fetchone()
        if row is None:
            return None
        if str(row["request_hash"]) != invocation.request_hash:
            raise ActionRuntimeError("action idempotency key conflicts with a different request")
        if row.get("receipt_json") is None:
            raise ActionRuntimeError("action invocation is already active without a terminal receipt")
        return _receipt_from_row(row)

    def find_current_verified(self, invocation: ActionInvocation) -> ActionReceipt | None:
        row = self._conn.execute(
            """
            SELECT invocations.*, receipts.receipt_json, receipts.receipt_hash
            FROM tutor_action_invocations AS invocations
            JOIN tutor_action_receipts AS receipts ON receipts.invocation_id = invocations.id
            WHERE invocations.run_id = %s
              AND invocations.input_revision = %s
              AND invocations.stable_action_key = %s
              AND invocations.status = 'verified'
            ORDER BY invocations.terminal_at DESC, invocations.id DESC
            LIMIT 1
            """,
            (invocation.run_id, invocation.input_revision, invocation.stable_action_key),
        ).fetchone()
        return _receipt_from_row(row) if row is not None else None

    def reserve(self, invocation: ActionInvocation, descriptor: ActionDescriptor) -> None:
        with self._conn.transaction():
            run = self._lock_current_run(invocation)
            if (
                _as_int(run["input_revision"]) != invocation.input_revision
                or str(run.get("active_lease_owner_id") or "") != invocation.lease_owner_id
                or _as_int(run["active_lease_generation"]) != invocation.lease_generation
                or not _lease_current_at(
                    run.get("active_lease_expires_at"),
                    now=invocation.requested_at,
                )
                or run.get("cancelled_at") is not None
                or run.get("superseded_by_run_id") is not None
                or run.get("terminal_outcome") is not None
                or str(run["catalog_digest"]) != invocation.catalog_digest
                or str(run["policy_fingerprint"]) != invocation.policy_fingerprint
            ):
                raise ActionRuntimeError("action invocation lost current run authority")
            existing = self._conn.execute(
                "SELECT * FROM tutor_action_invocations WHERE id = %s OR (run_id = %s AND idempotency_key = %s)",
                (invocation.invocation_id, invocation.run_id, invocation.idempotency_key),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["request_hash"]) != invocation.request_hash
                    or str(existing["descriptor_hash"]) != descriptor.contract_hash
                ):
                    raise ActionRuntimeError("action invocation conflicts with durable evidence")
                raise ActionRuntimeError("action invocation is already reserved")
            self._conn.execute(
                """
                INSERT INTO tutor_action_invocations (
                  id, run_id, conversation_id, user_id, input_revision, lease_owner_id, lease_generation,
                  action_generation, idempotency_key, stable_action_key, action_id, action_version,
                  descriptor_hash, owner_adapter_id, task_kind, origin, catalog_digest,
                  policy_fingerprint, selected_skill_reference, request_hash,
                  resource_profile_hash, resource_request_hash, parent_invocation_id,
                  retry_index, status, requested_at
                ) VALUES (
                  %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s,
                  %s, %s, %s,
                  %s, %s, %s,
                  %s, 'requested', %s
                )
                """,
                (
                    invocation.invocation_id,
                    invocation.run_id,
                    invocation.conversation_id,
                    invocation.user_id,
                    invocation.input_revision,
                    invocation.lease_owner_id,
                    invocation.lease_generation,
                    invocation.action_generation,
                    invocation.idempotency_key,
                    invocation.stable_action_key,
                    invocation.action_id,
                    invocation.action_version,
                    descriptor.contract_hash,
                    descriptor.owner_adapter_id,
                    invocation.task_kind,
                    invocation.origin,
                    invocation.catalog_digest,
                    invocation.policy_fingerprint,
                    invocation.selected_skill_reference,
                    invocation.request_hash,
                    descriptor.resource_profile.fingerprint,
                    invocation.resource_request.fingerprint,
                    invocation.parent_invocation_id,
                    invocation.retry_index,
                    invocation.requested_at,
                ),
            )

    def transition(
        self,
        invocation: ActionInvocation,
        *,
        expected: ActionLifecycleStatus,
        target: ActionLifecycleStatus,
        occurred_at: datetime,
    ) -> None:
        if not allowed_action_transition(expected, target):
            raise ActionRuntimeError("action lifecycle transition is invalid")
        effective = _utc(occurred_at)
        terminal_at = effective if target.terminal else None
        with self._conn.transaction():
            row = self._conn.execute(
                """
                UPDATE tutor_action_invocations
                SET status = %s,
                    admitted_at = CASE WHEN %s = 'admitted' THEN COALESCE(admitted_at, %s) ELSE admitted_at END,
                    started_at = CASE WHEN %s = 'running' THEN COALESCE(started_at, %s) ELSE started_at END,
                    terminal_at = COALESCE(%s, terminal_at),
                    updated_at = %s
                WHERE id = %s AND run_id = %s AND status = %s
                RETURNING id
                """,
                (
                    target.value,
                    target.value,
                    effective,
                    target.value,
                    effective,
                    terminal_at,
                    effective,
                    invocation.invocation_id,
                    invocation.run_id,
                    expected.value,
                ),
            ).fetchone()
            if row is None:
                raise ActionRuntimeError("action lifecycle lost transition ownership")

    def record_attempt(
        self,
        invocation: ActionInvocation,
        execution: ActionExecutionResult,
        *,
        attempt_index: int,
        created_at: datetime,
    ) -> None:
        safe = self._projector.project(
            {
                "kind": "action_attempt",
                "action_id": invocation.action_id,
                "action_version": invocation.action_version,
                "status": execution.status.value,
                "diagnostic_code": execution.diagnostic_code or "none",
                "authority_kind": execution.authority.kind.value if execution.authority else "none",
                "authority_id": execution.authority.reference_id if execution.authority else "none",
                "result_hash": execution.result_hash,
                "duration_ms": execution.duration_ms,
            }
        )
        with self._conn.transaction():
            existing = self._conn.execute(
                "SELECT * FROM tutor_action_attempts WHERE invocation_id = %s AND attempt_index = %s",
                (invocation.invocation_id, attempt_index),
            ).fetchone()
            if existing is not None:
                if str(existing["result_hash"]) != execution.result_hash:
                    raise ActionRuntimeError("action attempt conflicts with durable evidence")
                return
            self._conn.execute(
                """
                INSERT INTO tutor_action_attempts (
                  invocation_id, run_id, attempt_index, status, authority_kind,
                  authority_id, authority_hash, result_hash, safe_result_json,
                  diagnostic_code, duration_ms, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                """,
                (
                    invocation.invocation_id,
                    invocation.run_id,
                    attempt_index,
                    execution.status.value,
                    execution.authority.kind.value if execution.authority else None,
                    execution.authority.reference_id if execution.authority else None,
                    execution.authority.reference_hash if execution.authority else None,
                    execution.result_hash,
                    _json(safe),
                    execution.diagnostic_code,
                    execution.duration_ms,
                    _utc(created_at),
                ),
            )

    def record_verification(
        self,
        invocation: ActionInvocation,
        verification: ActionVerificationResult,
        *,
        created_at: datetime,
    ) -> None:
        safe = self._projector.project(
            {
                "kind": "action_verification",
                "action_id": invocation.action_id,
                "action_version": invocation.action_version,
                "verification_status": verification.status.value,
                "verifier_id": verification.verifier_id,
                "verifier_version": verification.verifier_version,
                "authority_kind": verification.authority.kind.value if verification.authority else "none",
                "authority_id": verification.authority.reference_id if verification.authority else "none",
                "diagnostic_code": verification.diagnostic_code or "none",
                "verification_hash": verification.verification_hash,
            }
        )
        with self._conn.transaction():
            existing = self._conn.execute(
                "SELECT * FROM tutor_action_verifications WHERE invocation_id = %s",
                (invocation.invocation_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["verification_hash"]) != verification.verification_hash:
                    raise ActionRuntimeError("action verification conflicts with durable evidence")
                return
            self._conn.execute(
                """
                INSERT INTO tutor_action_verifications (
                  invocation_id, run_id, status, verifier_id, verifier_version,
                  authority_kind, authority_id, authority_hash, verification_hash,
                  safe_verification_json, diagnostic_code, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                """,
                (
                    invocation.invocation_id,
                    invocation.run_id,
                    verification.status.value,
                    verification.verifier_id,
                    verification.verifier_version,
                    verification.authority.kind.value if verification.authority else None,
                    verification.authority.reference_id if verification.authority else None,
                    verification.authority.reference_hash if verification.authority else None,
                    verification.verification_hash,
                    _json(safe),
                    verification.diagnostic_code,
                    _utc(created_at),
                ),
            )

    def record(self, invocation: ActionInvocation, receipt: ActionReceipt) -> ActionReceipt:
        safe = self._projector.project(receipt.as_safe_dict())
        with self._conn.transaction():
            existing = self._conn.execute(
                "SELECT * FROM tutor_action_receipts WHERE invocation_id = %s",
                (invocation.invocation_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["receipt_hash"]) != receipt.receipt_hash:
                    raise ActionRuntimeError("action receipt conflicts with durable evidence")
                return _receipt_from_row({**dict(existing), **receipt.as_safe_dict()})
            state = self._conn.execute(
                "SELECT status FROM tutor_action_invocations WHERE id = %s AND run_id = %s FOR UPDATE",
                (invocation.invocation_id, invocation.run_id),
            ).fetchone()
            if state is None or str(state["status"]) != receipt.status.value:
                raise ActionRuntimeError("action terminal receipt does not match lifecycle state")
            self._conn.execute(
                """
                INSERT INTO tutor_action_receipts (
                  invocation_id, run_id, user_id, conversation_id, input_revision,
                  stable_action_key, action_id, action_version, status,
                  authority_kind, authority_id, authority_hash, safe_summary,
                  result_hash, verification_status, verification_hash, diagnostic_code,
                  recovery_kind, recovery_code, retry_after_seconds,
                  receipt_json, receipt_hash, terminal_at
                ) VALUES (
                  %s, %s, %s, %s, %s,
                  %s, %s, %s, %s,
                  %s, %s, %s, %s,
                  %s, %s, %s, %s,
                  %s, %s, %s,
                  %s::jsonb, %s, %s
                )
                """,
                (
                    invocation.invocation_id,
                    invocation.run_id,
                    invocation.user_id,
                    invocation.conversation_id,
                    invocation.input_revision,
                    invocation.stable_action_key,
                    invocation.action_id,
                    invocation.action_version,
                    receipt.status.value,
                    receipt.authority.kind.value if receipt.authority else None,
                    receipt.authority.reference_id if receipt.authority else None,
                    receipt.authority.reference_hash if receipt.authority else None,
                    receipt.safe_summary,
                    receipt.result_hash,
                    receipt.verification_status.value,
                    receipt.verification_hash,
                    receipt.diagnostic_code,
                    receipt.recovery.kind.value,
                    receipt.recovery.code,
                    receipt.recovery.retry_after_seconds,
                    _json(safe),
                    receipt.receipt_hash,
                    receipt.terminal_at,
                ),
            )
        return receipt

    def list_context_receipts(
        self,
        *,
        user_id: str,
        run_id: str,
        input_revision: int,
        limit: int = 4,
    ) -> tuple[ActionReceipt, ...]:
        if limit <= 0:
            return ()
        rows = self._conn.execute(
            """
            SELECT receipts.receipt_json, receipts.receipt_hash
            FROM tutor_action_receipts AS receipts
            WHERE receipts.user_id = %s AND receipts.run_id = %s
              AND receipts.input_revision <= %s
              AND receipts.status IN (
                'verified', 'retryable_failed', 'permanent_failed', 'denied',
                'cancelled', 'timed_out', 'superseded'
              )
            ORDER BY receipts.terminal_at DESC, receipts.invocation_id DESC
            LIMIT %s
            """,
            (user_id, run_id, input_revision, min(limit, 8)),
        ).fetchall()
        return tuple(_receipt_from_row(row) for row in rows)

    def _lock_current_run(self, invocation: ActionInvocation) -> Mapping[str, object]:
        row = self._conn.execute(
            """
            SELECT * FROM tutor_runs
            WHERE id = %s AND user_id = %s AND conversation_id = %s
            FOR UPDATE
            """,
            (invocation.run_id, invocation.user_id, invocation.conversation_id),
        ).fetchone()
        if row is None:
            raise ActionRuntimeError("action run authority was not found")
        return row


class PostgresActionFence:
    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn

    def snapshot(self, invocation: ActionInvocation):
        from app.agents.harness.actions import ActionFenceSnapshot

        row = self._conn.execute(
            """
            SELECT input_revision, active_lease_owner_id, active_lease_generation,
                   active_lease_expires_at, cancelled_at, superseded_by_run_id
            FROM tutor_runs
            WHERE id = %s AND user_id = %s AND conversation_id = %s
            """,
            (invocation.run_id, invocation.user_id, invocation.conversation_id),
        ).fetchone()
        if row is None:
            return ActionFenceSnapshot(
                input_revision=invocation.input_revision + 1,
                lease_generation=invocation.lease_generation,
                superseded=True,
            )
        return ActionFenceSnapshot(
            input_revision=_as_int(row["input_revision"]),
            lease_generation=_as_int(row["active_lease_generation"]),
            lease_current=(
                str(row.get("active_lease_owner_id") or "") == invocation.lease_owner_id
                and _lease_current_at(
                    row.get("active_lease_expires_at"),
                    now=datetime.now(UTC),
                )
            ),
            cancelled=row.get("cancelled_at") is not None,
            superseded=row.get("superseded_by_run_id") is not None,
        )


def _receipt_from_row(row: Mapping[str, object]) -> ActionReceipt:
    raw = row.get("receipt_json")
    if not isinstance(raw, Mapping):
        raw = row
    authority = None
    authority_kind = raw.get("authority_kind")
    authority_id = raw.get("authority_id")
    if authority_kind and authority_id and str(authority_kind) != "none" and str(authority_id) != "none":
        authority = ActionAuthorityReference(
            kind=ActionAuthorityKind(str(authority_kind)),
            reference_id=str(authority_id),
            reference_hash=(str(raw["authority_hash"]) if raw.get("authority_hash") else None),
        )
    terminal_at = raw.get("terminal_at")
    if isinstance(terminal_at, str):
        terminal_at = datetime.fromisoformat(terminal_at.replace("Z", "+00:00"))
    return ActionReceipt(
        invocation_id=str(raw["invocation_id"]),
        action_id=str(raw["action_id"]),
        action_version=str(raw["action_version"]),
        stable_action_key=str(raw["stable_action_key"]),
        status=ActionLifecycleStatus(str(raw["status"])),
        input_revision=_as_int(raw["input_revision"]),
        action_generation=_as_int(raw["action_generation"]),
        retry_index=_as_int(raw["retry_index"]),
        authority=authority,
        safe_summary=str(raw.get("safe_summary") or ""),
        result_hash=str(raw["result_hash"]) if raw.get("result_hash") else None,
        verification_status=ActionVerificationStatus(str(raw["verification_status"])),
        verification_hash=(str(raw["verification_hash"]) if raw.get("verification_hash") else None),
        diagnostic_code=str(raw["diagnostic_code"]) if raw.get("diagnostic_code") else None,
        recovery=ActionRecoveryDirective(
            kind=ActionRecoveryKind(str(raw["recovery_kind"])),
            code=str(raw["recovery_code"]),
            retry_after_seconds=_as_int(raw.get("retry_after_seconds")),
        ),
        terminal_at=terminal_at if isinstance(terminal_at, datetime) else None,
    )


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _lease_current_at(value: object, *, now: datetime) -> bool:
    return isinstance(value, datetime) and _utc(value) > _utc(now)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
