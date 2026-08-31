from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.routes.tutor as tutor_route
from app.core.config import Settings
from app.db.connection import connect
from app.services.tutor.conversation_contracts import (
    TUTOR_CONVERSATION_SNAPSHOT_V3_VERSION,
    TutorConversationEventKind,
    TutorDispatchJobState,
    TutorPublicTurnStatus,
    public_turn_status,
    validate_public_item,
)
from app.services.tutor.persistence import (
    PostgresTutorLifecycle,
    PostgresTutorRepository,
    TutorCursorInvalid,
    TutorIdempotencyConflict,
    TutorLifecycleConflict,
)
from app.services.tutor.public_api import TutorPublicService
from tests.support.tutor_public_api_support import (
    action_payload,
    assert_error,
    create_tutor_user,
    terminal_dispatcher,
    waiting_dispatcher,
)


def _create_v2_turn(fixture, *, action_id: str = "thread-turn-v2"):
    received_at = datetime.now(UTC)
    accepted = fixture.repository.create_first_interactive_turn(
        user_id=fixture.user_id,
        catalog_digest=fixture.catalog.digest,
        policy=fixture.run.policy,
        idempotency_key=action_id,
        content="请用一个安全的最小示例解释闭包。",
        received_at=received_at,
    )
    return accepted, received_at


def test_public_item_union_is_strict_and_turn_status_is_bounded() -> None:
    payload = validate_public_item(
        {
            "kind": "error",
            "id": "error-1",
            "turn_id": None,
            "code": "TUTOR_DISPATCH_FAILED",
            "message": "Tutor 暂时无法完成本轮处理，请重试。",
            "recoverable": True,
            "created_at": "2026-08-14T00:00:00+00:00",
        }
    )
    assert payload["kind"] == "error"
    assert payload["turn_id"] is None

    with pytest.raises(ValidationError):
        validate_public_item(
            {
                **payload,
                "raw_reasoning": "must never become a public item field",
            }
        )

    assert public_turn_status(terminal_outcome=None, cancelled=False, superseded=False) is TutorPublicTurnStatus.IN_PROGRESS
    assert public_turn_status(terminal_outcome="completed", cancelled=False, superseded=False) is TutorPublicTurnStatus.COMPLETED
    assert public_turn_status(terminal_outcome="cancelled", cancelled=True, superseded=False) is TutorPublicTurnStatus.INTERRUPTED
    assert public_turn_status(terminal_outcome="model_unavailable", cancelled=False, superseded=False) is TutorPublicTurnStatus.FAILED


def test_fresh_v2_turn_job_and_events_roll_back_together(tutor_persistence) -> None:
    fixture = tutor_persistence

    def counts() -> dict[str, int]:
        row = fixture.connection.execute(
            """
            SELECT
              (SELECT count(*) FROM tutor_conversations WHERE user_id = %s) AS conversations,
              (SELECT count(*) FROM tutor_runs WHERE user_id = %s) AS runs,
              (SELECT count(*) FROM tutor_messages AS messages
                 JOIN tutor_conversations AS conversations ON conversations.id = messages.conversation_id
               WHERE conversations.user_id = %s) AS messages,
              (SELECT count(*) FROM tutor_conversation_events WHERE user_id = %s) AS conversation_events,
              (SELECT count(*) FROM tutor_interactive_dispatch_jobs WHERE user_id = %s) AS dispatch_jobs
            """,
            (fixture.user_id,) * 5,
        ).fetchone()
        assert row is not None
        return {key: int(value) for key, value in row.items()}

    before = counts()

    def fail_after_job(stage: str) -> None:
        if stage == "after_interactive_dispatch_job":
            raise RuntimeError("forced durable dispatch rollback")

    repository = PostgresTutorRepository(fixture.connection, failpoint=fail_after_job)
    with pytest.raises(RuntimeError, match="forced durable dispatch rollback"):
        repository.create_first_interactive_turn(
            user_id=fixture.user_id,
            catalog_digest=fixture.catalog.digest,
            policy=fixture.run.policy,
            idempotency_key="thread-turn-v2-rollback",
            content="事务失败后不能留下孤儿 turn 或 job。",
            received_at=datetime.now(UTC),
        )

    assert counts() == before


