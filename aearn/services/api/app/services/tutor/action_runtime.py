"""Bounded orchestration for the Tutor controlled Action Runtime."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from pydantic import ValidationError

from app.agents.harness.actions import (
    ActionAuthorityReference,
    ActionDescriptor,
    ActionExecutionResult,
    ActionExecutionStatus,
    ActionFence,
    ActionFenceSnapshot,
    ActionInvocation,
    ActionLifecycleStatus,
    ActionReceipt,
    ActionRecoveryDirective,
    ActionRecoveryKind,
    ActionVerificationResult,
    ActionVerificationStatus,
    allowed_action_transition,
    validate_action_arguments,
    validate_action_resources,
)


class ActionAdapter(Protocol):
    def execute(self, invocation: ActionInvocation) -> ActionExecutionResult: ...


class ActionVerifier(Protocol):
    def verify(
        self,
        *,
        descriptor: ActionDescriptor,
        invocation: ActionInvocation,
        execution: ActionExecutionResult,
    ) -> ActionVerificationResult: ...


class ActionReceiptStore(Protocol):
    def usage(self, *, run_id: str) -> "ActionRuntimeUsage": ...

    def find_by_idempotency(self, invocation: ActionInvocation) -> ActionReceipt | None: ...

    def find_current_verified(self, invocation: ActionInvocation) -> ActionReceipt | None: ...

    def reserve(self, invocation: ActionInvocation, descriptor: ActionDescriptor) -> None: ...

    def transition(
        self,
        invocation: ActionInvocation,
        *,
        expected: ActionLifecycleStatus,
        target: ActionLifecycleStatus,
        occurred_at: datetime,
    ) -> None: ...

    def record_attempt(
        self,
        invocation: ActionInvocation,
        execution: ActionExecutionResult,
        *,
        attempt_index: int,
        created_at: datetime,
    ) -> None: ...

    def record_verification(
        self,
        invocation: ActionInvocation,
        verification: ActionVerificationResult,
        *,
        created_at: datetime,
    ) -> None: ...

    def record(self, invocation: ActionInvocation, receipt: ActionReceipt) -> ActionReceipt: ...


class ActionRuntimeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ActionRuntimeOutcome:
    receipt: ActionReceipt
    replayed: bool = False
    deduplicated: bool = False
    adapter_invoked: bool = False


@dataclass(frozen=True, slots=True)
class ActionRuntimeUsage:
    actions: int = 0
    verifications: int = 0
    recoveries: int = 0

    def __post_init__(self) -> None:
        if min(self.actions, self.verifications, self.recoveries) < 0:
            raise ValueError("action runtime usage must be non-negative")


@dataclass(frozen=True, slots=True)
class ActionRuntimeBudget:
    max_actions: int = 4
    max_retries: int = 2
    max_verifications: int = 4
    max_recoveries: int = 2

    def __post_init__(self) -> None:
        for name in ("max_actions", "max_retries", "max_verifications", "max_recoveries"):
            value = getattr(self, name)
            if value < 0 or value > 16:
                raise ValueError(f"{name} must be within 0..16")


class ControlledActionRuntime:
    """Execute one exact action without taking ownership of domain facts."""

    def __init__(
        self,
        *,
        descriptors: Sequence[ActionDescriptor],
        adapters: Mapping[str, ActionAdapter],
        verifiers: Mapping[str, ActionVerifier],
        fence: ActionFence,
        store: ActionReceiptStore,
        clock: Callable[[], datetime],
        approved_source_ids: Iterable[str] = (),
        approved_artifact_ids: Iterable[str] = (),
        budget: ActionRuntimeBudget | None = None,
    ) -> None:
        descriptor_values = tuple(descriptors)
        self._descriptors = {descriptor.reference: descriptor for descriptor in descriptor_values}
        if len(self._descriptors) != len(descriptor_values):
            raise ValueError("action descriptors must have unique exact references")
        self._adapters = dict(adapters)
        self._verifiers = dict(verifiers)
        self._fence = fence
        self._store = store
        self._clock = clock
        self._approved_source_ids = frozenset(approved_source_ids)
        self._approved_artifact_ids = frozenset(approved_artifact_ids)
        self._budget = budget or ActionRuntimeBudget()

    def execute(self, invocation: ActionInvocation) -> ActionRuntimeOutcome:
        descriptor = self._descriptors.get(f"{invocation.action_id}@{invocation.action_version}")
        if descriptor is None:
            return ActionRuntimeOutcome(
                receipt=_receipt(
                    invocation,
                    status=ActionLifecycleStatus.DENIED,
                    verification_status=ActionVerificationStatus.NOT_REQUIRED,
                    safe_summary="Action descriptor is not registered.",
                    code="unknown_action_descriptor",
                    recovery=ActionRecoveryDirective(ActionRecoveryKind.SAFE_STOP, "unknown_action_descriptor"),
                    now=_utc(self._clock()),
                )
            )

        replay = self._store.find_by_idempotency(invocation)
        if replay is not None:
            return ActionRuntimeOutcome(receipt=replay, replayed=True)
        verified = self._store.find_current_verified(invocation)
        if verified is not None:
            return ActionRuntimeOutcome(receipt=verified, replayed=True, deduplicated=True)

        self._store.reserve(invocation, descriptor)
        admission_code = self._admission_denial(descriptor, invocation)
        if admission_code is not None:
            return self._finish_without_adapter(
                invocation,
                expected=ActionLifecycleStatus.REQUESTED,
                status=ActionLifecycleStatus.DENIED,
                code=admission_code,
                descriptor=descriptor,
            )

        adapter = self._adapters.get(descriptor.owner_adapter_id)
        verifier = self._verifiers.get(descriptor.verifier_id)
        if adapter is None or verifier is None:
            code = "action_adapter_unavailable" if adapter is None else "action_verifier_unavailable"
            return self._finish_without_adapter(
                invocation,
                expected=ActionLifecycleStatus.REQUESTED,
                status=ActionLifecycleStatus.DENIED,
                code=code,
                descriptor=descriptor,
            )

        admitted_at = _utc(self._clock())
        self._store.transition(
            invocation,
            expected=ActionLifecycleStatus.REQUESTED,
            target=ActionLifecycleStatus.ADMITTED,
            occurred_at=admitted_at,
        )
        before = self._fence.snapshot(invocation)
        fenced = _fence_terminal(invocation, before, now=admitted_at)
        if fenced is not None:
            return self._finish_fenced(
                invocation,
                fenced,
                expected=ActionLifecycleStatus.ADMITTED,
            )

        started_at = _utc(self._clock())
        self._store.transition(
            invocation,
            expected=ActionLifecycleStatus.ADMITTED,
            target=ActionLifecycleStatus.RUNNING,
            occurred_at=started_at,
        )
        try:
            execution = adapter.execute(invocation)
        except Exception:
            execution = ActionExecutionResult(
                status=ActionExecutionStatus.PERMANENT_FAILED,
                safe_summary="Action adapter failed safely.",
                diagnostic_code="action_adapter_failed",
            )
        finished_at = _utc(self._clock())
        elapsed_seconds = max(0.0, (finished_at - started_at).total_seconds())
        self._store.record_attempt(
            invocation,
            execution,
            attempt_index=invocation.retry_index + 1,
            created_at=finished_at,
        )

        after = self._fence.snapshot(invocation)
        fenced = _fence_terminal(invocation, after, now=finished_at)
        if fenced is not None:
            return self._finish_fenced(
                invocation,
                fenced,
                expected=ActionLifecycleStatus.RUNNING,
                adapter_invoked=True,
            )
        if elapsed_seconds > descriptor.timeout_seconds:
            return self._finish(
                invocation,
                _receipt(
                    invocation,
                    status=ActionLifecycleStatus.TIMED_OUT,
                    verification_status=ActionVerificationStatus.NOT_REQUIRED,
                    safe_summary="Action exceeded its server-owned timeout.",
                    code="action_timed_out",
                    recovery=self._recovery(descriptor, invocation, code="action_timed_out"),
                    now=finished_at,
                ),
                expected=ActionLifecycleStatus.RUNNING,
                adapter_invoked=True,
            )

        if execution.status is not ActionExecutionStatus.SUCCEEDED:
            status = _execution_lifecycle(execution.status)
            code = execution.diagnostic_code or f"action_{execution.status.value}"
            recovery = self._recovery(descriptor, invocation, code=code)
            if status is ActionLifecycleStatus.RETRYABLE_FAILED and recovery.kind is not ActionRecoveryKind.RETRY:
                status = ActionLifecycleStatus.PERMANENT_FAILED
            finish = self._finish_fenced if status is ActionLifecycleStatus.CANCELLED else self._finish
            return finish(
                invocation,
                _receipt(
                    invocation,
                    status=status,
                    verification_status=ActionVerificationStatus.NOT_REQUIRED,
                    authority=execution.authority,
                    safe_summary=execution.safe_summary,
                    result_hash=execution.result_hash,
                    code=code,
                    recovery=recovery,
                    now=finished_at,
                ),
                expected=ActionLifecycleStatus.RUNNING,
                adapter_invoked=True,
            )

        self._store.transition(
            invocation,
            expected=ActionLifecycleStatus.RUNNING,
            target=ActionLifecycleStatus.SUCCEEDED_UNVERIFIED,
            occurred_at=finished_at,
        )
        try:
            descriptor.output_model.model_validate(execution.output or {})
        except (ValidationError, TypeError, ValueError):
            return self._finish(
                invocation,
                _receipt(
                    invocation,
                    status=ActionLifecycleStatus.PERMANENT_FAILED,
                    verification_status=ActionVerificationStatus.FAILED,
                    authority=execution.authority,
                    safe_summary="Action output failed its declared contract.",
                    result_hash=execution.result_hash,
                    code="action_output_invalid",
                    recovery=self._recovery(descriptor, invocation, code="action_output_invalid"),
                    now=finished_at,
                ),
                expected=ActionLifecycleStatus.SUCCEEDED_UNVERIFIED,
                adapter_invoked=True,
            )

        if self._store.usage(run_id=invocation.run_id).verifications >= self._budget.max_verifications:
            return self._finish(
                invocation,
                _receipt(
                    invocation,
                    status=ActionLifecycleStatus.PERMANENT_FAILED,
                    verification_status=ActionVerificationStatus.FAILED,
                    authority=execution.authority,
                    safe_summary="Action verification budget was exhausted.",
                    result_hash=execution.result_hash,
                    code="action_verification_budget_exhausted",
                    recovery=ActionRecoveryDirective(
                        ActionRecoveryKind.SAFE_STOP,
                        "action_verification_budget_exhausted",
                    ),
                    now=finished_at,
                ),
                expected=ActionLifecycleStatus.SUCCEEDED_UNVERIFIED,
                adapter_invoked=True,
            )

        try:
            verification = verifier.verify(
                descriptor=descriptor,
                invocation=invocation,
                execution=execution,
            )
        except Exception:
            verification = ActionVerificationResult(
                status=ActionVerificationStatus.FAILED,
                verifier_id=descriptor.verifier_id,
                verifier_version=descriptor.verifier_version,
                authority=execution.authority,
                safe_summary="Action verification failed safely.",
                diagnostic_code="action_verifier_failed",
            )
        if verification.authority != execution.authority:
            verification = ActionVerificationResult(
                status=ActionVerificationStatus.FAILED,
                verifier_id=descriptor.verifier_id,
                verifier_version=descriptor.verifier_version,
                authority=execution.authority,
                safe_summary="Action authority did not match verification evidence.",
                diagnostic_code="action_authority_mismatch",
            )
        verified_at = _utc(self._clock())
        self._store.record_verification(invocation, verification, created_at=verified_at)
        post_verification = self._fence.snapshot(invocation)
        fenced = _fence_terminal(invocation, post_verification, now=verified_at)
        if fenced is not None:
            return self._finish_fenced(
                invocation,
                fenced,
                expected=ActionLifecycleStatus.SUCCEEDED_UNVERIFIED,
                adapter_invoked=True,
            )

        if verification.status is ActionVerificationStatus.VERIFIED:
            return self._finish(
                invocation,
                _receipt(
                    invocation,
                    status=ActionLifecycleStatus.VERIFIED,
                    verification_status=verification.status,
                    authority=execution.authority,
                    safe_summary=verification.safe_summary or execution.safe_summary,
                    result_hash=execution.result_hash,
                    verification_hash=verification.verification_hash,
                    code=None,
                    recovery=ActionRecoveryDirective(ActionRecoveryKind.NONE, "none"),
                    now=verified_at,
                ),
                expected=ActionLifecycleStatus.SUCCEEDED_UNVERIFIED,
                adapter_invoked=True,
            )

        code = verification.diagnostic_code or "action_verification_failed"
        recovery = self._recovery(descriptor, invocation, code=code)
        status = (
            ActionLifecycleStatus.RETRYABLE_FAILED
            if recovery.kind is ActionRecoveryKind.RETRY
            else ActionLifecycleStatus.PERMANENT_FAILED
        )
        return self._finish(
            invocation,
            _receipt(
                invocation,
                status=status,
                verification_status=verification.status,
                authority=execution.authority,
                safe_summary=verification.safe_summary or "Action verification did not pass.",
                result_hash=execution.result_hash,
                verification_hash=verification.verification_hash,
                code=code,
                recovery=recovery,
                now=verified_at,
            ),
            expected=ActionLifecycleStatus.SUCCEEDED_UNVERIFIED,
            adapter_invoked=True,
        )

    def _admission_denial(self, descriptor: ActionDescriptor, invocation: ActionInvocation) -> str | None:
        if self._store.usage(run_id=invocation.run_id).actions > self._budget.max_actions:
            return "action_budget_exhausted"
        if invocation.retry_index > self._budget.max_retries:
            return "action_retry_budget_exhausted"
        if invocation.retry_index >= descriptor.retry_policy.max_attempts:
            return "action_descriptor_retry_exhausted"
        if invocation.origin not in descriptor.allowed_origins or invocation.task_kind not in descriptor.allowed_task_kinds:
            return "action_scope_denied"
        try:
            validate_action_arguments(descriptor, invocation.arguments)
            validate_action_resources(
                descriptor=descriptor,
                request=invocation.resource_request,
                approved_source_ids=self._approved_source_ids,
                approved_artifact_ids=self._approved_artifact_ids,
            )
        except (ValidationError, TypeError, ValueError):
            return "action_admission_denied"
        return None

    def _recovery(
        self,
        descriptor: ActionDescriptor,
        invocation: ActionInvocation,
        *,
        code: str,
    ) -> ActionRecoveryDirective:
        directive = _recovery(descriptor, invocation, code=code)
        actionable = {
            ActionRecoveryKind.RETRY,
            ActionRecoveryKind.REBUILD_CONTEXT,
            ActionRecoveryKind.REQUEST_CLARIFICATION,
        }
        usage = self._store.usage(run_id=invocation.run_id)
        retry_exhausted = (
            directive.kind is ActionRecoveryKind.RETRY
            and invocation.retry_index >= self._budget.max_retries
        )
        recovery_exhausted = (
            directive.kind in actionable
            and usage.recoveries >= self._budget.max_recoveries
        )
        if retry_exhausted or recovery_exhausted:
            return ActionRecoveryDirective(ActionRecoveryKind.SAFE_STOP, "action_recovery_budget_exhausted")
        return directive

    def _finish_without_adapter(
        self,
        invocation: ActionInvocation,
        *,
        expected: ActionLifecycleStatus,
        status: ActionLifecycleStatus,
        code: str,
        descriptor: ActionDescriptor,
    ) -> ActionRuntimeOutcome:
        return self._finish(
            invocation,
            _receipt(
                invocation,
                status=status,
                verification_status=ActionVerificationStatus.NOT_REQUIRED,
                safe_summary="Action was rejected by the controlled runtime.",
                code=code,
                recovery=self._recovery(descriptor, invocation, code=code),
                now=_utc(self._clock()),
            ),
            expected=expected,
        )

    def _finish_fenced(
        self,
        invocation: ActionInvocation,
        receipt: ActionReceipt,
        *,
        expected: ActionLifecycleStatus,
        adapter_invoked: bool = False,
    ) -> ActionRuntimeOutcome:
        if receipt.status is ActionLifecycleStatus.CANCELLED:
            self._store.transition(
                invocation,
                expected=expected,
                target=ActionLifecycleStatus.CANCEL_REQUESTED,
                occurred_at=receipt.terminal_at or _utc(self._clock()),
            )
            expected = ActionLifecycleStatus.CANCEL_REQUESTED
        return self._finish(
            invocation,
            receipt,
            expected=expected,
            adapter_invoked=adapter_invoked,
        )

    def _finish(
        self,
        invocation: ActionInvocation,
        receipt: ActionReceipt,
        *,
        expected: ActionLifecycleStatus,
        adapter_invoked: bool = False,
    ) -> ActionRuntimeOutcome:
        self._store.transition(
            invocation,
            expected=expected,
            target=receipt.status,
            occurred_at=receipt.terminal_at or _utc(self._clock()),
        )
        stored = self._store.record(invocation, receipt)
        return ActionRuntimeOutcome(receipt=stored, adapter_invoked=adapter_invoked)


class SchemaActionVerifier:
    """Validate declared output and retain the owner authority reference."""

    def verify(
        self,
        *,
        descriptor: ActionDescriptor,
        invocation: ActionInvocation,
        execution: ActionExecutionResult,
    ) -> ActionVerificationResult:
        del invocation
        try:
            descriptor.output_model.model_validate(execution.output or {})
        except (ValidationError, TypeError, ValueError):
            return ActionVerificationResult(
                status=ActionVerificationStatus.FAILED,
                verifier_id=descriptor.verifier_id,
                verifier_version=descriptor.verifier_version,
                authority=execution.authority,
                safe_summary="Declared action output could not be verified.",
                diagnostic_code="action_output_invalid",
            )
        return ActionVerificationResult(
            status=ActionVerificationStatus.VERIFIED,
            verifier_id=descriptor.verifier_id,
            verifier_version=descriptor.verifier_version,
            authority=execution.authority,
            safe_summary=execution.safe_summary or "Action result verified.",
        )


class CallableActionAdapter:
    def __init__(self, callback: Callable[[ActionInvocation], ActionExecutionResult]) -> None:
        self._callback = callback
        self.calls: list[ActionInvocation] = []

    def execute(self, invocation: ActionInvocation) -> ActionExecutionResult:
        self.calls.append(invocation)
        return self._callback(invocation)


class InMemoryActionFence:
    def __init__(self, snapshots: Iterable[ActionFenceSnapshot] = ()) -> None:
        self._snapshots = list(snapshots)
        self.calls = 0

    def snapshot(self, invocation: ActionInvocation) -> ActionFenceSnapshot:
        self.calls += 1
        if self._snapshots:
            return self._snapshots.pop(0)
        return ActionFenceSnapshot(
            input_revision=invocation.input_revision,
            lease_generation=invocation.lease_generation,
            lease_current=True,
        )


class InMemoryActionReceiptStore:
    def __init__(self) -> None:
        self._by_idempotency: dict[tuple[str, str], tuple[str, ActionReceipt]] = {}
        self._verified: dict[tuple[str, int, str], ActionReceipt] = {}
        self._states: dict[str, ActionLifecycleStatus] = {}
        self._run_ids: dict[str, str] = {}
        self.receipts: list[ActionReceipt] = []
        self.attempts: list[tuple[str, int, ActionExecutionResult]] = []
        self.verifications: list[tuple[str, ActionVerificationResult]] = []
        self.transitions: list[tuple[str, ActionLifecycleStatus, ActionLifecycleStatus]] = []

    def usage(self, *, run_id: str) -> ActionRuntimeUsage:
        invocation_ids = {
            invocation_id
            for invocation_id, stored_run_id in self._run_ids.items()
            if stored_run_id == run_id
        }
        return ActionRuntimeUsage(
            actions=len(invocation_ids),
            verifications=sum(
                1
                for invocation_id, _verification in self.verifications
                if invocation_id in invocation_ids
            ),
            recoveries=sum(
                1
                for receipt in self.receipts
                if receipt.invocation_id in invocation_ids
                and receipt.recovery.kind
                in {
                    ActionRecoveryKind.RETRY,
                    ActionRecoveryKind.REBUILD_CONTEXT,
                    ActionRecoveryKind.REQUEST_CLARIFICATION,
                }
            ),
        )

    def find_by_idempotency(self, invocation: ActionInvocation) -> ActionReceipt | None:
        stored = self._by_idempotency.get((invocation.run_id, invocation.idempotency_key))
        if stored is None:
            return None
        request_hash, receipt = stored
        if request_hash != invocation.request_hash:
            raise ActionRuntimeError("action idempotency key conflicts with a different request")
        return receipt

    def find_current_verified(self, invocation: ActionInvocation) -> ActionReceipt | None:
        return self._verified.get((invocation.run_id, invocation.input_revision, invocation.stable_action_key))

    def reserve(self, invocation: ActionInvocation, descriptor: ActionDescriptor) -> None:
        del descriptor
        if invocation.invocation_id in self._states:
            raise ActionRuntimeError("action invocation id already exists")
        self._states[invocation.invocation_id] = ActionLifecycleStatus.REQUESTED
        self._run_ids[invocation.invocation_id] = invocation.run_id

    def transition(
        self,
        invocation: ActionInvocation,
        *,
        expected: ActionLifecycleStatus,
        target: ActionLifecycleStatus,
        occurred_at: datetime,
    ) -> None:
        del occurred_at
        current = self._states.get(invocation.invocation_id)
        if current is not expected:
            raise ActionRuntimeError("action lifecycle lost transition ownership")
        if not allowed_action_transition(expected, target):
            raise ActionRuntimeError("action lifecycle transition is invalid")
        self._states[invocation.invocation_id] = target
        self.transitions.append((invocation.invocation_id, expected, target))

    def record_attempt(
        self,
        invocation: ActionInvocation,
        execution: ActionExecutionResult,
        *,
        attempt_index: int,
        created_at: datetime,
    ) -> None:
        del created_at
        self.attempts.append((invocation.invocation_id, attempt_index, execution))

    def record_verification(
        self,
        invocation: ActionInvocation,
        verification: ActionVerificationResult,
        *,
        created_at: datetime,
    ) -> None:
        del created_at
        self.verifications.append((invocation.invocation_id, verification))

    def record(self, invocation: ActionInvocation, receipt: ActionReceipt) -> ActionReceipt:
        if receipt.invocation_id != invocation.invocation_id:
            raise ActionRuntimeError("action receipt does not match invocation")
        if self._states.get(invocation.invocation_id) is not receipt.status:
            raise ActionRuntimeError("action terminal receipt does not match lifecycle state")
        key = (invocation.run_id, invocation.idempotency_key)
        existing = self._by_idempotency.get(key)
        if existing is not None:
            if existing[0] != invocation.request_hash or existing[1].receipt_hash != receipt.receipt_hash:
                raise ActionRuntimeError("action receipt conflicts with idempotent evidence")
            return existing[1]
        self._by_idempotency[key] = (invocation.request_hash, receipt)
        self.receipts.append(receipt)
        if receipt.status is ActionLifecycleStatus.VERIFIED:
            self._verified[(invocation.run_id, invocation.input_revision, invocation.stable_action_key)] = receipt
        return receipt


def _fence_terminal(
    invocation: ActionInvocation,
    fence: ActionFenceSnapshot,
    *,
    now: datetime,
) -> ActionReceipt | None:
    if fence.superseded or fence.input_revision != invocation.input_revision:
        return _receipt(
            invocation,
            status=ActionLifecycleStatus.SUPERSEDED,
            verification_status=ActionVerificationStatus.NOT_REQUIRED,
            safe_summary="Action was superseded by newer authoritative input.",
            code="action_superseded",
            recovery=ActionRecoveryDirective(ActionRecoveryKind.REBUILD_CONTEXT, "action_superseded"),
            now=now,
        )
    if fence.cancelled:
        return _receipt(
            invocation,
            status=ActionLifecycleStatus.CANCELLED,
            verification_status=ActionVerificationStatus.NOT_REQUIRED,
            safe_summary="Action was cancelled.",
            code="action_cancelled",
            recovery=ActionRecoveryDirective(ActionRecoveryKind.SAFE_STOP, "action_cancelled"),
            now=now,
        )
    if not fence.lease_current or fence.lease_generation != invocation.lease_generation:
        return _receipt(
            invocation,
            status=ActionLifecycleStatus.SUPERSEDED,
            verification_status=ActionVerificationStatus.NOT_REQUIRED,
            safe_summary="Action lost its lease generation.",
            code="action_lease_stale",
            recovery=ActionRecoveryDirective(ActionRecoveryKind.REBUILD_CONTEXT, "action_lease_stale"),
            now=now,
        )
    return None



def _execution_lifecycle(status: ActionExecutionStatus) -> ActionLifecycleStatus:
    return {
        ActionExecutionStatus.RETRYABLE_FAILED: ActionLifecycleStatus.RETRYABLE_FAILED,
        ActionExecutionStatus.PERMANENT_FAILED: ActionLifecycleStatus.PERMANENT_FAILED,
        ActionExecutionStatus.DENIED: ActionLifecycleStatus.DENIED,
        ActionExecutionStatus.CANCELLED: ActionLifecycleStatus.CANCELLED,
        ActionExecutionStatus.TIMED_OUT: ActionLifecycleStatus.TIMED_OUT,
        ActionExecutionStatus.SUPERSEDED: ActionLifecycleStatus.SUPERSEDED,
        ActionExecutionStatus.SUCCEEDED: ActionLifecycleStatus.SUCCEEDED_UNVERIFIED,
    }[status]


def _recovery(
    descriptor: ActionDescriptor,
    invocation: ActionInvocation,
    *,
    code: str,
) -> ActionRecoveryDirective:
    policy = descriptor.retry_policy
    can_retry = (
        ActionRecoveryKind.RETRY in descriptor.recovery_kinds
        and policy.retry_class.value != "never"
        and invocation.retry_index + 1 < policy.max_attempts
        and code in policy.retryable_codes
    )
    if can_retry:
        delay = policy.backoff_seconds[invocation.retry_index] if invocation.retry_index < len(policy.backoff_seconds) else 0
        return ActionRecoveryDirective(ActionRecoveryKind.RETRY, code, retry_after_seconds=delay)
    if ActionRecoveryKind.REBUILD_CONTEXT in descriptor.recovery_kinds:
        return ActionRecoveryDirective(ActionRecoveryKind.REBUILD_CONTEXT, code)
    if ActionRecoveryKind.REQUEST_CLARIFICATION in descriptor.recovery_kinds:
        return ActionRecoveryDirective(ActionRecoveryKind.REQUEST_CLARIFICATION, code)
    return ActionRecoveryDirective(ActionRecoveryKind.SAFE_STOP, code)


def _receipt(
    invocation: ActionInvocation,
    *,
    status: ActionLifecycleStatus,
    verification_status: ActionVerificationStatus,
    safe_summary: str,
    code: str | None,
    recovery: ActionRecoveryDirective,
    now: datetime,
    authority: ActionAuthorityReference | None = None,
    result_hash: str | None = None,
    verification_hash: str | None = None,
) -> ActionReceipt:
    if not status.terminal:
        raise ActionRuntimeError("runtime may only persist terminal invocation receipts")
    return ActionReceipt(
        invocation_id=invocation.invocation_id,
        action_id=invocation.action_id,
        action_version=invocation.action_version,
        stable_action_key=invocation.stable_action_key,
        status=status,
        input_revision=invocation.input_revision,
        action_generation=invocation.action_generation,
        retry_index=invocation.retry_index,
        authority=authority,
        safe_summary=safe_summary,
        result_hash=result_hash,
        verification_status=verification_status,
        verification_hash=verification_hash,
        diagnostic_code=code,
        recovery=recovery,
        terminal_at=_utc(now),
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = [
    "ActionAdapter",
    "ActionReceiptStore",
    "ActionRuntimeBudget",
    "ActionRuntimeError",
    "ActionRuntimeOutcome",
    "ActionRuntimeUsage",
    "ActionVerifier",
    "CallableActionAdapter",
    "ControlledActionRuntime",
    "InMemoryActionFence",
    "InMemoryActionReceiptStore",
    "SchemaActionVerifier",
]
