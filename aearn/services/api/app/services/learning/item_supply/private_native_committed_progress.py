"""Fresh concrete PRIVATE phase continuation over committed immutable evidence DATA.

Never reinstates an old lease, paid call or serialized capability. The SQL527
receiver independently checks the original producer history and current phase.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb
from psycopg.pq import TransactionStatus

from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash
from app.services.learning.item_supply.diagnostic_policy import parse_bundle, policy_for_hash
from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1
from app.services.learning.item_supply.finite_candidate_validation import prepare_finite_candidate_validation
from app.services.learning.item_supply.generation_contracts import GenerationRequestV2, GenerationResultV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.persistent_pack_contracts import PersistentPackTaskRef
from app.services.learning.item_supply.pipeline import PreparedGeneration, PreparedReview
from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending, PrivateSlotRef
from app.services.learning.item_supply.private_native_admission_facts import (
    QUALITY_TABLE, CompletedPrivateReview, PreparedPrivateReview, PrivateNativeAdmissionFactsOwner,
)
from app.services.learning.item_supply.finite_task_ambiguity import FiniteAmbiguityReceiptV1
from app.services.learning.item_supply.storage_contracts import checked_model

if TYPE_CHECKING:
    from app.services.learning.item_supply.private_enhancement_service import PrivateEnhancementService
    from app.services.learning.item_supply.private_generation_persistence_phase import IssuedPrivateGenerationPersistencePhase
    from app.services.learning.item_supply.private_generation_persistence import IssuedPrivateGenerationPersistence
    from app.services.learning.item_supply.persistent_pack_current_source import IssuedCurrentPackSourceBinding


@dataclass(frozen=True)
class IssuedPrivateCommittedReview:
    owner: Any
    resume_id: UUID
    ref: PrivateSlotRef
    lease: JobLeaseV1
    prepared: PreparedPrivateReview
    result: CompletedPrivateReview
    validation_id: UUID
    blind_id: UUID
    seal: str


@dataclass(frozen=True, repr=False)
class IssuedPrivateInitialQualityHandoff:
    owner: PrivateNativeCommittedProgressOwner
    handoff_id: UUID
    persistence: IssuedPrivateGenerationPersistence
    artifact_id: UUID
    artifact_hash: str
    spec: FiniteCandidateSpecV1


@dataclass(frozen=True, repr=False)
class IssuedPrivatePersistencePhaseQuality:
    owner: PrivateNativeCommittedProgressOwner
    handoff_id: UUID
    persistence: IssuedPrivateGenerationPersistencePhase
    artifact_id: UUID
    artifact_hash: str
    spec: FiniteCandidateSpecV1


COMMITTED_COMPLETION_ID = UUID('db9b6e57-21c0-4e19-8e99-01ca1ddfa871')
COMMITTED_COMPLETION_HASH = '96caf0f71a8b97e7bcd0066e22f5fdb58f8082bda1f754cf9372321ea033b972'
COMMITTED_BINDING_ID = UUID('755b5f67-bee2-47c9-bc2f-ec7790b97f4d')
COMMITTED_WRITER_ID = UUID('5dfe6762-b974-4ec4-a36c-2af7d3d342b0')
COMMITTED_ARTIFACT_ID = UUID('c8057dcb-a110-45fa-ab0b-46cd91c99191')
COMMITTED_VERSION_ID = UUID('192c9f88-afa4-4470-b47e-9a966695430c')
COMMITTED_CANDIDATE_ID = UUID('05e16768-e4c5-4a6d-80db-7038af56ec2b')
COMMITTED_CHECKPOINT_ID = UUID('60be139b-058f-4db7-aa9d-f68a332f89eb')
COMMITTED_OUTPUT_TOP = '269096'


@dataclass(frozen=True, repr=False)
class IssuedPrivateCommittedPhaseQuality:
    owner: PrivateNativeCommittedProgressOwner
    service: PrivateEnhancementService
    handoff_id: UUID
    task: PersistentPackTaskRef
    ref: PrivateSlotRef
    binding_id: UUID
    binding_hash: str
    completion_id: UUID
    completion_hash: str
    output_hash: str
    artifact_id: UUID
    artifact_hash: str
    version_id: UUID
    writer_lease: JobLeaseV1
    request: GenerationRequestV2
    result: GenerationResultV2
    spec: FiniteCandidateSpecV1


class PrivateNativeCommittedProgressOwner:
    def __init__(self, facts_owner: PrivateNativeAdmissionFactsOwner) -> None:
        if type(facts_owner) is not PrivateNativeAdmissionFactsOwner:
            raise PrivateNativePending('private_resume_original_facts_owner_required')
        self.facts_owner,self.conn=facts_owner,facts_owner.conn
        self._issued: dict[UUID, IssuedPrivateCommittedReview] = {}
        self._initial_quality: dict[UUID,tuple[IssuedPrivateInitialQualityHandoff,str]] = {}
        self._initial_quality_sources: dict[UUID,IssuedCurrentPackSourceBinding] = {}
        self._phase_quality: dict[UUID,tuple[IssuedPrivatePersistencePhaseQuality,str]] = {}
        self._phase_quality_sources: dict[UUID,IssuedCurrentPackSourceBinding] = {}
        self._committed_quality: dict[UUID,tuple[IssuedPrivateCommittedPhaseQuality,str,PrivateEnhancementService]] = {}
        self._committed_quality_sources: dict[UUID,IssuedCurrentPackSourceBinding] = {}

    def _committed_phase_guard(self, service: PrivateEnhancementService) -> str:
        from app.services.learning.item_supply.private_enhancement_service import PrivateEnhancementService
        if (type(service) is not PrivateEnhancementService or service.executor().progress is not self
                or service.facts_owner is not self.facts_owner or service.conn is not self.conn
                or self.facts_owner.conn is not self.conn or self.facts_owner.pipeline.conn is not self.conn
                or service.core.conn is not self.conn or self.facts_owner.settings is not service.settings
                or self.facts_owner.source_authority.connection is not self.conn):
            raise PrivateNativePending('private_committed_quality_original_owners_required')
        if self.conn.autocommit or self.conn.info.transaction_status != TransactionStatus.INTRANS:
            raise PrivateNativePending('private_committed_quality_caller_top_required')
        service._guard()
        service._generation_output_ready()
        ready = self.conn.execute('SELECT item_supply_internal.private_generation_persistence_phase_ready() AS ready').fetchone()
        row = self.conn.execute("SELECT pg_current_xact_id()::text AS top_xid, current_setting('transaction_isolation') AS isolation, current_setting('transaction_read_only') AS read_only").fetchone()
        if ready is None or ready['ready'] is not True or row is None or row['isolation'] != 'read committed' or row['read_only'] != 'off':
            raise PrivateNativePending('private_committed_quality_receivers_top_required')
        return str(row['top_xid'])

    @staticmethod
    def _committed_journal(row: dict[str, Any], task: PersistentPackTaskRef, *, key: str, keys: frozenset[str]) -> dict[str, Any]:
        body = row['payload_json']
        if (set(body) != keys or row['operation_key'] != key or row['record_kind'] != 'private_status'
                or (row['pack_task_id'],row['user_id'],row['epoch'],row['scope_id'],row['intent_hash'])
                != (task.pack_task_id,task.user_id,task.epoch,task.scope_id,task.intent_hash)
                or row['payload_hash'] != canonical_hash(body)):
            raise PrivateNativePending('private_committed_quality_exact_journal_required')
        return body

    def _committed_phase_data(self, service: PrivateEnhancementService, task: PersistentPackTaskRef) -> tuple[dict[str, Any], datetime]:
        # Only immutable constants/key sets are shared with C18; no C18 owner or
        # persistence capability is constructed, invoked or registered here.
        from app.services.learning.item_supply.private_generation_persistence_phase import BINDING_KEYS, COMPLETION_KEYS, PHASE_KEY, PREFIX
        from app.services.learning.item_supply.private_generation_persistence import OUTPUT_ID, PREPARATION_ID, JOB_ID
        from app.services.learning.item_supply.private_enhancement_service import (
            PRIVATE_JOURNAL, RECOVERY_TASK, RECOVERY_USER, RECOVERY_SCOPE, RECOVERY_MAPPING, RECOVERY_SLOT, RECOVERY_BUSINESS, RECOVERY_ROOT,
        )
        from app.services.learning.item_supply.private_development_model_accounting import accounting_batch_for_lease
        task = checked_model(task,PersistentPackTaskRef)
        if (task.pack_task_id,task.user_id,task.epoch,task.scope_id,task.mapping_receipt_id) != (RECOVERY_TASK,RECOVERY_USER,1,RECOVERY_SCOPE,RECOVERY_MAPPING):
            raise PrivateNativePending('private_committed_quality_fixed_task_required')
        top = self._committed_phase_guard(service)
        actual = service._recovery_source(task)
        origin = actual.origin_id()
        bindings = self.conn.execute('SELECT bound.* FROM '+PREFIX+'bound(%s,%s) AS bound',(COMMITTED_BINDING_ID,origin)).fetchall()
        completions = self.conn.execute('SELECT completed.* FROM '+PREFIX+'committed(%s,%s) AS completed',(COMMITTED_BINDING_ID,origin)).fetchall()
        if len(bindings) != 1 or len(completions) != 1:
            raise PrivateNativePending('private_committed_quality_exact_completion_required')
        binding,completion = bindings[0],completions[0]
        b = self._committed_journal(binding,task,key=PHASE_KEY,keys=BINDING_KEYS)
        c = self._committed_journal(completion,task,key=PHASE_KEY+'.complete',keys=COMPLETION_KEYS)
        if (binding['id'] != COMMITTED_BINDING_ID or completion['id'] != COMMITTED_COMPLETION_ID
                or completion['payload_hash'] != COMMITTED_COMPLETION_HASH
                or b['schema_version'] != 'private_generation_persistence_phase_v1'
                or c['schema_version'] != 'private_generation_persistence_complete_v1'
                or c['completed_top_xid'] != COMMITTED_OUTPUT_TOP or top in (b['bound_top_xid'],c['completed_top_xid'])
                or b['bound_top_xid'] == c['completed_top_xid']
                or any(c[key] != str(value) for key,value in dict(binding_id=COMMITTED_BINDING_ID,output_id=OUTPUT_ID,
                    writer_job_id=COMMITTED_WRITER_ID,artifact_id=COMMITTED_ARTIFACT_ID,version_id=COMMITTED_VERSION_ID,
                    candidate_id=COMMITTED_CANDIDATE_ID,checkpoint_id=COMMITTED_CHECKPOINT_ID).items())):
            raise PrivateNativePending('private_committed_quality_fixed_prior_completion_required')
        output = self.conn.execute('SELECT * FROM '+PRIVATE_JOURNAL+
            " WHERE pack_task_id=%s AND user_id=%s AND epoch=1 AND scope_id=%s AND record_kind='private_status' AND operation_key=%s FOR SHARE",
            (task.pack_task_id,task.user_id,task.scope_id,'private.generation.output.'+PREPARATION_ID.hex)).fetchone()
        if (output is None or output['id'] != OUTPUT_ID or output['payload_hash'] != canonical_hash(output['payload_json'])
                or output['payload_hash'] != b['output_hash'] or output['payload_json']['schema_version'] != 'private_generation_output_v1'
                or output['payload_json']['preparation_id'] != str(PREPARATION_ID)):
            raise PrivateNativePending('private_committed_quality_original_output_required')
        historical = output['payload_json']
        capture = historical['capture']
        accepted = self.conn.execute('SELECT item_supply_internal.private_generation_output_committed(%s,%s) AS id',
            (PREPARATION_ID,Jsonb(capture))).fetchone()
        if accepted is None or accepted['id'] != OUTPUT_ID:
            raise PrivateNativePending('private_committed_quality_original_output_required')
        ctx = capture['context']
        ref = PrivateSlotRef.model_validate_json(json.dumps(ctx['ref']))
        request = GenerationRequestV2.model_validate_json(json.dumps(ctx['request']))
        result = GenerationResultV2.model_validate_json(json.dumps(capture['result']))
        generation = JobLeaseV1.model_validate_json(json.dumps(ctx['lease']))  # Historical DATA only.
        frozen = JobLeaseV1.model_validate_json(json.dumps(b['lease']))
        record = service.core._task(task)
        if (record.ref != task or record.enhancement != 'prefer_private'
                or not any((s.slot_id,s.logical_item_id,s.slot)==(RECOVERY_SLOT,RECOVERY_BUSINESS,'practice-1') for s in record.slots)
                or (ref.pack_task_id,ref.user_id,ref.epoch,ref.scope_id,ref.mapping_receipt_id,ref.slot_id,ref.business_item_id,ref.root_id,ref.slot,ref.parent_version_id)
                != (RECOVERY_TASK,RECOVERY_USER,1,RECOVERY_SCOPE,RECOVERY_MAPPING,RECOVERY_SLOT,RECOVERY_BUSINESS,RECOVERY_ROOT,'practice',None)
                or b['ref'] != ctx['ref'] or b['output_id'] != str(OUTPUT_ID) or b['preparation_id'] != str(PREPARATION_ID)
                or b['generation_job_id'] != str(JOB_ID) or b['writer_job_id'] != str(COMMITTED_WRITER_ID)
                or any(b['original_'+key] != historical[key] for key in ('binding_id','started_id','consumed_id','settlement_id'))
                or b['generation_request_hash'] != canonical_hash(ctx['request']) or b['generation_profile_hash'] != generation.profile.profile_hash
                or generation.job_id != JOB_ID or request.candidate_id != PREPARATION_ID or request.profile != generation.profile
                or request.item_key != 'private-native.'+RECOVERY_BUSINESS.hex or request.version != 'v1'
                or ctx['scope_id'] != str(ref.scope_id) or ctx['attempt_bound'] != 1 or ctx['mode'] != 'live'
                or result.state != 'staged' or result.source is None or result.receipt is None
                or frozen.job_id != COMMITTED_WRITER_ID or frozen.generation != 1 or frozen.state_version != 2):
            raise PrivateNativePending('private_committed_quality_original_data_required')
        source,receipt = result.source,result.receipt
        if (request.model_dump(mode='json') != ctx['request'] or result.model_dump(mode='json') != capture['result']
                or source.blueprint != request.blueprint or receipt.candidate_id != request.candidate_id
                or receipt.scope_hash != request.scope_hash or receipt.source_hash != source.source_hash or receipt.content_hash != source.content_hash
                or [r.model_dump(mode='json') for r in receipt.sources] != ctx['sources']
                or receipt.provider.mode != 'provider' or receipt.provider.usage.state != 'known'
                or ctx['producer_binding'] != [receipt.provider.provider,receipt.provider.configured_model]):
            raise PrivateNativePending('private_committed_quality_original_data_required')
        pipeline = self.facts_owner.pipeline
        lease = pipeline.runtime.refresh_lease(frozen,now=service._guard())
        if (lease.model_dump(exclude={'state_version'}) != frozen.model_dump(exclude={'state_version'}) or lease.state_version < 3
                or lease.expires_at != datetime.fromisoformat('2026-10-16T13:38:12.081065+08:00')):
            raise PrivateNativePending('private_committed_quality_exact_current_writer_required')
        now = self.facts_owner._guard(ref,lease)
        control = pipeline.runtime._control(lease,now=now)
        batch = accounting_batch_for_lease(self.conn,lease,now=now)
        if (control['attempt_count'] != 1 or batch is None or str(batch['batch_id']) != b['batch_id']
                or list(pipeline._provider_binding(lease,receipt.provider.provider,receipt.provider.configured_model)) != ctx['producer_binding']):
            raise PrivateNativePending('private_committed_quality_current_accounting_required')
        for material,expected in zip(request.materials,receipt.sources,strict=True):
            self.facts_owner.source_authority.assert_current(material,expected)
        current = self.conn.execute('SELECT item_supply_internal.private_native_source_current(%s) AS ok',
            (Jsonb(dict(ref=ref.model_dump(mode='json'),request=request.model_dump(mode='json'),
                source_receipts=[r.model_dump(mode='json') for r in receipt.sources])),)).fetchone()
        if current is None or current['ok'] is not True:
            raise PrivateNativePending('private_committed_quality_current_source_required')
        artifact = self.conn.execute('SELECT a.*,c.candidate_key AS storage_key,v.version AS storage_version,v.public_json,v.private_json '
            'FROM tutor_item_supply_private_generation_artifacts a JOIN tutor_item_supply_private_candidates c ON c.id=a.candidate_id '
            'JOIN tutor_item_supply_private_versions v ON v.id=a.version_id AND v.candidate_id=c.id '
            'WHERE a.id=%s AND a.job_id=%s AND a.lease_generation=1 AND a.user_id=%s AND a.epoch=1 AND a.scope_id=%s FOR SHARE OF a,c,v',
            (COMMITTED_ARTIFACT_ID,COMMITTED_WRITER_ID,task.user_id,task.scope_id)).fetchone()
        checkpoint = self.conn.execute('SELECT id,stage,attempt,status,lease_generation,receipt_hash,safe_reason FROM tutor_item_supply_private_checkpoints '
            "WHERE job_id=%s AND user_id=%s AND epoch=1 AND scope_id=%s AND stage='generating' AND attempt=1",
            (COMMITTED_WRITER_ID,task.user_id,task.scope_id)).fetchone()
        digest = canonical_hash(dict(source=source.model_dump(mode='json'),receipt=receipt.model_dump(mode='json')))
        if (artifact is None or checkpoint is None or artifact['id'] != COMMITTED_ARTIFACT_ID or artifact['job_id'] != COMMITTED_WRITER_ID
                or artifact['candidate_id'] != COMMITTED_CANDIDATE_ID or artifact['version_id'] != COMMITTED_VERSION_ID
                or artifact['mode'] != 'live' or artifact['artifact_key'] != 'generation.'+PREPARATION_ID.hex
                or artifact['artifact_hash'] != digest or c['artifact_hash'] != digest
                or artifact['source_hash'] != source.source_hash or artifact['content_hash'] != source.content_hash
                or artifact['request_json'] != ctx['request'] or artifact['source_json'] != capture['result']['source']
                or artifact['receipt_json'] != capture['result']['receipt'] or artifact['storage_key'] != 'private.native.'+RECOVERY_BUSINESS.hex
                or artifact['storage_version'] != 1 or artifact['public_json'] != source.public.model_dump(mode='json')
                or artifact['private_json'] != source.private.model_dump(mode='json')
                or checkpoint != dict(id=COMMITTED_CHECKPOINT_ID,stage='generating',attempt=1,status='completed',
                    lease_generation=1,receipt_hash=digest,safe_reason='candidate_staged')):
            raise PrivateNativePending('private_committed_quality_exact_bundle_required')
        deadline = min(lease.expires_at,lease.parent_deadline,batch['valid_until'],actual.source_deadline,
            datetime.fromisoformat(b['valid_until']),lease.profile.bound_at+timedelta(milliseconds=lease.profile.values.stage_deadline_ms))
        actual.require()
        if max(self.facts_owner._guard(ref,lease),service._guard()) >= deadline:
            raise PrivateNativePending('private_committed_quality_current_writer_expired')
        return dict(ref=ref,binding_id=COMMITTED_BINDING_ID,binding_hash=binding['payload_hash'],completion_id=COMMITTED_COMPLETION_ID,
            completion_hash=completion['payload_hash'],output_hash=output['payload_hash'],artifact_id=COMMITTED_ARTIFACT_ID,
            artifact_hash=digest,version_id=COMMITTED_VERSION_ID,writer_lease=lease,request=request,result=result),deadline

    @staticmethod
    def _committed_quality_seal(cap: IssuedPrivateCommittedPhaseQuality) -> str:
        return canonical_hash(dict(task=cap.task.model_dump(mode='json'),ref=cap.ref.model_dump(mode='json'),
            binding_id=str(cap.binding_id),binding_hash=cap.binding_hash,completion_id=str(cap.completion_id),completion_hash=cap.completion_hash,
            output_hash=cap.output_hash,artifact_id=str(cap.artifact_id),artifact_hash=cap.artifact_hash,version_id=str(cap.version_id),
            writer_lease=cap.writer_lease.model_dump(mode='json'),request=cap.request.model_dump(mode='json'),
            result=cap.result.model_dump(mode='json'),spec=cap.spec.model_dump(mode='json')))

    def _committed_quality_identity(self, cap: IssuedPrivateCommittedPhaseQuality) -> None:
        saved = self._committed_quality.get(cap.handoff_id) if type(cap) is IssuedPrivateCommittedPhaseQuality else None
        if saved is None or cap.owner is not self or saved[0] is not cap or saved[2] is not cap.service or saved[1] != self._committed_quality_seal(cap):
            raise PrivateNativePending('private_committed_quality_original_cap_required')

    def issue_committed_phase_quality(self, service: PrivateEnhancementService, *, task_ref: PersistentPackTaskRef,
                                      completion_id: UUID) -> IssuedPrivateCommittedPhaseQuality:
        from app.services.learning.item_supply.finite_candidate_factory import build_finite_candidate_spec, build_finite_generation_request, check_finite_public_spec
        if type(completion_id) is not UUID or completion_id != COMMITTED_COMPLETION_ID:
            raise PrivateNativePending('private_committed_quality_fixed_completion_required')
        task = checked_model(task_ref,PersistentPackTaskRef)
        data,deadline = self._committed_phase_data(service,task)
        lease,ref,request,result = data['writer_lease'],data['ref'],data['request'],data['result']
        used = self.conn.execute("SELECT (EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence WHERE job_id=%s OR version_id=%s) "
            "OR EXISTS(SELECT 1 FROM tutor_item_supply_private_reservations WHERE job_id=%s) "
            "OR EXISTS(SELECT 1 FROM tutor_item_supply_private_pipeline_receipts WHERE job_id=%s) "
            "OR EXISTS(SELECT 1 FROM tutor_item_supply_private_checkpoints WHERE job_id=%s AND stage<>'generating') "
            "OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id=%s AND payload_json->>'job_id'=%s "
            "AND payload_json->>'schema_version'='private_native_stage_v1' AND payload_json->>'stage'='review')) AS started",
            (COMMITTED_WRITER_ID,COMMITTED_VERSION_ID,COMMITTED_WRITER_ID,COMMITTED_WRITER_ID,COMMITTED_WRITER_ID,task.pack_task_id,str(COMMITTED_WRITER_ID))).fetchone()
        if lease.state_version != 3 or self.facts_owner.pipeline.runtime.next_stage(lease) != 'validating' or used is None or used['started'] is not False:
            raise PrivateNativePending('private_committed_quality_existing_work_no_replay')
        record = service.core._task(task)
        slot = next(s for s in record.slots if s.slot_id == ref.slot_id)
        retained = service.core._versions(task)[slot.slot].published_version_id
        if retained is None:
            raise PrivateNativePending('private_committed_quality_retained_spec_required')
        original = service.base_service.type_owner.resolve_content(retained,current=True).spec
        spec = build_finite_candidate_spec(target_id=original.target_id,variant_id=original.allocation.variant_id,
            seed=original.seed,item_key=request.item_key,version=request.version,materials=request.materials,runtime_profile_hash=None,
            scorer_version=original.coverage_blueprint.scope.scorer_version,assistance_policy_hash=original.coverage_blueprint.scope.assistance_policy_hash,
            policy_version=original.coverage_blueprint.policy_version,difficulty_profile=original.blueprint.difficulty_profile,
            publication_policy=original.blueprint.publication_policy,public_spec_version=request.blueprint.version,allocation=original.allocation)
        expected = build_finite_generation_request(spec,candidate_id=request.candidate_id,profile=request.profile,limits=request.limits,materials=request.materials)
        scope = self.conn.execute('SELECT scope_hash FROM tutor_item_supply_private_scopes WHERE id=%s AND user_id=%s AND epoch=%s',
            (ref.scope_id,ref.user_id,ref.epoch)).fetchone()
        if scope is None or checked_model(expected.model_copy(update={'scope_hash':scope['scope_hash']}),GenerationRequestV2) != request:
            raise PrivateNativePending('private_committed_quality_original_spec_required')
        check_finite_public_spec(result.source.public,spec)
        if (deadline-max(self.facts_owner._guard(ref,lease),service._guard())).total_seconds() <= 7*lease.profile.values.request_timeout_ms/1000+15:
            raise PrivateNativePending('private_committed_quality_remaining_window_required')
        cap = IssuedPrivateCommittedPhaseQuality(self,service,uuid4(),task,spec=spec,**data)
        self._committed_quality[cap.handoff_id] = (cap,self._committed_quality_seal(cap),service)
        self._committed_quality_sources[cap.handoff_id] = service._recovery_source(task)
        self.require_committed_phase_quality(cap)
        return cap

    def require_committed_phase_quality(self, cap: IssuedPrivateCommittedPhaseQuality) -> JobLeaseV1:
        self._committed_quality_identity(cap)
        data,deadline = self._committed_phase_data(cap.service,cap.task)
        lease = data['writer_lease']
        if (any(getattr(cap,key) != value for key,value in data.items() if key != 'writer_lease')
                or lease.model_dump(exclude={'state_version'}) != cap.writer_lease.model_dump(exclude={'state_version'})
                or lease.state_version < cap.writer_lease.state_version):
            raise PrivateNativePending('private_committed_quality_changed_bundle')
        if (deadline-max(self.facts_owner._guard(cap.ref,lease),cap.service._guard())).total_seconds() <= 7*lease.profile.values.request_timeout_ms/1000+15:
            raise PrivateNativePending('private_committed_quality_remaining_window_required')
        return lease

    def select_committed_phase_quality_source(self, cap: IssuedPrivateCommittedPhaseQuality) -> None:
        self._committed_quality_identity(cap)
        if self.conn.info.transaction_status != TransactionStatus.IDLE:
            raise PrivateNativePending('private_committed_quality_idle_selector_required')
        self._select_quality_source(cap,self._committed_quality_sources.get(cap.handoff_id))

    @staticmethod
    def _phase_quality_seal(cap: IssuedPrivatePersistencePhaseQuality) -> str:
        return canonical_hash(dict(bridge_id=str(cap.persistence.bridge_id),bridge_hash=cap.persistence.bridge_hash,
            output_id=str(cap.persistence.output_id),output_hash=cap.persistence.output_hash,
            artifact_id=str(cap.artifact_id),artifact_hash=cap.artifact_hash,spec=cap.spec.model_dump(mode='json')))

    def issue_persistence_phase_quality(self, persistence_cap: IssuedPrivateGenerationPersistencePhase) -> IssuedPrivatePersistencePhaseQuality:
        from app.services.learning.item_supply.private_generation_persistence_phase import (
            IssuedPrivateGenerationPersistencePhase, PrivateGenerationPersistencePhaseOwner,
        )
        if (type(persistence_cap) is not IssuedPrivateGenerationPersistencePhase
                or type(persistence_cap.owner) is not PrivateGenerationPersistencePhaseOwner
                or persistence_cap.owner.facts is not self.facts_owner or persistence_cap.owner.conn is not self.conn):
            raise PrivateNativePending('private_phase_quality_original_owner_required')
        current,artifact = persistence_cap.owner.committed_artifact(persistence_cap)
        task,ref = persistence_cap.task,persistence_cap.ref
        if self.facts_owner.pipeline.runtime.next_stage(current.lease) != 'validating':
            raise PrivateNativePending('private_quality_original_validating_stage_required')
        prior = self.conn.execute("SELECT id FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id=%s AND user_id=%s AND epoch=%s AND scope_id=%s AND record_kind='private_status' AND payload_json->>'schema_version'='private_native_stage_v1' AND payload_json->>'slot_id'=%s AND payload_json->>'stage'='review' AND payload_json->>'subject_hash'=%s LIMIT 1",
            (task.pack_task_id,task.user_id,task.epoch,task.scope_id,str(ref.slot_id),canonical_hash(str(artifact['id'])))).fetchone()
        quality = self.conn.execute('SELECT id FROM '+QUALITY_TABLE+' WHERE pack_task_id=%s AND user_id=%s AND epoch=%s AND scope_id=%s AND version_id=%s LIMIT 1',
            (task.pack_task_id,task.user_id,task.epoch,task.scope_id,artifact['version_id'])).fetchone()
        if prior is not None or quality is not None:
            raise PrivateNativePending('private_quality_existing_stage_no_replay')
        spec = persistence_cap.owner.generation_spec(task,ref,persistence_cap.request,persistence_cap.result)
        cap = IssuedPrivatePersistencePhaseQuality(self,uuid4(),persistence_cap,UUID(str(artifact['id'])),artifact['artifact_hash'],spec)
        self._phase_quality[cap.handoff_id] = (cap,self._phase_quality_seal(cap))
        self._phase_quality_sources[cap.handoff_id] = persistence_cap.owner.service._recovery_source(task)
        self.require_persistence_phase_quality(cap)
        return cap

    def _phase_quality_identity(self, cap: IssuedPrivatePersistencePhaseQuality) -> None:
        saved = self._phase_quality.get(cap.handoff_id) if type(cap) is IssuedPrivatePersistencePhaseQuality else None
        if (saved is None or cap.owner is not self or saved[0] is not cap or saved[1] != self._phase_quality_seal(cap)
                or cap.persistence.owner.facts is not self.facts_owner or cap.persistence.owner.conn is not self.conn):
            raise PrivateNativePending('private_phase_quality_original_handoff_required')
        cap.persistence.owner.require_identity(cap.persistence)

    def require_persistence_phase_quality(self, cap: IssuedPrivatePersistencePhaseQuality) -> JobLeaseV1:
        self._phase_quality_identity(cap)
        current,artifact = cap.persistence.owner.committed_artifact(cap.persistence)
        if UUID(str(artifact['id'])) != cap.artifact_id or artifact['artifact_hash'] != cap.artifact_hash:
            raise PrivateNativePending('private_phase_quality_original_artifact_required')
        return current.lease

    def select_persistence_phase_quality_source(self, cap: IssuedPrivatePersistencePhaseQuality) -> None:
        self._phase_quality_identity(cap)
        self._select_quality_source(cap,self._phase_quality_sources.get(cap.handoff_id))

    @staticmethod
    def _initial_quality_seal(cap: IssuedPrivateInitialQualityHandoff) -> str:
        return canonical_hash(dict(output_id=str(cap.persistence.output_id),output_hash=cap.persistence.output_hash,
            artifact_id=str(cap.artifact_id),artifact_hash=cap.artifact_hash,spec=cap.spec.model_dump(mode='json')))

    def issue_initial_quality(self, persistence_cap: IssuedPrivateGenerationPersistence) -> IssuedPrivateInitialQualityHandoff:
        from app.services.learning.item_supply.private_generation_persistence import IssuedPrivateGenerationPersistence, PrivateGenerationPersistenceOwner
        from app.services.learning.item_supply.finite_candidate_factory import build_finite_candidate_spec, check_finite_public_spec
        from app.services.learning.item_supply.private_finite_factory import build_private_generation_request
        if (type(persistence_cap) is not IssuedPrivateGenerationPersistence
                or type(persistence_cap.owner) is not PrivateGenerationPersistenceOwner
                or persistence_cap.owner.facts is not self.facts_owner or persistence_cap.owner.conn is not self.conn):
            raise PrivateNativePending('private_quality_original_persistence_owner_required')
        current, artifact = persistence_cap.owner.committed_artifact(persistence_cap)
        service = persistence_cap.owner.service
        ref, task = persistence_cap.ref, persistence_cap.task
        if self.facts_owner.pipeline.runtime.next_stage(current.lease) != 'validating':
            raise PrivateNativePending('private_quality_original_validating_stage_required')
        prior = self.conn.execute("SELECT id FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id=%s AND user_id=%s AND epoch=%s AND scope_id=%s AND record_kind='private_status' AND payload_json->>'schema_version'='private_native_stage_v1' AND payload_json->>'slot_id'=%s AND payload_json->>'stage'='review' AND payload_json->>'subject_hash'=%s LIMIT 1",
            (task.pack_task_id,task.user_id,task.epoch,task.scope_id,str(ref.slot_id),canonical_hash(str(artifact['id'])))).fetchone()
        quality = self.conn.execute('SELECT id FROM '+QUALITY_TABLE+' WHERE pack_task_id=%s AND user_id=%s AND epoch=%s AND scope_id=%s AND version_id=%s LIMIT 1',
            (task.pack_task_id,task.user_id,task.epoch,task.scope_id,artifact['version_id'])).fetchone()
        if prior is not None or quality is not None:
            raise PrivateNativePending('private_quality_existing_stage_no_replay')
        record = service.core._task(task)
        slot = next(s for s in record.slots if s.slot_id == ref.slot_id)
        retained = service.core._versions(task)[slot.slot].published_version_id
        if retained is None:
            raise PrivateNativePending('private_quality_original_retained_spec_required')
        base = service.base_service.type_owner.resolve_content(retained,current=True)
        original, request = base.spec, persistence_cap.request
        spec = build_finite_candidate_spec(target_id=original.target_id,variant_id=original.allocation.variant_id,
            seed=original.seed,item_key=request.item_key,version=request.version,materials=request.materials,
            runtime_profile_hash=None,scorer_version=original.coverage_blueprint.scope.scorer_version,
            assistance_policy_hash=original.coverage_blueprint.scope.assistance_policy_hash,
            policy_version=original.coverage_blueprint.policy_version,difficulty_profile=original.blueprint.difficulty_profile,
            publication_policy=original.blueprint.publication_policy,public_spec_version=request.blueprint.version,allocation=original.allocation)
        expected = build_private_generation_request(self.facts_owner,ref=ref,lease=current.lease,spec=spec,
            materials=request.materials,limits=request.limits,candidate_id=request.candidate_id)
        if expected != request or persistence_cap.result.source is None:
            raise PrivateNativePending('private_quality_original_captured_spec_required')
        check_finite_public_spec(persistence_cap.result.source.public,spec)
        cap = IssuedPrivateInitialQualityHandoff(self,uuid4(),persistence_cap,UUID(str(artifact['id'])),artifact['artifact_hash'],spec)
        self._initial_quality[cap.handoff_id] = (cap,self._initial_quality_seal(cap))
        self._initial_quality_sources[cap.handoff_id] = service._recovery_source(task)
        self.require_initial_quality(cap)
        return cap

    def _initial_quality_identity(self, cap: IssuedPrivateInitialQualityHandoff) -> None:
        saved = self._initial_quality.get(cap.handoff_id) if type(cap) is IssuedPrivateInitialQualityHandoff else None
        if (saved is None or cap.owner is not self or saved[0] is not cap or saved[1] != self._initial_quality_seal(cap)
                or cap.persistence.owner.facts is not self.facts_owner or cap.persistence.owner.conn is not self.conn):
            raise PrivateNativePending('private_quality_original_handoff_required')
        cap.persistence.owner.require_identity(cap.persistence)

    def require_initial_quality(self, cap: IssuedPrivateInitialQualityHandoff) -> JobLeaseV1:
        self._initial_quality_identity(cap)
        current, artifact = cap.persistence.owner.committed_artifact(cap.persistence)
        if UUID(str(artifact['id'])) != cap.artifact_id or artifact['artifact_hash'] != cap.artifact_hash:
            raise PrivateNativePending('private_quality_original_artifact_required')
        return current.lease

    def select_initial_quality_source(self, cap: IssuedPrivateInitialQualityHandoff) -> None:
        """Identity-only selector at IDLE; facts reissues SOURCE in its next TOP."""
        self._initial_quality_identity(cap)
        self._select_quality_source(cap,self._initial_quality_sources.get(cap.handoff_id))

    def _select_quality_source(self, cap: IssuedPrivateInitialQualityHandoff | IssuedPrivatePersistencePhaseQuality | IssuedPrivateCommittedPhaseQuality,
                               source: IssuedCurrentPackSourceBinding | None) -> None:
        from app.services.learning.item_supply.persistent_pack_current_source import IssuedCurrentPackSourceBinding, _seal
        service = cap.service if isinstance(cap, IssuedPrivateCommittedPhaseQuality) else cap.persistence.owner.service
        task = cap.task if isinstance(cap, IssuedPrivateCommittedPhaseQuality) else cap.persistence.task
        if source is None or type(source) is not IssuedCurrentPackSourceBinding or source.owner is not service.core or source.task != task:
            raise PrivateNativePending('private_quality_original_source_selector_required')
        saved = service.core._current_source_bindings.get(source.binding_id)
        public = service.base_service.type_owner
        if (service.core.conn is not self.conn or service.core.type_owner is not public
                or saved is None or saved[0] is not source or saved[1] != _seal(source)
                or public.current_source_binding is not None and public.current_source_binding is not source):
            raise PrivateNativePending('private_quality_original_source_selector_required')
        public.current_source_binding = source

    def _seal(self, p: PreparedPrivateReview, r: CompletedPrivateReview) -> str:
        return canonical_hash({'ref':p.ref.model_dump(mode='json'),'lease':p.original.lease.model_dump(mode='json'),
            'artifact_id':str(p.original.artifact_id),'review_id':str(p.preparation_id),
            'spec':p.spec.model_dump(mode='json'),'request':p.request.model_dump(mode='json'),
            'bundle':r.bundle.model_dump(mode='json'),'ambiguity':r.ambiguity.model_dump(mode='json')})

    def issue_review(self, *, ref: PrivateSlotRef, lease: JobLeaseV1, review_id: UUID) -> IssuedPrivateCommittedReview:
        self.facts_owner._guard(ref,lease)
        row=self.conn.execute('SELECT payload_json FROM '+QUALITY_TABLE+
            " WHERE id=%s AND kind='review' AND user_id=%s AND epoch=%s AND scope_id=%s AND pack_task_id=%s AND slot_id=%s AND root_id=%s AND xmin::text::bigint<>(txid_current() %% 4294967296)",
            (review_id,ref.user_id,ref.epoch,ref.scope_id,ref.pack_task_id,ref.slot_id,ref.root_id)).fetchone()
        if row is None:
            raise PrivateNativePending('private_resume_committed_exact_review_required')
        payload=row['payload_json']
        old_ref=checked_model(payload['ref'],PrivateSlotRef)
        if old_ref!=ref:
            raise PrivateNativePending('private_resume_immutable_slot_lineage_required')
        artifact=self.facts_owner._artifact(ref,lease,UUID(payload['artifact_id']))
        source=LearningItemSourceV1.model_validate_json(json.dumps(artifact['source_json']))
        request=GenerationRequestV2.model_validate_json(json.dumps(artifact['request_json']))
        spec=checked_model(payload['spec'],FiniteCandidateSpecV1)
        policy=policy_for_hash(canonical_hash(payload['policy']))
        if policy.model_dump(mode='json')!=payload['policy']:
            raise PrivateNativePending('private_resume_original_policy_required')
        bundle=parse_bundle(payload['bundle'])
        ambiguity=checked_model(payload['ambiguity'],FiniteAmbiguityReceiptV1)
        static=prepare_finite_candidate_validation(source,spec=spec,materials=request.materials).static_facts
        if static is None:
            raise PrivateNativePending('private_resume_execution_owner_required')
        validation=self.conn.execute('SELECT id FROM '+QUALITY_TABLE+
            " WHERE kind='validation' AND version_id=%s AND user_id=%s AND epoch=%s AND scope_id=%s AND job_id=%s AND payload_json=%s ORDER BY created_at,id LIMIT 1",
            (artifact['version_id'],ref.user_id,ref.epoch,ref.scope_id,payload['lease']['job_id'],Jsonb(static.validation.model_dump(mode='json')))).fetchone()
        blind=self.conn.execute('SELECT id FROM '+QUALITY_TABLE+
            " WHERE kind='blind' AND version_id=%s AND user_id=%s AND epoch=%s AND scope_id=%s AND job_id=%s AND payload_json=%s ORDER BY created_at,id LIMIT 1",
            (artifact['version_id'],ref.user_id,ref.epoch,ref.scope_id,payload['lease']['job_id'],Jsonb(bundle.blind_solve.model_dump(mode='json')))).fetchone()
        if validation is None or blind is None:
            raise PrivateNativePending('private_resume_complete_original_validation_blind_required')
        # Current lease authorizes ONLY continuation. Historical binding, roles,
        # run IDs, policy, reservation and evidence remain bit-for-bit original.
        original=PreparedReview(lease,ref.scope_id,UUID(str(artifact['id'])),source,static.validation,bundle.binding,
            bundle.author_identity,UUID(payload['reservation_id']),'live',(1,)*7)
        prepared=PreparedPrivateReview(ref,original,spec,request,policy,review_id)
        result=CompletedPrivateReview(bundle,ambiguity)
        rid=uuid4()
        frame={'schema_version':'private_native_committed_review_resume_v1','ref':ref.model_dump(mode='json'),
            'lease':lease.model_dump(mode='json'),'review_id':str(review_id),'validation_id':str(validation['id']),
            'blind_id':str(blind['id']),'artifact_id':str(artifact['id'])}
        self.conn.execute('SELECT item_supply_internal.private_native_resume_review(%s,%s)',(rid,Jsonb(frame)))
        cap=IssuedPrivateCommittedReview(self,rid,ref,lease,prepared,result,UUID(str(validation['id'])),
            UUID(str(blind['id'])),self._seal(prepared,result))
        self._issued[rid]=cap
        self.require(cap)
        return cap

    def require(self, cap: IssuedPrivateCommittedReview) -> IssuedPrivateCommittedReview:
        if type(cap) is not IssuedPrivateCommittedReview or cap.owner is not self or self._issued.get(cap.resume_id) is not cap:
            raise PrivateNativePending('private_resume_fresh_concrete_identity_required')
        self.facts_owner._guard(cap.ref,cap.lease)
        if self._seal(cap.prepared,cap.result)!=cap.seal:
            raise PrivateNativePending('private_resume_mutated_evidence_denied')
        row=self.conn.execute('SELECT item_supply_internal.private_native_resume_current(%s,%s) AS ok',
            (cap.resume_id,cap.lease.job_id)).fetchone()
        if row is None or row['ok'] is not True:
            raise PrivateNativePending('private_resume_current_original_receiver_required')
        return cap

    def restore_child(self, cap: IssuedPrivateCommittedReview, normal: Any) -> None:
        from app.services.learning.item_supply.private_native_review_loop import (
            PrivateNativeNormalReadmissionOwner, PreparedPrivateRevision,
        )
        self.require(cap)
        if type(normal) is not PrivateNativeNormalReadmissionOwner or normal.facts_owner is not self.facts_owner:
            raise PrivateNativePending('private_resume_exact_child_owner_required')
        if cap.ref.parent_version_id is None:
            return
        row=self.conn.execute("SELECT id,payload_json FROM tutor_item_supply_private_persistent_pack_journal WHERE user_id=%s AND epoch=%s AND pack_task_id=%s AND record_kind='private_attachment' AND payload_json->'request'->>'schema_version'='private_native_revision_phase_v1' AND payload_json->'request'->>'parent_version_id'=%s AND payload_json->'request'->'request'=%s ORDER BY created_at DESC,id DESC LIMIT 1",
            (cap.ref.user_id,cap.ref.epoch,cap.ref.pack_task_id,str(cap.ref.parent_version_id),Jsonb(cap.prepared.request.model_dump(mode='json')))).fetchone()
        if row is None:
            raise PrivateNativePending('private_resume_original_child_preparation_required')
        p=row['payload_json']
        request=p['request']
        parent=self.conn.execute("SELECT source_json FROM tutor_item_supply_private_generation_artifacts WHERE version_id=%s AND user_id=%s AND epoch=%s AND scope_id=%s AND mode='live'",
            (cap.ref.parent_version_id,cap.ref.user_id,cap.ref.epoch,cap.ref.scope_id)).fetchone()
        if parent is None:
            raise PrivateNativePending('private_resume_original_parent_artifact_required')
        old_lease=checked_model(request['lease'],JobLeaseV1)
        generated=PreparedGeneration(old_lease,cap.ref.scope_id,cap.prepared.request,UUID(p['reservation_id']),(),1,'live')
        # Historical preparation is registered for readmission only, NEVER in
        # normal._prepared/_runs or pipeline's IO registry (cannot run/persist).
        child=PreparedPrivateRevision(UUID(str(row['id'])),UUID(request['investigation_id']),cap.ref,old_lease,
            cap.prepared.spec,generated,LearningItemSourceV1.model_validate_json(json.dumps(parent['source_json'])),request['directive_hash'])
        normal._children[cap.prepared.original.artifact_id]=child

    def restore_investigation(self, cap: IssuedPrivateCommittedReview, *, receipt_id: UUID, loop: Any) -> None:
        from app.services.learning.item_supply.private_native_review_loop import (
            PrivateNativeNormalReviewLoopOwner, PreparedPrivateInvestigation, PrivateInvestigationOutput,
        )
        from app.services.learning.item_supply.review_contracts_v2 import ProviderRunV2
        self.require(cap)
        if type(loop) is not PrivateNativeNormalReviewLoopOwner or loop.facts_owner is not self.facts_owner:
            raise PrivateNativePending('private_resume_exact_investigation_owner_required')
        row=self.conn.execute('SELECT payload_json FROM '+QUALITY_TABLE+
            " WHERE id=%s AND kind='investigation' AND user_id=%s AND epoch=%s AND scope_id=%s AND pack_task_id=%s AND slot_id=%s AND root_id=%s",
            (receipt_id,cap.ref.user_id,cap.ref.epoch,cap.ref.scope_id,cap.ref.pack_task_id,cap.ref.slot_id,cap.ref.root_id)).fetchone()
        checked=self.conn.execute('SELECT item_supply_internal.private_native_resume_investigation(%s,%s) AS ok',
            (receipt_id,cap.resume_id)).fetchone()
        if row is None or checked is None or checked['ok'] is not True:
            raise PrivateNativePending('private_resume_original_committed_investigation_required')
        payload=row['payload_json']
        output=checked_model(payload['output'],PrivateInvestigationOutput)
        run=checked_model(payload['run'],ProviderRunV2)
        old_lease=checked_model(payload['lease'],JobLeaseV1)
        historical=PreparedPrivateInvestigation(UUID(payload['preparation_id']),cap.prepared,cap.result,old_lease,
            payload['request'],UUID(payload['reservation_id']),run.provider_identity,min(old_lease.expires_at,old_lease.parent_deadline))
        # Registered lineage authorizes a NEW child preparation only. Never
        # registers old investigator in IO/_prepared/_runs/_started registries.
        loop._lineages[receipt_id]=(historical,output,UUID(cap.prepared.original.binding.version_key))

    def inherit_generation(self, *, ref: PrivateSlotRef, lease: JobLeaseV1, artifact_id: UUID) -> JobLeaseV1:
        from app.services.learning.item_supply.jobs import CheckpointV1
        self.facts_owner._guard(ref,lease)
        row=self.conn.execute('SELECT item_supply_internal.private_native_inherit_generation(%s) AS digest',
            (Jsonb({'ref':ref.model_dump(mode='json'),'lease':lease.model_dump(mode='json'),'artifact_id':str(artifact_id)}),)).fetchone()
        if row is None or not row['digest']:
            raise PrivateNativePending('private_resume_checked_original_generation_required')
        self.facts_owner.pipeline.runtime.checkpoint(lease,CheckpointV1(stage='generating',attempt=1,status='completed',
            receipt_hash=row['digest'],safe_reason='private_committed_generation_inherited'),now=self.facts_owner._guard(ref,lease))
        return self.facts_owner.pipeline.runtime.refresh_lease(lease,now=self.facts_owner._guard(ref,lease))


