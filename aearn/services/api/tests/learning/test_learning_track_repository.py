from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime

import psycopg
import pytest

from app.agents.harness.contracts import TutorPolicySnapshot
from app.agents.harness.skill_catalog import compile_published_skill_catalog
from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.db.connection import connect
from app.services.learning.context_adapter import TutorLearningContextAdapter
from app.services.learning.contracts import (
    LearningScope,
    LearningScopeKind,
    LearningTaskKind,
    MasteryEvidence,
    MasteryEvidenceKind,
    MasteryIndependence,
)
from app.services.learning.track_repository import (
    LearningIdempotencyConflict,
    LearningPlanVersionConflict,
    LearningScopeConflict,
    LearningTrackNotFound,
    PostgresLearningTrackRepository,
)
from app.services.learning.track_service import LearningTrackService
from app.services.repositories.local_user_data_repository import export_user_data, get_user_data_summary, reset_user_data
from app.services.tutor.cutover import HarnessCutoverService
from app.services.tutor.persistence import PostgresTutorRepository
from tests.support.learning_track_support import sample_plan


def _database_available() -> bool:
    try:
        with psycopg.connect(get_settings().database_url, connect_timeout=2) as conn:
            conn.execute("select 1")
        return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(
    not _database_available(),
    reason="PostgreSQL is not available; run aearn infra compose for LearningTrack persistence tests.",
)

LEARNING_TRACK_TABLES = {
    "tutor_learning_tracks",
    "tutor_track_plan_revisions",
    "tutor_track_active_plans",
    "tutor_track_plan_modules",
    "tutor_track_plan_nodes",
    "tutor_track_node_progress",
    "tutor_track_plan_migrations",
    "tutor_mastery_evidence",
    "tutor_mastery_states",
    "tutor_conversation_learning_scopes",
    "tutor_run_learning_scopes",
}

LEARNING_TRACK_TRIGGERS = {
    "trg_tutor_learning_tracks_updated_at",
    "trg_tutor_learning_tracks_current_key_active",
    "trg_tutor_track_plan_revisions_immutable",
    "trg_tutor_track_plan_revisions_active_consistency",
    "trg_tutor_track_active_plans_updated_at",
    "trg_tutor_track_active_plans_consistency",
    "trg_tutor_track_plan_modules_immutable",
    "trg_tutor_track_plan_nodes_immutable",
    "trg_tutor_track_node_progress_updated_at",
    "trg_tutor_track_plan_migrations_lifecycle",
    "trg_tutor_mastery_evidence_immutable",
    "trg_tutor_mastery_states_updated_at",
    "trg_tutor_conversation_learning_scopes_updated_at",
    "trg_tutor_run_learning_scopes_immutable",
}

LEARNING_TRACK_CONSTRAINTS = {
    "fk_tutor_track_plan_revision_predecessor_scope",
    "chk_tutor_track_plan_revision_predecessor_distinct",
    "fk_tutor_track_active_plan_revision_scope",
    "fk_tutor_track_plan_node_module_scope",
    "uq_tutor_track_plan_nodes_revision_scope_key",
    "fk_tutor_track_node_progress_revision_scope",
    "fk_tutor_track_node_progress_source_node",
    "fk_tutor_mastery_evidence_progress_scope",
    "fk_tutor_mastery_state_last_evidence_scope",
    "fk_tutor_run_learning_scope_run_user",
    "fk_tutor_run_learning_scope_run_conversation",
    "fk_tutor_run_learning_scope_progress",
    "chk_tutor_track_node_progress_times",
    "chk_tutor_track_plan_migration_times",
    "chk_tutor_run_learning_scope_shape",
}


def _create_user(conn, *, label: str = "LearningTrack Repository") -> str:
    row = conn.execute(
        "INSERT INTO users (display_name) VALUES (%s) RETURNING id",
        (f"{label} {uuid.uuid4().hex[:10]}",),
    ).fetchone()
    assert row is not None
    return str(row["id"])


def _create_run(conn, *, user_id: str) -> tuple[str, str]:
    catalog = compile_published_skill_catalog()
    tutor = PostgresTutorRepository(conn)
    tutor.record_catalog_snapshot(catalog)
    conversation_id = tutor.create_conversation(user_id=user_id)
    run = tutor.create_run(
        user_id=user_id,
        conversation_id=conversation_id,
        catalog_digest=catalog.digest,
        policy=TutorPolicySnapshot(
            deadline=datetime(2030, 1, 1, tzinfo=UTC),
            max_iterations=2,
            max_model_calls=2,
            max_capability_calls=0,
            max_effects=0,
            context_token_budget=64,
        ),
        origin="interactive",
    )
    return conversation_id, run.run_id


