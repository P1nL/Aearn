"""Typed contracts for track-scoped spaced review."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Mapping, Sequence

from app.services.learning.contracts import MasteryIndependence, stable_key
from app.services.learning.practice.contracts import ExerciseAttemptOutcome


REVIEW_POLICY_VERSION = "track_review_fsrs_v1"
REVIEW_CONTEXT_SCHEMA_VERSION = "review_authoritative_context_v1"


class ReviewCardState(StrEnum):
    NEW = "new"
    LEARNING = "learning"
    REVIEW = "review"
    RELEARNING = "relearning"
    SUSPENDED = "suspended"


class ReviewRiskLevel(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class ReviewRating(StrEnum):
    AGAIN = "again"
    HARD = "hard"
    GOOD = "good"
    EASY = "easy"


class ReviewSessionState(StrEnum):
    BLOCKED = "blocked"
    ACTIVE = "active"
    READY_TO_FINALIZE = "ready_to_finalize"
    FINALIZED = "finalized"
    CANCELLED = "cancelled"


class ReviewSessionStage(StrEnum):
    WARMUP = "warmup"
    PRACTICE = "practice"
    FINAL_SUMMARY = "final_summary"


class ReviewItemState(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class ReviewScheduleSnapshot:
    knowledge_key: str
    card_state: ReviewCardState
    stability: float
    difficulty: float
    due_at: datetime
    review_count: int = 0
    lapse_count: int = 0
    last_rating: ReviewRating | None = None
    risk_level: ReviewRiskLevel = ReviewRiskLevel.NORMAL
    scheduler_version: str = REVIEW_POLICY_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "knowledge_key", stable_key(self.knowledge_key, label="knowledge_key"))
        if self.stability < 0.1:
            raise ValueError("review stability must be at least 0.1")
        if not 1 <= self.difficulty <= 10:
            raise ValueError("review difficulty must be within 1..10")
        if self.review_count < 0 or self.lapse_count < 0:
            raise ValueError("review counts must be non-negative")
        stable_key(self.scheduler_version, label="scheduler_version")


@dataclass(frozen=True, slots=True)
class ReviewAttemptSummary:
    outcome: ExerciseAttemptOutcome
    score: float
    independence: MasteryIndependence
    capability_scores: Mapping[str, float]

    def __post_init__(self) -> None:
        if not 0 <= self.score <= 1:
            raise ValueError("review score must be within 0..1")
        for key, value in self.capability_scores.items():
            stable_key(key, label="capability score key")
            if not 0 <= value <= 1:
                raise ValueError("review capability score must be within 0..1")


@dataclass(frozen=True, slots=True)
class ReviewAggregate:
    attempts: tuple[ReviewAttemptSummary, ...]
    critical_capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.attempts:
            raise ValueError("review aggregate requires terminal attempts")
        object.__setattr__(
            self,
            "critical_capabilities",
            tuple(stable_key(item, label="critical capability") for item in self.critical_capabilities),
        )

    @property
    def average_score(self) -> float:
        return round(sum(item.score for item in self.attempts) / len(self.attempts), 4)

    @property
    def hint_count(self) -> int:
        return sum(item.independence is not MasteryIndependence.INDEPENDENT for item in self.attempts)

    @property
    def all_passed(self) -> bool:
        return all(item.outcome is ExerciseAttemptOutcome.PASSED for item in self.attempts)

    @property
    def critical_failure(self) -> bool:
        return any(
            item.capability_scores.get(capability, 0.0) < 0.6
            for item in self.attempts
            for capability in self.critical_capabilities
        )

    @property
    def independence(self) -> MasteryIndependence:
        values = {item.independence for item in self.attempts}
        if MasteryIndependence.REMEDIATED in values:
            return MasteryIndependence.REMEDIATED
        if MasteryIndependence.HINTED in values:
            return MasteryIndependence.HINTED
        return MasteryIndependence.INDEPENDENT


@dataclass(frozen=True, slots=True)
class ReviewScheduleDecision:
    rating: ReviewRating
    next_schedule: ReviewScheduleSnapshot
    reason_codes: tuple[str, ...]
    critical_prerequisite_gate: bool


@dataclass(frozen=True, slots=True)
class ReviewCandidate:
    exercise_version_id: str
    exercise_type: str
    title: str
    learner_prompt: Mapping[str, object]
    starter_artifact: Mapping[str, object]
    required_capabilities: tuple[str, ...]
    runtime_profile_key: str | None
    execution_required: bool
    content_hash: str


@dataclass(frozen=True, slots=True)
class ReviewBatch:
    knowledge_key: str
    candidates: Sequence[ReviewCandidate]
