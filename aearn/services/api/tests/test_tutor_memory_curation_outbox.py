from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.agents.harness.contracts import (
    TutorCheckpoint,
    TutorCheckpointReason,
    TutorCompactionTrigger,
    TutorRunResult,
    TutorRunStatus,
    TutorTerminalOutcome,
    build_compaction_request,
    empty_checkpoint_metadata,
)
from app.services.tutor.persistence import PostgresTutorRepository, TutorCurationEnvelope


_NOW = datetime(2026, 7, 27, tzinfo=UTC)


def _lease(fixture):
    lease = fixture.repository.acquire_lease(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        owner_id="curation-worker",
        now=_NOW,
        duration_seconds=60,
    )
    assert lease is not None
    return lease


def _checkpoint(fixture, *, reason: TutorCheckpointReason, status: TutorRunStatus) -> TutorCheckpoint:
    return TutorCheckpoint(
        run_id=fixture.run.run_id,
        input_revision=0,
        reason=reason,
        status=status,
        metadata=empty_checkpoint_metadata(token_budget=64),
        created_at=_NOW,
    )


def _envelope(fixture, *, trigger: TutorCompactionTrigger) -> TutorCurationEnvelope:
    request = build_compaction_request(
        run_id=fixture.run.run_id,
        conversation_id=fixture.conversation_id,
        input_revision=0,
        trigger=trigger,
        metadata=empty_checkpoint_metadata(token_budget=64),
    )
    return TutorCurationEnvelope(
        request=request,
        memory_setting_version="memory_settings_v1",
        priority=1,
        retention_until=_NOW + timedelta(days=30),
        stale_after=_NOW + timedelta(days=7),
    )


def test_lifecycle_failure_rolls_back_checkpoint_event_trace_and_outbox(tutor_persistence) -> None:
    fixture = tutor_persistence
    lease = _lease(fixture)

    def fail_after_event(stage: str) -> None:
        if stage == "after_event":
            raise RuntimeError("forced lifecycle rollback")

    failing_repository = PostgresTutorRepository(fixture.connection, failpoint=fail_after_event)
    with pytest.raises(RuntimeError, match="forced lifecycle rollback"):
        failing_repository.persist_safe_checkpoint(
            user_id=fixture.user_id,
            lease=lease,
            checkpoint=_checkpoint(fixture, reason=TutorCheckpointReason.SAFE_PROGRESS, status=TutorRunStatus.LEASED),
            envelope=_envelope(fixture, trigger=TutorCompactionTrigger.SAFE_CHECKPOINT),
        )

    counts = fixture.connection.execute(
        """
        SELECT
          (SELECT count(*) FROM tutor_run_checkpoints WHERE run_id = %s) AS checkpoints,
          (SELECT count(*) FROM tutor_run_events WHERE run_id = %s) AS events,
          (SELECT count(*) FROM tutor_run_traces WHERE run_id = %s) AS traces,
          (SELECT count(*) FROM tutor_memory_curation_outbox WHERE run_id = %s) AS outbox
        """,
        (fixture.run.run_id, fixture.run.run_id, fixture.run.run_id, fixture.run.run_id),
    ).fetchone()
    assert counts == {"checkpoints": 0, "events": 0, "traces": 0, "outbox": 0}


def test_terminal_lifecycle_outbox_and_proposal_are_deduplicated_without_domain_writes(tutor_persistence) -> None:
    fixture = tutor_persistence
    lease = _lease(fixture)
    safe_checkpoint = _checkpoint(fixture, reason=TutorCheckpointReason.SAFE_PROGRESS, status=TutorRunStatus.LEASED)
    safe_envelope = _envelope(fixture, trigger=TutorCompactionTrigger.SAFE_CHECKPOINT)
    fixture.repository.persist_safe_checkpoint(
        user_id=fixture.user_id,
        lease=lease,
        checkpoint=safe_checkpoint,
        envelope=safe_envelope,
    )
    terminal_checkpoint = _checkpoint(fixture, reason=TutorCheckpointReason.TERMINAL, status=TutorRunStatus.COMPLETED)
    terminal_result = TutorRunResult(
        run_id=fixture.run.run_id,
        status=TutorRunStatus.COMPLETED,
        input_revision=0,
        iteration_count=1,
        model_call_count=1,
        capability_call_count=0,
        effect_count=0,
        terminal_outcome=TutorTerminalOutcome.COMPLETED,
        diagnostic_code="completed",
    )
    first_terminal = fixture.repository.complete_run(
        user_id=fixture.user_id,
        lease=lease,
        checkpoint=terminal_checkpoint,
        result=terminal_result,
        envelope=_envelope(fixture, trigger=TutorCompactionTrigger.TERMINAL),
    )
    replayed_terminal = fixture.repository.complete_run(
        user_id=fixture.user_id,
        lease=lease,
        checkpoint=terminal_checkpoint,
        result=terminal_result,
        envelope=_envelope(fixture, trigger=TutorCompactionTrigger.TERMINAL),
    )
    outbox = fixture.connection.execute(
        """
        SELECT id, policy_version, memory_setting_version
        FROM tutor_memory_curation_outbox
        WHERE run_id = %s AND trigger = 'terminal'
        """,
        (fixture.run.run_id,),
    ).fetchone()
    assert outbox is not None

    proposal = fixture.repository.record_curation_proposal(
        user_id=fixture.user_id,
        outbox_id=str(outbox["id"]),
        kind="context_summary",
        state="pending",
        payload={
            "kind": "context_summary",
            "source_id": "checkpoint-1",
            "source_hash": "a" * 64,
            "provider_payload": "must never persist",
        },
        confidence="medium",
        policy_version=str(outbox["policy_version"]),
        memory_setting_version=str(outbox["memory_setting_version"]),
        created_at=_NOW,
    )
    replayed_proposal = fixture.repository.record_curation_proposal(
        user_id=fixture.user_id,
        outbox_id=str(outbox["id"]),
        kind="context_summary",
        state="pending",
        payload={
            "kind": "context_summary",
            "source_id": "checkpoint-1",
            "source_hash": "a" * 64,
            "provider_payload": "must never persist",
        },
        confidence="medium",
        policy_version=str(outbox["policy_version"]),
        memory_setting_version=str(outbox["memory_setting_version"]),
        created_at=_NOW,
    )
    counts = fixture.connection.execute(
        """
        SELECT
          (SELECT count(*) FROM tutor_memory_curation_outbox WHERE run_id = %s AND trigger = 'terminal') AS terminal_outbox,
          (SELECT count(*) FROM tutor_curation_proposals WHERE outbox_id = %s) AS proposals,
          (SELECT count(*) FROM tutor_run_events WHERE run_id = %s AND kind = 'terminal_result') AS terminal_events
        """,
        (fixture.run.run_id, outbox["id"], fixture.run.run_id),
    ).fetchone()

    assert first_terminal.status is TutorRunStatus.COMPLETED
    assert replayed_terminal.status is TutorRunStatus.COMPLETED
    assert proposal.replayed is False
    assert replayed_proposal.replayed is True
    assert replayed_proposal.proposal_id == proposal.proposal_id
    assert counts == {"terminal_outbox": 1, "proposals": 1, "terminal_events": 1}
