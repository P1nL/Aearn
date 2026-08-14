from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.routes.tutor as tutor_route
from app.agents.harness.contracts import TutorTerminalOutcome
from app.core.config import Settings
from app.db.connection import connect
from app.services.tutor.public_api import TutorPublicService
from tutor_public_api_support import (
    action_payload,
    assert_error,
    create_tutor_user,
    parse_sse_events,
    terminal_dispatcher,
    waiting_dispatcher,
)


def test_tutor_sse_replays_safe_ordered_terminal_timeline(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    dispatcher, provider = terminal_dispatcher(
        settings=tutor_api_settings,
        message="先比较回调与外层作用域，再用一个小例子验证。",
    )
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user = create_tutor_user(tutor_client)
    user_id = str(user["id"])
    conversation = tutor_client.post(
        "/api/tutor/conversations",
        json=action_payload(user_id, "sse-conversation"),
    )
    assert conversation.status_code == 201
    conversation_id = str(conversation.json()["conversation_id"])

    raw_prompt = "raw learner prompt should never appear in SSE; C:\\private\\path"
    accepted = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(user_id, "sse-input", content=raw_prompt),
    )
    assert accepted.status_code == 202
    run_id = str(accepted.json()["run_id"])
    assert provider.calls == [(run_id, 1)]

    response = tutor_client.get(f"/api/tutor/runs/{run_id}/events?user_id={user_id}")
    assert response.status_code == 200
    events = parse_sse_events(response.text)
    assert [event["event"] for event in events] == ["input_accepted", "done"]
    sequences = [int(str(event["id"])) for event in events]
    assert sequences == sorted(set(sequences))
    assert raw_prompt not in response.text
    assert "private\\path" not in response.text
    assert "provider" not in response.text.lower()
    assert "trace" not in response.text.lower()
    assert "hidden" not in response.text.lower()
    assert "code" not in response.text.lower()

    done = events[-1]["data"]
    assert done["public_message"] == "先比较回调与外层作用域，再用一个小例子验证。"
    assert done["result_ref"] == {"type": "TutorRun", "id": run_id}

    replay = tutor_client.get(
        f"/api/tutor/runs/{run_id}/events?user_id={user_id}",
        headers={"Last-Event-ID": str(sequences[0])},
    )
    assert replay.status_code == 200
    replay_events = parse_sse_events(replay.text)
    assert [event["event"] for event in replay_events] == ["done"]
    assert replay_events[0]["id"] == str(sequences[-1])

    consumed = tutor_client.get(
        f"/api/tutor/runs/{run_id}/events?user_id={user_id}",
        headers={"Last-Event-ID": str(sequences[-1])},
    )
    assert consumed.status_code == 200
    assert consumed.text == ""

    invalid_cursor = tutor_client.get(
        f"/api/tutor/runs/{run_id}/events?user_id={user_id}",
        headers={"Last-Event-ID": "not-a-run-cursor"},
    )
    assert_error(invalid_cursor, "SSE_CURSOR_INVALID", 400)


