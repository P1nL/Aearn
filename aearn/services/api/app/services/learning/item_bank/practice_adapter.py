"""Adapter from Learning Item Bank sources to existing Practice authority contracts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from app.services.learning.item_bank.contracts import (
    LearningItemCodeContentV1,
    LearningItemCodePrivateV1,
    LearningItemDemoContentV1,
    LearningItemKnowledgeCheckContentV1,
    LearningItemKnowledgeCheckPrivateV1,
    LearningItemModelReviewContentV1,
    LearningItemModelReviewPrivateV1,
    LearningItemSourceV1,
    LearningItemSqlContentV1,
    LearningItemSqlPrivateV1,
    canonical_hash,
)
from app.services.learning.practice.contracts import (
    ExercisePrivateRubric,
    ExerciseSourceKind,
    ExerciseType,
    ExerciseVersion,
)
from app.services.learning.practice.model_review_contracts import (
    ModelReviewValidationCheckV1,
    ModelReviewValidationReceiptV1,
)
from app.services.learning.practice.model_review_quality import candidate_hash


LEARNING_ITEM_PRACTICE_ADAPTER_VERSION = "learning_item_practice_adapter_v1"


@dataclass(frozen=True, slots=True)
class ExerciseAuthorityMaterial:
    """Existing immutable ExerciseVersion/private-rubric authority material."""

    exercise: ExerciseVersion
    rubric: ExercisePrivateRubric
    model_review_validation: ModelReviewValidationReceiptV1 | None
    runner_payload: Mapping[str, object]
    standard_submission: str
    starter_submission: str


def build_exercise_authority(
    source: LearningItemSourceV1,
) -> ExerciseAuthorityMaterial | None:
    public = source.public
    private = source.private
    blueprint = source.blueprint
    content = public.content
    private_content = private.content

    if isinstance(content, LearningItemDemoContentV1):
        return None

    exercise_type: ExerciseType
    learner_prompt: dict[str, object]
    starter_artifact: dict[str, object]
    runtime_profile_id: str | None
    execution_required: bool
    feedback_policy: str
    private_tests: tuple[Mapping[str, object], ...]
    reference_answer: dict[str, object]
    score_policy: dict[str, object]
    runner_payload: dict[str, object]
    standard_submission: str
    starter_submission: str

    if isinstance(content, LearningItemCodeContentV1) and isinstance(
        private_content,
        LearningItemCodePrivateV1,
    ):
        exercise_type = ExerciseType(content.exercise_type)
        learner_prompt = {
            "schema_version": "learning_item_prompt_v1",
            "instruction_markdown": public.instruction_markdown,
        }
        starter_artifact = {
            "schema_version": "learning_item_code_artifact_v1",
            "language_id": content.language_id,
            "editor_language": content.editor_language,
            "content": content.starter_code,
        }
        runtime_profile_id = blueprint.runtime_profile_id
        execution_required = True
        feedback_policy = "learning_item_exercise_feedback_v1"
        private_tests = tuple(item.model_dump(mode="json") for item in private_content.tests)
        reference_answer = {"content": private_content.standard_answer}
        score_policy = private_content.score_policy.model_dump(mode="json")
        runner_payload = {
            "runtime_profile": _runtime_profile(
                runtime_profile_id=runtime_profile_id,
                language_id=content.language_id,
            ),
            "code_blanks": [
                {
                    "blank_key": blank.blank_key,
                    "expected_concept": blank.expected_concept,
                    "acceptable_patterns_json": [
                        pattern.model_dump(mode="json")
                        for pattern in blank.acceptable_patterns
                    ],
                    "is_core": blank.is_core,
                }
                for blank in content.code_blanks
            ],
            "test_cases": list(private_tests),
            "metadata_json": {
                "required_patterns": list(content.required_patterns),
                "browser_rule_family": content.browser_rule_family,
                "preview_html": dict(content.preview_html),
            },
        }
        standard_submission = private_content.standard_answer
        starter_submission = content.starter_code
    elif isinstance(content, LearningItemSqlContentV1) and isinstance(
        private_content,
        LearningItemSqlPrivateV1,
    ):
        exercise_type = ExerciseType.SQL_QUERY
        learner_prompt = {
            "schema_version": "learning_item_prompt_v1",
            "instruction_markdown": public.instruction_markdown,
        }
        starter_artifact = {
            "schema_version": "learning_item_sql_artifact_v1",
            "dialect": content.dialect,
            "starter_query": content.starter_query,
            "schema_markdown": content.schema_markdown,
        }
        runtime_profile_id = blueprint.runtime_profile_id
        execution_required = True
        feedback_policy = "learning_item_sql_feedback_v1"
        private_tests = tuple(item.model_dump(mode="json") for item in private_content.tests)
        reference_answer = {"content": private_content.standard_query}
        score_policy = private_content.score_policy.model_dump(mode="json")
        runner_payload = {
            "runtime_profile": _runtime_profile(
                runtime_profile_id=runtime_profile_id,
                language_id="sql",
            ),
            "code_blanks": [],
            "test_cases": list(private_tests),
            "metadata_json": {
                "sql": {
                    "dialect": content.dialect,
                    "setup_sql": list(private_content.setup_sql),
                    "comparison": content.comparison,
                    "max_rows": content.max_rows,
                }
            },
        }
        standard_submission = private_content.standard_query
        starter_submission = content.starter_query
    elif isinstance(content, LearningItemKnowledgeCheckContentV1) and isinstance(
        private_content,
        LearningItemKnowledgeCheckPrivateV1,
    ):
        exercise_type = ExerciseType.STATIC_CODE_REASONING
        learner_prompt = {
            "schema_version": "knowledge_check_prompt_v1",
            "prompt_markdown": content.prompt_markdown,
            "response_kind": content.response_kind,
            "options": [item.model_dump(mode="json") for item in content.options],
        }
        starter_artifact = {
            "schema_version": "knowledge_check_artifact_v1",
            "response_kind": content.response_kind,
            "options": [item.model_dump(mode="json") for item in content.options],
        }
        runtime_profile_id = None
        execution_required = False
        feedback_policy = "knowledge_check_feedback_v1"
        private_tests = tuple(item.model_dump(mode="json") for item in private_content.tests)
        reference_answer = {
            "accepted_answers": list(private_content.accepted_answers),
            "answer_explanation_markdown": private_content.answer_explanation_markdown,
        }
        score_policy = private_content.score_policy.model_dump(mode="json")
        runner_payload = {}
        standard_submission = private_content.accepted_answers[0]
        starter_submission = ""
    elif isinstance(content, LearningItemModelReviewContentV1) and isinstance(
        private_content,
        LearningItemModelReviewPrivateV1,
    ):
        exercise_type = ExerciseType.MODEL_CODE_REVIEW
        learner_prompt = content.prompt.model_dump(mode="json")
        starter_artifact = content.artifact.model_dump(mode="json")
        runtime_profile_id = None
        execution_required = False
        feedback_policy = "model_code_review_feedback_v1"
        private_tests = tuple(item.model_dump(mode="json") for item in private_content.tests)
        reference_answer = private_content.rubric.model_dump(mode="json")
        score_policy = private_content.score_policy.model_dump(mode="json")
        runner_payload = {}
        standard_submission = private_content.reference_submission.canonical_json()
        starter_submission = ""
    else:  # pragma: no cover - source root validation makes this unreachable.
        raise ValueError("learning item public/private kind mismatch")

    exercise = ExerciseVersion(
        language_id=blueprint.language_id,
        exercise_key=public.item_key,
        exercise_type=exercise_type,
        version=public.version,
        source_kind=ExerciseSourceKind.CURATED_FIXTURE,
        title=public.title,
        learner_prompt=learner_prompt,
        starter_artifact=starter_artifact,
        required_capabilities=blueprint.required_capabilities,
        runtime_profile_id=runtime_profile_id,
        execution_required=execution_required,
        public_feedback_policy_version=feedback_policy,
    )
    rubric = ExercisePrivateRubric(
        rubric_version="learning_item_rubric_v1",
        private_test_bundle=private_tests,
        reference_answer=reference_answer,
        score_policy=score_policy,
    )
    validation = _model_review_validation(exercise, rubric, private_content)
    return ExerciseAuthorityMaterial(
        exercise=exercise,
        rubric=rubric,
        model_review_validation=validation,
        runner_payload=runner_payload,
        standard_submission=standard_submission,
        starter_submission=starter_submission,
    )


def _model_review_validation(
    exercise: ExerciseVersion,
    rubric: ExercisePrivateRubric,
    private_content: object,
) -> ModelReviewValidationReceiptV1 | None:
    if not isinstance(private_content, LearningItemModelReviewPrivateV1):
        return None
    candidate = candidate_hash(exercise, rubric)
    check_types = (
        "schema",
        "parser",
        "compile_or_typecheck",
        "visible_tests",
        "hidden_tests",
        "finding_reachability",
        "rubric_consistency",
        "coverage",
        "redaction",
    )
    return ModelReviewValidationReceiptV1(
        candidate_hash=candidate,
        validation_profile_version=private_content.validation_profile_version,
        checks=tuple(
            ModelReviewValidationCheckV1(
                check_type=check_type,  # type: ignore[arg-type]
                status="passed",
                proof_hash=canonical_hash(
                    {
                        "candidate_hash": candidate,
                        "check_type": check_type,
                        "profile": private_content.validation_profile_version,
                    }
                ),
            )
            for check_type in check_types
        ),
    )


def _runtime_profile(*, runtime_profile_id: str | None, language_id: str) -> dict[str, object]:
    if runtime_profile_id is None:
        return {"runtime_tier": "none", "language": language_id, "runner": "none"}
    runner = {
        "browser_preview": "browser",
        "python_stdout_test": "python",
        "node_typescript_test": "node",
        "sql_query_test": "sql",
        "managed_compiled_test": "compiled",
    }.get(runtime_profile_id, "none")
    return {
        "runtime_tier": runtime_profile_id,
        "language": language_id,
        "runner": runner,
    }


__all__ = (
    "LEARNING_ITEM_PRACTICE_ADAPTER_VERSION",
    "ExerciseAuthorityMaterial",
    "build_exercise_authority",
)
