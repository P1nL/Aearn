from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from aearn_shared.execution import ExecutionAction, SafeExecutionResultV1, SafeExecutionStatus

from app.services.learning.contracts import ExecutionComposition
from app.services.learning.practice.contracts import (
    ExecutionRequirement,
    ExerciseAttemptType,
    ExercisePrivateRubric,
    ExerciseSourceKind,
    ExerciseType,
    ExerciseVersion,
    GateRequirementKind,
    LessonGateBinding,
    canonical_hash,
)
from app.services.learning.practice.fixtures import CuratedExerciseFixture
from app.services.learning.practice.repository import PostgresExerciseGateRepository, request_hash
from app.services.learning.practice.service import ExerciseGateService, ExerciseGateServiceError
from app.services.repositories.local_user_data_repository import export_user_data, reset_user_data
from app.services.tutor.cutover import HarnessCutoverService
from app.services.tutor.execution import ExecutionIntentRepository
from tutor_execution_support import registry_with_python_lock
from test_lesson_document_repository import _publish

pytest_plugins = ("test_lesson_document_repository",)


def _success(_attempt, _submission: str) -> SafeExecutionResultV1:
    return SafeExecutionResultV1(
        status=SafeExecutionStatus.SUCCESS,
        stdout="3\n",
        passed_test_count=2,
        total_test_count=2,
        diagnostic_code="fixture_success",
    )


def test_required_gate_submit_updates_mastery_and_completes_node(lesson_repo) -> None:
    conn, lesson_repository, user_id, track_id, snapshot = lesson_repo
    published = _publish(conn, lesson_repository, user_id, track_id, snapshot, action="initial")
    started = lesson_repository.start_assignment(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        assignment_id=published.assignment_id,
        expected_assignment_version=1,
        expected_progress_version=1,
        now=datetime(2026, 8, 11, 1, tzinfo=UTC),
    )
    conn.commit()
    service = ExerciseGateService(
        conn,
        composition=ExecutionComposition.DEVELOPMENT,
        local_runner_available=True,
        local_runner=_success,
    )
    prepared = service.prepare_gate(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        gate_key="python.variables.basic",
        expected_track_version=1,
        expected_progress_version=int(started["progress_version"]),
        idempotency_key=f"prepare-{uuid4()}",
    )
    gate = prepared["gate"]
    assert gate["requirement_kind"] == "required"
    assert gate["execution_tier"] == "teaching_local"

    result = service.attempt_gate(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        gate_key="python.variables.basic",
        attempt_type="submit",
        submission="value = 3\nprint(value)",
        expected_track_version=1,
        expected_progress_version=int(started["progress_version"]),
        expected_assignment_version=1,
        expected_gate_version=int(gate["gate_version"]),
        idempotency_key=f"submit-{uuid4()}",
    )
    conn.commit()
    assert result["status"] == "terminal"
    assert result["result"]["outcome"] == "passed"
    assert result["route_changed"] is True
    progress = conn.execute(
        "SELECT status FROM tutor_track_node_progress WHERE track_id = %s AND knowledge_key = 'python.variables'",
        (track_id,),
    ).fetchone()
    assert progress is not None and progress["status"] == "completed"
    evidence = conn.execute(
        "SELECT evidence_effect FROM tutor_mastery_evidence WHERE track_id = %s AND source_receipt_id = %s",
        (track_id, result["attempt_id"]),
    ).fetchone()
    assert evidence is not None and evidence["evidence_effect"] == "reinforcing"

    with conn.transaction():
        conn.execute("SELECT set_config('aearn.learning_track_purge_user_id', %s, true)", (user_id,))
        conn.execute("DELETE FROM tutor_exercise_attempt_results WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM tutor_exercise_attempt_submissions WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM tutor_exercise_attempts WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM tutor_review_items WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM tutor_review_sessions WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM tutor_review_schedule_events WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM tutor_review_schedule_states WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM tutor_lesson_gate_states WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM tutor_lesson_gate_bindings WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM tutor_api_idempotency_records WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM tutor_mastery_states WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM tutor_mastery_evidence WHERE user_id = %s", (user_id,))
    conn.commit()


