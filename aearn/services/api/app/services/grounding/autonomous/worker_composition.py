"""Default-closed API composition for explicit RAG worker wakeups.

A queue UUID is a selector, never permission. A reviewed operator deployment must
install the server-owned configuration factory; no env-only live enablement.
"""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Protocol
from uuid import UUID

from psycopg import Connection

from .access_policy import AccessRequest, AuthorityResolver, AutonomousGates
from .budget import PostgresBudgetPolicyResolver, current_authority
from .campaign_authority import (
    PostgresCampaignAuthority,
    PostgresCampaignContextResolver,
    campaign_projection,
)
from .context_repository import (
    DiscoveryContextRepository,
    PostgresDiscoveryContextResolver,
    UserActorBindingResolver,
)
from .discovery_broker import (
    PreparedTavilySearchBridge,
    QualifiedCorpusPort,
    SearchSettlement,
    WorkClaim,
    _query_operation_id,
)
from .discovery_work import PostgresDiscoveryWork, WorkContext
from .contracts import ContentCapture, SourceCandidate
from .hop_policy import CandidateHopPolicy
from .intake_leases import PostgresIntakeLeaseRepository
from .intake_service import FreshCandidatePolicy, IntakeService, PostgresIntakeReadiness
from .live_egress import LiveEgressAttestor
from .pinned_tls_connector import PinnedTlsConnector
from .public_dns import PublicDnsResolver
from .retention import CaptureKind
from .safe_fetch import FetchLimits, SafeFetcher
from .qualified_corpus import QualificationAuthority, QualifiedCorpusAdapter
from .staging import CandidateStagingRepository
from .tavily_search import HttpxTavilyTransport
from .tavily_usage_authority import TavilyUsageAuthority


class _Permission(Protocol):
    def permitted(self) -> bool: ...


@dataclass(frozen=True)
class OperatorWorkerConfig:
    """Trusted server factories; never serialized or supplied by a task caller.

    Cost and network ports must each consult independent current approval state.
    Qualification is C's current authority, not B staging or a fixture.
    """

    connect: Callable[[], Connection[dict[str, Any]]]
    private_authority: Callable[[Connection[dict[str, Any]]], AuthorityResolver | None]
    actor_binding: Callable[
        [Connection[dict[str, Any]]], UserActorBindingResolver | None
    ]
    qualification: Callable[[Connection[dict[str, Any]]], QualificationAuthority | None]
    cost_approval: Callable[[Connection[dict[str, Any]]], _Permission | None]
    network_approval: Callable[[Connection[dict[str, Any]]], _Permission | None]
    tavily_key: str
    owner_id: str
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    # Expiration cleanup remains a privacy obligation when intake is disabled.
    # Only a reviewed operator may supply the independent approval authority.
    retention_approval: (
        Callable[[Connection[dict[str, Any]]], _Permission | None] | None
    ) = None
    # B2 requires separate reviewed storage and deployment-owned signed egress.
    # Neither an environment gate nor a queue UUID may supply these capabilities.
    storage_approval: (
        Callable[[Connection[dict[str, Any]]], _Permission | None] | None
    ) = None
    intake_attestor: Callable[[], LiveEgressAttestor | None] | None = None
    intake_capture: CaptureKind | None = None
    intake_prefix_bytes: int = 0


def _load_operator_config() -> OperatorWorkerConfig | None:
    """Operator-owned integration point; no .env, credential or approval fallback."""
    return None


def _gates() -> AutonomousGates:
    # Importing app.core.config would load .env. Re-read each gate at each boundary.
    def enabled(name: str) -> bool:
        return os.environ.get(name, "").lower() in {"true", "1", "yes"}

    return AutonomousGates(
        discovery=enabled("RAG_SOURCE_DISCOVERY_ENABLED"),
        intake=enabled("RAG_AUTO_INTAKE_ENABLED"),
        activation=enabled("RAG_AUTO_ACTIVATION_ENABLED"),
        evidence_consumer=enabled("RAG_EVIDENCE_CONSUMER_ENABLED"),
    )


