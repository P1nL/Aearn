from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.services.learning.contracts import ExecutionComposition, LearningScope, LearningScopeKind, LearningTaskKind
from app.services.learning.lesson_service import LessonDocumentService
from app.services.learning.practice.service import ExerciseGateService
from app.services.learning.teaching_contracts import (
    TeachingCheckpointState,
    TeachingSessionMode,
    TeachingStepDecision,
)
from app.services.learning.teaching_events import TeachingDomainEventAdapter
from app.services.learning.teaching_loop import build_teaching_action_shelf, reduce_teaching_checkpoint
from app.services.learning.teaching_sessions import (
    TeachingSessionConflict,
    TeachingSessionRepository,
    TeachingSessionService,
)
from app.services.repositories.local_user_data_repository import reset_user_data
from app.services.tutor.persistence import PostgresTutorRepository
from tests.support.teaching_session_support import database_available
from tests.learning.test_exercise_gate_repository import _success
from tests.learning.test_lesson_document_repository import _publish

pytest_plugins = ("tests.learning.test_lesson_document_repository",)
pytestmark = pytest.mark.skipif(not database_available(), reason="PostgreSQL is not available")


def test_gate_completion_admits_exactly_one_progress_turn_and_frozen_summary(lesson_repo) -> None:  # type: ignore[no-untyped-def]
    conn, lesson_repository, user_id, track_id, snapshot = lesson_repo
    published = _publish(conn, lesson_repository, user_id, track_id, snapshot, action="initial")
    started = lesson_repository.start_assignment(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        assignment_id=published.assignment_id,
        expected_assignment_version=1,
        expected_progress_version=1,
        now=datetime(2026, 8, 23, 1, tzinfo=UTC),
    )
    conversation_id = PostgresTutorRepository(conn).create_conversation(user_id=user_id)
    from app.services.learning.track_repository import PostgresLearningTrackRepository

    PostgresLearningTrackRepository(conn).bind_conversation_scope(
        user_id=user_id,
        conversation_id=conversation_id,
        scope=LearningScope(
            scope_kind=LearningScopeKind.LEARNING_TRACK,
            learning_track_id=track_id,
            task_kind=LearningTaskKind.LESSON_TEACHING,
            knowledge_key="python.variables",
        ),
    )
    opened = TeachingSessionService(conn).open(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        conversation_id=conversation_id,
        expected_track_version=1,
        expected_progress_version=int(started["progress_version"]),
        expected_assignment_version=1,
        mode=TeachingSessionMode.FREE_READING,
        idempotency_key=f"adaptive-open-{uuid4()}",
    )
    original_session_id = str(opened["teaching_session"]["session_id"])

    service = ExerciseGateService(
        conn,
        composition=ExecutionComposition.DEVELOPMENT,
        local_runner_available=True,
        local_runner=_success,
    )
    prepared = service.prepare_gate(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        gate_key="python.variables.basic",
        expected_track_version=1,
        expected_progress_version=int(started["progress_version"]),
        idempotency_key=f"adaptive-prepare-{uuid4()}",
    )
    result = service.attempt_gate(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        gate_key="python.variables.basic",
        attempt_type="submit",
        submission="value = 3\nprint(value)",
        expected_track_version=1,
        expected_progress_version=int(started["progress_version"]),
        expected_assignment_version=1,
        expected_gate_version=int(prepared["gate"]["gate_version"]),
        idempotency_key=f"adaptive-submit-{uuid4()}",
    )
    assert result["route_changed"] is True
    event = conn.execute(
        """SELECT stimuli.*, scopes.run_id, scopes.teaching_session_id
        FROM tutor_run_stimulus_events AS stimuli
        JOIN tutor_run_teaching_scopes AS scopes ON scopes.stimulus_id = stimuli.id
        WHERE stimuli.user_id = %s AND stimuli.stimulus_kind = 'domain_event'""",
        (user_id,),
    ).fetchone()
    assert event is not None
    assert event["domain_event_kind"] == "progress_changed"
    assert event["source_id"] == "progress:python.variables"
    assert event["message_id"] is None and event["control_key"] is None
    successor_id = str(event["teaching_session_id"])
    assert successor_id != original_session_id

    repository = TeachingSessionRepository(conn)
    context = repository.teaching_context(user_id=user_id, run_id=str(event["run_id"]))
    assert context is not None
    assert context["structured_summary"]["schema_version"] == "teaching_session_summary_v1"
    assert context["structured_summary"]["source_checkpoint_hash"]
    assert context["related_historical_summaries"][0]["teaching_session_id"] == original_session_id
    assert "value = 3" not in json.dumps(context, ensure_ascii=False)

    replay = TeachingDomainEventAdapter(conn).admit_progress_changed(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        source_version=int(event["source_version"]),
    )
    assert replay["event_status"] == "replayed"
    assert replay["run_id"] == str(event["run_id"])
    stale = TeachingDomainEventAdapter(conn).admit_progress_changed(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        source_version=int(event["source_version"]) - 1,
    )
    assert stale == {
        "event_status": "ignored",
        "code": "domain_event_stale",
        "idempotent_replayed": False,
    }
    assert conn.execute(
        "SELECT count(*) AS count FROM tutor_run_stimulus_events WHERE user_id=%s AND stimulus_kind='domain_event'",
        (user_id,),
    ).fetchone()["count"] == 1
    conn.rollback()


