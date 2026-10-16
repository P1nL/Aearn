"""PRIVATE committed relation DATA; never restores a Prepared/run/lease capability."""
from __future__ import annotations
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import NAMESPACE_URL, UUID, uuid5
from pydantic import Field, model_validator
from psycopg.types.json import Jsonb
from app.services.learning.item_bank.contracts import canonical_hash, canonical_json
from app.services.learning.item_supply.contracts import Digest
from app.services.learning.item_supply.finite_course_targets import get_finite_course_target
from app.services.learning.item_supply.native_type_contracts import NativeRelationJudgment, NativeRelationReport, NativeTypeEvidencePending
from app.services.learning.item_supply.persistent_pack_contracts import PersistentPackTaskRef, PersistentPublicPhaseRecord, SLOTS
from app.services.learning.item_supply.review_contracts_v2 import ProviderIdentityV2
from app.services.learning.item_supply.storage_contracts import StorageContract, checked_model
from app.services.learning.item_supply.type_evidence import TypeProfileV2, relationship_binding_hash
if TYPE_CHECKING:
    from app.services.learning.item_supply.native_relation_review import NativeRelationReviewProducer
    from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner

class CommittedNativeRelationFindingV1(StorageContract):
    """Actual PRIVATE model finding DATA; not a fake peer/clone or admission."""
    schema_version: Literal["persistent_committed_relation_finding_v1"] = "persistent_committed_relation_finding_v1"
    affected_slot: Literal["assessment-1", "assessment-2"]
    parent_revision_id: UUID
    parent_version_id: UUID
    pair: tuple[UUID, UUID]
    pair_kind: Literal["assessment_assessment", "assessment_training"]
    report: NativeRelationReport = Field(repr=False)
    judgment: NativeRelationJudgment = Field(repr=False)
    report_hash: Digest
    publication_enabled: Literal[False] = False
    blockers_discharged: Literal[False] = False
    @model_validator(mode="after")
    def exact_report(self) -> CommittedNativeRelationFindingV1:
        if (len(set(self.pair)) != 2 or self.parent_version_id not in self.pair
                or self.report.receipt_hash != self.report_hash or self.judgment not in self.report.judgments
                or self.judgment.conclusion == "nonredundant"
                or {r.version_id for r in self.judgment.references} != set(self.pair)):
            raise ValueError("actual negative judgment and exact pair required")
        return self

class CommittedNativeRelationDiagnosisV1(StorageContract):
    """Read-only historical outcome, NOT fresh relation eligibility. PRIVATE only."""
    schema_version: Literal["persistent_committed_relation_diagnosis_v1"] = "persistent_committed_relation_diagnosis_v1"
    phase_id: UUID
    relation_receipt_id: UUID = Field(repr=False)
    relation_receipt_hash: Digest = Field(repr=False)
    reports: tuple[NativeRelationReport, ...] = Field(min_length=4, max_length=4, repr=False)
    findings: tuple[CommittedNativeRelationFindingV1, ...] = Field(max_length=480, repr=False)
    publication_enabled: Literal[False] = False
    execution_authority_reusable: Literal[False] = False
    @model_validator(mode="after")
    def complete_reports(self) -> CommittedNativeRelationDiagnosisV1:
        if ({r.role for r in self.reports} != {"curriculum","technical","ambiguity","adversarial"}
                or len({r.actor_id for r in self.reports}) != 4 or len({r.run.run_id for r in self.reports}) != 4
                or any(f.report not in self.reports for f in self.findings)):
            raise ValueError("four independent original reports required")
        return self
    @property
    def outcome(self) -> Literal["quality_failed", "relation_ready"]:
        return "quality_failed" if any(j.conclusion != "nonredundant" for r in self.reports
            for j in r.judgments) else "relation_ready"

