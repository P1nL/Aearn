"""Isolated-owner regression for a blocked ancestor's ghost Artifact."""

from uuid import uuid4

import pytest
from psycopg.errors import CheckViolation

from tests.learning.test_gate_catalog_mapping import _require_dedicated_database
from app.services.learning.lesson_service import LessonDocumentService
from app.services.learning.teaching_contracts import TeachingSessionMode
from app.services.learning.teaching_sessions import TeachingSessionRepository
from tests.tutor.test_tutor_teaching_artifact_commit import (
    _materialized_knowledge_artifact,
    connection,
)


def _start_and_open(conn, settings, scope):
    LessonDocumentService(conn).start(
        user_id=str(scope["user_id"]),
        track_id=str(scope["track_id"]),
        knowledge_key="python.variables",
        assignment_id=str(scope["assignment_id"]),
        expected_assignment_version=1,
        expected_progress_version=1,
        idempotency_key=f"supersession-start:{uuid4()}",
    )
    repository = TeachingSessionRepository(conn, settings=settings)
    authority = repository.resolve_authority(
        user_id=str(scope["user_id"]),
        track_id=str(scope["track_id"]),
        knowledge_key="python.variables",
    )
    current, _ = repository.open_or_resume(
        authority=authority, mode=TeachingSessionMode.GUIDED
    )
    return repository, authority, current


def _artifact(conn, artifact_id):
    return conn.execute(
        "SELECT id,state,version,presentation_json,presentation_hash,owner_id,owner_version,owner_context_version,checkpoint_id,teaching_session_id,active_attempt_id,allowed_actions_json FROM tutor_learning_artifacts WHERE id=%s",
        (artifact_id,),
    ).fetchone()


def _assert_retired(conn, before, after, scope, successor):
    assert after["state"] == "superseded" and after["version"] == before["version"] + 1
    assert after["allowed_actions_json"] == []
    for field in (
        "presentation_json",
        "presentation_hash",
        "owner_id",
        "owner_version",
        "owner_context_version",
        "checkpoint_id",
        "teaching_session_id",
        "active_attempt_id",
    ):
        assert after[field] == before[field]
    terminal = conn.execute(
        "SELECT event_kind,safe_payload_json FROM tutor_learning_artifact_events WHERE artifact_id=%s AND to_version=%s",
        (after["id"], after["version"]),
    ).fetchone()
    assert terminal["event_kind"] == "terminal"
    assert terminal["safe_payload_json"]["owner_result"]["successor_session_id"] == str(
        successor["id"]
    )
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM tutor_conversation_events WHERE conversation_id=%s AND item_id=%s AND kind='item_updated'",
            (scope["conversation_id"], after["id"]),
        ).fetchone()["n"]
        == 1
    )
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM tutor_exercise_attempts WHERE track_id=%s",
            (scope["track_id"],),
        ).fetchone()["n"]
        == 0
    )
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM tutor_mastery_evidence WHERE user_id=%s",
            (scope["user_id"],),
        ).fetchone()["n"]
        == 0
    )
    progress = conn.execute(
        "SELECT status,version FROM tutor_track_node_progress WHERE track_id=%s AND knowledge_key='python.variables'",
        (scope["track_id"],),
    ).fetchone()
    assert progress == {"status": "in_progress", "version": 2}


def test_lesson_start_retires_old_artifact_via_terminal_event_without_scoring():
    _require_dedicated_database()
    settings, scope, artifact_id, old_session_id = _materialized_knowledge_artifact()
    with connection() as conn:
        before = _artifact(conn, artifact_id)
        _, _, current = _start_and_open(conn, settings, scope)
        assert str(current["predecessor_session_id"]) == old_session_id
        _assert_retired(conn, before, _artifact(conn, artifact_id), scope, current)


def test_matching_current_open_reconciles_legacy_leak_exactly_once(monkeypatch):
    _require_dedicated_database()
    settings, scope, artifact_id, old_session_id = _materialized_knowledge_artifact()
    with connection() as conn:
        before = _artifact(conn, artifact_id)
        # Simulate the old application omitting only the invalidation hook;
        # normal owners/triggers remain enabled in the dedicated test database.
        with monkeypatch.context() as patch:
            patch.setattr(
                TeachingSessionRepository,
                "_supersede_predecessor_artifacts",
                lambda self, session: None,
            )
            repository, authority, current = _start_and_open(conn, settings, scope)
        assert _artifact(conn, artifact_id)["state"] == "active"
        assert (
            conn.execute(
                "SELECT status FROM tutor_teaching_sessions WHERE id=%s",
                (old_session_id,),
            ).fetchone()["status"]
            == "blocked"
        )
        reopened, created = repository.open_or_resume(
            authority=authority, mode=TeachingSessionMode.GUIDED
        )
        assert not created and reopened["id"] == current["id"]
        after = _artifact(conn, artifact_id)
        _assert_retired(conn, before, after, scope, current)
        event_count = conn.execute(
            "SELECT count(*) AS n FROM tutor_learning_artifact_events WHERE artifact_id=%s",
            (artifact_id,),
        ).fetchone()["n"]
        repository.open_or_resume(authority=authority, mode=TeachingSessionMode.GUIDED)
        assert _artifact(conn, artifact_id) == after
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM tutor_learning_artifact_events WHERE artifact_id=%s",
                (artifact_id,),
            ).fetchone()["n"]
            == event_count
        )


def test_open_does_not_retire_current_active_artifact():
    _require_dedicated_database()
    settings, scope, artifact_id, session_id = _materialized_knowledge_artifact()
    with connection() as conn:
        before = _artifact(conn, artifact_id)
        repository = TeachingSessionRepository(conn, settings=settings)
        authority = repository.resolve_authority(
            user_id=str(scope["user_id"]),
            track_id=str(scope["track_id"]),
            knowledge_key="python.variables",
        )
        current, created = repository.open_or_resume(
            authority=authority, mode=TeachingSessionMode.GUIDED
        )
        assert not created and str(current["id"]) == session_id
        assert _artifact(conn, artifact_id) == before


@pytest.mark.parametrize("change_presentation", [False, True])
def test_database_rejects_forged_historical_retirement(
    monkeypatch, change_presentation
):
    _require_dedicated_database()
    settings, scope, artifact_id, _ = _materialized_knowledge_artifact()
    with connection() as conn:
        with monkeypatch.context() as patch:
            patch.setattr(
                TeachingSessionRepository,
                "_supersede_predecessor_artifacts",
                lambda self, session: None,
            )
            _start_and_open(conn, settings, scope)
        before = _artifact(conn, artifact_id)
        with pytest.raises(CheckViolation):
            with conn.transaction():
                if change_presentation:
                    conn.execute(
                        "UPDATE tutor_learning_artifacts SET state='superseded',version=version+1,allowed_actions_json='[]'::jsonb,terminal_at=now(),presentation_hash=%s WHERE id=%s",
                        ("0" * 64, artifact_id),
                    )
                else:
                    conn.execute(
                        "UPDATE tutor_learning_artifacts SET state='superseded',version=version+1,allowed_actions_json='[]'::jsonb,terminal_at=now() WHERE id=%s",
                        (artifact_id,),
                    )
                conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
        assert _artifact(conn, artifact_id) == before
