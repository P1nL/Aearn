from __future__ import annotations

from uuid import uuid4

import psycopg
import pytest

from app.db.bootstrap import bootstrap_database
from app.services.learning.teaching_contracts import TeachingSessionMode
from app.services.learning.teaching_sessions import TeachingSessionService
from teaching_session_support import connection, create_teaching_scope, database_available

pytestmark = pytest.mark.skipif(not database_available(), reason="PostgreSQL is not available")


def _open(conn, scope):  # type: ignore[no-untyped-def]
    return TeachingSessionService(conn).open(
        user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), knowledge_key="python.variables",
        conversation_id=str(scope["conversation_id"]), expected_track_version=1,
        expected_progress_version=1, expected_assignment_version=1,
        mode=TeachingSessionMode.FREE_READING, idempotency_key=f"open-{uuid4()}",
    )["teaching_session"]


def _empty_run(conn, scope):  # type: ignore[no-untyped-def]
    digest = uuid4().hex.ljust(64, "0")[:64]
    conn.execute(
        "INSERT INTO tutor_catalog_snapshots (digest,manifest_json,redaction_version) VALUES (%s,'{}'::jsonb,'test')",
        (digest,),
    )
    row = conn.execute(
        """INSERT INTO tutor_runs (
             user_id,conversation_id,origin,status,policy_json,policy_version,policy_fingerprint,catalog_digest,
             interaction_protocol_version,runtime_kind
           ) VALUES (%s,%s,'interactive','queued','{}'::jsonb,'test',%s,%s,'thread_turn_v2','harness_v1') RETURNING id""",
        (scope["user_id"], scope["conversation_id"], "f" * 64, digest),
    ).fetchone()
    assert row is not None
    return str(row["id"])


def test_bootstrap_twice_installs_tables_partial_unique_and_immutable_triggers() -> None:
    bootstrap_database()
    bootstrap_database()
    with connection() as conn:
        tables = {str(row["table_name"]) for row in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name LIKE 'tutor%teaching%'"
        ).fetchall()}
        assert {
            "tutor_teaching_sessions", "tutor_teaching_session_checkpoints",
            "tutor_run_teaching_scopes", "tutor_teaching_action_receipts",
        }.issubset(tables)
        index = conn.execute("SELECT indexdef FROM pg_indexes WHERE indexname='uq_tutor_teaching_sessions_one_current'").fetchone()
        assert index is not None and "WHERE" in str(index["indexdef"])
        assert "'blocked'" not in str(index["indexdef"])
        source_stimulus_fk = conn.execute(
            """SELECT condeferrable,confdeltype FROM pg_constraint
               WHERE conname='fk_tutor_teaching_checkpoint_source_stimulus'"""
        ).fetchone()
        assert source_stimulus_fk == {"condeferrable": True, "confdeltype": "a"}
        triggers = {str(row["tgname"]) for row in conn.execute(
            """SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgrelid IN (
                 'tutor_teaching_sessions'::regclass,'tutor_teaching_session_checkpoints'::regclass,
                 'tutor_run_stimulus_events'::regclass,'tutor_run_teaching_scopes'::regclass,
                 'tutor_teaching_action_receipts'::regclass)"""
        ).fetchall()}
        assert "trg_tutor_teaching_sessions_lifecycle" in triggers
        assert "trg_tutor_teaching_checkpoints_immutable" in triggers
        assert "trg_tutor_run_stimuli_immutable" in triggers
        assert "trg_tutor_run_teaching_scopes_immutable" in triggers
        assert "trg_tutor_teaching_action_receipts_immutable" in triggers


def test_postgres_rejects_duplicate_current_append_mutation_and_bad_exact_one_of() -> None:
    with connection() as conn:
        scope = create_teaching_scope(conn)
        session = _open(conn, scope)
        with pytest.raises(psycopg.errors.UniqueViolation):
            with conn.transaction():
                conn.execute(
                    """INSERT INTO tutor_teaching_sessions (
                         user_id,track_id,conversation_id,knowledge_key,track_version,active_plan_revision_id,
                         progress_version,lesson_assignment_id,assignment_version,document_id,document_content_hash,status,mode
                       ) SELECT user_id,track_id,conversation_id,knowledge_key,track_version,active_plan_revision_id,
                         progress_version,lesson_assignment_id,assignment_version,document_id,document_content_hash,'active',mode
                       FROM tutor_teaching_sessions WHERE id=%s""",
                    (session["session_id"],),
                )
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(
                    "UPDATE tutor_teaching_session_checkpoints SET state_json='{}'::jsonb WHERE id=%s",
                    (session["checkpoint_id"],),
                )
        run_id = _empty_run(conn, scope)
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(
                    """INSERT INTO tutor_run_stimulus_events (
                         run_id,user_id,conversation_id,teaching_session_id,stimulus_kind,message_id,
                         control_key,client_action_id,expected_session_version,expected_track_version,
                         expected_progress_version,expected_assignment_version,payload_hash
                       ) VALUES (%s,%s,%s,%s,'teaching_control',%s,'continue','bad-shape',1,1,1,1,%s)""",
                    (run_id, scope["user_id"], scope["conversation_id"], session["session_id"], uuid4(), "a" * 64),
                )
