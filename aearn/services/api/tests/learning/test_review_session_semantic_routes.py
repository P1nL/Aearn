from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg.pq import TransactionStatus

from app.main import app
from app.routes import learning_track_reviews as routes
from app.services.learning.practice.fixtures import CuratedExerciseFixture
from app.services.learning.practice.model_review_fixtures import MODEL_REVIEW_FIXTURES
from app.services.learning.practice.model_review_semantics import (
    SemanticReasonCode,
    SemanticReviewReceipt,
    SemanticReviewUnavailable,
    SemanticVerdict,
    StrictSemanticVerdict,
)
from app.services.learning.practice.repository import PostgresExerciseGateRepository
from app.services.learning.reviews.service import ReviewService
from tests.learning.test_review_sessions import _create_scope
from tests.support.teaching_session_support import connection, database_available


def submission(text: str = "count can be zero, so division needs a guard"):
    return {
        "schema_version": "model_code_review_submission_v1",
        "verdict": "correctness_issue",
        "findings": [
            {
                "client_finding_id": "finding-route",
                "finding_kind": "correctness",
                "start_line": 2,
                "end_line": 2,
                "category": "edge_case",
                "severity": "high",
                "trigger_condition": text,
                "principle": text,
                "impact": text,
                "validation_method": text,
                "suggested_fix": text,
            }
        ],
        "supplemental_note": None,
    }


pytestmark = pytest.mark.skipif(
    not database_available(), reason="PostgreSQL unavailable"
)


@pytest.fixture(autouse=True)
def isolated():
    assert os.environ.get("LLM_TYPE") == "disabled"
    with connection() as c:
        assert (
            c.execute("select current_database() name").fetchone()["name"]
            == "aearn_semantic_review_20260909"
        )


def setup_review():
    with connection() as c:
        user, track, schedule = _create_scope(c, with_candidate=False)
        fixture = MODEL_REVIEW_FIXTURES[0]
        exercise = replace(fixture.exercise, required_capabilities=("python",))
        PostgresExerciseGateRepository(c).ensure_curated_fixture(
            CuratedExerciseFixture(exercise=exercise, rubric=fixture.rubric),
            now=__import__("datetime").datetime.now(__import__("datetime").UTC),
        )
        service = ReviewService(c)
        created = service.create_session(
            user_id=user,
            track_id=track,
            knowledge_key="python.variables",
            expected_track_version=1,
            expected_schedule_version=int(schedule["version"]),
            max_items=1,
            idempotency_key=f"create-{uuid4()}",
        )
        current = service.read_session(
            user_id=user, track_id=track, session_id=str(created["session_id"])
        )
        if current["stage"] == "warmup":
            current = service.warmup(
                user_id=user,
                track_id=track,
                session_id=str(created["session_id"]),
                response_kind="skipped",
                confidence=None,
                expected_session_version=int(current["version"]),
                idempotency_key=f"warm-{uuid4()}",
            )
        c.commit()
        return (
            user,
            track,
            str(created["session_id"]),
            str(created["items"][0]["item_id"]),
            int(current["version"]),
        )


@pytest.mark.parametrize(
    "mode,status,outcome",
    [
        ("verified", 200, "passed"),
        ("rejected", 200, "failed"),
        ("unavailable", 503, None),
    ],
)
def test_review_route_semantic_matrix(monkeypatch, mode, status, outcome):
    user, track, session, item, version = setup_review()
    calls = []
    conns = []
    monkeypatch.setattr(routes, "runtime_gate_error", lambda **k: None)
    original = routes.connect

    @contextmanager
    def tracked():
        with original() as c:
            conns.append(c)
            yield c

    monkeypatch.setattr(routes, "connect", tracked)

    class Fake:
        def review(self, request, *, deterministic_pass):
            calls.append(1)
            assert (
                conns[0].closed
                and conns[0].info.transaction_status is TransactionStatus.UNKNOWN
            )
            verdict = (
                SemanticVerdict.VERIFIED
                if mode == "verified"
                else SemanticVerdict.REJECTED
            )
            reason = (
                SemanticReasonCode.AUTHORITY_SUPPORTED
                if mode == "verified"
                else SemanticReasonCode.AUTHORITY_CONTRADICTION
            )
            receipt = SemanticReviewReceipt(
                request.binding_hash,
                StrictSemanticVerdict(verdict=verdict, reason_code=reason),
                "fake",
                None,
            )
            if mode == "unavailable":
                raise SemanticReviewUnavailable(
                    receipt=SemanticReviewReceipt(
                        request.binding_hash,
                        StrictSemanticVerdict(
                            verdict=SemanticVerdict.UNCERTAIN,
                            reason_code=SemanticReasonCode.PROVIDER_UNAVAILABLE,
                        ),
                        None,
                        None,
                    )
                )
            return receipt

    monkeypatch.setattr(routes, "PrimarySemanticReviewer", Fake)
    payload = {
        "user_id": user,
        "client_action_id": f"attempt-{uuid4()}",
        "submission": None,
        "review_submission": submission(),
        "expected_session_version": version,
        "expected_item_version": 1,
    }
    with TestClient(app) as client:
        response = client.post(
            f"/api/learning-tracks/{track}/reviews/sessions/{session}/items/{item}/attempts",
            json=payload,
        )
    assert response.status_code == status
    with connection() as c:
        count = c.execute(
            "select count(*)::int count from tutor_exercise_attempts where review_session_id=%s",
            (session,),
        ).fetchone()["count"]
    assert count == (0 if mode == "unavailable" else 1)
    if outcome:
        assert response.json()["result"]["outcome"] == outcome
    assert len(calls) == 1


