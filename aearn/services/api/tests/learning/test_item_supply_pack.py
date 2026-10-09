"""Pure synthetic inventory, never live family/exposure/source authority."""
from datetime import timedelta
from itertools import combinations
from uuid import uuid4

import pytest

from app.services.learning.item_bank.contracts import LearningItemInteraction, LearningItemKind, LearningItemPurpose
from app.services.learning.item_supply.contracts import AssessmentSupplyDemandV1, CoverageBlueprintV1, ObjectiveClauseV1
from app.services.learning.item_supply.finite_course_targets import get_finite_course_target
from app.services.learning.item_supply.finite_task_families import families_for_course, initial_slot_allocations
from app.services.learning.item_supply.matrix import build_support_matrix
from app.services.learning.item_supply.pack_builder import build_pack
from app.services.learning.item_supply.pack_contracts import (
    AuthorizedSubDemandV1, CompleteExposureV1, CrossPoolMappingV1, FamilyMemberEvidenceV1,
    FamilyPairEvidenceV1, ExecutedFamilyTransferWitnessV1, NativeCandidateV1, NativeExposureV1,
    NativeProofV1, PackCandidateV1, PackInputsV1, PackRequestV1, StaticFamilyTransferWitnessV1,
)
from app.services.learning.item_supply.selection import select_pack
from tests.learning.test_item_supply_contracts import NOW, digest, make_scope, synthetic_candidate


