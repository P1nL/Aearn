from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import psycopg
import pytest

from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.db.connection import connect
from app.services.learning.contracts import MasteryEvidence, MasteryEvidenceKind, MasteryIndependence
from app.services.learning.practice.contracts import (
    ExercisePrivateRubric,
    ExerciseSourceKind,
    ExerciseType,
    ExerciseVersion,
)
from app.services.learning.practice.fixtures import CuratedExerciseFixture
from app.services.learning.practice.quality import require_exercise_quality
from app.services.learning.practice.repository import PostgresExerciseGateRepository
from app.services.learning.reviews.persistence import ReviewNotFound
from app.services.repositories.local_user_data_repository import export_user_data, reset_user_data
from app.services.tutor.cutover import HarnessCutoverService
from app.services.learning.reviews.service import ReviewService, ReviewServiceError
from app.services.learning.reviews.session_repository import PostgresReviewSessionRepository
from app.services.learning.track_repository import PostgresLearningTrackRepository
from learning_track_support import sample_plan


def _database_available() -> bool:
    try:
        with psycopg.connect(get_settings().database_url, connect_timeout=2) as conn:
            conn.execute("select 1")
        return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(
    not _database_available(),
    reason="PostgreSQL is not available; run aearn infra compose for ReviewSession tests.",
)


def _fixture() -> CuratedExerciseFixture:
    exercise = ExerciseVersion(
        language_id="python",
        exercise_key=f"python.review.variables.{uuid4().hex[:12]}",
        exercise_type=ExerciseType.STATIC_CODE_REASONING,
        version="v1",
        source_kind=ExerciseSourceKind.CURATED_FIXTURE,
        title="变量回忆检查",
        learner_prompt={"text": "Python 中用于绑定值的语句是什么？"},
        starter_artifact={"content": ""},
        required_capabilities=("python",),
        runtime_profile_id=None,
        execution_required=False,
        public_feedback_policy_version="lesson_gate_feedback_v1",
    )
    rubric = ExercisePrivateRubric(
        rubric_version="v1",
        private_test_bundle=({"case_type": "hidden", "input": {}, "expected": {"value": "x = 1"}},),
        reference_answer={"accepted_answers": ["x = 1"]},
        score_policy={"kind": "exact_static", "threshold": 0.8},
    )
    require_exercise_quality(exercise, rubric)
    return CuratedExerciseFixture(exercise=exercise, rubric=rubric)


def _create_scope(conn, *, with_candidate: bool = True):
    user = conn.execute(
        "INSERT INTO users (display_name) VALUES (%s) RETURNING id",
        (f"Review Session {uuid4().hex[:10]}",),
    ).fetchone()
    assert user is not None
    user_id = str(user["id"])
    tracks = PostgresLearningTrackRepository(conn)
    track_id = tracks.create_track(
        user_id=user_id,
        language_id="python",
        goal_text="复习 Python 基础",
        target_level="beginner",
        plan=sample_plan(),
    )
    evidence = MasteryEvidence(
        evidence_id=str(uuid4()),
        knowledge_key="python.variables",
        evidence_kind=MasteryEvidenceKind.GATE,
        source_receipt_id=f"gate-{uuid4()}",
        source_receipt_hash="a" * 64,
        independence=MasteryIndependence.INDEPENDENT,
        score=0.9,
        hint_count=0,
        attempt_count=1,
        summary={"strengths": ["python"]},
        created_at=datetime.now(UTC) - timedelta(days=8),
    )
    tracks.append_mastery_evidence(user_id=user_id, track_id=track_id, evidence=evidence)
    schedule = conn.execute(
        """UPDATE tutor_review_schedule_states
        SET due_at = %s, version = version + 1
        WHERE user_id = %s AND track_id = %s AND knowledge_key = 'python.variables'
        RETURNING *""",
        (datetime.now(UTC) - timedelta(minutes=1), user_id, track_id),
    ).fetchone()
    assert schedule is not None
    if with_candidate:
        PostgresExerciseGateRepository(conn).ensure_curated_fixture(_fixture(), now=datetime.now(UTC))
    return user_id, track_id, dict(schedule)


