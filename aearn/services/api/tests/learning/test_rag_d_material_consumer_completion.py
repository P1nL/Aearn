"""Offline consumer control flow only; no PG fixture, bootstrap, or HTTP."""
from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from psycopg import Connection
from psycopg.pq import TransactionStatus

from app.agents.harness.contracts import (
    TutorCapabilityRequest, TutorDecision, TutorExecutionProfile,
    TutorPolicySnapshot, TutorRunSnapshot, payload_fields_from_mapping,
)
from app.services.grounding.material_binding_repository import MaterialBindingStale
from app.services.learning import material_selection as material
from app.services.learning.material_semantics import (
    MaterialReviewReceipt, MaterialReviewRequest, ReviewReason, ReviewVerdict, StrictReviewVerdict,
)
from app.services.llm.contracts import LLMResponseDiagnostics, LLMUsage
from app.services.llm.http_execution import LLMHTTPExecution, LLMHTTPExecutionError, use_http_execution


class _Cursor:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row

    def fetchone(self) -> dict[str, Any] | None:
        return self.row


class _OfflineConnection:
    """Small statement recorder, not a DB emulator or SQL acceptance fixture."""

    def __init__(self) -> None:
        self.autocommit = True
        self.info = SimpleNamespace(transaction_status=TransactionStatus.IDLE)
        self.in_transaction = False
        self.row: dict[str, Any] | None = None
        self.statements: list[str] = []
        self.commits = 0

    @contextmanager
    def transaction(self) -> Iterator[None]:
        assert not self.in_transaction
        self.in_transaction = True
        try:
            yield
            self.commits += 1
        finally:
            self.in_transaction = False

    def rollback(self) -> None:
        raise AssertionError("offline tests must not need a driver rollback")

    def execute(self, sql: str, params: Sequence[Any]) -> _Cursor:
        assert self.in_transaction
        self.statements.append(sql)
        if sql.startswith("SELECT * FROM rag_material_semantic_reviews"):
            return _Cursor(self.row)
        if sql.startswith("INSERT INTO rag_material_semantic_reviews"):
            assert self.row is None
            self.row = {
                "id": "offline-review", "review_status": "dispatched",
                "selection_handle": params[6], "selection_digest": params[7],
                "candidate_digest": params[9], "request_binding_hash": params[12],
                "verdict": "uncertain", "reason_code": "insufficient_context",
                "reviewer_model": None, "usage_json": None,
            }
            return _Cursor(None)
        if sql.startswith("UPDATE rag_material_semantic_reviews SET review_status='settled'"):
            assert self.row is not None and self.row["review_status"] == "dispatched"
            self.row.update(
                review_status="settled", verdict=params[0], reason_code=params[1],
                reviewer_model=params[2], usage_json=params[3].obj if params[3] is not None else None,
            )
            return _Cursor({"id": self.row["id"]})
        raise AssertionError("unexpected SQL in isolated consumer test")


class _Reviewer:
    def __init__(self, conn: _OfflineConnection, error: Exception | None = None) -> None:
        self.conn, self.error = conn, error
        self.requests: list[MaterialReviewRequest] = []

    def review(self, request: MaterialReviewRequest) -> MaterialReviewReceipt:
        assert not self.conn.in_transaction and self.conn.autocommit
        assert self.conn.commits >= 2
        assert self.conn.row is not None and self.conn.row["review_status"] == "dispatched"
        request.assert_binding()
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return MaterialReviewReceipt(
            request.binding_hash,
            StrictReviewVerdict(verdict=ReviewVerdict.CONSISTENT, reason_code=ReviewReason.SUPPORTED),
            "offline-semantic", LLMUsage(input_tokens=7, output_tokens=2),
        )


def _consumer(
    monkeypatch: pytest.MonkeyPatch, *, profile: TutorExecutionProfile | None = TutorExecutionProfile.COMPLETION_DRIVEN_V1,
    error: Exception | None = None,
) -> tuple[material.PostgresMaterialPlanningConsumer, _OfflineConnection, _Reviewer, TutorRunSnapshot, TutorDecision]:
    conn = _OfflineConnection()
    reviewer = _Reviewer(conn, error)
    consumer = material.PostgresMaterialPlanningConsumer(
        cast(Connection[Any], conn), authority=Mock(), requirements=Mock(), semantic_reviewer=reviewer,
    )
    # Current/source authority and repositories are unrelated dependencies here;
    # keep actual consumer request binding, attempt lookup, and exception paths.
    draft = SimpleNamespace(session_id="offline-session", draft_id="offline-draft", content_hash="b" * 64)
    feedback = (SimpleNamespace(draft=draft), SimpleNamespace(
        draft=draft, selection_digest="a" * 64, handle="offline-selection",
    ))
    monkeypatch.setattr(consumer, "_assert_review_run_current", lambda _run: None)
    monkeypatch.setattr(consumer, "_feedback", lambda *_args: feedback)
    monkeypatch.setattr(consumer, "_plans", SimpleNamespace(
        active_session_for_run=lambda **_kwargs: {"current_draft_id": draft.draft_id},
        draft_for_session=lambda **_kwargs: {"profile_json": {}, "plan_json": {}},
    ))
    monkeypatch.setattr(material, "material_review_authority", lambda *_args: {"course_fact": "SQL filtering"})
    run = TutorRunSnapshot(
        run_id="00000000-0000-0000-0000-000000000001", conversation_id="offline-conversation",
        user_id="offline-user", input_revision=1, origin="interactive",
        policy=TutorPolicySnapshot(deadline=datetime(2030, 1, 1, tzinfo=UTC), execution_profile=profile),
    )
    decision = TutorDecision(capability_requests=(TutorCapabilityRequest(
        request_id="offline-request", capability_id="learning.plan.draft",
        arguments=payload_fields_from_mapping(
            dict.fromkeys(("profile_json", "module_1", "module_2"), "{}"), capability_id="learning.plan.draft",
        ),
    ),))
    return consumer, conn, reviewer, run, decision


