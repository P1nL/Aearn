from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from aearn_shared.execution import SafeExecutionResultV1, SafeExecutionStatus

from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.services.learning.contracts import (
    ExecutionComposition,
    MasteryEvidence,
    MasteryEvidenceKind,
    MasteryIndependence,
)
from app.services.learning.practice.service import ExerciseGateService, ExerciseGateServiceError
from app.services.learning.track_repository import PostgresLearningTrackRepository
from app.services.repositories.local_user_data_repository import reset_user_data
from tests.support.learning_track_support import sample_plan


def _database_available() -> bool:
    try:
        with psycopg.connect(get_settings().database_url, connect_timeout=2) as conn:
            conn.execute("select 1")
        return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(not _database_available(), reason="PostgreSQL is not available")


@pytest.fixture()
def diagnostic_scope():
    bootstrap_database()
    with psycopg.connect(get_settings().database_url, row_factory=dict_row) as conn:
        user = conn.execute(
            "INSERT INTO users (display_name) VALUES (%s) RETURNING id",
            (f"Diagnostic {uuid4().hex[:12]}",),
        ).fetchone()
        assert user is not None
        user_id = str(user["id"])
        plan = sample_plan()
        plan = replace(plan, modules=(replace(plan.modules[0], is_skippable=True),))
        track_id = PostgresLearningTrackRepository(conn).create_track(
            user_id=user_id,
            language_id="python",
            goal_text="Verify Python foundations",
            target_level="beginner",
            plan=plan,
        )
        conn.commit()
        try:
            yield conn, user_id, track_id
        finally:
            conn.rollback()
            with conn.transaction():
                reset_user_data(conn, user_id)
                conn.execute("DELETE FROM users WHERE id = %s", (user_id,))


def _success(_attempt, _submission: str) -> SafeExecutionResultV1:
    return SafeExecutionResultV1(
        status=SafeExecutionStatus.SUCCESS,
        stdout="ok\n",
        passed_test_count=2,
        total_test_count=2,
        diagnostic_code="fixture_success",
    )


def _failure(_attempt, _submission: str) -> SafeExecutionResultV1:
    return SafeExecutionResultV1(
        status=SafeExecutionStatus.FAILED,
        stderr="assertion failed",
        passed_test_count=0,
        total_test_count=2,
        diagnostic_code="fixture_failed",
    )


def _service(conn, runner) -> ExerciseGateService:
    return ExerciseGateService(
        conn,
        composition=ExecutionComposition.DEVELOPMENT,
        local_runner_available=True,
        local_runner=runner,
    )


def test_failed_diagnostic_is_observational_and_does_not_create_revision(diagnostic_scope) -> None:
    conn, user_id, track_id = diagnostic_scope
    tracks = PostgresLearningTrackRepository(conn)
    _, baseline, _ = tracks.append_mastery_evidence(
        user_id=user_id,
        track_id=track_id,
        evidence=MasteryEvidence(
            evidence_id=str(uuid4()),
            knowledge_key="python.variables",
            evidence_kind=MasteryEvidenceKind.GATE,
            source_receipt_id=f"baseline-{uuid4()}",
            source_receipt_hash="a" * 64,
            independence=MasteryIndependence.INDEPENDENT,
            score=1.0,
            hint_count=0,
            attempt_count=1,
            summary={"strengths": ["python"]},
            created_at=datetime(2026, 8, 11, tzinfo=UTC),
        ),
    )
    service = _service(conn, _failure)
    session = service.create_diagnostic(
        user_id=user_id,
        track_id=track_id,
        module_key="foundations",
        expected_track_version=1,
        idempotency_key=f"diagnostic-{uuid4()}",
    )
    item = session["items"][0]
    failed = service.attempt_diagnostic(
        user_id=user_id,
        track_id=track_id,
        module_key="foundations",
        session_id=str(session["session_id"]),
        item_id=str(item["item_id"]),
        submission="print('not enough')",
        expected_track_version=1,
        expected_session_version=int(session["version"]),
        idempotency_key=f"diagnostic-attempt-{uuid4()}",
    )

    assert failed["state"] == "failed"
    assert failed["proposed_plan_revision_id"] is None
    assert failed["weak_capabilities"] == ["python"]
    assert conn.execute(
        "SELECT count(*)::int AS count FROM tutor_track_plan_revisions WHERE user_id = %s",
        (user_id,),
    ).fetchone()["count"] == 1
    observed = conn.execute(
        """
        SELECT confidence, mastery_level, observation_count
        FROM tutor_mastery_states
        WHERE user_id = %s AND track_id = %s AND knowledge_key = 'python.variables'
        """,
        (user_id, track_id),
    ).fetchone()
    assert observed is not None
    assert float(observed["confidence"]) == baseline.confidence
    assert observed["mastery_level"] == baseline.mastery_level.value
    assert int(observed["observation_count"]) == 1
    effects = conn.execute(
        """
        SELECT evidence_effect FROM tutor_mastery_evidence
        WHERE user_id = %s AND track_id = %s AND evidence_kind = 'module_diagnostic'
        """,
        (user_id, track_id),
    ).fetchall()
    assert effects == [{"evidence_effect": "observational_non_degrading"}]


