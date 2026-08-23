from __future__ import annotations

from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.services.learning.contracts import LearningScope, LearningScopeKind, LearningTaskKind
from app.services.learning.track_repository import PostgresLearningTrackRepository
from app.services.tutor.persistence import PostgresTutorRepository
from learning_track_support import sample_plan


def database_available() -> bool:
    try:
        with psycopg.connect(get_settings().database_url, connect_timeout=2) as conn:
            conn.execute("SELECT 1")
        return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(not database_available(), reason="PostgreSQL is not available")


def create_teaching_scope(conn) -> dict[str, str | int]:  # type: ignore[no-untyped-def]
    suffix = uuid4().hex
    user = conn.execute("INSERT INTO users (display_name) VALUES (%s) RETURNING id", (f"Teaching {suffix[:8]}",)).fetchone()
    assert user is not None
    user_id = str(user["id"])
    tracks = PostgresLearningTrackRepository(conn)
    track_id = tracks.create_track(
        user_id=user_id, language_id="python", goal_text="Learn variables safely",
        target_level="beginner", plan=sample_plan(),
    )
    conversation_id = PostgresTutorRepository(conn).create_conversation(user_id=user_id)
    tracks.bind_conversation_scope(
        user_id=user_id, conversation_id=conversation_id,
        scope=LearningScope(
            scope_kind=LearningScopeKind.LEARNING_TRACK, learning_track_id=track_id,
            task_kind=LearningTaskKind.LESSON_TEACHING, knowledge_key="python.variables",
        ),
    )
    revision = conn.execute("SELECT revision_id FROM tutor_track_active_plans WHERE track_id=%s", (track_id,)).fetchone()
    assert revision is not None
    revision_id = str(revision["revision_id"])
    standard = conn.execute(
        """INSERT INTO tutor_lesson_documents (
             document_kind,knowledge_key,language_id,schema_version,content_standard_version,generator_version,
             policy_version,source_set_hash,title,coverage_keys_json,blocks_json,content_hash
           ) VALUES ('standard','python.variables','python','lesson_document_v1','programming_language_lesson_v1',
             %s,'teaching-test-v1',%s,'Variables','["python.variables"]'::jsonb,'[]'::jsonb,%s) RETURNING id""",
        (f"teaching-{suffix}", suffix.ljust(64, "0")[:64], ("a" + suffix).ljust(64, "0")[:64]),
    ).fetchone()
    assert standard is not None
    document = conn.execute(
        """INSERT INTO tutor_lesson_documents (
             document_kind,user_id,track_id,knowledge_key,language_id,active_plan_revision_id,standard_document_id,
             schema_version,content_standard_version,generator_version,policy_version,source_set_hash,profile_hash,
             title,coverage_keys_json,blocks_json,content_hash
           ) VALUES ('personalized',%s,%s,'python.variables','python',%s,%s,'lesson_document_v1',
             'programming_language_lesson_v1',%s,'teaching-test-v1',%s,%s,'Variables for learner',
             '["python.variables"]'::jsonb,'[]'::jsonb,%s) RETURNING id,content_hash""",
        (user_id, track_id, revision_id, standard["id"], f"teaching-{suffix}",
         ("b" + suffix).ljust(64, "0")[:64], ("c" + suffix).ljust(64, "0")[:64],
         ("d" + suffix).ljust(64, "0")[:64]),
    ).fetchone()
    assert document is not None
    assignment = conn.execute(
        """INSERT INTO tutor_lesson_assignments (
             user_id,track_id,knowledge_key,document_id,source_plan_revision_id,assignment_version,status,
             expected_progress_version,content_hash,activated_at
           ) VALUES (%s,%s,'python.variables',%s,%s,1,'active',1,%s,now()) RETURNING id""",
        (user_id, track_id, document["id"], revision_id, ("e" + suffix).ljust(64, "0")[:64]),
    ).fetchone()
    assert assignment is not None
    conn.commit()
    return {
        "user_id": user_id, "track_id": track_id, "conversation_id": conversation_id,
        "knowledge_key": "python.variables", "assignment_id": str(assignment["id"]),
        "document_id": str(document["id"]), "document_content_hash": str(document["content_hash"]),
        "track_version": 1, "progress_version": 1, "assignment_version": 1,
    }


def connection():  # type: ignore[no-untyped-def]
    bootstrap_database()
    return psycopg.connect(get_settings().database_url, row_factory=dict_row)
