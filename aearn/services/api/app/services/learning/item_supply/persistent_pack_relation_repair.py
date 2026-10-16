"""Additive PUBLIC model-relation repair implementation for ORIGINAL owners.

No new authority class, callbacks, JSON capabilities, job adoption, paid retry,
or PRIVATE receipt export. Core dispatch seams remain frozen during Main's
clone phase; these functions are connected only after that live slice finishes.
"""
from __future__ import annotations
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4
from psycopg.types.json import Jsonb
from app.services.learning.item_bank.contracts import canonical_hash, canonical_json
from app.services.learning.item_supply.diagnostic_policy import checked_bundle, parse_bundle, policy_for_hash
from app.services.learning.item_supply.finite_review_descriptor import finite_review_context
from app.services.learning.item_supply.generation_contracts import GenerationRequestV2
from app.services.learning.item_supply.native_relation_review import NativeRelationReviewProducer, PRODUCTION_PROTOCOL, ROLES
from app.services.learning.item_supply.native_review_investigation import NativeReviewInvestigationOwner, PreparedNativeReviewInvestigation
from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
from app.services.learning.item_supply.persistent_pack_candidate import PersistentCandidateExecutor
from app.services.learning.item_supply.persistent_pack_contracts import (
    BlockedPackPhase, IssuedPackPhase, PersistentPackPending, PersistentPackTaskRef,
    PersistentPublicPhaseRecord, PersistentPublicVersionRecord,
)
from app.services.learning.item_supply.persistent_pack_relation_repair_contracts import (
    PersistentPublicRelationFindingV1, PersistentRelationInvestigationInputV1, RELATION_PROTOCOL, public_parent_scalar_references,
)
from app.services.learning.item_supply.persistent_pack_relation_repair_sender import PersistentRelationInvestigationSender
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.review_contracts_v2 import LearningItemReviewRole, ProviderIdentityV2, ReviewInputV2
from app.services.learning.item_supply.review_deliberation import review_disputes
from app.services.learning.item_supply.repository import server_clock
from app.services.learning.item_supply.shared_continuation import SharedCandidateContinuationOwner
from app.services.learning.item_supply.shared_review import SharedReviewPipeline


def original_producer(owner: PersistentPackTaskOwner) -> NativeRelationReviewProducer:
    if type(owner) is not PersistentPackTaskOwner:
        raise PipelineRepositoryError("PERSISTENT_RELATION_CONCRETE_TASK_OWNER_REQUIRED")
    model = owner.settings.llm_model
    if model is None:
        raise PipelineRepositoryError("PERSISTENT_RELATION_CURRENT_CONFIGURED_MODEL_REQUIRED")
    identities = {role:ProviderIdentityV2(identity="deepseek.persistent.relation."+role,provider="deepseek",
        model=model,model_version=model) for role in ROLES}
    return NativeRelationReviewProducer(owner.type_owner,identities=identities,
        trusted_model_bindings={("deepseek",model):model},max_output_tokens=61440,enabled=True,protocol=PRODUCTION_PROTOCOL)


