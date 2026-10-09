"""Offline trusted-fact fixtures only; random IDs/hashes are NOT native proof."""
from datetime import timedelta
from itertools import combinations
from uuid import uuid4

import pytest

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.finite_task_families import families_for_course
from app.services.learning.item_supply.finite_candidate_factory import build_finite_slot_allocation
from app.services.learning.item_supply.pack_builder import build_pack
from app.services.learning.item_supply.pack_contracts import (
    CompleteExposureV2, CrossPoolMappingV1, FamilyMemberEvidenceV2,
    NativeCandidateV1, NativeExposureV2, NativeProofV1,
    PackCandidateV2, PackInputsV2, PackResultV1, PackResultV2, PackSelectionV2,
)
from app.services.learning.item_supply.selection import select_pack
from app.services.learning.item_supply.type_evidence import (
    ContentIdentityV2, ContentRelationshipEvidenceV2, KCTypeEvidenceV2,
    PythonTypeEvidenceV2, RelationshipReviewV2, SQLiteTypeEvidenceV2,
    relationship_binding_hash, relationship_reason,
)
from tests.learning.test_item_supply_contracts import NOW, digest
from tests.learning.test_item_supply_pack import inputs as legacy_inputs


def with_relationships(data, *, extra_pairs=()):
    """Four offline batch reviews, NOT seven pairs * four provider calls."""
    assessments = [c.type_evidence.content for c in data.candidates if c.candidate.slot == "assessment"]
    training = [c.type_evidence.content for c in data.candidates if c.candidate.slot != "assessment"]
    pairs = [*combinations(assessments, 2), *((a, p) for a in assessments for p in training), *extra_pairs]
    assert data.exposure is not None
    profile = data.candidates[0].type_evidence.profile
    covered = tuple(relationship_binding_hash(profile=profile, request_hash=data.request.request_hash,
                                              left=a, right=b) for a, b in pairs)
    batch = tuple(RelationshipReviewV2(role=role, actor_id=uuid4(), receipt_id=uuid4(),
        receipt_hash=digest("offline-batch-" + role), covered_binding_hashes=covered,
        conclusion="nonredundant", rationale_evidence_hash=digest("offline-reviewed-content-" + role),
        checked_at=NOW-timedelta(seconds=1), valid_until=NOW+timedelta(minutes=4))
        for role in ("curriculum", "technical", "ambiguity", "adversarial"))
    # One native relation batch may itself be projected over multiple exact pairs.
    batch_id = uuid4()
    relations = tuple(ContentRelationshipEvidenceV2(profile=profile, request_hash=data.request.request_hash,
        left=a, right=b, exposure_receipt_hash=data.exposure.completeness_receipt_hash,
        exposure_watermark=data.exposure.watermark, reviews=batch, receipt_id=batch_id,
        receipt_hash=digest("offline-relation-batch"), checked_at=NOW-timedelta(seconds=1),
        valid_until=NOW+timedelta(minutes=5)) for a, b in pairs)
    return data.model_copy(update={"relationships": relations})