def test_exercise_attempt_reuses_existing_execution_queue(lesson_repo) -> None:
    conn, lesson_repository, user_id, track_id, snapshot = lesson_repo
    published = _publish(conn, lesson_repository, user_id, track_id, snapshot, action="initial")
    started = lesson_repository.start_assignment(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        assignment_id=published.assignment_id,
        expected_assignment_version=1,
        expected_progress_version=1,
        now=datetime(2026, 8, 11, 1, tzinfo=UTC),
    )
    repository = PostgresExerciseGateRepository(conn)
    gates = repository.prepare_gates(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        expected_track_version=1,
        expected_progress_version=int(started["progress_version"]),
        now=datetime(2026, 8, 11, 2, tzinfo=UTC),
    )
    gate = gates[0]
    attempt_body = {
        "track_id": track_id,
        "gate_key": "python.variables.basic",
        "attempt_type": "run",
        "submission_hash": "b" * 64,
    }
    attempt = repository.create_gate_attempt(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        gate_key="python.variables.basic",
        attempt_type=ExerciseAttemptType.RUN,
        submission="value = 3\nprint(value)",
        expected_track_version=1,
        expected_progress_version=int(started["progress_version"]),
        expected_assignment_version=1,
        expected_gate_version=int(gate["gate_version"]),
        idempotency_key=f"execution-attempt-{uuid4()}",
        request_hash=request_hash(attempt_body),
        now=datetime(2026, 8, 11, 3, tzinfo=UTC),
    )
    registry = registry_with_python_lock()
    executor_id = f"gate-executor-{uuid4()}"
    conn.execute(
        """
        INSERT INTO tutor_executor_health (
          executor_id, service_version, registry_fingerprint, verified_runtime_ids_json,
          status, availability_code, last_heartbeat_at
        ) VALUES (%s, 'container-executor-v1', %s, %s::jsonb, 'available', 'executor_available', %s)
        """,
        (
            executor_id,
            registry.fingerprint,
            json.dumps(["python-stdout-v1"]),
            datetime(2026, 8, 11, 3, tzinfo=UTC),
        ),
    )
    execution = ExecutionIntentRepository(
        conn,
        registry=registry,
        executor_enabled=lambda: True,
        clock=lambda: datetime(2026, 8, 11, 3, tzinfo=UTC),
    )
    job = execution.create_or_replay_exercise_job(
        user_id=user_id,
        attempt_id=str(attempt["id"]),
        submission_id=str(attempt["submission_id"]),
        exercise_version_id=str(attempt["exercise_version_id"]),
        action=ExecutionAction.RUN,
    )
    replay = execution.create_or_replay_exercise_job(
        user_id=user_id,
        attempt_id=str(attempt["id"]),
        submission_id=str(attempt["submission_id"]),
        exercise_version_id=str(attempt["exercise_version_id"]),
        action=ExecutionAction.RUN,
    )
    assert replay.job_id == job.job_id
    assert job.owner_kind == "exercise_attempt"
    assert job.exercise_attempt_id == str(attempt["id"])
    assert job.effect_id is None and job.conversation_id is None and job.run_id is None
    intent = conn.execute(
        """
        SELECT source_kind, origin, conversation_id, run_id, source_message_id,
               exercise_id, exercise_attempt_id, exercise_submission_id
        FROM tutor_execution_intents WHERE id = %s
        """,
        (job.intent_proof_id,),
    ).fetchone()
    assert intent is not None
    assert intent["source_kind"] == "exercise_submission"
    assert intent["origin"] == "exercise_gate"
    assert intent["conversation_id"] is None and intent["run_id"] is None
    assert intent["source_message_id"] is None and intent["exercise_id"] is None
    assert str(intent["exercise_attempt_id"]) == str(attempt["id"])
    assert str(intent["exercise_submission_id"]) == str(attempt["submission_id"])

    with conn.transaction():
        conn.execute("SELECT set_config('aearn.learning_track_purge_user_id', %s, true)", (user_id,))
        conn.execute("DELETE FROM tutor_exercise_execution_links WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM tutor_execution_jobs WHERE user_id = %s AND owner_kind = 'exercise_attempt'", (user_id,))
        conn.execute("DELETE FROM tutor_execution_intents WHERE user_id = %s AND source_kind = 'exercise_submission'", (user_id,))
        conn.execute("DELETE FROM tutor_exercise_attempt_submissions WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM tutor_exercise_attempts WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM tutor_review_items WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM tutor_review_sessions WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM tutor_review_schedule_events WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM tutor_review_schedule_states WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM tutor_lesson_gate_states WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM tutor_lesson_gate_bindings WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM tutor_executor_health WHERE executor_id = %s", (executor_id,))
        conn.execute("DELETE FROM tutor_api_idempotency_records WHERE user_id = %s", (user_id,))
    conn.commit()


