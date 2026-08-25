from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.learning.contracts import (
    MasteryEvidence,
    MasteryEvidenceKind,
    MasteryIndependence,
)
from app.services.learning.practice.contracts import ExerciseAttemptOutcome
from app.services.learning.reviews.contracts import (
    ReviewAggregate,
    ReviewAttemptSummary,
    ReviewCardState,
    ReviewRating,
    ReviewRiskLevel,
    ReviewScheduleSnapshot,
)
from app.services.learning.reviews.scheduler import advance_schedule, current_risk, seed_schedule_from_evidence


def _attempt(*, score: float, independence: MasteryIndependence, passed: bool = True, critical: float = 1.0) -> ReviewAttemptSummary:
    return ReviewAttemptSummary(
        outcome=ExerciseAttemptOutcome.PASSED if passed else ExerciseAttemptOutcome.FAILED,
        score=score,
        independence=independence,
        capability_scores={"python": score, "python.variables": critical},
    )


def _schedule(now: datetime) -> ReviewScheduleSnapshot:
    return ReviewScheduleSnapshot(
        knowledge_key="python.variables",
        card_state=ReviewCardState.REVIEW,
        stability=4.0,
        difficulty=5.0,
        due_at=now,
    )


def test_review_rating_orders_failure_hinted_independent_and_high_confidence() -> None:
    now = datetime(2026, 8, 12, tzinfo=UTC)
    previous = _schedule(now)
    cases = [
        (_attempt(score=0.2, independence=MasteryIndependence.INDEPENDENT, passed=False), ReviewRating.AGAIN),
        (_attempt(score=0.9, independence=MasteryIndependence.HINTED), ReviewRating.HARD),
        (_attempt(score=0.85, independence=MasteryIndependence.INDEPENDENT), ReviewRating.GOOD),
        (_attempt(score=0.98, independence=MasteryIndependence.INDEPENDENT), ReviewRating.EASY),
    ]
    decisions = [
        advance_schedule(
            previous=previous,
            aggregate=ReviewAggregate(attempts=(attempt,)),
            now=now,
            prerequisite_for_current=False,
        )
        for attempt, _expected in cases
    ]
    assert [item.rating for item in decisions] == [expected for _attempt_value, expected in cases]
    assert [item.next_schedule.due_at for item in decisions] == sorted(item.next_schedule.due_at for item in decisions)


def test_schedule_properties_hold_across_supported_state_ranges() -> None:
    now = datetime(2026, 8, 12, tzinfo=UTC)
    for stability in (0.1, 1.0, 4.0, 30.0, 3650.0):
        for difficulty in (1.0, 5.0, 10.0):
            previous = ReviewScheduleSnapshot(
                knowledge_key="python.variables",
                card_state=ReviewCardState.REVIEW,
                stability=stability,
                difficulty=difficulty,
                due_at=now,
            )
            decisions = tuple(
                advance_schedule(
                    previous=previous,
                    aggregate=ReviewAggregate(attempts=(attempt,)),
                    now=now,
                    prerequisite_for_current=False,
                )
                for attempt in (
                    _attempt(
                        score=0.2,
                        independence=MasteryIndependence.INDEPENDENT,
                        passed=False,
                    ),
                    _attempt(score=0.9, independence=MasteryIndependence.HINTED),
                    _attempt(score=0.85, independence=MasteryIndependence.INDEPENDENT),
                    _attempt(score=0.98, independence=MasteryIndependence.INDEPENDENT),
                )
            )
            due_dates = [decision.next_schedule.due_at for decision in decisions]
            assert due_dates == sorted(due_dates)
            for decision in decisions:
                assert now < decision.next_schedule.due_at <= now + timedelta(days=3650)
                assert 0.1 <= decision.next_schedule.stability <= 3650
                assert 1 <= decision.next_schedule.difficulty <= 10
                assert decision.next_schedule.review_count == previous.review_count + 1


def test_critical_capability_failure_projects_short_gate_only_for_prerequisite() -> None:
    now = datetime(2026, 8, 12, tzinfo=UTC)
    aggregate = ReviewAggregate(
        attempts=(_attempt(score=0.9, independence=MasteryIndependence.INDEPENDENT, critical=0.2),),
        critical_capabilities=("python.variables",),
    )
    gated = advance_schedule(previous=_schedule(now), aggregate=aggregate, now=now, prerequisite_for_current=True)
    ordinary = advance_schedule(previous=_schedule(now), aggregate=aggregate, now=now, prerequisite_for_current=False)
    assert gated.rating is ReviewRating.AGAIN
    assert gated.next_schedule.risk_level is ReviewRiskLevel.CRITICAL
    assert gated.critical_prerequisite_gate is True
    assert ordinary.critical_prerequisite_gate is False


def test_diagnostic_skip_seeds_low_frequency_review() -> None:
    now = datetime(2026, 8, 12, tzinfo=UTC)
    evidence = MasteryEvidence(
        evidence_id="evidence-1",
        knowledge_key="python.variables",
        evidence_kind=MasteryEvidenceKind.MODULE_DIAGNOSTIC,
        source_receipt_id="diagnostic-1",
        source_receipt_hash="a" * 64,
        independence=MasteryIndependence.INDEPENDENT,
        score=1.0,
        hint_count=0,
        attempt_count=1,
        summary={"kind": "diagnostic_skipped_module"},
        created_at=now,
    )
    schedule = seed_schedule_from_evidence(evidence=evidence, now=now)
    assert schedule.due_at == now + timedelta(days=21)
    assert schedule.risk_level is ReviewRiskLevel.LOW


def test_overdue_repeated_lapse_escalates_to_critical() -> None:
    now = datetime(2026, 8, 12, tzinfo=UTC)
    schedule = ReviewScheduleSnapshot(
        knowledge_key="python.variables",
        card_state=ReviewCardState.RELEARNING,
        stability=1.0,
        difficulty=8.0,
        due_at=now - timedelta(days=2),
        review_count=3,
        lapse_count=2,
        risk_level=ReviewRiskLevel.HIGH,
    )
    assert current_risk(schedule=schedule, now=now) is ReviewRiskLevel.CRITICAL


def test_review_evidence_cannot_use_seed_path() -> None:
    now = datetime(2026, 8, 12, tzinfo=UTC)
    evidence = MasteryEvidence(
        evidence_id="evidence-1",
        knowledge_key="python.variables",
        evidence_kind=MasteryEvidenceKind.REVIEW,
        source_receipt_id="review-1",
        source_receipt_hash="b" * 64,
        independence=MasteryIndependence.INDEPENDENT,
        score=1.0,
        hint_count=0,
        attempt_count=1,
        summary={},
        created_at=now,
    )
    with pytest.raises(ValueError, match="session finalization"):
        seed_schedule_from_evidence(evidence=evidence)
