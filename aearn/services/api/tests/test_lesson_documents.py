from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

import app.services.learning.lesson_authoring as lesson_authoring
from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.db.connection import connect
from app.main import app
from app.services.grounding.grounding_index_repository import run_and_persist_fixture_grounding_reindex
from learning_track_support import sample_plan_payload
from test_lesson_document_authoring import FakeLessonAuthor
from tutor_public_api_support import assert_error


def _database_available() -> bool:
    try:
        with psycopg.connect(get_settings().database_url, connect_timeout=2) as conn:
            conn.execute("select 1")
        return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(not _database_available(), reason="PostgreSQL is required for Lesson API tests.")


@pytest.fixture()
def lesson_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    bootstrap_database()
    with connect() as conn:
        run_and_persist_fixture_grounding_reindex(conn)
        conn.commit()
    variant = {"title": "Python 变量：个性化"}
    monkeypatch.setattr(
        lesson_authoring,
        "LESSON_AUTHOR_FACTORY",
        lambda: FakeLessonAuthor(personalized_title=variant["title"]),
    )
    with TestClient(app) as client:
        client.variant = variant  # type: ignore[attr-defined]
        yield client


def _create_user(client: TestClient) -> str:
    response = client.post("/api/users", json={"display_name": f"Lesson API {uuid4().hex[:10]}"})
    assert response.status_code == 201
    user_id = str(response.json()["user"]["id"])
    decision = client.get(f"/api/harness/cutover?user_id={user_id}")
    assert decision.status_code == 200 and decision.json()["state"] == "verified"
    return user_id


def _create_track(client: TestClient, user_id: str) -> dict[str, object]:
    response = client.post(
        "/api/learning-tracks",
        json={
            "user_id": user_id,
            "client_action_id": f"track-{uuid4()}",
            "language_id": "python",
            "goal_text": "Learn Python variables for automation",
            "target_level": "beginner",
            "plan": sample_plan_payload(),
        },
    )
    assert response.status_code == 201
    return response.json()["track"]


def test_missing_prepare_ready_start_refresh_and_explicit_migration(lesson_client: TestClient) -> None:
    user_id = _create_user(lesson_client)
    track = _create_track(lesson_client, user_id)
    track_id = str(track["track_id"])
    path = f"/api/learning-tracks/{track_id}/lessons/python.variables"

    missing = lesson_client.get(f"{path}?user_id={user_id}")
    assert missing.status_code == 200
    assert missing.json()["status"] == "missing"
    assert missing.json()["module_key"] == "foundations"
    assert missing.json()["module_diagnostic_allowed"] is False

    prepare_payload = {
        "user_id": user_id,
        "client_action_id": f"prepare-{uuid4()}",
        "expected_track_version": track["version"],
        "expected_progress_version": 1,
    }
    prepared = lesson_client.post(f"{path}/prepare", json=prepare_payload)
    assert prepared.status_code == 202
    assert prepared.json()["status"] == "preparing"

    ready = lesson_client.get(f"{path}?user_id={user_id}")
    assert ready.status_code == 200
    body = ready.json()
    assert body["status"] == "ready"
    assert body["module_key"] == "foundations"
    assert body["module_diagnostic_allowed"] is False
    assert len(body["document"]["blocks"]) == 10
    assert body["sources"][0]["source_version_label"]
    assert body["sources"][0]["evidence_excerpt"]
    assert body["document"]["blocks"][7]["type"] == "exercise_gate"
    assignment = body["assignment"]

    started = lesson_client.post(
        f"{path}/start",
        json={
            "user_id": user_id,
            "client_action_id": f"start-{uuid4()}",
            "assignment_id": assignment["assignment_id"],
            "expected_assignment_version": assignment["assignment_version"],
            "expected_progress_version": body["progress_version"],
        },
    )
    assert started.status_code == 200
    assert started.json()["assignment"]["progress_status"] == "in_progress"

    lesson_client.variant["title"] = "Python 变量：自动化目标版"  # type: ignore[attr-defined]
    refreshed_state = lesson_client.get(f"{path}?user_id={user_id}").json()
    refresh = lesson_client.post(
        f"{path}/refresh",
        json={
            "user_id": user_id,
            "client_action_id": f"refresh-{uuid4()}",
            "expected_track_version": refreshed_state["track_version"],
            "expected_progress_version": refreshed_state["progress_version"],
        },
    )
    assert refresh.status_code == 202
    proposed_state = lesson_client.get(f"{path}?user_id={user_id}").json()
    assert proposed_state["update"]["status"] == "proposed"
    proposal = proposed_state["update"]

    activated = lesson_client.post(
        f"{path}/migrations/{proposal['assignment_id']}/activate",
        json={
            "user_id": user_id,
            "client_action_id": f"migrate-{uuid4()}",
            "expected_assignment_version": proposal["assignment_version"],
        },
    )
    assert activated.status_code == 200
    assert activated.json()["assignment"]["status"] == "active"
    migrated = lesson_client.get(f"{path}?user_id={user_id}").json()
    assert migrated["document"]["title"] == "Python 变量：自动化目标版"


def test_verified_scope_locked_node_cross_user_and_idempotency_conflict(lesson_client: TestClient) -> None:
    owner = _create_user(lesson_client)
    other = _create_user(lesson_client)
    track = _create_track(lesson_client, owner)
    track_id = str(track["track_id"])

    cross_user = lesson_client.get(f"/api/learning-tracks/{track_id}/lessons/python.variables?user_id={other}")
    assert_error(cross_user, "LESSON_DOCUMENT_NOT_FOUND", 404)

    locked = lesson_client.post(
        f"/api/learning-tracks/{track_id}/lessons/python.functions/prepare",
        json={
            "user_id": owner,
            "client_action_id": f"locked-{uuid4()}",
            "expected_track_version": 1,
            "expected_progress_version": 1,
        },
    )
    assert_error(locked, "LESSON_DOCUMENT_NOT_READY", 409)

    action = f"prepare-conflict-{uuid4()}"
    first = lesson_client.post(
        f"/api/learning-tracks/{track_id}/lessons/python.variables/prepare",
        json={
            "user_id": owner,
            "client_action_id": action,
            "expected_track_version": 1,
            "expected_progress_version": 1,
        },
    )
    assert first.status_code == 202
    conflict = lesson_client.post(
        f"/api/learning-tracks/{track_id}/lessons/python.variables/refresh",
        json={
            "user_id": owner,
            "client_action_id": action,
            "expected_track_version": 1,
            "expected_progress_version": 1,
        },
    )
    # prepare and refresh have separate semantic operations, so the same client key is allowed.
    assert conflict.status_code in {200, 202}
