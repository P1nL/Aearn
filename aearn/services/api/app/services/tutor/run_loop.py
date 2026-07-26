"""Finite, feature-disabled Tutor Harness run loop."""
from __future__ import annotations

from dataclasses import replace
from typing import Final

from app.agents.harness.context_builder import TutorContextBuilder
from app.agents.harness.contracts import (
    TutorCapabilityStatus,
    TutorCheckpoint,
    TutorCheckpointMetadata,
    TutorCheckpointReason,
    TutorCompactionTrigger,
    TutorDecision,
    TutorEffectResult,
    TutorEffectStatus,
    TutorLease,
    TutorRunResult,
    TutorRunSnapshot,
    TutorRunStatus,
    TutorTerminalOutcome,
    build_compaction_request,
    empty_checkpoint_metadata,
    terminal_status,
)
from app.core.config import Settings
from app.services.tutor.ports import (
    Clock,
    TutorCapabilityGateway,
    TutorCompactionPublisher,
    TutorContextLoader,
    TutorEffectCommitter,
    TutorProviderGateway,
    TutorRunStore,
)


_POLICY_BLOCKED: Final[str] = "blocked_policy"


class TutorRunLoop:
    """Run bounded Tutor decisions without routes, Graphs, persistence, or workers."""

    def __init__(
        self,
        *,
        store: TutorRunStore,
        context_loader: TutorContextLoader,
        context_builder: TutorContextBuilder,
        provider: TutorProviderGateway,
        capability_gateway: TutorCapabilityGateway,
        effect_committer: TutorEffectCommitter,
        clock: Clock,
        compaction_publisher: TutorCompactionPublisher,
    ) -> None:
        self._store = store
        self._context_loader = context_loader
        self._context_builder = context_builder
        self._provider = provider
        self._capability_gateway = capability_gateway
        self._effect_committer = effect_committer
        self._clock = clock
        self._compaction_publisher = compaction_publisher

    def run(self, *, run_id: str, lease_owner_id: str) -> TutorRunResult:
        snapshot = self._store.load_snapshot(run_id)
        if snapshot is None:
            return _missing_run_result(run_id)

        lease = self._store.acquire_lease(
            run_id,
            owner_id=lease_owner_id,
            now=self._clock.now(),
            duration_seconds=snapshot.policy.lease_duration_seconds,
        )
        if lease is None:
            return TutorRunResult(
                run_id=snapshot.run_id,
                status=TutorRunStatus.BLOCKED_POLICY,
                input_revision=snapshot.input_revision,
                iteration_count=snapshot.iteration_count,
                model_call_count=snapshot.model_call_count,
                capability_call_count=snapshot.capability_call_count,
                effect_count=snapshot.effect_count,
                terminal_outcome=TutorTerminalOutcome.BLOCKED_POLICY,
                diagnostic_code="lease_unavailable",
            )

        snapshot = replace(snapshot, status=TutorRunStatus.LEASED, lease=lease)
        effect_results: list[TutorEffectResult] = []
        metadata = empty_checkpoint_metadata(token_budget=snapshot.policy.context_token_budget)

        try:
            initial_stop = self._stop_outcome(snapshot)
            if initial_stop is not None:
                outcome, diagnostic = initial_stop
                return self._terminal(snapshot, outcome=outcome, diagnostic_code=diagnostic, metadata=metadata)

            while True:
                stop = self._stop_outcome(snapshot)
                if stop is not None:
                    outcome, diagnostic = stop
                    return self._terminal(
                        snapshot,
                        outcome=outcome,
                        diagnostic_code=diagnostic,
                        metadata=metadata,
                        effect_results=effect_results,
                    )

                if snapshot.iteration_count >= snapshot.policy.max_iterations:
                    return self._terminal(
                        snapshot,
                        outcome=TutorTerminalOutcome.BUDGET_EXHAUSTED,
                        diagnostic_code="iteration_budget_exhausted",
                        metadata=metadata,
                        effect_results=effect_results,
                    )
                if snapshot.model_call_count >= snapshot.policy.max_model_calls:
                    return self._terminal(
                        snapshot,
                        outcome=TutorTerminalOutcome.BUDGET_EXHAUSTED,
                        diagnostic_code="model_call_budget_exhausted",
                        metadata=metadata,
                        effect_results=effect_results,
                    )

                lease = self._heartbeat(lease, snapshot)
                if lease is None:
                    return self._terminal(
                        snapshot,
                        outcome=TutorTerminalOutcome.BLOCKED_POLICY,
                        diagnostic_code="lease_expired",
                        metadata=metadata,
                        effect_results=effect_results,
                    )

                current_revision = self._store.current_input_revision(snapshot.run_id)
                snapshot = replace(
                    snapshot,
                    status=TutorRunStatus.RUNNING,
                    lease=lease,
                    input_revision=current_revision,
                )
                context_input = self._context_loader.load_context(snapshot, input_revision=current_revision)
                context = self._context_builder.build(
                    context_input,
                    token_budget=snapshot.policy.context_token_budget,
                )
                metadata = context.checkpoint_metadata
                if context.high_water_compaction_request is not None:
                    self._compaction_publisher.publish(context.high_water_compaction_request)

                # Reload immediately before the model boundary so a newly accepted
                # learner input cannot be answered with stale composed context.
                before_model_revision = self._store.current_input_revision(snapshot.run_id)
                if before_model_revision != snapshot.input_revision:
                    snapshot = replace(snapshot, input_revision=before_model_revision)
                    continue

                provider_result = self._provider.decide(run=snapshot, context=context)
                snapshot = replace(
                    snapshot,
                    iteration_count=snapshot.iteration_count + 1,
                    model_call_count=snapshot.model_call_count + 1,
                )
                if provider_result.terminal_outcome is not None:
                    return self._terminal(
                        snapshot,
                        outcome=provider_result.terminal_outcome,
                        diagnostic_code=provider_result.safe_code,
                        metadata=metadata,
                        effect_results=effect_results,
                    )
                decision = provider_result.decision
                if decision is None:
                    return self._terminal(
                        snapshot,
                        outcome=TutorTerminalOutcome.MODEL_UNAVAILABLE,
                        diagnostic_code="MODEL_UNAVAILABLE",
                        metadata=metadata,
                        effect_results=effect_results,
                    )

                if decision.checkpoint_reason is not None:
                    self._save_safe_checkpoint(
                        snapshot,
                        reason=decision.checkpoint_reason,
                        metadata=metadata,
                    )

                snapshot, needs_rebuild, terminal = self._dispatch_capabilities(
                    snapshot,
                    lease=lease,
                    decision=decision,
                    metadata=metadata,
                    effect_results=effect_results,
                )
                lease = snapshot.lease or lease
                if terminal is not None:
                    return terminal
                if needs_rebuild:
                    continue

                snapshot, needs_rebuild, terminal = self._commit_effects(
                    snapshot,
                    lease=lease,
                    decision=decision,
                    metadata=metadata,
                    effect_results=effect_results,
                )
                lease = snapshot.lease or lease
                if terminal is not None:
                    return terminal
                if needs_rebuild:
                    continue

                if decision.terminal_outcome is not None:
                    return self._terminal(
                        snapshot,
                        outcome=decision.terminal_outcome,
                        diagnostic_code=None,
                        metadata=metadata,
                        effect_results=effect_results,
                        public_message=decision.public_message,
                    )

                return self._waiting_for_input(snapshot, decision=decision, effect_results=effect_results)
        except Exception:
            return self._terminal(
                snapshot,
                outcome=TutorTerminalOutcome.FAILED,
                diagnostic_code="tutor_runtime_failed",
                metadata=metadata,
                effect_results=effect_results,
            )

    def feature_disabled_result(self, *, run_id: str) -> TutorRunResult:
        """Return a local denial without taking a lease or touching product traffic."""
        snapshot = self._store.load_snapshot(run_id)
        if snapshot is None:
            return _missing_run_result(run_id)
        return TutorRunResult(
            run_id=snapshot.run_id,
            status=TutorRunStatus.BLOCKED_POLICY,
            input_revision=snapshot.input_revision,
            iteration_count=snapshot.iteration_count,
            model_call_count=snapshot.model_call_count,
            capability_call_count=snapshot.capability_call_count,
            effect_count=snapshot.effect_count,
            terminal_outcome=TutorTerminalOutcome.BLOCKED_POLICY,
            diagnostic_code="feature_disabled",
        )

    def _dispatch_capabilities(
        self,
        snapshot: TutorRunSnapshot,
        *,
        lease: TutorLease,
        decision: TutorDecision,
        metadata: TutorCheckpointMetadata,
        effect_results: list[TutorEffectResult],
    ) -> tuple[TutorRunSnapshot, bool, TutorRunResult | None]:
        for request in decision.capability_requests:
            refreshed, terminal = self._refresh_before_unsafe_boundary(
                snapshot,
                lease=lease,
                metadata=metadata,
                effect_results=effect_results,
            )
            if terminal is not None:
                return snapshot, False, terminal
            if refreshed.input_revision != snapshot.input_revision:
                return refreshed, True, None
            snapshot = refreshed
            if snapshot.capability_call_count >= snapshot.policy.max_capability_calls:
                return snapshot, False, self._terminal(
                    snapshot,
                    outcome=TutorTerminalOutcome.BUDGET_EXHAUSTED,
                    diagnostic_code="capability_call_budget_exhausted",
                    metadata=metadata,
                    effect_results=effect_results,
                )

            result = self._capability_gateway.dispatch(run=snapshot, request=request)
            snapshot = replace(snapshot, capability_call_count=snapshot.capability_call_count + 1)
            current_revision = self._store.current_input_revision(snapshot.run_id)
            if current_revision != snapshot.input_revision:
                return replace(snapshot, input_revision=current_revision), True, None
            if result.status is not TutorCapabilityStatus.COMPLETED:
                return snapshot, False, self._terminal(
                    snapshot,
                    outcome=TutorTerminalOutcome.BLOCKED_POLICY,
                    diagnostic_code="capability_denied",
                    metadata=metadata,
                    effect_results=effect_results,
                )
            if result.continue_run:
                return snapshot, True, None
        return snapshot, False, None

    def _commit_effects(
        self,
        snapshot: TutorRunSnapshot,
        *,
        lease: TutorLease,
        decision: TutorDecision,
        metadata: TutorCheckpointMetadata,
        effect_results: list[TutorEffectResult],
    ) -> tuple[TutorRunSnapshot, bool, TutorRunResult | None]:
        for proposal in decision.effect_proposals:
            refreshed, terminal = self._refresh_before_unsafe_boundary(
                snapshot,
                lease=lease,
                metadata=metadata,
                effect_results=effect_results,
            )
            if terminal is not None:
                return snapshot, False, terminal
            current_revision = refreshed.input_revision
            if current_revision != proposal.expected_input_revision:
                effect_results.append(
                    TutorEffectResult(effect_id=proposal.effect_id, status=TutorEffectStatus.STALE_REJECTED)
                )
                return refreshed, True, None
            snapshot = replace(refreshed, status=TutorRunStatus.AWAITING_EFFECT_COMMIT)
            if snapshot.effect_count >= snapshot.policy.max_effects:
                return snapshot, False, self._terminal(
                    snapshot,
                    outcome=TutorTerminalOutcome.BUDGET_EXHAUSTED,
                    diagnostic_code="effect_budget_exhausted",
                    metadata=metadata,
                    effect_results=effect_results,
                )

            result = self._effect_committer.commit(run=snapshot, proposal=proposal)
            effect_results.append(result)
            snapshot = replace(snapshot, effect_count=snapshot.effect_count + 1, status=TutorRunStatus.RUNNING)
            if result.status is not TutorEffectStatus.COMMITTED:
                return snapshot, False, self._terminal(
                    snapshot,
                    outcome=TutorTerminalOutcome.BLOCKED_POLICY,
                    diagnostic_code=_POLICY_BLOCKED,
                    metadata=metadata,
                    effect_results=effect_results,
                )
        return snapshot, False, None

    def _refresh_before_unsafe_boundary(
        self,
        snapshot: TutorRunSnapshot,
        *,
        lease: TutorLease,
        metadata: TutorCheckpointMetadata,
        effect_results: list[TutorEffectResult],
    ) -> tuple[TutorRunSnapshot, TutorRunResult | None]:
        stop = self._stop_outcome(snapshot)
        if stop is not None:
            outcome, diagnostic = stop
            return snapshot, self._terminal(
                snapshot,
                outcome=outcome,
                diagnostic_code=diagnostic,
                metadata=metadata,
                effect_results=effect_results,
            )
        refreshed_lease = self._heartbeat(lease, snapshot)
        if refreshed_lease is None:
            return snapshot, self._terminal(
                snapshot,
                outcome=TutorTerminalOutcome.BLOCKED_POLICY,
                diagnostic_code="lease_expired",
                metadata=metadata,
                effect_results=effect_results,
            )
        current_revision = self._store.current_input_revision(snapshot.run_id)
        return replace(snapshot, lease=refreshed_lease, input_revision=current_revision), None

    def _heartbeat(self, lease: TutorLease, snapshot: TutorRunSnapshot) -> TutorLease | None:
        return self._store.heartbeat_lease(
            lease,
            now=self._clock.now(),
            duration_seconds=snapshot.policy.lease_duration_seconds,
        )

    def _stop_outcome(self, snapshot: TutorRunSnapshot) -> tuple[TutorTerminalOutcome, str] | None:
        if self._store.is_cancelled(snapshot.run_id) or snapshot.cancelled:
            return TutorTerminalOutcome.CANCELLED, "cancelled"
        if self._clock.now() >= snapshot.policy.deadline:
            return TutorTerminalOutcome.BUDGET_EXHAUSTED, "deadline_exhausted"
        return None

    def _save_safe_checkpoint(
        self,
        snapshot: TutorRunSnapshot,
        *,
        reason: TutorCheckpointReason,
        metadata: TutorCheckpointMetadata,
    ) -> None:
        checkpoint = TutorCheckpoint(
            run_id=snapshot.run_id,
            input_revision=snapshot.input_revision,
            reason=reason,
            status=snapshot.status,
            metadata=metadata,
            created_at=self._clock.now(),
        )
        self._store.save_checkpoint(checkpoint)
        self._compaction_publisher.publish(
            build_compaction_request(
                run_id=snapshot.run_id,
                conversation_id=snapshot.conversation_id,
                input_revision=snapshot.input_revision,
                trigger=TutorCompactionTrigger.SAFE_CHECKPOINT,
                metadata=metadata,
            )
        )

    def _terminal(
        self,
        snapshot: TutorRunSnapshot,
        *,
        outcome: TutorTerminalOutcome,
        diagnostic_code: str | None,
        metadata: TutorCheckpointMetadata | None = None,
        effect_results: list[TutorEffectResult] | tuple[TutorEffectResult, ...] = (),
        public_message: str | None = None,
    ) -> TutorRunResult:
        checkpoint_metadata = metadata or empty_checkpoint_metadata(token_budget=snapshot.policy.context_token_budget)
        status = terminal_status(outcome)
        checkpoint = TutorCheckpoint(
            run_id=snapshot.run_id,
            input_revision=snapshot.input_revision,
            reason=TutorCheckpointReason.TERMINAL,
            status=status,
            metadata=checkpoint_metadata,
            created_at=self._clock.now(),
        )
        self._store.save_checkpoint(checkpoint)
        self._compaction_publisher.publish(
            build_compaction_request(
                run_id=snapshot.run_id,
                conversation_id=snapshot.conversation_id,
                input_revision=snapshot.input_revision,
                trigger=TutorCompactionTrigger.TERMINAL,
                metadata=checkpoint_metadata,
            )
        )
        result = TutorRunResult(
            run_id=snapshot.run_id,
            status=status,
            input_revision=snapshot.input_revision,
            iteration_count=snapshot.iteration_count,
            model_call_count=snapshot.model_call_count,
            capability_call_count=snapshot.capability_call_count,
            effect_count=snapshot.effect_count,
            terminal_outcome=outcome,
            public_message=public_message,
            diagnostic_code=diagnostic_code,
            effect_results=tuple(effect_results),
        )
        self._store.record_result(result)
        return result

    def _waiting_for_input(
        self,
        snapshot: TutorRunSnapshot,
        *,
        decision: TutorDecision,
        effect_results: list[TutorEffectResult],
    ) -> TutorRunResult:
        result = TutorRunResult(
            run_id=snapshot.run_id,
            status=TutorRunStatus.WAITING_FOR_INPUT,
            input_revision=snapshot.input_revision,
            iteration_count=snapshot.iteration_count,
            model_call_count=snapshot.model_call_count,
            capability_call_count=snapshot.capability_call_count,
            effect_count=snapshot.effect_count,
            public_message=decision.public_message,
            effect_results=tuple(effect_results),
        )
        self._store.record_result(result)
        return result


class TutorHarnessService:
    """An internal feature gate; no route, stream, or UI instantiates it in Child 00."""

    def __init__(self, *, loop: TutorRunLoop, enabled: bool) -> None:
        self._loop = loop
        self._enabled = enabled

    @classmethod
    def from_settings(cls, *, loop: TutorRunLoop, settings: Settings) -> "TutorHarnessService":
        return cls(loop=loop, enabled=settings.tutor_harness_enabled)

    def run(self, *, run_id: str, lease_owner_id: str) -> TutorRunResult:
        if not self._enabled:
            return self._loop.feature_disabled_result(run_id=run_id)
        return self._loop.run(run_id=run_id, lease_owner_id=lease_owner_id)


def _missing_run_result(run_id: str) -> TutorRunResult:
    return TutorRunResult(
        run_id=run_id,
        status=TutorRunStatus.FAILED,
        input_revision=0,
        iteration_count=0,
        model_call_count=0,
        capability_call_count=0,
        effect_count=0,
        terminal_outcome=TutorTerminalOutcome.FAILED,
        diagnostic_code="run_not_found",
    )
