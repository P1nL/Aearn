"""Publication-quality validation for model code-review candidates."""
from __future__ import annotations

import json
from dataclasses import dataclass

from app.services.learning.practice.contracts import ExercisePrivateRubric, ExerciseType, ExerciseVersion
from app.services.learning.practice.model_review_contracts import (
    ModelReviewArtifactV1,
    ModelReviewPromptV1,
    ModelReviewRubricV1,
    ModelReviewScenarioKind,
    ModelReviewValidationReceiptV1,
)


_REQUIRED_CHECKS = frozenset(
    {
        "schema",
        "parser",
        "compile_or_typecheck",
        "visible_tests",
        "hidden_tests",
        "finding_reachability",
        "rubric_consistency",
        "coverage",
        "redaction",
    }
)
_PROTECTED = (
    "expected_findings",
    "private_test",
    "hidden_test",
    "reference_answer",
    "matcher_tokens",
    "reachability_proof",
    "provider_body",
    "docker.sock",
    "container_id",
    "image_reference",
    "api_key",
    "authorization:",
)


@dataclass(frozen=True, slots=True)
class ModelReviewQualityReport:
    exercise_hash: str
    rubric_hash: str
    validation_hash: str
    checks: tuple[str, ...]


def parse_public_model_review(exercise: ExerciseVersion) -> tuple[ModelReviewPromptV1, ModelReviewArtifactV1]:
    if exercise.exercise_type is not ExerciseType.MODEL_CODE_REVIEW:
        raise ValueError("exercise is not a model code-review exercise")
    return (
        ModelReviewPromptV1.model_validate(dict(exercise.learner_prompt)),
        ModelReviewArtifactV1.model_validate(dict(exercise.starter_artifact)),
    )


def parse_private_model_review(rubric: ExercisePrivateRubric) -> ModelReviewRubricV1:
    return ModelReviewRubricV1.model_validate(dict(rubric.reference_answer))


def require_model_review_quality(
    exercise: ExerciseVersion,
    rubric: ExercisePrivateRubric,
    validation: ModelReviewValidationReceiptV1,
) -> ModelReviewQualityReport:
    prompt, artifact = parse_public_model_review(exercise)
    private = parse_private_model_review(rubric)
    if exercise.execution_required or exercise.runtime_profile_id is not None:
        raise ValueError("learner model review must be static-only")
    if artifact.language_id != exercise.language_id:
        raise ValueError("model review artifact language does not match exercise")
    public_text = json.dumps(
        {"prompt": prompt.model_dump(mode="json"), "artifact": artifact.model_dump(mode="json")},
        ensure_ascii=False,
        sort_keys=True,
    ).casefold()
    if any(marker in public_text for marker in _PROTECTED):
        raise ValueError("public model review contains a protected marker")
    if validation.candidate_hash != _candidate_hash(exercise, rubric):
        raise ValueError("model review validation does not reference exact candidate")
    statuses = {item.check_type: item.status for item in validation.checks}
    if set(statuses) != _REQUIRED_CHECKS or any(status not in {"passed", "not_applicable"} for status in statuses.values()):
        raise ValueError("model review validation check set is incomplete")
    if any(
        item.check_type != "compile_or_typecheck" and item.status != "passed"
        for item in validation.checks
    ):
        raise ValueError("required model review validation check did not pass")
    if private.scenario_kind in {
        ModelReviewScenarioKind.FULLY_CORRECT,
        ModelReviewScenarioKind.SUSPICIOUS_BUT_CORRECT,
    } and statuses["coverage"] != "passed":
        raise ValueError("correct model review scenario needs coverage proof")
    return ModelReviewQualityReport(
        exercise_hash=exercise.content_hash,
        rubric_hash=rubric.rubric_hash,
        validation_hash=validation.receipt_hash,
        checks=tuple(sorted(statuses)),
    )


def _candidate_hash(exercise: ExerciseVersion, rubric: ExercisePrivateRubric) -> str:
    from app.services.learning.practice.contracts import canonical_hash

    return canonical_hash({"exercise_hash": exercise.content_hash, "rubric_hash": rubric.rubric_hash})


def candidate_hash(exercise: ExerciseVersion, rubric: ExercisePrivateRubric) -> str:
    return _candidate_hash(exercise, rubric)
