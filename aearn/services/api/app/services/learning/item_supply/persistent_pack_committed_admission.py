"""One exact, unfunded admission-only action over committed finite KC quality DATA."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

from psycopg.pq import TransactionStatus
from psycopg.transaction import Transaction
from psycopg.types.json import Jsonb

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.committed_admission_quality import (
    BLIND, CHILD, PREPARATION, RECHECK, REVIEW, REVIEW_JOB, VALIDATION,
    CommittedChildQuality, read_committed_quality,
)
from app.services.learning.item_supply.finite_task_ambiguity import FiniteTaskAmbiguityOwner, FiniteAmbiguityReceiptV1, build_finite_ambiguity_plan
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.parameter_profiles import ExecutionParameterProfileV1, ProfileKeyV1
from app.services.learning.item_supply.persistent_pack_contracts import PersistentPackTaskRef, PersistentPublicVersionRecord, PersistentPhaseOutcome
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.policies import RetryPolicyV1
from app.services.learning.item_supply.shared_pipeline_repository import SharedPipelineArtifactRepository, ResolvedSharedGeneration

if TYPE_CHECKING:
    from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
    from app.services.learning.item_supply.persistent_pack_source_successor import IssuedSourceMappingSuccessor
    from app.services.learning.item_supply.native_normal_revision_readmission import NativeNormalRevisionReadmissionOwner
    from app.services.learning.item_supply.shared_admission_facts import SharedAdmissionFactsOwner

JOURNAL = "tutor_item_supply_shared_persistent_pack_journal"
KIND = "committed_admission"
ACTION = uuid5(NAMESPACE_URL,"aearn:committed-admission:"+RECHECK.hex)
KEY = "committed.admission."+RECHECK.hex
BODY_PINS: dict[str,str] = {
    "item_supply_internal.assert_normal_revision_readmission_v2(jsonb)": "de5e9d508af74c23d6e83f3efdfaf0562c799e1625207988840be4fc4b42da5c",
    "item_supply_internal.enforce_normal_revision_readmission_insert()": "4000dcccef78eb5a6e00039270d96cf26d259e94a9ea51291417d9bd86efe1fd",
    "item_supply_internal.normal_revision_readmission_matches(uuid,uuid,text)": "5ea5a21ac6fddf078da074274e4fd8efea563afd0ee8c5a4bd5428ecf4deda34",
    "item_supply_internal.deny_revision_admission_without_discharge()": "c95c1e10e96c968e4b6377440bcf4fefd23c16271d4640e1940badc8aef10d9b",
    "item_supply_internal.deny_controlled_counterexample_admission()": "092f245fb0efa0e584b34acb33a6b8f039fbb0c2b503ffa828ffa8108e1acbae",
    "enforce_learning_item_native_publication_proof()": "2968c704081ddb8f336edb62212d0b06c2c47f3fb084e22992ccba10b8f5ea08",
    "item_supply_internal.assert_committed_child_quality(jsonb)": "91dc7179a46665986be1018d382386c1772a8e6b007f39937ba2f866fdd4b720",
    "item_supply_internal.assert_committed_child_admission(jsonb)": "6c0703ad83796e434b5b957b485d3f9e4c26b945ab7c9dd3c8480e17200b91d9",
    "item_supply_internal.committed_child_admission_for_job(uuid)": "d1d767f1e8b795b7d9449ddb1671e0f180b23783961253b282720c1d84992da3",
    "item_supply_internal.assert_normal_revision_readmission_v3(jsonb)": "e798ca1018007fc2b9c5863ad14d7f2287424da38e5f81f51d8778c26becc24c",
    "item_supply_internal.assert_normal_revision_readmission(jsonb)": "db1ab4aaf95bfb60fd2e48d6237cffb46f4d09384e4529a83a90ecb8c9ec72ae",
    "enforce_item_supply_shared_admission_facts()": "93a806a714bf7c0bf65a683e89eef03f6a3460ca204cf2913fc5eceaa12ce17f",
    "item_supply_internal.committed_child_evaluation_matches(jsonb)": "c35f1f08e8aa90808891390b248e289919ee5d81ada162f5b558fd9a06226bcb",
    "enforce_item_supply_shared_stage_original()": "59a08acf16bd66e1f405a8496898965d666bdedfdf531f4df4fb9e38f06bb101",
    "enforce_item_supply_shared_pipeline_artifact()": "062595c5137f2d272d240331bfd0ae529c167141beca5609cc40b0c7f3c34272",
    "enforce_learning_item_native_validation_import()": "262346250b49d1dd49b073175d0162738aa8c9fd85d0bb7dfdea10b5d4784e68",
    "item_supply_internal.enforce_persistent_pack_journal_insert()": "6cb924d2b8a396cf2bb2c01f7315e659eadbc41bdcd0eea386190a5e8886580d",
    "item_supply_internal.deny_committed_admission_reservation()": "558862b541e3d8c6d169da2cc173c2f705246648af1d72f78e4ca05121aaf46d"
}


@dataclass(frozen=True, repr=False)
class IssuedCommittedChildAdmission:
    owner: PersistentPackTaskOwner
    task: PersistentPackTaskRef  # Process-only PRIVATE locator. Never in payload.
    source_successor: IssuedSourceMappingSuccessor
    admission_id: UUID
    lease: JobLeaseV1
    version: PersistentPublicVersionRecord
    quality: CommittedChildQuality
    ambiguity: FiniteAmbiguityReceiptV1
    payload: dict[str,Any]

    @property
    def normal_owner(self) -> NativeNormalRevisionReadmissionOwner:
        return self.owner._committed_admission_owners[self.admission_id][0]  # type: ignore[no-any-return]

    @property
    def facts_owner(self) -> SharedAdmissionFactsOwner:
        return self.owner._committed_admission_owners[self.admission_id][1]  # type: ignore[no-any-return]

    @property
    def valid_until(self) -> datetime:
        return datetime.fromisoformat(self.payload["valid_until"])

    def generation_data(self) -> ResolvedSharedGeneration:
        q = self.quality
        return ResolvedSharedGeneration(q.artifact,q.request,q.source,q.generation_receipt,self.lease)


def require_schema(conn: Any) -> None:
    if not BODY_PINS:
        raise PipelineRepositoryError("COMMITTED_ADMISSION_547_REQUIRED")
    for name,pin in BODY_PINS.items():
        r = conn.execute("SELECT p.prosrc,p.prosecdef,p.proconfig,l.lanname FROM pg_proc p "
            "JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure(%s)",(name,)).fetchone()
        if (r is None or r["prosecdef"] is not True or r["lanname"] != "plpgsql"
                or r["proconfig"] != ["search_path=pg_catalog, public, item_supply_internal, pg_temp"]
                or hashlib.sha256(r["prosrc"].encode()).hexdigest() != pin):
            raise PipelineRepositoryError("COMMITTED_ADMISSION_547_REQUIRED")


def require(frame: IssuedCommittedChildAdmission, *, committed: bool = True) -> datetime:
    from app.services.learning.item_supply.persistent_pack_source_successor import require as require_source
    if type(frame) is not IssuedCommittedChildAdmission:
        raise PipelineRepositoryError("COMMITTED_ADMISSION_ORIGINAL_FRAME_REQUIRED")
    core = frame.owner
    entry = core._committed_admissions.get(frame.admission_id)
    if (entry is None or entry[0] is not frame or entry[1] != canonical_hash(frame.payload)
            or frame.payload["lease"] != frame.lease.model_dump(mode="json")
            or frame.payload["version"] != frame.version.model_dump(mode="json")
            or frame.payload["quality"] != frame.quality.payload()
            or frame.payload["ambiguity"] != frame.ambiguity.model_dump(mode="json")):
        raise PipelineRepositoryError("COMMITTED_ADMISSION_FRAME_CHANGED")
    require_schema(core.conn)
    require_source(frame.source_successor,core,frame.task)
    q = read_committed_quality(core)
    if q.payload() != frame.quality.payload():
        raise PipelineRepositoryError("COMMITTED_ADMISSION_QUALITY_CHANGED")
    for material,receipt in zip(q.request.materials,q.generation_receipt.sources,strict=True):
        core.type_owner.source_authority.assert_current(material,receipt)
    core.runtime._control(frame.lease,now=core._guard())
    row = core.conn.execute("SELECT payload_json,payload_hash,(payload_json->>'capture_txid')::bigint=txid_current() AS same_top "
        "FROM "+JOURNAL+" WHERE id=%s AND record_kind=%s FOR SHARE",(frame.admission_id,KIND)).fetchone()
    if (row is None or (committed and row["same_top"]) or row["payload_json"] != frame.payload
            or row["payload_hash"] != canonical_hash(frame.payload)):
        raise PipelineRepositoryError("COMMITTED_ADMISSION_PREPARATION_COMMIT_REQUIRED")
    core.conn.execute("SELECT item_supply_internal.assert_committed_child_admission(%s)",(Jsonb(frame.payload),))
    return core._guard()


def prepare(core: PersistentPackTaskOwner, task: PersistentPackTaskRef, *, artifact_id: UUID, lineage_id: UUID,
            recheck_receipt_id: UUID, validation_receipt_id: UUID, blind_receipt_id: UUID, review_receipt_id: UUID,
            source_successor: IssuedSourceMappingSuccessor, transaction: Transaction) -> IssuedCommittedChildAdmission:
    from app.services.learning.item_supply.persistent_pack_source_successor import require as require_source
    from app.services.learning.item_supply.native_normal_revision_readmission import NativeNormalRevisionReadmissionOwner
    from app.services.learning.item_supply.shared_admission_facts import SharedAdmissionFactsOwner
    if (artifact_id,lineage_id,recheck_receipt_id,validation_receipt_id,blind_receipt_id,review_receipt_id) != (
            CHILD,PREPARATION,RECHECK,VALIDATION,BLIND,REVIEW):
        raise PipelineRepositoryError("COMMITTED_ADMISSION_EXACT_RECEIPTS_REQUIRED")
    if (type(transaction) is not Transaction or getattr(transaction,"_conn",None) is not core.conn
            or transaction.status != transaction.Status.ACTIVE or not getattr(transaction,"_outer_transaction",False)
            or getattr(transaction,"_stack_index",-1) != 0 or getattr(core.conn,"_num_transactions",0) != 1
            or core.conn.info.transaction_status != TransactionStatus.INTRANS):
        raise PipelineRepositoryError("COMMITTED_ADMISSION_ORIGINAL_TOP_REQUIRED")
    previous = transaction.force_rollback
    transaction.force_rollback = True
    require_schema(core.conn)
    record = require_source(source_successor,core,task)
    core.conn.execute("SELECT pg_advisory_xact_lock(hashtext('committed-child-admission'),hashtext(%s))",(str(RECHECK),))
    if core.conn.execute("SELECT 1 FROM "+JOURNAL+" WHERE record_kind=%s AND operation_key=%s",(KIND,KEY)).fetchone():
        raise PipelineRepositoryError("COMMITTED_ADMISSION_ONCE_ALREADY_ISSUED")
    if core.conn.execute("SELECT 1 FROM tutor_item_supply_shared_normal_revision_readmissions WHERE generation_artifact_id=%s "
            "UNION ALL SELECT 1 FROM tutor_item_supply_shared_admission_facts WHERE generation_artifact_id=%s",(CHILD,CHILD)).fetchone():
        raise PipelineRepositoryError("COMMITTED_ADMISSION_ALREADY_HAS_FACTS")
    q = read_committed_quality(core)
    version = next((v for v in core._versions(task).values() if v.artifact_id == CHILD),None)
    if (version is None or version.published_version_id is not None or version.specification != q.spec
            or not any(s.public_slot_id == version.public_slot_id for s in record.slots)):
        raise PipelineRepositoryError("COMMITTED_ADMISSION_CURRENT_SAME_SLOT_REQUIRED")
    row = core.conn.execute("SELECT profile_json FROM tutor_item_supply_parameter_profiles WHERE profile_hash=%s",
        (q.review_lease.profile.profile_hash,)).fetchone()
    if row is None:
        raise PipelineRepositoryError("COMMITTED_ADMISSION_HISTORICAL_PROFILE_REQUIRED")
    historical = ExecutionParameterProfileV1.model_validate_json(json.dumps(row["profile_json"]))
    key = ProfileKeyV1.model_validate(historical.profile_key.model_copy(update={
        "agent_role":"native.shared.admission-only-v1","prompt_version":"no-provider-admission-v1"}))
    next_version = core.conn.execute("SELECT COALESCE(max(profile_version),0)+1 AS v FROM tutor_item_supply_parameter_profiles "
        "WHERE profile_key_hash=%s",(key.key_hash,)).fetchone()
    assert next_version is not None
    now = core._guard()
    values = historical.current.model_copy(update={"parent_deadline_ms":900000,"stage_deadline_ms":900000})
    profile = ExecutionParameterProfileV1(profile_key=key,version=next_version["v"],state="frozen",initial=values,
        current=values,last_stable=values,floor=values,ceiling=values,measurement_window_started_at=now,
        change_reason="committed_admission_no_provider_v1",trusted_initial_evidence=(q.spec.specification_hash,q.review_row["receipt_hash"]))
    job = core.runtime.enqueue(root_id=q.artifact["root_id"],stage_key="committed.admission."+ACTION.hex,
        profile=profile,now=now,priority=1000,aging_seconds=86400,visibility="public",
        retry_policy=RetryPolicyV1(max_transient_attempts=1,initial_backoff_ms=1,maximum_backoff_ms=1))
    lease = core.runtime.claim(root_id=q.artifact["root_id"],lease_owner="committed.admission."+ACTION.hex,
        now=core._guard(),lease_seconds=900,visibility="public")
    if lease is None or lease.job_id != job:
        raise PipelineRepositoryError("COMMITTED_ADMISSION_EXACT_NEW_CONTROL_REQUIRED")
    until = min(lease.expires_at,lease.parent_deadline,lease.profile.parent_deadline_at,source_successor.valid_until,
        lease.profile.bound_at+timedelta(milliseconds=lease.profile.values.stage_deadline_ms))
    now = core._guard()
    ambiguity_owner = FiniteTaskAmbiguityOwner(None,parent_deadline_at=until)
    ambiguity = ambiguity_owner.run(q.source,build_finite_ambiguity_plan(q.source,spec=q.spec,inputs=q.inputs),
        spec=q.spec,inputs=q.inputs,run_id=uuid4())
    txrow = core.conn.execute("SELECT txid_current() AS id").fetchone()
    assert txrow is not None
    payload = dict(schema_version="committed_child_admission_v1",purpose="admission_only_no_provider",admission_id=str(ACTION),
        operation_key=KEY,public_task_id=str(task.public_task_id),public_slot_id=str(version.public_slot_id),
        revision_id=str(version.revision_id),root_id=str(q.artifact["root_id"]),artifact_id=str(CHILD),lineage_id=str(PREPARATION),
        review_job_id=str(REVIEW_JOB),lease=lease.model_dump(mode="json"),version=version.model_dump(mode="json"),
        quality=q.payload(),ambiguity=ambiguity.model_dump(mode="json"),checked_at=now.isoformat(),valid_until=until.isoformat(),
        source_valid_until=source_successor.valid_until.isoformat(),capture_txid=txrow["id"],provider_requests=0)
    core.conn.execute("INSERT INTO "+JOURNAL+"(id,public_task_id,record_kind,operation_key,root_id,job_id,phase_id,payload_json) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",(ACTION,task.public_task_id,KIND,KEY,q.artifact["root_id"],job,ACTION,Jsonb(payload)))
    frame = IssuedCommittedChildAdmission(core,task,source_successor,ACTION,lease,version,q,ambiguity,payload)
    core._committed_admissions[ACTION] = (frame,canonical_hash(payload))
    normal = NativeNormalRevisionReadmissionOwner(None,enabled=True,committed_admission=frame)
    facts = SharedAdmissionFactsOwner(core.conn,enabled=True,normal_readmission_owner=normal,committed_admission=frame)
    core._committed_admission_owners[ACTION] = (normal,facts)
    require(frame,committed=False)
    transaction.force_rollback = previous
    return frame


def run(frame: IssuedCommittedChildAdmission) -> PersistentPhaseOutcome:
    from app.services.learning.item_bank.native_import import NativeLearningItemBankImporter
    from app.services.learning.item_bank.native_publication import NativeLearningItemPublicationService
    core = frame.owner
    if core.conn.info.transaction_status != TransactionStatus.IDLE:
        raise PipelineRepositoryError("COMMITTED_ADMISSION_IDLE_REQUIRED")
    with core.conn.transaction():
        facts = frame.facts_owner.issue_committed(frame)
    if facts.evaluation.disposition != "eligible_internal":
        return PersistentPhaseOutcome(phase_id=frame.admission_id,status="quality_failed",safe_reason="original_full_admission_denied",artifact_id=CHILD)
    artifacts = SharedPipelineArtifactRepository(core.conn,enabled=True)
    importer = NativeLearningItemBankImporter(core.conn,core.settings,artifacts=artifacts,
        source_authority=core.type_owner.source_authority,enabled=True,committed_admission=frame)
    publisher = NativeLearningItemPublicationService(core.conn,core.settings,importer=importer,facts_owner=frame.facts_owner,
        approved_internal_bindings=tuple(core.type_owner.query._bindings.values()),enabled=True)
    with core.conn.transaction():
        require(frame)
        imported = importer.import_candidate(lease=frame.lease,artifact_id=CHILD,validation_receipt_id=VALIDATION,
            spec=frame.quality.spec,import_key="committed.admission."+frame.admission_id.hex)
        proof = publisher.publish_internal(imported,lease=frame.lease,spec=frame.quality.spec,facts_receipt=facts)
        qualified = frame.version.model_copy(update={"published_version_id":proof.version_id})
        core._public_event(frame.version.public_task_id,"qualified",qualified.model_dump(mode="json"),
            key="persistent.version."+frame.version.revision_id.hex,root_id=frame.version.root_id)
    return PersistentPhaseOutcome(phase_id=frame.admission_id,status="qualified",safe_reason="committed_quality_full_publication_completed",
        artifact_id=CHILD,published_version_id=proof.version_id)

