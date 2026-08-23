from __future__ import annotations

import json
from uuid import uuid4

import pytest

from app.services.learning.teaching_contracts import TeachingControlStimulus, TeachingSessionMode
from app.services.learning.teaching_sessions import TeachingSessionService, TeachingSessionServiceError
from teaching_session_support import connection, create_teaching_scope, database_available

pytestmark = pytest.mark.skipif(not database_available(), reason="PostgreSQL is not available")


def test_open_resume_mode_cas_and_public_projection_are_safe() -> None:
    with connection() as conn:
        scope = create_teaching_scope(conn)
        service = TeachingSessionService(conn)
        opened = service.open(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), knowledge_key="python.variables",
            conversation_id=str(scope["conversation_id"]), expected_track_version=1,
            expected_progress_version=1, expected_assignment_version=1,
            mode=TeachingSessionMode.GUIDED, idempotency_key="teaching-open-1",
        )
        assert opened["created"] is True
        replay = service.open(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), knowledge_key="python.variables",
            conversation_id=str(scope["conversation_id"]), expected_track_version=1,
            expected_progress_version=1, expected_assignment_version=1,
            mode=TeachingSessionMode.GUIDED, idempotency_key="teaching-open-1",
        )
        assert replay["idempotent_replayed"] is True
        session = opened["teaching_session"]
        assert isinstance(session, dict)
        control = TeachingControlStimulus(
            control_key="switch_mode", client_action_id="teaching-mode-1",
            expected_session_version=1, expected_track_version=1,
            expected_progress_version=1, expected_assignment_version=1,
            safe_payload={"target_mode": "free_reading"},
        )
        changed = service.action(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]),
            session_id=str(session["session_id"]), control=control,
            target_mode=TeachingSessionMode.FREE_READING, admit_run=False,
            idempotency_key="teaching-mode-1",
        )
        current = changed["teaching_session"]
        assert isinstance(current, dict)
        assert current["mode"] == "free_reading"
        assert current["session_version"] == 2
        serialized = json.dumps(current, ensure_ascii=False)
        for protected in ("document_content_hash", "source_hash", "prompt", "reasoning", "hidden_tests", "command", "path"):
            assert protected not in serialized


def test_cross_user_and_stale_authority_fail_closed() -> None:
    with connection() as conn:
        scope = create_teaching_scope(conn)
        service = TeachingSessionService(conn)
        with pytest.raises(TeachingSessionServiceError) as stale:
            service.open(
                user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), knowledge_key="python.variables",
                conversation_id=str(scope["conversation_id"]), expected_track_version=99,
                expected_progress_version=1, expected_assignment_version=1,
                mode=TeachingSessionMode.GUIDED, idempotency_key="teaching-stale",
            )
        assert stale.value.code == "TEACHING_AUTHORITY_CONFLICT"
        other = conn.execute("INSERT INTO users (display_name) VALUES (%s) RETURNING id", (f"Other {uuid4().hex[:8]}",)).fetchone()
        assert other is not None
        conn.commit()
        with pytest.raises(TeachingSessionServiceError) as crossed:
            service.list_sessions(user_id=str(other["id"]), track_id=str(scope["track_id"]))
        assert crossed.value.code == "LEARNING_TRACK_NOT_FOUND"


def test_teaching_session_routes_parse_additive_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    import app.routes.teaching_sessions as teaching_routes
    from app.main import app

    monkeypatch.setattr(teaching_routes, "runtime_gate_error", lambda *, user_id: None)
    with connection() as conn:
        scope = create_teaching_scope(conn)
    with TestClient(app) as client:
        opened = client.post(
            f"/api/learning-tracks/{scope['track_id']}/teaching-sessions/python.variables/open",
            json={
                "user_id": scope["user_id"], "client_action_id": "route-open",
                "conversation_id": scope["conversation_id"], "expected_track_version": 1,
                "expected_progress_version": 1, "expected_assignment_version": 1, "mode": "guided",
            },
        )
        assert opened.status_code == 201
        body = opened.json()
        assert body["teaching_session"]["knowledge_key"] == "python.variables"
        listed = client.get(
            f"/api/learning-tracks/{scope['track_id']}/teaching-sessions",
            params={"user_id": scope["user_id"]},
        )
        assert listed.status_code == 200
        assert listed.json()["items"][0]["session_id"] == body["teaching_session"]["session_id"]


def test_teaching_authority_export_and_reset_are_complete_and_redacted() -> None:
    from app.services.repositories.local_user_data_repository import export_user_data, reset_user_data

    with connection() as conn:
        scope = create_teaching_scope(conn)
        TeachingSessionService(conn).open(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), knowledge_key="python.variables",
            conversation_id=str(scope["conversation_id"]), expected_track_version=1,
            expected_progress_version=1, expected_assignment_version=1,
            mode=TeachingSessionMode.GUIDED, idempotency_key="export-open",
        )
        exported = export_user_data(conn, str(scope["user_id"]))
        assert exported["summary"]["counts"]["teaching_sessions"] == 1
        assert len(exported["teaching_session_summaries"]) == 1
        assert len(exported["teaching_checkpoint_summaries"]) == 1
        teaching_export = json.dumps({
            "sessions": exported["teaching_session_summaries"],
            "checkpoints": exported["teaching_checkpoint_summaries"],
            "stimuli": exported["teaching_stimulus_summaries"],
            "run_scopes": exported["run_teaching_scope_summaries"],
        }, ensure_ascii=False)
        assert str(scope["document_content_hash"]) not in teaching_export
        assert "source_hash" not in teaching_export
        reset = reset_user_data(conn, str(scope["user_id"]))
        assert reset["summary"]["counts"]["teaching_sessions"] == 0
        assert reset["summary"]["counts"]["teaching_checkpoints"] == 0
