"""One explicitly approved NEW attempt; never historical clearance or paid IO.

Separate from consumed535. PRIVATE approval/binding and an original process
issuer bind the deterministic investigation attempt key; all other keys remain.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from psycopg.pq import TransactionStatus
from psycopg.transaction import Transaction
from psycopg.types.json import Jsonb

from app.services.learning.item_supply.persistent_pack_contracts import (
    BlockedPackPhase, IssuedPackPhase, PersistentPackPending, PersistentPackTaskRef,
)
from app.services.learning.item_supply.public_normal_source_ingress import require_public_normal_receivers

if TYPE_CHECKING:
    from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner

TASK = UUID("6739d3c5-6619-44ce-970f-0ab1e49f3acc")
PUBLIC = UUID("9378a05f-b33e-5fc9-9bd7-6f073c2e6c8c")
ROOT = UUID("7d4b85ba-a0ec-4348-ac11-3401c6bded47")
REVISION = UUID("7ac04190-a21c-41f9-b121-353680e38fb9")
SLOT = UUID("e14de564-394a-5685-8e0a-07f2dd819a6c")
FAILED = UUID("92f71c9e-94fd-4d7f-8bf9-9a15a920bcee")
UNKNOWN_PHASES = (UUID("8c5b0671-54ec-4f64-9412-17cd8c286d58"), FAILED)
LOGICAL_OPERATION = "persistent.candidate." + REVISION.hex + ".repair"
LOGICAL_STAGE = "persistent.stage." + REVISION.hex + ".investigation"
ATTEMPT_KEY = LOGICAL_STAGE + ".explicit_release_20261012"
_PRIVATE = "tutor_item_supply_private_persistent_pack_journal"
_KEY = "p7.explicit." + TASK.hex + "." + FAILED.hex
_AUTHORIZATION_SHA = "65e73bab11b2179ae8fb0543f360e6f9b812657496813f0626acc14d286dde43"
_NATIVE_SHA = "c9494f4ca56f63735d3e84c6a37a7151cb2bc2690a7ab146f53b0f6d4fd3dfad"
_RECEIVER_PINS = {
    "assert_persistent_explicit_recovery(jsonb,uuid)": "ada943c596eab4b5f50296ffd1f8972cf57ac3e0ef3e400c8b3e76e9c8093d3c",
    "enforce_persistent_explicit_insert()": "0b006b0065efa42bc12a70650e5ae19757e947ecd6c42bec7e2fe494cecb2e2c",
    "enforce_persistent_explicit_stage()": "747bccb205b98f5e1358044fd0f83e64979e3ef2b9eb5a6de16d39f96296ac75",
    "enforce_persistent_explicit_preparation()": "5d3098447a1c47bd5f1f1897ab4be55ba35bf4c9a0dc05e476440f15fcb6ce28",
}
_INDEX_SHA = "939954c16fabee278964a0b6866c9f3e8b8bf36f7ccf83ec6856701aead09e42"


@dataclass
class _AllocationPermission:
    owner: PersistentPackTaskOwner
    task: PersistentPackTaskRef
    transaction: Transaction
    txid: str
    approval_id: UUID
    payload: dict[str, Any]
    covered: set[UUID] = field(default_factory=set)


@dataclass(frozen=True)
class _BoundAttempt:
    owner: PersistentPackTaskOwner
    phase: IssuedPackPhase
    binding_id: UUID
    approval_id: UUID


def _top(owner: PersistentPackTaskOwner, transaction: Transaction) -> str:
    if (type(transaction) is not Transaction or getattr(transaction, "_conn", None) is not owner.conn
            or transaction.status != transaction.Status.ACTIVE or not getattr(transaction, "_outer_transaction", False)
            or getattr(transaction, "_stack_index", -1) != 0 or getattr(owner.conn, "_num_transactions", 0) != 1
            or owner.conn.info.transaction_status != TransactionStatus.INTRANS):
        raise PersistentPackPending("explicit_recovery_top_required")
    row = owner.conn.execute("SELECT txid_current()::text AS txid,current_setting('TimeZone') AS timezone").fetchone()
    if row is None or row["timezone"] != "Asia/Shanghai":
        raise PersistentPackPending("explicit_recovery_snapshot_timezone_required")
    return str(row["txid"])


def _contracts(owner: PersistentPackTaskOwner) -> None:
    if hashlib.sha256(Path(__file__).with_name("native_review_investigation.py").read_bytes()).hexdigest() != _NATIVE_SHA:
        raise PersistentPackPending("explicit_recovery_context_repair_version_required")
    require_public_normal_receivers(owner.conn)
    for suffix, pin in _RECEIVER_PINS.items():
        row = owner.conn.execute("SELECT p.prosrc,p.prosecdef,p.prokind,p.proconfig,"
            "p.proowner='aearn_b1d_runtime_20261001'::regrole AS owner_ok,"
            "p.proacl=ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[] AS acl_ok "
            "FROM pg_proc p WHERE p.oid=to_regprocedure(%s)", ("item_supply_internal." + suffix,)).fetchone()
        if (row is None or hashlib.sha256(row["prosrc"].encode()).hexdigest() != pin
                or row["prosecdef"] is not True or row["prokind"] != "f" or row["owner_ok"] is not True
                or row["acl_ok"] is not True
                or row["proconfig"] != ["search_path=pg_catalog, public, item_supply_internal, pg_temp"]):
            raise PersistentPackPending("explicit_recovery_exact_536_receiver_required")
    row = owner.conn.execute("SELECT pg_get_indexdef(indexrelid) AS definition,indisunique,indisvalid,indisready "
        "FROM pg_index WHERE indexrelid=to_regclass('public.shared_investigation_explicit_review_once')").fetchone()
    if (row is None or not all(row[k] is True for k in ("indisunique", "indisvalid", "indisready"))
            or hashlib.sha256(row["definition"].encode()).hexdigest() != _INDEX_SHA):
        raise PersistentPackPending("explicit_recovery_reviewed_unique_bucket_required")
    for table, name, function in (
            (_PRIVATE, "a002_persistent_explicit_insert", "enforce_persistent_explicit_insert"),
            ("tutor_item_supply_shared_persistent_pack_journal", "a002_persistent_explicit_stage", "enforce_persistent_explicit_stage"),
            ("tutor_item_supply_shared_review_investigation_preparations", "a002_persistent_explicit_preparation", "enforce_persistent_explicit_preparation")):
        row = owner.conn.execute("SELECT pg_get_triggerdef(oid) AS definition FROM pg_trigger "
            "WHERE tgrelid=to_regclass(%s) AND tgname=%s AND tgenabled='O' AND NOT tgisinternal",
            ("public." + table, name)).fetchone()
        expected = (f"CREATE TRIGGER {name} BEFORE INSERT ON public.{table} FOR EACH ROW "
            f"EXECUTE FUNCTION item_supply_internal.{function}()")
        if row is None or row["definition"] != expected:
            raise PersistentPackPending("explicit_recovery_enabled_receiver_required")


def _permission(owner: PersistentPackTaskOwner, task: PersistentPackTaskRef) -> _AllocationPermission | None:
    p = owner._explicit_recovery
    if type(p) is not _AllocationPermission:
        return None
    if p.owner is not owner or p.task != task or _top(owner, p.transaction) != p.txid:
        raise PersistentPackPending("explicit_recovery_original_transaction_required")
    return p


def allow_existing_stage(owner: PersistentPackTaskOwner, task: PersistentPackTaskRef, version: Any, rows: list[Any]) -> bool:
    p = _permission(owner, task)
    if p is None:
        return False
    if (version.revision_id != REVISION or version.root_id != ROOT or version.public_slot_id != SLOT or len(rows) != 1
            or rows[0]["operation_key"] != LOGICAL_STAGE or rows[0]["phase_id"] != FAILED
            or rows[0]["record_kind"] != "stage_started"):
        raise PersistentPackPending("explicit_recovery_only_registered_old_investigation")
    owner.conn.execute("SELECT item_supply_internal.assert_persistent_explicit_recovery(%s,NULL)", (Jsonb(p.payload),)).fetchone()
    return True


def consume_explicit_exception(owner: PersistentPackTaskOwner, task: PersistentPackTaskRef, *, operation: str,
        root: UUID, kind: str, version: Any, previous: list[Any], old: Any) -> bool:
    p = _permission(owner, task)
    if p is None:
        return False
    if (task.pack_task_id != TASK or task.public_task_id != PUBLIC or root != ROOT or kind != "candidate"
            or operation != LOGICAL_OPERATION or version is None or version.revision_id != REVISION
            or version.public_slot_id != SLOT or len(previous) != 2
            or {r["phase_id"] for r in previous} != set(UNKNOWN_PHASES)
            or any(r["result"] is None or r["result"]["status"] != "outcome_unknown" for r in previous)
            or old["phase_id"] in p.covered):
        raise PersistentPackPending("explicit_recovery_only_two_frozen_unknowns")
    owner.conn.execute("SELECT item_supply_internal.assert_persistent_explicit_recovery(%s,NULL)", (Jsonb(p.payload),)).fetchone()
    p.covered.add(old["phase_id"])
    return True


def stage_operation(owner: PersistentPackTaskOwner, phase: IssuedPackPhase, stage: str) -> str:
    if phase.record.revision_id is None:
        raise PersistentPackPending("persistent_candidate_revision_required")
    logical = "persistent.stage." + phase.record.revision_id.hex + "." + stage
    if stage != "investigation":
        return logical
    issued = owner._explicit_attempts.get(phase.record.phase_id)
    if type(issued) is not _BoundAttempt:
        if phase.record.operation_key == LOGICAL_OPERATION + ".frame.3":
            raise PersistentPackPending("explicit_attempt_original_issuer_required")
        return logical
    if issued.owner is not owner or issued.phase is not phase or phase.owner is not owner or logical != LOGICAL_STAGE:
        raise PersistentPackPending("explicit_attempt_frame_changed")
    row = owner.conn.execute("SELECT a.payload_json FROM " + _PRIVATE + " a JOIN " + _PRIVATE + " b ON "
        "b.payload_json->>'approval_id'=a.id::text AND (b.pack_task_id,b.user_id,b.epoch,b.scope_id)="
        "(a.pack_task_id,a.user_id,a.epoch,a.scope_id) WHERE a.id=%s AND b.id=%s AND a.pack_task_id=%s "
        "AND a.user_id=%s AND a.epoch=%s AND a.record_kind='explicit_recovery_approval' "
        "AND b.record_kind='explicit_recovery_binding' AND b.payload_json->>'successor_phase_id'=%s",
        (issued.approval_id, issued.binding_id, TASK, owner.user_id, owner.epoch, str(phase.record.phase_id))).fetchone()
    if row is None:
        raise PersistentPackPending("explicit_attempt_actual_binding_required")
    owner.conn.execute("SELECT item_supply_internal.assert_persistent_explicit_recovery(%s,%s)",
        (Jsonb(row["payload_json"]), phase.record.phase_id)).fetchone()
    return ATTEMPT_KEY


def prepare_explicit_recovery(owner: PersistentPackTaskOwner, task: PersistentPackTaskRef, *, transaction: Transaction) -> IssuedPackPhase:
    from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
    if (type(owner) is not PersistentPackTaskOwner or type(task) is not PersistentPackTaskRef
            or task.pack_task_id != TASK or task.public_task_id != PUBLIC or owner._explicit_recovery is not None):
        raise PersistentPackPending("explicit_recovery_exact_original_case_required")
    txid = _top(owner, transaction)
    prior_rollback = transaction.force_rollback
    transaction.force_rollback = True
    try:
        _contracts(owner)
        owner._task(task)
        owner.conn.execute("SELECT pg_advisory_xact_lock(hashtext('persistent-public-phase'),hashtext(%s))", (str(PUBLIC),))
        if owner.conn.execute("SELECT 1 FROM " + _PRIVATE + " WHERE pack_task_id=%s AND user_id=%s "
                "AND epoch=%s AND record_kind='explicit_recovery_binding'", (TASK, task.user_id, task.epoch)).fetchone():
            raise PersistentPackPending("explicit_recovery_already_bound")
        if owner.get_status(task).status != "preparing":
            raise PersistentPackPending("explicit_recovery_current_original_task_required")
        approval = owner.conn.execute("SELECT id,payload_json FROM " + _PRIVATE + " WHERE pack_task_id=%s "
            "AND user_id=%s AND epoch=%s AND scope_id=%s AND intent_hash=%s AND record_kind='explicit_recovery_approval' "
            "AND operation_key=%s FOR UPDATE", (TASK, task.user_id, task.epoch, task.scope_id, task.intent_hash, _KEY + ".approval")).fetchone()
        if approval is None:
            row = owner.conn.execute("SELECT clock_timestamp() AS stamp").fetchone()
            if row is None:
                raise PersistentPackPending("explicit_recovery_clock_required")
            payload = dict(schema_version="persistent_explicit_recovery_approval_v1", case_key="explicit_stage_started_release_20261012",
                authorization_sha256=_AUTHORIZATION_SHA, basis="new_attempt_despite_retained_uncertainty",
                task_ref=task.model_dump(mode="json"), failed_phase_id=str(FAILED),
                retained_unknown_phase_ids=[str(v) for v in UNKNOWN_PHASES], logical_stage_key=LOGICAL_STAGE,
                attempt_key=ATTEMPT_KEY, checked_at=row["stamp"].isoformat(), valid_until=(row["stamp"] + timedelta(seconds=900)).isoformat())
            approval_id = owner._private_event(task, "explicit_recovery_approval", payload, key=_KEY + ".approval")
        else:
            approval_id, payload = approval["id"], approval["payload_json"]
        owner.conn.execute("SELECT item_supply_internal.assert_persistent_explicit_recovery(%s,NULL)", (Jsonb(payload),)).fetchone()
        permission = _AllocationPermission(owner, task, transaction, txid, approval_id, payload)
        owner._explicit_recovery = permission
        phase = owner.prepare_next_phase(task)
        if (isinstance(phase, BlockedPackPhase) or type(phase) is not IssuedPackPhase or phase.owner is not owner
                or permission.covered != set(UNKNOWN_PHASES) or phase.record.operation_key != LOGICAL_OPERATION + ".frame.3"
                or phase.record.root_id != ROOT or phase.record.revision_id != REVISION or phase.record.public_slot_id != SLOT
                or phase.prepared.get("resume_stage") != "committed_review_repair" or _top(owner, transaction) != txid):
            raise PersistentPackPending("explicit_recovery_original_frame3_required")
        binding_id = owner._private_event(task, "explicit_recovery_binding", dict(schema_version="persistent_explicit_recovery_binding_v1",
            approval_id=str(approval_id), failed_phase_id=str(FAILED), successor_phase_id=str(phase.record.phase_id),
            successor_frame_hash=phase.record.frame_hash, logical_stage_key=LOGICAL_STAGE, attempt_key=ATTEMPT_KEY, txid=txid), key=_KEY + ".binding")
        owner.require_phase(phase, kind="candidate")
        owner._explicit_attempts[phase.record.phase_id] = _BoundAttempt(owner, phase, binding_id, approval_id)
        transaction.force_rollback = prior_rollback
        return phase
    finally:
        owner._explicit_recovery = None
