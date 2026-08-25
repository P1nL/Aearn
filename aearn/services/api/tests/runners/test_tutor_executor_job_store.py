"""Serial PostgreSQL lifecycle coverage for the isolated executor store.

The test imports only the executor's pure PostgreSQL store through its source
tree. It does not import the Docker client or make the API runtime depend on
the executor package.
"""
from __future__ import annotations

import importlib
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from app.db.connection import connect

from tests.support.tutor_execution_support import create_pending_execution_job


def _cleanup_committed_fixture(
    *,
    user_id: str,
    conversation_id: str,
    run_id: str,
    exercise_id: str,
) -> None:
    """Remove only the fixture rows made visible for a cross-connection test."""

    with connect() as conn:
        with conn.transaction():
            relation = conn.execute(
                """
                SELECT knowledge_points.id AS knowledge_point_id,
                       plan_modules.id AS module_id,
                       learning_plans.id AS plan_id
                FROM exercises
                JOIN knowledge_points ON knowledge_points.id = exercises.knowledge_point_id
                JOIN plan_modules ON plan_modules.id = knowledge_points.module_id
                JOIN learning_plans ON learning_plans.id = plan_modules.plan_id
                WHERE exercises.id = %s
                """,
                (exercise_id,),
            ).fetchone()
            conn.execute(
                "DELETE FROM tutor_execution_attempts WHERE job_id IN (SELECT id FROM tutor_execution_jobs WHERE run_id = %s)",
                (run_id,),
            )
            conn.execute("DELETE FROM tutor_execution_jobs WHERE run_id = %s", (run_id,))
            conn.execute("DELETE FROM tutor_execution_intents WHERE run_id = %s", (run_id,))
            conn.execute("DELETE FROM tutor_effects WHERE run_id = %s", (run_id,))
            conn.execute("DELETE FROM tutor_capability_invocations WHERE run_id = %s", (run_id,))
            conn.execute(
                "DELETE FROM tutor_curation_proposals WHERE outbox_id IN (SELECT id FROM tutor_memory_curation_outbox WHERE run_id = %s)",
                (run_id,),
            )
            conn.execute("DELETE FROM tutor_memory_curation_outbox WHERE run_id = %s", (run_id,))
            conn.execute("DELETE FROM tutor_run_traces WHERE run_id = %s", (run_id,))
            conn.execute("DELETE FROM tutor_run_checkpoints WHERE run_id = %s", (run_id,))
            conn.execute("DELETE FROM tutor_run_skill_selections WHERE run_id = %s", (run_id,))
            conn.execute("DELETE FROM tutor_run_events WHERE run_id = %s", (run_id,))
            conn.execute("DELETE FROM tutor_run_input_events WHERE run_id = %s", (run_id,))
            conn.execute("DELETE FROM tutor_runs WHERE id = %s", (run_id,))
            conn.execute("DELETE FROM tutor_messages WHERE conversation_id = %s", (conversation_id,))
            conn.execute("DELETE FROM tutor_conversations WHERE id = %s", (conversation_id,))
            conn.execute("DELETE FROM tutor_executor_health WHERE executor_id = 'test-executor'")
            if relation is not None:
                conn.execute("DELETE FROM test_cases WHERE exercise_id = %s", (exercise_id,))
                conn.execute("DELETE FROM code_blanks WHERE exercise_id = %s", (exercise_id,))
                conn.execute("DELETE FROM exercises WHERE id = %s", (exercise_id,))
                conn.execute("DELETE FROM knowledge_points WHERE id = %s", (relation["knowledge_point_id"],))
                conn.execute("DELETE FROM plan_modules WHERE id = %s", (relation["module_id"],))
                conn.execute("DELETE FROM learning_plans WHERE id = %s", (relation["plan_id"],))
            conn.execute("DELETE FROM learner_profiles WHERE user_id = %s", (user_id,))
            conn.execute("DELETE FROM idempotency_records WHERE user_id = %s", (user_id,))
            # tutor_persistence models a verified post-cutover user. Cross-
            # connection tests commit that fixture deliberately, so the durable
            # receipt must be removed before the fixture user can be deleted.
            conn.execute("DELETE FROM harness_cutovers WHERE user_id = %s", (user_id,))
            conn.execute("DELETE FROM users WHERE id = %s", (user_id,))


