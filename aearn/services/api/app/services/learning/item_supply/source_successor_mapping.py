"""Confirmed mapping continuity using NEW actual-D evidence, never PUBLIC substitution."""
from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING
from uuid import UUID

from app.services.grounding.autonomous.confirmed_source_successor import MAPPING, PRIVATE_CLAIM, same_supported_source
from app.services.grounding.autonomous.source_assessment_profiles import PreparedActualDSourceAssessment, SignedSourceAssessment
from app.services.grounding.current_authorization import EvidenceDenied
from app.services.grounding.material_contracts_v2 import EvidenceBindingV2
from app.services.learning.item_supply.finite_course_mapping_contracts import FiniteCourseMappingReceiptV1
from app.services.learning.item_bank.native_publication_contracts import NativeInternalRuntimeBindingV1
from app.services.learning.item_supply.finite_course_targets import get_finite_course_target
from app.services.learning.item_supply.finite_targets.python_kc import PYTHON_KC_SCORER_VERSION
from app.services.learning.item_supply.sandbox.execution_contracts import RUNNER_VERSION
from app.services.learning.item_supply.generation_contracts import PublicMaterialV2
from app.services.learning.item_supply.storage_contracts import checked_model

if TYPE_CHECKING:
    from app.services.learning.item_supply.finite_course_mapping import FiniteCourseMappingOwner


def resolve_source_successor(owner: FiniteCourseMappingOwner, *, receipt_id: UUID, user_id: UUID,
                             epoch: int, materials: tuple[PublicMaterialV2, ...]) -> FiniteCourseMappingReceiptV1:
    if not owner.enabled or receipt_id != MAPPING or not materials:
        raise EvidenceDenied("CONFIRMED_SOURCE_SUCCESSOR_REQUIRED")
    owner._transaction()
    # Original SQL current confirmed plan/epoch checks do not pretend the old claim is current.
    row = owner.conn.execute("SELECT item_supply_internal.public_normal_mapping_current(%s,%s,%s) AS receipt",
        (receipt_id,user_id,epoch)).fetchone()
    if row is None:
        raise EvidenceDenied("CONFIRMED_SOURCE_SUCCESSOR_REQUIRED")
    saved = FiniteCourseMappingReceiptV1.model_validate_json(json.dumps(row["receipt"]))
    n = saved.frozen_node
    from app.services.learning.item_supply.finite_course_mapping import _mapping_hash
    if (saved.receipt_id != receipt_id or (n.user_id,n.epoch)!=(user_id,epoch)
            or saved.target_id != "python-kc-binding-v1" or saved.profile != owner.profiles.get(saved.profile.profile_id)
            or _mapping_hash(n,saved.profile) != saved.mapping_hash
            or get_finite_course_target(saved.target_id).definition_hash != saved.target_definition_hash):
        raise EvidenceDenied("CONFIRMED_SOURCE_SUCCESSOR_REQUIRED")
    course = owner.current_authority.read(user_id=user_id,epoch=epoch,track_id=n.track_id,revision_id=n.revision_id,
        node_id=n.node_id,session_id=n.session_id,assessment_binding_id=n.assessment_binding_id)
    if course.node != n or len(materials) != len(course.binding.evidence):
        raise EvidenceDenied("FROZEN_NODE_MISMATCH")
    historical = owner.conn.execute("SELECT signed_proof FROM rag_assessment_source_evidence WHERE claim_handle=%s FOR SHARE",
        (PRIVATE_CLAIM,)).fetchone()
    if historical is None:
        raise EvidenceDenied("CONFIRMED_SOURCE_SUCCESSOR_REQUIRED")
    old = SignedSourceAssessment.model_validate_json(json.dumps(historical["signed_proof"])).payload.prepared
    if type(old) is not PreparedActualDSourceAssessment:
        raise EvidenceDenied("CONFIRMED_SOURCE_SUCCESSOR_REQUIRED")
    receipts = owner.current_authority.receipts
    for raw, prior in zip(materials,course.binding.evidence,strict=True):
        material = checked_model(raw,PublicMaterialV2)
        binding = material.binding
        if (type(binding) is not EvidenceBindingV2 or len(binding.evidence)!=1 or len(material.exact_claims)!=1
                or binding.draft != course.binding.draft or binding.node_id != course.binding.node_id
                or binding.goal_hash != course.binding.goal_hash or binding.purpose != "assessment_evidence"
                or prior.binding.claim_receipt_id != PRIVATE_CLAIM
                or hashlib.sha256(material.excerpt.encode()).hexdigest() != prior.approved_excerpt_hash):
            raise EvidenceDenied("CONFIRMED_SOURCE_SUCCESSOR_REQUIRED")
        owner.current_authority.authority.authorize(material)
        current,_,_ = receipts._find(material.exact_claims[0].claim_receipt_id)
        if type(current.prepared) is not PreparedActualDSourceAssessment or current.claim_handle == PRIVATE_CLAIM:
            raise EvidenceDenied("CONFIRMED_SOURCE_SUCCESSOR_REQUIRED")
        same_supported_source(old,current.prepared)
        if current.prepared.actual_d.draft != course.binding.draft or current.prepared.actual_d.goal_hash != n.goal_hash:
            raise EvidenceDenied("FROZEN_NODE_MISMATCH")
    runtime = owner.runtime_owner
    if runtime is None or saved.target_id not in runtime._bindings:
        raise EvidenceDenied("AUTHORITY_MISSING")
    bound = checked_model(runtime._bindings[saved.target_id],NativeInternalRuntimeBindingV1)
    target = get_finite_course_target(saved.target_id)
    if (bound.runtime_profile_hash != saved.profile.runtime_profile_hash or bound.scorer_version != saved.profile.scorer_version
            or saved.profile.scorer_version != PYTHON_KC_SCORER_VERSION
            or bound.runtime_lock is not None and bound.runner_version != RUNNER_VERSION
            or bound.runtime_id != (target.assessment.runtime_profile_id or "static-exact-v1")):
        raise EvidenceDenied("AUTHORITY_MISSING")
    clock = owner.conn.execute("SELECT clock_timestamp() AS now").fetchone()
    if clock is None:
        raise EvidenceDenied("AUTHORITY_MISSING")
    runtime._current_runtime(bound,now=clock["now"])
    return saved
