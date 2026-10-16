"""One fixed DB output, one new PRIVATE writer; never an author/restart port."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from typing import Any
from uuid import UUID

from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.finite_candidate_factory import (
    FiniteCandidateSpecV1, build_finite_candidate_spec, build_finite_generation_request, check_finite_public_spec,
)
from app.services.learning.item_supply.generation_contracts import GenerationRequestV2, GenerationResultV2
from app.services.learning.item_supply.jobs import CheckpointV1, JobLeaseV1
from app.services.learning.item_supply.parameter_profiles import ExecutionParameterProfileV1, ParameterValuesV1
from app.services.learning.item_supply.persistent_pack_contracts import PersistentPackTaskRef
from app.services.learning.item_supply.private_development_model_accounting import (
    PrivateDevelopmentModelAccountingOwner, accounting_batch_for_lease,
)
from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending, PrivateSlotRef
from app.services.learning.item_supply.private_enhancement_service import (
    PRIVATE_JOURNAL, RECOVERY_BUSINESS, RECOVERY_MAPPING, RECOVERY_ROOT, RECOVERY_SCOPE,
    RECOVERY_SLOT, RECOVERY_TASK, RECOVERY_USER, PrivateEnhancementService,
)
from app.services.learning.item_supply.private_generation_persistence import JOB_ID, OUTPUT_ID, PREPARATION_ID
from app.services.learning.item_supply.policies import RetryPolicyV1
from app.services.learning.item_supply.storage_contracts import checked_model


PHASE_KEY = 'private.persistence.phase.' + OUTPUT_ID.hex
PREFIX = 'item_supply_internal.private_generation_persistence_phase_'
BINDING_KEYS = frozenset(('schema_version', 'output_id', 'preparation_id', 'output_hash', 'original_binding_id',
    'original_started_id', 'original_consumed_id', 'original_settlement_id', 'generation_job_id',
    'generation_request_hash', 'generation_profile_hash', 'ref', 'writer_job_id', 'batch_id', 'lease',
    'source_origin_id', 'bound_top_xid', 'bound_at', 'valid_until'))
COMPLETION_KEYS = frozenset(('schema_version', 'binding_id', 'output_id', 'writer_job_id', 'artifact_id',
    'artifact_hash', 'candidate_id', 'version_id', 'checkpoint_id', 'source_origin_id', 'completed_top_xid', 'completed_at'))


@dataclass(frozen=True, repr=False)
class IssuedPrivateGenerationPersistencePhase:
    owner: PrivateGenerationPersistencePhaseOwner
    task: PersistentPackTaskRef
    output_id: UUID
    output_hash: str
    capture: dict[str, Any]
    ref: PrivateSlotRef
    request: GenerationRequestV2
    result: GenerationResultV2
    generation_lease: JobLeaseV1
    bridge_id: UUID
    bridge_hash: str
    writer_lease: JobLeaseV1


@dataclass(frozen=True, repr=False)
class PrivatePersistencePhaseContext:
    bridge: dict[str, Any]
    lease: JobLeaseV1
    valid_until: datetime


class PrivateGenerationPersistencePhaseOwner:
    def __init__(self, service: PrivateEnhancementService) -> None:
        if type(service) is not PrivateEnhancementService:
            raise PrivateNativePending('private_phase_original_service_required')
        self.service, self.conn, self.facts = service, service.conn, service.facts_owner
        self.pipeline = self.facts.pipeline
        self._issued: dict[UUID, tuple[IssuedPrivateGenerationPersistencePhase, str]] = {}

    def _guard(self) -> str:
        s = self.service
        if (s.conn is not self.conn or s.facts_owner is not self.facts or self.facts.pipeline is not self.pipeline
                or self.facts.conn is not self.conn or self.pipeline.conn is not self.conn
                or s.core.conn is not self.conn or self.facts.settings is not s.settings
                or self.facts.source_authority.connection is not self.conn
                or s.generation_persistence_phase_owner() is not self):
            raise PrivateNativePending('private_phase_original_owners_required')
        if self.conn.autocommit or self.conn.info.transaction_status != TransactionStatus.INTRANS:
            raise PrivateNativePending('private_phase_caller_top_required')
        s._guard()
        if not self.pipeline.generation_enabled or not s.development_accounting_enabled:
            raise PrivateNativePending('private_phase_original_features_required')
        s._generation_output_ready()
        ready = self.conn.execute('SELECT '+PREFIX+'ready() AS ready').fetchone()
        if ready is None or ready['ready'] is not True:
            raise PrivateNativePending('private_phase_receivers_required')
        row = self.conn.execute("SELECT pg_current_xact_id()::text AS top_xid, current_setting('transaction_isolation') AS isolation, current_setting('transaction_read_only') AS read_only").fetchone()
        if row is None or row['isolation'] != 'read committed' or row['read_only'] != 'off':
            raise PrivateNativePending('private_phase_caller_top_required')
        return str(row['top_xid'])

    def _journal(self, key: str) -> dict[str, Any] | None:
        return self.conn.execute('SELECT * FROM '+PRIVATE_JOURNAL+
            " WHERE pack_task_id=%s AND user_id=%s AND epoch=1 AND scope_id=%s AND record_kind='private_status' AND operation_key=%s FOR SHARE",
            (RECOVERY_TASK, RECOVERY_USER, RECOVERY_SCOPE, key)).fetchone()

    @staticmethod
    def _row(row: dict[str, Any], key: str, keys: frozenset[str], task: PersistentPackTaskRef) -> dict[str, Any]:
        body = row['payload_json']
        if (set(body) != keys or row['operation_key'] != key or row['record_kind'] != 'private_status'
                or (row['pack_task_id'], row['user_id'], row['epoch'], row['scope_id'], row['intent_hash'])
                != (task.pack_task_id, task.user_id, task.epoch, task.scope_id, task.intent_hash)
                or row['payload_hash'] != canonical_hash(body)):
            raise PrivateNativePending('private_phase_exact_journal_required')
        return body

    def _output(self) -> dict[str, Any]:
        row = self._journal('private.generation.output.'+PREPARATION_ID.hex)
        if (row is None or row['id'] != OUTPUT_ID or row['payload_hash'] != canonical_hash(row['payload_json'])
                or row['payload_json']['schema_version'] != 'private_generation_output_v1'
                or row['payload_json']['preparation_id'] != str(PREPARATION_ID)):
            raise PrivateNativePending('private_phase_fixed_output_required')
        committed = self.conn.execute('SELECT item_supply_internal.private_generation_output_committed(%s,%s) AS id',
            (PREPARATION_ID, Jsonb(row['payload_json']['capture']))).fetchone()
        if committed is None or committed['id'] != OUTPUT_ID:
            raise PrivateNativePending('private_phase_committed_output_required')
        return row

    def _generation(self, task: PersistentPackTaskRef, output: dict[str, Any]) -> tuple[PrivateSlotRef, GenerationRequestV2, GenerationResultV2, JobLeaseV1]:
        capture = output['payload_json']['capture']
        ctx = capture['context']
        ref = PrivateSlotRef.model_validate_json(json.dumps(ctx['ref']))
        request = GenerationRequestV2.model_validate_json(json.dumps(ctx['request']))
        result = GenerationResultV2.model_validate_json(json.dumps(capture['result']))
        lease = JobLeaseV1.model_validate_json(json.dumps(ctx['lease']))
        record = self.service.core._task(task)
        if (record.ref != task or record.enhancement != 'prefer_private'
                or not any((s.slot_id, s.logical_item_id, s.slot) == (RECOVERY_SLOT, RECOVERY_BUSINESS, 'practice-1') for s in record.slots)
                or (ref.pack_task_id, ref.user_id, ref.epoch, ref.scope_id, ref.mapping_receipt_id, ref.slot_id,
                    ref.business_item_id, ref.root_id, ref.slot, ref.parent_version_id)
                != (RECOVERY_TASK, RECOVERY_USER, 1, RECOVERY_SCOPE, RECOVERY_MAPPING, RECOVERY_SLOT, RECOVERY_BUSINESS, RECOVERY_ROOT, 'practice', None)
                or request.candidate_id != PREPARATION_ID or request.item_key != 'private-native.'+RECOVERY_BUSINESS.hex
                or request.version != 'v1' or lease.job_id != JOB_ID or lease.generation != 1
                or lease.visibility != 'private' or (lease.owner_id, lease.owner_epoch) != (RECOVERY_USER, 1)
                or ctx['scope_id'] != str(ref.scope_id) or ctx['attempt_bound'] != 1 or ctx['mode'] != 'live'
                or result.state != 'staged' or result.source is None or result.receipt is None):
            raise PrivateNativePending('private_phase_original_generation_required')
        source, receipt = result.source, result.receipt
        if (request.profile != lease.profile or source.blueprint != request.blueprint
                or (source.public.item_key, source.public.version) != (request.item_key, request.version)
                or receipt.candidate_id != request.candidate_id or receipt.scope_hash != request.scope_hash
                or receipt.source_hash != source.source_hash or receipt.content_hash != source.content_hash
                or [s.model_dump(mode='json') for s in receipt.sources] != ctx['sources']
                or receipt.provider.mode != 'provider' or receipt.provider.request_attempt_bound != 1
                or receipt.provider.usage.state != 'known' or receipt.provider.model != receipt.provider.configured_model
                or ctx['producer_binding'] != [receipt.provider.provider, receipt.provider.configured_model]):
            raise PrivateNativePending('private_phase_original_generation_required')
        return ref, request, result, lease

    def generation_spec(self, task: PersistentPackTaskRef, ref: PrivateSlotRef, request: GenerationRequestV2,
                        result: GenerationResultV2) -> FiniteCandidateSpecV1:
        """Historical DATA comparison; no expired lease enters a current factory."""
        record = self.service.core._task(task)
        slot = next(s for s in record.slots if s.slot_id == ref.slot_id)
        retained = self.service.core._versions(task)[slot.slot].published_version_id
        if retained is None:
            raise PrivateNativePending('private_phase_retained_spec_required')
        original = self.service.base_service.type_owner.resolve_content(retained, current=True).spec
        spec = build_finite_candidate_spec(target_id=original.target_id, variant_id=original.allocation.variant_id,
            seed=original.seed, item_key=request.item_key, version=request.version, materials=request.materials,
            runtime_profile_hash=None, scorer_version=original.coverage_blueprint.scope.scorer_version,
            assistance_policy_hash=original.coverage_blueprint.scope.assistance_policy_hash,
            policy_version=original.coverage_blueprint.policy_version, difficulty_profile=original.blueprint.difficulty_profile,
            publication_policy=original.blueprint.publication_policy, public_spec_version=request.blueprint.version, allocation=original.allocation)
        expected = build_finite_generation_request(spec, candidate_id=request.candidate_id, profile=request.profile,
            limits=request.limits, materials=request.materials)
        scope = self.conn.execute('SELECT scope_hash FROM tutor_item_supply_private_scopes WHERE id=%s AND user_id=%s AND epoch=%s',
            (ref.scope_id, ref.user_id, ref.epoch)).fetchone()
        if scope is None:
            raise PrivateNativePending('private_phase_original_scope_required')
        expected = checked_model(expected.model_copy(update={'scope_hash': scope['scope_hash']}), GenerationRequestV2)
        if expected != request or result.source is None:
            raise PrivateNativePending('private_phase_original_captured_spec_required')
        check_finite_public_spec(result.source.public, spec)
        return spec

    def issue(self, *, task_ref: PersistentPackTaskRef, output_id: UUID) -> IssuedPrivateGenerationPersistencePhase:
        task = checked_model(task_ref, PersistentPackTaskRef)
        if (type(output_id) is not UUID or output_id != OUTPUT_ID
                or (task.pack_task_id, task.user_id, task.epoch, task.scope_id, task.mapping_receipt_id)
                != (RECOVERY_TASK, RECOVERY_USER, 1, RECOVERY_SCOPE, RECOVERY_MAPPING)):
            raise PrivateNativePending('private_phase_fixed_output_required')
        top = self._guard()
        # SQL551 requires new nominal limits in the caller TOP, not a subxid.
        # The caller owns atomic A and must roll it back on any issue failure.
        output = self._output()
        if self._journal(PHASE_KEY) is not None:
            raise PrivateNativePending('private_phase_already_bound')
        ref, request, result, generation_lease = self._generation(task, output)
        actual = self.service._recovery_source(task)
        actual.require()
        if request.materials != actual.public_materials or result.receipt is None:
            raise PrivateNativePending('private_phase_exact_current_materials_required')
        for material, receipt in zip(request.materials, result.receipt.sources, strict=True):
            self.facts.source_authority.assert_current(material, receipt)
        spec = self.generation_spec(task, ref, request, result)
        fallback = self.service.base_fallback_owner()
        fallback.require(fallback.resolve(task))
        executor = self.service.executor()
        if executor.development_accounting_enabled is not self.service.development_accounting_enabled:
            raise PrivateNativePending('private_phase_original_accounting_required')
        accounting = PrivateDevelopmentModelAccountingOwner(self.conn, enabled=True)
        now = self.service._guard()
        batch = accounting.prepare_batch(root_id=ref.root_id, user_id=task.user_id, epoch=task.epoch, scope_id=task.scope_id,
            provider_key=executor.provider.provider_key, model=executor.provider.configured_model,
            now=now, valid_until=now+timedelta(seconds=7200))
        profile = executor._profile(spec, request.materials, phase_kind='persistence_quality')
        now = self.service._guard()
        deadline = min(actual.source_deadline, batch.valid_until)
        milliseconds = min(profile.last_stable.parent_deadline_ms,
            int((deadline-now).total_seconds()*1000)-profile.last_stable.request_timeout_ms)
        if milliseconds < profile.last_stable.request_timeout_ms:
            raise PrivateNativePending('private_phase_current_window_required')
        values = checked_model(profile.last_stable.model_copy(update={
            'stage_deadline_ms': milliseconds, 'parent_deadline_ms': milliseconds}), ParameterValuesV1)
        profile = checked_model(profile.model_copy(update={key: values for key in
            ('initial', 'current', 'last_stable', 'floor', 'ceiling')}), ExecutionParameterProfileV1)
        job = self.pipeline.runtime.enqueue(root_id=ref.root_id, stage_key=PHASE_KEY, profile=profile, now=now,
            priority=80, aging_seconds=86400, visibility='private', user_id=task.user_id, epoch=task.epoch, scope_id=task.scope_id,
            parent_job_id=None, retry_policy=RetryPolicyV1(max_transient_attempts=1, initial_backoff_ms=1, maximum_backoff_ms=1))
        rows = self.conn.execute('SELECT claimed.* FROM '+PREFIX+'first_claim(%s,%s,%s,%s) AS claimed',
            (OUTPUT_ID, job, batch.batch_id, actual.origin_id())).fetchall()
        if len(rows) != 1 or rows[0]['job_id'] != job:
            raise PrivateNativePending('private_phase_exact_first_claim_required')
        lease = self.pipeline.runtime._lease(rows[0], 'private')
        self.pipeline.runtime._control(lease, now=self.service._guard())
        accounting.bind_job(lease=lease, batch_id=batch.batch_id, parent_job_id=None, now=self.service._guard())
        if self.service.bind_slot_phase(task_ref=task, slot_id=ref.slot_id, lease=lease, parent_version_id=None) != ref:
            raise PrivateNativePending('private_phase_exact_original_ref_required')
        self.service.record_wait_window(task_ref=task, lease=lease)
        bridge = self._journal(PHASE_KEY)
        if bridge is None or bridge['payload_json']['bound_top_xid'] != top:
            raise PrivateNativePending('private_phase_issued_binding_required')
        cap = IssuedPrivateGenerationPersistencePhase(self, task, OUTPUT_ID, output['payload_hash'],
            json.loads(json.dumps(output['payload_json']['capture'])), ref, request, result, generation_lease,
            bridge['id'], bridge['payload_hash'], lease)
        self._binding(cap, bridge, output)
        self._current(cap, bridge)
        # A rollback never grants B: every use re-reads the SQL binding and TOP.
        self._issued[cap.bridge_id] = (cap, self._seal(cap))
        return cap

    @staticmethod
    def _seal(cap: IssuedPrivateGenerationPersistencePhase) -> str:
        return canonical_hash(dict(task=cap.task.model_dump(mode='json'), output_id=str(cap.output_id), output_hash=cap.output_hash,
            capture=cap.capture, ref=cap.ref.model_dump(mode='json'), request=cap.request.model_dump(mode='json'),
            result=cap.result.model_dump(mode='json'), generation_lease=cap.generation_lease.model_dump(mode='json'),
            bridge_id=str(cap.bridge_id), bridge_hash=cap.bridge_hash, writer_lease=cap.writer_lease.model_dump(mode='json')))

    def require_identity(self, cap: IssuedPrivateGenerationPersistencePhase) -> None:
        saved = self._issued.get(cap.bridge_id) if type(cap) is IssuedPrivateGenerationPersistencePhase else None
        if saved is None or cap.owner is not self or saved[0] is not cap or saved[1] != self._seal(cap):
            raise PrivateNativePending('private_phase_original_cap_required')

    def _binding(self, cap: IssuedPrivateGenerationPersistencePhase, bridge: dict[str, Any], output: dict[str, Any]) -> None:
        body = self._row(bridge, PHASE_KEY, BINDING_KEYS, cap.task)
        original = output['payload_json']
        expected = dict(schema_version='private_generation_persistence_phase_v1', output_id=str(OUTPUT_ID),
            preparation_id=str(PREPARATION_ID), output_hash=cap.output_hash, generation_job_id=str(JOB_ID),
            generation_request_hash=canonical_hash(cap.request.model_dump(mode='json')),
            generation_profile_hash=cap.generation_lease.profile.profile_hash, ref=cap.ref.model_dump(mode='json'),
            writer_job_id=str(cap.writer_lease.job_id), lease=cap.writer_lease.model_dump(mode='json'),
            **{'original_'+name: original[name] for name in ('binding_id', 'started_id', 'consumed_id', 'settlement_id')})
        if (bridge['id'] != cap.bridge_id or bridge['payload_hash'] != cap.bridge_hash
                or any(body[key] != value for key, value in expected.items())
                or output['payload_hash'] != cap.output_hash or original['capture'] != cap.capture):
            raise PrivateNativePending('private_phase_binding_changed')

    def _current(self, cap: IssuedPrivateGenerationPersistencePhase, bridge: dict[str, Any]) -> PrivatePersistencePhaseContext:
        actual = self.service._recovery_source(cap.task)
        lease = self.pipeline.runtime.refresh_lease(cap.writer_lease, now=self.service._guard())
        if (lease.model_dump(mode='json', exclude={'state_version'}) != cap.writer_lease.model_dump(mode='json', exclude={'state_version'})
                or lease.job_id == JOB_ID or lease.generation != 1 or lease.state_version < cap.writer_lease.state_version):
            raise PrivateNativePending('private_phase_exact_current_writer_required')
        now = self.facts._guard(cap.ref, lease)
        batch = accounting_batch_for_lease(self.conn, lease, now=now)
        if batch is None or str(batch['batch_id']) != bridge['payload_json']['batch_id']:
            raise PrivateNativePending('private_phase_original_accounting_required')
        receipt = cap.result.receipt
        if receipt is None or list(self.pipeline._provider_binding(lease, receipt.provider.provider,
                receipt.provider.configured_model)) != cap.capture['context']['producer_binding']:
            raise PrivateNativePending('private_phase_original_provider_required')
        for material, expected in zip(cap.request.materials, receipt.sources, strict=True):
            self.facts.source_authority.assert_current(material, expected)
        source = self.conn.execute('SELECT item_supply_internal.private_native_source_current(%s) AS ok',
            (Jsonb(dict(ref=cap.ref.model_dump(mode='json'), request=cap.request.model_dump(mode='json'),
                source_receipts=[s.model_dump(mode='json') for s in receipt.sources])),)).fetchone()
        if source is None or source['ok'] is not True:
            raise PrivateNativePending('private_phase_original_source_required')
        valid_until = min(lease.expires_at, lease.parent_deadline, batch['valid_until'], actual.source_deadline,
            lease.profile.bound_at+timedelta(milliseconds=lease.profile.values.stage_deadline_ms),
            datetime.fromisoformat(bridge['payload_json']['valid_until']))
        context = PrivatePersistencePhaseContext(bridge, lease, valid_until)
        self._postwait(cap, context)
        return context

    def _postwait(self, cap: IssuedPrivateGenerationPersistencePhase, current: PrivatePersistencePhaseContext) -> None:
        self.service._recovery_source(cap.task).require()
        if self.facts._guard(cap.ref, current.lease) >= current.valid_until:
            raise PrivateNativePending('private_phase_current_writer_expired')

    def require(self, cap: IssuedPrivateGenerationPersistencePhase) -> PrivatePersistencePhaseContext:
        self.require_identity(cap)
        top = self._guard()
        output = self._output()
        rows = self.conn.execute('SELECT bound.* FROM '+PREFIX+'bound(%s,%s) AS bound',
            (cap.bridge_id, self.service._recovery_source(cap.task).origin_id())).fetchall()
        if len(rows) != 1 or rows[0]['payload_json']['bound_top_xid'] == top:
            raise PrivateNativePending('private_phase_prior_binding_top_required')
        self._binding(cap, rows[0], output)
        return self._current(cap, rows[0])

    def _bundle(self, cap: IssuedPrivateGenerationPersistencePhase, completion: dict[str, Any]) -> dict[str, Any]:
        body = self._row(completion, PHASE_KEY+'.complete', COMPLETION_KEYS, cap.task)
        artifact = self.conn.execute('SELECT a.*,c.candidate_key AS storage_key,v.version AS storage_version,v.public_json,v.private_json '
            'FROM tutor_item_supply_private_generation_artifacts a JOIN tutor_item_supply_private_candidates c ON c.id=a.candidate_id '
            'JOIN tutor_item_supply_private_versions v ON v.id=a.version_id AND v.candidate_id=c.id '
            'WHERE a.id=%s AND a.job_id=%s AND a.lease_generation=1 AND a.user_id=%s AND a.epoch=1 AND a.scope_id=%s FOR SHARE OF a,c,v',
            (UUID(body['artifact_id']), cap.writer_lease.job_id, RECOVERY_USER, RECOVERY_SCOPE)).fetchone()
        checkpoint = self.conn.execute('SELECT id,stage,attempt,status,lease_generation,receipt_hash,safe_reason FROM tutor_item_supply_private_checkpoints '
            "WHERE job_id=%s AND user_id=%s AND epoch=1 AND scope_id=%s AND stage='generating' AND attempt=1",
            (cap.writer_lease.job_id, RECOVERY_USER, RECOVERY_SCOPE)).fetchone()
        source, receipt = cap.result.source, cap.result.receipt
        if artifact is None or checkpoint is None or source is None or receipt is None:
            raise PrivateNativePending('private_phase_complete_bundle_required')
        digest = canonical_hash(dict(source=source.model_dump(mode='json'), receipt=receipt.model_dump(mode='json')))
        expected = dict(schema_version='private_generation_persistence_complete_v1', binding_id=str(cap.bridge_id), output_id=str(OUTPUT_ID),
            writer_job_id=str(cap.writer_lease.job_id), artifact_id=str(artifact['id']), artifact_hash=digest,
            candidate_id=str(artifact['candidate_id']), version_id=str(artifact['version_id']), checkpoint_id=str(checkpoint['id']))
        if (any(body[key] != value for key, value in expected.items()) or artifact['mode'] != 'live'
                or artifact['artifact_key'] != 'generation.'+PREPARATION_ID.hex or artifact['artifact_hash'] != digest
                or artifact['request_json'] != cap.request.model_dump(mode='json') or artifact['source_json'] != source.model_dump(mode='json')
                or artifact['receipt_json'] != receipt.model_dump(mode='json') or artifact['source_hash'] != source.source_hash
                or artifact['content_hash'] != source.content_hash or artifact['storage_key'] != 'private.native.'+RECOVERY_BUSINESS.hex
                or artifact['storage_version'] != 1 or artifact['public_json'] != source.public.model_dump(mode='json')
                or artifact['private_json'] != source.private.model_dump(mode='json')
                or {k: v for k, v in checkpoint.items() if k != 'id'} != dict(stage='generating', attempt=1, status='completed',
                    lease_generation=1, receipt_hash=digest, safe_reason='candidate_staged')):
            raise PrivateNativePending('private_phase_exact_bundle_required')
        return artifact

    def persist(self, cap: IssuedPrivateGenerationPersistencePhase) -> UUID:
        current = self.require(cap)
        with self.conn.transaction():
            completion = self._journal(PHASE_KEY+'.complete')
            if completion is None:
                partial = self.conn.execute('SELECT id FROM tutor_item_supply_private_generation_artifacts WHERE job_id=%s '
                    'UNION ALL SELECT id FROM tutor_item_supply_private_checkpoints WHERE job_id=%s LIMIT 1',
                    (cap.writer_lease.job_id, cap.writer_lease.job_id)).fetchone()
                if partial is not None:
                    raise PrivateNativePending('private_phase_partial_bundle_denied')
                if self.pipeline.runtime.next_stage(current.lease) != 'generating':
                    raise PrivateNativePending('private_phase_generating_stage_required')
                artifact = self.pipeline.artifacts.store_generation(lease=current.lease, scope_id=cap.ref.scope_id,
                    request=cap.request, result=cap.result, artifact_key='generation.'+PREPARATION_ID.hex,
                    now=self.facts._guard(cap.ref, current.lease), mode='live', source_authority=self.facts.source_authority,
                    private_slot_ref=cap.ref, persistence_phase=cap)
                self.pipeline.runtime.checkpoint(current.lease, CheckpointV1(stage='generating', attempt=1, status='completed',
                    receipt_hash=artifact['artifact_hash'], safe_reason='candidate_staged'), now=self.service._guard())
                current = self.require(cap)
                artifact_id = artifact['id']
            else:
                artifact_id = UUID(completion['payload_json']['artifact_id'])
            completed = self.conn.execute('SELECT '+PREFIX+'complete(%s,%s,%s) AS id',
                (cap.bridge_id, artifact_id, self.service._recovery_source(cap.task).origin_id())).fetchone()
            completion = self._journal(PHASE_KEY+'.complete')
            if completed is None or completion is None or completed['id'] != completion['id']:
                raise PrivateNativePending('private_phase_completion_required')
            artifact = self._bundle(cap, completion)
            self._postwait(cap, current)
        return UUID(str(artifact['id']))

    def committed_artifact(self, cap: IssuedPrivateGenerationPersistencePhase) -> tuple[PrivatePersistencePhaseContext, dict[str, Any]]:
        current = self.require(cap)
        top = self._guard()
        rows = self.conn.execute('SELECT completed.* FROM '+PREFIX+'committed(%s,%s) AS completed',
            (cap.bridge_id, self.service._recovery_source(cap.task).origin_id())).fetchall()
        if (len(rows) != 1 or rows[0]['payload_json']['completed_top_xid'] in (top, current.bridge['payload_json']['bound_top_xid'])):
            raise PrivateNativePending('private_phase_prior_completion_top_required')
        artifact = self._bundle(cap, rows[0])
        self._postwait(cap, current)
        return current, artifact
