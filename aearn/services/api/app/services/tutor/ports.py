"""Injected service ports and deterministic fakes for the Tutor Harness."""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Protocol

from app.agents.harness.contracts import (
    TokenEstimator as TokenEstimator,
    TutorCapabilityRequest,
    TutorCapabilityResult,
    TutorCapabilityStatus,
    TutorCheckpoint,
    TutorCompactionRequest,
    TutorContextInput,
    TutorContextSelection,
    TutorDecision,
    TutorDecisionGateResult,
    TutorDecisionGateStatus,
    TutorEffectProposal,
    TutorEffectResult,
    TutorEffectStatus,
    TutorInputEvent,
    TutorLease,
    TutorProviderAttemptReceipt,
    TutorProviderResult,
    TutorRunResult,
    TutorRunSnapshot,
)
from app.services.tutor.public_thinking_stream import TutorPublicThinkingSink


class TutorRunStore(Protocol):
    def load_snapshot(self, run_id: str) -> TutorRunSnapshot | None: ...

    def acquire_lease(
        self,
        run_id: str,
        *,
        owner_id: str,
        now: datetime,
        duration_seconds: int,
    ) -> TutorLease | None: ...

    def heartbeat_lease(
        self,
        lease: TutorLease,
        *,
        now: datetime,
        duration_seconds: int,
    ) -> TutorLease | None: ...

    def current_input_revision(self, run_id: str) -> int: ...

    def is_cancelled(self, run_id: str) -> bool: ...

    def is_superseded(self, run_id: str) -> bool: ...

    def save_checkpoint(self, checkpoint: TutorCheckpoint) -> None: ...

    def record_result(self, result: TutorRunResult) -> None: ...


class TutorContextLoader(Protocol):
    def load_context(self, snapshot: TutorRunSnapshot, *, input_revision: int) -> TutorContextInput: ...


class TutorProviderGateway(Protocol):
    def decide(
        self,
        *,
        run: TutorRunSnapshot,
        context: TutorContextSelection,
        thinking_sink: TutorPublicThinkingSink | None = None,
    ) -> TutorProviderResult: ...


class TutorCapabilityGateway(Protocol):
    def dispatch(
        self,
        *,
        run: TutorRunSnapshot,
        request: TutorCapabilityRequest,
    ) -> TutorCapabilityResult: ...


class TutorDecisionGate(Protocol):
    def validate(
        self,
        *,
        run: TutorRunSnapshot,
        decision: TutorDecision,
    ) -> TutorDecisionGateResult: ...


class TutorEffectCommitter(Protocol):
    def commit(
        self,
        *,
        run: TutorRunSnapshot,
        proposal: TutorEffectProposal,
    ) -> TutorEffectResult: ...


class TutorCompactionPublisher(Protocol):
    def publish(self, request: TutorCompactionRequest) -> None: ...


class TutorLifecyclePersistence(Protocol):
    """Atomic persistence seam for the composed target adapter only."""

    def create_public_thinking_sink(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        decision_iteration: int,
        now: Callable[[], datetime],
    ) -> TutorPublicThinkingSink: ...

    def persist_provider_attempts(
        self,
        *,
        snapshot: TutorRunSnapshot,
        decision_iteration: int,
        attempts: tuple[TutorProviderAttemptReceipt, ...],
        created_at: datetime,
    ) -> None: ...

    def persist_safe_checkpoint(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        checkpoint: TutorCheckpoint,
        compaction_request: TutorCompactionRequest,
    ) -> None: ...

    def persist_context_high_water(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        request: TutorCompactionRequest,
        created_at: datetime,
    ) -> None: ...

    def persist_terminal(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        checkpoint: TutorCheckpoint,
        result: TutorRunResult,
        compaction_request: TutorCompactionRequest,
    ) -> TutorRunResult: ...

    def persist_interaction_request(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        decision: TutorDecision,
        result: TutorRunResult,
        created_at: datetime,
    ) -> TutorRunResult: ...

    def persist_waiting_result(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        result: TutorRunResult,
        created_at: datetime,
    ) -> TutorRunResult: ...


class TutorLifecycleConflict(RuntimeError):
    """The composed lifecycle lost lease/revision/terminal ownership without committing."""


class Clock(Protocol):
    def now(self) -> datetime: ...


