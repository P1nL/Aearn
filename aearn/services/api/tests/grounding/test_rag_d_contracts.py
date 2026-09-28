"""Pure D identity tests; no database, provider, or network."""
from __future__ import annotations

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.services.grounding.autonomous.contracts import (
    LearningMaterialDemand, RagEvidenceBinding, SubjectScope, revalidate,
)
from app.services.grounding.material_binding_repository import goal_hash_for_node
from app.services.grounding.material_contracts_v2 import (
    DraftScope, EvidenceBindingV2, EvidenceCoordinate, MaterialFeedbackRef,
    MaterialSelectionEntry, MaterialSelectionResult, NodeMaterialRequirement,
    apply_material_dependencies, digest,
)


def _uuid() -> str:
    return str(uuid4())


def _fixture() -> tuple[MaterialSelectionResult, EvidenceBindingV2]:
    draft = DraftScope(user_id=_uuid(), conversation_id=_uuid(), session_id=_uuid(),
                       draft_id=_uuid(), draft_version=1, content_hash="a" * 64,
                       source_run_id=_uuid(), source_input_revision=1)
    node = {"knowledge_key": "sql.select", "title": "SELECT", "description": "query rows",
            "is_core": True, "prerequisite_keys": [], "required_capabilities": ["sql.query"]}
    scope = SubjectScope(subject_id="route.sql", subject_version="sqlite-docs-v1",
                         facets=("queries",))
    demand = LearningMaterialDemand(scope=scope, demand_hash="b" * 64,
                                    plan_ref=f"draft.{draft.draft_id}", node_ref="node.sql.select",
                                    draft_revision=1, purpose="supplementary_explanation",
                                    reading_level="beginner", language="zh")
    requirement = NodeMaterialRequirement(node_id="sql.select", goal_hash=goal_hash_for_node(node),
                                          prerequisites=(), demand=demand)
    a_binding = RagEvidenceBinding(scope=scope, demand_hash=demand.demand_hash,
                                   purpose=demand.purpose, source_handle="source.test",
                                   document_handle="document.test", document_revision="v1",
                                   document_hash="c" * 64, admission_receipt_id="admit.test")
    evidence = EvidenceCoordinate(binding=a_binding, subject_id="route.sql",
                                  corpus_version_id=_uuid(), active_generation=1,
                                  summary_hash="d" * 64, validation_hash="e" * 64,
                                  registry_digest="f" * 64, source_review_id=_uuid(),
                                  source_policy_id="policy.test", source_policy_generation=1,
                                  chunk_id="chunk.where", chunk_hash="1" * 64,
                                  approved_excerpt_hash="2" * 64, retrieval_hash="3" * 64,
                                  coverage_hash="4" * 64)
    entry = MaterialSelectionEntry(node_id="sql.select", goal_hash=requirement.goal_hash,
                                   purpose=demand.purpose, status="ready", covered_facets=("queries",),
                                   evidence=(evidence,))
    payload = dict(handle=f"selection.{uuid4().hex}", draft=draft, requirements=(requirement,),
                   entries=(entry,))
    selection = MaterialSelectionResult(**payload, selection_digest=digest(
        MaterialSelectionResult.model_construct(**payload, selection_digest="0" * 64).payload()))
    frozen = dict(selection_handle=selection.handle, selection_digest=selection.selection_digest,
                  draft=draft, node_id="sql.select", goal_hash=requirement.goal_hash,
                  purpose=demand.purpose, evidence=(evidence,))
    binding = EvidenceBindingV2(**frozen, binding_digest=digest(
        EvidenceBindingV2.model_construct(**frozen, binding_digest="0" * 64).payload()))
    return selection, binding


def test_exact_nested_contracts_and_hashes() -> None:
    selection, binding = _fixture()
    assert revalidate(selection, MaterialSelectionResult) == selection
    assert revalidate(binding, EvidenceBindingV2) == binding
    assert binding.evidence[0].chunk_id == "chunk.where"  # 260 text, not UUID
    assert binding.evidence[0].registry_digest == "f" * 64
    with pytest.raises(ValidationError):
        MaterialSelectionResult.model_validate({**selection.model_dump(mode="json"), "url": "https://x"})
    with pytest.raises(ValidationError):
        revalidate(selection.model_copy(update={"draft": selection.draft.model_copy(
            update={"content_hash": "0" * 64})}), MaterialSelectionResult)
    with pytest.raises(ValidationError):
        revalidate(binding.model_copy(update={"evidence": (binding.evidence[0].model_copy(
            update={"registry_digest": "wrong"}),)}), EvidenceBindingV2)
    with pytest.raises(ValidationError):
        EvidenceCoordinate.model_validate({**binding.evidence[0].model_dump(mode="json"),
                                           "source_url": "https://invalid"})


def test_ready_cannot_bypass_coverage_or_purpose() -> None:
    selection, binding = _fixture()
    entry = selection.entries[0]
    with pytest.raises(ValidationError):
        revalidate(selection.model_copy(update={"entries": (entry.model_copy(
            update={"covered_facets": ()}),)}), MaterialSelectionResult)
    with pytest.raises(ValidationError):
        revalidate(binding.model_copy(update={"purpose": "assessment_evidence"}), EvidenceBindingV2)
    with pytest.raises(ValidationError):
        EvidenceCoordinate.model_validate({**binding.evidence[0].model_dump(mode="json"),
                                           "chunk_id": str(uuid4()).upper()})


