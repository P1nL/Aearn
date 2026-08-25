from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.agents.harness.context_builder import TutorContextBuilder
from app.agents.harness.contracts import TutorContextSection
from app.services.tutor.interactive import PostgresTutorContextLoader
from app.services.tutor.learner_state import TutorLearnerStateRepository

from app.services.tutor.context_evals import (
    TutorContextEvalFixtureError,
    build_tutor_context_calibration_report,
    load_tutor_context_eval_cases,
    run_tutor_context_eval_case,
    run_tutor_context_eval_fixture,
)

from app.services.tutor.evals import (
    TutorEvalFixtureError,
    load_tutor_eval_cases,
    run_tutor_eval_case,
    run_tutor_eval_fixture,
)


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "tutor_evals" / "tutor_harness_foundation_v1.json"
CONTEXT_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "tutor_evals" / "tutor_context_governance_v2.json"


def test_fake_only_tutor_eval_fixture_covers_pinned_catalog_and_required_scenarios() -> None:
    results = run_tutor_eval_fixture(FIXTURE)

    assert results
    assert all(result.passed for result in results)
    assert {result.case_id for result in results} == {
        "catalog-identity-pinned",
        "policy-denial-no-capability",
        "strict-provider-envelope-rejected",
        "bounded-loop-exits-before-provider",
        "revision-race-stale-effect",
        "primary-only-model-unavailable",
        "protected-values-never-exported",
        "replay-outbox-proposal-terminal-unique",
        "current-input-pinned",
        "newest-history-selected",
        "teaching-correction-policy-present",
        "current-input-unrepresentable-provider-not-called",
    }


def test_eval_runner_rejects_unknown_fixture_version_and_mutable_catalog_alias(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"schema_version":"unknown","cases":[]}', encoding="utf-8")

    with pytest.raises(TutorEvalFixtureError, match="schema version"):
        load_tutor_eval_cases(invalid)

    case = load_tutor_eval_cases(FIXTURE)[0]
    mutable_catalog = dict(case.catalog) | {"skill_version": "current"}
    with pytest.raises(TutorEvalFixtureError, match="catalog identity"):
        run_tutor_eval_case(replace(case, catalog=mutable_catalog))


def test_context_governance_v2_fixture_covers_required_cross_contract_cases() -> None:
    results = run_tutor_context_eval_fixture(CONTEXT_FIXTURE)

    assert results
    assert all(result.passed for result in results)
    assert {result.case_id for result in results} >= {
        "current_input_pinned",
        "newest_history_selected",
        "current_input_not_duplicated",
        "optional_context_evicted_first",
        "required_input_unrepresentable_provider_not_called",
        "usage_cached_tokens_not_double_counted",
        "repair_attempts_accounted_separately",
        "compact_turn_uses_small_budget",
        "normal_turn_uses_normal_budget",
        "complex_turn_expands_budget",
        "physical_hard_limit_never_exceeded",
        "summary_covers_retired_messages_once",
        "summary_does_not_override_correction",
        "stale_summary_excluded",
        "confirmed_planning_fact_survives_long_history",
    }
    assert {
        result.receipt.budget_mode
        for result in results
        if result.receipt.budget_mode is not None
    } >= {"compact", "normal", "complex", "extended"}
    for result in results:
        receipt = result.receipt
        if receipt.estimated_total_input_tokens is not None:
            assert receipt.physical_input_limit is not None
            assert receipt.estimated_total_input_tokens <= receipt.physical_input_limit


def test_context_eval_receipts_are_safe_and_keep_attempt_usage_separate() -> None:
    cases = {case.case_id: case for case in load_tutor_context_eval_cases(CONTEXT_FIXTURE)}
    repair = run_tutor_context_eval_case(cases["repair_attempts_accounted_separately"]).receipt
    cached = run_tutor_context_eval_case(cases["usage_cached_tokens_not_double_counted"]).receipt
    serialized = str(repair.as_dict()) + str(cached.as_dict())

    assert repair.provider_call_count == 2
    assert repair.decision_count == 1
    assert [attempt.attempt_index for attempt in repair.attempts] == [1, 2]
    assert cached.actual_input_tokens == 175_420
    assert cached.cached_input_tokens == 170_368
    assert cached.uncached_input_tokens == 5_052
    assert cached.actual_input_tokens + cached.cached_input_tokens != cached.reported_total_tokens
    for forbidden in ("RAW_PROMPT_MARKER", "provider body", "reasoning", "credential", "api_key"):
        assert forbidden not in serialized


