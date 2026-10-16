"""Concrete persistent PUBLIC executor; only original generation/review/publication.

No callback authority, synthetic DTO verdict, dummy relation author or source IO.
The owner journals every network operation before dispatch, and never rerolls.
"""
from __future__ import annotations

from datetime import timedelta
import hashlib
import json
from typing import Any
from uuid import UUID, uuid4


from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.persistent_pack_contracts import (
    BlockedPackPhase, IssuedPackPhase, PersistentPackPending, PersistentPackTaskRef,
    PersistentPhaseOutcome, PersistentPublicPhaseRecord, PersistentPublicVersionRecord,
)
from app.services.learning.item_supply.provider_adapter import OpenAICompatibleGenerationProvider, GENERATION_PROMPT_VERSION
from app.services.learning.item_supply.parameter_profiles import ExecutionParameterProfileV1, ParameterValuesV1, ProfileKeyV1
from app.services.learning.item_supply.development_model_accounting import DevelopmentModelAccountingOwner
from app.services.learning.item_supply.native_relation_review import NativeRelationReviewProducer, PRODUCTION_PROTOCOL, ROLES
from app.services.learning.item_supply.review_contracts_v2 import ProviderIdentityV2
from app.services.learning.item_supply.policies import RetryPolicyV1
from app.services.learning.item_supply.persistent_pack_current_source import IssuedCurrentPackSourceBinding


