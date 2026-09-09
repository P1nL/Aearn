from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4
import pytest

from app.services.learning.contracts import ExecutionComposition
from app.services.learning.item_bank.contracts import LearningItemSourceV1
from app.services.learning.item_bank.repository import PostgresLearningItemBankRepository
from app.services.learning.item_bank.validation import validate_learning_item
from app.services.learning.practice.contracts import ExecutionRequirement
from app.services.learning.practice.gate_selection import (
    GateSelectionUnavailable,
    execution_requirement_for,
    gate_binding_compatibility,
    gate_slot_is_compatible,
    select_published_knowledge_check,
)
from app.services.learning.practice.repository import PostgresExerciseGateRepository
from app.services.learning.practice.service import ExerciseGateService, ExerciseGateServiceError
from tests.learning.test_learning_item_bank_repository import (
    _import as import_learning_item,
    _publish as publish_learning_item,
    _source as learning_item_source,
)
from tests.learning.test_lesson_document_repository import (
    _database_available as database_available,
    _publish as publish_lesson,
)
from tests.support.lesson_document_support import sample_lesson_document

pytest_plugins = ("tests.learning.test_lesson_document_repository",)


class _Result:
    def __init__(self, *, rows: list[dict[str, object]] | None = None, row: dict[str, object] | None = None) -> None:
        self._rows = rows or []
        self._row = row

    def fetchall(self) -> list[dict[str, object]]:
        return self._rows

    def fetchone(self) -> dict[str, object] | None:
        return self._row


class _CandidateConnection:
    def __init__(self, materialization: Mapping[str, object]) -> None:
        self.materialization = dict(materialization)
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, sql: str, params: tuple[object, ...]) -> _Result:
        self.calls.append((sql, params))
        if "public.candidate_summary" in sql:
            return _Result(
                rows=[
                    {
                        "handle": "li:" + "a" * 64,
                        "item_key": "python.variables.knowledge",
                        "version": "v1",
                        "item_kind": "knowledge_check",
                        "purpose": "knowledge_check",
                        "knowledge_key": "python.variables",
                        "language_id": "python",
                        "difficulty": "D1",
                        "required_capabilities_json": ["python"],
                        "title": "Variables check",
                        "candidate_summary": "Choose the exact value.",
                        "allowed_interactions_json": ["respond"],
                    }
                ]
            )
        if "WHERE handle = %s" in sql and "FOR UPDATE" in sql:
            return _Result(row={"id": "item-version"})
        return _Result(row=self.materialization)


def _materialization(*, response_kind: str = "short_text") -> dict[str, object]:
    options: list[dict[str, str]] = []
    accepted = ["42"]
    if response_kind == "single_choice":
        options = [
            {"option_id": "answer.42", "label": "42"},
            {"option_id": "answer.24", "label": "24"},
        ]
        accepted = ["answer.42"]
    return {
        "learning_item_version_id": "item-version",
        "item_handle": "li:" + "a" * 64,
        "item_key": "python.variables.knowledge",
        "item_version": "v1",
        "item_kind": "knowledge_check",
        "purpose": "knowledge_check",
        "item_knowledge_key": "python.variables",
        "item_language_id": "python",
        "item_capabilities_json": ["python"],
        "item_content_hash": "b" * 64,
        "public_json": {
            "content": {
                "type": "knowledge_check",
                "response_kind": response_kind,
                "options": options,
            }
        },
        "publication_state": "published",
        "materialization_handle": "li:" + "a" * 64,
        "materialization_content_hash": "b" * 64,
        "exercise_version_id": "exercise-version",
        "materialization_exercise_key": "python.variables.knowledge",
        "materialization_exercise_version": "v1",
        "materialization_exercise_content_hash": "c" * 64,
        "materialization_rubric_hash": "d" * 64,
        "exercise_language_id": "python",
        "exercise_key": "python.variables.knowledge",
        "exercise_version": "v1",
        "exercise_type": "static_code_reasoning",
        "source_kind": "curated_fixture",
        "exercise_capabilities_json": ["python"],
        "runtime_profile_key": None,
        "execution_required": False,
        "validation_status": "ready",
        "exercise_content_hash": "c" * 64,
        "reference_answer_json": {"accepted_answers": accepted},
        "score_policy_json": {
            "kind": "static_exact",
            "policy_version": "knowledge.check.v1",
            "threshold": 1,
        },
        "rubric_hash": "d" * 64,
    }


