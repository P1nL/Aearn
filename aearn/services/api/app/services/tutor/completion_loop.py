"""Completion-profile branch of TutorRunLoop, sharing its original gates/owners."""
from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING, cast

from pydantic import TypeAdapter

from app.agents.harness.contracts import (
    TutorContextInput, TutorContextSelection, TutorContextSection, TutorDecisionGateStatus,
    TutorEffectResult, TutorLease, TutorProviderResult, TutorRunResult, TutorRunSnapshot,
    TutorRunStatus, TutorTerminalOutcome, empty_checkpoint_metadata,
)
from app.services.llm.http_execution import LLMHTTPExecution, use_http_execution
from app.services.llm.completion_policy import COMPLETION_MAX_HTTP_SECONDS
from app.services.tutor.completion_execution import (
    COMPLETION_RESULT_RESERVE_SECONDS, CompletionExecutionError, CompletionExecutionOwner,
    CompletionTutorProviderResult, StepAttempt, private_json,
)

if TYPE_CHECKING:
    from app.services.tutor.run_loop import TutorRunLoop

_CONTEXT = TypeAdapter(TutorContextSelection)


def _dependencies(run: TutorRunSnapshot, context: TutorContextSelection) -> dict[str, object]:
    # Server-generated action receipts/Skill selection are expected to change
    # after lawful consumption. They are reloaded and revalidated, not inherited.
    # Learner input, teaching authority and required evidence remain exact DATA.
    return {
        "run_id": run.run_id, "user_id": run.user_id, "conversation_id": run.conversation_id,
        "input_revision": run.input_revision,
        "current_input": _CONTEXT.dump_python(context, mode="json")["current_input"],
        "evidence": [{"section": item.section.value, "source_id": item.source_id, "content": item.content}
                     for item in context.items if item.section in (
                         TutorContextSection.TEACHING_SESSION, TutorContextSection.REQUIRED_FACTS)],
    }