def test_checkpoint_lifecycle_replay_reuses_one_trace_event_and_outbox(tutor_persistence) -> None:
    fixture = tutor_persistence
    lease = _lease(fixture)
    checkpoint = _checkpoint(fixture, reason=TutorCheckpointReason.SAFE_PROGRESS, status=TutorRunStatus.LEASED)
    envelope = _envelope(fixture, trigger=TutorCompactionTrigger.SAFE_CHECKPOINT)

    first = fixture.repository.persist_safe_checkpoint(
        user_id=fixture.user_id,
        lease=lease,
        checkpoint=checkpoint,
        envelope=envelope,
    )
    replayed = fixture.repository.persist_safe_checkpoint(
        user_id=fixture.user_id,
        lease=lease,
        checkpoint=checkpoint,
        envelope=envelope,
    )
    counts = fixture.connection.execute(
        """
        SELECT
          (SELECT count(*) FROM tutor_run_events WHERE run_id = %s) AS events,
          (SELECT count(*) FROM tutor_run_traces WHERE run_id = %s) AS traces,
          (SELECT count(*) FROM tutor_memory_curation_outbox WHERE run_id = %s) AS outbox
        """,
        (fixture.run.run_id, fixture.run.run_id, fixture.run.run_id),
    ).fetchone()

    assert replayed.trace_id == first.trace_id
    assert counts == {"events": 1, "traces": 1, "outbox": 1}


def test_curation_proposal_marks_advanced_source_revision_stale_without_overriding_typed_payload(tutor_persistence) -> None:
    fixture = tutor_persistence
    lease = _lease(fixture)
    checkpoint = _checkpoint(fixture, reason=TutorCheckpointReason.SAFE_PROGRESS, status=TutorRunStatus.LEASED)
    fixture.repository.persist_safe_checkpoint(
        user_id=fixture.user_id,
        lease=lease,
        checkpoint=checkpoint,
        envelope=_envelope(fixture, trigger=TutorCompactionTrigger.SAFE_CHECKPOINT),
    )
    outbox = fixture.connection.execute(
        "SELECT id, policy_version, memory_setting_version FROM tutor_memory_curation_outbox WHERE run_id = %s",
        (fixture.run.run_id,),
    ).fetchone()
    assert outbox is not None
    fixture.repository.accept_input(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        idempotency_key="curation-newer-input",
        content="A newer input closes the old curation source range.",
    )

    proposal = fixture.repository.record_curation_proposal(
        user_id=fixture.user_id,
        outbox_id=str(outbox["id"]),
        kind="context_summary",
        state="pending",
        payload={
            "kind": "memory_entry",
            "confidence": "low",
            "source_id": "checkpoint-1",
            "source_hash": "a" * 64,
        },
        confidence="medium",
        policy_version=str(outbox["policy_version"]),
        memory_setting_version=str(outbox["memory_setting_version"]),
        created_at=_NOW,
    )
    stored = fixture.connection.execute(
        """
        SELECT proposals.state, proposals.payload_json, outbox.state AS outbox_state
        FROM tutor_curation_proposals AS proposals
        JOIN tutor_memory_curation_outbox AS outbox ON outbox.id = proposals.outbox_id
        WHERE proposals.id = %s
        """,
        (proposal.proposal_id,),
    ).fetchone()

    assert proposal.state == "stale"
    assert stored is not None
    assert stored["state"] == "stale"
    assert stored["outbox_state"] == "stale"
    assert stored["payload_json"]["kind"] == "context_summary"
    assert stored["payload_json"]["confidence"] == "medium"
