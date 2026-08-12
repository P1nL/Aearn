from __future__ import annotations

from datetime import UTC, datetime

from app.services.learning.practice.model_review_contracts import (
    ModelCodeReviewSubmissionV1,
    ModelReviewAssistanceKind,
    ModelReviewRubricV1,
)
from app.services.learning.practice.model_review_fixtures import MODEL_REVIEW_FIXTURES
from app.services.learning.practice.model_review_scoring import evaluate_model_code_review


NOW = datetime(2026, 8, 12, tzinfo=UTC)


def _rubric(index: int) -> ModelReviewRubricV1:
    return ModelReviewRubricV1.model_validate(MODEL_REVIEW_FIXTURES[index].rubric.reference_answer)


def _submission(verdict: str, findings: list[dict[str, object]]) -> ModelCodeReviewSubmissionV1:
    return ModelCodeReviewSubmissionV1.model_validate({"verdict": verdict, "findings": findings})


def _finding(*, finding_id: str = "finding-1", category: str = "edge_case", line: int = 2) -> dict[str, object]:
    return {
        "client_finding_id": finding_id,
        "finding_kind": "correctness",
        "start_line": line,
        "end_line": line,
        "category": category,
        "severity": "high",
        "trigger_condition": "count is zero and division is attempted",
        "principle": "the requirement defines a zero count boundary",
        "impact": "the function raises instead of returning zero",
        "validation_method": "test input total=0 and count=0 and assert return 0",
        "suggested_fix": "guard count == 0 before division and return zero",
    }


def test_supported_finding_passes_with_deterministic_safe_feedback() -> None:
    result = evaluate_model_code_review(
        submission=_submission("correctness_issue", [_finding()]),
        rubric=_rubric(0),
        line_count=2,
        required_capabilities=("python.functions.edge_cases",),
        assistance_kind=ModelReviewAssistanceKind.INDEPENDENT,
        threshold=0.8,
        now=NOW,
    )
    assert result.outcome.value == "passed"
    assert result.safe_feedback["execution_claim"] == "not_run"
    assert result.safe_feedback["finding_feedback"] == [
        {"client_finding_id": "finding-1", "status": "supported", "safe_reason_code": "finding_supported"}
    ]
    serialized = str(result.safe_feedback).casefold()
    assert "zero-division" not in serialized
    assert "matcher_tokens" not in serialized


def test_correct_code_penalizes_false_positive_and_accepts_no_issue() -> None:
    no_issue = evaluate_model_code_review(
        submission=_submission("no_correctness_issue", []),
        rubric=_rubric(3),
        line_count=4,
        required_capabilities=("sql.select.where",),
        assistance_kind=ModelReviewAssistanceKind.INDEPENDENT,
        threshold=0.8,
        now=NOW,
    )
    assert no_issue.outcome.value == "passed"
    false_positive = evaluate_model_code_review(
        submission=_submission("correctness_issue", [_finding(category="filter", line=3)]),
        rubric=_rubric(3),
        line_count=4,
        required_capabilities=("sql.select.where",),
        assistance_kind=ModelReviewAssistanceKind.INDEPENDENT,
        threshold=0.8,
        now=NOW,
    )
    assert false_positive.outcome.value == "failed"
    assert false_positive.score <= 0.49
    assert false_positive.safe_feedback["finding_feedback"][0]["status"] == "unsupported"


def test_duplicate_finding_does_not_increase_discovery() -> None:
    first = _finding()
    duplicate = dict(first, client_finding_id="finding-2")
    result = evaluate_model_code_review(
        submission=_submission("correctness_issue", [first, duplicate]),
        rubric=_rubric(0),
        line_count=2,
        required_capabilities=("python.functions.edge_cases",),
        assistance_kind=ModelReviewAssistanceKind.HINTED,
        threshold=0.8,
        now=NOW,
    )
    assert result.safe_feedback["finding_feedback"][1]["status"] == "duplicate"
    assert result.safe_feedback["score_breakdown"]["duplicate"] == 0.5
    assert result.safe_feedback["assistance_kind"] == "hinted"


def test_wrong_verdict_is_hard_capped_even_with_plausible_text() -> None:
    result = evaluate_model_code_review(
        submission=_submission("uncertain", [_finding()]),
        rubric=_rubric(0),
        line_count=2,
        required_capabilities=("python.functions.edge_cases",),
        assistance_kind=ModelReviewAssistanceKind.INDEPENDENT,
        threshold=0.8,
        now=NOW,
    )
    assert result.outcome.value == "failed"
    assert result.score <= 0.49
