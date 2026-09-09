"""Admission-only regressions: no dispatcher/provider, isolated PostgreSQL only."""
from __future__ import annotations

from uuid import uuid4
import os

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.conninfo import conninfo_to_dict

from app.core.config import get_settings
from app.services.learning.contracts import LearningScope, LearningScopeKind, LearningTaskKind
from app.services.learning.teaching_contracts import TeachingSessionMode
from app.services.learning.teaching_sessions import (
    TeachingSessionConflict, TeachingSessionNotReady, TeachingSessionRepository, TeachingSessionService,
)
from app.services.tutor.public_api import TutorPublicApiError, TutorPublicService


@pytest.fixture
def admission_conn():  # type: ignore[no-untyped-def]
    settings = get_settings()
    # Require an explicitly selected disposable database, not a session-specific name.
    target = conninfo_to_dict(settings.database_url)
    if not target.get("dbname", "").startswith(("aearn_repair_", "aearn_test_", "test_")):
        pytest.skip("requires an explicitly selected disposable test database")
    assert os.environ.get("DATABASE_URL") == settings.database_url
    assert settings.llm_type == "disabled"
    assert target["host"] in {"localhost", "127.0.0.1"} and target["port"] == "5432"
    from app.db.bootstrap import bootstrap_database
    bootstrap_database()
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        assert conn.execute("SELECT current_database() AS name").fetchone()["name"] == target["dbname"]
        yield conn
        conn.rollback()


def _fixture(conn):  # type: ignore[no-untyped-def]
    # Import only after the fixture has verified the exact database identity.
    from tests.support.teaching_session_support import create_teaching_scope
    return create_teaching_scope(conn)


def _scope(data, *, task=LearningTaskKind.LESSON_TEACHING, knowledge="python.variables"):  # type: ignore[no-untyped-def]
    return LearningScope(
        scope_kind=LearningScopeKind.LEARNING_TRACK,
        learning_track_id=str(data["track_id"]), task_kind=task, knowledge_key=knowledge,
    )


def _counts(conn):  # type: ignore[no-untyped-def]
    return tuple(
        conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]
        for table in (
            "tutor_messages", "tutor_runs", "tutor_interactive_dispatch_jobs",
            "tutor_run_teaching_scopes", "tutor_run_stimulus_events",
            "tutor_api_idempotency_records", "tutor_conversations",
        )
    )


def _accept(service, data, *, scope=None, key="admission", first=False):  # type: ignore[no-untyped-def]
    kwargs = dict(user_id=str(data["user_id"]), content="Explain variables", idempotency_key=key,
                  learning_scope=scope if scope is not None else _scope(data))
    if first:
        return service.accept_first_turn(**kwargs)
    return service.accept_conversation_input(conversation_id=str(data["conversation_id"]), **kwargs)


@pytest.mark.parametrize("first", [False, True])
def test_missing_session_rejects_before_admission(admission_conn, monkeypatch, first):  # type: ignore[no-untyped-def]
    data = _fixture(admission_conn)
    service = TutorPublicService(admission_conn)
    def forbidden(**kwargs):  # type: ignore[no-untyped-def]
        pytest.fail("durable admission must not be reached")
    monkeypatch.setattr(service._queue, "accept_or_queue", forbidden)
    monkeypatch.setattr(service._repository, "create_first_interactive_turn", forbidden)
    before = _counts(admission_conn)
    with pytest.raises(TutorPublicApiError) as caught:
        _accept(service, data, first=first)
    error = caught.value
    assert (error.code, error.status_code, error.recoverable, error.details) == (
        "TEACHING_NOT_READY", 409, True, {},
    )
    assert str(data["user_id"]) not in error.message
    assert _counts(admission_conn) == before


def _open(conn, data):  # type: ignore[no-untyped-def]
    return TeachingSessionService(conn).open(
        user_id=str(data["user_id"]), track_id=str(data["track_id"]), knowledge_key="python.variables",
        conversation_id=str(data["conversation_id"]), expected_track_version=1,
        expected_progress_version=1, expected_assignment_version=1,
        mode=TeachingSessionMode.FREE_READING, idempotency_key="admission-open",
    )


