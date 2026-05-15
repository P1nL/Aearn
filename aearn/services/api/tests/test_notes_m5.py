import uuid

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


def test_note_create_get_patch_and_repeat_create_reuses_same_record(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point = plan["knowledge_points"][0]

    created = client.post(
        "/api/notes",
        json={
            "user_id": user["id"],
            "knowledge_point_id": knowledge_point["id"],
            "title": "状态变量位置",
            "content_markdown": "第一次点击前先确认 count 的作用域。",
            "source": {
                "session_id": "sess_test_001",
                "attempt_id": "att_test_001",
            },
        },
    )
    assert created.status_code == 201
    created_note = created.json()["note"]
    assert created_note["knowledge_point_id"] == knowledge_point["id"]
    assert created_note["title"] == "状态变量位置"
    assert created_note["content_markdown"] == "第一次点击前先确认 count 的作用域。"
    assert created_note["is_user_edited"] is True

    fetched = client.get(
        f"/api/notes?user_id={user['id']}&knowledge_point_id={knowledge_point['id']}",
    )
    assert fetched.status_code == 200
    fetched_items = fetched.json()["items"]
    assert len(fetched_items) == 1
    assert fetched_items[0]["id"] == created_note["id"]
    assert fetched_items[0]["knowledge_point"]["title"] == knowledge_point["title"]
    assert fetched_items[0]["language"] == "javascript"

    updated = client.patch(
        f"/api/notes/{created_note['id']}",
        json={
            "title": "事件状态变量位置",
            "content_markdown": "状态变量放在回调外层，回调内部只做更新。",
            "is_user_edited": True,
        },
    )
    assert updated.status_code == 200
    updated_note = updated.json()["note"]
    assert updated_note["id"] == created_note["id"]
    assert updated_note["title"] == "事件状态变量位置"
    assert updated_note["content_markdown"] == "状态变量放在回调外层，回调内部只做更新。"
    assert updated_note["updated_at"] >= created_note["updated_at"]

    replayed_create = client.post(
        "/api/notes",
        json={
            "user_id": user["id"],
            "knowledge_point_id": knowledge_point["id"],
            "title": "不会创建第二条",
            "content_markdown": "重复创建必须复用可见 note。",
        },
    )
    assert replayed_create.status_code == 200
    assert replayed_create.json()["note"]["id"] == created_note["id"]

    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id
            FROM notes
            WHERE user_id = %s
              AND knowledge_point_id = %s
              AND deleted_at IS NULL
            """,
            (user["id"], knowledge_point["id"]),
        ).fetchall()
    assert len(rows) == 1


def test_note_list_ignores_soft_deleted_records_and_returns_empty_for_missing_note(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="python")
    first_kp = plan["knowledge_points"][0]
    second_kp = plan["knowledge_points"][1]

    first = client.post(
        "/api/notes",
        json={
            "user_id": user["id"],
            "knowledge_point_id": first_kp["id"],
            "title": "函数返回值",
            "content_markdown": "return 要和 stdout 区分开。",
        },
    )
    second = client.post(
        "/api/notes",
        json={
            "user_id": user["id"],
            "knowledge_point_id": second_kp["id"],
            "title": "测试断言",
            "content_markdown": "先看 visible tests 再决定下一步。",
        },
    )
    assert first.status_code == 201
    assert second.status_code == 201

    with connect() as conn:
        conn.execute("UPDATE notes SET deleted_at = now() WHERE id = %s", (first.json()["note"]["id"],))
        conn.commit()

    listing = client.get(f"/api/notes?user_id={user['id']}&limit=20")
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == second.json()["note"]["id"]
    assert items[0]["knowledge_point"]["id"] == second_kp["id"]
    assert listing.json()["page_info"]["has_more"] is False

    empty = client.get(f"/api/notes?user_id={user['id']}&knowledge_point_id={first_kp['id']}")
    assert empty.status_code == 200
    assert empty.json()["items"] == []


def test_agent_draft_only_updates_agent_field(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point = plan["knowledge_points"][0]
    created = client.post(
        "/api/notes",
        json={
            "user_id": user["id"],
            "knowledge_point_id": knowledge_point["id"],
            "title": "状态变量位置",
            "content_markdown": "原始正文不应该被 agent draft 覆盖。",
        },
    )
    assert created.status_code == 201
    note = created.json()["note"]

    drafted = client.post(
        f"/api/notes/{note['id']}/agent-draft",
        json={
            "user_id": user["id"],
            "style": "concise",
            "focus": "mistake_summary",
            "source": {
                "session_id": "sess_learning_001",
                "attempt_id": "att_submit_001",
            }
        },
    )
    assert drafted.status_code == 200
    drafted_note = drafted.json()["note"]
    assert drafted_note["id"] == note["id"]
    assert drafted_note["content_markdown"] == "原始正文不应该被 agent draft 覆盖。"
    assert isinstance(drafted_note["agent_draft_content"], str)
    assert drafted_note["agent_draft_content"]

    with connect() as conn:
        stored = conn.execute(
            """
            SELECT content_markdown, agent_draft_content, is_user_edited
            FROM notes
            WHERE id = %s
            """,
            (note["id"],),
        ).fetchone()
    assert stored is not None
    assert stored["content_markdown"] == "原始正文不应该被 agent draft 覆盖。"
    assert stored["agent_draft_content"] == drafted_note["agent_draft_content"]
    assert stored["is_user_edited"] is True


def _confirmed_plan(client: TestClient, *, language: str) -> tuple[dict[str, object], dict[str, object]]:
    user = _create_user(client)
    course = _course_by_language(client, language)
    draft_response = client.post(
        "/api/plans/generate",
        json={
            "user_id": user["id"],
            "mode": "goal_based",
            "goal_text": f"Practice {language} notes persistence.",
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
            "display_name": f"M5 User {uuid.uuid4().hex[:8]}",
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
