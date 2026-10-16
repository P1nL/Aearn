"""One registered original-class prestart proof; never HTTP=0 or a paid runner.

PRIVATE evidence is resolved by the original owner. No caller dossier, restored
capability, old lease change or generic UNKNOWN retry. Caller owns the TOP TX.
"""
from __future__ import annotations

from dataclasses import dataclass
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

if TYPE_CHECKING:
    from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner

TASK = UUID("6739d3c5-6619-44ce-970f-0ab1e49f3acc")
PUBLIC_TASK = UUID("9378a05f-b33e-5fc9-9bd7-6f073c2e6c8c")
FAILED_PHASE = UUID("8c5b0671-54ec-4f64-9412-17cd8c286d58")
ROOT = UUID("7d4b85ba-a0ec-4348-ac11-3401c6bded47")
REVISION = UUID("7ac04190-a21c-41f9-b121-353680e38fb9")
SLOT = UUID("e14de564-394a-5685-8e0a-07f2dd819a6c")
LOGICAL_OPERATION = "persistent.candidate." + REVISION.hex + ".repair"
_KEY = "p7.prestart." + TASK.hex + "." + FAILED_PHASE.hex
_PRIVATE = "tutor_item_supply_private_persistent_pack_journal"
_CODE_PINS = {
    "persistent_pack_candidate.py": "f87681ccaa20cd24cd95cfa5daf774a645c7501c00946f3e7de92d88c4cb8cfd",
    "native_review_investigation.py": "cd3c4ca774efad8dd4450f924fcc6a09ec475389b742afc03e1e4faeb08fc83d",
    "shared_review.py": "8f3dc93a12d3c89b4b1d565e75fe54bf1bb7a37fbc6dc96b858e8af6ed0606f8",
}
_RECEIVER_PINS = {
    "item_supply_internal.assert_persistent_prestart_recovery(jsonb,uuid)": "8aa33e6c5344e0c5212f8817aae1706573d4d86a67e0041b158e504b27554b70",
    "item_supply_internal.enforce_persistent_prestart_insert()": "11130ef827795132720e1415b86d2871c3c24afb2605c74ca107871431702ab6",
}


@dataclass
class _PrestartPermission:
    owner: PersistentPackTaskOwner
    task: PersistentPackTaskRef
    transaction: Transaction
    txid: str
    proof_id: UUID
    payload: dict[str, Any]
    used: bool = False


def _top(owner: PersistentPackTaskOwner, transaction: Transaction) -> str:
    if (type(transaction) is not Transaction or getattr(transaction, "_conn", None) is not owner.conn
            or transaction.status != transaction.Status.ACTIVE
            or not getattr(transaction, "_outer_transaction", False)
            or getattr(transaction, "_stack_index", -1) != 0
            or getattr(owner.conn, "_num_transactions", 0) != 1
            or owner.conn.info.transaction_status != TransactionStatus.INTRANS):
        raise PersistentPackPending("prestart_original_active_top_transaction_required")
    row = owner.conn.execute("SELECT txid_current()::text AS txid").fetchone()
    if row is None:
        raise PersistentPackPending("prestart_original_transaction_unavailable")
    return str(row["txid"])


def _contracts(owner: PersistentPackTaskOwner) -> None:
    for name, digest in _CODE_PINS.items():
        if hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() != digest:
            raise PersistentPackPending("prestart_registered_original_code_contract_changed")
    for signature, digest in _RECEIVER_PINS.items():
        row = owner.conn.execute("SELECT p.prosrc,p.prosecdef,p.prokind,p.proconfig,"
            "p.proowner='aearn_b1d_runtime_20261001'::regrole AS owner_ok,"
            "p.proacl=ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[] AS acl_ok "
            "FROM pg_proc p WHERE p.oid=to_regprocedure(%s)", (signature,)).fetchone()
        if (row is None or hashlib.sha256(row["prosrc"].encode()).hexdigest() != digest
                or row["prosecdef"] is not True or row["prokind"] != "f"
                or row["owner_ok"] is not True or row["acl_ok"] is not True
                or row["proconfig"] != ["search_path=pg_catalog, public, item_supply_internal, pg_temp"]):
            raise PersistentPackPending("prestart_exact_535_receiver_required")
    row = owner.conn.execute("SELECT pg_get_triggerdef(oid) AS definition FROM pg_trigger WHERE tgrelid="
        "'public.tutor_item_supply_private_persistent_pack_journal'::regclass "
        "AND tgname='a001_persistent_prestart_insert' AND tgenabled='O' AND NOT tgisinternal "
        "AND tgfoid=to_regprocedure('item_supply_internal.enforce_persistent_prestart_insert()')").fetchone()
    expected = ("CREATE TRIGGER a001_persistent_prestart_insert BEFORE INSERT ON "
        "public.tutor_item_supply_private_persistent_pack_journal FOR EACH ROW "
        "WHEN ((new.record_kind = ANY (ARRAY['prestart_proof'::text, 'prestart_binding'::text]))) "
        "EXECUTE FUNCTION item_supply_internal.enforce_persistent_prestart_insert()")
    if row is None or row["definition"] != expected:
        raise PersistentPackPending("prestart_enabled_535_receiver_required")


