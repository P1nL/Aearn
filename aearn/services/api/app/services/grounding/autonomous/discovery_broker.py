"""Internal B1 discovery: search hits are landing leads, never captured text.

B2 must separately probe a landing under current discovery/egress permission,
verify actual document bytes or an exact repository commit/path, and issue a
*new* probe/capture receipt linked to this discovery receipt before constructing
an eligible document/repo_file candidate. Neither a model label nor a Tavily
snippet may upgrade kind. No such B2 promotion is implemented by this broker.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Callable, Literal, Protocol

from pydantic import Field, model_validator

from .candidate_repository import _public_url
from .access_policy import (
    AccessRequest, AuthorityResolver, AutonomousGates, QueryProjectionResolver,
    check_access, issue_discovery_demand,
)
from .contracts import (
    FrozenContract, HANDLE, LearningMaterialDemand, RagBudgetDelegation,
    SourceCandidate, SourceDiscoveryDemand, SourceDiscoverySuggestion, revalidate,
)


class DiscoveryRequest(FrozenContract):
    """Server-provided references, still rechecked against the full demand."""

    demand: LearningMaterialDemand
    suggestion: SourceDiscoverySuggestion
    actor_id: str = Field(pattern=HANDLE)
    policy_id: str = Field(pattern=HANDLE)
    policy_generation: int = Field(ge=1)
    budget: RagBudgetDelegation


class CorpusAssessment(FrozenContract):
    """Trusted adapter's exact-purpose/version/reading-level coverage decision."""

    demand: LearningMaterialDemand
    status: Literal["sufficient", "gap"]
    receipt_id: str = Field(pattern=HANDLE)
    gap_reason: Literal["coverage_gap", "reading_level", "version_stale", "conflict"] | None = None

    @model_validator(mode="after")
    def coherent(self) -> CorpusAssessment:
        if (self.status == "gap") != (self.gap_reason is not None):
            raise ValueError("incoherent corpus assessment")
        return self


class QualifiedCorpusPort(Protocol):
    """Consult current admitted material, never search snippets or staging."""

    def assess(self, demand: LearningMaterialDemand) -> CorpusAssessment | None: ...


class GatesPort(Protocol):
    def current(self) -> AutonomousGates | None: ...


class SearchApprovalPort(Protocol):
    """Separate live network/cost permission; discovery flag alone is insufficient."""

    def permitted(self) -> bool: ...


class WorkClaim(FrozenContract):
    job_id: str = Field(pattern=HANDLE)
    reservation_id: str = Field(pattern=HANDLE)
    lease_owner: str = Field(pattern=HANDLE)
    lease_generation: int = Field(ge=1)


class WorkDecision(FrozenContract):
    status: Literal["claimed", "existing", "denied"]
    job_id: str | None = Field(default=None, pattern=HANDLE)
    claim: WorkClaim | None = None

    @model_validator(mode="after")
    def coherent(self) -> WorkDecision:
        if (self.status == "claimed") != (self.claim is not None):
            raise ValueError("invalid claim decision")
        if (self.status == "existing") != (self.job_id is not None):
            raise ValueError("invalid existing job decision")
        if self.claim is not None and self.job_id is not None:
            raise ValueError("conflicting job identity")
        return self


class AttemptTicket(FrozenContract):
    job_id: str = Field(pattern=HANDLE)
    attempt_id: str = Field(pattern=HANDLE)
    lease_generation: int = Field(ge=1)


class SearchResult(FrozenContract):
    """Provider-normalized result. URLs remain untrusted, never textbook bodies."""

    status: Literal["completed", "account_exhausted", "failed", "uncertain"]
    candidates: tuple[SourceCandidate, ...] = Field(default=(), max_length=5)
    usage_units: int | None = Field(default=None, ge=0)
    usage_receipt_id: str | None = Field(default=None, pattern=HANDLE)
    quota_receipt_id: str | None = Field(default=None, pattern=HANDLE)

    @model_validator(mode="after")
    def coherent(self) -> SearchResult:
        if ((self.usage_units is None) != (self.usage_receipt_id is None)
                or self.status != "completed" and self.candidates
                or self.status == "account_exhausted" and not self.quota_receipt_id
                or self.status != "account_exhausted" and self.quota_receipt_id):
            raise ValueError("incoherent search result")
        return self


class SearchPort(Protocol):
    """Projection and lease reach the bridge; transport receives reviewed terms only."""

    def search(self, demand: SourceDiscoveryDemand, claim: WorkClaim,
               ticket: AttemptTicket) -> SearchResult: ...