def test_review_route_unverified_never_calls_provider(monkeypatch):
    user, track, session, item, version = setup_review()
    calls = []
    monkeypatch.setattr(
        routes,
        "runtime_gate_error",
        lambda **k: type(
            "E",
            (),
            {
                "code": "CUTOVER",
                "message": "no",
                "status_code": 409,
                "details": {},
                "recoverable": True,
            },
        )(),
    )
    monkeypatch.setattr(routes, "PrimarySemanticReviewer", lambda: calls.append(1))
    payload = {
        "user_id": user,
        "client_action_id": f"attempt-{uuid4()}",
        "submission": None,
        "review_submission": submission(),
        "expected_session_version": version,
        "expected_item_version": 1,
    }
    with TestClient(app) as client:
        response = client.post(
            f"/api/learning-tracks/{track}/reviews/sessions/{session}/items/{item}/attempts",
            json=payload,
        )
    assert response.status_code == 409 and not calls


def test_review_route_replay_conflict_and_stale(monkeypatch):
    user, track, session, item, version = setup_review()
    calls = []
    monkeypatch.setattr(routes, "runtime_gate_error", lambda **k: None)

    class Fake:
        def review(self, request, *, deterministic_pass):
            calls.append(1)
            return SemanticReviewReceipt(
                request.binding_hash,
                StrictSemanticVerdict(
                    verdict=SemanticVerdict.VERIFIED,
                    reason_code=SemanticReasonCode.AUTHORITY_SUPPORTED,
                ),
                "fake",
                None,
            )

    monkeypatch.setattr(routes, "PrimarySemanticReviewer", Fake)
    key = f"attempt-{uuid4()}"
    payload = {
        "user_id": user,
        "client_action_id": key,
        "submission": None,
        "review_submission": submission(),
        "expected_session_version": version,
        "expected_item_version": 1,
    }
    with TestClient(app) as client:
        first = client.post(
            f"/api/learning-tracks/{track}/reviews/sessions/{session}/items/{item}/attempts",
            json=payload,
        )
        replay = client.post(
            f"/api/learning-tracks/{track}/reviews/sessions/{session}/items/{item}/attempts",
            json=payload,
        )
        changed = {
            **payload,
            "review_submission": submission("unrelated but bounded explanation"),
        }
        conflict = client.post(
            f"/api/learning-tracks/{track}/reviews/sessions/{session}/items/{item}/attempts",
            json=changed,
        )
    assert (
        first.status_code == 200
        and replay.status_code == 200
        and replay.json()["idempotent_replayed"] is True
    )
    assert conflict.status_code == 409
    assert len(calls) == 1
    user2, track2, session2, item2, version2 = setup_review()
    stale = {
        "user_id": user2,
        "client_action_id": f"stale-{uuid4()}",
        "submission": None,
        "review_submission": submission(),
        "expected_session_version": version2 + 1,
        "expected_item_version": 1,
    }
    with TestClient(app) as client:
        response = client.post(
            f"/api/learning-tracks/{track2}/reviews/sessions/{session2}/items/{item2}/attempts",
            json=stale,
        )
    assert response.status_code == 409
