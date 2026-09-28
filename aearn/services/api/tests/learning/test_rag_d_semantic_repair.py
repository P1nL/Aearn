"""Actual D dispatcher transport/reviewer receipts; both are deterministic fakes."""
from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

import app.routes.tutor as tutor_route
from app.core.config import Settings
from app.db.connection import connect
from app.services.grounding.material_contracts_v2 import DraftScope
from app.services.learning.material_planning_composition import build_internal_material_planning_dispatcher
from app.services.learning.material_semantics import (
    MaterialReviewReceipt, ReviewReason, ReviewVerdict, StrictReviewVerdict,
)
from app.services.learning.plan_repository import PostgresLearningPlanSessionRepository
from app.services.llm.contracts import LLMUsage
from app.services.llm.llm_client import LLMJsonResponse
from app.services.tutor.provider_gateway import PrimaryTutorProviderGateway
from app.agents.harness.contracts import TutorTerminalOutcome
from tests.learning.test_rag_d_planning_consumer import (
    SqlApprovedNodePolicy, SqlFeedbackProvider, SyntheticEvidence,
)
from tests.support.tutor_public_api_support import (
    RecordingTutorDispatcher, action_payload, create_tutor_user,
)

pytest_plugins = ("tests.support.tutor_public_api_support",)


@pytest.fixture
def d_database_guard() -> None:
    url = os.getenv("AEARN_RAG_D_TEST_DATABASE_URL")
    if not url:
        pytest.skip("D semantic integration requires isolated PostgreSQL")
    with psycopg.connect(url, connect_timeout=2) as conn:
        assert conn.execute("SELECT current_database()").fetchone()[0].startswith("aearn_rag260_c_d_")


def _message(text: str) -> dict[str, object]:
    return {"type": "agent_message", "text": text,
            "public_thinking_text": "I will check the exact course material meaning.",
            "conversation_title": None}


def _provider_item(action: dict[str, object], text: str = "Proposing a revised plan.") -> dict[str, object]:
    return {"schema_version": "tutor_provider_items_v5", "message": _message(text), "action": action}


def _sql_candidate(summary: str) -> dict[str, object]:
    data = SqlFeedbackProvider().draft_input().model_dump(exclude_none=True)
    profile = json.loads(data["profile_json"])
    profile["pace_summary"] = summary
    data["profile_json"] = json.dumps(profile, ensure_ascii=False, separators=(",", ":"))
    return _provider_item({"type": "request_capability", "capability_id": "learning.plan.draft",
                           "arguments": [{"key": key, "value": value} for key, value in data.items()]})


class ScriptedClient:
    model = "synthetic-primary-transport"

    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self.payloads = payloads
        self.messages: list[tuple[Mapping[str, str], ...]] = []

    def complete_json(self, messages: Sequence[Mapping[str, str]], **_kwargs: Any) -> LLMJsonResponse:
        self.messages.append(tuple(messages))
        return LLMJsonResponse(content=self.payloads.pop(0), model=self.model,
                               usage=LLMUsage(input_tokens=12, output_tokens=5))


class ScriptedReviewer:
    """A stub with explicit verdicts, not a word-list semantic classifier."""

    def __init__(self, verdicts: list[ReviewVerdict], *, lease_loss: bool = False,
                 usage_known: bool = True) -> None:
        self.verdicts = verdicts
        self.lease_loss = lease_loss
        self.usage_known = usage_known
        self.requests: list[Any] = []

    def review(self, request: Any) -> MaterialReviewReceipt:
        request.assert_binding()
        self.requests.append(request)
        if self.lease_loss:
            with connect() as conn:
                conn.execute("UPDATE tutor_runs SET active_lease_generation=active_lease_generation+1 "
                             "WHERE id=%s", (request.run_id,))
                conn.commit()
        verdict = self.verdicts.pop(0)
        reason = (ReviewReason.SUPPORTED if verdict is ReviewVerdict.CONSISTENT
                  else ReviewReason.INSUFFICIENT_CONTEXT if verdict is ReviewVerdict.UNCERTAIN
                  else ReviewReason.FACET_MEANING_MISMATCH)
        return MaterialReviewReceipt(request.binding_hash,
            StrictReviewVerdict(verdict=verdict, reason_code=reason),
            "synthetic-semantic-reviewer",
            LLMUsage(input_tokens=9, output_tokens=2) if self.usage_known else None)