def test_gate_export_reset_and_cutover_inventory_redact_private_submission(lesson_repo) -> None:
    conn, lesson_repository, user_id, track_id, snapshot = lesson_repo
    published = _publish(conn, lesson_repository, user_id, track_id, snapshot, action="initial")
    started = lesson_repository.start_assignment(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        assignment_id=published.assignment_id,
        expected_assignment_version=1,
        expected_progress_version=1,
        now=datetime(2026, 8, 11, 1, tzinfo=UTC),
    )
    conn.commit()
    service = ExerciseGateService(
        conn,
        composition=ExecutionComposition.DEVELOPMENT,
        local_runner_available=True,
        local_runner=_success,
    )
    prepared = service.prepare_gate(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        gate_key="python.variables.basic",
        expected_track_version=1,
        expected_progress_version=int(started["progress_version"]),
        idempotency_key=f"prepare-export-{uuid4()}",
    )
    gate = prepared["gate"]
    hint = service.hint(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        gate_key="python.variables.basic",
        expected_gate_version=int(gate["gate_version"]),
        idempotency_key=f"hint-export-{uuid4()}",
    )
    assert set(hint) == {
        "hint_id", "hint_level", "hint_policy_version", "safe_hint",
        "gate_version", "created_at", "idempotent_replayed",
    }
    result = service.attempt_gate(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        gate_key="python.variables.basic",
        attempt_type="submit",
        submission="value = 3\nprint(value)",
        expected_track_version=1,
        expected_progress_version=int(started["progress_version"]),
        expected_assignment_version=1,
        expected_gate_version=int(hint["gate_version"]),
        idempotency_key=f"submit-export-{uuid4()}",
    )
    conn.commit()
    exercise_version_id = str(result["exercise_version_id"])

    exported = export_user_data(conn, user_id)
    assert len(exported["lesson_gates"]) == 1
    assert len(exported["exercise_attempt_summaries"]) == 1
    assert exported["exercise_attempt_summaries"][0]["submission_hash"]
    serialized = json.dumps(exported, ensure_ascii=False).casefold()
    assert "value = 3" not in serialized
    assert "private_test_bundle" not in serialized
    assert "reference_answer" not in serialized
    assert exported["redaction"]["private_rubrics"] == "omitted"
    assert exported["redaction"]["exercise_submission_content"] == "omitted"

    inventory = HarnessCutoverService(conn)._inventory(user_id)
    assert inventory.target_counts["tutor_lesson_gate_states"] == 1
    assert inventory.target_counts["tutor_exercise_attempts"] == 1

    reset = reset_user_data(conn, user_id)
    conn.commit()
    assert reset["summary"]["counts"]["lesson_gates"] == 0
    assert reset["summary"]["counts"]["exercise_attempts"] == 0
    assert reset["summary"]["counts"]["module_diagnostics"] == 0
    assert conn.execute(
        "SELECT 1 FROM tutor_exercise_versions WHERE id = %s",
        (exercise_version_id,),
    ).fetchone() is not None


