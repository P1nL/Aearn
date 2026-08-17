"""Versioned, fake-only Tutor context governance evaluations and calibration."""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from math import ceil
from pathlib import Path
from statistics import fmean
from typing import Literal

from app.agents.harness.context_budget import TutorContextBudgetPlanner
from app.agents.harness.context_builder import TutorContextBuilder, Utf8ByteTokenEstimator
from app.agents.harness.contracts import (
    TUTOR_CONTEXT_SUMMARY_POLICY_VERSION,
    TUTOR_CONTEXT_SUMMARY_SCHEMA_VERSION,
    TutorContextBudgetMode,
    TutorContextBudgetPolicy,
    TutorContextCompactionCandidate,
    TutorContextCompactionPlan,
    TutorContextError,
    TutorContextInput,
    TutorContextSource,
    TutorPolicySnapshot,
    TutorProviderAttemptOutcome,
    TutorProviderAttemptReceipt,
    TutorProviderContextCapability,
    TutorRunSnapshot,
)
from app.core.config import Settings
from app.services.learning.planning_facts import (
    AuthoritativeContextSnapshot,
    PlanningFact,
    PlanningFactField,
    PlanningFactState,
    PlanningQuestionState,
    build_authoritative_context_snapshot,
    normalize_planning_fact,
    planning_fact_value_hash,
)
from app.services.llm.contracts import LLMUsage
from app.services.llm.llm_client import (
    LLMCallError,
    LLMJsonResponse,
    LLMVisibleOutputObserver,
)
from app.services.tutor.provider_gateway import PrimaryTutorProviderGateway, _build_messages


FIXTURE_SCHEMA_VERSION = "tutor_context_eval_v2"
RECEIPT_SCHEMA_VERSION = "tutor_context_eval_receipt_v1"
CALIBRATION_SCHEMA_VERSION = "tutor_context_calibration_v1"
_PERCENTILE_MIN_SAMPLES = 5
_ESTIMATION_ERROR_REVIEW_RATIO = 0.10


class TutorContextEvalFixtureError(ValueError):
    pass


@dataclass(frozen=True)
class TutorContextEvalCase:
    case_id: str
    scenario: str
    provider_capability: Mapping[str, object]
    budget_policy: Mapping[str, object]
    conversation: Mapping[str, object]
    provider_attempts: tuple[Mapping[str, object], ...]
    observability: Mapping[str, object]
    expected: Mapping[str, object]
    protected_markers: tuple[str, ...] = ()


@dataclass(frozen=True)
class TutorEvalAttemptMetrics:
    attempt_index: int
    outcome: str
    diagnostic_code: str | None
    actual_input_tokens: int | None
    cached_input_tokens: int | None
    uncached_input_tokens: int | None
    output_tokens: int | None
    reported_total_tokens: int | None
    calculated_total_tokens: int | None

    @classmethod
    def from_receipt(cls, receipt: TutorProviderAttemptReceipt) -> TutorEvalAttemptMetrics:
        usage = receipt.usage
        return cls(
            attempt_index=receipt.attempt_index,
            outcome=receipt.outcome.value,
            diagnostic_code=receipt.diagnostic_code,
            actual_input_tokens=usage.input_tokens if usage is not None else None,
            cached_input_tokens=usage.cached_input_tokens if usage is not None else None,
            uncached_input_tokens=usage.uncached_input_tokens if usage is not None else None,
            output_tokens=usage.output_tokens if usage is not None else None,
            reported_total_tokens=usage.total_tokens if usage is not None else None,
            calculated_total_tokens=usage.calculated_total_tokens if usage is not None else None,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "attempt_index": self.attempt_index,
            "outcome": self.outcome,
            "diagnostic_code": self.diagnostic_code,
            "actual_input_tokens": self.actual_input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "uncached_input_tokens": self.uncached_input_tokens,
            "output_tokens": self.output_tokens,
            "reported_total_tokens": self.reported_total_tokens,
            "calculated_total_tokens": self.calculated_total_tokens,
        }


