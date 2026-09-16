from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict


# Do not import project/database helpers until the runner proves that this is the
# dedicated repair database. The imported legacy fixtures probe DATABASE_URL at
# module import time.
def _require_dedicated_database() -> None:
    expected = os.environ.get("AEARN_TEST_DATABASE_NAME")
    database_url = os.environ.get("DATABASE_URL")
    if not expected or not database_url:
        pytest.skip(
            "Gate catalog mapping tests require AEARN_TEST_DATABASE_NAME and DATABASE_URL",
            allow_module_level=True,
        )
    try:
        info = conninfo_to_dict(database_url)
    except (TypeError, ValueError, psycopg.Error):
        pytest.skip(
            "Gate catalog mapping tests require a valid DATABASE_URL",
            allow_module_level=True,
        )
    actual = str(info.get("dbname") or "")
    host = str(info.get("host") or "")
    if (
        actual != expected
        or not expected.startswith("aearn_repair_")
        or expected.casefold() in {"postgres", "template0", "template1"}
        or host not in {"127.0.0.1", "localhost", "::1"}
    ):
        pytest.skip(
            "Gate catalog mapping tests refuse non-dedicated or template PostgreSQL databases",
            allow_module_level=True,
        )


_require_dedicated_database()

pytest_plugins = ("tests.learning.test_lesson_document_repository",)

from app.services.learning.item_bank.repository import (  # noqa: E402
    PostgresLearningItemBankRepository,
)  # noqa: E402
from app.services.learning.lesson_contracts import (  # noqa: E402
    calculate_lesson_impact,
    canonical_source_set_hash,
)  # noqa: E402
from app.services.learning.practice.repository import PostgresExerciseGateRepository  # noqa: E402
from app.services.learning.practice.service import ExerciseGateService  # noqa: E402
from app.services.learning.practice.gate_selection import gate_binding_compatibility  # noqa: E402
from app.services.learning.track_repository import PostgresLearningTrackRepository  # noqa: E402
from tests.learning.test_learning_item_bank_repository import (  # noqa: E402
    _import as import_learning_item,
    _publish as publish_learning_item,
    _source as learning_item_source,
)
from tests.support.learning_track_support import sample_plan  # noqa: E402
from tests.support.lesson_document_support import sample_lesson_document  # noqa: E402


def _knowledge_binding_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "gate_kind": "knowledge_check",
        "assessment_contract_version": "knowledge_check_v1",
        "slot_capabilities_json": ["python"],
        "node_capabilities_json": ["python"],
        "binding_knowledge_key": "n1_1",
        "scope_knowledge_key": "n1_1",
        "scope_catalog_knowledge_key": "python.catalog.variables",
        "requirement_kind": "required",
        "exercise_language_id": "python",
        "scope_language_id": "python",
        "exercise_capabilities_json": ["python"],
        "exercise_type": "static_code_reasoning",
        "source_kind": "curated_fixture",
        "execution_required": False,
        "runtime_profile_key": None,
        "execution_requirement": "forbidden",
        "latest_publication_state": "published",
        "item_kind": "knowledge_check",
        "item_purpose": "knowledge_check",
        "item_knowledge_key": "python.catalog.variables",
        "item_language_id": "python",
        "item_capabilities_json": ["python"],
        "materialization_handle": "li:" + "a" * 64,
        "item_handle": "li:" + "a" * 64,
        "materialization_content_hash": "b" * 64,
        "item_content_hash": "b" * 64,
        "materialization_exercise_version_id": "exercise-version",
        "exercise_version_id": "exercise-version",
        "materialization_exercise_key": "python.catalog.variables.check",
        "exercise_key": "python.catalog.variables.check",
        "materialization_exercise_version": "v1",
        "exercise_version": "v1",
        "materialization_exercise_content_hash": "c" * 64,
        "exercise_content_hash": "c" * 64,
        "materialization_rubric_hash": "d" * 64,
        "stored_rubric_hash": "d" * 64,
        "item_public_json": {
            "content": {"type": "knowledge_check", "response_kind": "short_text"}
        },
        "reference_answer_json": {"accepted_answers": ["42"]},
        "score_policy_json": {"kind": "static_exact", "threshold": 1},
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, True),
        (
            {"scope_catalog_knowledge_key": None, "item_knowledge_key": "n1_1"},
            True,
        ),
        ({"item_knowledge_key": "n1_1"}, False),
        ({"item_knowledge_key": "python.catalog.variables.alias"}, False),
        ({"binding_knowledge_key": "python.catalog.variables"}, False),
        ({"item_language_id": "javascript"}, False),
        ({"item_capabilities_json": ["python.io"]}, False),
    ],
)
def test_catalog_mapping_compatibility_is_exact_and_keeps_scope_identity(
    overrides: Mapping[str, object], expected: bool
) -> None:
    row = _knowledge_binding_row(**dict(overrides))
    assert gate_binding_compatibility(row).actionable is expected