class _JointApproval:
    def __init__(self, cost: _Permission | None, network: _Permission | None) -> None:
        self.cost, self.network = cost, network

    def permitted(self) -> bool:
        try:
            return (
                self.cost is not None
                and self.network is not None
                and self.cost.permitted() is True
                and self.network.permitted() is True
            )
        except Exception:
            return False


def _blocked() -> dict[str, object]:
    return {"status": "blocked_policy", "processed": 0}


def _select_context(
    conn: Connection[dict[str, Any]],
    job_id: UUID,
    private_authority: AuthorityResolver | None,
    binding: UserActorBindingResolver | None,
    clock: Callable[[], datetime],
) -> tuple[WorkContext, Any, AuthorityResolver] | None:
    campaign = PostgresCampaignAuthority(conn, clock=clock)
    campaign_context = PostgresCampaignContextResolver(
        conn,
        authority=campaign,
        gates=_gates,
        projection=campaign_projection(campaign),
    )
    private_context = PostgresDiscoveryContextResolver(
        DiscoveryContextRepository(conn),
        authority=private_authority,
        binding=binding,
        gates=_gates,
        clock=clock,
    )
    # Both paths resolve persisted full-demand issuance with current authority.
    # A canonical job may have both campaign and private refs; a deterministic
    # current owner may dispatch it, never a stale/hash-only owner.
    with conn.transaction():
        issued_campaign = campaign_context.resolve_job(job_id)
        issued_private = private_context.resolve_job(job_id)
    if issued_campaign is None and issued_private is None:
        return None
    if issued_campaign is not None and issued_private is not None:
        if _query_operation_id(
            issued_campaign.demand, issued_campaign.projection
        ) != _query_operation_id(issued_private.demand, issued_private.projection):
            return None
    if issued_campaign is not None:
        return issued_campaign, campaign_context, campaign
    if private_authority is None or issued_private is None:
        return None
    return issued_private, private_context, private_authority


def _dispatch(job_id: UUID, config: OperatorWorkerConfig) -> dict[str, object]:
    if not config.tavily_key or not config.owner_id or not _gates().discovery:
        return _blocked()
    with config.connect() as conn:
        if conn.autocommit:
            return _blocked()
        approval = _JointApproval(
            config.cost_approval(conn), config.network_approval(conn)
        )
        if not approval.permitted():
            return _blocked()
        corpus: QualifiedCorpusPort = QualifiedCorpusAdapter(config.qualification(conn))
        selected = _select_context(
            conn,
            job_id,
            config.private_authority(conn),
            config.actor_binding(conn),
            config.clock,
        )
        if selected is None:
            return _blocked()
        context, resolver, authority = selected
        assessed = corpus.assess(context.demand)
        if assessed is None:
            return _blocked()
        if assessed.status == "sufficient":
            return {"status": "no_work", "processed": 0}
        if not approval.permitted() or not _gates().discovery:
            return _blocked()
        # The SAME observation authority settles the exact attempt in work.
        usage = TavilyUsageAuthority(
            HttpxTavilyTransport(api_key=config.tavily_key, enabled=True)
        )
        work = PostgresDiscoveryWork(
            conn=conn,
            authority=authority,
            context=resolver,
            policy=PostgresBudgetPolicyResolver(conn),
            gates=_gates,
            permission=approval,
            usage=usage,
            owner_id=config.owner_id,
            clock=config.clock,
        )
        decision = work.claim_or_reuse(
            context.demand,
            context.projection,
            _query_operation_id(context.demand, context.projection),
        )
        if decision.status == "existing":
            return (
                {"status": "no_work", "processed": 0}
                if decision.job_id == f"job.{job_id.hex}"
                else _blocked()
            )
        if (
            decision.status != "claimed"
            or decision.claim is None
            or decision.claim.job_id != f"job.{job_id.hex}"
        ):
            return _blocked()
        claim: WorkClaim = decision.claim
        ticket = None
        recorded = False
        try:
            if corpus.assess(context.demand) != assessed or not approval.permitted():
                return _blocked()
            ticket = work.prepare_attempt(claim)
            if ticket is None or not _gates().discovery:
                return _blocked()
            bridge = PreparedTavilySearchBridge(
                dispatch=work,
                usage_authority=usage,
                enabled=True,
            )
            # The bridge calls work.take_dispatch: persistent CAS commits before
            # the one-shot transport can issue its external request.
            result = bridge.search(context.projection, claim, ticket)
            settlement = SearchSettlement(
                status=result.status,
                usage_units=result.usage_units,
                usage_receipt_id=result.usage_receipt_id,
                quota_receipt_id=result.quota_receipt_id,
            )
            current = corpus.assess(context.demand)
            candidates = (
                result.candidates
                if current is not None
                and current.status == "gap"
                and approval.permitted()
                and _gates().discovery
                else ()
            )
            if not work.record_outcome(claim, ticket, settlement, candidates):
                return _blocked()
            recorded = True
            if not approval.permitted() or not _gates().discovery:
                return _blocked()
            if result.status == "account_exhausted":
                return {"status": "no_work", "processed": 1}
            if result.status != "completed" or not candidates:
                return _blocked()
            return {"status": "completed", "processed": 1}
        finally:
            if not recorded:
                work.record_unknown(claim, ticket)


