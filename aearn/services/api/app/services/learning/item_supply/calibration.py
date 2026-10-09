"""Pure offline P3 controller; synthetic samples never prove provider quality.

Trusted callers resolve explicit configs, *complete* terminal populations and
scorer/safety facts. A manifest binds those facts but does not authenticate them.
No config/env, repository, provider, worker or publication is imported here.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from math import ceil
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.contracts import Digest, Identifier
from app.services.learning.item_supply.parameter_profiles import (
    PARAMETER_NAMES,
    ExecutionParameterProfileV1,
    ParameterName,
    ParameterValuesV1,
    ProfileKeyV1,
    ProfileState,
)
from app.services.learning.item_supply.storage_contracts import (
    StorageContract,
    checked_model,
)

Score = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
_TIMEOUT_METRICS: dict[ParameterName, str] = {
    "connection_timeout_ms": "actual_connection_ms",
    "first_token_timeout_ms": "actual_first_token_ms",
    "stream_idle_timeout_ms": "actual_stream_idle_ms",
    "request_timeout_ms": "actual_request_ms",
    "stage_deadline_ms": "actual_stage_ms",
    "parent_deadline_ms": "actual_parent_ms",
}
_ROUND_METRICS: dict[ParameterName, tuple[str, str]] = {
    "discussion_rounds": ("actual_discussion_rounds", "discussion_tail_contributions"),
    "revision_rounds": ("actual_revision_rounds", "revision_tail_contributions"),
    "investigation_rounds": (
        "actual_investigation_rounds",
        "investigation_tail_contributions",
    ),
}


class CalibrationPolicyV1(StorageContract):
    schema_version: Literal["parameter_calibration_policy_v1"] = (
        "parameter_calibration_policy_v1"
    )
    version: int = Field(default=1, ge=1)
    minimum_samples: int = Field(ge=2, le=10_000)
    minimum_complete_samples: int = Field(ge=2, le=10_000)
    maximum_right_censored_ratio: Score
    minimum_quality_score: Score
    minimum_coverage_score: Score
    timeout_step_ratio: float = Field(gt=0, le=0.25, allow_inf_nan=False)
    timeout_safety_margin_ratio: float = Field(gt=0, le=1, allow_inf_nan=False)
    maximum_quality_regression: Score
    maximum_coverage_regression: Score
    minimum_canary_samples: int = Field(ge=2, le=10_000)
    round_step: int = Field(ge=1, le=2)
    cooldown_seconds: int = Field(ge=1, le=31_536_000)
    freeze_after_rollbacks: int = Field(ge=1, le=16)
    minimum_window_seconds: int = Field(ge=1, le=31_536_000)
    latency_quantile: float = Field(ge=0.9, le=0.99, allow_inf_nan=False)
    minimum_quantile_samples: int = Field(ge=10, le=10_000)
    minimum_idle_tail_rounds: int = Field(ge=1, le=8)
    maximum_tail_contribution: Score
    minimum_qualified_yield_score: Score
    maximum_token_growth_ratio: float = Field(ge=1, le=2, allow_inf_nan=False)
    maximum_retry_increase: int = Field(ge=0, le=8)

    @model_validator(mode="after")
    def coherent(self) -> CalibrationPolicyV1:
        if self.minimum_complete_samples > self.minimum_samples:
            raise ValueError("complete sample threshold exceeds total threshold")
        if self.minimum_quantile_samples < ceil(1 / (1 - self.latency_quantile)):
            raise ValueError("tail quantile needs a representative population")
        return self

    @property
    def policy_hash(self) -> str:
        return canonical_hash(
            checked_model(self, CalibrationPolicyV1).model_dump(mode="json")
        )


class CalibrationObservationV1(StorageContract):
    schema_version: Literal["parameter_calibration_observation_v1"] = (
        "parameter_calibration_observation_v1"
    )
    observation_key: Identifier
    profile_key_hash: Digest
    profile_version: int = Field(ge=1)
    provider_version: Identifier
    model_version: Identifier
    runtime_version: Identifier
    load_bucket: Identifier
    prompt_version: Identifier
    validator_version: Identifier
    output_size_bucket: Identifier
    complexity_version: Identifier
    mode: Literal["shadow", "canary", "live", "control"]
    comparison_key: Identifier | None = None
    completed: bool
    right_censored: bool
    termination: Literal["completed", "timeout", "failed", "cancelled"]
    timeout_parameter: ParameterName | None = None
    quality_score: Score
    coverage_score: Score
    baseline_quality_score: Score
    baseline_coverage_score: Score
    qualified_yield_score: Score
    first_review_passed: bool
    final_review_passed: bool
    unresolved_issues: int = Field(ge=0, le=10_000)
    scorer_blocked: bool
    safety_blocked: bool
    retry_count: int = Field(ge=0, le=128)
    usage_tokens: int | None = Field(ge=0, le=1_000_000_000)
    values_used: ParameterValuesV1
    actual_connection_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    actual_first_token_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    actual_stream_idle_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    actual_request_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    actual_stage_ms: int | None = Field(default=None, ge=0, le=604_800_000)
    actual_parent_ms: int | None = Field(default=None, ge=0, le=2_592_000_000)
    actual_discussion_rounds: int | None = Field(default=None, ge=0, le=64)
    actual_revision_rounds: int | None = Field(default=None, ge=0, le=64)
    actual_investigation_rounds: int | None = Field(default=None, ge=0, le=64)
    discussion_tail_contributions: tuple[Score, ...] = Field(default=(), max_length=64)
    revision_tail_contributions: tuple[Score, ...] = Field(default=(), max_length=64)
    investigation_tail_contributions: tuple[Score, ...] = Field(
        default=(), max_length=64
    )
    observed_at: datetime

    @model_validator(mode="after")
    def shape(self) -> CalibrationObservationV1:
        if self.observed_at.tzinfo is None:
            raise ValueError("observation timestamp must be aware")
        if self.completed != (self.termination == "completed"):
            raise ValueError("terminal completion facts conflict")
        if self.completed and self.right_censored:
            raise ValueError("completion is not a right-censored duration")
        if self.termination in ("timeout", "cancelled") and not self.right_censored:
            raise ValueError("timeout/cancellation must retain right-censoring")
        if self.timeout_parameter is not None and (
            self.termination != "timeout"
            or self.timeout_parameter not in _TIMEOUT_METRICS
        ):
            raise ValueError("timeout boundary must identify an actual time limit")
        for name, metric in _TIMEOUT_METRICS.items():
            value = getattr(self, metric)
            if (
                self.completed
                and value is not None
                and value > self.values_used.value(name)
            ):
                raise ValueError("completed duration exceeds its permitted timeout")
        for name, (metric, tail_metric) in _ROUND_METRICS.items():
            value, tail = getattr(self, metric), getattr(self, tail_metric)
            if value is not None and value > self.values_used.value(name):
                raise ValueError("actual rounds exceed permitted rounds")
            if tail and (value is None or len(tail) > value):
                raise ValueError("round contribution facts have no matching rounds")
        return self


class CalibrationWindowV1(StorageContract):
    """Trusted collector's full terminal population, never selected successes.

    Controls carry the experiment profile identity but last_stable values. The
    future owner must resolve these from immutable actual job snapshots.
    """

    schema_version: Literal["parameter_calibration_window_v1"] = (
        "parameter_calibration_window_v1"
    )
    window_key: Identifier
    profile_hash: Digest
    policy_hash: Digest
    expected_observation_keys: tuple[Identifier, ...] = Field(
        min_length=1, max_length=10_000
    )
    started_at: datetime
    ended_at: datetime

    @model_validator(mode="after")
    def population(self) -> CalibrationWindowV1:
        if self.started_at.tzinfo is None or self.ended_at.tzinfo is None:
            raise ValueError("window must be aware")
        if self.ended_at < self.started_at:
            raise ValueError("window order invalid")
        if len(set(self.expected_observation_keys)) != len(
            self.expected_observation_keys
        ):
            raise ValueError("window observation identities must be unique")
        return self


class CalibrationDecisionV1(StorageContract):
    action: Literal["hold", "propose", "commit", "rollback", "freeze"]
    reason: Identifier
    source_profile_hash: Digest
    policy_hash: Digest
    evaluated_at: datetime
    parameter: ParameterName | None = None
    proposed: ParameterValuesV1 | None = None
    next_state: ProfileState
    cooldown_until: datetime | None = None
    rollback_count: int = Field(ge=0, le=16)

    @model_validator(mode="after")
    def shape(self) -> CalibrationDecisionV1:
        if self.evaluated_at.tzinfo is None:
            raise ValueError("decision clock must be aware")
        if self.cooldown_until is not None and (
            self.cooldown_until.tzinfo is None
            or self.cooldown_until <= self.evaluated_at
        ):
            raise ValueError("invalid cooldown")
        if (self.action == "hold") != (self.proposed is None):
            raise ValueError("mutating decisions require values")
        if (self.action == "propose") != (self.parameter is not None):
            raise ValueError("proposal requires exactly one named dimension")
        return self


def _context_matches(key: ProfileKeyV1, o: CalibrationObservationV1) -> bool:
    return (
        o.provider_version == key.provider_version
        and o.model_version == key.model_version
        and o.runtime_version == key.runtime
        and o.load_bucket == key.load_bucket
        and o.prompt_version == key.prompt_version
        and o.validator_version == key.validator_version
        and o.output_size_bucket == key.output_size_bucket
        and o.complexity_version == key.complexity_version
    )


def _single_step(
    stable: ParameterValuesV1, candidate: ParameterValuesV1, policy: CalibrationPolicyV1
) -> ParameterName | None:
    changed = tuple(
        name for name in PARAMETER_NAMES if stable.value(name) != candidate.value(name)
    )
    if len(changed) != 1:
        return None
    name = changed[0]
    delta = stable.value(name) - candidate.value(name)
    allowed = (
        policy.round_step
        if name in _ROUND_METRICS
        else max(1, int(stable.value(name) * policy.timeout_step_ratio))
    )
    return name if 0 < delta <= allowed else None


def calibrate(
    profile: ExecutionParameterProfileV1,
    observations: tuple[CalibrationObservationV1, ...],
    policy: CalibrationPolicyV1,
    *,
    now: datetime,
    rollback_count: int | None = None,
    window: CalibrationWindowV1 | None = None,
) -> CalibrationDecisionV1:
    p = checked_model(profile, ExecutionParameterProfileV1)
    pol = checked_model(policy, CalibrationPolicyV1)
    if not isinstance(observations, tuple) or len(observations) > 10_000:
        raise ValueError("calibration requires bounded observation tuples")
    obs = tuple(checked_model(item, CalibrationObservationV1) for item in observations)
    # Validate every supplied contract even if the decision will hold early.
    w = checked_model(window, CalibrationWindowV1) if window is not None else None
    if now.tzinfo is None or now < p.measurement_window_started_at:
        raise ValueError("invalid calibration clock")
    if rollback_count is not None and (
        type(rollback_count) is not int or not 0 <= rollback_count <= 16
    ):
        raise ValueError("invalid rollback count")
    count = max(p.rollback_count, rollback_count or 0)

    def decision(
        action: Literal["hold", "propose", "commit", "rollback", "freeze"],
        reason: str,
        *,
        state: ProfileState | None = None,
        proposed: ParameterValuesV1 | None = None,
        parameter: ParameterName | None = None,
        cooldown: datetime | None = None,
        rollbacks: int = count,
    ) -> CalibrationDecisionV1:
        return CalibrationDecisionV1(
            action=action,
            reason=reason,
            source_profile_hash=p.profile_hash,
            policy_hash=pol.policy_hash,
            evaluated_at=now,
            parameter=parameter,
            proposed=proposed,
            next_state=state or p.state,
            cooldown_until=cooldown,
            rollback_count=rollbacks,
        )

    def rollback(reason: str) -> CalibrationDecisionV1:
        freeze = count + 1 >= pol.freeze_after_rollbacks
        return decision(
            "freeze" if freeze else "rollback",
            reason,
            state="frozen" if freeze else "stable",
            proposed=p.last_stable,
            cooldown=now + timedelta(seconds=pol.cooldown_seconds),
            rollbacks=min(16, count + 1),
        )

    if p.state in ("frozen", "blocked"):
        return decision("hold", "profile_" + p.state)
    if not p.profile_key.calibration_ready:
        return decision("hold", "calibration_context_missing", state="warmup")

    def matches_profile(o: CalibrationObservationV1) -> bool:
        return (
            o.profile_key_hash == p.profile_key.key_hash
            and o.profile_version == p.version
            and _context_matches(p.profile_key, o)
        )

    def uses_expected_values(o: CalibrationObservationV1) -> bool:
        return o.values_used == (
            p.last_stable
            if o.mode == "control" or (o.mode == "shadow" and p.state == "canary")
            else p.current
        )

    def in_measurement_window(o: CalibrationObservationV1) -> bool:
        return p.measurement_window_started_at <= o.observed_at <= now and (
            p.measurement_window_ended_at is None
            or o.observed_at <= p.measurement_window_ended_at
        )

    # One matching terminal failure is sufficient to withdraw a canary. A mixed
    # or duplicated population cannot hide it, but unrelated versions, values or
    # old windows must not trigger a rollback of this profile.
    real = tuple(
        o
        for o in obs
        if o.mode != "shadow"
        and matches_profile(o)
        and uses_expected_values(o)
        and in_measurement_window(o)
    )
    if any(o.scorer_blocked or o.safety_blocked for o in real):
        return rollback("absolute_blocker")
    if any(
        o.completed
        and (
            o.quality_score < pol.minimum_quality_score
            or o.coverage_score < pol.minimum_coverage_score
            or o.quality_score
            < o.baseline_quality_score - pol.maximum_quality_regression
            or o.coverage_score
            < o.baseline_coverage_score - pol.maximum_coverage_regression
            or o.qualified_yield_score < pol.minimum_qualified_yield_score
            or not o.final_review_passed
            or o.unresolved_issues != 0
        )
        for o in real
    ):
        return rollback("quality_or_coverage_regression")
    changed_dimension = (
        _single_step(p.last_stable, p.current, pol) if p.state == "canary" else None
    )
    if p.state == "canary" and any(
        o.mode == "canary"
        and o.termination == "timeout"
        and o.timeout_parameter is not None
        and o.timeout_parameter == changed_dimension
        for o in real
    ):
        return rollback("canary_false_timeout")
    if any(not matches_profile(o) for o in obs):
        return decision("hold", "version_or_load_changed", state="warmup")
    if any(not uses_expected_values(o) for o in obs):
        return decision("hold", "observation_values_mismatch", state="warmup")
    if len({o.observation_key for o in obs}) != len(obs):
        return decision("hold", "duplicate_observation_identity")
    if any(not in_measurement_window(o) for o in obs):
        return decision("hold", "outside_measurement_window", state="warmup")
    if p.cooldown_until is not None and now < p.cooldown_until:
        return decision("hold", "cooldown_active")
    if p.state == "proposed":
        return decision("hold", "canary_not_started")
    if len(real) < pol.minimum_samples:
        return decision("hold", "insufficient_samples")
    if w is None:
        return decision("hold", "observation_population_unverified")
    if (
        w.profile_hash != p.profile_hash
        or w.policy_hash != pol.policy_hash
        or set(w.expected_observation_keys) != {o.observation_key for o in obs}
        or w.started_at < p.measurement_window_started_at
        or w.ended_at > now
        or (
            p.measurement_window_ended_at is not None
            and w.ended_at > p.measurement_window_ended_at
        )
        or any(not w.started_at <= o.observed_at <= w.ended_at for o in obs)
    ):
        return decision("hold", "observation_population_mismatch")
    if (w.ended_at - w.started_at).total_seconds() < pol.minimum_window_seconds or (
        max(o.observed_at for o in real) - min(o.observed_at for o in real)
    ).total_seconds() < pol.minimum_window_seconds:
        return decision("hold", "measurement_window_too_short")
    if (
        any(not o.completed or o.right_censored for o in real)
        or sum(o.right_censored for o in real) / len(real)
        > pol.maximum_right_censored_ratio
    ):
        return decision("hold", "censored_failure_or_success_bias")
    if any(o.usage_tokens is None for o in real):
        return decision("hold", "usage_unknown")
    if any(
        o.mode == "shadow"
        and (
            o.right_censored
            or not o.completed
            or o.scorer_blocked
            or o.safety_blocked
            or o.quality_score < pol.minimum_quality_score
            or o.coverage_score < pol.minimum_coverage_score
            or o.quality_score
            < o.baseline_quality_score - pol.maximum_quality_regression
            or o.coverage_score
            < o.baseline_coverage_score - pol.maximum_coverage_regression
            or o.qualified_yield_score < pol.minimum_qualified_yield_score
            or not o.final_review_passed
            or o.unresolved_issues != 0
        )
        for o in obs
    ):
        return decision("hold", "shadow_predicts_truncation")
    if p.state == "canary":
        if changed_dimension is None:
            return rollback("canary_step_outside_policy")
        canary = tuple(o for o in obs if o.mode == "canary")
        controls = tuple(o for o in obs if o.mode == "control")
        if len(canary) < pol.minimum_canary_samples:
            return decision("hold", "shadow_not_quality_proof")
        if len(controls) < pol.minimum_canary_samples:
            return decision("hold", "stable_control_missing")
        c_keys, b_keys = (
            [o.comparison_key for o in canary],
            [o.comparison_key for o in controls],
        )
        if (
            None in c_keys
            or None in b_keys
            or len(set(c_keys)) != len(c_keys)
            or len(set(b_keys)) != len(b_keys)
            or set(c_keys) != set(b_keys)
        ):
            return decision("hold", "canary_control_population_mismatch")
        if any(o.mode == "live" for o in obs):
            return decision("hold", "canary_population_mixed")
        if any(
            (
                max(o.observed_at for o in arm) - min(o.observed_at for o in arm)
            ).total_seconds()
            < pol.minimum_window_seconds
            for arm in (canary, controls)
        ):
            return decision("hold", "canary_window_too_short")
        metric = (
            _TIMEOUT_METRICS[changed_dimension]
            if changed_dimension in _TIMEOUT_METRICS
            else _ROUND_METRICS[changed_dimension][0]
        )
        if any(getattr(o, metric) is None for o in canary + controls):
            return decision("hold", "canary_metric_missing")
        shadow_actuals = [getattr(o, metric) for o in obs if o.mode == "shadow"]
        if any(value is None for value in shadow_actuals):
            return decision("hold", "shadow_metric_missing")
        if any(value > p.current.value(changed_dimension) for value in shadow_actuals):
            return decision("hold", "shadow_predicts_truncation")
        control_by_scenario = {o.comparison_key: o for o in controls}
        for candidate in canary:
            control = control_by_scenario[candidate.comparison_key]
            if (
                candidate.quality_score
                < control.quality_score - pol.maximum_quality_regression
                or candidate.coverage_score
                < control.coverage_score - pol.maximum_coverage_regression
                or candidate.qualified_yield_score < control.qualified_yield_score
                or (control.first_review_passed and not candidate.first_review_passed)
            ):
                return rollback("canary_control_regression")
            if (
                candidate.retry_count > control.retry_count + pol.maximum_retry_increase
                or candidate.usage_tokens is None
                or control.usage_tokens is None
                or candidate.usage_tokens
                > control.usage_tokens * pol.maximum_token_growth_ratio
            ):
                return rollback("canary_cost_or_retry_regression")
        return decision(
            "commit",
            "offline_canary_validated",
            state="stable",
            proposed=p.current,
            cooldown=now + timedelta(seconds=pol.cooldown_seconds),
        )
    complete = tuple(o for o in obs if o.mode == "live")
    if len(complete) < pol.minimum_complete_samples:
        return decision("hold", "shadow_not_quality_proof")
    if any(o.mode not in ("live", "shadow") for o in obs):
        return decision("hold", "baseline_population_mixed")
    # Never select only the subset which happens to report fast timings.
    for name in PARAMETER_NAMES:
        current = p.current.value(name)
        if name in _TIMEOUT_METRICS:
            actuals = [getattr(o, _TIMEOUT_METRICS[name]) for o in complete]
            if (
                any(value is None for value in actuals)
                or len(actuals) < pol.minimum_quantile_samples
            ):
                continue
            durations = sorted(int(value) for value in actuals)
            high_quantile = durations[ceil(pol.latency_quantile * len(durations)) - 1]
            # Retain margin for all observed slow successes, not just the quantile.
            margin = ceil(
                max(high_quantile, durations[-1])
                * (1 + pol.timeout_safety_margin_ratio)
            )
            target = max(
                margin,
                p.floor.value(name),
                current - max(1, int(current * pol.timeout_step_ratio)),
            )
        else:
            metric, tail_metric = _ROUND_METRICS[name]
            rounds = [getattr(o, metric) for o in complete]
            tails = [getattr(o, tail_metric) for o in complete]
            if any(value is None for value in rounds) or any(
                len(tail) < pol.minimum_idle_tail_rounds
                or max(tail[-pol.minimum_idle_tail_rounds :])
                > pol.maximum_tail_contribution
                for tail in tails
            ):
                continue
            target = max(
                max(int(value) for value in rounds),
                p.floor.value(name),
                current - pol.round_step,
            )
        if target >= current:
            continue
        try:
            proposed = p.current.replace(name, target)
        except ValueError:
            # Dependent timeout hierarchy can make this particular step unsafe.
            continue
        metric = (
            _TIMEOUT_METRICS[name]
            if name in _TIMEOUT_METRICS
            else _ROUND_METRICS[name][0]
        )
        shadow_actuals = [getattr(o, metric) for o in obs if o.mode == "shadow"]
        if any(value is None for value in shadow_actuals):
            return decision("hold", "shadow_metric_missing")
        if any(value > target for value in shadow_actuals):
            return decision("hold", "shadow_predicts_truncation")
        return decision(
            "propose",
            "single_dimension_canary",
            state="proposed",
            proposed=proposed,
            parameter=name,
        )
    return decision("hold", "no_safe_idle_margin")


def apply_decision(
    profile: ExecutionParameterProfileV1,
    result: CalibrationDecisionV1,
    policy: CalibrationPolicyV1,
) -> ExecutionParameterProfileV1:
    """Trusted controller composition only, not a model recommendation endpoint.

    Versions configs in memory. Durable CAS/job binding belongs to the repository
    owner. This API has no canonical root field and cannot reset any budget.
    """
    p = checked_model(profile, ExecutionParameterProfileV1)
    d = checked_model(result, CalibrationDecisionV1)
    pol = checked_model(policy, CalibrationPolicyV1)
    if d.source_profile_hash != p.profile_hash or d.policy_hash != pol.policy_hash:
        raise ValueError("decision does not belong to this profile/policy")
    if d.action == "hold":
        return p
    if (
        p.state in ("blocked", "frozen")
        or d.evaluated_at < p.measurement_window_started_at
    ):
        raise ValueError("profile cannot change automatically")
    assert d.proposed is not None
    if d.action in ("propose", "commit") and d.rollback_count != p.rollback_count:
        raise ValueError("successful tuning cannot clear oscillator history")
    if d.action in ("propose", "commit") and (
        p.cooldown_until is not None and d.evaluated_at < p.cooldown_until
    ):
        raise ValueError("tuning cannot skip active cooldown")
    if d.action == "propose":
        if (
            p.state not in ("warmup", "stable")
            or d.next_state != "proposed"
            or _single_step(p.current, d.proposed, pol) != d.parameter
        ):
            raise ValueError("invalid single-step proposal")
    elif d.action == "commit":
        if (
            p.state != "canary"
            or d.next_state != "stable"
            or d.proposed != p.current
            or _single_step(p.last_stable, p.current, pol) is None
        ):
            raise ValueError("only validated canary can commit")
    else:
        expected_count = min(16, p.rollback_count + 1)
        freeze = expected_count >= pol.freeze_after_rollbacks
        if (
            d.proposed != p.last_stable
            or d.rollback_count != expected_count
            or d.action != ("freeze" if freeze else "rollback")
            or d.next_state != ("frozen" if freeze else "stable")
        ):
            raise ValueError(
                "rollback can only restore stable values and retain oscillator history"
            )
    if d.action in ("commit", "rollback", "freeze") and (
        d.cooldown_until != d.evaluated_at + timedelta(seconds=pol.cooldown_seconds)
    ):
        raise ValueError("validated cooldown cannot be skipped")
    if d.action == "propose" and d.cooldown_until is not None:
        raise ValueError("proposal cannot invent cooldown state")
    return ExecutionParameterProfileV1.model_validate(
        {
            **p.model_dump(mode="python"),
            "version": p.version + 1,
            "parent_version": p.version,
            "state": d.next_state,
            "current": d.proposed,
            "last_stable": d.proposed
            if d.action == "commit"
            else (p.current if d.action == "propose" else p.last_stable),
            "change_reason": d.reason,
            "rollback_count": d.rollback_count,
            "cooldown_until": d.cooldown_until,
            "measurement_window_started_at": d.evaluated_at,
            "measurement_window_ended_at": None,
        },
        strict=True,
    )


def begin_canary(
    profile: ExecutionParameterProfileV1, *, started_at: datetime
) -> ExecutionParameterProfileV1:
    p = checked_model(profile, ExecutionParameterProfileV1)
    if (
        p.state != "proposed"
        or started_at.tzinfo is None
        or started_at < p.measurement_window_started_at
        or (p.cooldown_until is not None and started_at < p.cooldown_until)
    ):
        raise ValueError("canary requires a proposed profile and a valid clock")
    return ExecutionParameterProfileV1.model_validate(
        {
            **p.model_dump(mode="python"),
            "version": p.version + 1,
            "parent_version": p.version,
            "state": "canary",
            "change_reason": "offline_canary_started",
            "measurement_window_started_at": started_at,
            "measurement_window_ended_at": None,
        },
        strict=True,
    )