class DurableDispatchGate(Protocol):
    """Atomic consume of a persisted, exact-scope attempt before provider I/O.

    Match root/delegation, demand/query, owner/generation and the current live
    gate. A second call, including after restart, must return False. No budget
    reservation occurs here; uncertain dispatched attempts stay charged.
    """

    def take_dispatch(self, demand: SourceDiscoveryDemand, claim: WorkClaim,
                      ticket: AttemptTicket) -> bool: ...


class SearchSettlement(FrozenContract):
    """Candidate-free billing evidence; absent usage receipt means unknown spend."""

    status: Literal["completed", "account_exhausted", "failed", "uncertain"]
    usage_units: int | None = Field(default=None, ge=0)
    usage_receipt_id: str | None = Field(default=None, pattern=HANDLE)
    quota_receipt_id: str | None = Field(default=None, pattern=HANDLE)


class DiscoveryWorkPort(Protocol):
    """Durable, atomic canonical-root budget and shared-job owner.

    claim_or_reuse dedupes only an exact canonical query operation across
    campaign/on-demand callers. Different queries and demand hashes create
    separate jobs but debit the SAME canonical root/period cap. Attempts,
    dispatch, outcomes and candidate commits require owner + generation.
    No transaction spans provider I/O. Unknown usage stays reserved.

    Production mapping: enqueue/claim via DiscoveryJobRepository, reserve once
    via BudgetRepository under the same canonical root/period, then persist an
    attempt. take_dispatch MUST perform a durable first-writer CAS bound to the
    full projection, reservation, live owner/generation and current switch;
    BudgetRepository.record_attempt's existing replay is not a dispatch permit.
    The current schema has no dispatched marker, so this adapter cannot yet be
    truthfully provided without the schema owner's change. record_unknown must
    hold started/dispatched/ambiguous rows even after lease loss; only a genuine
    usage receipt may call settle. Quota classification must be durably recorded
    despite unknown usage before existing_only is returned. CandidateRepository
    may write receipt then landing candidates only after settled usage and a
    fresh authorization check. The pre-attempt reservation is never refunded by
    this broker; a separate authoritative reconciliation owns any safe release.
    """

    def claim_or_reuse(self, demand: LearningMaterialDemand,
                       projection: SourceDiscoveryDemand, operation_id: str) -> WorkDecision: ...

    def prepare_attempt(self, claim: WorkClaim) -> AttemptTicket | None: ...

    def take_dispatch(self, demand: SourceDiscoveryDemand, claim: WorkClaim,
                      ticket: AttemptTicket) -> bool: ...

    def record_outcome(self, claim: WorkClaim, ticket: AttemptTicket,
                       settlement: SearchSettlement,
                       candidates: tuple[SourceCandidate, ...] = ()) -> bool: ...

    def record_unknown(self, claim: WorkClaim, ticket: AttemptTicket | None) -> None: ...


class BrokerResult(FrozenContract):
    status: Literal["closed", "reused_corpus", "existing_job", "discovered", "existing_only"]
    receipt_id: str | None = Field(default=None, pattern=HANDLE)


def _query_operation_id(demand: LearningMaterialDemand, projection: SourceDiscoveryDemand) -> str:
    """Exact-query job identity, NOT the shared root-period spending limit.

    Same demand and reviewed terms share a job across campaign/on-demand. A
    different query/demand receives another job; BudgetRepository must sum all
    reservations for the canonical root and period regardless of this key.
    Hashing hides query terms from the persisted/loggable operation key.
    """
    identity = (
        projection.budget.root_id, projection.budget.delegation_id,
        projection.budget.generation, demand.demand_hash,
        projection.scope.model_dump(mode="json"), demand.purpose,
        demand.reading_level, demand.language, projection.policy_id,
        projection.policy_generation, projection.query_terms,
    )
    return "discovery." + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