@pytest.mark.parametrize("response_kind", ["short_text", "prediction", "single_choice"])
def test_published_static_knowledge_selection_supports_only_plain_exact_shapes(
    response_kind: str,
) -> None:
    conn = _CandidateConnection(_materialization(response_kind=response_kind))
    selected = select_published_knowledge_check(  # type: ignore[arg-type]
        conn,
        language_id="python",
        knowledge_key="python.variables",
        required_capabilities=("python",),
        available_capabilities=("python", "python.io"),
    )
    assert selected.exercise_version_id == "exercise-version"
    assert selected.execution_requirement is ExecutionRequirement.FORBIDDEN
    assert selected.pass_threshold == 1


@pytest.mark.parametrize("response_kind", ["multiple_choice", "ordering", "code_range"])
def test_structured_knowledge_shapes_fail_closed_in_generic_gate_scorer(
    response_kind: str,
) -> None:
    conn = _CandidateConnection(_materialization(response_kind=response_kind))
    with pytest.raises(GateSelectionUnavailable, match="no published static knowledge check"):
        select_published_knowledge_check(  # type: ignore[arg-type]
            conn,
            language_id="python",
            knowledge_key="python.variables",
            required_capabilities=("python",),
            available_capabilities=("python",),
        )


def test_model_authored_unknown_capability_fails_before_candidate_query() -> None:
    conn = _CandidateConnection(_materialization())
    with pytest.raises(GateSelectionUnavailable, match="outside the active track node scope"):
        select_published_knowledge_check(  # type: ignore[arg-type]
            conn,
            language_id="python",
            knowledge_key="python.variables",
            required_capabilities=("python", "python.fabricated"),
            available_capabilities=("python",),
        )
    assert conn.calls == []


def test_candidate_filters_are_applied_before_limit() -> None:
    conn = _CandidateConnection(_materialization())
    candidates = PostgresLearningItemBankRepository(conn).published_candidates(  # type: ignore[arg-type]
        knowledge_key="python.variables",
        purpose="knowledge_check",
        language_id="python",
        kinds=("knowledge_check",),
        available_capabilities=("python",),
        exact_capabilities=True,
        limit=1,
    )
    assert len(candidates) == 1
    sql, params = conn.calls[0]
    where = sql.index("WHERE versions.knowledge_key")
    language_filter = sql.index("versions.language_id", where)
    kind_filter = sql.index("versions.item_kind=ANY", where)
    exact_capability_filter = sql.index("required_capabilities_json", where)
    limit = sql.index("LIMIT %s", where)
    assert where < language_filter < limit
    assert where < kind_filter < limit
    assert where < exact_capability_filter < limit
    assert params[3:7] == ("python", "python", ["knowledge_check"], ["knowledge_check"])


def test_selection_locks_exact_version_before_rereading_publication() -> None:
    materialization = _materialization()
    materialization["publication_state"] = "retired"
    conn = _CandidateConnection(materialization)

    with pytest.raises(GateSelectionUnavailable, match="no published static knowledge check"):
        select_published_knowledge_check(  # type: ignore[arg-type]
            conn,
            language_id="python",
            knowledge_key="python.variables",
            required_capabilities=("python",),
            available_capabilities=("python",),
        )

    assert "public.candidate_summary" in conn.calls[0][0]
    assert "WHERE handle = %s" in conn.calls[1][0]
    assert "FOR UPDATE" in conn.calls[1][0]
    assert "WHERE versions.id = %s" in conn.calls[2][0]
    assert conn.calls[2][1] == ("item-version",)


