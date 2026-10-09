"""Synthetic P3-B pure contracts: no provider, database, worker or root fixtures."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from app.services.learning.item_supply.calibration import (
    CalibrationObservationV1,
    CalibrationPolicyV1,
    CalibrationWindowV1,
    apply_decision,
    begin_canary,
    calibrate,
)
from app.services.learning.item_supply.parameter_profiles import (
    PARAMETER_NAMES,
    ExecutionParameterProfileV1,
    FrozenProfileSnapshot,
    ParameterValuesV1,
    ProfileKeyV1,
    freeze_profile,
)

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
START = NOW - timedelta(minutes=3)


def changed(model: BaseModel, **updates: object):
    return type(model).model_validate(
        {**model.model_dump(mode="python"), **updates}, strict=True
    )


def values() -> ParameterValuesV1:
    return ParameterValuesV1(
        connection_timeout_ms=20_000,
        first_token_timeout_ms=30_000,
        stream_idle_timeout_ms=40_000,
        request_timeout_ms=100_000,
        stage_deadline_ms=300_000,
        parent_deadline_ms=600_000,
        discussion_rounds=8,
        revision_rounds=8,
        investigation_rounds=8,
    )


def profile(**updates: object) -> ExecutionParameterProfileV1:
    initial = values()
    p = ExecutionParameterProfileV1(
        profile_key=ProfileKeyV1(
            provider="synthetic.provider",
            provider_version="provider.v1",
            model_version="model.v1",
            agent_role="technical_reviewer",
            item_kind="code",
            risk_tier="medium",
            difficulty="advanced",
            input_size_bucket="large",
            output_size_bucket="medium",
            runtime="python.v1",
            prompt_version="prompt.v1",
            validator_version="validator.v1",
            load_bucket="normal",
            complexity_version="mix.v1",
        ),
        version=1,
        state="stable",
        initial=initial,
        current=initial,
        last_stable=initial,
        floor=ParameterValuesV1(
            connection_timeout_ms=10_000,
            first_token_timeout_ms=15_000,
            stream_idle_timeout_ms=20_000,
            request_timeout_ms=60_000,
            stage_deadline_ms=180_000,
            parent_deadline_ms=360_000,
            discussion_rounds=2,
            revision_rounds=2,
            investigation_rounds=2,
        ),
        ceiling=ParameterValuesV1(
            connection_timeout_ms=40_000,
            first_token_timeout_ms=60_000,
            stream_idle_timeout_ms=80_000,
            request_timeout_ms=300_000,
            stage_deadline_ms=900_000,
            parent_deadline_ms=1_800_000,
            discussion_rounds=16,
            revision_rounds=16,
            investigation_rounds=16,
        ),
        measurement_window_started_at=START,
        change_reason="synthetic.preflight",
        trusted_initial_evidence=("synthetic.config.v1", "synthetic.slow_probe.v1"),
    )
    return changed(p, **updates)


def policy(**updates: object) -> CalibrationPolicyV1:
    p = CalibrationPolicyV1(
        minimum_samples=20,
        minimum_complete_samples=20,
        minimum_canary_samples=5,
        maximum_right_censored_ratio=0.1,
        minimum_quality_score=0.8,
        minimum_coverage_score=0.8,
        timeout_step_ratio=0.1,
        timeout_safety_margin_ratio=0.2,
        maximum_quality_regression=0.03,
        maximum_coverage_regression=0.03,
        round_step=1,
        cooldown_seconds=60,
        freeze_after_rollbacks=2,
        minimum_window_seconds=60,
        latency_quantile=0.9,
        minimum_quantile_samples=20,
        minimum_idle_tail_rounds=2,
        maximum_tail_contribution=0.01,
        minimum_qualified_yield_score=0.9,
        maximum_token_growth_ratio=1.1,
        maximum_retry_increase=0,
    )
    return changed(p, **updates)


def observation(
    p: ExecutionParameterProfileV1,
    index: int = 0,
    *,
    now: datetime = NOW,
    mode: str = "live",
    **updates: object,
) -> CalibrationObservationV1:
    key = p.profile_key
    o = CalibrationObservationV1(
        observation_key=f"synthetic.{mode}.{index}",
        profile_key_hash=key.key_hash,
        profile_version=p.version,
        provider_version=key.provider_version,
        model_version=key.model_version,
        runtime_version=key.runtime,
        load_bucket=key.load_bucket,
        prompt_version=key.prompt_version,
        validator_version=key.validator_version,
        output_size_bucket=key.output_size_bucket,
        complexity_version=key.complexity_version,
        mode=mode,
        comparison_key=f"scenario.{index}" if mode in ("canary", "control") else None,
        completed=True,
        right_censored=False,
        termination="completed",
        quality_score=0.96,
        coverage_score=0.96,
        baseline_quality_score=0.96,
        baseline_coverage_score=0.96,
        qualified_yield_score=0.95,
        first_review_passed=True,
        final_review_passed=True,
        unresolved_issues=0,
        scorer_blocked=False,
        safety_blocked=False,
        retry_count=0,
        usage_tokens=1000,
        values_used=p.last_stable
        if mode == "control" or (mode == "shadow" and p.state == "canary")
        else p.current,
        actual_request_ms=min(50_000, p.current.request_timeout_ms),
        observed_at=now - timedelta(seconds=100 - index * 5),
    )
    return changed(o, **updates)


def cohort(
    p: ExecutionParameterProfileV1,
    *,
    mode: str = "live",
    count: int = 20,
    now: datetime = NOW,
    **updates: object,
) -> tuple[CalibrationObservationV1, ...]:
    return tuple(observation(p, i, mode=mode, now=now, **updates) for i in range(count))


def window(
    p: ExecutionParameterProfileV1,
    samples: tuple[CalibrationObservationV1, ...],
    pol: CalibrationPolicyV1,
    **updates: object,
) -> CalibrationWindowV1:
    w = CalibrationWindowV1(
        window_key="synthetic.window.v1",
        profile_hash=p.profile_hash,
        policy_hash=pol.policy_hash,
        expected_observation_keys=tuple(o.observation_key for o in samples),
        started_at=min(o.observed_at for o in samples),
        ended_at=max(o.observed_at for o in samples),
    )
    return changed(w, **updates)


def evaluate(
    p: ExecutionParameterProfileV1,
    samples: tuple[CalibrationObservationV1, ...],
    pol: CalibrationPolicyV1 | None = None,
    *,
    now: datetime = NOW,
):
    pol = pol or policy()
    return calibrate(
        p, samples, pol, now=now, window=window(p, samples, pol) if samples else None
    )


def canary(**updates: object) -> ExecutionParameterProfileV1:
    return profile(
        **{
            "state": "canary",
            "current": values().replace("request_timeout_ms", 90_000),
            **updates,
        }
    )


def paired(
    p: ExecutionParameterProfileV1, **updates: object
) -> tuple[CalibrationObservationV1, ...]:
    return cohort(p, mode="canary", **updates) + cohort(p, mode="control")


def test_no_timeout_or_round_defaults_or_legacy_claims() -> None:
    with pytest.raises(ValidationError):
        ParameterValuesV1()
    p = profile()
    assert p.initial.request_timeout_ms != 90_000
    assert p.initial.discussion_rounds != 2
    legacy = changed(p, profile_key=changed(p.profile_key, provider_version=None))
    assert evaluate(legacy, ()).reason == "calibration_context_missing"
    assert freeze_profile(legacy, bound_at=NOW).values == legacy.current


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider", "another"),
        ("provider_version", "v2"),
        ("model_version", "model.v2"),
        ("agent_role", "investigator"),
        ("item_kind", "knowledge_check"),
        ("risk_tier", "high"),
        ("difficulty", "basic"),
        ("input_size_bucket", "small"),
        ("output_size_bucket", "large"),
        ("runtime", "python.v2"),
        ("prompt_version", "prompt.v2"),
        ("validator_version", "validator.v2"),
        ("load_bucket", "busy"),
        ("complexity_version", "mix.v2"),
    ],
)
def test_every_bucket_coordinate_changes_hash(field: str, value: str) -> None:
    p = profile()
    assert changed(p.profile_key, **{field: value}).key_hash != p.profile_key.key_hash


@pytest.mark.parametrize("samples", [0, 1, 19])
def test_no_or_few_samples_keep_current_and_state(samples: int) -> None:
    p = profile(state="warmup")
    before = p.profile_hash
    d = evaluate(p, cohort(p, count=samples))
    assert d.action == "hold" and d.reason == "insufficient_samples"
    assert d.next_state == "warmup" and d.proposed is None
    assert apply_decision(p, d, policy()).profile_hash == before


def test_complete_population_manifest_prevents_success_selection_and_replay() -> None:
    p, pol = profile(), policy()
    all_samples = cohort(p)
    assert (
        calibrate(p, all_samples, pol, now=NOW).reason
        == "observation_population_unverified"
    )
    manifest = window(p, all_samples, pol)
    failure = changed(all_samples[-1], completed=False, termination="failed")
    complete = all_samples[:-1] + (failure,)
    assert (
        calibrate(p, complete, pol, now=NOW, window=manifest).reason
        == "censored_failure_or_success_bias"
    )
    successful = complete[:-1] + (
        changed(complete[-2], observation_key="other.success"),
    )
    assert (
        calibrate(p, successful, pol, now=NOW, window=manifest).reason
        == "observation_population_mismatch"
    )
    replay = all_samples[:-1] + (all_samples[0],)
    assert (
        calibrate(p, replay, pol, now=NOW, window=manifest).reason
        == "duplicate_observation_identity"
    )
    with pytest.raises(ValueError):
        window(p, replay, pol)


@pytest.mark.parametrize("termination", ["timeout", "cancelled", "failed"])
def test_failures_and_right_censoring_never_count_as_fast_completion(
    termination: str,
) -> None:
    p = profile()
    samples = cohort(p)
    censored = termination != "failed"
    sample = changed(
        samples[0], completed=False, right_censored=censored, termination=termination
    )
    d = evaluate(p, (sample,) + samples[1:])
    assert d.action == "hold" and d.reason == "censored_failure_or_success_bias"
    assert sample.actual_request_ms == 50_000  # lower bound, not completion evidence


@pytest.mark.parametrize("field", ["scorer_blocked", "safety_blocked"])
def test_absolute_blockers_precede_sample_counts_censoring_and_cooldown(
    field: str,
) -> None:
    p = profile(cooldown_until=NOW + timedelta(seconds=30))
    sample = observation(
        p, completed=False, termination="timeout", right_censored=True, **{field: True}
    )
    d = evaluate(p, (sample,))
    assert d.action == "rollback" and d.reason == "absolute_blocker"
    assert d.proposed == p.last_stable


@pytest.mark.parametrize(
    "facts",
    [
        {"quality_score": 0.5},
        {"coverage_score": 0.5},
        {"quality_score": 0.92},
        {"coverage_score": 0.92},
        {"qualified_yield_score": 0.85},
        {"final_review_passed": False},
        {"unresolved_issues": 1},
    ],
)
def test_quality_and_delivery_regression_reject_even_one_sample(
    facts: dict[str, object],
) -> None:
    p = canary()
    d = evaluate(p, (observation(p, mode="canary", **facts),))
    assert d.action == "rollback" and d.proposed == p.last_stable
    assert d.reason == "quality_or_coverage_regression"


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider_version", "v2"),
        ("model_version", "model.v2"),
        ("runtime_version", "python.v2"),
        ("load_bucket", "busy"),
        ("prompt_version", "prompt.v2"),
        ("validator_version", "validator.v2"),
        ("output_size_bucket", "large"),
        ("complexity_version", "mix.v2"),
        ("profile_version", 2),
        ("profile_key_hash", "0" * 64),
    ],
)
def test_version_runtime_load_or_complexity_change_holds_warmup(
    field: str, value: object
) -> None:
    p = profile()
    samples = cohort(p, **{field: value})
    d = evaluate(p, samples)
    assert d.reason == "version_or_load_changed" and d.next_state == "warmup"
    assert d.proposed is None


def test_values_used_not_just_version_must_match() -> None:
    p = profile()
    d = evaluate(
        p, cohort(p, values_used=values().replace("request_timeout_ms", 95_000))
    )
    assert d.reason == "observation_values_mismatch"


@pytest.mark.parametrize(
    "time", [START - timedelta(seconds=1), NOW + timedelta(seconds=1)]
)
def test_sample_time_outside_window_denies(time: datetime) -> None:
    p = profile()
    assert (
        evaluate(p, cohort(p, observed_at=time)).reason == "outside_measurement_window"
    )


def test_stability_window_is_measured_not_only_declared() -> None:
    p = profile()
    samples = cohort(p, observed_at=NOW)
    w = window(p, samples, policy(), started_at=START, ended_at=NOW)
    assert (
        calibrate(p, samples, policy(), now=NOW, window=w).reason
        == "measurement_window_too_short"
    )


@pytest.mark.parametrize("field", ["profile_hash", "policy_hash"])
def test_window_binding_cannot_cross_profiles_or_policies(field: str) -> None:
    p, pol = profile(), policy()
    samples = cohort(p)
    w = window(p, samples, pol, **{field: "0" * 64})
    assert (
        calibrate(p, samples, pol, now=NOW, window=w).reason
        == "observation_population_mismatch"
    )


@pytest.mark.parametrize(
    "name,metric,actual",
    [
        ("connection_timeout_ms", "actual_connection_ms", 5_000),
        ("first_token_timeout_ms", "actual_first_token_ms", 7_000),
        ("stream_idle_timeout_ms", "actual_stream_idle_ms", 8_000),
        ("request_timeout_ms", "actual_request_ms", 50_000),
        ("stage_deadline_ms", "actual_stage_ms", 120_000),
        ("parent_deadline_ms", "actual_parent_ms", 200_000),
    ],
)
def test_each_timeout_has_own_measurement_and_single_small_step(
    name: str, metric: str, actual: int
) -> None:
    p = profile()
    samples = (
        cohort(p, actual_request_ms=None, **{metric: actual})
        if metric != "actual_request_ms"
        else cohort(p)
    )
    d = evaluate(p, samples)
    assert d.action == "propose" and d.parameter == name
    assert d.proposed is not None
    changed_names = [
        field
        for field in PARAMETER_NAMES
        if d.proposed.value(field) != p.current.value(field)
    ]
    assert changed_names == [name]
    assert d.proposed.value(name) >= p.current.value(name) * 0.9
    assert d.proposed.value(name) >= actual * 1.2
    assert d.proposed.value(name) >= p.floor.value(name)


def test_parent_requires_parent_metric_not_stage_duration() -> None:
    p = profile(current=values().replace("stage_deadline_ms", 180_000))
    d = evaluate(p, cohort(p, actual_request_ms=None, actual_stage_ms=50_000))
    assert d.action == "hold" and d.reason == "no_safe_idle_margin"


def test_missing_metric_and_low_quantile_population_do_not_select_fast_subset() -> None:
    p = profile()
    obs = cohort(p)
    partial = obs[:-1] + (changed(obs[-1], actual_request_ms=None),)
    assert evaluate(p, partial).action == "hold"
    pol = policy(minimum_samples=3, minimum_complete_samples=3)
    small = cohort(p, count=3)
    small = tuple(
        changed(o, observed_at=START + timedelta(seconds=i * 70))
        for i, o in enumerate(small)
    )
    assert evaluate(p, small, pol).action == "hold"


def test_slow_tail_margin_blocks_false_fast_quantile_fit() -> None:
    p = profile()
    samples = cohort(p)
    slow = samples[:-1] + (changed(samples[-1], actual_request_ms=99_000),)
    assert evaluate(p, slow).action == "hold"


def test_dependency_deadline_boundary_holds_instead_of_raising() -> None:
    p = profile(
        current=values().replace("request_timeout_ms", 40_000),
        floor=changed(profile().floor, request_timeout_ms=30_000),
    )
    d = evaluate(p, cohort(p, actual_request_ms=10_000))
    assert d.action == "hold"  # idle timeout needs 40k; cannot shrink request alone


@pytest.mark.parametrize(
    "name,metric,tail",
    [
        (
            "discussion_rounds",
            "actual_discussion_rounds",
            "discussion_tail_contributions",
        ),
        ("revision_rounds", "actual_revision_rounds", "revision_tail_contributions"),
        (
            "investigation_rounds",
            "actual_investigation_rounds",
            "investigation_tail_contributions",
        ),
    ],
)
def test_rounds_require_resolved_actuals_and_idle_tail_contribution(
    name: str, metric: str, tail: str
) -> None:
    p = profile()
    idle = cohort(p, actual_request_ms=None, **{metric: 4, tail: (0.0, 0.0)})
    d = evaluate(p, idle)
    assert d.parameter == name and d.proposed.value(name) == 7
    useful = cohort(p, actual_request_ms=None, **{metric: 4, tail: (0.0, 0.5)})
    assert evaluate(p, useful).action == "hold"
    missing = cohort(p, actual_request_ms=None, **{metric: 4})
    assert evaluate(p, missing).action == "hold"


def test_shadow_cannot_propose_or_commit_quality() -> None:
    p = profile()
    assert evaluate(p, cohort(p, mode="shadow")).action == "hold"
    p = canary()
    shadow = cohort(p, mode="shadow") + cohort(p, mode="control")
    assert evaluate(p, shadow).reason == "shadow_not_quality_proof"
    assert evaluate(p, cohort(p, mode="canary")).reason == "stable_control_missing"


def test_shadow_predicted_truncation_rejects_proposal() -> None:
    p = profile()
    shadow = observation(
        p,
        100,
        observed_at=NOW,
        mode="shadow",
        completed=False,
        right_censored=True,
        termination="timeout",
    )
    assert evaluate(p, cohort(p) + (shadow,)).reason == "shadow_predicts_truncation"


def test_canary_requires_complete_unique_matched_control_population() -> None:
    p = canary()
    samples = paired(p)
    assert evaluate(p, samples).action == "commit"
    mismatched = samples[:-1] + (changed(samples[-1], comparison_key="other.scenario"),)
    assert evaluate(p, mismatched).reason == "canary_control_population_mismatch"
    duplicate = samples[:-1] + (changed(samples[-1], comparison_key="scenario.0"),)
    assert evaluate(p, duplicate).reason == "canary_control_population_mismatch"


@pytest.mark.parametrize(
    "updates,reason",
    [
        ({"first_review_passed": False}, "canary_control_regression"),
        ({"qualified_yield_score": 0.94}, "canary_control_regression"),
        ({"retry_count": 1}, "canary_cost_or_retry_regression"),
        ({"usage_tokens": 1200}, "canary_cost_or_retry_regression"),
    ],
)
def test_canary_checks_quality_yield_cost_retries_against_stable(
    updates: dict[str, object], reason: str
) -> None:
    p = canary()
    assert evaluate(p, paired(p, **updates)).reason == reason


def test_unknown_usage_holds_and_false_timeout_rolls_back_with_single_sample() -> None:
    p = canary()
    assert evaluate(p, paired(p, usage_tokens=None)).reason == "usage_unknown"
    sample = observation(
        p,
        mode="canary",
        completed=False,
        right_censored=True,
        termination="timeout",
        timeout_parameter="request_timeout_ms",
    )
    d = evaluate(p, (sample,))
    assert d.reason == "canary_false_timeout" and d.proposed == p.last_stable


def test_oversized_or_multi_dimension_canary_cannot_commit() -> None:
    with pytest.raises(ValueError):
        canary(
            current=values()
            .replace("request_timeout_ms", 90_000)
            .replace("discussion_rounds", 7)
        )
    p = profile(state="canary", current=values().replace("request_timeout_ms", 70_000))
    assert evaluate(p, paired(p)).reason == "canary_step_outside_policy"


def test_profile_evolution_updates_last_stable_and_cannot_mutate_old_job() -> None:
    p, pol = profile(), policy()
    snapshot = freeze_profile(
        p, bound_at=NOW, ancestor_deadline=NOW + timedelta(seconds=45)
    )
    old_json = snapshot.model_dump_json()
    decision = evaluate(p, cohort(p), pol)
    proposal = apply_decision(p, decision, pol)
    assert proposal.version == 2 and proposal.parent_version == 1
    assert proposal.state == "proposed" and proposal.last_stable == p.current
    with pytest.raises(ValueError):
        freeze_profile(proposal, bound_at=NOW)
    experiment = begin_canary(proposal, started_at=NOW)
    later = NOW + timedelta(minutes=3)
    samples = cohort(experiment, mode="canary", now=later) + cohort(
        experiment, mode="control", now=later
    )
    commit = evaluate(experiment, samples, pol, now=later)
    stable = apply_decision(experiment, commit, pol)
    assert (
        stable.state == "stable"
        and stable.current == stable.last_stable == experiment.current
    )
    assert stable.version == 4 and stable.cooldown_until > later
    assert snapshot.model_dump_json() == old_json and snapshot.values == p.current
    assert (
        snapshot.remaining_timeout_ms(
            "request_timeout_ms", now=NOW + timedelta(seconds=40)
        )
        == 5000
    )
    assert (
        snapshot.remaining_timeout_ms(
            "request_timeout_ms", now=NOW + timedelta(seconds=50)
        )
        == 0
    )


def test_rollback_cooldown_and_persistent_oscillation_freeze() -> None:
    p, pol = canary(), policy()
    first = evaluate(p, (observation(p, mode="canary", safety_blocked=True),))
    restored = apply_decision(p, first, pol)
    assert restored.current == p.last_stable and restored.rollback_count == 1
    assert restored.cooldown_until == NOW + timedelta(seconds=60)
    assert evaluate(restored, (), now=NOW).reason == "cooldown_active"
    later = NOW + timedelta(minutes=3)
    blocker = observation(restored, now=later, safety_blocked=True)
    second = evaluate(restored, (blocker,), now=later)
    frozen = apply_decision(restored, second, pol)
    assert frozen.state == "frozen" and frozen.rollback_count == 2
    assert evaluate(frozen, (), now=later).reason == "profile_frozen"
    assert freeze_profile(frozen, bound_at=later).values == frozen.last_stable
    # An external caller cannot lower a persisted oscillator count.
    assert (
        calibrate(restored, (blocker,), pol, now=later, rollback_count=0).action
        == "freeze"
    )


def test_decision_cas_and_policy_binding_reject_stale_or_tampered_proposal() -> None:
    p, pol = profile(), policy()
    d = evaluate(p, cohort(p), pol)
    with pytest.raises(ValueError):
        apply_decision(profile(version=2), d, pol)
    with pytest.raises(ValueError):
        apply_decision(p, d, changed(pol, version=2))
    forged = d.model_copy(
        update={"proposed": values().replace("request_timeout_ms", 70_000)}
    )
    with pytest.raises(ValueError):
        apply_decision(p, forged, pol)


@pytest.mark.parametrize("state", ["blocked", "frozen"])
def test_inactive_profiles_preserve_exact_state(state: str) -> None:
    p = profile(state=state)
    d = evaluate(p, ())
    assert d.action == "hold" and d.next_state == state
    if state == "blocked":
        with pytest.raises(ValueError):
            freeze_profile(p, bound_at=NOW)


@pytest.mark.parametrize(
    "ancestor", [NOW, NOW - timedelta(seconds=1), NOW.replace(tzinfo=None)]
)
def test_expired_or_naive_parent_cannot_bind_job(ancestor: datetime) -> None:
    with pytest.raises(ValueError):
        freeze_profile(profile(), bound_at=NOW, ancestor_deadline=ancestor)


def test_deadline_never_grows_to_later_ancestor_or_heartbeat() -> None:
    p = profile()
    snapshot = freeze_profile(
        p, bound_at=NOW, ancestor_deadline=NOW + timedelta(days=1)
    )
    assert snapshot.parent_deadline_at == NOW + timedelta(
        milliseconds=p.current.parent_deadline_ms
    )
    before = snapshot.model_dump_json()
    for seconds in (0, 10, 100, 500, 600, 700):
        assert (
            snapshot.remaining_timeout_ms(
                "stage_deadline_ms", now=NOW + timedelta(seconds=seconds)
            )
            <= max(0, 600 - seconds) * 1000
        )
    assert snapshot.model_dump_json() == before
    with pytest.raises(ValueError):
        snapshot.remaining_timeout_ms("discussion_rounds", now=NOW)


@pytest.mark.parametrize(
    "updates",
    [
        {"connection_timeout_ms": True},
        {"request_timeout_ms": "100000"},
        {"stage_deadline_ms": 50_000},
        {"parent_deadline_ms": 200_000},
        {"discussion_rounds": 0},
    ],
)
def test_values_strict_type_and_order(updates: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        changed(values(), **updates)


@pytest.mark.parametrize(
    "updates",
    [
        {"version": True},
        {"parent_version": 1},
        {"trusted_initial_evidence": ()},
        {"trusted_initial_evidence": ("same", "same")},
        {"measurement_window_started_at": NOW.replace(tzinfo=None)},
        {"current": values().replace("request_timeout_ms", 50_000)},
        {"ceiling": values().replace("request_timeout_ms", 80_000)},
    ],
)
def test_profile_bounds_evidence_lineage_are_strict(updates: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        profile(**updates)


@pytest.mark.parametrize(
    "updates",
    [
        {"right_censored": True},
        {"termination": "timeout"},
        {"quality_score": float("nan")},
        {"coverage_score": float("inf")},
        {"actual_request_ms": 100_001},
        {"actual_revision_rounds": 9},
        {"revision_tail_contributions": (0.0,)},
        {"observed_at": NOW.replace(tzinfo=None)},
    ],
)
def test_observation_terminal_metrics_nan_and_tail_rejected(
    updates: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        observation(profile(), **updates)


def test_nested_copy_construct_and_subclass_extras_fail_at_decision_and_hash_boundaries() -> (
    None
):
    p = profile()
    malformed = p.model_copy(
        update={"current": p.current.model_copy(update={"request_timeout_ms": True})}
    )
    with pytest.raises(ValueError):
        _ = malformed.profile_hash
    with pytest.raises(ValueError):
        freeze_profile(malformed, bound_at=NOW)
    invalid = observation(p).model_copy(update={"usage_tokens": "unknown"})
    with pytest.raises(ValueError):
        calibrate(p, (invalid,), policy(), now=NOW)

    class ExtraValues(ParameterValuesV1):
        model_advice: str

    extra = ExtraValues(
        **values().model_dump(mode="python"), model_advice="skip review"
    )
    with pytest.raises(ValueError):
        _ = p.model_copy(update={"current": extra}).profile_hash
    forged = FrozenProfileSnapshot.model_construct(
        profile_key_hash=p.profile_key.key_hash,
        profile_version=1,
        profile_hash=p.profile_hash,
        values=values(),
        bound_at=NOW,
        parent_deadline_at=NOW + timedelta(days=1),
    )
    with pytest.raises(ValueError):
        forged.remaining_timeout_ms("request_timeout_ms", now=NOW)


def test_policy_limits_cannot_relax_absolute_gates_or_claim_extreme_tail_on_tiny_batch() -> (
    None
):
    for changes in (
        {"timeout_step_ratio": 0.5},
        {"latency_quantile": 0.99},
        {"minimum_samples": 2},
        {"maximum_tail_contribution": float("nan")},
    ):
        with pytest.raises(ValueError):
            policy(**changes)
    p = profile()
    permissive = policy(
        minimum_quality_score=0.0,
        minimum_coverage_score=0.0,
        maximum_quality_regression=1.0,
        maximum_coverage_regression=1.0,
    )
    assert (
        evaluate(p, (observation(p, scorer_blocked=True),), permissive).reason
        == "absolute_blocker"
    )


def test_no_io_authority_imports_or_budget_root_fields() -> None:
    folder = Path(__file__).parents[2] / "app/services/learning/item_supply"
    for file in ("calibration.py", "parameter_profiles.py"):
        tree = ast.parse((folder / file).read_text(encoding="utf-8"))
        imports = [
            node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        ]
        assert not any(
            any(
                token in (module or "")
                for token in ("repository", "config", "provider", "scheduler", "worker")
            )
            for module in imports
        )
    for contract in (
        CalibrationObservationV1,
        CalibrationWindowV1,
        CalibrationPolicyV1,
        ExecutionParameterProfileV1,
        FrozenProfileSnapshot,
    ):
        assert not any(
            "budget_root" in name or "obligation" in name
            for name in contract.model_fields
        )


@pytest.mark.parametrize("state", ["stable", "canary"])
def test_shadow_historical_success_would_be_truncated_by_candidate(state: str) -> None:
    p = profile() if state == "stable" else canary()
    shadow = observation(
        p, 99, mode="shadow", observed_at=NOW, actual_request_ms=95_000
    )
    samples = cohort(p) if state == "stable" else paired(p)
    d = evaluate(p, samples + (shadow,))
    assert d.action == "hold" and d.reason == "shadow_predicts_truncation"


def test_canary_metric_missing_and_brief_canary_do_not_commit() -> None:
    p = canary()
    assert (
        evaluate(p, paired(p, actual_request_ms=None)).reason == "canary_metric_missing"
    )
    samples = cohort(p, mode="canary", observed_at=NOW) + cohort(p, mode="control")
    assert evaluate(p, samples).reason == "canary_window_too_short"
    samples = cohort(p, mode="canary") + cohort(p, mode="control", observed_at=NOW)
    assert evaluate(p, samples).reason == "canary_window_too_short"


def test_unknown_shadow_metric_cannot_validate_replay() -> None:
    p = canary()
    shadow = observation(p, 99, mode="shadow", observed_at=NOW, actual_request_ms=None)
    assert evaluate(p, paired(p) + (shadow,)).reason == "shadow_metric_missing"


def test_unrelated_network_timeout_or_cancellation_does_not_relax_tuning() -> None:
    p = canary()
    samples = paired(p)
    unrelated = changed(
        samples[0],
        completed=False,
        termination="timeout",
        right_censored=True,
        timeout_parameter="connection_timeout_ms",
    )
    d = evaluate(p, (unrelated,) + samples[1:])
    assert d.action == "hold" and d.proposed is None
    assert d.reason == "censored_failure_or_success_bias"
    cancellation = changed(
        samples[0], completed=False, termination="cancelled", right_censored=True
    )
    assert evaluate(p, (cancellation,) + samples[1:]).action == "hold"


def test_tampered_decision_cannot_skip_cooldown_freeze_or_reset_rollbacks() -> None:
    pol = policy()
    p = profile(rollback_count=1)
    proposal = evaluate(p, cohort(p))
    with pytest.raises(ValueError):
        apply_decision(p, proposal.model_copy(update={"rollback_count": 0}), pol)
    p = canary(rollback_count=1)
    freeze = evaluate(p, (observation(p, mode="canary", safety_blocked=True),))
    with pytest.raises(ValueError):
        apply_decision(
            p,
            freeze.model_copy(update={"action": "rollback", "next_state": "stable"}),
            pol,
        )
    with pytest.raises(ValueError):
        apply_decision(p, freeze.model_copy(update={"cooldown_until": None}), pol)


def test_rollback_not_unverified_initial_or_arbitrary_ceiling() -> None:
    p = canary(last_stable=values().replace("request_timeout_ms", 95_000))
    d = evaluate(p, (observation(p, mode="canary", safety_blocked=True),))
    assert d.proposed.request_timeout_ms == 95_000
    assert (
        d.proposed != p.initial
        and d.proposed.request_timeout_ms <= p.ceiling.request_timeout_ms
    )


@pytest.mark.parametrize(
    "drift",
    [
        {"model_version": "model.v2"},
        {"load_bucket": "busy"},
        {"values_used": values().replace("request_timeout_ms", 95_000)},
        {"observed_at": START - timedelta(seconds=1)},
        {"observation_key": "synthetic.canary.0"},
    ],
)
@pytest.mark.parametrize(
    "failure,reason",
    [
        ({"safety_blocked": True}, "absolute_blocker"),
        ({"scorer_blocked": True}, "absolute_blocker"),
        ({"quality_score": 0.5}, "quality_or_coverage_regression"),
        (
            {
                "completed": False,
                "termination": "timeout",
                "right_censored": True,
                "timeout_parameter": "request_timeout_ms",
            },
            "canary_false_timeout",
        ),
    ],
)
def test_mixed_population_cannot_mask_matching_canary_failure(
    drift: dict[str, object], failure: dict[str, object], reason: str
) -> None:
    p = canary()
    samples = (observation(p, mode="canary", **failure),) + (
        observation(p, 1, mode="canary", **drift),
    )
    d = calibrate(p, samples, policy(), now=NOW)
    assert d.action == "rollback" and d.reason == reason
    assert apply_decision(p, d, policy()).current == p.last_stable


@pytest.mark.parametrize(
    "drift",
    [
        {"model_version": "model.v2"},
        {"values_used": values().replace("request_timeout_ms", 95_000)},
        {"observed_at": START - timedelta(seconds=1)},
    ],
)
def test_unrelated_blocker_does_not_roll_back_this_profile(
    drift: dict[str, object],
) -> None:
    p = canary()
    d = calibrate(
        p,
        (observation(p, mode="canary", safety_blocked=True, **drift),),
        policy(),
        now=NOW,
    )
    assert d.action == "hold" and d.proposed is None
    assert apply_decision(p, d, policy()).profile_hash == p.profile_hash


@pytest.mark.parametrize("state", ["stable", "frozen", "blocked"])
@pytest.mark.parametrize(
    "updates", [{"untrusted_field": "must not disappear"}, {"started_at": True}]
)
def test_malformed_window_is_rejected_even_on_early_hold(
    state: str, updates: dict[str, object]
) -> None:
    p, pol = profile(state=state), policy()
    malformed = window(p, cohort(p), pol).model_copy(update=updates)
    with pytest.raises(ValueError):
        calibrate(p, (), pol, now=NOW, window=malformed)


def test_commit_decision_cannot_skip_active_cooldown() -> None:
    p, pol = canary(cooldown_until=NOW + timedelta(seconds=30)), policy()
    later = NOW + timedelta(minutes=3)
    valid = evaluate(p, paired(p, now=later), pol, now=later)
    assert valid.action == "commit"
    premature = changed(
        valid, evaluated_at=NOW, cooldown_until=NOW + timedelta(seconds=60)
    )
    with pytest.raises(ValueError):
        apply_decision(p, premature, pol)


def test_begin_canary_cannot_skip_active_cooldown() -> None:
    p, pol = profile(), policy()
    proposal = apply_decision(p, evaluate(p, cohort(p), pol), pol)
    cooling = changed(proposal, cooldown_until=NOW + timedelta(seconds=60))
    with pytest.raises(ValueError):
        begin_canary(cooling, started_at=NOW)


@pytest.mark.parametrize(
    "name,metrics",
    [
        ("connection_timeout_ms", {"actual_connection_ms": 5000}),
        ("first_token_timeout_ms", {"actual_first_token_ms": 7000}),
        ("stream_idle_timeout_ms", {"actual_stream_idle_ms": 8000}),
        ("request_timeout_ms", {"actual_request_ms": 50_000}),
        ("stage_deadline_ms", {"actual_stage_ms": 120_000}),
        ("parent_deadline_ms", {"actual_parent_ms": 200_000}),
        (
            "discussion_rounds",
            {
                "actual_discussion_rounds": 4,
                "discussion_tail_contributions": (0.0, 0.0),
            },
        ),
        (
            "revision_rounds",
            {"actual_revision_rounds": 4, "revision_tail_contributions": (0.0, 0.0)},
        ),
        (
            "investigation_rounds",
            {
                "actual_investigation_rounds": 4,
                "investigation_tail_contributions": (0.0, 0.0),
            },
        ),
    ],
)
def test_each_dimension_full_shadow_control_canary_cycle(
    name: str, metrics: dict[str, object]
) -> None:
    p, pol = profile(), policy()
    facts = {"actual_request_ms": None, **metrics}
    baseline = cohort(p, **facts) + (
        observation(p, 99, mode="shadow", observed_at=NOW, **facts),
    )
    proposal = evaluate(p, baseline, pol)
    assert proposal.action == "propose" and proposal.parameter == name
    experiment = begin_canary(apply_decision(p, proposal, pol), started_at=NOW)
    later = NOW + timedelta(minutes=3)
    samples = (
        cohort(experiment, mode="canary", now=later, **facts)
        + cohort(experiment, mode="control", now=later, **facts)
        + (observation(experiment, 99, mode="shadow", observed_at=later, **facts),)
    )
    commit = evaluate(experiment, samples, pol, now=later)
    assert commit.action == "commit" and commit.reason == "offline_canary_validated"
    stable = apply_decision(experiment, commit, pol)
    assert stable.current == stable.last_stable == experiment.current
    assert stable.version == 4 and p.version == 1
    assert [
        field
        for field in PARAMETER_NAMES
        if stable.current.value(field) != p.current.value(field)
    ] == [name]


@pytest.mark.parametrize("name", PARAMETER_NAMES[:6])
def test_all_timeout_layers_keep_absolute_ancestor_limit(name: str) -> None:
    snapshot = freeze_profile(
        profile(), bound_at=NOW, ancestor_deadline=NOW + timedelta(seconds=45)
    )
    before = snapshot.model_dump_json()
    assert snapshot.remaining_timeout_ms(name, now=NOW + timedelta(seconds=40)) == 5000
    assert snapshot.remaining_timeout_ms(name, now=NOW + timedelta(seconds=46)) == 0
    assert snapshot.model_dump_json() == before


def test_frozen_uses_last_stable_not_uncommitted_current_values() -> None:
    p = canary(state="frozen")
    snapshot = freeze_profile(p, bound_at=NOW)
    assert snapshot.values == p.last_stable and snapshot.values != p.current
    assert snapshot.profile_hash == p.profile_hash


def test_all_dimensions_at_floor_do_not_propose_smaller_values() -> None:
    p = profile(current=profile().floor, last_stable=profile().floor)
    samples = cohort(
        p,
        actual_connection_ms=1000,
        actual_first_token_ms=1000,
        actual_stream_idle_ms=1000,
        actual_request_ms=1000,
        actual_stage_ms=1000,
        actual_parent_ms=1000,
        actual_discussion_rounds=2,
        actual_revision_rounds=2,
        actual_investigation_rounds=2,
        discussion_tail_contributions=(0.0, 0.0),
        revision_tail_contributions=(0.0, 0.0),
        investigation_tail_contributions=(0.0, 0.0),
    )
    d = evaluate(p, samples)
    assert d.action == "hold" and d.reason == "no_safe_idle_margin"
