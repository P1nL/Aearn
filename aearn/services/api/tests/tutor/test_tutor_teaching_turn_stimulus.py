from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.learning.teaching_contracts import (
    DomainEventStimulus,
    LearnerMessageStimulus,
    TeachingControlStimulus,
    TeachingSessionMode,
)
from app.services.learning.teaching_sessions import (
    TeachingSessionConflict,
    TeachingSessionRepository,
    TeachingSessionService,
)
from tests.support.teaching_session_support import connection, create_teaching_scope, database_available

pytestmark = pytest.mark.skipif(not database_available(), reason="PostgreSQL is not available")


def _open(conn, scope):  # type: ignore[no-untyped-def]
    return TeachingSessionService(conn).open(
        user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), knowledge_key="python.variables",
        conversation_id=str(scope["conversation_id"]), expected_track_version=1,
        expected_progress_version=1, expected_assignment_version=1,
        mode=TeachingSessionMode.FREE_READING, idempotency_key=f"open-{uuid4()}",
    )["teaching_session"]


def _learner_run(conn, scope):  # type: ignore[no-untyped-def]
    digest = uuid4().hex.ljust(64, "0")[:64]
    conn.execute("INSERT INTO tutor_catalog_snapshots (digest,manifest_json,redaction_version) VALUES (%s,'{}'::jsonb,'test')", (digest,))
    run = conn.execute(
        """INSERT INTO tutor_runs (
             user_id,conversation_id,origin,status,policy_json,policy_version,policy_fingerprint,catalog_digest,
             interaction_protocol_version,runtime_kind,input_revision
           ) VALUES (%s,%s,'interactive','queued','{}'::jsonb,'test',%s,%s,'thread_turn_v2','harness_v1',1) RETURNING id""",
        (scope["user_id"], scope["conversation_id"], "f" * 64, digest),
    ).fetchone()
    assert run is not None
    message = conn.execute(
        "INSERT INTO tutor_messages (conversation_id,role,content) VALUES (%s,'learner','hello') RETURNING id",
        (scope["conversation_id"],),
    ).fetchone()
    assert message is not None
    conn.execute(
        """INSERT INTO tutor_run_input_events
           (run_id,conversation_id,message_id,input_revision,idempotency_key,body_hash,source)
           VALUES (%s,%s,%s,1,%s,%s,'learner_message')""",
        (run["id"], scope["conversation_id"], message["id"], f"input-{uuid4()}", "1" * 64),
    )
    conn.execute(
        """INSERT INTO tutor_run_learning_scopes
           (run_id,user_id,conversation_id,scope_kind,learning_track_id,task_kind,knowledge_key,scope_version)
           VALUES (%s,%s,%s,'learning_track',%s,'lesson_teaching','python.variables',1)""",
        (run["id"], scope["user_id"], scope["conversation_id"], scope["track_id"]),
    )
    return str(run["id"]), str(message["id"])


def test_learner_message_is_exact_stimulus_and_stale_progress_fails_closed() -> None:
    with connection() as conn:
        scope = create_teaching_scope(conn)
        _open(conn, scope)
        run_id, message_id = _learner_run(conn, scope)
        repository = TeachingSessionRepository(conn)
        admitted = repository.bind_learner_message_run(
            user_id=str(scope["user_id"]), run_id=run_id, conversation_id=str(scope["conversation_id"]),
            track_id=str(scope["track_id"]), knowledge_key="python.variables",
            message_id=message_id, input_revision=1,
        )
        assert admitted is not None and admitted["stimulus_kind"] == "learner_message"
        row = conn.execute("SELECT * FROM tutor_run_stimulus_events WHERE run_id=%s", (run_id,)).fetchone()
        assert row is not None
        assert row["message_id"] is not None and row["control_key"] is None and row["domain_event_kind"] is None
        repository.assert_run_scope_current(user_id=str(scope["user_id"]), run_id=run_id)
        conn.execute(
            "UPDATE tutor_learning_tracks SET version=version+1 WHERE id=%s AND user_id=%s",
            (scope["track_id"], scope["user_id"]),
        )
        with pytest.raises(TeachingSessionConflict, match="LearningTrack authority is stale"):
            repository.assert_run_scope_current(user_id=str(scope["user_id"]), run_id=run_id)


def test_control_and_domain_contracts_never_forge_learner_message_or_proactive_origin() -> None:
    learner = LearnerMessageStimulus(message_id=str(uuid4()), input_revision=1)
    domain = DomainEventStimulus(event_kind="gate_terminal", source_id="gate:terminal", source_version=1)
    assert learner.kind == "learner_message" and domain.kind == "domain_event"
    with connection() as conn:
        scope = create_teaching_scope(conn)
        session = _open(conn, scope)
        repository = TeachingSessionRepository(conn)
        authority = repository.resolve_authority(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), knowledge_key="python.variables",
            conversation_id=str(scope["conversation_id"]), for_update=True,
        )
        control = TeachingControlStimulus(
            control_key="continue", client_action_id="control-run",
            expected_session_version=1, expected_track_version=1,
            expected_progress_version=1, expected_assignment_version=1,
        )
        admitted = repository.admit_control_run(authority=authority, session=repository.read_by_id(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), session_id=str(session["session_id"]), for_update=True,
        ), stimulus=control)
        assert admitted["origin"] == "interactive"
        run_id = str(admitted["run_id"])
        assert conn.execute("SELECT count(*) AS count FROM tutor_run_input_events WHERE run_id=%s", (run_id,)).fetchone()["count"] == 0
        assert conn.execute("SELECT count(*) AS count FROM tutor_messages WHERE conversation_id=%s", (scope["conversation_id"],)).fetchone()["count"] == 0
        stimulus = conn.execute("SELECT * FROM tutor_run_stimulus_events WHERE run_id=%s", (run_id,)).fetchone()
        assert stimulus is not None and stimulus["stimulus_kind"] == "teaching_control" and stimulus["message_id"] is None
        from app.services.repositories.local_user_data_repository import reset_user_data

        reset = reset_user_data(conn, str(scope["user_id"]))
        assert reset["summary"]["counts"]["teaching_stimuli"] == 0
        assert reset["summary"]["counts"]["run_teaching_scopes"] == 0