def test_conversation_events_are_ordered_idempotent_scoped_and_append_only(tutor_persistence) -> None:
    fixture = tutor_persistence
    accepted, occurred_at = _create_v2_turn(fixture, action_id="event-foundation")
    conversation_id = accepted.run.conversation_id
    run_id = accepted.run.run_id

    initial = fixture.repository.conversation_events_after(
        user_id=fixture.user_id,
        conversation_id=conversation_id,
        cursor=None,
    )
    assert [event.sequence for event in initial] == list(range(1, len(initial) + 1))
    assert [event.kind for event in initial] == [
        TutorConversationEventKind.TURN_CREATED,
        TutorConversationEventKind.ITEM_ADDED,
        TutorConversationEventKind.ITEM_ADDED,
    ]
    assert accepted.acceptance.dispatch_job_id is not None
    assert "请用一个安全的最小示例解释闭包" not in json.dumps(
        [event.payload for event in initial], ensure_ascii=False, sort_keys=True
    )

    control = fixture.repository.append_conversation_event(
        user_id=fixture.user_id,
        conversation_id=conversation_id,
        event_key="control:foundation",
        kind=TutorConversationEventKind.CONTROL_UPDATED,
        payload={"control_version": 1},
        occurred_at=occurred_at + timedelta(seconds=1),
    )
    replayed = fixture.repository.append_conversation_event(
        user_id=fixture.user_id,
        conversation_id=conversation_id,
        event_key="control:foundation",
        kind=TutorConversationEventKind.CONTROL_UPDATED,
        payload={"control_version": 1},
        occurred_at=occurred_at + timedelta(seconds=2),
    )
    assert replayed.event_id == control.event_id
    assert replayed.sequence == control.sequence

    with pytest.raises(TutorIdempotencyConflict):
        fixture.repository.append_conversation_event(
            user_id=fixture.user_id,
            conversation_id=conversation_id,
            event_key="control:foundation",
            kind=TutorConversationEventKind.CONTROL_UPDATED,
            payload={"control_version": 2},
            occurred_at=occurred_at + timedelta(seconds=3),
        )

    after_initial = fixture.repository.conversation_events_after(
        user_id=fixture.user_id,
        conversation_id=conversation_id,
        cursor=initial[-1].cursor,
    )
    assert [(event.sequence, event.event_id) for event in after_initial] == [(control.sequence, control.event_id)]

    other_conversation_id = fixture.repository.create_conversation(user_id=fixture.user_id)
    with pytest.raises(TutorCursorInvalid):
        fixture.repository.conversation_events_after(
            user_id=fixture.user_id,
            conversation_id=other_conversation_id,
            cursor=control.cursor,
        )

    with pytest.raises(ValueError, match="identity"):
        fixture.repository.append_conversation_event(
            user_id=fixture.user_id,
            conversation_id=conversation_id,
            event_key="turn:mismatched",
            kind=TutorConversationEventKind.TURN_UPDATED,
            turn_id=run_id,
            payload={
                "turn": {
                    "turn_id": other_conversation_id,
                    "conversation_id": conversation_id,
                    "interaction_protocol_version": "thread_turn_v2",
                    "status": "in_progress",
                    "created_at": occurred_at.isoformat(),
                    "updated_at": occurred_at.isoformat(),
                }
            },
            occurred_at=occurred_at,
        )

    with pytest.raises(psycopg.errors.CheckViolation, match="append-only"):
        with fixture.connection.transaction():
            fixture.connection.execute(
                "UPDATE tutor_conversation_events SET event_key = 'mutated' WHERE id = %s",
                (control.event_id,),
            )


