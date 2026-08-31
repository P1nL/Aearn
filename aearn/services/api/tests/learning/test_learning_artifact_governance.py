from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Mapping
from uuid import uuid4

import pytest
from psycopg.errors import CheckViolation, UniqueViolation

from app.db.bootstrap import bootstrap_database
from app.db.connection import connect as app_connect
from app.services.learning.artifacts.contracts import ARTIFACT_PROTECTED_MARKERS
from app.services.learning.teaching_contracts import TeachingSessionMode
from app.services.learning.teaching_sessions import TeachingSessionService
from app.services.repositories.local_user_data_repository import (
    delete_user_data,
    export_user_data,
    get_user_data_summary,
    reset_user_data,
)
from app.services.tutor.cutover import (
    CUTOVER_SHARED_TUTOR_TABLES,
    CUTOVER_TARGET_TUTOR_TABLES,
    HarnessCutoverService,
)
from tests.support.teaching_session_support import (
    connection as teaching_connection,
    create_teaching_scope,
    database_available,
)

pytestmark = pytest.mark.skipif(
    not database_available(), reason="PostgreSQL is not available"
)

ARTIFACT_TABLES = {
    "tutor_learning_artifacts",
    "tutor_learning_artifact_events",
    "tutor_learning_artifact_references",
    "tutor_learning_artifact_attempt_links",
}
ARTIFACT_CONSTRAINTS = {
    "uq_tutor_exercise_attempts_artifact_exact_scope",
    "uq_tutor_learning_artifacts_exact_scope",
    "fk_tutor_learning_artifact_conversation",
    "fk_tutor_learning_artifact_turn",
    "fk_tutor_learning_artifact_track",
    "fk_tutor_learning_artifact_progress",
    "fk_tutor_learning_artifact_session",
    "fk_tutor_learning_artifact_checkpoint",
    "fk_tutor_learning_artifact_active_attempt",
    "chk_tutor_learning_artifact_terminal",
    "chk_tutor_learning_artifact_event_versions",
    "chk_tutor_learning_artifact_event_action_shape",
    "fk_tutor_learning_artifact_attempt_link_scope",
    "fk_tutor_learning_artifact_attempt_link_attempt",
}
ARTIFACT_TRIGGERS = {
    "trg_tutor_learning_artifacts_owner_scope",
    "trg_tutor_learning_artifacts_lifecycle",
    "trg_tutor_learning_artifacts_updated_at",
    "trg_tutor_learning_artifact_events_immutable",
    "trg_tutor_learning_artifact_references_immutable",
    "trg_tutor_learning_artifact_attempt_links_immutable",
    "trg_tutor_learning_artifact_attempt_links_scope",
}


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _open_teaching_scope(conn):  # type: ignore[no-untyped-def]
    scope = create_teaching_scope(conn)
    opened = TeachingSessionService(conn).open(
        user_id=str(scope["user_id"]),
        track_id=str(scope["track_id"]),
        knowledge_key=str(scope["knowledge_key"]),
        conversation_id=str(scope["conversation_id"]),
        expected_track_version=int(scope["track_version"]),
        expected_progress_version=int(scope["progress_version"]),
        expected_assignment_version=int(scope["assignment_version"]),
        mode=TeachingSessionMode.FREE_READING,
        idempotency_key=f"artifact-open-{uuid4()}",
    )
    session_projection = opened["teaching_session"]
    assert isinstance(session_projection, Mapping)
    session = conn.execute(
        """
        SELECT id, current_checkpoint_id, version, track_version, progress_version,
               assignment_version, lesson_assignment_id, status
        FROM tutor_teaching_sessions
        WHERE id = %s AND user_id = %s
        """,
        (session_projection["session_id"], scope["user_id"]),
    ).fetchone()
    assert session is not None
    return scope, session


