"""Deterministic finding matching and scoring for model code-review exercises."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from datetime import datetime
from typing import Literal

from app.services.learning.practice.contracts import (
    ExerciseAttemptOutcome,
    ExerciseAttemptResult,
)
from app.services.learning.practice.model_review_contracts import (
    MODEL_REVIEW_SCORE_POLICY_VERSION,
    ModelCodeReviewSubmissionV1,
    ModelReviewAssistanceKind,
    ModelReviewExpectedFindingV1,
    ModelReviewFindingFeedbackV1,
    ModelReviewFindingStatus,
    ModelReviewRubricV1,
    ModelReviewSafeFeedbackV1,
    ModelReviewScoreBreakdownV1,
    ModelReviewSeverity,
)


_SEVERITY = {
    ModelReviewSeverity.INFO: 0,
    ModelReviewSeverity.LOW: 1,
    ModelReviewSeverity.MEDIUM: 2,
    ModelReviewSeverity.HIGH: 3,
    ModelReviewSeverity.CRITICAL: 4,
}
_WEIGHTS = {
    "verdict": 0.16,
    "discovery": 0.22,
    "omission": 0.12,
    "severity": 0.08,
    "evidence": 0.12,
    "validation_method": 0.08,
    "suggested_fix": 0.08,
    "false_positive": 0.10,
    "duplicate": 0.04,
}


@dataclass(frozen=True, slots=True)
class _Edge:
    user_index: int
    expected_index: int
    score: int
    token_matches: int
    severity_distance: int


def evaluate_model_code_review(
    *,
    submission: ModelCodeReviewSubmissionV1,
    rubric: ModelReviewRubricV1,
    line_count: int,
    required_capabilities: tuple[str, ...],
    assistance_kind: ModelReviewAssistanceKind,
    threshold: float,
    now: datetime,
) -> ExerciseAttemptResult:
    submission.validate_line_count(line_count)
    matched, duplicate_indexes = _match_findings(submission=submission, rubric=rubric)
    matched_expected = {expected_index for expected_index in matched.values()}
    expected_total = len(rubric.expected_findings)
    supported_count = 0
    partial_count = 0
    unsupported_count = 0
    feedback: list[ModelReviewFindingFeedbackV1] = []
    evidence_scores: list[float] = []
    validation_scores: list[float] = []
    fix_scores: list[float] = []
    severity_scores: list[float] = []

    for index, finding in enumerate(submission.findings):
        if index in duplicate_indexes:
            feedback.append(
                ModelReviewFindingFeedbackV1(
                    client_finding_id=finding.client_finding_id,
                    status=ModelReviewFindingStatus.DUPLICATE,
                    safe_reason_code="duplicate_finding",
                )
            )
            continue
        expected_index = matched.get(index)
        if expected_index is None:
            unsupported_count += 1
            feedback.append(
                ModelReviewFindingFeedbackV1(
                    client_finding_id=finding.client_finding_id,
                    status=ModelReviewFindingStatus.UNSUPPORTED,
                    safe_reason_code="finding_not_supported",
                )
            )
            continue
        expected = rubric.expected_findings[expected_index]
        token_matches = len(finding.evidence_tokens.intersection(expected.matcher_tokens))
        evidence = min(1.0, token_matches / max(expected.minimum_token_matches + 1, 2))
        validation = _text_quality(finding.validation_method, markers=("test", "input", "assert", "reproduce", "测试", "输入", "复现", "断言"))
        fix = _text_quality(finding.suggested_fix, markers=("change", "return", "guard", "validate", "修改", "返回", "校验", "边界"))
        severity = max(0.0, 1.0 - 0.25 * abs(_SEVERITY[finding.severity] - _SEVERITY[expected.severity]))
        evidence_scores.append(evidence)
        validation_scores.append(validation)
        fix_scores.append(fix)
        severity_scores.append(severity)
        if evidence >= 0.5 and validation >= 0.5:
            supported_count += 1
            status = ModelReviewFindingStatus.SUPPORTED
            reason = "finding_supported"
        else:
            partial_count += 1
            status = ModelReviewFindingStatus.PARTIAL
            reason = "finding_evidence_partial"
        feedback.append(
            ModelReviewFindingFeedbackV1(
                client_finding_id=finding.client_finding_id,
                status=status,
                safe_reason_code=reason,
            )
        )

    verdict_score = 1.0 if submission.verdict is rubric.expected_verdict else 0.0
    discovery = 1.0 if expected_total == 0 else len(matched_expected) / expected_total
    omission = 1.0 if expected_total == 0 else 1.0 - ((expected_total - len(matched_expected)) / expected_total)
    severity = _average(severity_scores, fallback=1.0 if expected_total == 0 else 0.0)
    evidence = _average(evidence_scores, fallback=1.0 if not submission.findings else 0.0)
    validation = _average(validation_scores, fallback=1.0 if not submission.findings else 0.0)
    suggested_fix = _average(fix_scores, fallback=1.0 if not submission.findings else 0.0)
    false_positive = max(0.0, 1.0 - unsupported_count / max(1, len(submission.findings)))
    duplicate = max(0.0, 1.0 - len(duplicate_indexes) / max(1, len(submission.findings)))
    breakdown = ModelReviewScoreBreakdownV1(
        verdict=round(verdict_score, 4),
        discovery=round(discovery, 4),
        omission=round(omission, 4),
        severity=round(severity, 4),
        evidence=round(evidence, 4),
        validation_method=round(validation, 4),
        suggested_fix=round(suggested_fix, 4),
        false_positive=round(false_positive, 4),
        duplicate=round(duplicate, 4),
    )
    score = round(sum(getattr(breakdown, key) * weight for key, weight in _WEIGHTS.items()), 4)
    # A wrong verdict or unsupported correctness accusation is a hard learning boundary.
    if verdict_score == 0:
        score = min(score, 0.49)
    if unsupported_count and rubric.expected_verdict.value in {"no_correctness_issue", "improvement_only"}:
        score = min(score, 0.59)
    passed = score >= threshold
    omitted = expected_total - len(matched_expected)
    omission_band: Literal["none", "limited", "major"] = (
        "none" if omitted == 0 else "limited" if omitted == 1 else "major"
    )
    if passed:
        message = "审核结论和证据满足当前评分要求。"
        next_action: Literal["advance_next", "review_variant", "show_hint"] = "advance_next"
    elif evidence < 0.5 or validation < 0.5:
        message = "结论仍需补充更具体的触发条件和验证方法。"
        next_action = "show_hint"
    else:
        message = "本次审核仍有遗漏或误报，请换一个变体继续练习。"
        next_action = "review_variant"
    safe = ModelReviewSafeFeedbackV1(
        message=message,
        assistance_kind=assistance_kind,
        score_breakdown=breakdown,
        finding_feedback=tuple(feedback),
        omission_band=omission_band,
        next_action=next_action,
    )
    return ExerciseAttemptResult(
        outcome=ExerciseAttemptOutcome.PASSED if passed else ExerciseAttemptOutcome.FAILED,
        score=score,
        safe_feedback=safe.model_dump(mode="json"),
        capability_scores={capability: score for capability in required_capabilities},
        policy_version=MODEL_REVIEW_SCORE_POLICY_VERSION,
        terminal_at=now,
    )


def _match_findings(
    *,
    submission: ModelCodeReviewSubmissionV1,
    rubric: ModelReviewRubricV1,
) -> tuple[dict[int, int], set[int]]:
    edges: list[_Edge] = []
    duplicates: set[int] = set()
    fingerprints: dict[tuple[object, ...], int] = {}
    for user_index, finding in enumerate(submission.findings):
        fingerprint = (
            finding.finding_kind.value,
            finding.category,
            finding.start_line,
            finding.end_line,
            tuple(sorted(finding.evidence_tokens)),
        )
        if fingerprint in fingerprints:
            duplicates.add(user_index)
            continue
        fingerprints[fingerprint] = user_index
        for expected_index, expected in enumerate(rubric.expected_findings):
            edge = _candidate_edge(user_index=user_index, finding=finding, expected_index=expected_index, expected=expected)
            if edge is not None:
                edges.append(edge)
    edges_by_user: dict[int, tuple[_Edge, ...]] = {}
    for user_index in range(len(submission.findings)):
        edges_by_user[user_index] = tuple(
            sorted(
                (edge for edge in edges if edge.user_index == user_index),
                key=lambda edge: (-edge.score, -edge.token_matches, edge.severity_distance, edge.expected_index),
            )
        )

    @lru_cache(maxsize=None)
    def choose(user_index: int, used_expected_mask: int) -> tuple[int, int, int, int, tuple[int, ...]]:
        if user_index >= len(submission.findings):
            return (0, 0, 0, 0, ())
        skipped = choose(user_index + 1, used_expected_mask)
        best = (skipped[0], skipped[1], skipped[2], skipped[3], (-1, *skipped[4]))
        if user_index in duplicates:
            return best
        for edge in edges_by_user[user_index]:
            bit = 1 << edge.expected_index
            if used_expected_mask & bit:
                continue
            tail = choose(user_index + 1, used_expected_mask | bit)
            candidate = (
                edge.score + tail[0],
                edge.token_matches + tail[1],
                -edge.severity_distance + tail[2],
                1 + tail[3],
                (edge.expected_index, *tail[4]),
            )
            if _matching_rank(candidate) > _matching_rank(best):
                best = candidate
            elif _matching_rank(candidate) == _matching_rank(best) and _assignment_key(candidate[4]) < _assignment_key(best[4]):
                best = candidate
        return best

    assignment = choose(0, 0)[4]
    return ({index: expected for index, expected in enumerate(assignment) if expected >= 0}, duplicates)


def _matching_rank(value: tuple[int, int, int, int, tuple[int, ...]]) -> tuple[int, int, int, int]:
    return value[:4]


def _assignment_key(values: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(value if value >= 0 else 1_000_000 for value in values)


def _candidate_edge(*, user_index: int, finding, expected_index: int, expected: ModelReviewExpectedFindingV1) -> _Edge | None:
    if finding.finding_kind is not expected.finding_kind or finding.category != expected.category:
        return None
    if not any(
        finding.start_line <= accepted.end_line and finding.end_line >= accepted.start_line
        for accepted in expected.accepted_line_ranges
    ):
        return None
    token_matches = len(finding.evidence_tokens.intersection(expected.matcher_tokens))
    if token_matches < expected.minimum_token_matches:
        return None
    severity_distance = abs(_SEVERITY[finding.severity] - _SEVERITY[expected.severity])
    score = 100 + token_matches * 10 - severity_distance * 3
    return _Edge(user_index, expected_index, score, token_matches, severity_distance)


def _text_quality(value: str, *, markers: tuple[str, ...]) -> float:
    normalized = value.casefold()
    if len(value.strip()) >= 32 and any(marker in normalized for marker in markers):
        return 1.0
    if len(value.strip()) >= 12:
        return 0.5
    return 0.0


def _average(values: list[float], *, fallback: float) -> float:
    return sum(values) / len(values) if values else fallback