def _run_semantic_chain(
    *, tutor_client: TestClient, tutor_api_settings: Settings,
    monkeypatch: pytest.MonkeyPatch, verdicts: list[ReviewVerdict],
    assign_feedback: bool = True, custom_provider: bool = False,
    lease_loss: bool = False, usage_known: bool = True,
    wrong_thinking: bool = False,
) -> tuple[str, str, Any, ScriptedClient, ScriptedReviewer]:
    settings = tutor_api_settings.model_copy(update={"tutor_default_context_window_tokens": 16_384,
                                              "tutor_context_max_dynamic_target_tokens": 12_000,
                                              "rag_evidence_consumer_enabled": True})
    monkeypatch.setattr(tutor_route, "get_settings", lambda: settings)
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: RecordingTutorDispatcher())
    user_id = str(create_tutor_user(tutor_client)["id"])
    created = tutor_client.post("/api/learning-plan-sessions", json={
        "user_id": user_id, "client_action_id": "semantic-session-" + user_id,
        "preferred_language_id": "sql"})
    assert created.status_code in {200, 201}
    session = created.json()["session"]
    conversation_id = str(session["conversation_id"])

    def accept(suffix: str) -> dict[str, object]:
        result = tutor_client.post(f"/api/tutor/conversations/{conversation_id}/inputs",
            json=action_payload(user_id, "semantic-" + suffix + user_id,
                content="Revise SQL course using qualified material.",
                learning_scope={"scope_kind": "plan_drafting", "task_kind": "plan_drafting"}))
        assert result.status_code == 202
        return result.json()

    first = accept("first")
    initial = __import__("app.services.tutor.interactive", fromlist=["TutorInteractiveRunDispatcher"])
    initial_result = initial.TutorInteractiveRunDispatcher(
        settings=settings, provider_factory=lambda _settings: SqlFeedbackProvider(),
    ).dispatch(user_id=user_id, run_id=str(first["run_id"]))
    assert initial_result.terminal_outcome is TutorTerminalOutcome.COMPLETED
    second = accept("second")
    with connect() as conn:
        parent = conn.execute("SELECT * FROM tutor_learning_plan_drafts WHERE user_id=%s AND source_run_id=%s",
                              (user_id, str(first["run_id"]))).fetchone()
        assert parent is not None
        scope = DraftScope(user_id=user_id, conversation_id=conversation_id,
            session_id=str(session["session_id"]), draft_id=str(parent["id"]),
            draft_version=parent["draft_version"], content_hash=parent["content_hash"],
            source_run_id=str(first["run_id"]), source_input_revision=int(first["input_revision"]))
        version = int(conn.execute("SELECT version FROM tutor_learning_plan_sessions WHERE id=%s",
                                   (scope.session_id,)).fetchone()["version"])
        PostgresLearningPlanSessionRepository(conn).draft_for_session(
            user_id=user_id, session_id=scope.session_id, draft_id=scope.draft_id)
        from app.services.learning.material_selection import PostgresMaterialPlanningConsumer
        consumer = PostgresMaterialPlanningConsumer(
            conn, authority=SyntheticEvidence(conn, ready=True), requirements=SqlApprovedNodePolicy())
        if assign_feedback:
            consumer.assign_parent_feedback(parent=scope, target_run_id=str(second["run_id"]),
                target_input_revision=int(second["input_revision"]), expected_session_version=version)
        conn.commit()

    wrong = _sql_candidate("Missing WHERE details mean I need the learner's study location.")
    fixed = _sql_candidate("SQL WHERE filtering material is admitted for these course topics.")
    if wrong_thinking:
        wrong = _sql_candidate("SQL WHERE filtering material is admitted for these course topics.")
        wrong["message"] = _message("SQL WHERE course material review is pending.")
        wrong["message"]["public_thinking_text"] = "WHERE details mean the learner's study location."
    payloads = [
        _provider_item({"type": "select_skill", "skill_id": "tutor.learning-plan-draft",
                        "version": "1.1.0"}), wrong,
        fixed if ReviewVerdict.CONSISTENT in verdicts else wrong,
        _provider_item({"type": "turn_completed"}),
    ]
    client = ScriptedClient(payloads)
    reviewer = ScriptedReviewer(verdicts, lease_loss=lease_loss, usage_known=usage_known)
    dispatcher = build_internal_material_planning_dispatcher(
        settings, server_opt_in=True, requirements=SqlApprovedNodePolicy(),
        evidence_factory=lambda conn: SyntheticEvidence(conn, ready=True),
        semantic_reviewer=reviewer,
        provider_factory=(lambda _config: SqlFeedbackProvider()) if custom_provider else
                         (lambda config: PrimaryTutorProviderGateway(settings=config, client=client)),
    )
    result = dispatcher.dispatch(user_id=user_id, run_id=str(second["run_id"]))
    return user_id, str(second["run_id"]), result, client, reviewer