class DiscoveryBroker:
    def __init__(
        self, *, authority: AuthorityResolver | None, projection: QueryProjectionResolver | None,
        corpus: QualifiedCorpusPort | None, gates: GatesPort | None,
        approval: SearchApprovalPort | None, work: DiscoveryWorkPort | None,
        search: SearchPort | None, clock: Callable[[], datetime],
    ) -> None:
        self.authority = authority
        self.projection = projection
        self.corpus = corpus
        self.gates = gates
        self.approval = approval
        self.work = work
        self.search = search
        self.clock = clock

    def _authorized(self, request: DiscoveryRequest) -> bool:
        gates = self.gates.current() if self.gates else None
        access = AccessRequest(
            demand_hash=request.demand.demand_hash, scope=request.demand.scope,
            purpose=request.demand.purpose, actor_id=request.actor_id,
            action="discover", policy_id=request.policy_id,
            policy_generation=request.policy_generation, budget=request.budget,
        )
        return check_access(access, gates=gates, resolver=self.authority,
                            now=self.clock(), demand=request.demand).allowed

    def discover(self, incoming: DiscoveryRequest) -> BrokerResult:
        """One attempt; absent or failing adapters close without revealing inputs."""
        closed = BrokerResult(status="closed")
        claim: WorkClaim | None = None
        ticket: AttemptTicket | None = None
        recorded = False
        try:
            request = revalidate(incoming, DiscoveryRequest)
            if not self._authorized(request) or self.corpus is None:
                return closed
            assessment = self.corpus.assess(request.demand)
            if assessment is None:
                return closed
            checked = revalidate(assessment, CorpusAssessment)
            if checked.demand != request.demand:
                return closed
            if checked.status == "sufficient":
                return BrokerResult(status="reused_corpus", receipt_id=checked.receipt_id)
            if (checked.gap_reason != request.suggestion.reason or self.approval is None
                    or not self.approval.permitted() or self.work is None or self.search is None):
                return closed
            projected = issue_discovery_demand(
                request.demand, request.suggestion, actor_id=request.actor_id,
                policy_id=request.policy_id, policy_generation=request.policy_generation,
                budget=request.budget, gates=self.gates.current() if self.gates else None,
                resolver=self.authority, projection=self.projection, now=self.clock(),
            )
            if projected is None:
                return closed
            decision = revalidate(self.work.claim_or_reuse(
                request.demand, projected, _query_operation_id(request.demand, projected),
            ), WorkDecision)
            if decision.status == "existing":
                return BrokerResult(status="existing_job", receipt_id=decision.job_id)
            if decision.status != "claimed" or decision.claim is None:
                return closed
            claim = decision.claim
            if not self._authorized(request) or not self.approval.permitted():
                return closed
            ticket = self.work.prepare_attempt(claim)
            if ticket is None:
                return closed
            ticket = revalidate(ticket, AttemptTicket)
            if ticket.job_id != claim.job_id or ticket.lease_generation != claim.lease_generation:
                return closed
            if not self._authorized(request) or not self.approval.permitted():
                return closed
            # The bridge must consume a durable dispatch gate before provider I/O.
            # From persisted attempt onward, any failure holds unknown usage.
            result = revalidate(self.search.search(projected, claim, ticket), SearchResult)
            settlement = SearchSettlement(
                status=result.status, usage_units=result.usage_units,
                usage_receipt_id=result.usage_receipt_id,
                quota_receipt_id=result.quota_receipt_id,
            )
            # The work adapter owns settlement, candidate commit and job terminal
            # transition in one transaction. Invalid/empty leads settle as failed.
            # Billing persists even if permission vanished during I/O, but
            # the now-revoked actor cannot submit new candidate facts.
            candidate_allowed = self._authorized(request) and self.approval.permitted()
            candidates = tuple(result.candidates) if result.status == "completed" and candidate_allowed else ()
            if candidates:
                try:
                    if any(item.demand_hash != request.demand.demand_hash
                           or item.scope != request.demand.scope or item.kind != "landing"
                           or item.capture.kind != "none"
                           or item.discovery_receipt_id != ticket.attempt_id for item in candidates):
                        candidates = ()
                    else:
                        for item in candidates:
                            _public_url(item.url)
                except (ValueError, TypeError):
                    candidates = ()
            if not self.work.record_outcome(claim, ticket, settlement, candidates):
                return closed
            recorded = True
            if not self._authorized(request) or not self.approval.permitted():
                return closed
            if result.status == "account_exhausted":
                return BrokerResult(status="existing_only", receipt_id=result.quota_receipt_id)
            if result.status != "completed" or result.usage_receipt_id is None or not candidates:
                return closed
            return BrokerResult(status="discovered", receipt_id=claim.job_id)
        except Exception:
            return closed
        finally:
            if self.work is not None and claim is not None and not recorded:
                try:
                    # Never refund from process-local called=False. A crash after
                    # persisting the attempt is ambiguous; the adapter holds the
                    # reservation and reconciles it from durable state.
                    self.work.record_unknown(claim, ticket)
                except Exception:
                    # The reservation remains held; recovery must scan it.
                    pass