def test_review_session_warmup_attempt_and_exactly_once_finalization() -> None:
    bootstrap_database()
    with connect() as conn:
        user_id, track_id, schedule = _create_scope(conn)
        service = ReviewService(conn)
        queue = service.read_queue(user_id=user_id, track_id=track_id)
        assert queue["due_count"] == 1
        created = service.create_session(
            user_id=user_id,
            track_id=track_id,
            knowledge_key="python.variables",
            expected_track_version=1,
            expected_schedule_version=int(schedule["version"]),
            max_items=1,
            idempotency_key=f"review-create-{uuid4()}",
        )
        assert created["state"] == "active"
        assert created["context_snapshot"]["schema_version"] == "review_authoritative_context_v1"
        session_id = str(created["session_id"])
        item_id = str(created["items"][0]["item_id"])
        before = conn.execute(
            """SELECT
              (SELECT count(*) FROM tutor_mastery_evidence WHERE user_id = %s) AS evidence_count,
              (SELECT version FROM tutor_review_schedule_states WHERE user_id = %s AND track_id = %s
               AND knowledge_key = 'python.variables') AS schedule_version""",
            (user_id, user_id, track_id),
        ).fetchone()
        warmup = service.warmup(
            user_id=user_id,
            track_id=track_id,
            session_id=session_id,
            response_kind="skipped",
            confidence=None,
            expected_session_version=int(created["version"]),
            idempotency_key=f"review-warmup-{uuid4()}",
        )
        after_warmup = conn.execute(
            """SELECT
              (SELECT count(*) FROM tutor_mastery_evidence WHERE user_id = %s) AS evidence_count,
              (SELECT version FROM tutor_review_schedule_states WHERE user_id = %s AND track_id = %s
               AND knowledge_key = 'python.variables') AS schedule_version""",
            (user_id, user_id, track_id),
        ).fetchone()
        assert after_warmup == before
        attempt = service.attempt_item(
            user_id=user_id,
            track_id=track_id,
            session_id=session_id,
            item_id=item_id,
            submission="x = 1",
            review_submission=None,
            expected_session_version=int(warmup["version"]),
            expected_item_version=1,
            idempotency_key=f"review-attempt-{uuid4()}",
        )
        assert attempt["status"] == "terminal"
        assert attempt["result"]["outcome"] == "passed"
        after_attempt = conn.execute(
            """SELECT
              (SELECT count(*) FROM tutor_mastery_evidence WHERE user_id = %s) AS evidence_count,
              (SELECT version FROM tutor_review_schedule_states WHERE user_id = %s AND track_id = %s
               AND knowledge_key = 'python.variables') AS schedule_version""",
            (user_id, user_id, track_id),
        ).fetchone()
        assert after_attempt == before
        finalize_key = f"review-finalize-{uuid4()}"
        finalized = service.finalize_session(
            user_id=user_id,
            track_id=track_id,
            session_id=session_id,
            expected_session_version=int(attempt["session_version"]),
            idempotency_key=finalize_key,
        )
        assert finalized["state"] == "finalized"
        assert finalized["finalization"]["rating"] == "easy"
        counts = conn.execute(
            """SELECT
              (SELECT count(*) FROM tutor_review_finalizations WHERE session_id = %s) AS finalizations,
              (SELECT count(*) FROM tutor_mastery_evidence WHERE user_id = %s AND evidence_kind = 'review') AS review_evidence,
              (SELECT count(*) FROM tutor_review_schedule_events WHERE user_id = %s AND source_kind = 'session_finalization') AS schedule_events""",
            (session_id, user_id, user_id),
        ).fetchone()
        assert counts == {"finalizations": 1, "review_evidence": 1, "schedule_events": 1}
        replay = service.finalize_session(
            user_id=user_id,
            track_id=track_id,
            session_id=session_id,
            expected_session_version=int(attempt["session_version"]),
            idempotency_key=finalize_key,
        )
        assert replay["state"] == "finalized"
        conn.rollback()


