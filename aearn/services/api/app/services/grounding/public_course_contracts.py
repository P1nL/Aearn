"""Native public curriculum evidence binding: no private DraftScope or fake user.

Registry identity is not a source grant. The same concrete C/claim/current fence
must still verify every evidence coordinate and executed semantic scope.
"""
from __future__ import annotations

from typing import Literal, Sequence

from pydantic import Field, model_validator

from app.services.grounding.autonomous.access_policy import AccessRequest
from app.services.grounding.autonomous.assessment_contracts import VerifiedClaim
from app.services.grounding.autonomous.contracts import FrozenContract, HASH, LearningMaterialDemand, SubjectScope, revalidate
from app.services.grounding.autonomous.finite_course_source_oracle import public_course_execution_scope, public_course_source_request
from app.services.grounding.material_contracts_v2 import EvidenceCoordinate, digest
from app.services.learning.item_supply.finite_course_targets import get_finite_course_target
from app.services.learning.item_supply.finite_targets.contracts import TargetId

PUBLIC_COURSE_ACTOR = "service.rag-public-course"


def public_course_demand(target_id: TargetId) -> LearningMaterialDemand:
    target = get_finite_course_target(target_id)
    scope = SubjectScope(subject_id=target.subject_id, subject_version="1.0", facets=target.required_facets)
    payload = {"contract": "public_course_source_demand_v1", "target_id": target_id,
               "target_definition_hash": target.definition_hash, "scope": scope.model_dump(mode="json"),
               "purpose": "assessment_evidence", "revision": 1}
    return LearningMaterialDemand(scope=scope, demand_hash=digest(payload),
        plan_ref="course." + target_id + "." + target.definition_hash,
        node_ref="target." + target_id, draft_revision=1, purpose="assessment_evidence", reading_level="beginner", language="en")


class PublicCourseEvidenceBindingV1(FrozenContract):
    contract_version: Literal["rag_public_course_binding_v1"] = "rag_public_course_binding_v1"
    target_id: TargetId
    target_definition_hash: str = Field(pattern=HASH)
    course_goal_hash: str = Field(pattern=HASH)
    demand: LearningMaterialDemand
    purpose: Literal["assessment_evidence"] = "assessment_evidence"
    evidence: tuple[EvidenceCoordinate, ...] = Field(min_length=1, max_length=12)
    binding_digest: str = Field(pattern=HASH)

    def payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"binding_digest"})

    @model_validator(mode="after")
    def coherent(self) -> PublicCourseEvidenceBindingV1:
        target = get_finite_course_target(self.target_id)
        demand = revalidate(self.demand, LearningMaterialDemand)
        coordinates = tuple(revalidate(c, EvidenceCoordinate) for c in self.evidence)
        if (target.definition_hash != self.target_definition_hash
                or self.course_goal_hash != digest({"goal": target.goal_text, "clauses": [c.definition_hash for c in target.clauses]})
                or demand != public_course_demand(self.target_id)
                or len({digest(c.model_dump(mode="json")) for c in coordinates}) != len(coordinates)
                or tuple(sorted(coordinates, key=lambda c: digest(c.model_dump(mode="json")))) != coordinates
                or any(c.binding.purpose != self.purpose or c.binding.scope != demand.scope
                       or c.binding.demand_hash != demand.demand_hash for c in coordinates)
                or digest(self.payload()) != self.binding_digest):
            raise ValueError("public course binding mismatch")
        return self


def validate_public_course_request(binding: PublicCourseEvidenceBindingV1, request: AccessRequest,
                                   claims: Sequence[VerifiedClaim]) -> PublicCourseEvidenceBindingV1:
    """Pure exact precheck only; never bypass the later concrete C authority."""
    binding = revalidate(binding, PublicCourseEvidenceBindingV1)
    request = revalidate(request, AccessRequest)
    demand = public_course_demand(binding.target_id)
    if (request.actor_id != PUBLIC_COURSE_ACTOR or request.action != "consume"
            or request.demand_hash != demand.demand_hash or request.scope != demand.scope
            or request.purpose != demand.purpose or len(claims) != len(binding.evidence)):
        raise ValueError("public course request mismatch")
    required_scope = public_course_execution_scope(binding.target_id)
    _, _, applicability = public_course_source_request(binding.target_id)
    by_receipt = {c.binding.claim_receipt_id: c for c in binding.evidence}
    if len(by_receipt) != len(binding.evidence):
        raise ValueError("public course exact claim mismatch")
    for raw in claims:
        claim = revalidate(raw, VerifiedClaim)
        coord = by_receipt.get(claim.claim_receipt_id)
        if (coord is None or claim.binding != coord.binding or claim.scope != demand.scope
                or claim.execution_scope != required_scope or claim.applicability != applicability):
            raise ValueError("public course semantic claim mismatch")
    return binding
