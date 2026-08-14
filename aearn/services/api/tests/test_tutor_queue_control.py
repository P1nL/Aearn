from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

import app.routes.tutor as tutor_route
from app.agents.harness.contracts import TutorContinuationKind, TutorTerminalOutcome
from app.agents.harness.skill_catalog import compile_published_skill_catalog
from app.core.config import Settings
from app.db.connection import connect
from app.services.tutor.interactive import TutorInteractiveRunDispatcher
from app.services.tutor.persistence import PostgresTutorRepository
from app.services.tutor.queue_control import PostgresTutorQueueController, build_queue_turn_policy
from tutor_public_api_support import (
    RecordingTutorDispatcher,
    TerminalTutorProvider,
    action_payload,
    assert_error,
    create_tutor_user,
    waiting_dispatcher,
)

pytest_plugins = ("tutor_public_api_support",)


def _conversation(client: TestClient, user_id: str, key: str) -> str:
    response = client.post("/api/tutor/conversations", json=action_payload(user_id, key))
    assert response.status_code == 201
    return str(response.json()["conversation_id"])


def _send(client: TestClient, *, user_id: str, conversation_id: str, key: str, content: str):  # type: ignore[no-untyped-def]
    return client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(user_id, key, content=content),
    )


def _queue(client: TestClient, *, user_id: str, conversation_id: str) -> dict[str, object]:
    response = client.get(f"/api/tutor/conversations/{conversation_id}/queue?user_id={user_id}")
    assert response.status_code == 200
    return response.json()


def test_queue_edit_reorder_steer_interrupt_resume_and_execute(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    del tutor_api_settings
    dispatcher = RecordingTutorDispatcher()
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user_id = str(create_tutor_user(tutor_client)["id"])
    conversation_id = _conversation(tutor_client, user_id, "queue-control-conversation")

    first = _send(
        tutor_client, user_id=user_id, conversation_id=conversation_id,
        key="queue-control-first", content="先解释闭包。",
    )
    assert first.status_code == 202
    first_body = first.json()
    turn_id = str(first_body["run_id"])
    assert first_body["input_revision"] == 1

    queued = []
    for index in range(1, 4):
        response = _send(
            tutor_client, user_id=user_id, conversation_id=conversation_id,
            key=f"queue-control-{index}", content=f"排队输入 {index}",
        )
        assert response.status_code == 202
        body = response.json()
        assert body["queued"] is True
        assert body["pending_count"] == index
        queued.append(body["queue_item"])

    state = _queue(tutor_client, user_id=user_id, conversation_id=conversation_id)
    assert state["control_state"] == "running"
    assert state["queue_paused"] is False
    assert [item["content"] for item in state["items"]] == ["排队输入 1", "排队输入 2", "排队输入 3"]

    edited = tutor_client.patch(
        f"/api/tutor/conversations/{conversation_id}/queue/{queued[1]['item_id']}",
        json=action_payload(
            user_id, "queue-control-edit", content="排队输入二（已编辑）",
            expected_control_version=state["control_version"], expected_item_version=queued[1]["version"],
        ),
    )
    assert edited.status_code == 200
    edited_body = edited.json()
    assert edited_body["queue_item"]["version"] == 2
    assert edited_body["queue_item"]["content"] == "排队输入二（已编辑）"

    stale = tutor_client.patch(
        f"/api/tutor/conversations/{conversation_id}/queue/{queued[0]['item_id']}",
        json=action_payload(
            user_id, "queue-control-stale-edit", content="不应写入",
            expected_control_version=state["control_version"], expected_item_version=queued[0]["version"],
        ),
    )
    assert_error(stale, "TUTOR_CONTROL_CONFLICT", 409)

    reordered = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/queue/reorder",
        json=action_payload(
            user_id, "queue-control-reorder", expected_control_version=edited_body["control_version"],
            item_ids=[queued[2]["item_id"], queued[1]["item_id"], queued[0]["item_id"]],
        ),
    )
    assert reordered.status_code == 200
    reordered_body = reordered.json()
    assert [item["item_id"] for item in reordered_body["items"]] == [
        queued[2]["item_id"], queued[1]["item_id"], queued[0]["item_id"],
    ]

    steered = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/queue/{queued[2]['item_id']}/steer",
        json=action_payload(
            user_id, "queue-control-steer", expected_control_version=reordered_body["control_version"],
            expected_turn_id=turn_id, expected_input_revision=1,
        ),
    )
    assert steered.status_code == 202
    steered_body = steered.json()
    assert steered_body["run_id"] == turn_id
    assert steered_body["input_revision"] == 2
    assert steered_body["queue_item"]["state"] == "claimed"

    interrupted = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/interrupt",
        json=action_payload(
            user_id, "queue-control-interrupt", expected_control_version=steered_body["control_version"],
            expected_turn_id=turn_id, expected_input_revision=2,
        ),
    )
    assert interrupted.status_code == 200
    interrupted_body = interrupted.json()
    assert interrupted_body["control_state"] == "queue_paused"
    assert interrupted_body["queue_paused"] is True
    assert interrupted_body["queue_pause_reason"] == "interrupted"

    paused_send = _send(
        tutor_client, user_id=user_id, conversation_id=conversation_id,
        key="queue-control-paused-send", content="中断后继续排队",
    )
    assert paused_send.status_code == 202
    paused_body = paused_send.json()
    assert paused_body["queued"] is True
    paused_state = _queue(tutor_client, user_id=user_id, conversation_id=conversation_id)
    assert paused_state["queue_paused"] is True

    resumed = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/queue/resume",
        json=action_payload(
            user_id, "queue-control-resume", expected_control_version=paused_state["control_version"],
        ),
    )
    assert resumed.status_code == 202
    resumed_body = resumed.json()
    assert resumed_body["run_id"] != turn_id
    assert resumed_body["input_revision"] == 1

    after_resume = _queue(tutor_client, user_id=user_id, conversation_id=conversation_id)
    selected = after_resume["items"][0]
    executed = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/queue/{selected['item_id']}/execute",
        json=action_payload(
            user_id, "queue-control-execute", expected_control_version=after_resume["control_version"],
        ),
    )
    assert executed.status_code == 202
    assert executed.json()["run_id"] != resumed_body["run_id"]