def inputs_v2(*, target_id="python-state-update-v1", private=False, context=None):
    old = legacy_inputs(target_id=target_id, private=private, context=context)
    families = families_for_course(target_id)
    family = next(f for f in families if f.task_kind == "diagnose") if target_id == "python-kc-binding-v1" else families[0]
    author = uuid4()
    records = []
    slot_counts = {}
    for i, old_record in enumerate(old.candidates, 1):
        item = old_record.candidate
        slot_counts[item.slot] = slot_counts.get(item.slot, 0) + 1
        allocation = build_finite_slot_allocation(target_id=target_id, family_id=family.family_id,
            slot=item.slot, slot_index=slot_counts[item.slot])
        proof = NativeProofV1.model_validate({**item.proof.model_dump(), "candidate_family_id": family.family_id})
        candidate = NativeCandidateV1.model_validate({**item.model_dump(), "proof": proof,
                                                     "candidate_family_id": family.family_id})
        member = FamilyMemberEvidenceV2.model_validate({**old_record.member.model_dump(),
            "schema_version": "family_member_evidence_v2", "family_id": family.family_id,
            "family_definition_hash": family.definition_hash,
            "allocation_variant_id": allocation.variant_id,
            "allocation_definition_hash": allocation.definition_hash,
            "semantic_signature": family.definition_hash,  # legacy coarse identity
            "slot": candidate.slot, "purpose": candidate.scope.purpose.value})
        decision = "training-method" if candidate.slot != "assessment" else "assessment-decision-" + str(i)
        content = ContentIdentityV2(item_handle=candidate.item_handle, version_id=old_record.version_id,
            content_hash=candidate.content_hash, actual_public_task_hash=member.actual_public_task_hash,
            actual_fixture_hash=member.actual_fixture_hash, decision_signature=digest("offline-" + decision),
            answer_leakage_signature=digest("offline-contextual-answer-" + decision), author_id=author)
        common = dict(content=content, scope_hash=candidate.scope.scope_hash,
            objective_hash=candidate.objective_hash, target_definition_hash=old.request.target_definition_hash,
            course_mapping_hash=old.request.course_mapping_hash,
            runtime_profile_id=candidate.scope.runtime_profile_id,
            runtime_profile_hash=candidate.scope.runtime_profile_hash, scorer_version=candidate.scope.scorer_version,
            assistance_policy_hash=candidate.scope.assistance_policy_hash,
            validation_receipt_hash=digest("offline-validation-" + str(i)),
            item_review_bundle_hash=digest("offline-six-role-item-review-" + str(i)),
            receipt_id=uuid4(), receipt_hash=digest("offline-type-receipt-" + str(i)),
            checked_at=NOW-timedelta(seconds=1), valid_until=NOW+timedelta(minutes=5))
        if target_id == "python-kc-binding-v1":
            evidence = KCTypeEvidenceV2(**common, truth_derivation_hash=digest("offline-truth"),
                all_options_verification_hash=digest("offline-options"), blind_solve_receipt_hash=digest("offline-blind"),
                ambiguity_review_receipt_hash=digest("offline-ambiguity"),
                misconception_review_receipt_hash=digest("offline-misconceptions"))
        else:
            cls = PythonTypeEvidenceV2 if target_id == "python-state-update-v1" else SQLiteTypeEvidenceV2
            evidence = cls(**common, terminal_receipt_hash=digest("offline-terminal"),
                scorer_receipt_hash=digest("offline-scorer"), reference_submission_hash=digest("offline-reference"),
                equivalent_submission_hash=digest("offline-different-equivalent"),
                reference_execution_hash=digest("offline-reference-execution"),
                equivalent_execution_hash=digest("offline-equivalent-execution"),
                wrong_solution_control_hash=digest("offline-wrong"), hardcoded_control_hash=digest("offline-hardcoded"),
                boundary_control_hash=digest("offline-boundaries"))
        records.append(PackCandidateV2.model_validate({**old_record.model_dump(), "candidate": candidate,
            "member": member, "type_evidence": evidence, "original_proof_hash": proof.proof_hash}))
    exposure = CompleteExposureV2.model_validate({**old.exposure.model_dump(), "records": ()})
    return with_relationships(PackInputsV2(request=old.request, candidates=tuple(records), exposure=exposure))


@pytest.mark.parametrize("target", ["python-kc-binding-v1", "python-state-update-v1", "sqlite-predicate-order-v1"])
@pytest.mark.parametrize("private", [False, True])
def test_one_family_five_items_no_transfers_or_practice_independence(target, private):
    data = inputs_v2(target_id=target, private=private)
    result = build_pack(data, now=NOW)
    assert isinstance(result, PackResultV2) and result.status == "complete"
    pack = result.snapshot
    assert pack is not None and pack.authority_status == "trusted_caller_computation_only"
    assert len({r.member.family_id for r in pack.selected}) == 1
    assert len({r.member.semantic_signature for r in pack.selected}) == 1  # coarse is not actual
    assert [r.candidate.slot for r in pack.selected].count("assessment") == 2
    assert len(pack.relationship_receipt_hashes) == 7
    assert data.legacy_family_pairs == ()
    assert pack.valid_until == NOW+timedelta(minutes=4)  # original reviewer bound
    assert len({r.receipt_id for p in data.relationships for r in p.reviews}) == 4
    assert len(pack.snapshot_hash) == 64


