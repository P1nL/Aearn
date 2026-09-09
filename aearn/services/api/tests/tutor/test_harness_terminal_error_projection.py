"""Isolated, rollback-only terminal history and recovery regression."""
from __future__ import annotations

import json
from datetime import timedelta
from uuid import uuid4

import pytest

from app.agents.harness.contracts import (
    TutorCheckpoint, TutorCheckpointReason, TutorCompactionTrigger, TutorRunResult,
    TutorRunStatus, TutorTerminalOutcome, build_compaction_request, empty_checkpoint_metadata,
)
from app.services.tutor.persistence import TutorCurationEnvelope, TutorInteractionRequestConflict, TutorRunNotFound
from app.services.tutor.public_api import TutorPublicService
from app.services.tutor.queue_control import PostgresTutorQueueController
from tests.tutor.test_tutor_conversation_runtime import _create_v2_turn


@pytest.fixture(autouse=True)
def isolated_database_guard():
    # Standard fixtures may bootstrap only this explicitly selected disposable DB.
    import os
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    from app.core.config import get_settings

    settings = get_settings()
    assert settings.llm_type == "disabled"
    assert os.environ.get("DATABASE_URL") == settings.database_url
    target = conninfo_to_dict(settings.database_url)
    assert target["dbname"].startswith(("aearn_repair_", "aearn_test_", "test_"))
    assert target["host"] in {"localhost", "127.0.0.1"} and target["port"] == "5432"
    with psycopg.connect(settings.database_url) as conn:
        assert conn.execute("SELECT current_database()").fetchone()[0] == target["dbname"]


def _snapshot(fixture, conversation_id):
    return TutorPublicService(fixture.connection).read_conversation_snapshot(
        user_id=fixture.user_id, conversation_id=conversation_id, limit=40, cursor=None,
    )


@pytest.mark.parametrize(("outcome", "diagnostic", "recoverable", "code"), [
    ("blocked_policy", "unknown_capability", False, "CAPABILITY_DENIED"),
    ("blocked_policy", "unknown_effect_type", False, "CAPABILITY_DENIED"),
    ("blocked_policy", "capability_denied", True, "CAPABILITY_DENIED"),
    ("blocked_policy", "private_provider_payload_sentinel", False, "CAPABILITY_DENIED"),
    ("budget_exhausted", "deadline_exhausted", True, "TUTOR_RUN_UNAVAILABLE"),
    ("budget_exhausted", "model_call_budget_exhausted", False, "TUTOR_RUN_UNAVAILABLE"),
    ("model_unavailable", "private_provider_payload_sentinel", True, "MODEL_UNAVAILABLE"),
    ("failed", "private_provider_payload_sentinel", True, "TUTOR_RUN_FAILED"),
])
def test_historical_failure_snapshot_history_and_queue_authority(tutor_persistence, outcome, diagnostic, recoverable, code):
    f = tutor_persistence
    accepted, now = _create_v2_turn(f)
    run = accepted.run
    f.connection.execute(
        "UPDATE tutor_runs SET status=%s, terminal_outcome=%s, terminal_diagnostic_code=%s, terminal_at=%s WHERE id=%s",
        (outcome, outcome, diagnostic, now, run.run_id),
    )
    before = f.connection.execute("SELECT count(*) AS n FROM tutor_conversation_events WHERE conversation_id=%s", (run.conversation_id,)).fetchone()
    first = _snapshot(f, run.conversation_id)
    assert first["active_turn"] is None
    errors = [item for item in first["timeline"] if item["kind"] == "error"]
    assert len(errors) == 1
    error = errors[0]
    assert error["turn_id"] == run.run_id
    assert error["id"] != run.run_id  # Not the hidden process identity.
    assert error["code"] == code
    assert error["recoverable"] is recoverable
    assert "private_provider_payload_sentinel" not in json.dumps(first)
    assert diagnostic not in error["message"]
    assert ("重试" in error["message"]) is recoverable
    assert _snapshot(f, run.conversation_id) == first
    history, _, _ = f.repository.read_public_history(user_id=f.user_id, conversation_id=run.conversation_id, limit=40, include_errors=True)
    assert [item.item_id for item in history if item.kind == "error"] == [error["id"]]
    # Paginated history uses the same stable identity and timestamp.
    seen, cursor = [], None
    while True:
        page = TutorPublicService(f.connection).read_conversation_snapshot(user_id=f.user_id, conversation_id=run.conversation_id, limit=1, cursor=cursor)
        seen.extend(item["id"] for item in page["timeline"] if item["kind"] == "error")
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
    assert seen == [error["id"]]
    assert f.connection.execute("SELECT count(*) AS n FROM tutor_conversation_events WHERE conversation_id=%s", (run.conversation_id,)).fetchone() == before
    assert TutorPublicService(f.connection).replay_conversation_events(user_id=f.user_id, conversation_id=run.conversation_id, cursor=first["stream_cursor"]) == ()
    controller = PostgresTutorQueueController(f.connection)
    kwargs = dict(user_id=f.user_id, conversation_id=run.conversation_id, turn_id=run.run_id,
                  expected_control_version=first["conversation"]["control_version"], catalog_digest=f.catalog.digest,
                  policy=f.run.policy, occurred_at=now + timedelta(seconds=1))
    if recoverable:
        retried, _ = controller.retry(**kwargs)
        assert retried.run.run_id != run.run_id
    else:
        with pytest.raises(TutorInteractionRequestConflict, match="not recoverable"):
            controller.retry(**kwargs)