def _mapped_plan(*, scope_key: str, catalog_key: str):
    plan = sample_plan()
    module = plan.modules[0]
    first, second = module.nodes
    mapped_nodes = (
        replace(first, knowledge_key=scope_key, catalog_knowledge_key=catalog_key),
        replace(second, prerequisite_keys=(scope_key,)),
    )
    return replace(plan, modules=(replace(module, nodes=mapped_nodes),))


def _publish_lesson_for_scope(
    conn,
    repository,
    user_id: str,
    track_id: str,
    snapshot,
    *,
    knowledge_key: str,
    standard_document,
    personalized_document,
):
    scope = repository.read_scope(
        user_id=user_id,
        track_id=track_id,
        knowledge_key=knowledge_key,
    )
    assert scope.module_key == "foundations"
    assert scope.module_diagnostic_allowed is False
    run, replayed = repository.create_or_replay_authoring_run(
        scope=scope,
        run_kind="prepare",
        idempotency_key=f"lesson-mapped-{knowledge_key}",
        request_hash="c" * 64,
        profile_hash="d" * 64,
    )
    assert replayed is False
    conn.commit()
    with conn.transaction():
        claimed = repository.claim_authoring_run(
            run_id=run.run_id,
            owner="test-worker",
            now=datetime(2026, 9, 13, tzinfo=UTC),
        )
        assert claimed is not None
        running = repository.mark_authoring_running(
            run_id=claimed.run_id,
            lease_generation=claimed.lease_generation,
        )
        source_hash = canonical_source_set_hash((snapshot,))
        repository.set_authoring_source_set(
            run_id=running.run_id,
            lease_generation=running.lease_generation,
            source_set_hash=source_hash,
        )
    with conn.transaction():
        return repository.publish_authoring_result(
            run=running,
            standard_document=standard_document,
            personalized_document=personalized_document,
            snapshots=(snapshot,),
            standard_quality={"passed": True},
            personalized_quality={"passed": True},
            standard_change_summary={},
            personalized_change_summary={"personalized": True},
            generator_version="lesson-gate-catalog-test-v1",
            policy_version="lesson-quality-test-v1",
            source_set_hash=source_hash,
            impact=calculate_lesson_impact(standard_document, personalized_document),
            now=datetime(2026, 9, 13, tzinfo=UTC),
        )


def _knowledge_check_documents(*, knowledge_key: str):
    standard = replace(
        sample_lesson_document(),
        knowledge_key=knowledge_key,
        coverage_keys=(knowledge_key,),
    )
    standard_blocks = list(standard.blocks)
    standard_gate = standard_blocks[7]
    standard_blocks[7] = replace(
        standard_gate,
        assessment_contract_version="knowledge_check_v1",
        required_capabilities=("python",),
    )

    personalized = replace(
        sample_lesson_document(personalized=True),
        knowledge_key=knowledge_key,
        coverage_keys=(knowledge_key,),
    )
    personalized_blocks = list(personalized.blocks)
    personalized_gate = personalized_blocks[7]
    personalized_blocks[7] = replace(
        personalized_gate,
        assessment_contract_version="knowledge_check_v1",
        required_capabilities=("python",),
    )
    return replace(standard, blocks=tuple(standard_blocks)), replace(
        personalized, blocks=tuple(personalized_blocks)
    )