def test_assignment_migration_refreshes_authority_and_replays_exact_event(lesson_repo) -> None:  # type: ignore[no-untyped-def]
    conn, lesson_repository, user_id, track_id, snapshot = lesson_repo
    first = _publish(conn, lesson_repository, user_id, track_id, snapshot, action="initial")
    started = lesson_repository.start_assignment(
        user_id=user_id, track_id=track_id, knowledge_key="python.variables",
        assignment_id=first.assignment_id, expected_assignment_version=1,
        expected_progress_version=1, now=datetime(2026, 8, 23, 2, tzinfo=UTC),
    )
    conn.commit()
    proposed = _publish(
        conn,
        lesson_repository,
        user_id,
        track_id,
        snapshot,
        action="refresh",
        personalized_title="Python 变量：迁移版",
    )
    assert first.assignment_status == "active" and proposed.assignment_status == "proposed"
    conversation_id = PostgresTutorRepository(conn).create_conversation(user_id=user_id)
    from app.services.learning.track_repository import PostgresLearningTrackRepository

    PostgresLearningTrackRepository(conn).bind_conversation_scope(
        user_id=user_id,
        conversation_id=conversation_id,
        scope=LearningScope(
            scope_kind=LearningScopeKind.LEARNING_TRACK,
            learning_track_id=track_id,
            task_kind=LearningTaskKind.LESSON_TEACHING,
            knowledge_key="python.variables",
        ),
    )
    opened = TeachingSessionService(conn).open(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        conversation_id=conversation_id,
        expected_track_version=1,
        expected_progress_version=int(started["progress_version"]),
        expected_assignment_version=1,
        mode=TeachingSessionMode.FREE_READING,
        idempotency_key=f"assignment-open-{uuid4()}",
    )
    original_session_id = str(opened["teaching_session"]["session_id"])
    migrated = LessonDocumentService(conn).activate_migration(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        assignment_id=proposed.assignment_id,
        expected_assignment_version=2,
        idempotency_key=f"assignment-migrate-{uuid4()}",
    )
    assert migrated["assignment"]["assignment_id"] == proposed.assignment_id
    event = conn.execute(
        """SELECT stimuli.*, scopes.run_id, scopes.teaching_session_id
        FROM tutor_run_stimulus_events AS stimuli
        JOIN tutor_run_teaching_scopes AS scopes ON scopes.stimulus_id=stimuli.id
        WHERE stimuli.user_id=%s AND stimuli.domain_event_kind='assignment_changed'""",
        (user_id,),
    ).fetchone()
    assert event is not None
    assert str(event["source_id"]) == proposed.assignment_id
    assert int(event["source_version"]) == 2
    assert str(event["teaching_session_id"]) != original_session_id
    replay = TeachingDomainEventAdapter(conn).admit_assignment_changed(
        user_id=user_id,
        assignment_id=proposed.assignment_id,
    )
    assert replay["event_status"] == "replayed"
    assert replay["run_id"] == str(event["run_id"])
    assert conn.execute(
        "SELECT count(*) AS count FROM tutor_run_stimulus_events WHERE user_id=%s AND domain_event_kind='assignment_changed'",
        (user_id,),
    ).fetchone()["count"] == 1
    conn.rollback()