class _CurrentIntakeAuthority:
    """Reopen current A authority and independent operator approvals per check.

    The initial selector connection is never kept alive over network I/O. A
    withdrawn actor, changed full demand, or changed policy cannot be replaced
    with a matching hash or a cached approval during a redirect/staging commit.
    """

    def __init__(
        self, config: OperatorWorkerConfig, job_id: UUID, context: WorkContext,
        *, connection: Connection[dict[str, Any]] | None = None,
    ) -> None:
        self.config, self.job_id, self.context = config, job_id, context
        self.connection = connection

    def bind(self, connection: Connection[dict[str, Any]]) -> _CurrentIntakeAuthority:
        """Use the staging transaction for commit checks, not a nested connection.

        Opening a fresh connection while holding candidate/root row locks can
        hang behind a queued revocation UPDATE that itself awaits those locks.
        """
        return _CurrentIntakeAuthority(
            self.config, self.job_id, self.context, connection=connection,
        )

    def resolve(self, request: AccessRequest):
        if (
            not _gates().discovery
            or not _gates().intake
            or self.config.storage_approval is None
        ):
            return None
        try:
            with (nullcontext(self.connection) if self.connection is not None
                  else self.config.connect()) as conn:
                if conn.autocommit:
                    return None
                approvals = (
                    self.config.cost_approval(conn),
                    self.config.network_approval(conn),
                    self.config.storage_approval(conn),
                )
                if any(
                    value is None or value.permitted() is not True
                    for value in approvals
                ):
                    return None
                selected = _select_context(
                    conn,
                    self.job_id,
                    self.config.private_authority(conn),
                    self.config.actor_binding(conn),
                    self.config.clock,
                )
                if selected is None or selected[0] != self.context:
                    return None
                return selected[2].resolve(request)
        except Exception:
            return None