def _binding_row(*, assessment: str = "lesson_gate_v1") -> dict[str, object]:
    return {
        "gate_key": "python.variables.basic",
        "gate_kind": "knowledge_check",
        "assessment_contract_version": assessment,
        "slot_capabilities_json": ["python.variables"],
        "node_capabilities_json": ["python"],
        "learner_prompt": "Explain variables.",
        "binding_id": "binding",
        "binding_knowledge_key": "python.variables",
        "binding_contract_hash": "e" * 64,
        "requirement_kind": "required",
        "pass_policy_version": "lesson_gate_pass_v1",
        "pass_threshold": 0.8,
        "execution_requirement": "required",
        "scope_language_id": "python",
        "scope_knowledge_key": "python.variables",
        "exercise_version_id": "exercise-version",
        "language_id": "python",
        "exercise_language_id": "python",
        "exercise_key": "python.variables.output",
        "exercise_type": "code_completion",
        "exercise_version": "v1",
        "source_kind": "curated_fixture",
        "exercise_title": "Output value",
        "learner_prompt_json": {"text": "Complete the code."},
        "starter_artifact_json": {"content": "value = 3"},
        "required_capabilities_json": ["python.variables"],
        "exercise_capabilities_json": ["python.variables"],
        "runtime_profile_key": "python_stdout_test",
        "execution_required": True,
        "exercise_content_hash": "f" * 64,
        "gate_state": "available",
        "gate_version": 1,
        "attempt_count": 0,
        "best_score": 0,
        "latest_attempt_id": None,
        "passed_at": None,
        "latest_outcome": None,
    }


def test_legacy_static_binding_remains_actionable_but_knowledge_contract_rejects_it() -> None:
    row = _binding_row()
    row.update(
        exercise_type="static_code_reasoning",
        runtime_profile_key=None,
        execution_required=False,
        execution_requirement="forbidden",
        reference_answer_json={"accepted_answers": ["immutable"]},
        score_policy_json={"kind": "exact_normalized", "threshold": 0.8},
    )
    assert gate_binding_compatibility(row).actionable is True

    knowledge_row = dict(row)
    knowledge_row["assessment_contract_version"] = "knowledge_check_v1"
    assert gate_binding_compatibility(knowledge_row).actionable is False

    unknown_row = dict(row)
    unknown_row.update(
        exercise_type="self_authored_unknown",
        execution_required=True,
        execution_requirement="required",
        runtime_profile_key="unknown-runtime",
    )
    assert gate_binding_compatibility(unknown_row).actionable is False


def test_supported_gate_slots_require_active_node_capabilities() -> None:
    for assessment in ("lesson_gate_v1", "knowledge_check_v1", "model_code_review_v1"):
        row = _binding_row(assessment=assessment)
        assert gate_slot_is_compatible(row) is True
        row["slot_capabilities_json"] = ["python.fabricated"]
        assert gate_slot_is_compatible(row) is False


def test_mutation_rereads_publication_after_locking_bound_item_version() -> None:
    class _GateMutationConnection:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def execute(self, sql: str, _params: tuple[object, ...]) -> _Result:
            self.calls.append(sql)
            if "FROM tutor_learning_tracks AS tracks" in sql:
                row = _binding_row(assessment="knowledge_check_v1")
                row["materialization_version_id"] = "item-version"
                row["latest_publication_state"] = "published"
                return _Result(row=row)
            if "tutor_learning_item_versions WHERE id" in sql:
                return _Result(row={"id": "item-version"})
            if "FROM tutor_learning_item_publication_events" in sql:
                return _Result(row={"state": "retired"})
            raise AssertionError(f"unexpected SQL: {sql}")

    conn = _GateMutationConnection()
    gate = PostgresExerciseGateRepository(conn).read_gate(  # type: ignore[arg-type]
        user_id="user",
        track_id="track",
        knowledge_key="python.variables",
        gate_key="python.variables.basic",
        for_update=True,
    )

    assert gate["latest_publication_state"] == "retired"
    assert "FOR UPDATE" in conn.calls[0]
    assert "tutor_learning_item_versions WHERE id" in conn.calls[1]
    assert "FROM tutor_learning_item_publication_events" in conn.calls[2]


