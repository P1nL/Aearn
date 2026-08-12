from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.services.grounding.grounding_index_repository import replace_grounding_chunks
from app.services.grounding.grounding_processing import GroundingChunk
from app.services.learning.lesson_contracts import calculate_lesson_impact, canonical_source_set_hash
from app.services.learning.lesson_repository import PostgresLessonDocumentRepository
from app.services.learning.track_repository import PostgresLearningTrackRepository
from app.services.repositories.local_user_data_repository import export_user_data, reset_user_data
from app.services.tutor.cutover import HarnessCutoverService
from learning_track_support import sample_plan
from lesson_document_support import sample_lesson_document, sample_source_snapshot


def _database_available() -> bool:
    try:
        with psycopg.connect(get_settings().database_url, connect_timeout=2) as conn:
            conn.execute("select 1")
        return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(
    not _database_available(),
    reason="PostgreSQL is not available; run aearn infra compose for Lesson repository tests.",
)


@pytest.fixture()
def lesson_repo():
    bootstrap_database()
    with psycopg.connect(get_settings().database_url, row_factory=dict_row) as conn:
        suffix = uuid4().hex[:12]
        user = conn.execute("INSERT INTO users (display_name) VALUES (%s) RETURNING id", (f"Lesson Repo {suffix}",)).fetchone()
        assert user is not None
        user_id = str(user["id"])
        track_id = PostgresLearningTrackRepository(conn).create_track(
            user_id=user_id,
            language_id="python",
            goal_text="Learn Python variables for automation",
            target_level="beginner",
            plan=sample_plan(),
        )
        snapshot = sample_source_snapshot()
        replace_grounding_chunks(
            conn,
            (
                GroundingChunk(
                    chunk_id=snapshot.grounding_chunk_id,
                    source_id=snapshot.source_id,
                    language_id="python",
                    title="Variables",
                    section_path=snapshot.section_path,
                    canonical_url=snapshot.canonical_url,
                    source_type=snapshot.source_type,
                    source_trust_tier=snapshot.trust_tier,
                    fetched_at=snapshot.fetched_at,
                    content_hash=snapshot.chunk_content_hash,
                    text=snapshot.evidence_excerpt,
                    topic_tags=("basics",),
                    source_version_label=snapshot.source_version_label,
                    source_version_kind=snapshot.source_version_kind,
                    document_content_hash=snapshot.document_content_hash,
                ),
            ),
            source_ids=(snapshot.source_id,),
        )
        conn.commit()
        try:
            yield conn, PostgresLessonDocumentRepository(conn), user_id, track_id, snapshot
        finally:
            conn.rollback()
            with conn.transaction():
                conn.execute("SELECT set_config('aearn.learning_track_purge_user_id', %s, true)", (user_id,))
                conn.execute("SET CONSTRAINTS ALL DEFERRED")
                conn.execute("DELETE FROM tutor_lesson_authoring_attempt_receipts WHERE user_id = %s", (user_id,))
                conn.execute("DELETE FROM tutor_lesson_authoring_runs WHERE user_id = %s", (user_id,))
                conn.execute("DELETE FROM tutor_lesson_assignments WHERE user_id = %s", (user_id,))
                conn.execute("DELETE FROM tutor_lesson_block_citations WHERE user_id = %s", (user_id,))
                conn.execute("DELETE FROM tutor_lesson_gate_slots WHERE user_id = %s", (user_id,))
                conn.execute("DELETE FROM tutor_lesson_source_snapshots WHERE user_id = %s", (user_id,))
                conn.execute("DELETE FROM tutor_lesson_documents WHERE user_id = %s", (user_id,))
                conn.execute("UPDATE tutor_learning_tracks SET current_knowledge_key = NULL WHERE user_id = %s", (user_id,))
                conn.execute("DELETE FROM tutor_mastery_states WHERE user_id = %s", (user_id,))
                conn.execute("DELETE FROM tutor_track_node_progress WHERE user_id = %s", (user_id,))
                conn.execute("DELETE FROM tutor_track_plan_nodes WHERE user_id = %s", (user_id,))
                conn.execute("DELETE FROM tutor_track_plan_modules WHERE user_id = %s", (user_id,))
                conn.execute("DELETE FROM tutor_track_active_plans WHERE user_id = %s", (user_id,))
                conn.execute("DELETE FROM tutor_track_plan_revisions WHERE user_id = %s", (user_id,))
                conn.execute("DELETE FROM tutor_learning_tracks WHERE user_id = %s", (user_id,))
                conn.execute("DELETE FROM users WHERE id = %s", (user_id,))