def test_prepared_session_admits_one_bound_stimulus_without_provider(admission_conn, monkeypatch):  # type: ignore[no-untyped-def]
    data = _fixture(admission_conn)
    opened = _open(admission_conn, data)
    assert opened["pending_run"] is None
    service = TutorPublicService(admission_conn)
    result = _accept(service, data)
    assert result["teaching_scope"]["session_id"]
    row = admission_conn.execute(
        "SELECT count(*) AS n FROM tutor_run_teaching_scopes WHERE run_id=%s", (result["run_id"],),
    ).fetchone()
    assert row["n"] == 1
    assert admission_conn.execute(
        "SELECT count(*) AS n FROM tutor_run_stimulus_events WHERE run_id=%s", (result["run_id"],),
    ).fetchone()["n"] == 1
    # Replay must not require the session to still be current.
    def unavailable(**kwargs):  # type: ignore[no-untyped-def]
        raise TeachingSessionNotReady("unavailable after original acceptance")
    monkeypatch.setattr(service._teaching_sessions, "prepare_learner_message_admission", unavailable)
    before = _counts(admission_conn)
    replay = _accept(service, data)
    assert replay["idempotent_replayed"] is True
    assert replay["run_id"] == result["run_id"]
    assert _counts(admission_conn) == before


@pytest.mark.parametrize("kind", ["general", "track_qa", "review", "feedback"])
def test_nonmanaged_paths_do_not_require_session(admission_conn, monkeypatch, kind):  # type: ignore[no-untyped-def]
    data = _fixture(admission_conn)
    service = TutorPublicService(admission_conn)
    def forbidden(**kwargs):  # type: ignore[no-untyped-def]
        pytest.fail("nonmanaged path must not resolve teaching authority")
    monkeypatch.setattr(service._teaching_sessions, "prepare_learner_message_admission", forbidden)
    if kind == "general":
        result = _accept(service, data, scope=LearningScope(), first=True)
    else:
        task = {"track_qa": LearningTaskKind.LESSON_TEACHING,
                "review": LearningTaskKind.REVIEW_COACHING,
                "feedback": LearningTaskKind.EXERCISE_FEEDBACK}[kind]
        result = _accept(service, data, scope=_scope(data, task=task, knowledge=None if kind == "track_qa" else "python.variables"))
    assert result["run_id"]
    assert "teaching_scope" not in result


@pytest.mark.parametrize("damage", ["blocked", "completed", "authority", "checkpoint"])
def test_unprepared_authority_fails_closed(admission_conn, monkeypatch, damage):  # type: ignore[no-untyped-def]
    data = _fixture(admission_conn)
    _open(admission_conn, data)
    service = TutorPublicService(admission_conn)
    repository = service._teaching_sessions
    original = repository.read_current
    def damaged_session(**kwargs):  # type: ignore[no-untyped-def]
        session = dict(original(**kwargs))
        if damage in {"blocked", "completed"}:
            session["status"] = damage
        elif damage == "authority":
            session["track_version"] = int(session["track_version"]) + 1
        else:
            session["current_checkpoint_id"] = str(uuid4())
        return session
    # The DB itself forbids corrupting immutable authority. Inject a stale read
    # instead of weakening triggers or manufacturing invalid persisted rows.
    monkeypatch.setattr(repository, "read_current", damaged_session)
    before = _counts(admission_conn)
    with pytest.raises(TutorPublicApiError, match="教学尚未准备就绪") as caught:
        _accept(service, data)
    assert caught.value.code == "TEACHING_NOT_READY"
    assert _counts(admission_conn) == before


def test_binding_missing_managed_scope_is_not_silent(admission_conn):  # type: ignore[no-untyped-def]
    data = _fixture(admission_conn)
    with pytest.raises(TeachingSessionNotReady):
        TeachingSessionRepository(admission_conn).bind_learner_message_run(
            user_id=str(data["user_id"]), run_id=str(uuid4()), conversation_id=str(data["conversation_id"]),
            track_id=str(data["track_id"]), knowledge_key="python.variables", message_id=str(uuid4()), input_revision=1,
        )