class FixedClock:
    """Deterministic clock for unit tests and isolated loop simulation."""

    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, *, seconds: int) -> None:
        self._now += timedelta(seconds=seconds)


class InMemoryTutorRunStore:
    """Non-durable fake that proves lease and monotonic revision behavior."""

    def __init__(self, snapshots: Iterable[TutorRunSnapshot] = ()) -> None:
        self._snapshots: dict[str, TutorRunSnapshot] = {}
        self._input_revisions: dict[str, int] = {}
        self._cancelled: set[str] = set()
        self._superseded: set[str] = set()
        self._leases: dict[str, TutorLease] = {}
        self._lease_generations: dict[str, int] = {}
        self.checkpoints: list[TutorCheckpoint] = []
        self.results: list[TutorRunResult] = []
        self.lease_attempts = 0
        self.deny_leases = False
        for snapshot in snapshots:
            self.add_snapshot(snapshot)

    def add_snapshot(self, snapshot: TutorRunSnapshot) -> None:
        self._snapshots[snapshot.run_id] = snapshot
        self._input_revisions[snapshot.run_id] = snapshot.input_revision

    def load_snapshot(self, run_id: str) -> TutorRunSnapshot | None:
        snapshot = self._snapshots.get(run_id)
        if snapshot is None:
            return None
        return replace(
            snapshot,
            input_revision=self._input_revisions[run_id],
            cancelled=run_id in self._cancelled or snapshot.cancelled,
        )

    def acquire_lease(
        self,
        run_id: str,
        *,
        owner_id: str,
        now: datetime,
        duration_seconds: int,
    ) -> TutorLease | None:
        self.lease_attempts += 1
        if self.deny_leases or run_id not in self._snapshots:
            return None
        current = self._leases.get(run_id)
        if current is not None and current.expires_at > now and current.owner_id != owner_id:
            return None
        generation = self._lease_generations.get(run_id, 0) + 1
        lease = TutorLease(
            run_id=run_id,
            owner_id=owner_id,
            expires_at=now + timedelta(seconds=duration_seconds),
            generation=generation,
        )
        self._leases[run_id] = lease
        self._lease_generations[run_id] = generation
        return lease

    def heartbeat_lease(
        self,
        lease: TutorLease,
        *,
        now: datetime,
        duration_seconds: int,
    ) -> TutorLease | None:
        current = self._leases.get(lease.run_id)
        # A late heartbeat may renew only while the exact owner/generation CAS
        # still matches. Any replacement claim changes the generation first.
        if current != lease:
            return None
        renewed = TutorLease(
            run_id=lease.run_id,
            owner_id=lease.owner_id,
            expires_at=now + timedelta(seconds=duration_seconds),
            generation=lease.generation,
        )
        self._leases[lease.run_id] = renewed
        return renewed

    def current_input_revision(self, run_id: str) -> int:
        return self._input_revisions[run_id]

    def accept_input(self, event: TutorInputEvent) -> TutorRunSnapshot:
        if event.run_id not in self._snapshots:
            raise KeyError(event.run_id)
        current_revision = self._input_revisions[event.run_id]
        if event.revision != current_revision + 1:
            raise ValueError("Tutor input revisions must increment by one")
        self._input_revisions[event.run_id] = event.revision
        snapshot = self.load_snapshot(event.run_id)
        if snapshot is None:
            raise KeyError(event.run_id)
        return snapshot

    def cancel(self, run_id: str) -> None:
        self._cancelled.add(run_id)

    def supersede(self, run_id: str) -> None:
        self._superseded.add(run_id)

    def is_cancelled(self, run_id: str) -> bool:
        return run_id in self._cancelled or bool(self._snapshots.get(run_id, None) and self._snapshots[run_id].cancelled)

    def is_superseded(self, run_id: str) -> bool:
        return run_id in self._superseded

    def save_checkpoint(self, checkpoint: TutorCheckpoint) -> None:
        self.checkpoints.append(checkpoint)

    def record_result(self, result: TutorRunResult) -> None:
        self.results.append(result)


class InMemoryTutorContextLoader:
    """Revision-indexed, non-persistent scoped context fake."""

    def __init__(self, contexts: Mapping[tuple[str, int], TutorContextInput]) -> None:
        self._contexts = dict(contexts)
        self.loaded_revisions: list[tuple[str, int]] = []

    def load_context(self, snapshot: TutorRunSnapshot, *, input_revision: int) -> TutorContextInput:
        self.loaded_revisions.append((snapshot.run_id, input_revision))
        context = self._contexts[(snapshot.run_id, input_revision)]
        return replace(context, input_revision=input_revision)