def test_actual_dispatcher_wrong_sql_where_meaning_repairs_before_successor(
    d_database_guard: None, tutor_client: TestClient, tutor_api_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id, run_id, outcome, client, reviewer = _run_semantic_chain(
        tutor_client=tutor_client, tutor_api_settings=tutor_api_settings,
        monkeypatch=monkeypatch,
        verdicts=[ReviewVerdict.INCONSISTENT, ReviewVerdict.CONSISTENT],
    )
    assert outcome.terminal_outcome is TutorTerminalOutcome.COMPLETED
    assert len(reviewer.requests) == 2 and len(client.messages) == 4
    assert "material_facet_meaning_mismatch" in client.messages[2][-1]["content"]
    assert "course material topics and purposes" in client.messages[2][-1]["content"]
    assert "Revise the same learning.plan.draft capability" in client.messages[2][-1]["content"]
    authority = json.loads(reviewer.requests[0].authority_json)
    assert authority["requirements"][0]["subject"] == "route.sql"
    assert len(authority["requirements"]) == len(authority["outcomes"]) == 2
    assert "study location" in reviewer.requests[0].candidate_json
    with connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM rag_material_semantic_reviews "
                            "WHERE run_id=%s", (run_id,)).fetchone()["n"] == 2
        assert conn.execute("SELECT count(*) AS n FROM tutor_learning_plan_drafts "
                            "WHERE user_id=%s AND source_run_id=%s", (user_id,run_id)).fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) AS n FROM rag_plan_material_bindings b "
                            "JOIN tutor_learning_plan_drafts d ON d.id=b.draft_id "
                            "WHERE d.source_run_id=%s", (run_id,)).fetchone()["n"] == 2


def test_actual_dispatcher_review_exhaustion_writes_no_successor_or_binding(
    d_database_guard: None, tutor_client: TestClient, tutor_api_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id, run_id, outcome, client, reviewer = _run_semantic_chain(
        tutor_client=tutor_client, tutor_api_settings=tutor_api_settings,
        monkeypatch=monkeypatch,
        verdicts=[ReviewVerdict.INCONSISTENT, ReviewVerdict.INCONSISTENT],
    )
    assert outcome.terminal_outcome is TutorTerminalOutcome.MODEL_UNAVAILABLE
    assert len(reviewer.requests) == 2 and len(client.messages) == 3
    with connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM rag_material_semantic_reviews "
                            "WHERE run_id=%s AND verdict='inconsistent'", (run_id,)).fetchone()["n"] == 2
        assert conn.execute("SELECT count(*) AS n FROM tutor_learning_plan_drafts "
                            "WHERE user_id=%s AND source_run_id=%s", (user_id,run_id)).fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM rag_plan_material_bindings b "
                            "JOIN tutor_learning_plan_drafts d ON d.id=b.draft_id "
                            "WHERE d.source_run_id=%s", (run_id,)).fetchone()["n"] == 0