def _publish(
    conn,
    repo,
    user_id,
    track_id,
    snapshot,
    *,
    action: str,
    personalized_title: str = "Python 变量",
    standard_document=None,
    personalized_document=None,
):
    scope = repo.read_scope(user_id=user_id, track_id=track_id, knowledge_key="python.variables")
    assert scope.module_key == "foundations"
    assert scope.module_diagnostic_allowed is False
    run, replayed = repo.create_or_replay_authoring_run(
        scope=scope,
        run_kind="prepare" if action == "initial" else "refresh",
        idempotency_key=f"lesson-{action}",
        request_hash=("c" if action == "initial" else "e") * 64,
        profile_hash=("d" if action == "initial" else "f") * 64,
    )
    assert replayed is False
    conn.commit()
    with conn.transaction():
        claimed = repo.claim_authoring_run(run_id=run.run_id, owner="test-worker", now=datetime(2026, 8, 11, tzinfo=UTC))
        assert claimed is not None
        running = repo.mark_authoring_running(run_id=claimed.run_id, lease_generation=claimed.lease_generation)
        source_hash = canonical_source_set_hash((snapshot,))
        repo.set_authoring_source_set(run_id=running.run_id, lease_generation=running.lease_generation, source_set_hash=source_hash)
    standard = standard_document or sample_lesson_document()
    personalized = personalized_document or sample_lesson_document(
        title=personalized_title,
        personalized=True,
    )
    with conn.transaction():
        published = repo.publish_authoring_result(
            run=running,
            standard_document=standard,
            personalized_document=personalized,
            snapshots=(snapshot,),
            standard_quality={"passed": True},
            personalized_quality={"passed": True},
            standard_change_summary={},
            personalized_change_summary={"personalized": True},
            generator_version="lesson-author-test-v1",
            policy_version="lesson-quality-test-v1",
            source_set_hash=source_hash,
            impact=calculate_lesson_impact(standard, personalized),
            now=datetime(2026, 8, 11, tzinfo=UTC),
        )
    return published


def test_publish_round_trip_start_freeze_and_snapshot_survives_reindex(lesson_repo) -> None:
    conn, repo, user_id, track_id, snapshot = lesson_repo
    published = _publish(conn, repo, user_id, track_id, snapshot, action="initial")

    state = repo.read_lesson_state(user_id=user_id, track_id=track_id, knowledge_key="python.variables")
    assert state["document"] == sample_lesson_document(personalized=True)
    assert state["sources"] == (snapshot,)
    assignment = state["assignment"]
    assert isinstance(assignment, dict)
    assert assignment["status"] == "active"

    started = repo.start_assignment(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        assignment_id=published.assignment_id,
        expected_assignment_version=1,
        expected_progress_version=1,
        now=datetime(2026, 8, 11, 1, tzinfo=UTC),
    )
    conn.commit()
    assert started["progress_status"] == "in_progress"
    assert started["started_at"] is not None

    replace_grounding_chunks(conn, (), source_ids=(snapshot.source_id,))
    conn.commit()
    assert repo.load_source_snapshots(document_id=published.personalized_document_id) == (snapshot,)


