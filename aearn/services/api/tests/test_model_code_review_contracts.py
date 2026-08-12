from __future__ import annotations

import pytest

from app.services.learning.practice.contracts import ExerciseType
from app.services.learning.practice.model_review_contracts import (
    ModelCodeReviewSubmissionV1,
    ModelReviewFindingKind,
    ModelReviewScenarioKind,
    ModelReviewValidationReceiptV1,
    ModelReviewVerdict,
    code_hash,
)
from app.services.learning.practice.model_review_fixtures import MODEL_REVIEW_FIXTURES, validation_checks_for_fixture
from app.services.learning.practice.model_review_quality import candidate_hash, require_model_review_quality


def _finding(**overrides):
    payload = {
        "client_finding_id": "finding-1",
        "finding_kind": "correctness",
        "start_line": 2,
        "end_line": 2,
        "category": "edge_case",
        "severity": "high",
        "trigger_condition": "count is zero and division is attempted",
        "principle": "the requirement defines a zero-count boundary",
        "impact": "the function raises instead of returning zero",
        "validation_method": "test input total=0 and count=0 and assert return 0",
        "suggested_fix": "guard count == 0 before division and return 0",
    }
    payload.update(overrides)
    return payload


def test_model_review_fixtures_cover_six_scenarios_and_core_languages() -> None:
    assert {item.rubric.reference_answer["scenario_kind"] for item in MODEL_REVIEW_FIXTURES} == {
        item.value for item in ModelReviewScenarioKind
    }
    assert {item.exercise.language_id for item in MODEL_REVIEW_FIXTURES} == {
        "python", "javascript", "typescript", "sql"
    }
    assert all(item.exercise.exercise_type is ExerciseType.MODEL_CODE_REVIEW for item in MODEL_REVIEW_FIXTURES)
    assert all(item.exercise.execution_required is False for item in MODEL_REVIEW_FIXTURES)


def test_submission_contract_enforces_verdict_finding_shape_and_line_range() -> None:
    submission = ModelCodeReviewSubmissionV1.model_validate(
        {"verdict": "correctness_issue", "findings": [_finding()]}
    )
    submission.validate_line_count(2)
    assert submission.submission_hash
    assert submission.findings[0].finding_kind is ModelReviewFindingKind.CORRECTNESS

    with pytest.raises(ValueError, match="requires a correctness finding"):
        ModelCodeReviewSubmissionV1.model_validate({"verdict": "correctness_issue", "findings": []})
    with pytest.raises(ValueError, match="cannot contain correctness"):
        ModelCodeReviewSubmissionV1.model_validate(
            {"verdict": "no_correctness_issue", "findings": [_finding()]}
        )
    with pytest.raises(ValueError, match="exceeds"):
        submission.validate_line_count(1)


def test_public_artifact_hash_and_validation_receipt_are_exact() -> None:
    fixture = MODEL_REVIEW_FIXTURES[0]
    artifact = fixture.exercise.starter_artifact
    assert artifact["code_hash"] == code_hash(str(artifact["model_code"]))
    receipt = ModelReviewValidationReceiptV1.model_validate(
        {
            "candidate_hash": fixture.candidate_hash,
            "validation_profile_version": fixture.validation_profile_version,
            "checks": validation_checks_for_fixture(fixture),
        }
    )
    report = require_model_review_quality(fixture.exercise, fixture.rubric, receipt)
    assert report.validation_hash == receipt.receipt_hash
    assert candidate_hash(fixture.exercise, fixture.rubric) == fixture.candidate_hash

    bad = receipt.model_copy(update={"candidate_hash": "f" * 64})
    with pytest.raises(ValueError, match="exact candidate"):
        require_model_review_quality(fixture.exercise, fixture.rubric, bad)


def test_correct_and_improvement_scenarios_reject_inconsistent_private_rubric() -> None:
    correct = MODEL_REVIEW_FIXTURES[3]
    assert correct.rubric.reference_answer["expected_verdict"] == ModelReviewVerdict.NO_CORRECTNESS_ISSUE.value
    improvement = MODEL_REVIEW_FIXTURES[2]
    assert improvement.rubric.reference_answer["expected_verdict"] == ModelReviewVerdict.IMPROVEMENT_ONLY.value