def test_structured_summary_detects_stale_checkpoint_source() -> None:
    from tests.support.teaching_session_support import connection, create_teaching_scope

    with connection() as conn:
        scope = create_teaching_scope(conn)
        opened = TeachingSessionService(conn).open(
            user_id=str(scope["user_id"]),
            track_id=str(scope["track_id"]),
            knowledge_key="python.variables",
            conversation_id=str(scope["conversation_id"]),
            expected_track_version=1,
            expected_progress_version=1,
            expected_assignment_version=1,
            mode=TeachingSessionMode.FREE_READING,
            idempotency_key=f"summary-open-{uuid4()}",
        )
        session = TeachingSessionRepository(conn).read_by_id(
            user_id=str(scope["user_id"]),
            track_id=str(scope["track_id"]),
            session_id=str(opened["teaching_session"]["session_id"]),
        )
        repository = TeachingSessionRepository(conn)
        checkpoint = dict(repository.current_checkpoint(
            session_id=str(session["id"]), user_id=str(scope["user_id"]),
        ))
        summary = repository.structured_summary(session=session, checkpoint=checkpoint)
        assert summary["objective"]["objective_id"] == "knowledge:python.variables"
        assert summary["authority_snapshot_hash"]
        checkpoint["source_hash"] = "0" * 64
        with pytest.raises(TeachingSessionConflict, match="source hash is stale"):
            repository.structured_summary(session=session, checkpoint=checkpoint)
        reset_user_data(conn, str(scope["user_id"]))
        conn.commit()


def test_closed_teaching_paths_preserve_parent_and_require_explicit_next() -> None:
    state = TeachingCheckpointState.model_validate({
        "objective": {
            "objective_id": "knowledge:python.variables",
            "summary": "Python 变量",
            "source_handles": ["knowledge:python.variables"],
        },
        "active_focus": {
            "focus_id": "knowledge:python.variables",
            "focus_kind": "knowledge",
            "summary": "Python 变量",
            "source_handles": ["knowledge:python.variables"],
        },
        "pause_reason": "soft_pause",
    })
    question = reduce_teaching_checkpoint(
        state=state,
        step=TeachingStepDecision(
            action="answer_question",
            objective_id="knowledge:python.variables",
            focus_id="question:assignment-vs-binding",
            source_handles=("knowledge:python.variables",),
            public_message="先回答赋值与绑定的区别，然后停下来。",
            focus_resolution="push_child",
            pause_kind="soft_pause",
        ),
        mode=TeachingSessionMode.GUIDED,
        stimulus_id="stimulus:question",
        source_message_id=str(uuid4()),
    )
    assert question.active_focus is not None
    assert question.active_focus.focus_id == "question:assignment-vs-binding"
    assert question.suspended_focuses[0].focus_id == "knowledge:python.variables"
    assert len(question.unresolved_questions) == 1

    resumed = reduce_teaching_checkpoint(
        state=question,
        step=TeachingStepDecision(
            action="explain_concept",
            objective_id="knowledge:python.variables",
            focus_id="knowledge:python.variables",
            source_handles=("knowledge:python.variables",),
            public_message="问题已处理，显式返回变量主线并停下来。",
            focus_resolution="resolve_and_resume_parent",
            pause_kind="soft_pause",
        ),
        mode=TeachingSessionMode.GUIDED,
        stimulus_id="stimulus:return",
        source_message_id=None,
    )
    assert resumed.active_focus is not None
    assert resumed.active_focus.focus_id == "knowledge:python.variables"
    assert resumed.suspended_focuses == () and resumed.unresolved_questions == ()

    completion = resumed.model_copy(update={
        "pause_reason": "completion_pause",
        "recommended_action_key": "enter_next_knowledge",
    })
    no_candidate = build_teaching_action_shelf(
        session_id=str(uuid4()),
        session_version=3,
        checkpoint_id=str(uuid4()),
        mode=TeachingSessionMode.GUIDED,
        state=completion,
        track_version=1,
        progress_version=3,
        assignment_version=1,
        runtime_active=False,
        blocking_request=False,
        progress_status="completed",
        next_knowledge_key=None,
    )
    assert no_candidate.state == "completion" and no_candidate.primary_action is None
    candidate = build_teaching_action_shelf(
        session_id=str(uuid4()),
        session_version=3,
        checkpoint_id=str(uuid4()),
        mode=TeachingSessionMode.GUIDED,
        state=completion,
        track_version=1,
        progress_version=3,
        assignment_version=1,
        runtime_active=False,
        blocking_request=False,
        progress_status="completed",
        next_knowledge_key="python.functions",
    )
    assert candidate.primary_action is not None
    assert candidate.primary_action.key == "enter_next_knowledge"
    assert candidate.primary_action.target_id == "python.functions"
