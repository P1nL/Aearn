from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.db.connection import connect
from app.main import app
from app.services.learning.contracts import MasteryEvidence, MasteryEvidenceKind, MasteryIndependence
from app.services.learning.practice.contracts import (
    ExercisePrivateRubric,
    ExerciseSourceKind,
    ExerciseType,
    ExerciseVersion,
)
from app.services.learning.practice.fixtures import CuratedExerciseFixture
from app.services.learning.practice.quality import require_exercise_quality
from app.services.learning.practice.repository import PostgresExerciseGateRepository
from app.services.learning.track_repository import PostgresLearningTrackRepository
from tests.support.learning_track_support import sample_plan_payload
from tests.support.tutor_public_api_support import assert_error


def _database_available() -> bool:
    try:
        with psycopg.connect(get_settings().database_url, connect_timeout=2) as conn:
            conn.execute("select 1")
        return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(
    not _database_available(),
    reason="PostgreSQL is required for ReviewSession API tests.",
)


@pytest.fixture()
def review_client() -> Iterator[TestClient]:
    bootstrap_database()
    with TestClient(app) as client:
        yield client


def _create_user(client: TestClient) -> str:
    response = client.post(
        "/api/users",
        json={"display_name": f"Review API {uuid4().hex[:10]}"},
    )
    assert response.status_code == 201
    user_id = str(response.json()["user"]["id"])
    cutover = client.get(f"/api/harness/cutover?user_id={user_id}")
    assert cutover.status_code == 200
    assert cutover.json()["state"] == "verified"
    return user_id


def _create_due_track(client: TestClient, user_id: str) -> tuple[str, int, int]:
    created = client.post(
        "/api/learning-tracks",
        json={
            "user_id": user_id,
            "client_action_id": f"review-track-{uuid4()}",
            "language_id": "python",
            "goal_text": "使用 API 复习 Python",
            "target_level": "beginner",
            "plan": sample_plan_payload(),
        },
    )
    assert created.status_code == 201
    track = created.json()["track"]
    track_id = str(track["track_id"])
    with connect() as conn:
        evidence = MasteryEvidence(
            evidence_id=str(uuid4()),
            knowledge_key="python.variables",
            evidence_kind=MasteryEvidenceKind.GATE,
            source_receipt_id=f"review-api-gate-{uuid4()}",
            source_receipt_hash="d" * 64,
            independence=MasteryIndependence.INDEPENDENT,
            score=0.9,
            hint_count=0,
            attempt_count=1,
            summary={"strengths": ["python"]},
            created_at=datetime.now(UTC) - timedelta(days=8),
        )
        PostgresLearningTrackRepository(conn).append_mastery_evidence(
            user_id=user_id,
            track_id=track_id,
            evidence=evidence,
        )
        schedule = conn.execute(
            """UPDATE tutor_review_schedule_states
            SET due_at = %s, version = version + 1
            WHERE user_id = %s AND track_id = %s AND knowledge_key = 'python.variables'
            RETURNING version""",
            (datetime.now(UTC) - timedelta(minutes=1), user_id, track_id),
        ).fetchone()
        assert schedule is not None
        exercise = ExerciseVersion(
            language_id="python",
            exercise_key=f"python.api.review.{uuid4().hex[:12]}",
            exercise_type=ExerciseType.STATIC_CODE_REASONING,
            version="v1",
            source_kind=ExerciseSourceKind.CURATED_FIXTURE,
            title="API 变量回忆",
            learner_prompt={"text": "写出把 1 绑定给 x 的语句。"},
            starter_artifact={"content": ""},
            required_capabilities=("python",),
            runtime_profile_id=None,
            execution_required=False,
            public_feedback_policy_version="lesson_gate_feedback_v1",
        )
        rubric = ExercisePrivateRubric(
            rubric_version="v1",
            private_test_bundle=(
                {"case_type": "hidden", "input": {}, "expected": {"value": "x = 1"}},
            ),
            reference_answer={"accepted_answers": ["x = 1"]},
            score_policy={"kind": "exact_static", "threshold": 0.8},
        )
        require_exercise_quality(exercise, rubric)
        PostgresExerciseGateRepository(conn).ensure_curated_fixture(
            CuratedExerciseFixture(exercise=exercise, rubric=rubric),
            now=datetime.now(UTC),
        )
        conn.commit()
    return track_id, int(track["version"]), int(schedule["version"])


