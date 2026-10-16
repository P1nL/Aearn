"""Explicit PRIVATE development accounting; never source or execution authority.

Caller owns the original transaction. Locator DATA cannot restore a lease, a
source capability or a dispatch. Original allocations and settlements remain.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.pq import TransactionStatus

from app.core.config import DEEPSEEK_V4_FLASH_MODEL
from app.services.learning.item_supply.development_model_accounting import (
    AUTHORIZATION, DATABASE, MODE, PROVIDER,
)
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.policies import RESOURCE_KINDS, SupplyRuntimeError
from app.services.learning.item_supply.repository import (
    ItemSupplyRuntimeRepository, aware_time, lock_private_namespace, server_clock,
)
from app.services.learning.item_supply.storage_contracts import checked_model

BATCH_TABLE = "tutor_item_supply_private_development_model_accounting_batches"
JOB_TABLE = "tutor_item_supply_private_development_model_accounting_jobs"
GLOBAL_MODE_TABLE = "tutor_item_supply_development_private_global_limit_modes"


@dataclass(frozen=True)
class PrivateDevelopmentBatchRef:
    batch_id: UUID
    root_id: UUID
    window_id: UUID
    global_limit_ids: tuple[UUID, ...]
    user_limit_ids: tuple[UUID, ...]
    started_at: datetime
    valid_until: datetime


def private_accounting_available(conn: Connection[dict[str, Any]]) -> bool:
    """Schema inventory only: absent is ordinary, partial installation denies."""
    row = conn.execute(
        "SELECT to_regclass(%s) AS batches,to_regclass(%s) AS jobs,"
        "to_regclass(%s) AS modes",
        ("public." + BATCH_TABLE, "public." + JOB_TABLE, "public." + GLOBAL_MODE_TABLE),
    ).fetchone()
    if row is None:
        raise SupplyRuntimeError("PRIVATE_DEVELOPMENT_ACCOUNTING_SCHEMA_INCOMPLETE")
    present = [row[key] is not None for key in ("batches", "jobs", "modes")]
    if not any(present):
        return False
    if not all(present):
        raise SupplyRuntimeError("PRIVATE_DEVELOPMENT_ACCOUNTING_SCHEMA_INCOMPLETE")
    helpers = conn.execute(
        "SELECT to_regprocedure(%s) AS current,to_regprocedure(%s) AS batch_insert,"
        "to_regprocedure(%s) AS job_insert,to_regprocedure(%s) AS purge,"
        "to_regprocedure(%s) AS mode_insert",
        ("item_supply_internal.private_development_accounting_batch_current(public." + BATCH_TABLE + ")",
         "item_supply_internal.enforce_private_development_accounting_batch_insert()",
         "item_supply_internal.enforce_private_development_accounting_job_insert()",
         "item_supply_internal.purge_private_development_accounting_on_epoch_advance()",
         "item_supply_internal.enforce_private_development_global_mode_insert()"),
    ).fetchone()
    if helpers is None or any(value is None for value in helpers.values()):
        raise SupplyRuntimeError("PRIVATE_DEVELOPMENT_ACCOUNTING_SCHEMA_INCOMPLETE")
    triggers = conn.execute(
        "SELECT count(*) AS n FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
        "JOIN pg_namespace s ON s.oid=c.relnamespace WHERE s.nspname='public' "
        "AND NOT t.tgisinternal AND t.tgenabled='O' AND ("
        "(c.relname=%s AND t.tgname IN ('private_development_global_mode_insert','private_development_global_mode_immutable')) OR "
        "(c.relname=%s AND t.tgname IN ('private_development_accounting_batch_insert','private_development_accounting_immutable','supply_epoch')) OR "
        "(c.relname=%s AND t.tgname IN ('private_development_accounting_job_insert','private_development_accounting_immutable','supply_epoch')) OR "
        "(c.relname='tutor_item_supply_user_epochs' AND t.tgname='a000_private_development_accounting_epoch_purge'))",
        (GLOBAL_MODE_TABLE, BATCH_TABLE, JOB_TABLE),
    ).fetchone()
    if triggers is None or triggers["n"] != 9:
        raise SupplyRuntimeError("PRIVATE_DEVELOPMENT_ACCOUNTING_SCHEMA_INCOMPLETE")
    return True


def ordinary_private_window_filter(conn: Connection[dict[str, Any]]) -> str:
    """Append to an unaliased original PRIVATE window query (including _fund)."""
    if not private_accounting_available(conn):
        return ""
    return (" AND NOT EXISTS(SELECT 1 FROM " + BATCH_TABLE +
            " dev WHERE dev.window_id=tutor_item_supply_private_budget_windows.id)")


def _context(conn: Connection[dict[str, Any]], lease: JobLeaseV1, now: datetime) -> tuple[dict[str, Any], dict[str, Any]]:
    lease = checked_model(lease, JobLeaseV1)
    if lease.visibility != "private" or lease.owner_id is None or lease.owner_epoch is None:
        raise SupplyRuntimeError("PRIVATE_DEVELOPMENT_ACCOUNTING_LEASE_REQUIRED")
    control = ItemSupplyRuntimeRepository(conn)._control(lease, now=now)
    row = conn.execute(
        "SELECT j.root_id,j.user_id,j.epoch,j.scope_id,j.parent_job_id,"
        "j.created_at AS job_created_at,j.xmin::text AS job_xmin,"
        "p.profile_hash,p.profile_key_hash,p.profile_json->'profile_key' AS profile_key "
        "FROM tutor_item_supply_private_jobs j "
        "JOIN tutor_item_supply_parameter_profiles p ON p.id=%s "
        "WHERE j.id=%s AND j.user_id=%s AND j.epoch=%s AND j.scope_id=%s",
        (control["profile_id"], lease.job_id, lease.owner_id, lease.owner_epoch, control["scope_id"]),
    ).fetchone()
    if (row is None or row["profile_hash"] != lease.profile.profile_hash
            or row["profile_key_hash"] != lease.profile.profile_key_hash
            or row["profile_key"]["provider"] != PROVIDER
            or row["profile_key"]["model_version"] != DEEPSEEK_V4_FLASH_MODEL):
        raise SupplyRuntimeError("PRIVATE_DEVELOPMENT_ACCOUNTING_PROFILE_MISMATCH")
    return control, row


def _batch(conn: Connection[dict[str, Any]], batch_id: UUID, context: dict[str, Any]) -> dict[str, Any]:
    row = conn.execute("SELECT b.*,b.xmin::text AS batch_xmin FROM " + BATCH_TABLE + " b WHERE b.id=%s", (batch_id,)).fetchone()
    if row is None or any(row[key] != context[key] for key in ("root_id", "user_id", "epoch", "scope_id")):
        raise SupplyRuntimeError("PRIVATE_DEVELOPMENT_ACCOUNTING_BATCH_BINDING_INVALID")
    # Concrete SQL owner checks the entire immutable closure, namespace and final
    # DB clock, both before selection and again after the budget locks.
    conn.execute("SELECT item_supply_internal.private_development_accounting_batch_current(b) FROM " + BATCH_TABLE + " b WHERE b.id=%s", (batch_id,)).fetchone()
    return row


def accounting_batch_for_lease(conn: Connection[dict[str, Any]], lease: JobLeaseV1, *, now: datetime) -> dict[str, Any] | None:
    if lease.visibility != "private" or not private_accounting_available(conn):
        return None
    mapping = conn.execute("SELECT * FROM " + JOB_TABLE + " WHERE job_id=%s", (lease.job_id,)).fetchone()
    if mapping is None:
        return None
    control, context = _context(conn, lease, now)
    batch = _batch(conn, UUID(str(mapping["batch_id"])), context)
    if (any(mapping[key] != context[key] for key in ("root_id", "user_id", "epoch", "scope_id", "parent_job_id"))
            or mapping["window_id"] != batch["window_id"]
            or mapping["lease_generation"] != lease.generation
            or mapping["lease_owner"] != lease.lease_owner
            or mapping["lease_state_version"] > lease.state_version
            or mapping["profile_hash"] != lease.profile.profile_hash
            or mapping["parent_deadline"] != lease.parent_deadline
            or lease.parent_deadline > batch["valid_until"]
            or lease.profile.parent_deadline_at != control["parent_deadline"]):
        raise SupplyRuntimeError("PRIVATE_DEVELOPMENT_ACCOUNTING_JOB_BINDING_INVALID")
    # Closure reads may themselves consume the remaining lease lifetime.
    ItemSupplyRuntimeRepository(conn)._control(lease, now=server_clock(conn, now))
    return dict(namespace="private", batch_id=UUID(str(batch["id"])),
                root_id=UUID(str(batch["root_id"])), window_id=UUID(str(batch["window_id"])),
                global_limit_ids=[UUID(str(value)) for value in batch["global_limit_ids"]],
                user_limit_ids=[UUID(str(value)) for value in batch["user_limit_ids"]],
                provider_key=batch["provider_key"], model=batch["model"],
                valid_until=batch["valid_until"], mode=MODE, cumulative_caps_enforced=False)


class PrivateDevelopmentModelAccountingOwner:
    def __init__(self, conn: Connection[dict[str, Any]], *, enabled: bool = False) -> None:
        self.conn, self.enabled = conn, enabled

    def _guard(self) -> None:
        if self.enabled is not True:
            raise SupplyRuntimeError("PRIVATE_DEVELOPMENT_MODEL_ACCOUNTING_DISABLED")
        if not private_accounting_available(self.conn):
            raise SupplyRuntimeError("PRIVATE_DEVELOPMENT_MODEL_ACCOUNTING_551_REQUIRED")
        row = self.conn.execute("SELECT current_database() AS database").fetchone()
        if row is None or row["database"] != DATABASE:
            raise SupplyRuntimeError("PRIVATE_DEVELOPMENT_ACCOUNTING_ISOLATED_DATABASE_REQUIRED")
        if self.conn.info.transaction_status != TransactionStatus.INTRANS:
            raise SupplyRuntimeError("PRIVATE_DEVELOPMENT_ACCOUNTING_ATOMIC_TRANSACTION_REQUIRED")

    def prepare_batch(self, *, root_id: UUID, user_id: UUID, epoch: int, scope_id: UUID,
                      provider_key: str, model: str, now: datetime, valid_until: datetime) -> PrivateDevelopmentBatchRef:
        self._guard()
        aware_time(valid_until)
        lock_private_namespace(self.conn, user_id, epoch, scope_id)
        now = server_clock(self.conn, now)
        if (provider_key != PROVIDER or model != DEEPSEEK_V4_FLASH_MODEL
                or not now < valid_until <= now + timedelta(seconds=7200)):
            raise SupplyRuntimeError("PRIVATE_DEVELOPMENT_ACCOUNTING_MODEL_OR_DEADLINE_INVALID")
        root = self.conn.execute(
            "SELECT r.canonical_key,o.canonical_key AS obligation_key,o.pool_class,o.provider_key "
            "FROM tutor_item_supply_private_budget_roots r "
            "JOIN tutor_item_supply_private_obligations o ON (o.root_id,o.user_id,o.epoch,o.scope_id)=(r.id,r.user_id,r.epoch,r.scope_id) "
            "WHERE r.id=%s AND r.user_id=%s AND r.epoch=%s AND r.scope_id=%s",
            (root_id, user_id, epoch, scope_id),
        ).fetchone()
        if (root is None or root["canonical_key"] != root["obligation_key"]
                or root["pool_class"] != "enhancement" or root["provider_key"] != provider_key):
            raise SupplyRuntimeError("PRIVATE_DEVELOPMENT_ACCOUNTING_ROOT_MISMATCH")
        from app.services.learning.item_supply.budget import ItemSupplyBudgetRepository

        batch_id, window_id = uuid4(), uuid4()
        self.conn.execute(
            "INSERT INTO tutor_item_supply_private_budget_windows "
            "(id,user_id,epoch,scope_id,root_id,pool_key,provider_key,window_start,window_end,request_cap,token_cap,resource_cap) "
            "VALUES(%s,%s,%s,%s,%s,'enhancement',%s,%s,%s,1,1,1)",
            (window_id, user_id, epoch, scope_id, root_id, provider_key, now, valid_until),
        )
        budget = ItemSupplyBudgetRepository(self.conn)
        dimensions: tuple[tuple[Literal["system", "provider", "window", "pool"], str], ...] = (
            ("system", "item-supply"), ("window", "item-supply"), ("pool", "enhancement"), ("provider", PROVIDER),
        )
        global_ids = tuple(budget.register_global_limit(dimension_kind=kind, dimension_key=key,
            resource_kind=resource, window_start=now, window_end=valid_until, cap_amount=1)
            for kind, key in dimensions for resource in RESOURCE_KINDS)
        user_ids = tuple(budget.register_user_limit(user_id=user_id, epoch=epoch,
            resource_kind=resource, window_start=now, window_end=valid_until, cap_amount=1)
            for resource in RESOURCE_KINDS)
        for limit_id in global_ids:
            self.conn.execute("INSERT INTO " + GLOBAL_MODE_TABLE + "(global_limit_id) VALUES(%s)", (limit_id,))
        self.conn.execute("INSERT INTO " + BATCH_TABLE +
            "(id,user_id,epoch,scope_id,root_id,window_id,provider_key,model,authorization_key,global_limit_ids,user_limit_ids,started_at,valid_until) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (batch_id, user_id, epoch, scope_id, root_id, window_id, provider_key, model,
             AUTHORIZATION, list(global_ids), list(user_ids), now, valid_until))
        return PrivateDevelopmentBatchRef(batch_id, root_id, window_id, global_ids, user_ids, now, valid_until)

    def bind_job(self, *, lease: JobLeaseV1, batch_id: UUID, parent_job_id: UUID | None = None, now: datetime) -> None:
        self._guard()
        _, context = _context(self.conn, lease, now)
        batch = _batch(self.conn, batch_id, context)
        # SQL validates fresh first claim, unspent job, actual parent closure and
        # final clocks while holding the original control; no hydration or IO.
        self.conn.execute("INSERT INTO " + JOB_TABLE +
            "(user_id,epoch,scope_id,root_id,window_id,job_id,batch_id,parent_job_id,lease_owner,lease_generation,lease_state_version,profile_hash,parent_deadline) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (lease.owner_id, lease.owner_epoch, context["scope_id"], context["root_id"], batch["window_id"],
             lease.job_id, batch_id, parent_job_id, lease.lease_owner, lease.generation,
             lease.state_version, lease.profile.profile_hash, lease.parent_deadline))
