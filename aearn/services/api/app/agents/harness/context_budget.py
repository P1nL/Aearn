"""Provider-bounded adaptive context planning for Tutor TurnRuns."""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from math import ceil

from app.agents.harness.context_builder import TutorContextBuilder, Utf8ByteTokenEstimator
from app.agents.harness.contracts import (
    TokenEstimator,
    TutorCheckpointMetadata,
    TutorCompactionTrigger,
    TutorContextBudgetMode,
    TutorContextBudgetPlan,
    TutorContextBudgetPolicy,
    TutorContextError,
    TutorContextInput,
    TutorContextSelection,
    TutorExecutionProfile,
    TutorProviderContextCapability,
    TutorRunSnapshot,
    build_compaction_request,
)
from app.core.config import Settings, get_settings
from app.services.llm.completion_policy import (
    estimate_completion_request_tokens, resolve_completion_stage_policy,
)
from app.services.llm.contracts import LLMUsage
from app.services.llm.llm_client import build_json_request_payload
from app.services.tutor.decision_protocol import TUTOR_PROVIDER_ITEMS_SCHEMA_NAME, tutor_provider_output_schema

from app.agents.harness.provider_request import TutorProviderRequestSerializer


_MODE_ORDER = (
    TutorContextBudgetMode.COMPACT,
    TutorContextBudgetMode.NORMAL,
    TutorContextBudgetMode.COMPLEX,
    TutorContextBudgetMode.EXTENDED,
)


@dataclass(frozen=True)
class TutorContextBudgetSignals:
    current_input_characters: int
    current_input_lines: int
    code_fence_count: int
    candidate_source_count: int
    long_source_count: int
    recent_message_count: int
    working_summary_available: bool


@dataclass(frozen=True)
class TutorContextBudgetCalibration:
    estimated_input_tokens: int
    actual_input_tokens: int
    cached_input_tokens: int
    absolute_error_tokens: int
    within_safety_margin: bool




def resolve_tutor_provider_context_capability(
    settings: Settings,
) -> TutorProviderContextCapability:
    """Resolve only exact registry evidence or explicit conservative Settings."""

    capability_version = (
        "deepseek-flash-responses-v2"
        if settings.uses_deepseek_v4_flash_responses
        else "configured-conservative-provider-v1"
    )
    return TutorProviderContextCapability(
        context_window_tokens=settings.tutor_context_window_capacity_tokens,
        max_output_reserve_tokens=settings.tutor_context_output_reserve_tokens,
        protocol_reserve_tokens=settings.tutor_context_protocol_reserve_tokens,
        safety_margin_tokens=settings.tutor_context_safety_margin_tokens,
        maximum_dynamic_target_tokens=settings.tutor_context_max_dynamic_target_capacity_tokens,
        capability_version=capability_version,
    )


def build_tutor_context_budget_policy(
    settings: Settings, *, completion_stage: str | None = None,
) -> TutorContextBudgetPolicy:
    fixed_mode = (
        TutorContextBudgetMode(settings.tutor_context_fixed_mode)
        if settings.tutor_context_fixed_mode is not None
        else None
    )
    capability = resolve_tutor_provider_context_capability(settings)
    if completion_stage is not None:
        completion_capability = resolve_completion_stage_policy(settings, completion_stage).context_capability
        if completion_capability is None:
            raise ValueError("Sidecar has no ordinary HTTP context budget policy")
        capability = completion_capability
    return TutorContextBudgetPolicy(
        capability=capability,
        mode_targets=(
            (TutorContextBudgetMode.COMPACT, settings.tutor_context_compact_target_tokens),
            (TutorContextBudgetMode.NORMAL, settings.tutor_context_normal_target_tokens),
            (TutorContextBudgetMode.COMPLEX, settings.tutor_context_complex_target_tokens),
            (TutorContextBudgetMode.EXTENDED, settings.tutor_context_extended_target_tokens),
        ),
        warning_ratio=settings.tutor_context_warning_ratio,
        critical_ratio=settings.tutor_context_critical_ratio,
        max_expansions=settings.tutor_context_max_expansions,
        estimator_version="utf8_bytes_v1",
        policy_version="tutor_completion_context_budget_v1" if completion_stage is not None else "tutor_context_budget_v1",
        fixed_mode=fixed_mode,
    )