def test_schema_bootstrap_is_repeatable_and_installs_scoped_constraints() -> None:
    bootstrap_database()
    bootstrap_database()
    with connect() as conn:
        tables = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name = ANY(%s)",
            (list(LEARNING_TRACK_TABLES),),
        ).fetchall()
        triggers = conn.execute(
            "SELECT tgname FROM pg_trigger WHERE tgname = ANY(%s) AND NOT tgisinternal",
            (list(LEARNING_TRACK_TRIGGERS),),
        ).fetchall()
        constraints = conn.execute(
            "SELECT conname FROM pg_constraint WHERE conname = ANY(%s)",
            (list(LEARNING_TRACK_CONSTRAINTS),),
        ).fetchall()
        active_index = conn.execute(
            "SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_tutor_track_plan_revisions_one_active'",
        ).fetchone()
        progress_check = conn.execute(
            "SELECT pg_get_constraintdef(oid, true) AS definition FROM pg_constraint WHERE conname = 'chk_tutor_track_node_progress_times'",
        ).fetchone()

    assert {str(row["table_name"]) for row in tables} == LEARNING_TRACK_TABLES
    assert {str(row["tgname"]) for row in triggers} == LEARNING_TRACK_TRIGGERS
    assert {str(row["conname"]) for row in constraints} == LEARNING_TRACK_CONSTRAINTS
    assert active_index is not None and "WHERE (status = 'active'::text)" in str(active_index["indexdef"])
    assert progress_check is not None and "= (started_at IS NOT NULL)" in str(progress_check["definition"])


def test_revision_activation_preserves_progress_and_computes_new_node_availability() -> None:
    bootstrap_database()
    with connect() as conn:
        user_id = _create_user(conn)
        repository = PostgresLearningTrackRepository(conn)
        track_id = repository.create_track(
            user_id=user_id,
            language_id="python",
            goal_text="Learn Python safely",
            target_level="beginner",
            plan=sample_plan(),
        )
        now = datetime.now(UTC)
        conn.execute(
            """
            UPDATE tutor_track_node_progress
            SET status = 'completed', started_at = %s, completed_at = %s, version = version + 1
            WHERE track_id = %s AND user_id = %s AND knowledge_key = 'python.variables'
            """,
            (now, now, track_id, user_id),
        )
        revision_id, impact, version = repository.propose_revision(
            user_id=user_id,
            track_id=track_id,
            expected_track_version=1,
            plan=sample_plan(
                title="Python Foundations v2",
                target_level="intermediate",
                generator_version="learning-plan-test-v2",
                change_reason="Add loops after completed variables.",
                include_loops=True,
            ),
            idempotency_key="repository-propose-v2",
            request_hash="a" * 64,
        )
        assert impact.added == ("python.loops",)
        assert impact.retained_progress == ("python.functions", "python.variables")

        next_version = repository.activate_revision(
            user_id=user_id,
            track_id=track_id,
            revision_id=revision_id,
            expected_track_version=version,
        )
        rows = conn.execute(
            "SELECT knowledge_key, status FROM tutor_track_node_progress WHERE track_id = %s ORDER BY knowledge_key",
            (track_id,),
        ).fetchall()
        migration = conn.execute(
            "SELECT status, confirmed_at, applied_at FROM tutor_track_plan_migrations WHERE to_revision_id = %s",
            (revision_id,),
        ).fetchone()
        conn.rollback()

    assert next_version == 3
    assert {str(row["knowledge_key"]): str(row["status"]) for row in rows} == {
        "python.functions": "locked",
        "python.loops": "available",
        "python.variables": "completed",
    }
    assert migration is not None
    assert migration["status"] == "applied"
    assert migration["confirmed_at"] is not None and migration["applied_at"] is not None