@dataclass(frozen=True)
class TutorContextEvalReceipt:
    case_id: str
    provider: str
    protocol: str
    model: str
    capability_version: str
    estimator_version: str
    budget_config_version: str
    budget_mode: str | None = None
    physical_input_limit: int | None = None
    estimated_total_input_tokens: int | None = None
    estimated_dynamic_context_tokens: int | None = None
    actual_input_tokens: int | None = None
    cached_input_tokens: int | None = None
    uncached_input_tokens: int | None = None
    output_tokens: int | None = None
    reported_total_tokens: int | None = None
    calculated_total_tokens: int | None = None
    selected_count: int = 0
    skipped_count: int = 0
    truncated_count: int = 0
    budget_expansion_count: int = 0
    compaction_trigger: str | None = None
    summary_coverage_count: int = 0
    authoritative_snapshot_schema_version: str | None = None
    authoritative_snapshot_hash: str | None = None
    fact_revision: int = 0
    required_fact_count: int = 0
    required_fact_selected_count: int = 0
    required_fact_missing_count: int = 0
    confirmed_question_reasked_count: int = 0
    summary_blocked_by_unprojected_fact: int = 0
    provider_called: bool = False
    provider_call_count: int = 0
    provider_attempt_count: int = 0
    decision_count: int = 0
    current_input_present: bool = False
    current_input_occurrences: int = 0
    first_token_latency_ms: int | None = None
    selected_source_ids: tuple[str, ...] = ()
    excluded_source_ids: tuple[str, ...] = ()
    replay_stable: bool | None = None
    diagnostic_code: str | None = None
    attempts: tuple[TutorEvalAttemptMetrics, ...] = ()
    rubric: Mapping[str, bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "selected_count",
            "skipped_count",
            "truncated_count",
            "budget_expansion_count",
            "summary_coverage_count",
            "fact_revision",
            "required_fact_count",
            "required_fact_selected_count",
            "required_fact_missing_count",
            "confirmed_question_reasked_count",
            "summary_blocked_by_unprojected_fact",
            "provider_call_count",
            "provider_attempt_count",
            "decision_count",
            "current_input_occurrences",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.cached_input_tokens is not None and (
            self.actual_input_tokens is None
            or self.cached_input_tokens > self.actual_input_tokens
        ):
            raise ValueError("cached input metrics must be a subset of actual input")
        if self.actual_input_tokens is not None and self.uncached_input_tokens is not None:
            expected = self.actual_input_tokens - (self.cached_input_tokens or 0)
            if self.uncached_input_tokens != expected:
                raise ValueError("uncached input metrics are inconsistent")
        object.__setattr__(self, "selected_source_ids", tuple(self.selected_source_ids))
        object.__setattr__(self, "excluded_source_ids", tuple(self.excluded_source_ids))
        object.__setattr__(self, "attempts", tuple(self.attempts))
        object.__setattr__(self, "rubric", dict(self.rubric))

    def as_dict(self) -> dict[str, object]:
        return {
            "receipt_schema_version": RECEIPT_SCHEMA_VERSION,
            "fixture_schema_version": 2,
            "case_id": self.case_id,
            "provider": self.provider,
            "protocol": self.protocol,
            "model": self.model,
            "capability_version": self.capability_version,
            "estimator_version": self.estimator_version,
            "budget_config_version": self.budget_config_version,
            "budget_mode": self.budget_mode,
            "physical_input_limit": self.physical_input_limit,
            "estimated_total_input_tokens": self.estimated_total_input_tokens,
            "estimated_dynamic_context_tokens": self.estimated_dynamic_context_tokens,
            "actual_input_tokens": self.actual_input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "uncached_input_tokens": self.uncached_input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.reported_total_tokens,
            "reported_total_tokens": self.reported_total_tokens,
            "calculated_total_tokens": self.calculated_total_tokens,
            "selected_count": self.selected_count,
            "skipped_count": self.skipped_count,
            "truncated_count": self.truncated_count,
            "budget_expansion_count": self.budget_expansion_count,
            "compaction_trigger": self.compaction_trigger,
            "summary_coverage_count": self.summary_coverage_count,
            "authoritative_snapshot_schema_version": self.authoritative_snapshot_schema_version,
            "authoritative_snapshot_hash": self.authoritative_snapshot_hash,
            "fact_revision": self.fact_revision,
            "required_fact_count": self.required_fact_count,
            "required_fact_selected_count": self.required_fact_selected_count,
            "required_fact_missing_count": self.required_fact_missing_count,
            "confirmed_question_reasked_count": self.confirmed_question_reasked_count,
            "summary_blocked_by_unprojected_fact": self.summary_blocked_by_unprojected_fact,
            "provider_called": self.provider_called,
            "provider_call_count": self.provider_call_count,
            "provider_attempt_count": self.provider_attempt_count,
            "decision_count": self.decision_count,
            "current_input_present": self.current_input_present,
            "current_input_occurrences": self.current_input_occurrences,
            "first_token_latency_ms": self.first_token_latency_ms,
            "selected_source_ids": list(self.selected_source_ids),
            "excluded_source_ids": list(self.excluded_source_ids),
            "replay_stable": self.replay_stable,
            "diagnostic_code": self.diagnostic_code,
            "attempts": [attempt.as_dict() for attempt in self.attempts],
            "rubric": dict(self.rubric),
        }


@dataclass(frozen=True)
class TutorContextEvalResult:
    case_id: str
    passed: bool
    receipt: TutorContextEvalReceipt


@dataclass(frozen=True)
class TutorCalibrationGroup:
    provider: str
    protocol: str
    capability_version: str
    budget_mode: str
    estimator_version: str
    budget_config_version: str
    sample_count: int
    mean_estimated_input_tokens: float
    mean_actual_input_tokens: float
    mean_absolute_error_tokens: float
    mean_absolute_error_ratio: float
    mean_cache_ratio: float | None
    mean_output_tokens: float | None
    mean_first_token_latency_ms: float | None
    p50_actual_input_tokens: int | None
    p95_actual_input_tokens: int | None

    def as_dict(self) -> dict[str, object]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class TutorCalibrationReport:
    groups: tuple[TutorCalibrationGroup, ...]
    percentile_min_samples: int
    recommendation: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": CALIBRATION_SCHEMA_VERSION,
            "percentile_min_samples": self.percentile_min_samples,
            "recommendation": self.recommendation,
            "groups": [group.as_dict() for group in self.groups],
        }