def test_critical_prerequisite_is_immediately_queued_and_startable() -> None:
    bootstrap_database()
    with connect() as conn:
        user_id, track_id, _schedule = _create_scope(conn)
        conn.execute(
            "UPDATE tutor_learning_tracks SET current_knowledge_key = 'python.functions' "
            "WHERE id = %s AND user_id = %s",
            (track_id, user_id),
        )
        future_schedule = conn.execute(
            """UPDATE tutor_review_schedule_states
            SET due_at = %s, risk_level = 'critical', version = version + 1
            WHERE user_id = %s AND track_id = %s AND knowledge_key = 'python.variables'
            RETURNING *""",
            (datetime.now(UTC) + timedelta(minutes=10), user_id, track_id),
        ).fetchone()
        assert future_schedule is not None

        service = ReviewService(conn)
        queue = service.read_queue(user_id=user_id, track_id=track_id)
        assert queue["due_count"] == 1
        assert queue["critical_prerequisite_gate"]["knowledge_key"] == "python.variables"
        assert queue["items"][0]["critical_prerequisite_gate"] is True
        assert int(PostgresLearningTrackRepository(conn).read_track(
            user_id=user_id,
            track_id=track_id,
        )["review_due_count"]) == 1

        created = service.create_session(
            user_id=user_id,
            track_id=track_id,
            knowledge_key="python.variables",
            expected_track_version=1,
            expected_schedule_version=int(future_schedule["version"]),
            max_items=1,
            idempotency_key=f"review-critical-{uuid4()}",
        )
        assert created["state"] == "active"
        conn.rollback()


def test_review_batch_waits_for_every_terminal_attempt_before_finalization() -> None:
    bootstrap_database()
    with connect() as conn:
        user_id, track_id, schedule = _create_scope(conn)
        PostgresExerciseGateRepository(conn).ensure_curated_fixture(
            _fixture(),
            now=datetime.now(UTC),
        )
        service = ReviewService(conn)
        created = service.create_session(
            user_id=user_id,
            track_id=track_id,
            knowledge_key="python.variables",
            expected_track_version=1,
            expected_schedule_version=int(schedule["version"]),
            max_items=2,
            idempotency_key=f"review-batch-{uuid4()}",
        )
        assert len(created["items"]) == 2
        session_id = str(created["session_id"])
        warmup = service.warmup(
            user_id=user_id,
            track_id=track_id,
            session_id=session_id,
            response_kind="answered",
            confidence="high",
            expected_session_version=int(created["version"]),
            idempotency_key=f"review-batch-warmup-{uuid4()}",
        )

        first = service.attempt_item(
            user_id=user_id,
            track_id=track_id,
            session_id=session_id,
            item_id=str(created["items"][0]["item_id"]),
            submission="x = 1",
            review_submission=None,
            expected_session_version=int(warmup["version"]),
            expected_item_version=1,
            idempotency_key=f"review-batch-first-{uuid4()}",
        )
        assert first["status"] == "terminal"
        assert service.read_session(
            user_id=user_id,
            track_id=track_id,
            session_id=session_id,
        )["state"] == "active"
        with pytest.raises(ReviewServiceError) as early:
            service.finalize_session(
                user_id=user_id,
                track_id=track_id,
                session_id=session_id,
                expected_session_version=int(first["session_version"]),
                idempotency_key=f"review-batch-early-{uuid4()}",
            )
        assert early.value.code == "REVIEW_NOT_READY"

        second = service.attempt_item(
            user_id=user_id,
            track_id=track_id,
            session_id=session_id,
            item_id=str(created["items"][1]["item_id"]),
            submission="x = 1",
            review_submission=None,
            expected_session_version=int(first["session_version"]),
            expected_item_version=1,
            idempotency_key=f"review-batch-second-{uuid4()}",
        )
        assert second["status"] == "terminal"
        finalized = service.finalize_session(
            user_id=user_id,
            track_id=track_id,
            session_id=session_id,
            expected_session_version=int(second["session_version"]),
            idempotency_key=f"review-batch-finalize-{uuid4()}",
        )
        assert finalized["state"] == "finalized"
        assert finalized["finalization"]["aggregate"]["attempt_count"] == 2
        counts = conn.execute(
            """SELECT
              (SELECT count(*) FROM tutor_review_finalizations WHERE session_id = %s) AS finalizations,
              (SELECT count(*) FROM tutor_mastery_evidence
               WHERE user_id = %s AND track_id = %s AND evidence_kind = 'review') AS review_evidence""",
            (session_id, user_id, track_id),
        ).fetchone()
        assert counts == {"finalizations": 1, "review_evidence": 1}
        conn.rollback()