def test_dispatch_job_lease_retry_dead_and_snapshot_error_projection(tutor_persistence) -> None:
    fixture = tutor_persistence
    accepted, received_at = _create_v2_turn(fixture, action_id="dispatch-lifecycle")
    job_id = accepted.acceptance.dispatch_job_id
    assert job_id is not None
    run_id = accepted.run.run_id
    conversation_id = accepted.run.conversation_id

    fixture.connection.execute(
        "UPDATE tutor_interactive_dispatch_jobs SET max_attempts = 2 WHERE id = %s",
        (job_id,),
    )
    first = fixture.repository.claim_interactive_dispatch_jobs(
        owner_id="dispatch-owner-a",
        now=received_at + timedelta(seconds=1),
        limit=1,
        job_id=job_id,
        lease_seconds=30,
    )
    assert len(first) == 1
    assert first[0].state is TutorDispatchJobState.LEASED
    assert first[0].attempt_count == 1
    assert fixture.repository.claim_interactive_dispatch_jobs(
        owner_id="dispatch-owner-b",
        now=received_at + timedelta(seconds=2),
        limit=1,
        job_id=job_id,
        lease_seconds=30,
    ) == ()

    delayed = fixture.repository.retry_interactive_dispatch_job(
        job_id=job_id,
        owner_id="dispatch-owner-a",
        lease_generation=first[0].lease_generation,
        error_code="dispatch_failed",
        failed_at=received_at + timedelta(seconds=3),
    )
    assert delayed is not None
    assert delayed.state is TutorDispatchJobState.RETRY_WAIT
    assert fixture.repository.claim_interactive_dispatch_jobs(
        owner_id="dispatch-owner-b",
        now=delayed.available_at - timedelta(microseconds=1),
        limit=1,
        job_id=job_id,
        lease_seconds=30,
    ) == ()

    second = fixture.repository.claim_interactive_dispatch_jobs(
        owner_id="dispatch-owner-b",
        now=delayed.available_at,
        limit=1,
        job_id=job_id,
        lease_seconds=30,
    )
    assert len(second) == 1
    assert second[0].attempt_count == 2
    assert second[0].lease_generation > first[0].lease_generation
    assert fixture.repository.complete_interactive_dispatch_job(
        job_id=job_id,
        owner_id="dispatch-owner-a",
        lease_generation=first[0].lease_generation,
        completed_at=delayed.available_at,
    ) is False

    dead = fixture.repository.retry_interactive_dispatch_job(
        job_id=job_id,
        owner_id="dispatch-owner-b",
        lease_generation=second[0].lease_generation,
        error_code="dispatch_failed",
        failed_at=delayed.available_at + timedelta(seconds=1),
    )
    assert dead is not None
    assert dead.state is TutorDispatchJobState.DEAD
    assert dead.attempt_count == 2

    run = fixture.repository.read_run_state(user_id=fixture.user_id, run_id=run_id)
    assert run.terminal_outcome is not None
    assert public_turn_status(
        terminal_outcome=run.terminal_outcome.value,
        cancelled=False,
        superseded=False,
    ) is TutorPublicTurnStatus.FAILED

    snapshot = TutorPublicService(fixture.connection).read_conversation_snapshot(
        user_id=fixture.user_id,
        conversation_id=conversation_id,
        limit=40,
        cursor=None,
    )
    assert snapshot["active_turn"] is None
    assert any(
        item["kind"] == "process" and item["display_state"] == "failed"
        for item in snapshot["timeline"]
    )
    public_error = next(item for item in snapshot["timeline"] if item["kind"] == "error")
    assert public_error == {
        "kind": "error",
        "id": job_id,
        "turn_id": run_id,
        "code": "TUTOR_DISPATCH_FAILED",
        "message": "Tutor 暂时无法完成本轮处理，请重试。",
        "recoverable": True,
        "created_at": public_error["created_at"],
    }

    events = fixture.repository.conversation_events_after(
        user_id=fixture.user_id,
        conversation_id=conversation_id,
        cursor=None,
    )
    assert TutorConversationEventKind.DISPATCH_DELAYED in {event.kind for event in events}
    dead_event = next(event for event in events if event.kind is TutorConversationEventKind.DISPATCH_DEAD)
    assert dead_event.item_id == job_id
    assert dead_event.item_kind == "error"


