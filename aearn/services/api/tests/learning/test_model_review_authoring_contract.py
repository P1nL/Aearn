from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

import pytest
from aearn_shared.execution import (
    ExecutionJobState,
    ExecutionJobV1,
    SafeExecutionResultV1,
    SafeExecutionStatus,
    SafeTestFeedbackV1,
)

from app.core.config import Settings
from app.services.learning.practice.model_review_authoring import (
    ModelReviewAuthoringFailure,
    ModelReviewAuthoringRequest,
    PrimaryModelCodeReviewAuthor,
    _author_messages,
    _parse_candidate,
    _request_payload,
)
from app.services.learning.practice.model_review_contracts import ModelReviewScenarioKind
from app.services.learning.practice.model_review_quality import (
    candidate_hash as publication_candidate_hash,
    model_review_public_redaction_proof,
)
from app.services.learning.practice.model_review_repository import (
    ModelReviewCandidateRecord,
    ModelReviewRepositoryError,
    ModelReviewValidationRecord,
    PostgresModelReviewRepository,
)
from app.services.learning.practice.model_review_templates import (
    MODEL_REVIEW_AUTHOR_CANDIDATE_SCHEMA_NAME,
    MODEL_REVIEW_TEMPLATES,
    ModelReviewAuthorCandidateV2,
    expected_model_review_test_outcomes,
    model_review_author_output_schema,
    model_review_template_coverage_proof,
    validate_controlled_model_review_candidate,
)
from app.services.llm.llm_client import LLMJsonResponse


_PRIVATE_AUTHOR_FIELDS = {
    "template_id",
    "requirements",
    "tests",
    "hidden_tests",
    "expected_outcomes",
    "rubric",
    "findings",
    "matcher_tokens",
    "proof_ids",
    "score_policy",
    "validation_rules",
}


def _request(template_index: int = 0) -> ModelReviewAuthoringRequest:
    template = MODEL_REVIEW_TEMPLATES[template_index]
    return ModelReviewAuthoringRequest(
        language_id=template.language_id,
        knowledge_key=f"{template.language_id}.controlled-review",
        required_capabilities=(template.capability_hint,),
        mastery_level="practicing",
        mastery_confidence=0.62,
        validation_profile_version="model_review_validation_v1",
        template_id=template.template_id,
    )


def test_model_review_author_schema_contains_only_learner_scenario_and_candidate_code() -> None:
    schema = model_review_author_output_schema()

    assert schema["additionalProperties"] is False
    assert schema["required"] == [
        "schema_version",
        "title",
        "learner_instruction",
        "candidate_code",
    ]
    assert set(schema["properties"]) == set(schema["required"])
    assert not (_PRIVATE_AUTHOR_FIELDS & set(schema["properties"]))


@pytest.mark.parametrize("template", MODEL_REVIEW_TEMPLATES, ids=lambda item: item.template_id)
def test_each_controlled_model_review_template_builds_private_tests_rubric_and_coverage(template) -> None:
    request = ModelReviewAuthoringRequest(
        language_id=template.language_id,
        knowledge_key=f"{template.language_id}.controlled-review",
        required_capabilities=(template.capability_hint,),
        mastery_level="practicing",
        mastery_confidence=0.62,
        validation_profile_version="model_review_validation_v1",
        template_id=template.template_id,
    )
    exercise, rubric = _parse_candidate(template.canonical_author_example(), request)

    selected = validate_controlled_model_review_candidate(exercise=exercise, rubric=rubric)
    coverage = model_review_template_coverage_proof(template=selected, rubric=rubric)
    outcomes = expected_model_review_test_outcomes(rubric)
    public_proof = model_review_public_redaction_proof(exercise)

    assert selected is template
    assert coverage["visible_count"] >= 1
    assert coverage["hidden_count"] >= 1
    assert len(outcomes) == coverage["test_count"]
    assert public_proof["protected_marker_count"] == 0
    assert {item["case_type"] for item in rubric.private_test_bundle} == {"visible", "hidden"}
    assert all("candidate_expected_pass" in item and "proof_ids" in item for item in rubric.private_test_bundle)
    assert "expected_findings" not in json.dumps(exercise.public_payload(), ensure_ascii=False)


