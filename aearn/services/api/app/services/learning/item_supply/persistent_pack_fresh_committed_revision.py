"""One newly authorized revision execution; old investigation stays historical DATA."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
from typing import TYPE_CHECKING, Any
from uuid import UUID
from psycopg.pq import TransactionStatus
from psycopg.transaction import Transaction
from psycopg.types.json import Jsonb
from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.development_model_accounting import DevelopmentModelAccountingOwner, accounting_batch_for_lease
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.parameter_profiles import ProfileKeyV1
from app.services.learning.item_supply.persistent_pack_committed_revision import (
    TASK, PHASE, ROOT, RECEIPT, ARTIFACT, PREP_SHA, RECEIPT_SHA, JOURNAL, PRIVATE, RevisionOnlyContext,
)
from app.services.learning.item_supply.persistent_pack_contracts import PersistentPackTaskRef, PersistentPublicPhaseRecord
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.policies import RetryPolicyV1
from app.services.learning.item_supply.public_normal_source_ingress import PUBLIC_NORMAL_RECEIVER_PINS
from app.services.learning.item_supply.shared_continuation import (
    SharedCandidateContinuationOwner, SharedCandidateContinuationBindingV1, ResolvedSharedCandidateContinuation,
    bind_shared_candidate_continuation,
)
if TYPE_CHECKING:
    from app.services.learning.item_supply.persistent_pack_source_successor import IssuedSourceMappingSuccessor
    from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
    from app.services.learning.item_supply.native_review_investigation import NativeReviewInvestigationOwner
    from app.services.learning.item_supply.native_revision import NativeRevisionOwner, PreparedNativeRevision

KIND = "committed_revision_execution"
KEY = "p7.committed-revision." + TASK.hex + "." + RECEIPT.hex + ".execution"
STAGE = "revision.execution." + RECEIPT.hex
AUTHORIZATION = "beb3e25f2a11f9fcb6d6bac24d17e143a9909907befc9081ed540c937df72fc1"
SUCCESSOR_AUTHORIZATION = "68860baaac9273f5b952392ac094315e5042e13c7b75325c3b6ab3936ea95243"
SUCCESSOR_KEY = KEY + ".successor.1"
SUCCESSOR_STAGE = STAGE + ".successor.1"
PREDECESSOR = UUID("c8593cb3-2360-48c0-a7f8-a3a69c930184")
RECEIVER_PINS = {
    "item_supply_internal.confirmed_source_successor_allowed(jsonb)": "efd457d39e508464dc97a2b21f2c11487926011685dee1058f6bda03b5d4df86",
    "item_supply_internal.assert_source_mapping_successor(jsonb)": "4c67d2c7189bb7400af21402aba32be049b312bdb31332bffb77d7f8f832e206",
    "item_supply_internal.enforce_source_mapping_successor_insert()": "0f4fd99b506f3b2e117c45d66727675faac547ebb0335d7c1c214faa80ef2bf2",
    "item_supply_internal.revision_source_successor_matches(jsonb)": "450299724984a2c123774b0da6f768ecd541d125f8c207a84e9eb350b14ae504",
    "item_supply_internal.assert_committed_revision_execution(jsonb)": "7e6d8b7596d231dbac9fb83da54a3e47a8e58c85a85937b1a5d02c9a366736f1",
    "item_supply_internal.fresh_committed_revision_matches(jsonb)": "25044674cc353a88a66ca595ec21b4f39cb04b5208b1c6daebe50db5b9ea2c8e",
    "item_supply_internal.enforce_committed_revision_execution_insert()": "5be96158f3bc36d27095ff115bd93b1380ebe643cc357d96d84020484b914509",
    "item_supply_internal.enforce_native_revision_insert()": "b11320c5f781e34f0b962e73b3d91ea313502fd6cd0da30acb84a0d3d20dfbe5",
    "item_supply_internal.persistent_registered_family_revision_matches(jsonb)": "9262b89bbabebedc7a91fa7e6636a463751dfbc24aae1d745cd5463e572405e1",
}

@dataclass(frozen=True, repr=False)
class FreshRevisionExecution:
    owner: PersistentPackTaskOwner
    record_id: UUID
    lease: JobLeaseV1
    payload: dict[str, Any]
    valid_until: datetime


def contracts(conn: Any) -> None:
    pins = {**PUBLIC_NORMAL_RECEIVER_PINS, **RECEIVER_PINS}
    for signature, digest in pins.items():
        row = conn.execute("SELECT p.prosrc,p.prosecdef,p.prokind,p.proconfig FROM pg_proc p WHERE p.oid=to_regprocedure(%s)", (signature,)).fetchone()
        if (row is None or row["prosecdef"] is not True or row["prokind"] != "f"
                or row["proconfig"] != ["search_path=pg_catalog, public, item_supply_internal, pg_temp"]
                or hashlib.sha256(row["prosrc"].replace("\r\n", "\n").encode()).hexdigest() != digest):
            raise PipelineRepositoryError("FRESH_COMMITTED_REVISION_539_REQUIRED")
    row = conn.execute("SELECT pg_get_triggerdef(oid) AS definition FROM pg_trigger WHERE "
        "tgrelid='public.tutor_item_supply_private_persistent_pack_journal'::regclass "
        "AND tgname='a003_committed_revision_execution' AND tgenabled='O' AND NOT tgisinternal").fetchone()
    if row is None or row["definition"] != ("CREATE TRIGGER a003_committed_revision_execution BEFORE INSERT ON "
            "public.tutor_item_supply_private_persistent_pack_journal FOR EACH ROW EXECUTE FUNCTION "
            "item_supply_internal.enforce_committed_revision_execution_insert()"):
        raise PipelineRepositoryError("FRESH_COMMITTED_REVISION_539_REQUIRED")


def require_execution(context: RevisionOnlyContext) -> FreshRevisionExecution:
    execution = context.execution
    if type(execution) is not FreshRevisionExecution or execution.owner is not context.owner:
        raise PipelineRepositoryError("FRESH_COMMITTED_REVISION_ORIGINAL_ISSUER_REQUIRED")
    core = context.owner
    entry = core._fresh_revision_executions.get(RECEIPT)
    if (entry is None or entry[0] is not execution or entry[1] != canonical_hash(execution.payload)
            or execution.payload["execution_lease"] != execution.lease.model_dump(mode="json")
            or datetime.fromisoformat(execution.payload["valid_until"]) != execution.valid_until):
        raise PipelineRepositoryError("FRESH_COMMITTED_REVISION_ORIGINAL_ISSUER_REQUIRED")
    contracts(core.conn)
    authorization = execution.payload.get("authorization_sha256")
    if context.source_successor is None:
        if "source_successor_id" in execution.payload or "source_successor_hash" in execution.payload:
            raise PipelineRepositoryError("SOURCE_SUCCESSOR_ORIGINAL_ISSUER_REQUIRED")
    elif (authorization != SUCCESSOR_AUTHORIZATION
            or execution.payload.get("source_successor_id") != str(context.source_successor.record_id)
            or execution.payload.get("source_successor_hash") != canonical_hash(context.source_successor.payload)):
        raise PipelineRepositoryError("SOURCE_SUCCESSOR_ORIGINAL_ISSUER_REQUIRED")
    if authorization not in (AUTHORIZATION, SUCCESSOR_AUTHORIZATION):
        raise PipelineRepositoryError("FRESH_COMMITTED_REVISION_ORIGINAL_ISSUER_REQUIRED")
    key = SUCCESSOR_KEY if authorization == SUCCESSOR_AUTHORIZATION else KEY
    row = core.conn.execute("SELECT payload_json FROM " + PRIVATE + " WHERE id=%s AND pack_task_id=%s AND user_id=%s "
        "AND epoch=%s AND scope_id=%s AND intent_hash=%s AND record_kind=%s AND operation_key=%s FOR SHARE",
        (execution.record_id,TASK,context.task.user_id,context.task.epoch,context.task.scope_id,context.task.intent_hash,KIND,key)).fetchone()
    if row is None or row["payload_json"] != execution.payload:
        raise PipelineRepositoryError("FRESH_COMMITTED_REVISION_ACTUAL_ONCE_RECORD_REQUIRED")
    core.conn.execute("SELECT item_supply_internal.assert_committed_revision_execution(%s)", (Jsonb(execution.payload),))
    now = core._guard()
    core.runtime._control(execution.lease,now=now)
    batch = accounting_batch_for_lease(core.conn,execution.lease,now=now)
    if batch is None or str(batch["batch_id"]) != execution.payload["batch_id"] or now >= execution.valid_until:
        raise PipelineRepositoryError("FRESH_COMMITTED_REVISION_EXECUTION_EXPIRED_OR_CHANGED")
    return execution


def historical_parent(owner: NativeReviewInvestigationOwner, context: RevisionOnlyContext) -> ResolvedSharedCandidateContinuation:
    """Validate old adoption DATA, current sources and fresh canonical root; no old control renewal."""
    execution = require_execution(context)
    continuation = owner.review.continuation_owner
    if type(continuation) is not SharedCandidateContinuationOwner:
        raise PipelineRepositoryError("FRESH_COMMITTED_REVISION_ORIGINAL_CONTINUATION_REQUIRED")
    authority = context.owner.type_owner.source_authority
    continuation._require(authority)
    row = owner.conn.execute("SELECT binding_json,binding_hash FROM tutor_item_supply_shared_candidate_continuations "
        "WHERE job_id=%s AND generation_artifact_id=%s FOR SHARE", (context.record.job_id,ARTIFACT)).fetchone()
    if row is None:
        raise PipelineRepositoryError("FRESH_COMMITTED_REVISION_HISTORICAL_ADOPTION_REQUIRED")
    binding = SharedCandidateContinuationBindingV1.model_validate_json(json.dumps(row["binding_json"]))
    if context.source_successor is None:
        original = continuation._original(ARTIFACT,authority)
    else:
        from app.services.learning.item_supply.persistent_pack_source_successor import original as successor_original
        original = successor_original(continuation,context.source_successor)
    expected,source,request,_,inputs = bind_shared_candidate_continuation(artifact=original,
        spec=context.version.specification,lease=binding.adoption_lease,operation_key=binding.operation_key)
    meta = continuation.artifacts.context(execution.lease,now=context.owner._guard())
    if (row["binding_hash"] != binding.binding_hash or binding != expected
            or binding.adoption_lease != context.record.lease or binding.root_id != ROOT
            or UUID(str(meta["root_id"])) != ROOT or meta["canonical_key"] != binding.canonical_root_key
            or meta["coverage"] != context.version.specification.coverage_blueprint):
        raise PipelineRepositoryError("FRESH_COMMITTED_REVISION_HISTORICAL_ADOPTION_CHANGED")
    return ResolvedSharedCandidateContinuation(binding,context.record.lease,original,source,request,inputs)


def prepare_fresh_committed_revision(core: PersistentPackTaskOwner, task: PersistentPackTaskRef, *, transaction: Transaction) -> tuple[NativeRevisionOwner, PreparedNativeRevision]:
    return _prepare_execution(core, task, transaction=transaction, successor=False)


def prepare_successor_committed_revision(core: PersistentPackTaskOwner, task: PersistentPackTaskRef, *, transaction: Transaction,
                                         source_successor: IssuedSourceMappingSuccessor | None = None) -> tuple[NativeRevisionOwner, PreparedNativeRevision]:
    return _prepare_execution(core, task, transaction=transaction, successor=True,source_successor=source_successor)


def successor_predecessor(context: RevisionOnlyContext) -> UUID | None:
    """Only a live original issuer + exact SQL-validated successor may exclude the historical row."""
    execution = require_execution(context)
    return PREDECESSOR if execution.payload["authorization_sha256"] == SUCCESSOR_AUTHORIZATION else None


def _prepare_execution(core: PersistentPackTaskOwner, task: PersistentPackTaskRef, *, transaction: Transaction,
                       successor: bool, source_successor: IssuedSourceMappingSuccessor | None = None) -> tuple[NativeRevisionOwner, PreparedNativeRevision]:
    from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
    from app.services.learning.item_supply.persistent_pack_pipeline import PersistentPublicPipeline
    from app.services.learning.item_supply.shared_review import SharedReviewPipeline
    from app.services.learning.item_supply.shared_pipeline import SharedGenerationPipeline
    from app.services.learning.item_supply.native_review_investigation import NativeReviewInvestigationOwner
    from app.services.learning.item_supply.native_revision import NativeRevisionOwner
    if (type(core) is not PersistentPackTaskOwner or type(task) is not PersistentPackTaskRef or task.pack_task_id != TASK
            or type(transaction) is not Transaction or getattr(transaction,"_conn",None) is not core.conn
            or transaction.status != transaction.Status.ACTIVE or not getattr(transaction,"_outer_transaction",False)
            or getattr(transaction,"_stack_index",-1) != 0 or getattr(core.conn,"_num_transactions",0) != 1
            or core.conn.info.transaction_status != TransactionStatus.INTRANS):
        raise PipelineRepositoryError("FRESH_COMMITTED_REVISION_ORIGINAL_TOP_REQUIRED")
    prior = transaction.force_rollback
    transaction.force_rollback = True
    key = SUCCESSOR_KEY if successor else KEY
    stage = SUCCESSOR_STAGE if successor else STAGE
    authorization = SUCCESSOR_AUTHORIZATION if successor else AUTHORIZATION
    try:
        if source_successor is None:
            core._task(task)
        else:
            from app.services.learning.item_supply.persistent_pack_source_successor import require
            if not successor:
                raise PipelineRepositoryError("SOURCE_SUCCESSOR_EXPLICIT_REVISION_ONLY")
            require(source_successor,core,task)
        core.conn.execute("SELECT pg_advisory_xact_lock(hashtext('fresh-committed-revision'),hashtext(%s))", (str(RECEIPT),))
        if successor:
            if (core.conn.execute("SELECT 1 FROM " + PRIVATE + " WHERE pack_task_id=%s AND record_kind=%s AND operation_key=%s", (TASK,KIND,key)).fetchone()
                    or core.conn.execute("SELECT 1 FROM tutor_item_supply_shared_revision_preparations WHERE investigation_receipt_id=%s AND id<>%s", (RECEIPT,PREDECESSOR)).fetchone()):
                raise PipelineRepositoryError("SUCCESSOR_COMMITTED_REVISION_ONCE_CONSUMED")
        elif (core.conn.execute("SELECT 1 FROM " + PRIVATE + " WHERE pack_task_id=%s AND record_kind=%s", (TASK,KIND)).fetchone()
                or core.conn.execute("SELECT 1 FROM tutor_item_supply_shared_revision_preparations WHERE investigation_receipt_id=%s", (RECEIPT,)).fetchone()):
            raise PipelineRepositoryError("FRESH_COMMITTED_REVISION_ONCE_CONSUMED")
        contracts(core.conn)
        phase_row = core.conn.execute("SELECT payload_json FROM " + JOURNAL + " WHERE phase_id=%s AND record_kind='phase'", (PHASE,)).fetchone()
        prep = core.conn.execute("SELECT payload_json,snapshot_hash FROM tutor_item_supply_shared_review_investigation_preparations WHERE id=%s", (RECEIPT,)).fetchone()
        receipt = core.conn.execute("SELECT snapshot_hash FROM tutor_item_supply_shared_review_investigation_receipts WHERE id=%s", (RECEIPT,)).fetchone()
        if phase_row is None or prep is None or receipt is None or prep["snapshot_hash"] != PREP_SHA or receipt["snapshot_hash"] != RECEIPT_SHA:
            raise PipelineRepositoryError("FRESH_COMMITTED_REVISION_EXACT_HISTORY_REQUIRED")
        phase = PersistentPublicPhaseRecord.model_validate_json(json.dumps(phase_row["payload_json"]))
        versions = [v for v in core._versions(task).values() if v.revision_id == phase.revision_id and v.artifact_id == ARTIFACT]
        if len(versions) != 1:
            raise PipelineRepositoryError("FRESH_COMMITTED_REVISION_EXACT_HISTORY_REQUIRED")
        version = versions[0]
        continuation = SharedCandidateContinuationOwner(core.conn,core.settings,enabled=True)
        continuation._require(core.type_owner.source_authority)
        if source_successor is None:
            original = continuation._original(ARTIFACT,core.type_owner.source_authority)
        else:
            from app.services.learning.item_supply.persistent_pack_source_successor import original as successor_original
            original = successor_original(continuation,source_successor)
        from app.services.learning.item_supply.generation_contracts import GenerationRequestV2
        request = GenerationRequestV2.model_validate_json(json.dumps(original["request_json"]))
        source_deadlines = prep["payload_json"]["source_deadlines"]
        if source_successor is not None:
            source_deadlines = source_successor.payload["source_deadlines"]
        source_bound = min(datetime.fromisoformat(x["retained_until"]) for x in source_deadlines)
        if source_successor is not None:
            source_bound = min(source_bound,source_successor.valid_until)
        now = core._guard()
        if source_bound <= now:
            raise PipelineRepositoryError("FRESH_COMMITTED_REVISION_CURRENT_SOURCE_EXPIRED")
        pipeline = PersistentPublicPipeline(core)
        accounting = DevelopmentModelAccountingOwner(core.conn,enabled=True)
        batch = accounting.prepare_batch(root_id=ROOT,provider_key=pipeline.provider.provider_key,
            model=pipeline.provider.configured_model,now=now,valid_until=now+timedelta(seconds=7200))
        profile_row = core.conn.execute("SELECT p.profile_json->'profile_key' AS key FROM tutor_item_supply_shared_generation_artifacts a "
            "JOIN tutor_item_supply_parameter_profiles p ON p.profile_hash=a.request_json->'profile'->>'profile_hash' "
            "WHERE a.id=%s AND a.root_id=%s", (ARTIFACT,ROOT)).fetchone()
        if profile_row is None:
            raise PipelineRepositoryError("FRESH_COMMITTED_REVISION_ORIGINAL_PROFILE_KEY_REQUIRED")
        original_key = ProfileKeyV1.model_validate_json(json.dumps(profile_row["key"]))
        profile = pipeline._profile(version.specification,request.materials if source_successor is None else source_successor.public_materials,original_key)
        job = core.runtime.enqueue(root_id=ROOT,stage_key=stage,profile=profile,now=core._guard(),priority=80,
            aging_seconds=86400,visibility="public",retry_policy=RetryPolicyV1(max_transient_attempts=1,initial_backoff_ms=1,maximum_backoff_ms=1))
        lease = core.runtime.claim(root_id=ROOT,lease_owner=stage,now=core._guard(),lease_seconds=3600,visibility="public")
        if lease is None or lease.job_id != job:
            raise PipelineRepositoryError("FRESH_COMMITTED_REVISION_EXACT_EXECUTION_CLAIM_REQUIRED")
        accounting.bind_job(lease=lease,batch_id=UUID(str(batch["batch_id"])),now=core._guard())
        deadline = min(lease.expires_at,lease.parent_deadline,source_bound,
            lease.profile.bound_at+timedelta(milliseconds=lease.profile.values.stage_deadline_ms))
        stamp = core._guard()
        payload = dict(schema_version="persistent_committed_revision_execution_v1",authorization_sha256=authorization,
            task_ref=task.model_dump(mode="json"),historical_phase_id=str(PHASE),investigation_receipt_id=str(RECEIPT),
            investigation_receipt_hash=RECEIPT_SHA,investigation_preparation_hash=PREP_SHA,root_id=str(ROOT),
            execution_job_id=str(job),execution_lease=lease.model_dump(mode="json"),batch_id=str(batch["batch_id"]),
            profile_hash=lease.profile.profile_hash,source_deadlines=source_deadlines,issued_at=stamp.isoformat(),valid_until=deadline.isoformat())
        if source_successor is not None:
            payload.update(source_successor_id=str(source_successor.record_id),source_successor_hash=canonical_hash(source_successor.payload))
        record_id = core._private_event(task,KIND,payload,key=key)
        execution = FreshRevisionExecution(core,record_id,lease,payload,deadline)
        core._fresh_revision_executions[RECEIPT] = (execution,canonical_hash(payload))
        context = RevisionOnlyContext(core,task,phase,version,execution,source_successor)
        core._revision_contexts[PHASE] = (context,canonical_hash(phase.model_dump(mode="json")))
        model = pipeline.provider.configured_model
        bindings = {(pipeline.provider.provider_key,model):model}
        review = SharedReviewPipeline(core.conn,core.settings,enabled=True,continuation_owner=continuation,trusted_model_bindings=bindings)
        investigator = NativeReviewInvestigationOwner(review,enabled=True,protocol="scalar-evidence-v2")
        proof = investigator.issue_committed_revision(context)
        generation = SharedGenerationPipeline(core.conn,core.settings,enabled=True,trusted_model_bindings=bindings)
        revision = NativeRevisionOwner(investigator,generation,enabled=True)
        prepared = revision.prepare_committed(proof)
        if prepared is None:
            raise PipelineRepositoryError("FRESH_COMMITTED_REVISION_ONCE_CONSUMED")
        transaction.force_rollback = prior
        return revision,prepared
    except BaseException:
        core._fresh_revision_executions.pop(RECEIPT,None)
        core._revision_contexts.pop(PHASE,None)
        raise
