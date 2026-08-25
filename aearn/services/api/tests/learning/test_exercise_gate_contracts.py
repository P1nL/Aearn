from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.services.learning.contracts import MasteryEvidence, MasteryEvidenceEffect, MasteryEvidenceKind, MasteryIndependence
from app.services.learning.mastery import MasteryProjector, PROJECTOR_VERSION
from app.services.learning.practice.contracts import (
    ExecutionRequirement,
    ExerciseAttemptOutcome,
    ExerciseAttemptResult,
    GateRequirementKind,
    LessonGateBinding,
    ModuleDiagnosticItem,
    ModuleDiagnosticVersion,
    canonical_submission_hash,
)
from app.services.learning.practice.fixtures import CORE_EXERCISE_FIXTURES
from app.services.learning.practice.policies import diagnostic_decision, evaluate_static_reasoning


NOW = datetime(2026, 8, 11, tzinfo=UTC)


def test_curated_exercise_contracts_are_stable_and_cover_core_languages() -> None:
    assert [item.exercise.language_id for item in CORE_EXERCISE_FIXTURES] == [
        "python",
        "javascript",
        "typescript",
        "sql",
    ]
    assert all(len(item.exercise.content_hash) == 64 for item in CORE_EXERCISE_FIXTURES)
    assert all(len(item.rubric.rubric_hash) == 64 for item in CORE_EXERCISE_FIXTURES)
    assert canonical_submission_hash("a\r\nb") == canonical_submission_hash("a\nb")


def test_gate_binding_keeps_requirement_separate_and_hashes_policy() -> None:
    exercise = CORE_EXERCISE_FIXTURES[0].exercise
    binding = LessonGateBinding(
        gate_key="variables-check",
        exercise_key=exercise.exercise_key,
        exercise_version=exercise.version,
        requirement_kind=GateRequirementKind.REQUIRED,
        pass_policy_version="lesson_gate_pass_v1",
        pass_threshold=0.8,
        execution_requirement=ExecutionRequirement.REQUIRED,
        slot_contract_hash="a" * 64,
    )
    assert binding.requirement_kind is GateRequirementKind.REQUIRED
    assert len(binding.binding_contract_hash) == 64
    assert replace(binding, requirement_kind=GateRequirementKind.RECOMMENDED).binding_contract_hash != binding.binding_contract_hash


def test_module_diagnostic_requires_exact_core_capability_coverage() -> None:
    item = ModuleDiagnosticItem(
        item_key="variables",
        capability_key="python.variables",
        knowledge_key="python.variables",
        exercise_key="python.variables.output",
        exercise_version="v1",
        threshold=0.8,
    )
    version = ModuleDiagnosticVersion(
        language_id="python",
        module_key="python.basics",
        version="v1",
        policy_version="module_diagnostic_v1",
        core_capabilities=("python.variables",),
        pass_threshold=0.8,
        require_all_core=True,
        independent_only=True,
        cooldown_seconds=86400,
        items=(item,),
    )
    result = ExerciseAttemptResult(
        outcome=ExerciseAttemptOutcome.PASSED,
        score=1.0,
        safe_feedback={"status": "passed"},
        capability_scores={"python.variables": 1.0},
        policy_version="lesson_gate_pass_v1",
        terminal_at=NOW,
    )
    assert diagnostic_decision(
        version=version,
        results=(result,),
        independence=(MasteryIndependence.INDEPENDENT,),
    ).passed
    assert not diagnostic_decision(
        version=version,
        results=(result,),
        independence=(MasteryIndependence.HINTED,),
    ).passed

    with pytest.raises(ValueError, match="cover every core capability"):
        replace(version, core_capabilities=("python.variables", "python.loops"))


def test_static_evaluator_never_claims_execution() -> None:
    result = evaluate_static_reasoning(
        answer="immutable",
        accepted_answers=("immutable",),
        required_capabilities=("concept.immutability",),
        now=NOW,
    )
    assert result.outcome is ExerciseAttemptOutcome.PASSED
    assert result.safe_feedback["execution_claim"] == "not_run"


def test_observational_diagnostic_evidence_does_not_reduce_mastery() -> None:
    reinforcing = tuple(
        MasteryEvidence(
            evidence_id=f"evidence-{index}",
            knowledge_key="python.variables",
            evidence_kind=MasteryEvidenceKind.GATE,
            source_receipt_id=f"receipt-{index}",
            source_receipt_hash=f"{index + 1:064x}",
            independence=MasteryIndependence.INDEPENDENT,
            score=1.0,
            hint_count=0,
            attempt_count=1,
            summary={"strengths": ["variables"]},
            created_at=NOW,
        )
        for index in range(4)
    )
    observation = MasteryEvidence(
        evidence_id="diagnostic-failure",
        knowledge_key="python.variables",
        evidence_kind=MasteryEvidenceKind.MODULE_DIAGNOSTIC,
        source_receipt_id="diagnostic-receipt",
        source_receipt_hash="f" * 64,
        independence=MasteryIndependence.INDEPENDENT,
        score=0.0,
        hint_count=0,
        attempt_count=1,
        summary={"weaknesses": ["edge cases"]},
        created_at=NOW,
        evidence_effect=MasteryEvidenceEffect.OBSERVATIONAL_NON_DEGRADING,
    )
    projector = MasteryProjector()
    baseline = projector.project(knowledge_key="python.variables", evidence=reinforcing)
    observed = projector.project(knowledge_key="python.variables", evidence=(*reinforcing, observation))
    assert PROJECTOR_VERSION == "learning_mastery_v2"
    assert observed.confidence == baseline.confidence
    assert observed.mastery_level == baseline.mastery_level
    assert observed.evidence_count == baseline.evidence_count
    assert observed.observation_count == 1
    assert observed.last_observation_id == "diagnostic-failure"
    assert "edge cases" in observed.weaknesses