class TutorContextBudgetPlanner:
    """Classify, allocate, dry-build, and hard-bound one complete request."""

    def __init__(
        self,
        *,
        estimator: TokenEstimator | None = None,
        serializer: TutorProviderRequestSerializer | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._estimator = estimator or Utf8ByteTokenEstimator()
        self._serializer = serializer or TutorProviderRequestSerializer()
        self._settings = settings

    def build_context(
        self,
        *,
        run: TutorRunSnapshot,
        context_input: TutorContextInput,
        builder: TutorContextBuilder,
        expansion_count: int = 0,
    ) -> TutorContextSelection:
        policy = run.policy.context_budget_policy
        if policy is None:
            return builder.build(
                context_input,
                token_budget=run.policy.context_token_budget,
            )
        bounded_expansion_count = min(expansion_count, policy.max_expansions)
        capability = policy.capability
        required_selection = builder.build(
            context_input,
            token_budget=capability.input_hard_limit,
            optional_token_budget=0,
            preserve_required_content=run.policy.execution_profile is TutorExecutionProfile.COMPLETION_DRIVEN_V1,
        )
        mode = self._mode_for(
            policy=policy,
            signals=self.classify_signals(context_input),
            expansion_count=bounded_expansion_count,
        )
        warning_tokens = min(
            capability.input_hard_limit - 1,
            max(1, ceil(capability.input_hard_limit * policy.warning_ratio)),
        )
        critical_tokens = max(
            warning_tokens + 1,
            ceil(capability.input_hard_limit * policy.critical_ratio),
        )
        critical_tokens = min(critical_tokens, capability.input_hard_limit)
        preliminary_required_estimate = self._estimate_complete_request(
            run=run,
            context=required_selection,
            capability=capability,
        )
        if preliminary_required_estimate > capability.input_hard_limit:
            raise TutorContextError("TUTOR_CONTEXT_REQUIRED_OVERFLOW")
        preliminary_plan = TutorContextBudgetPlan(
            mode=mode,
            physical_input_limit=capability.input_hard_limit,
            required_token_estimate=preliminary_required_estimate,
            optional_token_budget=0,
            total_input_warning_tokens=warning_tokens,
            total_input_critical_tokens=critical_tokens,
            expansion_count=bounded_expansion_count,
            estimator_version=policy.estimator_version,
            capability_version=capability.capability_version,
            policy_version=policy.policy_version,
            estimated_total_input_tokens=preliminary_required_estimate,
        )
        required_selection, required_estimate = self._stabilize_estimate(
            run=run,
            context_input=context_input,
            selection=required_selection,
            plan=preliminary_plan,
            capability=capability,
        )
        if required_estimate > capability.input_hard_limit:
            raise TutorContextError("TUTOR_CONTEXT_REQUIRED_OVERFLOW")

        physical_optional_capacity = capability.input_hard_limit - required_estimate
        optional_budget = min(
            policy.target_for(mode),
            capability.maximum_dynamic_target_tokens,
            physical_optional_capacity,
        )
        dynamic_warning_tokens, dynamic_critical_tokens = self._dynamic_thresholds(
            required_token_estimate=required_estimate,
            optional_token_budget=optional_budget,
            physical_input_limit=capability.input_hard_limit,
            warning_ratio=policy.warning_ratio,
            critical_ratio=policy.critical_ratio,
        )
        plan = replace(
            preliminary_plan,
            required_token_estimate=required_estimate,
            optional_token_budget=optional_budget,
            total_input_warning_tokens=dynamic_warning_tokens,
            total_input_critical_tokens=dynamic_critical_tokens,
            estimated_total_input_tokens=required_estimate,
        )

        for _ in range(32):
            selection_budget = max(
                1,
                required_selection.checkpoint_metadata.consumed_tokens + optional_budget,
            )
            candidate = builder.build(
                context_input,
                token_budget=selection_budget,
                optional_token_budget=optional_budget,
                budget_plan=replace(plan, optional_token_budget=optional_budget),
                preserve_required_content=run.policy.execution_profile is TutorExecutionProfile.COMPLETION_DRIVEN_V1,
            )
            candidate, estimate = self._stabilize_estimate(
                run=run,
                context_input=context_input,
                selection=candidate,
                plan=replace(plan, optional_token_budget=optional_budget),
                capability=capability,
            )
            if estimate <= capability.input_hard_limit:
                return candidate
            reduced = optional_budget - max(1, estimate - capability.input_hard_limit)
            optional_budget = max(0, reduced)

        raise TutorContextError("TUTOR_CONTEXT_REQUEST_OVERFLOW")

    def classify_signals(self, context_input: TutorContextInput) -> TutorContextBudgetSignals:
        raw_current = context_input.current_input.content if context_input.current_input is not None else ""
        if isinstance(raw_current, dict):
            raw_current = raw_current.get("content", "")
        current = str(raw_current or "")
        source_values = [source.content for _, sources in context_input.section_sources() for source in sources]
        serialized_sources = [
            json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
            if not isinstance(value, str)
            else value
            for value in source_values
        ]
        return TutorContextBudgetSignals(
            current_input_characters=len(current),
            current_input_lines=max(1, current.count("\n") + 1),
            code_fence_count=current.count("```"),
            candidate_source_count=len(source_values),
            long_source_count=sum(len(value) >= 1200 for value in serialized_sources),
            recent_message_count=len(context_input.recent_messages),
            working_summary_available=bool(context_input.working_summary),
        )

    def classify_mode(self, signals: TutorContextBudgetSignals) -> TutorContextBudgetMode:
        if (
            signals.current_input_characters >= 12_000
            or signals.current_input_lines >= 200
            or signals.candidate_source_count >= 24
            or signals.long_source_count >= 8
        ):
            return TutorContextBudgetMode.EXTENDED
        if (
            signals.current_input_characters >= 4_000
            or signals.current_input_lines >= 80
            or signals.code_fence_count >= 4
            or signals.candidate_source_count >= 12
            or signals.long_source_count >= 3
            or (signals.recent_message_count >= 6 and not signals.working_summary_available)
        ):
            return TutorContextBudgetMode.COMPLEX
        if (
            signals.current_input_characters >= 400
            or signals.current_input_lines >= 8
            or signals.code_fence_count >= 2
            or signals.candidate_source_count >= 5
            or signals.recent_message_count >= 3
        ):
            return TutorContextBudgetMode.NORMAL
        return TutorContextBudgetMode.COMPACT

    def calibrate(
        self,
        *,
        metadata: TutorCheckpointMetadata,
        usage: LLMUsage,
        safety_margin_tokens: int,
    ) -> TutorContextBudgetCalibration:
        if metadata.estimated_total_input_tokens is None or usage.input_tokens is None:
            raise ValueError("estimated and actual input tokens are required for calibration")
        cached = usage.cached_input_tokens or 0
        error = abs(usage.input_tokens - metadata.estimated_total_input_tokens)
        return TutorContextBudgetCalibration(
            estimated_input_tokens=metadata.estimated_total_input_tokens,
            actual_input_tokens=usage.input_tokens,
            cached_input_tokens=cached,
            absolute_error_tokens=error,
            within_safety_margin=error <= safety_margin_tokens,
        )

    @staticmethod
    def _dynamic_thresholds(
        *,
        required_token_estimate: int,
        optional_token_budget: int,
        physical_input_limit: int,
        warning_ratio: float,
        critical_ratio: float,
    ) -> tuple[int, int]:
        if optional_token_budget <= 0:
            return physical_input_limit - 1, physical_input_limit
        warning_tokens = min(
            physical_input_limit - 1,
            required_token_estimate + max(1, ceil(optional_token_budget * warning_ratio)),
        )
        critical_tokens = min(
            physical_input_limit,
            max(
                warning_tokens + 1,
                required_token_estimate + max(2, ceil(optional_token_budget * critical_ratio)),
            ),
        )
        return warning_tokens, critical_tokens

    def _mode_for(
        self,
        *,
        policy: TutorContextBudgetPolicy,
        signals: TutorContextBudgetSignals,
        expansion_count: int,
    ) -> TutorContextBudgetMode:
        mode = policy.fixed_mode or self.classify_mode(signals)
        index = min(len(_MODE_ORDER) - 1, _MODE_ORDER.index(mode) + expansion_count)
        return _MODE_ORDER[index]

    def _estimate_complete_request(
        self,
        *,
        run: TutorRunSnapshot,
        context: TutorContextSelection,
        capability: TutorProviderContextCapability,
    ) -> int:
        messages = self._serializer.build_messages(run=run, context=context)
        request: object = messages
        if run.policy.execution_profile is TutorExecutionProfile.COMPLETION_DRIVEN_V1:
            settings = self._settings or get_settings()
            request = build_json_request_payload(
                settings, messages, max_tokens=capability.max_output_reserve_tokens,
                output_schema=tutor_provider_output_schema(), schema_name=TUTOR_PROVIDER_ITEMS_SCHEMA_NAME,
            )
        return estimate_completion_request_tokens(
            request, capability=capability, estimator=self._estimator,
        )

    def _stabilize_estimate(
        self,
        *,
        run: TutorRunSnapshot,
        context_input: TutorContextInput,
        selection: TutorContextSelection,
        plan: TutorContextBudgetPlan,
        capability: TutorProviderContextCapability,
    ) -> tuple[TutorContextSelection, int]:
        estimate = plan.required_token_estimate
        current = selection
        for _ in range(4):
            finalized_plan = replace(plan, estimated_total_input_tokens=estimate)
            metadata = replace(
                current.checkpoint_metadata,
                budget_mode=finalized_plan.mode,
                estimated_total_input_tokens=estimate,
                optional_token_budget=finalized_plan.optional_token_budget,
                warning_reached=estimate >= finalized_plan.total_input_warning_tokens,
                critical_reached=estimate >= finalized_plan.total_input_critical_tokens,
                expansion_count=finalized_plan.expansion_count,
                estimator_version=finalized_plan.estimator_version,
                capability_version=finalized_plan.capability_version,
                budget_policy_version=finalized_plan.policy_version,
            )
            request = None
            if metadata.warning_reached and (current.current_input is not None or current.items):
                request = build_compaction_request(
                    run_id=context_input.run_id,
                    conversation_id=context_input.conversation_id,
                    input_revision=context_input.input_revision,
                    trigger=TutorCompactionTrigger.CONTEXT_HIGH_WATER,
                    metadata=metadata,
                )
            current = replace(
                current,
                checkpoint_metadata=metadata,
                high_water_compaction_request=request,
            )
            updated = max(
                plan.required_token_estimate,
                self._estimate_complete_request(
                    run=run,
                    context=current,
                    capability=capability,
                ),
            )
            if updated == estimate or updated > plan.physical_input_limit:
                return current, updated
            estimate = updated
        metadata = replace(
            current.checkpoint_metadata,
            estimated_total_input_tokens=estimate,
            warning_reached=estimate >= plan.total_input_warning_tokens,
            critical_reached=estimate >= plan.total_input_critical_tokens,
        )
        request = None
        if metadata.warning_reached and (current.current_input is not None or current.items):
            request = build_compaction_request(
                run_id=context_input.run_id,
                conversation_id=context_input.conversation_id,
                input_revision=context_input.input_revision,
                trigger=TutorCompactionTrigger.CONTEXT_HIGH_WATER,
                metadata=metadata,
            )
        return replace(
            current,
            checkpoint_metadata=metadata,
            high_water_compaction_request=request,
        ), estimate
