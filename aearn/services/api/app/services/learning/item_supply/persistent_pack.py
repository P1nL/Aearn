"""ONE persistent demand task; concrete PUBLIC bounded phases, no JSON caps.

Default-off. Caller owns short DB transactions; run_phase starts IDLE. PRIVATE
identities never enter public journals. Public work does not fork budget roots.
"""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

from psycopg import Connection
from psycopg.pq import TransactionStatus
from psycopg.transaction import Transaction
from psycopg.types.json import Jsonb

from app.core.config import Settings
from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.persistent_pack_contracts import (
    PROTOCOL, SLOTS, BlockedPackPhase, IssuedPackPhase, PersistentPackIntentV1,
    PersistentPackPending, PersistentPackSlotRef, PersistentPackStatus,
    PersistentPackTaskRecord, PersistentPackTaskRef, PersistentPhaseOutcome,
    PersistentPublicTaskRecord, PersistentPublicVersionRecord,
)
from app.services.learning.item_supply.native_supply_service_contracts import NativeSupplyDemandRef
from app.services.learning.item_supply.generation_contracts import PublicMaterialV2
from app.services.learning.item_supply.sandbox.execution_contracts import RunnerPort
from app.services.learning.item_supply.native_type_evidence import NativeTypeEvidenceOwner
from app.services.learning.item_supply.native_type_exposure import NativeExposureOwnerV2
from app.services.learning.item_supply.repository import ItemSupplyRuntimeRepository
from app.services.learning.item_supply.storage_contracts import checked_model

if TYPE_CHECKING:
    from app.services.learning.item_supply.persistent_pack_current_source import IssuedCurrentPackSourceBinding
    from app.services.learning.item_supply.persistent_pack_source_successor import IssuedSourceMappingSuccessor
    from app.services.learning.item_supply.persistent_pack_committed_recheck import IssuedCommittedChildRecheck
    from app.services.learning.item_supply.persistent_pack_committed_admission import IssuedCommittedChildAdmission
    from app.services.learning.item_supply.generation_contracts import PublicMaterialV2
    from app.services.learning.item_supply.native_revision import NativeRevisionOwner, PreparedNativeRevision

SHARED = "tutor_item_supply_shared_persistent_pack_journal"
PRIVATE = "tutor_item_supply_private_persistent_pack_journal"


