"""Offline original planner quality seam, not source/confirmation authority."""
from dataclasses import replace
import json

import pytest

from app.agents.harness.contracts import TutorCapabilityStatus
from app.services.learning.item_supply.finite_course_mapping import finite_node_description
from app.services.learning.item_supply.finite_course_targets import get_finite_course_target
from app.services.learning.plan_capability import (
    LearningPlanDraftCapabilityError, _language, _validate_quality, build_validated_learning_plan_artifact,
)
from app.services.learning.plan_drafting import CompactPlanModule, CompactPlanNode, CompactPlanProfile


def _draft(target_id, *, required=None):
    target = get_finite_course_target(target_id)
    profile = CompactPlanProfile(language_id=target.language_id, goal_text=target.goal_text,
        target_level="beginner", weekly_minutes=60, experience_level="beginner",
        teaching_preferences=[], pace_summary="One session per week.", title="Finite course")
    # Ordinary nodes retain the original selectable language capability. Only
    # the exact registered finite node carries the finite semantic labels.
    modules = (
        CompactPlanModule(module_key="basics", title="Basics", is_core=False, is_skippable=True,
            nodes=[CompactPlanNode(knowledge_key="course.basics", title="Basics", is_core=False,
                description="Known basics", required_capabilities=[target.language_id])]),
        CompactPlanModule(module_key="finite", title="Finite", nodes=[CompactPlanNode(
            knowledge_key="course.finite", title="Finite", description=finite_node_description(target_id),
            required_capabilities=list(target.required_capabilities) if required is None else required)]),
    )
    return build_validated_learning_plan_artifact(
        session={"preferred_language_id": target.language_id}, profile=profile, modules=modules)


@pytest.mark.parametrize("target_id", [
    "python-kc-binding-v1", "python-state-update-v1", "sqlite-predicate-order-v1",
])
def test_original_planner_accepts_only_exact_registered_finite_semantics(target_id):
    target = get_finite_course_target(target_id)
    artifact = _draft(target_id)
    assert artifact.plan.nodes[0].required_capabilities == (target.language_id,)
    assert artifact.plan.nodes[1].required_capabilities == target.required_capabilities
    assert artifact.plan.nodes[1].description == finite_node_description(target_id)


def test_original_planner_still_rejects_an_unregistered_finite_label():
    with pytest.raises(LearningPlanDraftCapabilityError) as caught:
        _draft("python-kc-binding-v1", required=["python.assignment.typo"])
    assert caught.value.diagnostic_code == "learning_plan_draft_quality_blocked"


@pytest.mark.parametrize("branch", ["core_shape_missing", "capability_match_failed"])
def test_quality_diagnostics_keep_rejection_and_never_log_inputs(caplog, branch):
    sentinel = "private.secret.sentinel"
    artifact = _draft("python-kc-binding-v1")
    modules = list(artifact.plan.modules)
    if branch == "core_shape_missing":
        modules = [replace(module, is_core=False, nodes=tuple(
            replace(node, is_core=False, description=sentinel, required_capabilities=(sentinel,))
            for node in module.nodes)) for module in modules]
    else:
        modules[1] = replace(modules[1], nodes=(replace(modules[1].nodes[0],
            description=sentinel, required_capabilities=(sentinel,)),))
    artifact = replace(artifact, plan=replace(artifact.plan, modules=tuple(modules)),
        profile=artifact.profile.model_copy(update={"goal_text": sentinel, "title": sentinel}))
    canonical, capabilities = _language("python")
    with pytest.raises(LearningPlanDraftCapabilityError) as caught:
        _validate_quality(artifact=artifact, capabilities=capabilities, canonical_language_id=canonical)
    assert caught.value.code == "LEARNING_PLAN_DRAFT_QUALITY_BLOCKED"
    assert caught.value.diagnostic_code == "learning_plan_draft_quality_blocked"
    assert caught.value.status is TutorCapabilityStatus.UNAVAILABLE
    records = [r for r in caplog.records if r.name == "app.services.learning.plan_capability"]
    assert len(records) == 1
    prefix, data = records[0].getMessage().split(" ", 1)
    assert prefix == "learning_plan_draft_quality_diagnostic"
    assert sentinel not in caplog.text and sentinel not in repr(records[0].__dict__)
    payload = json.loads(data)
    assert payload["branch"] == branch and payload["language_selectable"] is True
    assert payload["module_count"] == payload["node_count"] == 2
    if branch == "core_shape_missing":
        assert payload["core_module_count"] == payload["core_node_count"] == 0
        assert payload["module_index"] is None and payload["node_index"] is None
        assert payload["registered_targets"] == []
    else:
        assert payload["core_module_count"] == payload["core_node_count"] == 1
        assert payload["module_index"] == 1 and payload["node_index"] == 0
        assert payload["description_length"] == len(sentinel) and payload["capability_count"] == 1
        assert len(payload["registered_targets"]) == 3
        assert all(not item["description_exact"] and not item["capabilities_exact"]
                   for item in payload["registered_targets"])