def test_controlled_registry_covers_all_six_review_scenarios() -> None:
    assert {template.scenario_kind for template in MODEL_REVIEW_TEMPLATES} == set(ModelReviewScenarioKind)


def test_model_review_author_cannot_select_template_or_override_private_authority() -> None:
    template = MODEL_REVIEW_TEMPLATES[0]
    request = _request()
    for forbidden_payload in (
        {**template.canonical_author_example(), "template_id": template.template_id},
        {**template.canonical_author_example(), "private_test_bundle": []},
        {**template.canonical_author_example(), "expected_findings": []},
        {**template.canonical_author_example(), "score_policy": {"threshold": 0}},
    ):
        with pytest.raises(ModelReviewAuthoringFailure, match="受控模板校验"):
            _parse_candidate(forbidden_payload, request)


def test_model_review_prompt_exposes_controlled_authoring_spec_but_no_private_test_or_rubric_data() -> None:
    request = _request(1)
    template = MODEL_REVIEW_TEMPLATES[1]
    messages = _author_messages(request)
    request_payload = _request_payload(request)
    serialized_request = json.dumps(request_payload, ensure_ascii=False, sort_keys=True)
    system = messages[0]["content"]

    assert request_payload["selected_template"] == template.public_authoring_spec()
    assert "private_test_bundle" not in serialized_request
    assert "candidate_expected_pass" not in serialized_request
    assert "reachability_proof_ids" not in serialized_request
    assert all(test_case.id not in serialized_request for test_case in template.test_bundle)
    assert "selected template identity is server-owned" in system
    assert json.dumps(template.canonical_author_example(), ensure_ascii=False, sort_keys=True, separators=(",", ":")) in system


class _CapturingClient:
    def __init__(self, payload: Mapping[str, object]) -> None:
        self.payload = dict(payload)
        self.messages: tuple[dict[str, str], ...] = ()
        self.output_schema: Mapping[str, object] | None = None
        self.schema_name: str | None = None

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
        output_schema: Mapping[str, object] | None = None,
        schema_name: str | None = None,
    ) -> LLMJsonResponse:
        del temperature, max_tokens, timeout_seconds
        self.messages = tuple(dict(item) for item in messages)
        self.output_schema = output_schema
        self.schema_name = schema_name
        return LLMJsonResponse(content=self.payload, model="fake-model-review-author")


def test_primary_model_review_author_uses_strict_schema_and_selected_template_example() -> None:
    request = _request(2)
    template = MODEL_REVIEW_TEMPLATES[2]
    client = _CapturingClient(template.canonical_author_example())

    response = PrimaryModelCodeReviewAuthor(
        settings=Settings(llm_type="disabled"),
        client=client,  # type: ignore[arg-type]
    ).author(request)

    assert response.candidate == template.canonical_author_example()
    assert client.output_schema == model_review_author_output_schema()
    assert client.schema_name == MODEL_REVIEW_AUTHOR_CANDIDATE_SCHEMA_NAME
    assert "valid example" in client.messages[0]["content"].lower()
    ModelReviewAuthorCandidateV2.model_validate(response.candidate)

class _NoDatabaseConnection:
    def execute(self, *args, **kwargs):
        del args, kwargs
        raise AssertionError("validation must fail before writing database evidence")