def finding_data(owner: PersistentPackTaskOwner, task: PersistentPackTaskRef, relation_phase_id: UUID,
                 *, parent: PersistentPublicVersionRecord | None=None) -> PersistentPublicRelationFindingV1:
    row = owner.conn.execute("SELECT payload_json FROM tutor_item_supply_shared_persistent_pack_journal "
        "WHERE public_task_id=%s AND phase_id=%s AND record_kind='phase'",(task.public_task_id,relation_phase_id)).fetchone()
    if row is None:
        raise PipelineRepositoryError("PERSISTENT_ORIGINAL_RELATION_PHASE_DATA_REQUIRED")
    record = PersistentPublicPhaseRecord.model_validate_json(canonical_json(row["payload_json"]))
    diagnosis = original_producer(owner).resolve_committed_persistent(task_owner=owner,task=task,record=record)
    if diagnosis is None:
        raise PipelineRepositoryError("PERSISTENT_RELATION_OUTCOME_UNKNOWN_NO_PAID_REPLAY")
    selected = tuple(f for f in diagnosis.findings if parent is None or
        (f.parent_revision_id==parent.revision_id and f.parent_version_id==parent.published_version_id))
    if not selected:
        raise PipelineRepositoryError("PERSISTENT_ACTUAL_CURRENT_PUBLIC_RELATION_FINDING_REQUIRED")
    actual = sorted(selected,key=lambda f:(f.affected_slot,f.report.role,f.judgment.binding_hash))[0]
    version = owner._versions(task)[actual.affected_slot]
    pair_sources = tuple(owner.type_owner.resolve_content(v,current=True).source for v in actual.pair)
    refs = public_parent_scalar_references(pair_sources[actual.pair.index(actual.parent_version_id)])
    values = dict(public_relation_phase_id=relation_phase_id,public_slot_id=version.public_slot_id,
        parent_revision_id=actual.parent_revision_id,parent_version_id=actual.parent_version_id,
        pair=actual.pair,pair_kind=actual.pair_kind,pair_sources=pair_sources,report=actual.report,judgment=actual.judgment,
        safe_code="assessment_relation_conflict" if actual.judgment.conclusion=="conflict" else "assessment_relation_uncertain",
        references=refs)
    # Hash defaults as serialized by the strict DATA contract; no verified flag.
    data = dict(schema_version="persistent_public_relation_finding_v1",role="relation",**values,
        historical_finding_resolved=False,publication_enabled=False)
    serialized = {**data,"public_relation_phase_id":str(relation_phase_id),"public_slot_id":str(version.public_slot_id),
        "parent_revision_id":str(actual.parent_revision_id),"parent_version_id":str(actual.parent_version_id),
        "pair":[str(v) for v in actual.pair],"pair_sources":[s.model_dump(mode="json") for s in pair_sources],"report":actual.report.model_dump(mode="json"),
        "judgment":actual.judgment.model_dump(mode="json"),"references":[r.model_dump(mode="json") for r in refs]}
    return PersistentPublicRelationFindingV1.model_validate_json(canonical_json(dict(serialized,dispute_key=canonical_hash(serialized))))


def require_current_relation(owner: NativeReviewInvestigationOwner, phase: IssuedPackPhase,
                             request: PersistentRelationInvestigationInputV1) -> None:
    if (type(owner) is not NativeReviewInvestigationOwner or type(phase) is not IssuedPackPhase
            or type(phase.owner) is not PersistentPackTaskOwner or owner.conn is not phase.owner.conn
            or phase.version is None or phase.version.published_version_id is None
            or type(request) is not PersistentRelationInvestigationInputV1
            or request.execution_profile_hash != phase.record.lease.profile.profile_hash):
        raise PipelineRepositoryError("PERSISTENT_RELATION_ORIGINAL_SAME_PROCESS_FRAME_REQUIRED")
    f = request.relation_finding
    if (f.public_slot_id != phase.version.public_slot_id or f.parent_revision_id != phase.version.revision_id
            or f.parent_version_id != phase.version.published_version_id or phase.version.root_id != phase.record.root_id):
        raise PipelineRepositoryError("PERSISTENT_RELATION_EXACT_SAME_ITEM_PARENT_REQUIRED")
    # Controlled wins before source/model permission. Historical report deadlines
    # remain DATA; each PUBLIC pair receives original current query/source checks.
    mapping = phase.owner.type_owner.resolve_mapping(phase.task.mapping_receipt_id)
    for index, version_id in enumerate(f.pair):
        row = owner.conn.execute("SELECT g.job_id FROM tutor_learning_item_native_publication_proofs p "
            "JOIN tutor_item_supply_shared_generation_artifacts g ON g.id=p.generation_artifact_id "
            "WHERE p.version_id=%s",(version_id,)).fetchone()
        held = None if row is None else owner.conn.execute("SELECT item_supply_internal.controlled_counterexample_held(%s) AS held",
                (row["job_id"],)).fetchone()
        if held is None or held["held"] is not False:
            raise PipelineRepositoryError("PERSISTENT_RELATION_CONTROLLED_ANCESTRY_DENIED_FIRST")
        actual = phase.owner.type_owner.resolve_content(version_id,current=True)
        if actual.source != f.pair_sources[index]:
            raise PipelineRepositoryError("PERSISTENT_RELATION_ORIGINAL_PAIR_SOURCE_CHANGED")
        phase.owner.type_owner._candidate(actual,mapping,phase.owner._guard())
    phase.owner.require_phase(phase,kind="candidate")
    # The SQL helper re-resolves the immutable original four-role batch using
    # PRIVATE header attachments internally. No private batch ID/hash is exported.
    owner.conn.execute("SELECT item_supply_internal.assert_persistent_public_relation_finding(%s::jsonb,%s::jsonb)",
        (Jsonb(phase.record.model_dump(mode="json")),Jsonb(f.model_dump(mode="json")))).fetchone()


