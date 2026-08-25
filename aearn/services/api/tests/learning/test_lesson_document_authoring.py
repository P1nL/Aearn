from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.services.grounding.grounding_index_repository import run_and_persist_fixture_grounding_reindex
from app.services.learning.lesson_authoring import (
    LessonAuthoringFailure,
    LessonAuthoringRequest,
    LessonAuthoringResponse,
    dispatch_lesson_authoring_run,
)
from app.services.learning.lesson_repository import PostgresLessonDocumentRepository
from app.services.learning.lesson_service import LessonDocumentService
from app.services.learning.track_repository import PostgresLearningTrackRepository
from app.services.llm.contracts import LLMUsage
from tests.support.learning_track_support import sample_plan
from tests.support.lesson_document_support import author_candidate_payload


def _database_available() -> bool:
    try:
        with psycopg.connect(get_settings().database_url, connect_timeout=2) as conn:
            conn.execute("select 1")
        return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(not _database_available(), reason="PostgreSQL is required for Lesson authoring tests.")


class FakeLessonAuthor:
    def __init__(self, *, invalid: bool = False, unavailable: bool = False, personalized_title: str = "Python 变量：个性化") -> None:
        self.invalid = invalid
        self.unavailable = unavailable
        self.personalized_title = personalized_title
        self.requests: list[LessonAuthoringRequest] = []

    def author(self, request: LessonAuthoringRequest) -> LessonAuthoringResponse:
        self.requests.append(request)
        if self.unavailable:
            raise LessonAuthoringFailure("LESSON_DOCUMENT_GENERATION_UNAVAILABLE", "课程生成服务当前不可用。", outcome="unavailable")
        candidate = author_candidate_payload(
            personalized=request.document_kind == "personalized",
            title=self.personalized_title if request.document_kind == "personalized" else "Python 变量",
        )
        if self.invalid:
            candidate["unknown"] = True
        return LessonAuthoringResponse(
            candidate=candidate,
            provider="fake-primary",
            model="fake-lesson-author",
            protocol="responses",
            usage=LLMUsage(input_tokens=120, output_tokens=80, total_tokens=200),
        )


@pytest.fixture()
def authoring_scope():
    bootstrap_database()
    with psycopg.connect(get_settings().database_url, row_factory=dict_row) as conn:
        run_and_persist_fixture_grounding_reindex(conn)
        user = conn.execute("INSERT INTO users (display_name) VALUES (%s) RETURNING id", (f"Lesson Author {uuid4().hex[:10]}",)).fetchone()
        assert user is not None
        user_id = str(user["id"])
        track_id = PostgresLearningTrackRepository(conn).create_track(
            user_id=user_id, language_id="python", goal_text="Learn Python variables",
            target_level="beginner", plan=sample_plan(),
        )
        service = LessonDocumentService(conn)
        prepared = service.prepare(
            user_id=user_id, track_id=track_id, knowledge_key="python.variables",
            expected_track_version=1, expected_progress_version=1,
            idempotency_key=f"prepare-{uuid4()}",
        )
        conn.commit()
        run = prepared["authoring_run"]
        assert isinstance(run, dict)
        yield conn, user_id, track_id, str(run["run_id"])
        conn.rollback()


def test_dispatch_generates_standard_personalized_assignment_and_safe_attempts(authoring_scope) -> None:
    conn, user_id, track_id, run_id = authoring_scope
    fake = FakeLessonAuthor()
    dispatch_lesson_authoring_run(run_id, author=fake, now=lambda: datetime(2026, 8, 11, tzinfo=UTC))

    state = PostgresLessonDocumentRepository(conn).read_lesson_state(
        user_id=user_id, track_id=track_id, knowledge_key="python.variables",
    )
    assert state["assignment"] is not None
    assert state["document"] is not None
    assert len(fake.requests) == 2
    assert fake.requests[0].evidence[0].handle == "S1"
    assert "https://" not in fake.requests[0].evidence[0].evidence_excerpt

    receipts = conn.execute(
        "SELECT attempt_index, provider, model, protocol, outcome, usage_available, input_tokens, output_tokens FROM tutor_lesson_authoring_attempt_receipts WHERE run_id = %s ORDER BY attempt_index",
        (run_id,),
    ).fetchall()
    assert [row["attempt_index"] for row in receipts] == [1, 2]
    assert all(row["provider"] == "fake-primary" and row["outcome"] == "success" for row in receipts)
    assert all(row["usage_available"] is True for row in receipts)


def test_invalid_or_unavailable_author_fails_closed_without_partial_document(authoring_scope) -> None:
    conn, user_id, track_id, run_id = authoring_scope
    dispatch_lesson_authoring_run(run_id, author=FakeLessonAuthor(invalid=True))

    run = conn.execute("SELECT state, failure_code FROM tutor_lesson_authoring_runs WHERE id = %s", (run_id,)).fetchone()
    assert run is not None
    assert run["state"] == "failed"
    assert run["failure_code"] == "LESSON_DOCUMENT_INVALID"
    assert conn.execute("SELECT count(*)::int AS count FROM tutor_lesson_documents WHERE user_id = %s", (user_id,)).fetchone()["count"] == 0
    assert conn.execute("SELECT count(*)::int AS count FROM tutor_lesson_assignments WHERE track_id = %s", (track_id,)).fetchone()["count"] == 0
