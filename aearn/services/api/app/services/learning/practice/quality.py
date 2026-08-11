"""Pure publication quality gate for versioned exercises and Gate bindings."""
from __future__ import annotations

import json
from dataclasses import dataclass

from app.services.learning.practice.contracts import (
    ExecutionRequirement,
    ExercisePrivateRubric,
    ExerciseType,
    ExerciseVersion,
    LessonGateBinding,
)


_PROTECTED_MARKERS = (
    "private_test",
    "hidden_test",
    "reference_answer",
    "solution_reference",
    "docker.sock",
    "container_id",
    "image_reference",
    "mounts",
    "authorization:",
    "api_key",
)
_APPROVED_RUNTIME_PROFILES = {
    "python_stdout_test",
    "browser_preview",
    "node_typescript_test",
    "sql_query_test",
}


@dataclass(frozen=True, slots=True)
class ExerciseQualityReport:
    exercise_hash: str
    rubric_hash: str
    binding_hash: str | None
    checks: tuple[str, ...]


def require_exercise_quality(
    exercise: ExerciseVersion,
    rubric: ExercisePrivateRubric,
    *,
    binding: LessonGateBinding | None = None,
) -> ExerciseQualityReport:
    public_text = json.dumps(exercise.public_payload(), ensure_ascii=False, sort_keys=True).casefold()
    if any(marker in public_text for marker in _PROTECTED_MARKERS):
        raise ValueError("public exercise contains a protected marker")
    if exercise.execution_required:
        if exercise.runtime_profile_id not in _APPROVED_RUNTIME_PROFILES:
            raise ValueError("execution exercise runtime profile is not approved")
        if exercise.exercise_type is ExerciseType.STATIC_CODE_REASONING:
            raise ValueError("static reasoning exercise cannot require execution")
    elif exercise.exercise_type is not ExerciseType.STATIC_CODE_REASONING:
        raise ValueError("non-static exercise must require an approved runtime")
    if binding is not None:
        if binding.exercise_key != exercise.exercise_key or binding.exercise_version != exercise.version:
            raise ValueError("Gate binding does not reference the exact exercise version")
        if exercise.execution_required and binding.execution_requirement is ExecutionRequirement.FORBIDDEN:
            raise ValueError("execution exercise cannot use a forbidden execution binding")
        if not exercise.execution_required and binding.execution_requirement is not ExecutionRequirement.FORBIDDEN:
            raise ValueError("static exercise binding must forbid execution")
    return ExerciseQualityReport(
        exercise_hash=exercise.content_hash,
        rubric_hash=rubric.rubric_hash,
        binding_hash=binding.binding_contract_hash if binding else None,
        checks=("public_private_boundary", "runtime_profile", "binding_scope"),
    )
