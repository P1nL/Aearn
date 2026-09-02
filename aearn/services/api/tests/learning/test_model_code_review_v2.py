from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest

from app.services.learning.artifacts.contracts import (
    TutorArtifactActionRequest,
    TutorArtifactCompleteReviewAction,
    TutorArtifactModelCodeReviewPresentationV2,
)
from app.services.learning.practice.contracts import canonical_hash
from app.services.learning.practice.model_review_contracts import (
    ModelCodeReviewSubmissionV2,
    ModelReviewAcceptedRangeV2,
    ModelReviewArtifactV2,
    ModelReviewAssistanceKind,
    ModelReviewErrorCategoryV2,
    ModelReviewExpectedFindingV2,
    ModelReviewRubricV2,
)
from app.services.learning.practice.model_review_diff import build_model_review_artifact_v2
from app.services.learning.practice.model_review_scoring import evaluate_model_code_review_v2


NOW = datetime(2026, 9, 2, tzinfo=UTC)


def _target():
    return build_model_review_artifact_v2(
        language_id="python",
        runtime_label="Python 3",
        source_code="def average(total, count):\n    return 0",
        modified_code="def average(total, count):\n    return total / count",
    )


def _rubric(target) -> ModelReviewRubricV2:
    return ModelReviewRubricV2(
        expected_verdict="correctness_issue",
        expected_findings=(
            ModelReviewExpectedFindingV2(
                finding_key="zero-division",
                category="logic_boundary",
                severity="high",
                accepted_ranges=(
                    ModelReviewAcceptedRangeV2(
                        hunk_id=target.hunks[0].hunk_id,
                        side="modified",
                        start_line=2,
                        end_line=2,
                    ),
                ),
                required_concepts=("count", "zero", "guard", "division"),
                minimum_concept_matches=1,
            ),
        ),
    )


def _submission(target, *, presentation_hash: str | None = None) -> ModelCodeReviewSubmissionV2:
    return ModelCodeReviewSubmissionV2.model_validate(
        {
            "presentation_hash": presentation_hash or target.presentation_hash,
            "verdict": "correctness_issue",
            "findings": [
                {
                    "client_finding_id": "finding-1",
                    "hunk_id": target.hunks[0].hunk_id,
                    "side": "modified",
                    "start_line": 2,
                    "end_line": 2,
                    "category": "logic_boundary",
                    "severity": "high",
                    "explanation": "count can be zero, so division needs a guard",
                }
            ],
        }
    )


def test_server_diff_builder_is_stable_and_maps_both_sides() -> None:
    first = _target()
    second = _target()

    assert first == second
    assert first.presentation_mode == "diff"
    assert first.source_hash != first.modified_hash
    assert first.hunks[0].hunk_id == "diff.h1"
    assert any(line.kind.value == "removed" and line.source_line == 2 for line in first.hunks[0].lines)
    assert any(line.kind.value == "added" and line.modified_line == 2 for line in first.hunks[0].lines)


def test_v2_artifact_rejects_self_hashed_noncanonical_line_maps() -> None:
    base = _target().model_dump(mode="json")
    variants: list[dict[str, object]] = []

    wrong_text = deepcopy(base)
    wrong_text["hunks"][0]["lines"][0]["text"] = "not the published code"
    variants.append(wrong_text)

    wrong_line = deepcopy(base)
    wrong_line["hunks"][0]["lines"][0]["source_line"] = 99
    variants.append(wrong_line)

    wrong_header = deepcopy(base)
    wrong_header["hunks"][0]["header"] = "@@ bogus @@"
    variants.append(wrong_header)

    wrong_count = deepcopy(base)
    wrong_count["hunks"][0]["source_count"] += 1
    variants.append(wrong_count)

    wrong_start = deepcopy(base)
    wrong_start["hunks"][0]["modified_start"] = 2
    variants.append(wrong_start)

    duplicate_line = deepcopy(base)
    duplicate_line["hunks"][0]["lines"][1]["source_line"] = 1
    variants.append(duplicate_line)

    wrong_line_key = deepcopy(base)
    wrong_line_key["hunks"][0]["lines"][0]["line_key"] = "h1.l99"
    variants.append(wrong_line_key)

    for payload in variants:
        payload["diff_hash"] = canonical_hash({
            "presentation_mode": payload["presentation_mode"],
            "source_hash": payload["source_hash"],
            "modified_hash": payload["modified_hash"],
            "hunks": payload["hunks"],
        })
        with pytest.raises(ValueError):
            ModelReviewArtifactV2.model_validate(payload)