def inputs(*, private=False, context=None, target_id="python-state-update-v1", runtime_profile_id=None):
    target = get_finite_course_target(target_id)
    learner, track, revision, node = context or tuple(uuid4() for _ in range(4))
    storage, remediation_storage = uuid4(), uuid4()
    mapping = tuple((c.clause_id, c.definition_hash, "python.c" + str(i), c.definition_hash)
                    for i, c in enumerate(target.clauses, 1))
    demands = []
    for slot in ("practice", "assessment", "remediation"):
        scope = make_scope(knowledge_key="finite." + target.target_id,
            language_id=target.language_id, subject_id=target.subject_id,
            dialect="sqlite" if target.language_id == "sql" else None,
            item_kind=LearningItemKind(target.assessment.item_kind),
            interaction=LearningItemInteraction(target.assessment.interaction), required_facets=target.required_facets,
            required_capabilities=target.required_capabilities,
            runtime_profile_id=runtime_profile_id or target.assessment.runtime_profile_id or "static-exact-v1",
            assessment_contract_version=target.target_id,
            purpose=LearningItemPurpose.REMEDIATION if slot == "remediation" else LearningItemPurpose(target.assessment.purpose),
            visibility="private" if private else "public", owner_ref="user:" + str(learner) if private else None)
        blueprint = CoverageBlueprintV1(scope=scope, objective_hash=digest("synthetic-objective"),
            clauses=tuple(ObjectiveClauseV1(clause_id=m[2], clause_hash=m[3]) for m in mapping),
            matrix_hash=build_support_matrix().matrix_hash, policy_version="supply-v1")
        demand = AssessmentSupplyDemandV1(demand_id="synthetic-demand-" + slot, learner_ref="user:" + str(learner),
            scope=scope, objective_hash=blueprint.objective_hash, blueprint_hash=blueprint.blueprint_hash,
            matrix_hash=blueprint.matrix_hash, policy_version=blueprint.policy_version, input_revision=1)
        demands.append(AuthorizedSubDemandV1(slot=slot, storage_scope_id=remediation_storage if slot == "remediation" else storage,
            demand=demand, blueprint=blueprint, mapping_receipt_hash=digest("synthetic-sub-demand-" + slot)))
    request = PackRequestV1(target_id=target.target_id, target_definition_hash=target.definition_hash,
        learner_id=learner, epoch=1, track_id=track, revision_id=revision, node_id=node, storage_scope_id=storage,
        course_mapping_hash=digest("synthetic-course-mapping"), clause_mapping=mapping, demands=tuple(demands))
    families = {f.family_id: f for f in families_for_course(target.target_id)}
    candidates = []
    for index, allocation in enumerate(initial_slot_allocations(target.target_id), 1):
        entry = next(d for d in demands if d.slot == allocation.slot)
        candidate = synthetic_candidate(entry.blueprint, index, allocation.slot)
        handle = "lip:v2:" + str(uuid4()) if private else candidate.item_handle
        assert candidate.proof is not None
        proof = NativeProofV1.model_validate({**candidate.proof.model_dump(), "item_handle": handle,
                                            "candidate_family_id": allocation.family_id})
        native = NativeCandidateV1.model_validate({**candidate.model_dump(), "item_handle": handle,
            "candidate_family_id": allocation.family_id, "proof": proof})
        member = FamilyMemberEvidenceV1(family_id=allocation.family_id,
            family_definition_hash=families[allocation.family_id].definition_hash,
            allocation_variant_id=allocation.variant_id, allocation_definition_hash=allocation.definition_hash,
            allocation_receipt_hash=digest("synthetic-allocation-" + str(index)), target_definition_hash=target.definition_hash,
            actual_public_task_hash=digest("synthetic-task-" + str(index)), actual_fixture_hash=digest("synthetic-fixture-" + allocation.family_id),
            semantic_signature=digest("synthetic-semantic-" + allocation.family_id), course_mapping_hash=request.course_mapping_hash,
            candidate_content_hash=native.content_hash, receipt_hash=digest("synthetic-member-" + str(index)))
        candidates.append(PackCandidateV1(candidate=native, member=member, publication_id=uuid4(), materialization_id=uuid4(),
            proof_id=uuid4(), version_id=uuid4(), owner_id=learner if private else None, epoch=1 if private else None,
            storage_scope_id=entry.storage_scope_id, original_publication_hash=digest("synthetic-publication-" + str(index)),
            original_materialization_hash=digest("synthetic-material-" + str(index)), original_proof_hash=proof.proof_hash,
            complete_source_set_hash=digest("synthetic-source-set-" + str(index)), runtime_or_static_observation_hash=digest("synthetic-runtime"),
            observed_at=NOW-timedelta(seconds=1), valid_until=NOW+timedelta(minutes=5)))
    pairs = []
    for left, right in combinations(families, 2):
        witness_bindings = tuple(dict(source_family_id=a, target_family_id=b,
            source_submission_hash=digest("synthetic-source-submission-" + a),
            source_fixture_hash=digest("synthetic-fixture-" + a),
            adapted_submission_hash=digest("synthetic-adapted-" + a + b), target_fixture_hash=digest("synthetic-fixture-" + b),
            outcome="successful_semantic_mismatch") for a, b in ((left, right), (right, left)))
        if target.target_id == "python-kc-binding-v1":
            witnesses = tuple(StaticFamilyTransferWitnessV1(**binding,
                source_response_verification_hash=digest("synthetic-source-response-" + binding["source_family_id"]),
                target_response_verification_hash=digest("synthetic-target-response-" + binding["target_family_id"]),
                truth_derivation_hash=digest("synthetic-static-truth")) for binding in witness_bindings)
        else:
            witnesses = tuple(ExecutedFamilyTransferWitnessV1(**binding,
                source_terminal_receipt_hash=digest("synthetic-source-terminal-" + binding["source_family_id"]),
                source_scorer_receipt_hash=digest("synthetic-source-scorer-" + binding["source_family_id"]),
                terminal_receipt_hash=digest("synthetic-terminal-" + binding["target_family_id"]),
                scorer_receipt_hash=digest("synthetic-scorer-" + binding["target_family_id"])) for binding in witness_bindings)
        pairs.append(FamilyPairEvidenceV1(left_family_id=left, right_family_id=right,
            left_semantic_signature=digest("synthetic-semantic-" + left), right_semantic_signature=digest("synthetic-semantic-" + right),
            course_mapping_hash=request.course_mapping_hash, relation="independent", witnesses=witnesses,
            review_receipts=tuple((role, digest("synthetic-review-" + role + left + right)) for role in ("curriculum", "technical", "ambiguity", "adversarial")),
            receipt_hash=digest("synthetic-pair-" + left + right), checked_at=NOW-timedelta(seconds=1), valid_until=NOW+timedelta(minutes=5)))
    exposure = CompleteExposureV1(learner_id=learner, epoch=1, collector_version="synthetic-complete-v1", watermark=0,
        completeness_receipt_hash=digest("synthetic-exposure"), observed_at=NOW-timedelta(seconds=1), valid_until=NOW+timedelta(minutes=5))
    return PackInputsV1(request=request, candidates=tuple(candidates), family_pairs=tuple(pairs), exposure=exposure)