class _PreparedAdmission:
    """One-shot SearchAdmission for an ALREADY reserved and persisted attempt.

    It does not call the budget again. This local one-shot guard is NOT replay
    authority: the bridge already required WorkPort.take_dispatch's durable CAS.
    """

    def __init__(self, demand: SourceDiscoveryDemand, ticket: AttemptTicket) -> None:
        self._demand = demand
        self._ticket = ticket
        self._used = False

    def authorize_and_reserve(self, demand: SourceDiscoveryDemand):
        from .search_port import SearchPermit

        if self._used or revalidate(demand, SourceDiscoveryDemand) != self._demand:
            return None
        self._used = True
        return SearchPermit(self._demand, self._ticket.attempt_id)


class PreparedTavilySearchBridge:
    """Bind a durable dispatched attempt to one credentialed observation source.

    Without the shared TavilyUsageAuthority, production cannot call the provider
    or mint billing/quota evidence. The explicit offline protocol mode exercises
    fake adapter shape only; it cannot settle usage or certify exhaustion.
    """

    def __init__(self, *, transport=None, dispatch: DurableDispatchGate | None,
                 usage_authority=None, enabled: bool = False,
                 offline_protocol_test: bool = False) -> None:
        from .tavily_search import HttpxTavilyTransport
        from .tavily_usage_authority import TavilyUsageAuthority

        if usage_authority is not None and type(usage_authority) is not TavilyUsageAuthority:
            raise ValueError("invalid usage authority")
        if usage_authority is not None and (transport is not None or offline_protocol_test):
            raise ValueError("ambiguous Tavily bridge wiring")
        if offline_protocol_test and (transport is None or type(transport) is HttpxTavilyTransport):
            raise ValueError("offline protocol mode requires fake transport")
        self._transport = transport
        self._dispatch = dispatch
        self._usage_authority = usage_authority
        self._enabled = enabled
        self._offline_protocol_test = offline_protocol_test

    def search(self, demand: SourceDiscoveryDemand, claim: WorkClaim,
               ticket: AttemptTicket) -> SearchResult:
        from .tavily_search import TavilySearchAdapter

        checked = revalidate(demand, SourceDiscoveryDemand)
        owner = revalidate(claim, WorkClaim)
        issued = revalidate(ticket, AttemptTicket)
        if (not self._enabled or self._dispatch is None
                or (self._usage_authority is None and not self._offline_protocol_test)
                or issued.job_id != owner.job_id
                or issued.lease_generation != owner.lease_generation):
            return SearchResult(status="uncertain")
        try:
            if not self._dispatch.take_dispatch(checked, owner, issued):
                return SearchResult(status="uncertain")
            # A failed bind after the durable CAS is unknown, never a retry or
            # process-local refund. The authority owns its credentialed transport.
            transport = (self._usage_authority.for_attempt(issued.attempt_id)
                         if self._usage_authority is not None else self._transport)
        except Exception:
            return SearchResult(status="uncertain")
        outcome = TavilySearchAdapter(
            admission=_PreparedAdmission(checked, issued),
            transport=transport, enabled=self._enabled,
        ).search(checked)
        receipt = outcome.receipt
        if receipt is not None and receipt.attempt_id != issued.attempt_id:
            return SearchResult(status="uncertain")
        if outcome.status == "quota_exhausted" and receipt is not None:
            quota_id = (self._usage_authority.quota_receipt(issued.attempt_id)
                        if self._usage_authority is not None else None)
            if quota_id is None:
                return SearchResult(status="uncertain")
            return SearchResult(status="account_exhausted", quota_receipt_id=quota_id)
        if outcome.status == "invalid_response":
            return SearchResult(status="uncertain")
        usage: int | None = None
        usage_id: str | None = None
        if (self._usage_authority is not None and receipt is not None
                and receipt.provider_request_id is not None and receipt.credits is not None):
            usage_id = self._usage_authority.usage_receipt(
                issued.attempt_id, receipt.provider_request_id, receipt.credits,
            )
            if usage_id is not None:
                usage = receipt.credits
        if outcome.status == "ok":
            return SearchResult(status="completed", candidates=outcome.candidates,
                                usage_units=usage, usage_receipt_id=usage_id)
        return SearchResult(status="failed" if receipt is not None else "uncertain",
                            usage_units=usage, usage_receipt_id=usage_id)