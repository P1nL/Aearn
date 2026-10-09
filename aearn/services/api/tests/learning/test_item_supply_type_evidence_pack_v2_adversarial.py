"""Checker regressions: offline projections do not mint native authority."""
from datetime import timedelta
from uuid import uuid4

import pytest
from pydantic import Field

from app.services.learning.item_supply.finite_candidate_factory import check_finite_public_spec
from app.services.learning.item_supply.finite_task_families import families_for_course
from app.services.learning.item_supply.pack_builder import build_pack
from app.services.learning.item_supply.pack_contracts import (
    CrossPoolMappingV1, NativeExposureV2, PackSelectionV1,
)
from app.services.learning.item_supply.selection import select_pack
from app.services.learning.item_supply.type_evidence import ContentIdentityV2, relationship_binding_hash
from tests.learning.test_item_supply_contracts import NOW, digest
from tests.learning.test_item_supply_flexible_spec import flexible_spec, proposed_source
from tests.learning.test_item_supply_pack import inputs as legacy_inputs
from tests.learning.test_item_supply_type_evidence_pack_v2 import inputs_v2, with_relationships


def pool_pair():
    base = inputs_v2()
    a = base.request
    private = inputs_v2(private=True, context=(a.learner_id, a.track_id, a.revision_id, a.node_id))
    mapping = CrossPoolMappingV1(base_request_hash=a.request_hash,
        enhancement_request_hash=private.request.request_hash, mapping_receipt_hash=digest("offline-mapping"),
        checked_at=NOW-timedelta(seconds=1), valid_until=NOW+timedelta(seconds=30))
    return base, private, mapping


@pytest.mark.parametrize("target", ["python-state-update-v1", "sqlite-predicate-order-v1", "python-kc-binding-v1"])
def test_pack_all_five_allocation_members_match_actual_v3_factory_specs(target):
    # Only allocation reachability is real here. Semantic/reviewer fingerprints
    # remain declared OFFLINE fixtures, never native nonredundancy certification.
    data = inputs_v2(target_id=target)
    counts = {}
    for seed, record in enumerate(data.candidates, 1):
        member = record.member
        counts[member.slot] = counts.get(member.slot, 0) + 1
        family_index = next(i for i, f in enumerate(families_for_course(target)) if f.family_id == member.family_id)
        spec, _ = flexible_spec(target, slot=member.slot, slot_index=counts[member.slot],
            seed=seed, family_index=family_index)
        check_finite_public_spec(proposed_source(spec).public, spec)
        allocation = spec.allocation
        assert (member.allocation_variant_id, member.allocation_definition_hash, member.family_id,
                member.family_definition_hash, member.slot, member.purpose) == (
            allocation.variant_id, allocation.definition_hash, allocation.family_id,
            spec.family_definition_hash, allocation.slot, allocation.purpose)
    assert build_pack(data, now=NOW).status == "complete"


@pytest.mark.parametrize("field,value", [("allocation_variant_id", "invented-offline-variant"),
    ("allocation_definition_hash", digest("invented-allocation")), ("slot", "assessment"),
    ("purpose", "remediation")])
def test_nonfactory_allocation_or_slot_cannot_be_laundered_by_member_labels(field, value):
    data = inputs_v2()
    record, *rest = data.candidates
    record = record.model_copy(update={"member": record.member.model_copy(update={field: value})})
    result = build_pack(data.model_copy(update={"candidates": (record, *rest), "relationships": ()}), now=NOW)
    assert result.snapshot is None and "family_member_mismatch" in result.reasons


@pytest.mark.parametrize("mutation", ["actor_id", "receipt_id", "receipt_hash", "covered_binding_hashes",
    "rationale_evidence_hash", "checked_at", "valid_until"])
def test_reused_batch_review_identity_cannot_change_immutable_facts(mutation):
    data = inputs_v2()
    pair, *rest = data.relationships
    review, *other_reviews = pair.reviews
    changes = {"actor_id": uuid4(), "receipt_id": uuid4(), "receipt_hash": digest("changed-review"),
        "covered_binding_hashes": (*review.covered_binding_hashes, digest("new-unreviewed-binding")),
        "rationale_evidence_hash": digest("changed-rationale"), "checked_at": NOW-timedelta(seconds=2),
        "valid_until": NOW+timedelta(minutes=5)}
    changed = review.model_copy(update={mutation: changes[mutation]})
    pair = pair.model_copy(update={"reviews": (changed, *other_reviews)})
    result = build_pack(data.model_copy(update={"relationships": (pair, *rest)}), now=NOW)
    assert result.reasons == ("relationship_receipt_identity_conflict",)


@pytest.mark.parametrize("mutation", ["receipt_id", "receipt_hash", "checked_at", "valid_until"])
def test_reused_relation_batch_cannot_change_immutable_identity_or_renew_dates(mutation):
    data = inputs_v2()
    pair, *rest = data.relationships
    changes = {"receipt_id": uuid4(), "receipt_hash": digest("changed-relation"),
        "checked_at": NOW-timedelta(seconds=2), "valid_until": NOW+timedelta(minutes=6)}
    pair = pair.model_copy(update={mutation: changes[mutation]})
    result = build_pack(data.model_copy(update={"relationships": (pair, *rest)}), now=NOW)
    assert result.reasons == ("relationship_receipt_identity_conflict",)