def test_frozen_wrong_binding_is_readable_but_has_no_new_actions() -> None:
    row = _binding_row(assessment="knowledge_check_v1")
    compatibility = gate_binding_compatibility(row)
    assert compatibility.actionable is False

    service = object.__new__(ExerciseGateService)
    service._composition = ExecutionComposition.PUBLIC
    projected = ExerciseGateService._project_gate(service, row)
    assert projected["status"] == "available"
    assert projected["allowed_actions"] == []
    assert projected["execution_tier"] == "unavailable"
    assert "保留已有历史" in str(projected["execution_disclosure"])


def test_execution_requirement_is_derived_from_exercise_authority() -> None:
    assert execution_requirement_for(True) is ExecutionRequirement.REQUIRED
    assert execution_requirement_for(False) is ExecutionRequirement.FORBIDDEN


def _single_choice_source(item_key: str) -> LearningItemSourceV1:
    source, _validation = learning_item_source(item_key, capability="python")
    payload = source.model_dump(mode="json")
    public_content = payload["public"]["content"]
    assert isinstance(public_content, dict)
    public_content.update(
        response_kind="single_choice",
        options=[
            {"option_id": "answer.42", "label": "42"},
            {"option_id": "answer.24", "label": "24"},
        ],
    )
    private_content = payload["private"]["content"]
    assert isinstance(private_content, dict)
    private_content["accepted_answers"] = ["answer.42"]
    tests = private_content["tests"]
    assert isinstance(tests, list)
    tests[0]["input_json"] = {"answer": "answer.42"}
    tests[1]["input_json"] = {"answer": "answer.24"}
    return LearningItemSourceV1.model_validate(payload)