def test_review_session_is_strictly_user_scoped() -> None:
    bootstrap_database()
    with connect() as conn:
        user_id, track_id, schedule = _create_scope(conn)
        other = conn.execute("INSERT INTO users (display_name) VALUES ('Review Other') RETURNING id").fetchone()
        assert other is not None
        created = ReviewService(conn).create_session(
            user_id=user_id,
            track_id=track_id,
            knowledge_key="python.variables",
            expected_track_version=1,
            expected_schedule_version=int(schedule["version"]),
            max_items=1,
            idempotency_key=f"review-cross-{uuid4()}",
        )
        with pytest.raises(ReviewNotFound):
            PostgresReviewSessionRepository(conn).read_session(
                user_id=str(other["id"]),
                track_id=track_id,
                session_id=str(created["session_id"]),
            )
        conn.rollback()



def test_candidate_shortage_is_recoverable_without_low_quality_fallback() -> None:
    bootstrap_database()
    with connect() as conn:
        user_id, track_id, schedule = _create_scope(conn, with_candidate=False)
        service = ReviewService(conn)
        key = f"review-blocked-{uuid4()}"
        with patch.object(service, "_candidates", return_value=()):
            blocked = service.create_session(
                user_id=user_id,
                track_id=track_id,
                knowledge_key="python.variables",
                expected_track_version=1,
                expected_schedule_version=int(schedule["version"]),
                max_items=1,
                idempotency_key=key,
            )
        assert blocked["state"] == "blocked"
        assert blocked["failure_code"] == "REVIEW_CANDIDATE_UNAVAILABLE"
        assert blocked["recoverable"] is True
        assert blocked["items"] == []
        PostgresExerciseGateRepository(conn).ensure_curated_fixture(_fixture(), now=datetime.now(UTC))
        recovered = service.create_session(
            user_id=user_id,
            track_id=track_id,
            knowledge_key="python.variables",
            expected_track_version=1,
            expected_schedule_version=int(schedule["version"]),
            max_items=1,
            idempotency_key=key,
        )
        assert recovered["session_id"] == blocked["session_id"]
        assert recovered["state"] == "active"
        assert recovered["failure_code"] is None
        assert recovered["idempotent_replayed"] is True
        assert len(recovered["items"]) == 1
        conn.rollback()