def consume_registered_exception(owner: PersistentPackTaskOwner, task: PersistentPackTaskRef, *,
        operation: str, root: UUID, kind: str, version: Any, previous: list[Any], old: Any) -> bool:
    permission = owner._prestart_recovery
    if type(permission) is not _PrestartPermission:
        return False
    if (permission.owner is not owner or permission.task != task or permission.used
            or _top(owner, permission.transaction) != permission.txid
            or task.pack_task_id != TASK or task.public_task_id != PUBLIC_TASK
            or operation != LOGICAL_OPERATION or root != ROOT or kind != "candidate"
            or version is None or version.revision_id != REVISION or version.public_slot_id != SLOT
            or len(previous) != 1 or old["phase_id"] != FAILED_PHASE
            or old["result"]["status"] != "outcome_unknown"):
        raise PersistentPackPending("prestart_exact_same_operation_once_required")
    owner.conn.execute("SELECT item_supply_internal.assert_persistent_prestart_recovery(%s,NULL)",
        (Jsonb(permission.payload),)).fetchone()
    permission.used = True
    return True


def prepare_registered_recovery(owner: PersistentPackTaskOwner, task: PersistentPackTaskRef, *,
        transaction: Transaction) -> IssuedPackPhase:
    from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
    if (type(owner) is not PersistentPackTaskOwner or type(task) is not PersistentPackTaskRef
            or task.pack_task_id != TASK or task.public_task_id != PUBLIC_TASK
            or owner._prestart_recovery is not None):
        raise PersistentPackPending("prestart_exact_original_owner_and_case_required")
    txid = _top(owner, transaction)
    # If any preparation check fails, even a caller swallowing that exception
    # cannot commit a half-prepared frame. Successful rollback rehearsals stay so.
    prior_rollback = transaction.force_rollback
    transaction.force_rollback = True
    try:
        _contracts(owner)
        record = owner._task(task)
        if not any(s.public_slot_id == SLOT for s in record.slots):
            raise PersistentPackPending("prestart_original_fixed_slot_required")
        owner.conn.execute("SELECT pg_advisory_xact_lock(hashtext('persistent-public-phase'),hashtext(%s))",
            (str(PUBLIC_TASK),))
        status = owner.get_status(task)  # Recheck original mapping and all retained current contents.
        if status.status != "preparing":
            raise PersistentPackPending("prestart_original_current_repair_required")
        if owner.conn.execute("SELECT 1 FROM " + _PRIVATE + " WHERE pack_task_id=%s AND user_id=%s "
                "AND epoch=%s AND record_kind='prestart_binding'", (TASK, task.user_id, task.epoch)).fetchone():
            raise PersistentPackPending("prestart_registered_recovery_already_bound")
        proof = owner.conn.execute("SELECT id,payload_json FROM " + _PRIVATE + " WHERE pack_task_id=%s "
            "AND user_id=%s AND epoch=%s AND scope_id=%s AND intent_hash=%s "
            "AND record_kind='prestart_proof' AND operation_key=%s FOR UPDATE",
            (TASK, task.user_id, task.epoch, task.scope_id, task.intent_hash, _KEY + ".proof")).fetchone()
        if proof is None:
            clock = owner.conn.execute("SELECT clock_timestamp() AS stamp").fetchone()
            if clock is None:
                raise PersistentPackPending("prestart_server_clock_required")
            payload = dict(schema_version="persistent_prestart_proof_v1",
                case_key="persistent_normal_prepare_json_precedence_v1", task_ref=task.model_dump(mode="json"),
                failed_phase_id=str(FAILED_PHASE),
                failed_frame_hash="d1f8a528b05847766cf70e28129e2474b846487792e798b8d0cf5284309451ee",
                failed_payload_hash="7fa9a52ffaaa82ef7109e773a0dcb01fdcf2cddf4e1e259cb8409f55feb55129",
                old_helper_hash="1e4139459d5138c5af7f205a226b0747e27f9dcaaa846acce3a8a41dc66e9401",
                repaired_helper_hash="ff5c3fbe5a46b010f34870d36cfe387e62f212748a1ae7c3694f5004eea0b87e",
                archived_review_hash="db6e0ab123d07cb166c52a138395f690e075c49a1dd609c0a1037e7b8d8a3907",
                code_contract=dict(_CODE_PINS), checked_at=clock["stamp"].isoformat(),
                valid_until=(clock["stamp"] + timedelta(seconds=900)).isoformat())
            proof_id = owner._private_event(task, "prestart_proof", payload, key=_KEY + ".proof")
        else:
            proof_id, payload = proof["id"], proof["payload_json"]
        owner.conn.execute("SELECT item_supply_internal.assert_persistent_prestart_recovery(%s,NULL)",
            (Jsonb(payload),)).fetchone()
        permission = _PrestartPermission(owner, task, transaction, txid, proof_id, payload)
        owner._prestart_recovery = permission
        phase = owner.prepare_next_phase(task)
        if (isinstance(phase, BlockedPackPhase) or not permission.used
                or type(phase) is not IssuedPackPhase or phase.owner is not owner
                or phase.record.operation_key != LOGICAL_OPERATION + ".frame.2"
                or phase.record.root_id != ROOT or phase.record.revision_id != REVISION
                or phase.record.public_slot_id != SLOT
                or phase.prepared.get("resume_stage") != "committed_review_repair"
                or _top(owner, transaction) != txid):
            raise PersistentPackPending("prestart_exact_original_successor_preparation_required")
        owner._private_event(task, "prestart_binding", dict(schema_version="persistent_prestart_binding_v1",
            proof_id=str(proof_id), failed_phase_id=str(FAILED_PHASE), successor_phase_id=str(phase.record.phase_id),
            successor_frame_hash=phase.record.frame_hash, txid=txid), key=_KEY + ".binding")
        owner.require_phase(phase, kind="candidate")
        transaction.force_rollback = prior_rollback
        return phase
    finally:
        owner._prestart_recovery = None