def _unknown(*, usage: bool = True) -> LLMHTTPExecutionError:
    error = LLMHTTPExecutionError("request_timeout", outcome_unknown=True, physical_attempts=3)
    error.usage = LLMUsage(input_tokens=23) if usage else None
    error.model = "observed-semantic-model"
    error.response_diagnostics = LLMResponseDiagnostics(response_status="missing_terminal", requested_max_output_tokens=256)
    return error


@pytest.mark.parametrize("usage", [True, False])
def test_completion_unknown_preserves_signal_and_blocks_cold_replay(
    monkeypatch: pytest.MonkeyPatch, usage: bool,
) -> None:
    original = _unknown(usage=usage)
    consumer, conn, reviewer, run, decision = _consumer(monkeypatch, error=original)
    with pytest.raises(material.MaterialSemanticReviewOutcomeUnknown) as caught:
        consumer.review_decision(run, decision, 1)
    error = caught.value
    assert isinstance(error, LLMHTTPExecutionError) and error.outcome_unknown
    assert error.reason == "material_review_outcome_unknown"
    assert error.physical_attempts == 3 and not error.from_dispatched_receipt
    assert error.usage is original.usage and error.model == original.model
    assert error.response_diagnostics is original.response_diagnostics
    assert error.__cause__ is original
    assert conn.row is not None and conn.row["review_status"] == "dispatched"
    assert error.request_binding_hash == conn.row["request_binding_hash"]
    assert len(reviewer.requests) == 1 and not any(sql.startswith("UPDATE") for sql in conn.statements)
    with pytest.raises(material.MaterialSemanticReviewOutcomeUnknown) as cold:
        consumer.review_decision(run, decision, 1)
    assert cold.value.reason == "material_review_dispatched_unknown"
    assert cold.value.from_dispatched_receipt and cold.value.outcome_unknown
    # No active scope: zero new observations, NOT a historical zero-send claim.
    assert cold.value.physical_attempts == 0 and cold.value.usage is None
    assert cold.value.request_binding_hash == error.request_binding_hash
    assert len(reviewer.requests) == 1
    assert sum(sql.startswith("INSERT") for sql in conn.statements) == 1
    assert not any(sql.startswith("UPDATE") for sql in conn.statements)


def test_dispatched_cold_read_blocks_without_reviewer_and_keeps_current_counter(monkeypatch: pytest.MonkeyPatch) -> None:
    consumer, conn, reviewer, run, decision = _consumer(monkeypatch, error=_unknown())
    with pytest.raises(material.MaterialSemanticReviewOutcomeUnknown):
        consumer.review_decision(run, decision, 1)
    monkeypatch.setattr(consumer, "_semantic_reviewer", None)
    execution = LLMHTTPExecution(lambda: 90, lambda: None, execution_profile=TutorExecutionProfile.COMPLETION_DRIVEN_V1)
    execution.physical_attempts = 4
    with use_http_execution(execution), pytest.raises(material.MaterialSemanticReviewOutcomeUnknown) as caught:
        consumer.review_decision(run, decision, 1)
    assert caught.value.outcome_unknown and caught.value.from_dispatched_receipt
    assert caught.value.physical_attempts == execution.physical_attempts == 4
    assert len(reviewer.requests) == 1
    assert conn.row is not None and conn.row["review_status"] == "dispatched"


