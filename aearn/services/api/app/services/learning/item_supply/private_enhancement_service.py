"""Explicit PRIVATE same-task composition. No global rollout or restored JSON caps.

Original runtime owns jobs, finite phases and paid reservations. This owner binds
those actual PRIVATE leases to B523 fixed slots and uses original pipeline writes.
ensure_supply is zero-network and does not terminate work when consumer wait ends.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from app.core.config import Settings
from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_bank.private_native_publication import PrivateNativePublicationOwner
from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1
from app.services.learning.item_supply.generation_contracts import GenerationLimitsV2, GenerationResultV2, PublicMaterialV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.native_supply_service import NativeSupplyService
from app.services.learning.item_supply.native_supply_service_contracts import NativeSupplyDemandRef, NativeSupplyLearnerStatusV1
from app.services.learning.item_supply.native_type_contracts import NativeResolvedContent
from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
from app.services.learning.item_supply.persistent_pack_contracts import PersistentPackTaskRef
from app.services.learning.item_supply.pipeline import PreparedGeneration
from app.services.learning.item_supply.private_enhancement_contracts import (
    PrivateEnhancementReady, PrivateEnhancementResult, PrivateNativePending, PrivateSlotRef, PrivateTeachingDeliveryContext,
)
from app.services.learning.item_supply.private_finite_factory import build_private_generation_request
from app.services.learning.item_supply.private_generation_durability import (
    C14_GAP_BINDING, LOST_C14_CANDIDATE, ObservedPrivateGeneration, PrivateGenerationCaptureOutcome, generation_context,
)
from app.services.learning.item_supply.private_native_admission_facts import PrivateNativeAdmissionFactsOwner
from app.services.learning.item_supply.private_native_exposure import PrivateNativeExposureOwner, PrivateExposureObservation
from app.services.learning.item_supply.private_native_type_evidence import PrivateNativeTypeEvidenceOwner
from app.services.learning.item_supply.provider_adapter import OpenAICompatibleGenerationProvider
from app.services.learning.item_supply.storage_contracts import checked_model


if TYPE_CHECKING:
    from app.services.learning.item_supply.private_generation_persistence_phase import PrivateGenerationPersistencePhaseOwner
    from app.services.learning.item_supply.private_generation_persistence import PrivateGenerationPersistenceOwner
    from app.services.learning.item_supply.persistent_pack_current_source import IssuedCurrentPackSourceBinding
    from app.services.learning.item_supply.private_native_pack_executor import PrivateNativePackExecutor


@dataclass(frozen=True)
class PreparedPrivateSlotGeneration:
    ref: PrivateSlotRef
    original: PreparedGeneration


RECOVERY_KEY = 'p7.private.initial-author.recovery.20261015.once1'
CONTINUATION_KEY = 'p7.private.initial-author.continuation.20261016'
CONTINUATION_FIRST_FAILURE = UUID('df0a6e8c-287a-4814-98f1-5deeb59347a3')
RECOVERY_TASK = UUID('6739d3c5-6619-44ce-970f-0ab1e49f3acc')
RECOVERY_USER = UUID('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe')
RECOVERY_SCOPE = UUID('cef6af15-84c0-466a-b330-3dc3235aa587')
RECOVERY_MAPPING = UUID('d8e34e01-3514-41a3-9bbd-55ee3e627134')
RECOVERY_SLOT = UUID('f2b5a6dd-97d2-52dd-8962-68962f6ea76c')
RECOVERY_BUSINESS = UUID('7e9c4444-5b16-53c1-ad8b-39b402e5aa51')
RECOVERY_ROOT = UUID('aaaf99e5-4530-4319-bb1a-0fe6d84020f9')
RECOVERY_OLD_JOB = UUID('487b12c4-f98a-41c9-a21b-abb9243a28dd')
RECOVERY_OLD_CANDIDATE = UUID('17458037-ad0c-46d8-8c3b-a621bee386f1')
RECOVERY_OLD_STARTED = UUID('5ad70ab7-0441-456b-ae5e-156755a80911')
PRIVATE_JOURNAL = 'tutor_item_supply_private_persistent_pack_journal'


@dataclass(frozen=True)
class IssuedPrivateInitialAuthorRecovery:
    owner: PrivateEnhancementService
    task: PersistentPackTaskRef
    slot_id: UUID
    approval_id: UUID
    authorization_key: str = RECOVERY_KEY
    predecessor_failure_id: UUID | None = None


class PrivateEnhancementService:
    def __init__(self, conn: Connection[dict[str, Any]], settings: Settings, *,
                 core: PersistentPackTaskOwner, base_service: NativeSupplyService,
                 facts_owner: PrivateNativeAdmissionFactsOwner,
                 publication_owner: PrivateNativePublicationOwner,
                 type_owner: PrivateNativeTypeEvidenceOwner,
                 exposure_owner: PrivateNativeExposureOwner, enabled: bool = False,
                 development_accounting_enabled: bool = False) -> None:
        if (type(core) is not PersistentPackTaskOwner or type(base_service) is not NativeSupplyService
                or type(facts_owner) is not PrivateNativeAdmissionFactsOwner
                or type(publication_owner) is not PrivateNativePublicationOwner
                or type(type_owner) is not PrivateNativeTypeEvidenceOwner
                or type(exposure_owner) is not PrivateNativeExposureOwner
                or any(o.conn is not conn for o in (core,base_service,facts_owner,publication_owner,type_owner,exposure_owner))
                or any(o.settings is not settings for o in (core,base_service,facts_owner,publication_owner,type_owner))
                or base_service.persistent_owner is not core or core.type_owner is not base_service.type_owner
                or exposure_owner.public_owner is not base_service.exposure_owner
                or exposure_owner.type_owner is not type_owner
                or type_owner.public_owner is not base_service.type_owner
                or publication_owner.facts_owner is not facts_owner
                or facts_owner.mapping_owner is not type_owner.mapping_owner
                or type_owner.mapping_owner is not base_service.type_owner.mapping_owner
                or facts_owner.source_authority is not type_owner.query.source_authority
                or facts_owner.source_authority is not base_service.type_owner.source_authority
                or (type_owner.user_id,type_owner.epoch)!=(base_service.user_id,base_service.epoch)):
            raise PrivateNativePending('private_service_original_same_connection_owners_required')
        if type(development_accounting_enabled) is not bool:
            raise PrivateNativePending('private_service_explicit_accounting_flag_required')
        facts_owner.bind_type_owner(type_owner)
        self.conn,self.settings,self.core,self.base_service=conn,settings,core,base_service
        self.facts_owner,self.publication_owner,self.type_owner,self.exposure_owner=facts_owner,publication_owner,type_owner,exposure_owner
        self.enabled=enabled
        self.development_accounting_enabled=development_accounting_enabled
        self._prepared: dict[UUID,tuple[PreparedPrivateSlotGeneration,str,OpenAICompatibleGenerationProvider]]={}
        self._started: set[UUID]=set()
        self._results: dict[UUID,GenerationResultV2]={}
        self._observed_generation_outputs: dict[UUID,ObservedPrivateGeneration] = {}
        self._generation_persistence: PrivateGenerationPersistenceOwner | None = None
        self._generation_persistence_phase: PrivateGenerationPersistencePhaseOwner | None = None
        self._executor: PrivateNativePackExecutor | None = None
        self._fallback: Any = None
        self._recoveries: dict[UUID,tuple[IssuedPrivateInitialAuthorRecovery,str,PersistentPackTaskOwner]] = {}
        self._recovery_bindings: dict[UUID,tuple[PreparedPrivateSlotGeneration,IssuedPrivateInitialAuthorRecovery,UUID]] = {}
        self._recovery_sources: dict[UUID,IssuedCurrentPackSourceBinding] = {}

    def _recovery_receivers(self) -> None:
        signatures = (
            'private_initial_author_recovery_anchor(uuid,uuid,bigint,uuid)',
            'private_initial_author_recovery_source(uuid)',
            'private_initial_author_recovery_bound(uuid,uuid,boolean)',
            'private_initial_author_recovery_first_claim(uuid,uuid,uuid,uuid,text)',
            'private_initial_author_recovery_consume(uuid,uuid)',
            'private_initial_author_recovery_terminal(uuid)',
            'private_initial_author_failure_committed(uuid,uuid,uuid,bigint,uuid)',
            'enforce_private_initial_author_recovery_insert()',
            'enforce_private_initial_author_recovery_auxiliary()',
            'enforce_private_initial_author_recovery_control()',
        )
        row = self.conn.execute('SELECT count(*) AS n FROM unnest(%s::text[]) AS requested(signature) '
            "JOIN pg_proc p ON p.oid=to_regprocedure('item_supply_internal.'||requested.signature) "
            "WHERE p.prosecdef AND p.prokind='f' AND p.provolatile='v' AND p.proowner='aearn_b1d_runtime_20261001'::regrole "
            "AND p.proacl=ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[] "
            "AND p.proconfig=ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']",(list(signatures),)).fetchone()
        if row is None or row['n'] != len(signatures):
            raise PrivateNativePending('private_recovery_555_receivers_required')
        row = self.conn.execute("SELECT count(*) AS n FROM pg_trigger WHERE NOT tgisinternal AND tgenabled='O' AND "
            "((tgrelid='tutor_item_supply_private_persistent_pack_journal'::regclass AND "
            "((tgname='private_initial_author_recovery_insert' AND tgtype=7 AND NOT tgdeferrable AND tgfoid=to_regprocedure('item_supply_internal.enforce_private_initial_author_recovery_insert()')) OR "
            "(tgname='private_initial_author_recovery_auxiliary' AND tgtype=5 AND tgdeferrable AND tginitdeferred AND tgfoid=to_regprocedure('item_supply_internal.enforce_private_initial_author_recovery_auxiliary()')))) OR "
            "(tgrelid='tutor_item_supply_private_job_controls'::regclass AND tgname='private_initial_author_recovery_control' AND tgtype=19 AND NOT tgdeferrable "
            "AND tgfoid=to_regprocedure('item_supply_internal.enforce_private_initial_author_recovery_control()')))").fetchone()
        if row is None or row['n'] != 3:
            raise PrivateNativePending('private_recovery_555_receivers_required')

    def _generation_output_ready(self) -> None:
        if self.conn.autocommit or self.conn.info.transaction_status != TransactionStatus.INTRANS:
            raise PrivateNativePending('private_generation_caller_transaction_required')
        row = self.conn.execute('SELECT item_supply_internal.private_generation_durability_ready() AS ready').fetchone()
        if row is None or row['ready'] is not True:
            raise PrivateNativePending('private_generation_560_receivers_required')

    def issue_initial_author_persistence_gap(self, task_ref: PersistentPackTaskRef, binding_id: UUID) -> UUID:
        """Issue only the fixed expired C14 factual gap; never restore an author."""
        self._guard()
        task_ref = checked_model(task_ref, PersistentPackTaskRef)
        if (type(self) is not PrivateEnhancementService or not self.development_accounting_enabled
                or type(binding_id) is not UUID or binding_id != C14_GAP_BINDING
                or (task_ref.pack_task_id,task_ref.user_id,task_ref.epoch,task_ref.scope_id,task_ref.mapping_receipt_id)
                != (RECOVERY_TASK,RECOVERY_USER,1,RECOVERY_SCOPE,RECOVERY_MAPPING)):
            raise PrivateNativePending('private_generation_exact_persistence_gap_required')
        self._generation_output_ready()
        record = self.core._task(task_ref)
        if record.enhancement != 'prefer_private' or not any(
                (s.slot_id,s.logical_item_id,s.slot)==(RECOVERY_SLOT,RECOVERY_BUSINESS,'practice-1') for s in record.slots):
            raise PrivateNativePending('private_generation_exact_persistence_gap_required')
        # No old lease/source refresh: SQL derives historical identity, natural
        # expiry and absent durable output under the original namespace locks.
        row = self.conn.execute('SELECT item_supply_internal.private_initial_author_persistence_gap_issue(%s,%s,%s,%s,%s) AS id',
            (task_ref.pack_task_id,task_ref.user_id,task_ref.epoch,task_ref.scope_id,binding_id)).fetchone()
        if row is None or type(row['id']) is not UUID:
            raise PrivateNativePending('private_generation_persistence_gap_not_issued')
        return row['id']

    def _continuation_receivers(self) -> None:
        self._recovery_receivers()
        signatures = (
            'private_initial_author_continuation_failure_committed(uuid,uuid,uuid,bigint,uuid)',
            'private_initial_author_continuation_predecessor(uuid,uuid,uuid,bigint,uuid)',
            'private_initial_author_continuation_approval(uuid)',
            'private_initial_author_continuation_bound(uuid,uuid,boolean)',
            'private_initial_author_continuation_first_claim(uuid,uuid,uuid,uuid,text)',
            'private_initial_author_continuation_consume(uuid,uuid)',
            'private_initial_author_continuation_auxiliary(uuid)',
            'private_initial_author_continuation_terminal(uuid)',
            'enforce_private_initial_author_continuation_insert()',
            'enforce_private_initial_author_continuation_control()',
        )
        row = self.conn.execute('SELECT count(*) AS n FROM unnest(%s::text[]) AS requested(signature) '
            "JOIN pg_proc p ON p.oid=to_regprocedure('item_supply_internal.'||requested.signature) "
            "WHERE p.prosecdef AND p.prokind='f' AND p.provolatile='v' AND p.proowner='aearn_b1d_runtime_20261001'::regrole "
            "AND p.proacl=ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[] "
            "AND p.proconfig=ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']", (list(signatures),)).fetchone()
        triggers = self.conn.execute("SELECT count(*) AS n FROM pg_trigger WHERE NOT tgisinternal AND tgenabled='O' "
            "AND NOT tgdeferrable AND NOT tginitdeferred AND ((tgrelid='tutor_item_supply_private_persistent_pack_journal'::regclass "
            "AND tgname='private_initial_author_continuation_insert' AND tgtype=7 "
            "AND tgfoid=to_regprocedure('item_supply_internal.enforce_private_initial_author_continuation_insert()')) OR "
            "(tgrelid='tutor_item_supply_private_job_controls'::regclass AND tgname='private_initial_author_continuation_control' "
            "AND tgtype=19 AND tgfoid=to_regprocedure('item_supply_internal.enforce_private_initial_author_continuation_control()'))) ").fetchone()
        if row is None or row['n'] != len(signatures) or triggers is None or triggers['n'] != 2:
            raise PrivateNativePending('private_continuation_558_receivers_required')

    @staticmethod
    def _initial_author_key(cap: IssuedPrivateInitialAuthorRecovery) -> str:
        if cap.authorization_key == RECOVERY_KEY and cap.predecessor_failure_id is None:
            return RECOVERY_KEY
        if cap.authorization_key == CONTINUATION_KEY and type(cap.predecessor_failure_id) is UUID:
            return CONTINUATION_KEY+'.'+cap.predecessor_failure_id.hex
        raise PrivateNativePending('private_recovery_original_issued_cap_required')

    @staticmethod
    def _initial_author_protocol(cap: IssuedPrivateInitialAuthorRecovery) -> str:
        PrivateEnhancementService._initial_author_key(cap)
        return 'continuation' if cap.authorization_key == CONTINUATION_KEY else 'recovery'

    def _recovery_source(self, task: PersistentPackTaskRef) -> IssuedCurrentPackSourceBinding:
        from app.services.learning.item_supply.native_type_evidence import NativeTypeEvidenceOwner
        from app.services.learning.item_supply.persistent_pack_current_source import IssuedCurrentPackSourceBinding
        if self.core is not self.base_service.persistent_owner or self.core.type_owner is not self.type_owner.public_owner:
            raise PrivateNativePending('private_recovery_original_core_required')
        actual = NativeTypeEvidenceOwner._source_binding(self.base_service.type_owner)
        if type(actual) is not IssuedCurrentPackSourceBinding or actual.owner is not self.core or actual.task != task:
            raise PrivateNativePending('private_recovery_fresh_original_source_required')
        actual.require()
        return actual

    @contextmanager
    def _fresh_recovery_source(self, task: PersistentPackTaskRef) -> Iterator[IssuedCurrentPackSourceBinding]:
        from app.services.learning.item_supply.persistent_pack_current_source import SOURCE_DATA
        actual = self.core.issue_current_source_binding(task, source_data_id=SOURCE_DATA)
        public = self.base_service.type_owner
        public.attach_current_source_binding(actual)
        try:
            with actual.current_scope():
                self._recovery_source(task)
                yield actual
        finally:
            public.current_source_binding = None

    def issue_initial_author_recovery(self, *, task_ref: PersistentPackTaskRef, slot_id: UUID) -> IssuedPrivateInitialAuthorRecovery:
        now = self._guard()
        task_ref = checked_model(task_ref, PersistentPackTaskRef)
        if (type(self) is not PrivateEnhancementService or not self.development_accounting_enabled
                or (task_ref.pack_task_id,task_ref.user_id,task_ref.epoch,task_ref.scope_id,task_ref.mapping_receipt_id,slot_id)
                != (RECOVERY_TASK,RECOVERY_USER,1,RECOVERY_SCOPE,RECOVERY_MAPPING,RECOVERY_SLOT)):
            raise PrivateNativePending('private_recovery_exact_approved_task_required')
        self._recovery_receivers()
        source = self._recovery_source(task_ref)
        record = self.core._task(task_ref)
        if record.enhancement != 'prefer_private' or not any(
                (s.slot_id,s.logical_item_id,s.slot)==(RECOVERY_SLOT,RECOVERY_BUSINESS,'practice-1') for s in record.slots):
            raise PrivateNativePending('private_recovery_exact_approved_task_required')
        if self.conn.execute('SELECT id FROM '+PRIVATE_JOURNAL+' WHERE user_id=%s AND epoch=1 AND operation_key=%s',
                (RECOVERY_USER,RECOVERY_KEY+'.approval')).fetchone() is not None:
            raise PrivateNativePending('private_recovery_already_issued')
        payload = dict(schema_version='private_initial_author_recovery_approval_v1',authorization_key=RECOVERY_KEY,
            old_started_id=str(RECOVERY_OLD_STARTED),old_job_id=str(RECOVERY_OLD_JOB),old_candidate_id=str(RECOVERY_OLD_CANDIDATE),
            slot_id=str(RECOVERY_SLOT),business_item_id=str(RECOVERY_BUSINESS),root_id=str(RECOVERY_ROOT),
            mapping_receipt_id=str(RECOVERY_MAPPING),item_key='private-native.'+RECOVERY_BUSINESS.hex,version='v1',
            candidate_key='private.native.'+RECOVERY_BUSINESS.hex,storage_version=1,issued_at=now.isoformat())
        approval = self.core._private_event(task_ref,'private_status',payload,key=RECOVERY_KEY+'.approval')
        cap = IssuedPrivateInitialAuthorRecovery(self,task_ref,slot_id,approval)
        self._recoveries[approval]=(cap,canonical_hash(payload),self.core)
        self._recovery_sources[approval]=source
        return cap

    def issue_initial_author_continuation(self, *, task_ref: PersistentPackTaskRef, slot_id: UUID,
                                         predecessor_failure_id: UUID) -> IssuedPrivateInitialAuthorRecovery:
        now = self._guard()
        task_ref = checked_model(task_ref, PersistentPackTaskRef)
        if (type(self) is not PrivateEnhancementService or not self.development_accounting_enabled
                or type(predecessor_failure_id) is not UUID
                or (task_ref.pack_task_id,task_ref.user_id,task_ref.epoch,task_ref.scope_id,task_ref.mapping_receipt_id,slot_id)
                != (RECOVERY_TASK,RECOVERY_USER,1,RECOVERY_SCOPE,RECOVERY_MAPPING,RECOVERY_SLOT)):
            raise PrivateNativePending('private_recovery_exact_approved_task_required')
        self._continuation_receivers()
        source = self._recovery_source(task_ref)
        record = self.core._task(task_ref)
        if record.enhancement != 'prefer_private' or not any(
                (s.slot_id,s.logical_item_id,s.slot)==(RECOVERY_SLOT,RECOVERY_BUSINESS,'practice-1') for s in record.slots):
            raise PrivateNativePending('private_recovery_exact_approved_task_required')
        # The receiver locks the original namespace/task/root/predecessor and
        # verifies its committed failure lineage. File/UUID DATA grants nothing.
        predecessor = self.conn.execute('SELECT original.* FROM item_supply_internal.private_initial_author_continuation_predecessor(%s,%s,%s,%s,%s) AS original',
            (predecessor_failure_id,task_ref.pack_task_id,task_ref.user_id,task_ref.epoch,task_ref.scope_id)).fetchone()
        if predecessor is None or predecessor['id'] != predecessor_failure_id:
            raise PrivateNativePending('private_continuation_committed_predecessor_required')
        key = CONTINUATION_KEY+'.'+predecessor_failure_id.hex
        if self.conn.execute('SELECT id FROM '+PRIVATE_JOURNAL+' WHERE user_id=%s AND epoch=1 AND operation_key=%s',
                (RECOVERY_USER,key+'.approval')).fetchone() is not None:
            raise PrivateNativePending('private_continuation_successor_already_issued')
        payload = dict(schema_version='private_initial_author_continuation_approval_v1',authorization_key=CONTINUATION_KEY,
            predecessor_failure_id=str(predecessor_failure_id),old_started_id=str(RECOVERY_OLD_STARTED),
            old_job_id=str(RECOVERY_OLD_JOB),old_candidate_id=str(RECOVERY_OLD_CANDIDATE),slot_id=str(RECOVERY_SLOT),
            business_item_id=str(RECOVERY_BUSINESS),root_id=str(RECOVERY_ROOT),mapping_receipt_id=str(RECOVERY_MAPPING),
            item_key='private-native.'+RECOVERY_BUSINESS.hex,version='v1',candidate_key='private.native.'+RECOVERY_BUSINESS.hex,
            storage_version=1,issued_at=now.isoformat())
        approval = self.core._private_event(task_ref,'private_status',payload,key=key+'.approval')
        cap = IssuedPrivateInitialAuthorRecovery(self,task_ref,slot_id,approval,CONTINUATION_KEY,predecessor_failure_id)
        self._recoveries[approval]=(cap,canonical_hash(payload),self.core)
        self._recovery_sources[approval]=source
        return cap

    def _select_initial_recovery_source(self, cap: IssuedPrivateInitialAuthorRecovery) -> None:
        # Only an original issued object retained by THIS process selects the
        # fresh pre-IO protocol. It never restores its old TOP origin/authority.
        source = self._recovery_sources.get(cap.approval_id)
        saved = self._recoveries.get(cap.approval_id)
        if saved is None or saved[0] is not cap or cap.owner is not self or source is None:
            raise PrivateNativePending('private_recovery_original_issued_cap_required')
        if self.base_service.type_owner.current_source_binding is None:
            self.base_service.type_owner.current_source_binding = source

    def _require_initial_recovery(self, cap: IssuedPrivateInitialAuthorRecovery) -> None:
        self._guard()
        if type(cap) is not IssuedPrivateInitialAuthorRecovery or cap.owner is not self:
            raise PrivateNativePending('private_recovery_original_issued_cap_required')
        key = self._initial_author_key(cap)
        saved = self._recoveries.get(cap.approval_id)
        row = self.conn.execute('SELECT payload_json FROM '+PRIVATE_JOURNAL+
            " WHERE id=%s AND pack_task_id=%s AND user_id=%s AND epoch=%s AND record_kind='private_status' AND operation_key=%s",
            (cap.approval_id,cap.task.pack_task_id,cap.task.user_id,cap.task.epoch,key+'.approval')).fetchone()
        if saved is None or saved[0] is not cap or saved[2] is not self.core or row is None or canonical_hash(row['payload_json']) != saved[1]:
            raise PrivateNativePending('private_recovery_original_issued_cap_required')
        if cap.authorization_key == CONTINUATION_KEY:
            payload = row['payload_json']
            if (payload.get('schema_version') != 'private_initial_author_continuation_approval_v1'
                    or payload.get('authorization_key') != cap.authorization_key
                    or payload.get('predecessor_failure_id') != str(cap.predecessor_failure_id)
                    or payload.get('slot_id') != str(cap.slot_id) or cap.slot_id != RECOVERY_SLOT
                    or (cap.task.pack_task_id,cap.task.user_id,cap.task.epoch,cap.task.scope_id,cap.task.mapping_receipt_id)
                    != (RECOVERY_TASK,RECOVERY_USER,1,RECOVERY_SCOPE,RECOVERY_MAPPING)):
                raise PrivateNativePending('private_recovery_original_issued_cap_required')
            self._continuation_receivers()
        else:
            self._recovery_receivers()
        self._recovery_source(cap.task)

    def claim_initial_author_recovery(self, cap: IssuedPrivateInitialAuthorRecovery, *, job_id: UUID, batch_id: UUID) -> JobLeaseV1:
        self._require_initial_recovery(cap)
        actual = self._recovery_source(cap.task)
        protocol = self._initial_author_protocol(cap)
        row = self.conn.execute('SELECT claimed.* FROM item_supply_internal.private_initial_author_'+protocol+'_first_claim(%s,%s,%s,%s,%s) AS claimed',
            (cap.approval_id,job_id,batch_id,actual.origin_id(),'private.initial.author.'+protocol+'.'+cap.approval_id.hex)).fetchone()
        if row is None or row['job_id'] != job_id:
            raise PrivateNativePending('private_recovery_exact_first_claim_required')
        lease = self.facts_owner.pipeline.runtime._lease(row,'private')
        self.facts_owner.pipeline.runtime._control(lease,now=self._guard())
        return lease

    def base_fallback_owner(self) -> Any:
        from app.services.learning.item_supply.private_native_base_fallback import PrivateNativeBaseFallbackOwner
        if self._fallback is None:
            self._fallback = PrivateNativeBaseFallbackOwner(self)
        if type(self._fallback) is not PrivateNativeBaseFallbackOwner or self._fallback.service is not self:
            raise PrivateNativePending('private_service_concrete_whole_base_fallback_required')
        return self._fallback

    def executor(self) -> PrivateNativePackExecutor:
        from app.services.learning.item_supply.private_native_pack_executor import PrivateNativePackExecutor
        if self._executor is None:
            self._executor = PrivateNativePackExecutor(self)
        if type(self._executor) is not PrivateNativePackExecutor or self._executor.service is not self:
            raise PrivateNativePending('private_service_concrete_executor_required')
        return self._executor

    def generation_persistence_owner(self) -> PrivateGenerationPersistenceOwner:
        from app.services.learning.item_supply.private_generation_persistence import PrivateGenerationPersistenceOwner
        if self._generation_persistence is None:
            self._generation_persistence = PrivateGenerationPersistenceOwner(self)
        if type(self._generation_persistence) is not PrivateGenerationPersistenceOwner or self._generation_persistence.service is not self:
            raise PrivateNativePending('private_persistence_original_owners_required')
        return self._generation_persistence

    def generation_persistence_phase_owner(self) -> PrivateGenerationPersistencePhaseOwner:
        from app.services.learning.item_supply.private_generation_persistence_phase import PrivateGenerationPersistencePhaseOwner
        if self._generation_persistence_phase is None:
            self._generation_persistence_phase = PrivateGenerationPersistencePhaseOwner(self)
        if (type(self._generation_persistence_phase) is not PrivateGenerationPersistencePhaseOwner
                or self._generation_persistence_phase.service is not self):
            raise PrivateNativePending('private_phase_original_owners_required')
        return self._generation_persistence_phase

    def _guard(self)->datetime:
        if not self.enabled:
            raise PrivateNativePending('private_service_disabled')
        if (self.facts_owner.type_owner is not self.type_owner
                or self.type_owner.public_owner is not self.base_service.type_owner
                or self.type_owner.mapping_owner is not self.base_service.type_owner.mapping_owner
                or self.facts_owner.source_authority is not self.base_service.type_owner.source_authority):
            raise PrivateNativePending('private_service_original_same_connection_owners_required')
        self.facts_owner.bind_type_owner(self.type_owner)
        self.base_service._guard()
        now,_=self.type_owner._guard()
        return now

    def bind_slot_phase(self, *, task_ref: PersistentPackTaskRef, slot_id: UUID,
                        lease: JobLeaseV1, parent_version_id: UUID | None=None)->PrivateSlotRef:
        self._guard()
        task=self.core._task(task_ref)
        if task.enhancement!='prefer_private':
            raise PrivateNativePending('private_service_same_prefer_private_task_required')
        slot=next((s for s in task.slots if s.slot_id==slot_id),None)
        if slot is None:
            raise PrivateNativePending('private_service_original_fixed_slot_required')
        role: Literal['practice','assessment','remediation']='practice' if slot.slot.startswith('practice-') else (
            'assessment' if slot.slot.startswith('assessment-') else 'remediation')
        mapping=self.type_owner.resolve_mapping(task_ref.mapping_receipt_id)
        entry=next(d for d in mapping.pack_request.demands if d.slot==role)
        meta=self.facts_owner.pipeline.budget._job_meta(lease,now=self._guard())
        ref=PrivateSlotRef(pack_task_id=task_ref.pack_task_id,slot_id=slot.slot_id,business_item_id=slot.logical_item_id,
            root_id=UUID(str(meta['root_id'])),mapping_receipt_id=task_ref.mapping_receipt_id,
            user_id=task_ref.user_id,epoch=task_ref.epoch,scope_id=task_ref.scope_id,
            goal_scope_id=entry.storage_scope_id,slot=role,parent_version_id=parent_version_id)
        if parent_version_id is not None:
            parent=self.conn.execute('SELECT payload_json FROM tutor_item_supply_private_native_quality_evidence '
                "WHERE version_id=%s AND user_id=%s AND epoch=%s AND scope_id=%s AND pack_task_id=%s AND slot_id=%s AND kind='review'",
                (parent_version_id,ref.user_id,ref.epoch,ref.scope_id,ref.pack_task_id,ref.slot_id)).fetchone()
            if parent is None:
                raise PrivateNativePending('private_service_actual_same_slot_parent_review_required')
        self.conn.execute('SELECT item_supply_internal.private_pack_bind_phase(%s,%s)',
            (Jsonb(ref.model_dump(mode='json')),Jsonb(lease.model_dump(mode='json'))))
        self.facts_owner._guard(ref,lease)
        return ref

    def prepare_generation(self, *, ref: PrivateSlotRef, lease: JobLeaseV1,
                           spec: FiniteCandidateSpecV1, materials: tuple[PublicMaterialV2,...],
                           limits: GenerationLimitsV2, provider: OpenAICompatibleGenerationProvider,
                           recovery: IssuedPrivateInitialAuthorRecovery | None = None)->PreparedPrivateSlotGeneration:
        self._guard()
        self._generation_output_ready()
        if recovery is not None:
            self._require_initial_recovery(recovery)
            if (ref.pack_task_id,ref.slot_id,ref.business_item_id,ref.root_id) != (
                    RECOVERY_TASK,RECOVERY_SLOT,RECOVERY_BUSINESS,RECOVERY_ROOT):
                raise PrivateNativePending('private_recovery_exact_approved_task_required')
            if self.conn.execute('SELECT id FROM '+PRIVATE_JOURNAL+" WHERE operation_key=%s AND user_id=%s AND epoch=1",
                    (self._initial_author_key(recovery)+'.binding',RECOVERY_USER)).fetchone() is not None:
                raise PrivateNativePending('private_recovery_preparation_once_required')
        elif self.conn.execute('SELECT id FROM '+PRIVATE_JOURNAL+
                " WHERE pack_task_id=%s AND record_kind='private_status' AND payload_json->>'schema_version'='private_native_stage_v1' "
                "AND payload_json->>'slot_id'=%s AND payload_json->>'stage'='author' AND payload_json->>'status'='started' LIMIT 1",
                (ref.pack_task_id,str(ref.slot_id))).fetchone() is not None:
            raise PrivateNativePending('private_service_original_author_once_required')
        if (type(provider) is not OpenAICompatibleGenerationProvider or provider.request_attempt_bound!=1
                or ref.parent_version_id is not None
                or spec.public_template.item_key!='private-native.'+ref.business_item_id.hex):
            raise PrivateNativePending('private_service_original_initial_author_required')
        request=build_private_generation_request(self.facts_owner,ref=ref,lease=lease,spec=spec,
            materials=materials,limits=limits,candidate_id=uuid4())
        original=self.facts_owner.pipeline.prepare_generation(lease=lease,scope_id=ref.scope_id,request=request,
            provider=provider,source_authority=self.facts_owner.source_authority,mode='live')
        if original is None:
            raise PrivateNativePending('private_service_original_author_reservation_unavailable')
        prepared=PreparedPrivateSlotGeneration(ref,original)
        payload={'schema_version':'private_native_initial_author_v1','ref':ref.model_dump(mode='json'),
            'request':request.model_dump(mode='json')}
        self.conn.execute('SELECT item_supply_internal.private_pack_prepare_auxiliary(%s,%s,%s,%s,%s,%s)',
            (ref.pack_task_id,request.candidate_id,lease.job_id,original.reservation_id,Jsonb(payload),
             min(lease.expires_at,lease.parent_deadline)))
        self._prepared[request.candidate_id]=(prepared,canonical_hash(generation_context(prepared)),provider)
        if recovery is not None:
            key = self._initial_author_key(recovery)
            protocol = self._initial_author_protocol(recovery)
            actual = self._recovery_source(recovery.task)
            claim = self.conn.execute('SELECT id,payload_json FROM '+PRIVATE_JOURNAL+
                " WHERE operation_key=%s AND pack_task_id=%s AND user_id=%s AND epoch=1",
                (key+'.claim',RECOVERY_TASK,RECOVERY_USER)).fetchone()
            if claim is None or claim['payload_json']['job_id'] != str(lease.job_id):
                raise PrivateNativePending('private_recovery_exact_first_claim_required')
            binding = dict(schema_version='private_initial_author_'+protocol+'_binding_v1',approval_id=str(recovery.approval_id),
                claim_id=str(claim['id']),candidate_id=str(request.candidate_id),preparation_id=str(request.candidate_id),
                reservation_id=str(original.reservation_id),ref=ref.model_dump(mode='json'),lease=lease.model_dump(mode='json'),
                request=request.model_dump(mode='json'),sources=[source.model_dump(mode='json') for source in original.sources],
                item_key=request.item_key,version=request.version,
                candidate_key='private.native.'+RECOVERY_BUSINESS.hex,storage_version=1,source_origin_id=str(actual.origin_id()),
                valid_until=min(lease.expires_at,lease.parent_deadline,actual.source_deadline).isoformat())
            bound = self.core._private_event(recovery.task,'private_status',binding,key=key+'.binding')
            self._recovery_bindings[request.candidate_id]=(prepared,recovery,bound)
        return prepared

    def _prepared_recovery(self, p: PreparedPrivateSlotGeneration) -> tuple[IssuedPrivateInitialAuthorRecovery,UUID] | None:
        saved = self._recovery_bindings.get(p.original.request.candidate_id)
        row = self.conn.execute('SELECT id FROM '+PRIVATE_JOURNAL+
            " WHERE pack_task_id=%s AND payload_json->>'schema_version' IN('private_initial_author_recovery_binding_v1','private_initial_author_continuation_binding_v1') "
            "AND payload_json->>'candidate_id'=%s", (p.ref.pack_task_id,str(p.original.request.candidate_id))).fetchone()
        if saved is None:
            if row is not None:
                raise PrivateNativePending('private_recovery_original_prepared_registry_required')
            return None
        if saved[0] is not p or row is None or row['id'] != saved[2]:
            raise PrivateNativePending('private_recovery_original_prepared_registry_required')
        self._require_initial_recovery(saved[1])
        return saved[1],saved[2]

    def _require_generation(self,p:PreparedPrivateSlotGeneration)->OpenAICompatibleGenerationProvider:
        saved=self._prepared.get(p.original.request.candidate_id)
        if saved is None or saved[0] is not p or saved[1]!=canonical_hash(generation_context(p)):
            raise PrivateNativePending('private_service_issued_author_preparation_required')
        return saved[2]

    @contextmanager
    def _generation_source_front(self, ref: PrivateSlotRef) -> Iterator[IssuedCurrentPackSourceBinding | None]:
        with self.facts_owner.current_source_front(ref) as actual:
            if actual is not None and actual.owner is not self.core:
                raise PrivateNativePending('private_service_original_task_source_binding_required')
            yield actual

    def run_generation(self,p:PreparedPrivateSlotGeneration)->GenerationResultV2:
        provider=self._require_generation(p)
        key=p.original.request.candidate_id
        if key == LOST_C14_CANDIDATE:
            raise PrivateNativePending('private_generation_historical_output_backfill_denied')
        if self.conn.info.transaction_status!=TransactionStatus.IDLE or key in self._started:
            raise PrivateNativePending('private_service_idle_once_required')
        issued_recovery = self._recovery_bindings.get(key)
        if issued_recovery is not None:
            if issued_recovery[0] is not p:
                raise PrivateNativePending('private_recovery_original_prepared_registry_required')
            self._select_initial_recovery_source(issued_recovery[1])
        with self.conn.transaction():
            with self._generation_source_front(p.ref) as actual:
                self._guard()
                if p.original.mode == 'live':
                    self._generation_output_ready()
                self.facts_owner._guard(p.ref,p.original.lease)
                row=self.conn.execute('SELECT item_supply_internal.private_pack_auxiliary_committed(%s,%s) AS ok',
                    (p.ref.pack_task_id,key)).fetchone()
                if row is None or row['ok'] is not True:
                    raise PrivateNativePending('private_service_committed_author_preparation_required')
                if len(p.original.request.materials) != len(p.original.sources):
                    raise PrivateNativePending('private_service_complete_author_sources_required')
                for material, receipt in zip(p.original.request.materials, p.original.sources, strict=True):
                    self.facts_owner.source_authority.assert_current(material, receipt)
                if actual is not None:
                    actual.require()
                self.facts_owner._guard(p.ref,p.original.lease)
                now = self._guard()
                if actual is not None and now >= actual.source_deadline:
                    raise PrivateNativePending('private_service_current_author_source_required')
                recovery = self._prepared_recovery(p)
                if recovery is not None:
                    if actual is None:
                        raise PrivateNativePending('private_recovery_fresh_original_source_required')
                    protocol = self._initial_author_protocol(recovery[0])
                    self.conn.execute('SELECT item_supply_internal.private_initial_author_'+protocol+'_consume(%s,%s)',
                        (recovery[1],actual.origin_id())).fetchone()
                    actual.require()
                    self.facts_owner._guard(p.ref,p.original.lease)
                    if self._guard() >= min(actual.source_deadline,p.original.lease.expires_at,p.original.lease.parent_deadline):
                        raise PrivateNativePending('private_service_current_author_source_required')
        if self.conn.info.transaction_status != TransactionStatus.IDLE:
            raise PrivateNativePending('private_service_idle_once_required')
        self._started.add(key)
        result=self.facts_owner.pipeline.run_generation(p.original,provider)
        if p.original.mode == 'live':
            # Seal the original observation before the caller can mutate DATA.
            self._observed_generation_outputs[key] = ObservedPrivateGeneration.observe(p,result)
        self._results[key]=result
        return result

    def _generation_capture_payload(self, p: PreparedPrivateSlotGeneration, result: GenerationResultV2) -> dict[str,Any]:
        key = p.original.request.candidate_id
        if key == LOST_C14_CANDIDATE:
            raise PrivateNativePending('private_generation_historical_output_backfill_denied')
        self._require_generation(p)
        observed = self._observed_generation_outputs.get(key)
        if (observed is None or key not in self._started or self._results.get(key) is not result
                or p.original.mode != 'live'):
            raise PrivateNativePending('private_generation_original_output_observation_required')
        return observed.require(p,result)

    def capture_generation_output(self, p: PreparedPrivateSlotGeneration, result: GenerationResultV2) -> PrivateGenerationCaptureOutcome:
        """Append in a savepoint only. Caller must commit fees even on failure."""
        if self.conn.autocommit or self.conn.info.transaction_status != TransactionStatus.INTRANS:
            return PrivateGenerationCaptureOutcome('capture_failed', reason='private_generation_caller_transaction_required')
        try:
            with self.conn.transaction():
                if p.original.request.candidate_id == LOST_C14_CANDIDATE:
                    raise PrivateNativePending('private_generation_historical_output_backfill_denied')
                self._require_generation(p)
                if p.original.mode != 'live':
                    return PrivateGenerationCaptureOutcome('not_applicable')
                payload = self._generation_capture_payload(p,result)
                if result.state != 'staged':
                    return PrivateGenerationCaptureOutcome('not_applicable')
                # Observed output DATA does not refresh expired author SOURCE,
                # lease or prior-TOP pack scopes. SQL locks/checks current namespace.
                self._generation_output_ready()
                row = self.conn.execute('SELECT item_supply_internal.private_generation_output_capture(%s,%s) AS id',
                    (p.original.request.candidate_id,Jsonb(payload))).fetchone()
                if row is None or type(row['id']) is not UUID:
                    raise PrivateNativePending('private_generation_output_not_captured')
                output_id = row['id']
        except Exception:
            # No exception body/payload escapes, and no outer transaction is
            # rolled back here. Failure is not a durable-output acknowledgement.
            return PrivateGenerationCaptureOutcome('capture_failed', reason='private_generation_output_capture_failed')
        return PrivateGenerationCaptureOutcome('captured', output_id)

    def _require_committed_generation_output(self, p: PreparedPrivateSlotGeneration, result: GenerationResultV2) -> UUID:
        payload = self._generation_capture_payload(p,result)
        self._generation_output_ready()
        row = self.conn.execute('SELECT item_supply_internal.private_generation_output_committed(%s,%s) AS id',
            (p.original.request.candidate_id,Jsonb(payload))).fetchone()
        if row is None or type(row['id']) is not UUID:
            raise PrivateNativePending('private_generation_committed_output_required')
        return row['id']

    def settle_generation(self,p:PreparedPrivateSlotGeneration,result:GenerationResultV2)->None:
        self._require_generation(p)
        if self._results.get(p.original.request.candidate_id) is not result:
            raise PrivateNativePending('private_service_original_author_result_required')
        if p.original.mode == 'live':
            self._generation_capture_payload(p,result)
        self.facts_owner.pipeline.settle_generation(p.original,result)

    def persist_generation(self,p:PreparedPrivateSlotGeneration,result:GenerationResultV2)->UUID:
        self._require_generation(p)
        if self._results.get(p.original.request.candidate_id) is not result:
            raise PrivateNativePending('private_service_original_author_result_required')
        if result is None:
            raise PrivateNativePending('private_service_original_author_result_required')
        if p.original.mode == 'live' and result.state == 'staged':
            self._require_committed_generation_output(p,result)
        self.facts_owner._guard(p.ref,p.original.lease)
        stored=self.facts_owner.pipeline.commit_generation(p.original,result,
            source_authority=self.facts_owner.source_authority,private_slot_ref=p.ref)
        if stored.artifact_id is None:
            raise PrivateNativePending('private_service_original_author_not_staged')
        return stored.artifact_id

    def persist_generation_failure(self, p: PreparedPrivateSlotGeneration, result: GenerationResultV2) -> UUID:
        self._require_generation(p)
        if (self._results.get(p.original.request.candidate_id) is not result or p.original.request.candidate_id not in self._started
                or result.state == 'staged' or result.source is not None):
            raise PrivateNativePending('private_recovery_original_failed_result_required')
        recovery = self._prepared_recovery(p)
        if recovery is None:
            raise PrivateNativePending('private_recovery_original_failed_result_required')
        cap,binding = recovery
        actual = self._recovery_source(cap.task)
        self.facts_owner._guard(p.ref,p.original.lease)
        receipt = result.receipt
        if receipt is not None and (receipt.candidate_id != p.original.request.candidate_id
                or receipt.scope_hash != p.original.request.scope_hash or receipt.sources != p.original.sources
                or receipt.provider.request_attempt_bound != 1 or receipt.provider.mode != 'provider'
                or (receipt.provider.provider,receipt.provider.configured_model) != p.original.producer_binding):
            raise PrivateNativePending('private_recovery_original_failed_receipt_required')
        for material, expected in zip(p.original.request.materials,p.original.sources,strict=True):
            self.facts_owner.source_authority.assert_current(material,expected)
        settled = self.conn.execute('SELECT s.id FROM tutor_item_supply_private_runtime_settlements s '
            'JOIN tutor_item_supply_private_reservations r ON r.id=s.reservation_id '
            'WHERE s.reservation_id=%s AND r.job_id=%s AND r.lease_generation=%s AND s.settlement_key=%s '
            'AND s.xmin::text::bigint<>(txid_current() %% 4294967296)',
            (p.original.reservation_id,p.original.lease.job_id,p.original.lease.generation,
             'generation.'+p.original.request.candidate_id.hex)).fetchone()
        consumed = self.conn.execute('SELECT id,payload_json FROM '+PRIVATE_JOURNAL+
            " WHERE operation_key=%s AND pack_task_id=%s AND xmin::text::bigint<>(txid_current() %% 4294967296)",
            (self._initial_author_key(cap)+'.consumed',p.ref.pack_task_id)).fetchone()
        if settled is None or consumed is None or consumed['payload_json']['binding_id'] != str(binding):
            raise PrivateNativePending('private_recovery_committed_settlement_consume_required')
        actual.require()
        now = self.facts_owner._guard(p.ref,p.original.lease)
        if self._guard() >= actual.source_deadline:
            raise PrivateNativePending('private_recovery_fresh_original_source_required')
        failure_schema = ('private_initial_author_continuation_failure_v1' if cap.authorization_key == CONTINUATION_KEY
            else 'private_initial_author_failure_v1')
        payload = dict(schema_version=failure_schema,binding_id=str(binding),consumed_id=str(consumed['id']),
            started_id=consumed['payload_json']['started_id'],job_id=str(p.original.lease.job_id),
            candidate_id=str(p.original.request.candidate_id),reservation_id=str(p.original.reservation_id),settlement_id=str(settled['id']),
            state=result.state,safe_reason=result.safe_reason,receipt=None if receipt is None else receipt.model_dump(mode='json'),
            source_origin_id=str(actual.origin_id()),recorded_at=now.isoformat())
        return self.core._private_event(cap.task,'private_status',payload,key=self._initial_author_key(cap)+'.failure')

    def _wait_source_contents(self, task_ref: PersistentPackTaskRef, union: Any) -> list[NativeResolvedContent]:
        """Reuse exact same-TOP immutable DATA, never cached source permission."""
        from app.services.learning.item_supply.native_type_evidence import NativeTypeEvidenceOwner, _CurrentPackData

        public = self.base_service.type_owner
        scoped = NativeTypeEvidenceOwner._current_pack_data(public)
        selected = union.snapshot.selected
        if scoped is None:
            return [public.resolve_content(c.version_id,current=True) for c in selected]
        if (type(public) is not NativeTypeEvidenceOwner or type(scoped) is not _CurrentPackData
                or public.conn is not self.conn or public.settings is not self.settings
                or self.core.type_owner is not public or self.base_service.persistent_owner is not self.core
                or (public.user_id,public.epoch)!=(task_ref.user_id,task_ref.epoch)
                or scoped.txid!=public._guard()[1] or scoped.mapping_id!=task_ref.mapping_receipt_id
                or scoped.exposure_owner is not self.base_service.exposure_owner
                or scoped.mapping is None or scoped.mapping.receipt_id!=task_ref.mapping_receipt_id
                or scoped.inputs is None or scoped.observation is None
                or scoped.capability is None or scoped.capability is not union.public_capability
                or union.public_capability.snapshot.request!=union.snapshot.request
                or len(selected)!=5 or len({c.version_id for c in selected})!=5
                or {c.version_id for c in selected}!={c.version_id for c in union.public_capability.snapshot.selected}):
            raise PrivateNativePending('private_wait_exact_scoped_contents_required')
        NativeTypeEvidenceOwner._require_pack_identity(public,union.public_capability)
        contents: list[NativeResolvedContent] = []
        for member in selected:
            content = scoped.contents.get(member.version_id)
            if (type(content) is not NativeResolvedContent or content.content!=member.type_evidence.content
                    or content.publication.version_id!=member.version_id or content.publication.proof_id!=member.proof_id
                    or content.publication.publication_event_id!=member.publication_id
                    or content.publication.materialization_id!=member.materialization_id
                    or member.owner_id is not None or member.epoch is not None or member.candidate.visibility!='public'):
                raise PrivateNativePending('private_wait_exact_scoped_contents_required')
            contents.append(content)
        return contents

    def record_wait_window(self, *, task_ref: PersistentPackTaskRef, lease: JobLeaseV1) -> None:
        self._guard()
        union=self.base_fallback_owner().resolve(task_ref)
        self.base_fallback_owner().require(union)
        contents=self._wait_source_contents(task_ref,union)
        source_deadline=min(self.base_service.type_owner.source_deadline(c) for c in contents)
        from datetime import timedelta
        deadline=min(lease.parent_deadline,lease.profile.bound_at+timedelta(milliseconds=lease.profile.values.stage_deadline_ms),
            source_deadline-timedelta(seconds=15))
        now,_=self.type_owner._guard()
        if deadline<=now:
            raise PrivateNativePending('private_wait_not_started_base_current_time_insufficient')
        rows=self.conn.execute("SELECT id FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id=%s AND record_kind='private_status' AND payload_json->>'schema_version'='private_enhancement_wait_v1'",
            (task_ref.pack_task_id,)).fetchall()
        if rows:
            return  # immutable consumer wait, never technical lease expiry => new wait.
        self.core._private_event(task_ref,'private_status',dict(schema_version='private_enhancement_wait_v1',
            job_id=str(lease.job_id),base_union_id=str(union.receipt_id),checked_at=now.isoformat(),valid_until=deadline.isoformat()),
            key='private.wait.'+task_ref.pack_task_id.hex)

    def end_wait(self, *, task_ref: PersistentPackTaskRef) -> None:
        # Explicit server-side request to stop THIS consumer's wait. This event
        # does not cancel PRIVATE jobs/task, produce score or grant fallback.
        self._guard()
        self.core._task(task_ref)
        self.core._private_event(task_ref,'private_status',dict(schema_version='private_enhancement_wait_end_v1',
            reason='consumer_cancelled'),key='private.wait.end.'+task_ref.pack_task_id.hex)

    def fallback(self, demand: NativeSupplyDemandRef, *, task_ref: PersistentPackTaskRef) -> PrivateEnhancementResult:
        self._guard()
        task=self.core._task(task_ref)
        if task.enhancement!='prefer_private' or demand.mapping_receipt_id!=task_ref.mapping_receipt_id or demand.demand_id!=task_ref.demand_id:
            raise PrivateNativePending('private_fallback_same_original_demand_task_required')
        ended=self.conn.execute("SELECT id FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id=%s AND record_kind='private_status' AND (payload_json->>'schema_version'='private_enhancement_wait_end_v1' OR (payload_json->>'schema_version'='private_enhancement_wait_v1' AND (payload_json->>'valid_until')::timestamptz<=clock_timestamp()) OR payload_json->>'schema_version'='private_enhancement_failure_v1') LIMIT 1",
            (task_ref.pack_task_id,)).fetchone()
        if ended is None:
            failed = self.conn.execute('SELECT id FROM '+PRIVATE_JOURNAL+
                " WHERE pack_task_id=%s AND payload_json->>'schema_version'='private_initial_author_failure_v1' LIMIT 1",
                (task_ref.pack_task_id,)).fetchone()
            if failed is not None:
                self._recovery_receivers()
                ended = self.conn.execute('SELECT id FROM '+PRIVATE_JOURNAL+' WHERE id=%s AND '
                    'item_supply_internal.private_initial_author_failure_committed(id,pack_task_id,user_id,epoch::bigint,scope_id)',
                    (failed['id'],)).fetchone()
        if ended is None:
            raise PrivateNativePending('private_fallback_actual_wait_end_timeout_or_failure_required')
        cap=self.base_fallback_owner().resolve(task_ref)
        base=self.base_service._attempt(demand,reserve=True)
        if base.ready is None:
            return PrivateEnhancementResult(base.learner,'unavailable',base=base)
        self.base_fallback_owner().require(cap)
        from app.services.learning.item_supply.selection import select_pack
        selected=select_pack(cap.inputs,now=self.type_owner._guard()[0])
        if selected.status!='computed_base' or selected.pack is None:
            raise PrivateNativePending('private_fallback_original_whole_base_selector_required')
        return PrivateEnhancementResult(NativeSupplyLearnerStatusV1(status='ready',reason='available',allowed_actions=('continue',)),
            'waiting_ended',base=base,fallback=cap,diagnostic='current_whole_base_union_fallback')

    def require_fallback(self, cap: Any) -> Any:
        return self.base_fallback_owner().require(cap)

    def revalidate_supply(self, demand_id: UUID, *, task_ref: PersistentPackTaskRef) -> PrivateEnhancementResult:
        # Reconnect coordinates are DATA. Fresh original current owners issue ALL
        # proofs again; no30sec snapshot/capability is persisted/restored here.
        self._guard()
        demand=self.base_service._request_for(demand_id)
        if demand.enhancement!='prefer_private':
            raise PrivateNativePending('private_service_original_enhancement_intent_required')
        return self.ensure_supply(demand,task_ref=task_ref)

    def get_supply_status(self, demand_id: UUID, *, task_ref: PersistentPackTaskRef) -> NativeSupplyLearnerStatusV1:
        return self.revalidate_supply(demand_id,task_ref=task_ref).learner

    def delivery_context(self, ready: PrivateEnhancementReady, *, version_id: UUID, run_id: UUID) -> PrivateTeachingDeliveryContext:
        if type(ready) is not PrivateEnhancementReady or type(run_id) is not UUID or type(version_id) is not UUID:
            raise PrivateNativePending('private_service_exact_delivery_DATA_required')
        self._guard()
        task=self.core._task(ready.task_ref)
        pack=self.type_owner.require_pack(ready.capability)
        if task.enhancement!='prefer_private' or not any(c.version_id==version_id and c.member.slot=='practice' for c in pack.selected):
            raise PrivateNativePending('private_service_current_selected_practice_required')
        current,_=self.exposure_owner.resolve_reserved_pack(ready.reservation_id)
        if {(c.version_id,c.proof_id) for c in self.type_owner.require_pack(current).selected}!={(c.version_id,c.proof_id) for c in pack.selected}:
            raise PrivateNativePending('private_service_exact_retained_private_pack_required')
        return PrivateTeachingDeliveryContext(self.exposure_owner,ready.task_ref.mapping_receipt_id,
            ready.reservation_id,version_id,run_id,ready.task_ref.pack_task_id)

    def ensure_supply(self,demand:NativeSupplyDemandRef,*,task_ref:PersistentPackTaskRef)->PrivateEnhancementResult:
        self._guard()
        task=self.core._task(task_ref)
        if (demand.enhancement!='prefer_private' or task.enhancement!='prefer_private'
                or (demand.demand_id,demand.mapping_receipt_id)!=(task_ref.demand_id,task_ref.mapping_receipt_id)):
            raise PrivateNativePending('private_service_same_original_demand_task_required')
        # Issue complete union clearance BEFORE original502 may reserve again.
        # The same stable five PUBLIC versions remain PUBLIC, never relabeled.
        union_base=self.base_fallback_owner().resolve(task_ref)
        base=self.base_service._attempt(demand,reserve=True)
        if base.ready is None:
            return PrivateEnhancementResult(base.learner,'unavailable',base=base)
        observation=PrivateExposureObservation(union_base.exposure_snapshot_id,self.exposure_owner.require_snapshot(union_base.exposure_snapshot_id))
        rows=self.conn.execute('SELECT DISTINCT ON(p.slot_id) p.version_id,p.slot_id FROM tutor_item_supply_private_native_publications p '
            "WHERE p.pack_task_id=%s AND p.user_id=%s AND p.epoch=%s AND p.state='published' "
            'AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_native_publications s WHERE s.version_id=p.version_id '
            'AND s.user_id=p.user_id AND s.epoch=p.epoch AND s.state_version>p.state_version) '
            'ORDER BY p.slot_id,p.created_at DESC,p.id DESC LIMIT 17',(task_ref.pack_task_id,task_ref.user_id,task_ref.epoch)).fetchall()
        # Only a genuinely published same-slot child advances a head; no seed /
        # replacement-item lottery. An active consumer retains its exact group.
        versions: dict[UUID,UUID]={}
        for row in rows:
            versions.setdefault(UUID(str(row['slot_id'])),UUID(str(row['version_id'])))
        if len(versions)!=5 or set(versions)!={s.slot_id for s in task.slots}:
            # A whole-base return with PRIVATE exposure needs a separately verified
            # union selector; do not equate original public-only cap with that grant.
            return PrivateEnhancementResult(NativeSupplyLearnerStatusV1(status='preparing',reason='preparing',
                allowed_actions=('refresh',)),'preparing',base=base,diagnostic='private_fixed_slots_incomplete')
        selected_ids={str(v) for v in versions.values()}
        active=self.conn.execute('SELECT DISTINCT res.payload_json FROM tutor_item_supply_private_native_artifact_bindings b '
            'JOIN tutor_learning_artifacts a ON a.id=b.artifact_id AND a.user_id=b.user_id '
            'JOIN tutor_item_supply_private_native_consumer_receipts r ON r.id=b.creation_receipt_id '
            'JOIN tutor_item_supply_private_native_assessment_reservations res ON res.id=r.reservation_id '
            "WHERE b.user_id=%s AND b.epoch=%s AND b.pack_task_id=%s AND (a.state IN('pending','ready','active') OR a.active_attempt_id IS NOT NULL)",
            (task_ref.user_id,task_ref.epoch,task_ref.pack_task_id)).fetchall()
        if any(set(r['payload_json']['versions'])!=selected_ids for r in active):
            return PrivateEnhancementResult(NativeSupplyLearnerStatusV1(status='preparing',reason='preparing',allowed_actions=('refresh',)),
                'preparing',base=base,diagnostic='active_original_consumer_retains_exact_private_selection')
        relations=self.conn.execute('SELECT id FROM tutor_item_supply_private_native_quality_evidence '
            "WHERE pack_task_id=%s AND user_id=%s AND epoch=%s AND kind='relation' AND valid_until>clock_timestamp() ORDER BY checked_at,id LIMIT 17",
            (task_ref.pack_task_id,task_ref.user_id,task_ref.epoch)).fetchall()
        if not 1<=len(relations)<=16:
            raise PrivateNativePending('private_service_current_actual_relations_required')
        cap=self.type_owner.resolve_pack(demand.mapping_receipt_id,tuple(versions[s.slot_id] for s in task.slots),
            observation.snapshot_id,tuple(UUID(str(r['id'])) for r in relations))
        self.type_owner.require_pack(cap)
        from app.services.learning.item_supply.pack_contracts import CrossPoolMappingV1
        from app.services.learning.item_supply.selection import select_pack
        enhanced_inputs=self.type_owner._inputs(demand.mapping_receipt_id,tuple(versions[s.slot_id] for s in task.slots),
            observation.snapshot_id,tuple(UUID(str(r['id'])) for r in relations))
        now,_=self.type_owner._guard()
        mapping=self.type_owner.resolve_mapping(demand.mapping_receipt_id)
        cross=CrossPoolMappingV1(base_request_hash=union_base.inputs.request.request_hash,
            enhancement_request_hash=enhanced_inputs.request.request_hash,mapping_receipt_hash=mapping.mapping_hash,
            checked_at=now,valid_until=min(union_base.snapshot.valid_until,cap.snapshot.valid_until))
        selection=select_pack(union_base.inputs,now=now,enhancement=enhanced_inputs,mapping=cross)
        if selection.status!='computed_enhancement' or selection.pack is None:
            raise PrivateNativePending('private_service_original_typed_whole_enhancement_required')
        self.base_fallback_owner().require(union_base)
        operation='private.supply.'+demand.demand_id.hex
        original=self.conn.execute('SELECT payload_json FROM tutor_item_supply_private_native_assessment_reservations '
            'WHERE user_id=%s AND epoch=%s AND operation_key=%s',
            (task_ref.user_id,task_ref.epoch,operation)).fetchone()
        if original is None or set(original['payload_json']['versions'])!=selected_ids:
            # New future consumer group, SAME task/root/slots. Never includes
            # ephemeral snapshot/proof/eligibility IDs or overwrites old bindings.
            operation+='.'+canonical_hash(sorted(selected_ids))
        reservation=self.exposure_owner.reserve_assessment(cap=cap,exposure_snapshot_id=observation.snapshot_id,
            operation_key=operation,base_reservation_id=base.ready.reservation_id)
        self.base_service.type_owner.require_pack(base.ready.capability)
        self.type_owner.require_pack(cap)
        return PrivateEnhancementResult(NativeSupplyLearnerStatusV1(status='ready',reason='available',allowed_actions=('continue',)),
            'ready',base=base,ready=PrivateEnhancementReady(base.ready,cap,reservation,task_ref,selection),diagnostic='private_whole_pack_reserved')