@pytest.mark.parametrize("outcome", [None, "completed", "cancelled"])
def test_normal_terminal_and_active_runs_are_not_errors(tutor_persistence, outcome):
    f = tutor_persistence
    accepted, now = _create_v2_turn(f)
    if outcome:
        f.connection.execute("UPDATE tutor_runs SET status=%s, terminal_outcome=%s, terminal_at=%s WHERE id=%s", (outcome, outcome, now, accepted.run.run_id))
    assert not [i for i in _snapshot(f, accepted.run.conversation_id)["timeline"] if i["kind"] == "error"]


def test_superseded_failure_and_cross_user_are_not_projected(tutor_persistence):
    f = tutor_persistence
    accepted, now = _create_v2_turn(f)
    f.connection.execute("UPDATE tutor_runs SET status='failed', terminal_outcome='failed', terminal_at=%s, superseded_by_run_id=%s WHERE id=%s", (now, f.run.run_id, accepted.run.run_id))
    assert not [i for i in _snapshot(f, accepted.run.conversation_id)["timeline"] if i["kind"] == "error"]
    with pytest.raises(TutorRunNotFound):
        f.repository.read_public_history(user_id=str(uuid4()), conversation_id=accepted.run.conversation_id, limit=40, include_errors=True)


def test_new_terminal_lifecycle_and_replay_are_idempotent(tutor_persistence):
    f = tutor_persistence
    # The base fixture is legacy/revision zero. Admit a real v2 learner input
    # and carry its exact revision through lease, checkpoint and curation.
    accepted, now = _create_v2_turn(f, action_id="stage3-terminal-lifecycle")
    run = accepted.run
    revision = accepted.acceptance.input_revision
    assert revision == 1
    authority = f.connection.execute(
        "SELECT interaction_protocol_version, input_revision FROM tutor_runs WHERE id=%s",
        (run.run_id,),
    ).fetchone()
    assert authority == {"interaction_protocol_version": "thread_turn_v2", "input_revision": revision}
    lease = f.repository.acquire_lease(
        user_id=f.user_id, run_id=run.run_id, owner_id="stage3-terminal-worker",
        now=now + timedelta(seconds=1), duration_seconds=60,
    )
    assert lease is not None
    terminal_at = now + timedelta(seconds=2)
    metadata = empty_checkpoint_metadata(token_budget=64)
    checkpoint = TutorCheckpoint(
        run_id=run.run_id, input_revision=revision,
        reason=TutorCheckpointReason.TERMINAL, status=TutorRunStatus.BLOCKED_POLICY,
        metadata=metadata, created_at=terminal_at,
    )
    envelope = TutorCurationEnvelope(
        request=build_compaction_request(
            run_id=run.run_id, conversation_id=run.conversation_id, input_revision=revision,
            trigger=TutorCompactionTrigger.TERMINAL, metadata=metadata,
        ),
        memory_setting_version="memory_settings_v1", priority=1,
        retention_until=terminal_at + timedelta(days=30),
        stale_after=terminal_at + timedelta(days=7),
    )
    result = TutorRunResult(
        run_id=run.run_id, status=TutorRunStatus.BLOCKED_POLICY, input_revision=revision,
        iteration_count=1, model_call_count=0, capability_call_count=0, effect_count=0,
        terminal_outcome=TutorTerminalOutcome.BLOCKED_POLICY, diagnostic_code="unknown_capability",
    )
    service = TutorPublicService(f.connection)
    before = _snapshot(f, run.conversation_id)
    assert before["active_turn"]["turn_id"] == run.run_id
    assert not [item for item in before["timeline"] if item["kind"] == "error"]
    snapshots, replays = [], []
    for _ in range(2):
        f.repository.complete_run(user_id=f.user_id, lease=lease, checkpoint=checkpoint, result=result,
                                  envelope=envelope)
        snapshots.append(_snapshot(f, run.conversation_id))
        replays.append(service.replay_conversation_events(
            user_id=f.user_id, conversation_id=run.conversation_id, cursor=before["stream_cursor"],
        ))
    assert snapshots[0] == snapshots[1]
    assert replays[0] == replays[1]
    first = snapshots[0]
    assert first["active_turn"] is None
    errors = [item for item in first["timeline"] if item["kind"] == "error"]
    assert len(errors) == 1
    assert errors[0]["turn_id"] == run.run_id
    assert errors[0]["code"] == "CAPABILITY_DENIED"
    assert errors[0]["recoverable"] is False
    updates = [event for event in replays[0] if event.event_type == "turn_updated"]
    assert len(updates) == 1
    assert updates[0].data["turn_id"] == run.run_id
    assert _snapshot(f, run.conversation_id) == first
    assert service.replay_conversation_events(
        user_id=f.user_id, conversation_id=run.conversation_id, cursor=first["stream_cursor"],
    ) == ()