@pytest.mark.parametrize("mutation", ["watermark", "receipt", "records"])
def test_v2_enhancement_cannot_use_a_different_current_complete_ledger(mutation):
    base, private, mapping = pool_pair()
    exposure = private.exposure
    if mutation == "watermark":
        exposure = exposure.model_copy(update={"watermark": 1})
    elif mutation == "receipt":
        exposure = exposure.model_copy(update={"completeness_receipt_hash": digest("different-ledger")})
    else:
        record = private.candidates[0]
        content = record.type_evidence.content
        event = NativeExposureV2(event_id=uuid4(), item_handle=content.item_handle,
            content_hash=content.content_hash, content=content, family_id=record.member.family_id,
            semantic_signature=record.member.semantic_signature, kind="hint")
        exposure = exposure.model_copy(update={"records": (event,)})
    private = private.model_copy(update={"exposure": exposure, "relationships": tuple(p.model_copy(update={
        "exposure_watermark": exposure.watermark, "exposure_receipt_hash": exposure.completeness_receipt_hash})
        for p in private.relationships)})
    assert build_pack(private, now=NOW).status == "complete"
    result = select_pack(base, enhancement=private, mapping=mapping, now=NOW)
    assert result.status == "computed_base" and result.pack.request == base.request


def test_known_exposed_private_assessment_cannot_be_erased_by_empty_enhancement():
    base, private, mapping = pool_pair()
    selected = next(r for r in private.candidates if r.candidate.slot == "assessment")
    # Make this private OFFLINE candidate genuinely distinct from the public
    # fixture's fingerprints, with all immutable item/proof/source bindings kept.
    content_hash, task_hash = digest("private-distinct-content"), digest("private-distinct-task")
    item = selected.candidate
    item = item.model_copy(update={"content_hash": content_hash,
        "proof": item.proof.model_copy(update={"content_hash": content_hash}),
        "current_authorization": item.current_authorization.model_copy(update={"content_hash": content_hash})})
    content = selected.type_evidence.content.model_copy(update={"content_hash": content_hash,
        "actual_public_task_hash": task_hash, "decision_signature": digest("private-distinct-decision"),
        "answer_leakage_signature": digest("private-distinct-contextual-leakage")})
    selected = selected.model_copy(update={"candidate": item, "original_proof_hash": item.proof.proof_hash,
        "member": selected.member.model_copy(update={"candidate_content_hash": content_hash, "actual_public_task_hash": task_hash}),
        "type_evidence": selected.type_evidence.model_copy(update={"content": content})})
    private = with_relationships(private.model_copy(update={"candidates": tuple(selected if
        r.candidate.item_handle == selected.candidate.item_handle else r for r in private.candidates)}))
    event = NativeExposureV2(event_id=uuid4(), item_handle=content.item_handle, content_hash=content.content_hash,
        content=content, family_id=selected.member.family_id, semantic_signature=selected.member.semantic_signature, kind="shown")
    base = base.model_copy(update={"exposure": base.exposure.model_copy(update={"watermark": 1,
        "completeness_receipt_hash": digest("known-exposure"), "records": (event,)})})
    base = with_relationships(base, extra_pairs=tuple((r.type_evidence.content, content)
        for r in base.candidates if r.candidate.slot == "assessment"))
    assert build_pack(base, now=NOW).status == build_pack(private, now=NOW).status == "complete"
    assert select_pack(base, enhancement=private, mapping=mapping, now=NOW).status == "computed_base"
    # Supplying the actual ledger also makes the private builder reject the clone.
    exposed_private = private.model_copy(update={"exposure": base.exposure})
    exposed_private = with_relationships(exposed_private)
    assert "assessment_clone" in build_pack(exposed_private, now=NOW).reasons


@pytest.mark.parametrize("value", ["", None])
def test_empty_records_are_not_complete_without_a_valid_completeness_receipt(value):
    data = inputs_v2()
    assert data.exposure.records == ()
    exposure = data.exposure.model_copy(update={"completeness_receipt_hash": value})
    with pytest.raises(ValueError):
        build_pack(data.model_copy(update={"exposure": exposure}), now=NOW)


def test_v1_base_v2_enhancement_falls_back_without_version_reinterpretation():
    base = legacy_inputs()
    result = select_pack(base, enhancement=inputs_v2(private=True), now=NOW)
    assert type(result) is PackSelectionV1 and result.status == "computed_base"
    assert result.pack.request == base.request
    assert select_pack(base, enhancement=inputs_v2(), now=NOW+timedelta(minutes=6)).status == "unavailable"


def test_transient_exposure_renewal_cannot_extend_original_review_deadline():
    data = inputs_v2()
    exposure = data.exposure.model_copy(update={"observed_at": NOW+timedelta(minutes=4),
        "completeness_receipt_hash": digest("fresh-exposure-after-old-reviews-expired")})
    data = data.model_copy(update={"exposure": exposure, "relationships": tuple(p.model_copy(update={
        "exposure_receipt_hash": exposure.completeness_receipt_hash}) for p in data.relationships)})
    result = build_pack(data, now=NOW+timedelta(minutes=4))
    assert result.snapshot is None and "relationship_stale" in result.reasons


def test_nested_excluded_subclass_field_cannot_disappear_through_evidence_or_hash():
    class ForgedIdentity(ContentIdentityV2):
        native_permission: bool = Field(default=True, exclude=True)

    data = inputs_v2()
    record, *rest = data.candidates
    content = ForgedIdentity(**record.type_evidence.content.model_dump())
    assert "native_permission" not in content.model_dump()
    bad = record.model_copy(update={"type_evidence": record.type_evidence.model_copy(update={"content": content})})
    bad_data = data.model_copy(update={"candidates": (bad, *rest)})
    with pytest.raises(ValueError):
        build_pack(bad_data, now=NOW)
    with pytest.raises(ValueError):
        _ = bad_data.inputs_hash
    with pytest.raises(ValueError):
        relationship_binding_hash(profile="python", request_hash=data.request.request_hash,
            left=content, right=data.candidates[1].type_evidence.content)
