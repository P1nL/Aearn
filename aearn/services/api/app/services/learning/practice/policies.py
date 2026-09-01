"""Versioned deterministic Gate, hint, and diagnostic policies."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Mapping, Sequence

from aearn_shared.execution import (
    SafeExecutionResultV1,
    SafeExecutionResultV2,
    SafeExecutionStatus,
    parse_safe_execution_result,
)

from app.services.learning.contracts import MasteryIndependence
from app.services.learning.practice.contracts import (
    ExerciseAttemptOutcome,
    ExerciseAttemptResult,
    ModuleDiagnosticVersion,
    capability_score_summary,
)


GATE_PASS_POLICY_VERSION = "lesson_gate_pass_v1"
DIAGNOSTIC_POLICY_VERSION = "module_diagnostic_v1"
HINT_POLICY_VERSION = "lesson_gate_hint_v1"
DEFAULT_GATE_THRESHOLD = 0.8
DEFAULT_DIAGNOSTIC_THRESHOLD = 0.8
DEFAULT_DIAGNOSTIC_COOLDOWN_SECONDS = 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class DiagnosticDecision:
    passed: bool
    capability_scores: Mapping[str, float]
    weak_capabilities: tuple[str, ...]


def score_execution_result(
    result: SafeExecutionResultV1 | SafeExecutionResultV2,
    *,
    required_capabilities: Sequence[str],
    threshold: float = DEFAULT_GATE_THRESHOLD,
) -> ExerciseAttemptResult:
    result = parse_safe_execution_result(result)
    total = result.total_test_count
    score = result.passed_test_count / total if total > 0 else float(result.status is SafeExecutionStatus.SUCCESS)
    passed = result.status is SafeExecutionStatus.SUCCESS and score >= threshold
    outcome = {
        SafeExecutionStatus.TIMEOUT: ExerciseAttemptOutcome.TIMED_OUT,
        SafeExecutionStatus.CANCELLED: ExerciseAttemptOutcome.CANCELLED,
        SafeExecutionStatus.UNAVAILABLE: ExerciseAttemptOutcome.UNAVAILABLE,
    }.get(result.status, ExerciseAttemptOutcome.PASSED if passed else ExerciseAttemptOutcome.FAILED)
    safe_feedback = result.model_dump(mode="json")
    return ExerciseAttemptResult(
        outcome=outcome,
        score=round(score, 4),
        safe_feedback=safe_feedback,
        capability_scores={str(item): round(score, 4) for item in required_capabilities},
        policy_version=GATE_PASS_POLICY_VERSION,
        terminal_at=datetime.now(UTC),
    )


def evaluate_static_reasoning(
    *,
    answer: str,
    accepted_answers: Sequence[str],
    required_capabilities: Sequence[str],
    now,
    threshold: float = DEFAULT_GATE_THRESHOLD,
) -> ExerciseAttemptResult:
    normalized = " ".join(answer.strip().casefold().split())
    accepted = {" ".join(item.strip().casefold().split()) for item in accepted_answers}
    score = 1.0 if normalized and normalized in accepted else 0.0
    passed = score >= threshold
    return ExerciseAttemptResult(
        outcome=ExerciseAttemptOutcome.PASSED if passed else ExerciseAttemptOutcome.FAILED,
        score=score,
        safe_feedback={
            "status": "static_evaluated",
            "message": "回答符合要求。" if passed else "回答尚未满足当前检查要求。",
            "execution_claim": "not_run",
        },
        capability_scores={str(item): score for item in required_capabilities},
        policy_version=GATE_PASS_POLICY_VERSION,
        terminal_at=now,
    )


def diagnostic_decision(
    *,
    version: ModuleDiagnosticVersion,
    results: Sequence[ExerciseAttemptResult],
    independence: Sequence[MasteryIndependence],
) -> DiagnosticDecision:
    scores = capability_score_summary(results)
    weak = tuple(
        capability
        for capability in version.core_capabilities
        if scores.get(capability, 0.0) < version.pass_threshold
    )
    independent = all(item is MasteryIndependence.INDEPENDENT for item in independence)
    complete = len(results) == len(version.items)
    passed = complete and not weak and (independent or not version.independent_only)
    return DiagnosticDecision(passed=passed, capability_scores=scores, weak_capabilities=weak)
