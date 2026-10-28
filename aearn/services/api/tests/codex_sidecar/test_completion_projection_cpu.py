"""Actual projection acceptance/replay branches with a CPU SQL transcript."""
from __future__ import annotations

import hashlib
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services.tutor.runtime_projection import (
    PostgresTutorRuntimeProjectionRepository, TutorRuntimeProjectionError,
    TutorRuntimeProjectionEvent, TutorRuntimeProjectionFence, TutorRuntimeProjectionStatus,
)
from tests.codex_sidecar.test_completion_dispatcher import Rows


class ProjectionConnection:
    def __init__(self):
        now = datetime.now(UTC)
        self.binding = dict(
            id="binding", run_id="run", user_id="user", conversation_id="conversation", step_attempt_id="step",
            input_revision=1, active_lease_owner_id="fresh-owner", active_lease_generation=2,
            active_lease_expires_at=now + timedelta(minutes=2), terminal_outcome=None,
            cancelled_at=None, superseded_by_run_id=None, connection_generation=1,
            external_thread_id="thread", external_turn_id="turn", state="running", final_message_id=None,
            final_message_blocked=False, run_status="running", origin="interactive", interaction_protocol_version="thread_turn_v2",
        )
        self.accepted = True
        self.receipt = None
        self.messages = []
        self.calls = []

    def transaction(self):
        return nullcontext()

    def execute(self, statement, params=()):
        sql = " ".join(statement.split())
        self.calls.append((sql, params))
        if "SELECT bindings.*" in sql:
            return Rows(self.binding)
        if "SELECT * FROM tutor_runtime_item_receipts" in sql:
            return Rows(self.receipt)
        if sql.startswith("SELECT id FROM tutor_run_step_attempts"):
            assert params == ("step", "run", "user", "conversation", 1, "fresh-owner", 2)
            return Rows({"id": "step"} if self.accepted else None)
        if sql.startswith("SELECT state, accepted_owner_id"):
            return Rows(dict(state="accepted" if self.accepted else "result_recorded",
                             accepted_owner_id="fresh-owner", accepted_owner_generation=2, input_revision=1))
        if sql.startswith("SELECT final_message_id"):
            return Rows({"final_message_id": self.binding["final_message_id"]})
        if sql.startswith("INSERT INTO tutor_messages"):
            self.messages.append(params[1])
            return Rows({"id": "public-message"})
        if sql.startswith("UPDATE tutor_run_runtime_bindings SET final_message_id"):
            self.binding["final_message_id"] = params[0]
            return Rows({"id": "binding"})
        raise AssertionError(sql)


@pytest.fixture
def projection(monkeypatch):
    conn = ProjectionConnection()
    repo = PostgresTutorRuntimeProjectionRepository.__new__(PostgresTutorRuntimeProjectionRepository)
    repo._conn = conn
    repo._tutor = SimpleNamespace(
        _ensure_public_process_locked=lambda **kw: None,
        _advance_public_process_locked=lambda **kw: None,
        _touch_conversation_public_activity_locked=lambda **kw: None,
        _append_item_reference_event_locked=lambda **kw: None,
    )
    monkeypatch.setattr(repo, "link_completed_text_items_to_message", lambda **kw: None)
    monkeypatch.setattr(repo, "_project_text_item", lambda **kw: (TutorRuntimeProjectionStatus.APPLIED, "text", "runtime_text"))
    monkeypatch.setattr(repo, "_receipt", lambda row, **kw: SimpleNamespace(receipt_id=row["id"], **kw))

    def insert(*, event_key, status, **kw):
        assert conn.receipt is None
        conn.receipt = dict(id="immutable-receipt", event_key=event_key, projection_status=status.value)
        return SimpleNamespace(receipt_id=conn.receipt["id"], replayed=False)

    monkeypatch.setattr(repo, "_insert_receipt", insert)
    fence = TutorRuntimeProjectionFence(1, "fresh-owner", 2, 1)
    text = "计划草案已经准备好。"
    event = TutorRuntimeProjectionEvent(
        kind="message_completed", thread_id="thread", turn_id="turn", sequence=3,
        projection_sequence=3, occurred_at=datetime.now(UTC), item_id="native-message", phase="final_answer",
        visible_text=text, content_hash=hashlib.sha256(text.encode()).hexdigest(), defer_public_message=True,
    )
    return conn, repo, fence, event


def test_deferred_message_replay_publishes_once_only_after_acceptance(projection):
    conn, repo, fence, event = projection
    first = repo.project(binding_id="binding", fence=fence, event=event)
    assert not conn.messages
    replay = repo.project(binding_id="binding", fence=fence, event=replace(event, defer_public_message=False))
    again = repo.project(binding_id="binding", fence=fence, event=replace(event, defer_public_message=False))
    assert first.receipt_id == replay.receipt_id == again.receipt_id == "immutable-receipt"
    assert replay.replayed and again.replayed
    assert conn.messages == [event.visible_text]
    assert not any(sql.startswith("UPDATE tutor_runtime_item_receipts") for sql, _ in conn.calls)


@pytest.mark.parametrize("streamed", [False, True])
def test_unaccepted_step_cannot_publish_even_without_a_stream_receipt(projection, streamed):
    conn, repo, fence, event = projection
    if streamed:
        repo.project(binding_id="binding", fence=fence, event=event)
    conn.accepted = False
    with pytest.raises(TutorRuntimeProjectionError, match="accepted current step"):
        repo.project(binding_id="binding", fence=fence, event=replace(event, defer_public_message=False))
    assert not conn.messages


def test_late_message_replay_cannot_mutate_internal_terminal_binding(projection):
    conn, repo, fence, event = projection
    repo.project(binding_id="binding", fence=fence, event=event)
    conn.binding["state"] = "completed"
    replay = repo.project(binding_id="binding", fence=fence, event=replace(event, defer_public_message=False))
    assert replay.replayed and not conn.messages


def test_typed_terminal_receipt_after_original_owner_finished_run(projection):
    conn, repo, fence, _event = projection
    conn.binding.update(state="completed", terminal_outcome="completed", final_message_id="typed-message",
                        active_lease_owner_id=None, active_lease_expires_at=None)
    event = TutorRuntimeProjectionEvent(
        kind="turn_completed", thread_id="thread", turn_id="turn", sequence=4,
        occurred_at=datetime.now(UTC), terminal_status="completed",
    )
    receipt = repo.project(binding_id="binding", fence=fence, event=event, complete_business_run=True)
    assert not receipt.replayed
    assert conn.receipt["projection_status"] == "applied"
    assert not conn.messages  # The typed owner already wrote the only public message.
    assert not any(sql.startswith("UPDATE tutor_runs") for sql, _ in conn.calls)


def test_typed_terminal_without_accepted_current_step_is_rejected(projection):
    conn, repo, fence, _event = projection
    conn.accepted = False
    event = TutorRuntimeProjectionEvent(kind="turn_completed", thread_id="thread", turn_id="turn", sequence=4,
                                        occurred_at=datetime.now(UTC), terminal_status="completed")
    with pytest.raises(TutorRuntimeProjectionError, match="requires accepted current step"):
        repo.project(binding_id="binding", fence=fence, event=event, complete_business_run=True)
    assert conn.receipt is None



def test_accepted_step_can_publish_when_no_stream_callback_was_recorded(projection):
    conn, repo, fence, event = projection
    receipt = repo.project(binding_id="binding", fence=fence, event=replace(event, defer_public_message=False))
    assert not receipt.replayed
    assert conn.messages == [event.visible_text]
    assert conn.binding["final_message_id"] == "public-message"