def _intake(candidate_id: UUID, config: OperatorWorkerConfig) -> dict[str, object]:
    """Fenced B2 only: resolve current full demand and settled B1 receipt first."""
    gates = _gates()
    if (
        not gates.discovery
        or not gates.intake
        or not config.owner_id
        or config.storage_approval is None
        or config.intake_attestor is None
        or config.intake_capture not in ("none", "prefix", "full")
        or type(config.intake_prefix_bytes) is not int
        or (
            config.intake_capture == "prefix"
            and not 0 < config.intake_prefix_bytes < 1_000_000
        )
        or (config.intake_capture != "prefix" and config.intake_prefix_bytes != 0)
    ):
        return _blocked()
    attestor = config.intake_attestor()
    if type(attestor) is not LiveEgressAttestor:
        return _blocked()
    capture_kind = config.intake_capture
    assert capture_kind is not None
    planned = (
        0
        if capture_kind == "none"
        else config.intake_prefix_bytes
        if capture_kind == "prefix"
        else 1_000_000
    )
    with config.connect() as conn:
        if conn.autocommit:
            return _blocked()
        # This is a lookup, not a caller-supplied DTO. Claim independently checks
        # settled attempt/reservation, job scope and exact candidate/receipt again.
        row = conn.execute(
            "SELECT c.*,r.receipt_handle,j.id AS exact_job_id "
            "FROM rag_discovery_candidates c "
            "JOIN rag_discovery_jobs j ON j.id=c.job_id "
            "JOIN rag_discovery_receipts r ON r.id=c.discovery_receipt_id AND r.job_id=j.id "
            "WHERE c.id=%s",
            (candidate_id,),
        ).fetchone()
        if row is None or row["exact_job_id"] != row["job_id"]:
            return _blocked()
        job_id = row["job_id"]
        selected = _select_context(
            conn,
            job_id,
            config.private_authority(conn),
            config.actor_binding(conn),
            config.clock,
        )
        if selected is None:
            return _blocked()
        context = selected[0]
        if (
            row["demand_hash"],
            row["subject_id"],
            row["subject_version"],
            row["canonical_url_hash"],
        ) != (
            context.demand.demand_hash,
            context.demand.scope.subject_id,
            context.demand.scope.subject_version,
            hashlib.sha256(row["canonical_url"].encode()).hexdigest(),
        ):
            return _blocked()
        candidate = SourceCandidate(
            kind=row["kind"],
            demand_hash=context.demand.demand_hash,
            scope=context.demand.scope,
            url=row["canonical_url"],
            discovery_receipt_id=row["receipt_handle"],
            repo_commit=row["repo_commit"],
            repo_path=row["repo_path"],
            capture=ContentCapture(kind="none", captured_bytes=0),
        )
        issued = context.projection
        probe = AccessRequest(
            demand_hash=context.demand.demand_hash,
            scope=context.demand.scope,
            purpose=context.demand.purpose,
            actor_id=issued.actor_id,
            action="probe",
            policy_id=issued.policy_id,
            policy_generation=issued.policy_generation,
            budget=issued.budget,
        )
        store = probe.model_copy(update={"action": "store"})
        authority = _CurrentIntakeAuthority(config, job_id, context)
        # The selector connection already owns job/context locks. A fresh nested
        # resolver connection can queue behind a revocation waiting for those
        # locks; bind both pre-claim and claim rechecks to this transaction.
        claim_authority = authority.bind(conn)
        now = config.clock()
        current_authority(
            request=probe,
            demand=context.demand,
            gates=gates,
            resolver=claim_authority,
            now=now,
        )
        current_authority(
            request=store,
            demand=context.demand,
            gates=gates,
            resolver=claim_authority,
            now=now,
        )
        leases = PostgresIntakeLeaseRepository(conn)
        # A crash after stage but before finish must never refetch, even when
        # the body was subsequently cleared by retention.
        if leases.reconcile_captured(candidate_id=candidate_id):
            return {"status": "no_work", "processed": 0}
        lease = leases.claim(
            candidate_id=candidate_id,
            candidate=candidate,
            probe=probe,
            store=store,
            demand=context.demand,
            gates=gates,
            authority_resolver=claim_authority,
            capture_kind=capture_kind,
            planned_bytes=planned,
            owner_id=config.owner_id,
        )
        if lease is None:
            return _blocked()
    # The claim connection has committed/closed. The staging connection has no
    # transaction until stage(); all per-hop checks use fresh short connections.
    completed = False
    try:
        policy = FreshCandidatePolicy(config.connect)
        hop = CandidateHopPolicy(
            candidate=candidate,
            request=probe,
            gates=gates,
            authority_resolver=authority,
            policy_repository=policy,
            now_factory=config.clock,
        )
        fetcher = SafeFetcher(
            resolver=PublicDnsResolver(),
            connector=PinnedTlsConnector(),
            egress=attestor,
            hop_policy=hop,
            limits=FetchLimits(expanded_bytes=1_000_000),
        )
        if not fetcher.live_ready:
            return _blocked()
        with config.connect() as stage_conn:
            if stage_conn.autocommit:
                return _blocked()
            service = IntakeService(
                fetcher=fetcher,
                staging=CandidateStagingRepository(stage_conn, live_fetcher=fetcher),
                readiness=PostgresIntakeReadiness(config.connect),
                clock=config.clock,
            )
            asyncio.run(
                service.intake(
                    candidate_id=candidate_id,
                    candidate=candidate,
                    lease=lease,
                    demand=context.demand,
                    probe=probe,
                    store=store,
                    capture_kind=capture_kind,
                    prefix_bytes=config.intake_prefix_bytes,
                    gates=gates,
                    authority_resolver=authority,
                    storage_resolver=policy,
                )
            )
        with config.connect() as finish_conn:
            if finish_conn.autocommit:
                return _blocked()
            PostgresIntakeLeaseRepository(finish_conn).finish(lease=lease, success=True)
        completed = True
        return {"status": "completed", "processed": 1}
    finally:
        if not completed:
            # A failed/expired release cannot authorize a second fetch. A retry
            # reconciles an already persisted capture before it can claim.
            try:
                with config.connect() as release_conn:
                    if not release_conn.autocommit:
                        PostgresIntakeLeaseRepository(release_conn).release(lease=lease)
            except Exception:
                pass