def test_feedback_digest_binds_full_parent_and_target() -> None:
    selection, _ = _fixture()
    data = dict(selection_handle=selection.handle, selection_digest=selection.selection_digest,
                draft=selection.draft.model_dump(mode="json"), target_run_id=_uuid(),
                target_input_revision=2, expected_session_version=4)
    ref = MaterialFeedbackRef.model_validate({**data, "assignment_digest": digest(data)})
    assert revalidate(ref, MaterialFeedbackRef) == ref
    with pytest.raises(ValidationError):
        revalidate(ref.model_copy(update={"target_input_revision": 3}), MaterialFeedbackRef)


def test_selection_cannot_duplicate_exact_evidence() -> None:
    selection, _ = _fixture()
    entry = selection.entries[0]
    with pytest.raises(ValidationError):
        revalidate(entry.model_copy(update={"evidence": (entry.evidence[0], entry.evidence[0])}),
                   MaterialSelectionEntry)


def test_ready_dependency_requires_main_teaching_not_same_purpose() -> None:
    selection, _ = _fixture()
    requirement = selection.requirements[0]
    child = NodeMaterialRequirement(
        node_id="sql.filter", goal_hash="5" * 64,
        prerequisites=(requirement.node_id,),
        demand=requirement.demand.model_copy(update={"node_ref": "node.sql.filter"}),
    )
    child_entry = selection.entries[0].model_copy(update={
        "node_id": child.node_id, "goal_hash": child.goal_hash,
    })
    raw = selection.model_dump(mode="json", exclude={"selection_digest"})
    raw["requirements"] = [requirement.model_dump(mode="json"), child.model_dump(mode="json")]
    raw["entries"] = [selection.entries[0].model_dump(mode="json"),
                      child_entry.model_dump(mode="json")]
    with pytest.raises(ValidationError):
        MaterialSelectionResult.model_validate_json(json.dumps(
            {**raw, "selection_digest": digest(raw)}))


def test_dependency_helper_transitive_order_independent_and_preserves_evidence() -> None:
    selection, _ = _fixture()
    child = selection.requirements[0].model_copy(update={"prerequisites": ("sql.base",)})
    parent = selection.requirements[0].model_copy(update={
        "node_id": "sql.base", "goal_hash": "6" * 64,
        "demand": selection.requirements[0].demand.model_copy(update={
            "node_ref": "node.sql.base", "purpose": "main_teaching",
        }),
    })
    parent_gap = MaterialSelectionEntry(node_id="sql.base", goal_hash=parent.goal_hash,
                                        purpose="main_teaching", status="gap",
                                        gaps=("missing_material",))
    child_ready = selection.entries[0]
    output = apply_material_dependencies((child, parent), (parent_gap, child_ready))
    assert output[0].status == "gap"
    assert output[0].gaps == ("prerequisite_blocked",)
    assert output[0].evidence == child_ready.evidence
    assert output[0].covered_facets == child_ready.covered_facets
    assert output[1] == parent_gap
    reordered = apply_material_dependencies((parent, child), (child_ready, parent_gap))
    assert reordered == (parent_gap, output[0])
    already_partial = child_ready.model_copy(update={
        "status": "partial", "gaps": ("insufficient_coverage",),
    })
    partial = apply_material_dependencies((parent, child), (parent_gap, already_partial))[1]
    assert partial.gaps == ("insufficient_coverage", "prerequisite_blocked")
    assert partial.evidence == already_partial.evidence
    middle = parent.model_copy(update={
        "node_id": "sql.middle", "goal_hash": "7" * 64,
        "prerequisites": (parent.node_id,),
        "demand": parent.demand.model_copy(update={"node_ref": "node.sql.middle"}),
    })
    middle_coord = child_ready.evidence[0].model_copy(update={
        "binding": child_ready.evidence[0].binding.model_copy(update={"purpose": "main_teaching"}),
    })
    middle_ready = MaterialSelectionEntry(
        node_id=middle.node_id, goal_hash=middle.goal_hash, purpose="main_teaching",
        status="ready", covered_facets=("queries",), evidence=(middle_coord,),
    )
    leaf = child.model_copy(update={"prerequisites": (middle.node_id,)})
    chain = apply_material_dependencies(
        (leaf, parent, middle), (middle_ready, child_ready, parent_gap))
    assert chain[0].status == chain[2].status == "gap"
    assert chain[0].evidence == child_ready.evidence
    raw = selection.model_dump(mode="json", exclude={"selection_digest"})
    raw["requirements"] = [parent.model_dump(mode="json"), child.model_dump(mode="json")]
    raw["entries"] = [entry.model_dump(mode="json") for entry in reordered]
    assert MaterialSelectionResult.model_validate_json(json.dumps(
        {**raw, "selection_digest": digest(raw)})).entries[1] == output[0]


def test_dependency_helper_rejects_unknown_cycles_and_mismatched_members() -> None:
    selection, _ = _fixture()
    parent = selection.requirements[0]
    child = parent.model_copy(update={
        "node_id": "sql.filter", "goal_hash": "5" * 64,
        "prerequisites": (parent.node_id,),
        "demand": parent.demand.model_copy(update={"node_ref": "node.sql.filter"}),
    })
    child_gap = selection.entries[0].model_copy(update={
        "node_id": child.node_id, "goal_hash": child.goal_hash,
        "status": "gap", "gaps": ("missing_material",), "evidence": (),
        "covered_facets": (),
    })
    with pytest.raises(ValueError, match="unknown"):
        apply_material_dependencies((child,), (child_gap,))
    cyclic_parent = parent.model_copy(update={"prerequisites": (child.node_id,)})
    with pytest.raises(ValueError, match="cyclic"):
        apply_material_dependencies((cyclic_parent, child), (selection.entries[0], child_gap))
    with pytest.raises(ValueError, match="match exactly"):
        apply_material_dependencies((parent, child), (selection.entries[0],))