def test_plan_revision_retains_and_explicitly_suspends_review_schedule() -> None:
    bootstrap_database()
    with connect() as conn:
        user_id, track_id, schedule = _create_scope(conn)
        tracks = PostgresLearningTrackRepository(conn)
        retained_revision, retained_impact, retained_version = tracks.propose_revision(
            user_id=user_id,
            track_id=track_id,
            expected_track_version=1,
            plan=sample_plan(
                title="Python Foundations v2",
                target_level="intermediate",
                generator_version="review-plan-v2",
                change_reason="保留变量并增加循环。",
                include_loops=True,
            ),
            idempotency_key=f"review-plan-retain-{uuid4()}",
            request_hash="b" * 64,
        )
        tracks.activate_revision(
            user_id=user_id,
            track_id=track_id,
            revision_id=retained_revision,
            expected_track_version=retained_version,
        )
        retained = conn.execute(
            """SELECT status, card_state, source_plan_revision_id, version
            FROM tutor_review_schedule_states
            WHERE user_id = %s AND track_id = %s AND knowledge_key = 'python.variables'""",
            (user_id, track_id),
        ).fetchone()
        assert retained is not None
        assert retained["status"] == "active"
        assert str(retained["source_plan_revision_id"]) == retained_revision
        assert int(retained["version"]) == int(schedule["version"]) + 1
        assert retained_impact.retained_progress == ("python.functions", "python.variables")

        active_revision, active_plan = tracks.read_active_plan(user_id=user_id, track_id=track_id)
        functions_only = sample_plan(
            title="Python Functions Only",
            target_level="intermediate",
            generator_version="review-plan-v3",
            change_reason="显式移除变量节点。",
        )
        from app.services.learning.contracts import LearningPlan, LearningPlanModule

        functions_only = LearningPlan(
            title=functions_only.title,
            target_level=functions_only.target_level,
            generator_version=functions_only.generator_version,
            policy_version=functions_only.policy_version,
            change_reason=functions_only.change_reason,
            modules=(
                LearningPlanModule(
                    module_key="foundations",
                    title="Foundations",
                    description="Core language foundations.",
                    order_index=0,
                    is_core=True,
                    is_skippable=False,
                    nodes=(replace(active_plan.nodes[1], prerequisite_keys=(), order_index=0),),
                ),
            ),
        )
        track_row = conn.execute(
            "SELECT version FROM tutor_learning_tracks WHERE id = %s AND user_id = %s",
            (track_id, user_id),
        ).fetchone()
        assert track_row is not None and active_revision == retained_revision
        removed_revision, removed_impact, removed_version = tracks.propose_revision(
            user_id=user_id,
            track_id=track_id,
            expected_track_version=int(track_row["version"]),
            plan=functions_only,
            idempotency_key=f"review-plan-remove-{uuid4()}",
            request_hash="c" * 64,
        )
        tracks.activate_revision(
            user_id=user_id,
            track_id=track_id,
            revision_id=removed_revision,
            expected_track_version=removed_version,
        )
        suspended = conn.execute(
            """SELECT status, card_state, source_plan_revision_id
            FROM tutor_review_schedule_states
            WHERE user_id = %s AND track_id = %s AND knowledge_key = 'python.variables'""",
            (user_id, track_id),
        ).fetchone()
        assert suspended == {
            "status": "suspended",
            "card_state": "suspended",
            "source_plan_revision_id": suspended["source_plan_revision_id"],
        }
        assert str(suspended["source_plan_revision_id"]) == removed_revision
        assert removed_impact.removed == ("python.loops", "python.variables")
        conn.rollback()


def test_review_export_reset_and_cutover_inventory_are_safe() -> None:
    bootstrap_database()
    with connect() as conn:
        user_id, track_id, schedule = _create_scope(conn)
        service = ReviewService(conn)
        created = service.create_session(
            user_id=user_id,
            track_id=track_id,
            knowledge_key="python.variables",
            expected_track_version=1,
            expected_schedule_version=int(schedule["version"]),
            max_items=1,
            idempotency_key=f"review-export-{uuid4()}",
        )
        exported = export_user_data(conn, user_id)
        assert exported["summary"]["counts"]["review_schedules"] == 1
        assert exported["summary"]["counts"]["review_sessions"] == 1
        assert len(exported["review_schedule_summaries"]) == 1
        assert len(exported["review_session_summaries"]) == 1
        serialized = json.dumps(exported, ensure_ascii=False, sort_keys=True)
        assert '"context_snapshot_json"' not in serialized
        assert '"context_snapshot_hash"' not in serialized
        assert '"selection_reason_json"' not in serialized
        inventory = HarnessCutoverService(conn)._inventory(user_id)
        assert inventory.target_counts["tutor_review_schedule_states"] == 1
        assert inventory.target_counts["tutor_review_sessions"] == 1
        assert inventory.target_counts["tutor_review_items"] == 1
        reset = reset_user_data(conn, user_id)
        assert reset["summary"]["counts"]["review_schedules"] == 0
        assert reset["summary"]["counts"]["review_sessions"] == 0
        assert reset["summary"]["counts"]["review_finalizations"] == 0
        assert created["context_snapshot_hash"]
        conn.rollback()