def test_static_only_gate_submit_is_deterministic_and_run_is_hidden_server_side(lesson_repo) -> None:
    conn, lesson_repository, user_id, track_id, snapshot = lesson_repo
    published = _publish(conn, lesson_repository, user_id, track_id, snapshot, action="initial")
    started = lesson_repository.start_assignment(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        assignment_id=published.assignment_id,
        expected_assignment_version=1,
        expected_progress_version=1,
        now=datetime(2026, 8, 11, 1, tzinfo=UTC),
    )
    repository = PostgresExerciseGateRepository(conn)
    exercise = ExerciseVersion(
        language_id="python",
        exercise_key=f"python.variables.static.{uuid4().hex[:10]}",
        exercise_type=ExerciseType.STATIC_CODE_REASONING,
        version="v1",
        source_kind=ExerciseSourceKind.CURATED_FIXTURE,
        title="判断变量绑定语义",
        learner_prompt={"text": "输入 immutable。"},
        starter_artifact={"content": ""},
        required_capabilities=("python.variables",),
        runtime_profile_id=None,
        execution_required=False,
        public_feedback_policy_version="lesson_gate_feedback_v1",
    )
    rubric = ExercisePrivateRubric(
        rubric_version="v1",
        private_test_bundle=({"case_type": "static", "order_index": 0},),
        reference_answer={"accepted_answers": ["immutable"]},
        score_policy={"kind": "exact_normalized", "threshold": 0.8},
    )
    exercise_version_id = repository.ensure_curated_fixture(
        CuratedExerciseFixture(exercise=exercise, rubric=rubric),
        now=datetime(2026, 8, 11, 2, tzinfo=UTC),
    )
    slot = conn.execute(
        "SELECT * FROM tutor_lesson_gate_slots WHERE document_id = %s AND gate_key = 'python.variables.basic'",
        (published.personalized_document_id,),
    ).fetchone()
    assert slot is not None
    binding = LessonGateBinding(
        gate_key="python.variables.basic",
        exercise_key=exercise.exercise_key,
        exercise_version=exercise.version,
        requirement_kind=GateRequirementKind.REQUIRED,
        pass_policy_version="lesson_gate_pass_v1",
        pass_threshold=0.8,
        execution_requirement=ExecutionRequirement.FORBIDDEN,
        slot_contract_hash=canonical_hash(
            {
                "gate_kind": str(slot["gate_kind"]),
                "assessment_contract_version": str(slot["assessment_contract_version"]),
                "required_capabilities": list(slot["required_capabilities_json"]),
                "learner_prompt_hash": str(slot["learner_prompt_hash"]),
            }
        ),
    )
    binding_row = conn.execute(
        """
        INSERT INTO tutor_lesson_gate_bindings (
          slot_id, document_id, user_id, track_id, knowledge_key, gate_key,
          exercise_version_id, requirement_kind, pass_policy_version, pass_threshold,
          execution_requirement, slot_contract_hash, binding_contract_hash, published_at
        ) VALUES (%s, %s, %s, %s, 'python.variables', 'python.variables.basic', %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            slot["id"], published.personalized_document_id, user_id, track_id,
            exercise_version_id, binding.requirement_kind.value, binding.pass_policy_version,
            binding.pass_threshold, binding.execution_requirement.value, binding.slot_contract_hash,
            binding.binding_contract_hash, datetime(2026, 8, 11, 2, tzinfo=UTC),
        ),
    ).fetchone()
    assert binding_row is not None
    conn.execute(
        """
        INSERT INTO tutor_lesson_gate_states (
          user_id, track_id, knowledge_key, lesson_assignment_id, document_id,
          gate_binding_id, state
        ) VALUES (%s, %s, 'python.variables', %s, %s, %s, 'available')
        """,
        (user_id, track_id, published.assignment_id, published.personalized_document_id, binding_row["id"]),
    )
    conn.commit()

    service = ExerciseGateService(conn)
    gate = service.read_gates(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
    )["items"][0]
    assert gate["execution_tier"] == "static_only"
    assert gate["allowed_actions"] == ["hint", "submit"]

    with pytest.raises(ExerciseGateServiceError) as run_error:
        service.attempt_gate(
            user_id=user_id,
            track_id=track_id,
            knowledge_key="python.variables",
            gate_key="python.variables.basic",
            attempt_type="run",
            submission="immutable",
            expected_track_version=1,
            expected_progress_version=int(started["progress_version"]),
            expected_assignment_version=1,
            expected_gate_version=int(gate["gate_version"]),
            idempotency_key=f"static-run-{uuid4()}",
        )
    assert run_error.value.code == "EXECUTION_UNAVAILABLE"
    assert conn.execute(
        "SELECT count(*)::int AS count FROM tutor_exercise_attempts WHERE user_id = %s",
        (user_id,),
    ).fetchone() == {"count": 0}

    submitted = service.attempt_gate(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        gate_key="python.variables.basic",
        attempt_type="submit",
        submission=" IMMUTABLE ",
        expected_track_version=1,
        expected_progress_version=int(started["progress_version"]),
        expected_assignment_version=1,
        expected_gate_version=int(gate["gate_version"]),
        idempotency_key=f"static-submit-{uuid4()}",
    )
    conn.commit()
    assert submitted["status"] == "terminal"
    assert submitted["result"]["outcome"] == "passed"
    assert submitted["result"]["safe_feedback"]["execution_claim"] == "not_run"
    assert submitted["execution_tier"] == "static_only"
    reset_user_data(conn, user_id)
    conn.commit()