def _create_attempt(conn, scope):  # type: ignore[no-untyped-def]
    suffix = uuid4().hex
    revision = conn.execute(
        "SELECT revision_id FROM tutor_track_active_plans WHERE track_id = %s",
        (scope["track_id"],),
    ).fetchone()
    assert revision is not None
    exercise = conn.execute(
        """
        INSERT INTO tutor_exercise_versions (
          language_id, exercise_key, exercise_type, version, source_kind, title,
          learner_prompt_json, starter_artifact_json, required_capabilities_json,
          runtime_profile_key, execution_required, public_feedback_policy_version,
          validation_status, content_hash, published_at
        ) VALUES (
          'python', %s, 'static_code_reasoning', 'v1', 'curated_fixture',
          'Artifact governance exercise', %s::jsonb, %s::jsonb, %s::jsonb,
          NULL, false, 'artifact-governance-v1', 'ready', %s, now()
        )
        RETURNING id
        """,
        (
            f"artifact.governance.{suffix}",
            json.dumps({"text": "Explain the visible behavior."}),
            json.dumps({"content": ""}),
            json.dumps(["python.variables"]),
            _hash(f"exercise:{suffix}"),
        ),
    ).fetchone()
    assert exercise is not None
    gate_key = f"artifact.gate.{suffix}"
    slot = conn.execute(
        """
        INSERT INTO tutor_lesson_gate_slots (
          document_id, user_id, track_id, knowledge_key, block_id, gate_key,
          gate_kind, assessment_contract_version, required_capabilities_json,
          learner_prompt_hash, learner_prompt
        ) VALUES (
          %s, %s, %s, %s, %s, %s, 'knowledge_check',
          'artifact-governance-v1', %s::jsonb, %s, 'Explain the visible behavior.'
        )
        RETURNING id
        """,
        (
            scope["document_id"],
            scope["user_id"],
            scope["track_id"],
            scope["knowledge_key"],
            f"artifact.block.{suffix}",
            gate_key,
            json.dumps(["python.variables"]),
            _hash(f"prompt:{suffix}"),
        ),
    ).fetchone()
    assert slot is not None
    binding = conn.execute(
        """
        INSERT INTO tutor_lesson_gate_bindings (
          slot_id, document_id, user_id, track_id, knowledge_key, gate_key,
          exercise_version_id, requirement_kind, pass_policy_version, pass_threshold,
          execution_requirement, slot_contract_hash, binding_contract_hash, published_at
        ) VALUES (
          %s, %s, %s, %s, %s, %s, %s, 'recommended',
          'artifact-governance-v1', 0.8, 'forbidden', %s, %s, now()
        )
        RETURNING id
        """,
        (
            slot["id"],
            scope["document_id"],
            scope["user_id"],
            scope["track_id"],
            scope["knowledge_key"],
            gate_key,
            exercise["id"],
            _hash(f"slot:{suffix}"),
            _hash(f"binding:{suffix}"),
        ),
    ).fetchone()
    assert binding is not None
    attempt = conn.execute(
        """
        INSERT INTO tutor_exercise_attempts (
          attempt_type, user_id, track_id, plan_revision_id, expected_track_version,
          expected_progress_version, knowledge_key, lesson_assignment_id, document_id,
          gate_binding_id, exercise_version_id, submission_hash, hint_state_hash,
          independence, idempotency_key, request_hash, accepted_at
        ) VALUES (
          'run', %s, %s, %s, 1, 1, %s, %s, %s, %s, %s,
          %s, %s, 'independent', %s, %s, now()
        )
        RETURNING id
        """,
        (
            scope["user_id"],
            scope["track_id"],
            revision["revision_id"],
            scope["knowledge_key"],
            scope["assignment_id"],
            scope["document_id"],
            binding["id"],
            exercise["id"],
            _hash(f"submission:{suffix}"),
            _hash(f"hint:{suffix}"),
            f"artifact-attempt-{suffix}",
            _hash(f"request:{suffix}"),
        ),
    ).fetchone()
    assert attempt is not None
    conn.execute(
        """
        INSERT INTO tutor_exercise_attempt_submissions (
          attempt_id, user_id, exercise_version_id, submission_kind,
          content_text, content_hash
        ) VALUES (%s, %s, %s, 'code', %s, %s)
        """,
        (
            attempt["id"],
            scope["user_id"],
            exercise["id"],
            ARTIFACT_PROTECTED_MARKERS[0],
            _hash(ARTIFACT_PROTECTED_MARKERS[0]),
        ),
    )
    return str(attempt["id"]), str(exercise["id"])


