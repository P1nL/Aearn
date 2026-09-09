"""Finite, feature-disabled Tutor Harness run loop."""
from __future__ import annotations

import json
import logging
from dataclasses import replace
from typing import Final

from app.agents.harness.context_budget import TutorContextBudgetPlanner
from app.agents.harness.context_builder import TutorContextBuilder
from app.agents.harness.contracts import (
    TutorCapabilityStatus,
    TutorCheckpoint,
    TutorCheckpointMetadata,
    TutorCheckpointReason,
    TutorCompactionTrigger,
    TutorContextError,
    TutorContextInput,
    TutorContextSection,
    TutorContextSelection,
    TutorDecision,
    TutorDecisionGateStatus,
    TutorEffectResult,
    TutorEffectStatus,
    TutorLease,
    TutorRunResult,
    TutorRunSnapshot,
    TutorRunStatus,
    TutorTerminalOutcome,
    TutorTurnCompletionReason,
    build_compaction_request,
    empty_checkpoint_metadata,
    terminal_status,
)
from app.core.safe_diagnostics import log_safe_event, safe_diagnostic_identifier
from app.agents.harness.skill_catalog import SkillCatalogSnapshot
from app.services.learning.teaching_contracts import TeachingStepDecision
from app.services.tutor.public_thinking_stream import TutorPublicThinkingSink
from app.services.tutor.ports import (
    Clock,
    DefaultDenyTutorDecisionGate,
    TutorCapabilityGateway,
    TutorCompactionPublisher,
    TutorContextLoader,
    TutorDecisionGate,
    TutorEffectCommitter,
    TutorLifecycleConflict,
    TutorLifecyclePersistence,
    TutorProviderGateway,
    TutorRunStore,
)


