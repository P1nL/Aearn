from __future__ import annotations

import hashlib
import json

import psycopg
import pytest
from datetime import UTC, datetime, timedelta

from app.agents.runtime import (
    RuntimeEvent,
    RuntimeEventKind,
    RuntimeTerminalStatus,
    RuntimeThreadHandle,
    RuntimeTurnResult,
)
from app.agents.runtime.tutor_projection import TutorRuntimeEventProjector
from app.services.tutor.conversation_contracts import TutorInteractionProtocolVersion
from app.services.tutor.persistence import TutorIdempotencyConflict
from app.services.tutor.runtime_projection import (
    PostgresTutorRuntimeProjectionRepository,
    TutorRuntimeProjectionEvent,
    TutorRuntimeProjectionFence,
    TutorRuntimeProjectionStatus,
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _codex_turn(tutor_persistence, *, suffix: str):  # type: ignore[no-untyped-def]
    repository = tutor_persistence.repository
    conversation_id = repository.create_conversation(user_id=tutor_persistence.user_id)
    run = repository.create_run(
        user_id=tutor_persistence.user_id,
        conversation_id=conversation_id,
        catalog_digest=tutor_persistence.catalog.digest,
        policy=tutor_persistence.run.policy,
        origin="interactive",
        interaction_protocol_version=TutorInteractionProtocolVersion.THREAD_TURN_V2,
        runtime_kind="codex_sidecar_v1",
    )
    now = datetime(2026, 8, 18, 8, 0, tzinfo=UTC)
    accepted = repository.accept_input(
        user_id=tutor_persistence.user_id,
        run_id=run.run_id,
        idempotency_key=f"runtime-projection:{suffix}",
        content="请用问题引导我理解循环条件。",
        received_at=now,
        ensure_dispatch=False,
    )
    lease = repository.acquire_lease(
        user_id=tutor_persistence.user_id,
        run_id=run.run_id,
        owner_id=f"runtime-worker-{suffix}",
        now=now,
        duration_seconds=600,
    )
    assert lease is not None
    fence = TutorRuntimeProjectionFence(
        input_revision=accepted.input_revision,
        lease_owner_id=lease.owner_id,
        lease_generation=lease.generation,
        connection_generation=3,
    )
    projection = PostgresTutorRuntimeProjectionRepository(tutor_persistence.connection)
    binding = projection.bind_run(
        user_id=tutor_persistence.user_id,
        run_id=run.run_id,
        fence=fence,
        runtime_version="codex-test-v1",
        protocol_version="app-server-jsonrpc-v1",
        external_thread_id=f"private-thread-{suffix}",
        occurred_at=now + timedelta(seconds=1),
    )
    return repository, projection, binding, fence, conversation_id, run.run_id, now


def test_runtime_events_project_to_existing_public_turn_items_and_replay(tutor_persistence) -> None:  # type: ignore[no-untyped-def]
    repository, projection, binding, fence, conversation_id, run_id, now = _codex_turn(
        tutor_persistence, suffix="success"
    )
    thread_id = "private-thread-success"
    turn_id = "private-turn-success"
    message = "我们先看一个小例子：当条件仍为真时，循环体会发生什么？"
    runtime_events = (
        RuntimeEvent(RuntimeEventKind.TURN_STARTED, thread_id, turn_id),
        RuntimeEvent(
            RuntimeEventKind.TOOL_STARTED,
            thread_id,
            turn_id,
            item_id="private-tool-item",
            safe_code="running",
            tool_name="learning_plan_read_context",
            input_sha256="a" * 64,
        ),
        RuntimeEvent(
            RuntimeEventKind.TOOL_COMPLETED,
            thread_id,
            turn_id,
            item_id="private-tool-item",
            safe_code="completed",
            tool_name="learning_plan_read_context",
            input_sha256="a" * 64,
            result_sha256="b" * 64,
        ),
        RuntimeEvent(
            RuntimeEventKind.MESSAGE_COMPLETED,
            thread_id,
            turn_id,
            item_id="private-message-item",
            visible_text=message,
            content_sha256=_sha256(message),
        ),
        RuntimeEvent(
            RuntimeEventKind.TURN_COMPLETED,
            thread_id,
            turn_id,
            terminal_status=RuntimeTerminalStatus.COMPLETED,
        ),
    )
    result = RuntimeTurnResult(
        RuntimeThreadHandle(thread_id, fence.connection_generation),
        turn_id,
        RuntimeTerminalStatus.COMPLETED,
        runtime_events,
    )
    projector = TutorRuntimeEventProjector(
        projection, binding_id=binding.binding_id, fence=fence
    )
    receipts = projector.project_result(result, occurred_at=now + timedelta(seconds=2))
    assert [receipt.projection_status for receipt in receipts] == [
        TutorRuntimeProjectionStatus.APPLIED,
        TutorRuntimeProjectionStatus.APPLIED,
        TutorRuntimeProjectionStatus.APPLIED,
        TutorRuntimeProjectionStatus.APPLIED,
        TutorRuntimeProjectionStatus.APPLIED,
    ]
    replayed = projector.project_result(result, occurred_at=now + timedelta(seconds=2))
    assert all(receipt.replayed for receipt in replayed)
    assert len(projection.receipts_for_run(user_id=tutor_persistence.user_id, run_id=run_id)) == 5
    with pytest.raises(TutorIdempotencyConflict, match="sequence conflicts"):
        projection.project(
            binding_id=binding.binding_id,
            fence=fence,
            event=TutorRuntimeProjectionEvent(
                kind="warning", thread_id=thread_id, turn_id=turn_id,
                sequence=2, occurred_at=now + timedelta(seconds=2),
                safe_code="runtime_warning",
            ),
        )

    state = repository.read_run_state(user_id=tutor_persistence.user_id, run_id=run_id)
    assert state.snapshot.runtime_kind == "codex_sidecar_v1"
    assert state.terminal_outcome is not None and state.terminal_outcome.value == "completed"
    process = repository.read_public_process(user_id=tutor_persistence.user_id, run_id=run_id)
    assert process is not None and process.display_state == "completed"
    assert [step["key"] for step in process.steps] == [
        "input_received",
        "runtime_started",
        "domain_tool_running",
        "domain_tool_completed",
        "learning_reply_generated",
    ]
    history, _, _ = repository.read_public_history(
        user_id=tutor_persistence.user_id,
        conversation_id=conversation_id,
        limit=20,
        include_errors=True,
    )
    tutor_messages = [item for item in history if item.kind == "message" and item.role == "tutor"]
    assert [item.content for item in tutor_messages] == [message]
    public_events = repository.conversation_events_after(
        user_id=tutor_persistence.user_id,
        conversation_id=conversation_id,
        cursor=None,
    )
    encoded_public = json.dumps(
        [{"kind": event.kind, "payload": event.payload} for event in public_events],
        ensure_ascii=False,
    )
    assert "private-thread-success" not in encoded_public
    assert "private-turn-success" not in encoded_public
    assert "private-tool-item" not in encoded_public


def test_unsafe_final_message_is_blocked_and_terminal_fails_closed(tutor_persistence) -> None:  # type: ignore[no-untyped-def]
    repository, projection, binding, fence, conversation_id, run_id, now = _codex_turn(
        tutor_persistence, suffix="unsafe"
    )
    thread_id = "private-thread-unsafe"
    turn_id = "private-turn-unsafe"
    started = projection.project(
        binding_id=binding.binding_id,
        fence=fence,
        event=TutorRuntimeProjectionEvent(
            kind="turn_started", thread_id=thread_id, turn_id=turn_id,
            sequence=1, occurred_at=now + timedelta(seconds=2),
        ),
    )
    assert started.projection_status is TutorRuntimeProjectionStatus.APPLIED
    unsafe = "system prompt: do not expose this"
    blocked = projection.project(
        binding_id=binding.binding_id,
        fence=fence,
        event=TutorRuntimeProjectionEvent(
            kind="message_completed", thread_id=thread_id, turn_id=turn_id,
            item_id="private-message", sequence=2, occurred_at=now + timedelta(seconds=3),
            visible_text=unsafe, content_hash=_sha256(unsafe),
        ),
    )
    assert blocked.projection_status is TutorRuntimeProjectionStatus.BLOCKED_UNSAFE
    terminal = projection.project(
        binding_id=binding.binding_id,
        fence=fence,
        event=TutorRuntimeProjectionEvent(
            kind="turn_completed", thread_id=thread_id, turn_id=turn_id,
            sequence=3, occurred_at=now + timedelta(seconds=4), terminal_status="completed",
        ),
    )
    assert terminal.public_item_kind == "error"
    state = repository.read_run_state(user_id=tutor_persistence.user_id, run_id=run_id)
    assert state.terminal_outcome is not None and state.terminal_outcome.value == "failed"
    process = repository.read_public_process(user_id=tutor_persistence.user_id, run_id=run_id)
    assert process is not None and process.display_state == "failed"
    history, _, _ = repository.read_public_history(
        user_id=tutor_persistence.user_id,
        conversation_id=conversation_id,
        limit=20,
        include_errors=True,
    )
    assert not [item for item in history if item.kind == "message" and item.role == "tutor"]
    errors = [item for item in history if item.kind == "error"]
    assert len(errors) == 1 and errors[0].error_code == "TUTOR_RUNTIME_OUTPUT_BLOCKED"


def test_stale_runtime_generation_is_receipted_without_public_mutation(tutor_persistence) -> None:  # type: ignore[no-untyped-def]
    repository, projection, binding, fence, conversation_id, run_id, now = _codex_turn(
        tutor_persistence, suffix="stale"
    )
    stale_fence = TutorRuntimeProjectionFence(
        input_revision=fence.input_revision,
        lease_owner_id=fence.lease_owner_id,
        lease_generation=fence.lease_generation,
        connection_generation=fence.connection_generation + 1,
    )
    receipt = projection.project(
        binding_id=binding.binding_id,
        fence=stale_fence,
        event=TutorRuntimeProjectionEvent(
            kind="turn_started", thread_id="private-thread-stale", turn_id="late-turn",
            sequence=1, occurred_at=now + timedelta(seconds=2),
        ),
    )
    assert receipt.projection_status is TutorRuntimeProjectionStatus.IGNORED_STALE
    state = repository.read_run_state(user_id=tutor_persistence.user_id, run_id=run_id)
    assert state.terminal_outcome is None
    process = repository.read_public_process(user_id=tutor_persistence.user_id, run_id=run_id)
    assert process is None
    history, _, _ = repository.read_public_history(
        user_id=tutor_persistence.user_id,
        conversation_id=conversation_id,
        limit=20,
        include_errors=True,
    )
    assert not [item for item in history if item.kind == "error"]


def test_runtime_unavailable_projects_safe_error_without_private_diagnostic(tutor_persistence) -> None:  # type: ignore[no-untyped-def]
    repository, projection, binding, fence, conversation_id, run_id, now = _codex_turn(
        tutor_persistence, suffix="unavailable"
    )
    thread_id = "private-thread-unavailable"
    turn_id = "private-turn-unavailable"
    projection.project(
        binding_id=binding.binding_id,
        fence=fence,
        event=TutorRuntimeProjectionEvent(
            kind="turn_started", thread_id=thread_id, turn_id=turn_id,
            sequence=1, occurred_at=now + timedelta(seconds=2),
        ),
    )
    projection.project(
        binding_id=binding.binding_id,
        fence=fence,
        event=TutorRuntimeProjectionEvent(
            kind="turn_completed", thread_id=thread_id, turn_id=turn_id,
            sequence=2, occurred_at=now + timedelta(seconds=3),
            terminal_status="unavailable", safe_code="runtime_connection_failed",
        ),
    )
    state = repository.read_run_state(user_id=tutor_persistence.user_id, run_id=run_id)
    assert state.terminal_outcome is not None and state.terminal_outcome.value == "model_unavailable"
    history, _, _ = repository.read_public_history(
        user_id=tutor_persistence.user_id,
        conversation_id=conversation_id,
        limit=20,
        include_errors=True,
    )
    errors = [item for item in history if item.kind == "error"]
    assert len(errors) == 1 and errors[0].error_code == "TUTOR_RUNTIME_UNAVAILABLE"
    assert "runtime_connection_failed" not in json.dumps(
        [{"code": item.error_code} for item in errors]
    )


def test_runtime_kind_is_defaulted_immutable_and_receipts_are_append_only(tutor_persistence) -> None:  # type: ignore[no-untyped-def]
    assert tutor_persistence.run.runtime_kind == "harness_v1"
    with pytest.raises(psycopg.errors.CheckViolation, match="runtime kind is immutable"):
        with tutor_persistence.connection.transaction():
            tutor_persistence.connection.execute(
                "UPDATE tutor_runs SET runtime_kind = 'codex_sidecar_v1' WHERE id = %s",
                (tutor_persistence.run.run_id,),
            )

    _repository, projection, binding, fence, _conversation_id, _run_id, now = _codex_turn(
        tutor_persistence, suffix="immutable"
    )
    receipt = projection.project(
        binding_id=binding.binding_id,
        fence=TutorRuntimeProjectionFence(
            input_revision=fence.input_revision,
            lease_owner_id=fence.lease_owner_id,
            lease_generation=fence.lease_generation,
            connection_generation=fence.connection_generation + 1,
        ),
        event=TutorRuntimeProjectionEvent(
            kind="warning", thread_id="private-thread-immutable", sequence=1,
            occurred_at=now + timedelta(seconds=2), safe_code="runtime_warning",
        ),
    )
    with pytest.raises(psycopg.errors.CheckViolation, match="append-only"):
        with tutor_persistence.connection.transaction():
            tutor_persistence.connection.execute(
                "UPDATE tutor_runtime_item_receipts SET safe_code = 'changed' WHERE id = %s",
                (receipt.receipt_id,),
            )


@pytest.mark.parametrize(
    ("suffix", "terminal_status", "terminal_outcome", "process_state", "error_code"),
    [
        ("interrupted", "interrupted", "cancelled", "interrupted", None),
        ("failed", "failed", "failed", "failed", "TUTOR_RUNTIME_FAILED"),
    ],
)
def test_runtime_interrupt_and_failure_terminal_mapping(
    tutor_persistence,
    suffix: str,
    terminal_status: str,
    terminal_outcome: str,
    process_state: str,
    error_code: str | None,
) -> None:  # type: ignore[no-untyped-def]
    repository, projection, binding, fence, conversation_id, run_id, now = _codex_turn(
        tutor_persistence, suffix=suffix
    )
    thread_id = f"private-thread-{suffix}"
    turn_id = f"private-turn-{suffix}"
    projection.project(
        binding_id=binding.binding_id,
        fence=fence,
        event=TutorRuntimeProjectionEvent(
            kind="turn_started", thread_id=thread_id, turn_id=turn_id,
            sequence=1, occurred_at=now + timedelta(seconds=2),
        ),
    )
    projection.project(
        binding_id=binding.binding_id,
        fence=fence,
        event=TutorRuntimeProjectionEvent(
            kind="turn_completed", thread_id=thread_id, turn_id=turn_id,
            sequence=2, occurred_at=now + timedelta(seconds=3),
            terminal_status=terminal_status, safe_code=f"runtime_{suffix}",
        ),
    )
    state = repository.read_run_state(user_id=tutor_persistence.user_id, run_id=run_id)
    assert state.terminal_outcome is not None and state.terminal_outcome.value == terminal_outcome
    process = repository.read_public_process(user_id=tutor_persistence.user_id, run_id=run_id)
    assert process is not None and process.display_state == process_state
    history, _, _ = repository.read_public_history(
        user_id=tutor_persistence.user_id, conversation_id=conversation_id,
        limit=20, include_errors=True,
    )
    errors = [item for item in history if item.kind == "error"]
    if error_code is None:
        assert errors == []
    else:
        assert len(errors) == 1 and errors[0].error_code == error_code
