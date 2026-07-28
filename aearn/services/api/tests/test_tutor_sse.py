from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.routes.tutor as tutor_route
from app.agents.harness.contracts import TutorTerminalOutcome
from app.core.config import Settings
from tutor_public_api_support import (
    action_payload,
    assert_error,
    create_tutor_user,
    parse_sse_events,
    terminal_dispatcher,
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