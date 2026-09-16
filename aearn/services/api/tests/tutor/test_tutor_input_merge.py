from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.routes.tutor as tutor_route
from app.agents.harness.contracts import (
    TutorDecision,
    TutorProviderResult,
    TutorTerminalOutcome,
)
from app.core.config import Settings
from app.db.connection import connect
from app.services.tutor.interactive import TutorInteractiveRunDispatcher
from app.services.tutor.public_api import TutorPublicService
from tests.support.tutor_public_api_support import (
    RecordingTutorDispatcher,
    action_payload,
    assert_error,
    create_tutor_user,
    terminal_dispatcher,
)


def test_ordinary_inputs_queue_behind_the_active_foreground_turn(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    """A running thread_turn_v2 keeps one foreground turn and queues normal sends FIFO."""

    del tutor_api_settings
    dispatcher = RecordingTutorDispatcher()
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user = create_tutor_user(tutor_client)
    user_id = str(user["id"])
    conversation = tutor_client.post(
        "/api/tutor/conversations",
        json=action_payload(user_id, "turnrun-queue-conversation"),
    )
    assert conversation.status_code == 201
    conversation_id = str(conversation.json()["conversation_id"])

    first = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(user_id, "ordinary-turn-0", content="第 1 条普通消息：继续说明闭包与作用域。"),
    )
    assert first.status_code == 202
    first_body = first.json()
    run_id = str(first_body["run_id"])
    assert first_body["input_revision"] == 1
    assert first_body["replaced_run_id"] is None

    queued_items: list[dict[str, object]] = []
    last_action_id = ""
    last_content = ""
    for index in range(1, 10):
        last_action_id = f"ordinary-turn-{index}"
        last_content = f"第 {index + 1} 条普通消息：继续说明闭包与作用域。"
        response = tutor_client.post(
            f"/api/tutor/conversations/{conversation_id}/inputs",
            json=action_payload(user_id, last_action_id, content=last_content),
        )
        assert response.status_code == 202
        body = response.json()
        assert body["conversation_id"] == conversation_id
        assert body["queued"] is True
        assert body["pending_count"] == index
        queued_items.append(body["queue_item"])

    assert dispatcher.calls == [(user_id, run_id)]
    queue = tutor_client.get(f"/api/tutor/conversations/{conversation_id}/queue?user_id={user_id}")
    assert queue.status_code == 200
    assert [item["item_id"] for item in queue.json()["items"]] == [item["item_id"] for item in queued_items]

    replay = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(user_id, last_action_id, content=last_content),
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replayed"] is True
    assert replay.json()["queued"] is True
    assert replay.json()["queue_item"]["item_id"] == queued_items[-1]["item_id"]
    assert dispatcher.calls == [(user_id, run_id)]

    normal_run_input = tutor_client.post(
        f"/api/tutor/runs/{run_id}/inputs",
        json=action_payload(user_id, "ordinary-run-input-rejected", content="普通聊天不能复用当前 run。"),
    )
    assert_error(normal_run_input, "TUTOR_LEGACY_CONTINUATION_DISABLED", 410)

    with connect() as conn:
        row = conn.execute(
            """
            SELECT input_revision, iteration_count, model_call_count, terminal_outcome,
                   cancelled_at, superseded_by_run_id
            FROM tutor_runs WHERE id = %s AND user_id = %s
            """,
            (run_id, user_id),
        ).fetchone()
        message_count = conn.execute(
            "SELECT count(*) AS count FROM tutor_messages WHERE conversation_id = %s",
            (conversation_id,),
        ).fetchone()
        process_count = conn.execute(
            "SELECT count(*) AS count FROM tutor_run_public_processes WHERE conversation_id = %s",
            (conversation_id,),
        ).fetchone()
        queue_count = conn.execute(
            "SELECT count(*) AS count FROM tutor_queued_inputs WHERE conversation_id = %s AND state = 'pending'",
            (conversation_id,),
        ).fetchone()
        receipt = conn.execute(
            """
            SELECT request_hash, response_json::text AS response_json
            FROM tutor_api_idempotency_records
            WHERE user_id = %s AND operation = 'tutor.conversation.input'
            ORDER BY created_at ASC LIMIT 1
            """,
            (user_id,),
        ).fetchone()
    assert row == {
        "input_revision": 1,
        "iteration_count": 0,
        "model_call_count": 0,
        "terminal_outcome": None,
        "cancelled_at": None,
        "superseded_by_run_id": None,
    }
    assert message_count == {"count": 1}
    assert process_count == {"count": 1}
    assert queue_count == {"count": 9}
    assert receipt is not None
    assert "闭包与作用域" not in str(receipt["response_json"])
    assert "闭包与作用域" not in str(receipt["request_hash"])

    other_user = create_tutor_user(tutor_client)
    cross_user = tutor_client.post(
        f"/api/tutor/runs/{run_id}/inputs",
        json=action_payload(str(other_user["id"]), "cross-user-run-input", content="不属于当前用户的 run。"),
    )
    assert_error(cross_user, "TUTOR_LEGACY_CONTINUATION_DISABLED", 410)