@pytest.mark.parametrize("mutation,reason", [
    ("missing", "relationship_evidence_missing"), ("stale", "relationship_stale"),
    ("uncertain", "relationship_conflict_or_uncertain"),
    ("binding", "relationship_review_binding_mismatch"),
    ("actor", "relationship_review_independence_missing"),
    ("author", "relationship_review_independence_missing"),
    ("receipt", "relationship_review_independence_missing"),
    ("owner", "relationship_context_mismatch"), ("watermark", "relationship_context_mismatch"),
    ("changed_content", "relationship_content_mismatch"),
])
def test_relation_gap_conflict_stale_binding_and_independence(mutation, reason):
    data = inputs_v2()
    pair, *rest = data.relationships
    review, *other_reviews = pair.reviews
    if mutation == "missing":
        data = data.model_copy(update={"relationships": tuple(rest)})
    else:
        if mutation == "stale":
            pair = pair.model_copy(update={"valid_until": NOW})
        elif mutation == "owner":
            pair = pair.model_copy(update={"request_hash": data.request.model_copy(update={"learner_id": uuid4()}).request_hash})
        elif mutation == "watermark":
            pair = pair.model_copy(update={"exposure_watermark": 1})
        elif mutation == "changed_content":
            pair = pair.model_copy(update={"left": pair.left.model_copy(update={"decision_signature": digest("changed")})})
        else:
            updates = {"uncertain": {"conclusion": "uncertain"},
                "binding": {"covered_binding_hashes": (digest("unbound"),)},
                "actor": {"actor_id": other_reviews[0].actor_id},
                "author": {"actor_id": pair.left.author_id},
                "receipt": {"receipt_id": other_reviews[0].receipt_id}}[mutation]
            review = review.model_copy(update=updates)
            pair = pair.model_copy(update={"reviews": (review, *other_reviews)})
        data = data.model_copy(update={"relationships": (pair, *rest)})
    result = build_pack(data, now=NOW)
    assert result.snapshot is None
    if mutation in {"stale", "uncertain", "binding", "actor", "author", "receipt"}:
        # A mutated copy of this reused immutable batch is now denied even before
        # selection. The original individual judgment veto must still hold too.
        assert relationship_reason(pair, now=NOW) == reason
        assert "relationship_receipt_identity_conflict" in result.reasons
    else:
        assert reason in result.reasons


@pytest.mark.parametrize("field", ["item_handle", "content_hash", "actual_public_task_hash", "decision_signature", "answer_leakage_signature"])
def test_exact_exposure_clones_deny_without_a_clearance_receipt(field):
    data = inputs_v2()
    assessment = next(r for r in data.candidates if r.candidate.slot == "assessment")
    content = assessment.type_evidence.content
    # A different actual exposure which shares the selected clone coordinate.
    event_content = content.model_copy(update={name: uuid4() if name == "version_id" else
        "li:"+digest("different-item") if name == "item_handle" else digest("different-" + name)
        for name in ("item_handle", "version_id", "content_hash", "actual_public_task_hash",
                     "decision_signature", "answer_leakage_signature") if name != field})
    event = NativeExposureV2(event_id=uuid4(), item_handle=event_content.item_handle,
        content_hash=event_content.content_hash, family_id=assessment.member.family_id,
        semantic_signature=assessment.member.semantic_signature, content=event_content, kind="hint")
    exposure = data.exposure.model_copy(update={"records": (event,), "watermark": 1})
    data = data.model_copy(update={"exposure": exposure,
        "relationships": tuple(p.model_copy(update={"exposure_watermark": 1}) for p in data.relationships)})
    result = build_pack(data, now=NOW)
    assert result.snapshot is None
    assert "assessment_clone" in result.reasons or "actual_content_identity_conflict" in result.reasons


