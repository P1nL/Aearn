from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import app.routes.tutor as tutor_route
from app.core.config import Settings
from app.db.connection import connect
from tutor_public_api_support import (
    action_payload,
    assert_error,
    create_tutor_user,
    terminal_dispatcher,
)


def _first_turn(client: TestClient, *, user_id: str, action_id: str, content: str) -> dict[str, object]:
    response = client.post(
        "/api/tutor/conversations/first-turn",
        json=action_payload(user_id, action_id, content=content),
    )
    assert response.status_code == 202
    return response.json()


def test_public_conversation_list_and_history_cursors_are_ordered_and_scoped(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    dispatcher, _provider = terminal_dispatcher(settings=tutor_api_settings)
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user = create_tutor_user(tutor_client)
    user_id = str(user["id"])

    first = _first_turn(
        tutor_client,
        user_id=user_id,
        action_id="history-cursor-first",
        content="请从闭包的最小示例开始。",
    )
    second = _first_turn(
        tutor_client,
        user_id=user_id,
        action_id="history-cursor-second",
        content="请再比较一下回调和外层变量。",
    )
    first_conversation_id = str(first["conversation_id"])
    second_conversation_id = str(second["conversation_id"])

    now = datetime.now(UTC)
    with connect() as conn:
        conn.execute(
            "UPDATE tutor_conversations SET last_public_activity_at = %s WHERE id = %s",
            (now - timedelta(minutes=5), first_conversation_id),
        )
        conn.execute(
            "UPDATE tutor_conversations SET last_public_activity_at = %s WHERE id = %s",
            (now, second_conversation_id),
        )
        conn.commit()

    first_page = tutor_client.get(f"/api/tutor/conversations?user_id={user_id}&limit=1")
    assert first_page.status_code == 200
    first_page_body = first_page.json()
    assert first_page_body["has_more"] is True
    assert first_page_body["items"][0]["conversation_id"] == second_conversation_id
    list_cursor = first_page_body["next_cursor"]
    assert isinstance(list_cursor, str) and list_cursor

    second_page = tutor_client.get(f"/api/tutor/conversations?user_id={user_id}&limit=1&cursor={list_cursor}")
    assert second_page.status_code == 200
    assert second_page.json()["has_more"] is False
    assert second_page.json()["items"][0]["conversation_id"] == first_conversation_id
    assert second_page.json()["items"][0]["title"] == "新对话"
    assert second_page.json()["items"][0]["active_run"] is None

    other_user = create_tutor_user(tutor_client)
    cross_user_list = tutor_client.get(
        f"/api/tutor/conversations?user_id={other_user['id']}&limit=1&cursor={list_cursor}"
    )
    assert_error(cross_user_list, "CURSOR_INVALID", 400)

    history_page = tutor_client.get(
        f"/api/tutor/conversations/{first_conversation_id}/history?user_id={user_id}&limit=2"
    )
    assert history_page.status_code == 200
    history_page_body = history_page.json()
    assert history_page_body["has_more"] is True
    assert [item["kind"] for item in history_page_body["items"]] == ["message", "process"]
    assert history_page_body["items"][0]["role"] == "tutor"
    assert history_page_body["items"][0]["public_thinking_steps"] == [
        "我先定位学习者当前最需要澄清的概念。\n\n接着选择一个能够马上验证理解的小例子。",
    ]
    history_cursor = history_page_body["next_cursor"]
    assert isinstance(history_cursor, str) and history_cursor

    older_history = tutor_client.get(
        f"/api/tutor/conversations/{first_conversation_id}/history?user_id={user_id}&limit=2&cursor={history_cursor}"
    )
    assert older_history.status_code == 200
    assert older_history.json()["has_more"] is False
    assert [item["kind"] for item in older_history.json()["items"]] == ["message"]
    assert older_history.json()["items"][0]["role"] == "learner"
    assert older_history.json()["items"][0]["public_thinking_steps"] == []

    cross_conversation_history = tutor_client.get(
        f"/api/tutor/conversations/{second_conversation_id}/history?user_id={user_id}&limit=2&cursor={history_cursor}"
    )
    assert_error(cross_conversation_history, "CURSOR_INVALID", 400)

    other_turn = _first_turn(
        tutor_client,
        user_id=str(other_user["id"]),
        action_id="history-cursor-other-user",
        content="请解释 Python 的作用域。",
    )
    cross_user_history = tutor_client.get(
        f"/api/tutor/conversations/{other_turn['conversation_id']}/history?user_id={other_user['id']}&limit=2&cursor={history_cursor}"
    )
    assert_error(cross_user_history, "CURSOR_INVALID", 400)

    tampered_cursor = history_cursor[:-1] + ("A" if history_cursor[-1] != "A" else "B")
    tampered_history = tutor_client.get(
        f"/api/tutor/conversations/{first_conversation_id}/history?user_id={user_id}&limit=2&cursor={tampered_cursor}"
    )
    assert_error(tampered_history, "CURSOR_INVALID", 400)


def test_history_keeps_legacy_messages_and_exposes_only_bounded_public_process_fields(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    dispatcher, _provider = terminal_dispatcher(settings=tutor_api_settings)
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user = create_tutor_user(tutor_client)
    user_id = str(user["id"])

    accepted = _first_turn(
        tutor_client,
        user_id=user_id,
        action_id="public-process-duration",
        content="请解释异步回调为何还能访问外层变量。",
    )
    conversation_id = str(accepted["conversation_id"])
    run_id = str(accepted["run_id"])
    now = datetime.now(UTC)

    legacy = tutor_client.post(
        "/api/tutor/conversations",
        json=action_payload(user_id, "legacy-message-only-conversation"),
    )
    assert legacy.status_code == 201
    legacy_conversation_id = str(legacy.json()["conversation_id"])
    with connect() as conn:
        conn.execute(
            """
            UPDATE tutor_run_public_processes
            SET started_at = %s, finished_at = %s
            WHERE run_id = %s
            """,
            (now - timedelta(days=2), now, run_id),
        )
        conn.execute(
            """
            INSERT INTO tutor_messages (conversation_id, role, content, created_at)
            VALUES
              (%s, 'learner', '旧版 learner 消息仍应正常显示。', %s),
              (%s, 'tutor', '旧版 Tutor 回复不应伪造公开处理过程。', %s)
            """,
            (legacy_conversation_id, now - timedelta(minutes=2), legacy_conversation_id, now - timedelta(minutes=1)),
        )
        conn.commit()

    history = tutor_client.get(
        f"/api/tutor/conversations/{conversation_id}/history?user_id={user_id}&limit=40"
    )
    assert history.status_code == 200
    process = next(item for item in history.json()["items"] if item["kind"] == "process")
    assert set(process) == {
        "kind",
        "id",
        "run_id",
        "display_state",
        "steps",
        "elapsed_seconds",
        "created_at",
        "finished_at",
    }
    assert process["run_id"] == run_id
    assert process["display_state"] == "completed"
    assert process["elapsed_seconds"] == 3_600
    assert process["steps"][-1] == {
        "key": "learning_reply_generated",
        "state": "completed",
        "label": "已完成一次受控学习建议生成",
    }
    serialized_process = json.dumps(process, ensure_ascii=False, sort_keys=True)
    for protected in ("provider", "reasoning", "trace", "prompt", "diagnostic", "capability_id", "effect_id"):
        assert protected not in serialized_process

    legacy_history = tutor_client.get(
        f"/api/tutor/conversations/{legacy_conversation_id}/history?user_id={user_id}&limit=40"
    )
    assert legacy_history.status_code == 200
    legacy_items = legacy_history.json()["items"]
    assert [item["kind"] for item in legacy_items] == ["message", "message"]
    assert [item["role"] for item in legacy_items] == ["tutor", "learner"]
    assert all(item["public_thinking_steps"] == [] for item in legacy_items)
    assert all("elapsed_seconds" not in item and "steps" not in item for item in legacy_items)