logger = logging.getLogger(__name__)


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
        context_budget_planner: TutorContextBudgetPlanner | None = None,
        capability_gateway: TutorCapabilityGateway,
        effect_committer: TutorEffectCommitter,
        clock: Clock,
        compaction_publisher: TutorCompactionPublisher,
        decision_gate: TutorDecisionGate | None = None,
        lifecycle: TutorLifecyclePersistence | None = None,
    ) -> None:
        self._store = store
        self._context_loader = context_loader
        self._context_builder = context_builder
        self._context_budget_planner = context_budget_planner or TutorContextBudgetPlanner()
        self._provider = provider
        self._capability_gateway = capability_gateway
        self._effect_committer = effect_committer
        self._decision_gate = decision_gate or DefaultDenyTutorDecisionGate()
        self._clock = clock
        self._compaction_publisher = compaction_publisher
        self._lifecycle = lifecycle

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
            return _lease_unavailable_result(snapshot)

        snapshot = replace(snapshot, status=TutorRunStatus.LEASED, lease=lease)
        effect_results: list[TutorEffectResult] = []
        context_expansion_count = 0
        metadata = empty_checkpoint_metadata(token_budget=snapshot.policy.context_token_budget)
        thinking_sink: TutorPublicThinkingSink | None = None

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
                    _discard_public_thinking(thinking_sink)
                    return self._terminal(
                        snapshot,
                        outcome=TutorTerminalOutcome.BLOCKED_POLICY,
                        diagnostic_code="lease_expired",
                        metadata=metadata,
                        effect_results=effect_results,
                    )

                current_revision = self._store.current_input_revision(snapshot.run_id)
                if current_revision != snapshot.input_revision:
                    context_expansion_count = 0
                snapshot = replace(
                    snapshot,
                    status=TutorRunStatus.RUNNING,
                    lease=lease,
                    input_revision=current_revision,
                )
                context_input = self._context_loader.load_context(snapshot, input_revision=current_revision)
                context = self._context_budget_planner.build_context(
                    run=snapshot,
                    context_input=context_input,
                    builder=self._context_builder,
                    expansion_count=context_expansion_count,
                )
                result_evaluation_fallback = _result_evaluation_fallback(context)
                metadata = context.checkpoint_metadata
                if context.high_water_compaction_request is not None:
                    if self._lifecycle is None:
                        self._compaction_publisher.publish(context.high_water_compaction_request)
                    else:
                        if snapshot.lease is None:
                            raise RuntimeError("owned Tutor lifecycle is missing a lease")
                        self._lifecycle.persist_context_high_water(
                            snapshot=snapshot,
                            lease=snapshot.lease,
                            request=context.high_water_compaction_request,
                            created_at=self._clock.now(),
                        )

                # Reload immediately before the model boundary so a newly accepted
                # learner input cannot be answered with stale composed context.
                before_model_revision = self._store.current_input_revision(snapshot.run_id)
                if before_model_revision != snapshot.input_revision:
                    context_expansion_count = 0
                    snapshot = replace(snapshot, input_revision=before_model_revision)
                    continue

                decision_iteration = snapshot.model_call_count + 1
                thinking_sink = None
                if (
                    self._lifecycle is not None
                    and snapshot.origin == "interactive"
                    and snapshot.interaction_protocol_version == "thread_turn_v2"
                ):
                    create_sink = getattr(self._lifecycle, "create_public_thinking_sink", None)
                    if callable(create_sink):
                        thinking_sink = create_sink(
                            snapshot=snapshot,
                            lease=lease,
                            decision_iteration=decision_iteration,
                            now=self._clock.now,
                        )
                provider_result = (
                    self._provider.decide(
                        run=snapshot,
                        context=context,
                        thinking_sink=thinking_sink,
                    )
                    if thinking_sink is not None
                    else self._provider.decide(run=snapshot, context=context)
                )
                if self._lifecycle is not None and provider_result.attempts:
                    self._lifecycle.persist_provider_attempts(
                        snapshot=snapshot,
                        decision_iteration=decision_iteration,
                        attempts=provider_result.attempts,
                        created_at=self._clock.now(),
                    )
                snapshot = replace(
                    snapshot,
                    iteration_count=snapshot.iteration_count + 1,
                    model_call_count=decision_iteration,
                )
                refreshed, terminal = self._refresh_before_unsafe_boundary(
                    snapshot,
                    lease=lease,
                    metadata=metadata,
                    effect_results=effect_results,
                )
                if terminal is not None:
                    _discard_public_thinking(thinking_sink)
                    return terminal
                if refreshed.input_revision != snapshot.input_revision:
                    _discard_public_thinking(thinking_sink)
                    context_expansion_count = 0
                    snapshot = refreshed
                    continue
                snapshot = refreshed
                lease = snapshot.lease or lease

                if provider_result.terminal_outcome is not None:
                    _discard_public_thinking(thinking_sink)
                    return self._terminal(
                        snapshot,
                        outcome=provider_result.terminal_outcome,
                        diagnostic_code=provider_result.safe_code,
                        metadata=metadata,
                        effect_results=effect_results,
                        public_message=(
                            result_evaluation_fallback
                            if provider_result.terminal_outcome
                            is TutorTerminalOutcome.MODEL_UNAVAILABLE
                            else None
                        ),
                    )

                decision = provider_result.decision
                if decision is None:
                    _discard_public_thinking(thinking_sink)
                    return self._terminal(
                        snapshot,
                        outcome=TutorTerminalOutcome.MODEL_UNAVAILABLE,
                        diagnostic_code="MODEL_UNAVAILABLE",
                        metadata=metadata,
                        effect_results=effect_results,
                        public_message=result_evaluation_fallback,
                    )

                gate_result = self._decision_gate.validate(run=snapshot, decision=decision)
                if gate_result.status is TutorDecisionGateStatus.DENIED:
                    _log_gate_denial(snapshot, decision, gate_result.diagnostic_code, context_input, self._decision_gate)
                    if gate_result.diagnostic_code == "confirmed_question_reasked":
                        metadata = replace(
                            metadata,
                            confirmed_question_reasked_count=(
                                metadata.confirmed_question_reasked_count + 1
                            ),
                        )
                    _discard_public_thinking(thinking_sink)
                    return self._terminal(
                        snapshot,
                        outcome=TutorTerminalOutcome.BLOCKED_POLICY,
                        diagnostic_code=gate_result.diagnostic_code or _POLICY_BLOCKED,
                        metadata=metadata,
                        effect_results=effect_results,
                    )
                if gate_result.status is TutorDecisionGateStatus.REBUILD_CONTEXT:
                    max_expansions = (
                        snapshot.policy.context_budget_policy.max_expansions
                        if snapshot.policy.context_budget_policy is not None
                        else 0
                    )
                    if context_expansion_count < max_expansions:
                        context_expansion_count += 1
                    _discard_public_thinking(thinking_sink)
                    continue

                refreshed, terminal = self._refresh_before_unsafe_boundary(
                    snapshot,
                    lease=lease,
                    metadata=metadata,
                    effect_results=effect_results,
                )
                if terminal is not None:
                    _discard_public_thinking(thinking_sink)
                    return terminal
                if refreshed.input_revision != snapshot.input_revision:
                    _discard_public_thinking(thinking_sink)
                    snapshot = refreshed
                    continue
                snapshot = refreshed
                lease = snapshot.lease or lease

                if decision.checkpoint_reason is not None:
                    self._save_safe_checkpoint(
                        snapshot,
                        lease=lease,
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
                    _discard_public_thinking(thinking_sink)
                    return terminal
                if needs_rebuild:
                    _discard_public_thinking(thinking_sink)
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
                    _discard_public_thinking(thinking_sink)
                    return terminal
                if needs_rebuild:
                    _discard_public_thinking(thinking_sink)
                    continue

                if decision.terminal_outcome is not None:
                    return self._terminal(
                        snapshot,
                        outcome=decision.terminal_outcome,
                        diagnostic_code=None,
                        metadata=metadata,
                        effect_results=effect_results,
                        public_message=decision.public_message,
                        public_thinking_text=decision.public_thinking_text,
                        public_thinking_steps=decision.public_thinking_steps,
                        conversation_title=decision.conversation_title,
                        teaching_step=decision.teaching_step,
                    )

                if decision.continuation_kind is not None:
                    if snapshot.interaction_protocol_version == "thread_turn_v2":
                        return self._interaction_request(snapshot, decision=decision, effect_results=effect_results)
                    return self._waiting_for_input(snapshot, decision=decision, effect_results=effect_results)

                return self._terminal(
                    snapshot,
                    outcome=TutorTerminalOutcome.COMPLETED,
                    diagnostic_code=None,
                    metadata=metadata,
                    effect_results=effect_results,
                    public_message=decision.public_message,
                    public_thinking_text=decision.public_thinking_text,
                    public_thinking_steps=decision.public_thinking_steps,
                    conversation_title=decision.conversation_title,
                )
        except TutorLifecycleConflict:
            return _lease_unavailable_result(snapshot, effect_results=effect_results)
        except TutorContextError as exc:
            _discard_public_thinking(thinking_sink)
            return self._terminal(
                snapshot,
                outcome=TutorTerminalOutcome.FAILED,
                diagnostic_code=exc.safe_code,
                metadata=metadata,
                effect_results=effect_results,
            )
        except Exception:
            _discard_public_thinking(thinking_sink)
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
                    public_message=_capability_failure_public_message(request.capability_id),
                    public_thinking_text=decision.public_thinking_text,
                    public_thinking_steps=decision.public_thinking_steps,
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
        if self._store.is_superseded(snapshot.run_id):
            return TutorTerminalOutcome.CANCELLED, "superseded"
        if self._store.is_cancelled(snapshot.run_id) or snapshot.cancelled:
            return TutorTerminalOutcome.CANCELLED, "cancelled"
        if self._clock.now() >= snapshot.policy.deadline:
            return TutorTerminalOutcome.BUDGET_EXHAUSTED, "deadline_exhausted"
        return None

    def _save_safe_checkpoint(
        self,
        snapshot: TutorRunSnapshot,
        *,
        lease: TutorLease,
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
        request = build_compaction_request(
            run_id=snapshot.run_id,
            conversation_id=snapshot.conversation_id,
            input_revision=snapshot.input_revision,
            trigger=TutorCompactionTrigger.SAFE_CHECKPOINT,
            metadata=metadata,
        )
        if self._lifecycle is not None:
            self._lifecycle.persist_safe_checkpoint(
                snapshot=snapshot,
                lease=lease,
                checkpoint=checkpoint,
                compaction_request=request,
            )
            return
        self._store.save_checkpoint(checkpoint)
        self._compaction_publisher.publish(request)

    def _terminal(
        self,
        snapshot: TutorRunSnapshot,
        *,
        outcome: TutorTerminalOutcome,
        diagnostic_code: str | None,
        metadata: TutorCheckpointMetadata | None = None,
        effect_results: list[TutorEffectResult] | tuple[TutorEffectResult, ...] = (),
        public_message: str | None = None,
        public_thinking_text: str = "",
        public_thinking_steps: tuple[str, ...] = (),
        conversation_title: str | None = None,
        teaching_step: TeachingStepDecision | None = None,
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
        request = build_compaction_request(
            run_id=snapshot.run_id,
            conversation_id=snapshot.conversation_id,
            input_revision=snapshot.input_revision,
            trigger=TutorCompactionTrigger.TERMINAL,
            metadata=checkpoint_metadata,
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
            public_thinking_text=public_thinking_text,
            public_thinking_steps=public_thinking_steps,
            conversation_title=conversation_title,
            diagnostic_code=diagnostic_code,
            effect_results=tuple(effect_results),
            teaching_step=teaching_step,
        )
        if self._lifecycle is not None:
            if snapshot.lease is None:
                raise RuntimeError("owned Tutor lifecycle is missing a lease")
            return self._lifecycle.persist_terminal(
                snapshot=snapshot,
                lease=snapshot.lease,
                checkpoint=checkpoint,
                result=result,
                compaction_request=request,
            )
        self._store.save_checkpoint(checkpoint)
        self._compaction_publisher.publish(request)
        self._store.record_result(result)
        return result

    def _interaction_request(
        self,
        snapshot: TutorRunSnapshot,
        *,
        decision: TutorDecision,
        effect_results: list[TutorEffectResult],
    ) -> TutorRunResult:
        kind = decision.continuation_kind
        if kind is None:
            raise RuntimeError("typed interaction request requires a continuation kind")
        completion_reason = (
            TutorTurnCompletionReason.AWAITING_APPROVAL
            if kind.value == "approval"
            else TutorTurnCompletionReason.AWAITING_AUTHORITY
            if kind.value in {"capability_result", "external_result"}
            else TutorTurnCompletionReason.AWAITING_USER
        )
        result = TutorRunResult(
            run_id=snapshot.run_id,
            status=TutorRunStatus.COMPLETED,
            input_revision=snapshot.input_revision,
            iteration_count=snapshot.iteration_count,
            model_call_count=snapshot.model_call_count,
            capability_call_count=snapshot.capability_call_count,
            effect_count=snapshot.effect_count,
            terminal_outcome=TutorTerminalOutcome.COMPLETED,
            public_message=decision.public_message,
            public_thinking_text=decision.public_thinking_text,
            public_thinking_steps=decision.public_thinking_steps,
            conversation_title=decision.conversation_title,
            completion_reason=completion_reason,
            effect_results=tuple(effect_results),
        )
        if self._lifecycle is not None:
            if snapshot.lease is None:
                raise RuntimeError("owned Tutor lifecycle is missing a lease")
            return self._lifecycle.persist_interaction_request(
                snapshot=snapshot,
                lease=snapshot.lease,
                decision=decision,
                result=result,
                created_at=self._clock.now(),
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
            public_thinking_text=decision.public_thinking_text,
            public_thinking_steps=decision.public_thinking_steps,
            continuation_kind=decision.continuation_kind,
            effect_results=tuple(effect_results),
        )
        if self._lifecycle is not None:
            if snapshot.lease is None:
                raise RuntimeError("owned Tutor lifecycle is missing a lease")
            return self._lifecycle.persist_waiting_result(
                snapshot=snapshot,
                lease=snapshot.lease,
                result=result,
                created_at=self._clock.now(),
            )
        self._store.record_result(result)
        return result


class TutorHarnessService:
    """Tutor runtime execution boundary."""

    def __init__(self, *, loop: TutorRunLoop, enabled: bool) -> None:
        self._loop = loop
        self._enabled = enabled

    @classmethod
    def enabled(cls, *, loop: TutorRunLoop) -> "TutorHarnessService":
        return cls(loop=loop, enabled=True)

    def run(self, *, run_id: str, lease_owner_id: str) -> TutorRunResult:
        if not self._enabled:
            return self._loop.feature_disabled_result(run_id=run_id)
        return self._loop.run(run_id=run_id, lease_owner_id=lease_owner_id)


def _discard_public_thinking(sink: TutorPublicThinkingSink | None) -> None:
    if sink is None:
        return
    try:
        sink.discard_current()
    except TutorLifecycleConflict:
        return


def _capability_failure_public_message(capability_id: str) -> str:
    if capability_id == "learning.plan.draft":
        return "计划草稿暂时没有生成成功，请重试。"
    return "这一步暂时没有完成，请重试。"


def _result_evaluation_fallback(
    context: TutorContextSelection,
) -> str | None:
    teaching_items = tuple(
        item
        for item in context.items
        if item.section is TutorContextSection.TEACHING_SESSION
    )
    if len(teaching_items) != 1:
        return None
    try:
        payload = json.loads(teaching_items[0].content)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    stimulus = payload.get("stimulus")
    handles = payload.get("allowed_source_handles")
    if not isinstance(stimulus, dict) or not isinstance(handles, list):
        return None
    if (
        stimulus.get("kind") != "teaching_control"
        or stimulus.get("control_key") != "continue"
    ):
        return None
    safe_payload = stimulus.get("safe_payload")
    if not isinstance(safe_payload, dict) or set(safe_payload) != {
        "reason_code",
        "source_handle",
        "result_summary",
    }:
        return None
    source_handle = safe_payload.get("source_handle")
    summary = safe_payload.get("result_summary")
    if (
        safe_payload.get("reason_code") != "result_evaluation"
        or not isinstance(source_handle, str)
        or not source_handle.startswith("artifact:")
        or source_handle not in handles
        or not isinstance(summary, str)
        or not summary.strip()
        or len(summary) > 320
    ):
        return None
    return (
        "**运行评价**\n\n"
        "Tutor 暂时无法生成个性化评价，以下为服务器保存的权威结果摘要：\n\n"
        f"{summary.strip()}"
    )


def _lease_unavailable_result(
    snapshot: TutorRunSnapshot,
    *,
    effect_results: list[TutorEffectResult] | tuple[TutorEffectResult, ...] = (),
) -> TutorRunResult:
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
        effect_results=tuple(effect_results),
    )


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


def _log_gate_denial(
    run: TutorRunSnapshot, decision: TutorDecision, code: str | None,
    context: TutorContextInput, gate: TutorDecisionGate,
) -> None:
    # Read only the concrete gate's frozen catalog, never call selection storage
    # or serialize gate/context objects. This avoids new persistence contracts.
    catalog: SkillCatalogSnapshot | None = None
    candidate: object = gate
    # Planning/teaching decorators wrap the catalog gate; bounded read-only
    # traversal preserves the exact snapshot rather than recompiling a newer one.
    for _ in range(4):
        frozen_catalog = getattr(candidate, "_catalog", None)
        if isinstance(frozen_catalog, SkillCatalogSnapshot):
            catalog = frozen_catalog
            break
        candidate = getattr(candidate, "_base", None)
    fields: dict[str, object] = {
        "stage": "decision_gate", "code": code or _POLICY_BLOCKED,
        "run_id": run.run_id, "conversation_id": run.conversation_id,
        "input_revision": run.input_revision, "model_call_count": run.model_call_count,
        "catalog_digest": catalog.digest if catalog else None,
    }
    for source in context.system_descriptors:
        if source.source_id.startswith("catalog:selected:"):
            fields["skill_reference"] = source.source_id.removeprefix("catalog:selected:")
            break
    actions: list[tuple[str, str, str, bool]] = []
    for index, request in enumerate(decision.capability_requests):
        actions.append(("capability", f"capability_requests[{index}].capability_id", request.capability_id,
                        catalog is not None and catalog.capability(request.capability_id) is not None))
    for index, proposal in enumerate(decision.effect_proposals):
        actions.append(("effect", f"effect_proposals[{index}].effect_type", proposal.effect_type,
                        catalog is not None and catalog.effect(proposal.effect_type) is not None))
    for index, reference in enumerate(decision.skill_references):
        actions.append(("skill", f"skill_references[{index}]", f"{reference.skill_id}@{reference.version}",
                        catalog is not None and catalog.resolve_skill(reference.skill_id, reference.version) is not None))
    if decision.teaching_step is not None:
        actions.append(("teaching_step", "teaching_step.action", decision.teaching_step.action, True))
    if not actions:
        actions.append(("decision", "decision", "no_capability_or_effect", True))
    # Each entry describes an action in the denied decision, not an inferred
    # offending payload value. Unknown identifiers are fingerprinted, never echoed.
    for category, path, identifier, trusted in actions:
        log_safe_event(
            logger, "tutor_decision_denied", level=logging.WARNING, exception=None, **fields, action_category=category,
            field_path=path, action_identifier=safe_diagnostic_identifier(identifier, trusted=trusted),
        )