def test_interactive_turn_uses_deepseek_v4_flash_context_window_after_output_reservation(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    del tutor_api_settings
    settings = Settings(llm_type="deepseek", deepseek_model="deepseek-flash", tutor_thread_turn_v2_enabled=True)
    dispatcher = RecordingTutorDispatcher()
    monkeypatch.setattr(tutor_route, "get_settings", lambda: settings)
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user = create_tutor_user(tutor_client)
    user_id = str(user["id"])

    accepted = tutor_client.post(
        "/api/tutor/conversations/first-turn",
        json=action_payload(user_id, "deepseek-token-window", content="请解释变量作用域。"),
    )

    assert accepted.status_code == 202
    run_id = str(accepted.json()["run_id"])
    assert dispatcher.calls == [(user_id, run_id)]
    with connect() as conn:
        row = conn.execute(
            "SELECT policy_json FROM tutor_runs WHERE id = %s AND user_id = %s",
            (run_id, user_id),
        ).fetchone()
    assert row is not None
    assert row["policy_json"]["context_token_budget"] == 131_072
    budget_policy = row["policy_json"]["context_budget_policy"]
    assert budget_policy["capability"]["context_window_tokens"] == 192_512
    assert budget_policy["capability"]["max_output_reserve_tokens"] == 61_440
    assert budget_policy["capability"]["capability_version"] == "deepseek-flash-responses-v2"
    assert budget_policy["mode_targets"] == {
        "compact": 16_000,
        "normal": 64_000,
        "complex": 96_000,
        "extended": 130_688,
    }
    assert budget_policy["max_expansions"] == 1
    assert budget_policy["estimator_version"] == "utf8_bytes_v1"


def test_first_turn_is_idempotent_and_dispatches_only_the_new_run(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    del tutor_api_settings
    dispatcher = RecordingTutorDispatcher()
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user = create_tutor_user(tutor_client)
    user_id = str(user["id"])
    content = "我想从 JavaScript 闭包开始，但不要先创建空会话。"
    headers = {"Idempotency-Key": "first-turn-replay-key"}

    first = tutor_client.post(
        "/api/tutor/conversations/first-turn",
        headers=headers,
        json=action_payload(user_id, "first-turn-accept", content=content),
    )

    assert first.status_code == 202
    first_body = first.json()
    conversation_id = str(first_body["conversation_id"])
    first_run_id = str(first_body["run_id"])
    assert first_body["merged"] is False
    assert first_body["input_revision"] == 1
    process = first_body["process"]
    assert process["kind"] == "process"
    assert process["run_id"] == first_run_id
    assert process["display_state"] == "thinking"
    assert process["steps"] == [{"key": "input_received", "state": "completed", "label": "已接收你的问题"}]
    assert process["finished_at"] is None
    assert dispatcher.calls == [(user_id, first_run_id)]

    replay = tutor_client.post(
        "/api/tutor/conversations/first-turn",
        headers=headers,
        json=action_payload(user_id, "first-turn-replay", content=content),
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replayed"] is True
    assert replay.json()["conversation_id"] == conversation_id
    assert replay.json()["run_id"] == first_run_id
    assert dispatcher.calls == [(user_id, first_run_id)]

    collision = tutor_client.post(
        "/api/tutor/conversations/first-turn",
        headers=headers,
        json=action_payload(user_id, "first-turn-conflict", content="相同 key 不能接收另一条首发消息。"),
    )
    assert_error(collision, "IDEMPOTENCY_CONFLICT", 409)

    with connect() as conn:
        conversation_count = conn.execute(
            "SELECT count(*) AS count FROM tutor_conversations WHERE user_id = %s",
            (user_id,),
        ).fetchone()
        run_count = conn.execute(
            "SELECT count(*) AS count FROM tutor_runs WHERE user_id = %s",
            (user_id,),
        ).fetchone()
        message_count = conn.execute(
            "SELECT count(*) AS count FROM tutor_messages WHERE conversation_id = %s",
            (conversation_id,),
        ).fetchone()
        process_count = conn.execute(
            "SELECT count(*) AS count FROM tutor_run_public_processes WHERE conversation_id = %s",
            (conversation_id,),
        ).fetchone()
    assert conversation_count == {"count": 1}
    assert run_count == {"count": 1}
    assert message_count == {"count": 1}
    assert process_count == {"count": 1}

    next_turn = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(user_id, "first-turn-follow-up", content="这是第二条普通消息，应进入 Queue。"),
    )
    assert next_turn.status_code == 202
    assert next_turn.json()["queued"] is True
    assert next_turn.json()["conversation_id"] == conversation_id
    assert dispatcher.calls == [(user_id, first_run_id)]


def test_conversation_title_fills_once_without_learner_text_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    dispatcher, provider = terminal_dispatcher(
        settings=tutor_api_settings,
        message="我们先用一个最小例子确认闭包何时保留外层变量。",
    )
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user = create_tutor_user(tutor_client)
    user_id = str(user["id"])
    learner_text = "我原始的首条提问不能被拿来当作会话标题。"

    first = tutor_client.post(
        "/api/tutor/conversations/first-turn",
        json=action_payload(user_id, "untitled-first-turn", content=learner_text),
    )
    assert first.status_code == 202
    conversation_id = str(first.json()["conversation_id"])

    untitled_list = tutor_client.get(f"/api/tutor/conversations?user_id={user_id}&limit=8")
    assert untitled_list.status_code == 200
    untitled_item = next(item for item in untitled_list.json()["items"] if item["conversation_id"] == conversation_id)
    assert untitled_item["title"] == "新对话"
    assert learner_text not in untitled_list.text

    provider.conversation_title = "JavaScript 闭包练习"
    second = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(user_id, "title-fill-turn", content="请继续解释回调函数里的变量。"),
    )
    assert second.status_code == 202

    provider.conversation_title = "不应覆盖既有标题"
    third = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(user_id, "title-overwrite-turn", content="再给我一个不同作用域的例子。"),
    )
    assert third.status_code == 202

    title_list = tutor_client.get(f"/api/tutor/conversations?user_id={user_id}&limit=8")
    assert title_list.status_code == 200
    titled_item = next(item for item in title_list.json()["items"] if item["conversation_id"] == conversation_id)
    assert titled_item["title"] == "JavaScript 闭包练习"
    with connect() as conn:
        stored = conn.execute(
            "SELECT title FROM tutor_conversations WHERE id = %s AND user_id = %s",
            (conversation_id, user_id),
        ).fetchone()
    assert stored == {"title": "JavaScript 闭包练习"}


