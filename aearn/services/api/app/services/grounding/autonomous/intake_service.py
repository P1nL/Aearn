"""Default-closed B2 intake; live needs signed egress and fresh DB authority."""

from __future__ import annotations

import asyncio
from hashlib import sha256
from datetime import datetime, timezone
from typing import Any, Callable, Protocol
from uuid import UUID

from psycopg import Connection

from .access_policy import (
    AccessRequest,
    AuthorityResolver,
    AutonomousGates,
    AuthoritySnapshot,
    check_candidate_access,
)
from .budget import BudgetDenied, PostgresBudgetPolicyResolver, current_authority
from .candidate_repository import _public_url
from .candidate_policy_repository import PostgresCandidatePolicyResolver
from .hop_policy import CandidateHopPolicy
from .contracts import LearningMaterialDemand, SourceCandidate, revalidate
from .jobs import DiscoveryJobRepository
from .intake_leases import IntakeLease, require_live_intake_lease
from .provenance import Attribution, PreparedCapture, prepare_capture
from .retention import CaptureKind, StorageDecision, StorageGrant, StorageGrantResolver, check_storage
from .safe_fetch import SafeFetcher
from .staging import CandidateStagingRepository


class IntakeReadiness(Protocol):
    """Trusted short-transaction read, not a caller assertion or cached grant.

    Must verify candidate_id belongs to lease.job_id and its exact discovery
    receipt/candidate scope, canonical root is enabled and budget obligations
    are valid, and lease owner/generation/expiry are current. Recheck after I/O.
    """

    def verify(
        self,
        *,
        candidate_id: UUID,
        candidate: SourceCandidate,
        lease: IntakeLease,
        demand: LearningMaterialDemand,
        authority: AuthoritySnapshot,
        now: datetime,
    ) -> bool: ...


class PostgresIntakeReadiness:
    """Fresh short transaction per check, never spanning network I/O.

    The factory must provide a new non-autocommit connection. This preflight
    does not replace staging's commit-time fencing and permission checks.
    """

    def __init__(self, connect: Callable[[], Connection[dict[str, Any]]]) -> None:
        self.connect = connect

    def verify(
        self,
        *,
        candidate_id: UUID,
        candidate: SourceCandidate,
        lease: IntakeLease,
        demand: LearningMaterialDemand,
        authority: AuthoritySnapshot,
        now: datetime,
    ) -> bool:
        try:
            item = revalidate(candidate, SourceCandidate)
            need = revalidate(demand, LearningMaterialDemand)
            snapshot = revalidate(authority, AuthoritySnapshot)
            if (
                type(candidate_id) is not UUID
                or type(lease) is not IntakeLease
                or lease.candidate_id != candidate_id
                or item.demand_hash != need.demand_hash
                or item.scope != need.scope
                or _public_url(item.url) != item.url
            ):
                return False
            with self.connect() as conn:
                if conn.autocommit:
                    return False
                with conn.transaction():
                    clock_row = conn.execute("SELECT clock_timestamp() AS db_now").fetchone()
                    if clock_row is None:
                        return False
                    db_now = clock_row["db_now"]
                    require_live_intake_lease(conn, lease, db_now)
                    clock_row = conn.execute("SELECT clock_timestamp() AS db_now").fetchone()
                    if clock_row is None:
                        return False
                    db_now = clock_row["db_now"]
                    require_live_intake_lease(conn, lease, db_now)
                    root = PostgresBudgetPolicyResolver(conn).resolve(snapshot)
                    if (
                        root is None
                        or root.root_id != snapshot.budget.root_id
                        or not root.period_start <= db_now < root.period_end
                    ):
                        return False
                    job = conn.execute(
                        "SELECT * FROM rag_discovery_jobs WHERE id=%s",
                        (lease.job_id,),
                    ).fetchone()
                    if job is None:
                        return False
                    DiscoveryJobRepository._scope(job, snapshot, need)
                    row = conn.execute(
                        "SELECT c.canonical_url,c.canonical_url_hash,c.kind,c.demand_hash,"
                        "c.subject_id,c.subject_version,c.repo_commit,c.repo_path,"
                        "r.receipt_handle,a.state AS attempt_state,res.job_id AS reserved_job,"
                        "res.root_id AS reserved_root,res.period_key AS reserved_period,"
                        "res.state AS reservation_state,j.state AS job_state "
                        "FROM rag_discovery_candidates c "
                        "JOIN rag_discovery_jobs j ON j.id=c.job_id "
                        "JOIN rag_discovery_receipts r ON r.id=c.discovery_receipt_id "
                        "AND r.job_id=c.job_id "
                        "JOIN rag_budget_attempts a ON a.id=r.attempt_id AND a.job_id=c.job_id "
                        "JOIN rag_budget_reservations res ON res.id=a.reservation_id AND res.job_id=c.job_id "
                        "WHERE c.id=%s AND c.job_id=%s",
                        (candidate_id, lease.job_id),
                    ).fetchone()
                    return row is not None and (
                        row["canonical_url"],
                        row["canonical_url_hash"],
                        row["kind"],
                        row["demand_hash"],
                        row["subject_id"],
                        row["subject_version"],
                        row["repo_commit"],
                        row["repo_path"],
                        row["receipt_handle"],
                        row["attempt_state"],
                        row["reserved_job"],
                        row["reserved_root"],
                        row["reserved_period"],
                        row["reservation_state"],
                        row["job_state"],
                    ) == (
                        item.url,
                        sha256(item.url.encode()).hexdigest(),
                        item.kind,
                        need.demand_hash,
                        need.scope.subject_id,
                        need.scope.subject_version,
                        item.repo_commit,
                        item.repo_path,
                        item.discovery_receipt_id,
                        "settled",
                        lease.job_id,
                        root.root_id,
                        root.period_key,
                        "settled",
                        "completed",
                    )
        except Exception:
            return False