def test_historical_unbound_request_replay_and_history_remain_readable(admission_conn, monkeypatch):  # type: ignore[no-untyped-def]
    data = _fixture(admission_conn)
    service = TutorPublicService(admission_conn)
    # Reproduce the old admission ONLY for the fixture; restore both real fences.
    with monkeypatch.context() as legacy:
        legacy.setattr(service, "_prepare_teaching_admission", lambda **kwargs: None)
        legacy.setattr(service, "_bind_teaching_scope", lambda **kwargs: None)
        result = _accept(service, data, key="historical-unbound")
    before = _counts(admission_conn)
    replay = _accept(service, data, key="historical-unbound")
    assert replay["idempotent_replayed"] is True
    assert replay["run_id"] == result["run_id"]
    assert "teaching_scope" not in replay
    assert service.read_run(user_id=str(data["user_id"]), run_id=str(result["run_id"]))
    assert service.read_conversation_snapshot(user_id=str(data["user_id"]), conversation_id=str(data["conversation_id"]), limit=20, cursor=None)
    assert _counts(admission_conn) == before
    with pytest.raises(TutorPublicApiError) as caught:
        _accept(service, data, key="fresh-after-historical")
    assert caught.value.code == "TEACHING_NOT_READY"
    assert _counts(admission_conn) == before


@pytest.mark.parametrize("state", ["advanced", "closed"])
def test_binding_replay_uses_frozen_scope_not_current_session(admission_conn, monkeypatch, state):  # type: ignore[no-untyped-def]
    data = _fixture(admission_conn)
    _open(admission_conn, data)
    service = TutorPublicService(admission_conn)
    result = _accept(service, data)
    repository = service._teaching_sessions
    original = repository.read_current
    def changed_current(**kwargs):  # type: ignore[no-untyped-def]
        session = dict(original(**kwargs))
        if state == "closed":
            session["status"] = "completed"
        else:
            session["version"] = int(session["version"]) + 1
            session["current_checkpoint_id"] = str(uuid4())
        return session
    monkeypatch.setattr(repository, "read_current", changed_current)
    before = _counts(admission_conn)
    kwargs = dict(
        user_id=str(data["user_id"]), run_id=str(result["run_id"]),
        conversation_id=str(data["conversation_id"]), track_id=str(data["track_id"]),
        knowledge_key="python.variables", message_id=str(result["message_id"]),
        input_revision=int(result["input_revision"]),
    )
    assert repository.bind_learner_message_run(**kwargs) == result["teaching_scope"]
    with pytest.raises(TeachingSessionConflict):
        repository.bind_learner_message_run(**{**kwargs, "message_id": str(uuid4())})
    with pytest.raises(TeachingSessionConflict):
        repository.bind_learner_message_run(**{**kwargs, "input_revision": kwargs["input_revision"] + 1})
    assert _counts(admission_conn) == before


def test_prepared_session_does_not_bind_a_new_first_turn_conversation(admission_conn, monkeypatch):  # type: ignore[no-untyped-def]
    data = _fixture(admission_conn)
    _open(admission_conn, data)
    service = TutorPublicService(admission_conn)
    def forbidden(**kwargs):  # type: ignore[no-untyped-def]
        pytest.fail("must not create an unrelated conversation for a prepared session")
    monkeypatch.setattr(service._repository, "create_first_interactive_turn", forbidden)
    before = _counts(admission_conn)
    with pytest.raises(TutorPublicApiError) as caught:
        _accept(service, data, first=True)
    assert caught.value.code == "TEACHING_NOT_READY"
    assert _counts(admission_conn) == before


def test_planning_preflight_is_unaffected(monkeypatch):  # type: ignore[no-untyped-def]
    service = object.__new__(TutorPublicService)
    # No repository exists here: unrelated planning must not touch it.
    service._prepare_teaching_admission(
        user_id=str(uuid4()), conversation_id=None,
        learning_scope=LearningScope(scope_kind=LearningScopeKind.PLAN_DRAFTING),
    )
