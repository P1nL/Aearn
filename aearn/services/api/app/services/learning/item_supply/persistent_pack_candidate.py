"""Concrete finite PUBLIC candidate stages; no journal verdict grants admission.

One phase has a finite 1-author/7-peer/1-investigator/1-child/7-child-peer
ceiling. Further business work uses committed DATA and a new original frame,
never a new seed, replacement slot, restored capability or paid UNKNOWN replay.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import json
from typing import Any
from uuid import UUID, uuid5, NAMESPACE_URL

from app.services.learning.item_bank.contracts import (
    LearningItemDifficultyProfileV1, LearningItemPublicationPolicyV1, canonical_hash,
)
from app.services.learning.item_bank.review_contracts import REQUIRED_REVIEW_ROLES
from app.services.learning.item_supply.blind_protocol import SINGLE_CHOICE_BLIND_PROTOCOL, LEGACY_BLIND_PROTOCOL
from app.services.learning.item_supply.diagnostic_policy import policy_for_hash, completed_blind_allowed
from app.services.learning.item_supply.finite_candidate_factory import (
    FLEXIBLE_FACTORY_VERSION, build_finite_candidate_spec, build_finite_generation_request,
)
from app.services.learning.item_supply.finite_task_families import initial_slot_allocations
from app.services.learning.item_supply.finite_targets.python_kc import PYTHON_KC_SCORER_VERSION
from app.services.learning.item_supply.generation_contracts import GenerationLimitsV2
from app.services.learning.item_supply.persistent_pack_contracts import (
    BlockedPackPhase, IssuedPackPhase, PersistentPackPending, PersistentPackTaskRef,
    PersistentPhaseOutcome, PersistentPublicVersionRecord,
)
from app.services.learning.item_supply.policies import CoverageObligationV1, derive_runtime_contract_hash
from app.services.learning.item_supply.review_contracts_v2 import ProviderIdentityV2
from app.services.learning.item_supply.review_provider import BoundedOpenAIReviewClient, JsonBlindSolverV2, JsonReviewerV2
from app.services.learning.item_supply.shared_pipeline import SharedGenerationPipeline
from app.services.learning.item_supply.shared_validation import SharedValidationPipeline
from app.services.learning.item_supply.shared_review import SharedReviewPipeline
from app.services.learning.item_supply.storage import PostgresSharedSupplyStorage
from app.services.learning.item_supply.storage_contracts import AutonomousEvidencePolicyV2

FORMAL = 61440


class PersistentCandidateExecutor:
    def __init__(self, pipeline: Any) -> None:
        from app.services.learning.item_supply.persistent_pack_pipeline import PersistentPublicPipeline
        if type(pipeline) is not PersistentPublicPipeline:
            raise PersistentPackPending("persistent_concrete_pipeline_required")
        self.pipeline, self.owner, self.conn = pipeline, pipeline.owner, pipeline.conn
        self.settings, self.authority = pipeline.settings, pipeline.authority

    def initial(self, task: PersistentPackTaskRef) -> IssuedPackPhase | BlockedPackPhase:
        record = self.owner._task(task)
        existing = self.owner._versions(task)
        slot = next(s for s in record.slots if s.slot not in existing)
        logical_revision=uuid5(NAMESPACE_URL,"persistent.initial."+slot.public_slot_id.hex)
        if self.conn.execute("SELECT id FROM tutor_item_supply_shared_persistent_pack_journal WHERE operation_key=%s "
            "AND record_kind='stage_started'",("persistent.stage."+logical_revision.hex+".author",)).fetchone():
            return BlockedPackPhase("original_author_started_without_adoptable_data_no_repeat",task.pack_task_id)
        materials = self.owner.public_materials
        if not materials:
            return BlockedPackPhase("original_current_public_materials_required", task.pack_task_id)
        mapping = self.owner.type_owner.resolve_mapping(task.mapping_receipt_id)
        target = mapping.target_id
        # Pure slot declaration from original registered factory, not green reroll.
        allocation = next(a for a in initial_slot_allocations(target)
            if a.variant_id == target+":"+slot.slot)
        binding = self.owner.type_owner.query._bindings.get(target)
        if binding is None or (target != "python-kc-binding-v1" and self.owner.runner is None):
            return BlockedPackPhase("original_approved_runtime_and_runner_required",task.pack_task_id)
        original_policy = AutonomousEvidencePolicyV2()
        spec = build_finite_candidate_spec(target_id=target,variant_id=allocation.variant_id,
            seed=record.slots.index(slot),item_key="persistent.public."+slot.public_slot_id.hex,version="v1",
            materials=materials,runtime_profile_hash=None if binding.runtime_lock is None else binding.runtime_profile_hash,
            scorer_version=PYTHON_KC_SCORER_VERSION if target=="python-kc-binding-v1" else binding.scorer_version,
            assistance_policy_hash=canonical_hash({"visibility":"public","purpose":"exercise",
                "no_learner_attempt":True,"evidence_policy":original_policy.policy_hash}),
            policy_version=original_policy.policy_version,
            difficulty_profile=LearningItemDifficultyProfileV1.model_validate_json(json.dumps(dict(base="D1",
                reasoning_depth=1,concept_count=2,context_novelty=1,transfer_distance=1,response_complexity=1,scaffolding=5))),
            publication_policy=LearningItemPublicationPolicyV1.model_validate_json(json.dumps(dict(risk_tier="low",
                required_review_roles=[r.value for r in REQUIRED_REVIEW_ROLES],agent_review_required=True,
                pilot_required=True,human_approval_required=False))),
            public_spec_version=FLEXIBLE_FACTORY_VERSION,allocation=allocation)
        for material in materials:
            self.authority.authorize(material)
        coverage = spec.coverage_blueprint
        obligation = CoverageObligationV1(blueprint_hash=coverage.blueprint_hash,scope_hash=coverage.scope.scope_hash,
            objective_hash=coverage.objective_hash,purpose=coverage.scope.purpose.value,
            runtime_contract_hash=derive_runtime_contract_hash(coverage.scope),visibility="public",policy_version=coverage.policy_version)
        storage = PostgresSharedSupplyStorage(self.conn)
        storage.register_policy(original_policy)
        root = self.owner.runtime.ensure_shared_root(blueprint_id=storage.register_blueprint(coverage),
            obligation=obligation,pool="base",provider_key=self.pipeline.provider.provider_key)
        version = PersistentPublicVersionRecord(public_task_id=task.public_task_id,public_slot_id=slot.public_slot_id,
            slot=slot.slot,revision_id=uuid5(NAMESPACE_URL,"persistent.initial."+slot.public_slot_id.hex),revision_seq=1,
            parent_revision_id=None,candidate_id=uuid5(NAMESPACE_URL,"persistent.candidate."+slot.public_slot_id.hex),
            specification=spec,root_id=root)
        operation = "persistent.candidate."+version.revision_id.hex+".author"
        phase = self.pipeline._phase(task,spec=spec,root=root,materials=materials,
            operation=operation,kind="candidate",version=version)
        if isinstance(phase,BlockedPackPhase):
            return phase
        # No content version exists before the sole first actual author dispatch.
        # UNSTARTED expiry cannot reuse an old frozen generation-policy frame.
        version=version.model_copy(update={"candidate_id":uuid5(NAMESPACE_URL,"persistent.author."+phase.record.phase_id.hex)})
        phase=replace(phase,version=version)
        self.owner._issued[phase.record.phase_id]=(phase,canonical_hash(phase.record.model_dump(mode="json")))
        gp = self._generation()
        request = build_finite_generation_request(spec,candidate_id=version.candidate_id,profile=phase.record.lease.profile,
            limits=GenerationLimitsV2(max_input_bytes=131072,max_output_tokens=FORMAL,max_output_bytes=131072),materials=materials)
        policy = self._policy()
        prepared = gp.prepare_generation(lease=phase.record.lease,request=request,provider=self.pipeline.provider,
            source_authority=self.authority,evidence_policy=policy)
        if prepared is None:
            raise PersistentPackPending("persistent_original_author_prepare_denied")
        phase.prepared.update(candidate_executor=self,generation_owner=gp,generation=prepared,policy=policy)
        # Network allowance remains the original GP's process-issued reservation.
        return phase

    def continue_candidate(self, task: PersistentPackTaskRef, version: PersistentPublicVersionRecord) -> IssuedPackPhase | BlockedPackPhase:
        from app.services.learning.item_supply.shared_continuation import SharedCandidateContinuationOwner
        if version.artifact_id is None:
            return BlockedPackPhase("committed_author_data_required_no_repeat",task.pack_task_id)
        held=self.conn.execute("SELECT item_supply_internal.controlled_counterexample_held(job_id) AS held "
            "FROM tutor_item_supply_shared_generation_artifacts WHERE id=%s",(version.artifact_id,)).fetchone()
        if held is None or held["held"] is not False:
            return BlockedPackPhase("controlled_ancestry_unconditional_hold",task.pack_task_id)
        stages=self.conn.execute("SELECT phase_id,operation_key,record_kind,payload_json FROM tutor_item_supply_shared_persistent_pack_journal "
            "WHERE operation_key LIKE %s AND record_kind IN('stage_started','stage_result')",
            ("persistent.stage."+version.revision_id.hex+".%",)).fetchall()
        # Exact operation identities: a new attempt result NEVER settles old UNKNOWN.
        started={r["operation_key"] for r in stages if r["record_kind"]=="stage_started"}
        done={r["operation_key"]:r["payload_json"] for r in stages if r["record_kind"]=="stage_result"}
        if started-set(done):
            from app.services.learning.item_supply.persistent_pack_explicit_recovery import allow_existing_stage, ATTEMPT_KEY
            if not allow_existing_stage(self.owner,task,version,stages):
                reason=("explicit_attempt_committed_result_requires_original_reconciliation" if ATTEMPT_KEY in done
                    else "started_stage_outcome_unknown_no_paid_replay")
                return BlockedPackPhase(reason,task.pack_task_id)
        if any(d["outcome"]!="completed" for d in done.values()):
            return BlockedPackPhase("immutable_failed_stage_requires_substantive_finding_owner",task.pack_task_id)
        original_review=self.conn.execute("SELECT id FROM tutor_item_supply_shared_pipeline_receipts "
            "WHERE generation_artifact_id=%s AND artifact_kind='review_bundle' ORDER BY created_at DESC,id LIMIT 1",
            (version.artifact_id,)).fetchone()
        if original_review is not None:
            # Issuing a NEW context from committed blind/six-peer DATA belongs to
            # the original review/investigation owners, never this dispatcher.
            return self.prepare_committed_review(task,version,original_review["id"])
        if version.published_version_id is not None:
            return BlockedPackPhase("committed_relationship_repair_owner_required",task.pack_task_id)
        continuation=SharedCandidateContinuationOwner(self.conn,self.settings,enabled=True)
        original=continuation._original(version.artifact_id,self.authority)
        from app.services.learning.item_supply.generation_contracts import GenerationRequestV2
        request=GenerationRequestV2.model_validate_json(json.dumps(original["request_json"]))
        phase=self.pipeline._phase(task,spec=version.specification,root=version.root_id,materials=request.materials,
            operation="persistent.candidate."+version.revision_id.hex+".review",kind="candidate",version=version)
        if isinstance(phase,BlockedPackPhase):
            return phase
        adopted=continuation.adopt_persistent_phase(phase=phase,artifact_id=version.artifact_id,
            spec=version.specification,source_authority=self.authority)
        gp=self._generation()
        phase.prepared.update(candidate_executor=self,generation_owner=gp,continuation_owner=continuation,
            continuation=adopted,policy=policy_for_hash(gp.artifacts.generation_policy(phase.record.lease,adopted.original_request,
                now=self.owner._guard()).policy_hash),resume_stage="validation_review")
        return phase

    def prepare_committed_review(self, task: PersistentPackTaskRef, version: PersistentPublicVersionRecord,
                                 review_id: UUID, *, clone_pair: tuple[UUID,UUID] | None=None) -> IssuedPackPhase | BlockedPackPhase:
        from app.services.learning.item_supply.shared_continuation import SharedCandidateContinuationOwner
        from app.services.learning.item_supply.finite_review_descriptor import finite_review_context
        from app.services.learning.item_supply.review_deliberation import review_disputes
        from app.services.learning.item_supply.diagnostic_policy import parse_bundle
        from app.services.learning.item_supply.generation_contracts import GenerationRequestV2
        from app.services.learning.item_supply.public_normal_source_ingress import require_public_normal_receivers
        try:
            require_public_normal_receivers(self.conn)
        except ValueError:
            return BlockedPackPhase("persistent_normal_525_receiver_required",task.pack_task_id)
        if version.artifact_id is None:
            raise PersistentPackPending("persistent_original_committed_artifact_required")
        continuation=SharedCandidateContinuationOwner(self.conn,self.settings,enabled=True)
        original=continuation._original(version.artifact_id,self.authority)
        request=GenerationRequestV2.model_validate_json(json.dumps(original["request_json"]))
        row=self.conn.execute("SELECT payload_json FROM tutor_item_supply_shared_pipeline_receipts WHERE id=%s "
            "AND generation_artifact_id=%s AND artifact_kind='review_bundle'",(review_id,version.artifact_id)).fetchone()
        if row is None:
            raise PersistentPackPending("persistent_original_committed_review_required")
        bundle=parse_bundle(row["payload_json"])
        from app.services.learning.item_bank.contracts import LearningItemSourceV1
        source=LearningItemSourceV1.model_validate_json(json.dumps(original["source_json"]))
        with finite_review_context(source,spec=version.specification,materials=request.materials):
            if not review_disputes(bundle) and clone_pair is None:
                return BlockedPackPhase("committed_quality_requires_original_facts_continuation",task.pack_task_id)
        phase=self.pipeline._phase(task,spec=version.specification,root=version.root_id,materials=request.materials,
            operation="persistent.candidate."+version.revision_id.hex+".repair",kind="candidate",version=version)
        if isinstance(phase,BlockedPackPhase):
            return phase
        adopted=continuation.adopt_persistent_phase(phase=phase,artifact_id=version.artifact_id,
            spec=version.specification,source_authority=self.authority)
        model=self.pipeline.provider.configured_model
        rp=SharedReviewPipeline(self.conn,self.settings,enabled=True,continuation_owner=continuation,
            trusted_model_bindings={(self.pipeline.provider.provider_key,model):model})
        with finite_review_context(source,spec=version.specification,materials=request.materials):
            review,reviewed=rp.reissue_committed_phase(phase=phase,review_receipt_id=review_id,source_authority=self.authority)
        gp=self._generation()
        phase.prepared.update(candidate_executor=self,generation_owner=gp,continuation_owner=continuation,
            continuation=adopted,policy=policy_for_hash(review.binding.policy_hash),resume_stage="committed_review_repair",
            review_owner=rp,review=review,reviewed=reviewed,review_id=review_id,clone_pair=clone_pair)
        return phase

    @staticmethod
    def _policy() -> Any:
        from app.services.learning.item_supply.diagnostic_policy import AutonomousEvidencePolicyV3
        return AutonomousEvidencePolicyV3()

    def _generation(self) -> SharedGenerationPipeline:
        provider = self.pipeline.provider
        return SharedGenerationPipeline(self.conn,self.settings,enabled=True,
            trusted_model_bindings={(provider.provider_key,provider.configured_model):provider.configured_model})

    def remaining(self, phase: IssuedPackPhase, lease: Any, requests: int, *, bound: Any=None) -> None:
        self.owner.require_phase(phase,kind="candidate")
        now = self.owner._guard()
        self.owner.runtime._control(lease,now=now,compare_version=False)
        deadline = min(phase.record.valid_until,lease.expires_at,lease.parent_deadline,
            lease.profile.bound_at+timedelta(milliseconds=lease.profile.values.stage_deadline_ms))
        if bound is not None:
            deadline=min(deadline,bound)
        if (deadline-self.owner._guard()).total_seconds()<=requests*100+15:
            raise PersistentPackPending("persistent_next_stage_remaining_insufficient")

    def stage_start(self, phase: IssuedPackPhase, stage: str, *, lease: Any, requests: int, bound: Any=None) -> None:
        self.remaining(phase,lease,requests,bound=bound)
        if phase.record.revision_id is None:
            raise PersistentPackPending("persistent_candidate_revision_required")
        from app.services.learning.item_supply.persistent_pack_explicit_recovery import stage_operation
        key=stage_operation(self.owner,phase,stage)
        # Only the536-issued investigation attempt has an explicitly bound alternate key.
        prior=self.conn.execute("SELECT record_kind FROM tutor_item_supply_shared_persistent_pack_journal "
            "WHERE operation_key=%s AND record_kind IN('stage_started','stage_result')",(key,)).fetchall()
        if prior:
            raise PersistentPackPending("persistent_committed_stage_or_unknown_no_paid_replay")
        self.owner._public_event(phase.record.public_task_id,"stage_started",dict(schema_version="persistent_stage_started_v1",
            phase_id=str(phase.record.phase_id),stage=stage,operation_key=key),key=key,
            root_id=phase.record.root_id,job_id=phase.record.job_id,phase_id=phase.record.phase_id)

    def stage_result(self, phase: IssuedPackPhase, stage: str, receipt: UUID | None, *, outcome: str="completed") -> None:
        if phase.record.revision_id is None:
            raise PersistentPackPending("persistent_candidate_revision_required")
        from app.services.learning.item_supply.persistent_pack_explicit_recovery import stage_operation
        key=stage_operation(self.owner,phase,stage)
        self.owner._public_event(phase.record.public_task_id,"stage_result",dict(schema_version="persistent_stage_result_v1",
            phase_id=str(phase.record.phase_id),stage=stage,operation_key=key,outcome=outcome,
            receipt_id=None if receipt is None else str(receipt),safe_reason="original_stage_committed"),key=key,
            root_id=phase.record.root_id,job_id=phase.record.job_id,phase_id=phase.record.phase_id)

    def _ports(self, lease: Any, spec: Any) -> Any:
        model=self.pipeline.provider.configured_model
        ports=[]
        port: JsonBlindSolverV2 | JsonReviewerV2
        for role in ("blind_solver",*[r.value for r in REQUIRED_REVIEW_ROLES]):
            client=BoundedOpenAIReviewClient(self.settings,profile=lease.profile)
            if client.model!=model or client.configured_provider!=self.pipeline.provider.provider_key:
                raise PersistentPackPending("persistent_review_configured_identity_required")
            identity=ProviderIdentityV2(identity="deepseek.persistent."+lease.job_id.hex+"."+role,
                provider=client.configured_provider,model=model,model_version=model)
            if role=="blind_solver":
                port=JsonBlindSolverV2(client,identity=identity,profile_hash=lease.profile.profile_hash,
                    timeout_seconds=100,max_output_tokens=FORMAL,max_input_bytes=262144,
                    blind_protocol=SINGLE_CHOICE_BLIND_PROTOCOL if spec.target_id=="python-kc-binding-v1" else LEGACY_BLIND_PROTOCOL)
            else:
                port=JsonReviewerV2(client,role=next(r for r in REQUIRED_REVIEW_ROLES if r.value==role),
                    identity=identity,profile_hash=lease.profile.profile_hash,timeout_seconds=100,
                    max_output_tokens=FORMAL,max_input_bytes=262144,review_protocol="evidenced-v1")
            ports.append(port)
        return ports[0],tuple(ports[1:])

    def record_version(self, phase: IssuedPackPhase, version: PersistentPublicVersionRecord, kind: str) -> None:
        self.owner._public_event(phase.record.public_task_id,kind,version.model_dump(mode="json"),
            key="persistent.version."+version.revision_id.hex,root_id=version.root_id)

    def run(self, phase: IssuedPackPhase) -> PersistentPhaseOutcome:
        if phase.version is None:
            raise PersistentPackPending("persistent_candidate_version_required")
        if phase.prepared.get("resume_stage")=="committed_child_recheck":
            return self.run_committed_child_recheck(phase)
        if phase.prepared.get("resume_stage")=="committed_review_repair":
            vp=SharedValidationPipeline(self.conn,self.settings,enabled=True,
                continuation_owner=phase.prepared["continuation_owner"])
            return self.normal_loop(phase,version=phase.version,gp=phase.prepared["generation_owner"],vp=vp,
                rp=phase.prepared["review_owner"],lease=phase.record.lease,review=phase.prepared["review"],
                reviewed=phase.prepared["reviewed"],review_id=phase.prepared["review_id"])
        if phase.prepared.get("resume_stage")=="validation_review":
            if phase.version.artifact_id is None:
                raise PersistentPackPending("persistent_original_committed_artifact_required")
            return self.validate_review(phase,artifact=phase.version.artifact_id,lease=phase.record.lease,
                gp=phase.prepared["generation_owner"])
        gp, prepared = phase.prepared["generation_owner"],phase.prepared["generation"]
        with self.conn.transaction():
            self.stage_start(phase,"author",lease=prepared.lease,requests=17)
        generated=gp.run_generation(prepared,self.pipeline.provider)
        with self.conn.transaction():
            gp.settle_generation(prepared,generated)
        with self.conn.transaction():
            staged=gp.commit_generation(prepared,generated,source_authority=self.authority)
            self.stage_result(phase,"author",staged.artifact_id,outcome="completed" if staged.state=="staged" else "failed")
        if staged.state!="staged" or staged.artifact_id is None:
            return self.failed(phase,"original_author_failed_no_repeat")
        with self.conn.transaction():
            lease=gp.runtime.refresh_lease(prepared.lease,now=self.owner._guard())
        return self.validate_review(phase,artifact=staged.artifact_id,lease=lease,gp=gp)

    def validate_review(self, phase: IssuedPackPhase, *, artifact: UUID, lease: Any, gp: Any) -> PersistentPhaseOutcome:
        version=phase.version
        if version is None:
            raise PersistentPackPending("persistent_fixed_candidate_version_required")
        continuation=phase.prepared.get("continuation_owner")
        vp=SharedValidationPipeline(self.conn,self.settings,enabled=True,continuation_owner=continuation)
        with self.conn.transaction():
            self.remaining(phase,lease,16)
            validation=vp.prepare_validation(lease=lease,artifact_id=artifact,spec=version.specification,
                source_authority=self.authority,runner=self.owner.runner,operation_deadline_at=phase.record.valid_until)
            if validation is None:
                raise PersistentPackPending("persistent_original_validation_prepare_required")
            version=version.model_copy(update={"artifact_id":artifact})
            self.record_version(phase,version,"version")
        result=vp.run_validation(validation)
        with self.conn.transaction():
            vp.settle_validation(validation,result)
        with self.conn.transaction():
            validated=vp.commit_validation(validation,result)
        if validated.state!="machine_verified" or validated.validation_receipt_id is None:
            return self.failed(phase,"original_validation_failed_same_item",artifact)
        with self.conn.transaction():
            lease=vp.runtime.refresh_lease(lease,now=self.owner._guard())
        solver,reviewers=self._ports(lease,version.specification)
        rp=SharedReviewPipeline(self.conn,self.settings,enabled=True,
            trusted_model_bindings=gp._models,blind_protocol=solver.blind_protocol,continuation_owner=continuation)
        with self.conn.transaction():
            self.remaining(phase,lease,7)
            review=rp.prepare_review(lease=lease,artifact_id=artifact,validation_receipt_id=validated.validation_receipt_id,
                spec=version.specification,source_authority=self.authority,solver=solver,reviewers=reviewers,
                runner=self.owner.runner,operation_deadline_at=phase.record.valid_until)
            if review is None or review.resources.requests!=7:
                raise PersistentPackPending("persistent_exact_blind_six_prepare_required")
            self.stage_start(phase,"review",lease=lease,requests=7)
        reviewed=rp.run_review(review)
        with self.conn.transaction():
            rp.settle_review(review,reviewed)
        with self.conn.transaction():
            committed=rp.commit_review(review,reviewed)
            self.stage_result(phase,"review",committed.review_receipt_id,
                outcome="completed" if committed.review_receipt_id is not None else "failed")
        if (committed.blind_receipt_id is None or committed.review_receipt_id is None or reviewed.bundle is None
            or reviewed.blind is None or not completed_blind_allowed(reviewed.blind,phase.prepared["policy"])):
            return self.failed(phase,"original_independent_review_incomplete",artifact)
        from app.services.learning.item_supply.finite_review_descriptor import finite_review_context
        from app.services.learning.item_supply.review_deliberation import review_disputes
        with finite_review_context(review.source,spec=review.spec,materials=review.request.materials):
            disputes=review_disputes(reviewed.bundle)
        with self.conn.transaction():
            lease=rp.runtime.refresh_lease(lease,now=self.owner._guard())
        if disputes:
            return self.normal_loop(phase,version=version,gp=gp,vp=vp,rp=rp,lease=lease,review=review,
                reviewed=reviewed,review_id=committed.review_receipt_id)
        from app.services.learning.item_supply.shared_admission_facts import SharedAdmissionFactsOwner
        issuer=SharedAdmissionFactsOwner(self.conn,validation_pipeline=vp,review_pipeline=rp,enabled=True)
        with self.conn.transaction():
            facts=issuer.issue(lease=lease,validation_prepared=validation,validation_result=result,
                validation_receipt_id=validated.validation_receipt_id,review_prepared=review,review_result=reviewed,
                blind_receipt_id=committed.blind_receipt_id,review_receipt_id=committed.review_receipt_id)
        if facts.evaluation.disposition!="eligible_internal":
            return self.failed(phase,"original_full_admission_denied",artifact)
        return self.publish(phase,version=version,lease=lease,vp=vp,rp=rp,issuer=issuer,facts=facts)

    @staticmethod
    def failed(phase: IssuedPackPhase, reason: str, artifact: UUID | None=None) -> PersistentPhaseOutcome:
        return PersistentPhaseOutcome(phase_id=phase.record.phase_id,status="quality_failed",safe_reason=reason,artifact_id=artifact)

    def normal_loop(self, phase: IssuedPackPhase, *, version: PersistentPublicVersionRecord,
            gp: Any, vp: Any, rp: Any, lease: Any, review: Any, reviewed: Any, review_id: UUID) -> PersistentPhaseOutcome:
        from app.services.learning.item_supply.finite_review_descriptor import finite_review_context
        from app.services.learning.item_supply.native_review_investigation import NativeReviewInvestigationOwner
        from app.services.learning.item_supply.native_revision import NativeRevisionOwner
        from app.services.learning.item_supply.native_revision_recheck import NativeRevisionRecheckOwner
        from app.services.learning.item_supply.native_normal_revision_readmission import NativeNormalRevisionReadmissionOwner
        from app.services.learning.item_supply.shared_admission_facts import SharedAdmissionFactsOwner
        investigator=NativeReviewInvestigationOwner(rp,enabled=True,protocol="scalar-evidence-v2")
        with self.conn.transaction():
            self.remaining(phase,lease,9)
            with finite_review_context(review.source,spec=review.spec,materials=review.request.materials):
                if review.persistent_committed_frame is None:
                    investigation=investigator.prepare(original=review,result=reviewed,lease=lease,review_receipt_id=review_id)
                else:
                    investigation=investigator.prepare_persistent(phase=phase,original=review,result=reviewed,
                        review_receipt_id=review_id,clone_pair=phase.prepared.get("clone_pair"))
            if investigation is None or investigation.resources.requests!=1 or investigation.resources.output_tokens!=FORMAL:
                raise PersistentPackPending("persistent_original_formal_investigation_required")
            self.stage_start(phase,"investigation",lease=lease,requests=9,bound=investigation.deadline_at)
        investigated=investigator.run(investigation)
        with self.conn.transaction():
            investigator.settle(investigation,investigated)
        with self.conn.transaction():
            investigation_id=investigator.persist(investigation,investigated)
            self.stage_result(phase,"investigation",investigation_id,
                outcome="completed" if investigated.report is not None else "failed")
        if investigated.report is None:
            return self.failed(phase,"original_investigation_failed_no_repeat",version.artifact_id)
        revision_owner=NativeRevisionOwner(investigator,gp,enabled=True)
        with self.conn.transaction():
            self.remaining(phase,lease,8)
            revision=revision_owner.prepare(investigation=investigation,result=investigated,investigation_receipt_id=investigation_id)
            if revision is None:
                raise PersistentPackPending("persistent_original_substantive_revision_required")
        with self.conn.transaction():
            author=revision_owner.prepare_author(revision,provider=self.pipeline.provider)
            if author is None:
                raise PersistentPackPending("persistent_original_revision_author_required")
            self.stage_start(phase,"revision",lease=revision.lease,requests=8,bound=revision.deadline_at)
        revised=revision_owner.run(revision,author)
        with self.conn.transaction():
            settlement=revision_owner.settle(revision,author,revised)
        if settlement.durability == "settled_only":
            return PersistentPhaseOutcome(phase_id=phase.record.phase_id,status="blocked",safe_reason=settlement.safe_reason)
        with self.conn.transaction():
            child=revision_owner.commit_generation(revision,author,revised)
        if child.state!="staged" or child.artifact_id is None:
            with self.conn.transaction():
                self.stage_result(phase,"revision",None,outcome="failed")
            return self.failed(phase,"original_substantive_child_failed_no_repeat",version.artifact_id)
        with self.conn.transaction():
            child_lease=gp.runtime.refresh_lease(revision.lease,now=self.owner._guard())
            lineage_id=revision_owner.persist_lineage(revision,author,revised,lease=child_lease)
            self.stage_result(phase,"revision",lineage_id)
        # Stable business slot; a genuine original509 lineage, not replacement DATA.
        child_version=PersistentPublicVersionRecord(public_task_id=version.public_task_id,
            public_slot_id=version.public_slot_id,slot=version.slot,
            revision_id=uuid5(NAMESPACE_URL,"persistent.child."+revision.preparation_id.hex),
            revision_seq=version.revision_seq+1,parent_revision_id=version.revision_id,
            candidate_id=revision.request.candidate_id,specification=revision.spec,root_id=version.root_id,artifact_id=child.artifact_id)
        recheck=NativeRevisionRecheckOwner(revision_owner,vp,rp,enabled=True,persistent_phase=phase)
        with self.conn.transaction():
            prepared=recheck.prepare(revision=revision,author=author,author_result=revised,lease=child_lease)
            if prepared is None:
                raise PersistentPackPending("persistent_original_child_recheck_required")
        with self.conn.transaction():
            validation=recheck.prepare_validation(prepared,lease=child_lease,runner=self.owner.runner)
            if validation is None:
                raise PersistentPackPending("persistent_child_new_validation_required")
            self.record_version(phase,child_version,"version")
        recheck.run_validation(prepared)
        with self.conn.transaction():
            recheck.settle_validation(prepared)
        with self.conn.transaction():
            child_validation=recheck.commit_validation(prepared)
        if child_validation.state!="machine_verified" or child_validation.validation_receipt_id is None:
            return self.failed(phase,"original_child_validation_failed_same_item",child.artifact_id)
        with self.conn.transaction():
            child_lease=vp.runtime.refresh_lease(child_lease,now=self.owner._guard())
            self.remaining(phase,child_lease,7,bound=revision.deadline_at)
            independent=recheck.prepare_review(prepared,lease=child_lease)
            if independent is None or independent.resources.requests!=7:
                raise PersistentPackPending("persistent_child_independent_blind_six_required")
            self.stage_start(phase,"recheck",lease=child_lease,requests=7,bound=revision.deadline_at)
        rechecked=recheck.run_review(prepared)
        with self.conn.transaction():
            recheck.settle_review(prepared)
        with self.conn.transaction():
            reviewed_stage=recheck.commit_review(prepared)
        if reviewed_stage.blind_receipt_id is None or reviewed_stage.review_receipt_id is None:
            with self.conn.transaction():
                self.stage_result(phase,"recheck",None,outcome="failed")
            return self.failed(phase,"original_child_independent_review_incomplete",child.artifact_id)
        if rechecked.blind is None or rechecked.bundle is None:
            raise PersistentPackPending("persistent_child_complete_original_result_required")
        with self.conn.transaction():
            child_lease=rp.runtime.refresh_lease(child_lease,now=self.owner._guard())
            recheck_id=recheck.persist_dispute_evidence(prepared,lease=child_lease)
            self.stage_result(phase,"recheck",recheck_id)
        # 510 remains DATA-only, unsupported findings are NOT discharged.
        normal=NativeNormalRevisionReadmissionOwner(recheck,enabled=True)
        with self.conn.transaction():
            permit=normal.prepare(recheck=prepared,lease=child_lease,recheck_receipt_id=recheck_id)
            context=normal.verify_context(permit,lease=child_lease)
        issuer=SharedAdmissionFactsOwner(self.conn,validation_pipeline=vp,review_pipeline=rp,
            normal_readmission_owner=normal,enabled=True)
        with self.conn.transaction():
            facts=issuer.issue(lease=child_lease,validation_prepared=context.validation_prepared,
                validation_result=context.validation_result,validation_receipt_id=context.validation_receipt_id,
                review_prepared=context.review_prepared,review_result=context.review_result,
                blind_receipt_id=context.blind_receipt_id,review_receipt_id=context.review_receipt_id,normal_readmission=permit)
        if facts.evaluation.disposition!="eligible_internal":
            return self.failed(phase,"original_child_full_admission_denied",child.artifact_id)
        return self.publish(phase,version=child_version,lease=child_lease,vp=vp,rp=rp,issuer=issuer,facts=facts)

    def publish(self, phase: IssuedPackPhase, *, version: PersistentPublicVersionRecord,
                lease: Any, vp: Any, rp: Any, issuer: Any, facts: Any) -> PersistentPhaseOutcome:
        from app.services.learning.item_bank.native_import import NativeLearningItemBankImporter
        from app.services.learning.item_bank.native_publication import NativeLearningItemPublicationService
        if facts.evaluation.disposition!="eligible_internal":
            raise PersistentPackPending("persistent_original_admission_required")
        bindings=tuple(self.owner.type_owner.query._bindings.values())
        importer=NativeLearningItemBankImporter(self.conn,self.settings,artifacts=vp.artifacts,
            source_authority=self.authority,enabled=True)
        publisher=NativeLearningItemPublicationService(self.conn,self.settings,importer=importer,
            facts_owner=issuer,approved_internal_bindings=bindings,enabled=True)
        with self.conn.transaction():
            self.remaining(phase,lease,0)
            imported=importer.import_candidate(lease=lease,artifact_id=facts.generation_artifact_id,
                validation_receipt_id=facts.validation_receipt_id,spec=version.specification,
                import_key="persistent.public."+version.revision_id.hex)
            proof=publisher.publish_internal(imported,lease=lease,spec=version.specification,facts_receipt=facts)
            qualified=version.model_copy(update={"published_version_id":proof.version_id,"artifact_id":facts.generation_artifact_id})
            self.record_version(phase,qualified,"qualified")
        # These original owner objects are retained only in this actual process.
        phase.prepared.update(publication=proof,validation_owner=vp,review_owner=rp,facts_owner=issuer,publisher=publisher)
        return PersistentPhaseOutcome(phase_id=phase.record.phase_id,status="qualified",safe_reason="original_full_publication_completed",
            artifact_id=facts.generation_artifact_id,published_version_id=proof.version_id)

    def run_committed_child_recheck(self, phase: IssuedPackPhase) -> PersistentPhaseOutcome:
        """Only new validation/independent review/admission; never investigate/author."""
        from app.services.learning.item_supply.persistent_pack_committed_recheck import IssuedCommittedChildRecheck
        from app.services.learning.item_supply.native_normal_revision_readmission import NativeNormalRevisionReadmissionOwner
        from app.services.learning.item_supply.shared_admission_facts import SharedAdmissionFactsOwner
        frame=phase.prepared["committed_child_frame"]
        if type(frame) is not IssuedCommittedChildRecheck or frame.phase is not phase or phase.version is None:
            raise PersistentPackPending("persistent_committed_child_process_frame_required")
        recheck,p=frame.recheck_owner,frame.recheck
        lease=phase.record.lease
        vp,rp=recheck.validation,recheck.review
        with self.conn.transaction():
            self.remaining(phase,lease,7,bound=frame.revision.deadline_at)
            validation=recheck.prepare_validation(p,lease=lease,runner=self.owner.runner)
            if validation is None:
                raise PersistentPackPending("persistent_child_new_validation_required")
        recheck.run_validation(p)
        with self.conn.transaction():
            recheck.settle_validation(p)
        with self.conn.transaction():
            validated=recheck.commit_validation(p)
        if validated.state!="machine_verified" or validated.validation_receipt_id is None:
            return self.failed(phase,"original_child_validation_failed_same_item",p.artifact_id)
        with self.conn.transaction():
            lease=vp.runtime.refresh_lease(lease,now=self.owner._guard())
            independent=recheck.prepare_review(p,lease=lease)
            if independent is None or independent.resources.requests!=7:
                raise PersistentPackPending("persistent_child_independent_blind_six_required")
            self.stage_start(phase,"recheck",lease=lease,requests=7,bound=frame.revision.deadline_at)
        result=recheck.run_review(p)
        with self.conn.transaction():
            recheck.settle_review(p)
        with self.conn.transaction():
            reviewed=recheck.commit_review(p)
        if (reviewed.blind_receipt_id is None or reviewed.review_receipt_id is None
                or result.blind is None or result.bundle is None):
            with self.conn.transaction():
                self.stage_result(phase,"recheck",None,outcome="failed")
            return self.failed(phase,"original_child_independent_review_incomplete",p.artifact_id)
        with self.conn.transaction():
            lease=rp.runtime.refresh_lease(lease,now=self.owner._guard())
            receipt=recheck.persist_dispute_evidence(p,lease=lease)
            self.stage_result(phase,"recheck",receipt)
        normal=NativeNormalRevisionReadmissionOwner(recheck,enabled=True)
        with self.conn.transaction():
            permit=normal.prepare(recheck=p,lease=lease,recheck_receipt_id=receipt)
            inputs=normal.verify_context(permit,lease=lease)
        issuer=SharedAdmissionFactsOwner(self.conn,validation_pipeline=vp,review_pipeline=rp,
            normal_readmission_owner=normal,enabled=True)
        with self.conn.transaction():
            facts=issuer.issue(lease=lease,validation_prepared=inputs.validation_prepared,
                validation_result=inputs.validation_result,validation_receipt_id=inputs.validation_receipt_id,
                review_prepared=inputs.review_prepared,review_result=inputs.review_result,
                blind_receipt_id=inputs.blind_receipt_id,review_receipt_id=inputs.review_receipt_id,normal_readmission=permit)
        if facts.evaluation.disposition!="eligible_internal":
            return self.failed(phase,"original_child_full_admission_denied",p.artifact_id)
        return self.publish(phase,version=phase.version,lease=lease,vp=vp,rp=rp,issuer=issuer,facts=facts)
