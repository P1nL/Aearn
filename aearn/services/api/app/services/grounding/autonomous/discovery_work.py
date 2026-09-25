"""Durable B1 discovery work; no live provider or worker is enabled here.

Context resolution must be server-owned issuance state, never a caller echo or
hash-only lookup. Fake ports demonstrate protocol behavior, not production safety.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Protocol
from uuid import UUID

from psycopg import Connection
from psycopg.pq import TransactionStatus

from .access_policy import AccessRequest, AuthorityResolver, AutonomousGates
from .budget import BudgetDenied, BudgetPolicyResolver, BudgetRepository, current_authority, fingerprint
from .candidate_repository import CandidateRepository, _public_url
from .contracts import LearningMaterialDemand, SourceCandidate, SourceDiscoveryDemand, revalidate
from .discovery_broker import (
    AttemptTicket, DiscoveryWorkPort, SearchSettlement, WorkClaim, WorkDecision,
    _query_operation_id,
)
from .jobs import DiscoveryJobRepository, JobLease, projected_query_hash, require_live_lease


@dataclass(frozen=True)
class WorkContext:
    demand: LearningMaterialDemand
    projection: SourceDiscoveryDemand


class DiscoveryContextResolver(Protocol):
    """Resolve both issued and persisted jobs from trusted full-demand state."""

    def resolve_issued(self, demand: LearningMaterialDemand,
                       projection: SourceDiscoveryDemand) -> WorkContext | None: ...

    def resolve_job(self, job_id: UUID) -> WorkContext | None: ...


class UsageAuthority(Protocol):
    """Verify authoritative provider evidence, not self-reported usage."""

    def verify_usage(self, attempt_id: UUID, receipt_id: str, units: int) -> bool: ...

    def verify_account_exhausted(self, attempt_id: UUID, receipt_id: str) -> bool: ...


class LiveSearchPermission(Protocol):
    def permitted(self) -> bool: ...


def _handle(prefix: str, identity: UUID) -> str:
    return f"{prefix}.{identity.hex}"


def _uuid(handle: str, prefix: str) -> UUID:
    if (not isinstance(handle, str) or not handle.startswith(prefix + ".")
            or len(handle) != len(prefix) + 33
            or any(c not in "0123456789abcdef" for c in handle[len(prefix) + 1:])):
        raise BudgetDenied("INVALID_HANDLE")
    return UUID(hex=handle[len(prefix) + 1:])


class PostgresDiscoveryWork(DiscoveryWorkPort):
    """One connection owns atomic job/reservation and fenced outcome commits."""

    def __init__(
        self, *, conn: Connection[dict[str, Any]], authority: AuthorityResolver | None,
        context: DiscoveryContextResolver | None, policy: BudgetPolicyResolver | None,
        gates: Callable[[], AutonomousGates | None],
        permission: LiveSearchPermission | None, usage: UsageAuthority | None,
        owner_id: str, clock: Callable[[], datetime], reserve_units: int = 1,
    ) -> None:
        self.conn, self.authority, self.context = conn, authority, context
        self.policy, self.gates, self.permission = policy, gates, permission
        self.usage, self.owner_id, self.clock = usage, owner_id, clock
        self.reserve_units = reserve_units
        self.jobs = DiscoveryJobRepository(conn)
        self.budget = BudgetRepository(conn)
        self.candidates = CandidateRepository(conn)

    def _issued(self, demand: LearningMaterialDemand,
                projection: SourceDiscoveryDemand) -> WorkContext:
        if self.context is None:
            raise BudgetDenied("CONTEXT_MISSING")
        valid_demand = revalidate(demand, LearningMaterialDemand)
        valid_projection = revalidate(projection, SourceDiscoveryDemand)
        found = self.context.resolve_issued(valid_demand, valid_projection)
        if (not isinstance(found, WorkContext)
                or revalidate(found.demand, LearningMaterialDemand) != valid_demand
                or revalidate(found.projection, SourceDiscoveryDemand) != valid_projection):
            raise BudgetDenied("CONTEXT_STALE")
        return found

    def _resolver(self) -> AuthorityResolver:
        if self.authority is None:
            raise BudgetDenied("AUTHORITY_MISSING")
        return self.authority

    def _transaction(self) -> Any:
        # Provider I/O must follow a committed CAS, never a savepoint.
        if self.conn.autocommit or self.conn.info.transaction_status != TransactionStatus.IDLE:
            raise BudgetDenied("TRANSACTION_NOT_IDLE")
        return self.conn.transaction()

    def _live(self, context: WorkContext) -> tuple[AccessRequest, AutonomousGates, datetime]:
        if (self.conn.autocommit or self.authority is None or self.permission is None
                or self.permission.permitted() is not True):
            raise BudgetDenied("WORK_DISABLED")
        gates = self.gates()
        if gates is None:
            raise BudgetDenied("GATE_CLOSED")
        demand, projection = context.demand, context.projection
        request = AccessRequest(
            demand_hash=demand.demand_hash, scope=demand.scope, purpose=demand.purpose,
            actor_id=projection.actor_id, action="discover", policy_id=projection.policy_id,
            policy_generation=projection.policy_generation, budget=projection.budget,
        )
        now = self.clock()
        snapshot = current_authority(request=request, demand=demand, gates=gates,
                                     resolver=self._resolver(), now=now)
        projected_query_hash(projection, snapshot, demand)
        return request, gates, now

    def _claim(self, claim: WorkClaim) -> tuple[WorkContext, JobLease, UUID, datetime]:
        checked = revalidate(claim, WorkClaim)
        job_id, reservation_id = _uuid(checked.job_id, "job"), _uuid(checked.reservation_id, "reservation")
        job = self.conn.execute("SELECT * FROM rag_discovery_jobs WHERE id=%s", (job_id,)).fetchone()
        if job is None or self.context is None:
            raise BudgetDenied("CONTEXT_MISSING")
        found = self.context.resolve_job(job_id)
        if not isinstance(found, WorkContext):
            raise BudgetDenied("CONTEXT_STALE")
        context = self._issued(found.demand, found.projection)
        if _query_operation_id(context.demand, context.projection) != job["operation_key"]:
            raise BudgetDenied("CONTEXT_STALE")
        request, gates, now = self._live(context)
        snapshot = current_authority(request=request, demand=context.demand, gates=gates,
                                     resolver=self._resolver(), now=now)
        DiscoveryJobRepository._scope(job, snapshot, context.demand)
        if (job["query_hash"] != projected_query_hash(context.projection, snapshot, context.demand)
                or job["lease_owner_id"] != checked.lease_owner
                or job["lease_generation"] != checked.lease_generation):
            raise BudgetDenied("LEASE_STALE")
        lease = JobLease(job_id, checked.lease_owner, checked.lease_generation, job["lease_expires_at"])
        require_live_lease(self.conn, lease, now)
        row = self.conn.execute(
            "SELECT operation_key,request_hash FROM rag_budget_reservations WHERE id=%s AND job_id=%s",
            (reservation_id, job_id),
        ).fetchone()
        if row is None or (row["operation_key"], row["request_hash"]) != (
                job["operation_key"], job["request_hash"]):
            raise BudgetDenied("RESERVATION_NOT_FOUND")
        return context, lease, reservation_id, now

    def _ticket(self, claim: WorkClaim, ticket: AttemptTicket) -> tuple[WorkContext, JobLease, UUID, datetime]:
        context, lease, reservation_id, now = self._claim(claim)
        issued = revalidate(ticket, AttemptTicket)
        if issued.job_id != claim.job_id or issued.lease_generation != lease.generation:
            raise BudgetDenied("ATTEMPT_SCOPE_STALE")
        attempt_id = _uuid(issued.attempt_id, "attempt")
        row = self.conn.execute(
            "SELECT attempt_key FROM rag_budget_attempts WHERE id=%s AND reservation_id=%s AND job_id=%s",
            (attempt_id, reservation_id, lease.job_id),
        ).fetchone()
        if row is None or row["attempt_key"] != _handle("attempt", reservation_id):
            raise BudgetDenied("ATTEMPT_SCOPE_STALE")
        return context, lease, attempt_id, now

    def claim_or_reuse(self, demand: LearningMaterialDemand,
                       projection: SourceDiscoveryDemand, operation_id: str) -> WorkDecision:
        try:
            # One short transaction: unique job, canonical root/period reserve, lease.
            # Nested repository transactions are savepoints; no network I/O occurs.
            with self._transaction():
                context = self._issued(demand, projection)
                if self.policy is None or operation_id != _query_operation_id(context.demand, context.projection):
                    return WorkDecision(status="denied")
                request, gates, now = self._live(context)
                request_hash = fingerprint(context.demand.model_dump(mode="json"),
                                           context.projection.query_terms, operation_id)
                job_id = self.jobs.enqueue(
                    request=request, demand=context.demand, projection=context.projection,
                    gates=gates, resolver=self._resolver(), operation_key=operation_id,
                    request_hash=request_hash, now=now,
                )
                reservation = self.budget.reserve(
                    request=request, demand=context.demand, gates=gates,
                    resolver=self._resolver(), policy_resolver=self.policy, job_id=job_id,
                    operation_key=operation_id, request_hash=request_hash,
                    units=self.reserve_units, now=now,
                )
                if not reservation.allowed or reservation.reservation_id is None:
                    raise BudgetDenied(reservation.reason)
                if reservation.reason == "REPLAY":
                    state = self.conn.execute(
                        "SELECT state FROM rag_budget_reservations WHERE id=%s FOR UPDATE",
                        (reservation.reservation_id,),
                    ).fetchone()
                    if state is None or state["state"] != "reserved":
                        return WorkDecision(status="existing", job_id=_handle("job", job_id))
                lease = self.jobs.claim(
                    job_id=job_id, request=request, demand=context.demand, gates=gates,
                    resolver=self._resolver(), owner_id=self.owner_id, now=now,
                )
                if lease is None:
                    return WorkDecision(status="existing", job_id=_handle("job", job_id))
                return WorkDecision(status="claimed", claim=WorkClaim(
                    job_id=_handle("job", job_id),
                    reservation_id=_handle("reservation", reservation.reservation_id),
                    lease_owner=lease.owner_id, lease_generation=lease.generation,
                ))
        except Exception:
            return WorkDecision(status="denied")

    def prepare_attempt(self, claim: WorkClaim) -> AttemptTicket | None:
        try:
            with self._transaction():
                _, lease, reservation_id, now = self._claim(claim)
                result = self.budget.record_attempt(
                    reservation_id=reservation_id, attempt_key=_handle("attempt", reservation_id),
                    lease=lease, now=now,
                )
                if not result.created or result.state != "started":
                    return None
                return AttemptTicket(job_id=claim.job_id,
                                     attempt_id=_handle("attempt", result.attempt_id),
                                     lease_generation=lease.generation)
        except Exception:
            return None

    def take_dispatch(self, demand: SourceDiscoveryDemand, claim: WorkClaim,
                      ticket: AttemptTicket) -> bool:
        try:
            with self._transaction():
                context, lease, attempt_id, now = self._ticket(claim, ticket)
                if revalidate(demand, SourceDiscoveryDemand) != context.projection:
                    return False
                request, gates, _ = self._live(context)
                return self.budget.take_dispatch(
                    projection=context.projection, request=request, demand=context.demand,
                    gates=gates, resolver=self._resolver(), lease=lease,
                    reservation_id=_uuid(claim.reservation_id, "reservation"),
                    attempt_id=attempt_id, now=now,
                )
        except Exception:
            return False

    def record_outcome(self, claim: WorkClaim, ticket: AttemptTicket,
                       settlement: SearchSettlement,
                       candidates: tuple[SourceCandidate, ...] = ()) -> bool:
        """Settle and terminalize in one transaction; never strand a settled lease.

        Bad/empty leads still settle verified usage, but produce a failed job. A
        crash before this transaction commits leaves the full reservation held.
        """
        try:
            outcome = revalidate(settlement, SearchSettlement)
            with self._transaction():
                context, lease, attempt_id, now = self._ticket(claim, ticket)
                row = self.conn.execute("SELECT state FROM rag_budget_attempts WHERE id=%s FOR UPDATE",
                                        (attempt_id,)).fetchone()
                if row is None or row["state"] != "dispatched" or self.usage is None:
                    return False
                request, gates, _ = self._live(context)
                if outcome.status == "account_exhausted":
                    if (outcome.quota_receipt_id != ticket.attempt_id
                            or not self.usage.verify_account_exhausted(attempt_id, outcome.quota_receipt_id)):
                        return False
                    self.budget.mark_unknown(attempt_id=attempt_id, error_code="ACCOUNT_EXHAUSTED", now=now)
                    self.jobs.complete(lease=lease, request=request, demand=context.demand,
                                       gates=gates, resolver=self._resolver(), now=now, success=False)
                    return True
                if outcome.usage_units is None or outcome.usage_receipt_id is None:
                    self.budget.mark_unknown(attempt_id=attempt_id, error_code="USAGE_UNKNOWN", now=now)
                    self.jobs.complete(lease=lease, request=request, demand=context.demand,
                                       gates=gates, resolver=self._resolver(), now=now, success=False)
                    return True
                if not self.usage.verify_usage(attempt_id, outcome.usage_receipt_id, outcome.usage_units):
                    return False
                # Validate the *whole* batch before writing any candidate. A bad
                # provider lead must not make a successfully billed job nonterminal.
                valid: tuple[SourceCandidate, ...] = ()
                if outcome.status == "completed" and 0 < len(candidates) <= 5:
                    try:
                        checked = tuple(revalidate(item, SourceCandidate) for item in candidates)
                        if all(c.kind == "landing" and c.capture.kind == "none"
                               and c.discovery_receipt_id == ticket.attempt_id
                               and c.demand_hash == context.demand.demand_hash
                               and c.scope == context.demand.scope for c in checked):
                            for candidate in checked:
                                _public_url(candidate.url)
                            valid = checked
                    except (ValueError, BudgetDenied):
                        pass
                result = self.budget.settle(
                    attempt_id=attempt_id, lease=lease, usage=outcome.usage_units,
                    receipt_hash=fingerprint(attempt_id.hex, outcome.usage_receipt_id,
                                             outcome.usage_units), now=now,
                )
                if result.state != "settled":
                    return False
                if valid:
                    self.candidates.record_receipt(
                        lease=lease, request=request, demand=context.demand, gates=gates,
                        resolver=self._resolver(), attempt_id=attempt_id,
                        receipt_handle=ticket.attempt_id, result_code="SEARCH_COMPLETED",
                        response_hash=fingerprint(tuple(c.model_dump(mode="json") for c in valid),
                                                  ticket.attempt_id), now=now,
                    )
                    for candidate in valid:
                        self.candidates.record_candidate(
                            lease=lease, request=request, demand=context.demand,
                            gates=gates, resolver=self._resolver(), candidate=candidate, now=now,
                        )
                self.jobs.complete(lease=lease, request=request, demand=context.demand,
                                   gates=gates, resolver=self._resolver(), now=now, success=bool(valid))
                return True
        except Exception:
            return False

    def record_unknown(self, claim: WorkClaim, ticket: AttemptTicket | None) -> None:
        # A reservation without an attempt stays held; no process-local refund.
        if ticket is None:
            return
        try:
            checked, issued = revalidate(claim, WorkClaim), revalidate(ticket, AttemptTicket)
            job_id = _uuid(checked.job_id, "job")
            reservation_id = _uuid(checked.reservation_id, "reservation")
            attempt_id = _uuid(issued.attempt_id, "attempt")
            if issued.job_id != checked.job_id or issued.lease_generation != checked.lease_generation:
                return
            with self._transaction():
                row = self.conn.execute(
                    "SELECT a.attempt_key FROM rag_budget_attempts a JOIN rag_budget_reservations r "
                    "ON r.id=a.reservation_id WHERE a.id=%s AND a.reservation_id=%s "
                    "AND a.job_id=%s AND r.job_id=%s",
                    (attempt_id, reservation_id, job_id, job_id),
                ).fetchone()
                if row is not None and row["attempt_key"] == _handle("attempt", reservation_id):
                    now = self.clock()
                    self.budget.mark_unknown(attempt_id=attempt_id, error_code="OUTCOME_UNKNOWN", now=now)
                    self.jobs.fail_if_owned(
                        lease=JobLease(job_id, checked.lease_owner, checked.lease_generation, now),
                        now=now,
                    )
        except Exception:
            return
