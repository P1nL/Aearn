from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from app.agents.harness.contracts import (
    TutorCheckpoint,
    TutorCheckpointReason,
    TutorCompactionTrigger,
    TutorRunStatus,
    build_compaction_request,
    empty_checkpoint_metadata,
)
from app.services.tutor.persistence import TutorCurationEnvelope
from app.services.tutor.safe_projection import TutorSafeProjection


_NOW = datetime(2026, 7, 27, tzinfo=UTC)


def test_safe_projection_removes_nested_fields_and_value_shaped_protected_data() -> None:
    projector = TutorSafeProjection()
    protected = {
        "kind": "diagnostic",
        "status": "completed",
        "redaction_version": "untrusted-version",
        "providerPayload": {"raw_prompt": "system prompt should not persist"},
        "hiddenTestBody": "hidden test oracle",
        "solution_reference": "complete answer",
        "path": "C:\\container\\workspace\\secret.py",
        "shell_target": "powershell Remove-Item C:\\data",
        "sql_target": "SELECT secret FROM credentials",
        "credential_url": "https://user:password@example.test/path",
        "traceback": "Traceback (most recent call last)",
        "source_hash": "b" * 64,
        "source_id": "safe-source",
    }

    projected = projector.export(projector.project(protected))
    serialized = json.dumps(projected, ensure_ascii=False, sort_keys=True)

    assert projected["kind"] == "diagnostic"
    assert projected["redaction_version"] == projector.version
    assert projected["source_hash"] == "b" * 64
    assert projected["source_id"] == "safe-source"
    for marker in (
        "system prompt",
        "hidden test",
        "complete answer",
        "container\\workspace",
        "Remove-Item",
        "SELECT secret",
        "user:password",
        "Traceback",
    ):
        assert marker not in serialized


def test_trace_outbox_and_export_never_rehydrate_learner_or_historical_malformed_payload(tutor_persistence) -> None:
    fixture = tutor_persistence
    raw_learner_text = "I pasted a private code sample that must stay in canonical messages only."
    accepted = fixture.repository.accept_input(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        idempotency_key="trace-input",
        content=raw_learner_text,
    )
    lease = fixture.repository.acquire_lease(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        owner_id="trace-worker",
        now=_NOW,
        duration_seconds=60,
    )
    assert lease is not None
    metadata = empty_checkpoint_metadata(token_budget=64)
    checkpoint = TutorCheckpoint(
        run_id=fixture.run.run_id,
        input_revision=1,
        reason=TutorCheckpointReason.SAFE_PROGRESS,
        status=TutorRunStatus.LEASED,
        metadata=metadata,
        created_at=_NOW,
    )
    request = build_compaction_request(
        run_id=fixture.run.run_id,
        conversation_id=fixture.conversation_id,
        input_revision=1,
        trigger=TutorCompactionTrigger.SAFE_CHECKPOINT,
        metadata=metadata,
    )
    fixture.repository.persist_safe_checkpoint(
        user_id=fixture.user_id,
        lease=lease,
        checkpoint=checkpoint,
        envelope=TutorCurationEnvelope(
            request=request,
            retention_until=_NOW + timedelta(days=30),
            stale_after=_NOW + timedelta(days=7),
        ),
    )

    normal_rows = fixture.connection.execute(
        """
        SELECT payload_json::text AS body FROM tutor_run_events WHERE run_id = %s
        UNION ALL SELECT trace_json::text FROM tutor_run_traces WHERE run_id = %s
        UNION ALL SELECT envelope_json::text FROM tutor_memory_curation_outbox WHERE run_id = %s
        """,
        (fixture.run.run_id, fixture.run.run_id, fixture.run.run_id),
    ).fetchall()
    assert all(raw_learner_text not in str(row["body"]) for row in normal_rows)

    malformed = {
        "kind": "diagnostic",
        "status": "provider raw Authorization: Bearer secret-token",
        "provider_payload": {"hidden_test_body": "hidden test body"},
        "source_id": "safe-source",
        "source_hash": "c" * 64,
        "path": "C:\\host\\secret.txt",
    }
    fixture.connection.execute(
        "UPDATE tutor_run_events SET payload_json = %s::jsonb, kind = %s WHERE id = %s",
        (json.dumps(malformed), "provider_raw_secret_token", accepted.event.event_id),
    )
    fixture.connection.execute(
        "UPDATE tutor_run_traces SET kind = %s WHERE run_id = %s",
        ("C:\\host\\secret-trace", fixture.run.run_id),
    )
    replayed_events = fixture.repository.events_after(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        after_sequence=0,
        limit=10,
    )
    exported = fixture.repository.export_diagnostics(user_id=fixture.user_id, run_id=fixture.run.run_id)
    serialized = json.dumps(exported, ensure_ascii=False, sort_keys=True)

    canonical_message = fixture.connection.execute(
        "SELECT content FROM tutor_messages WHERE id = %s",
        (accepted.message_id,),
    ).fetchone()
    assert canonical_message is not None and canonical_message["content"] == raw_learner_text
    assert replayed_events[0].kind == "invalid_event"
    for marker in (
        raw_learner_text,
        "secret-token",
        "hidden test body",
        "C:\\host\\secret.txt",
        "provider_raw_secret_token",
        "C:\\host\\secret-trace",
    ):
        assert marker not in serialized
