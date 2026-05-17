import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.db.connection import connect
from app.main import app


def _database_available() -> bool:
    try:
        with psycopg.connect(get_settings().database_url, connect_timeout=2) as conn:
            conn.execute("select 1")
        return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(
    not _database_available(),
    reason="PostgreSQL is not available; run aearn infra compose for DB smoke tests.",
)


@pytest.fixture()
def client() -> TestClient:
    bootstrap_database()
    return TestClient(app)


def test_dashboard_returns_resume_entry_and_due_notice_without_forcing_review(client: TestClient) -> None:
    user, plan = _confirmed_plan(client)
    first_kp_id = plan["knowledge_points"][0]["id"]
    second_kp_id = plan["knowledge_points"][1]["id"]

    start = client.post(
        "/api/learning-sessions/start",
        json={
            "user_id": user["id"],
            "plan_id": plan["LearningPlan"]["id"],
            "knowledge_point_id": first_kp_id,
        },
    )
    assert start.status_code == 201

    with connect() as conn:
        conn.execute(
            """
            UPDATE review_states
            SET card_state = 'review',
                due_at = now() - interval '30 minutes',
                last_fsrs_rating = 'Hard',
                reps = 1
            WHERE knowledge_point_id = %s
            """,
            (second_kp_id,),
        )
        conn.execute(
            "UPDATE knowledge_points SET status = 'reviewing' WHERE id = %s",
            (second_kp_id,),
        )
        conn.commit()

    response = client.get(f"/api/dashboard?user_id={user['id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["resume_available"] is True
    assert body["today_review_count"] == 1
    assert body["next_entry_point"]["type"] == "resume"
    assert body["next_entry_point"]["plan_id"] == plan["LearningPlan"]["id"]
    assert body["current_course"]["title"]
    assert body["today_learning_tasks"][0]["knowledge_point_id"] == first_kp_id


def test_dashboard_prioritizes_review_after_inactivity_and_high_risk(client: TestClient) -> None:
    user, plan = _confirmed_plan(client)
    first_kp_id = plan["knowledge_points"][0]["id"]
    second_kp_id = plan["knowledge_points"][1]["id"]

    start = client.post(
        "/api/learning-sessions/start",
        json={
            "user_id": user["id"],
            "plan_id": plan["LearningPlan"]["id"],
            "knowledge_point_id": first_kp_id,
        },
    )
    assert start.status_code == 201
    session_id = start.json()["session_id"]

    with connect() as conn:
        stale_time = datetime.now(UTC) - timedelta(days=4)
        conn.execute(
            """
            UPDATE learning_sessions
            SET started_at = %s,
                updated_at = %s
            WHERE id = %s
            """,
            (stale_time, stale_time, session_id),
        )
        conn.execute(
            """
            UPDATE review_states
            SET card_state = 'relearning',
                due_at = now() - interval '1 day',
                last_fsrs_rating = 'Again',
                reps = 2,
                lapses = 1
            WHERE knowledge_point_id = %s
            """,
            (second_kp_id,),
        )
        conn.execute(
            "UPDATE knowledge_points SET status = 'reviewing' WHERE id = %s",
            (second_kp_id,),
        )
        conn.commit()

    response = client.get(f"/api/dashboard?user_id={user['id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["today_review_count"] == 1
    assert body["next_entry_point"]["type"] == "review"
    assert body["next_entry_point"]["knowledge_point_id"] == second_kp_id
    assert body["next_entry_point"]["next_action"] == "review_variant"


def test_resume_returns_synthesized_summary_and_current_entry(client: TestClient) -> None:
    user, plan = _confirmed_plan(client)
    first_kp = plan["knowledge_points"][0]

    start = client.post(
        "/api/learning-sessions/start",
        json={
            "user_id": user["id"],
            "plan_id": plan["LearningPlan"]["id"],
            "knowledge_point_id": first_kp["id"],
        },
    )
    assert start.status_code == 201

    response = client.get(
        f"/api/learning-sessions/resume?user_id={user['id']}&plan_id={plan['LearningPlan']['id']}",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["resume_available"] is True
    assert body["next_entry_point"]["type"] == "learning_session"
    assert body["next_entry_point"]["knowledge_point_id"] == first_kp["id"]
    assert first_kp["title"] in body["last_session_summary"]
    assert body["current_module"]["id"] == plan["modules"][0]["id"]


def test_resume_returns_unavailable_when_no_session_exists(client: TestClient) -> None:
    user, plan = _confirmed_plan(client)
    first_kp = plan["knowledge_points"][0]

    response = client.get(
        f"/api/learning-sessions/resume?user_id={user['id']}&plan_id={plan['LearningPlan']['id']}",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["resume_available"] is False
    assert body["last_session_summary"] is None
    assert body["next_entry_point"]["knowledge_point_id"] == first_kp["id"]


def test_dashboard_and_resume_validate_missing_entities(client: TestClient) -> None:
    missing_dashboard = client.get(f"/api/dashboard?user_id={uuid.uuid4()}")
    assert missing_dashboard.status_code == 404
    assert missing_dashboard.json()["error"]["code"] == "USER_NOT_FOUND"

    user, _plan = _confirmed_plan(client)
    missing_resume = client.get(
        f"/api/learning-sessions/resume?user_id={user['id']}&plan_id={uuid.uuid4()}",
    )
    assert missing_resume.status_code == 404
    assert missing_resume.json()["error"]["code"] == "PLAN_NOT_FOUND"


def _confirmed_plan(client: TestClient) -> tuple[dict[str, object], dict[str, object]]:
    user = _create_user(client)
    course = _course_by_language(client, "javascript")
    draft_response = client.post(
        "/api/plans/generate",
        json={
            "user_id": user["id"],
            "mode": "goal_based",
            "goal_text": "Resume current learning and respect review priority.",
            "course_id": course["id"],
        },
    )
    assert draft_response.status_code == 200
    draft = draft_response.json()["plan_draft"]

    confirm_response = client.post("/api/plans", json={"user_id": user["id"], "plan_draft": draft})
    assert confirm_response.status_code == 201
    return user, confirm_response.json()


def _create_user(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/users",
        json={
            "display_name": f"M6 User {uuid.uuid4().hex[:8]}",
            "learning_style": "practice_first",
            "teaching_preference": "step_by_step",
        },
    )
    assert response.status_code == 201
    user = response.json()["user"]
    assert isinstance(user, dict)
    return user


def _course_by_language(client: TestClient, language: str) -> dict[str, object]:
    response = client.get(f"/api/language-courses?language={language}")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    course = items[0]
    assert isinstance(course, dict)
    return course
