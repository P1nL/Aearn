"""Explicit B1 discovery jobs; no beat/worker/route is registered by this module."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from psycopg import Connection

from .access_policy import AccessRequest, AuthorityResolver, AutonomousGates
from .budget import BudgetDenied, _valid_hash, _valid_key, current_authority, fingerprint, require_transaction
from .contracts import LearningMaterialDemand, SourceDiscoveryDemand, revalidate


class PrivateReferenceRemovalAuthority(Protocol):
    """Server-owned self-unlink/reset/delete authorization; never caller identity alone."""

    def authorize(self, actor_id: str) -> bool: ...

@dataclass(frozen=True)
class JobLease:
    job_id: UUID
    owner_id: str
    generation: int
    expires_at: datetime


def require_live_lease(conn: Connection[dict[str, Any]], lease: JobLease, now: datetime) -> None:
    """Must be called inside a transaction before writes; fence on owner and generation."""
    row = conn.execute(
        "SELECT id FROM rag_discovery_jobs WHERE id=%s AND state='leased' "
        "AND lease_owner_id=%s AND lease_generation=%s AND lease_expires_at>%s FOR UPDATE",
        (lease.job_id, lease.owner_id, lease.generation, now),
    ).fetchone()
    if row is None or now.tzinfo is None or lease.expires_at.tzinfo is None or now >= lease.expires_at:
        raise BudgetDenied("LEASE_STALE")


def projected_query_hash(projection: SourceDiscoveryDemand, snapshot: Any,
                         demand: LearningMaterialDemand) -> str:
    valid = revalidate(projection, SourceDiscoveryDemand)
    if (valid.demand_hash != demand.demand_hash or valid.scope != demand.scope
            or valid.actor_id != snapshot.actor_id or valid.policy_id != snapshot.policy_id
            or valid.policy_generation != snapshot.policy_generation or valid.budget != snapshot.budget):
        raise BudgetDenied("PROJECTION_SCOPE_STALE")
    # Actor-free so two authorized profiles can reuse the same shared job.
    return fingerprint(valid.query_terms)

class DiscoveryJobRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def enqueue(
        self, *, request: AccessRequest, demand: LearningMaterialDemand,
        gates: AutonomousGates, resolver: AuthorityResolver,
        operation_key: str, request_hash: str, projection: SourceDiscoveryDemand,
        now: datetime,
    ) -> UUID:
        _valid_key(operation_key)
        _valid_hash(request_hash)
        if request.action != "discover":
            raise BudgetDenied("ACTION_DENIED")
        snapshot = current_authority(request=request, demand=demand, gates=gates, resolver=resolver, now=now)
        query_hash = projected_query_hash(projection, snapshot, demand)
        require_transaction(self.conn)
        with self.conn.transaction():
            if current_authority(request=request, demand=demand, gates=gates, resolver=resolver, now=now) != snapshot:
                raise BudgetDenied("AUTHORITY_CHANGED")
            # Unique key serializes first write; a conflicting replay never joins a different scope.
            self.conn.execute(
                "INSERT INTO rag_discovery_jobs(operation_key,request_hash,query_hash,demand_hash,subject_id,subject_version,"
                "purpose,policy_id,policy_generation,root_id,delegation_id,delegation_generation) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (operation_key) DO NOTHING",
                (operation_key, request_hash, query_hash, demand.demand_hash, demand.scope.subject_id,
                 demand.scope.subject_version, demand.purpose, snapshot.policy_id,
                 snapshot.policy_generation, snapshot.budget.root_id,
                 snapshot.budget.delegation_id, snapshot.budget.generation),
            )
            row = self.conn.execute(
                "SELECT * FROM rag_discovery_jobs WHERE operation_key=%s", (operation_key,),
            ).fetchone()
            if row is None or (
                row["request_hash"], row["query_hash"], row["demand_hash"], row["subject_id"], row["subject_version"],
                row["purpose"], row["policy_id"], row["policy_generation"], row["root_id"],
                row["delegation_id"], row["delegation_generation"]
            ) != (
                request_hash, query_hash, demand.demand_hash, demand.scope.subject_id, demand.scope.subject_version,
                demand.purpose, snapshot.policy_id, snapshot.policy_generation, snapshot.budget.root_id,
                snapshot.budget.delegation_id, snapshot.budget.generation
            ):
                raise BudgetDenied("JOB_CONFLICT")
            self.conn.execute(
                "INSERT INTO rag_discovery_job_refs(job_id,actor_id,demand_hash) VALUES (%s,%s,%s) "
                "ON CONFLICT DO NOTHING", (row["id"], snapshot.actor_id, demand.demand_hash),
            )
            return row["id"]

    def claim(
        self, *, job_id: UUID, request: AccessRequest, demand: LearningMaterialDemand,
        gates: AutonomousGates, resolver: AuthorityResolver,
        owner_id: str, now: datetime, lease_seconds: int = 60,
    ) -> JobLease | None:
        if (not re.fullmatch(r"^[A-Za-z0-9._:-]{3,120}$", owner_id)
                or not 1 <= lease_seconds <= 300 or request.action != "discover"):
            raise BudgetDenied("INVALID_CLAIM")
        snapshot = current_authority(request=request, demand=demand, gates=gates, resolver=resolver, now=now)
        require_transaction(self.conn)
        with self.conn.transaction():
            if current_authority(request=request, demand=demand, gates=gates, resolver=resolver, now=now) != snapshot:
                raise BudgetDenied("AUTHORITY_CHANGED")
            row = self.conn.execute(
                "SELECT * FROM rag_discovery_jobs WHERE id=%s FOR UPDATE SKIP LOCKED", (job_id,),
            ).fetchone()
            if row is None:
                return None
            self._scope(row, snapshot, demand)
            if row["state"] not in {"pending", "leased"} or (
                row["state"] == "leased" and row["lease_expires_at"] > now
            ):
                return None
            expires_at = now + timedelta(seconds=lease_seconds)
            generation = row["lease_generation"] + 1
            self.conn.execute(
                "UPDATE rag_discovery_jobs SET state='leased',lease_owner_id=%s,lease_generation=%s,"
                "lease_expires_at=%s,updated_at=%s WHERE id=%s",
                (owner_id, generation, expires_at, now, job_id),
            )
            return JobLease(job_id, owner_id, generation, expires_at)

    def complete(
        self, *, lease: JobLease, request: AccessRequest, demand: LearningMaterialDemand,
        gates: AutonomousGates, resolver: AuthorityResolver, now: datetime, success: bool,
    ) -> None:
        if request.action != "discover":
            raise BudgetDenied("ACTION_DENIED")
        snapshot = current_authority(request=request, demand=demand, gates=gates, resolver=resolver, now=now)
        require_transaction(self.conn)
        with self.conn.transaction():
            require_live_lease(self.conn, lease, now)
            if current_authority(request=request, demand=demand, gates=gates, resolver=resolver, now=now) != snapshot:
                raise BudgetDenied("AUTHORITY_CHANGED")
            row = self.conn.execute("SELECT * FROM rag_discovery_jobs WHERE id=%s", (lease.job_id,)).fetchone()
            if row is None:
                raise BudgetDenied("JOB_NOT_FOUND")
            self._scope(row, snapshot, demand)
            self.conn.execute(
                "UPDATE rag_discovery_jobs SET state=%s,lease_owner_id=NULL,lease_expires_at=NULL,"
                "terminal_at=%s,updated_at=%s WHERE id=%s",
                ("completed" if success else "failed", now, now, lease.job_id),
            )

    def fail_if_owned(self, *, lease: JobLease, now: datetime) -> bool:
        """End ambiguous work without releasing its unknown spend or bypassing fencing."""
        require_transaction(self.conn)
        with self.conn.transaction():
            return self.conn.execute(
                "UPDATE rag_discovery_jobs SET state='failed',lease_owner_id=NULL,"
                "lease_expires_at=NULL,terminal_at=%s,updated_at=%s "
                "WHERE id=%s AND state='leased' AND lease_owner_id=%s AND lease_generation=%s",
                (now, now, lease.job_id, lease.owner_id, lease.generation),
            ).rowcount > 0

    def unlink_ref(self, *, job_id: UUID, actor_id: str,
                   authority: PrivateReferenceRemovalAuthority | None) -> bool:
        """Remove this actor's private mapping only, never the shared job or ledger."""
        self._authorize_removal(actor_id, authority)
        require_transaction(self.conn)
        with self.conn.transaction():
            self._authorize_removal(actor_id, authority)
            return self.conn.execute(
                "DELETE FROM rag_discovery_job_refs WHERE actor_id=%s AND job_id=%s",
                (actor_id, job_id),
            ).rowcount > 0

    def unlink_actor(self, *, actor_id: str,
                     authority: PrivateReferenceRemovalAuthority | None) -> int:
        """Reset/delete hook: purge only owned private refs, preserve shared facts."""
        self._authorize_removal(actor_id, authority)
        require_transaction(self.conn)
        with self.conn.transaction():
            self._authorize_removal(actor_id, authority)
            return self.conn.execute("DELETE FROM rag_discovery_job_refs WHERE actor_id=%s", (actor_id,)).rowcount

    @staticmethod
    def _authorize_removal(actor_id: str, authority: PrivateReferenceRemovalAuthority | None) -> None:
        if not re.fullmatch(r"^[a-z][a-z0-9._:-]{2,159}$", actor_id):
            raise BudgetDenied("INVALID_ACTOR")
        if authority is None:
            raise BudgetDenied("REMOVAL_AUTHORITY_MISSING")
        try:
            authorized = authority.authorize(actor_id)
        except Exception as exc:
            raise BudgetDenied("REMOVAL_AUTHORITY_MISSING") from exc
        if authorized is not True:
            raise BudgetDenied("REMOVAL_DENIED")
    @staticmethod
    def _scope(row: dict[str, Any], snapshot: Any, demand: LearningMaterialDemand) -> None:
        if (row["root_id"], row["demand_hash"], row["subject_id"], row["subject_version"],
                row["purpose"], row["policy_id"], row["policy_generation"],
                row["delegation_id"], row["delegation_generation"]) != (
                snapshot.budget.root_id, demand.demand_hash, demand.scope.subject_id,
                demand.scope.subject_version, demand.purpose, snapshot.policy_id, snapshot.policy_generation,
                snapshot.budget.delegation_id, snapshot.budget.generation
        ):
            raise BudgetDenied("JOB_SCOPE_STALE")
