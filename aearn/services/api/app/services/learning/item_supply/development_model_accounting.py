"""Default-off isolated development ledger scope, NOT model/publication authority.

Original owners still fence source, lease, once, prepared/result identity and
per-operation resources. Nominal positive caps only satisfy legacy SQL checks.
Caller owns transactions; no provider calls or JSON capability hydration here.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.pq import TransactionStatus

from app.core.config import DEEPSEEK_V4_FLASH_MODEL
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.policies import RESOURCE_KINDS, SupplyRuntimeError
from app.services.learning.item_supply.repository import ItemSupplyRuntimeRepository, aware_time, server_clock
from app.services.learning.item_supply.storage_contracts import checked_model

AUTHORIZATION = "development-unlimited-model-calls-20261010"
DATABASE = "aearn_b1d_sandbox_20261001"
PROVIDER = "deepseek"
MODE = "accounting_only"


def _available(conn: Connection[dict[str, Any]]) -> bool:
    row = conn.execute("SELECT current_database() AS database, "
        "to_regclass('public.tutor_item_supply_development_model_accounting_batches') AS batches, "
        "to_regclass('public.tutor_item_supply_development_model_accounting_jobs') AS jobs").fetchone()
    if row is None or row["database"] != DATABASE:
        return False
    if row["batches"] is None and row["jobs"] is None:
        return False
    if row["batches"] is None or row["jobs"] is None:
        raise SupplyRuntimeError("DEVELOPMENT_ACCOUNTING_SCHEMA_INCOMPLETE")
    return True


def _public_batch(batch: dict[str, Any]) -> dict[str, Any]:
    return dict(root_id=UUID(str(batch["root_id"])),window_id=UUID(str(batch["window_id"])),
        global_limit_ids=[UUID(str(value)) for value in batch["global_limit_ids"]],
        batch_id=UUID(str(batch["id"])),provider_key=batch["provider_key"],model=batch["model"],
        valid_until=batch["valid_until"],mode=MODE,cumulative_caps_enforced=False)


def _context(conn: Connection[dict[str, Any]], lease: JobLeaseV1, now: datetime) -> tuple[dict[str, Any], dict[str, Any]]:
    lease = checked_model(lease,JobLeaseV1)
    if lease.visibility != "public" or lease.owner_id is not None or lease.owner_epoch is not None:
        raise SupplyRuntimeError("DEVELOPMENT_ACCOUNTING_PUBLIC_LEASE_REQUIRED")
    control = ItemSupplyRuntimeRepository(conn)._control(lease,now=now)
    row = conn.execute("SELECT j.root_id,j.parent_job_id,j.created_at AS job_created_at,j.xmin::text AS job_xmin, "
        "o.pool_class,o.provider_key,r.canonical_key AS root_key,o.canonical_key AS obligation_key, "
        "p.profile_hash,p.profile_key_hash,p.profile_json->'profile_key' AS profile_key "
        "FROM tutor_item_supply_shared_jobs j JOIN tutor_item_supply_shared_budget_roots r ON r.id=j.root_id "
        "JOIN tutor_item_supply_shared_obligations o ON o.root_id=r.id "
        "JOIN tutor_item_supply_parameter_profiles p ON p.id=%s WHERE j.id=%s",
        (control["profile_id"],lease.job_id)).fetchone()
    if (row is None or row["root_key"] != row["obligation_key"]
            or row["provider_key"] != PROVIDER or row["profile_key"]["provider"] != PROVIDER
            or row["profile_key"]["model_version"] != DEEPSEEK_V4_FLASH_MODEL
            or row["profile_hash"] != lease.profile.profile_hash
            or row["profile_key_hash"] != lease.profile.profile_key_hash):
        raise SupplyRuntimeError("DEVELOPMENT_ACCOUNTING_ORIGINAL_ROOT_PROFILE_MISMATCH")
    return control,row


def _batch(conn: Connection[dict[str, Any]], batch_id: UUID, root_id: UUID, *, now: datetime) -> dict[str, Any]:
    row = conn.execute("SELECT b.*,b.xmin::text AS batch_xmin,o.pool_class,o.provider_key AS root_provider, "
        "r.canonical_key AS root_key,o.canonical_key AS obligation_key,w.root_id AS window_root, "
        "w.pool_key,w.provider_key AS window_provider,w.window_start,w.window_end,w.request_cap,w.token_cap,w.resource_cap "
        "FROM tutor_item_supply_development_model_accounting_batches b "
        "JOIN tutor_item_supply_shared_budget_roots r ON r.id=b.root_id "
        "JOIN tutor_item_supply_shared_obligations o ON o.root_id=r.id "
        "JOIN tutor_item_supply_shared_budget_windows w ON w.id=b.window_id WHERE b.id=%s",(batch_id,)).fetchone()
    now = server_clock(conn,now)
    if (row is None or row["root_id"] != root_id or row["window_root"] != root_id
            or row["root_key"] != row["obligation_key"] or row["authorization_key"] != AUTHORIZATION
            or row["mode"] != MODE or row["cumulative_caps_enforced"] is not False
            or row["provider_key"] != PROVIDER or row["root_provider"] != PROVIDER or row["window_provider"] != PROVIDER
            or row["model"] != DEEPSEEK_V4_FLASH_MODEL or row["pool_key"] != row["pool_class"]
            or row["window_start"] != row["started_at"] or row["window_end"] != row["valid_until"]
            or not row["started_at"] <= now < row["valid_until"]
            or row["valid_until"] > row["started_at"]+timedelta(seconds=7200)
            or (row["request_cap"],row["token_cap"],row["resource_cap"]) != (1,1,1)
            or len(row["global_limit_ids"]) != 32 or len(set(row["global_limit_ids"])) != 32):
        raise SupplyRuntimeError("DEVELOPMENT_ACCOUNTING_BATCH_BINDING_INVALID")
    limits = conn.execute("SELECT * FROM tutor_item_supply_runtime_global_limits WHERE id=ANY(%s::uuid[])",
        (row["global_limit_ids"],)).fetchall()
    dimensions = (("system","item-supply"),("window","item-supply"),("pool",row["pool_class"]),("provider",PROVIDER))
    expected = {(kind,key,resource) for kind,key in dimensions for resource in RESOURCE_KINDS}
    if (len(limits) != 32 or {(r["dimension_kind"],r["dimension_key"],r["resource_kind"]) for r in limits} != expected
            or any(r["cap_amount"] != 1 or r["window_start"] != row["started_at"] or r["window_end"] != row["valid_until"] for r in limits)):
        raise SupplyRuntimeError("DEVELOPMENT_ACCOUNTING_GLOBAL_CLOSURE_INVALID")
    return row


def accounting_batch_for_lease(conn: Connection[dict[str, Any]], lease: JobLeaseV1, *, now: datetime) -> dict[str, Any] | None:
    if lease.visibility == "private":
        from app.services.learning.item_supply.private_development_model_accounting import accounting_batch_for_lease as private_batch_for_lease

        return private_batch_for_lease(conn, lease, now=now)
    if lease.visibility != "public" or lease.owner_id is not None or lease.owner_epoch is not None:
        return None
    if not _available(conn):
        return None
    mapping = conn.execute("SELECT * FROM tutor_item_supply_development_model_accounting_jobs WHERE job_id=%s",(lease.job_id,)).fetchone()
    if mapping is None:
        return None
    control,context = _context(conn,lease,now)
    batch = _batch(conn,UUID(str(mapping["batch_id"])),context["root_id"],now=now)
    if (mapping["parent_job_id"] != context["parent_job_id"]
            or mapping["lease_generation"] != lease.generation or mapping["lease_owner"] != lease.lease_owner
            or mapping["lease_state_version"] > lease.state_version or mapping["profile_hash"] != lease.profile.profile_hash
            or mapping["parent_deadline"] != lease.parent_deadline or lease.parent_deadline > batch["valid_until"]
            or lease.profile.parent_deadline_at != control["parent_deadline"]):
        raise SupplyRuntimeError("DEVELOPMENT_ACCOUNTING_JOB_BINDING_INVALID")
    return _public_batch(batch)


def _bind(conn: Connection[dict[str, Any]], *, lease: JobLeaseV1, batch_id: UUID,
          parent_job_id: UUID | None, now: datetime) -> None:
    control,context = _context(conn,lease,now)
    batch = _batch(conn,batch_id,context["root_id"],now=now)
    if (control["attempt_count"] != 1 or lease.generation != 1 or control["breaker_open"]
            or context["parent_job_id"] != parent_job_id or lease.parent_deadline > batch["valid_until"]
            or (context["job_created_at"] < batch["started_at"] and context["job_xmin"] != batch["batch_xmin"])):
        raise SupplyRuntimeError("DEVELOPMENT_ACCOUNTING_FRESH_FIRST_CLAIM_REQUIRED")
    prior = conn.execute("SELECT EXISTS(SELECT 1 FROM tutor_item_supply_shared_reservations WHERE job_id=%s) "
        "OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_controlled_counterexample_preparations WHERE job_id=%s) "
        "OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_generation_artifacts WHERE job_id=%s) "
        "OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints WHERE job_id=%s) AS used",
        (lease.job_id,lease.job_id,lease.job_id,lease.job_id)).fetchone()
    if prior is None or prior["used"]:
        raise SupplyRuntimeError("DEVELOPMENT_ACCOUNTING_PREVIOUS_JOB_WORK_DENIED")
    if parent_job_id is not None:
        parent = conn.execute("SELECT m.batch_id,c.parent_deadline FROM tutor_item_supply_development_model_accounting_jobs m "
            "JOIN tutor_item_supply_shared_job_controls c ON c.job_id=m.job_id WHERE m.job_id=%s",(parent_job_id,)).fetchone()
        if parent is None or parent["batch_id"] != batch_id or lease.parent_deadline > parent["parent_deadline"]:
            raise SupplyRuntimeError("DEVELOPMENT_ACCOUNTING_PARENT_BATCH_MISMATCH")
    conn.execute("INSERT INTO tutor_item_supply_development_model_accounting_jobs "
        "(job_id,batch_id,parent_job_id,lease_owner,lease_generation,lease_state_version,profile_hash,parent_deadline) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
        (lease.job_id,batch_id,parent_job_id,lease.lease_owner,lease.generation,lease.state_version,lease.profile.profile_hash,lease.parent_deadline))


class DevelopmentModelAccountingOwner:
    def __init__(self, conn: Connection[dict[str, Any]], *, enabled: bool = False) -> None:
        self.conn,self.enabled = conn,enabled

    def _guard(self) -> None:
        if self.enabled is not True:
            raise SupplyRuntimeError("DEVELOPMENT_MODEL_ACCOUNTING_DISABLED")
        if not _available(self.conn):
            raise SupplyRuntimeError("DEVELOPMENT_MODEL_ACCOUNTING_517_REQUIRED")

    def prepare_batch(self, *, root_id: UUID, provider_key: str, model: str,
                      now: datetime, valid_until: datetime) -> dict[str, Any]:
        self._guard()
        aware_time(valid_until)
        now = server_clock(self.conn,now)
        if (provider_key != PROVIDER or model != DEEPSEEK_V4_FLASH_MODEL
                or not now < valid_until <= now+timedelta(seconds=7200)):
            raise SupplyRuntimeError("DEVELOPMENT_ACCOUNTING_MODEL_OR_OPERATION_DEADLINE_INVALID")
        root = self.conn.execute("SELECT r.id,r.canonical_key,o.canonical_key AS obligation_key,o.pool_class,o.provider_key "
            "FROM tutor_item_supply_shared_budget_roots r JOIN tutor_item_supply_shared_obligations o ON o.root_id=r.id "
            "WHERE r.id=%s",(root_id,)).fetchone()
        if root is None or root["canonical_key"] != root["obligation_key"] or root["provider_key"] != provider_key:
            raise SupplyRuntimeError("DEVELOPMENT_ACCOUNTING_EXISTING_CANONICAL_ROOT_REQUIRED")
        # Do not leave untagged nominal-cap rows behind under autocommit. The
        # window, all 32 limits and batch tag must commit or roll back together.
        if self.conn.info.transaction_status != TransactionStatus.INTRANS:
            raise SupplyRuntimeError("DEVELOPMENT_ACCOUNTING_ATOMIC_TRANSACTION_REQUIRED")
        batch_id,window_id = uuid4(),uuid4()
        self.conn.execute("INSERT INTO tutor_item_supply_shared_budget_windows "
            "(id,root_id,pool_key,provider_key,window_start,window_end,request_cap,token_cap,resource_cap) "
            "VALUES(%s,%s,%s,%s,%s,%s,1,1,1)",(window_id,root_id,root["pool_class"],provider_key,now,valid_until))
        from app.services.learning.item_supply.budget import ItemSupplyBudgetRepository
        budget = ItemSupplyBudgetRepository(self.conn)
        limits = [budget.register_global_limit(dimension_kind=kind,dimension_key=key,resource_kind=resource,
            window_start=now,window_end=valid_until,cap_amount=1)
            for kind,key in (("system","item-supply"),("window","item-supply"),("pool",root["pool_class"]),("provider",provider_key))
            for resource in RESOURCE_KINDS]
        self.conn.execute("INSERT INTO tutor_item_supply_development_model_accounting_batches "
            "(id,root_id,window_id,provider_key,model,authorization_key,global_limit_ids,started_at,valid_until) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (batch_id,root_id,window_id,provider_key,model,AUTHORIZATION,limits,now,valid_until))
        return _public_batch(dict(id=batch_id,root_id=root_id,window_id=window_id,provider_key=provider_key,
            model=model,global_limit_ids=limits,valid_until=valid_until))

    def bind_job(self, *, lease: JobLeaseV1, batch_id: UUID,
                 parent_job_id: UUID | None = None, now: datetime) -> None:
        self._guard()
        _bind(self.conn,lease=lease,batch_id=batch_id,parent_job_id=parent_job_id,now=now)


def inherit_development_model_accounting(conn: Connection[dict[str, Any]], *,
                                        parent_lease: JobLeaseV1, child_lease: JobLeaseV1, now: datetime) -> None:
    batch = accounting_batch_for_lease(conn,parent_lease,now=now)
    if batch is None:
        return
    # A real enqueue/claim parent-child pair, not serialized capabilities. Parent
    # may have reservations; only the actual fresh child must be unspent.
    ItemSupplyRuntimeRepository(conn)._control(parent_lease,now=now)
    if child_lease.parent_deadline > parent_lease.parent_deadline:
        raise SupplyRuntimeError("DEVELOPMENT_ACCOUNTING_CHILD_DEADLINE_EXTENSION_DENIED")
    _bind(conn,lease=child_lease,batch_id=batch["batch_id"],parent_job_id=parent_lease.job_id,now=now)