def test_context_eval_fixture_rejects_unknown_version_and_invalid_usage(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid-context-eval.json"
    invalid.write_text('{"schema_version":"unknown","cases":[]}', encoding="utf-8")

    with pytest.raises(TutorContextEvalFixtureError, match="schema version"):
        load_tutor_context_eval_cases(invalid)

    cases = {case.case_id: case for case in load_tutor_context_eval_cases(CONTEXT_FIXTURE)}
    invalid_attempt = dict(cases["usage_cached_tokens_not_double_counted"].provider_attempts[0])
    invalid_attempt["usage"] = {"input_tokens": 10, "cached_input_tokens": 11}
    with pytest.raises(ValueError, match="must not exceed"):
        run_tutor_context_eval_case(
            replace(
                cases["usage_cached_tokens_not_double_counted"],
                provider_attempts=(invalid_attempt,),
            )
        )


def test_calibration_report_groups_versioned_safe_metrics_and_applies_sample_threshold() -> None:
    cases = {case.case_id: case for case in load_tutor_context_eval_cases(CONTEXT_FIXTURE)}
    base = run_tutor_context_eval_case(cases["usage_cached_tokens_not_double_counted"]).receipt
    samples = tuple(
        replace(
            base,
            case_id=f"calibration-{index}",
            budget_mode="normal",
            estimated_total_input_tokens=100 + index,
            actual_input_tokens=101 + index,
            cached_input_tokens=50,
            uncached_input_tokens=51 + index,
            output_tokens=10 + index,
            reported_total_tokens=111 + (index * 2),
            calculated_total_tokens=111 + (index * 2),
            first_token_latency_ms=20 + index,
        )
        for index in range(5)
    )

    report = build_tutor_context_calibration_report(samples)
    document = report.as_dict()

    assert report.recommendation == "retain_versioned_config_pending_real_provider_evidence"
    assert len(report.groups) == 1
    assert report.groups[0].sample_count == 5
    assert report.groups[0].p50_actual_input_tokens == 103
    assert report.groups[0].p95_actual_input_tokens == 105
    assert set(document) == {"schema_version", "percentile_min_samples", "recommendation", "groups"}
    assert "prompt" not in str(document).lower()


class _OneTokenEstimator:
    def estimate_tokens(self, value: object) -> int:
        del value
        return 1


def test_context_eval_postgres_fixture_pins_current_and_orders_equal_timestamp_history(
    tutor_persistence,
) -> None:
    fixture = tutor_persistence
    created_at = datetime(2026, 8, 8, 9, 0, tzinfo=UTC)
    message_rows = (
        ("00000000-0000-0000-0000-000000000003", "learner", "third"),
        ("00000000-0000-0000-0000-000000000001", "learner", "first"),
        ("00000000-0000-0000-0000-000000000002", "tutor", "second"),
    )
    for message_id, role, content in message_rows:
        fixture.connection.execute(
            """
            INSERT INTO tutor_messages (id, conversation_id, role, content, created_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (message_id, fixture.conversation_id, role, content, created_at),
        )
    accepted = fixture.repository.accept_input(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        idempotency_key="context-eval-current",
        content="authoritative current input",
        received_at=datetime(2026, 8, 8, 9, 1, tzinfo=UTC),
    )
    snapshot = fixture.repository.load_snapshot(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
    )
    assert snapshot is not None
    loaded = PostgresTutorContextLoader(
        conn=fixture.connection,
        learner_state=TutorLearnerStateRepository(fixture.connection),
        now_provider=lambda: datetime(2026, 8, 8, 10, 0, tzinfo=UTC),
    ).load_context(snapshot, input_revision=accepted.input_revision)
    selection = TutorContextBuilder(estimator=_OneTokenEstimator()).build(
        loaded,
        token_budget=64,
    )

    assert selection.current_input is not None
    assert selection.current_input.source_id == f"message:{accepted.message_id}"
    assert selection.current_input.source_id not in {item.source_id for item in selection.items}
    assert [
        item.source_id
        for item in selection.items
        if item.section is TutorContextSection.RECENT_MESSAGES
    ] == [
        "message:00000000-0000-0000-0000-000000000001",
        "message:00000000-0000-0000-0000-000000000002",
        "message:00000000-0000-0000-0000-000000000003",
    ]
