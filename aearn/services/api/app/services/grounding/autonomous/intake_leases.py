"""Persisted candidate-specific B2 lease; completed B1 discovery is never reopened.

Only short database transactions occur here. Network work belongs between claim and
finish, with the caller rechecking this fence at its staging commit.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from psycopg import Connection

from .access_policy import AccessRequest, AuthorityResolver, AutonomousGates
from .budget import (
    BudgetDenied,
    PostgresBudgetPolicyResolver,
    current_authority,
    require_transaction,
)
from .candidate_policy_repository import PostgresCandidatePolicyResolver
from .candidate_repository import _public_url
from .contracts import LearningMaterialDemand, SourceCandidate, revalidate
from .jobs import DiscoveryJobRepository
from .retention import CaptureKind, check_storage

_OWNER = re.compile(r"[A-Za-z0-9._:-]{3,120}\Z")


@dataclass(frozen=True)
class IntakeLease:
    candidate_id: UUID
    job_id: UUID
    owner_id: str
    generation: int
    expires_at: datetime


def require_live_intake_lease(
    conn: Connection[dict[str, Any]],
    lease: IntakeLease,
    now: datetime,
) -> None:
    """Lock and fence the exact candidate; never accept a caller's stale clock."""
    require_transaction(conn)
    if (
        type(lease) is not IntakeLease
        or type(lease.candidate_id) is not UUID
        or type(lease.job_id) is not UUID
        or now.tzinfo is None
    ):
        raise BudgetDenied("INTAKE_LEASE_STALE")
    row = conn.execute(
        "SELECT candidate_id FROM rag_candidate_intake_leases "
        "WHERE candidate_id=%s AND job_id=%s AND state='leased' "
        "AND owner_id=%s AND generation=%s AND expires_at>%s FOR UPDATE",
        (lease.candidate_id, lease.job_id, lease.owner_id, lease.generation, now),
    ).fetchone()
    clock = conn.execute("SELECT clock_timestamp() AS db_now").fetchone()
    if (
        row is None
        or clock is None
        or lease.expires_at.tzinfo is None
        or lease.expires_at <= clock["db_now"]
        or now >= lease.expires_at
    ):
        raise BudgetDenied("INTAKE_LEASE_STALE")


def _db_now(conn: Connection[dict[str, Any]]) -> datetime:
    row = conn.execute("SELECT clock_timestamp() AS db_now").fetchone()
    if row is None:
        raise BudgetDenied("INTAKE_CLOCK_UNAVAILABLE")
    return row["db_now"]


class PostgresIntakeLeaseRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def claim(
        self,
        *,
        candidate_id: UUID,
        candidate: SourceCandidate,
        probe: AccessRequest,
        store: AccessRequest,
        demand: LearningMaterialDemand,
        gates: AutonomousGates,
        authority_resolver: AuthorityResolver,
        capture_kind: CaptureKind,
        planned_bytes: int,
        owner_id: str,
        lease_seconds: int = 60,
    ) -> IntakeLease | None:
        """Claim a completed, settled B1 candidate after current B2 authority checks."""
        if (
            type(candidate_id) is not UUID
            or not isinstance(owner_id, str)
            or _OWNER.fullmatch(owner_id) is None
            or type(lease_seconds) is not int
            or not 1 <= lease_seconds <= 300
        ):
            raise BudgetDenied("INVALID_INTAKE_CLAIM")
        try:
            item = revalidate(candidate, SourceCandidate)
            need = revalidate(demand, LearningMaterialDemand)
            probe_req = revalidate(probe, AccessRequest)
            store_req = revalidate(store, AccessRequest)
            if (
                probe_req.action != "probe"
                or store_req.action != "store"
                or probe_req.model_copy(update={"action": "store"}) != store_req
                or item.demand_hash != need.demand_hash
                or item.scope != need.scope
                or item.capture.kind != "none"
                or _public_url(item.url) != item.url
            ):
                raise BudgetDenied("INTAKE_SCOPE_STALE")
        except (ValueError, TypeError) as exc:
            raise BudgetDenied("INTAKE_SCOPE_STALE") from exc
        require_transaction(self.conn)
        with self.conn.transaction():
            # Lock the candidate first to serialize initial creation, then use the
            # DB clock after any lock wait. No network call occurs under this lock.
            row = self.conn.execute(
                "SELECT c.*,j.state AS job_state,j.root_id,j.policy_id,j.policy_generation,"
                "j.purpose,j.delegation_id,j.delegation_generation,"
                "r.receipt_handle,a.state AS attempt_state,b.state AS reservation_state,"
                "b.job_id AS reserved_job,b.root_id AS reserved_root,b.period_key AS reserved_period "
                "FROM rag_discovery_candidates c "
                "JOIN rag_discovery_jobs j ON j.id=c.job_id "
                "JOIN rag_discovery_receipts r ON r.id=c.discovery_receipt_id AND r.job_id=c.job_id "
                "JOIN rag_budget_attempts a ON a.id=r.attempt_id AND a.job_id=c.job_id "
                "JOIN rag_budget_reservations b ON b.id=a.reservation_id AND b.job_id=c.job_id "
                "WHERE c.id=%s FOR UPDATE OF c SKIP LOCKED",
                (candidate_id,),
            ).fetchone()
            if row is None:
                return None
            db_now = _db_now(self.conn)
            probe_authority = current_authority(
                request=probe_req,
                demand=need,
                gates=gates,
                resolver=authority_resolver,
                now=db_now,
            )
            store_authority = current_authority(
                request=store_req,
                demand=need,
                gates=gates,
                resolver=authority_resolver,
                now=db_now,
            )
            if (
                probe_authority.budget != store_authority.budget
                or probe_authority.policy_id != store_authority.policy_id
                or probe_authority.policy_generation
                != store_authority.policy_generation
            ):
                raise BudgetDenied("INTAKE_SCOPE_STALE")
            DiscoveryJobRepository._scope(row, store_authority, need)
            root = PostgresBudgetPolicyResolver(self.conn).resolve(store_authority)
            if (
                root is None
                or not root.period_start <= db_now < root.period_end
                or row["reserved_period"] != root.period_key
                or row["reserved_root"] != root.root_id
                or row["reserved_job"] != row["job_id"]
                or row["attempt_state"] != "settled"
                or row["reservation_state"] != "settled"
                or row["job_state"] != "completed"
            ):
                raise BudgetDenied("INTAKE_DISCOVERY_STALE")
            if (
                row["canonical_url"],
                row["canonical_url_hash"],
                row["kind"],
                row["demand_hash"],
                row["subject_id"],
                row["subject_version"],
                row["repo_commit"],
                row["repo_path"],
                row["receipt_handle"],
            ) != (
                item.url,
                hashlib.sha256(item.url.encode()).hexdigest(),
                item.kind,
                need.demand_hash,
                need.scope.subject_id,
                need.scope.subject_version,
                item.repo_commit,
                item.repo_path,
                item.discovery_receipt_id,
            ):
                raise BudgetDenied("INTAKE_CANDIDATE_STALE")
            policy = PostgresCandidatePolicyResolver(self.conn)
            probe_decision = policy.check_probe(
                item,
                probe_req,
                gates=gates,
                authority_resolver=authority_resolver,
                now=db_now,
            )
            if not probe_decision.allowed:
                raise BudgetDenied(probe_decision.reason)
            storage = check_storage(
                item,
                store_req,
                intended_capture=capture_kind,
                planned_bytes=planned_bytes,
                gates=gates,
                authority_resolver=authority_resolver,
                storage_resolver=policy,
                now=db_now,
            )
            if not storage.allowed:
                raise BudgetDenied(storage.reason)
            if (
                self.conn.execute(
                    "SELECT 1 FROM rag_candidate_captures WHERE candidate_id=%s",
                    (candidate_id,),
                ).fetchone()
                is not None
            ):
                return None
            self.conn.execute(
                "INSERT INTO rag_candidate_intake_leases(candidate_id,job_id) VALUES (%s,%s) "
                "ON CONFLICT (candidate_id) DO NOTHING",
                (candidate_id, row["job_id"]),
            )
            lease_row = self.conn.execute(
                "SELECT state,generation,expires_at FROM rag_candidate_intake_leases "
                "WHERE candidate_id=%s AND job_id=%s FOR UPDATE",
                (candidate_id, row["job_id"]),
            ).fetchone()
            if lease_row is None or lease_row["state"] == "done":
                return None
            # The lease-row lock can wait while actor authority changes or an
            # expiry passes. Do not authorize from the pre-wait snapshot/clock.
            db_now = _db_now(self.conn)
            if lease_row["state"] == "leased" and lease_row["expires_at"] > db_now:
                return None
            fresh_probe = current_authority(
                request=probe_req,
                demand=need,
                gates=gates,
                resolver=authority_resolver,
                now=db_now,
            )
            fresh_store = current_authority(
                request=store_req,
                demand=need,
                gates=gates,
                resolver=authority_resolver,
                now=db_now,
            )
            if fresh_probe != probe_authority or fresh_store != store_authority:
                raise BudgetDenied("AUTHORITY_CHANGED")
            fresh_root = PostgresBudgetPolicyResolver(self.conn).resolve(fresh_store)
            if (
                fresh_root != root
                or fresh_root is None
                or not fresh_root.period_start <= db_now < fresh_root.period_end
                or fresh_root.period_key != row["reserved_period"]
            ):
                raise BudgetDenied("INTAKE_DISCOVERY_STALE")
            fresh_probe_decision = policy.check_probe(
                item,
                probe_req,
                gates=gates,
                authority_resolver=authority_resolver,
                now=db_now,
            )
            if not fresh_probe_decision.allowed:
                raise BudgetDenied(fresh_probe_decision.reason)
            fresh_storage = check_storage(
                item,
                store_req,
                intended_capture=capture_kind,
                planned_bytes=planned_bytes,
                gates=gates,
                authority_resolver=authority_resolver,
                storage_resolver=policy,
                now=db_now,
            )
            if not fresh_storage.allowed or fresh_storage.retention_until is None:
                raise BudgetDenied(fresh_storage.reason)
            # The trigger itself rejects an already-expired new lease.
            expires = db_now + timedelta(seconds=lease_seconds)
            generation = lease_row["generation"] + 1
            self.conn.execute(
                "UPDATE rag_candidate_intake_leases SET state='leased',owner_id=%s,"
                "generation=%s,expires_at=%s,updated_at=%s WHERE candidate_id=%s",
                (owner_id, generation, expires, db_now, candidate_id),
            )
            return IntakeLease(
                candidate_id, row["job_id"], owner_id, generation, expires
            )

    def finish(self, *, lease: IntakeLease, success: bool) -> None:
        """Mark done only after a capture exists; failure releases without refund."""
        if type(success) is not bool:
            raise BudgetDenied("INVALID_INTAKE_FINISH")
        require_transaction(self.conn)
        with self.conn.transaction():
            db_now = _db_now(self.conn)
            require_live_intake_lease(self.conn, lease, db_now)
            if (
                success
                and self.conn.execute(
                    "SELECT 1 FROM rag_candidate_captures WHERE candidate_id=%s AND job_id=%s",
                    (lease.candidate_id, lease.job_id),
                ).fetchone()
                is None
            ):
                raise BudgetDenied("INTAKE_CAPTURE_MISSING")
            changed = self.conn.execute(
                "UPDATE rag_candidate_intake_leases SET state=%s,owner_id=NULL,expires_at=NULL,"
                "updated_at=clock_timestamp() WHERE candidate_id=%s AND job_id=%s "
                "AND state='leased' AND owner_id=%s AND generation=%s "
                "AND expires_at>clock_timestamp()",
                (
                    "done" if success else "idle",
                    lease.candidate_id,
                    lease.job_id,
                    lease.owner_id,
                    lease.generation,
                ),
            )
            if changed.rowcount != 1:
                raise BudgetDenied("INTAKE_LEASE_STALE")

    def release(self, *, lease: IntakeLease) -> None:
        self.finish(lease=lease, success=False)

    def reconcile_captured(self, *, candidate_id: UUID) -> bool:
        """Close a stranded capture audit without I/O or another B1 dispatch.

        Existing capture identity is immutable even after retention clearing or
        policy revocation. A currently live owner keeps the lease; an idle or
        expired lease is advanced through a new fenced generation to `done`.
        """
        if type(candidate_id) is not UUID:
            raise BudgetDenied("INVALID_INTAKE_CLAIM")
        require_transaction(self.conn)
        with self.conn.transaction():
            # Match claim's lock order. A competing claim skips this candidate;
            # a concurrent reconciler also gets no opportunity to steal it.
            candidate = self.conn.execute(
                "SELECT id,job_id FROM rag_discovery_candidates WHERE id=%s "
                "FOR UPDATE SKIP LOCKED",
                (candidate_id,),
            ).fetchone()
            if candidate is None:
                return False
            lease = self.conn.execute(
                "SELECT state,generation,expires_at FROM rag_candidate_intake_leases "
                "WHERE candidate_id=%s AND job_id=%s FOR UPDATE SKIP LOCKED",
                (candidate_id, candidate["job_id"]),
            ).fetchone()
            if lease is None:
                return False
            # A cleared body retains its audit row. Conversely, a lease alone
            # never proves that stage() actually persisted a capture.
            capture = self.conn.execute(
                "SELECT 1 FROM rag_candidate_captures WHERE candidate_id=%s AND job_id=%s",
                (candidate_id, candidate["job_id"]),
            ).fetchone()
            if capture is None:
                return False
            if lease["state"] == "done":
                return True
            db_now = _db_now(self.conn)
            if lease["state"] == "leased" and lease["expires_at"] > db_now:
                return False
            owner_id = "intake.reconcile"  # internal, never actor-owned
            generation = lease["generation"] + 1
            expires = db_now + timedelta(seconds=30)
            changed = self.conn.execute(
                "UPDATE rag_candidate_intake_leases SET state='leased',owner_id=%s,"
                "generation=%s,expires_at=%s,updated_at=%s "
                "WHERE candidate_id=%s AND job_id=%s AND generation=%s "
                "AND (state='idle' OR (state='leased' AND expires_at<=clock_timestamp()))",
                (
                    owner_id,
                    generation,
                    expires,
                    db_now,
                    candidate_id,
                    candidate["job_id"],
                    lease["generation"],
                ),
            )
            if changed.rowcount != 1:
                return False
            done = self.conn.execute(
                "UPDATE rag_candidate_intake_leases SET state='done',owner_id=NULL,"
                "expires_at=NULL,updated_at=clock_timestamp() "
                "WHERE candidate_id=%s AND job_id=%s AND state='leased' "
                "AND owner_id=%s AND generation=%s AND expires_at>clock_timestamp()",
                (candidate_id, candidate["job_id"], owner_id, generation),
            )
            if done.rowcount != 1:
                raise BudgetDenied("INTAKE_LEASE_STALE")
            return True
