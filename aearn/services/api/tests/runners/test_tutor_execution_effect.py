from __future__ import annotations

from datetime import timedelta

from aearn_shared.execution import ExecutionAction, ExecutionBudgetV1
from app.agents.harness.contracts import TutorEffectProposal, TutorEffectStatus, payload_fields_from_mapping
from app.services.tutor.execution import (
    EXECUTION_EFFECT_TYPE,
    ExecutionIntentRepository,
    build_execution_effect_handlers,
)
from app.services.tutor.persistence import PostgresTutorRepository

from tests.support.tutor_execution_support import record_healthy_executor, registry_with_python_lock, seed_python_exercise, select_execution_skill


def test_execution_effect_persists_one_job_inside_child02_effect_transaction_and_replays(tutor_persistence) -> None:
    fixture = tutor_persistence
    now = fixture.run.policy.deadline - timedelta(days=1)
    accepted = fixture.repository.accept_input(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        idempotency_key="execution-input",
        content="def answer():\n    return 42\n",
    )
    select_execution_skill(fixture, input_revision=accepted.input_revision)
    exercise_id = seed_python_exercise(fixture)
    registry = registry_with_python_lock()
    record_healthy_executor(fixture, registry=registry, now=now)
    execution = ExecutionIntentRepository(
        fixture.connection,
        registry=registry,
        executor_enabled=lambda: True,
        clock=lambda: now,
    )
    proof = execution.issue_intent(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        source_message_id=accepted.message_id,
        exercise_id=exercise_id,
        action=ExecutionAction.TEST,
        budget=ExecutionBudgetV1(max_wall_clock_seconds=15, max_output_bytes=8192),
        now=now,
    )
    lease = fixture.repository.acquire_lease(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        owner_id="execution-effect-worker",
        now=now,
        duration_seconds=60,
    )
    assert lease is not None
    repository = PostgresTutorRepository(
        fixture.connection,
        effect_handlers=build_execution_effect_handlers(execution),
    )
    proposal = TutorEffectProposal(
        effect_id="execution-effect-1",
        effect_type=EXECUTION_EFFECT_TYPE,
        expected_input_revision=accepted.input_revision,
        payload=payload_fields_from_mapping({"intent_proof_id": proof.proof_id}),
    )

    first = repository.commit_effect_if_current(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        lease=lease,
        proposal=proposal,
        idempotency_key="execution-effect-key",
        now=now,
    )
    replayed = repository.commit_effect_if_current(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        lease=lease,
        proposal=proposal,
        idempotency_key="execution-effect-key",
        now=now,
    )

    assert first.result.status is TutorEffectStatus.COMMITTED
    assert first.result.commit_id is not None
    assert first.committer_invoked is True
    assert replayed.replayed is True
    assert replayed.result.commit_id == first.result.commit_id
    job_rows = fixture.connection.execute(
        """
        SELECT state, runtime_id, lock_fingerprint, result_json::text AS result_json
        FROM tutor_execution_jobs
        WHERE run_id = %s
        """,
        (fixture.run.run_id,),
    ).fetchall()
    assert len(job_rows) == 1
    assert job_rows[0]["state"] == "pending"
    assert job_rows[0]["runtime_id"] == "python-stdout-v1"
    assert len(str(job_rows[0]["lock_fingerprint"])) == 64
    assert job_rows[0]["result_json"] is None
    intent = fixture.connection.execute(
        """
        SELECT consumed_at, consumed_by_effect_id
        FROM tutor_execution_intents
        WHERE id = %s
        """,
        (proof.proof_id,),
    ).fetchone()
    assert intent is not None
    assert intent["consumed_at"] is not None
    assert intent["consumed_by_effect_id"] is not None


def test_disabled_executor_denies_effect_without_creating_a_job(tutor_persistence) -> None:
    fixture = tutor_persistence
    now = fixture.run.policy.deadline - timedelta(days=1)
    accepted = fixture.repository.accept_input(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        idempotency_key="disabled-execution-input",
        content="print('no host fallback')",
    )
    select_execution_skill(fixture, input_revision=accepted.input_revision)
    execution = ExecutionIntentRepository(
        fixture.connection,
        registry=registry_with_python_lock(),
        executor_enabled=lambda: False,
        clock=lambda: now,
    )
    proof = execution.issue_intent(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        source_message_id=accepted.message_id,
        exercise_id=seed_python_exercise(fixture),
        action=ExecutionAction.RUN,
        budget=ExecutionBudgetV1(max_wall_clock_seconds=15, max_output_bytes=8192),
        now=now,
    )
    lease = fixture.repository.acquire_lease(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        owner_id="disabled-execution-worker",
        now=now,
        duration_seconds=60,
    )
    assert lease is not None
    repository = PostgresTutorRepository(
        fixture.connection,
        effect_handlers=build_execution_effect_handlers(execution),
    )
    receipt = repository.commit_effect_if_current(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        lease=lease,
        proposal=TutorEffectProposal(
            effect_id="disabled-execution-effect",
            effect_type=EXECUTION_EFFECT_TYPE,
            expected_input_revision=accepted.input_revision,
            payload=payload_fields_from_mapping({"intent_proof_id": proof.proof_id}),
        ),
        idempotency_key="disabled-execution-key",
        now=now,
    )

    assert receipt.result.status is TutorEffectStatus.DENIED
    count = fixture.connection.execute(
        "SELECT count(*) AS count FROM tutor_execution_jobs WHERE run_id = %s",
        (fixture.run.run_id,),
    ).fetchone()
    assert count == {"count": 0}
