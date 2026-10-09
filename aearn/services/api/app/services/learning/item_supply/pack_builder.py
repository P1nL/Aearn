"""Bounded assessment-first pack computation over already-resolved native facts."""
from __future__ import annotations

from datetime import datetime
from itertools import combinations
from typing import cast, overload

from app.services.learning.item_bank.contracts import LearningItemPurpose, canonical_hash
from app.services.learning.item_supply.contracts import CandidateAuthorityV1, require_aware
from app.services.learning.item_supply.coverage import _candidate_reason
from app.services.learning.item_supply.finite_course_targets import get_finite_course_target
from app.services.learning.item_supply.finite_task_families import families_for_course, initial_slot_allocations
from app.services.learning.item_supply.matrix import build_support_matrix
from app.services.learning.item_supply.pack_contracts import (
    NativeScopedCandidateV2, PackCandidateV1, PackCandidateV2, PackInputsV1, PackInputsV2,
    PackResultV1, PackResultV2, PackSnapshotV1, PackSnapshotV2,
)
from app.services.learning.item_supply.storage_contracts import checked_model
from app.services.learning.item_supply.type_evidence import (
    ContentIdentityV2, ContentRelationshipEvidenceV2, TypeProfileV2,
    assessment_clone, relationship_reason,
)
from app.services.runners.language_capabilities import LANGUAGE_CAPABILITIES


def _validate_request(inputs: PackInputsV1 | PackInputsV2) -> None:
    request = inputs.request
    target = get_finite_course_target(request.target_id)
    if request.target_definition_hash != target.definition_hash:
        raise ValueError("pack target declaration mismatch")
    slots = {entry.slot: entry for entry in request.demands}
    if set(slots) != {"practice", "assessment", "remediation"}:
        raise ValueError("pack requires three exact purpose mappings")
    primary = slots["practice"].demand
    if slots["practice"].storage_scope_id != request.storage_scope_id:
        raise ValueError("pack primary storage scope mismatch")
    primary_scope = primary.scope.model_dump(exclude={"purpose"})
    mapped = request.clause_mapping
    if tuple((m[0], m[1]) for m in mapped) != tuple((c.clause_id, c.definition_hash) for c in target.clauses):
        raise ValueError("pack finite clauses mismatch")
    if len({m[2] for m in mapped}) != 3:
        raise ValueError("pack actual clauses not unique")
    for slot, entry in slots.items():
        demand, blueprint = entry.demand, entry.blueprint
        if (demand.scope != blueprint.scope or demand.blueprint_hash != blueprint.blueprint_hash
                or demand.objective_hash != blueprint.objective_hash or demand.matrix_hash != blueprint.matrix_hash
                or demand.policy_version != blueprint.policy_version
                or demand.scope.model_dump(exclude={"purpose"}) != primary_scope
                or demand.objective_hash != primary.objective_hash or demand.input_revision != primary.input_revision
                or demand.learner_ref != "user:" + str(request.learner_id)
                or blueprint.matrix_hash != build_support_matrix().matrix_hash
                or tuple((c.clause_id, c.clause_hash) for c in blueprint.clauses) != tuple((m[2], m[3]) for m in mapped)):
            raise ValueError("pack exact sub-demand mapping mismatch")
        purpose = LearningItemPurpose.REMEDIATION if slot == "remediation" else LearningItemPurpose(target.assessment.purpose)
        if demand.scope.purpose != purpose or demand.scope.assessment_contract_version != target.target_id:
            raise ValueError("pack purpose or assessment contract mismatch")
        if demand.scope.visibility == "private" and demand.scope.owner_ref != demand.learner_ref:
            raise ValueError("pack private owner mismatch")
    if (primary.scope.language_id != target.language_id or primary.scope.subject_id != target.subject_id
            or primary.scope.required_facets != target.required_facets
            or primary.scope.item_kind.value != target.assessment.item_kind
            or primary.scope.interaction.value != target.assessment.interaction
            # Supply scopes use native runner IDs, not item-bank test contracts.
            or primary.scope.runtime_profile_id != (target.assessment.runtime_profile_id or "static-exact-v1")
            or primary.scope.required_capabilities != target.required_capabilities
            or LANGUAGE_CAPABILITIES[primary.scope.language_id].capability_state in {"planned", "unsupported"}):
        raise ValueError("pack target scope mismatch")