def test_passed_diagnostic_requires_confirmation_before_skip(diagnostic_scope) -> None:
    conn, user_id, track_id = diagnostic_scope
    service = _service(conn, _success)
    session = service.create_diagnostic(
        user_id=user_id,
        track_id=track_id,
        module_key="foundations",
        expected_track_version=1,
        idempotency_key=f"diagnostic-{uuid4()}",
    )
    item = session["items"][0]
    passed = service.attempt_diagnostic(
        user_id=user_id,
        track_id=track_id,
        module_key="foundations",
        session_id=str(session["session_id"]),
        item_id=str(item["item_id"]),
        submission="value = 3\nprint(value)",
        expected_track_version=1,
        expected_session_version=int(session["version"]),
        idempotency_key=f"diagnostic-attempt-{uuid4()}",
    )

    assert passed["state"] == "passed_pending_confirmation"
    proposed_revision_id = str(passed["proposed_plan_revision_id"])
    assert proposed_revision_id
    active_before = conn.execute(
        "SELECT revision_id FROM tutor_track_active_plans WHERE user_id = %s AND track_id = %s",
        (user_id, track_id),
    ).fetchone()
    assert active_before is not None
    assert str(active_before["revision_id"]) != proposed_revision_id
    statuses_before = {
        str(row["status"])
        for row in conn.execute(
            "SELECT status FROM tutor_track_node_progress WHERE user_id = %s AND track_id = %s",
            (user_id, track_id),
        ).fetchall()
    }
    assert "diagnostic_skipped" not in statuses_before

    impact = passed["impact"]
    confirmed = service.confirm_diagnostic_skip(
        user_id=user_id,
        track_id=track_id,
        module_key="foundations",
        session_id=str(session["session_id"]),
        expected_track_version=int(impact["expected_track_version"]),
        expected_session_version=int(passed["version"]),
        idempotency_key=f"diagnostic-confirm-{uuid4()}",
    )
    assert confirmed["state"] == "confirmed"
    active_after = conn.execute(
        "SELECT revision_id FROM tutor_track_active_plans WHERE user_id = %s AND track_id = %s",
        (user_id, track_id),
    ).fetchone()
    assert active_after is not None
    assert str(active_after["revision_id"]) == proposed_revision_id
    statuses_after = conn.execute(
        """
        SELECT knowledge_key, status FROM tutor_track_node_progress
        WHERE user_id = %s AND track_id = %s ORDER BY knowledge_key
        """,
        (user_id, track_id),
    ).fetchall()
    assert statuses_after == [
        {"knowledge_key": "python.functions", "status": "diagnostic_skipped"},
        {"knowledge_key": "python.variables", "status": "diagnostic_skipped"},
    ]



def test_module_diagnostic_rejects_direct_request_after_module_boundary(diagnostic_scope) -> None:
    conn, user_id, track_id = diagnostic_scope
    conn.execute(
        """
        UPDATE tutor_track_node_progress
        SET status = 'completed', started_at = COALESCE(started_at, %s),
            completed_at = %s, version = version + 1
        WHERE user_id = %s AND track_id = %s AND knowledge_key = 'python.variables'
        """,
        (
            datetime(2026, 8, 11, 3, tzinfo=UTC),
            datetime(2026, 8, 11, 4, tzinfo=UTC),
            user_id,
            track_id,
        ),
    )
    conn.execute(
        "UPDATE tutor_track_node_progress SET status = 'available' WHERE user_id = %s AND track_id = %s AND knowledge_key = 'python.functions'",
        (user_id, track_id),
    )
    conn.execute(
        "UPDATE tutor_learning_tracks SET current_knowledge_key = 'python.functions' WHERE user_id = %s AND id = %s",
        (user_id, track_id),
    )
    conn.commit()

    with pytest.raises(ExerciseGateServiceError) as raised:
        _service(conn, _success).create_diagnostic(
            user_id=user_id,
            track_id=track_id,
            module_key="foundations",
            expected_track_version=1,
            idempotency_key=f"diagnostic-after-boundary-{uuid4()}",
        )
    assert raised.value.code == "MODULE_DIAGNOSTIC_NOT_ALLOWED"
    assert raised.value.status_code == 409
    assert conn.execute(
        "SELECT count(*)::int AS count FROM tutor_module_diagnostic_sessions WHERE user_id = %s",
        (user_id,),
    ).fetchone() == {"count": 0}