def test_submission_rejects_stale_hash_and_unknown_hunk() -> None:
    target = _target()
    stale = _submission(target, presentation_hash="f" * 64)
    with pytest.raises(ValueError, match="stale presentation"):
        stale.validate_presentation(target)

    payload = _submission(target).model_dump(mode="json")
    payload["findings"][0]["hunk_id"] = "diff.missing"
    missing = ModelCodeReviewSubmissionV2.model_validate(payload)
    with pytest.raises(ValueError, match="current hunk"):
        missing.validate_presentation(target)

    oversized_payload = _submission(target).model_dump(mode="json")
    oversized_payload["findings"][0]["end_line"] = 3
    oversized = ModelCodeReviewSubmissionV2.model_validate(oversized_payload)
    with pytest.raises(ValueError, match="exactly"):
        oversized.validate_presentation(target)


def test_code_only_submission_rejects_an_invented_source_side() -> None:
    target = build_model_review_artifact_v2(
        language_id="python",
        runtime_label="Python 3",
        modified_code="value = total / count",
    )
    submission = ModelCodeReviewSubmissionV2.model_validate(
        {
            "presentation_hash": target.presentation_hash,
            "verdict": "correctness_issue",
            "findings": [
                {
                    "client_finding_id": "finding-source",
                    "hunk_id": target.hunks[0].hunk_id,
                    "side": "source",
                    "start_line": 1,
                    "end_line": 1,
                    "category": "logic_boundary",
                    "severity": "high",
                    "explanation": "count can be zero, so division needs a guard",
                }
            ],
        }
    )

    with pytest.raises(ValueError, match="has no source side"):
        submission.validate_presentation(target)


def test_uncertain_verdict_cannot_persist_scored_findings() -> None:
    target = _target()
    payload = _submission(target).model_dump(mode="json")
    payload["verdict"] = "uncertain"

    with pytest.raises(ValueError, match="non-correctness verdict"):
        ModelCodeReviewSubmissionV2.model_validate(payload)


def test_v2_scoring_is_repeatable_and_taxonomy_closed() -> None:
    target = _target()
    kwargs = dict(
        submission=_submission(target),
        presentation=target,
        rubric=_rubric(target),
        required_capabilities=("python.functions.edge_cases",),
        assistance_kind=ModelReviewAssistanceKind.INDEPENDENT,
        threshold=0.8,
        now=NOW,
    )
    first = evaluate_model_code_review_v2(**kwargs)
    second = evaluate_model_code_review_v2(**kwargs)

    assert first == second
    assert first.outcome.value == "passed"
    assert first.policy_version == "model_code_review_score_v2"
    assert first.safe_feedback["finding_feedback"] == [
        {
            "client_finding_id": "finding-1",
            "status": "supported",
            "safe_reason_code": "finding_supported",
        }
    ]
    with pytest.raises(ValueError):
        ModelCodeReviewSubmissionV2.model_validate(
            {
                **_submission(target).model_dump(mode="json"),
                "findings": [
                    {
                        **_submission(target).model_dump(mode="json")["findings"][0],
                        "category": "style",
                    }
                ],
            }
        )
    assert set(ModelReviewErrorCategoryV2) >= {
        ModelReviewErrorCategoryV2.REQUIREMENTS_DRIFT,
        ModelReviewErrorCategoryV2.SECURITY_TRUST,
        ModelReviewErrorCategoryV2.ERROR_FALSE_SUCCESS,
    }