class FreshCandidatePolicy:
    """Per-hop/retention policy read with a fresh short DB transaction."""

    def __init__(self, connect: Callable[[], Connection[dict[str, Any]]]) -> None:
        self.connect = connect

    def check_probe(self, candidate: SourceCandidate, request: AccessRequest, *,
                    gates: AutonomousGates | None,
                    authority_resolver: AuthorityResolver | None,
                    now: datetime):
        try:
            with self.connect() as conn:
                if conn.autocommit:
                    return None
                with conn.transaction():
                    return PostgresCandidatePolicyResolver(conn).check_probe(
                        candidate, request, gates=gates,
                        authority_resolver=authority_resolver, now=now,
                    )
        except Exception:
            return None

    def resolve(self, candidate: SourceCandidate, request: AccessRequest) -> StorageGrant | None:
        try:
            with self.connect() as conn:
                if conn.autocommit:
                    return None
                with conn.transaction():
                    return PostgresCandidatePolicyResolver(conn).resolve(candidate, request)
        except Exception:
            return None


class IntakeService:
    def __init__(
        self,
        *,
        fetcher: SafeFetcher,
        staging: CandidateStagingRepository,
        readiness: IntakeReadiness | None,
        clock: Callable[[], datetime] | None = None,
        offline_protocol_test: bool = False,
    ) -> None:
        self.fetcher = fetcher
        self.staging = staging
        self.readiness = readiness
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.offline_protocol_test = offline_protocol_test

    def _authorize(
        self,
        *,
        candidate_id: UUID,
        candidate: SourceCandidate,
        lease: IntakeLease,
        demand: LearningMaterialDemand,
        probe: AccessRequest,
        store: AccessRequest,
        capture_kind: CaptureKind,
        planned_bytes: int,
        gates: AutonomousGates,
        authority_resolver: AuthorityResolver,
        storage_resolver: StorageGrantResolver,
        now: datetime,
    ) -> StorageDecision:
        probe_decision = check_candidate_access(
            candidate, probe, gates=gates, resolver=authority_resolver, now=now
        )
        if not probe_decision.allowed:
            raise BudgetDenied(probe_decision.reason)
        storage = check_storage(
            candidate,
            store,
            intended_capture=capture_kind,
            planned_bytes=planned_bytes,
            gates=gates,
            authority_resolver=authority_resolver,
            storage_resolver=storage_resolver,
            now=now,
        )
        if not storage.allowed or storage.retention_until is None:
            raise BudgetDenied(storage.reason)
        probe_authority = current_authority(
            request=probe,
            demand=demand,
            gates=gates,
            resolver=authority_resolver,
            now=now,
        )
        store_authority = current_authority(
            request=store,
            demand=demand,
            gates=gates,
            resolver=authority_resolver,
            now=now,
        )
        if probe_authority.budget.root_id != store_authority.budget.root_id:
            raise BudgetDenied("BUDGET_SCOPE_STALE")
        if self.readiness is None:
            raise BudgetDenied("INTAKE_READINESS_MISSING")
        try:
            ready = self.readiness.verify(
                candidate_id=candidate_id,
                candidate=candidate,
                lease=lease,
                demand=demand,
                authority=store_authority,
                now=now,
            )
        except Exception as exc:
            raise BudgetDenied("INTAKE_READINESS_UNVERIFIED") from exc
        if ready is not True:
            raise BudgetDenied("INTAKE_READINESS_UNVERIFIED")
        return storage

    async def intake(
        self,
        *,
        candidate_id: UUID,
        candidate: SourceCandidate,
        lease: IntakeLease,
        demand: LearningMaterialDemand,
        probe: AccessRequest,
        store: AccessRequest,
        capture_kind: CaptureKind,
        prefix_bytes: int = 0,
        gates: AutonomousGates,
        authority_resolver: AuthorityResolver,
        storage_resolver: StorageGrantResolver,
        attribution: Attribution | None = None,
        cancelled: asyncio.Event | None = None,
    ) -> UUID:
        """Authorize, bounded fetch/parse, then re-authorize and quarantine.

        Offline results retain ``offline_protocol_only``; a live receipt requires
        the concrete pinned connector, per-hop policy and signed attestor.
        """
        if self.offline_protocol_test:
            if not self.fetcher.offline_protocol_test or not self.staging.offline_protocol_test:
                raise BudgetDenied("INTAKE_MODE_MISMATCH")
        else:
            # Import locally: the worker composition owns the concrete, current
            # authority and imports this service at module load time.
            from .worker_composition import _CurrentIntakeAuthority

            hop = self.fetcher.hop_policy
            if (type(authority_resolver) is not _CurrentIntakeAuthority
                    or authority_resolver.connection is not None
                    or type(self.fetcher) is not SafeFetcher or not self.fetcher.live_ready
                    or type(self.staging) is not CandidateStagingRepository
                    or self.staging.offline_protocol_test
                    or self.staging.live_fetcher is not self.fetcher
                    or type(self.readiness) is not PostgresIntakeReadiness
                    or type(hop) is not CandidateHopPolicy
                    or type(hop.policy_repository) is not FreshCandidatePolicy
                    or storage_resolver is not hop.policy_repository
                    or hop.candidate != candidate or hop.request != probe
                    or hop.gates != gates or hop.authority_resolver is not authority_resolver):
                raise BudgetDenied("LIVE_EGRESS_UNVERIFIED")
        try:
            item = revalidate(candidate, SourceCandidate)
            need = revalidate(demand, LearningMaterialDemand)
            probe_request = revalidate(probe, AccessRequest)
            store_request = revalidate(store, AccessRequest)
            if (
                probe_request.action != "probe"
                or store_request.action != "store"
                or probe_request.model_copy(update={"action": "store"}) != store_request
                or item.demand_hash != need.demand_hash
                or item.scope != need.scope
                or item.capture.kind != "none"
                or self.fetcher.limits.expanded_bytes > 1_000_000
                or capture_kind not in ("none", "prefix", "full")
                or type(prefix_bytes) is not int
                or (capture_kind != "prefix" and prefix_bytes != 0)
                or (
                    capture_kind == "prefix"
                    and not 0 < prefix_bytes < self.fetcher.limits.expanded_bytes
                )
            ):
                raise BudgetDenied("INTAKE_SCOPE_INVALID")
        except (TypeError, ValueError) as exc:
            raise BudgetDenied("INTAKE_SCOPE_INVALID") from exc
        planned = (
            0
            if capture_kind == "none"
            else prefix_bytes
            if capture_kind == "prefix"
            else self.fetcher.limits.expanded_bytes
        )
        now = self.clock()
        self._authorize(
            candidate_id=candidate_id,
            candidate=item,
            lease=lease,
            demand=need,
            probe=probe_request,
            store=store_request,
            capture_kind=capture_kind,
            planned_bytes=planned,
            gates=gates,
            authority_resolver=authority_resolver,
            storage_resolver=storage_resolver,
            now=now,
        )
        def current_hop_grant(_url: str) -> bool:
            # Candidate permission, retention grant, root and fenced lease are
            # freshly checked before DNS and again before every pinned dial.
            self._authorize(
                candidate_id=candidate_id, candidate=item, lease=lease, demand=need,
                probe=probe_request, store=store_request, capture_kind=capture_kind,
                planned_bytes=planned, gates=gates, authority_resolver=authority_resolver,
                storage_resolver=storage_resolver, now=self.clock(),
            )
            return True

        fetched = await self.fetcher.fetch(
            item.url, capture_kind=capture_kind, prefix_bytes=prefix_bytes,
            cancelled=cancelled, hop_grant=current_hop_grant,
        )
        now = self.clock()
        current_storage = self._authorize(
            candidate_id=candidate_id,
            candidate=item,
            lease=lease,
            demand=need,
            probe=probe_request,
            store=store_request,
            capture_kind=capture_kind,
            planned_bytes=planned,
            gates=gates,
            authority_resolver=authority_resolver,
            storage_resolver=storage_resolver,
            now=now,
        )
        if attribution is not None and type(attribution) is not Attribution:
            raise BudgetDenied("ATTRIBUTION_INVALID")
        if attribution is not None and attribution.license_id not in (
            None, current_storage.license_id
        ):
            raise BudgetDenied("STORAGE_LICENSE_MISMATCH")
        # The reviewed policy license is distinct from untrusted page claims.
        # Populate the capture from fresh storage authority so a worker without
        # page attribution can stage under an explicitly licensed operator rule.
        prepared: PreparedCapture = prepare_capture(
            item, fetched, capture_kind=capture_kind, prefix_bytes=prefix_bytes,
            attribution=Attribution(
                license_id=current_storage.license_id,
                author_name=attribution.author_name if attribution else None,
                claimed_origin_url=attribution.claimed_origin_url if attribution else None,
            ),
        )
        if cancelled is not None and cancelled.is_set():
            raise BudgetDenied("CANCELLED")
        # stage() repeats current storage, root, receipt and fenced lease checks
        # in its own transaction. Bind the concrete live authority to that SAME
        # connection: a nested fresh connection under row locks can stall behind
        # an operator revocation waiting for the staging transaction to finish.
        commit_authority = authority_resolver
        if not self.offline_protocol_test:
            if type(authority_resolver) is not _CurrentIntakeAuthority:
                raise BudgetDenied("LIVE_AUTHORITY_UNVERIFIED")
            commit_authority = authority_resolver.bind(self.staging.conn)
        now = self.clock()
        return self.staging.stage(
            candidate_id=candidate_id,
            candidate=item,
            prepared=prepared,
            lease=lease,
            request=store_request,
            demand=need,
            gates=gates,
            authority_resolver=commit_authority,
            storage_resolver=storage_resolver,
            now=now,
        )
