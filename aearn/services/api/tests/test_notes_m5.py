import json
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

import app.routes.plans as plans_route
from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.db.connection import connect
from app.main import app
from app.services import note_repository


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


@pytest.fixture(autouse=True)
def disable_note_assist_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeNoteAssistClient:
        model = "fake-note-assist-model"

        def complete_text(
            self,
            context: object,
            *,
            temperature: float = 0.3,
        ) -> str:
            del temperature
            return _fake_note_draft(context)

        def complete_text_stream(
            self,
            context: object,
            *,
            temperature: float = 0.3,
        ):
            del temperature
            draft = _fake_note_draft(context)
            for line in draft.splitlines(keepends=True):
                yield line

    monkeypatch.setattr(note_repository, "build_note_assist_client", lambda: FakeNoteAssistClient())
    monkeypatch.setattr(plans_route, "build_sdk_plan_generation_response", lambda *args, **kwargs: None)
    monkeypatch.setattr(plans_route, "build_sdk_onboarding_plan_response", lambda *args, **kwargs: None)


def _fake_note_draft(context: object) -> str:
    return "\n".join(
        [
            f"补充主题：{getattr(context, 'module_title')} / {getattr(context, 'knowledge_point_title')}",
            f"当前笔记：{getattr(context, 'note_title')}",
            "可补充：",
            "- 错因：先写清触发条件和失败现象。",
            "- 修正：只追加当前知识点相关部分，不覆盖已有正文。",
        ]
    )


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
    assert "补充主题：" in drafted_note["agent_draft_content"]
    assert "可补充：" in drafted_note["agent_draft_content"]

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


def test_agent_draft_streams_sse_and_updates_agent_field(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_id = f"req_note_sse_{uuid.uuid4().hex}"
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
    note = created.json()["note"]

    class FakeNoteAssistClient:
        model = "sdk-note-assist-model"

        def __init__(self) -> None:
            self.context = None

        def complete_text(
            self,
            context: object,
            *,
            temperature: float = 0.3,
        ) -> str:
            self.context = context
            del temperature
            return "补充主题：JavaScript DOM 基础 / 状态变量\n可补充：\n- 错因：最近一次运行状态为 success，说明笔记可以补充对比说明。"

        def complete_text_stream(
            self,
            context: object,
            *,
            temperature: float = 0.3,
        ):
            self.context = context
            del temperature
            yield "补充主题：JavaScript DOM 基础 / 状态变量\n"
            yield "可补充：\n- 错因：最近一次运行状态为 success，说明笔记可以补充对比说明。"

    monkeypatch.setattr(note_repository, "build_note_assist_client", lambda: FakeNoteAssistClient())

    with client.stream(
        "POST",
        f"/api/notes/{note['id']}/agent-draft",
        headers={"Accept": "text/event-stream", "X-Request-Id": request_id},
        json={
            "user_id": user["id"],
            "style": "concise",
            "focus": "mistake_summary",
            "source": {
                "session_id": "sess_learning_001",
                "attempt_id": "att_submit_001",
            },
        },
    ) as response:
        assert response.status_code == 200
        events = _parse_sse_events("".join(response.iter_text()))

    event_types = [event["event"] for event in events]
    assert event_types[0] == "tool_status"
    assert "agent_message" in event_types
    assert event_types[-1] == "done"
    agent_messages = [event["data"] for event in events if event["event"] == "agent_message"]
    assert agent_messages[-1]["request_id"] == request_id
    assert agent_messages[-1]["content"]
    assert events[-1]["data"]["result_ref"] == {"type": "Note", "id": note["id"]}
    assert agent_messages[0]["delta"].startswith("补充主题：")
    assert "可补充：" in agent_messages[-1]["content"]

    with connect() as conn:
        stored = conn.execute(
            """
            SELECT content_markdown, agent_draft_content
            FROM notes
            WHERE id = %s
            """,
            (note["id"],),
        ).fetchone()
    assert stored is not None
    assert stored["content_markdown"] == "原始正文不应该被 agent draft 覆盖。"
    assert stored["agent_draft_content"] == agent_messages[-1]["content"].strip()


def test_agent_draft_returns_model_unavailable_when_sdk_output_mentions_code_draft(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    note = created.json()["note"]

    class LeakingNoteAssistClient:
        model = "sdk-note-assist-model"

        def complete_text(
            self,
            context: object,
            *,
            temperature: float = 0.3,
        ) -> str:
            del context, temperature
            return "CodeDraft /api/code-drafts 完整笔记必须重写。"

        def complete_text_stream(
            self,
            context: object,
            *,
            temperature: float = 0.3,
        ):
            del context, temperature
            yield "CodeDraft /api/code-drafts 完整笔记必须重写。"

    monkeypatch.setattr(note_repository, "build_note_assist_client", lambda: LeakingNoteAssistClient())

    drafted = client.post(
        f"/api/notes/{note['id']}/agent-draft",
        json={
            "user_id": user["id"],
            "style": "concise",
            "focus": "mistake_summary",
            "source": {
                "session_id": "sess_learning_001",
                "attempt_id": "att_submit_001",
            },
        },
    )
    assert drafted.status_code == 503
    assert drafted.json()["error"]["code"] == "MODEL_UNAVAILABLE"

    with connect() as conn:
        stored = conn.execute(
            """
            SELECT agent_draft_content
            FROM notes
            WHERE id = %s
            """,
            (note["id"],),
        ).fetchone()
    assert stored is not None
    assert stored["agent_draft_content"] is None


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


def _parse_sse_events(text: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for frame in text.replace("\r\n", "\n").split("\n\n"):
        if not frame.strip():
            continue
        event_type = ""
        data_lines: list[str] = []
        for line in frame.splitlines():
            if line.startswith("event:"):
                event_type = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data_lines.append(line.removeprefix("data:").strip())
        if not event_type:
            continue
        events.append({"event": event_type, "data": json.loads("\n".join(data_lines))})
    return events