EXECUTOR_SOURCE = Path(__file__).resolve().parents[3] / "executor"


def _executor_repository_module():
    if str(EXECUTOR_SOURCE) not in sys.path:
        sys.path.insert(0, str(EXECUTOR_SOURCE))
    return importlib.import_module("aearn_executor.repository")


def test_expired_unreserved_claim_is_reclaimed_once_and_old_lease_cannot_reserve(tutor_persistence) -> None:
    """An expired pre-launch lease is safe to reclaim, but it cannot create twice."""

    fixture = tutor_persistence
    now = fixture.run.policy.deadline - timedelta(days=1)
    _, job_id = create_pending_execution_job(fixture, now=now)
    repository = _executor_repository_module()
    store = repository.PostgresExecutionJobStore(fixture.connection)

    first_claim = store.claim_next(executor_id="executor-one", now=now, lease_seconds=5)
    assert first_claim is not None
    assert first_claim.job.job_id == job_id
    assert first_claim.claim.lease_generation == 1

    after_expiry = now + timedelta(seconds=6)
    replacement_claim = store.claim_next(executor_id="executor-two", now=after_expiry, lease_seconds=30)
    assert replacement_claim is not None
    assert replacement_claim.job.job_id == job_id
    assert replacement_claim.claim.lease_generation == 2

    with pytest.raises(repository.ExecutionJobStoreError, match="lease"):
        store.reserve_launch(claimed=first_claim, now=after_expiry)

    reservation = store.reserve_launch(claimed=replacement_claim, now=after_expiry)
    assert reservation is not None
    assert reservation.job.launch_token is not None
    assert store.claim_next(executor_id="executor-three", now=after_expiry + timedelta(seconds=1), lease_seconds=30) is None

    row = fixture.connection.execute(
        """
        SELECT state, launch_token, lease_generation
        FROM tutor_execution_jobs
        WHERE id = %s
        """,
        (job_id,),
    ).fetchone()
    assert row == {
        "state": "launch_reserved",
        "launch_token": reservation.job.launch_token,
        "lease_generation": 2,
    }
    attempts = fixture.connection.execute(
        """
        SELECT stage, safe_diagnostic_code, lease_generation
        FROM tutor_execution_attempts
        WHERE job_id = %s
        ORDER BY attempt_sequence ASC
        """,
        (job_id,),
    ).fetchall()
    assert attempts == [
        {"stage": "claimed", "safe_diagnostic_code": "job_claimed", "lease_generation": 1},
        {"stage": "claimed", "safe_diagnostic_code": "job_reclaimed", "lease_generation": 2},
        {"stage": "launch_reserved", "safe_diagnostic_code": "launch_reserved", "lease_generation": 2},
    ]


def test_run_cancellation_before_reservation_terminalizes_without_a_launch_token(tutor_persistence) -> None:
    """A cancellation racing the claimed state is observed before Docker can start."""

    fixture = tutor_persistence
    now = fixture.run.policy.deadline - timedelta(days=1)
    _, job_id = create_pending_execution_job(fixture, now=now)
    repository = _executor_repository_module()
    store = repository.PostgresExecutionJobStore(fixture.connection)
    claimed = store.claim_next(executor_id="executor-one", now=now, lease_seconds=30)
    assert claimed is not None

    fixture.connection.execute(
        "UPDATE tutor_runs SET cancelled_at = %s WHERE id = %s",
        (now + timedelta(seconds=1), fixture.run.run_id),
    )
    assert store.reserve_launch(claimed=claimed, now=now + timedelta(seconds=1)) is None

    row = fixture.connection.execute(
        """
        SELECT state, launch_token, safe_diagnostic_code, result_json->>'status' AS result_status
        FROM tutor_execution_jobs
        WHERE id = %s
        """,
        (job_id,),
    ).fetchone()
    assert row == {
        "state": "cancelled",
        "launch_token": None,
        "safe_diagnostic_code": "execution_cancelled_before_launch",
        "result_status": "cancelled",
    }
    assert store.claim_next(executor_id="executor-two", now=now + timedelta(seconds=2), lease_seconds=30) is None


