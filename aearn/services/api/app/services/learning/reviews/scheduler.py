"""Pure deterministic scheduling rules for track-scoped reviews."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.learning.contracts import MasteryEvidence, MasteryEvidenceKind, MasteryIndependence
from app.services.learning.reviews.contracts import (
    REVIEW_POLICY_VERSION,
    ReviewAggregate,
    ReviewCardState,
    ReviewRating,
    ReviewRiskLevel,
    ReviewScheduleDecision,
    ReviewScheduleSnapshot,
)


_MIN_STABILITY = 0.1
_MAX_STABILITY_DAYS = 3650.0


def seed_schedule_from_evidence(*, evidence: MasteryEvidence, now: datetime | None = None) -> ReviewScheduleSnapshot:
    """Create the first schedule from trusted non-review evidence."""

    current = _utc(now or evidence.created_at)
    if evidence.evidence_kind is MasteryEvidenceKind.REVIEW:
        raise ValueError("review evidence must be scheduled by session finalization")
    if evidence.evidence_kind is MasteryEvidenceKind.MODULE_DIAGNOSTIC:
        interval_days = 21.0
        state = ReviewCardState.REVIEW
        risk = ReviewRiskLevel.LOW
        difficulty = 4.0
    elif evidence.score < 0.6:
        interval_days = 10.0 / (24 * 60)
        state = ReviewCardState.RELEARNING
        risk = ReviewRiskLevel.HIGH
        difficulty = 7.0
    elif evidence.independence is MasteryIndependence.INDEPENDENT and evidence.score >= 0.9:
        interval_days = 7.0
        state = ReviewCardState.REVIEW
        risk = ReviewRiskLevel.LOW
        difficulty = 3.5
    elif evidence.independence is MasteryIndependence.INDEPENDENT:
        interval_days = 3.0
        state = ReviewCardState.REVIEW
        risk = ReviewRiskLevel.NORMAL
        difficulty = 4.5
    else:
        interval_days = 1.0
        state = ReviewCardState.LEARNING
        risk = ReviewRiskLevel.NORMAL
        difficulty = 6.0
    return ReviewScheduleSnapshot(
        knowledge_key=evidence.knowledge_key,
        card_state=state,
        stability=round(max(_MIN_STABILITY, interval_days), 4),
        difficulty=difficulty,
        due_at=current + timedelta(days=interval_days),
        risk_level=risk,
        scheduler_version=REVIEW_POLICY_VERSION,
    )


def rate_review(aggregate: ReviewAggregate) -> tuple[ReviewRating, tuple[str, ...]]:
    reasons: list[str] = []
    if aggregate.critical_failure:
        reasons.append("critical_capability_failed")
        return ReviewRating.AGAIN, tuple(reasons)
    if not aggregate.all_passed:
        reasons.append("attempt_failed")
        return ReviewRating.AGAIN, tuple(reasons)
    if aggregate.independence is not MasteryIndependence.INDEPENDENT:
        reasons.append("assistance_used")
        return ReviewRating.HARD, tuple(reasons)
    if aggregate.average_score >= 0.95:
        reasons.append("independent_high_confidence")
        return ReviewRating.EASY, tuple(reasons)
    if aggregate.average_score >= 0.75:
        reasons.append("independent_pass")
        return ReviewRating.GOOD, tuple(reasons)
    reasons.append("independent_fragile_pass")
    return ReviewRating.HARD, tuple(reasons)


def advance_schedule(
    *,
    previous: ReviewScheduleSnapshot,
    aggregate: ReviewAggregate,
    now: datetime,
    prerequisite_for_current: bool,
) -> ReviewScheduleDecision:
    current = _utc(now)
    rating, reasons = rate_review(aggregate)
    difficulty = previous.difficulty
    lapse_count = previous.lapse_count
    if rating is ReviewRating.AGAIN:
        interval_days = 10.0 / (24 * 60)
        stability = max(_MIN_STABILITY, previous.stability * 0.35)
        difficulty = min(10.0, difficulty + (1.4 if aggregate.critical_failure else 1.0))
        lapse_count += 1
        state = ReviewCardState.RELEARNING
        risk = ReviewRiskLevel.CRITICAL if aggregate.critical_failure or lapse_count >= 2 else ReviewRiskLevel.HIGH
    elif rating is ReviewRating.HARD:
        interval_days = max(1.0, previous.stability * 0.8)
        stability = max(1.0, interval_days)
        difficulty = min(10.0, difficulty + 0.3)
        state = ReviewCardState.LEARNING
        risk = ReviewRiskLevel.HIGH if previous.risk_level is ReviewRiskLevel.CRITICAL else ReviewRiskLevel.NORMAL
    elif rating is ReviewRating.GOOD:
        interval_days = max(3.0, previous.stability * 1.7)
        stability = interval_days
        difficulty = max(1.0, difficulty - 0.25)
        state = ReviewCardState.REVIEW
        risk = ReviewRiskLevel.NORMAL
    else:
        interval_days = max(7.0, previous.stability * 2.5)
        stability = interval_days
        difficulty = max(1.0, difficulty - 0.6)
        state = ReviewCardState.REVIEW
        risk = ReviewRiskLevel.LOW
    interval_days = min(_MAX_STABILITY_DAYS, interval_days)
    stability = round(min(_MAX_STABILITY_DAYS, stability), 4)
    critical_gate = prerequisite_for_current and risk is ReviewRiskLevel.CRITICAL
    if critical_gate:
        reasons = (*reasons, "critical_prerequisite_gate")
    return ReviewScheduleDecision(
        rating=rating,
        next_schedule=ReviewScheduleSnapshot(
            knowledge_key=previous.knowledge_key,
            card_state=state,
            stability=stability,
            difficulty=round(difficulty, 4),
            due_at=current + timedelta(days=interval_days),
            review_count=previous.review_count + 1,
            lapse_count=lapse_count,
            last_rating=rating,
            risk_level=risk,
            scheduler_version=REVIEW_POLICY_VERSION,
        ),
        reason_codes=tuple(reasons),
        critical_prerequisite_gate=critical_gate,
    )


def current_risk(*, schedule: ReviewScheduleSnapshot, now: datetime) -> ReviewRiskLevel:
    """Escalate overdue schedules without mutating persisted state."""

    if schedule.card_state is ReviewCardState.SUSPENDED:
        return ReviewRiskLevel.LOW
    overdue = _utc(now) - _utc(schedule.due_at)
    if overdue <= timedelta(0):
        return schedule.risk_level
    if schedule.lapse_count >= 2 and overdue >= timedelta(days=1):
        return ReviewRiskLevel.CRITICAL
    if overdue >= timedelta(days=max(2.0, schedule.stability * 0.75)):
        return ReviewRiskLevel.HIGH
    return max(schedule.risk_level, ReviewRiskLevel.NORMAL, key=_risk_rank)


def _risk_rank(value: ReviewRiskLevel) -> int:
    return {
        ReviewRiskLevel.LOW: 0,
        ReviewRiskLevel.NORMAL: 1,
        ReviewRiskLevel.HIGH: 2,
        ReviewRiskLevel.CRITICAL: 3,
    }[value]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
