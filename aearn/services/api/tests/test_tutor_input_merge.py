from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.routes.tutor as tutor_route
from app.agents.harness.contracts import (
    TutorCapabilityRequest,
    TutorDecision,
    TutorEffectProposal,
    TutorProviderResult,
    TutorTerminalOutcome,
)
from app.core.config import Settings
from app.db.connection import connect
from app.services.tutor.interactive import TutorInteractiveRunDispatcher
from app.services.tutor.public_api import TutorPublicService
from tutor_public_api_support import (
    RecordingTutorDispatcher,
    action_payload,
    assert_error,
    create_tutor_user,
    terminal_dispatcher,
)


def test_ordinary_turns_create_fresh_runs_and_supersede_the_prior_foreground_run(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    """A long-lived conversation never reuses a normal interactive TurnRun."""

    del tutor_api_settings
    dispatcher = RecordingTutorDispatcher()
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user = create_tutor_user(tutor_client)
    user_id = str(user["id"])
    conversation = tutor_client.post(
        "/api/tutor/conversations",
        json=action_payload(user_id, "turnrun-compatibility-conversation"),
    )
    assert conversation.status_code == 201
    conversation_id = str(conversation.json()["conversation_id"])

    run_ids: list[str] = []
    last_action_id = ""
    last_content = ""
    for index in range(10):
        action_id = f"ordinary-turn-{index}"
        content = f"第 {index + 1} 条普通消息：继续说明闭包与作用域。"
        response = tutor_client.post(
            f"/api/tutor/conversations/{conversation_id}/inputs",
            json=action_payload(user_id, action_id, content=content),
        )
        assert response.status_code == 202
        body = response.json()
        run_id = str(body["run_id"])
        assert body["conversation_id"] == conversation_id
        assert body["input_revision"] == 1
        assert body["merged"] is False
        assert body["run"]["input_revision"] == 1
        assert body["run"]["iteration_count"] == 0
        assert body["run"]["model_call_count"] == 0
        assert body["run"]["terminal_outcome"] is None
        assert body["process"]["display_state"] == "thinking"
        assert body["process"]["steps"] == [
            {"key": "input_received", "state": "completed", "label": "已接收你的问题"}
        ]
        if run_ids:
            assert body["replaced_run_id"] == run_ids[-1]
            assert body["replaced_process"]["run_id"] == run_ids[-1]
            assert body["replaced_process"]["display_state"] == "superseded"
            assert body["replaced_process"]["steps"][-1] == {
                "key": "replaced_by_newer_input",
                "state": "completed",
                "label": "已根据你的新消息更新本轮处理",
            }
        else:
            assert body["replaced_run_id"] is None
            assert body["replaced_process"] is None
        run_ids.append(run_id)
        last_action_id = action_id
        last_content = content

    assert len(set(run_ids)) == 10
    assert dispatcher.calls == [(user_id, run_id) for run_id in run_ids]

    replay = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(user_id, last_action_id, content=last_content),
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replayed"] is True
    assert replay.json()["run_id"] == run_ids[-1]
    assert dispatcher.calls == [(user_id, run_id) for run_id in run_ids]

    normal_run_input = tutor_client.post(
        f"/api/tutor/runs/{run_ids[-1]}/inputs",
        json=action_payload(user_id, "ordinary-run-input-rejected", content="普通聊天不能复用当前 run。"),
    )
    assert_error(normal_run_input, "RUN_NOT_ACTIVE", 409)

    with connect() as conn:
        for index, run_id in enumerate(run_ids):
            row = conn.execute(
                """
                SELECT input_revision, iteration_count, model_call_count, terminal_outcome,
                       cancelled_at, superseded_by_run_id
                FROM tutor_runs
                WHERE id = %s AND user_id = %s
                """,
                (run_id, user_id),
            ).fetchone()
            assert row is not None
            assert row["input_revision"] == 1
            assert row["iteration_count"] == 0
            assert row["model_call_count"] == 0
            if index < len(run_ids) - 1:
                assert row["terminal_outcome"] == "cancelled"
                assert row["cancelled_at"] is not None
                assert str(row["superseded_by_run_id"]) == run_ids[index + 1]
            else:
                assert row["terminal_outcome"] is None
                assert row["cancelled_at"] is None
                assert row["superseded_by_run_id"] is None
        message_count = conn.execute(
            "SELECT count(*) AS count FROM tutor_messages WHERE conversation_id = %s",
            (conversation_id,),
        ).fetchone()
        process_count = conn.execute(
            "SELECT count(*) AS count FROM tutor_run_public_processes WHERE conversation_id = %s",
            (conversation_id,),
        ).fetchone()
        receipt = conn.execute(
            """
            SELECT request_hash, response_json::text AS response_json
            FROM tutor_api_idempotency_records
            WHERE user_id = %s AND operation = 'tutor.conversation.input'
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
    assert message_count == {"count": 10}
    assert process_count == {"count": 10}
    assert receipt is not None
    assert "闭包与作用域" not in str(receipt["response_json"])
    assert "闭包与作用域" not in str(receipt["request_hash"])

    other_user = create_tutor_user(tutor_client)
    cross_user = tutor_client.post(
        f"/api/tutor/runs/{run_ids[-1]}/inputs",
        json=action_payload(str(other_user["id"]), "cross-user-run-input", content="不属于当前用户的 run。"),
    )
    assert_error(cross_user, "TUTOR_RUN_NOT_FOUND", 404)


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
        json=action_payload(user_id, "first-turn-follow-up", content="这是第二条普通消息，应生成新的有限 run。"),
    )
    assert next_turn.status_code == 202
    assert next_turn.json()["run_id"] != first_run_id
    assert dispatcher.calls == [(user_id, first_run_id), (user_id, str(next_turn.json()["run_id"]))]


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


def test_post_provider_replacement_cannot_publish_stale_message_title_capability_or_effect(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    class SupersedingProvider:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.replacement_run_id: str | None = None

        def decide(self, *, run, context):  # type: ignore[no-untyped-def]
            del context
            self.calls.append(run.run_id)
            with connect() as replacement_conn:
                replacement = TutorPublicService(replacement_conn).accept_conversation_input(
                    user_id=run.user_id,
                    conversation_id=run.conversation_id,
                    content="这条新消息必须取代 provider 返回前的旧结果。",
                    idempotency_key=f"post-provider-replacement:{run.run_id}",
                )
                replacement_conn.commit()
            self.replacement_run_id = str(replacement["run_id"])
            return TutorProviderResult(
                decision=TutorDecision(
                    public_message="这条旧 provider 结果不能写入公开时间线。",
                    conversation_title="不能写入的旧标题",
                    capability_requests=(TutorCapabilityRequest("stale-capability", "safe-capability"),),
                    effect_proposals=(TutorEffectProposal("stale-effect", "save_note", expected_input_revision=1),),
                    terminal_outcome=TutorTerminalOutcome.COMPLETED,
                )
            )

    provider = SupersedingProvider()
    dispatcher = TutorInteractiveRunDispatcher(
        settings=tutor_api_settings,
        provider_factory=lambda _settings: provider,
    )
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user = create_tutor_user(tutor_client)
    user_id = str(user["id"])

    accepted = tutor_client.post(
        "/api/tutor/conversations/first-turn",
        json=action_payload(user_id, "post-provider-race-first-turn", content="先解释闭包的作用域。"),
    )
    assert accepted.status_code == 202
    old_run_id = str(accepted.json()["run_id"])
    conversation_id = str(accepted.json()["conversation_id"])
    assert provider.calls == [old_run_id]
    assert provider.replacement_run_id is not None
    assert provider.replacement_run_id != old_run_id

    with connect() as conn:
        old_run = conn.execute(
            """
            SELECT terminal_outcome, superseded_by_run_id
            FROM tutor_runs
            WHERE id = %s AND user_id = %s
            """,
            (old_run_id, user_id),
        ).fetchone()
        title = conn.execute(
            "SELECT title FROM tutor_conversations WHERE id = %s AND user_id = %s",
            (conversation_id, user_id),
        ).fetchone()
        old_tutor_messages = conn.execute(
            """
            SELECT count(*) AS count
            FROM tutor_messages
            WHERE conversation_id = %s AND role = 'tutor'
            """,
            (conversation_id,),
        ).fetchone()
        stale_capabilities = conn.execute(
            "SELECT count(*) AS count FROM tutor_capability_invocations WHERE run_id = %s",
            (old_run_id,),
        ).fetchone()
        stale_effects = conn.execute(
            "SELECT count(*) AS count FROM tutor_effects WHERE run_id = %s",
            (old_run_id,),
        ).fetchone()
        old_process = conn.execute(
            "SELECT display_state FROM tutor_run_public_processes WHERE run_id = %s",
            (old_run_id,),
        ).fetchone()

    assert old_run is not None
    assert old_run["terminal_outcome"] == "cancelled"
    assert str(old_run["superseded_by_run_id"]) == provider.replacement_run_id
    assert title == {"title": None}
    assert old_tutor_messages == {"count": 0}
    assert stale_capabilities == {"count": 0}
    assert stale_effects == {"count": 0}
    assert old_process == {"display_state": "superseded"}