class SequenceTutorProvider:
    """Returns injected results in order without any model or network call."""

    def __init__(
        self,
        results: Iterable[TutorProviderResult],
        *,
        on_decide: Callable[[TutorRunSnapshot, TutorContextSelection], None] | None = None,
    ) -> None:
        self._results = list(results)
        self._on_decide = on_decide
        self.calls: list[tuple[TutorRunSnapshot, TutorContextSelection]] = []

    def decide(
        self,
        *,
        run: TutorRunSnapshot,
        context: TutorContextSelection,
        thinking_sink: TutorPublicThinkingSink | None = None,
    ) -> TutorProviderResult:
        del thinking_sink
        self.calls.append((run, context))
        if self._on_decide is not None:
            self._on_decide(run, context)
        if not self._results:
            return TutorProviderResult.model_unavailable()
        return self._results.pop(0)


class DefaultDenyCapabilityGateway:
    def dispatch(self, *, run: TutorRunSnapshot, request: TutorCapabilityRequest) -> TutorCapabilityResult:
        del run
        return TutorCapabilityResult(
            request_id=request.request_id,
            status=TutorCapabilityStatus.DENIED,
            continue_run=False,
        )


class SequenceCapabilityGateway:
    def __init__(self, results: Iterable[TutorCapabilityResult]) -> None:
        self._results = list(results)
        self.calls: list[TutorCapabilityRequest] = []

    def dispatch(self, *, run: TutorRunSnapshot, request: TutorCapabilityRequest) -> TutorCapabilityResult:
        del run
        self.calls.append(request)
        if not self._results:
            return TutorCapabilityResult(request_id=request.request_id, status=TutorCapabilityStatus.UNAVAILABLE)
        return self._results.pop(0)


class DefaultDenyTutorDecisionGate:
    """Deny model-selected Skills, capabilities, and effects until composed explicitly."""

    def validate(
        self,
        *,
        run: TutorRunSnapshot,
        decision: TutorDecision,
    ) -> TutorDecisionGateResult:
        del run
        if decision.skill_references or decision.capability_requests or decision.effect_proposals:
            return TutorDecisionGateResult(
                status=TutorDecisionGateStatus.DENIED,
                diagnostic_code="catalog_not_configured",
            )
        return TutorDecisionGateResult(status=TutorDecisionGateStatus.APPROVED)


class AllowTutorDecisionGate:
    """Explicit deterministic fake for Child 00 loop tests only."""

    def validate(
        self,
        *,
        run: TutorRunSnapshot,
        decision: TutorDecision,
    ) -> TutorDecisionGateResult:
        del run, decision
        return TutorDecisionGateResult(status=TutorDecisionGateStatus.APPROVED)


class DefaultDenyEffectCommitter:
    def commit(self, *, run: TutorRunSnapshot, proposal: TutorEffectProposal) -> TutorEffectResult:
        del run
        return TutorEffectResult(effect_id=proposal.effect_id, status=TutorEffectStatus.DENIED)


class RecordingEffectCommitter:
    def __init__(self, *, status: TutorEffectStatus = TutorEffectStatus.COMMITTED) -> None:
        self.status = status
        self.calls: list[TutorEffectProposal] = []

    def commit(self, *, run: TutorRunSnapshot, proposal: TutorEffectProposal) -> TutorEffectResult:
        del run
        self.calls.append(proposal)
        commit_id = f"commit:{proposal.effect_id}" if self.status is TutorEffectStatus.COMMITTED else None
        return TutorEffectResult(effect_id=proposal.effect_id, status=self.status, commit_id=commit_id)


class InMemoryTutorCompactionPublisher:
    """Idempotent recording publisher; it never calls a worker or Curator."""

    def __init__(self) -> None:
        self.requests: list[TutorCompactionRequest] = []
        self._keys: set[str] = set()

    def publish(self, request: TutorCompactionRequest) -> None:
        if request.idempotency_key in self._keys:
            return
        self._keys.add(request.idempotency_key)
        self.requests.append(request)


class NoopTutorCompactionPublisher:
    def publish(self, request: TutorCompactionRequest) -> None:
        del request