def test_tutor_sse_maps_terminal_model_failure_to_safe_error(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    dispatcher, provider = terminal_dispatcher(settings=tutor_api_settings)
    provider.outcome = TutorTerminalOutcome.MODEL_UNAVAILABLE
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user = create_tutor_user(tutor_client)
    user_id = str(user["id"])
    conversation = tutor_client.post(
        "/api/tutor/conversations",
        json=action_payload(user_id, "sse-error-conversation"),
    )
    assert conversation.status_code == 201
    run = tutor_client.post(
        f"/api/tutor/conversations/{conversation.json()['conversation_id']}/inputs",
        json=action_payload(user_id, "sse-error-input", content="模型不可用时仍要返回安全错误。"),
    )
    assert run.status_code == 202
    run_id = str(run.json()["run_id"])

    response = tutor_client.get(f"/api/tutor/runs/{run_id}/events?user_id={user_id}")
    assert response.status_code == 200
    events = parse_sse_events(response.text)
    assert [event["event"] for event in events] == ["input_accepted", "error"]
    error = events[-1]["data"]["error"]
    assert error["code"] == "MODEL_UNAVAILABLE"
    assert "fixture_terminal" not in response.text

    public_run = tutor_client.get(f"/api/tutor/runs/{run_id}?user_id={user_id}")
    assert public_run.status_code == 200
    assert "diagnostic_code" not in public_run.json()
    assert "fixture_terminal" not in public_run.text

    with connect() as conn:
        internal = conn.execute(
            "SELECT terminal_diagnostic_code FROM tutor_runs WHERE id = %s AND user_id = %s",
            (run_id, user_id),
        ).fetchone()
    assert internal == {"terminal_diagnostic_code": "fixture_terminal"}


def test_tutor_typed_request_response_creates_a_fresh_turn(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    dispatcher, provider = waiting_dispatcher(settings=tutor_api_settings, message="请继续补充你的学习背景。")
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user = create_tutor_user(tutor_client)
    user_id = str(user["id"])
    conversation = tutor_client.post(
        "/api/tutor/conversations",
        json=action_payload(user_id, "typed-follow-up-conversation"),
    )
    assert conversation.status_code == 201
    conversation_id = str(conversation.json()["conversation_id"])

    first = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(user_id, "typed-follow-up-first", content="我想学习做网站。"),
    )
    assert first.status_code == 202
    source_turn_id = str(first.json()["run_id"])
    assert provider.calls == [(source_turn_id, 1)]

    snapshot = tutor_client.get(
        f"/api/tutor/conversations/{conversation_id}/snapshot?user_id={user_id}"
    )
    assert snapshot.status_code == 200
    pending = snapshot.json()["pending_requests"]
    assert len(pending) == 1
    request = pending[0]
    assert request["request_kind"] == "clarification"
    assert request["actor"] == "learner"
    assert request["state"] == "pending"

    legacy_follow_up = tutor_client.post(
        f"/api/tutor/runs/{source_turn_id}/inputs",
        json=action_payload(user_id, "typed-follow-up-legacy", content="我完全没有基础。"),
    )
    assert legacy_follow_up.status_code == 410
    assert legacy_follow_up.json()["error"]["code"] == "TUTOR_LEGACY_CONTINUATION_DISABLED"

    response_body = {
        "user_id": user_id,
        "client_action_id": "typed-follow-up-response",
        "expected_request_version": request["version"],
        "response": {"kind": "clarification", "answer_text": "我完全没有基础。"},
    }
    follow_up = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/requests/{request['id']}/responses",
        json=response_body,
    )
    assert follow_up.status_code == 202
    answer_turn_id = str(follow_up.json()["run_id"])
    assert answer_turn_id != source_turn_id
    assert follow_up.json()["request"]["state"] == "answered"
    assert follow_up.json()["response_replayed"] is False
    assert provider.calls == [(source_turn_id, 1), (answer_turn_id, 1)]

    replay = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/requests/{request['id']}/responses",
        json={**response_body, "client_action_id": "typed-follow-up-response-replay"},
    )
    assert replay.status_code == 202
    assert replay.json()["run_id"] == answer_turn_id
    assert replay.json()["response_replayed"] is True

    conflict = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/requests/{request['id']}/responses",
        json={
            **response_body,
            "client_action_id": "typed-follow-up-response-conflict",
            "response": {"kind": "clarification", "answer_text": "不同回答"},
        },
    )
    assert conflict.status_code == 409

    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id::text AS id, response_to_request_id::text AS response_to_request_id,
                   completion_reason, input_revision, model_call_count,
                   active_lease_owner_id, active_lease_expires_at,
                   (policy_json ->> 'deadline') AS deadline
            FROM tutor_runs
            WHERE id IN (%s, %s)
            ORDER BY id
            """,
            (source_turn_id, answer_turn_id),
        ).fetchall()
        request_row = conn.execute(
            """
            SELECT state, version, answer_turn_id::text AS answer_turn_id,
                   answer_message_id::text AS answer_message_id
            FROM tutor_interaction_requests WHERE item_id = %s
            """,
            (request["id"],),
        ).fetchone()
    by_id = {row["id"]: row for row in rows}
    assert by_id[source_turn_id]["completion_reason"] == "awaiting_user"
    assert by_id[answer_turn_id]["response_to_request_id"] == request["request_id"]
    assert by_id[answer_turn_id]["input_revision"] == 1
    assert by_id[answer_turn_id]["model_call_count"] == 1
    assert by_id[source_turn_id]["deadline"] != by_id[answer_turn_id]["deadline"]
    assert all(row["active_lease_owner_id"] is None and row["active_lease_expires_at"] is None for row in rows)
    assert request_row is not None
    assert request_row["state"] == "answered"
    assert request_row["version"] == 2
    assert request_row["answer_turn_id"] == answer_turn_id
    assert request_row["answer_message_id"] is not None


def test_tutor_event_replay_projects_terminal_request_without_raw_input(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    message = "先明确网站面向谁、要解决什么问题，再从一个最小页面开始。"
    dispatcher, provider = waiting_dispatcher(settings=tutor_api_settings, message=message)
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user = create_tutor_user(tutor_client)
    user_id = str(user["id"])
    conversation = tutor_client.post(
        "/api/tutor/conversations",
        json=action_payload(user_id, "typed-message-conversation"),
    )
    assert conversation.status_code == 201
    conversation_id = str(conversation.json()["conversation_id"])
    raw_prompt = "请帮我做一个网站，原文不应通过事件回放泄露。"
    accepted = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(user_id, "typed-message-input", content=raw_prompt),
    )
    assert accepted.status_code == 202
    run_id = str(accepted.json()["run_id"])
    assert provider.calls == [(run_id, 1)]

    with connect() as conn:
        events = TutorPublicService(conn).replay_events(user_id=user_id, run_id=run_id, after_sequence=0)

    event_types = [event.event_type for event in events]
    assert event_types[0] == "input_accepted"
    assert event_types[-1] == "done"
    assert events[-1].terminal is True
    projected = repr([event.data for event in events])
    assert raw_prompt not in projected
    assert message not in projected
    for protected in ("provider", "trace", "capability_id", "effect_id"):
        assert protected not in projected

    snapshot = tutor_client.get(
        f"/api/tutor/conversations/{conversation_id}/snapshot?user_id={user_id}"
    )
    assert snapshot.status_code == 200
    pending = snapshot.json()["pending_requests"]
    assert len(pending) == 1
    assert pending[0]["prompt"] == message
    assert pending[0]["presentation"]["type"] == "text"
    assert snapshot.json()["active_turn"] is None

    public_run = tutor_client.get(f"/api/tutor/runs/{run_id}?user_id={user_id}")
    assert public_run.status_code == 200
    assert public_run.json()["status"] == "completed"
    assert public_run.json()["terminal_outcome"] == "completed"
    assert public_run.json()["completion_reason"] == "awaiting_user"
    assert public_run.json()["continuation_kind"] is None