def test_postgresql_rejects_cross_scope_and_immutable_mutations() -> None:
    bootstrap_database()
    with connect() as conn:
        owner_id = _create_user(conn, label="LearningTrack Owner")
        other_id = _create_user(conn, label="LearningTrack Other")
        repository = PostgresLearningTrackRepository(conn)
        track_id = repository.create_track(
            user_id=owner_id,
            language_id="python",
            goal_text="Owner track",
            target_level="beginner",
            plan=sample_plan(),
        )
        row = conn.execute(
            """
            SELECT revisions.id AS revision_id, modules.id AS module_id, nodes.id AS node_id
            FROM tutor_track_plan_revisions AS revisions
            JOIN tutor_track_plan_modules AS modules ON modules.revision_id = revisions.id
            JOIN tutor_track_plan_nodes AS nodes ON nodes.module_id = modules.id
            WHERE revisions.track_id = %s
            ORDER BY nodes.order_index
            LIMIT 1
            """,
            (track_id,),
        ).fetchone()
        assert row is not None

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            with conn.transaction():
                conn.execute(
                    """
                    INSERT INTO tutor_track_plan_modules (
                      revision_id, track_id, user_id, module_key, title, order_index
                    ) VALUES (%s, %s, %s, 'cross-scope', 'Cross scope', 99)
                    """,
                    (row["revision_id"], track_id, other_id),
                )

        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(
                    "UPDATE tutor_track_plan_modules SET title = 'Mutated' WHERE id = %s",
                    (row["module_id"],),
                )
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(
                    "UPDATE tutor_track_plan_nodes SET title = 'Mutated' WHERE id = %s",
                    (row["node_id"],),
                )
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute("DELETE FROM tutor_track_plan_nodes WHERE id = %s", (row["node_id"],))
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            with conn.transaction():
                conn.execute(
                    """
                    INSERT INTO tutor_track_node_progress (
                      track_id, user_id, knowledge_key, status, source_plan_revision_id
                    ) VALUES (%s, %s, 'python.detached', 'available', %s)
                    """,
                    (track_id, owner_id, row["revision_id"]),
                )

        self_referencing_revision_id = str(uuid.uuid4())
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(
                    """
                    INSERT INTO tutor_track_plan_revisions (
                      id, track_id, user_id, predecessor_revision_id, status, title,
                      target_level, plan_json, generator_version, policy_version,
                      change_reason, content_hash
                    ) VALUES (
                      %s, %s, %s, %s, 'proposed', 'Self reference',
                      'beginner', '{}'::jsonb, 'test-generator', 'test-policy',
                      'Reject a self-referencing predecessor.', %s
                    )
                    """,
                    (
                        self_referencing_revision_id,
                        track_id,
                        owner_id,
                        self_referencing_revision_id,
                        "c" * 64,
                    ),
                )

        candidate_id, _impact, _version = repository.propose_revision(
            user_id=owner_id,
            track_id=track_id,
            expected_track_version=1,
            plan=sample_plan(title="Candidate", generator_version="candidate-v1", change_reason="Candidate revision."),
            idempotency_key="repository-one-active",
            request_hash="b" * 64,
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            with conn.transaction():
                conn.execute(
                    "UPDATE tutor_track_plan_revisions SET status = 'active', activated_at = now() WHERE id = %s",
                    (candidate_id,),
                )
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(
                    "UPDATE tutor_track_plan_revisions SET status = 'rejected', activated_at = NULL WHERE id = %s",
                    (row["revision_id"],),
                )
        conn.rollback()


def test_scope_adapter_evidence_replay_and_local_data_boundary() -> None:
    bootstrap_database()
    with connect() as conn:
        user_id = _create_user(conn)
        conversation_id, run_id = _create_run(conn, user_id=user_id)
        repository = PostgresLearningTrackRepository(conn)
        track_id = repository.create_track(
            user_id=user_id,
            language_id="python",
            goal_text="Track context",
            target_level="beginner",
            plan=sample_plan(),
        )

        general = TutorLearningContextAdapter(conn).load(user_id=user_id, run_id=run_id)
        assert general.scope.scope_kind is LearningScopeKind.GENERAL
        assert [source.source_id for source in general.sources] == [f"learning-scope:{run_id}"]

        scope = LearningScope(
            scope_kind=LearningScopeKind.LEARNING_TRACK,
            learning_track_id=track_id,
            task_kind=LearningTaskKind.LESSON_TEACHING,
            knowledge_key="python.variables",
        )
        snapshot = repository.snapshot_run_scope(user_id=user_id, run_id=run_id, explicit_scope=scope)
        scoped = TutorLearningContextAdapter(conn).load(user_id=user_id, run_id=run_id)
        assert snapshot.conversation_id == conversation_id
        assert [source.source_id for source in scoped.sources] == [
            f"learning-scope:{run_id}",
            f"learning-track:{track_id}",
            "learning-node:python.variables",
        ]
        with pytest.raises(LearningScopeConflict):
            repository.snapshot_run_scope(user_id=user_id, run_id=run_id, explicit_scope=LearningScope())
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(
                    "UPDATE tutor_run_learning_scopes SET task_kind = 'review_coaching' WHERE run_id = %s",
                    (run_id,),
                )

        evidence = MasteryEvidence(
            evidence_id=str(uuid.uuid4()),
            knowledge_key="python.variables",
            evidence_kind=MasteryEvidenceKind.GATE,
            source_receipt_id="gate-receipt-1",
            source_receipt_hash="c" * 64,
            independence=MasteryIndependence.INDEPENDENT,
            score=0.85,
            hint_count=0,
            attempt_count=1,
            summary={"strengths": ["binding"]},
            created_at=datetime.now(UTC),
        )
        evidence_id, first_projection, replayed = repository.append_mastery_evidence(
            user_id=user_id,
            track_id=track_id,
            evidence=evidence,
        )
        replay_id, replay_projection, replayed_again = repository.append_mastery_evidence(
            user_id=user_id,
            track_id=track_id,
            evidence=evidence,
        )
        assert replayed is False and replayed_again is True
        assert replay_id == evidence_id
        assert replay_projection == first_projection
        state_after_replay = conn.execute(
            "SELECT version FROM tutor_mastery_states WHERE track_id = %s AND knowledge_key = %s",
            (track_id, evidence.knowledge_key),
        ).fetchone()
        assert state_after_replay == {"version": 2}
        conflicting_evidence = MasteryEvidence(
            evidence_id=evidence.evidence_id,
            knowledge_key=evidence.knowledge_key,
            evidence_kind=evidence.evidence_kind,
            source_receipt_id=evidence.source_receipt_id,
            source_receipt_hash=evidence.source_receipt_hash,
            independence=evidence.independence,
            score=0.2,
            hint_count=evidence.hint_count,
            attempt_count=evidence.attempt_count,
            summary=evidence.summary,
            created_at=evidence.created_at,
        )
        with pytest.raises(LearningIdempotencyConflict):
            repository.append_mastery_evidence(
                user_id=user_id,
                track_id=track_id,
                evidence=conflicting_evidence,
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute("UPDATE tutor_mastery_evidence SET score = 0.1 WHERE id = %s", (evidence_id,))
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute("DELETE FROM tutor_mastery_evidence WHERE id = %s", (evidence_id,))

        summary = get_user_data_summary(conn, user_id)
        exported = export_user_data(conn, user_id)
        export_text = str(exported)
        assert summary["counts"]["learning_tracks"] == 1
        assert summary["counts"]["mastery_evidence"] == 1
        assert len(exported["learning_tracks"]) == 1
        assert len(exported["learning_track_plan_revisions"]) == 1
        assert "evidence_summary_json" not in export_text
        assert "plan_json" not in export_text

        reset = reset_user_data(conn, user_id)
        remaining = {
            table: conn.execute(f"SELECT count(*)::int AS count FROM {table} WHERE user_id = %s", (user_id,)).fetchone()["count"]
            for table in LEARNING_TRACK_TABLES
        }
        conversation = conn.execute("SELECT id FROM tutor_conversations WHERE id = %s", (conversation_id,)).fetchone()
        conn.rollback()

    assert reset["summary"]["counts"]["learning_tracks"] == 0
    assert all(count == 0 for count in remaining.values())
    assert conversation is not None


def test_track_version_conflict_and_cutover_inventory_fail_closed() -> None:
    bootstrap_database()
    with connect() as conn:
        user_id = _create_user(conn)
        repository = PostgresLearningTrackRepository(conn)
        track_id = repository.create_track(
            user_id=user_id,
            language_id="python",
            goal_text="Version conflict",
            target_level="beginner",
            plan=sample_plan(),
        )
        with pytest.raises(LearningPlanVersionConflict):
            repository.propose_revision(
                user_id=user_id,
                track_id=track_id,
                expected_track_version=99,
                plan=sample_plan(title="Stale candidate", generator_version="stale-v1", change_reason="Stale."),
                idempotency_key="repository-stale",
                request_hash="d" * 64,
            )
        inventory = HarnessCutoverService(conn)._inventory(user_id)
        conn.rollback()

    assert inventory.has_target_state
    assert inventory.target_counts["tutor_learning_tracks"] == 1
    assert inventory.target_counts["tutor_track_plan_revisions"] == 1


def test_scope_rejects_detached_progress_and_reset_cancels_active_continuations() -> None:
    bootstrap_database()
    with connect() as conn:
        user_id = _create_user(conn, label="LearningTrack Scope Reset")
        conversation_id, run_id = _create_run(conn, user_id=user_id)
        repository = PostgresLearningTrackRepository(conn)
        track_id = repository.create_track(
            user_id=user_id,
            language_id="python",
            goal_text="Retire a scoped knowledge key safely",
            target_level="beginner",
            plan=sample_plan(),
        )
        original_scope = LearningScope(
            scope_kind=LearningScopeKind.LEARNING_TRACK,
            learning_track_id=track_id,
            task_kind=LearningTaskKind.LESSON_TEACHING,
            knowledge_key="python.functions",
        )
        repository.snapshot_run_scope(
            user_id=user_id,
            run_id=run_id,
            explicit_scope=original_scope,
        )
        candidate = sample_plan()
        module = candidate.modules[0]
        detached_plan = replace(
            candidate,
            title="Python Variables Only",
            generator_version="learning-plan-test-v2",
            change_reason="Remove the functions node.",
            modules=(replace(module, nodes=(module.nodes[0],)),),
        )
        revision_id, _impact, version = repository.propose_revision(
            user_id=user_id,
            track_id=track_id,
            expected_track_version=1,
            plan=detached_plan,
            idempotency_key="scope-detach-plan",
            request_hash="e" * 64,
        )
        repository.activate_revision(
            user_id=user_id,
            track_id=track_id,
            revision_id=revision_id,
            expected_track_version=version,
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(
                    "UPDATE tutor_learning_tracks SET current_knowledge_key = 'python.functions' WHERE id = %s AND user_id = %s",
                    (track_id, user_id),
                )
        _next_conversation_id, next_run_id = _create_run(conn, user_id=user_id)
        with pytest.raises(LearningTrackNotFound):
            repository.snapshot_run_scope(
                user_id=user_id,
                run_id=next_run_id,
                explicit_scope=original_scope,
            )

        conn.execute(
            """
            UPDATE tutor_runs
            SET status = 'waiting_for_input', continuation_kind = 'capability_result'
            WHERE id = %s AND user_id = %s
            """,
            (run_id, user_id),
        )
        reset_user_data(conn, user_id)
        cancelled = conn.execute(
            """
            SELECT status, terminal_outcome, cancelled_at
            FROM tutor_runs
            WHERE id = %s AND user_id = %s
            """,
            (run_id, user_id),
        ).fetchone()
        remaining_scope = conn.execute(
            "SELECT 1 FROM tutor_run_learning_scopes WHERE run_id = %s",
            (run_id,),
        ).fetchone()
        conn.rollback()

    assert cancelled is not None
    assert cancelled["status"] == "cancelled"
    assert cancelled["terminal_outcome"] == "cancelled"
    assert cancelled["cancelled_at"] is not None
    assert remaining_scope is None


def test_concurrent_learning_track_create_replays_one_result() -> None:
    bootstrap_database()
    with connect() as conn:
        user_id = _create_user(conn, label="LearningTrack Idempotency")
        conn.commit()

    def create_once() -> dict[str, object]:
        with connect() as worker_conn:
            response = LearningTrackService(worker_conn).create_track(
                user_id=user_id,
                language_id="python",
                goal_text="Concurrent idempotency",
                target_level="beginner",
                plan=sample_plan(),
                conversation_id=None,
                idempotency_key="concurrent-track-create",
            )
            worker_conn.commit()
            return response

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _index: create_once(), range(2)))

    track_ids = {str(response["track"]["track_id"]) for response in responses}
    assert len(track_ids) == 1
    assert sorted(bool(response["idempotent_replayed"]) for response in responses) == [False, True]
    with connect() as conn:
        count = conn.execute(
            "SELECT count(*)::int AS count FROM tutor_learning_tracks WHERE user_id = %s",
            (user_id,),
        ).fetchone()
        conn.execute("SELECT set_config('aearn.learning_track_purge_user_id', %s, true)", (user_id,))
        conn.execute("DELETE FROM tutor_mastery_states WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM tutor_review_schedule_events WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM tutor_review_schedule_states WHERE user_id = %s", (user_id,))
        conn.execute("UPDATE tutor_learning_tracks SET current_knowledge_key = NULL WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM tutor_track_node_progress WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM tutor_track_plan_nodes WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM tutor_track_plan_modules WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM tutor_track_active_plans WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM tutor_track_plan_revisions WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM tutor_learning_tracks WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM tutor_api_idempotency_records WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
    assert count == {"count": 1}
