from __future__ import annotations

import pytest

from app.agents.harness.context_builder import TutorContextBuilder, TutorContextBuilderConfig
from app.agents.harness.contracts import TutorContextError, TutorContextSection
from app.services.learning.teaching_contracts import TeachingSessionMode
from app.services.learning.teaching_sessions import TeachingSessionService
from app.services.tutor.interactive import PostgresTutorContextLoader, PostgresTutorLearningContextLoader
from app.services.tutor.learner_state import TutorLearnerStateRepository
from app.services.tutor.persistence import PostgresTutorRepository
from teaching_session_support import connection, create_teaching_scope, database_available

pytestmark = pytest.mark.skipif(not database_available(), reason="PostgreSQL is not available")


def test_required_teaching_context_contains_exact_session_stimulus_and_handles() -> None:
    with connection() as conn:
        scope = create_teaching_scope(conn)
        opened = TeachingSessionService(conn).open(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), knowledge_key="python.variables",
            conversation_id=str(scope["conversation_id"]), expected_track_version=1,
            expected_progress_version=1, expected_assignment_version=1,
            mode=TeachingSessionMode.GUIDED, idempotency_key="teaching-context-open",
        )
        pending = opened["pending_run"]
        assert isinstance(pending, dict)
        run_id = str(pending["run_id"])
        snapshot = PostgresTutorRepository(conn).load_snapshot(user_id=str(scope["user_id"]), run_id=run_id)
        assert snapshot is not None and snapshot.input_revision == 0
        loader = PostgresTutorLearningContextLoader(
            conn=conn,
            base_loader=PostgresTutorContextLoader(
                conn=conn, learner_state=TutorLearnerStateRepository(conn),
            ),
        )
        context_input = loader.load_context(snapshot, input_revision=0)
        assert context_input.current_input is None
        assert len(context_input.teaching_session) == 1
        teaching = context_input.teaching_session[0].content
        assert isinstance(teaching, dict)
        assert teaching["stimulus"]["kind"] == "teaching_control"
        assert teaching["session"]["session_id"] == opened["teaching_session"]["session_id"]
        assert "knowledge:python.variables" in teaching["allowed_source_handles"]
        selection = TutorContextBuilder(
            config=TutorContextBuilderConfig(max_source_characters=4000),
        ).build(context_input, token_budget=5000)
        section = next(item for item in selection.checkpoint_metadata.sections if item.section is TutorContextSection.TEACHING_SESSION)
        assert section.selected_count == 1 and section.skipped_count == 0


def test_required_teaching_context_fails_closed_before_provider_when_unrepresentable() -> None:
    with connection() as conn:
        scope = create_teaching_scope(conn)
        opened = TeachingSessionService(conn).open(
            user_id=str(scope["user_id"]), track_id=str(scope["track_id"]), knowledge_key="python.variables",
            conversation_id=str(scope["conversation_id"]), expected_track_version=1,
            expected_progress_version=1, expected_assignment_version=1,
            mode=TeachingSessionMode.GUIDED, idempotency_key="teaching-context-budget",
        )
        pending = opened["pending_run"]
        assert isinstance(pending, dict)
        snapshot = PostgresTutorRepository(conn).load_snapshot(
            user_id=str(scope["user_id"]), run_id=str(pending["run_id"]),
        )
        assert snapshot is not None
        loader = PostgresTutorLearningContextLoader(
            conn=conn,
            base_loader=PostgresTutorContextLoader(conn=conn, learner_state=TutorLearnerStateRepository(conn)),
        )
        context_input = loader.load_context(snapshot, input_revision=0)
        with pytest.raises(TutorContextError) as error:
            TutorContextBuilder(
                config=TutorContextBuilderConfig(max_source_characters=80),
            ).build(context_input, token_budget=40)
        assert error.value.safe_code == "TUTOR_TEACHING_SESSION_UNREPRESENTABLE"