class PersistentPublicPipeline:
    def __init__(self, owner: Any) -> None:
        from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
        if type(owner) is not PersistentPackTaskOwner:
            raise PersistentPackPending("persistent_original_task_owner_required")
        self.owner, self.conn, self.settings = owner, owner.conn, owner.settings
        self.authority = owner.type_owner.source_authority
        self.provider = OpenAICompatibleGenerationProvider(self.settings,max_http_attempts=1)
        if (self.provider.provider_key,self.provider.configured_model)!=("deepseek","deepseek-flash"):
            raise PersistentPackPending("persistent_configured_formal_provider_required")

    def _profile(self, spec: Any, materials: Any, original_key: ProfileKeyV1 | None=None) -> ExecutionParameterProfileV1:
        key=original_key or ProfileKeyV1(provider=self.provider.provider_key,model_version=self.provider.configured_model,
            agent_role="native.shared.v3.author."+spec.target_id,item_kind=spec.public_template.kind.value,
            risk_tier="low",difficulty="basic",input_size_bucket="bounded-131072",
            runtime=spec.blueprint.runtime_profile_id or "static-exact-v1",provider_version="openai-compatible-v1",
            prompt_version=GENERATION_PROMPT_VERSION,validator_version="finite-native-v1",
            output_size_bucket="bounded-65536",load_bucket="single",complexity_version=spec.target_id)
        if (key.provider,key.model_version)!=(self.provider.provider_key,self.provider.configured_model):
            raise PersistentPackPending("persistent_current_original_profile_provider_required")
        row=self.conn.execute("SELECT max(profile_version) AS v FROM tutor_item_supply_parameter_profiles WHERE profile_key_hash=%s",(key.key_hash,)).fetchone()
        values=ParameterValuesV1(connection_timeout_ms=20000,first_token_timeout_ms=100000,
            stream_idle_timeout_ms=100000,request_timeout_ms=100000,parent_deadline_ms=6000000,
            stage_deadline_ms=6000000,discussion_rounds=2,investigation_rounds=1,revision_rounds=1)
        return ExecutionParameterProfileV1(profile_key=key,version=int((row["v"] if row is not None else 0) or 0)+1,state="frozen",
            initial=values,current=values,last_stable=values,floor=values,ceiling=values,
            measurement_window_started_at=self.owner._guard(),change_reason="persistent_new_bounded_phase_v1",
            trusted_initial_evidence=(materials[0].exact_claims[0].claim_receipt_id,spec.target_definition_hash))

    def _phase(self, task: PersistentPackTaskRef, *, spec: Any, root: UUID, materials: Any,
               operation: str, kind: str, version: PersistentPublicVersionRecord | None,
               selected: tuple[UUID,...]=(), anchor: UUID | None=None,
               current_source_binding: IssuedCurrentPackSourceBinding | None=None) -> IssuedPackPhase | BlockedPackPhase:
        if current_source_binding is not None:
            if type(current_source_binding) is not IssuedCurrentPackSourceBinding or kind != "relation_pack" or version is not None:
                raise PersistentPackPending("persistent_relation_current_source_original_cap_required")
            current_source_binding.require_relation(owner=self.owner.type_owner, task=task, candidate_version_ids=selected)
            if materials != current_source_binding.public_materials:
                raise PersistentPackPending("persistent_relation_current_source_materials_changed")
        # Physical phase identity is distinct from the stable logical stage key.
        # Expired unstarted frames may end; a started opaque stage may NOT replay.
        previous=self.conn.execute("SELECT p.phase_id,r.payload_json AS result FROM tutor_item_supply_shared_persistent_pack_journal p "
            "LEFT JOIN tutor_item_supply_shared_persistent_pack_journal r ON r.phase_id=p.phase_id AND r.record_kind='phase_result' "
            "WHERE p.public_task_id=%s AND p.record_kind='phase' AND (p.operation_key=%s OR p.operation_key LIKE %s) "
            "ORDER BY p.created_at,p.id",(task.public_task_id,operation,operation+".frame.%")).fetchall()
        for old in previous:
            if old["result"] is None:
                return BlockedPackPhase("original_phase_still_unsettled",task.pack_task_id)
            if old["result"]["status"]=="outcome_unknown":
                from app.services.learning.item_supply.persistent_pack_explicit_recovery import consume_explicit_exception
                if consume_explicit_exception(self.owner,task,operation=operation,root=root,kind=kind,
                        version=version,previous=previous,old=old):
                    continue
                from app.services.learning.item_supply.persistent_pack_prestart_recovery import consume_registered_exception
                if consume_registered_exception(self.owner,task,operation=operation,root=root,kind=kind,
                        version=version,previous=previous,old=old):
                    continue
                return BlockedPackPhase("opaque_phase_outcome_unknown_no_paid_replay",task.pack_task_id)
            if kind=="relation_pack" and old["result"]["status"]=="quality_failed":
                return BlockedPackPhase("committed_relationship_requires_same_slot_revision",task.pack_task_id)
        operation=operation+".frame."+str(len(previous)+1)
        phase_id=uuid4()
        now=self.owner._guard()
        # Caller TOP owns batch BEFORE enqueue. No old window is changed.
        accounting=DevelopmentModelAccountingOwner(self.conn,enabled=True)
        batch=accounting.prepare_batch(root_id=root,provider_key=self.provider.provider_key,
            model=self.provider.configured_model,now=now,valid_until=now+timedelta(seconds=7200))
        original_key=None
        if kind=="candidate" and version is not None and version.artifact_id is not None:
            row=self.conn.execute("SELECT p.profile_json->'profile_key' AS key FROM tutor_item_supply_shared_generation_artifacts a "
                "JOIN tutor_item_supply_parameter_profiles p ON p.profile_hash=a.request_json->'profile'->>'profile_hash' "
                "WHERE a.id=%s AND a.root_id=%s",(version.artifact_id,root)).fetchone()
            if row is None:
                raise PersistentPackPending("persistent_committed_original_profile_key_required")
            original_key=ProfileKeyV1.model_validate_json(json.dumps(row["key"]))
        profile=self._profile(spec,materials,original_key)
        retry=RetryPolicyV1(max_transient_attempts=1,initial_backoff_ms=1,maximum_backoff_ms=1)
        job=self.owner.runtime.enqueue(root_id=root,stage_key="persistent.phase."+phase_id.hex,profile=profile,
            now=self.owner._guard(),priority=80,aging_seconds=86400,visibility="public",retry_policy=retry)
        lease=self.owner.runtime.claim(root_id=root,lease_owner="persistent.phase."+phase_id.hex,
            now=self.owner._guard(),lease_seconds=3600,visibility="public")
        if lease is None or lease.job_id!=job:
            raise PersistentPackPending("persistent_exact_phase_claim_rollback_required")
        accounting.bind_job(lease=lease,batch_id=UUID(str(batch["batch_id"])),now=self.owner._guard())
        for material in materials:
            self.authority.authorize(material)
        deadline=min(lease.expires_at,lease.parent_deadline,
            lease.profile.bound_at+timedelta(milliseconds=lease.profile.values.stage_deadline_ms))
        required=4 if kind=="relation_pack" else 17
        if (deadline-self.owner._guard()).total_seconds()<=required*100+15:
            raise PersistentPackPending("persistent_phase_remaining_insufficient")
        values: dict[str,Any]=dict(public_task_id=task.public_task_id,public_slot_id=None if version is None else version.public_slot_id,
            phase_id=phase_id,revision_id=None if version is None else version.revision_id,kind=kind,
            operation_key=operation,job_id=job,root_id=root,batch_id=UUID(str(batch["batch_id"])),lease=lease,
            valid_until=deadline,anchor_version_id=anchor,candidate_version_ids=selected)
        provisional=PersistentPublicPhaseRecord(frame_hash="0"*64, **values)
        record=provisional.model_copy(update={"frame_hash":canonical_hash(provisional.model_dump(mode="json",exclude={"frame_hash"}))})
        self.owner._public_event(task.public_task_id,"phase",record.model_dump(mode="json"),key=operation,
            root_id=root,job_id=job,phase_id=phase_id)
        context: dict[str,Any]={"provider":self.provider,"materials":materials}
        if current_source_binding is not None:
            context.update(current_source_binding=current_source_binding,
                current_source_binding_hash=current_source_binding.relation_binding_hash())
        phase=IssuedPackPhase(record,task,version,self.owner,context)
        self.owner._issued[phase_id]=(phase,canonical_hash(record.model_dump(mode="json")))
        self.owner._private_event(task,"phase",dict(schema_version="persistent_private_phase_attachment_v1",
            phase_id=str(phase_id),public_task_id=str(task.public_task_id)),key="phase."+phase_id.hex)
        return phase

    def prepare_relation(self, task: PersistentPackTaskRef, selected: tuple[UUID,...]) -> IssuedPackPhase | BlockedPackPhase:
        row = self.conn.execute("SELECT prosrc FROM pg_proc WHERE oid=to_regprocedure('public.enforce_native_type_evidence_insert()')").fetchone()
        if row is None or hashlib.sha256(row["prosrc"].replace("\r\n", "\n").encode()).hexdigest() != "70194b777ae1860df750c87e62b278360601842d98c6c9a4011defeba02dbb51":
            return BlockedPackPhase("persistent_relation_523_receiver_required", task.pack_task_id)
        if len(selected)!=5 or len(set(selected))!=5:
            raise PersistentPackPending("persistent_exact_five_original_versions_required")
        contents=tuple(self.owner.type_owner.resolve_content(v,current=True) for v in selected)
        mapping=self.owner.type_owner.resolve_mapping(task.mapping_receipt_id)
        for content in contents:
            self.owner.type_owner._candidate(content,mapping,self.owner._guard())
        # Original deterministic veto is evaluated BEFORE a relation phase is issued.
        # A real collision routes to the SAME fixed item normal revision; never replacement inventory.
        observation=self.owner.exposure_owner.snapshot_v2()
        if observation.exposure is None or observation.snapshot_id is None:
            raise PersistentPackPending("persistent_complete_exposure_required")
        from app.services.learning.item_supply.type_evidence import assessment_clone
        assessments=[c.content for c in contents if c.spec.allocation.slot=="assessment"]
        training=[c.content for c in contents if c.spec.allocation.slot!="assessment"]
        comparisons=[(assessments[0],assessments[1])]
        comparisons += [(a,t) for a in assessments for t in training]
        comparisons += [(a,e.content) for a in assessments for e in observation.exposure.records]
        collision=next(((a,b) for a,b in comparisons if assessment_clone(a,b)),None)
        if collision is not None:
            from app.services.learning.item_supply.persistent_pack_candidate import PersistentCandidateExecutor
            from app.services.learning.item_supply.persistent_pack_contracts import SLOTS
            versions=self.owner._versions(task)
            pair=(collision[0].version_id,collision[1].version_id)
            affected=[v for v in versions.values() if v.published_version_id in pair
                and v.specification.allocation.slot=="assessment"]
            if (len(set(pair))!=2 or any(i not in selected for i in pair) or not affected):
                return BlockedPackPhase("persistent_private_exposure_repair_attachment_required",task.pack_task_id)
            parent=max(affected,key=lambda v:SLOTS.index(v.slot))
            review=self.conn.execute("SELECT id FROM tutor_item_supply_shared_pipeline_receipts WHERE "
                "generation_artifact_id=%s AND artifact_kind='review_bundle' ORDER BY created_at DESC,id LIMIT 1",
                (parent.artifact_id,)).fetchone()
            if review is None:
                raise PersistentPackPending("persistent_exact_committed_parent_review_required")
            return PersistentCandidateExecutor(self).prepare_committed_review(task,parent,review["id"],clone_pair=pair)
        anchor=next(c for c in contents if c.spec.allocation.slot=="assessment")
        op="persistent.relation."+canonical_hash(dict(task=str(task.public_task_id),versions=sorted(map(str,selected))))
        current_source = getattr(self.owner.type_owner, "current_source_binding", None)
        if current_source is not None and type(current_source) is not IssuedCurrentPackSourceBinding:
            raise PersistentPackPending("persistent_relation_current_source_original_cap_required")
        materials = anchor.publication.materials if current_source is None else current_source.public_materials
        phase=self._phase(task,spec=anchor.spec,root=anchor.facts.root_id,materials=materials,
            operation=op,kind="relation_pack",version=None,selected=selected,anchor=anchor.content.version_id,
            current_source_binding=current_source)
        if isinstance(phase, BlockedPackPhase):
            return phase
        identity={role:ProviderIdentityV2(identity="deepseek.persistent.relation."+role,provider="deepseek",
            model=self.provider.configured_model,model_version=self.provider.configured_model) for role in ROLES}
        producer=NativeRelationReviewProducer(self.owner.type_owner,identities=identity,
            trusted_model_bindings={("deepseek",self.provider.configured_model):self.provider.configured_model},
            enabled=True,protocol=PRODUCTION_PROTOCOL,max_output_tokens=61440)
        producer.preflight_clients(phase.record.lease.profile)
        if any(assessment_clone(a,b) for a,b in comparisons):
            raise PersistentPackPending("persistent_assessment_clone_or_exposed")
        def ordered_pair(a: UUID,b: UUID) -> tuple[UUID,UUID]:
            return (a,b) if str(a)<=str(b) else (b,a)
        pairs=tuple(sorted({ordered_pair(a.version_id,b.version_id) for a,b in comparisons},key=str))
        prepared=producer.prepare_committed_phase(phase=phase,mapping_receipt_id=task.mapping_receipt_id,pairs=pairs)
        phase.prepared.update(relation_owner=producer,relation=prepared)
        return phase

    def prepare_candidate(self, task: PersistentPackTaskRef, version: PersistentPublicVersionRecord | None) -> IssuedPackPhase | BlockedPackPhase:
        from app.services.learning.item_supply.persistent_pack_candidate import PersistentCandidateExecutor
        executor=PersistentCandidateExecutor(self)
        if version is not None:
            return executor.continue_candidate(task,version)
        return executor.initial(task)

    def run(self, phase: IssuedPackPhase) -> PersistentPhaseOutcome:
        if phase.record.kind=="relation_pack":
            producer=phase.prepared["relation_owner"]
            prepared=phase.prepared["relation"]
            if type(producer) is not NativeRelationReviewProducer or producer.conn is not self.conn:
                raise PersistentPackPending("persistent_original_relation_issuer_required")
            run=producer.run(prepared)
            with self.conn.transaction():
                producer.settle(prepared,run)
            with self.conn.transaction():
                receipt=producer.persist(prepared,run)
            bad=any(j.conclusion!="nonredundant" for report in run.reports for j in report.judgments)
            return PersistentPhaseOutcome(phase_id=phase.record.phase_id,
                status="quality_failed" if bad else "relation_ready",safe_reason="relation_conflict_requires_same_slot_repair" if bad else "original_four_role_relation_completed",
                relation_receipt_id=receipt)
        from app.services.learning.item_supply.persistent_pack_candidate import PersistentCandidateExecutor
        executor=phase.prepared.get("candidate_executor")
        if type(executor) is not PersistentCandidateExecutor or executor.owner is not self.owner or executor.conn is not self.conn:
            raise PersistentPackPending("persistent_original_candidate_executor_required")
        return executor.run(phase)