def test_review_routes_complete_verified_only_lifecycle(review_client: TestClient) -> None:
    user_id = _create_user(review_client)
    track_id, track_version, schedule_version = _create_due_track(review_client, user_id)

    queue = review_client.get(f"/api/learning-tracks/{track_id}/reviews?user_id={user_id}")
    assert queue.status_code == 200
    assert queue.json()["due_count"] == 1
    listing = review_client.get(f"/api/learning-tracks?user_id={user_id}")
    assert listing.status_code == 200
    assert listing.json()["items"][0]["review_due_count"] == 1

    create_payload = {
        "user_id": user_id,
        "client_action_id": f"review-api-create-{uuid4()}",
        "knowledge_key": "python.variables",
        "expected_track_version": track_version,
        "expected_schedule_version": schedule_version,
        "max_items": 1,
    }
    created = review_client.post(
        f"/api/learning-tracks/{track_id}/reviews/sessions",
        json=create_payload,
    )
    replay = review_client.post(
        f"/api/learning-tracks/{track_id}/reviews/sessions",
        json=create_payload,
    )
    assert created.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["idempotent_replayed"] is True
    assert replay.json()["session_id"] == created.json()["session_id"]
    session = created.json()
    session_id = str(session["session_id"])
    item_id = str(session["items"][0]["item_id"])

    warmup = review_client.post(
        f"/api/learning-tracks/{track_id}/reviews/sessions/{session_id}/warmup",
        json={
            "user_id": user_id,
            "client_action_id": f"review-api-warmup-{uuid4()}",
            "response_kind": "answered",
            "confidence": "medium",
            "expected_session_version": session["version"],
        },
    )
    assert warmup.status_code == 200
    assert warmup.json()["stage"] == "practice"

    hint = review_client.post(
        f"/api/learning-tracks/{track_id}/reviews/sessions/{session_id}/items/{item_id}/hints",
        json={
            "user_id": user_id,
            "client_action_id": f"review-api-hint-{uuid4()}",
            "hint_level": 1,
            "expected_session_version": warmup.json()["version"],
            "expected_item_version": 1,
        },
    )
    assert hint.status_code == 200
    assert hint.json()["safe_hint"]["reveals_answer"] is False

    attempt = review_client.post(
        f"/api/learning-tracks/{track_id}/reviews/sessions/{session_id}/items/{item_id}/attempts",
        json={
            "user_id": user_id,
            "client_action_id": f"review-api-attempt-{uuid4()}",
            "submission": "x = 1",
            "expected_session_version": warmup.json()["version"],
            "expected_item_version": 1,
        },
    )
    assert attempt.status_code == 200
    attempt_body = attempt.json()
    assert attempt_body["status"] == "terminal"
    assert attempt_body["independence"] == "hinted"
    assert attempt_body["result"]["outcome"] == "passed"

    finalize_key = f"review-api-finalize-{uuid4()}"
    finalize_payload = {
        "user_id": user_id,
        "client_action_id": finalize_key,
        "expected_session_version": attempt_body["session_version"],
    }
    finalized = review_client.post(
        f"/api/learning-tracks/{track_id}/reviews/sessions/{session_id}/finalize",
        json=finalize_payload,
    )
    finalized_replay = review_client.post(
        f"/api/learning-tracks/{track_id}/reviews/sessions/{session_id}/finalize",
        json=finalize_payload,
    )
    assert finalized.status_code == finalized_replay.status_code == 200
    assert finalized.json()["state"] == "finalized"
    assert finalized.json()["finalization"]["rating"] == "hard"
    assert finalized_replay.json()["idempotent_replayed"] is True
    assert review_client.get(
        f"/api/learning-tracks/{track_id}/reviews/sessions/{session_id}?user_id={user_id}"
    ).json()["state"] == "finalized"


def test_review_routes_hide_cross_user_and_require_verified_cutover(review_client: TestClient) -> None:
    owner_id = _create_user(review_client)
    other_id = _create_user(review_client)
    track_id, _track_version, _schedule_version = _create_due_track(review_client, owner_id)
    cross = review_client.get(f"/api/learning-tracks/{track_id}/reviews?user_id={other_id}")
    assert_error(cross, "REVIEW_NOT_FOUND", 404)

    unverified = review_client.post(
        "/api/users",
        json={"display_name": f"Review Unverified {uuid4().hex[:8]}"},
    )
    assert unverified.status_code == 201
    unverified_id = str(unverified.json()["user"]["id"])
    with connect() as conn:
        conn.execute("DELETE FROM harness_cutovers WHERE user_id = %s", (unverified_id,))
        conn.commit()
    gated = review_client.get(f"/api/learning-tracks/{track_id}/reviews?user_id={unverified_id}")
    assert_error(gated, "CUTOVER_REQUIRED", 409)