def load_tutor_context_eval_cases(path: Path) -> tuple[TutorContextEvalCase, ...]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TutorContextEvalFixtureError("Tutor context eval fixture is not valid JSON") from exc
    if not isinstance(document, Mapping) or document.get("schema_version") != FIXTURE_SCHEMA_VERSION:
        raise TutorContextEvalFixtureError("Tutor context eval fixture schema version is unsupported")
    defaults = document.get("defaults") or {}
    raw_cases = document.get("cases")
    if not isinstance(defaults, Mapping) or not isinstance(raw_cases, list) or not raw_cases:
        raise TutorContextEvalFixtureError("Tutor context eval fixture shape is invalid")
    default_capability = _mapping(defaults.get("provider_capability"), "provider capability defaults")
    default_policy = _mapping(defaults.get("budget_policy"), "budget policy defaults")
    default_observability = _mapping(defaults.get("observability") or {}, "observability defaults")
    cases: list[TutorContextEvalCase] = []
    seen: set[str] = set()
    for raw in raw_cases:
        if not isinstance(raw, Mapping):
            raise TutorContextEvalFixtureError("Tutor context eval case is invalid")
        case_id = str(raw.get("case_id") or "")
        scenario = str(raw.get("scenario") or case_id)
        attempts = raw.get("provider_attempts") or []
        markers = raw.get("protected_markers") or []
        if (
            not case_id
            or case_id in seen
            or not scenario
            or not isinstance(attempts, list)
            or any(not isinstance(item, Mapping) for item in attempts)
            or not isinstance(markers, list)
            or any(not isinstance(marker, str) for marker in markers)
        ):
            raise TutorContextEvalFixtureError("Tutor context eval case identity is invalid")
        capability = _deep_merge(default_capability, _mapping(raw.get("provider_capability") or {}, "provider capability"))
        policy = _deep_merge(default_policy, _mapping(raw.get("budget_policy") or {}, "budget policy"))
        observability = _deep_merge(default_observability, _mapping(raw.get("observability") or {}, "observability"))
        _capability(capability)
        _policy(policy, capability)
        seen.add(case_id)
        cases.append(
            TutorContextEvalCase(
                case_id=case_id,
                scenario=scenario,
                provider_capability=capability,
                budget_policy=policy,
                conversation=_mapping(raw.get("conversation") or {}, "conversation"),
                provider_attempts=tuple(dict(item) for item in attempts),
                observability=observability,
                expected=_mapping(raw.get("expected") or {}, "expected"),
                protected_markers=tuple(markers),
            )
        )
    return tuple(cases)


def run_tutor_context_eval_case(case: TutorContextEvalCase) -> TutorContextEvalResult:
    if case.scenario == "required_input_unrepresentable_provider_not_called":
        receipt = _unrepresentable_receipt(case)
    elif case.scenario in {
        "usage_cached_tokens_not_double_counted",
        "repair_attempts_accounted_separately",
        "missing_usage_remains_unknown",
        "reported_and_calculated_total_remain_distinct",
    }:
        receipt = _usage_receipt(case)
    else:
        receipt = _selection_receipt(case)
    document = receipt.as_dict()
    serialized = json.dumps(document, ensure_ascii=False, sort_keys=True)
    if any(marker and marker in serialized for marker in case.protected_markers):
        raise TutorContextEvalFixtureError("Tutor context eval receipt contains protected evidence")
    return TutorContextEvalResult(
        case_id=case.case_id,
        passed=_subset_matches(document, case.expected),
        receipt=receipt,
    )


def run_tutor_context_eval_fixture(path: Path) -> tuple[TutorContextEvalResult, ...]:
    return tuple(run_tutor_context_eval_case(case) for case in load_tutor_context_eval_cases(path))


def build_tutor_context_calibration_report(
    receipts: Sequence[TutorContextEvalReceipt],
    *,
    percentile_min_samples: int = _PERCENTILE_MIN_SAMPLES,
) -> TutorCalibrationReport:
    if percentile_min_samples < 1:
        raise ValueError("percentile_min_samples must be positive")
    grouped: dict[tuple[str, str, str, str, str, str], list[TutorContextEvalReceipt]] = {}
    for receipt in receipts:
        if receipt.budget_mode is None or receipt.estimated_total_input_tokens is None or receipt.actual_input_tokens is None:
            continue
        key = (
            receipt.provider,
            receipt.protocol,
            receipt.capability_version,
            receipt.budget_mode,
            receipt.estimator_version,
            receipt.budget_config_version,
        )
        grouped.setdefault(key, []).append(receipt)
    groups: list[TutorCalibrationGroup] = []
    review_required = False
    for key, samples in sorted(grouped.items()):
        actual = [item.actual_input_tokens for item in samples if item.actual_input_tokens is not None]
        estimated = [item.estimated_total_input_tokens for item in samples if item.estimated_total_input_tokens is not None]
        errors = [abs(actual_value - estimated_value) for actual_value, estimated_value in zip(actual, estimated)]
        ratios = [error / max(actual_value, 1) for error, actual_value in zip(errors, actual)]
        cache_ratios = [
            item.cached_input_tokens / max(item.actual_input_tokens, 1)
            for item in samples
            if item.cached_input_tokens is not None and item.actual_input_tokens is not None
        ]
        outputs = [item.output_tokens for item in samples if item.output_tokens is not None]
        latencies = [item.first_token_latency_ms for item in samples if item.first_token_latency_ms is not None]
        review_required = review_required or any(ratio > _ESTIMATION_ERROR_REVIEW_RATIO for ratio in ratios)
        groups.append(
            TutorCalibrationGroup(
                provider=key[0],
                protocol=key[1],
                capability_version=key[2],
                budget_mode=key[3],
                estimator_version=key[4],
                budget_config_version=key[5],
                sample_count=len(samples),
                mean_estimated_input_tokens=fmean(estimated),
                mean_actual_input_tokens=fmean(actual),
                mean_absolute_error_tokens=fmean(errors),
                mean_absolute_error_ratio=fmean(ratios),
                mean_cache_ratio=fmean(cache_ratios) if cache_ratios else None,
                mean_output_tokens=fmean(outputs) if outputs else None,
                mean_first_token_latency_ms=fmean(latencies) if latencies else None,
                p50_actual_input_tokens=_percentile(actual, 0.50) if len(actual) >= percentile_min_samples else None,
                p95_actual_input_tokens=_percentile(actual, 0.95) if len(actual) >= percentile_min_samples else None,
            )
        )
    recommendation = "review_estimator_or_safety_margin" if review_required else "retain_versioned_config_pending_real_provider_evidence"
    return TutorCalibrationReport(tuple(groups), percentile_min_samples, recommendation)