def _insert_artifact(
    conn,  # type: ignore[no-untyped-def]
    scope: Mapping[str, object],
    session: Mapping[str, object],
    *,
    blocking: bool = True,
    owner_version: int | None = None,
    state: str = "active",
    allowed_actions: tuple[str, ...] = ("run",),
    terminal_at: datetime | None = None,
    active_attempt_id: str | None = None,
) -> str:
    resolved_owner_version = (
        int(session["version"]) if owner_version is None else owner_version
    )
    active_summary = None
    if active_attempt_id is not None:
        active_summary = json.dumps(
            {
                "attempt_id": active_attempt_id,
                "status": "pending",
                "private_marker": ARTIFACT_PROTECTED_MARKERS[2],
            }
        )
    row = conn.execute(
        """
        INSERT INTO tutor_learning_artifacts (
          user_id, conversation_id, learning_track_id, knowledge_key,
          teaching_session_id, checkpoint_id, track_version, progress_version,
          assignment_version, owner_kind, owner_id, owner_version,
          owner_context_version, artifact_kind, purpose, state, blocking,
          title, instruction_markdown, difficulty, presentation_kind,
          presentation_json, presentation_hash, allowed_actions_json,
          active_attempt_id, active_attempt_summary_json, terminal_at
        ) VALUES (
          %s, %s, %s, %s, %s, %s, %s, %s, %s,
          'teaching_practice', %s, %s, %s, 'knowledge_check',
          'knowledge_check', %s, %s, 'Artifact governance fixture', %s,
          'D2', 'knowledge_check_v1', %s::jsonb, %s, %s::jsonb,
          %s, %s::jsonb, %s
        )
        RETURNING id
        """,
        (
            scope["user_id"],
            scope["conversation_id"],
            scope["track_id"],
            scope["knowledge_key"],
            session["id"],
            session["current_checkpoint_id"],
            session["track_version"],
            session["progress_version"],
            session["assignment_version"],
            session["current_checkpoint_id"],
            resolved_owner_version,
            resolved_owner_version,
            state,
            blocking,
            f"Visible instruction. {ARTIFACT_PROTECTED_MARKERS[1]}",
            json.dumps(
                {
                    "type": "knowledge_check_v1",
                    "prompt_markdown": ARTIFACT_PROTECTED_MARKERS[4],
                }
            ),
            _hash(f"presentation:{uuid4()}"),
            json.dumps(list(allowed_actions)),
            active_attempt_id,
            active_summary,
            terminal_at,
        ),
    ).fetchone()
    assert row is not None
    return str(row["id"])