def test_post_provider_normal_send_is_queued_without_invalidating_the_current_result(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    class QueueingProvider:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.queued_item_id: str | None = None

        def decide(self, *, run, context, thinking_sink=None):  # type: ignore[no-untyped-def]
            del context, thinking_sink
            self.calls.append(run.run_id)
            with connect() as queue_conn:
                queued = TutorPublicService(queue_conn).accept_conversation_input(
                    user_id=run.user_id,
                    conversation_id=run.conversation_id,
                    content="这条新消息应等待当前 provider 结果完成。",
                    idempotency_key=f"post-provider-queue:{run.run_id}",
                )
                queue_conn.commit()
            assert queued["queued"] is True
            self.queued_item_id = str(queued["queue_item"]["item_id"])
            return TutorProviderResult(
                decision=TutorDecision(
                    public_message="当前 provider 结果仍应安全写入公开时间线。",
                    conversation_title="闭包作用域",
                    terminal_outcome=TutorTerminalOutcome.COMPLETED,
                )
            )

    provider = QueueingProvider()
    dispatcher = TutorInteractiveRunDispatcher(
        settings=tutor_api_settings,
        provider_factory=lambda _settings: provider,
    )
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user = create_tutor_user(tutor_client)
    user_id = str(user["id"])

    accepted = tutor_client.post(
        "/api/tutor/conversations/first-turn",
        json=action_payload(user_id, "post-provider-queue-first-turn", content="先解释闭包的作用域。"),
    )
    assert accepted.status_code == 202
    run_id = str(accepted.json()["run_id"])
    conversation_id = str(accepted.json()["conversation_id"])
    assert provider.calls == [run_id]
    assert provider.queued_item_id is not None

    with connect() as conn:
        run = conn.execute(
            "SELECT terminal_outcome, superseded_by_run_id FROM tutor_runs WHERE id = %s AND user_id = %s",
            (run_id, user_id),
        ).fetchone()
        title = conn.execute(
            "SELECT title FROM tutor_conversations WHERE id = %s AND user_id = %s",
            (conversation_id, user_id),
        ).fetchone()
        tutor_messages = conn.execute(
            "SELECT count(*) AS count FROM tutor_messages WHERE conversation_id = %s AND role = 'tutor'",
            (conversation_id,),
        ).fetchone()
        queued = conn.execute(
            "SELECT state, content FROM tutor_queued_inputs WHERE id = %s",
            (provider.queued_item_id,),
        ).fetchone()
        process = conn.execute(
            "SELECT display_state FROM tutor_run_public_processes WHERE run_id = %s",
            (run_id,),
        ).fetchone()

    assert run == {"terminal_outcome": "completed", "superseded_by_run_id": None}
    assert title == {"title": "闭包作用域"}
    assert tutor_messages == {"count": 1}
    assert queued == {"state": "pending", "content": "这条新消息应等待当前 provider 结果完成。"}
    assert process == {"display_state": "completed"}