def test_fresh_exposure_reuses_same_native_batch_reviews_no_model_rerun():
    data = inputs_v2()
    first = build_pack(data, now=NOW)
    training = next(r for r in data.candidates if r.candidate.slot == "practice")
    content = training.type_evidence.content
    event = NativeExposureV2(event_id=uuid4(), item_handle=content.item_handle,
        content_hash=content.content_hash, family_id=training.member.family_id,
        semantic_signature=training.member.semantic_signature, content=content, kind="hint")
    exposure = data.exposure.model_copy(update={"records": (event,), "watermark": 1,
        "completeness_receipt_hash": digest("fresh-complete-exposure"), "observed_at": NOW+timedelta(seconds=30)})
    refreshed = data.model_copy(update={"exposure": exposure, "relationships": tuple(p.model_copy(update={
        "exposure_receipt_hash": exposure.completeness_receipt_hash, "exposure_watermark": 1}) for p in data.relationships)})
    second = build_pack(refreshed, now=NOW+timedelta(seconds=30))
    assert first.snapshot is not None and second.snapshot is not None
    assert first.snapshot.snapshot_hash != second.snapshot.snapshot_hash
    for a, b in zip(data.relationships, refreshed.relationships, strict=True):
        assert a.binding_hash == b.binding_hash and a.reviews == b.reviews
        assert (a.receipt_id, a.receipt_hash, a.checked_at, a.valid_until) == (b.receipt_id, b.receipt_hash, b.checked_at, b.valid_until)
    assert first.snapshot.valid_until == second.snapshot.valid_until  # no extension
    assert second.snapshot.exposure_watermark == 1


def test_new_nonclone_exposure_needs_exact_relation_not_family_or_prose_clearance():
    data = inputs_v2()
    seed = data.candidates[0].type_evidence.content
    content = seed.model_copy(update={"item_handle": "li:"+digest("new-exposed"), "version_id": uuid4(),
        "content_hash": digest("new-content"), "actual_public_task_hash": digest("new-task"),
        "decision_signature": digest("new-decision"), "answer_leakage_signature": digest("new-contextual-answer")})
    event = NativeExposureV2(event_id=uuid4(), item_handle=content.item_handle, content_hash=content.content_hash,
        family_id=data.candidates[0].member.family_id, semantic_signature=data.candidates[0].member.semantic_signature,
        content=content, kind="shown")
    data = data.model_copy(update={"exposure": data.exposure.model_copy(update={"records": (event,)})})
    assert "relationship_evidence_missing" in build_pack(data, now=NOW).reasons
    assessments = [r.type_evidence.content for r in data.candidates if r.candidate.slot == "assessment"]
    approved = with_relationships(data, extra_pairs=tuple((a, content) for a in assessments))
    assert build_pack(approved, now=NOW).status == "complete"