def _selection_receipt(case: TutorContextEvalCase) -> TutorContextEvalReceipt:
    capability = _capability(case.provider_capability)
    policy = _policy(case.budget_policy, case.provider_capability)
    run = _run(case, policy)
    context_input = _context_input(case, run=run)
    planner = TutorContextBudgetPlanner(estimator=Utf8ByteTokenEstimator())
    builder = TutorContextBuilder(estimator=Utf8ByteTokenEstimator())
    expansion_count = _required_int(case.budget_policy.get("expansion_count"), default=0)
    try:
        selection = planner.build_context(
            run=run,
            context_input=context_input,
            builder=builder,
            expansion_count=expansion_count,
        )
    except TutorContextError as exc:
        return _base_receipt(
            case,
            capability=capability,
            policy=policy,
            provider_called=False,
            diagnostic_code=exc.safe_code,
            rubric=_rubric(provider_safely_not_called_when_required=True),
        )
    replay = planner.build_context(
        run=run,
        context_input=context_input,
        builder=builder,
        expansion_count=expansion_count,
    )
    raw_attempts: Sequence[Mapping[str, object]] = case.provider_attempts or ({"outcome": "accepted"},)
    client = _FixtureJsonClient(_fixture_responses(raw_attempts))
    provider_result = PrimaryTutorProviderGateway(
        settings=Settings(llm_type="disabled"),
        client=client,
    ).decide(run=run, context=selection)
    attempts = tuple(TutorEvalAttemptMetrics.from_receipt(item) for item in provider_result.attempts)
    aggregate = _aggregate(attempts)
    metadata = selection.checkpoint_metadata
    selected_ids = tuple(item.source_id for item in selection.items)
    optional_ids = tuple(
        source.source_id
        for _section, sources in context_input.section_sources()
        for source in sources
    )
    messages = _build_messages(run=run, context=selection)
    serialized_messages = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    current_content = selection.current_input.content if selection.current_input is not None else None
    compaction = metadata.compaction_input
    trigger = selection.high_water_compaction_request
    policy_text = messages[0]["content"]
    correction_policy = all(
        marker in policy_text
        for marker in (
            "current_input, then recent_messages, then working_summary",
            "must never overwrite a newer correction or completion",
            "stop the stale path",
            "answer directly first",
        )
    )
    base = _base_receipt(
        case,
        capability=capability,
        policy=policy,
        provider_called=client.calls > 0,
        provider_call_count=client.calls,
        provider_attempt_count=len(attempts),
        decision_count=1,
        diagnostic_code=provider_result.safe_code,
    )
    return replace(
        base,
        budget_mode=metadata.budget_mode.value if metadata.budget_mode is not None else None,
        physical_input_limit=capability.input_hard_limit,
        estimated_total_input_tokens=metadata.estimated_total_input_tokens,
        estimated_dynamic_context_tokens=metadata.optional_token_budget,
        actual_input_tokens=aggregate[0],
        cached_input_tokens=aggregate[1],
        uncached_input_tokens=aggregate[2],
        output_tokens=aggregate[3],
        reported_total_tokens=aggregate[4],
        calculated_total_tokens=aggregate[5],
        selected_count=len(selection.items),
        skipped_count=sum(section.skipped_count for section in metadata.sections),
        truncated_count=metadata.truncated_count,
        budget_expansion_count=metadata.expansion_count,
        compaction_trigger=trigger.trigger.value if trigger is not None else None,
        summary_coverage_count=len(compaction.retired_message_ids) if compaction is not None else 0,
        authoritative_snapshot_schema_version=metadata.authoritative_snapshot_schema_version,
        authoritative_snapshot_hash=metadata.authoritative_snapshot_hash,
        fact_revision=metadata.fact_revision,
        required_fact_count=metadata.required_fact_count,
        required_fact_selected_count=metadata.required_fact_selected_count,
        required_fact_missing_count=metadata.required_fact_missing_count,
        confirmed_question_reasked_count=metadata.confirmed_question_reasked_count,
        summary_blocked_by_unprojected_fact=metadata.summary_blocked_by_unprojected_fact,
        current_input_present=selection.current_input is not None,
        current_input_occurrences=serialized_messages.count(current_content) if current_content else 0,
        first_token_latency_ms=_optional_int(case.observability.get("first_token_latency_ms")),
        selected_source_ids=selected_ids,
        excluded_source_ids=tuple(source_id for source_id in optional_ids if source_id not in selected_ids),
        replay_stable=selection.checkpoint_metadata.as_dict() == replay.checkpoint_metadata.as_dict(),
        attempts=attempts,
        rubric=_rubric(
            answers_current_input=selection.current_input is not None and provider_result.decision is not None,
            correction_contract=correction_policy if case.scenario == "summary_does_not_override_correction" else True,
            selected_context_is_relevant=all(source_id in optional_ids for source_id in selected_ids),
        ),
    )