def test_started_assignment_receives_proposal_and_explicit_migration(lesson_repo) -> None:
    conn, repo, user_id, track_id, snapshot = lesson_repo
    first = _publish(conn, repo, user_id, track_id, snapshot, action="initial")
    repo.start_assignment(
        user_id=user_id, track_id=track_id, knowledge_key="python.variables",
        assignment_id=first.assignment_id, expected_assignment_version=1,
        expected_progress_version=1, now=datetime(2026, 8, 11, 1, tzinfo=UTC),
    )
    conn.commit()

    second = _publish(conn, repo, user_id, track_id, snapshot, action="refresh", personalized_title="Python 变量：自动化版")
    assert second.assignment_status == "proposed"
    state = repo.read_lesson_state(user_id=user_id, track_id=track_id, knowledge_key="python.variables")
    active = state["assignment"]
    proposed = state["proposed_assignment"]
    assert isinstance(active, dict) and isinstance(proposed, dict)
    assert str(active["id"]) == first.assignment_id
    assert str(proposed["id"]) == second.assignment_id

    activated = repo.activate_proposed_assignment(
        user_id=user_id, track_id=track_id, knowledge_key="python.variables",
        assignment_id=second.assignment_id, expected_assignment_version=2,
        now=datetime(2026, 8, 11, 2, tzinfo=UTC),
    )
    conn.commit()
    assert activated["status"] == "active"
    assert str(repo.read_lesson_state(user_id=user_id, track_id=track_id, knowledge_key="python.variables")["assignment"]["id"]) == second.assignment_id


def test_schema_tables_indexes_and_immutable_triggers_exist(lesson_repo) -> None:
    conn, _repo, _user_id, _track_id, _snapshot = lesson_repo
    tables = {
        str(row["table_name"])
        for row in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name LIKE 'tutor_lesson_%'"
        ).fetchall()
    }
    assert {
        "tutor_lesson_documents", "tutor_lesson_source_snapshots",
        "tutor_lesson_block_citations", "tutor_lesson_gate_slots",
        "tutor_lesson_assignments", "tutor_lesson_authoring_runs",
        "tutor_lesson_authoring_attempt_receipts",
    } <= tables
    trigger_names = {
        str(row["tgname"])
        for row in conn.execute(
            "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgrelid::regclass::text LIKE 'tutor_lesson_%'"
        ).fetchall()
    }
    assert "trg_tutor_lesson_documents_immutable" in trigger_names
    assert "trg_tutor_lesson_authoring_attempt_receipts_immutable" in trigger_names


def test_local_export_reset_and_cutover_inventory_keep_shared_standard(lesson_repo) -> None:
    conn, repo, user_id, track_id, snapshot = lesson_repo
    published = _publish(conn, repo, user_id, track_id, snapshot, action="initial")
    exported = export_user_data(conn, user_id)
    assert len(exported["lesson_documents"]) == 1
    assert exported["lesson_documents"][0]["blocks_json"]
    assert len(exported["lesson_assignments"]) == 1
    assert len(exported["lesson_citations"]) == 1
    assert "evidence_excerpt" not in exported["lesson_citations"][0]

    inventory = HarnessCutoverService(conn)._inventory(user_id)
    assert inventory.target_counts["tutor_lesson_documents"] == 1
    assert inventory.target_counts["tutor_lesson_assignments"] == 1
    assert inventory.target_counts["tutor_lesson_authoring_runs"] == 1

    reset = reset_user_data(conn, user_id)
    conn.commit()
    assert reset["summary"]["counts"]["lesson_documents"] == 0
    assert reset["summary"]["counts"]["lesson_assignments"] == 0
    assert reset["summary"]["counts"]["lesson_authoring_runs"] == 0
    assert conn.execute("SELECT 1 FROM tutor_lesson_documents WHERE id = %s", (published.standard_document_id,)).fetchone() is not None
    assert conn.execute("SELECT 1 FROM tutor_lesson_documents WHERE id = %s", (published.personalized_document_id,)).fetchone() is None