def prepare_relation_investigation(owner: NativeReviewInvestigationOwner, *, phase: IssuedPackPhase,
        original: Any, result: Any, review_receipt_id: UUID) -> PreparedNativeReviewInvestigation | None:
    if type(owner) is not NativeReviewInvestigationOwner or owner.conn is not phase.owner.conn:
        raise PipelineRepositoryError("PERSISTENT_RELATION_ORIGINAL_INVESTIGATION_OWNER_REQUIRED")
    meta,row,blind_id,sources = owner._committed_original(original,result,phase.record.lease,review_receipt_id)
    if owner.review._committed_frames[original.reservation_id][2] is not phase or result.bundle is None:
        raise PipelineRepositoryError("PERSISTENT_RELATION_ORIGINAL_REISSUED_REVIEW_REQUIRED")
    relation_id = phase.prepared.get("public_relation_phase_id")
    if type(relation_id) is not UUID or phase.version is None:
        raise PipelineRepositoryError("PERSISTENT_RELATION_TYPED_PUBLIC_PHASE_SELECTION_REQUIRED")
    finding = finding_data(phase.owner,phase.task,relation_id,parent=phase.version)
    lease = phase.record.lease
    now = server_clock(owner.conn,datetime.now(UTC))
    deadline = min(phase.record.valid_until,lease.expires_at,lease.parent_deadline,*(t for _,_,t in sources))
    timeout = min(100.0,lease.profile.values.request_timeout_ms/1000,(deadline-now).total_seconds())
    if timeout <= 0:
        raise PipelineRepositoryError("PERSISTENT_RELATION_NORMAL_PHASE_EXPIRED")
    with finite_review_context(original.source,spec=original.spec,materials=original.request.materials):
        request = PersistentRelationInvestigationInputV1(review_receipt_id=review_receipt_id,review_receipt_hash=row["receipt_hash"],
            bundle=checked_bundle(result.bundle),review_input=ReviewInputV2(binding=original.binding,
            role=LearningItemReviewRole.TECHNICAL,source=original.source,validation_receipt=original.validation),
            execution_profile_hash=lease.profile.profile_hash,disputes=(*review_disputes(result.bundle),finding),
            revision_allocation=owner._select_registered_child_allocation(phase,original.spec))
        require_current_relation(owner,phase,request)
        key = meta["key"]
        model = owner.review.settings.llm_model
        if model is None:
            raise PipelineRepositoryError("PERSISTENT_RELATION_ACTUAL_CURRENT_MODEL_REQUIRED")
        identity = ProviderIdentityV2(identity="deepseek.native.shared.investigator",provider=key.provider,
            model=model,model_version=key.model_version)
        if (owner.review._models.get((key.provider,key.model_version)) != model
                or identity.identity in {original.author_identity,*(i.identity for i in original.provider_identities)}):
            raise PipelineRepositoryError("PERSISTENT_RELATION_INDEPENDENT_INVESTIGATOR_REQUIRED")
        adapter = PersistentRelationInvestigationSender(owner.review.settings,profile=lease.profile,identity=identity,timeout_seconds=timeout)
        resources = adapter.resource_plan(request)
        reservation = owner.budget.reserve(lease=lease,reservation_key="investigate."+original.artifact_id.hex+"."+review_receipt_id.hex,
            amounts=resources,now=now)
        if not reservation.allowed or reservation.reservation_id is None or reservation.reason=="REPLAY":
            return None
        assert original.persistent_committed_frame is not None
        p = PreparedNativeReviewInvestigation(uuid4(),UUID(str(meta["root_id"])),lease,original,result,blind_id,
            review_receipt_id,original.persistent_committed_frame["continuation_binding_hash"],reservation.reservation_id,
            request,identity,resources,sources,deadline,timeout,persistent_phase=phase)
        payload = p.payload()
        owner.conn.execute("SELECT item_supply_internal.assert_persistent_normal_repair(%s::jsonb)",(Jsonb(payload),)).fetchone()
    owner.conn.execute("INSERT INTO tutor_item_supply_shared_review_investigation_preparations "
        "(id,root_id,job_id,lease_owner,lease_generation,lease_state_version,generation_artifact_id,review_receipt_id,reservation_id,payload_json,valid_until) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",(p.preparation_id,p.root_id,lease.job_id,lease.lease_owner,
        lease.generation,lease.state_version,original.artifact_id,review_receipt_id,p.reservation_id,Jsonb(payload),deadline))
    owner._prepared[p.preparation_id]=(p,canonical_hash(payload),adapter,owner.review.settings.model_copy(deep=True))
    owner._sender_seals[p.preparation_id]=(RELATION_PROTOCOL,adapter.envelope_hash(request))
    return p