def _terminal_validation_fixture():
    template = MODEL_REVIEW_TEMPLATES[0]
    request = _request(0)
    exercise, rubric = _parse_candidate(template.canonical_author_example(), request)
    private_payload = {
        "rubric_version": rubric.rubric_version,
        "private_test_bundle": [dict(item) for item in rubric.private_test_bundle],
        "reference_answer": dict(rubric.reference_answer),
        "score_policy": dict(rubric.score_policy),
        "rubric_hash": rubric.rubric_hash,
    }
    candidate_hash = publication_candidate_hash(exercise, rubric)
    candidate = ModelReviewCandidateRecord(
        candidate_id="00000000-0000-0000-0000-000000000101",
        authoring_run_id="00000000-0000-0000-0000-000000000102",
        user_id="00000000-0000-0000-0000-000000000103",
        track_id="00000000-0000-0000-0000-000000000104",
        knowledge_key=request.knowledge_key,
        public_payload=exercise.public_payload(),
        private_payload=private_payload,
        public_hash="a" * 64,
        private_hash="b" * 64,
        candidate_hash=candidate_hash,
        validation_profile_version=request.validation_profile_version,
        state="validating",
    )
    validation = ModelReviewValidationRecord(
        validation_id="00000000-0000-0000-0000-000000000105",
        authoring_run_id=candidate.authoring_run_id,
        candidate_id=candidate.candidate_id,
        user_id=candidate.user_id,
        track_id=candidate.track_id,
        validation_profile_version=candidate.validation_profile_version,
        candidate_hash=candidate.candidate_hash,
        state="running",
        action_invocation_id="model-review-validation-test",
        authority_hash=None,
        action_receipt_hash=None,
    )
    return candidate, validation, rubric


def _completed_validation_job(*, runtime_id: str, observed_outcomes: tuple[tuple[bool, bool], ...]) -> ExecutionJobV1:
    feedback = tuple(
        SafeTestFeedbackV1(
            case_id=f"case-{index}",
            visible=visible,
            passed=passed,
            message="controlled validation result",
        )
        for index, (visible, passed) in enumerate(observed_outcomes, start=1)
    )
    return ExecutionJobV1(
        job_id="00000000-0000-0000-0000-000000000111",
        intent_proof_id="00000000-0000-0000-0000-000000000112",
        user_id="00000000-0000-0000-0000-000000000103",
        runtime_id=runtime_id,
        owner_kind="model_review_validation",
        conversation_id="00000000-0000-0000-0000-000000000113",
        run_id="00000000-0000-0000-0000-000000000114",
        model_review_validation_id="00000000-0000-0000-0000-000000000105",
        lock_fingerprint="c" * 64,
        state=ExecutionJobState.COMPLETED,
        result=SafeExecutionResultV1(
            status=SafeExecutionStatus.SUCCESS,
            test_feedback=feedback,
            passed_test_count=sum(passed for _, passed in observed_outcomes),
            total_test_count=len(observed_outcomes),
            diagnostic_code="controlled_validation_complete",
        ),
    )


def test_terminal_model_review_validation_rejects_wrong_runtime_before_writing_checks() -> None:
    candidate, validation, rubric = _terminal_validation_fixture()
    job = _completed_validation_job(
        runtime_id="node-typescript-v1",
        observed_outcomes=expected_model_review_test_outcomes(rubric),
    )
    repository = PostgresModelReviewRepository(_NoDatabaseConnection())  # type: ignore[arg-type]

    with pytest.raises(ModelReviewRepositoryError, match="MODEL_REVIEW_VALIDATION_FAILED"):
        repository.verify_terminal_job(
            validation=validation,
            candidate=candidate,
            job=job,
            now=datetime(2026, 8, 13, tzinfo=UTC),
        )


def test_terminal_model_review_validation_rejects_outcome_mismatch_before_writing_checks() -> None:
    candidate, validation, rubric = _terminal_validation_fixture()
    expected = expected_model_review_test_outcomes(rubric)
    mismatched = (*expected[:-1], (expected[-1][0], not expected[-1][1]))
    job = _completed_validation_job(runtime_id="python-stdout-v1", observed_outcomes=mismatched)
    repository = PostgresModelReviewRepository(_NoDatabaseConnection())  # type: ignore[arg-type]

    with pytest.raises(ModelReviewRepositoryError, match="MODEL_REVIEW_VALIDATION_FAILED"):
        repository.verify_terminal_job(
            validation=validation,
            candidate=candidate,
            job=job,
            now=datetime(2026, 8, 13, tzinfo=UTC),
        )