def test_dead_dispatch_suppresses_generic_harness_error(tutor_persistence):
    f = tutor_persistence
    accepted, now = _create_v2_turn(f)
    f.connection.execute("UPDATE tutor_runs SET status='failed', terminal_outcome='failed', terminal_at=%s WHERE id=%s", (now, accepted.run.run_id))
    f.connection.execute("UPDATE tutor_interactive_dispatch_jobs SET state='dead', dead_at=%s WHERE id=%s", (now, accepted.acceptance.dispatch_job_id))
    errors = [i for i in _snapshot(f, accepted.run.conversation_id)["timeline"] if i["kind"] == "error"]
    assert len(errors) == 1
    assert errors[0]["id"] == accepted.acceptance.dispatch_job_id
    assert errors[0]["code"] == "TUTOR_DISPATCH_FAILED"


def test_runtime_error_keeps_identity_and_uses_queue_authority_without_private_text(tutor_persistence):
    from tests.codex_sidecar.test_codex_runtime_projection import _codex_turn

    f = tutor_persistence
    _, _, binding, _, conversation_id, run_id, now = _codex_turn(f, suffix="stage3-error")
    f.connection.execute("UPDATE tutor_runs SET status='failed', terminal_outcome='failed', terminal_at=%s WHERE id=%s", (now, run_id))
    error = f.connection.execute(
        "INSERT INTO tutor_runtime_public_errors (binding_id, run_id, user_id, conversation_id, code, recoverable, created_at) VALUES (%s,%s,%s,%s,'MODEL_UNAVAILABLE',false,%s) RETURNING id",
        (binding.binding_id, run_id, f.user_id, conversation_id, now),
    ).fetchone()
    # Deliberately stale stored recoverability must not override Queue authority.
    snapshot = _snapshot(f, conversation_id)
    errors = [i for i in snapshot["timeline"] if i["kind"] == "error"]
    assert len(errors) == 1 and errors[0]["id"] == str(error["id"])
    assert errors[0]["recoverable"] is True
    assert "private-thread" not in json.dumps(snapshot)


@pytest.mark.parametrize(("outcome", "diagnostic", "expected"), [
    ("blocked_policy", "unknown_capability", False),
    ("blocked_policy", "unknown_effect_type", False),
    ("blocked_policy", "capability_denied", True),
    ("budget_exhausted", "deadline_exhausted", True),
    ("budget_exhausted", "unknown_limit", False),
    ("model_unavailable", "private_provider_sentinel", True),
    ("failed", "private_provider_sentinel", True),
    ("cancelled", "cancelled", False),
    ("completed", "completed", False),
    (None, None, False),
    ("unknown_identifier", "private_provider_sentinel", False),
])
def test_safe_terminal_mapping(outcome, diagnostic, expected):
    from app.services.tutor.terminal_error import terminal_error_code, terminal_error_message, terminal_is_recoverable

    assert terminal_is_recoverable(outcome, diagnostic) is expected
    message = terminal_error_message(terminal_error_code(outcome, diagnostic), recoverable=expected)
    assert "private_provider_sentinel" not in message
    assert ("重试" in message) is expected
    assert any("\u4e00" <= character <= "\u9fff" for character in message)