def test_queue_capacity_and_pending_request_blocks_control_but_not_send(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    dispatcher, _provider = waiting_dispatcher(
        settings=tutor_api_settings,
        message="你希望先看哪一部分？",
        continuation_kind=TutorContinuationKind.CLARIFICATION,
    )
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user_id = str(create_tutor_user(tutor_client)["id"])
    conversation_id = _conversation(tutor_client, user_id, "queue-pending-conversation")
    first = _send(
        tutor_client, user_id=user_id, conversation_id=conversation_id,
        key="queue-pending-first", content="帮我制定学习计划。",
    )
    assert first.status_code == 202
    turn_id = str(first.json()["run_id"])

    queued_items = []
    for index in range(10):
        response = _send(
            tutor_client, user_id=user_id, conversation_id=conversation_id,
            key=f"queue-capacity-{index}", content=f"容量输入 {index}",
        )
        assert response.status_code == 202
        assert response.json()["queued"] is True
        queued_items.append(response.json()["queue_item"])

    full = _send(
        tutor_client, user_id=user_id, conversation_id=conversation_id,
        key="queue-capacity-overflow", content="第十一个排队输入",
    )
    assert_error(full, "TUTOR_QUEUE_FULL", 409)
    state = _queue(tutor_client, user_id=user_id, conversation_id=conversation_id)
    assert state["control_state"] == "waiting"
    assert state["queue_paused"] is True
    assert state["queue_pause_reason"] == "pending_request"
    assert state["pending_count"] == 10

    steer = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/queue/{queued_items[0]['item_id']}/steer",
        json=action_payload(
            user_id, "queue-pending-steer", expected_control_version=state["control_version"],
            expected_turn_id=turn_id, expected_input_revision=1,
        ),
    )
    assert_error(steer, "TUTOR_CONTROL_CONFLICT", 409)
    execute = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/queue/{queued_items[0]['item_id']}/execute",
        json=action_payload(
            user_id, "queue-pending-execute", expected_control_version=state["control_version"],
        ),
    )
    assert_error(execute, "TUTOR_CONTROL_CONFLICT", 409)


