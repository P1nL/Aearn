"""Offline review regressions for the private Lesson response diagnostic boundary."""
from contextlib import nullcontext
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.services.learning import lesson_authoring as authoring
from app.services.learning.lesson_authoring_feedback import (
    attempt_diagnostic,
    validate_attempt_diagnostic,
)
from app.services.learning.lesson_repository import PostgresLessonDocumentRepository
from app.services.llm.contracts import LLMResponseDiagnostics, LLMUsage
from app.services.llm.llm_client import LLMInvalidResponseError, LLMInvalidResponseKind, LLMJsonResponse
from tests.support.lesson_document_support import (
    CITATION_ID,
    author_candidate_payload,
    sample_source_snapshot,
)


def _request():
    evidence = authoring.LessonAuthoringEvidence(
        "S1", "Python", "Python", "official", "3", "rolling", (), "Names bind values.",
    )
    return authoring.LessonAuthoringRequest(
        "standard", "python", "python.variables", "Variables", "Learn", "beginner",
        (), "unseen", 0, (evidence,), citation_handles=(("S1", CITATION_ID),),
    )


def _primary(client):
    settings = Settings(
        llm_type="deepseek", deepseek_model="deepseek-v4-flash",
        deepseek_api_key="offline-test-key", deepseek_base_url="https://provider.invalid",
    )
    return authoring.PrimaryLessonDocumentAuthor(settings, client=client)


@pytest.mark.parametrize("reason", [None, "unknown", "content_filter", "context_length_exceeded"])
def test_nonrepairable_incomplete_stops_before_second_call(monkeypatch, reason):
    receipts = []
    run = _offline_repository(monkeypatch, receipts)
    calls = []
    metadata = LLMResponseDiagnostics(response_status="incomplete", incomplete_reason=reason)

    class Client:
        def complete_json(self, messages, **kwargs):
            calls.append(messages)
            raise LLMInvalidResponseError(
                "PRIVATE_PROVIDER_BODY", kind=LLMInvalidResponseKind.RESPONSE_INCOMPLETE,
                response_diagnostics=metadata,
            )

    budget = authoring._RepairBudget(next_attempt=1, remaining=1)
    with pytest.raises(authoring.LessonAuthoringFailure):
        _invoke(_primary(Client()), _request(), run, budget)
    assert len(calls) == len(receipts) == 1
    assert budget.remaining == 1
    diagnostic = receipts[0]["diagnostic"]
    assert diagnostic["issue_codes"] == ["LESSON_PROVIDER_RESPONSE_INCOMPLETE_NONREPAIRABLE"]
    assert diagnostic["provider_response"]["incomplete_reason"] == reason
    assert "PRIVATE_PROVIDER_BODY" not in json.dumps(diagnostic)


def _offline_repository(monkeypatch, receipts):
    class Repository:
        def __init__(self, conn):
            pass

        def assert_authoring_current(self, **kwargs):
            pass

        def evidence_is_current(self, snapshots):
            return True

        def record_authoring_attempt(self, **kwargs):
            receipts.append(kwargs)

    connection = SimpleNamespace(transaction=lambda: nullcontext())
    monkeypatch.setattr(authoring, "connect", lambda: nullcontext(connection))
    monkeypatch.setattr(authoring, "PostgresLessonDocumentRepository", Repository)
    return SimpleNamespace(run_id="offline-review-run")


def _invoke(port, request, run, budget):
    return authoring._author_and_validate(
        port=port, request=request, run=run, budget=budget,
        handles={"S1": CITATION_ID}, snapshots=(sample_source_snapshot(),),
    )


@pytest.mark.parametrize("first_repair_kind", ["provider", "candidate"])
def test_provider_and_candidate_repair_share_one_budget_across_documents(monkeypatch, first_repair_kind):
    receipts = []
    run = _offline_repository(monkeypatch, receipts)
    calls = []
    metadata = LLMResponseDiagnostics(
        response_status="incomplete", incomplete_reason="max_output_tokens",
        requested_max_output_tokens=12000, requested_reasoning_effort="none", visible_output_chars=42,
    )

    class Client:
        def complete_json(self, messages, **kwargs):
            calls.append((messages, kwargs))
            if len(calls) == 1 and first_repair_kind == "candidate":
                return LLMJsonResponse(content={"PRIVATE_REJECTED_FIELD": "PRIVATE_VALUE"}, model="offline")
            if len(calls) != 2:
                raise LLMInvalidResponseError(
                    "PRIVATE_PROVIDER_BODY", kind=LLMInvalidResponseKind.RESPONSE_INCOMPLETE,
                    usage=LLMUsage(output_tokens=12000, reasoning_tokens=100),
                    response_diagnostics=metadata,
                )
            return LLMJsonResponse(content=author_candidate_payload(), model="offline")

    port = _primary(Client())
    request = _request()
    budget = authoring._RepairBudget(next_attempt=1, remaining=1)
    standard, _ = _invoke(port, request, run, budget)
    with pytest.raises(authoring.LessonAuthoringFailure):
        _invoke(port, replace(request, document_kind="personalized", standard_document=standard), run, budget)
    assert len(calls) == len(receipts) == 3
    assert budget.remaining == 0
    assert [receipt["outcome"] for receipt in receipts] == ["invalid", "success", "invalid"]
    assert [receipt["attempt_index"] for receipt in receipts] == [1, 2, 3]
    assert [receipt["diagnostic"]["document_attempt_index"] for receipt in receipts] == [1, 2, 1]
    assert all(kwargs["thinking_mode"] == "disabled" for _, kwargs in calls)
    assert all(kwargs["max_tokens"] == 12000 for _, kwargs in calls)
    retry_messages = json.dumps(calls[1][0])
    assert "lesson_author_feedback_v1" in retry_messages
    assert "PRIVATE_" not in retry_messages
    assert receipts[-1]["diagnostic"]["reasoning_tokens"] == 100


@pytest.mark.parametrize("diagnostic", [None, {}, attempt_diagnostic("standard", 1)])
def test_legacy_nullable_diagnostic_is_normalized_by_repository_without_database(monkeypatch, diagnostic):
    writes = []
    run = SimpleNamespace(run_id="run", user_id="user", state="running", lease_generation=1)
    connection = SimpleNamespace(execute=lambda sql, params: writes.append((sql, params)))
    monkeypatch.setattr(PostgresLessonDocumentRepository, "read_authoring_run", lambda *args, **kwargs: run)
    PostgresLessonDocumentRepository(connection).record_authoring_attempt(
        run=run, attempt_index=1, provider="offline", model="offline", protocol="responses",
        outcome="success", diagnostic_code=None, usage=None, request_hash="a" * 64,
        response_hash=None, diagnostic=diagnostic,
    )
    assert writes[0][1][-1].obj == (diagnostic or {})


def test_usage_only_v2_preserves_zero_without_inventing_provider_fields():
    diagnostic = attempt_diagnostic("standard", 1, usage=LLMUsage(reasoning_tokens=0))
    assert diagnostic["schema_version"] == "lesson_author_attempt_diagnostic_v2"
    assert diagnostic["provider_response"] is None
    assert diagnostic["reasoning_tokens"] == 0
    assert validate_attempt_diagnostic(diagnostic) == diagnostic