def _seed_artifact_graph(conn):  # type: ignore[no-untyped-def]
    scope, session = _open_teaching_scope(conn)
    attempt_id, exercise_version_id = _create_attempt(conn, scope)
    artifact_id = _insert_artifact(
        conn,
        scope,
        session,
        active_attempt_id=attempt_id,
    )
    conn.execute(
        """
        INSERT INTO tutor_learning_artifact_events (
          artifact_id, user_id, conversation_id, teaching_session_id,
          event_sequence, event_key, event_kind, from_version, to_version,
          state, request_hash, safe_payload_json, payload_hash
        ) VALUES (
          %s, %s, %s, %s, 1, %s, 'created', NULL, 1, 'active', %s, %s::jsonb, %s
        )
        """,
        (
            artifact_id,
            scope["user_id"],
            scope["conversation_id"],
            session["id"],
            f"artifact:{artifact_id}:created",
            _hash(f"creation-request:{artifact_id}"),
            json.dumps({"private_marker": ARTIFACT_PROTECTED_MARKERS[3]}),
            _hash(f"event:{artifact_id}"),
        ),
    )
    conn.execute(
        """
        INSERT INTO tutor_learning_artifact_references (
          artifact_id, user_id, conversation_id, teaching_session_id,
          reference_index, reference_kind, reference_id, reference_version,
          content_hash, label
        ) VALUES (%s, %s, %s, %s, 0, 'exercise_version', %s, 1, %s, %s)
        """,
        (
            artifact_id,
            scope["user_id"],
            scope["conversation_id"],
            session["id"],
            exercise_version_id,
            _hash(f"reference:{artifact_id}"),
            "Visible exercise reference",
        ),
    )
    conn.execute(
        """
        INSERT INTO tutor_learning_artifact_attempt_links (
          artifact_id, user_id, conversation_id, teaching_session_id,
          learning_track_id, attempt_id, artifact_version
        ) VALUES (%s, %s, %s, %s, %s, %s, 1)
        """,
        (
            artifact_id,
            scope["user_id"],
            scope["conversation_id"],
            session["id"],
            scope["track_id"],
            attempt_id,
        ),
    )
    sequence = conn.execute(
        """
        UPDATE tutor_conversations
        SET next_public_event_sequence = next_public_event_sequence + 1
        WHERE id = %s AND user_id = %s
        RETURNING next_public_event_sequence - 1 AS event_sequence
        """,
        (scope["conversation_id"], scope["user_id"]),
    ).fetchone()
    assert sequence is not None
    conn.execute(
        """
        INSERT INTO tutor_conversation_events (
          user_id, conversation_id, event_sequence, event_key, kind,
          item_id, item_kind, projection_version, payload_json, payload_hash,
          occurred_at
        ) VALUES (
          %s, %s, %s, %s, 'item_added', %s, 'artifact',
          'tutor_conversation_event_v3', %s::jsonb, %s, now()
        )
        """,
        (
            scope["user_id"],
            scope["conversation_id"],
            sequence["event_sequence"],
            f"artifact:{artifact_id}:item-added",
            artifact_id,
            json.dumps({"private_marker": ARTIFACT_PROTECTED_MARKERS[5]}),
            _hash(f"conversation-event:{artifact_id}"),
        ),
    )
    return scope, session, artifact_id, attempt_id, exercise_version_id