def test_v2_scorer_penalizes_wrong_verdict_omission_false_positive_duplicate_and_severity() -> None:
    target = _target()
    kwargs = {
        "presentation": target,
        "required_capabilities": ("python.functions.edge_cases",),
        "assistance_kind": ModelReviewAssistanceKind.INDEPENDENT,
        "threshold": 0.8,
        "now": NOW,
    }
    correct = _submission(target)
    reworded_payload = correct.model_dump(mode="json")
    reworded_payload["findings"][0]["explanation"] = "guard division when count is zero"
    reworded = ModelCodeReviewSubmissionV2.model_validate(reworded_payload)
    assert evaluate_model_code_review_v2(
        submission=correct, rubric=_rubric(target), **kwargs
    ).score == evaluate_model_code_review_v2(
        submission=reworded, rubric=_rubric(target), **kwargs
    ).score

    wrong_verdict = ModelCodeReviewSubmissionV2(
        presentation_hash=target.presentation_hash,
        verdict="no_correctness_issue",
    )
    wrong_result = evaluate_model_code_review_v2(
        submission=wrong_verdict, rubric=_rubric(target), **kwargs
    )
    assert wrong_result.outcome.value == "failed"
    assert wrong_result.score <= 0.49

    second_expected = ModelReviewExpectedFindingV2(
        finding_key="contract-boundary",
        category="contract_integration",
        severity="medium",
        accepted_ranges=(
            ModelReviewAcceptedRangeV2(
                hunk_id=target.hunks[0].hunk_id,
                side="modified",
                start_line=2,
                end_line=2,
            ),
        ),
        required_concepts=("contract", "count"),
        minimum_concept_matches=1,
    )
    omission_rubric = ModelReviewRubricV2(
        expected_verdict="correctness_issue",
        expected_findings=(*_rubric(target).expected_findings, second_expected),
    )
    omission = evaluate_model_code_review_v2(
        submission=correct, rubric=omission_rubric, **kwargs
    )
    assert omission.outcome.value == "failed"
    assert omission.safe_feedback["omission_band"] == "limited"

    false_positive_rubric = ModelReviewRubricV2(
        expected_verdict="no_correctness_issue",
    )
    false_positive = evaluate_model_code_review_v2(
        submission=correct, rubric=false_positive_rubric, **kwargs
    )
    assert false_positive.outcome.value == "failed"
    assert false_positive.score <= 0.49
    assert false_positive.safe_feedback["finding_feedback"][0]["status"] == "unsupported"

    duplicate_payload = correct.model_dump(mode="json")
    duplicate = deepcopy(duplicate_payload["findings"][0])
    duplicate["client_finding_id"] = "finding-duplicate"
    duplicate_payload["findings"].append(duplicate)
    duplicate_result = evaluate_model_code_review_v2(
        submission=ModelCodeReviewSubmissionV2.model_validate(duplicate_payload),
        rubric=_rubric(target),
        **kwargs,
    )
    assert duplicate_result.safe_feedback["finding_feedback"][1]["status"] == "duplicate"

    low_severity_payload = correct.model_dump(mode="json")
    low_severity_payload["findings"][0]["severity"] = "info"
    low_severity = evaluate_model_code_review_v2(
        submission=ModelCodeReviewSubmissionV2.model_validate(low_severity_payload),
        rubric=_rubric(target),
        **kwargs,
    )
    high_severity = evaluate_model_code_review_v2(
        submission=correct, rubric=_rubric(target), **kwargs
    )
    assert low_severity.score < high_severity.score


def test_v2_artifact_action_is_additive_to_v1_contract() -> None:
    target = _target()
    presentation = TutorArtifactModelCodeReviewPresentationV2(
        exercise_version_id="exercise-v2",
        presentation_hash=target.presentation_hash,
        review_target=target,
        review_categories=tuple(ModelReviewErrorCategoryV2),
    )
    with pytest.raises(ValueError, match="remediation outcome"):
        TutorArtifactModelCodeReviewPresentationV2(
            exercise_version_id="exercise-v2",
            presentation_hash=target.presentation_hash,
            review_target=target,
            review_categories=tuple(ModelReviewErrorCategoryV2),
            submission_locked=True,
            outcome="failed",
            score=0.4,
            evaluation_markdown="服务器已确定仍需补救。",
            review_receipt_id="receipt-v2",
            result_hash="a" * 64,
        )
    action = TutorArtifactActionRequest.model_validate(
        {
            "user_id": "user",
            "learning_track_id": "track",
            "teaching_session_id": "session",
            "client_action_id": "review-v2",
            "expected_artifact_version": 1,
            "action": {
                "action": "complete_review",
                "review_submission": _submission(target).model_dump(mode="json"),
            },
        }
    )

    assert presentation.type == "model_code_review_v2"
    assert isinstance(action.action, TutorArtifactCompleteReviewAction)
    assert isinstance(action.action.review_submission, ModelCodeReviewSubmissionV2)