def test_explicit_catalog_plan_prepares_gate_and_attempt_keeps_node_identity(
    lesson_repo,
) -> None:
    conn, lesson_repository, user_id, _base_track_id, snapshot = lesson_repo
    scope_key = "n1_1"
    catalog_key = f"python.catalog.{uuid4().hex[:12]}"
    source, validation = learning_item_source(
        f"test.gate.catalog.{uuid4().hex[:12]}",
        knowledge_key=catalog_key,
        capability="python",
    )
    imported = import_learning_item(
        PostgresLearningItemBankRepository(conn),
        source,
        validation,
        key=f"gate-catalog:{catalog_key}",
    )
    publication = publish_learning_item(
        conn, imported.handle, f"gate-catalog:{catalog_key}"
    )
    assert publication.state == "published"

    track_id = PostgresLearningTrackRepository(conn).create_track(
        user_id=user_id,
        language_id="python",
        goal_text="Learn mapped Python variables",
        target_level="beginner",
        plan=_mapped_plan(scope_key=scope_key, catalog_key=catalog_key),
    )
    standard, personalized = _knowledge_check_documents(knowledge_key=scope_key)
    published_lesson = _publish_lesson_for_scope(
        conn,
        lesson_repository,
        user_id,
        track_id,
        snapshot,
        knowledge_key=scope_key,
        standard_document=standard,
        personalized_document=personalized,
    )
    started = lesson_repository.start_assignment(
        user_id=user_id,
        track_id=track_id,
        knowledge_key=scope_key,
        assignment_id=published_lesson.assignment_id,
        expected_assignment_version=1,
        expected_progress_version=1,
        now=datetime(2026, 9, 13, 1, tzinfo=UTC),
    )

    repository = PostgresExerciseGateRepository(conn)
    scope = repository.read_scope(
        user_id=user_id, track_id=track_id, knowledge_key=scope_key
    )
    assert scope.knowledge_key == scope_key
    assert scope.catalog_knowledge_key == catalog_key
    assert scope.catalog_knowledge_key_source == "explicit_catalog_knowledge_key"

    service = ExerciseGateService(conn)
    prepared = service.prepare_gate(
        user_id=user_id,
        track_id=track_id,
        knowledge_key=scope_key,
        gate_key="python.variables.basic",
        expected_track_version=1,
        expected_progress_version=int(started["progress_version"]),
        idempotency_key=f"prepare-catalog-{catalog_key}",
    )
    prepared_gate = prepared["gate"]
    assert prepared_gate["exercise"]["exercise_key"] == source.public.item_key

    gate = repository.read_gate(
        user_id=user_id,
        track_id=track_id,
        knowledge_key=scope_key,
        gate_key="python.variables.basic",
    )
    assert gate["scope_knowledge_key"] == scope_key
    assert gate["scope_catalog_knowledge_key"] == catalog_key
    assert gate["catalog_knowledge_key_source"] == "explicit_catalog_knowledge_key"
    assert gate["binding_knowledge_key"] == scope_key
    assert gate["item_knowledge_key"] == catalog_key

    listed_gate = next(
        item
        for item in repository.read_gates(
            user_id=user_id,
            track_id=track_id,
            knowledge_key=scope_key,
        )
        if item["gate_key"] == "python.variables.basic"
    )
    assert listed_gate["scope_knowledge_key"] == scope_key
    assert listed_gate["scope_catalog_knowledge_key"] == catalog_key
    assert (
        listed_gate["catalog_knowledge_key_source"] == "explicit_catalog_knowledge_key"
    )
    assert listed_gate["binding_knowledge_key"] == scope_key
    assert listed_gate["item_knowledge_key"] == catalog_key

    result = service.attempt_gate(
        user_id=user_id,
        track_id=track_id,
        knowledge_key=scope_key,
        gate_key="python.variables.basic",
        attempt_type="submit",
        submission="42",
        expected_track_version=1,
        expected_progress_version=int(started["progress_version"]),
        expected_assignment_version=1,
        expected_gate_version=int(prepared_gate["gate_version"]),
        idempotency_key=f"submit-catalog-{catalog_key}",
    )
    assert result["knowledge_key"] == scope_key
    assert result["result"]["outcome"] == "passed"

    stored = conn.execute(
        """
        SELECT attempts.knowledge_key AS attempt_knowledge_key,
               bindings.knowledge_key AS binding_knowledge_key,
               progress.knowledge_key AS progress_knowledge_key,
               items.knowledge_key AS item_knowledge_key
        FROM tutor_exercise_attempts AS attempts
        JOIN tutor_lesson_gate_bindings AS bindings
          ON bindings.id = attempts.gate_binding_id
        JOIN tutor_track_node_progress AS progress
          ON progress.track_id = attempts.track_id
         AND progress.user_id = attempts.user_id
         AND progress.knowledge_key = attempts.knowledge_key
        JOIN tutor_learning_item_practice_materializations AS materializations
          ON materializations.exercise_version_id = attempts.exercise_version_id
        JOIN tutor_learning_item_versions AS items
          ON items.id = materializations.version_id
        WHERE attempts.id = %s
        """,
        (result["attempt_id"],),
    ).fetchone()
    assert stored == {
        "attempt_knowledge_key": scope_key,
        "binding_knowledge_key": scope_key,
        "progress_knowledge_key": scope_key,
        "item_knowledge_key": catalog_key,
    }
    route = conn.execute("SELECT current_knowledge_key FROM tutor_learning_tracks WHERE id=%s", (track_id,)).fetchone()
    assert route == {"current_knowledge_key":"python.functions"}
    assert conn.execute("SELECT status FROM tutor_track_node_progress WHERE track_id=%s AND knowledge_key=%s",(track_id,scope_key)).fetchone() == {"status":"completed"}