@pytest.mark.skipif(not database_available(), reason="PostgreSQL is required for Gate selection")
def test_prepare_gate_binds_published_static_knowledge_materialization(lesson_repo) -> None:  # type: ignore[no-untyped-def]
    conn, lesson_repository, user_id, track_id, snapshot = lesson_repo
    standard = sample_lesson_document()
    standard_blocks = list(standard.blocks)
    legacy_standard_gate = standard_blocks[7]
    standard_blocks[7] = replace(
        legacy_standard_gate,
        assessment_contract_version="knowledge_check_v1",
        required_capabilities=("python",),
    )
    standard_blocks.insert(
        8,
        replace(
            legacy_standard_gate,
            block_id="gate-legacy",
            order_index=8,
            gate_key="python.variables.legacy",
        ),
    )
    standard_blocks[9] = replace(standard_blocks[9], order_index=9)
    standard_blocks[10] = replace(standard_blocks[10], order_index=10)
    personalized = sample_lesson_document(personalized=True)
    personalized_blocks = list(personalized.blocks)
    legacy_personalized_gate = personalized_blocks[7]
    personalized_blocks[7] = replace(
        legacy_personalized_gate,
        assessment_contract_version="knowledge_check_v1",
        required_capabilities=("python",),
    )
    personalized_blocks.insert(
        8,
        replace(
            legacy_personalized_gate,
            block_id="gate-legacy",
            order_index=8,
            gate_key="python.variables.legacy",
        ),
    )
    personalized_blocks[9] = replace(personalized_blocks[9], order_index=9)
    personalized_blocks[10] = replace(personalized_blocks[10], order_index=10)
    published_lesson = publish_lesson(
        conn,
        lesson_repository,
        user_id,
        track_id,
        snapshot,
        action="initial",
        standard_document=replace(standard, blocks=tuple(standard_blocks)),
        personalized_document=replace(personalized, blocks=tuple(personalized_blocks)),
    )
    started = lesson_repository.start_assignment(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        assignment_id=published_lesson.assignment_id,
        expected_assignment_version=1,
        expected_progress_version=1,
        now=datetime(2026, 9, 8, tzinfo=UTC),
    )

    suffix = uuid4().hex
    source = _single_choice_source(f"test.gate.knowledge.{suffix}")
    validation = validate_learning_item(source)
    imported = import_learning_item(
        PostgresLearningItemBankRepository(conn),
        source,
        validation,
        key=f"gate-knowledge:{suffix}",
    )
    publication = publish_learning_item(conn, imported.handle, f"gate-knowledge:{suffix}")
    assert publication.state == "published"

    service = ExerciseGateService(conn)
    prepared = service.prepare_gate(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        gate_key="python.variables.basic",
        expected_track_version=1,
        expected_progress_version=int(started["progress_version"]),
        idempotency_key=f"prepare-knowledge-{suffix}",
    )
    gate = prepared["gate"]
    assert gate["assessment_contract_version"] == "knowledge_check_v1"
    assert gate["exercise"]["exercise_key"] == source.public.item_key
    assert gate["exercise"]["exercise_type"] == "static_code_reasoning"
    assert gate["execution_requirement"] == "forbidden"
    assert gate["execution_tier"] == "static_only"
    assert gate["allowed_actions"] == ["hint", "submit"]
    all_gates = service.read_gates(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
    )["items"]
    legacy_gate = next(item for item in all_gates if item["gate_key"] == "python.variables.legacy")
    assert legacy_gate["status"] == "unbound"
    assert legacy_gate["allowed_actions"] == ["prepare"]
    assert conn.execute(
        "SELECT count(*)::int AS count FROM tutor_lesson_gate_bindings WHERE document_id = %s",
        (published_lesson.personalized_document_id,),
    ).fetchone() == {"count": 1}

    hint_key = f"hint-knowledge-{suffix}"
    hint = service.hint(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        gate_key="python.variables.basic",
        expected_gate_version=int(gate["gate_version"]),
        idempotency_key=hint_key,
    )
    submit_key = f"submit-knowledge-{suffix}"
    result = service.attempt_gate(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        gate_key="python.variables.basic",
        attempt_type="submit",
        submission="answer.42",
        expected_track_version=1,
        expected_progress_version=int(started["progress_version"]),
        expected_assignment_version=1,
        expected_gate_version=int(hint["gate_version"]),
        idempotency_key=submit_key,
    )
    assert result["status"] == "terminal"
    assert result["result"]["outcome"] == "passed"

    retired = PostgresLearningItemBankRepository(conn).append_publication_state(
        handle=imported.handle,
        expected_state_version=publication.state_version,
        next_state="retired",
        transition_key=f"retire-gate-knowledge:{suffix}",
        authority_kind="operator",
        authority_hash="9" * 64,
        policy_version="gate-selection-test-v1",
        reason_code="test-retired",
        occurred_at=datetime(2026, 9, 8, 1, tzinfo=UTC),
    )
    assert retired.state == "retired"
    frozen = service.read_gates(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
    )["items"][0]
    assert frozen["allowed_actions"] == []
    assert frozen["execution_tier"] == "unavailable"
    assert frozen["latest_result"]["outcome"] == "passed"

    replayed_hint = service.hint(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        gate_key="python.variables.basic",
        expected_gate_version=int(gate["gate_version"]),
        idempotency_key=hint_key,
    )
    assert replayed_hint["idempotent_replayed"] is True
    replayed_attempt = service.attempt_gate(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        gate_key="python.variables.basic",
        attempt_type="submit",
        submission="answer.42",
        expected_track_version=1,
        expected_progress_version=int(started["progress_version"]),
        expected_assignment_version=1,
        expected_gate_version=int(hint["gate_version"]),
        idempotency_key=submit_key,
    )
    assert replayed_attempt["idempotent_replayed"] is True
    assert replayed_attempt["result"]["outcome"] == "passed"

    with pytest.raises(ExerciseGateServiceError) as fresh_error:
        service.hint(
            user_id=user_id,
            track_id=track_id,
            knowledge_key="python.variables",
            gate_key="python.variables.basic",
            expected_gate_version=int(frozen["gate_version"]),
            idempotency_key=f"fresh-hint-after-retire-{suffix}",
        )
    assert fresh_error.value.code == "LESSON_GATE_NOT_READY"
