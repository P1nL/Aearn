"""Original finite KC committed quality reader. DATA only, no Prepared/ports/registry recovery."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from uuid import UUID

from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash
from app.services.learning.item_bank.review_contracts import REQUIRED_REVIEW_ROLES
from app.services.learning.item_supply.blind_protocol import SINGLE_CHOICE_BLIND_PROTOCOL
from app.services.learning.item_supply.diagnostic_policy import AutonomousEvidencePolicyV3, ReviewBundleV3, checked_bundle
from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1
from app.services.learning.item_supply.finite_candidate_validation import FiniteCandidateValidationInputsV1, prepare_finite_candidate_validation
from app.services.learning.item_supply.finite_review_descriptor import finite_review_context
from app.services.learning.item_supply.finite_static_blind_scorer import FiniteStaticBlindScorer
from app.services.learning.item_supply.generation_contracts import GenerationReceiptV2, GenerationRequestV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.persistent_pack_committed_recheck import CHILD, PREPARATION, _history
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.policies import ResourceAmounts
from app.services.learning.item_supply.review_contracts_v2 import BlindSolveReceiptV2
from app.services.learning.item_supply.review_provider import blind_input
from app.services.learning.item_supply.review_protocol import make_review_request, verify_review_report
from app.services.learning.item_supply.shared_admission_facts_contracts import SharedFactsBudgetV1
from app.services.learning.item_supply.shared_pipeline_repository import SharedPipelineArtifactRepository
from app.services.learning.item_supply.validation_adapter import CandidateValidationV2

RECHECK = UUID("f3c2a54f-7f4b-4181-a8c0-ef783f24c919")
VALIDATION = UUID("d358224f-bc80-4aec-8eee-3a6ed6d7b0ec")
BLIND = UUID("8b74793c-8153-44a2-83ba-3b8ec9fc0cb5")
REVIEW = UUID("402d599d-a5f1-45e3-a285-c115e40238f6")
REVIEW_JOB = UUID("4316f475-9655-4f58-baf1-fcc0359be8b8")
REVIEW_PHASE = UUID("92cb8c13-09ac-4f52-8b12-5dfea54d97f5")


def _model(cls: Any, value: Any) -> Any:
    return cls.model_validate_json(json.dumps(value))


def _row(conn: Any, table: str, key: str, identity: UUID) -> dict[str, Any]:
    row = conn.execute("SELECT *,xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction FROM "
        + table + " WHERE " + key + "=%s FOR SHARE", (identity,)).fetchone()
    if row is None or row["same_transaction"]:
        raise PipelineRepositoryError("COMMITTED_QUALITY_SEPARATE_COMMIT_REQUIRED")
    return dict(row)


@dataclass(frozen=True, repr=False)
class CommittedChildQuality:
    artifact: dict[str, Any]
    lineage: dict[str, Any]
    recheck: dict[str, Any]
    recheck_preparation: dict[str, Any]
    validation_row: dict[str, Any]
    validation_preparation: dict[str, Any]
    validation_evidence: dict[str, Any]
    blind_row: dict[str, Any]
    review_row: dict[str, Any]
    review_lease: JobLeaseV1
    validation_lease: JobLeaseV1
    source: LearningItemSourceV1
    request: GenerationRequestV2
    generation_receipt: GenerationReceiptV2
    spec: FiniteCandidateSpecV1
    inputs: FiniteCandidateValidationInputsV1
    validation: CandidateValidationV2
    blind: BlindSolveReceiptV2
    bundle: ReviewBundleV3
    review_budget: SharedFactsBudgetV1
    matched_answer: str

    def payload(self) -> dict[str, Any]:
        static = self.inputs.static_facts
        assert static is not None
        return dict(schema_version="committed_child_quality_data_v1", artifact_id=str(self.artifact["id"]),
            artifact_hash=self.artifact["artifact_hash"], source_hash=self.source.source_hash, content_hash=self.source.content_hash,
            producer_job_id=str(self.artifact["job_id"]), lineage_id=str(self.lineage["id"]), lineage_hash=self.lineage["snapshot_hash"],
            recheck_receipt_id=str(self.recheck["id"]), recheck_hash=self.recheck["snapshot_hash"],
            recheck_preparation_hash=self.recheck_preparation["snapshot_hash"],
            validation_preparation_id=str(self.validation_preparation["id"]), validation_preparation_hash=self.validation_preparation["payload_hash"],
            validation_evidence_id=str(self.validation_evidence["id"]), validation_evidence_hash=self.validation_evidence["payload_hash"],
            validation_receipt_id=str(self.validation_row["id"]), validation_hash=self.validation_row["receipt_hash"],
            blind_receipt_id=str(self.blind_row["id"]), blind_hash=self.blind_row["receipt_hash"],
            review_receipt_id=str(self.review_row["id"]), review_hash=self.review_row["receipt_hash"],
            review_lease=self.review_lease.model_dump(mode="json"), validation_lease=self.validation_lease.model_dump(mode="json"),
            historical_continuation_hash=self.review_row["continuation_binding_hash"],
            binding=self.bundle.binding.model_dump(mode="json"), specification_hash=self.spec.specification_hash,
            request_hash=canonical_hash(self.request.model_dump(mode="json")), inputs_hash=canonical_hash(self.inputs.model_dump(mode="json")),
            static_facts_hash=canonical_hash(static.model_dump(mode="json")), matched_answer=self.matched_answer,
            solution_hash=self.blind.solution_hash, score=self.blind.score.model_dump(mode="json"),
            review_budget=self.review_budget.model_dump(mode="json"))


def read_committed_quality(core: Any) -> CommittedChildQuality:
    """DB history + original finite rules; all old dates are issuance-time checks."""
    conn = core.conn
    h = _history(core, PREPARATION, CHILD, PREPARATION)
    a, line, producer_p = h["artifact"], h["lineage"], h["preparation"]
    p = _row(conn, "tutor_item_supply_shared_revision_recheck_preparations", "id", RECHECK)
    rr = _row(conn, "tutor_item_supply_shared_revision_recheck_receipts", "id", RECHECK)
    vr, br, peer = tuple(_row(conn, "tutor_item_supply_shared_pipeline_receipts", "id", identity)
        for identity in (VALIDATION, BLIND, REVIEW))
    old_lease = _model(JobLeaseV1, rr["payload_json"]["lease"])
    for row in (p, rr):
        if (row["job_id"] != REVIEW_JOB or row["generation_artifact_id"] != CHILD
                or row["snapshot_hash"] != canonical_hash(row["payload_json"])):
            raise PipelineRepositoryError("COMMITTED_QUALITY_RECHECK_CHANGED")
    until = min(p["valid_until"], old_lease.expires_at, old_lease.parent_deadline, old_lease.profile.parent_deadline_at)
    if (rr["payload_json"]["preparation_hash"] != p["snapshot_hash"] or p["lineage_id"] != PREPARATION
            or rr["payload_json"]["lineage_hash"] != line["snapshot_hash"]
            or (rr["validation_receipt_id"],rr["blind_receipt_id"],rr["review_receipt_id"]) != (VALIDATION,BLIND,REVIEW)
            or not p["created_at"] <= rr["created_at"] < until
            or rr["payload_json"]["schema_version"] != "native_shared_revision_recheck_receipt_v2"
            or rr["payload_json"]["blockers_discharged"] is not False
            or rr["payload_json"]["admission_eligible"] is not False):
        raise PipelineRepositoryError("COMMITTED_QUALITY_HISTORICAL_RECHECK_INVALID")
    for row, kind in ((vr,"validation"),(br,"blind_solve"),(peer,"review_bundle")):
        if (row["job_id"] != REVIEW_JOB or row["generation_artifact_id"] != CHILD or row["artifact_kind"] != kind
                or row["lease_generation"] != old_lease.generation or row["lease_owner"] != old_lease.lease_owner
                or row["source_hash"] != a["source_hash"] or row["content_hash"] != a["content_hash"]
                or not p["created_at"] <= row["created_at"] <= rr["created_at"] < until
                or row["mode"] != "live" or row["publication_enabled"] is not False):
            raise PipelineRepositoryError("COMMITTED_QUALITY_HISTORICAL_STAGE_INVALID")
    prep_id = UUID(vr["artifact_key"].removeprefix("validation."))
    vp = _row(conn, "tutor_item_supply_shared_validation_preparations", "id", prep_id)
    ve = _row(conn, "tutor_item_supply_shared_validation_evidence", "preparation_id", prep_id)
    spec = _model(FiniteCandidateSpecV1, vp["payload_json"]["spec"])
    source, request, generation_receipt = (_model(LearningItemSourceV1,a["source_json"]),
        _model(GenerationRequestV2,a["request_json"]),_model(GenerationReceiptV2,a["receipt_json"]))
    inputs = prepare_finite_candidate_validation(source,spec=spec,materials=request.materials)
    validation = _model(CandidateValidationV2,vr["payload_json"])
    validation_lease = _model(JobLeaseV1,vp["payload_json"]["lease"])
    if (spec.target_id != "python-kc-binding-v1" or inputs.static_facts is None or validation != inputs.static_facts.validation
            or validation.state != "machine_verified" or vr["receipt_hash"] != validation.evidence_hash
            or vp["job_id"] != REVIEW_JOB or vp["generation_artifact_id"] != CHILD
            or vp["payload_hash"] != canonical_hash(vp["payload_json"]) or ve["payload_hash"] != canonical_hash(ve["payload_json"])
            or vp["payload_json"]["request"] != a["request_json"] or vp["payload_json"]["inputs"] != inputs.model_dump(mode="json")
            or vp["payload_json"]["artifact_hash"] != a["artifact_hash"] or ve["payload_json"]["validation"] != vr["payload_json"]
            or ve["payload_json"]["actual"] is not None or ve["payload_json"]["terminals"] != [] or ve["reservation_id"] is not None
            or spec.model_dump(mode="json") != producer_p["payload_json"]["context"]["persistent_family_revision"]["child_specification"]
            or validation_lease.profile != old_lease.profile or validation_lease.job_id != REVIEW_JOB
            or validation_lease.generation != old_lease.generation or validation_lease.state_version > old_lease.state_version):
        raise PipelineRepositoryError("COMMITTED_QUALITY_STATIC_VALIDATION_CHANGED")
    blind = _model(BlindSolveReceiptV2,br["payload_json"])
    bundle = _model(ReviewBundleV3,peer["payload_json"])
    checked_bundle(bundle)
    if (br["receipt_hash"] != blind.receipt_hash or peer["receipt_hash"] != bundle.bundle_hash
            or bundle.blind_solve != blind or rr["payload_json"]["review_hash"] != bundle.bundle_hash
            or bundle.binding.profile_hash != old_lease.profile.profile_hash
            or bundle.bundle_version != p["payload_json"]["bundle_version"]):
        raise PipelineRepositoryError("COMMITTED_QUALITY_BLIND_REVIEW_CHANGED")
    with finite_review_context(source,spec=spec,materials=request.materials):
        original_input = blind_input(source,bundle.binding,blind_protocol=SINGLE_CHOICE_BLIND_PROTOCOL)
        if blind.run.input_hash != original_input.input_hash:
            raise PipelineRepositoryError("COMMITTED_QUALITY_BLIND_INPUT_CHANGED")
        for report in bundle.reports:
            verify_review_report(report,make_review_request(source,binding=bundle.binding,
                validation_receipt=validation,role=report.role,protocol="evidenced-v1"))
        answer = FiniteStaticBlindScorer.verify_committed_single_choice(source,spec=spec,materials=request.materials,blind=blind)
    runs = (blind.run,*(r.run for r in bundle.reports))
    forbidden = {UUID(x) for x in p["payload_json"]["forbidden_run_ids"]}
    if (tuple(r.role for r in bundle.reports) != REQUIRED_REVIEW_ROLES or len({r.run_id for r in runs}) != 7
            or forbidden & {r.run_id for r in runs} or any(r.max_output_tokens != 61440 for r in runs)):
        raise PipelineRepositoryError("COMMITTED_QUALITY_COMPLETE_INDEPENDENT_RUNS_REQUIRED")
    for ancestor in p["payload_json"]["ancestor_reviews"]:
        old = _row(conn,"tutor_item_supply_shared_pipeline_receipts","id",UUID(ancestor["receipt_id"]))
        if old["receipt_hash"] != ancestor["receipt_hash"]:
            raise PipelineRepositoryError("COMMITTED_QUALITY_ANCESTOR_CHANGED")
    continuation = _row(conn,"tutor_item_supply_shared_candidate_continuations","job_id",REVIEW_JOB)
    if (continuation["generation_artifact_id"] != CHILD or continuation["original_job_id"] != a["job_id"]
            or any(row["continuation_binding_hash"] != continuation["binding_hash"] for row in (vr,br,peer))
            or continuation["binding_json"]["original_request_hash"] != canonical_hash(a["request_json"])):
        raise PipelineRepositoryError("COMMITTED_QUALITY_ORIGINAL_491_REQUIRED")
    policy = SharedPipelineArtifactRepository(conn,enabled=True).published_generation_policy(a)
    if type(policy) is not AutonomousEvidencePolicyV3 or policy.policy_hash != bundle.binding.policy_hash:
        raise PipelineRepositoryError("COMMITTED_QUALITY_ORIGINAL_POLICY_REQUIRED")
    reservation = _row(conn,"tutor_item_supply_shared_reservations","id",UUID(peer["artifact_key"].removeprefix("review_bundle.")))
    settled = _row(conn,"tutor_item_supply_shared_runtime_settlements","reservation_id",reservation["id"])
    key = "review."+CHILD.hex
    if (reservation["job_id"] != REVIEW_JOB or reservation["root_id"] != a["root_id"] or reservation["requests"] != 7
            or reservation["reservation_key"] != key or settled["settlement_key"] != key or settled["usage_state"] != "unknown"
            or settled["cost_amount"] is not None or settled["receipt_hash"] is not None):
        raise PipelineRepositoryError("COMMITTED_QUALITY_ORIGINAL_UNKNOWN_SETTLEMENT_REQUIRED")
    amounts = conn.execute("SELECT DISTINCT resource_kind,reserved_amount FROM tutor_item_supply_runtime_global_reservation_amounts "
        "WHERE reservation_namespace='shared' AND reservation_id=%s",(reservation["id"],)).fetchall()
    resources = ResourceAmounts(**{r["resource_kind"]:int(r["reserved_amount"]) for r in amounts})
    if resources.requests != 7 or resources.output_tokens != 7*61440:
        raise PipelineRepositoryError("COMMITTED_QUALITY_EXACT_ORIGINAL_RESERVATION_REQUIRED")
    budget = SharedFactsBudgetV1(reservation_id=reservation["id"],settlement_id=settled["id"],settlement_key=key,
        reserved=resources,usage_state="unknown",actual=None,receipt_hash=None)
    return CommittedChildQuality(a,line,rr,p,vr,vp,ve,br,peer,old_lease,validation_lease,
        source,request,generation_receipt,spec,inputs,validation,blind,bundle,budget,answer)