class PersistentRelationCandidateExecutor(PersistentCandidateExecutor):
    """Same full 508/509/new validation+blind/six/510/522/facts/publisher chain.

    Inherited normal_loop is connected to the original investigator's explicit
    new branch AFTER Main's frozen clone phase, never monkeypatched at runtime.
    """
    def prepare_relation_repair(self, task: PersistentPackTaskRef, *, relation_phase_id: UUID) -> IssuedPackPhase | BlockedPackPhase:
        # Until the reviewed explicit original-owner API is connected, no jobs,
        # batches, reservations or paid paths may be prepared by this new slice.
        if "prepare_persistent_relation" not in NativeReviewInvestigationOwner.__dict__:
            return BlockedPackPhase("persistent_public_relation_original_seam_unwired",task.pack_task_id)
        finding = finding_data(self.owner,task,relation_phase_id)
        version = next(v for v in self.owner._versions(task).values() if v.public_slot_id==finding.public_slot_id)
        if version.artifact_id is None:
            raise PersistentPackPending("persistent_relation_actual_parent_artifact_required")
        # Structural gate BEFORE any job/batch; the complete installed 532 hash
        # preflight is connected with the original owner seams, not an opt-in bool.
        guard = self.conn.execute("SELECT to_regprocedure('item_supply_internal.assert_persistent_public_relation_finding(jsonb,jsonb)') AS guard").fetchone()
        if guard is None or guard["guard"] is None:
            return BlockedPackPhase("persistent_public_relation_532_receiver_required",task.pack_task_id)
        continuation = SharedCandidateContinuationOwner(self.conn,self.settings,enabled=True)
        original = continuation._original(version.artifact_id,self.authority)
        request = GenerationRequestV2.model_validate_json(canonical_json(original["request_json"]))
        row = self.conn.execute("SELECT id,payload_json FROM tutor_item_supply_shared_pipeline_receipts "
            "WHERE generation_artifact_id=%s AND artifact_kind='review_bundle' ORDER BY created_at DESC,id LIMIT 1",(version.artifact_id,)).fetchone()
        if row is None:
            raise PersistentPackPending("persistent_relation_original_complete_parent_review_required")
        parse_bundle(row["payload_json"])
        phase = self.pipeline._phase(task,spec=version.specification,root=version.root_id,materials=request.materials,
            operation="persistent.candidate."+version.revision_id.hex+".relation."+relation_phase_id.hex,
            kind="candidate",version=version)
        if isinstance(phase,BlockedPackPhase):
            return phase
        phase.prepared["public_relation_phase_id"] = relation_phase_id
        adopted = continuation.adopt_persistent_phase(phase=phase,artifact_id=version.artifact_id,
            spec=version.specification,source_authority=self.authority)
        model = self.pipeline.provider.configured_model
        rp = SharedReviewPipeline(self.conn,self.settings,enabled=True,continuation_owner=continuation,
            trusted_model_bindings={(self.pipeline.provider.provider_key,model):model})
        from app.services.learning.item_bank.contracts import LearningItemSourceV1
        source = LearningItemSourceV1.model_validate_json(canonical_json(original["source_json"]))
        with finite_review_context(source,spec=version.specification,materials=request.materials):
            review,reviewed = rp.reissue_committed_phase(phase=phase,review_receipt_id=row["id"],source_authority=self.authority)
        phase.prepared.update(candidate_executor=self,generation_owner=self._generation(),continuation_owner=continuation,
            continuation=adopted,policy=policy_for_hash(review.binding.policy_hash),resume_stage="committed_review_repair",
            review_owner=rp,review=review,reviewed=reviewed,review_id=row["id"])
        return cast(IssuedPackPhase,phase)
