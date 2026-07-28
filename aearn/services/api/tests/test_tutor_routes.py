from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import app.routes.tutor as tutor_route
from app.core.config import Settings
from app.main import app
from tutor_public_api_support import (
    RecordingTutorDispatcher,
    action_payload,
    assert_error,
    create_tutor_user,
)


def test_tutor_routes_fail_closed_before_any_target_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def unexpected_connect():  # type: ignore[no-untyped-def]
        calls.append("connect")
        raise AssertionError("disabled Tutor route must not open a target connection")

    monkeypatch.setattr(tutor_route, "get_settings", lambda: Settings(tutor_harness_enabled=False))
    monkeypatch.setattr(tutor_route, "connect", unexpected_connect)
    client = TestClient(app)

    response = client.post(
        "/api/tutor/conversations",
        json=action_payload(str(uuid4()), "disabled-conversation"),
    )

    assert_error(response, "CUTOVER_REQUIRED", 409)
    assert calls == []


def test_tutor_conversation_and_safe_read_models(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    del tutor_api_settings
    dispatcher = RecordingTutorDispatcher()
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user = create_tutor_user(tutor_client)
    user_id = str(user["id"])

    created = tutor_client.post(
        "/api/tutor/conversations",
        json=action_payload(user_id, "conversation-create"),
    )
    assert created.status_code == 201
    conversation_id = created.json()["conversation_id"]

    replay = tutor_client.post(
        "/api/tutor/conversations",
        json=action_payload(user_id, "conversation-create"),
    )
    assert replay.status_code == 200
    assert replay.json()["conversation_id"] == conversation_id
    assert replay.json()["idempotent_replayed"] is True

    conflict = tutor_client.post(
        "/api/tutor/conversations",
        headers={"Idempotency-Key": "shared-conversation-key"},
        json=action_payload(user_id, "different-client-action"),
    )
    assert conflict.status_code == 201
    collision = tutor_client.post(
        "/api/tutor/conversations",
        headers={"Idempotency-Key": "shared-conversation-key"},
        json=action_payload(user_id, "different-client-action-2", conversation_id=str(uuid4())),
    )
    assert_error(collision, "IDEMPOTENCY_CONFLICT", 409)

    for endpoint, expected in (
        (f"/api/tutor/activity?user_id={user_id}", {"items": []}),
        (f"/api/tutor/inbox?user_id={user_id}", {"items": []}),
        (f"/api/tutor/memory?user_id={user_id}", {"items": []}),
    ):
        response = tutor_client.get(endpoint)
        assert response.status_code == 200
        assert response.json() == expected

    plans = tutor_client.get(f"/api/tutor/plans/revisions?user_id={user_id}")
    assert plans.status_code == 200
    assert plans.json() == {"active_revision_id": None, "items": []}

    rollback = tutor_client.post(
        "/api/tutor/plans/rollback",
        json=action_payload(user_id, "empty-plan-rollback"),
    )
    assert_error(rollback, "PLAN_ROLLBACK_UNAVAILABLE", 409)

    preferences = tutor_client.get(f"/api/tutor/preferences?user_id={user_id}")
    assert preferences.status_code == 200
    current = preferences.json()
    assert current["inferred_memory_enabled"] is False
    assert current["proactive_paused"] is False

    updated = tutor_client.patch(
        "/api/tutor/preferences",
        json=action_payload(
            user_id,
            "disable-inferred-memory",
            inferred_memory_enabled=False,
            expected_memory_setting_version=current["memory_setting_version"],
            proactive_paused=True,
        ),
    )
    assert updated.status_code == 200
    assert updated.json()["inferred_memory_enabled"] is False
    assert updated.json()["proactive_paused"] is True

    missing_memory = tutor_client.patch(
        f"/api/tutor/memory/{uuid4()}",
        json=action_payload(user_id, "missing-memory", statement="保留变量在外层作用域。"),
    )
    assert_error(missing_memory, "MEMORY_ENTRY_NOT_FOUND", 404)

    missing_inbox = tutor_client.post(
        f"/api/tutor/inbox/{uuid4()}/read",
        json=action_payload(user_id, "missing-inbox"),
    )
    assert_error(missing_inbox, "INBOX_ITEM_NOT_FOUND", 404)

    missing_run = tutor_client.get(f"/api/tutor/runs/{uuid4()}?user_id={user_id}")
    assert_error(missing_run, "TUTOR_RUN_NOT_FOUND", 404)
    assert dispatcher.calls == []