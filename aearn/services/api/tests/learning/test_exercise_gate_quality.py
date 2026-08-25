from __future__ import annotations

from dataclasses import replace

import pytest

from app.services.learning.practice.contracts import (
    ExecutionRequirement,
    ExerciseType,
    GateRequirementKind,
    LessonGateBinding,
)
from app.services.learning.practice.fixtures import CORE_EXERCISE_FIXTURES
from app.services.learning.practice.quality import require_exercise_quality


def test_all_curated_fixtures_pass_public_private_quality_boundary() -> None:
    for fixture in CORE_EXERCISE_FIXTURES:
        binding = LessonGateBinding(
            gate_key=f"{fixture.exercise.language_id}.gate",
            exercise_key=fixture.exercise.exercise_key,
            exercise_version=fixture.exercise.version,
            requirement_kind=GateRequirementKind.REQUIRED,
            pass_policy_version="lesson_gate_pass_v1",
            pass_threshold=0.8,
            execution_requirement=ExecutionRequirement.REQUIRED,
            slot_contract_hash="a" * 64,
        )
        report = require_exercise_quality(fixture.exercise, fixture.rubric, binding=binding)
        assert report.exercise_hash == fixture.exercise.content_hash
        assert report.rubric_hash == fixture.rubric.rubric_hash
        assert report.binding_hash == binding.binding_contract_hash


def test_quality_gate_rejects_protected_public_markers_and_static_execution() -> None:
    fixture = CORE_EXERCISE_FIXTURES[0]
    leaked = replace(fixture.exercise, learner_prompt={"private_test": "do not expose"})
    with pytest.raises(ValueError, match="protected marker"):
        require_exercise_quality(leaked, fixture.rubric)

    invalid_static = replace(fixture.exercise, exercise_type=ExerciseType.STATIC_CODE_REASONING)
    with pytest.raises(ValueError, match="cannot require execution"):
        require_exercise_quality(invalid_static, fixture.rubric)


def test_quality_gate_rejects_binding_to_different_version() -> None:
    fixture = CORE_EXERCISE_FIXTURES[0]
    binding = LessonGateBinding(
        gate_key="python.variables.gate",
        exercise_key=fixture.exercise.exercise_key,
        exercise_version="v2",
        requirement_kind=GateRequirementKind.REQUIRED,
        pass_policy_version="lesson_gate_pass_v1",
        pass_threshold=0.8,
        execution_requirement=ExecutionRequirement.REQUIRED,
        slot_contract_hash="b" * 64,
    )
    with pytest.raises(ValueError, match="exact exercise version"):
        require_exercise_quality(fixture.exercise, fixture.rubric, binding=binding)