def _retention(limit: int, config: OperatorWorkerConfig) -> dict[str, object]:
    """Clear expired content using the DB clock; never unlink actor references.

    Cleanup must remain available when intake is off. Neither a queue argument
    nor an environment flag can supply the operator's retention approval.
    """
    if config.retention_approval is None:
        return _blocked()
    with config.connect() as conn:
        if conn.autocommit:
            return _blocked()
        approval = config.retention_approval(conn)
        if approval is None or approval.permitted() is not True:
            return _blocked()
        # Current policy is checked immediately before the short DB transaction.
        if approval.permitted() is not True:
            return _blocked()
        cleared = CandidateStagingRepository(conn).clear_expired(limit=limit)
        return {"status": "completed", "processed": cleared}


def run_rag_worker_operation(
    *,
    operation: object,
    job_id: object = None,
    candidate_id: object = None,
    limit: object = None,
) -> dict[str, object]:
    """Selector-only worker entrypoint; B2 intake is not a B1 alias."""
    try:
        if operation == "dispatch":
            if (
                not isinstance(job_id, str)
                or candidate_id is not None
                or limit is not None
                or str(UUID(job_id)) != job_id
                or not _gates().discovery
            ):
                return _blocked()
            config = _load_operator_config()
            if type(config) is not OperatorWorkerConfig:
                return _blocked()
            return _dispatch(UUID(job_id), config)
        if operation == "intake":
            if (
                not isinstance(candidate_id, str)
                or job_id is not None
                or limit is not None
                or str(UUID(candidate_id)) != candidate_id
            ):
                return _blocked()
            if not _gates().discovery or not _gates().intake:
                return _blocked()
            config = _load_operator_config()
            if type(config) is not OperatorWorkerConfig:
                return _blocked()
            return _intake(UUID(candidate_id), config)
        if operation == "retention":
            if (
                type(limit) is not int
                or not 1 <= limit <= 100
                or job_id is not None
                or candidate_id is not None
            ):
                return _blocked()
            config = _load_operator_config()
            if type(config) is not OperatorWorkerConfig:
                return _blocked()
            return _retention(limit, config)
    except Exception:
        # Never return DB/provider/credential/query/candidate text to Celery.
        return _blocked()
    return _blocked()