def test_native_private_and_shared_five_slots_compute_without_claiming_live_ready():
    # Same narrow runtime seam as the native factory; all authority is synthetic.
    for target_id, runtime_id in (("python-state-update-v1", "python-stdout-v1"),
            ("sqlite-predicate-order-v1", "sqlite-query-v1"), ("python-kc-binding-v1", "static-exact-v1")):
        target = get_finite_course_target(target_id)
        for private in (False, True):
            data = inputs(private=private, target_id=target_id)
            assert all(entry.demand.scope.runtime_profile_id == runtime_id for entry in data.request.demands)
            result = build_pack(data, now=NOW)
            assert result.status == "complete" and result.snapshot is not None
            assert len(result.snapshot.selected) == 5
            assert result.snapshot.authority_status == "trusted_caller_computation_only"
            assert all(r.candidate.item_handle.startswith("lip:v2:" if private else "li:") for r in result.snapshot.selected)
            assert len(result.snapshot.snapshot_hash) == 64
        wrong_native_id = "python-stdout-v1" if runtime_id != "python-stdout-v1" else "sqlite-query-v1"
        for wrong_id in (target.assessment.execution_contract, wrong_native_id):
            with pytest.raises(ValueError, match="pack target scope mismatch"):
                build_pack(inputs(target_id=target_id, runtime_profile_id=wrong_id), now=NOW)


@pytest.mark.parametrize("missing", ["complete_exposure", "family_pair", "family_conflict", "shown_assessment", "other_owner"])
def test_false_readiness_inputs_stay_gap(missing):
    data = inputs(private=True)
    update = {}
    if missing == "complete_exposure":
        update["exposure"] = None
    elif missing == "family_pair":
        update["family_pairs"] = data.family_pairs[:-1]
    elif missing == "family_conflict":
        update["family_pairs"] = (data.family_pairs[0].model_copy(update={"relation": "conflict"}), *data.family_pairs[1:])
    elif missing == "other_owner":
        update["candidates"] = tuple(r.model_copy(update={"owner_id": uuid4()}) for r in data.candidates)
    else:
        assert data.exposure is not None
        assessment = next(r for r in data.candidates if r.candidate.slot == "assessment")
        event = NativeExposureV1(event_id=uuid4(), item_handle=assessment.candidate.item_handle,
            content_hash=assessment.candidate.content_hash, family_id=assessment.member.family_id,
            semantic_signature=assessment.member.semantic_signature, kind="shown")
        update["exposure"] = data.exposure.model_copy(update={"records": (event,), "watermark": 1})
    assert build_pack(data.model_copy(update=update), now=NOW).snapshot is None


def test_whole_base_enhancement_mapping_fallback_and_stale_base():
    base = inputs()
    a = base.request
    enhanced = inputs(private=True, context=(a.learner_id, a.track_id, a.revision_id, a.node_id))
    mapping = CrossPoolMappingV1(base_request_hash=a.request_hash, enhancement_request_hash=enhanced.request.request_hash,
        mapping_receipt_hash=digest("synthetic-cross-pool"), checked_at=NOW-timedelta(seconds=1), valid_until=NOW+timedelta(seconds=30))
    selected = select_pack(base, now=NOW, enhancement=enhanced, mapping=mapping)
    assert selected.status == "computed_enhancement" and selected.valid_until == mapping.valid_until
    failed = enhanced.model_copy(update={"candidates": enhanced.candidates[:-1]})
    assert select_pack(base, now=NOW, enhancement=failed, mapping=mapping).status == "computed_base"
    assert select_pack(base, now=NOW+timedelta(minutes=6), enhancement=enhanced, mapping=mapping).status == "unavailable"
