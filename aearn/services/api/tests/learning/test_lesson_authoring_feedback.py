from dataclasses import replace
import json

import pytest

from app.services.learning.lesson_authoring_feedback import (
    CONSTRAINTS, LessonAuthorFeedback, LessonFeedbackIssue, attempt_diagnostic, validate_attempt_diagnostic,
)
from app.services.learning.lesson_authoring import (
    LessonAuthoringFailure, LessonAuthoringRequest, PrimaryLessonDocumentAuthor,
)
from app.core.config import Settings
from app.services.llm.llm_client import LLMInvalidResponseError, LLMInvalidResponseKind
from app.services.llm.contracts import LLMResponseDiagnostics, LLMUsage


def test_feedback_is_closed_bounded_and_hash_stable():
    issue = LessonFeedbackIssue("LESSON_BLOCK_FIELDS_INVALID", "blocks[5]")
    feedback = LessonAuthorFeedback("standard", "candidate_contract", 1, (issue,))
    assert feedback.content_hash == replace(feedback).content_hash
    assert feedback.payload()["issues"] == [issue.payload()]
    assert feedback.repairable
    assert attempt_diagnostic("standard", 1, feedback)["feedback_hash"] == feedback.content_hash
    assert validate_attempt_diagnostic({}) == {}
    for location in ["blocks[64]", "C:/secret", "/home/user", "https://example.com", "run_id", "document.secret"]:
        with pytest.raises(ValueError):
            LessonFeedbackIssue(issue.code, location)
    with pytest.raises(ValueError):
        LessonFeedbackIssue("SECRET_TOKEN")
    with pytest.raises(ValueError):
        replace(feedback, issues=(issue,) * 13)
    with pytest.raises(ValueError):
        replace(feedback, previous_attempt_index=True)
    diagnostic = attempt_diagnostic("standard", 1, feedback)
    with pytest.raises(ValueError):
        validate_attempt_diagnostic({**diagnostic, "provider_body": "secret"})
    with pytest.raises(ValueError):
        validate_attempt_diagnostic({**diagnostic, "issue_codes": ["secret"]})
    assert all(len(code) <= 80 and len(constraint) <= 240 for code, constraint in CONSTRAINTS.items())


@pytest.mark.parametrize("kind,repairable", [(kind, kind in {
    LLMInvalidResponseKind.ENVELOPE_INVALID, LLMInvalidResponseKind.CONTENT_MISSING,
    LLMInvalidResponseKind.CONTENT_NOT_JSON_OBJECT, LLMInvalidResponseKind.RESPONSE_INCOMPLETE,
}) for kind in LLMInvalidResponseKind])
def test_primary_adapter_preserves_safe_invalid_metadata(kind, repairable):
    usage = LLMUsage(input_tokens=11, output_tokens=7, total_tokens=18)
    class Client:
        def complete_json(self, *args, **kwargs):
            raise LLMInvalidResponseError("SECRET RAW PROVIDER BODY", kind=kind, usage=usage, model="safe-model")
    # Explicit real fields keep this injected-client test independent of LLM_TYPE.
    settings = Settings(
        llm_type="deepseek", deepseek_model="deepseek-v4-flash",
        deepseek_api_key="fake-test-key", deepseek_base_url="https://provider.invalid",
    )
    from app.services.learning.lesson_authoring import LessonAuthoringEvidence
    evidence = LessonAuthoringEvidence("S1", "Python", "Python", "official", "3", "rolling", (), "Evidence")
    request = LessonAuthoringRequest("standard", "python", "python.variables", "Variables", "Learn", "beginner", (), "unseen", 0, (evidence,))
    with pytest.raises(LessonAuthoringFailure) as result:
        PrimaryLessonDocumentAuthor(settings, client=Client()).author(request)
    failure = result.value
    assert failure.model == "safe-model" and failure.usage == usage
    assert failure.protocol == "deepseek_responses"
    feedback = LessonAuthorFeedback("standard", failure.stage, 1, failure.issues)
    assert feedback.repairable is repairable
    assert "SECRET" not in json.dumps(feedback.payload())


@pytest.mark.parametrize("defect,stage,location", [
    ("extra", "candidate_shape", "document"),
    ("block_extra", "candidate_contract", "blocks[2]"),
    ("block_type", "candidate_contract", "blocks[2].type"),
    ("citation", "candidate_contract", "blocks[2].citation_ids"),
    ("order", "candidate_contract", "blocks[2].order_index"),
    ("scope", "candidate_identity", "knowledge_key"),
])
def test_candidate_feedback_locations_do_not_echo_values(defect, stage, location):
    from app.services.learning.lesson_authoring import _parse_author_candidate, _assert_candidate_identity
    from tests.support.lesson_document_support import author_candidate_payload, CITATION_ID
    candidate = author_candidate_payload()
    if defect == "extra":
        candidate["SECRET_PROVIDER_FIELD"] = "secret"
    elif defect == "block_extra":
        candidate["blocks"][2]["SECRET_PROVIDER_FIELD"] = "secret"
    elif defect == "block_type":
        candidate["blocks"][2]["type"] = "SECRET_PROVIDER_FIELD"
    elif defect == "citation":
        candidate["blocks"][2]["citation_ids"] = ["SECRET_PROVIDER_FIELD"]
    elif defect == "order":
        candidate["blocks"][2]["order_index"] = 25
    else:
        candidate["knowledge_key"] = "secret.other-scope"
    with pytest.raises(LessonAuthoringFailure) as result:
        document = _parse_author_candidate(candidate, {"S1": CITATION_ID})
        request = LessonAuthoringRequest("standard", "python", "python.variables", "Variables", "Learn", "beginner", (), "unseen", 0, ())
        _assert_candidate_identity(document, request)
    assert result.value.stage == stage
    assert result.value.issues[0].location == location
    feedback = LessonAuthorFeedback("standard", stage, 1, result.value.issues)
    assert "SECRET_PROVIDER_FIELD" not in json.dumps(feedback.payload())
    assert "secret.other-scope" not in json.dumps(feedback.payload())