def test_independent_connections_skip_locked_before_only_one_claim_commits(tutor_persistence) -> None:
    """A held row lock is skipped rather than double-claimed by another executor."""

    fixture = tutor_persistence
    now = fixture.run.policy.deadline - timedelta(days=1)
    _, job_id = create_pending_execution_job(fixture, now=now)
    intent = fixture.connection.execute(
        "SELECT exercise_id FROM tutor_execution_intents WHERE run_id = %s",
        (fixture.run.run_id,),
    ).fetchone()
    assert intent is not None

    # The fixture normally rolls back. This one test commits only its own rows so
    # two genuinely independent psycopg connections can observe and lock them.
    fixture.connection.commit()
    try:
        repository = _executor_repository_module()
        with connect() as locker, connect() as contender:
            with locker.transaction():
                locked = locker.execute(
                    "SELECT id FROM tutor_execution_jobs WHERE id = %s FOR UPDATE",
                    (job_id,),
                ).fetchone()
                assert locked is not None
                assert str(locked["id"]) == job_id

                contender_store = repository.PostgresExecutionJobStore(contender)
                assert contender_store.claim_next(
                    executor_id="executor-contender",
                    now=now,
                    lease_seconds=30,
                ) is None

            claimed = contender_store.claim_next(
                executor_id="executor-contender",
                now=now,
                lease_seconds=30,
            )
            assert claimed is not None
            assert claimed.job.job_id == job_id
            assert claimed.claim.lease_generation == 1
            assert contender_store.claim_next(
                executor_id="executor-third",
                now=now,
                lease_seconds=30,
            ) is None
    finally:
        _cleanup_committed_fixture(
            user_id=fixture.user_id,
            conversation_id=fixture.conversation_id,
            run_id=fixture.run.run_id,
            exercise_id=str(intent["exercise_id"]),
        )


def test_expired_reserved_launch_recovers_the_original_token_without_another_reservation(tutor_persistence) -> None:
    """Recovery may adopt an existing reservation but can never allocate a second token."""

    fixture = tutor_persistence
    now = fixture.run.policy.deadline - timedelta(days=1)
    _, job_id = create_pending_execution_job(fixture, now=now)
    repository = _executor_repository_module()
    store = repository.PostgresExecutionJobStore(fixture.connection)

    first_claim = store.claim_next(executor_id="executor-one", now=now, lease_seconds=5)
    assert first_claim is not None
    first_reservation = store.reserve_launch(claimed=first_claim, now=now)
    assert first_reservation is not None
    assert first_reservation.job.launch_token is not None

    recovery_time = now + timedelta(seconds=6)
    recovered = store.claim_reserved_for_recovery(
        executor_id="executor-two",
        now=recovery_time,
        lease_seconds=30,
    )
    assert recovered is not None
    assert recovered.job.job_id == job_id
    assert recovered.job.launch_token == first_reservation.job.launch_token
    assert recovered.job.launch_generation == first_reservation.job.launch_generation == 1
    assert recovered.claim.lease_generation == 2

    with pytest.raises(repository.ExecutionJobStoreError, match="no longer eligible"):
        store.reserve_launch(claimed=recovered, now=recovery_time)

    row = fixture.connection.execute(
        """
        SELECT state, launch_token, launch_generation, lease_generation
        FROM tutor_execution_jobs
        WHERE id = %s
        """,
        (job_id,),
    ).fetchone()
    assert row == {
        "state": "launch_reserved",
        "launch_token": first_reservation.job.launch_token,
        "launch_generation": 1,
        "lease_generation": 2,
    }
