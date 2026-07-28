from __future__ import annotations

from datetime import UTC, datetime
import pytest
from fastapi.testclient import TestClient

import app.routes.tutor as tutor_route
from app.core.config import Settings
from app.db.connection import connect
from app.services.tutor.persistence import PostgresTutorRepository
from tutor_public_api_support import (
    RecordingTutorDispatcher,
    action_payload,
    assert_error,
    create_tutor_user,
)


def test_active_run_merges_follow_up_input_and_preserves_idempotency(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    del tutor_api_settings
    dispatcher = RecordingTutorDispatcher()
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user = create_tutor_user(tutor_client)
    user_id = str(user["id"])
    conversation = tutor_client.post(
        "/api/tutor/conversations",
        json=action_payload(user_id, "merge-conversation"),
    )
    assert conversation.status_code == 201
    conversation_id = str(conversation.json()["conversation_id"])

    first = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(user_id, "merge-input-one", content="我想先理解闭包中的变量作用域。"),
    )
    assert first.status_code == 202
    first_body = first.json()
    run_id = str(first_body["run_id"])
    assert first_body["input_revision"] == 1
    assert first_body["merged"] is False

    second = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(user_id, "merge-input-two", content="再比较一下回调里和外层的变量。"),
    )
    assert second.status_code == 202
    second_body = second.json()
    assert second_body["run_id"] == run_id
    assert second_body["input_revision"] == 2
    assert second_body["merged"] is True
    assert dispatcher.calls == [(user_id, run_id), (user_id, run_id)]

    replay = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(user_id, "merge-input-two", content="再比较一下回调里和外层的变量。"),
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replayed"] is True
    assert replay.json()["run_id"] == run_id
    assert dispatcher.calls == [(user_id, run_id), (user_id, run_id)]

    conflict = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        headers={"Idempotency-Key": "same-target-input"},
        json=action_payload(user_id, "merge-input-header-one", content="同一幂等键的第一条消息。"),
    )
    assert conflict.status_code == 202
    collision = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        headers={"Idempotency-Key": "same-target-input"},
        json=action_payload(user_id, "merge-input-header-two", content="同一幂等键但正文不同。"),
    )
    assert_error(collision, "IDEMPOTENCY_CONFLICT", 409)

    explicit_run_input = tutor_client.post(
        f"/api/tutor/runs/{run_id}/inputs",
        json=action_payload(user_id, "explicit-run-input", content="这是针对同一活动 run 的第三条输入。"),
    )
    assert explicit_run_input.status_code == 202
    assert explicit_run_input.json()["run_id"] == run_id
    assert explicit_run_input.json()["input_revision"] == 4
    assert explicit_run_input.json()["merged"] is True

    with connect() as conn:
        input_count = conn.execute(
            "SELECT count(*) AS count FROM tutor_run_input_events WHERE run_id = %s",
            (run_id,),
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
    assert input_count is not None and input_count["count"] == 4
    assert receipt is not None
    assert "闭包中的变量作用域" not in str(receipt["response_json"])
    assert "闭包中的变量作用域" not in str(receipt["request_hash"])

    with connect() as conn:
        repository = PostgresTutorRepository(conn)
        repository.request_cancellation(user_id=user_id, run_id=run_id, now=datetime.now(UTC))
        conn.commit()

    terminal = tutor_client.post(
        f"/api/tutor/runs/{run_id}/inputs",
        json=action_payload(user_id, "terminal-run-input", content="已经取消的 run 不应继续合并。"),
    )
    assert_error(terminal, "RUN_NOT_ACTIVE", 409)

    other_user = create_tutor_user(tutor_client)
    cross_user = tutor_client.post(
        f"/api/tutor/runs/{run_id}/inputs",
        json=action_payload(str(other_user["id"]), "cross-user-run-input", content="不属于当前用户的 run。"),
    )
    assert_error(cross_user, "TUTOR_RUN_NOT_FOUND", 404)