def _build_pack_v1(inputs: PackInputsV1, *, now: datetime) -> PackResultV1:
    """Complete means a pure computation, never a live publication/ready receipt."""
    inputs = checked_model(inputs, PackInputsV1)
    require_aware(now)
    request = inputs.request
    _validate_request(inputs)
    slots = {entry.slot: entry for entry in request.demands}
    families = {f.family_id: f for f in families_for_course(request.target_id)}
    allocations = {a.variant_id: a for a in initial_slot_allocations(request.target_id)}
    reasons: list[str] = []

    def gap(reason: str, *, stale: bool = False) -> PackResultV1:
        return PackResultV1(status="stale" if stale else "gap", request_hash=request.request_hash, reasons=(reason,))

    if any((d.blueprint.minimum.practice, d.blueprint.minimum.assessment, d.blueprint.minimum.remediation) != (2, 2, 1)
           for d in request.demands):
        return gap("minimum_profile_unsupported")

    exposure = inputs.exposure
    if exposure is None:
        return gap("exposure_incomplete")
    if (exposure.learner_id != request.learner_id or exposure.epoch != request.epoch
            or not exposure.observed_at <= now < exposure.valid_until):
        return gap("exposure_stale_or_wrong_owner", stale=True)
    pairs = {}
    for pair in inputs.family_pairs:
        key = frozenset((pair.left_family_id, pair.right_family_id))
        if len(key) != 2 or not key <= families.keys() or key in pairs or pair.course_mapping_hash != request.course_mapping_hash:
            return gap("family_pair_mismatch")
        if not pair.checked_at <= now < pair.valid_until:
            return gap("family_pair_stale", stale=True)
        if ({role for role, _ in pair.review_receipts} != {"curriculum", "technical", "ambiguity", "adversarial"}
                or {(w.source_family_id, w.target_family_id) for w in pair.witnesses}
                   != {(pair.left_family_id, pair.right_family_id), (pair.right_family_id, pair.left_family_id)}):
            return gap("family_pair_evidence_incomplete")
        expected_kind = "static_response_counterexample" if request.target_id == "python-kc-binding-v1" else "sealed_code_execution"
        if any(w.evidence_kind != expected_kind for w in pair.witnesses):
            return gap("family_pair_evidence_kind_mismatch")
        pairs[key] = pair
    if len(pairs) != 6:
        return gap("family_pair_evidence_incomplete")
    candidates: list[PackCandidateV1] = []
    seen = set()
    for record in inputs.candidates:
        item, member = record.candidate, record.member
        if item.item_handle in seen:
            return gap("duplicate_candidate_handle")
        seen.add(item.item_handle)
        family = families.get(member.family_id)
        allocation = allocations.get(member.allocation_variant_id)
        entry = slots[item.slot]
        if (family is None or member.family_id != item.candidate_family_id
                or member.family_definition_hash != family.definition_hash
                or member.target_definition_hash != request.target_definition_hash
                or member.course_mapping_hash != request.course_mapping_hash
                or member.candidate_content_hash != item.content_hash
                or allocation is None or allocation.definition_hash != member.allocation_definition_hash
                or allocation.family_id != member.family_id or allocation.slot != item.slot
                or allocation.purpose != item.scope.purpose.value):
            reasons.append("family_member_mismatch")
            continue
        if (item.visibility == "private" and (record.owner_id != request.learner_id or record.epoch != request.epoch)
                or item.visibility == "public" and (record.owner_id is not None or record.epoch is not None)):
            reasons.append("candidate_owner_mismatch")
            continue
        if record.storage_scope_id != entry.storage_scope_id:
            reasons.append("candidate_storage_scope_mismatch")
            continue
        if not record.observed_at <= now < record.valid_until:
            reasons.append("candidate_observation_stale")
            continue
        # Native subclasses retain actual handles and reuse the unchanged P1
        # exact proof/scope/source/runtime predicate. No fake li hash conversion.
        reason = _candidate_reason(item, entry.demand, entry.blueprint, now)
        if reason is not None:
            reasons.append(reason)
            continue
        if any((item.candidate_family_id == p.left_family_id and member.semantic_signature != p.left_semantic_signature)
               or (item.candidate_family_id == p.right_family_id and member.semantic_signature != p.right_semantic_signature)
               for p in pairs.values()):
            reasons.append("family_semantic_binding_mismatch")
            continue
        candidates.append(record)

    def independent(left: PackCandidateV1, right: PackCandidateV1) -> bool:
        a, b = left.candidate, right.candidate
        if (a.item_handle == b.item_handle or a.content_hash == b.content_hash
                or a.candidate_family_id == b.candidate_family_id
                or left.member.semantic_signature == right.member.semantic_signature):
            return False
        pair = pairs.get(frozenset((a.candidate_family_id, b.candidate_family_id)))
        return pair is not None and pair.relation == "independent"

    def unseen(record: PackCandidateV1) -> bool:
        item = record.candidate
        return not any(e.item_handle == item.item_handle or e.content_hash == item.content_hash
                       or e.family_id == item.candidate_family_id or e.semantic_signature == record.member.semantic_signature
                       for e in exposure.records)

    ordered = sorted(candidates, key=lambda r: r.candidate.item_handle)
    assessments = [r for r in ordered if r.candidate.slot == "assessment" and unseen(r)]
    practices = [r for r in ordered if r.candidate.slot == "practice"]
    remediations = [r for r in ordered if r.candidate.slot == "remediation"]
    selected = None
    for assess in combinations(assessments, 2):
        if not independent(*assess):
            continue
        eligible_practice = [p for p in practices if all(independent(p, a) for a in assess)]
        for practice in combinations(eligible_practice, 2):
            if not independent(*practice):
                continue
            for remediation in remediations:
                if (not all(independent(remediation, a) for a in assess)
                        or any(remediation.candidate.item_handle == p.candidate.item_handle
                               or remediation.candidate.content_hash == p.candidate.content_hash for p in practice)):
                    continue
                proposed = (*practice, *assess, remediation)
                # Every mapped objective clause independently receives 2/2/1.
                if all(sum(r.candidate.slot == slot and any(c.clause_id == clause and c.clause_hash == digest
                           for c in r.candidate.clauses) for r in proposed) >= count
                       for _, _, clause, digest in request.clause_mapping
                       for slot, count in (("practice", 2), ("assessment", 2), ("remediation", 1))):
                    selected = proposed
                    break
            if selected is not None:
                break
        if selected is not None:
            break
    if selected is None:
        reasons.append("independent_unexposed_coverage_gap")
        return PackResultV1(status="gap", request_hash=request.request_hash, reasons=tuple(dict.fromkeys(reasons))[:32])
    deadline = min(exposure.valid_until, *(r.valid_until for r in selected),
                   *(pair.valid_until for pair in pairs.values()),
                   *(r.candidate.proof.valid_until for r in selected if r.candidate.proof is not None),
                   *(r.candidate.current_authorization.valid_until for r in selected if r.candidate.current_authorization is not None))
    snapshot = PackSnapshotV1(request=request, inputs_hash=inputs.inputs_hash, selected=selected,
        family_pair_receipt_hashes=tuple(pair.receipt_hash for _, pair in sorted(pairs.items(), key=lambda entry: sorted(entry[0]))),
        exposure_receipt_hash=exposure.completeness_receipt_hash, exposure_watermark=exposure.watermark,
        checked_at=now, valid_until=deadline)
    return PackResultV1(status="complete", request_hash=request.request_hash, snapshot=snapshot)


