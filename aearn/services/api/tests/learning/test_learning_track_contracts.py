from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.services.learning.contracts import (
    LearningPlan,
    LearningPlanModule,
    LearningPlanNode,
    LearningScope,
    LearningScopeKind,
    LearningTaskKind,
    MasteryEvidence,
    MasteryEvidenceKind,
    MasteryIndependence,
    MasteryLevel,
    calculate_plan_impact,
)
from app.services.learning.mastery import MasteryProjector, PROJECTOR_VERSION
from tests.support.learning_track_support import sample_plan


def test_plan_hash_is_canonical_and_impact_uses_stable_knowledge_keys() -> None:
    current = sample_plan()
    candidate = sample_plan(
        title="Python Foundations v2",
        target_level="intermediate",
        generator_version="learning-plan-test-v2",
        change_reason="Add loops after variables.",
        include_loops=True,
    )

    assert current.content_hash == sample_plan().content_hash
    assert len(current.content_hash) == 64

    impact = calculate_plan_impact(
        current,
        candidate,
        progress_keys={"python.variables", "python.functions", "detached.old-key"},
    )
    assert impact.as_dict() == {
        "added": ["python.loops"],
        "removed": [],
        "reordered": [],
        "prerequisite_changed": [],
        "retained_progress": ["python.functions", "python.variables"],
    }


def test_plan_contract_rejects_unknown_prerequisites_cycles_and_unstable_keys() -> None:
    valid = sample_plan()
    module = valid.modules[0]
    variables, functions = module.nodes

    with pytest.raises(ValueError, match="unknown prerequisite"):
        LearningPlan(
            title=valid.title,
            target_level=valid.target_level,
            generator_version=valid.generator_version,
            policy_version=valid.policy_version,
            change_reason=valid.change_reason,
            modules=(replace(module, nodes=(replace(functions, prerequisite_keys=("python.missing",)),)),),
        )

    with pytest.raises(ValueError, match="acyclic"):
        LearningPlan(
            title=valid.title,
            target_level=valid.target_level,
            generator_version=valid.generator_version,
            policy_version=valid.policy_version,
            change_reason=valid.change_reason,
            modules=(
                LearningPlanModule(
                    module_key="cycle",
                    title="Cycle",
                    description="",
                    order_index=0,
                    is_core=True,
                    is_skippable=False,
                    nodes=(
                        replace(variables, prerequisite_keys=("python.functions",)),
                        replace(functions, prerequisite_keys=("python.variables",)),
                    ),
                ),
            ),
        )

    with pytest.raises(ValueError, match="stable lowercase identifier"):
        LearningPlanNode(
            knowledge_key="Python Variables",
            title="Variables",
            description="",
            order_index=0,
            is_core=True,
            prerequisite_keys=(),
            required_capabilities=(),
        )


def test_learning_scope_shapes_are_server_authoritative() -> None:
    assert LearningScope().task_kind is LearningTaskKind.GENERAL_TUTOR
    assert LearningScope(scope_kind=LearningScopeKind.PLAN_DRAFTING).task_kind is LearningTaskKind.PLAN_DRAFTING
    scoped = LearningScope(
        scope_kind=LearningScopeKind.LEARNING_TRACK,
        learning_track_id="track-1",
        task_kind=LearningTaskKind.EXERCISE_FEEDBACK,
        knowledge_key="python.variables",
    )
    assert scoped.knowledge_key == "python.variables"

    with pytest.raises(ValueError, match="general scope"):
        LearningScope(scope_kind=LearningScopeKind.GENERAL, learning_track_id="track-1")
    with pytest.raises(ValueError, match="track teaching task"):
        LearningScope(
            scope_kind=LearningScopeKind.LEARNING_TRACK,
            learning_track_id="track-1",
            task_kind=LearningTaskKind.GENERAL_TUTOR,
        )


def test_mastery_projector_is_deterministic_and_uses_independence_weighting() -> None:
    now = datetime(2026, 8, 4, tzinfo=UTC)
    evidence = tuple(
        MasteryEvidence(
            evidence_id=f"evidence-{index}",
            knowledge_key="python.variables",
            evidence_kind=MasteryEvidenceKind.GATE,
            source_receipt_id=f"receipt-{index}",
            source_receipt_hash=f"{index:x}" * 64,
            independence=MasteryIndependence.INDEPENDENT,
            score=0.9,
            hint_count=0,
            attempt_count=1,
            summary={"strengths": ["scope reasoning"], "weaknesses": ["naming"] if index == 1 else []},
            created_at=now,
        )
        for index in range(1, 5)
    )
    projector = MasteryProjector()

    first = projector.project(knowledge_key="python.variables", evidence=evidence)
    second = projector.project(knowledge_key="python.variables", evidence=evidence)
    hinted = projector.project(
        knowledge_key="python.variables",
        evidence=tuple(replace(item, independence=MasteryIndependence.HINTED) for item in evidence),
    )

    assert first == second
    assert first.projector_version == PROJECTOR_VERSION
    assert first.mastery_level is MasteryLevel.DURABLE
    assert first.strengths == ("scope reasoning",)
    assert first.weaknesses == ("naming",)
    assert hinted.confidence < first.confidence
    assert hinted.mastery_level is not MasteryLevel.DURABLE
