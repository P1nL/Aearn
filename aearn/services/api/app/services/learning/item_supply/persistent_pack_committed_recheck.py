"""Fresh once-only recheck of committed child DATA; never restores author capability."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid5, NAMESPACE_URL

from psycopg.pq import TransactionStatus
from psycopg.transaction import Transaction
from psycopg.types.json import Jsonb

from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash
from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1
from app.services.learning.item_supply.generation_contracts import GenerationRequestV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.persistent_pack_committed_revision import CommittedRevisionParent
from app.services.learning.item_supply.persistent_pack_contracts import (
    BlockedPackPhase, IssuedPackPhase, PersistentPackTaskRef, PersistentPublicVersionRecord,
)
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.review_deliberation_contracts import ReviewDisputeV1
from app.services.learning.item_supply.persistent_pack_repair import PersistentCloneFindingV1
from app.services.learning.item_supply.shared_continuation import SharedCandidateContinuationOwner

if TYPE_CHECKING:
    from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
    from app.services.learning.item_supply.persistent_pack_source_successor import IssuedSourceMappingSuccessor
    from app.services.learning.item_supply.native_revision_recheck import NativeRevisionRecheckOwner, PreparedNativeRevisionRecheck

CHILD = UUID("4e230bc0-dceb-4d39-bd17-bb5b2a41d8a3")
PREPARATION = UUID("4228be3f-a129-4c06-a531-4d69a37c1d46")
RECHECK_BODY_PIN = "9885428fd7199eb110aa5707baf8aa689445bc2233037bbcdb23afff37d5daba"
COMMITTED_BODY_PIN = "35017faca1ef617ff972ffd2777b62d1a1ef9570faf7206865e3c1ab4a5bc7b0"


@dataclass(frozen=True, repr=False)
class CommittedDisputes:
    disputes: tuple[ReviewDisputeV1 | PersistentCloneFindingV1, ...]


@dataclass(frozen=True, repr=False)
class CommittedChildInvestigationData:
    """Ancestral input DATA, not a provider/investigation capability."""
    root_id: UUID
    original: CommittedRevisionParent
    request: CommittedDisputes


@dataclass(frozen=True, repr=False)
class CommittedChildRevisionData:
    preparation_id: UUID
    investigation: CommittedChildInvestigationData
    spec: FiniteCandidateSpecV1
    context_hash: str
    deadline_at: datetime


@dataclass(frozen=True, repr=False)
class IssuedCommittedChildRecheck:
    owner: PersistentPackTaskOwner
    phase: IssuedPackPhase
    revision: CommittedChildRevisionData
    source_successor: IssuedSourceMappingSuccessor
    continuation_owner: SharedCandidateContinuationOwner
    payload: dict[str, Any]

    @property
    def recheck_owner(self) -> NativeRevisionRecheckOwner:
        return self.phase.prepared["recheck_owner"]  # type: ignore[no-any-return]

    @property
    def recheck(self) -> PreparedNativeRevisionRecheck:
        return self.phase.prepared["recheck"]  # type: ignore[no-any-return]


def require_schema(conn: Any) -> None:
    for signature, pin in {
        "item_supply_internal.enforce_revision_recheck_insert()": RECHECK_BODY_PIN,
        "item_supply_internal.assert_committed_child_recheck(jsonb,jsonb)": COMMITTED_BODY_PIN,
        "item_supply_internal.assert_committed_child_history(uuid,uuid,uuid)": "ca07c2265627c477393e318c27cb0667a84fb2efb95682c3aecdec1a57f621c4",
        "item_supply_internal.committed_child_version_data_matches(jsonb)": "ec01b6e9e097aea2b0c7258188ad7083e256807b323b5eafa1356a576c9b08c0",
        "item_supply_internal.enforce_persistent_pack_journal_insert()": "6cb924d2b8a396cf2bb2c01f7315e659eadbc41bdcd0eea386190a5e8886580d",
        "public.enforce_item_supply_shared_candidate_continuation()": "368c07a1950a76d042fb9fa142620e4c9ccec37ccb5597fa185f424207a55ca1",
    }.items():
        row = conn.execute("SELECT p.prosrc,p.prosecdef,p.proconfig,l.lanname FROM pg_proc p "
            "JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure(%s)", (signature,)).fetchone()
        if (row is None or hashlib.sha256(row["prosrc"].encode()).hexdigest() != pin
                or row["prosecdef"] is not True or row["lanname"] != "plpgsql"
                or row["proconfig"] != ["search_path=pg_catalog, public, item_supply_internal, pg_temp"]):
            raise PipelineRepositoryError("COMMITTED_CHILD_RECHECK_546_REQUIRED")


def _history(core: PersistentPackTaskOwner, preparation_id: UUID, artifact_id: UUID, lineage_id: UUID) -> dict[str, Any]:
    if (preparation_id, artifact_id, lineage_id) != (PREPARATION, CHILD, PREPARATION):
        raise PipelineRepositoryError("COMMITTED_CHILD_RECHECK_EXACT_AUTHORIZED_CASE_REQUIRED")
    records = {}
    for name, table, key, value in (
        ("preparation", "revision_preparations", "id", preparation_id),
        ("lineage", "revision_lineage", "id", lineage_id),
        ("output", "revision_generation_outputs", "preparation_id", preparation_id),
        ("artifact", "generation_artifacts", "id", artifact_id),
    ):
        row = core.conn.execute("SELECT *,xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_shared_" + table + " WHERE " + key + "=%s FOR SHARE", (value,)).fetchone()
        if row is None or row["same_transaction"]:
            raise PipelineRepositoryError("COMMITTED_CHILD_RECHECK_COMMITTED_DATA_REQUIRED")
        records[name] = row
    p, line, output, a = (records[n] for n in ("preparation", "lineage", "output", "artifact"))
    settlement = core.conn.execute("SELECT * FROM tutor_item_supply_shared_runtime_settlements WHERE id=%s FOR SHARE",
        (output["settlement_id"],)).fetchone()
    tx = core.conn.execute("SELECT txid_current() AS id").fetchone()
    if (settlement is None or tx is None or output["capture_txid"] == tx["id"]
            or (line["preparation_id"], line["child_artifact_id"], line["child_job_id"], line["root_id"])
            != (preparation_id, artifact_id, a["job_id"], a["root_id"])
            or (p["child_job_id"], output["job_id"], output["candidate_id"], output["root_id"])
            != (a["job_id"], a["job_id"], a["candidate_id"], a["root_id"])
            or (line["reservation_id"], line["settlement_id"], settlement["reservation_id"])
            != (output["reservation_id"], output["settlement_id"], output["reservation_id"])
            or output["payload_json"]["returned_state"] != "staged"
            or output["payload_json"]["preparation_hash"] != p["snapshot_hash"]
            or output["payload_json"]["result"]["source"] != a["source_json"]
            or output["payload_json"]["result"]["receipt"] != a["receipt_json"]
            or output["payload_json"]["request"] != a["request_json"]
            or output["payload_json"]["author_input"] != line["payload_json"]["author_input"]):
        raise PipelineRepositoryError("COMMITTED_CHILD_RECHECK_DURABLE_BINDING_CHANGED")
    for row in (p, line, output):
        if canonical_hash(row["payload_json"]) != row["snapshot_hash"]:
            raise PipelineRepositoryError("COMMITTED_CHILD_RECHECK_HISTORY_CHANGED")
    return records


def require(frame: IssuedCommittedChildRecheck, *, lease: JobLeaseV1 | None = None) -> dict[str, Any]:
    from app.services.learning.item_supply.persistent_pack_source_successor import require as require_source
    if type(frame) is not IssuedCommittedChildRecheck:
        raise PipelineRepositoryError("COMMITTED_CHILD_RECHECK_PROCESS_FRAME_REQUIRED")
    core = frame.owner
    entry = core._committed_child_rechecks.get(frame.phase.record.phase_id)
    if entry is None or entry[0] is not frame or entry[1] != canonical_hash(frame.payload):
        raise PipelineRepositoryError("COMMITTED_CHILD_RECHECK_PROCESS_FRAME_REQUIRED")
    phase_entry = core._issued.get(frame.phase.record.phase_id)
    if (phase_entry is None or phase_entry[0] is not frame.phase
            or phase_entry[1] != canonical_hash(frame.phase.record.model_dump(mode="json"))
            or frame.payload["phase"] != frame.phase.record.model_dump(mode="json")
            or frame.phase.version is None or frame.payload["version"] != frame.phase.version.model_dump(mode="json")
            or frame.revision.spec != frame.phase.version.specification
            or frame.payload["deadline_at"] != frame.revision.deadline_at.isoformat()):
        raise PipelineRepositoryError("COMMITTED_CHILD_RECHECK_FRAME_CHANGED")
    require_schema(core.conn)
    require_source(frame.source_successor, core, frame.phase.task)
    facts = _history(core, frame.revision.preparation_id, CHILD, frame.revision.preparation_id)
    current = lease or frame.phase.record.lease
    if (current.job_id != frame.phase.record.job_id or current.profile != frame.phase.record.lease.profile
            or current.generation != frame.phase.record.lease.generation):
        raise PipelineRepositoryError("COMMITTED_CHILD_RECHECK_OPERATION_CHANGED")
    adopted = frame.continuation_owner.resolve(lease=current, artifact_id=CHILD, spec=frame.revision.spec,
        source_authority=core.type_owner.source_authority)
    if (adopted.binding.binding_hash != frame.payload["adoption_hash"]
            or facts["lineage"]["snapshot_hash"] != frame.payload["lineage_hash"]
            or facts["output"]["snapshot_hash"] != frame.payload["output_hash"]):
        raise PipelineRepositoryError("COMMITTED_CHILD_RECHECK_HISTORY_CHANGED")
    core.conn.execute("SELECT item_supply_internal.assert_committed_child_recheck(%s,%s)",
        (Jsonb(frame.payload), Jsonb(current.model_dump(mode="json"))))
    facts["authority"] = core.type_owner.source_authority
    return facts


def prepare(core: PersistentPackTaskOwner, task: PersistentPackTaskRef, *, preparation_id: UUID,
            artifact_id: UUID, lineage_id: UUID, source_successor: IssuedSourceMappingSuccessor,
            transaction: Transaction) -> IssuedCommittedChildRecheck:
    from app.services.learning.item_supply.persistent_pack_source_successor import require as require_source
    from app.services.learning.item_supply.persistent_pack_pipeline import PersistentPublicPipeline
    from app.services.learning.item_supply.persistent_pack_candidate import PersistentCandidateExecutor
    from app.services.learning.item_supply.shared_validation import SharedValidationPipeline
    from app.services.learning.item_supply.shared_review import SharedReviewPipeline
    from app.services.learning.item_supply.native_revision_recheck import NativeRevisionRecheckOwner
    from app.services.learning.item_supply.diagnostic_policy import parse_bundle
    if (type(transaction) is not Transaction or getattr(transaction, "_conn", None) is not core.conn
            or transaction.status != transaction.Status.ACTIVE or not getattr(transaction, "_outer_transaction", False)
            or getattr(transaction, "_stack_index", -1) != 0 or getattr(core.conn, "_num_transactions", 0) != 1
            or core.conn.info.transaction_status != TransactionStatus.INTRANS):
        raise PipelineRepositoryError("COMMITTED_CHILD_RECHECK_ORIGINAL_TOP_REQUIRED")
    prior = transaction.force_rollback
    transaction.force_rollback = True
    require_schema(core.conn)
    task_record = require_source(source_successor, core, task)
    history = _history(core, preparation_id, artifact_id, lineage_id)
    p, line, a = (history[n] for n in ("preparation", "lineage", "artifact"))
    core.conn.execute("SELECT pg_advisory_xact_lock(hashtext('committed-child-recheck'),hashtext(%s))", (str(lineage_id),))
    if (core.conn.execute("SELECT 1 FROM tutor_item_supply_shared_revision_recheck_preparations WHERE lineage_id=%s", (lineage_id,)).fetchone()
            or core.conn.execute("SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts WHERE generation_artifact_id=%s", (artifact_id,)).fetchone()):
        raise PipelineRepositoryError("COMMITTED_CHILD_RECHECK_ONCE_OR_UNKNOWN_NO_REPLAY")
    parent_version = next((v for v in core._versions(task).values() if v.artifact_id == line["parent_artifact_id"]), None)
    if parent_version is None or not any(s.public_slot_id == parent_version.public_slot_id for s in task_record.slots):
        raise PipelineRepositoryError("COMMITTED_CHILD_RECHECK_ORIGINAL_SLOT_REQUIRED")
    spec = FiniteCandidateSpecV1.model_validate_json(json.dumps(
        p["payload_json"]["context"]["persistent_family_revision"]["child_specification"]))
    version = PersistentPublicVersionRecord(public_task_id=task.public_task_id,
        public_slot_id=parent_version.public_slot_id, slot=parent_version.slot,
        revision_id=uuid5(NAMESPACE_URL, "persistent.child." + preparation_id.hex),
        revision_seq=parent_version.revision_seq+1, parent_revision_id=parent_version.revision_id,
        candidate_id=a["candidate_id"], specification=spec, root_id=a["root_id"], artifact_id=artifact_id)
    pipeline = PersistentPublicPipeline(core)
    executor = PersistentCandidateExecutor(pipeline)
    continuation = SharedCandidateContinuationOwner(core.conn, core.settings, enabled=True)
    original = continuation._original(artifact_id, core.type_owner.source_authority)
    request = GenerationRequestV2.model_validate_json(json.dumps(original["request_json"]))
    if request.materials != source_successor.public_materials:
        raise PipelineRepositoryError("COMMITTED_CHILD_RECHECK_EXACT_SUCCESSOR_REQUIRED")
    phase = pipeline._phase(task, spec=spec, root=a["root_id"], materials=request.materials,
        operation="persistent.child." + preparation_id.hex + ".recheck", kind="candidate", version=version)
    if isinstance(phase, BlockedPackPhase):
        raise PipelineRepositoryError(phase.safe_reason)
    core._committed_child_recheck_sources[phase.record.phase_id] = (phase, source_successor)
    #546 explicitly permits this committed child DATA before validation/adoption.
    executor.record_version(phase, version, "version")
    adopted = continuation.adopt_persistent_phase(phase=phase, artifact_id=artifact_id, spec=spec,
        source_authority=core.type_owner.source_authority)
    parent = continuation._original_row(line["parent_artifact_id"])
    investigation = core.conn.execute("SELECT ip.payload_json AS preparation,ir.payload_json AS receipt "
        "FROM tutor_item_supply_shared_review_investigation_receipts ir "
        "JOIN tutor_item_supply_shared_review_investigation_preparations ip ON ip.id=ir.preparation_id "
        "WHERE ir.id=%s", (p["investigation_receipt_id"],)).fetchone()
    ancestor = None if investigation is None else core.conn.execute("SELECT payload_json "
        "FROM tutor_item_supply_shared_pipeline_receipts WHERE id=%s AND generation_artifact_id=%s "
        "AND artifact_kind='review_bundle'", (UUID(investigation["preparation"]["review_receipt_id"]), line["parent_artifact_id"])).fetchone()
    if ancestor is None or investigation is None:
        raise PipelineRepositoryError("COMMITTED_CHILD_RECHECK_COMPLETE_ANCESTRY_REQUIRED")
    parent_source = LearningItemSourceV1.model_validate_json(json.dumps(parent["source_json"]))
    parent_request = GenerationRequestV2.model_validate_json(json.dumps(parent["request_json"]))
    parent_data = CommittedRevisionParent(line["parent_artifact_id"], parent["artifact_hash"], parent_source,
        parent_version.specification, parent_request, parse_bundle(ancestor["payload_json"]).binding)
    disputes = tuple((PersistentCloneFindingV1 if d.get("schema_version") == "persistent_deterministic_clone_finding_v1" else ReviewDisputeV1)
        .model_validate_json(json.dumps(d)) for d in investigation["receipt"]["disputes"])
    revision = CommittedChildRevisionData(preparation_id,
        CommittedChildInvestigationData(a["root_id"], parent_data, CommittedDisputes(disputes)),
        spec, p["payload_json"]["context_hash"], min(phase.record.valid_until, source_successor.valid_until))
    payload = dict(schema_version="committed_child_recheck_binding_v2", preparation_id=str(preparation_id),
        preparation_hash=p["snapshot_hash"], lineage_id=str(lineage_id), lineage_hash=line["snapshot_hash"],
        artifact_id=str(artifact_id), artifact_hash=a["artifact_hash"], producer_job_id=str(a["job_id"]),
        output_hash=history["output"]["snapshot_hash"], settlement_id=str(history["output"]["settlement_id"]),
        adoption_hash=adopted.binding.binding_hash, phase=phase.record.model_dump(mode="json"),
        version=version.model_dump(mode="json"), source_deadlines=[dict(binding_digest=b,claim_receipt_id=c,
            retained_until=t.isoformat()) for b,c,t in source_successor.source_deadlines], deadline_at=revision.deadline_at.isoformat())
    frame = IssuedCommittedChildRecheck(core, phase, revision, source_successor, continuation, payload)
    core._committed_child_rechecks[phase.record.phase_id] = (frame, canonical_hash(payload))
    vp = SharedValidationPipeline(core.conn, core.settings, enabled=True, continuation_owner=continuation)
    gp = executor._generation()  # Configured owner only; no author/result registration.
    rp = SharedReviewPipeline(core.conn, core.settings, enabled=True, continuation_owner=continuation,
        trusted_model_bindings=gp._models)
    recheck_owner = NativeRevisionRecheckOwner(None, vp, rp, enabled=True, persistent_phase=phase, committed_child=frame)
    prepared = recheck_owner.prepare_committed_child(frame, lease=phase.record.lease)
    if prepared is None:
        raise PipelineRepositoryError("COMMITTED_CHILD_RECHECK_ONCE_CONSUMED")
    phase.prepared.update(candidate_executor=executor, resume_stage="committed_child_recheck",
        committed_child_frame=frame, generation_owner=gp, validation_owner=vp, review_owner=rp,
        continuation_owner=continuation, recheck_owner=recheck_owner, recheck=prepared)
    transaction.force_rollback = prior
    return frame