@pytest.mark.parametrize("usage", [{"input_tokens": 17}, {"input_tokens": True}])
def test_dispatched_cold_usage_never_changes_unknown(
    monkeypatch: pytest.MonkeyPatch, usage: dict[str, Any],
) -> None:
    consumer, conn, reviewer, run, decision = _consumer(monkeypatch, error=_unknown())
    with pytest.raises(material.MaterialSemanticReviewOutcomeUnknown):
        consumer.review_decision(run, decision, 1)
    assert conn.row is not None
    conn.row.update(usage_json=usage, reviewer_model="saved-semantic-model")
    with pytest.raises(material.MaterialSemanticReviewOutcomeUnknown) as caught:
        consumer.review_decision(run, decision, 1)
    assert caught.value.outcome_unknown and caught.value.model == "saved-semantic-model"
    assert caught.value.usage == (LLMUsage(input_tokens=17) if usage["input_tokens"] == 17 else None)
    assert len(reviewer.requests) == 1 and conn.row["review_status"] == "dispatched"


@pytest.mark.parametrize("profile", [None, TutorExecutionProfile.MVP_TEACHING_V1])
def test_legacy_unknown_retains_original_uncertain_contract(
    monkeypatch: pytest.MonkeyPatch, profile: TutorExecutionProfile | None,
) -> None:
    consumer, conn, reviewer, run, decision = _consumer(monkeypatch, profile=profile, error=_unknown())
    assert consumer.review_decision(run, decision, 1) == "material_review_uncertain_provider_unavailable"
    assert conn.row is not None and conn.row["review_status"] == "settled"
    assert conn.row["usage_json"] is conn.row["reviewer_model"] is None
    assert consumer.review_decision(run, decision, 1) == "material_review_uncertain_provider_unavailable"
    assert len(reviewer.requests) == 1


def test_legacy_dispatched_receipt_retains_original_denial(monkeypatch: pytest.MonkeyPatch) -> None:
    consumer, conn, reviewer, run, decision = _consumer(monkeypatch)
    assert consumer.review_decision(run, decision, 1) is None
    assert conn.row is not None
    conn.row["review_status"] = "dispatched"
    legacy = TutorRunSnapshot(
        run_id=run.run_id, conversation_id=run.conversation_id, user_id=run.user_id,
        input_revision=1, origin="interactive", policy=TutorPolicySnapshot(deadline=run.policy.deadline),
    )
    assert consumer.review_decision(legacy, decision, 1) == "material_review_uncertain_incomplete_dispatch"
    assert len(reviewer.requests) == 1


def test_new_known_transport_failure_retains_usage_without_inventing_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    original = LLMHTTPExecutionError("http_error", outcome_unknown=False, physical_attempts=1)
    original.usage, original.model = LLMUsage(input_tokens=5), "known-semantic-model"
    consumer, conn, reviewer, run, decision = _consumer(monkeypatch, error=original)
    assert consumer.review_decision(run, decision, 1) == "material_review_uncertain_provider_unavailable"
    assert conn.row is not None and conn.row["review_status"] == "settled"
    assert conn.row["usage_json"] == {"input_tokens": 5, "cached_input_tokens": None,
        "output_tokens": None, "total_tokens": None, "reasoning_tokens": None}
    assert conn.row["reviewer_model"] == original.model and len(reviewer.requests) == 1


def test_generic_failure_is_not_relabelled_execution_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    consumer, conn, reviewer, run, decision = _consumer(monkeypatch, error=RuntimeError("ordinary failure"))
    assert consumer.review_decision(run, decision, 1) == "material_review_uncertain_provider_unavailable"
    assert conn.row is not None and conn.row["review_status"] == "settled"
    assert len(reviewer.requests) == 1


def test_new_missing_reviewer_without_prior_does_not_create_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    consumer, conn, reviewer, run, decision = _consumer(monkeypatch)
    monkeypatch.setattr(consumer, "_semantic_reviewer", None)
    assert consumer.review_decision(run, decision, 1) == "material_review_uncertain_unavailable"
    assert conn.row is None and not reviewer.requests
    assert not any(sql.startswith(("INSERT", "UPDATE")) for sql in conn.statements)


def test_new_settled_result_still_reuses_without_reviewer(monkeypatch: pytest.MonkeyPatch) -> None:
    consumer, conn, reviewer, run, decision = _consumer(monkeypatch)
    assert consumer.review_decision(run, decision, 1) is None
    monkeypatch.setattr(consumer, "_semantic_reviewer", None)
    assert consumer.review_decision(run, decision, 1) is None
    assert conn.row is not None and conn.row["review_status"] == "settled"
    assert len(reviewer.requests) == 1


def test_cold_binding_conflict_remains_a_conflict_not_a_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    consumer, conn, reviewer, run, decision = _consumer(monkeypatch, error=_unknown())
    with pytest.raises(material.MaterialSemanticReviewOutcomeUnknown):
        consumer.review_decision(run, decision, 1)
    assert conn.row is not None
    conn.row["request_binding_hash"] = "d" * 64
    with pytest.raises(MaterialBindingStale, match="conflicts"):
        consumer.review_decision(run, decision, 1)
    assert len(reviewer.requests) == 1 and conn.row["review_status"] == "dispatched"
