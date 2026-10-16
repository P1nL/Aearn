"""Full original finite admission evaluation over a newly issued committed-DATA context."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from psycopg.types.json import Jsonb

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.admission import evaluate_admission
from app.services.learning.item_supply.diagnostic_policy import ReviewBundleV3, policy_for_hash
from app.services.learning.item_supply.finite_review_descriptor import finite_review_context
from app.services.learning.item_supply.finite_task_ambiguity import FiniteAmbiguityReceiptV1, FiniteTaskAmbiguityOwner, build_finite_ambiguity_plan
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.persistent_pack_committed_admission import IssuedCommittedChildAdmission, require
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.policies import ResourceAmounts
from app.services.learning.item_supply.review_contracts_v2 import AdmissionEvidenceV2, BlindSolveReceiptV2, ProbeOutcomeV2
from app.services.learning.item_supply.shared_admission_facts_contracts import IssuedSharedAdmissionFactsV1
from app.services.learning.item_supply.storage_contracts import checked_model

if TYPE_CHECKING:
    from app.services.learning.item_supply.shared_admission_facts import SharedAdmissionFactsOwner


@dataclass(frozen=True)
class CommittedQualityObservation:
    """Typed read-only proof-composition inputs; never a SharedReviewResult issuer."""
    blind: BlindSolveReceiptV2
    bundle: ReviewBundleV3
    ambiguity: FiniteAmbiguityReceiptV1


def build(owner: SharedAdmissionFactsOwner, frame: IssuedCommittedChildAdmission, *, committed: bool,
          checked_at: datetime | None = None, valid_until: datetime | None = None) -> IssuedSharedAdmissionFactsV1:
    from app.services.learning.item_supply.shared_admission_facts import SharedAdmissionFactsOwner, _target_proof
    if (type(owner) is not SharedAdmissionFactsOwner or owner._committed_admission is not frame or not owner.enabled
            or owner.conn is not frame.owner.conn or not frame.owner.settings.learning_item_v2_admission_enabled
            or owner.normal_readmission_owner is not frame.normal_owner):
        raise PipelineRepositoryError("COMMITTED_ADMISSION_ORIGINAL_FACTS_OWNER_REQUIRED")
    now = require(frame,committed=committed)
    q, ambiguity = frame.quality, frame.ambiguity
    if ambiguity.plan != build_finite_ambiguity_plan(q.source,spec=q.spec,inputs=q.inputs) or ambiguity.mode != "static_options":
        raise PipelineRepositoryError("COMMITTED_ADMISSION_NEW_STATIC_AMBIGUITY_REQUIRED")
    # Verify the ORIGINAL deterministic rule over this newly persisted observation.
    # No historical run timestamps or _runs/_issued entries are recreated.
    verifier = FiniteTaskAmbiguityOwner(None,parent_deadline_at=frame.valid_until)
    if verifier._receipt(ambiguity.plan,ambiguity.run_id,(),started=ambiguity.started_at,completed=ambiguity.completed_at) != ambiguity:
        raise PipelineRepositoryError("COMMITTED_ADMISSION_STATIC_AMBIGUITY_CHANGED")
    static = q.inputs.static_facts
    if static is None:
        raise PipelineRepositoryError("COMMITTED_ADMISSION_ONLY_FINITE_KC")
    fh = canonical_hash(static.model_dump(mode="json"))
    counts = dict(positive_cases=sum(o.accepted for o in static.options),negative_cases=sum(not o.accepted for o in static.options),
        false_positives=0,false_negatives=0,pending_cases=0)
    if (counts["positive_cases"],counts["negative_cases"]) != (1,3):
        raise PipelineRepositoryError("COMMITTED_ADMISSION_UNIQUE_STATIC_PROPOSITIONS_REQUIRED")
    probes = tuple(ProbeOutcomeV2.model_validate(dict(probe=name,passed=True,receipt_hash=canonical_hash(dict(facts=fh,
        options=[o.model_dump(mode="json") for o in static.options if o.accepted == accepted]))))
        for name,accepted in (("correct",True),("incorrect",False))) + (
            ProbeOutcomeV2(probe="ambiguity",passed=True,receipt_hash=ambiguity.receipt_hash),)
    proof = _target_proof(q,CommittedQualityObservation(q.blind,q.bundle,ambiguity),(fh,))
    claims: set[str] = set()
    for material,expected in zip(q.request.materials,q.generation_receipt.sources,strict=True):
        claims.update(frame.owner.type_owner.source_authority.assert_current(material,expected).claim_receipt_hashes)
    if not claims:
        raise PipelineRepositoryError("COMMITTED_ADMISSION_CURRENT_SOURCE_REQUIRED")
    evidence = AdmissionEvidenceV2(binding=q.bundle.binding,validation_receipt_hash=q.validation.evidence_hash,
        source_current=True,source_claim_receipt_hashes=tuple(sorted(claims)),coverage_proof_hash=None if proof is None else proof.proof_hash,
        probes=probes,execution_receipt_hash=None,execution_isolated=False,runner_available=False,scorer_available=True,known_misjudgments=0)
    with finite_review_context(q.source,spec=q.spec,materials=q.request.materials):
        evaluation = evaluate_admission(q.source,binding=q.bundle.binding,policy=policy_for_hash(q.bundle.binding.policy_hash),
            validation_receipt=q.validation,author_identity=q.bundle.author_identity,bundle=q.bundle,evidence=evidence,enabled=True)
    stamp,until = checked_at or now,valid_until or frame.valid_until
    if not stamp <= now < until <= frame.valid_until:
        raise PipelineRepositoryError("COMMITTED_ADMISSION_EXPIRED")
    scope = q.spec.coverage_blueprint.scope
    return IssuedSharedAdmissionFactsV1(receipt_id=frame.admission_id,root_id=q.artifact["root_id"],
        generation_artifact_id=q.artifact["id"],artifact_hash=q.artifact["artifact_hash"],item_id=q.artifact["item_id"],version_id=q.artifact["version_id"],
        lease=frame.lease,continuation_binding_hash=None,target_id=q.spec.target_id,target_definition_hash=q.spec.target_definition_hash,
        specification_hash=q.spec.specification_hash,public_task_hash=q.inputs.public_task_hash,instance_hash=q.inputs.instance_hash,
        inputs_hash=canonical_hash(q.inputs.model_dump(mode="json")),coverage_blueprint_hash=q.spec.coverage_blueprint.blueprint_hash,
        profile_hash=frame.lease.profile.profile_hash,runtime_profile_hash=scope.runtime_profile_hash,scorer_version=scope.scorer_version,
        validation_preparation_id=q.validation_preparation["id"],validation_receipt_id=q.validation_row["id"],blind_receipt_id=q.blind_row["id"],
        review_receipt_id=q.review_row["id"],validation_receipt_hash=q.validation.evidence_hash,blind_receipt_hash=q.blind.receipt_hash,
        review_receipt_hash=q.bundle.bundle_hash,validation_budget=None,review_budget=q.review_budget,review_execution_usage=ResourceAmounts(),
        validation_terminals=(),blind_terminals=(),ambiguity=ambiguity,scorer_counts=counts,target_proof=proof,evidence=evidence,evaluation=evaluation,
        checked_at=stamp,valid_until=until)


def issue(owner: SharedAdmissionFactsOwner, frame: IssuedCommittedChildAdmission) -> IssuedSharedAdmissionFactsV1:
    if frame.admission_id in owner._committed_issued:
        raise PipelineRepositoryError("COMMITTED_ADMISSION_FACTS_ONCE_USE_VERIFY")
    facts = build(owner,frame,committed=True)
    owner._committed_pending = facts
    try:
        frame.normal_owner.persist_committed(frame,facts_owner=owner,facts=facts)
        lease = frame.lease
        row = owner.conn.execute("INSERT INTO tutor_item_supply_shared_admission_facts "
            "(id,root_id,job_id,lease_owner,lease_generation,lease_state_version,profile_hash,generation_artifact_id,item_id,version_id,"
            "source_hash,content_hash,continuation_binding_hash,validation_preparation_id,validation_receipt_id,blind_receipt_id,review_receipt_id,payload_json) "
            "VALUES("+",".join(["%s"]*18)+") RETURNING payload_hash",(facts.receipt_id,facts.root_id,lease.job_id,lease.lease_owner,
            lease.generation,lease.state_version,facts.profile_hash,facts.generation_artifact_id,facts.item_id,facts.version_id,
            facts.evidence.binding.source_hash,facts.evidence.binding.content_hash,None,facts.validation_preparation_id,
            facts.validation_receipt_id,facts.blind_receipt_id,facts.review_receipt_id,Jsonb(facts.model_dump(mode="json")))).fetchone()
        if row is None or row["payload_hash"] != facts.receipt_hash:
            raise PipelineRepositoryError("COMMITTED_ADMISSION_FACTS_HASH_CHANGED")
        owner._committed_issued[facts.receipt_id] = facts
        return facts
    finally:
        owner._committed_pending = None


def verify(owner: SharedAdmissionFactsOwner, facts: IssuedSharedAdmissionFactsV1, *, lease: JobLeaseV1) -> AdmissionEvidenceV2:
    frame = owner._committed_admission
    facts = checked_model(facts,IssuedSharedAdmissionFactsV1)
    if frame is None or owner._committed_issued.get(facts.receipt_id) != facts or lease != frame.lease or facts.lease != lease:
        raise PipelineRepositoryError("COMMITTED_ADMISSION_FACTS_ISSUER_REQUIRED")
    current = build(owner,frame,committed=True,checked_at=facts.checked_at,valid_until=facts.valid_until)
    row = owner.conn.execute("SELECT payload_json,payload_hash FROM tutor_item_supply_shared_admission_facts WHERE id=%s FOR SHARE",
        (facts.receipt_id,)).fetchone()
    if row is None or current != facts or row["payload_json"] != facts.model_dump(mode="json") or row["payload_hash"] != facts.receipt_hash:
        raise PipelineRepositoryError("COMMITTED_ADMISSION_CURRENT_FACTS_CHANGED")
    frame.normal_owner.verify_committed(frame,facts=facts)
    return facts.evidence