@overload
def build_pack(inputs: PackInputsV1, *, now: datetime) -> PackResultV1: ...


@overload
def build_pack(inputs: PackInputsV2, *, now: datetime) -> PackResultV2: ...


def build_pack(inputs: PackInputsV1 | PackInputsV2, *, now: datetime) -> PackResultV1 | PackResultV2:
    """Version dispatch is explicit; default V1 bytes and rules remain unchanged."""
    if type(inputs) is PackInputsV2:
        return _build_pack_v2(inputs, now=now)
    if not isinstance(inputs, PackInputsV1):
        raise ValueError("invalid pack inputs version")
    return _build_pack_v1(checked_model(inputs, PackInputsV1), now=now)


def _build_pack_v2(inputs: PackInputsV2, *, now: datetime) -> PackResultV2:
    from app.services.learning.item_supply.finite_candidate_factory import build_finite_slot_allocation

    inputs = checked_model(inputs, PackInputsV2)
    require_aware(now)
    _validate_request(inputs)
    request = inputs.request
    slots = {entry.slot: entry for entry in request.demands}
    families = {f.family_id: f for f in families_for_course(request.target_id)}
    profiles: dict[str, TypeProfileV2] = {"python-kc-binding-v1": "kc", "python-state-update-v1": "python",
                                       "sqlite-predicate-order-v1": "sqlite"}
    profile = profiles[request.target_id]
    coarse_signatures = {h for f in families.values() for h in (f.definition_hash, f.structure_signature)}

    def gap(reason: str, *, stale: bool = False) -> PackResultV2:
        return PackResultV2(status="stale" if stale else "gap", request_hash=request.request_hash, reasons=(reason,))

    if any((d.blueprint.minimum.practice, d.blueprint.minimum.assessment, d.blueprint.minimum.remediation) != (2, 2, 1)
           for d in request.demands):
        return gap("minimum_profile_unsupported")
    exposure = inputs.exposure
    if exposure is None:
        return gap("exposure_incomplete")
    if (exposure.learner_id != request.learner_id or exposure.epoch != request.epoch
            or not exposure.observed_at <= now < exposure.valid_until):
        return gap("exposure_stale_or_wrong_owner", stale=True)
    if any(e.content.decision_signature in coarse_signatures for e in exposure.records):
        return gap("exposure_content_semantics_missing")

    candidates: list[PackCandidateV2] = []
    reasons: list[str] = []
    seen: set[str] = set()
    for record in inputs.candidates:
        item, member, evidence = record.candidate, record.member, record.type_evidence
        if item.item_handle in seen:
            return gap("duplicate_candidate_handle")
        seen.add(item.item_handle)
        entry = slots[item.slot]
        family = families.get(member.family_id)
        try:
            # Use B's real bounded allocation contract, not arbitrary variant
            # labels/hash placeholders that the native factory cannot produce.
            allocation = build_finite_slot_allocation(target_id=request.target_id,
                family_id=member.family_id, slot=item.slot,
                slot_index=2 if member.allocation_variant_id.endswith(":practice-2")
                    or member.allocation_variant_id.endswith(":assessment-2") else 1)
        except ValueError:
            reasons.append("family_member_mismatch")
            continue
        # V2 supports any explicit allocation of a supported family to an exact
        # slot/purpose. A V1 fixed allocation lookup must not make this unreachable.
        if (family is None or item.candidate_family_id != member.family_id
                or member.family_definition_hash != family.definition_hash
                or member.target_definition_hash != request.target_definition_hash
                or member.course_mapping_hash != request.course_mapping_hash
                or member.candidate_content_hash != item.content_hash
                or member.allocation_variant_id != allocation.variant_id
                or member.allocation_definition_hash != allocation.definition_hash
                or member.slot != item.slot or member.purpose != item.scope.purpose.value):
            reasons.append("family_member_mismatch")
            continue
        if (item.visibility == "private" and (record.owner_id != request.learner_id or record.epoch != request.epoch)
                or item.visibility == "public" and (record.owner_id is not None or record.epoch is not None)):
            reasons.append("candidate_owner_mismatch")
            continue
        if record.storage_scope_id != entry.storage_scope_id:
            reasons.append("candidate_storage_scope_mismatch")
            continue
        if not record.observed_at <= now < record.valid_until:
            reasons.append("candidate_observation_stale")
            continue
        if isinstance(item, NativeScopedCandidateV2) and (
                item.learner_id != request.learner_id or item.epoch != request.epoch
                or item.storage_scope_id != entry.storage_scope_id
                or item.course_mapping_hash != request.course_mapping_hash
                or item.scope.owner_ref != entry.demand.learner_ref):
            reasons.append("candidate_private_context_mismatch")
            continue
        # The shared pure coverage check is structural. V2's separate constructor
        # already validates public content ownership versus private context; no
        # V1 object is fabricated or namespace validator bypassed here.
        reason = _candidate_reason(cast(CandidateAuthorityV1, item), entry.demand, entry.blueprint, now)
        if reason is not None:
            reasons.append(reason)
            continue
        content = evidence.content
        if content.decision_signature in coarse_signatures:
            reasons.append("type_evidence_content_semantics_missing")
            continue
        if (content.item_handle != item.item_handle or content.version_id != record.version_id
                or content.content_hash != item.content_hash
                or content.actual_public_task_hash != member.actual_public_task_hash
                or content.actual_fixture_hash != member.actual_fixture_hash
                or evidence.profile != profile or evidence.scope_hash != item.scope.scope_hash
                or evidence.objective_hash != item.objective_hash
                or evidence.target_definition_hash != request.target_definition_hash
                or evidence.course_mapping_hash != request.course_mapping_hash
                or any(getattr(evidence, name) != getattr(item.scope, name) for name in (
                    "runtime_profile_id", "runtime_profile_hash", "scorer_version", "assistance_policy_hash"))):
            reasons.append("type_evidence_binding_mismatch")
            continue
        if not evidence.checked_at <= now < evidence.valid_until:
            reasons.append("type_evidence_stale")
            continue
        candidates.append(record)

    # Unknown/legacy content decision signatures cannot stand in for native V2
    # content identities. Duplicate events for the same real content are deduped,
    # but conflicting immutable projections fail closed.
    contents: dict[str, ContentIdentityV2] = {}
    for content in (*[c.type_evidence.content for c in candidates], *[e.content for e in exposure.records]):
        if content.item_handle in contents and contents[content.item_handle] != content:
            return gap("actual_content_identity_conflict")
        contents[content.item_handle] = content
    exposed = {e.content.item_handle: e.content for e in exposure.records}
    relations: dict[frozenset[str], ContentRelationshipEvidenceV2] = {}
    receipt_facts: dict[tuple[str, str, str], str] = {}
    for relation in inputs.relationships:
        # Reusing a persisted batch is allowed; mutating its original reviewer
        # facts or validity under the same receipt ID/hash is not. Pair and fresh
        # exposure fields are projections, not the immutable batch identity.
        batch_facts = canonical_hash(relation.model_dump(mode="json", exclude={
            "left", "right", "exposure_receipt_hash", "exposure_watermark", "reviews",
        }))
        receipt_projections = [("relationship", str(relation.receipt_id), relation.receipt_hash, batch_facts)]
        receipt_projections.extend(("review", str(review.receipt_id), review.receipt_hash,
            canonical_hash(review.model_dump(mode="json"))) for review in relation.reviews)
        for kind, receipt_id, receipt_hash, facts in receipt_projections:
            for identity_kind, identity in (("id", receipt_id), ("hash", receipt_hash)):
                receipt_key = (kind, identity_kind, identity)
                if receipt_key in receipt_facts and receipt_facts[receipt_key] != facts:
                    return gap("relationship_receipt_identity_conflict")
                receipt_facts[receipt_key] = facts
        key = frozenset((relation.left.item_handle, relation.right.item_handle))
        if (len(key) != 2 or key in relations or relation.request_hash != request.request_hash
                or relation.profile != profile
                or relation.exposure_receipt_hash != exposure.completeness_receipt_hash
                or relation.exposure_watermark != exposure.watermark):
            return gap("relationship_context_mismatch")
        # Bind both full actual content identities, never just IDs/family labels.
        if any(contents.get(content.item_handle) != content for content in (relation.left, relation.right)):
            return gap("relationship_content_mismatch")
        relations[key] = relation

    def compatible(left: ContentIdentityV2, right: ContentIdentityV2,
                   used: dict[frozenset[str], ContentRelationshipEvidenceV2]) -> bool:
        if assessment_clone(left, right):
            reasons.append("assessment_clone")
            return False
        key = frozenset((left.item_handle, right.item_handle))
        relation = relations.get(key)
        if relation is None:
            reasons.append("relationship_evidence_missing")
            return False
        reason = relationship_reason(relation, now=now)
        if reason is not None:
            reasons.append(reason)
            return False
        used[key] = relation
        return True

    ordered = sorted(candidates, key=lambda r: r.candidate.item_handle)
    assessments = []
    for record in ordered:
        if record.candidate.slot != "assessment":
            continue
        # Exact clones are intrinsic vetoes, not contingent on obtaining a
        # clearance for the other assessment first (or on input ordering).
        if any(assessment_clone(record.type_evidence.content, e) for e in exposed.values()):
            reasons.append("assessment_clone")
            continue
        assessments.append(record)
    practices = [r for r in ordered if r.candidate.slot == "practice"]
    remediations = [r for r in ordered if r.candidate.slot == "remediation"]
    selected: tuple[PackCandidateV2, ...] | None = None
    selected_relations: dict[frozenset[str], ContentRelationshipEvidenceV2] = {}
    for assess in combinations(assessments, 2):
        assess_relations: dict[frozenset[str], ContentRelationshipEvidenceV2] = {}
        if not compatible(assess[0].type_evidence.content, assess[1].type_evidence.content, assess_relations):
            continue
        if not all(compatible(a.type_evidence.content, e, assess_relations) for a in assess for e in exposed.values()):
            continue
        for practice in combinations(practices, 2):
            for remediation in remediations:
                proposed = (*practice, *assess, remediation)
                # Practice/practice independence is NOT required. All five items
                # and exact full contents still must be distinct.
                if (len({r.candidate.item_handle for r in proposed}) != 5
                        or len({r.candidate.content_hash for r in proposed}) != 5):
                    reasons.append("duplicate_selected_content")
                    continue
                used = dict(assess_relations)
                if not all(compatible(a.type_evidence.content, p.type_evidence.content, used)
                           for a in assess for p in (*practice, remediation)):
                    continue
                if not all(sum(r.candidate.slot == slot and any(c.clause_id == clause and c.clause_hash == digest
                               for c in r.candidate.clauses) for r in proposed) >= count
                           for _, _, clause, digest in request.clause_mapping
                           for slot, count in (("practice", 2), ("assessment", 2), ("remediation", 1))):
                    reasons.append("exact_clause_coverage_gap")
                    continue
                selected, selected_relations = proposed, used
                break
            if selected is not None:
                break
        if selected is not None:
            break
    if selected is None:
        reasons.append("nonredundant_unexposed_coverage_gap")
        return PackResultV2(status="gap", request_hash=request.request_hash, reasons=tuple(dict.fromkeys(reasons))[:32])
    deadline = min(exposure.valid_until, *(r.valid_until for r in selected),
        *(r.type_evidence.valid_until for r in selected),
        *(p.valid_until for p in selected_relations.values()),
        *(review.valid_until for p in selected_relations.values() for review in p.reviews),
        *(r.candidate.proof.valid_until for r in selected if r.candidate.proof is not None),
        *(r.candidate.current_authorization.valid_until for r in selected if r.candidate.current_authorization is not None))
    snapshot = PackSnapshotV2(request=request, inputs_hash=inputs.inputs_hash, selected=selected,
        relationship_receipt_hashes=tuple(p.receipt_hash for _, p in sorted(selected_relations.items(), key=lambda pair: sorted(pair[0]))),
        type_evidence_receipt_hashes=tuple(r.type_evidence.receipt_hash for r in selected),
        exposure_receipt_hash=exposure.completeness_receipt_hash, exposure_watermark=exposure.watermark,
        checked_at=now, valid_until=deadline)
    return PackResultV2(status="complete", request_hash=request.request_hash, snapshot=snapshot)