def resolve_committed_relation(producer: NativeRelationReviewProducer, *, task_owner: PersistentPackTaskOwner,
        task: PersistentPackTaskRef, record: PersistentPublicPhaseRecord) -> CommittedNativeRelationDiagnosisV1 | None:
    from app.services.learning.item_supply.native_relation_review import (
        NativeRelationReviewProducer, PRODUCTION_PROTOCOL, PRODUCTION_PROMPT_VERSION, PRODUCTION_WIRE_SCHEMA_NAME,
        ROLES, _ProductionOutput, _item_payload, production_config, relation_prompt,
    )
    from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
    if (type(producer) is not NativeRelationReviewProducer or type(task_owner) is not PersistentPackTaskOwner
            or producer.owner is not task_owner.type_owner or producer.conn is not task_owner.conn
            or producer.protocol != PRODUCTION_PROTOCOL or not producer.enabled):
        raise NativeTypeEvidencePending("persistent_committed_relation_original_owner_required")
    task,record = checked_model(task,PersistentPackTaskRef),checked_model(record,PersistentPublicPhaseRecord)
    if record.kind != "relation_pack" or record.public_task_id != task.public_task_id:
        raise NativeTypeEvidencePending("persistent_committed_relation_exact_task_phase_required")
    task_owner._task(task)
    producer.require_production_schema()
    conn = producer.conn
    phase_rows = conn.execute("SELECT payload_json,payload_hash FROM tutor_item_supply_shared_persistent_pack_journal "
        "WHERE public_task_id=%s AND phase_id=%s AND job_id=%s AND root_id=%s AND record_kind='phase' FOR SHARE",
        (record.public_task_id,record.phase_id,record.job_id,record.root_id)).fetchall()
    if (len(phase_rows) != 1 or phase_rows[0]["payload_json"] != record.model_dump(mode="json")
            or phase_rows[0]["payload_hash"] != canonical_hash(phase_rows[0]["payload_json"])):
        raise NativeTypeEvidencePending("persistent_committed_relation_original_phase_required")
    rows = conn.execute("SELECT b.*,p.payload_json AS preparation_json,p.payload_hash AS preparation_hash,"
        "p.checked_at AS prepared_at,p.valid_until AS execution_until,p.evidence_valid_until "
        "FROM tutor_item_supply_native_relation_batches b JOIN tutor_item_supply_native_relation_preparations p "
        "ON p.id=b.preparation_id AND p.user_id=b.user_id AND p.epoch=b.epoch AND p.mapping_receipt_id=b.mapping_receipt_id "
        "AND p.root_id=b.root_id AND p.job_id=b.job_id AND p.reservation_id=b.reservation_id "
        "WHERE b.user_id=%s AND b.epoch=%s AND b.mapping_receipt_id=%s AND b.job_id=%s AND b.root_id=%s "
        "AND p.payload_json->'persistent_phase'=%s::jsonb FOR SHARE OF b,p",
        (producer.owner.user_id,producer.owner.epoch,task.mapping_receipt_id,record.job_id,record.root_id,
         Jsonb(record.model_dump(mode="json")))).fetchall()
    if not rows:
        return None  # No result is NOT zero usage or paid repeat permission.
    if len(rows) != 1:
        raise NativeTypeEvidencePending("persistent_committed_relation_single_batch_required")
    row = rows[0]
    payload,audit = row["payload_json"],row["preparation_json"]
    if (set(payload) != {"pairs","contents","reports","safe_reason","profile_hash","production_config","production_envelope_hash"}
            or row["payload_hash"] != canonical_hash(payload) or row["preparation_hash"] != canonical_hash(audit)
            or payload["profile_hash"] != record.lease.profile.profile_hash or audit["lease"] != record.lease.model_dump(mode="json")
            or audit["pairs"] != payload["pairs"] or audit["contents"] != payload["contents"]
            or row["valid_until"] != row["evidence_valid_until"]
            or not row["prepared_at"] <= row["checked_at"] < row["execution_until"]):
        raise NativeTypeEvidencePending("persistent_committed_relation_immutable_binding_changed")
    settled = conn.execute("SELECT s.usage_state,s.receipt_hash,r.requests,r.lease_generation "
        "FROM tutor_item_supply_shared_runtime_settlements s JOIN tutor_item_supply_shared_reservations r ON r.id=s.reservation_id "
        "WHERE r.id=%s AND r.root_id=%s AND r.job_id=%s AND r.reservation_key=%s AND s.settlement_key=%s FOR SHARE OF s,r",
        (row["reservation_id"],record.root_id,record.job_id,"native.relation."+row["preparation_id"].hex,
         "native.relation."+row["preparation_id"].hex)).fetchone()
    if (settled is None or settled["usage_state"] != "unknown" or settled["receipt_hash"] is not None
            or settled["requests"] != 4 or settled["lease_generation"] != record.lease.generation):
        raise NativeTypeEvidencePending("persistent_committed_relation_original_unknown_settlement_required")
    mapping = producer.owner.resolve_mapping(task.mapping_receipt_id)
    if row["request_hash"] != mapping.pack_request.request_hash or audit["request_hash"] != row["request_hash"]:
        raise NativeTypeEvidencePending("persistent_committed_relation_current_mapping_changed")
    ids = tuple(UUID(c["version_id"]) for c in payload["contents"])
    if not 5 <= len(ids) <= 16 or len(set(ids)) != len(ids) or not set(record.candidate_version_ids).issubset(ids):
        raise NativeTypeEvidencePending("persistent_committed_relation_exact_members_required")
    contents = tuple(producer.owner.resolve_content(v,current=True) for v in ids)
    now = task_owner._guard()
    for content in contents:
        held = conn.execute("SELECT item_supply_internal.controlled_counterexample_held(job_id) AS held "
            "FROM tutor_item_supply_shared_generation_artifacts WHERE id=%s",(content.publication.generation_artifact_id,)).fetchone()
        if held is None or held["held"] is not False:
            raise NativeTypeEvidencePending("persistent_committed_relation_controlled_ancestry_denied")
        producer.owner._candidate(content,mapping,now)
    if [c.content.model_dump(mode="json") for c in contents] != payload["contents"]:
        raise NativeTypeEvidencePending("persistent_committed_relation_original_content_changed")
    by_id = {c.content.version_id:c for c in contents}
    profile = cast(TypeProfileV2,{"python-kc-binding-v1":"kc","python-state-update-v1":"python",
        "sqlite-predicate-order-v1":"sqlite"}[mapping.target_id])
    pairs: dict[str,tuple[UUID,UUID]] = {}
    for pair in payload["pairs"]:
        if set(pair) != {"left_version_id","right_version_id","binding_hash"}:
            raise NativeTypeEvidencePending("persistent_committed_relation_closed_pair_required")
        a,b = UUID(pair["left_version_id"]),UUID(pair["right_version_id"])
        if a == b or a not in by_id or b not in by_id:
            raise NativeTypeEvidencePending("persistent_committed_relation_pair_members_required")
        binding = relationship_binding_hash(profile=profile,request_hash=row["request_hash"],left=by_id[a].content,right=by_id[b].content)
        if binding != pair["binding_hash"] or binding in pairs:
            raise NativeTypeEvidencePending("persistent_committed_relation_pair_binding_changed")
        pairs[binding] = (a,b)
    if not 1 <= len(pairs) <= 120:
        raise NativeTypeEvidencePending("persistent_committed_relation_bounded_pairs_required")
    original: dict[str,Any] = dict(request_hash=row["request_hash"],objective=dict(target_id=mapping.target_id,
        target_definition_hash=mapping.target_definition_hash,clauses=[c.model_dump(mode="json") for c in get_finite_course_target(mapping.target_id).clauses],
        runtime_profile_hash=mapping.profile.runtime_profile_hash,scorer_version=mapping.profile.scorer_version),
        pairs=payload["pairs"],items=[_item_payload(c) for c in contents])
    config = production_config(producer.owner.settings)
    envelope = producer._production_envelope(original)
    if (audit["payload_hash"] != canonical_hash(original) or audit["production_config"] != config or payload["production_config"] != config
            or audit["production_envelope_hash"] != canonical_hash(envelope) or payload["production_envelope_hash"] != canonical_hash(envelope)):
        raise NativeTypeEvidencePending("persistent_committed_relation_original_prompt_config_changed")
    indexes = {UUID(i["version_id"]):i["field_hashes"] for i in original["items"]}
    reports = tuple(NativeRelationReport.model_validate_json(canonical_json(r)) for r in payload["reports"])
    if (len(reports) != 4 or {r.role for r in reports} != set(ROLES)
            or len({r.actor_id for r in reports}) != 4 or len({r.run.run_id for r in reports}) != 4):
        raise NativeTypeEvidencePending("persistent_committed_relation_complete_independent_four_required")
    parents = {v.published_version_id:v for v in task_owner._versions(task).values() if v.published_version_id is not None}
    findings = []
    for report in reports:
        identity = ProviderIdentityV2.model_validate_json(canonical_json(audit["identities"][report.role]))
        input_binding = dict(role=report.role,messages=relation_prompt(report.role,original,protocol=PRODUCTION_PROTOCOL),production_config=config,
            output_schema=_ProductionOutput.model_json_schema(),schema_name=PRODUCTION_WIRE_SCHEMA_NAME,
            timeout_seconds=report.run.timeout_seconds,max_input_bytes=producer.max_input_bytes)
        if (report.run.provider_identity != identity or producer.bindings.get((identity.provider,identity.model_version)) != identity.model
                or identity.provider != config["provider"] or identity.model != config["model"]
                or report.actor_id != uuid5(NAMESPACE_URL,"aearn:item-author:"+identity.identity)
                or report.actor_id in {c.content.author_id for c in contents} or report.run.prompt_version != PRODUCTION_PROMPT_VERSION
                or report.run.profile_hash != record.lease.profile.profile_hash or report.run.max_output_tokens != 61440
                or report.run.input_hash != canonical_hash(input_binding) or report.valid_until != row["valid_until"]
                or not row["prepared_at"] <= report.checked_at <= row["checked_at"] or report.checked_at >= row["execution_until"]
                or {j.binding_hash for j in report.judgments} != set(pairs) or len(report.judgments) != len(pairs)):
            raise NativeTypeEvidencePending("persistent_committed_relation_original_run_identity_required")
        for judgment in report.judgments:
            pair = pairs[judgment.binding_hash]
            if ({r.version_id for r in judgment.references} != set(pair)
                    or any(indexes[r.version_id].get(r.pointer) != r.value_hash for r in judgment.references)):
                raise NativeTypeEvidencePending("persistent_committed_relation_original_references_required")
            if judgment.conclusion == "nonredundant":
                continue
            affected = [parents[v] for v in pair if v in parents and parents[v].slot.startswith("assessment-")]
            if not affected:
                continue  # Never invent a replacement/private exposure target.
            parent = max(affected,key=lambda v:SLOTS.index(v.slot))
            if parent.slot not in ("assessment-1","assessment-2") or parent.published_version_id is None:
                raise NativeTypeEvidencePending("persistent_committed_relation_fixed_assessment_parent_required")
            findings.append(CommittedNativeRelationFindingV1(affected_slot=parent.slot,parent_revision_id=parent.revision_id,
                parent_version_id=parent.published_version_id,pair=pair,pair_kind="assessment_assessment"
                    if all(by_id[v].spec.allocation.slot=="assessment" for v in pair) else "assessment_training",
                report=report,judgment=judgment,report_hash=report.receipt_hash))
    # Old phase/producer/report deadlines are DATA, not renewed capabilities.
    task_owner._task(task)
    now = task_owner._guard()
    for content in contents:
        producer.owner._candidate(content,mapping,now)
    return CommittedNativeRelationDiagnosisV1(phase_id=record.phase_id,relation_receipt_id=row["id"],
        relation_receipt_hash=row["payload_hash"],reports=reports,findings=tuple(findings))

