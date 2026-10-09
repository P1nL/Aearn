"""Synthetic public binding prechecks; no source grant/execution/PG is issued."""
import json

import pytest

from app.services.grounding.autonomous.access_policy import AccessRequest
from app.services.grounding.autonomous.assessment_contracts import VerifiedClaim
from app.services.grounding.autonomous.contracts import RagEvidenceBinding
from app.services.grounding.autonomous.finite_course_source_oracle import public_course_execution_scope, public_course_source_request
from app.services.grounding.current_authorization import CurrentAuthorization, EvidenceDenied
from app.services.grounding.material_contracts_v2 import EvidenceCoordinate, digest
from app.services.grounding.public_course_contracts import (
    PUBLIC_COURSE_ACTOR, PublicCourseEvidenceBindingV1, public_course_demand, validate_public_course_request,
)
from app.services.learning.item_supply.finite_course_targets import get_finite_course_target
from app.services.learning.item_supply.generation_contracts import PublicMaterialV2
from app.services.learning.item_supply.evidence import require_exact_material
from tests.learning.test_item_supply_evidence import make_material


def public_material():
    old, _ = make_material()
    target = get_finite_course_target("python-state-update-v1")
    demand = public_course_demand(target.target_id)
    source = RagEvidenceBinding.model_validate({**old.binding.evidence[0].binding.model_dump(),
        "scope": demand.scope, "demand_hash": demand.demand_hash})
    coordinate = EvidenceCoordinate.model_validate({**old.binding.evidence[0].model_dump(), "binding": source})
    payload = dict(contract_version="rag_public_course_binding_v1", target_id=target.target_id,
        target_definition_hash=target.definition_hash,
        course_goal_hash=digest({"goal": target.goal_text, "clauses": [c.definition_hash for c in target.clauses]}),
        demand=demand.model_dump(mode="json"), purpose="assessment_evidence", evidence=[coordinate.model_dump(mode="json")])
    binding = PublicCourseEvidenceBindingV1.model_validate_json(json.dumps({**payload, "binding_digest": digest(payload)}))
    access = AccessRequest.model_validate({**old.access_request.model_dump(), "actor_id": PUBLIC_COURSE_ACTOR,
                                          "demand_hash": demand.demand_hash, "scope": demand.scope})
    claim = VerifiedClaim.model_validate({**old.exact_claims[0].model_dump(), "binding": source,
        "execution_scope": public_course_execution_scope(target.target_id),
        "applicability": public_course_source_request(target.target_id)[2]})
    return PublicMaterialV2(binding=binding, access_request=access, exact_claims=(claim,), excerpt=old.excerpt)


def test_public_curriculum_demand_is_exact_and_has_no_private_draft_identity():
    for target in ("python-state-update-v1", "python-kc-binding-v1", "sqlite-predicate-order-v1"):
        demand = public_course_demand(target)
        assert demand == public_course_demand(target)
        assert demand.plan_ref.startswith("course.") and demand.node_ref == "target." + target
        assert not any(key in demand.model_dump() for key in ("user_id", "conversation_id", "draft_id"))
        request, expected, _ = public_course_source_request(target)
        assert request.action.value == "test" and expected["cases"]
        assert public_course_execution_scope(target).input_hash == digest(request.model_dump(mode="json"))


def test_native_public_binding_roundtrip_and_pure_semantic_precheck_not_authority():
    material = public_material()
    assert validate_public_course_request(material.binding, material.access_request, material.exact_claims) == material.binding
    assert require_exact_material(material) == material
    restored = PublicMaterialV2.model_validate_json(material.model_dump_json())
    assert type(restored.binding) is PublicCourseEvidenceBindingV1
    assert "draft" not in type(restored.binding).model_fields
    assert all(key not in restored.binding.model_dump() for key in ("user_id", "conversation_id", "session_id"))


def test_wrong_actor_old_narrow_claim_and_private_draft_injection_fail_closed():
    material = public_material()
    wrong_actor = AccessRequest.model_validate({**material.access_request.model_dump(), "actor_id": "actor.private"})
    with pytest.raises(ValueError, match="request mismatch"):
        validate_public_course_request(material.binding, wrong_actor, material.exact_claims)
    unproven = VerifiedClaim.model_validate({**material.exact_claims[0].model_dump(), "execution_scope": None})
    with pytest.raises(ValueError, match="semantic claim mismatch"):
        validate_public_course_request(material.binding, material.access_request, (unproven,))
    payload = material.binding.model_dump(mode="json")
    payload["draft"] = {"user_id": "a-private-user"}
    with pytest.raises(ValueError):
        PublicCourseEvidenceBindingV1.model_validate_json(json.dumps(payload))


def test_default_closed_current_authority_rejects_before_io_and_private_contract_survives():
    material = public_material()
    owner = CurrentAuthorization(None, governance=None)
    with pytest.raises(EvidenceDenied, match="GATE_CLOSED"):
        owner.check_current_authorization(material.binding, "assessment_evidence", request=material.access_request,
                                           exact_item_claims=material.exact_claims)
    old, _ = make_material()
    assert require_exact_material(PublicMaterialV2.model_validate_json(old.model_dump_json())) == old