def test_actual_dispatcher_uncertain_review_is_terminal_and_audited(
    d_database_guard: None, tutor_client: TestClient, tutor_api_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id, run_id, outcome, client, reviewer = _run_semantic_chain(
        tutor_client=tutor_client, tutor_api_settings=tutor_api_settings,
        monkeypatch=monkeypatch, verdicts=[ReviewVerdict.UNCERTAIN],
    )
    assert outcome.terminal_outcome is TutorTerminalOutcome.MODEL_UNAVAILABLE
    assert len(reviewer.requests) == 1 and len(client.messages) == 2
    with connect() as conn:
        row = conn.execute("SELECT verdict,reason_code,usage_json FROM rag_material_semantic_reviews "
                           "WHERE run_id=%s", (run_id,)).fetchone()
        assert row is not None and row["verdict"] == "uncertain"
        assert row["reason_code"] == "insufficient_context"
        assert row["usage_json"]["input_tokens"] == 9
        assert conn.execute("SELECT count(*) AS n FROM tutor_learning_plan_drafts "
                            "WHERE user_id=%s AND source_run_id=%s", (user_id,run_id)).fetchone()["n"] == 0


def test_semantic_receipt_rejects_wrong_candidate_and_wrong_run(
    d_database_guard: None, tutor_client: TestClient, tutor_api_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from app.services.grounding.material_binding_repository import MaterialBindingStale
    from app.services.grounding.material_contracts_v2 import MaterialSelectionResult
    from app.services.learning.material_selection import PostgresMaterialPlanningConsumer
    from app.services.tutor.persistence import PostgresTutorRepository

    user_id, run_id, outcome, _client, _reviewer = _run_semantic_chain(
        tutor_client=tutor_client, tutor_api_settings=tutor_api_settings,
        monkeypatch=monkeypatch,
        verdicts=[ReviewVerdict.INCONSISTENT, ReviewVerdict.CONSISTENT],
    )
    assert outcome.terminal_outcome is TutorTerminalOutcome.COMPLETED
    with connect() as conn:
        snapshot = PostgresTutorRepository(conn).load_snapshot(user_id=user_id, run_id=run_id)
        assert snapshot is not None
        row = conn.execute("SELECT s.handle,s.snapshot_json,s.draft_id,d.session_id,d.user_id,s.conversation_id,"
                           "d.draft_version,d.content_hash,d.source_run_id,d.source_input_revision "
                           "FROM rag_material_selections s JOIN tutor_learning_plan_drafts d "
                           "ON d.id=s.draft_id WHERE s.target_run_id=%s", (run_id,)).fetchone()
        assert row is not None
        scope = DraftScope(user_id=user_id, conversation_id=str(row["conversation_id"]),
            session_id=str(row["session_id"]), draft_id=str(row["draft_id"]),
            draft_version=row["draft_version"], content_hash=row["content_hash"],
            source_run_id=str(row["source_run_id"]),
            source_input_revision=row["source_input_revision"])
        selection = MaterialSelectionResult.model_validate_json(json.dumps(row["snapshot_json"]))
        assert selection.draft == scope and selection.handle == row["handle"]
        parent = PostgresLearningPlanSessionRepository(conn).draft_for_session(
            user_id=user_id, session_id=scope.session_id, draft_id=scope.draft_id)
        consumer = PostgresMaterialPlanningConsumer(
            conn, authority=SyntheticEvidence(conn, ready=True),
            requirements=SqlApprovedNodePolicy())
        altered = SqlFeedbackProvider().draft_input()
        with pytest.raises(MaterialBindingStale, match="exact material semantic review"):
            consumer.assert_review_before_append(snapshot, altered, parent, selection)
        with pytest.raises(MaterialBindingStale, match="exact material semantic review"):
            consumer.assert_review_before_append(replace(snapshot, run_id=str(uuid4())),
                                                 altered, parent, selection)


@pytest.mark.parametrize("custom_provider", [False, True])
def test_d_existing_draft_without_assigned_feedback_cannot_bypass_review(
    d_database_guard: None, tutor_client: TestClient, tutor_api_settings: Settings,
    monkeypatch: pytest.MonkeyPatch, custom_provider: bool,
) -> None:
    user_id, run_id, outcome, client, reviewer = _run_semantic_chain(
        tutor_client=tutor_client, tutor_api_settings=tutor_api_settings,
        monkeypatch=monkeypatch, verdicts=[ReviewVerdict.CONSISTENT],
        assign_feedback=False, custom_provider=custom_provider,
    )
    assert outcome.terminal_outcome is not TutorTerminalOutcome.COMPLETED
    assert not reviewer.requests and not client.messages
    with connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM tutor_learning_plan_drafts "
                            "WHERE user_id=%s AND source_run_id=%s", (user_id,run_id)).fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM rag_plan_material_bindings b "
                            "JOIN tutor_learning_plan_drafts d ON d.id=b.draft_id "
                            "WHERE d.source_run_id=%s", (run_id,)).fetchone()["n"] == 0


