from __future__ import annotations

from datetime import timedelta

from aearn_shared.execution import ExecutionAction, ExecutionBudgetV1
from app.services.tutor.execution import ExecutionIntentRepository

from tutor_execution_support import create_pending_execution_job, registry_with_python_lock, seed_python_exercise


def test_intent_issuance_rejects_cross_conversation_source_and_does_not_persist(tutor_persistence) -> None:
    fixture = tutor_persistence
    now = fixture.run.policy.deadline - timedelta(days=1)
    repository = ExecutionIntentRepository(
        fixture.connection,
        registry=registry_with_python_lock(),
        executor_enabled=lambda: True,
        clock=lambda: now,
    )

    try:
        repository.issue_intent(
            user_id=fixture.user_id,
            run_id=fixture.run.run_id,
            source_message_id="00000000-0000-0000-0000-000000000000",
            exercise_id=seed_python_exercise(fixture),
            action=ExecutionAction.DEBUG,
            budget=ExecutionBudgetV1(max_wall_clock_seconds=15, max_output_bytes=8192),
            now=now,
        )
    except ValueError as exc:
        assert str(exc) == "source_scope_denied"
    else:
        raise AssertionError("cross-scope source must be denied")

    count = fixture.connection.execute("SELECT count(*) AS count FROM tutor_execution_intents").fetchone()
    assert count == {"count": 0}


def test_job_cancellation_is_idempotent_and_remains_a_durable_request_only(tutor_persistence) -> None:
    fixture = tutor_persistence
    now = fixture.run.policy.deadline - timedelta(days=1)
    execution, job_id = create_pending_execution_job(fixture, now=now)

    execution.request_cancellation(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        job_id=job_id,
        now=now,
    )
    execution.request_cancellation(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        job_id=job_id,
        now=now,
    )

    row = fixture.connection.execute(
        """
        SELECT state, cancellation_requested_at, result_json::text AS result_json
        FROM tutor_execution_jobs
        WHERE id = %s
        """,
        (job_id,),
    ).fetchone()
    assert row is not None
    assert row["state"] == "pending"
    assert row["cancellation_requested_at"] is not None
    assert row["result_json"] is None


def test_job_cancellation_path_has_no_legacy_runner_fallback() -> None:
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "services" / "tutor" / "execution.py").read_text(
        encoding="utf-8"
    )
    assert "runtime_runner" not in source
    assert "get_runner_registry" not in source
    assert "subprocess" not in source