def _usage_receipt(case: TutorContextEvalCase) -> TutorContextEvalReceipt:
    capability = _capability(case.provider_capability)
    policy = _policy(case.budget_policy, case.provider_capability)
    run = _run(case, policy)
    selection = TutorContextBudgetPlanner(estimator=Utf8ByteTokenEstimator()).build_context(
        run=run,
        context_input=_context_input(case, run=run),
        builder=TutorContextBuilder(estimator=Utf8ByteTokenEstimator()),
    )
    client = _FixtureJsonClient(_fixture_responses(case.provider_attempts))
    result = PrimaryTutorProviderGateway(
        settings=Settings(llm_type="disabled"),
        client=client,
    ).decide(run=run, context=selection)
    attempts = tuple(TutorEvalAttemptMetrics.from_receipt(item) for item in result.attempts)
    aggregate = _aggregate(attempts)
    metadata = selection.checkpoint_metadata
    base = _base_receipt(
        case,
        capability=capability,
        policy=policy,
        provider_called=client.calls > 0,
        provider_call_count=client.calls,
        provider_attempt_count=len(attempts),
        decision_count=1,
        diagnostic_code=result.safe_code,
    )
    return replace(
        base,
        budget_mode=metadata.budget_mode.value if metadata.budget_mode is not None else None,
        physical_input_limit=capability.input_hard_limit,
        estimated_total_input_tokens=metadata.estimated_total_input_tokens,
        estimated_dynamic_context_tokens=metadata.optional_token_budget,
        actual_input_tokens=aggregate[0],
        cached_input_tokens=aggregate[1],
        uncached_input_tokens=aggregate[2],
        output_tokens=aggregate[3],
        reported_total_tokens=aggregate[4],
        calculated_total_tokens=aggregate[5],
        selected_count=len(selection.items),
        skipped_count=sum(section.skipped_count for section in metadata.sections),
        truncated_count=metadata.truncated_count,
        budget_expansion_count=metadata.expansion_count,
        authoritative_snapshot_schema_version=metadata.authoritative_snapshot_schema_version,
        authoritative_snapshot_hash=metadata.authoritative_snapshot_hash,
        fact_revision=metadata.fact_revision,
        required_fact_count=metadata.required_fact_count,
        required_fact_selected_count=metadata.required_fact_selected_count,
        required_fact_missing_count=metadata.required_fact_missing_count,
        confirmed_question_reasked_count=metadata.confirmed_question_reasked_count,
        summary_blocked_by_unprojected_fact=metadata.summary_blocked_by_unprojected_fact,
        current_input_present=selection.current_input is not None,
        current_input_occurrences=1 if selection.current_input is not None else 0,
        first_token_latency_ms=_optional_int(case.observability.get("first_token_latency_ms")),
        attempts=attempts,
        rubric=_rubric(answers_current_input=result.decision is not None),
    )


def _unrepresentable_receipt(case: TutorContextEvalCase) -> TutorContextEvalReceipt:
    capability = _capability(case.provider_capability)
    policy = _policy(case.budget_policy, case.provider_capability)

    class _TwoTokenEstimator:
        def estimate_tokens(self, value: object) -> int:
            del value
            return 2

    try:
        TutorContextBuilder(estimator=_TwoTokenEstimator()).build(
            TutorContextInput(
                run_id=f"eval:{case.case_id}",
                conversation_id=f"eval-conversation:{case.case_id}",
                input_revision=1,
                current_input_required=True,
                current_input=TutorContextSource("message-current", "x"),
            ),
            token_budget=1,
        )
    except TutorContextError as exc:
        return _base_receipt(
            case,
            capability=capability,
            policy=policy,
            provider_called=False,
            diagnostic_code=exc.safe_code,
            rubric=_rubric(provider_safely_not_called_when_required=True),
        )
    raise AssertionError("unrepresentable current input unexpectedly fit")


def _base_receipt(
    case: TutorContextEvalCase,
    *,
    capability: TutorProviderContextCapability,
    policy: TutorContextBudgetPolicy,
    provider_called: bool,
    provider_call_count: int = 0,
    provider_attempt_count: int = 0,
    decision_count: int = 0,
    diagnostic_code: str | None = None,
    rubric: Mapping[str, bool] | None = None,
) -> TutorContextEvalReceipt:
    return TutorContextEvalReceipt(
        case_id=case.case_id,
        provider=str(case.provider_capability.get("provider") or "fake-openai-compatible"),
        protocol=str(case.provider_capability.get("protocol") or "responses"),
        model=str(case.provider_capability.get("model") or "fixture-model"),
        capability_version=capability.capability_version,
        estimator_version=policy.estimator_version,
        budget_config_version=policy.policy_version,
        provider_called=provider_called,
        provider_call_count=provider_call_count,
        provider_attempt_count=provider_attempt_count,
        decision_count=decision_count,
        diagnostic_code=diagnostic_code,
        rubric=rubric or {},
    )


