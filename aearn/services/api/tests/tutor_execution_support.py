"""Shared helpers for isolated Tutor execution persistence tests."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from aearn_shared.execution import ExecutionAction, ExecutionBudgetV1, RuntimeImageLockV1, load_runtime_catalog_registry
from app.agents.harness.contracts import TutorEffectProposal, TutorEffectStatus, payload_fields_from_mapping
from app.agents.harness.skill_catalog import CatalogSkillReference
from app.services.tutor.execution import EXECUTION_EFFECT_TYPE, ExecutionIntentRepository, build_execution_effect_handlers
from app.services.tutor.persistence import PostgresTutorRepository
from app.services.tutor.skill_selection import TutorSkillSelection


API_ROOT = Path(__file__).resolve().parents[1]
AEARN_ROOT = API_ROOT.parents[1]
EXECUTOR_ROOT = AEARN_ROOT / "infra" / "executor"


def registry_with_python_lock():
    source = load_runtime_catalog_registry(
        catalog_path=EXECUTOR_ROOT / "runtime-catalog.json",
        image_locks_path=EXECUTOR_ROOT / "image-locks.json",
    )
    entry = source.runtime("python-stdout-v1")
    lock = RuntimeImageLockV1(
        runtime_id=entry.runtime_id,
        protocol_version=entry.protocol_version,
        image_reference=f"registry.example/aearn/python@sha256:{'d' * 63}e",
        fixed_entrypoint=entry.fixed_entrypoint,
        non_root_user=entry.non_root_user,
        limits=entry.limits,
    )
    return source.__class__(
        runtimes=source.runtimes,
        locks=(lock,),
        catalog_fingerprint=source.catalog_fingerprint,
        fingerprint="e" * 64,
    )


def seed_python_exercise(fixture) -> str:
    conn = fixture.connection
    suffix = uuid4().hex[:12]
    course = conn.execute(
        """
        SELECT language_courses.id, language_courses.language, language_courses.runtime_profile_id
        FROM language_courses
        WHERE language_courses.slug = 'course_python_basic_beginner'
        """
    ).fetchone()
    assert course is not None
    plan = conn.execute(
        """
        INSERT INTO learning_plans (user_id, language_course_id, goal_text, language, target_level, mode)
        VALUES (%s, %s, %s, %s, 'beginner', 'goal_based')
        RETURNING id
        """,
        (fixture.user_id, course["id"], f"Executor test {suffix}", course["language"]),
    ).fetchone()
    assert plan is not None
    module = conn.execute(
        """
        INSERT INTO plan_modules (plan_id, title, order_index, is_skippable)
        VALUES (%s, %s, 0, false)
        RETURNING id
        """,
        (plan["id"], f"Executor module {suffix}"),
    ).fetchone()
    assert module is not None
    knowledge = conn.execute(
        """
        INSERT INTO knowledge_points (module_id, language_course_id, title, order_index)
        VALUES (%s, %s, %s, 0)
        RETURNING id
        """,
        (module["id"], course["id"], f"Executor knowledge {suffix}"),
    ).fetchone()
    assert knowledge is not None
    exercise = conn.execute(
        """
        INSERT INTO exercises (
          knowledge_point_id, runtime_profile_id, title, exercise_type,
          prompt_markdown, starter_code
        )
        VALUES (%s, %s, %s, 'implement_function', %s, %s)
        RETURNING id
        """,
        (
            knowledge["id"],
            course["runtime_profile_id"],
            f"Executor exercise {suffix}",
            "Write one safe test function.",
            "def answer():\n    return 42\n",
        ),
    ).fetchone()
    assert exercise is not None
    return str(exercise["id"])


def select_execution_skill(fixture, *, input_revision: int) -> None:
    skill = next(skill for skill in fixture.catalog.skills if skill.reference.key == "tutor.runner-execution@1.0.0")
    fixture.repository.record_skill_selection(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        input_revision=input_revision,
        selection=TutorSkillSelection(
            reference=CatalogSkillReference(skill.manifest.id, skill.manifest.version),
            manifest_hash=skill.manifest_hash,
            instruction_hash=skill.instruction_hash,
        ),
    )


def record_healthy_executor(fixture, *, registry, now: datetime) -> None:
    fixture.connection.execute(
        """
        INSERT INTO tutor_executor_health (
          executor_id, service_version, registry_fingerprint, verified_runtime_ids_json,
          status, availability_code, last_heartbeat_at
        )
        VALUES ('test-executor', 'container-executor-v1', %s, %s::jsonb, 'available', 'executor_available', %s)
        """,
        (registry.fingerprint, json.dumps(["python-stdout-v1"]), now),
    )


def create_pending_execution_job(fixture, *, now: datetime) -> tuple[ExecutionIntentRepository, str]:
    accepted = fixture.repository.accept_input(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        idempotency_key="pending-execution-input",
        content="def answer():\n    return 42\n",
    )
    select_execution_skill(fixture, input_revision=accepted.input_revision)
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
        exercise_id=seed_python_exercise(fixture),
        action=ExecutionAction.RUN,
        budget=ExecutionBudgetV1(max_wall_clock_seconds=15, max_output_bytes=8192),
        now=now,
    )
    lease = fixture.repository.acquire_lease(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        owner_id="pending-execution-worker",
        now=now,
        duration_seconds=60,
    )
    assert lease is not None
    receipt = PostgresTutorRepository(
        fixture.connection,
        effect_handlers=build_execution_effect_handlers(execution),
    ).commit_effect_if_current(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        lease=lease,
        proposal=TutorEffectProposal(
            effect_id="pending-execution-effect",
            effect_type=EXECUTION_EFFECT_TYPE,
            expected_input_revision=accepted.input_revision,
            payload=payload_fields_from_mapping({"intent_proof_id": proof.proof_id}),
        ),
        idempotency_key="pending-execution-key",
        now=now,
    )
    assert receipt.result.status is TutorEffectStatus.COMMITTED
    assert receipt.result.commit_id is not None
    return execution, receipt.result.commit_id