class PersistentPackTaskOwner:
    def __init__(self, conn: Connection[dict[str, Any]], settings: Settings, *,
                 type_owner: NativeTypeEvidenceOwner, exposure_owner: NativeExposureOwnerV2,
                 enabled: bool = False, public_materials: tuple[PublicMaterialV2, ...] = (),
                 runner: RunnerPort | None = None) -> None:
        if (type(type_owner) is not NativeTypeEvidenceOwner or type(exposure_owner) is not NativeExposureOwnerV2
                or type_owner.conn is not conn or type_owner.settings is not settings
                or exposure_owner.conn is not conn or exposure_owner.type_owner is not type_owner
                or type(enabled) is not bool):
            raise PersistentPackPending("persistent_concrete_same_connection_required")
        self.conn, self.settings, self.type_owner, self.exposure_owner = conn, settings, type_owner, exposure_owner
        self.enabled = enabled
        self.public_materials = tuple(checked_model(m,PublicMaterialV2) for m in public_materials)
        self.runner = runner  # Only the ORIGINAL validation/scorer may verify terminal authority.
        self.user_id, self.epoch = type_owner.user_id, type_owner.epoch
        self.runtime = ItemSupplyRuntimeRepository(conn)
        self._issued: dict[UUID, tuple[IssuedPackPhase, str]] = {}
        self._started: set[UUID] = set()
        self._prestart_recovery: Any = None  # Original same-TOP, one-use permission only.
        self._explicit_recovery: Any = None  # Separate explicit release, never535 reuse.
        self._explicit_attempts: dict[UUID, Any] = {}
        self._revision_contexts: dict[UUID, Any] = {}  # Evidence only; never _issued/run_phase.
        self._fresh_revision_executions: dict[UUID, Any] = {}
        self._source_successors: dict[UUID, Any] = {}
        self._current_source_bindings: dict[UUID, Any] = {}
        self._current_source_origins: dict[tuple[UUID, int], Any] = {}
        self._committed_child_rechecks: dict[UUID, Any] = {}
        self._committed_child_recheck_sources: dict[UUID, Any] = {}
        self._committed_admissions: dict[UUID, Any] = {}
        self._committed_admission_owners: dict[UUID, Any] = {}

    def _guard(self) -> datetime:
        if not self.enabled:
            raise PersistentPackPending("persistent_pack_disabled")
        stamp, _ = self.type_owner._guard()
        function = self.conn.execute("SELECT p.prosrc,p.prosecdef,p.prokind,p.proconfig FROM pg_proc p WHERE p.oid="
            "to_regprocedure('item_supply_internal.assert_persistent_pack_phase(jsonb)')").fetchone()
        if (function is None or not function["prosecdef"] or function["prokind"] != "f"
                or hashlib.sha256(function["prosrc"].replace("\r\n", "\n").encode()).hexdigest() != "6c26c1c3fb4fac05b84dcd8dc4a7f112d375167039e8df14f3a06f7a73d896d2"):
            raise PersistentPackPending("persistent_523_required")
        return stamp

    def issue_current_source_binding(self, task_ref: PersistentPackTaskRef, *,
                                     source_data_id: UUID) -> IssuedCurrentPackSourceBinding:
        """Fresh original C/D permission; revision-only successor DATA is not a cap."""
        from app.services.learning.item_supply.persistent_pack_current_source import issue
        return issue(self, task_ref, source_data_id=source_data_id)

    def _public_event(self, public_task: UUID, kind: str, payload: dict[str, Any], *,
                      key: str, root_id: UUID | None = None, job_id: UUID | None = None,
                      phase_id: UUID | None = None) -> UUID:
        self._guard()
        row = self.conn.execute("INSERT INTO " + SHARED + "(id,public_task_id,record_kind,operation_key,root_id,job_id,phase_id,payload_json) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(operation_key,record_kind) DO NOTHING RETURNING id",
            (uuid4(), public_task, kind, key, root_id, job_id, phase_id, Jsonb(payload))).fetchone()
        if row is not None:
            return row["id"]
        prior = self.conn.execute("SELECT id,payload_json FROM " + SHARED + " WHERE operation_key=%s AND record_kind=%s",
            (key, kind)).fetchone()
        if prior is None or prior["payload_json"] != payload:
            raise PersistentPackPending("persistent_operation_conflict")
        return prior["id"]

    def _private_event(self, task: PersistentPackTaskRef, kind: str, payload: dict[str, Any], *, key: str) -> UUID:
        self._guard()
        identity = task.pack_task_id if kind == "task" else uuid4()
        row = self.conn.execute("INSERT INTO " + PRIVATE + "(id,pack_task_id,user_id,epoch,scope_id,record_kind,operation_key,intent_hash,payload_json) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(user_id,epoch,operation_key,record_kind) DO NOTHING RETURNING id",
            (identity, task.pack_task_id, task.user_id, task.epoch, task.scope_id, kind, key, task.intent_hash, Jsonb(payload))).fetchone()
        if row is not None:
            return row["id"]
        prior = self.conn.execute("SELECT id,payload_json FROM " + PRIVATE + " WHERE user_id=%s AND epoch=%s AND operation_key=%s AND record_kind=%s",
            (task.user_id, task.epoch, key, kind)).fetchone()
        if prior is None or prior["payload_json"] != payload:
            raise PersistentPackPending("persistent_private_binding_conflict")
        return prior["id"]

    def ensure_task(self, demand_ref: NativeSupplyDemandRef,
                    intent_ref: PersistentPackIntentV1 | None = None) -> PersistentPackTaskRef:
        self._guard()
        if type(demand_ref) is not NativeSupplyDemandRef:
            raise PersistentPackPending("persistent_original_demand_required")
        intent = checked_model(intent_ref or PersistentPackIntentV1(), PersistentPackIntentV1)
        mapping = self.type_owner.resolve_mapping(demand_ref.mapping_receipt_id)
        if not any(d.demand_id == demand_ref.demand_id for d in mapping.stored_demands):
            raise PersistentPackPending("persistent_demand_mapping_mismatch")
        scope = next(d.scope_id for d in mapping.stored_demands if d.slot == "assessment")
        # Request keys/preferences do not fork ONE confirmed goal intent.
        key = canonical_hash(dict(node=str(mapping.frozen_node.node_id), revision=str(mapping.frozen_node.revision_id),
            goal=mapping.frozen_node.goal_hash, target=mapping.target_id, scope=str(scope)))
        self.conn.execute("SELECT pg_advisory_xact_lock(hashtext('persistent-demand'),hashtext(%s))", (str(self.user_id) + key,))
        prior = self.conn.execute("SELECT payload_json FROM " + PRIVATE + " WHERE user_id=%s AND epoch=%s AND scope_id=%s "
            "AND intent_hash=%s AND record_kind='task'", (self.user_id,self.epoch,scope,key)).fetchone()
        if prior is not None:
            ref = PersistentPackTaskRecord.model_validate_json(json.dumps(prior["payload_json"])).ref
            self._task(ref)
            if intent.enhancement=="prefer_private":
                self.attach_enhancement_intent(ref)
            return ref
        public_key = canonical_hash(dict(protocol=PROTOCOL, target=mapping.target_id, definition=mapping.target_definition_hash))
        public_id = uuid5(NAMESPACE_URL, "aearn:persistent-public:" + public_key)
        public_slots = tuple(uuid5(public_id, slot) for slot in SLOTS)
        public = PersistentPublicTaskRecord(public_task_id=public_id, intent_hash=public_key,
            target_id=mapping.target_id, target_definition_hash=mapping.target_definition_hash, public_slots=public_slots)
        self._public_event(public_id, "task", public.model_dump(mode="json"), key="task."+public_id.hex)
        task_id = uuid4()
        ref = PersistentPackTaskRef(pack_task_id=task_id,user_id=self.user_id,epoch=self.epoch,scope_id=scope,
            mapping_receipt_id=mapping.receipt_id,demand_id=demand_ref.demand_id,intent_hash=key,public_task_id=public_id)
        slots = tuple(PersistentPackSlotRef(slot_id=uuid5(task_id,slot),logical_item_id=uuid5(task_id,"item."+slot),
            slot=slot, public_slot_id=public_slots[index]) for index,slot in enumerate(SLOTS))
        record = PersistentPackTaskRecord(ref=ref, slots=slots, enhancement=intent.enhancement)
        self._private_event(ref,"task",record.model_dump(mode="json"),key="task."+key)
        if demand_ref.candidate_version_ids:
            self._adopt_initial(ref, demand_ref.candidate_version_ids)
        return ref

    def _task(self, task: PersistentPackTaskRef) -> PersistentPackTaskRecord:
        self._guard()
        task = checked_model(task,PersistentPackTaskRef)
        if (task.user_id,task.epoch)!=(self.user_id,self.epoch):
            raise PersistentPackPending("persistent_private_namespace_mismatch")
        row = self.conn.execute("SELECT payload_json FROM " + PRIVATE + " WHERE id=%s AND pack_task_id=%s AND user_id=%s "
            "AND epoch=%s AND scope_id=%s AND record_kind='task'",(task.pack_task_id,task.pack_task_id,self.user_id,self.epoch,task.scope_id)).fetchone()
        if row is None:
            raise PersistentPackPending("persistent_task_missing")
        record = PersistentPackTaskRecord.model_validate_json(json.dumps(row["payload_json"]))
        if record.ref != task:
            raise PersistentPackPending("persistent_task_ref_mismatch")
        self.type_owner.resolve_mapping(task.mapping_receipt_id)
        from app.services.learning.item_supply.persistent_pack_intent import effective_enhancement
        return effective_enhancement(self,record)

    def attach_enhancement_intent(self, task_ref: PersistentPackTaskRef) -> PersistentPackTaskRecord:
        """Same immutable task header, explicit append-only base_only -> prefer_private intent."""
        from app.services.learning.item_supply.persistent_pack_intent import attach_enhancement_intent
        return attach_enhancement_intent(self,task_ref)

    def _versions(self, task: PersistentPackTaskRef) -> dict[str, PersistentPublicVersionRecord]:
        rows = self.conn.execute("SELECT payload_json FROM " + SHARED + " WHERE public_task_id=%s AND record_kind IN('version','qualified') "
            "ORDER BY created_at,id",(task.public_task_id,)).fetchall()
        result: dict[str,PersistentPublicVersionRecord] = {}
        for row in rows:
            version=PersistentPublicVersionRecord.model_validate_json(json.dumps(row["payload_json"]))
            old=result.get(version.slot)
            if old is None or version.revision_seq >= old.revision_seq:
                result[version.slot]=version
        return result

    def _adopt_initial(self, task: PersistentPackTaskRef, ids: tuple[UUID,...]) -> None:
        mapping=self.type_owner.resolve_mapping(task.mapping_receipt_id)
        record=self._task(task)
        used: set[str]=set()
        for version_id in ids:
            resolved=self.type_owner.resolve_content(version_id,current=True)
            self.type_owner._candidate(resolved,mapping,self._guard())
            original_row=self.conn.execute("SELECT candidate_id,item_supply_internal.controlled_counterexample_held(job_id) AS held FROM tutor_item_supply_shared_generation_artifacts WHERE id=%s",
                    (resolved.publication.generation_artifact_id,)).fetchone()
            if original_row is None or original_row["held"] is not False:
                raise PersistentPackPending("persistent_controlled_ancestry_denied")
            slot=next((s for s in record.slots if s.slot not in used and
                ("remediation" if s.slot=="guided-remediation" else s.slot.split('-')[0])==resolved.spec.allocation.slot),None)
            if slot is None:
                raise PersistentPackPending("persistent_initial_slot_binding_conflict")
            used.add(slot.slot)
            v=PersistentPublicVersionRecord(public_task_id=task.public_task_id,public_slot_id=slot.public_slot_id,
                slot=slot.slot,revision_id=uuid4(),revision_seq=1,parent_revision_id=None,
                candidate_id=original_row["candidate_id"],specification=resolved.spec,root_id=resolved.facts.root_id,
                artifact_id=resolved.publication.generation_artifact_id,published_version_id=version_id)
            self._public_event(task.public_task_id,"qualified",v.model_dump(mode="json"),key="adopt."+slot.public_slot_id.hex,
                root_id=v.root_id)

    def get_status(self, task_ref: PersistentPackTaskRef) -> PersistentPackStatus:
        self._task(task_ref)
        flags=self.conn.execute("SELECT record_kind FROM " + PRIVATE + " WHERE pack_task_id=%s AND user_id=%s AND epoch=%s "
            "AND record_kind IN('pause','stop') ORDER BY created_at DESC,id LIMIT 1",(task_ref.pack_task_id,self.user_id,self.epoch)).fetchone()
        if flags:
            return PersistentPackStatus(status="paused",reason="consumer_stopped",qualified_slots=0,
                current_version_ids=(),pack_task_id=task_ref.pack_task_id)
        versions=self._versions(task_ref)
        current: list[UUID]=[]
        for slot in SLOTS:
            version=versions.get(slot)
            if version is not None and version.published_version_id is not None:
                current.append(version.published_version_id)
        if len(current) == 5:
            relation = self.conn.execute("SELECT payload_json FROM " + PRIVATE + " WHERE pack_task_id=%s AND user_id=%s AND epoch=%s "
                "AND record_kind='private_status' AND payload_json->>'relation_receipt_id' IS NOT NULL ORDER BY created_at DESC,id LIMIT 1",
                (task_ref.pack_task_id,self.user_id,self.epoch)).fetchone()
            if relation is not None:
                receipt = UUID(relation["payload_json"]["relation_receipt_id"])
                if relation["payload_json"]["status"]!="relation_ready":
                    return PersistentPackStatus(status="preparing",reason="committed_relationship_findings_same_slot_repair",
                        qualified_slots=5,current_version_ids=tuple(current),pack_task_id=task_ref.pack_task_id)
                evidence = self.conn.execute("SELECT valid_until FROM tutor_item_supply_native_relation_batches "
                    "WHERE id=%s AND user_id=%s AND epoch=%s",(receipt,self.user_id,self.epoch)).fetchone()
                if evidence is None or evidence["valid_until"] <= self._guard():
                    return PersistentPackStatus(status="preparing",reason="relation_evidence_expired_same_task",
                        qualified_slots=5,current_version_ids=tuple(current),pack_task_id=task_ref.pack_task_id)
                try:
                    # A short DATA projection only. No issued cap or Ready escapes.
                    with self.type_owner.current_pack(task_ref.mapping_receipt_id, tuple(current),
                            (receipt,), self.exposure_owner) as capability:
                        self.type_owner.require_pack(capability)
                except ValueError:
                    return PersistentPackStatus(status="preparing",reason="current_relationship_requires_phase",
                        qualified_slots=5,current_version_ids=tuple(current),pack_task_id=task_ref.pack_task_id)
                return PersistentPackStatus(status="ready",reason="original_current_whole_pack",qualified_slots=5,
                    current_version_ids=tuple(current),pack_task_id=task_ref.pack_task_id)
        verified: list[UUID] = []
        for version_id in current:
            try:
                self.type_owner.resolve_content(version_id, current=True)
            except ValueError:
                return PersistentPackStatus(status="blocked", reason="current_source_or_content_unavailable",
                    qualified_slots=len(verified), current_version_ids=tuple(verified), pack_task_id=task_ref.pack_task_id)
            verified.append(version_id)
        return PersistentPackStatus(status="preparing",reason="relation_required" if len(current)==5 else "same_slot_work_pending",
            qualified_slots=len(current),current_version_ids=tuple(current),pack_task_id=task_ref.pack_task_id)

    def pause(self, task_ref: PersistentPackTaskRef) -> None:
        self._task(task_ref)
        self._private_event(task_ref,"pause",dict(schema_version="persistent_private_stop_v1",reason="user_stop"),
            key="pause."+task_ref.pack_task_id.hex)

    def _store_outcome(self, task: PersistentPackTaskRef, record: Any, result: PersistentPhaseOutcome) -> None:
        if result.relation_receipt_id is not None:
            self._private_event(task,"private_status",result.model_dump(mode="json"),key="result."+record.phase_id.hex)
        public=result.model_dump(mode="json")
        public["relation_receipt_id"]=None
        self._public_event(record.public_task_id,"phase_result",public,key=record.operation_key,
            root_id=record.root_id,job_id=record.job_id,phase_id=record.phase_id)

    def _reconcile_phase(self, task: PersistentPackTaskRef, pending: Any) -> IssuedPackPhase | BlockedPackPhase | None:
        """Only immutable outcome DATA; never rehydrate an execution frame."""
        from app.services.learning.item_supply.persistent_pack_contracts import PersistentPublicPhaseRecord
        record=PersistentPublicPhaseRecord.model_validate_json(json.dumps(pending["payload_json"]))
        if record.public_task_id!=task.public_task_id:
            raise PersistentPackPending("persistent_pending_task_binding_changed")
        started=self.conn.execute("SELECT id FROM "+SHARED+" WHERE phase_id=%s AND record_kind='dispatch_started'",
            (record.phase_id,)).fetchone()
        # Reconcile ONLY the original owner's fully checked committed outcome.
        # No Prepared/lease, role run, settlement or publication cap is restored.
        if record.kind=="relation_pack":
            from app.services.learning.item_supply.native_relation_review import (
                NativeRelationReviewProducer, PRODUCTION_PROTOCOL, ROLES, production_config,
            )
            from app.services.learning.item_supply.review_contracts_v2 import ProviderIdentityV2
            model=production_config(self.settings)["model"]
            if not isinstance(model,str) or not model:
                raise PersistentPackPending("persistent_committed_relation_configured_model_required")
            identities={role:ProviderIdentityV2(identity="deepseek.persistent.relation."+role,
                provider="deepseek",model=model,model_version=model) for role in ROLES}
            producer=NativeRelationReviewProducer(self.type_owner,identities=identities,
                trusted_model_bindings={("deepseek",model):model},enabled=True,
                protocol=PRODUCTION_PROTOCOL,max_output_tokens=61440)
            diagnosis=producer.resolve_committed_persistent(task_owner=self,task=task,record=record)
            if diagnosis is not None:
                self._store_outcome(task,record,PersistentPhaseOutcome(phase_id=record.phase_id,
                    status=diagnosis.outcome,safe_reason="original_committed_relation_reconciled",
                    relation_receipt_id=diagnosis.relation_receipt_id))
                return None
        if record.kind=="candidate":
            for version in self._versions(task).values():
                if version.public_slot_id==record.public_slot_id and version.published_version_id is not None:
                    actual=self.type_owner.resolve_content(version.published_version_id,current=True)
                    if actual.facts.root_id!=record.root_id:
                        raise PersistentPackPending("persistent_committed_candidate_root_changed")
                    descendant=self.conn.execute("WITH RECURSIVE lineage AS (SELECT id AS job_id,parent_job_id FROM "
                        "tutor_item_supply_shared_jobs WHERE id=%s UNION ALL SELECT j.id,j.parent_job_id FROM "
                        "tutor_item_supply_shared_jobs j JOIN lineage l ON j.id=l.parent_job_id) "
                        "SELECT 1 FROM lineage WHERE job_id=%s",(actual.facts.lease.job_id,record.job_id)).fetchone()
                    if descendant is not None:
                        self._store_outcome(task,record,PersistentPhaseOutcome(phase_id=record.phase_id,status="qualified",
                            safe_reason="original_committed_publication_reconciled",artifact_id=version.artifact_id,
                            published_version_id=version.published_version_id))
                        return None
        if started is not None:
            # Successful stage receipts may be reconciled by their concrete owner
            # in a subsequent phase; a missing receipt NEVER means zero usage.
            stages=self.conn.execute("SELECT record_kind,payload_json FROM "+SHARED+" WHERE phase_id=%s "
                "AND record_kind IN('stage_started','stage_result')",(record.phase_id,)).fetchall()
            starts={r["payload_json"]["stage"] for r in stages if r["record_kind"]=="stage_started"}
            done={r["payload_json"]["stage"] for r in stages if r["record_kind"]=="stage_result"}
            if record.kind=="relation_pack" or starts-done or not done:
                return BlockedPackPhase("opaque_phase_outcome_unknown_no_paid_replay",task.pack_task_id)
            self._store_outcome(task,record,PersistentPhaseOutcome(phase_id=record.phase_id,status="blocked",
                safe_reason="committed_stages_require_original_continuation"))
            return None
        entry=self._issued.get(record.phase_id)
        if entry is not None and self._guard()<record.valid_until:
            self.require_phase(entry[0])
            return entry[0]  # Exact original process object, not serialized lease.
        if self._guard()<record.lease.expires_at:
            return BlockedPackPhase("unstarted_live_phase_wait_original_expiry",task.pack_task_id)
        if not self.runtime.retire_persistent_unstarted_phase(owner=self,phase_id=record.phase_id):
            return BlockedPackPhase("unstarted_phase_original_runtime_pending",task.pack_task_id)
        self._store_outcome(task,record,PersistentPhaseOutcome(phase_id=record.phase_id,status="blocked",
            safe_reason="expired_without_dispatch_same_task_new_phase"))
        return None

    def prepare_prestart_recovery(self, task_ref: PersistentPackTaskRef, *, transaction: Any) -> IssuedPackPhase:
        """Explicit registered prestart proof + same-operation preparation; no IO run."""
        from app.services.learning.item_supply.persistent_pack_prestart_recovery import prepare_registered_recovery
        return prepare_registered_recovery(self, task_ref, transaction=transaction)

    def prepare_explicit_recovery(self, task_ref: PersistentPackTaskRef, *, transaction: Any) -> IssuedPackPhase:
        """One human-approved new attempt despite retained UNKNOWN; preparation only."""
        from app.services.learning.item_supply.persistent_pack_explicit_recovery import prepare_explicit_recovery
        return prepare_explicit_recovery(self, task_ref, transaction=transaction)

    def prepare_next_phase(self, task_ref: PersistentPackTaskRef) -> IssuedPackPhase | BlockedPackPhase:
        self._task(task_ref)
        status=self.get_status(task_ref)
        if status.status == "ready":
            return BlockedPackPhase("pack_already_ready_no_new_paid", task_ref.pack_task_id)
        if status.status in {"blocked","paused"}:
            return BlockedPackPhase(status.reason,task_ref.pack_task_id)
        # Exactly one phase active. No lock is kept across network IO.
        self.conn.execute("SELECT pg_advisory_xact_lock(hashtext('persistent-public-phase'),hashtext(%s))",(str(task_ref.public_task_id),))
        pending=self.conn.execute("SELECT p.id,p.phase_id,p.record_kind,p.payload_json FROM " + SHARED + " p WHERE public_task_id=%s AND record_kind='phase' "
            "AND NOT EXISTS(SELECT 1 FROM " + SHARED + " done WHERE done.phase_id=p.phase_id AND done.record_kind='phase_result') LIMIT 1",
            (task_ref.public_task_id,)).fetchone()
        if pending is not None:
            reconciled=self._reconcile_phase(task_ref,pending)
            if reconciled is not None:
                return reconciled
            status=self.get_status(task_ref)
            if status.status=="ready":
                return BlockedPackPhase("pack_already_ready_no_new_paid",task_ref.pack_task_id)
        from app.services.learning.item_supply.persistent_pack_pipeline import PersistentPublicPipeline
        pipeline=PersistentPublicPipeline(self)
        version=next((self._versions(task_ref).get(s) for s in SLOTS
            if self._versions(task_ref).get(s) is None or self._versions(task_ref)[s].published_version_id is None),None)
        if len(status.current_version_ids)==5:
            phase=pipeline.prepare_relation(task_ref,tuple(status.current_version_ids))
        else:
            phase=pipeline.prepare_candidate(task_ref,version)
        if isinstance(phase, BlockedPackPhase):
            return phase
        self._issued[phase.record.phase_id]=(phase,canonical_hash(phase.record.model_dump(mode="json")))
        return phase

    def prepare_fresh_committed_revision(self, task_ref: PersistentPackTaskRef, *, transaction: Transaction) -> tuple[NativeRevisionOwner, PreparedNativeRevision]:
        from app.services.learning.item_supply.persistent_pack_fresh_committed_revision import prepare_fresh_committed_revision
        return prepare_fresh_committed_revision(self, task_ref, transaction=transaction)

    def prepare_source_mapping_successor(self, task_ref: PersistentPackTaskRef, *, public_materials: tuple[PublicMaterialV2, ...],
                                         course_materials: tuple[PublicMaterialV2, ...]) -> IssuedSourceMappingSuccessor:
        from app.services.learning.item_supply.persistent_pack_source_successor import prepare
        return prepare(self,task_ref,public_materials=public_materials,course_materials=course_materials)

    def compose_source_mapping_successor(self, task_ref: PersistentPackTaskRef, *, public_claim_id: str,
                                         course_claim_id: str) -> IssuedSourceMappingSuccessor:
        from app.services.learning.item_supply.persistent_pack_source_successor import compose
        return compose(self,task_ref,public_claim_id=public_claim_id,course_claim_id=course_claim_id)

    def resolve_source_mapping_successor(self, task_ref: PersistentPackTaskRef, record_id: UUID) -> IssuedSourceMappingSuccessor:
        from app.services.learning.item_supply.persistent_pack_source_successor import resolve
        return resolve(self,task_ref,record_id)

    def prepare_successor_committed_revision(self, task_ref: PersistentPackTaskRef, *, transaction: Transaction,
                                            source_successor: IssuedSourceMappingSuccessor | None = None) -> tuple[NativeRevisionOwner, PreparedNativeRevision]:
        from app.services.learning.item_supply.persistent_pack_fresh_committed_revision import prepare_successor_committed_revision
        return prepare_successor_committed_revision(self, task_ref, transaction=transaction,source_successor=source_successor)

    def prepare_committed_revision(self, task_ref: PersistentPackTaskRef, *, transaction: Transaction) -> tuple[NativeRevisionOwner, PreparedNativeRevision]:
        from app.services.learning.item_supply.persistent_pack_committed_revision import prepare_committed_revision
        return prepare_committed_revision(self, task_ref, transaction=transaction)

    def prepare_committed_child_recheck(self, task_ref: PersistentPackTaskRef, *, preparation_id: UUID,
            artifact_id: UUID, lineage_id: UUID, source_successor: IssuedSourceMappingSuccessor,
            transaction: Transaction) -> IssuedCommittedChildRecheck:
        from app.services.learning.item_supply.persistent_pack_committed_recheck import prepare
        return prepare(self, task_ref, preparation_id=preparation_id, artifact_id=artifact_id, lineage_id=lineage_id,
            source_successor=source_successor, transaction=transaction)

    def require_phase(self, phase: IssuedPackPhase, *, kind: str | None = None) -> datetime:
        self._guard()
        if type(phase) is not IssuedPackPhase or phase.owner is not self:
            raise PersistentPackPending("persistent_process_issuer_required")
        entry=self._issued.get(phase.record.phase_id)
        if entry is None or entry[0] is not phase or entry[1]!=canonical_hash(phase.record.model_dump(mode="json")):
            raise PersistentPackPending("persistent_phase_frame_changed")
        if kind is not None and phase.record.kind!=kind:
            raise PersistentPackPending("persistent_phase_kind_mismatch")
        committed = self._committed_child_rechecks.get(phase.record.phase_id)
        if committed is None:
            source = self._committed_child_recheck_sources.get(phase.record.phase_id)
            if source is None:
                self._task(phase.task)
            else:
                from app.services.learning.item_supply.persistent_pack_source_successor import require as require_source
                if source[0] is not phase:
                    raise PersistentPackPending("persistent_committed_child_phase_changed")
                require_source(source[1], self, phase.task)
        else:
            from app.services.learning.item_supply.persistent_pack_committed_recheck import require
            require(committed[0], lease=self.runtime.refresh_lease(phase.record.lease, now=self._guard()))
        self.runtime._control(phase.record.lease,now=datetime.now(UTC),compare_version=False)
        now=self._guard()
        if now>=phase.record.valid_until:
            raise PersistentPackPending("persistent_phase_expired_same_task_retained")
        self.conn.execute("SELECT item_supply_internal.assert_persistent_pack_phase(%s)",(Jsonb(phase.record.model_dump(mode="json")),))
        return now

    def prepare_committed_child_admission(self, task_ref: PersistentPackTaskRef, *, artifact_id: UUID, lineage_id: UUID,
            recheck_receipt_id: UUID, validation_receipt_id: UUID, blind_receipt_id: UUID, review_receipt_id: UUID,
            source_successor: IssuedSourceMappingSuccessor, transaction: Transaction) -> IssuedCommittedChildAdmission:
        from app.services.learning.item_supply.persistent_pack_committed_admission import prepare
        return prepare(self,task_ref,artifact_id=artifact_id,lineage_id=lineage_id,recheck_receipt_id=recheck_receipt_id,
            validation_receipt_id=validation_receipt_id,blind_receipt_id=blind_receipt_id,review_receipt_id=review_receipt_id,
            source_successor=source_successor,transaction=transaction)

    def run_committed_child_admission(self, frame: IssuedCommittedChildAdmission) -> PersistentPhaseOutcome:
        from app.services.learning.item_supply.persistent_pack_committed_admission import run
        return run(frame)

    def run_until_terminal(self, task_ref: PersistentPackTaskRef) -> PersistentPackStatus:
        """Single active executor, single slot; internal finite phase sequencing.

        No business-round/time cap. Every phase still has original bounded
        authorization. Known committed results are reused; opaque output stops.
        A session-level dispatcher lock is NOT a transaction/quality authority.
        """
        import time
        if (self.conn.info.transaction_status!=TransactionStatus.IDLE
                or not self.settings.learning_item_supply_scheduler_enabled):
            raise PersistentPackPending("persistent_single_executor_idle_scheduler_required")
        key=str(task_ref.public_task_id)
        with self.conn.transaction():
            self._task(task_ref)
            lock=self.conn.execute("SELECT pg_try_advisory_lock(hashtext('persistent-single-executor'),hashtext(%s)) AS held",(key,)).fetchone()
            if lock is None or lock["held"] is not True:
                return PersistentPackStatus(status="blocked",reason="another_original_dispatcher_active",qualified_slots=0,
                    current_version_ids=(),pack_task_id=task_ref.pack_task_id)
        try:
            while True:
                with self.conn.transaction():
                    status=self.get_status(task_ref)
                    if status.status in {"ready","blocked","paused"}:
                        return status
                    phase=self.prepare_next_phase(task_ref)
                    if isinstance(phase,BlockedPackPhase) and phase.safe_reason=="pack_already_ready_no_new_paid":
                        return self.get_status(task_ref)
                    if isinstance(phase,BlockedPackPhase) and phase.safe_reason not in {
                            "unstarted_live_phase_wait_original_expiry","unstarted_phase_original_runtime_pending"}:
                        return status.model_copy(update={"status":"blocked","reason":phase.safe_reason})
                if isinstance(phase,BlockedPackPhase):
                    # No transaction/row lock across wait or provider IO. Stop /
                    # source revocation is rechecked on every bounded polling turn.
                    time.sleep(5)
                    continue
                self.run_phase(phase)
        except ValueError:
            return PersistentPackStatus(status="blocked",reason="current_source_or_original_runtime_denied",
                qualified_slots=0,current_version_ids=(),pack_task_id=task_ref.pack_task_id)
        finally:
            with self.conn.transaction():
                self.conn.execute("SELECT pg_advisory_unlock(hashtext('persistent-single-executor'),hashtext(%s))",(key,))

    def run_phase(self, phase: IssuedPackPhase) -> PersistentPhaseOutcome:
        if self.conn.info.transaction_status!=TransactionStatus.IDLE:
            raise PersistentPackPending("persistent_phase_network_idle_required")
        with self.conn.transaction():
            self.require_phase(phase)
            if phase.record.phase_id in self._started:
                raise PersistentPackPending("persistent_phase_once_consumed")
            self._public_event(phase.record.public_task_id,"dispatch_started",dict(schema_version="persistent_dispatch_started_v1",
                phase_id=str(phase.record.phase_id)),key=phase.record.operation_key,root_id=phase.record.root_id,
                job_id=phase.record.job_id,phase_id=phase.record.phase_id)
            self._started.add(phase.record.phase_id)
        from app.services.learning.item_supply.persistent_pack_pipeline import PersistentPublicPipeline
        try:
            result=PersistentPublicPipeline(self).run(phase)
        except Exception as exc:
            from app.services.learning.item_supply.persistent_pack_diagnostics import observe_persistent_pack_failure
            observe_persistent_pack_failure(exc)
            result=PersistentPhaseOutcome(phase_id=phase.record.phase_id,status="outcome_unknown",
                safe_reason="source_or_original_stage_failed" if isinstance(exc,ValueError) else "opaque_stage_outcome_unknown")
        with self.conn.transaction():
            self._store_outcome(phase.task,phase.record,result)
        return result