def test_private_diagnostic_v2_is_closed_and_preserves_unknown_usage():
    metadata = LLMResponseDiagnostics(
        response_status="incomplete", incomplete_reason="max_output_tokens",
        requested_max_output_tokens=12000, requested_reasoning_effort="none", visible_output_chars=123,
    )
    value = attempt_diagnostic("standard", 1, response_diagnostics=metadata)
    assert value["schema_version"] == "lesson_author_attempt_diagnostic_v2"
    assert value["reasoning_tokens"] is None
    assert validate_attempt_diagnostic(value) == value
    measured = attempt_diagnostic("standard", 1, response_diagnostics=metadata,
                                  usage=LLMUsage(input_tokens=4, output_tokens=10, reasoning_tokens=3))
    assert measured["reasoning_tokens"] == 3
    for bad in (-1, True, "secret"):
        with pytest.raises(ValueError):
            validate_attempt_diagnostic({**value, "reasoning_tokens": bad})
    for field, bad in (("incomplete_reason", "PRIVATE_PROVIDER_TEXT"), ("response_status", []),
                       ("requested_max_output_tokens", True), ("visible_output_chars", -1),
                       ("requested_reasoning_effort", "PRIVATE_REASONING")):
        with pytest.raises(ValueError):
            validate_attempt_diagnostic({**value, "provider_response": {**value["provider_response"], field: bad}})
    with pytest.raises(ValueError):
        validate_attempt_diagnostic({**value, "provider_response": {**value["provider_response"], "raw_body": "secret"}})


@pytest.mark.parametrize("model,expected", [("deepseek-v4-flash", "disabled"), ("deepseek-chat", None)])
def test_lesson_thinking_override_is_scoped_to_exact_responses_model(model, expected):
    from types import SimpleNamespace
    from app.services.learning.lesson_authoring import LessonAuthoringEvidence
    calls = []
    class Client:
        def complete_json(self, messages, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(content={}, model=model, usage=None)
    settings = Settings(llm_type="deepseek", deepseek_model=model,
                        deepseek_api_key="test", deepseek_base_url="https://provider.invalid")
    evidence = LessonAuthoringEvidence("S1", "Python", "Python", "official", "3", "rolling", (), "Evidence")
    request = LessonAuthoringRequest("standard", "python", "python.variables", "Variables", "Learn", "beginner", (), "unseen", 0, (evidence,))
    PrimaryLessonDocumentAuthor(settings, client=Client()).author(request)
    assert calls[0]["thinking_mode"] == expected
    assert calls[0]["max_tokens"] == 12000


@pytest.mark.parametrize("reason,repairable", [("max_output_tokens", True), ("content_filter", False),
                                             ("context_length_exceeded", False), ("unknown", False)])
def test_incomplete_diagnostic_cause_controls_lesson_repair(reason, repairable):
    from app.services.learning.lesson_authoring import LessonAuthoringEvidence
    metadata = LLMResponseDiagnostics(response_status="incomplete", incomplete_reason=reason)
    class Client:
        def complete_json(self, *args, **kwargs):
            raise LLMInvalidResponseError("PRIVATE BODY", kind=LLMInvalidResponseKind.RESPONSE_INCOMPLETE,
                                          response_diagnostics=metadata)
    settings = Settings(llm_type="deepseek", deepseek_model="deepseek-v4-flash",
                        deepseek_api_key="test", deepseek_base_url="https://provider.invalid")
    evidence = LessonAuthoringEvidence("S1", "Python", "Python", "official", "3", "rolling", (), "Evidence")
    request = LessonAuthoringRequest("standard", "python", "python.variables", "Variables", "Learn", "beginner", (), "unseen", 0, (evidence,))
    with pytest.raises(LessonAuthoringFailure) as caught:
        PrimaryLessonDocumentAuthor(settings, client=Client()).author(request)
    failure = caught.value
    assert failure.response_diagnostics == metadata
    assert LessonAuthorFeedback("standard", failure.stage, 1, failure.issues).repairable is repairable


@pytest.mark.parametrize("status", ["missing_terminal", "queued", "in_progress", "cancelled", "unknown"])
def test_nonterminal_envelope_never_consumes_content_repair(status):
    from app.services.learning.lesson_authoring import LessonAuthoringEvidence
    metadata = LLMResponseDiagnostics(response_status=status)
    class Client:
        def complete_json(self, *args, **kwargs):
            raise LLMInvalidResponseError("PRIVATE BODY", kind=LLMInvalidResponseKind.ENVELOPE_INVALID,
                                          response_diagnostics=metadata)
    settings = Settings(llm_type="deepseek", deepseek_model="deepseek-v4-flash",
                        deepseek_api_key="test", deepseek_base_url="https://provider.invalid")
    evidence = LessonAuthoringEvidence("S1", "Python", "Python", "official", "3", "rolling", (), "Evidence")
    request = LessonAuthoringRequest("standard", "python", "python.variables", "Variables", "Learn", "beginner", (), "unseen", 0, (evidence,))
    with pytest.raises(LessonAuthoringFailure) as caught:
        PrimaryLessonDocumentAuthor(settings, client=Client()).author(request)
    failure = caught.value
    assert not LessonAuthorFeedback("standard", failure.stage, 1, failure.issues).repairable
