"""Pure factory/context DATA tests; no DB, original issuer or source authorization claim."""
import json
from uuid import uuid4

import pytest

from app.services.learning.item_supply.finite_candidate_factory import (
    FLEXIBLE_FACTORY_VERSION, build_finite_candidate_spec, build_finite_generation_request, build_finite_slot_allocation,
)
from app.services.learning.item_supply.finite_task_families import families_for_course
from app.services.learning.item_supply.native_revision_contracts import NativeRevisionContextV1
from app.services.learning.item_supply.persistent_pack_revision_contracts import PersistentRegisteredFamilyRevisionV1
from tests.learning.test_item_supply_generation import make_request
from tests.learning.test_item_supply_shared_validation import _candidate


def data():
    parent, materials, source = _candidate("python-kc-binding-v1")
    # Freeze a prior citation coordinate as historical DATA, not a renewed proof.
    old_refs = tuple(r.model_copy(update={"source_version": "old-document", "locator": "old-chunk"})
                     for r in source.blueprint.source_references)
    source = source.model_copy(update={"blueprint": source.blueprint.model_copy(update={"source_references": old_refs}),
        "public": source.public.model_copy(update={"source_references": old_refs})})
    family = next(f for f in families_for_course(parent.target_id) if f.family_id != parent.allocation.family_id)
    allocation = build_finite_slot_allocation(target_id=parent.target_id, family_id=family.family_id,
        slot="assessment", slot_index=1)
    spec = build_finite_candidate_spec(target_id=parent.target_id, variant_id=allocation.variant_id,
        seed=parent.seed, item_key="new.revision", version="revision-new", materials=materials,
        runtime_profile_hash=None, scorer_version=parent.coverage_blueprint.scope.scorer_version,
        assistance_policy_hash=parent.coverage_blueprint.scope.assistance_policy_hash,
        policy_version=parent.coverage_blueprint.policy_version, difficulty_profile=parent.blueprint.difficulty_profile,
        publication_policy=parent.blueprint.publication_policy, public_spec_version=FLEXIBLE_FACTORY_VERSION, allocation=allocation)
    base, _ = make_request()
    request = build_finite_generation_request(spec, candidate_id=uuid4(), profile=base.profile, limits=base.limits, materials=materials)
    family_data = PersistentRegisteredFamilyRevisionV1(phase_id=uuid4(), public_slot_id=uuid4(), parent_revision_id=uuid4(),
        parent_specification_hash=parent.specification_hash, finding_key="a" * 64, child_specification=spec)
    payload = dict(schema_version="native_revision_author_context_v3", parent_artifact_id=str(uuid4()), parent_artifact_hash="b" * 64,
        parent_source_hash=source.source_hash, parent_content_hash=source.content_hash, parent_review_hash="c" * 64,
        investigation_receipt_id=str(uuid4()), investigation_receipt_hash="d" * 64, investigation_report_hash="e" * 64,
        child_candidate_id=str(request.candidate_id), child_item_key=request.item_key, child_version=request.version,
        scope_hash=request.scope_hash, policy_hash="f" * 64, target_definition_hash=parent.target_definition_hash,
        parent_source=source.model_dump(mode="json"), persistent_family_revision=family_data.model_dump(mode="json"),
        problems=[dict(dispute_key="a" * 64, analysis="Synthetic historical clone", verification_question="Different family?",
            references=[dict(pointer="/source/public/content", value_hash="b" * 64)])])
    return payload, request


def test_v3_factory_references_can_differ_from_frozen_parent():
    payload, request = data()
    context = NativeRevisionContextV1.model_validate_json(json.dumps(payload))
    assert request.blueprint.source_references != context.parent_source.blueprint.source_references
    context.check_request(request)


def test_v2_still_rejects_changed_parent_references():
    payload, _ = data()
    payload["schema_version"] = "native_revision_author_context_v2"
    with pytest.raises(ValueError, match="same public objective"):
        NativeRevisionContextV1.model_validate_json(json.dumps(payload))


def test_v3_rejects_changed_semantics_and_nonfactory_references():
    payload, request = data()
    payload["persistent_family_revision"]["child_specification"]["blueprint"]["knowledge_key"] = "different"
    with pytest.raises(ValueError, match="same public objective"):
        NativeRevisionContextV1.model_validate_json(json.dumps(payload))
    payload, request = data()
    spec = payload["persistent_family_revision"]["child_specification"]
    spec["blueprint"]["source_references"][0]["locator"] = "unbound-chunk"
    spec["public_template"]["source_references"][0]["locator"] = "unbound-chunk"
    context = NativeRevisionContextV1.model_validate_json(json.dumps(payload))
    child = context.persistent_family_revision.child_specification
    request = request.model_copy(update={"blueprint": child.blueprint, "public_template": child.public_template})
    with pytest.raises(ValueError, match="finite_public_request_source_mismatch"):
        context.check_request(request)