def _rubric(
    *,
    answers_current_input: bool = False,
    correction_contract: bool = True,
    selected_context_is_relevant: bool = True,
    provider_safely_not_called_when_required: bool = False,
) -> dict[str, bool]:
    return {
        "answers_current_input": answers_current_input,
        "acknowledges_user_correction": correction_contract,
        "avoids_repeating_completed_steps": correction_contract,
        "avoids_rejected_path": correction_contract,
        "answers_advice_before_procedure": correction_contract,
        "does_not_force_stale_teaching_path": correction_contract,
        "selected_context_is_relevant": selected_context_is_relevant,
        "provider_safely_not_called_when_required": provider_safely_not_called_when_required,
    }



def _capability(raw: Mapping[str, object]) -> TutorProviderContextCapability:
    try:
        return TutorProviderContextCapability(
            context_window_tokens=_required_int(raw.get("context_window_tokens")),
            max_output_reserve_tokens=_required_int(raw.get("max_output_reserve_tokens")),
            protocol_reserve_tokens=_required_int(raw.get("protocol_reserve_tokens")),
            safety_margin_tokens=_required_int(raw.get("safety_margin_tokens")),
            maximum_dynamic_target_tokens=_required_int(raw.get("maximum_dynamic_target_tokens")),
            capability_version=str(raw["capability_version"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise TutorContextEvalFixtureError("Tutor context eval provider capability is invalid") from exc


def _policy(raw: Mapping[str, object], capability_raw: Mapping[str, object]) -> TutorContextBudgetPolicy:
    targets = raw.get("mode_targets")
    if not isinstance(targets, Mapping):
        raise TutorContextEvalFixtureError("Tutor context eval mode targets are invalid")
    fixed_mode_value = raw.get("fixed_mode")
    try:
        return TutorContextBudgetPolicy(
            capability=_capability(capability_raw),
            mode_targets=tuple(
                (mode, _required_int(targets.get(mode.value)))
                for mode in TutorContextBudgetMode
            ),
            warning_ratio=_required_float(raw.get("warning_ratio"), default=0.8),
            critical_ratio=_required_float(raw.get("critical_ratio"), default=0.95),
            max_expansions=_required_int(raw.get("max_expansions"), default=1),
            estimator_version=str(raw.get("estimator_version") or "utf8_bytes_v1"),
            policy_version=str(raw.get("policy_version") or "tutor_context_budget_eval_v1"),
            fixed_mode=TutorContextBudgetMode(str(fixed_mode_value)) if fixed_mode_value else None,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise TutorContextEvalFixtureError("Tutor context eval budget policy is invalid") from exc


def _run(case: TutorContextEvalCase, policy: TutorContextBudgetPolicy) -> TutorRunSnapshot:
    origin = _origin(case.conversation.get("origin"))
    return TutorRunSnapshot(
        run_id=f"eval:{case.case_id}",
        conversation_id=f"eval-conversation:{case.case_id}",
        user_id="eval-context-user",
        origin=origin,
        input_revision=1,
        policy=TutorPolicySnapshot(
            deadline=datetime(2030, 1, 1, tzinfo=UTC),
            max_iterations=3,
            max_model_calls=3,
            max_capability_calls=0,
            max_effects=0,
            context_token_budget=policy.capability.maximum_dynamic_target_tokens,
            context_budget_policy=policy,
        ),
    )


def _context_input(
    case: TutorContextEvalCase,
    *,
    run: TutorRunSnapshot,
) -> TutorContextInput:
    current_raw = case.conversation.get("current_input")
    current = _source(current_raw) if isinstance(current_raw, Mapping) else None
    origin = _origin(case.conversation.get("origin"))
    recent = _sources(case.conversation.get("recent_messages"), timeline_sort=True)
    summary_raw = case.conversation.get("working_summary")
    working_summary: tuple[TutorContextSource, ...] = ()
    if isinstance(summary_raw, Mapping) and bool(summary_raw.get("eligible", True)):
        working_summary = (_source(summary_raw),)
    compaction_raw = case.conversation.get("compaction_candidates")
    compaction_plan = None
    if isinstance(compaction_raw, list) and compaction_raw:
        candidates: list[TutorContextCompactionCandidate] = []
        for raw in compaction_raw:
            if not isinstance(raw, Mapping):
                raise TutorContextEvalFixtureError("Tutor context eval compaction candidate is invalid")
            candidates.append(
                TutorContextCompactionCandidate(
                    message_id=str(raw["message_id"]),
                    content_hash=str(raw["content_hash"]),
                    created_at=_timestamp(raw["created_at"]),
                )
            )
        protected_raw = case.conversation.get("protected_message_ids", [])
        if not isinstance(protected_raw, list) or any(
            not isinstance(value, str) for value in protected_raw
        ):
            raise TutorContextEvalFixtureError(
                "Tutor context eval protected message identities are invalid"
            )
        compaction_plan = TutorContextCompactionPlan(
            summary_schema_version=TUTOR_CONTEXT_SUMMARY_SCHEMA_VERSION,
            summary_policy_version=TUTOR_CONTEXT_SUMMARY_POLICY_VERSION,
            candidates=tuple(candidates),
            prior_summary_id=str(case.conversation["prior_summary_id"]) if case.conversation.get("prior_summary_id") is not None else None,
            prior_summary_hash=str(case.conversation["prior_summary_hash"]) if case.conversation.get("prior_summary_hash") is not None else None,
            protected_message_ids=tuple(protected_raw),
        )
    authoritative = _eval_authoritative_snapshot(case, run=run)
    return TutorContextInput(
        run_id=run.run_id,
        conversation_id=run.conversation_id,
        input_revision=1,
        current_input_required=origin == "interactive",
        current_input=current,
        system_descriptors=_sources(case.conversation.get("system_descriptors")),
        required_facts=authoritative.required_facts,
        active_plan=_sources(case.conversation.get("active_plan")),
        review_snapshot=_sources(case.conversation.get("review_snapshot")),
        recent_messages=recent,
        working_summary=working_summary,
        learner_memory=_sources(case.conversation.get("learner_memory")),
        activity_facts=_sources(case.conversation.get("activity")),
        capability_schemas=_sources(case.conversation.get("capability_schemas")),
        compaction_plan=compaction_plan,
        authoritative_snapshot_schema_version=authoritative.schema_version,
        authoritative_snapshot_hash=authoritative.snapshot_hash,
        fact_revision=authoritative.fact_revision,
        confirmed_question_reasked_count=authoritative.confirmed_question_reasked_count,
        summary_blocked_by_unprojected_fact=_required_int(
            case.conversation.get("summary_blocked_by_unprojected_fact"), default=0
        ),
    )


def _eval_authoritative_snapshot(
    case: TutorContextEvalCase,
    *,
    run: TutorRunSnapshot,
) -> AuthoritativeContextSnapshot:
    raw_facts = case.conversation.get("planning_facts")
    if raw_facts is None:
        facts: tuple[PlanningFact, ...] = ()
    else:
        if not isinstance(raw_facts, list) or any(not isinstance(item, Mapping) for item in raw_facts):
            raise TutorContextEvalFixtureError("Tutor context eval planning facts are invalid")
        normalized_facts: list[PlanningFact] = []
        for index, raw in enumerate(raw_facts, start=1):
            field = PlanningFactField(str(raw.get("field_key") or ""))
            value = normalize_planning_fact(field, raw.get("value"))
            revision = _required_int(raw.get("revision"), default=1)
            normalized_facts.append(
                PlanningFact(
                    fact_id=str(raw.get("fact_id") or f"eval-fact-{index}"),
                    session_id=f"eval-planning:{case.case_id}",
                    field_key=field,
                    value=value,
                    value_hash=planning_fact_value_hash(field, value),
                    revision=revision,
                    state=PlanningFactState.CONFIRMED,
                    source_message_id=str(raw.get("source_message_id") or f"eval-message-{index}"),
                    source_run_id=run.run_id,
                    source_input_revision=_required_int(raw.get("source_input_revision"), default=1),
                    supersedes_fact_id=(
                        str(raw["supersedes_fact_id"])
                        if raw.get("supersedes_fact_id") is not None
                        else None
                    ),
                )
            )
        facts = tuple(normalized_facts)
    raw_questions = case.conversation.get("planning_question_states")
    if raw_questions is None:
        question_states = {
            fact.field_key: PlanningQuestionState.CONFIRMED for fact in facts
        }
    elif isinstance(raw_questions, Mapping):
        question_states = {
            PlanningFactField(str(field)): PlanningQuestionState(str(state))
            for field, state in raw_questions.items()
        }
    else:
        raise TutorContextEvalFixtureError("Tutor context eval planning question states are invalid")
    return build_authoritative_context_snapshot(
        run=run,
        input_revision=1,
        planning_session_id=f"eval-planning:{case.case_id}" if facts else None,
        facts=facts,
        question_states=question_states,
        confirmed_question_reasked_count=_required_int(
            case.conversation.get("confirmed_question_reasked_count"),
            default=0,
        ),
    )


def _sources(raw: object, *, timeline_sort: bool = False) -> tuple[TutorContextSource, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or any(not isinstance(item, Mapping) for item in raw):
        raise TutorContextEvalFixtureError("Tutor context eval sources are invalid")
    items = list(raw)
    if timeline_sort and items and all(item.get("created_at") is not None for item in items):
        items.sort(
            key=lambda item: (
                _timestamp(item["created_at"]),
                str(item.get("message_id") or item.get("source_id") or ""),
            )
        )
    return tuple(_source(item) for item in items)


def _source(raw: Mapping[str, object]) -> TutorContextSource:
    source_id = raw.get("source_id") or raw.get("message_id")
    if source_id is None or "content" not in raw:
        raise TutorContextEvalFixtureError("Tutor context eval source is incomplete")
    return TutorContextSource(
        str(source_id),
        raw["content"],
        semantic_class=_semantic_class(raw.get("semantic_class")),
    )


def _semantic_class(
    value: object,
) -> Literal["ordinary", "confirmed_fact_source", "correction", "unresolved_question"]:
    normalized = str(value or "ordinary")
    if normalized == "ordinary":
        return "ordinary"
    if normalized == "confirmed_fact_source":
        return "confirmed_fact_source"
    if normalized == "correction":
        return "correction"
    if normalized == "unresolved_question":
        return "unresolved_question"
    raise TutorContextEvalFixtureError("Tutor context eval semantic class is invalid")


def _timestamp(raw: object) -> datetime:
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError as exc:
        raise TutorContextEvalFixtureError("Tutor context eval timestamp is invalid") from exc
    if value.tzinfo is None:
        raise TutorContextEvalFixtureError("Tutor context eval timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _fixture_responses(raw_attempts: Sequence[Mapping[str, object]]) -> tuple[LLMJsonResponse, ...]:
    responses: list[LLMJsonResponse] = []
    for raw in raw_attempts:
        outcome = str(raw.get("outcome") or "accepted")
        usage_raw = raw.get("usage")
        usage = None
        if isinstance(usage_raw, Mapping):
            usage = LLMUsage(
                input_tokens=_optional_int(usage_raw.get("input_tokens")),
                cached_input_tokens=_optional_int(usage_raw.get("cached_input_tokens")),
                output_tokens=_optional_int(usage_raw.get("output_tokens")),
                total_tokens=_optional_int(usage_raw.get("total_tokens")),
                reasoning_tokens=_optional_int(usage_raw.get("reasoning_tokens")),
            )
        content: dict[str, object] = (
            {"public_message": "fixture", "checkpoint_reason": "invalid"}
            if outcome == TutorProviderAttemptOutcome.REPAIRABLE_REJECTED.value
            else {
                "schema_version": "tutor_provider_items_v4",
                "message": {
                    "type": "agent_message",
                    "text": "fixture learner-safe reply",
                    "public_thinking_text": "当前目标可以收敛为一个可验证的小步骤。",
                    "conversation_title": None,
                },
                "action": {"type": "turn_completed"},
            }
        )
        responses.append(LLMJsonResponse(content=content, model="fixture-model", usage=usage))
    return tuple(responses)


class _FixtureJsonClient:
    def __init__(self, responses: Sequence[LLMJsonResponse]) -> None:
        self._responses = list(responses)
        self.calls = 0

    @property
    def model(self) -> str:
        return "fixture-model"

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
        output_schema: Mapping[str, object] | None = None,
        schema_name: str | None = None,
        thinking_mode: Literal["enabled", "disabled"] | None = None,
        capture_provider_body: bool = False,
        visible_output_observer: LLMVisibleOutputObserver | None = None,
    ) -> LLMJsonResponse:
        del (
            messages,
            temperature,
            max_tokens,
            timeout_seconds,
            output_schema,
            schema_name,
            thinking_mode,
            capture_provider_body,
            visible_output_observer,
        )
        self.calls += 1
        if not self._responses:
            raise LLMCallError("fixture response sequence exhausted")
        return self._responses.pop(0)


def _aggregate(attempts: Sequence[TutorEvalAttemptMetrics]) -> tuple[int | None, int | None, int | None, int | None, int | None, int | None]:
    return (
        _sum_known(item.actual_input_tokens for item in attempts),
        _sum_known(item.cached_input_tokens for item in attempts),
        _sum_known(item.uncached_input_tokens for item in attempts),
        _sum_known(item.output_tokens for item in attempts),
        _sum_known(item.reported_total_tokens for item in attempts),
        _sum_known(item.calculated_total_tokens for item in attempts),
    )


def _sum_known(values: Iterable[int | None]) -> int | None:
    normalized = list(values)
    if not normalized or any(value is None for value in normalized):
        return None
    return sum(value for value in normalized if value is not None)



def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _required_int(value: object, *, default: int | None = None) -> int:
    if value is None and default is not None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise TutorContextEvalFixtureError("Tutor context eval integer is invalid")
    return value


def _required_float(value: object, *, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TutorContextEvalFixtureError("Tutor context eval ratio is invalid")
    return float(value)


def _origin(value: object) -> Literal["interactive", "proactive"]:
    normalized = str(value or "interactive")
    if normalized not in {"interactive", "proactive"}:
        raise TutorContextEvalFixtureError("Tutor context eval origin is invalid")
    return "interactive" if normalized == "interactive" else "proactive"

def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TutorContextEvalFixtureError("Tutor context eval numeric metric is invalid")
    return value


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TutorContextEvalFixtureError(f"Tutor context eval {label} is invalid")
    return dict(value)


def _deep_merge(base: Mapping[str, object], override: Mapping[str, object]) -> dict[str, object]:
    result = dict(base)
    for key, value in override.items():
        existing = result.get(str(key))
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            result[str(key)] = _deep_merge(existing, value)
        else:
            result[str(key)] = value
    return result


def _subset_matches(observed: object, expected: object) -> bool:
    if isinstance(expected, Mapping):
        return isinstance(observed, Mapping) and all(
            key in observed and _subset_matches(observed[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(observed, list) and len(observed) == len(expected) and all(
            _subset_matches(actual, wanted)
            for actual, wanted in zip(observed, expected)
        )
    return observed == expected


def _percentile(values: Sequence[int], ratio: float) -> int:
    if not values or not 0 < ratio <= 1:
        raise ValueError("percentile inputs are invalid")
    ordered = sorted(values)
    return ordered[max(0, ceil(len(ordered) * ratio) - 1)]