@pytest.mark.parametrize("mutation,reason", [
    ("owner", "candidate_owner_mismatch"), ("type", "type_evidence_binding_mismatch"),
    ("scorer", "type_evidence_binding_mismatch"), ("proof", "proof_mismatch"),
    ("runtime", "runtime_unavailable"), ("published", "not_published"),
    ("source", "authorization_inactive"), ("exposure_owner", "exposure_stale_or_wrong_owner"),
    ("exposure_epoch", "exposure_stale_or_wrong_owner"), ("exposure_missing", "exposure_incomplete"),
    ("duplicate", "duplicate_candidate_handle"),
])
def test_existing_native_fences_still_deny(mutation, reason):
    data = inputs_v2(private=True)
    record, *rest = data.candidates
    if mutation.startswith("exposure_"):
        exposure = None if mutation == "exposure_missing" else data.exposure.model_copy(update={
            "learner_id": uuid4()} if mutation == "exposure_owner" else {"epoch": 2})
        data = data.model_copy(update={"exposure": exposure})
    elif mutation == "duplicate":
        data = data.model_copy(update={"candidates": (record, record, *rest)})
    else:
        if mutation == "owner":
            record = record.model_copy(update={"owner_id": uuid4()})
        elif mutation in {"type", "scorer"}:
            record = record.model_copy(update={"type_evidence": record.type_evidence.model_copy(update={
                "content": record.type_evidence.content.model_copy(update={"content_hash": digest("altered")})}
                if mutation == "type" else {"scorer_version": "different-scorer"})})
        else:
            candidate = record.candidate
            changes = {"proof": {"proof": candidate.proof.model_copy(update={"evidence_hash": digest("altered")})},
                "runtime": {"runtime_available": False}, "published": {"published": False},
                "source": {"current_authorization": candidate.current_authorization.model_copy(update={"active": False})}}[mutation]
            record = record.model_copy(update={"candidate": candidate.model_copy(update=changes)})
        # Remove relationships involving the excluded item to examine its precise
        # native fence rather than unrelated dangling relationship projections.
        data = data.model_copy(update={"candidates": (record, *rest), "relationships": ()})
    result = build_pack(data, now=NOW)
    assert result.snapshot is None and reason in result.reasons


def test_v2_whole_enhancement_fallback_mapping_and_current_base():
    base = inputs_v2()
    a = base.request
    private = inputs_v2(private=True, context=(a.learner_id, a.track_id, a.revision_id, a.node_id))
    mapping = CrossPoolMappingV1(base_request_hash=a.request_hash, enhancement_request_hash=private.request.request_hash,
        mapping_receipt_hash=digest("offline-cross-pool"), checked_at=NOW-timedelta(seconds=1),
        valid_until=NOW+timedelta(seconds=30))
    selection = select_pack(base, enhancement=private, mapping=mapping, now=NOW)
    assert isinstance(selection, PackSelectionV2) and selection.status == "computed_enhancement"
    assert selection.valid_until == mapping.valid_until
    assert select_pack(base, enhancement=private.model_copy(update={"exposure": None}), mapping=mapping, now=NOW).status == "computed_base"
    assert select_pack(base, enhancement=legacy_inputs(private=True), mapping=mapping, now=NOW).status == "computed_base"
    assert select_pack(base, enhancement=private, mapping=mapping, now=NOW+timedelta(seconds=40)).status == "computed_base"
    assert select_pack(base, enhancement=private, mapping=mapping, now=NOW+timedelta(minutes=6)).status == "unavailable"


def test_v1_defaults_hash_shape_and_family_gate_remain_unchanged():
    old = legacy_inputs()
    result = build_pack(old, now=NOW)
    assert type(result) is PackResultV1 and result.status == "complete"
    assert "schema_version" not in old.model_dump()
    assert old.inputs_hash == canonical_hash(old.model_dump(mode="json"))
    assert result.snapshot.snapshot_hash == canonical_hash(result.snapshot.model_dump(mode="json"))
    assert build_pack(old.model_copy(update={"family_pairs": ()}), now=NOW).reasons == ("family_pair_evidence_incomplete",)
    assert build_pack(inputs_v2().model_copy(update={"legacy_family_pairs": old.family_pairs}), now=NOW).status == "complete"


def test_strict_profiles_do_not_accept_passed_flags_or_fake_kc_os_fields():
    kc = inputs_v2(target_id="python-kc-binding-v1")
    evidence = kc.candidates[0].type_evidence
    for extra in ({"passed": True}, {"terminal_receipt_hash": digest("fake-os")}, {"profile": "generic"}):
        with pytest.raises(ValueError):
            KCTypeEvidenceV2.model_validate({**evidence.model_dump(), **extra})
    data = inputs_v2()
    record, *rest = data.candidates
    bad = record.type_evidence.model_copy(update={"equivalent_submission_hash": record.type_evidence.reference_submission_hash})
    with pytest.raises(ValueError):
        build_pack(data.model_copy(update={"candidates": (record.model_copy(update={"type_evidence": bad}), *rest)}), now=NOW)
    pair = data.relationships[0]
    assert relationship_reason(pair, now=NOW+timedelta(minutes=4)) == "relationship_stale"