def test_learning_artifact_schema_bootstrap_twice_and_declares_governance() -> None:
    bootstrap_database()
    bootstrap_database()
    with app_connect() as conn:
        table_rows = conn.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = ANY(%s)
            """,
            (list(ARTIFACT_TABLES),),
        ).fetchall()
        constraint_rows = conn.execute(
            """
            SELECT conname, pg_get_constraintdef(oid) AS definition
            FROM pg_constraint
            WHERE conname = ANY(%s)
            """,
            (list(ARTIFACT_CONSTRAINTS),),
        ).fetchall()
        trigger_rows = conn.execute(
            """
            SELECT tgname
            FROM pg_trigger
            WHERE tgname = ANY(%s) AND NOT tgisinternal
            """,
            (list(ARTIFACT_TRIGGERS),),
        ).fetchall()
        index_rows = conn.execute(
            """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'public' AND indexname = ANY(%s)
            """,
            (
                [
                    "uq_tutor_learning_artifacts_one_blocking_conversation",
                    "uq_tutor_learning_artifacts_one_blocking_session",
                ],
            ),
        ).fetchall()

    assert {str(row["table_name"]) for row in table_rows} == ARTIFACT_TABLES
    definitions = {
        str(row["conname"]): str(row["definition"]) for row in constraint_rows
    }
    assert set(definitions) == ARTIFACT_CONSTRAINTS
    assert "knowledge_key" in definitions["fk_tutor_learning_artifact_active_attempt"]
    assert (
        "learning_track_id"
        in definitions["fk_tutor_learning_artifact_attempt_link_scope"]
    )
    assert "event_kind" in definitions["chk_tutor_learning_artifact_event_versions"]
    assert (
        "action_kind IS NULL"
        in definitions["chk_tutor_learning_artifact_event_action_shape"]
    )
    assert {str(row["tgname"]) for row in trigger_rows} == ARTIFACT_TRIGGERS
    assert {str(row["indexname"]) for row in index_rows} == {
        "uq_tutor_learning_artifacts_one_blocking_conversation",
        "uq_tutor_learning_artifacts_one_blocking_session",
    }
    assert all(" WHERE " in str(row["indexdef"]) for row in index_rows)
    assert ARTIFACT_TABLES <= CUTOVER_TARGET_TUTOR_TABLES
    assert ARTIFACT_TABLES.isdisjoint(CUTOVER_SHARED_TUTOR_TABLES)


def test_bootstrap_twice_preserves_committed_v3_conversation_event() -> None:
    bootstrap_database()
    user_id: str
    conversation_id: str
    event_id: str
    with app_connect() as conn:
        user = conn.execute(
            "INSERT INTO users (display_name) VALUES (%s) RETURNING id",
            (f"Bootstrap v3 {uuid4().hex}",),
        ).fetchone()
        assert user is not None
        user_id = str(user["id"])
        conversation = conn.execute(
            """
            INSERT INTO tutor_conversations (user_id, next_public_event_sequence)
            VALUES (%s, 2)
            RETURNING id
            """,
            (user_id,),
        ).fetchone()
        assert conversation is not None
        conversation_id = str(conversation["id"])
        event = conn.execute(
            """
            INSERT INTO tutor_conversation_events (
              user_id, conversation_id, event_sequence, event_key, kind,
              item_id, item_kind, projection_version, payload_json, payload_hash,
              occurred_at
            ) VALUES (
              %s, %s, 1, %s, 'item_added', %s, 'artifact',
              'tutor_conversation_event_v3', %s::jsonb, %s, now()
            )
            RETURNING id
            """,
            (
                user_id,
                conversation_id,
                f"bootstrap-v3:{uuid4().hex}",
                str(uuid4()),
                json.dumps({"kind": "bootstrap_v3_regression"}),
                _hash(f"bootstrap-v3:{conversation_id}"),
            ),
        ).fetchone()
        assert event is not None
        event_id = str(event["id"])
        conn.commit()

    try:
        bootstrap_database()
        bootstrap_database()
        with app_connect() as conn:
            persisted = conn.execute(
                """
                SELECT projection_version
                FROM tutor_conversation_events
                WHERE id = %s AND user_id = %s
                """,
                (event_id, user_id),
            ).fetchone()
            projection_default = conn.execute(
                """
                SELECT column_default
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'tutor_conversation_events'
                  AND column_name = 'projection_version'
                """
            ).fetchone()
            projection_constraint = conn.execute(
                """
                SELECT pg_get_constraintdef(oid) AS definition
                FROM pg_constraint
                WHERE conrelid = 'tutor_conversation_events'::regclass
                  AND conname = 'chk_tutor_conversation_events_projection_version'
                """
            ).fetchone()

        assert persisted is not None
        assert persisted["projection_version"] == "tutor_conversation_event_v3"
        assert projection_default is not None
        assert "tutor_conversation_event_v3" in str(
            projection_default["column_default"]
        )
        assert projection_constraint is not None
        definition = str(projection_constraint["definition"])
        assert "tutor_conversation_event_v1" in definition
        assert "tutor_conversation_event_v2" in definition
        assert "tutor_conversation_event_v3" in definition
    finally:
        with app_connect() as conn:
            conn.execute(
                "SELECT set_config('aearn.learning_track_purge_user_id', %s, true)",
                (user_id,),
            )
            conn.execute("SET CONSTRAINTS ALL DEFERRED")
            conn.execute(
                "DELETE FROM tutor_conversation_events WHERE id = %s AND user_id = %s",
                (event_id, user_id),
            )
            conn.execute(
                "DELETE FROM tutor_conversations WHERE id = %s AND user_id = %s",
                (conversation_id, user_id),
            )
            conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
            conn.commit()


def test_learning_artifact_postgres_enforces_governance_invariants() -> None:
    with teaching_connection() as conn:
        scope, session = _open_teaching_scope(conn)
        artifact_id = _insert_artifact(conn, scope, session)
        conn.execute(
            """
            INSERT INTO tutor_learning_artifact_events (
              artifact_id, user_id, conversation_id, teaching_session_id,
              event_sequence, event_key, event_kind, from_version, to_version,
              state, request_hash, safe_payload_json, payload_hash
            ) VALUES (
              %s, %s, %s, %s, 1, %s, 'created', NULL, 1, 'active', %s, '{}'::jsonb, %s
            )
            """,
            (
                artifact_id,
                scope["user_id"],
                scope["conversation_id"],
                session["id"],
                f"artifact:{artifact_id}:created",
                _hash(f"creation-request:{artifact_id}"),
                _hash(f"event:{artifact_id}"),
            ),
        )

        with pytest.raises(UniqueViolation):
            with conn.transaction():
                _insert_artifact(conn, scope, session)

        with pytest.raises(CheckViolation):
            with conn.transaction():
                _insert_artifact(conn, scope, session, blocking=False, owner_version=2)

        other = conn.execute(
            "INSERT INTO users (display_name) VALUES ('Artifact Other') RETURNING id"
        ).fetchone()
        assert other is not None
        foreign_scope = dict(scope)
        foreign_scope["user_id"] = other["id"]
        with pytest.raises(CheckViolation):
            with conn.transaction():
                _insert_artifact(conn, foreign_scope, session, blocking=False)

        with pytest.raises(CheckViolation):
            with conn.transaction():
                conn.execute(
                    "UPDATE tutor_learning_artifacts SET state = 'running', version = 3 WHERE id = %s",
                    (artifact_id,),
                )

        with pytest.raises(CheckViolation):
            with conn.transaction():
                conn.execute(
                    "UPDATE tutor_learning_artifacts SET state = 'pending', version = 2 WHERE id = %s",
                    (artifact_id,),
                )

        with pytest.raises(CheckViolation):
            with conn.transaction():
                _insert_artifact(
                    conn,
                    scope,
                    session,
                    blocking=False,
                    state="completed",
                    terminal_at=datetime.now(UTC),
                )

        with pytest.raises(CheckViolation):
            with conn.transaction():
                conn.execute(
                    """
                    INSERT INTO tutor_learning_artifact_events (
                      artifact_id, user_id, conversation_id, teaching_session_id,
                      event_sequence, event_key, event_kind, from_version, to_version,
                      state, action_kind, safe_payload_json, payload_hash
                    ) VALUES (
                      %s, %s, %s, %s, 2, %s, 'state_changed', 1, 2,
                      'running', 'run', '{}'::jsonb, %s
                    )
                    """,
                    (
                        artifact_id,
                        scope["user_id"],
                        scope["conversation_id"],
                        session["id"],
                        f"artifact:{artifact_id}:invalid-action-shape",
                        _hash(f"invalid-event:{artifact_id}"),
                    ),
                )

        with pytest.raises(CheckViolation):
            with conn.transaction():
                conn.execute(
                    "UPDATE tutor_learning_artifact_events SET safe_payload_json = '{}'::jsonb "
                    "WHERE artifact_id = %s",
                    (artifact_id,),
                )

        unlinked_artifact_id = _insert_artifact(conn, scope, session, blocking=False)
        with pytest.raises(CheckViolation):
            with conn.transaction():
                conn.execute(
                    "DELETE FROM tutor_learning_artifacts WHERE id = %s",
                    (unlinked_artifact_id,),
                )


def test_learning_artifact_export_cutover_and_reset_are_complete_and_redacted() -> None:
    with teaching_connection() as conn:
        scope, _session, artifact_id, _attempt_id, exercise_version_id = (
            _seed_artifact_graph(conn)
        )
        user_id = str(scope["user_id"])

        inventory = HarnessCutoverService(conn)._inventory(user_id)
        assert inventory.target_counts["tutor_learning_artifacts"] == 1
        assert inventory.target_counts["tutor_learning_artifact_events"] == 1
        assert inventory.target_counts["tutor_learning_artifact_references"] == 1
        assert inventory.target_counts["tutor_learning_artifact_attempt_links"] == 1

        summary = get_user_data_summary(conn, user_id)
        assert summary["counts"]["learning_artifacts"] == 1
        assert summary["counts"]["learning_artifact_events"] == 1
        assert summary["counts"]["learning_artifact_references"] == 1
        assert summary["counts"]["learning_artifact_attempt_links"] == 1

        exported = export_user_data(conn, user_id)
        assert len(exported["learning_artifact_summaries"]) == 1
        assert len(exported["learning_artifact_event_summaries"]) == 1
        assert len(exported["learning_artifact_reference_summaries"]) == 1
        assert len(exported["learning_artifact_attempt_link_summaries"]) == 1
        artifact_summary = exported["learning_artifact_summaries"][0]
        assert artifact_summary["id"] == artifact_id
        assert artifact_summary["event_count"] == 1
        assert artifact_summary["reference_count"] == 1
        assert artifact_summary["attempt_link_count"] == 1

        serialized = json.dumps(exported, ensure_ascii=False, sort_keys=True)
        for marker in ARTIFACT_PROTECTED_MARKERS:
            assert marker not in serialized
        artifact_serialized = json.dumps(
            {
                "artifacts": exported["learning_artifact_summaries"],
                "events": exported["learning_artifact_event_summaries"],
                "references": exported["learning_artifact_reference_summaries"],
                "attempt_links": exported["learning_artifact_attempt_link_summaries"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        for protected_field in (
            "instruction_markdown",
            "presentation_json",
            "active_attempt_summary_json",
            "safe_payload_json",
            "request_hash",
            "payload_hash",
            "content_hash",
        ):
            assert f'"{protected_field}"' not in artifact_serialized
        assert exported["redaction"]["artifact_presentations"] == "omitted"
        assert exported["redaction"]["artifact_event_payloads"] == "omitted"

        reset = reset_user_data(conn, user_id)
        assert reset["summary"]["counts"]["learning_artifacts"] == 0
        assert reset["summary"]["counts"]["learning_artifact_events"] == 0
        assert reset["summary"]["counts"]["learning_artifact_references"] == 0
        assert reset["summary"]["counts"]["learning_artifact_attempt_links"] == 0
        for table_name in ARTIFACT_TABLES:
            remaining = conn.execute(
                f"SELECT count(*)::int AS count FROM {table_name} WHERE user_id = %s",
                (user_id,),
            ).fetchone()
            assert remaining is not None and remaining["count"] == 0
        dangling_event = conn.execute(
            """
            SELECT count(*)::int AS count
            FROM tutor_conversation_events
            WHERE user_id = %s AND item_kind = 'artifact' AND item_id = %s
            """,
            (user_id, artifact_id),
        ).fetchone()
        assert dangling_event is not None and dangling_event["count"] == 0
        assert (
            conn.execute(
                "SELECT 1 FROM tutor_exercise_versions WHERE id = %s",
                (exercise_version_id,),
            ).fetchone()
            is not None
        )


def test_learning_artifact_delete_user_reuses_child_first_purge() -> None:
    with teaching_connection() as conn:
        scope, _session, artifact_id, _attempt_id, _exercise_version_id = (
            _seed_artifact_graph(conn)
        )
        user_id = str(scope["user_id"])

        deleted = delete_user_data(conn, user_id)
        assert deleted["deleted_user_id"] == user_id
        assert (
            conn.execute(
                "SELECT deleted_at FROM users WHERE id = %s",
                (user_id,),
            ).fetchone()["deleted_at"]
            is not None
        )
        for table_name in ARTIFACT_TABLES:
            remaining = conn.execute(
                f"SELECT count(*)::int AS count FROM {table_name} WHERE user_id = %s",
                (user_id,),
            ).fetchone()
            assert remaining is not None and remaining["count"] == 0
        dangling_event = conn.execute(
            """
            SELECT count(*)::int AS count
            FROM tutor_conversation_events
            WHERE user_id = %s AND item_kind = 'artifact' AND item_id = %s
            """,
            (user_id, artifact_id),
        ).fetchone()
        assert dangling_event is not None and dangling_event["count"] == 0
