"""Caller-transaction-owned B1 accounting; no provider calls or local balance authority."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from psycopg import Connection
from psycopg.pq import TransactionStatus

from .access_policy import (
    AccessRequest, AuthorityResolver, AuthoritySnapshot, AutonomousGates, check_access,
)
from .contracts import LearningMaterialDemand, SourceDiscoveryDemand, revalidate

_KEY = re.compile(r"^[A-Za-z0-9._:-]{8,160}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")


class BudgetDenied(ValueError):
    """Bounded, non-secret denial reason (never include resolver/provider text)."""


@dataclass(frozen=True)
class BudgetPolicy:
    """Resolved by a trusted server port, never supplied by model/request payload."""

    root_id: str
    period_key: str
    cap_units: int
    period_end: datetime
    period_start: datetime


class BudgetPolicyResolver(Protocol):
    def resolve(self, snapshot: AuthoritySnapshot) -> BudgetPolicy | None: ...


class PostgresBudgetPolicyResolver:
    """Read-only server-owned root authority; bootstrap never enables/provisions roots.

    The caller must run this on the same connection/transaction as reserve().
    This complements, never replaces, A's full-demand AuthorityResolver.
    """

    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def resolve(self, snapshot: AuthoritySnapshot) -> BudgetPolicy | None:
        require_transaction(self.conn)
        row = self.conn.execute(
            "SELECT root_id,delegation_id,delegation_generation,delegation_expires_at,"
            "policy_id,policy_generation,period_key,period_start,period_end,cap_units "
            "FROM rag_budget_authority_roots WHERE root_id=%s AND enabled=true FOR SHARE",
            (snapshot.budget.root_id,),
        ).fetchone()
        if row is None or (
            row["delegation_id"], row["delegation_generation"], row["delegation_expires_at"],
            row["policy_id"], row["policy_generation"]
        ) != (
            snapshot.budget.delegation_id, snapshot.budget.generation, snapshot.budget.expires_at,
            snapshot.policy_id, snapshot.policy_generation
        ):
            return None
        return BudgetPolicy(row["root_id"], row["period_key"], row["cap_units"],
                            row["period_end"], row["period_start"])

@dataclass(frozen=True)
class ReservationDecision:
    allowed: bool
    reason: str
    reservation_id: UUID | None = None


@dataclass(frozen=True)
class AttemptDecision:
    attempt_id: UUID
    state: str
    created: bool


@dataclass(frozen=True)
class SettlementDecision:
    state: str
    charged_units: int
    overage_units: int = 0


def fingerprint(*parts: object) -> str:
    """Opaque identity; do not log inputs, especially learner/private demand fields."""
    return hashlib.sha256(json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


class _CaptureResolver:
    def __init__(self, delegate: AuthorityResolver) -> None:
        self.delegate = delegate
        self.snapshot: AuthoritySnapshot | None = None

    def resolve(self, request: AccessRequest) -> AuthoritySnapshot | None:
        self.snapshot = self.delegate.resolve(request)
        return self.snapshot


def current_authority(
    *, request: AccessRequest, demand: LearningMaterialDemand, gates: AutonomousGates,
    resolver: AuthorityResolver, now: datetime,
) -> AuthoritySnapshot:
    """Resolve once with A's full-demand/action/gate check, not a caller delegation alone."""
    if resolver is None:
        raise BudgetDenied("AUTHORITY_MISSING")
    capture = _CaptureResolver(resolver)
    decision = check_access(request, demand=demand, gates=gates, resolver=capture, now=now)
    if not decision.allowed or capture.snapshot is None:
        raise BudgetDenied(decision.reason)
    try:
        return revalidate(capture.snapshot, AuthoritySnapshot)
    except (ValueError, TypeError) as exc:
        raise BudgetDenied("INVALID_CONTRACT") from exc


def require_transaction(conn: Connection[dict[str, Any]]) -> None:
    if conn.autocommit:
        raise BudgetDenied("TRANSACTION_REQUIRED")
    if conn.info.transaction_status == TransactionStatus.IDLE:
        conn.execute("SELECT 1")


def _valid_key(key: str) -> None:
    if not isinstance(key, str) or not _KEY.fullmatch(key):
        raise BudgetDenied("INVALID_OPERATION")


def _valid_hash(value: str) -> None:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise BudgetDenied("INVALID_RECEIPT")


class BudgetRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def reserve(
        self, *, request: AccessRequest, demand: LearningMaterialDemand,
        gates: AutonomousGates, resolver: AuthorityResolver,
        policy_resolver: BudgetPolicyResolver, job_id: UUID,
        operation_key: str, request_hash: str, units: int, now: datetime,
    ) -> ReservationDecision:
        _valid_key(operation_key)
        _valid_hash(request_hash)
        if not isinstance(units, int) or isinstance(units, bool) or not 1 <= units <= 1_000_000:
            raise BudgetDenied("INVALID_UNITS")
        snapshot = current_authority(request=request, demand=demand, gates=gates, resolver=resolver, now=now)
        try:
            policy = policy_resolver.resolve(snapshot)
        except Exception as exc:
            raise BudgetDenied("BUDGET_POLICY_UNAVAILABLE") from exc
        if (policy is None or policy.root_id != snapshot.budget.root_id
                or not re.fullmatch(r"^[A-Za-z0-9._:-]{1,79}$", policy.period_key)
                or not 1 <= policy.cap_units <= 1_000_000
                or now.tzinfo is None or policy.period_start.tzinfo is None
                or policy.period_end.tzinfo is None or not policy.period_start <= now < policy.period_end):
            raise BudgetDenied("BUDGET_POLICY_UNAVAILABLE")
        require_transaction(self.conn)
        with self.conn.transaction():
            if current_authority(request=request, demand=demand, gates=gates, resolver=resolver, now=now) != snapshot:
                raise BudgetDenied("AUTHORITY_CHANGED")
            job = self.conn.execute(
                "SELECT id FROM rag_discovery_jobs WHERE id=%s AND root_id=%s AND demand_hash=%s "
                "AND subject_id=%s AND subject_version=%s AND purpose=%s AND policy_id=%s "
                "AND policy_generation=%s AND delegation_id=%s AND delegation_generation=%s",
                (job_id, policy.root_id, demand.demand_hash, demand.scope.subject_id,
                 demand.scope.subject_version, demand.purpose, snapshot.policy_id, snapshot.policy_generation,
                 snapshot.budget.delegation_id, snapshot.budget.generation),
            ).fetchone()
            if job is None:
                raise BudgetDenied("JOB_SCOPE_STALE")
            self.conn.execute(
                "INSERT INTO rag_budget_periods(root_id,period_key,cap_units,period_end) VALUES (%s,%s,%s,%s) "
                "ON CONFLICT DO NOTHING", (policy.root_id, policy.period_key, policy.cap_units, policy.period_end),
            )
            period = self.conn.execute(
                "SELECT cap_units,period_end FROM rag_budget_periods WHERE root_id=%s AND period_key=%s FOR UPDATE",
                (policy.root_id, policy.period_key),
            ).fetchone()
            if period is None or period["cap_units"] != policy.cap_units or period["period_end"] != policy.period_end:
                raise BudgetDenied("BUDGET_POLICY_STALE")
            previous = self.conn.execute(
                "SELECT id,request_hash,job_id,reserved_units,state FROM rag_budget_reservations "
                "WHERE root_id=%s AND period_key=%s AND operation_key=%s",
                (policy.root_id, policy.period_key, operation_key),
            ).fetchone()
            if previous is not None:
                if (previous["request_hash"], previous["job_id"], previous["reserved_units"]) != (
                    request_hash, job_id, units
                ):
                    raise BudgetDenied("RESERVATION_CONFLICT")
                return ReservationDecision(True, "REPLAY", previous["id"])
            charged_row = self.conn.execute(
                "SELECT COALESCE(SUM(CASE WHEN state='settled' THEN settled_units "
                "ELSE reserved_units END),0) AS units "
                "FROM rag_budget_reservations WHERE root_id=%s AND period_key=%s",
                (policy.root_id, policy.period_key),
            ).fetchone()
            assert charged_row is not None
            charged = charged_row["units"]
            if charged + units > policy.cap_units:
                return ReservationDecision(False, "CAP_EXHAUSTED")
            inserted = self.conn.execute(
                "INSERT INTO rag_budget_reservations(root_id,period_key,operation_key,request_hash,job_id,reserved_units) "
                "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                (policy.root_id, policy.period_key, operation_key, request_hash, job_id, units),
            ).fetchone()
            assert inserted is not None
            return ReservationDecision(True, "RESERVED", inserted["id"])

    def record_attempt(self, *, reservation_id: UUID, attempt_key: str, lease: JobLease, now: datetime) -> AttemptDecision:
        from .jobs import require_live_lease
        _valid_key(attempt_key)
        require_transaction(self.conn)
        with self.conn.transaction():
            require_live_lease(self.conn, lease, now)
            reservation = self.conn.execute(
                "SELECT id,job_id,state FROM rag_budget_reservations WHERE id=%s FOR UPDATE", (reservation_id,),
            ).fetchone()
            if reservation is None or reservation["job_id"] != lease.job_id:
                raise BudgetDenied("RESERVATION_NOT_FOUND")
            existing = self.conn.execute(
                "SELECT id,attempt_key,state FROM rag_budget_attempts WHERE reservation_id=%s", (reservation_id,),
            ).fetchone()
            if existing:
                if existing["attempt_key"] != attempt_key:
                    raise BudgetDenied("ATTEMPT_CONFLICT")
                return AttemptDecision(existing["id"], existing["state"], False)
            if reservation["state"] != "reserved":
                raise BudgetDenied("RESERVATION_NOT_READY")
            row = self.conn.execute(
                "INSERT INTO rag_budget_attempts(reservation_id,job_id,attempt_key) VALUES (%s,%s,%s) "
                "ON CONFLICT DO NOTHING RETURNING id",
                (reservation_id, lease.job_id, attempt_key),
            ).fetchone()
            self.conn.execute("UPDATE rag_budget_reservations SET state='attempted',updated_at=%s WHERE id=%s", (now, reservation_id))
            if row is None:
                raise BudgetDenied("ATTEMPT_CONFLICT")
            return AttemptDecision(row["id"], "started", True)

    def take_dispatch(
        self, *, projection: SourceDiscoveryDemand, request: AccessRequest,
        demand: LearningMaterialDemand, gates: AutonomousGates,
        resolver: AuthorityResolver, lease: JobLease, reservation_id: UUID,
        attempt_id: UUID, now: datetime,
    ) -> bool:
        """Durable one-shot provider dispatch; external I/O starts only after caller commits.

        A crash after this CAS is ambiguous spend: never dispatch this attempt again.
        """
        from .jobs import DiscoveryJobRepository, projected_query_hash, require_live_lease
        if request.action != "discover":
            raise BudgetDenied("ACTION_DENIED")
        snapshot = current_authority(request=request, demand=demand, gates=gates, resolver=resolver, now=now)
        query_hash = projected_query_hash(projection, snapshot, demand)
        require_transaction(self.conn)
        with self.conn.transaction():
            require_live_lease(self.conn, lease, now)
            if current_authority(request=request, demand=demand, gates=gates, resolver=resolver, now=now) != snapshot:
                raise BudgetDenied("AUTHORITY_CHANGED")
            job = self.conn.execute("SELECT * FROM rag_discovery_jobs WHERE id=%s", (lease.job_id,)).fetchone()
            if job is None:
                raise BudgetDenied("JOB_NOT_FOUND")
            DiscoveryJobRepository._scope(job, snapshot, demand)
            if job["query_hash"] != query_hash:
                raise BudgetDenied("PROJECTION_SCOPE_STALE")
            row = self.conn.execute(
                "SELECT a.state AS attempt_state,r.state AS reservation_state,r.job_id,r.root_id "
                "FROM rag_budget_attempts a JOIN rag_budget_reservations r ON r.id=a.reservation_id "
                "WHERE a.id=%s AND a.reservation_id=%s FOR UPDATE OF a,r",
                (attempt_id, reservation_id),
            ).fetchone()
            if row is None or row["job_id"] != lease.job_id or row["root_id"] != snapshot.budget.root_id:
                raise BudgetDenied("ATTEMPT_NOT_FOUND")
            if row["attempt_state"] != "started" or row["reservation_state"] != "attempted":
                return False
            updated = self.conn.execute(
                "UPDATE rag_budget_attempts SET state='dispatched',dispatch_owner_id=%s,"
                "dispatch_generation=%s,dispatched_at=%s,updated_at=%s "
                "WHERE id=%s AND state='started' RETURNING id",
                (lease.owner_id, lease.generation, now, now, attempt_id),
            ).fetchone()
            return updated is not None
    def mark_unknown(self, *, attempt_id: UUID, error_code: str, now: datetime) -> None:
        """Durably hold full reservation after ambiguous provider result, even if lease expired."""
        if not re.fullmatch(r"^[A-Z][A-Z0-9_]{0,79}$", error_code):
            raise BudgetDenied("INVALID_ERROR_CODE")
        require_transaction(self.conn)
        with self.conn.transaction():
            row = self.conn.execute(
                "SELECT a.reservation_id,a.state,r.state AS reservation_state FROM rag_budget_attempts a "
                "JOIN rag_budget_reservations r ON r.id=a.reservation_id WHERE a.id=%s FOR UPDATE OF a,r", (attempt_id,),
            ).fetchone()
            if row is None:
                raise BudgetDenied("ATTEMPT_NOT_FOUND")
            if row["state"] == "settled":
                return
            self.conn.execute("UPDATE rag_budget_attempts SET state='unknown',error_code=%s,updated_at=%s WHERE id=%s",
                              (error_code, now, attempt_id))
            self.conn.execute("UPDATE rag_budget_reservations SET state='unknown',updated_at=%s WHERE id=%s",
                              (now, row["reservation_id"]))

    def settle(
        self, *, attempt_id: UUID, lease: JobLease, usage: int | None,
        receipt_hash: str | None, now: datetime,
    ) -> SettlementDecision:
        """Only authoritative usage/hash settles; None is an unknown hold, never zero."""
        from .jobs import require_live_lease
        if usage is not None:
            if isinstance(usage, bool) or not isinstance(usage, int) or not 0 <= usage <= 1_000_000:
                raise BudgetDenied("INVALID_USAGE")
            if receipt_hash is None:
                raise BudgetDenied("INVALID_RECEIPT")
            _valid_hash(receipt_hash)
        elif receipt_hash is not None:
            raise BudgetDenied("INVALID_RECEIPT")
        require_transaction(self.conn)
        with self.conn.transaction():
            require_live_lease(self.conn, lease, now)
            identity = self.conn.execute(
                "SELECT r.root_id,r.period_key FROM rag_budget_attempts a "
                "JOIN rag_budget_reservations r ON r.id=a.reservation_id WHERE a.id=%s", (attempt_id,),
            ).fetchone()
            if identity is None:
                raise BudgetDenied("ATTEMPT_NOT_FOUND")
            self.conn.execute(
                "SELECT 1 FROM rag_budget_periods WHERE root_id=%s AND period_key=%s FOR UPDATE",
                (identity["root_id"], identity["period_key"]),
            )
            row = self.conn.execute(
                "SELECT a.reservation_id,a.state,a.dispatch_owner_id,r.job_id,r.reserved_units,r.settled_units,r.settlement_receipt_hash "
                "FROM rag_budget_attempts a JOIN rag_budget_reservations r ON r.id=a.reservation_id "
                "WHERE a.id=%s FOR UPDATE OF a,r", (attempt_id,),
            ).fetchone()
            if row is None or row["job_id"] != lease.job_id:
                raise BudgetDenied("ATTEMPT_NOT_FOUND")
            if row["state"] == "settled":
                if usage != row["settled_units"] or receipt_hash != row["settlement_receipt_hash"]:
                    raise BudgetDenied("SETTLEMENT_CONFLICT")
                assert usage is not None
                return SettlementDecision("settled", usage, max(0, usage - row["reserved_units"]))
            if usage is not None and row["dispatch_owner_id"] is None:
                raise BudgetDenied("DISPATCH_NOT_TAKEN")
            if usage is None:
                self.conn.execute("UPDATE rag_budget_attempts SET state='unknown',updated_at=%s WHERE id=%s", (now, attempt_id))
                self.conn.execute("UPDATE rag_budget_reservations SET state='unknown',updated_at=%s WHERE id=%s",
                                  (now, row["reservation_id"]))
                return SettlementDecision("unknown", row["reserved_units"])
            self.conn.execute("UPDATE rag_budget_attempts SET state='settled',updated_at=%s WHERE id=%s", (now, attempt_id))
            self.conn.execute(
                "UPDATE rag_budget_reservations SET state='settled',settled_units=%s,settlement_receipt_hash=%s,updated_at=%s WHERE id=%s",
                (usage, receipt_hash, now, row["reservation_id"]),
            )
            return SettlementDecision("settled", usage, max(0, usage - row["reserved_units"]))


if TYPE_CHECKING:
    from .jobs import JobLease