def test_legacy_coarse_family_hash_cannot_be_upgraded_to_content_semantics():
    data = inputs_v2()
    record, *rest = data.candidates
    content = record.type_evidence.content.model_copy(update={"decision_signature": record.member.family_definition_hash})
    bad = record.model_copy(update={"type_evidence": record.type_evidence.model_copy(update={"content": content})})
    result = build_pack(data.model_copy(update={"candidates": (bad, *rest), "relationships": ()}), now=NOW)
    assert result.snapshot is None and "type_evidence_content_semantics_missing" in result.reasons
    event = NativeExposureV2(event_id=uuid4(), item_handle=content.item_handle, content_hash=content.content_hash,
        family_id=record.member.family_id, semantic_signature=record.member.family_definition_hash,
        content=content, kind="shown")
    exposure = data.exposure.model_copy(update={"records": (event,)})
    assert build_pack(data.model_copy(update={"exposure": exposure}), now=NOW).reasons == ("exposure_content_semantics_missing",)


def test_coincident_raw_answer_is_not_a_contextual_leakage_fingerprint():
    # Two unrelated KC tasks happen to use option B. Only a trusted upstream
    # semantic producer can certify these task-bound fingerprints in live use.
    data = inputs_v2(target_id="python-kc-binding-v1")
    a, b = [r.type_evidence.content for r in data.candidates if r.candidate.slot == "assessment"]
    answer_a = canonical_hash({"offline_context": "post-update state", "answer": "B", "task": a.actual_public_task_hash})
    answer_b = canonical_hash({"offline_context": "pre-update observation", "answer": "B", "task": b.actual_public_task_hash})
    assert answer_a != answer_b
    # Raw answers are not accepted anywhere in the projection schema.
    with pytest.raises(ValueError):
        ContentIdentityV2.model_validate({**a.model_dump(), "raw_answer": "B"})
    assert build_pack(data, now=NOW).status == "complete"


@pytest.mark.parametrize("other_slot", ["assessment", "practice", "remediation"])
def test_assessment_semantic_clone_veto_even_with_four_positive_batch_verdicts(other_slot):
    data = inputs_v2()
    assessment = next(r for r in data.candidates if r.candidate.slot == "assessment")
    other = next(r for r in data.candidates if r.candidate.slot == other_slot and r is not assessment)
    content = assessment.type_evidence.content.model_copy(update={
        "decision_signature": other.type_evidence.content.decision_signature})
    assessment = assessment.model_copy(update={"type_evidence": assessment.type_evidence.model_copy(update={"content": content})})
    data = data.model_copy(update={"candidates": tuple(assessment if r.candidate.item_handle == assessment.candidate.item_handle else r
                                                     for r in data.candidates)})
    reviewed = with_relationships(data)
    result = build_pack(reviewed, now=NOW)
    assert result.snapshot is None and "assessment_clone" in result.reasons


def test_duplicate_assessment_handle_and_missing_exact_clause_cannot_count_twice():
    data = inputs_v2()
    assessment = next(r for r in data.candidates if r.candidate.slot == "assessment")
    duplicate = data.model_copy(update={"candidates": (*data.candidates, assessment)})
    assert build_pack(duplicate, now=NOW).reasons == ("duplicate_candidate_handle",)
    clauses = assessment.candidate.clauses[:-1]
    proof = assessment.candidate.proof.model_copy(update={"clauses": clauses})
    candidate = assessment.candidate.model_copy(update={"clauses": clauses, "proof": proof})
    assessment = assessment.model_copy(update={"candidate": candidate, "original_proof_hash": proof.proof_hash})
    partial = data.model_copy(update={"candidates": tuple(assessment if r.candidate.item_handle == assessment.candidate.item_handle else r
                                                        for r in data.candidates)})
    result = build_pack(partial, now=NOW)
    assert result.snapshot is None and "exact_clause_coverage_gap" in result.reasons