def test_retry_creates_fresh_lineage_for_recoverable_turn(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    provider = TerminalTutorProvider(message="暂时不可用", outcome=TutorTerminalOutcome.MODEL_UNAVAILABLE)
    dispatcher = TutorInteractiveRunDispatcher(settings=tutor_api_settings, provider_factory=lambda _settings: provider)
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user_id = str(create_tutor_user(tutor_client)["id"])
    conversation_id = _conversation(tutor_client, user_id, "queue-retry-conversation")
    failed = _send(
        tutor_client, user_id=user_id, conversation_id=conversation_id,
        key="queue-retry-first", content="请解释生成器。",
    )
    assert failed.status_code == 202
    failed_turn_id = str(failed.json()["run_id"])
    state = _queue(tutor_client, user_id=user_id, conversation_id=conversation_id)
    assert state["active_turn"] is None

    recording = RecordingTutorDispatcher()
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: recording)
    retried = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/turns/{failed_turn_id}/retry",
        json=action_payload(
            user_id, "queue-retry-action", expected_control_version=state["control_version"],
        ),
    )
    assert retried.status_code == 202
    body = retried.json()
    assert body["run_id"] != failed_turn_id
    assert body["run"]["retry_of_turn_id"] == failed_turn_id
    assert body["run"]["retry_root_turn_id"] == failed_turn_id



def test_completed_only_drain_is_duplicate_safe(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    dispatcher = RecordingTutorDispatcher()
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user_id = str(create_tutor_user(tutor_client)["id"])
    conversation_id = _conversation(tutor_client, user_id, "queue-drain-conversation")
    first = _send(
        tutor_client, user_id=user_id, conversation_id=conversation_id,
        key="queue-drain-first", content="先运行一个 turn。",
    )
    assert first.status_code == 202
    source_turn_id = str(first.json()["run_id"])
    queued = _send(
        tutor_client, user_id=user_id, conversation_id=conversation_id,
        key="queue-drain-next", content="完成后自动执行。",
    )
    assert queued.status_code == 202 and queued.json()["queued"] is True
    queued_item_id = str(queued.json()["queue_item"]["item_id"])

    now = datetime.now(UTC)
    with connect() as conn:
        conn.execute(
            """
            UPDATE tutor_runs
            SET status = 'completed', terminal_outcome = 'completed', terminal_diagnostic_code = 'completed',
                terminal_at = %s, active_lease_owner_id = NULL, active_lease_expires_at = NULL
            WHERE id = %s
            """,
            (now, source_turn_id),
        )
        repository = PostgresTutorRepository(conn)
        catalog = compile_published_skill_catalog()
        repository.record_catalog_snapshot(catalog)
        queue = PostgresTutorQueueController(conn)
        first_drain = queue.drain_completed(
            user_id=user_id,
            conversation_id=conversation_id,
            catalog_digest=catalog.digest,
            policy=build_queue_turn_policy(now, settings=tutor_api_settings),
            occurred_at=now,
        )
        duplicate = queue.drain_completed(
            user_id=user_id,
            conversation_id=conversation_id,
            catalog_digest=catalog.digest,
            policy=build_queue_turn_policy(now, settings=tutor_api_settings),
            occurred_at=now,
        )
        claimed = conn.execute(
            "SELECT state, claimed_turn_id::text AS claimed_turn_id FROM tutor_queued_inputs WHERE id = %s",
            (queued_item_id,),
        ).fetchone()

    assert first_drain is not None
    assert duplicate is None
    assert claimed == {"state": "claimed", "claimed_turn_id": first_drain.run.run_id}