def test_exact_attempt_replay_reuses_review_without_second_billed_call(
    d_database_guard: None, tutor_client: TestClient, tutor_api_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.learning.material_selection import PostgresMaterialPlanningConsumer
    original = PostgresMaterialPlanningConsumer.review_decision

    def replay(self: PostgresMaterialPlanningConsumer, run: Any, decision: Any,
               attempt_index: int) -> str | None:
        result = original(self, run, decision, attempt_index)
        if decision.capability_requests:
            assert original(self, run, decision, attempt_index) == result
        return result

    monkeypatch.setattr(PostgresMaterialPlanningConsumer, "review_decision", replay)
    _user_id, _run_id, outcome, _client, reviewer = _run_semantic_chain(
        tutor_client=tutor_client, tutor_api_settings=tutor_api_settings,
        monkeypatch=monkeypatch,
        verdicts=[ReviewVerdict.INCONSISTENT, ReviewVerdict.CONSISTENT],
    )
    assert outcome.terminal_outcome is TutorTerminalOutcome.COMPLETED
    assert len(reviewer.requests) == 2


@pytest.mark.parametrize("usage_known", [True, False])
def test_review_usage_audit_survives_lease_loss_without_authorizing_append(
    d_database_guard: None, tutor_client: TestClient, tutor_api_settings: Settings,
    monkeypatch: pytest.MonkeyPatch, usage_known: bool,
) -> None:
    user_id, run_id, outcome, _client, reviewer = _run_semantic_chain(
        tutor_client=tutor_client, tutor_api_settings=tutor_api_settings,
        monkeypatch=monkeypatch, verdicts=[ReviewVerdict.CONSISTENT],
        lease_loss=True, usage_known=usage_known,
    )
    assert outcome.terminal_outcome is not TutorTerminalOutcome.COMPLETED
    assert len(reviewer.requests) == 1
    with connect() as conn:
        audit = conn.execute("SELECT review_status,verdict,usage_json FROM rag_material_semantic_reviews "
                             "WHERE run_id=%s", (run_id,)).fetchone()
        assert audit is not None and audit["review_status"] == "settled"
        assert audit["verdict"] == "consistent"  # Recorded result is not an eligible grant.
        assert (audit["usage_json"] is not None) is usage_known
        assert conn.execute("SELECT count(*) AS n FROM tutor_learning_plan_drafts "
                            "WHERE user_id=%s AND source_run_id=%s", (user_id,run_id)).fetchone()["n"] == 0


def test_candidate_public_thinking_is_in_semantic_review_input(
    d_database_guard: None, tutor_client: TestClient, tutor_api_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _user_id, _run_id, outcome, _client, reviewer = _run_semantic_chain(
        tutor_client=tutor_client, tutor_api_settings=tutor_api_settings,
        monkeypatch=monkeypatch,
        verdicts=[ReviewVerdict.INCONSISTENT, ReviewVerdict.CONSISTENT],
        wrong_thinking=True,
    )
    assert outcome.terminal_outcome is TutorTerminalOutcome.COMPLETED
    assert "study location" in reviewer.requests[0].candidate_json
    assert "public_thinking_text" in reviewer.requests[0].candidate_json