def test_legacy_snapshot_projects_history_without_event_backfill(
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    user = create_tutor_user(tutor_client)
    user_id = str(user["id"])
    created = tutor_client.post(
        "/api/tutor/conversations",
        json=action_payload(user_id, "legacy-snapshot-conversation"),
    )
    assert created.status_code == 201
    conversation_id = str(created.json()["conversation_id"])

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO tutor_messages (conversation_id, role, content)
            VALUES (%s, 'learner', '旧会话没有 conversation event backfill。')
            """,
            (conversation_id,),
        )
        conn.commit()

    response = tutor_client.get(
        f"/api/tutor/conversations/{conversation_id}/snapshot?user_id={user_id}&limit=40"
    )
    assert response.status_code == 200
    snapshot = response.json()
    assert snapshot["snapshot_version"] == TUTOR_CONVERSATION_SNAPSHOT_V3_VERSION
    assert snapshot["active_turn"] is None
    assert snapshot["pending_requests"] == []
    assert snapshot["queue"] == []
    assert snapshot["timeline"][0]["kind"] == "message"
    assert snapshot["timeline"][0]["turn_id"] is None
    assert isinstance(snapshot["stream_cursor"], str) and snapshot["stream_cursor"]

    with connect() as conn:
        replay = TutorPublicService(conn, settings=tutor_api_settings).replay_conversation_events(
            user_id=user_id,
            conversation_id=conversation_id,
            cursor=snapshot["stream_cursor"],
        )
    assert replay == ()

    invalid = tutor_client.get(
        f"/api/tutor/conversations/{conversation_id}/events?user_id={user_id}",
        headers={"Last-Event-ID": "not-an-opaque-conversation-cursor"},
    )
    assert_error(invalid, "CONVERSATION_CURSOR_INVALID", 400)


def test_active_public_thinking_snapshot_recovers_the_safe_prefix_and_isolates_repair_generations(
    tutor_persistence,
) -> None:
    fixture = tutor_persistence
    accepted, occurred_at = _create_v2_turn(fixture, action_id="active-thinking-snapshot")
    lease = fixture.repository.acquire_lease(
        user_id=fixture.user_id,
        run_id=accepted.run.run_id,
        owner_id="thinking-worker",
        now=occurred_at,
        duration_seconds=60,
    )
    assert lease is not None
    snapshot = fixture.repository.load_snapshot(
        user_id=fixture.user_id,
        run_id=accepted.run.run_id,
    )
    assert snapshot is not None
    lifecycle = PostgresTutorLifecycle(repository=fixture.repository)
    sink = lifecycle.create_public_thinking_sink(
        snapshot=snapshot,
        lease=lease,
        decision_iteration=1,
        now=lambda: occurred_at,
    )

    sink.begin_attempt(1)
    sink.append_text(1, "先确认目标。")
    active = fixture.repository.read_conversation_snapshot(
        user_id=fixture.user_id,
        conversation_id=accepted.run.conversation_id,
        limit=40,
        cursor=None,
        now=occurred_at,
    )
    assert active.active_thinking == {
        "turn_id": accepted.run.run_id,
        "input_revision": accepted.run.input_revision,
        "generation": 10001,
        "state": "active",
        "text": "先确认目标。",
        "complete": False,
        "last_event_sequence": active.active_thinking["last_event_sequence"],
    }

    sink.reset_attempt(2)
    with pytest.raises(TutorLifecycleConflict, match="stale provider attempt"):
        sink.append_text(1, "不能混入新尝试。")
    reset = fixture.repository.read_conversation_snapshot(
        user_id=fixture.user_id,
        conversation_id=accepted.run.conversation_id,
        limit=40,
        cursor=None,
        now=occurred_at,
    )
    assert reset.active_thinking is not None
    assert reset.active_thinking["generation"] == 10002
    assert reset.active_thinking["text"] == ""

    sink.discard_attempt(2)
    discarded = fixture.repository.read_conversation_snapshot(
        user_id=fixture.user_id,
        conversation_id=accepted.run.conversation_id,
        limit=40,
        cursor=None,
        now=occurred_at,
    )
    assert discarded.active_thinking is None


def test_public_thinking_stream_is_replayable_and_atomically_accepted_with_terminal_message(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    thinking_text = "先确认目标。\n\n再选择一个最小例子。"
    dispatcher, _provider = terminal_dispatcher(
        settings=tutor_api_settings,
        message="我们先从最小例子开始。",
        public_thinking_text=thinking_text,
        stream_public_thinking=True,
    )
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user = create_tutor_user(tutor_client)
    user_id = str(user["id"])

    accepted = tutor_client.post(
        "/api/tutor/conversations/first-turn",
        json=action_payload(user_id, "thinking-stream-terminal", content="请解释闭包。"),
    )
    assert accepted.status_code == 202
    body = accepted.json()
    conversation_id = str(body["conversation_id"])
    run_id = str(body["run_id"])

    snapshot_response = tutor_client.get(
        f"/api/tutor/conversations/{conversation_id}/snapshot?user_id={user_id}&limit=40"
    )
    assert snapshot_response.status_code == 200
    snapshot = snapshot_response.json()
    assert snapshot["snapshot_version"] == TUTOR_CONVERSATION_SNAPSHOT_V3_VERSION
    assert snapshot["active_turn"] is None
    assert snapshot["active_thinking"] is None
    tutor_message = next(item for item in snapshot["timeline"] if item["kind"] == "message" and item["role"] == "tutor")
    assert tutor_message["turn_id"] == run_id
    assert tutor_message["public_thinking_text"] == thinking_text
    assert tutor_message["public_thinking_steps"] == []

    with connect() as conn:
        stream_row = conn.execute(
            "SELECT state, thinking_text, provider_attempt FROM tutor_turn_public_thinking_streams WHERE run_id = %s",
            (run_id,),
        ).fetchone()
        replay = TutorPublicService(conn, settings=tutor_api_settings).replay_conversation_events(
            user_id=user_id,
            conversation_id=conversation_id,
            cursor=None,
        )
    assert stream_row == {"state": "accepted", "thinking_text": thinking_text, "provider_attempt": 1}
    output_events = [event.data for event in replay if event.event_type == "turn_output"]
    assert [event["payload"]["operation"] for event in output_events] == ["reset", "append", "complete"]
    assert [event["payload"]["chunk_sequence"] for event in output_events] == [0, 1, 2]
    assert output_events[1]["payload"]["text"] == thinking_text
    assert "reasoning" not in json.dumps(output_events, ensure_ascii=False).lower()


def test_typed_request_accepts_public_thinking_and_persists_formal_message(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    thinking_text = "我先确认当前缺少哪一项必要信息。"
    dispatcher, _provider = waiting_dispatcher(
        settings=tutor_api_settings,
        message="请补充你的每周可投入时间。",
        public_thinking_text=thinking_text,
        stream_public_thinking=True,
    )
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user = create_tutor_user(tutor_client)
    user_id = str(user["id"])

    accepted = tutor_client.post(
        "/api/tutor/conversations/first-turn",
        json=action_payload(user_id, "thinking-stream-request", content="帮我制定学习计划。"),
    )
    assert accepted.status_code == 202
    body = accepted.json()
    conversation_id = str(body["conversation_id"])
    run_id = str(body["run_id"])

    snapshot_response = tutor_client.get(
        f"/api/tutor/conversations/{conversation_id}/snapshot?user_id={user_id}&limit=40"
    )
    assert snapshot_response.status_code == 200
    snapshot = snapshot_response.json()
    assert snapshot["active_turn"] is None
    assert snapshot["active_thinking"] is None
    assert snapshot["pending_requests"][0]["turn_id"] == run_id
    assert snapshot["pending_requests"][0]["public_thinking_text"] == thinking_text

    with connect() as conn:
        stream_row = conn.execute(
            "SELECT state, thinking_text FROM tutor_turn_public_thinking_streams WHERE run_id = %s",
            (run_id,),
        ).fetchone()
        message_row = conn.execute(
            """
            SELECT content, public_thinking_text
            FROM tutor_messages
            WHERE conversation_id = %s AND role = 'tutor'
            """,
            (conversation_id,),
        ).fetchone()
    assert stream_row == {"state": "accepted", "thinking_text": thinking_text}
    assert message_row == {
        "content": "请补充你的每周可投入时间。",
        "public_thinking_text": thinking_text,
    }


def test_concurrent_event_append_allocates_one_contiguous_conversation_sequence(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    dispatcher, _provider = terminal_dispatcher(settings=tutor_api_settings)
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user = create_tutor_user(tutor_client)
    user_id = str(user["id"])
    accepted = tutor_client.post(
        "/api/tutor/conversations/first-turn",
        json=action_payload(user_id, "concurrent-event-sequence", content="验证 conversation-global sequence。"),
    )
    assert accepted.status_code == 202
    conversation_id = str(accepted.json()["conversation_id"])

    with connect() as conn:
        before = PostgresTutorRepository(conn).conversation_events_after(
            user_id=user_id,
            conversation_id=conversation_id,
            cursor=None,
        )
    assert before
    base_sequence = before[-1].sequence

    def append(index: int) -> int:
        with connect() as conn:
            event = PostgresTutorRepository(conn).append_conversation_event(
                user_id=user_id,
                conversation_id=conversation_id,
                event_key=f"control:concurrent:{index}",
                kind=TutorConversationEventKind.CONTROL_UPDATED,
                payload={"control_version": 1},
                occurred_at=datetime.now(UTC),
            )
            return event.sequence

    with ThreadPoolExecutor(max_workers=8) as executor:
        sequences = list(executor.map(append, range(8)))

    assert sorted(sequences) == list(range(base_sequence + 1, base_sequence + 9))
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT event_sequence
            FROM tutor_conversation_events
            WHERE conversation_id = %s AND event_key LIKE 'control:concurrent:%%'
            ORDER BY event_sequence
            """,
            (conversation_id,),
        ).fetchall()
    assert [int(row["event_sequence"]) for row in rows] == list(range(base_sequence + 1, base_sequence + 9))
