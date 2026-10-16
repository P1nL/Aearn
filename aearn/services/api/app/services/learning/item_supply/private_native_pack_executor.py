"""Explicit internal PRIVATE phase factory/executor on ONE original task/root.

Network is only in original author/review runners, between committed transactions.
No callbacks, shared522/517 grants, restored capability or JSON ready bits.
"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import nullcontext
from datetime import timedelta

from typing import Any, Literal, cast
from uuid import UUID, uuid4

from psycopg.pq import TransactionStatus

from app.services.learning.item_supply.type_evidence import RelationshipRoleV2
from app.services.learning.item_bank.review_contracts import REQUIRED_REVIEW_ROLES
from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.blind_protocol import SINGLE_CHOICE_BLIND_PROTOCOL
from app.services.learning.item_supply.diagnostic_policy import AutonomousEvidencePolicyV3
from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1, FLEXIBLE_FACTORY_VERSION, build_finite_candidate_spec
from app.services.learning.item_supply.generation_contracts import GenerationLimitsV2, GenerationResultV2, PublicMaterialV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.parameter_profiles import ExecutionParameterProfileV1, ParameterValuesV1, ProfileKeyV1
from app.services.learning.item_supply.persistent_pack_contracts import PersistentPackTaskRef, PersistentPackSlotRef
from app.services.learning.item_supply.policies import CoverageObligationV1, ResourceAmounts, RESOURCE_KINDS, RetryPolicyV1, derive_runtime_contract_hash
from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending, PrivateSlotRef
from app.services.learning.item_supply.private_enhancement_service import (
    IssuedPrivateInitialAuthorRecovery, PreparedPrivateSlotGeneration, PRIVATE_JOURNAL,
    RECOVERY_KEY, RECOVERY_ROOT, RECOVERY_SLOT, CONTINUATION_KEY,
)
from app.services.learning.item_supply.private_native_admission_facts import PreparedPrivateReview, CompletedPrivateReview
from app.services.learning.item_supply.private_generation_persistence import IssuedPrivateGenerationPersistence
from app.services.learning.item_supply.private_generation_persistence_phase import IssuedPrivateGenerationPersistencePhase
from app.services.learning.item_supply.private_native_committed_progress import IssuedPrivateInitialQualityHandoff, IssuedPrivatePersistencePhaseQuality, IssuedPrivateCommittedPhaseQuality
from app.services.learning.item_supply.private_native_review_loop import PrivateNativeNormalReviewLoopOwner, PrivateNativeNormalReadmissionOwner, PrivateNativeRelationReviewOwner
from app.services.learning.item_supply.provider_adapter import OpenAICompatibleGenerationProvider, GENERATION_PROMPT_VERSION
from app.services.learning.item_supply.review_contracts_v2 import ProviderIdentityV2
from app.services.learning.item_supply.review_provider import BoundedOpenAIReviewClient, JsonBlindSolverV2, JsonReviewerV2
from app.services.learning.item_supply.storage_contracts import checked_model


@dataclass(frozen=True)
class PrivatePhaseOutcome:
    pack_task_id: UUID
    status: Literal['published','review_pending','revision_pending','relation_ready','quality_failed','preparing','not_started']
    version_id: UUID | None = None
    reason: str = 'current_original_authority_required'


@dataclass(frozen=True)
class _PrivateWork:
    task: PersistentPackTaskRef
    slot: PersistentPackSlotRef
    ref: PrivateSlotRef
    lease: JobLeaseV1
    spec: FiniteCandidateSpecV1
    materials: tuple[PublicMaterialV2, ...]


class PrivateNativePackExecutor:
    """Single concrete entry. Caller supplies owners, never prepared JSON/providers."""
    def __init__(self, service: Any) -> None:
        from app.services.learning.item_supply.private_enhancement_service import PrivateEnhancementService
        if type(service) is not PrivateEnhancementService:
            raise PrivateNativePending('private_executor_concrete_service_required')
        self.service, self.conn, self.settings = service, service.conn, service.settings
        self.development_accounting_enabled = service.development_accounting_enabled
        self.facts, self.runtime, self.budget = service.facts_owner, service.facts_owner.pipeline.runtime, service.facts_owner.pipeline.budget
        self.provider = OpenAICompatibleGenerationProvider(self.settings,max_http_attempts=1)
        if (self.provider.provider_key,self.provider.configured_model,self.settings.tutor_max_output_tokens) != ('deepseek','deepseek-flash',61440):
            raise PrivateNativePending('private_executor_original_formal_profile_required')
        self.loop = PrivateNativeNormalReviewLoopOwner(self.facts,enabled=service.enabled)
        self.normal = PrivateNativeNormalReadmissionOwner(self.loop,enabled=service.enabled)
        self._review: dict[UUID,tuple[_PrivateWork,UUID]] = {}
        self._failed: dict[UUID,tuple[_PrivateWork,PreparedPrivateReview,CompletedPrivateReview]] = {}
        self._investigation: dict[UUID,tuple[_PrivateWork,UUID]] = {}
        from app.services.learning.item_supply.private_native_committed_progress import PrivateNativeCommittedProgressOwner
        self.progress = PrivateNativeCommittedProgressOwner(self.facts)
        from app.services.learning.item_supply.private_native_relation_repair import PrivateNativeRelationRepairOwner
        self.relation_repair = PrivateNativeRelationRepairOwner(service)
        self._initial_authors: dict[UUID,tuple[PreparedPrivateSlotGeneration,IssuedPrivateInitialAuthorRecovery,_PrivateWork]] = {}
        self._initial_finished: set[UUID] = set()
        self._initial_success: dict[UUID,tuple[PreparedPrivateSlotGeneration,_PrivateWork,UUID]] = {}
        self._initial_reviews: dict[UUID,tuple[PreparedPrivateReview,_PrivateWork,UUID,PreparedPrivateSlotGeneration | IssuedPrivateInitialQualityHandoff | IssuedPrivatePersistencePhaseQuality | IssuedPrivateCommittedPhaseQuality]] = {}
        self._durable_initial_quality: dict[UUID,IssuedPrivateInitialQualityHandoff | IssuedPrivatePersistencePhaseQuality | IssuedPrivateCommittedPhaseQuality] = {}

    def prepare_initial_author_recovery(self, task_ref: PersistentPackTaskRef, *,
                                       recovery: IssuedPrivateInitialAuthorRecovery) -> PreparedPrivateSlotGeneration:
        self.service._require_initial_recovery(recovery)
        if recovery.task != task_ref:
            raise PrivateNativePending('private_recovery_exact_approved_task_required')
        actual = self.service._recovery_source(task_ref)
        record = self.service.core._task(task_ref)
        slot = next(s for s in record.slots if s.slot_id == recovery.slot_id)
        # _phase(kind='candidate') retains the original full PRIVATE whole-base
        # resolve/require in record_wait_window before generation reservation.
        # Do not repeat that expensive dynamic resolution before the same phase.
        retained = self.service.core._versions(task_ref)[slot.slot].published_version_id
        if retained is None:
            raise PrivateNativePending('private_executor_actual_current_base_version_required')
        public = self.service.base_service.type_owner.resolve_content(retained,current=True)
        original = public.spec
        spec = build_finite_candidate_spec(target_id=original.target_id,variant_id=original.allocation.variant_id,
            seed=original.seed,item_key='private-native.'+slot.logical_item_id.hex,version='v1',materials=actual.public_materials,
            runtime_profile_hash=None,scorer_version=original.coverage_blueprint.scope.scorer_version,
            assistance_policy_hash=original.coverage_blueprint.scope.assistance_policy_hash,
            policy_version=original.coverage_blueprint.policy_version,difficulty_profile=original.blueprint.difficulty_profile,
            publication_policy=original.blueprint.publication_policy,public_spec_version=FLEXIBLE_FACTORY_VERSION,allocation=original.allocation)
        work = self._phase(task_ref,slot,spec,actual.public_materials,recovery=recovery)
        prepared = self.service.prepare_generation(ref=work.ref,lease=work.lease,spec=spec,materials=work.materials,
            limits=GenerationLimitsV2(max_input_bytes=262144,max_output_tokens=61440,max_output_bytes=262144),
            provider=self.provider,recovery=recovery)
        self._stage(work,'author',subject=spec.public_template.version,started=True,recovery=recovery)
        actual.require()
        self.facts._guard(work.ref,work.lease)
        self._initial_authors[prepared.original.request.candidate_id]=(prepared,recovery,work)
        return prepared

    def finish_initial_author_recovery(self, prepared: PreparedPrivateSlotGeneration, result: GenerationResultV2) -> PrivatePhaseOutcome:
        key = prepared.original.request.candidate_id
        saved = self._initial_authors.get(key)
        if (self.conn.info.transaction_status != TransactionStatus.IDLE or saved is None or saved[0] is not prepared
                or key in self._initial_finished or self.service._results.get(key) is not result):
            raise PrivateNativePending('private_recovery_original_live_author_required')
        _,recovery,work = saved
        with self.conn.transaction(), self.service._fresh_recovery_source(work.task):
            if result.state == 'staged':
                # Independent settlement must already have committed, not merely
                # have been called in this persistence transaction. The service
                # also requires the exact sealed output in a different TOP.
                settled = self.conn.execute('SELECT id FROM tutor_item_supply_private_runtime_settlements '
                    'WHERE reservation_id=%s AND settlement_key=%s AND xmin::text::bigint<>(txid_current() %% 4294967296)',
                    (prepared.original.reservation_id,'generation.'+key.hex)).fetchone()
                if settled is None:
                    raise PrivateNativePending('private_recovery_committed_settlement_consume_required')
                artifact = self.service.persist_generation(prepared,result)
                work = self._refresh(work)
                self._stage(work,'author',subject=work.spec.public_template.version,result=artifact,recovery=recovery)
            else:
                self.service.persist_generation_failure(prepared,result)
        self._initial_finished.add(key)
        if result.state != 'staged':
            return PrivatePhaseOutcome(work.task.pack_task_id,'quality_failed',reason='genuine_private_initial_author_failure_committed')
        self._initial_success[key]=(prepared,work,artifact)
        self._review[work.slot.slot_id]=(work,artifact)
        return PrivatePhaseOutcome(work.task.pack_task_id,'review_pending',reason='genuine_private_recovery_author_committed')

    def _initial_review_time(self, work: _PrivateWork) -> None:
        from app.services.learning.item_supply.private_development_model_accounting import accounting_batch_for_lease
        actual = self.service._recovery_source(work.task)
        batch = accounting_batch_for_lease(self.conn,work.lease,now=self.service._guard())
        if batch is None:
            raise PrivateNativePending('private_recovery_quality_current_work_required')
        deadline = min(actual.source_deadline,work.lease.expires_at,work.lease.parent_deadline,
            work.lease.profile.parent_deadline_at,work.lease.profile.bound_at+
            timedelta(milliseconds=work.lease.profile.values.stage_deadline_ms),batch['valid_until'])
        actual.require()
        now = self.facts._guard(work.ref,work.lease)
        if (deadline-max(now,self.service._guard())).total_seconds() <= 7*work.lease.profile.values.request_timeout_ms/1000+15:
            raise PrivateNativePending('private_recovery_quality_current_work_required')

    def prepare_initial_recovery_review(self, prepared_author: PreparedPrivateSlotGeneration) -> PreparedPrivateReview:
        from app.services.learning.item_supply.native_type_contracts import NativeTypeEvidencePending
        from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
        from app.services.learning.item_supply.policies import SupplyRuntimeError
        try:
            return self._prepare_initial_recovery_review(prepared_author)
        except (NativeTypeEvidencePending,PipelineRepositoryError,SupplyRuntimeError):
            raise PrivateNativePending('private_recovery_quality_current_work_required') from None

    def _prepare_initial_recovery_review(self, prepared_author: PreparedPrivateSlotGeneration) -> PreparedPrivateReview:
        saved = self._initial_success.get(prepared_author.original.request.candidate_id)
        if saved is None or saved[0] is not prepared_author:
            raise PrivateNativePending('private_recovery_quality_live_work_required')
        _,work,artifact = saved
        self.service._recovery_source(work.task)
        work = self._refresh(work)  # Same live job, never root-wide claim/inherit.
        row = self.conn.execute('SELECT a.id FROM tutor_item_supply_private_generation_artifacts a '
            'JOIN tutor_item_supply_private_checkpoints cp ON cp.job_id=a.job_id AND cp.lease_generation=a.lease_generation '
            "AND cp.stage='generating' AND cp.status='completed' AND cp.receipt_hash=a.artifact_hash "
            'WHERE a.id=%s AND a.job_id=%s AND a.xmin::text::bigint<>(txid_current() %% 4294967296)',
            (artifact,work.lease.job_id)).fetchone()
        if row is None or self.runtime.next_stage(work.lease) != 'validating':
            raise PrivateNativePending('private_recovery_quality_current_work_required')
        return self._prepare_initial_quality(work,artifact,prepared_author)

    def adopt_persisted_initial(self, cap: IssuedPrivateGenerationPersistence) -> IssuedPrivateInitialQualityHandoff:
        handoff = self.progress.issue_initial_quality(cap)
        self._durable_initial_quality[cap.ref.slot_id] = handoff
        work = self._durable_quality_work(handoff)
        self._review[work.slot.slot_id] = (work,handoff.artifact_id)
        return handoff

    def adopt_persisted_phase(self, cap: IssuedPrivateGenerationPersistencePhase) -> IssuedPrivatePersistencePhaseQuality:
        handoff = self.progress.issue_persistence_phase_quality(cap)
        self._durable_initial_quality[cap.ref.slot_id] = handoff
        work = self._durable_quality_work(handoff)
        self._review[work.slot.slot_id] = (work,handoff.artifact_id)
        return handoff

    def _durable_quality_work(self, handoff: IssuedPrivateInitialQualityHandoff | IssuedPrivatePersistencePhaseQuality | IssuedPrivateCommittedPhaseQuality) -> _PrivateWork:
        if isinstance(handoff, IssuedPrivateCommittedPhaseQuality):
            lease = self.progress.require_committed_phase_quality(handoff)
            service,task,ref,request = handoff.service,handoff.task,handoff.ref,handoff.request
        else:
            lease = (self.progress.require_persistence_phase_quality(handoff) if isinstance(handoff, IssuedPrivatePersistencePhaseQuality)
                else self.progress.require_initial_quality(handoff))
            cap = handoff.persistence
            service,task,ref,request = cap.owner.service,cap.task,cap.ref,cap.request
        if service is not self.service or self._durable_initial_quality.get(ref.slot_id) is not handoff:
            raise PrivateNativePending('private_quality_original_executor_handoff_required')
        slot = next(s for s in self.service.core._task(task).slots if s.slot_id == ref.slot_id)
        return _PrivateWork(task,slot,ref,lease,handoff.spec,request.materials)

    @staticmethod
    def _quality_handoff_task(handoff: IssuedPrivateInitialQualityHandoff | IssuedPrivatePersistencePhaseQuality | IssuedPrivateCommittedPhaseQuality) -> PersistentPackTaskRef:
        return handoff.task if isinstance(handoff, IssuedPrivateCommittedPhaseQuality) else handoff.persistence.task

    def adopt_committed_phase_quality(self, *, task_ref: PersistentPackTaskRef, completion_id: UUID) -> IssuedPrivateCommittedPhaseQuality:
        handoff = self.progress.issue_committed_phase_quality(self.service,task_ref=task_ref,completion_id=completion_id)
        self._durable_initial_quality[handoff.ref.slot_id] = handoff
        work = self._durable_quality_work(handoff)
        self._review[work.slot.slot_id] = (work,handoff.artifact_id)
        return handoff

    def prepare_committed_phase_review(self, handoff: IssuedPrivateCommittedPhaseQuality) -> PreparedPrivateReview:
        work = self._durable_quality_work(handoff)
        if self.runtime.next_stage(work.lease) != 'validating':
            raise PrivateNativePending('private_quality_original_validating_stage_required')
        return self._prepare_initial_quality(work,handoff.artifact_id,handoff)

    def prepare_durable_initial_review(self, handoff: IssuedPrivateInitialQualityHandoff) -> PreparedPrivateReview:
        work = self._durable_quality_work(handoff)
        if self.runtime.next_stage(work.lease) != 'validating':
            raise PrivateNativePending('private_quality_original_validating_stage_required')
        return self._prepare_initial_quality(work,handoff.artifact_id,handoff)

    def prepare_persistence_phase_review(self, handoff: IssuedPrivatePersistencePhaseQuality) -> PreparedPrivateReview:
        work = self._durable_quality_work(handoff)
        if self.runtime.next_stage(work.lease) != 'validating':
            raise PrivateNativePending('private_quality_original_validating_stage_required')
        return self._prepare_initial_quality(work,handoff.artifact_id,handoff)

    def _prepare_initial_quality(self, work: _PrivateWork, artifact: UUID,
            selector: PreparedPrivateSlotGeneration | IssuedPrivateInitialQualityHandoff | IssuedPrivatePersistencePhaseQuality | IssuedPrivateCommittedPhaseQuality) -> PreparedPrivateReview:
        self._initial_review_time(work)
        validation_id,_ = self.facts.validate(ref=work.ref,lease=work.lease,artifact_id=artifact,spec=work.spec)
        work = self._refresh(work)
        client = BoundedOpenAIReviewClient(self.settings,profile=work.lease.profile)
        solver = JsonBlindSolverV2(client,identity=self._identity(work.lease,'blind_solver'),profile_hash=work.lease.profile.profile_hash,
            timeout_seconds=work.lease.profile.values.request_timeout_ms/1000,max_output_tokens=61440,max_input_bytes=262144,
            blind_protocol=SINGLE_CHOICE_BLIND_PROTOCOL)
        reviewers = tuple(JsonReviewerV2(BoundedOpenAIReviewClient(self.settings,profile=work.lease.profile),role=role,
            identity=self._identity(work.lease,role.value),profile_hash=work.lease.profile.profile_hash,
            timeout_seconds=work.lease.profile.values.request_timeout_ms/1000,max_output_tokens=61440,max_input_bytes=262144,
            review_protocol='evidenced-v1') for role in REQUIRED_REVIEW_ROLES)
        p = self.facts.prepare_review(ref=work.ref,lease=work.lease,artifact_id=artifact,spec=work.spec,
            policy=AutonomousEvidencePolicyV3(),solver=solver,reviewers=reviewers,
            resources=ResourceAmounts(requests=7,input_tokens=262144*7,output_tokens=61440*7))
        self._stage(work,'review',subject=str(artifact),started=True)
        self._initial_review_time(work)
        # Replaces a rolled-back probe preparation; that object can never run.
        self._initial_reviews[work.slot.slot_id]=(p,work,validation_id,selector)
        return p

    def run_initial_recovery_review(self, p: PreparedPrivateReview) -> PrivatePhaseOutcome:
        saved = self._initial_reviews.get(p.ref.slot_id)
        if (self.conn.info.transaction_status != TransactionStatus.IDLE or saved is None or saved[0] is not p
                or p.preparation_id in self.facts._started):
            raise PrivateNativePending('private_recovery_quality_live_work_required')
        _,work,validation_id,_ = saved
        selector = saved[3]
        if isinstance(selector, IssuedPrivateCommittedPhaseQuality):
            self.progress.select_committed_phase_quality_source(selector)
        elif isinstance(selector, IssuedPrivatePersistencePhaseQuality):
            self.progress.select_persistence_phase_quality_source(selector)
        elif isinstance(selector, IssuedPrivateInitialQualityHandoff):
            self.progress.select_initial_quality_source(selector)
        else:
            self.service._select_initial_recovery_source(self._initial_authors[selector.original.request.candidate_id][1])
        try:
            result = self.facts.run_review(p)
        finally:
            # A source/committed-aux denial occurs BEFORE the original once mark;
            # do not mask it with review_not_started from settlement. Once any
            # real review started, independent UNKNOWN settlement is mandatory.
            if p.preparation_id in self.facts._started:
                with self.conn.transaction():
                    self.facts.settle_review(p)
        with self.conn.transaction(), self.service._fresh_recovery_source(work.task):
            blind_id,review_id = self.facts.persist_review(p,result)
            self._stage(work,'review',subject=str(p.original.artifact_id),result=review_id)
        if (isinstance(selector, (IssuedPrivateInitialQualityHandoff, IssuedPrivatePersistencePhaseQuality, IssuedPrivateCommittedPhaseQuality))
                and self._durable_initial_quality.get(p.ref.slot_id) is selector):
            self._durable_initial_quality.pop(p.ref.slot_id)
        self._initial_reviews.pop(p.ref.slot_id)
        self._review.pop(p.ref.slot_id,None)
        return self._finish_review(work,p,result,validation_id=validation_id,blind_id=blind_id,review_id=review_id,recovery=True)

    def _identity(self, lease: JobLeaseV1, role: str) -> ProviderIdentityV2:
        return ProviderIdentityV2(identity='deepseek.private.persistent.'+lease.job_id.hex+'.'+role,
            provider=self.provider.provider_key,model=self.provider.configured_model,model_version=self.provider.configured_model)

    def _profile(self, spec: FiniteCandidateSpecV1, materials: tuple[PublicMaterialV2,...], *,
                 phase_kind: Literal['author', 'persistence_quality']='author') -> ExecutionParameterProfileV1:
        key=ProfileKeyV1(provider=self.provider.provider_key,model_version=self.provider.configured_model,
            agent_role='native.private.persistent.'+phase_kind+'.'+spec.target_id,item_kind=spec.public_template.kind.value,
            risk_tier='low',difficulty='basic',input_size_bucket='bounded-262144',runtime=spec.blueprint.runtime_profile_id or 'static-exact-v1',
            provider_version='openai-compatible-v1',prompt_version=GENERATION_PROMPT_VERSION if phase_kind=='author' else 'private-durable-persistence-quality-v1',validator_version='finite-native-v1',
            output_size_bucket='bounded-65536',load_bucket='single',complexity_version=spec.target_id)
        row=self.conn.execute('SELECT max(profile_version) AS v FROM tutor_item_supply_parameter_profiles WHERE profile_key_hash=%s',(key.key_hash,)).fetchone()
        if row is None:
            raise PrivateNativePending('private_executor_original_profile_inventory_required')
        values=ParameterValuesV1(connection_timeout_ms=20000,first_token_timeout_ms=100000,stream_idle_timeout_ms=100000,
            request_timeout_ms=100000,parent_deadline_ms=6000000,stage_deadline_ms=6000000,discussion_rounds=2,investigation_rounds=1,revision_rounds=1)
        return ExecutionParameterProfileV1(profile_key=key,version=int(row['v'] or 0)+1,state='frozen',initial=values,current=values,
            last_stable=values,floor=values,ceiling=values,measurement_window_started_at=self.service._guard(),
            change_reason='private_persistent_new_bounded_phase_v1' if phase_kind=='author' else 'private_durable_output_new_phase_v1',trusted_initial_evidence=(materials[0].exact_claims[0].claim_receipt_id,spec.target_definition_hash))

    def _fund(self, root: UUID, task: PersistentPackTaskRef) -> None:
        from app.services.learning.item_supply.private_development_model_accounting import ordinary_private_window_filter
        now=self.service._guard()
        # The SAME canonical PRIVATE root/wallet. Never alter an old cap/window,
        # overlap another root window, filter prior UNKNOWN or borrow517 batches.
        rows=self.conn.execute('SELECT id FROM tutor_item_supply_private_budget_windows WHERE root_id=%s AND window_start<=%s AND window_end>%s'
            + ordinary_private_window_filter(self.conn),
            (root,now,now)).fetchall()
        if rows:
            if len(rows)!=1:
                raise PrivateNativePending('private_executor_original_window_ambiguous')
            return
        end=now+timedelta(seconds=7200)
        caps=ResourceAmounts(requests=64,input_tokens=262144*64,output_tokens=61440*64,candidates=5,revision_rounds=8,investigation_rounds=8)
        for dimension,key in (('system','item-supply'),('provider',self.provider.provider_key),('window','item-supply'),('pool','enhancement')):
            for kind in RESOURCE_KINDS:
                self.budget.register_global_limit(dimension_kind=cast(Literal['system','provider','window','pool'],dimension),dimension_key=key,resource_kind=kind,
                    window_start=now,window_end=end,cap_amount=caps.as_dict()[kind])
        for kind in RESOURCE_KINDS:
            self.budget.register_user_limit(user_id=task.user_id,epoch=task.epoch,resource_kind=kind,
                window_start=now,window_end=end,cap_amount=caps.as_dict()[kind])
        self.conn.execute('INSERT INTO tutor_item_supply_private_budget_windows(user_id,epoch,scope_id,root_id,pool_key,provider_key,window_start,window_end,request_cap,token_cap,resource_cap) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (task.user_id,task.epoch,task.scope_id,root,'enhancement',self.provider.provider_key,now,end,caps.requests,caps.input_tokens+caps.output_tokens,caps.candidates))

    def _phase(self, task: PersistentPackTaskRef, slot: PersistentPackSlotRef, spec: FiniteCandidateSpecV1,
               materials: tuple[PublicMaterialV2,...], parent: UUID | None=None, *, kind: Literal['candidate','fallback_relation']='candidate',
               recovery: IssuedPrivateInitialAuthorRecovery | None=None) -> _PrivateWork:
        self.service._guard()
        if recovery is not None:
            self.service._require_initial_recovery(recovery)
            if recovery.task != task or recovery.slot_id != slot.slot_id or parent is not None or kind != 'candidate':
                raise PrivateNativePending('private_recovery_exact_approved_task_required')
        mapping=self.service.type_owner.resolve_mapping(task.mapping_receipt_id)
        anchors = [e for e in mapping.stored_demands if (e.demand_id, e.scope_id) == (task.demand_id, task.scope_id)]
        stored_assessments = [e for e in mapping.stored_demands if e.slot == 'assessment']
        assessments = [e for e in mapping.pack_request.demands if e.slot == 'assessment']
        if (len(anchors) != 1 or anchors[0].slot not in ('practice', 'assessment')
                or len(stored_assessments) != 1 or len(assessments) != 1):
            raise PrivateNativePending('private_executor_original_assessment_storage_required')
        task_demands = [e for e in mapping.pack_request.demands if e.slot == anchors[0].slot]
        assessment = assessments[0]
        if (len(task_demands) != 1 or task_demands[0].storage_scope_id != task.scope_id
                or assessment.storage_scope_id != task.scope_id or stored_assessments[0].scope_id != task.scope_id
                or any(getattr(task_demands[0].demand, field) != getattr(assessment.demand, field)
                    for field in ('scope', 'blueprint_hash', 'objective_hash', 'policy_version'))):
            raise PrivateNativePending('private_executor_original_assessment_storage_required')
        # Use the actual immutable task demand, whose full assessment contract
        # was compared above. The runtime independently verifies its DB binding.
        demand = task_demands[0].demand
        scope=demand.scope
        obligation=CoverageObligationV1(blueprint_hash=demand.blueprint_hash,scope_hash=scope.scope_hash,
            objective_hash=demand.objective_hash,purpose=scope.purpose.value,runtime_contract_hash=derive_runtime_contract_hash(scope),
            visibility='private',policy_version=demand.policy_version,owner_id=task.user_id)
        from app.services.learning.item_supply.native_type_evidence import NativeTypeEvidenceOwner
        public = self.service.type_owner.public_owner
        cap = None if public is None else NativeTypeEvidenceOwner._source_binding(public)
        # resolve_mapping above fully verified this original attached binding.
        source_deadline = None if cap is None else cap.source_deadline
        # Original runtime uses the bound STORAGE scope hash, not DTO scope hash.
        stored=self.conn.execute('SELECT scope_hash FROM tutor_item_supply_private_scopes WHERE id=%s AND user_id=%s AND epoch=%s',
            (task.scope_id,task.user_id,task.epoch)).fetchone()
        if stored is None:
            raise PrivateNativePending('private_executor_original_scope_missing')
        obligation=checked_model(obligation.model_copy(update={'scope_hash':stored['scope_hash']}),CoverageObligationV1)
        root=self.runtime.ensure_private_root(user_id=task.user_id,epoch=task.epoch,scope_id=task.scope_id,demand_id=task.demand_id,
            obligation=obligation,pool='enhancement',provider_key=self.provider.provider_key)
        if recovery is not None and (root != RECOVERY_ROOT or cap is None or materials != cap.public_materials):
            raise PrivateNativePending('private_recovery_same_canonical_root_materials_required')
        for material in materials:
            self.facts.source_authority.authorize(material)
        if self.development_accounting_enabled is not self.service.development_accounting_enabled:
            raise PrivateNativePending('private_executor_exact_service_accounting_flag_required')
        batch = None
        accounting = None
        if self.development_accounting_enabled:
            from app.services.learning.item_supply.private_development_model_accounting import PrivateDevelopmentModelAccountingOwner
            accounting = PrivateDevelopmentModelAccountingOwner(self.conn, enabled=True)
            now = self.service._guard()
            batch = accounting.prepare_batch(root_id=root, user_id=task.user_id, epoch=task.epoch,
                scope_id=task.scope_id, provider_key=self.provider.provider_key, model=self.provider.configured_model,
                now=now, valid_until=now+timedelta(seconds=7200))
        else:
            self._fund(root,task)
        phase_id=uuid4()
        profile=self._profile(spec,materials)
        now = self.service._guard()
        phase_deadline = source_deadline
        if batch is not None:
            phase_deadline = batch.valid_until if phase_deadline is None else min(phase_deadline, batch.valid_until)
        if phase_deadline is not None:
            # Freeze THIS fresh profile shorter when needed, never extend a
            # source/batch, an old window or historical profile. Leave one request's
            # bound for the original enqueue/claim lock waits.
            remaining_ms = int((phase_deadline-now).total_seconds()*1000)
            deadline_ms = min(profile.last_stable.parent_deadline_ms,
                remaining_ms-profile.last_stable.request_timeout_ms)
            if deadline_ms < profile.last_stable.request_timeout_ms:
                raise PrivateNativePending('private_executor_current_phase_deadline_required')
            if deadline_ms != profile.last_stable.parent_deadline_ms:
                values = checked_model(profile.last_stable.model_copy(update={
                    'parent_deadline_ms': deadline_ms, 'stage_deadline_ms': deadline_ms}), ParameterValuesV1)
                profile = checked_model(profile.model_copy(update={name: values for name in
                    ('initial','current','last_stable','floor','ceiling')}), ExecutionParameterProfileV1)
        job=self.runtime.enqueue(root_id=root,stage_key='private.persistent.phase.'+phase_id.hex,profile=profile,now=now,
            priority=80,aging_seconds=86400,visibility='private',user_id=task.user_id,epoch=task.epoch,scope_id=task.scope_id,
            retry_policy=RetryPolicyV1(max_transient_attempts=1,initial_backoff_ms=1,maximum_backoff_ms=1))
        lease: JobLeaseV1 | None
        if recovery is not None:
            if batch is None:
                raise PrivateNativePending('private_recovery_fresh_development_batch_required')
            lease=self.service.claim_initial_author_recovery(recovery,job_id=job,batch_id=batch.batch_id)
        else:
            lease=self.runtime.claim(root_id=root,lease_owner='private.persistent.phase.'+phase_id.hex,now=self.service._guard(),
                lease_seconds=3600,visibility='private',user_id=task.user_id,epoch=task.epoch)
        if lease is None or lease.job_id!=job:
            raise PrivateNativePending('private_executor_exact_claim_rollback_required')
        if phase_deadline is not None and max(lease.parent_deadline, lease.profile.parent_deadline_at,
                lease.profile.bound_at+timedelta(milliseconds=lease.profile.values.stage_deadline_ms)) > phase_deadline:
            raise PrivateNativePending('private_executor_current_phase_deadline_required')
        if batch is not None and accounting is not None:
            accounting.bind_job(lease=lease, batch_id=batch.batch_id, parent_job_id=None, now=self.service._guard())
        ref=self.service.bind_slot_phase(task_ref=task,slot_id=slot.slot_id,lease=lease,parent_version_id=parent)
        if kind=='candidate':
            self.service.record_wait_window(task_ref=task,lease=lease)
        return _PrivateWork(task,slot,ref,lease,spec,materials)

    def _stage(self, work: _PrivateWork, stage: str, *, subject: str, result: UUID | None=None, started: bool=False,
               recovery: IssuedPrivateInitialAuthorRecovery | None=None) -> None:
        self.facts._guard(work.ref,work.lease)
        # Original journal's unique operation identity serializes competing
        # phases for ONE actual stage subject, not one disposable job/lease.
        key='private.stage.'+work.slot.logical_item_id.hex+'.'+stage+'.'+canonical_hash(subject)
        if recovery is not None:
            self.service._require_initial_recovery(recovery)
            if recovery.task != work.task or recovery.slot_id != work.slot.slot_id or stage != 'author' or subject != 'v1':
                raise PrivateNativePending('private_recovery_exact_author_stage_required')
            key=self.service._initial_author_key(recovery)+'.author'
        if started:
            prior=self.conn.execute("SELECT id FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id=%s AND record_kind='private_status' AND operation_key=%s",
                (work.task.pack_task_id,key+'.started')).fetchone()
            if prior is not None:
                raise PrivateNativePending('private_executor_committed_once_no_paid_replay')
        self.service.core._private_event(work.task,'private_status',dict(schema_version='private_native_stage_v1',
            job_id=str(work.lease.job_id),slot_id=str(work.slot.slot_id),stage=stage,status='started' if started else 'committed',
            subject_hash=canonical_hash(subject),
            receipt_id=None if result is None else str(result)),key=key+('.started' if started else '.result'))

    def _refresh(self, work: _PrivateWork) -> _PrivateWork:
        from dataclasses import replace
        lease=self.runtime.refresh_lease(work.lease,now=self.service._guard())
        return replace(work,lease=lease)

    def run_next_phase(self, task: PersistentPackTaskRef) -> PrivatePhaseOutcome:
        if self.conn.autocommit or self.conn.info.transaction_status!=TransactionStatus.IDLE:
            raise PrivateNativePending('private_executor_original_idle_connection_required')
        handoff = getattr(self,'_durable_initial_quality',{}).get(RECOVERY_SLOT)
        source_scope = (self.service._fresh_recovery_source(task)
            if handoff is not None and self._quality_handoff_task(handoff) == task else nullcontext())
        with self.conn.transaction(), source_scope:
            self.service._guard()
            record=self.service.core._task(task)
            if record.enhancement!='prefer_private':
                raise PrivateNativePending('private_executor_same_task_enhancement_intent_required')
            recovery_row=self.conn.execute('SELECT id FROM '+PRIVATE_JOURNAL+
                " WHERE pack_task_id=%s AND operation_key=%s",(task.pack_task_id,RECOVERY_KEY+'.claim')).fetchone()
            continuation=self.conn.execute('SELECT id FROM '+PRIVATE_JOURNAL+
                " WHERE pack_task_id=%s AND payload_json->>'schema_version'='private_initial_author_continuation_approval_v1' LIMIT 1",
                (task.pack_task_id,)).fetchone()
            recovery_clause=''
            if recovery_row is not None or continuation is not None:
                if continuation is not None:
                    self.service._continuation_receivers()
                    receiver='private_initial_author_continuation_terminal'
                else:
                    self.service._recovery_receivers()
                    receiver='private_initial_author_recovery_terminal'
                terminal=self.conn.execute('SELECT item_supply_internal.'+receiver+'(id) AS status FROM '+
                    PRIVATE_JOURNAL+' WHERE pack_task_id=%s AND operation_key=%s',
                    (task.pack_task_id,RECOVERY_KEY+'.author.started')).fetchone()
                if terminal is None or terminal['status'] not in ('artifact','published','review_failed'):
                    return PrivatePhaseOutcome(task.pack_task_id,'quality_failed' if terminal and terminal['status']=='failure' else 'preparing',
                        reason='private_recovery_author_terminal_or_live_process_required')
                # Only an unfinished initial quality stage needs this process's
                # original work. Completed publication/veto is verified by the
                # receiver; ordinary committed-review adoption remains below.
                if terminal['status'] == 'artifact' and not any(
                        saved[1].task == task and saved[1].slot.slot_id == RECOVERY_SLOT for saved in self._initial_success.values()):
                    if handoff is None or self._quality_handoff_task(handoff) != task:
                        return PrivatePhaseOutcome(task.pack_task_id,'preparing',reason='private_recovery_quality_live_work_required')
                    self._durable_quality_work(handoff)
                recovery_clause=" AND COALESCE(item_supply_internal."+receiver+"(started.id),'') NOT IN ('artifact','published','review_failed')"
            mapping=self.service.type_owner.resolve_mapping(task.mapping_receipt_id)
            if mapping.target_id!='python-kc-binding-v1':
                raise PrivateNativePending('private_executor_original_OS_chain_not_yet_supported')
            from app.services.learning.item_supply.native_supply_service_contracts import NativeSupplyDemandRef
            from app.services.learning.item_supply.native_type_exposure import _protected
            self.service.base_fallback_owner().resolve(task)
            base=self.service.base_service._attempt(NativeSupplyDemandRef(task.demand_id,task.mapping_receipt_id,enhancement='prefer_private'),reserve=True)
            if base.ready is None:
                return PrivatePhaseOutcome(task.pack_task_id,'preparing',reason='original_whole_base_not_retained')
            base_pack=self.service.base_service.type_owner.require_pack(base.ready.capability)
            union=self.service.exposure_owner.snapshot_complete()
            _protected(base_pack,union.exposure)
            unresolved=self.conn.execute("SELECT started.id FROM tutor_item_supply_private_persistent_pack_journal started WHERE started.pack_task_id=%s AND started.record_kind='private_status' AND started.payload_json->>'schema_version'='private_native_stage_v1' AND started.payload_json->>'status'='started' AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal done WHERE done.pack_task_id=started.pack_task_id AND done.record_kind='private_status' AND done.operation_key=replace(started.operation_key,'.started','.result') AND done.payload_json->>'status'='committed')"+recovery_clause+' LIMIT 1',
                (task.pack_task_id,)).fetchone()
            if unresolved is not None:
                raise PrivateNativePending('private_executor_opaque_started_phase_no_paid_replay')
            versions=self.service.core._versions(task)
            if len(versions)!=5 or any(v.published_version_id is None for v in versions.values()):
                return PrivatePhaseOutcome(task.pack_task_id,'preparing',reason='original_whole_base_not_retained')
            repair=self.relation_repair.pending(task)
            if repair is not None:
                # Current finite-v3 fixes public.content. Do not pay an author to
                # disguise clone repair as prose/seed/new-item replacement. A
                # versioned semantic-child compiler/receiver is required first.
                return PrivatePhaseOutcome(task.pack_task_id,'revision_pending',repair.parent_version_id,
                    'same_slot_relation_repair_requires_versioned_semantic_child_contract')
            qualified={UUID(str(r['slot_id'])) for r in self.conn.execute("SELECT DISTINCT slot_id FROM tutor_item_supply_private_native_publications WHERE pack_task_id=%s AND user_id=%s AND epoch=%s AND state='published'",
                (task.pack_task_id,task.user_id,task.epoch)).fetchall()}
            missing=[s for s in record.slots if s.slot_id not in qualified]
            # Author/complete7 plus final4, calibrated from the ORIGINAL frozen
            # request bound. This is prospective remaining work, NOT a fixed
            # business-round ceiling or old producer's expired proof interval.
            calls=4
            for pending in missing:
                calls += 7 if pending.slot_id in self._review else 9 if pending.slot_id in self._failed else 8
            deadline=min(self.service.base_service.type_owner.source_deadline(
                self.service.base_service.type_owner.resolve_content(c.version_id,current=True)) for c in base_pack.selected)
            if (deadline-self.service._guard()).total_seconds() <= calls*100+15:
                return PrivatePhaseOutcome(task.pack_task_id,'not_started',reason='retained_base_current_source_profile_remaining_insufficient')
            slot=next(iter(missing),None)
        if slot is None:
            return self._relations(task,record.slots)
        if slot.slot_id in self._review:
            return self._run_review(slot.slot_id)
        if slot.slot_id in self._failed:
            return self._run_investigation(slot.slot_id)
        if slot.slot_id in self._investigation:
            return self._run_revision(slot.slot_id)
        resumed=self._recover_committed_progress(task,slot,versions[slot.slot].published_version_id)
        if resumed is not None:
            return resumed
        if slot.slot_id in self._failed:
            return self._run_investigation(slot.slot_id)
        if slot.slot_id in self._investigation:
            return self._run_revision(slot.slot_id)
        if slot.slot_id in self._review:
            return self._run_review(slot.slot_id)
        with self.conn.transaction():
            published=versions[slot.slot].published_version_id
            if published is None:
                raise PrivateNativePending('private_executor_actual_current_base_version_required')
            public=self.service.base_service.type_owner.resolve_content(published,current=True)
            original=public.spec
            spec=build_finite_candidate_spec(target_id=original.target_id,variant_id=original.allocation.variant_id,
                seed=original.seed,item_key='private-native.'+slot.logical_item_id.hex,version='v1',
                materials=public.publication.materials,runtime_profile_hash=None,
                scorer_version=original.coverage_blueprint.scope.scorer_version,
                assistance_policy_hash=original.coverage_blueprint.scope.assistance_policy_hash,
                policy_version=original.coverage_blueprint.policy_version,difficulty_profile=original.blueprint.difficulty_profile,
                publication_policy=original.blueprint.publication_policy,public_spec_version=FLEXIBLE_FACTORY_VERSION,
                allocation=original.allocation)
            work=self._phase(task,slot,spec,public.publication.materials)
            prepared=self.service.prepare_generation(ref=work.ref,lease=work.lease,spec=spec,materials=work.materials,
                limits=GenerationLimitsV2(max_input_bytes=262144,max_output_tokens=61440,max_output_bytes=262144),provider=self.provider)
            self._stage(work,'author',subject=work.spec.public_template.version,started=True)
        generated=self.service.run_generation(prepared)
        return self._finish_initial_generation(work,prepared,generated)

    def _finish_initial_generation(self, work: _PrivateWork, prepared: PreparedPrivateSlotGeneration,
                                   generated: GenerationResultV2) -> PrivatePhaseOutcome:
        capture = None
        with self.conn.transaction():
            self.service.settle_generation(prepared,generated)
            if prepared.original.mode == 'live' and generated.state == 'staged':
                capture = self.service.capture_generation_output(prepared,generated)
        # Deliberately outside the settlement TOP: capture failure cannot erase
        # known fees or UNKNOWN reservations by raising through that transaction.
        if capture is not None and capture.status != 'captured':
            return PrivatePhaseOutcome(work.task.pack_task_id,'preparing',reason='private_generation_output_capture_failed')
        with self.conn.transaction():
            artifact=self.service.persist_generation(prepared,generated)
            work=self._refresh(work)
            self._stage(work,'author',subject=work.spec.public_template.version,result=artifact)
        self._review[work.slot.slot_id]=(work,artifact)
        return PrivatePhaseOutcome(work.task.pack_task_id,'review_pending',reason='genuine_private_original_author_committed')

    def _run_review(self, slot_id: UUID) -> PrivatePhaseOutcome:
        previous,artifact=self._review[slot_id]
        handoff = getattr(self,'_durable_initial_quality',{}).get(slot_id)
        if handoff is not None:
            if handoff.artifact_id != artifact or self._quality_handoff_task(handoff) != previous.task:
                raise PrivateNativePending('private_quality_original_executor_handoff_required')
            with self.conn.transaction(), self.service._fresh_recovery_source(previous.task):
                if isinstance(handoff, IssuedPrivateCommittedPhaseQuality):
                    prepared = self.prepare_committed_phase_review(handoff)
                else:
                    prepared = (self.prepare_persistence_phase_review(handoff) if isinstance(handoff, IssuedPrivatePersistencePhaseQuality)
                        else self.prepare_durable_initial_review(handoff))
            return self.run_initial_recovery_review(prepared)
        with self.conn.transaction():
            recovered=self.conn.execute('SELECT id FROM '+PRIVATE_JOURNAL+
                " WHERE pack_task_id=%s AND (operation_key=%s OR payload_json->>'schema_version'='private_initial_author_continuation_claim_v1') AND payload_json->>'job_id'=%s",
                (previous.task.pack_task_id,RECOVERY_KEY+'.claim',str(previous.lease.job_id))).fetchone()
        if recovered is not None:
            live=next((saved for saved in self._initial_success.values() if saved[1].slot.slot_id==slot_id and saved[2]==artifact),None)
            if live is None:
                return PrivatePhaseOutcome(previous.task.pack_task_id,'preparing',reason='private_recovery_quality_live_work_required')
            try:
                with self.conn.transaction(), self.service._fresh_recovery_source(previous.task):
                    prepared=self.prepare_initial_recovery_review(live[0])
            except PrivateNativePending:
                return PrivatePhaseOutcome(previous.task.pack_task_id,'preparing',reason='private_recovery_quality_current_work_required')
            return self.run_initial_recovery_review(prepared)
        with self.conn.transaction():
            work=self._phase(previous.task,previous.slot,previous.spec,previous.materials,previous.ref.parent_version_id)
            from dataclasses import replace
            work=replace(work,lease=self.progress.inherit_generation(ref=work.ref,lease=work.lease,artifact_id=artifact))
            validation_id,_=self.facts.validate(ref=work.ref,lease=work.lease,artifact_id=artifact,spec=work.spec)
            work=self._refresh(work)
            client=BoundedOpenAIReviewClient(self.settings,profile=work.lease.profile)
            solver=JsonBlindSolverV2(client,identity=self._identity(work.lease,'blind_solver'),profile_hash=work.lease.profile.profile_hash,
                timeout_seconds=work.lease.profile.values.request_timeout_ms/1000,max_output_tokens=61440,max_input_bytes=262144,blind_protocol=SINGLE_CHOICE_BLIND_PROTOCOL)
            reviewers=tuple(JsonReviewerV2(BoundedOpenAIReviewClient(self.settings,profile=work.lease.profile),role=role,
                identity=self._identity(work.lease,role.value),profile_hash=work.lease.profile.profile_hash,
                timeout_seconds=work.lease.profile.values.request_timeout_ms/1000,max_output_tokens=61440,max_input_bytes=262144,
                review_protocol='evidenced-v1') for role in REQUIRED_REVIEW_ROLES)
            p=self.facts.prepare_review(ref=work.ref,lease=work.lease,artifact_id=artifact,spec=work.spec,policy=AutonomousEvidencePolicyV3(),
                solver=solver,reviewers=reviewers,resources=ResourceAmounts(requests=7,input_tokens=262144*7,output_tokens=61440*7))
            self._stage(work,'review',subject=str(artifact),started=True)
        try:
            result=self.facts.run_review(p)
        finally:
            with self.conn.transaction():
                self.facts.settle_review(p)
        with self.conn.transaction():
            blind_id,review_id=self.facts.persist_review(p,result)
            self._stage(work,'review',subject=str(artifact),result=review_id)
        self._review.pop(slot_id)
        return self._finish_review(work,p,result,validation_id=validation_id,blind_id=blind_id,review_id=review_id)

    def _finish_review(self, work: _PrivateWork, p: PreparedPrivateReview, result: CompletedPrivateReview,
                       *, validation_id: UUID, blind_id: UUID, review_id: UUID, recovery: bool=False) -> PrivatePhaseOutcome:
        with self.conn.transaction(), (self.service._fresh_recovery_source(work.task) if recovery else nullcontext()):
            from app.services.learning.item_supply.review_deliberation import review_disputes
            from app.services.learning.item_supply.finite_review_descriptor import finite_review_context
            with finite_review_context(p.original.source,spec=p.spec,materials=p.request.materials):
                disputes=review_disputes(result.bundle)
            if disputes:
                self._failed[work.slot.slot_id]=(work,p,result)
                # Normal-loop diagnostic only. No failure/terminal/fallback right.
                existing=self.conn.execute("SELECT id FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id=%s AND operation_key=%s AND record_kind='private_status'",
                    (work.task.pack_task_id,'private.review.veto.'+review_id.hex)).fetchone()
                if existing is None:
                    self.service.core._private_event(work.task,'private_status',dict(schema_version='private_enhancement_review_veto_v1',
                        review_receipt_id=str(review_id)),key='private.review.veto.'+review_id.hex)
                return PrivatePhaseOutcome(work.task.pack_task_id,'revision_pending',version_id=UUID(p.original.binding.version_key),reason='original_findings_need_same_item_substantive_child')
            normal_id=None
            if work.ref.parent_version_id is not None:
                resumed=self.facts._committed_reviews.get(p.preparation_id)
                if resumed is not None:
                    self.progress.restore_child(resumed,self.normal)
                normal_id=self.normal.issue_current_re_admission(p,result,validation_receipt_id=validation_id,blind_receipt_id=blind_id,review_receipt_id=review_id)
            q=self.facts.issue(p,result,validation_receipt_id=validation_id,blind_receipt_id=blind_id,review_receipt_id=review_id,normal_readmission_id=normal_id)
            publication=self.service.publication_owner.publish_internal(q)
        return PrivatePhaseOutcome(work.task.pack_task_id,'published',publication.version_id,'complete_original_private_quality_published')

    def _run_investigation(self, slot_id: UUID) -> PrivatePhaseOutcome:
        old,p,result=self._failed[slot_id]
        with self.conn.transaction():
            work=self._phase(old.task,old.slot,old.spec,old.materials,old.ref.parent_version_id)
            cap=self.progress.issue_review(ref=work.ref,lease=work.lease,review_id=p.preparation_id)
            p,result=self.facts.adopt_committed_review(cap)
            investigation=self.loop.prepare_investigation(p,result,lease=work.lease,identity=self._identity(work.lease,'investigator'))
            self._stage(work,'investigation',subject=str(p.preparation_id),started=True)
        try:
            output=self.loop.run_investigation(investigation)
        finally:
            with self.conn.transaction():
                self.loop.settle_investigation(investigation)
        with self.conn.transaction():
            receipt=self.loop.persist_investigation(investigation,output)
            self._stage(work,'investigation',subject=str(p.preparation_id),result=receipt)
        self._failed.pop(slot_id)
        self._investigation[slot_id]=(work,receipt)
        return PrivatePhaseOutcome(work.task.pack_task_id,'revision_pending',UUID(p.original.binding.version_key),'genuine_specific_investigation_committed')

    def _run_revision(self, slot_id: UUID) -> PrivatePhaseOutcome:
        old,receipt=self._investigation[slot_id]
        investigation,_,parent=self.loop._lineages[receipt]
        parent_source=investigation.original.original.source
        try:
            serial=int(parent_source.public.version.removeprefix('v'))
        except ValueError as exc:
            raise PrivateNativePending('private_executor_actual_version_lineage_required') from exc
        spec=checked_model(old.spec.model_copy(update={'public_template':old.spec.public_template.model_copy(
            update={'version':'v'+str(serial+1)})}),FiniteCandidateSpecV1)
        with self.conn.transaction():
            work=self._phase(old.task,old.slot,spec,old.materials,parent)
            revision=self.normal.prepare_revision(receipt,ref=work.ref,lease=work.lease,spec=spec,provider=self.provider)
            self._stage(work,'revision',subject=work.spec.public_template.version,started=True)
        result=self.normal.run_revision(revision)
        with self.conn.transaction():
            self.normal.settle_revision(revision,result)
        with self.conn.transaction():
            artifact=self.normal.persist_revision(revision,result)
            work=self._refresh(work)
            self._stage(work,'revision',subject=work.spec.public_template.version,result=artifact)
        self._investigation.pop(slot_id)
        self._review[slot_id]=(work,artifact)
        return PrivatePhaseOutcome(work.task.pack_task_id,'review_pending',reason='substantive_child_needs_all_new_validation_blind_six_peer')

    def run_fallback_relation(self, task: PersistentPackTaskRef) -> PrivatePhaseOutcome:
        # New genuine4 only when current PUBLIC base vs actual PRIVATE exposures
        # needs those exact pairs. It does not repair clone by changing a label.
        from app.services.learning.item_supply.type_evidence import assessment_clone
        if self.conn.autocommit or self.conn.info.transaction_status!=TransactionStatus.IDLE:
            raise PrivateNativePending('private_fallback_relation_original_idle_required')
        with self.conn.transaction():
            self.service._guard()
            record=self.service.core._task(task)
            versions=self.service.core._versions(task)
            retained=self.service.base_service._reservation(task.demand_id)
            ids=(tuple(UUID(v) for v in retained['request_json']['candidate_version_ids']) if retained is not None
                else tuple(v.published_version_id for v in versions.values()))
            if len(ids)!=5 or any(v is None for v in ids):
                raise PrivateNativePending('private_fallback_relation_retained_whole_base_required')
            contents=[self.service.base_service.type_owner.resolve_content(v,current=True) for v in ids if v is not None]
            observation=self.service.exposure_owner.snapshot_complete()
            exposed=[e.content for e in observation.exposure.records if e.content.item_handle.startswith('lip:v2:')]
            assessments=[c.content for c in contents if c.spec.allocation.slot=='assessment']
            comparisons=[(a,b) for a in assessments for b in exposed]
            if not comparisons:
                return PrivatePhaseOutcome(task.pack_task_id,'relation_ready',reason='no_private_exposure_extra_pairs')
            if any(assessment_clone(a,b) for a,b in comparisons):
                raise PrivateNativePending('private_fallback_union_clone_retained_base_unavailable')
            candidates=self.conn.execute("SELECT version_id,slot_id FROM tutor_item_supply_private_native_publications WHERE user_id=%s AND epoch=%s AND pack_task_id=%s AND state='published' ORDER BY created_at,id",
                (task.user_id,task.epoch,task.pack_task_id)).fetchall()
            if not candidates:
                raise PrivateNativePending('private_fallback_relation_original_private_anchor_required')
            anchor=self.service.type_owner.query.resolve_content(UUID(str(candidates[0]['version_id'])))
            slot=next(s for s in record.slots if s.slot_id==anchor.quality.ref.slot_id)
            pairs=tuple(sorted({cast(tuple[UUID,UUID],tuple(sorted((a.version_id,b.version_id),key=str))) for a,b in comparisons},key=str))
            all_ids={v for pair in pairs for v in pair}|{anchor.publication.version_id}
            if len(all_ids)>16 or len(pairs)>120:
                raise PrivateNativePending('private_fallback_relation_full_inventory_bound')
            # Quality receiver stores a genuine PRIVATE source anchor first, not
            # a PUBLIC version falsely inserted into PRIVATE evidence/FKs.
            relation_ids=(anchor.publication.version_id,*sorted(all_ids-{anchor.publication.version_id},key=str))
            work=self._phase(task,slot,anchor.quality.spec,anchor.quality.request.materials,
                anchor.quality.ref.parent_version_id,kind='fallback_relation')
            identities={cast(RelationshipRoleV2,role):self._identity(work.lease,'fallback.relation.'+role) for role in ('curriculum','technical','ambiguity','adversarial')}
            producer=PrivateNativeRelationReviewOwner(self.facts,self.service.type_owner,identities=identities,
                enabled=self.service.enabled,exposure_owner=self.service.exposure_owner)
            p=producer.prepare(ref=work.ref,lease=work.lease,version_ids=relation_ids,pairs=pairs,exposure_snapshot_id=observation.snapshot_id)
            self._stage(work,'fallback_relation',subject=canonical_hash(p.payload),started=True)
        try:
            result=producer.run(p)
        finally:
            with self.conn.transaction():
                producer.settle(p)
        with self.conn.transaction():
            receipt=producer.persist(p,result)
            self._stage(work,'fallback_relation',subject=canonical_hash(p.payload),result=receipt)
        if any(j.conclusion!='nonredundant' for r in result.reports for j in r.judgments):
            return PrivatePhaseOutcome(task.pack_task_id,'quality_failed',reason='genuine_fallback_relation_conflict')
        return PrivatePhaseOutcome(task.pack_task_id,'relation_ready',reason='genuine_public_base_private_exposure_relation')

    def _relations(self, task: PersistentPackTaskRef, slots: tuple[PersistentPackSlotRef,...]) -> PrivatePhaseOutcome:
        from app.services.learning.item_supply.type_evidence import assessment_clone
        with self.conn.transaction():
            self.service._guard()
            rows=self.conn.execute("SELECT DISTINCT ON(slot_id) version_id,slot_id FROM tutor_item_supply_private_native_publications WHERE pack_task_id=%s AND user_id=%s AND epoch=%s AND state='published' ORDER BY slot_id,created_at DESC,id DESC",
                (task.pack_task_id,task.user_id,task.epoch)).fetchall()
            selected=tuple(UUID(str(r['version_id'])) for r in rows)
            if len(selected)!=5:
                raise PrivateNativePending('private_executor_exact_five_publications_required')
            contents={v:self.service.type_owner.query.resolve_content(v) for v in selected}
            observation=self.service.exposure_owner.snapshot_complete()
            current=self.conn.execute("SELECT id FROM tutor_item_supply_private_native_quality_evidence WHERE user_id=%s AND epoch=%s AND pack_task_id=%s AND kind='relation' AND valid_until>clock_timestamp() ORDER BY checked_at DESC,id LIMIT 16",
                (task.user_id,task.epoch,task.pack_task_id)).fetchall()
            if current:
                try:
                    cap=self.service.type_owner.resolve_pack(task.mapping_receipt_id,selected,observation.snapshot_id,tuple(UUID(str(r['id'])) for r in current))
                    self.service.type_owner.require_pack(cap)
                    return PrivatePhaseOutcome(task.pack_task_id,'relation_ready',reason='current_whole_private_pack_reused')
                except PrivateNativePending:
                    pass  # Never readiness; only concrete fresh preparation below.
            assessments=[c.content for c in contents.values() if c.quality.ref.slot=='assessment']
            training=[c.content for c in contents.values() if c.quality.ref.slot!='assessment']
            comparisons=[(assessments[0],assessments[1])]+[(a,t) for a in assessments for t in training]
            comparisons += [(a,e.content) for a in assessments for e in observation.exposure.records]
            clone=next(((a,b) for a,b in comparisons if assessment_clone(a,b)),None)
            if clone is not None:
                a,b=clone
                parent=next(c for c in contents.values() if c.quality.ref.slot=='assessment' and c.content.version_id in (a.version_id,b.version_id))
                self.relation_repair.request(task,parent_version_id=parent.publication.version_id,
                    left_version_id=a.version_id,right_version_id=b.version_id)
                return PrivatePhaseOutcome(task.pack_task_id,'revision_pending',parent.publication.version_id,
                    'actual_clone_bound_to_same_assessment_slot_substantive_repair')
            pairs=tuple(sorted({cast(tuple[UUID,UUID],tuple(sorted((a.version_id,b.version_id),key=str))) for a,b in comparisons},key=str))
            versions=tuple(sorted({v for pair in pairs for v in pair},key=str))
            if len(versions)>16 or len(pairs)>120:
                raise PrivateNativePending('private_executor_relation_current_inventory_bound')
            anchor=next(c for c in contents.values() if c.quality.ref.slot=='assessment')
            versions=(anchor.publication.version_id,*[v for v in versions if v!=anchor.publication.version_id])
            slot=next(s for s in slots if s.slot_id==anchor.quality.ref.slot_id)
            work=self._phase(task,slot,anchor.quality.spec,anchor.quality.request.materials,anchor.quality.ref.parent_version_id)
            identities={cast(RelationshipRoleV2,role):self._identity(work.lease,'relation.'+role) for role in ('curriculum','technical','ambiguity','adversarial')}
            producer=PrivateNativeRelationReviewOwner(self.facts,self.service.type_owner,identities=identities,
                enabled=self.service.enabled,exposure_owner=self.service.exposure_owner)
            p=producer.prepare(ref=work.ref,lease=work.lease,version_ids=versions,pairs=pairs,exposure_snapshot_id=observation.snapshot_id)
            self._stage(work,'relation',subject=canonical_hash(p.payload),started=True)
        try:
            result=producer.run(p)
        finally:
            with self.conn.transaction():
                producer.settle(p)
        with self.conn.transaction():
            receipt=producer.persist(p,result)
            self._stage(work,'relation',subject=canonical_hash(p.payload),result=receipt)
        bad=next((j for r in result.reports for j in r.judgments if j.conclusion!='nonredundant'),None)
        if bad is not None:
            pair=next(pair for pair in p.payload['pairs'] if pair['binding_hash']==bad.binding_hash)
            left,right=UUID(pair['left_version_id']),UUID(pair['right_version_id'])
            parent=next(c for c in contents.values() if c.quality.ref.slot=='assessment' and c.content.version_id in (left,right))
            with self.conn.transaction():
                self.relation_repair.request(task,parent_version_id=parent.publication.version_id,
                    left_version_id=left,right_version_id=right,relation_receipt_id=receipt)
            return PrivatePhaseOutcome(task.pack_task_id,'revision_pending',parent.publication.version_id,
                'genuine_four_role_failure_bound_to_same_slot_repair')
        with self.conn.transaction():
            fresh=self.service.exposure_owner.snapshot_complete()
            cap=self.service.type_owner.resolve_pack(task.mapping_receipt_id,selected,fresh.snapshot_id,(receipt,))
            self.service.type_owner.require_pack(cap)
        return PrivatePhaseOutcome(task.pack_task_id,'relation_ready',reason='genuine_four_role_whole_private_current_pack')

    def _recover_committed_progress(self, task: PersistentPackTaskRef, slot: PersistentPackSlotRef,
                                    retained_public: UUID | None) -> PrivatePhaseOutcome | None:
        import json
        from app.services.learning.item_bank.contracts import LearningItemSourceV1
        from app.services.learning.item_supply.generation_contracts import GenerationRequestV2
        from app.services.learning.item_supply.private_native_admission_facts import QUALITY_TABLE
        with self.conn.transaction():
            self.service._guard()
            phase_handoff = getattr(self,'_durable_initial_quality',{}).get(slot.slot_id)
            if isinstance(phase_handoff, (IssuedPrivatePersistencePhaseQuality, IssuedPrivateCommittedPhaseQuality)):
                if self._quality_handoff_task(phase_handoff) != task:
                    raise PrivateNativePending('private_quality_original_executor_handoff_required')
                with self.service._fresh_recovery_source(task):
                    phase_work = self._durable_quality_work(phase_handoff)
                self._review[slot.slot_id] = (phase_work,phase_handoff.artifact_id)
                return PrivatePhaseOutcome(task.pack_task_id,'review_pending',reason='original_private_persistence_phase_quality_handoff')
            stage=self.conn.execute("SELECT operation_key,payload_json FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id=%s AND user_id=%s AND epoch=%s AND record_kind='private_status' AND payload_json->>'schema_version'='private_native_stage_v1' AND payload_json->>'slot_id'=%s AND payload_json->>'status'='committed' ORDER BY created_at DESC,id DESC LIMIT 1",
                (task.pack_task_id,task.user_id,task.epoch,str(slot.slot_id))).fetchone()
            if stage is None:
                return None
            event=stage['payload_json']
            receipt=UUID(event['receipt_id'])
            if (stage['operation_key'] == RECOVERY_KEY+'.author.result'
                    or (stage['operation_key'].startswith(CONTINUATION_KEY+'.') and stage['operation_key'].endswith('.author.result'))):
                handoff = getattr(self,'_durable_initial_quality',{}).get(slot.slot_id)
                if isinstance(handoff, IssuedPrivateInitialQualityHandoff):
                    if (handoff.artifact_id != receipt or handoff.persistence.task != task
                            or str(handoff.persistence.original_lease.job_id) != event['job_id']):
                        raise PrivateNativePending('private_quality_original_executor_handoff_required')
                    with self.service._fresh_recovery_source(task):
                        work = self._durable_quality_work(handoff)
                    self._review[slot.slot_id] = (work,receipt)
                    return PrivatePhaseOutcome(task.pack_task_id,'review_pending',reason='original_private_durable_quality_handoff')
                live=next((saved for saved in self._initial_success.values() if saved[1].task == task
                    and saved[1].slot.slot_id == slot.slot_id and saved[2] == receipt
                    and str(saved[1].lease.job_id) == event['job_id']),None)
                if live is not None:
                    self._review[slot.slot_id]=(live[1],receipt)
                    return PrivatePhaseOutcome(task.pack_task_id,'review_pending',reason='original_private_initial_live_work_retained')
                return PrivatePhaseOutcome(task.pack_task_id,'preparing',reason='private_recovery_quality_live_work_required')
            if event['stage'] in ('author','revision'):
                artifact=self.conn.execute("SELECT id,source_json,request_json FROM tutor_item_supply_private_generation_artifacts WHERE id=%s AND user_id=%s AND epoch=%s AND scope_id=%s AND job_id=%s AND mode='live' AND xmin::text::bigint<>(txid_current() %% 4294967296)",
                    (receipt,task.user_id,task.epoch,task.scope_id,event['job_id'])).fetchone()
                phase=self.conn.execute("SELECT payload_json FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id=%s AND user_id=%s AND epoch=%s AND record_kind='phase' AND payload_json->>'job_id'=%s AND payload_json->>'slot_id'=%s",
                    (task.pack_task_id,task.user_id,task.epoch,event['job_id'],str(slot.slot_id))).fetchone()
                if artifact is None or phase is None or retained_public is None:
                    raise PrivateNativePending('private_resume_exact_committed_generation_required')
                ref=checked_model(phase['payload_json']['ref'],PrivateSlotRef)
                source=LearningItemSourceV1.model_validate_json(json.dumps(artifact['source_json']))
                request=GenerationRequestV2.model_validate_json(json.dumps(artifact['request_json']))
                base=self.service.base_service.type_owner.resolve_content(retained_public,current=True)
                spec=build_finite_candidate_spec(target_id=base.spec.target_id,variant_id=base.spec.allocation.variant_id,
                    seed=base.spec.seed,item_key=source.public.item_key,version=source.public.version,materials=request.materials,
                    runtime_profile_hash=None,scorer_version=base.spec.coverage_blueprint.scope.scorer_version,
                    assistance_policy_hash=base.spec.coverage_blueprint.scope.assistance_policy_hash,
                    policy_version=base.spec.coverage_blueprint.policy_version,difficulty_profile=source.blueprint.difficulty_profile,
                    publication_policy=source.blueprint.publication_policy,public_spec_version=source.blueprint.version,allocation=base.spec.allocation)
                from app.services.learning.item_supply.finite_candidate_factory import check_finite_public_spec
                check_finite_public_spec(source.public,spec)
                work=self._phase(task,slot,spec,request.materials,ref.parent_version_id)
                self.facts._artifact(work.ref,work.lease,UUID(str(artifact['id'])))
                self._review[slot.slot_id]=(work,receipt)
                return PrivatePhaseOutcome(task.pack_task_id,'review_pending',reason='fresh_phase_resumed_original_committed_generation')
            if event['stage'] not in ('review','investigation'):
                raise PrivateNativePending('private_resume_stage_requires_distinct_concrete_issuer')
            row=self.conn.execute('SELECT payload_json FROM '+QUALITY_TABLE+
                ' WHERE id=%s AND user_id=%s AND epoch=%s AND scope_id=%s AND pack_task_id=%s AND slot_id=%s AND job_id=%s AND kind=%s',
                (receipt,task.user_id,task.epoch,task.scope_id,task.pack_task_id,slot.slot_id,event['job_id'],event['stage'])).fetchone()
            if row is None:
                raise PrivateNativePending('private_resume_exact_committed_stage_receipt_required')
            review_id=receipt if event['stage']=='review' else UUID(row['payload_json']['parent_review_id'])
            peer=self.conn.execute('SELECT payload_json FROM '+QUALITY_TABLE+" WHERE id=%s AND kind='review' AND user_id=%s AND epoch=%s",
                (review_id,task.user_id,task.epoch)).fetchone()
            if peer is None:
                raise PrivateNativePending('private_resume_complete_original_parent_review_required')
            spec=checked_model(peer['payload_json']['spec'],FiniteCandidateSpecV1)
            old_ref=checked_model(peer['payload_json']['ref'],PrivateSlotRef)
            artifact=self.conn.execute("SELECT request_json FROM tutor_item_supply_private_generation_artifacts WHERE id=%s AND user_id=%s AND epoch=%s AND mode='live'",
                (peer['payload_json']['artifact_id'],task.user_id,task.epoch)).fetchone()
            if artifact is None:
                raise PrivateNativePending('private_resume_exact_parent_artifact_required')
            request=GenerationRequestV2.model_validate_json(json.dumps(artifact['request_json']))
            work=self._phase(task,slot,spec,request.materials,old_ref.parent_version_id)
            cap=self.progress.issue_review(ref=work.ref,lease=work.lease,review_id=review_id)
            p,result=self.facts.adopt_committed_review(cap)
            if event['stage']=='investigation':
                self.progress.restore_investigation(cap,receipt_id=receipt,loop=self.loop)
                self._investigation[slot.slot_id]=(work,receipt)
                return PrivatePhaseOutcome(task.pack_task_id,'revision_pending',reason='fresh_phase_resumed_original_committed_investigation')
        return self._finish_review(work,p,result,validation_id=cap.validation_id,blind_id=cap.blind_id,review_id=review_id)