def run_completion(loop: TutorRunLoop, *, run: TutorRunSnapshot, lease: TutorLease,
                   owner: CompletionExecutionOwner, stage_seconds: float) -> TutorRunResult:
    """Only NEW profile runs enter. No counter reset or policy/deadline rewrite."""
    effects: list[TutorEffectResult] = []
    metadata = empty_checkpoint_metadata(token_budget=run.policy.context_token_budget)
    expansion = 0
    step: StepAttempt | None = None

    def renew() -> None:
        nonlocal run, lease
        renewed = loop._heartbeat(lease, run)
        if renewed is None:
            raise CompletionExecutionError("completion_lease_lost")
        lease = renewed
        run = replace(run, lease=lease)
        owner.assert_current(run=run, lease=lease)

    def load() -> tuple[TutorContextInput, TutorContextSelection]:
        inputs = loop._context_loader.load_context(run, input_revision=run.input_revision)
        context = loop._context_budget_planner.build_context(
            run=run, context_input=inputs, builder=loop._context_builder, expansion_count=expansion,
        )
        return inputs, context

    def stop(code: str, outcome: TutorTerminalOutcome = TutorTerminalOutcome.BLOCKED_POLICY) -> TutorRunResult:
        return loop._terminal(run, outcome=outcome, diagnostic_code=code, metadata=metadata, effect_results=effects)

    def persist_attempts(recorded: StepAttempt) -> None:
        # DATA may have committed just before a crash/receipt-COMMIT ambiguity.
        # The original append-only receipt owner checks the exact tuple on replay.
        saved = recorded.result
        if isinstance(saved, TutorProviderResult) and saved.attempts and loop._lifecycle is not None:
            loop._lifecycle.persist_provider_attempts(
                snapshot=run, decision_iteration=recorded.decision_iteration,
                attempts=saved.attempts, created_at=loop._clock.now(),
            )

    try:
        while True:
            renew()
            step = owner.pending_step(run=run, lease=lease)
            if step is not None:
                persist_attempts(step)
            if step is not None and step.state in ("dispatched", "outcome_unknown"):
                return stop("completion_outcome_unknown")
            inputs, context = load()
            metadata = context.checkpoint_metadata
            dependencies = _dependencies(run, context)
            # Canonical JSON checks include full current input/evidence, not just
            # object IDs or a provider's claim that its answer is still valid.
            dependencies = json.loads(private_json(dependencies))
            if step is not None and step.dependencies != dependencies:
                if step.state == "result_recorded":
                    owner.reject_result(run=run, lease=lease, step=step, diagnostic_code="completion_dependencies_changed")
                return stop("completion_dependencies_changed")
            if step is not None and step.state == "prepared":
                owner.mark_not_sent(run=run, lease=lease, step=step)
            batch = owner.ensure_batch(run=run, lease=lease, now=loop._clock.now(),
                                       minimum_seconds=0 if step is not None and step.state == 'result_recorded' else stage_seconds,
                                       minimum_http_attempts=0 if step is not None and step.state == 'result_recorded' else 6)
            if step is None or step.state == "prepared":
                request = step.request if step is not None else {
                    "context": _CONTEXT.dump_python(context, mode="json"),
                    "progress_identity": {"input": dependencies['current_input'], "items": context.as_prompt_context()},
                }
                step = owner.prepare_step(
                    run=run, lease=lease, batch=batch,
                    step_key=step.step_key if step is not None else f"decision-{run.model_call_count + 1}",
                    kind="provider_decision", request=request, dependencies=dependencies,
                )
                # Reclaimed prepared work sends its exact original request.
                context = _CONTEXT.validate_json(private_json(step.request["context"]))
                step = owner.mark_dispatched(run=run, lease=lease, step=step)

                def before_send() -> float:
                    renew()
                    remaining = (batch.expires_at - loop._clock.now()).total_seconds() - COMPLETION_RESULT_RESERVE_SECONDS
                    if remaining <= 0:
                        raise CompletionExecutionError("completion_batch_expired")
                    return min(stage_seconds, remaining)

                def on_attempt(_number: int) -> None:
                    owner.record_http_attempt(run=run, lease=lease, step=cast(StepAttempt, step), batch=batch)

                execution = LLMHTTPExecution(before_send, renew, on_attempt, max_attempts=16,
                                             execution_profile=run.policy.execution_profile)
                with use_http_execution(execution):
                    provider_result = loop._provider.decide(run=run, context=context)
                unknown = bool(provider_result.safe_code and "_http_unknown_" in provider_result.safe_code) or (
                    isinstance(provider_result, CompletionTutorProviderResult)
                    and any(item.outcome_unknown for item in provider_result.nested_http_outcomes)
                )
                step = owner.record_result(run=run, lease=lease, step=step, result=provider_result, outcome_unknown=unknown)
                run = replace(run, model_call_count=max(run.model_call_count, step.decision_iteration),
                              iteration_count=max(run.iteration_count, step.decision_iteration))
                persist_attempts(step)
                if unknown:
                    return stop("completion_outcome_unknown")
            assert step is not None
            result = step.result
            if not isinstance(result, TutorProviderResult):
                raise CompletionExecutionError("completion_result_type_invalid")
            run = replace(run, status=TutorRunStatus.RUNNING,
                          iteration_count=max(run.iteration_count, step.decision_iteration),
                          model_call_count=max(run.model_call_count, step.decision_iteration),
                          capability_call_count=max(run.capability_call_count, step.capability_count_before),
                          effect_count=max(run.effect_count, step.effect_count_before))
            renew()
            inputs, current = load()
            if json.loads(private_json(_dependencies(run, current))) != dependencies:
                owner.reject_result(run=run, lease=lease, step=step, diagnostic_code="completion_dependencies_changed")
                return stop("completion_dependencies_changed")
            if result.terminal_outcome is not None:
                owner.reject_result(run=run, lease=lease, step=step, diagnostic_code="completion_provider_rejected")
                return stop(result.safe_code or "completion_provider_rejected", result.terminal_outcome)
            decision = result.decision
            if decision is None:
                raise CompletionExecutionError("completion_decision_missing")
            gate = loop._decision_gate.validate(run=run, decision=decision, context=current)
            if gate.status is TutorDecisionGateStatus.DENIED:
                owner.reject_result(run=run, lease=lease, step=step, diagnostic_code=gate.diagnostic_code or "completion_gate_denied")
                return stop(gate.diagnostic_code or "completion_gate_denied")

            def validate() -> None:
                _, fresh = load()
                if json.loads(private_json(_dependencies(run, fresh))) != dependencies:
                    raise CompletionExecutionError("completion_dependencies_changed")
                checked = loop._decision_gate.validate(run=run, decision=decision, context=fresh)
                if checked.status is TutorDecisionGateStatus.DENIED:
                    raise CompletionExecutionError(checked.diagnostic_code or "completion_gate_denied")

            if gate.status is TutorDecisionGateStatus.REBUILD_CONTEXT or (
                decision.skill_references and not decision.capability_requests
                and not decision.effect_proposals and decision.terminal_outcome is None
                and decision.continuation_kind is None
            ):
                owner.accept_result(run=run, lease=lease, step=step, batch=batch,
                                    dependencies=dependencies, validate=validate, consume=lambda: None)
                maximum = run.policy.context_budget_policy.max_expansions if run.policy.context_budget_policy else 0
                expansion = min(expansion + 1, maximum)
                continue

            # Existing stable action IDs/receipts remain the only capability and
            # effect execution authority, including after a crash AFTER commit.
            # HTTP nested inside those owners is still charged to this batch.
            batch = owner.ensure_batch(run=run, lease=lease, minimum_seconds=COMPLETION_MAX_HTTP_SECONDS, minimum_http_attempts=6)

            def action_send() -> float:
                nonlocal batch
                renew()
                batch = owner.ensure_batch(run=run, lease=lease, minimum_seconds=COMPLETION_MAX_HTTP_SECONDS, minimum_http_attempts=1)
                return min(COMPLETION_MAX_HTTP_SECONDS, (batch.expires_at-loop._clock.now()).total_seconds()-COMPLETION_RESULT_RESERVE_SECONDS)

            def action_attempt(_number: int) -> None:
                owner.record_http_attempt(run=run, lease=lease, step=cast(StepAttempt, step), batch=batch)

            execution = LLMHTTPExecution(action_send, renew, action_attempt, max_attempts=16,
                                         execution_profile=run.policy.execution_profile)
            with use_http_execution(execution):
                run, rebuild, terminal = loop._dispatch_capabilities(
                    run, lease=lease, decision=decision, metadata=metadata, effect_results=effects,
                    completion_step=step, validate_action=validate,
                )
            lease = run.lease or lease
            if terminal is not None:
                return terminal
            if not rebuild:
                run, rebuild, terminal = loop._commit_effects(
                    run, lease=lease, decision=decision, metadata=metadata, effect_results=effects,
                    completion_step=step, validate_action=validate,
                )
                lease = run.lease or lease
                if terminal is not None:
                    return terminal
            renew()
            batch = owner.ensure_batch(run=run, lease=lease, minimum_seconds=0, minimum_http_attempts=0)
            if rebuild:
                owner.accept_result(run=run, lease=lease, step=step, batch=batch,
                                    dependencies=dependencies, validate=validate, consume=lambda: None)
                continue

            def consume() -> TutorRunResult:
                if decision.continuation_kind is not None:
                    if run.interaction_protocol_version == "thread_turn_v2":
                        value = loop._interaction_request(run, decision=decision, effect_results=effects)
                        valid = value.status is TutorRunStatus.COMPLETED and value.terminal_outcome is TutorTerminalOutcome.COMPLETED
                    else:
                        value = loop._waiting_for_input(run, decision=decision, effect_results=effects)
                        valid = (value.status is TutorRunStatus.WAITING_FOR_INPUT
                                 and value.continuation_kind is decision.continuation_kind)
                else:
                    value = loop._terminal(
                        run, outcome=decision.terminal_outcome or TutorTerminalOutcome.COMPLETED,
                        diagnostic_code=None, metadata=metadata, effect_results=effects,
                        public_message=decision.public_message, public_thinking_text=decision.public_thinking_text,
                        public_thinking_steps=decision.public_thinking_steps, conversation_title=decision.conversation_title,
                        teaching_step=decision.teaching_step,
                    )
                    valid = value.terminal_outcome == (decision.terminal_outcome or TutorTerminalOutcome.COMPLETED)
                if not valid or value.run_id != run.run_id or value.input_revision != run.input_revision:
                    raise CompletionExecutionError("completion_consumption_rejected")
                return value

            return owner.accept_result(run=run, lease=lease, step=step, batch=batch,
                                       dependencies=dependencies, validate=validate, consume=consume)
    except Exception as exc:
        # A failed/ambiguous durable boundary is not permission to re-send. Leave
        # its persisted state intact for exact recovery under the next owner.
        # Action owners may already have COMMITTED while the caller did not get
        # their return value. Read counters only; never infer/replay that action.
        try:
            observed = loop._store.load_snapshot(run.run_id)
            if observed is not None and observed.input_revision == run.input_revision:
                run = replace(run, **{name: max(getattr(run, name), getattr(observed, name)) for name in (
                    'iteration_count', 'model_call_count', 'capability_call_count', 'effect_count')})
        except Exception:
            pass  # A broken connection cannot establish a different durable state.
        return TutorRunResult(
            run_id=run.run_id, status=TutorRunStatus.BLOCKED_POLICY, input_revision=run.input_revision,
            iteration_count=run.iteration_count, model_call_count=run.model_call_count,
            capability_call_count=run.capability_call_count, effect_count=run.effect_count,
            terminal_outcome=TutorTerminalOutcome.BLOCKED_POLICY,
            diagnostic_code=exc.safe_code if isinstance(exc, CompletionExecutionError) else 'completion_boundary_unconfirmed',
        )
