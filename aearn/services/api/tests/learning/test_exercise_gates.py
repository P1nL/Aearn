from __future__ import annotations

from collections.abc import Iterator
from functools import partial
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
from tests.support.learning_track_support import sample_plan_payload
from tests.learning.test_lesson_document_authoring import FakeLessonAuthor
from tests.support.tutor_public_api_support import assert_error


def _database_available() -> bool:
    try:
        with psycopg.connect(get_settings().database_url, connect_timeout=2) as conn:
            conn.execute("select 1")
        return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(not _database_available(), reason="PostgreSQL is required for Gate API tests")


@pytest.fixture()
def gate_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    # This fixture pairs offline grounding with a fake author, not live evidence.
    monkeypatch.setattr(
        lesson_authoring, "_load_evidence_snapshots",
        partial(lesson_authoring._load_evidence_snapshots, allow_fixtures_for_tests=True),
    )
    bootstrap_database()
    with connect() as conn:
        run_and_persist_fixture_grounding_reindex(conn)
        conn.commit()
    monkeypatch.setattr(
        lesson_authoring,
        "LESSON_AUTHOR_FACTORY",
        lambda: FakeLessonAuthor(personalized_title="Python 变量：练习版"),
    )
    with TestClient(app) as client:
        yield client


def _create_user(client: TestClient) -> str:
    response = client.post("/api/users", json={"display_name": f"Gate API {uuid4().hex[:10]}"})
    assert response.status_code == 201
    user_id = str(response.json()["user"]["id"])
    cutover = client.get(f"/api/harness/cutover?user_id={user_id}")
    assert cutover.status_code == 200
    assert cutover.json()["state"] == "verified"
    return user_id


def _create_track(client: TestClient, user_id: str, *, skippable: bool = False) -> dict[str, object]:
    plan = sample_plan_payload()
    modules = plan["modules"]
    assert isinstance(modules, list) and isinstance(modules[0], dict)
    modules[0]["is_skippable"] = skippable
    response = client.post(
        "/api/learning-tracks",
        json={
            "user_id": user_id,
            "client_action_id": f"track-{uuid4()}",
            "language_id": "python",
            "goal_text": "Learn Python variables for automation",
            "target_level": "beginner",
            "plan": plan,
        },
    )
    assert response.status_code == 201
    return response.json()["track"]


def _prepare_and_start_lesson(client: TestClient, user_id: str, track_id: str) -> dict[str, object]:
    path = f"/api/learning-tracks/{track_id}/lessons/python.variables"
    prepared = client.post(
        f"{path}/prepare",
        json={
            "user_id": user_id,
            "client_action_id": f"lesson-prepare-{uuid4()}",
            "expected_track_version": 1,
            "expected_progress_version": 1,
        },
    )
    assert prepared.status_code == 202
    ready = client.get(f"{path}?user_id={user_id}")
    assert ready.status_code == 200
    state = ready.json()
    assignment = state["assignment"]
    started = client.post(
        f"{path}/start",
        json={
            "user_id": user_id,
            "client_action_id": f"lesson-start-{uuid4()}",
            "assignment_id": assignment["assignment_id"],
            "expected_assignment_version": assignment["assignment_version"],
            "expected_progress_version": state["progress_version"],
        },
    )
    assert started.status_code == 200
    current = client.get(f"{path}?user_id={user_id}")
    assert current.status_code == 200
    return current.json()


def test_gate_prepare_public_unavailable_does_not_create_attempt(gate_client: TestClient) -> None:
    user_id = _create_user(gate_client)
    track = _create_track(gate_client, user_id)
    track_id = str(track["track_id"])
    lesson = _prepare_and_start_lesson(gate_client, user_id, track_id)
    assert lesson["module_key"] == "foundations"
    assert lesson["module_diagnostic_allowed"] is False
    path = f"/api/learning-tracks/{track_id}/lessons/python.variables/gates"

    initial = gate_client.get(f"{path}?user_id={user_id}")
    assert initial.status_code == 200
    assert initial.json()["items"][0]["status"] == "unbound"

    prepared = gate_client.post(
        f"{path}/python.variables.basic/prepare",
        json={
            "user_id": user_id,
            "client_action_id": f"gate-prepare-{uuid4()}",
            "expected_track_version": lesson["track_version"],
            "expected_progress_version": lesson["progress_version"],
        },
    )
    assert prepared.status_code == 200
    gate = prepared.json()["gate"]
    assert gate["gate_kind"] == "knowledge_check"
    assert gate["requirement_kind"] == "required"
    assert gate["execution_tier"] == "unavailable"
    assert gate["allowed_actions"] == []
    serialized = prepared.text.casefold()
    for protected in ("private_test", "reference_answer", "rubric_hash", "content_text", "container_name"):
        assert protected not in serialized

    request_id = f"req-{uuid4()}"
    unavailable = gate_client.post(
        f"{path}/python.variables.basic/attempts",
        headers={"X-Request-Id": request_id},
        json={
            "user_id": user_id,
            "client_action_id": f"gate-attempt-{uuid4()}",
            "attempt_type": "submit",
            "submission": "value = 3\nprint(value)",
            "expected_track_version": lesson["track_version"],
            "expected_progress_version": lesson["progress_version"],
            "expected_assignment_version": lesson["assignment"]["assignment_version"],
            "expected_gate_version": gate["gate_version"],
        },
    )
    assert_error(unavailable, "EXECUTION_UNAVAILABLE", 503)
    assert unavailable.headers.get("x-request-id") == request_id
    with connect() as conn:
        count = conn.execute(
            "SELECT count(*)::int AS count FROM tutor_exercise_attempts WHERE user_id = %s",
            (user_id,),
        ).fetchone()
        assert count == {"count": 0}


def test_gate_and_diagnostic_routes_hide_cross_scope(gate_client: TestClient) -> None:
    owner = _create_user(gate_client)
    other = _create_user(gate_client)
    track = _create_track(gate_client, owner, skippable=True)
    track_id = str(track["track_id"])
    lesson = _prepare_and_start_lesson(gate_client, owner, track_id)
    assert lesson["module_key"] == "foundations"
    assert lesson["module_diagnostic_allowed"] is True

    cross_user = gate_client.get(
        f"/api/learning-tracks/{track_id}/lessons/python.variables/gates?user_id={other}"
    )
    assert_error(cross_user, "LESSON_GATE_NOT_FOUND", 404)

    created = gate_client.post(
        f"/api/learning-tracks/{track_id}/modules/foundations/diagnostics",
        json={
            "user_id": owner,
            "client_action_id": f"diagnostic-{uuid4()}",
            "expected_track_version": 1,
        },
    )
    assert created.status_code == 200
    session_id = str(created.json()["session_id"])
    wrong_module = gate_client.get(
        f"/api/learning-tracks/{track_id}/modules/not-found/diagnostics/{session_id}?user_id={owner}"
    )
    assert_error(wrong_module, "MODULE_DIAGNOSTIC_NOT_ALLOWED", 404)

    extra_field = gate_client.post(
        f"/api/learning-tracks/{track_id}/modules/foundations/diagnostics",
        json={
            "user_id": owner,
            "client_action_id": f"diagnostic-{uuid4()}",
            "expected_track_version": 1,
            "score": 1,
        },
    )
    assert_error(extra_field, "VALIDATION_ERROR", 400)
