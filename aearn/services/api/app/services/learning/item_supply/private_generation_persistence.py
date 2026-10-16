"""Fixed C17 DB-output persistence authority, never an author capability."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from typing import Any
from uuid import UUID

from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.generation_contracts import GenerationRequestV2, GenerationResultV2
from app.services.learning.item_supply.jobs import CheckpointV1, JobLeaseV1
from app.services.learning.item_supply.persistent_pack_contracts import PersistentPackTaskRef
from app.services.learning.item_supply.private_development_model_accounting import accounting_batch_for_lease
from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending, PrivateSlotRef
from app.services.learning.item_supply.private_enhancement_service import (
    PRIVATE_JOURNAL, RECOVERY_BUSINESS, RECOVERY_MAPPING, RECOVERY_ROOT, RECOVERY_SCOPE,
    RECOVERY_SLOT, RECOVERY_TASK, RECOVERY_USER, PrivateEnhancementService,
)
from app.services.learning.item_supply.storage_contracts import checked_model


OUTPUT_ID = UUID('f4519c66-4130-4e34-b053-64dba6214dcb')
PREPARATION_ID = UUID('d55f63a9-8043-4d74-8a1c-0862660aed30')
JOB_ID = UUID('c9442831-e8d6-43b6-9367-b94875c60f36')


@dataclass(frozen=True, repr=False)
class IssuedPrivateGenerationPersistence:
    owner: PrivateGenerationPersistenceOwner
    task: PersistentPackTaskRef
    output_id: UUID
    output_hash: str
    capture: dict[str, Any]
    ref: PrivateSlotRef
    request: GenerationRequestV2
    result: GenerationResultV2
    original_lease: JobLeaseV1


@dataclass(frozen=True, repr=False)
class PrivateGenerationPersistenceContext:
    output: dict[str, Any]
    lease: JobLeaseV1
    started: dict[str, Any]
    valid_until: datetime


class PrivateGenerationPersistenceOwner:
    def __init__(self, service: PrivateEnhancementService) -> None:
        if type(service) is not PrivateEnhancementService:
            raise PrivateNativePending('private_persistence_concrete_service_required')
        self.service, self.conn, self.facts = service, service.conn, service.facts_owner
        self.pipeline = self.facts.pipeline
        self._issued: dict[UUID, tuple[IssuedPrivateGenerationPersistence, str]] = {}
        self._observed: dict[UUID, tuple[IssuedPrivateGenerationPersistence, str, UUID, str]] = {}

    def _guard(self) -> str:
        s = self.service
        if (s.conn is not self.conn or s.facts_owner is not self.facts or self.facts.pipeline is not self.pipeline
                or self.facts.conn is not self.conn or self.pipeline.conn is not self.conn
                or s.core.conn is not self.conn or self.facts.settings is not s.settings
                or self.facts.source_authority.connection is not self.conn
                or s.generation_persistence_owner() is not self):
            raise PrivateNativePending('private_persistence_original_owners_required')
        if self.conn.autocommit or self.conn.info.transaction_status != TransactionStatus.INTRANS:
            raise PrivateNativePending('private_persistence_caller_top_required')
        if not self.pipeline.generation_enabled:
            raise PrivateNativePending('private_persistence_generation_disabled')
        s._guard()
        s._generation_output_ready()
        row = self.conn.execute("SELECT pg_current_xact_id()::text AS top_xid, current_setting('transaction_isolation') AS isolation, current_setting('transaction_read_only') AS read_only").fetchone()
        if row is None or row['isolation'] != 'read committed' or row['read_only'] != 'off':
            raise PrivateNativePending('private_persistence_caller_top_required')
        return str(row['top_xid'])

    @staticmethod
    def _seal(cap: IssuedPrivateGenerationPersistence) -> str:
        return canonical_hash(dict(task=cap.task.model_dump(mode='json'), output_id=str(cap.output_id),
            output_hash=cap.output_hash, capture=cap.capture, ref=cap.ref.model_dump(mode='json'),
            request=cap.request.model_dump(mode='json'), result=cap.result.model_dump(mode='json'),
            lease=cap.original_lease.model_dump(mode='json')))

    def _output(self) -> dict[str, Any]:
        row = self.conn.execute('SELECT id,payload_json,payload_hash FROM '+PRIVATE_JOURNAL+
            " WHERE id=%s AND pack_task_id=%s AND user_id=%s AND epoch=1 AND scope_id=%s AND record_kind='private_status' AND operation_key=%s FOR SHARE",
            (OUTPUT_ID,RECOVERY_TASK,RECOVERY_USER,RECOVERY_SCOPE,'private.generation.output.'+PREPARATION_ID.hex)).fetchone()
        if (row is None or row['payload_json'].get('schema_version') != 'private_generation_output_v1'
                or row['payload_json'].get('preparation_id') != str(PREPARATION_ID)
                or row['payload_hash'] != canonical_hash(row['payload_json'])):
            raise PrivateNativePending('private_persistence_exact_db_output_required')
        committed = self.conn.execute('SELECT item_supply_internal.private_generation_output_committed(%s,%s) AS id',
            (PREPARATION_ID,Jsonb(row['payload_json']['capture']))).fetchone()
        if committed is None or committed['id'] != OUTPUT_ID:
            raise PrivateNativePending('private_persistence_committed_output_required')
        return row

    def issue(self, *, task_ref: PersistentPackTaskRef, output_id: UUID) -> IssuedPrivateGenerationPersistence:
        task_ref = checked_model(task_ref,PersistentPackTaskRef)
        if (type(output_id) is not UUID or output_id != OUTPUT_ID
                or (task_ref.pack_task_id,task_ref.user_id,task_ref.epoch,task_ref.scope_id,task_ref.mapping_receipt_id)
                != (RECOVERY_TASK,RECOVERY_USER,1,RECOVERY_SCOPE,RECOVERY_MAPPING)):
            raise PrivateNativePending('private_persistence_fixed_output_required')
        top = self._guard()
        row = self._output()
        capture = row['payload_json']['capture']
        cap = IssuedPrivateGenerationPersistence(self,task_ref,output_id,row['payload_hash'],capture,
            PrivateSlotRef.model_validate_json(json.dumps(capture['context']['ref'])),
            GenerationRequestV2.model_validate_json(json.dumps(capture['context']['request'])),
            GenerationResultV2.model_validate_json(json.dumps(capture['result'])),
            JobLeaseV1.model_validate_json(json.dumps(capture['context']['lease'])))
        current = self._current(cap,row)
        bundle = self._bundle(cap,current)
        self._postwait(cap,current)
        self._issued[output_id] = (cap,self._seal(cap))
        self._observed.pop(output_id,None)
        if bundle is not None:
            self._observe(cap,top,bundle)
        return cap

    def require_identity(self, cap: IssuedPrivateGenerationPersistence) -> None:
        saved = self._issued.get(cap.output_id) if type(cap) is IssuedPrivateGenerationPersistence else None
        if (saved is None or cap.owner is not self or saved[0] is not cap or saved[1] != self._seal(cap)):
            raise PrivateNativePending('private_persistence_original_cap_required')

    def require(self, cap: IssuedPrivateGenerationPersistence) -> PrivateGenerationPersistenceContext:
        self.require_identity(cap)
        self._guard()
        row = self._output()
        if row['payload_hash'] != cap.output_hash or row['payload_json']['capture'] != cap.capture:
            raise PrivateNativePending('private_persistence_output_changed')
        return self._current(cap,row)

    def _current(self, cap: IssuedPrivateGenerationPersistence, row: dict[str, Any]) -> PrivateGenerationPersistenceContext:
        ref, request, result, frozen = cap.ref, cap.request, cap.result, cap.original_lease
        ctx = cap.capture['context']
        record = self.service.core._task(cap.task)
        if (record.ref != cap.task or record.enhancement != 'prefer_private'
                or not any((s.slot_id,s.logical_item_id,s.slot)==(RECOVERY_SLOT,RECOVERY_BUSINESS,'practice-1') for s in record.slots)
                or (ref.pack_task_id,ref.user_id,ref.epoch,ref.scope_id,ref.mapping_receipt_id,ref.slot_id,ref.business_item_id,ref.root_id,ref.slot,ref.parent_version_id)
                != (RECOVERY_TASK,RECOVERY_USER,1,RECOVERY_SCOPE,RECOVERY_MAPPING,RECOVERY_SLOT,RECOVERY_BUSINESS,RECOVERY_ROOT,'practice',None)
                or request.candidate_id != PREPARATION_ID or request.item_key != 'private-native.'+RECOVERY_BUSINESS.hex
                or request.version != 'v1' or frozen.job_id != JOB_ID or frozen.generation != 1
                or frozen.visibility != 'private' or (frozen.owner_id,frozen.owner_epoch)!=(RECOVERY_USER,1)
                or ctx['scope_id'] != str(ref.scope_id) or ctx['attempt_bound'] != 1 or ctx['mode'] != 'live'
                or result.state != 'staged' or result.source is None or result.receipt is None):
            raise PrivateNativePending('private_persistence_exact_initial_context_required')
        source, receipt = result.source, result.receipt
        if (source.blueprint != request.blueprint or (source.public.item_key,source.public.version)!=(request.item_key,request.version)
                or request.profile != frozen.profile or receipt.candidate_id != request.candidate_id or receipt.scope_hash != request.scope_hash
                or [s.model_dump(mode='json') for s in receipt.sources] != ctx['sources']
                or receipt.source_hash != source.source_hash or receipt.content_hash != source.content_hash
                or receipt.provider.mode != 'provider' or receipt.provider.request_attempt_bound != 1
                or receipt.provider.model != receipt.provider.configured_model
                or ctx['producer_binding'] != [receipt.provider.provider,receipt.provider.configured_model]):
            raise PrivateNativePending('private_persistence_original_result_binding_required')
        actual = self.service._recovery_source(cap.task)
        bound = self.conn.execute('SELECT b.id,b.payload_json FROM item_supply_internal.private_initial_author_continuation_bound(%s,%s,true) AS b',
            (UUID(row['payload_json']['binding_id']),actual.origin_id())).fetchone()
        if bound is None or str(bound['id']) != row['payload_json']['binding_id']:
            raise PrivateNativePending('private_persistence_original_binding_required')
        lease = self.pipeline.runtime.refresh_lease(frozen,now=self.service._guard())
        now = self.facts._guard(ref,lease)
        control = self.pipeline.runtime._control(lease,now=now)
        if control['attempt_count'] != 1 or list(self.pipeline._provider_binding(lease,receipt.provider.provider,
                receipt.provider.configured_model)) != ctx['producer_binding']:
            raise PrivateNativePending('private_persistence_original_provider_profile_required')
        batch = accounting_batch_for_lease(self.conn,lease,now=now)
        if batch is None:
            raise PrivateNativePending('private_persistence_original_accounting_required')
        for material, expected in zip(request.materials,receipt.sources,strict=True):
            self.facts.source_authority.assert_current(material,expected)
        current = self.conn.execute('SELECT item_supply_internal.private_native_source_current(%s) AS ok',
            (Jsonb(dict(ref=ref.model_dump(mode='json'),request=request.model_dump(mode='json'),
                source_receipts=[s.model_dump(mode='json') for s in receipt.sources])),)).fetchone()
        if current is None or current['ok'] is not True:
            raise PrivateNativePending('private_persistence_original_source_current_required')
        actual.require()
        now = self.facts._guard(ref,lease)
        valid_until = min(frozen.expires_at,lease.expires_at,lease.parent_deadline,batch['valid_until'],actual.source_deadline,
            datetime.fromisoformat(bound['payload_json']['valid_until']),
            frozen.profile.bound_at+timedelta(milliseconds=frozen.profile.values.stage_deadline_ms))
        if now >= valid_until:
            raise PrivateNativePending('private_persistence_original_writer_expired')
        started = self.conn.execute('SELECT id,operation_key,payload_json FROM '+PRIVATE_JOURNAL+
            " WHERE id=%s AND pack_task_id=%s AND user_id=%s AND epoch=1 AND scope_id=%s AND record_kind='private_status'",
            (UUID(row['payload_json']['started_id']),RECOVERY_TASK,RECOVERY_USER,RECOVERY_SCOPE)).fetchone()
        if (started is None or not started['operation_key'].endswith('.author.started')
                or started['payload_json'] != dict(schema_version='private_native_stage_v1',job_id=str(JOB_ID),
                    slot_id=str(RECOVERY_SLOT),stage='author',status='started',subject_hash=canonical_hash('v1'),receipt_id=None)):
            raise PrivateNativePending('private_persistence_original_started_required')
        return PrivateGenerationPersistenceContext(row,lease,started,valid_until)

    def _postwait(self, cap: IssuedPrivateGenerationPersistence, current: PrivateGenerationPersistenceContext) -> None:
        self.service._recovery_source(cap.task).require()
        if self.facts._guard(cap.ref,current.lease) >= current.valid_until:
            raise PrivateNativePending('private_persistence_original_writer_expired')

    @staticmethod
    def _result_key(current: PrivateGenerationPersistenceContext) -> str:
        return current.started['operation_key'][:-len('.started')]+'.result'

    @staticmethod
    def _result_payload(artifact_id: UUID) -> dict[str, Any]:
        return dict(schema_version='private_native_stage_v1',job_id=str(JOB_ID),slot_id=str(RECOVERY_SLOT),
            stage='author',status='committed',subject_hash=canonical_hash('v1'),receipt_id=str(artifact_id))

    def _bundle(self, cap: IssuedPrivateGenerationPersistence, current: PrivateGenerationPersistenceContext) -> tuple[dict[str, Any], str] | None:
        artifact = self.conn.execute('SELECT a.*,c.candidate_key AS storage_key,v.version AS storage_version,v.public_json,v.private_json '
            'FROM tutor_item_supply_private_generation_artifacts a JOIN tutor_item_supply_private_candidates c ON c.id=a.candidate_id '
            'JOIN tutor_item_supply_private_versions v ON v.id=a.version_id AND v.candidate_id=c.id '
            'WHERE a.job_id=%s AND a.lease_generation=1 AND a.user_id=%s AND a.epoch=1 AND a.scope_id=%s FOR SHARE OF a,c,v',
            (JOB_ID,RECOVERY_USER,RECOVERY_SCOPE)).fetchone()
        checkpoint = self.conn.execute('SELECT stage,attempt,status,lease_generation,receipt_hash,safe_reason FROM tutor_item_supply_private_checkpoints '
            "WHERE job_id=%s AND user_id=%s AND epoch=1 AND scope_id=%s AND stage='generating' AND attempt=1",
            (JOB_ID,RECOVERY_USER,RECOVERY_SCOPE)).fetchone()
        done = self.conn.execute('SELECT id,payload_json FROM '+PRIVATE_JOURNAL+
            " WHERE pack_task_id=%s AND user_id=%s AND epoch=1 AND scope_id=%s AND record_kind='private_status' AND operation_key=%s",
            (RECOVERY_TASK,RECOVERY_USER,RECOVERY_SCOPE,self._result_key(current))).fetchone()
        if artifact is None and checkpoint is None and done is None:
            return None
        source, receipt = cap.result.source, cap.result.receipt
        if source is None or receipt is None or artifact is None or checkpoint is None or done is None:
            raise PrivateNativePending('private_persistence_partial_generation_denied')
        digest = canonical_hash(dict(source=source.model_dump(mode='json'),receipt=receipt.model_dump(mode='json')))
        if (artifact['mode'] != 'live' or artifact['artifact_key'] != 'generation.'+PREPARATION_ID.hex
                or artifact['request_json'] != cap.request.model_dump(mode='json')
                or artifact['source_json'] != source.model_dump(mode='json') or artifact['receipt_json'] != receipt.model_dump(mode='json')
                or artifact['source_hash'] != source.source_hash or artifact['content_hash'] != source.content_hash or artifact['artifact_hash'] != digest
                or artifact['storage_key'] != 'private.native.'+RECOVERY_BUSINESS.hex or artifact['storage_version'] != 1
                or artifact['public_json'] != source.public.model_dump(mode='json') or artifact['private_json'] != source.private.model_dump(mode='json')
                or checkpoint != dict(stage='generating',attempt=1,status='completed',lease_generation=1,
                    receipt_hash=digest,safe_reason='candidate_staged')
                or done['payload_json'] != self._result_payload(UUID(str(artifact['id'])))):
            raise PrivateNativePending('private_persistence_original_generation_conflict')
        frame = dict(output_hash=cap.output_hash,artifact_id=str(artifact['id']),artifact_hash=digest,
            candidate_id=str(artifact['candidate_id']),version_id=str(artifact['version_id']),checkpoint=checkpoint,
            result_id=str(done['id']),result=done['payload_json'])
        return artifact,canonical_hash(frame)

    def _observe(self, cap: IssuedPrivateGenerationPersistence, top: str, bundle: tuple[dict[str, Any], str]) -> None:
        self._observed[cap.output_id] = (cap,top,UUID(str(bundle[0]['id'])),bundle[1])

    def persist(self, cap: IssuedPrivateGenerationPersistence) -> UUID:
        current = self.require(cap)
        with self.conn.transaction():  # Only a savepoint inside the caller TOP.
            bundle = self._bundle(cap,current)
            if bundle is None:
                if self.pipeline.runtime.next_stage(current.lease) != 'generating':
                    raise PrivateNativePending('private_persistence_original_generating_stage_required')
                now = self.facts._guard(cap.ref,current.lease)
                artifact = self.pipeline.artifacts.store_generation(lease=current.lease,scope_id=cap.ref.scope_id,
                    request=cap.request,result=cap.result,artifact_key='generation.'+PREPARATION_ID.hex,now=now,
                    mode='live',source_authority=self.facts.source_authority,private_slot_ref=cap.ref)
                self.pipeline.runtime.checkpoint(current.lease,CheckpointV1(stage='generating',attempt=1,status='completed',
                    receipt_hash=artifact['artifact_hash'],safe_reason='candidate_staged'),now=self.service._guard())
                self.service.core._private_event(cap.task,'private_status',self._result_payload(UUID(str(artifact['id']))),
                    key=self._result_key(current))
                current = self.require(cap)
                bundle = self._bundle(cap,current)
            if bundle is None:
                raise PrivateNativePending('private_persistence_original_generation_required')
            self._postwait(cap,current)
            self._observe(cap,self._guard(),bundle)
        return UUID(str(bundle[0]['id']))

    def committed_artifact(self, cap: IssuedPrivateGenerationPersistence) -> tuple[PrivateGenerationPersistenceContext, dict[str, Any]]:
        current = self.require(cap)
        observed = self._observed.get(cap.output_id)
        if observed is None or observed[0] is not cap or observed[1] == self._guard():
            raise PrivateNativePending('private_persistence_distinct_artifact_top_required')
        bundle = self._bundle(cap,current)
        if bundle is None or (UUID(str(bundle[0]['id'])),bundle[1]) != observed[2:]:
            raise PrivateNativePending('private_persistence_committed_generation_required')
        self._postwait(cap,current)
        return current,bundle[0]
