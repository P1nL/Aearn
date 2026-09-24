"""Read-only authority port and deterministic, default-deny actor/action/budget checks.

A does not implement resolver authenticity, atomic budget reservation or network egress.
"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import Field

from .contracts import (
    Action, FrozenContract, HASH, HANDLE, LearningMaterialDemand, Usage,
    RagBudgetDelegation, SourceCandidate, SourceDiscoveryDemand, SourceDiscoverySuggestion,
    SubjectScope, revalidate,
)


class AutonomousGates(FrozenContract):
    discovery: bool = False
    intake: bool = False
    activation: bool = False
    evidence_consumer: bool = False


class AccessRequest(FrozenContract):
    demand_hash: str = Field(pattern=HASH)
    scope: SubjectScope
    purpose: Usage
    actor_id: str = Field(pattern=HANDLE)
    action: Action
    policy_id: str = Field(pattern=HANDLE)
    policy_generation: int = Field(ge=1)
    budget: RagBudgetDelegation


class AuthoritySnapshot(FrozenContract):
    """Resolver-owned snapshot, never constructed from model suggestions or a matching hash."""
    demand: LearningMaterialDemand
    demand_hash: str = Field(pattern=HASH)
    scope: SubjectScope
    purpose: Usage
    actor_id: str = Field(pattern=HANDLE)
    allowed_actions: tuple[Action, ...] = Field(max_length=5)
    policy_id: str = Field(pattern=HANDLE)
    policy_generation: int = Field(ge=1)
    budget: RagBudgetDelegation
    budget_active: bool
    authorized: bool


class AuthorityResolver(Protocol):
    def resolve(self, request: AccessRequest) -> AuthoritySnapshot | None: ...


class QueryProjectionResolver(Protocol):
    """Trusted server reviewer; filtering alone does not de-identify model text."""
    def project(self, demand: LearningMaterialDemand, suggestion: SourceDiscoverySuggestion) -> tuple[str, ...] | None: ...


class AccessDecision(FrozenContract):
    allowed: bool
    reason: str


def _closed(reason: str) -> AccessDecision:
    return AccessDecision(allowed=False, reason=reason)


def check_access(
    request: AccessRequest, *, gates: AutonomousGates | None,
    resolver: AuthorityResolver | None, now: datetime,
    demand: LearningMaterialDemand | None = None,
) -> AccessDecision:
    """Gate first (zero resolver calls), then recheck canonical trusted state."""
    try:
        req = AccessRequest.model_validate(request.model_dump(mode="python"))
        enabled = AutonomousGates.model_validate(gates.model_dump(mode="python")) if gates else None
        if enabled is None or not {
            "discover": enabled.discovery, "probe": enabled.discovery,
            "store": enabled.intake, "activate": enabled.activation,
            "consume": enabled.evidence_consumer,
        }[req.action]:
            return _closed("GATE_CLOSED")
        if resolver is None:
            return _closed("AUTHORITY_MISSING")
        found = resolver.resolve(req)
        if found is None:
            return _closed("AUTHORITY_MISSING")
        snapshot = AuthoritySnapshot.model_validate(found.model_dump(mode="python"))
        if (not snapshot.authorized or req.actor_id != snapshot.actor_id
                or req.action not in snapshot.allowed_actions
                or len(set(snapshot.allowed_actions)) != len(snapshot.allowed_actions)):
            return _closed("ACTOR_ACTION_DENIED")
        if (req.demand_hash != snapshot.demand_hash or req.scope != snapshot.scope
                or req.purpose != snapshot.purpose
                or req.demand_hash != snapshot.demand.demand_hash
                or req.scope != snapshot.demand.scope
                or req.purpose != snapshot.demand.purpose
                or req.policy_id != snapshot.policy_id
                or req.policy_generation != snapshot.policy_generation
                or (demand is not None and revalidate(demand, LearningMaterialDemand) != snapshot.demand)):
            return _closed("POLICY_SCOPE_STALE")
        if (req.budget != snapshot.budget or not snapshot.budget_active
                or now.tzinfo is None or snapshot.budget.expires_at.tzinfo is None
                or now >= snapshot.budget.expires_at):
            return _closed("BUDGET_UNAVAILABLE")
        return AccessDecision(allowed=True, reason="AUTHORIZED_REFERENCE")
    except Exception:  # resolver failure must never authorize
        return _closed("INVALID_CONTRACT")


def issue_discovery_demand(
    demand: LearningMaterialDemand, suggestion: SourceDiscoverySuggestion, *,
    actor_id: str, policy_id: str, policy_generation: int,
    budget: RagBudgetDelegation, gates: AutonomousGates | None,
    resolver: AuthorityResolver | None, projection: QueryProjectionResolver | None, now: datetime,
) -> SourceDiscoveryDemand | None:
    """Server-only projection; no model field can supply an actor/root/balance."""
    try:
        valid_demand = revalidate(demand, LearningMaterialDemand)
        valid_suggestion = revalidate(suggestion, SourceDiscoverySuggestion)
        valid_budget = revalidate(budget, RagBudgetDelegation)
        if valid_suggestion.demand_hash != valid_demand.demand_hash:
            return None
        request = AccessRequest(
            demand_hash=valid_demand.demand_hash, scope=valid_demand.scope,
            purpose=valid_demand.purpose, actor_id=actor_id, action="discover", policy_id=policy_id,
            policy_generation=policy_generation, budget=valid_budget,
        )
        # The hash is a lookup key, not proof of the full demand fields.
        if not check_access(request, gates=gates, resolver=resolver, now=now, demand=valid_demand).allowed:
            return None
        if projection is None:
            return None
        reviewed_terms = projection.project(valid_demand, valid_suggestion)
        if reviewed_terms is None:
            return None
        return SourceDiscoveryDemand(
            demand_hash=request.demand_hash, scope=request.scope,
            query_terms=reviewed_terms, actor_id=request.actor_id,
            policy_id=request.policy_id, policy_generation=request.policy_generation,
            budget=request.budget,
        )
    except Exception:  # projection or resolver failure is closed
        return None


def check_candidate_access(
    candidate: SourceCandidate, request: AccessRequest, *,
    gates: AutonomousGates | None, resolver: AuthorityResolver | None, now: datetime,
) -> AccessDecision:
    """Candidate URL is metadata for a future broker, never fetched here."""
    try:
        valid_candidate = revalidate(candidate, SourceCandidate)
        valid_request = AccessRequest.model_validate(request.model_dump(mode="python"))
        if (valid_candidate.demand_hash != valid_request.demand_hash
                or valid_candidate.scope != valid_request.scope):
            return _closed("CANDIDATE_DEMAND_MISMATCH")
        if valid_request.action not in {"probe", "store"}:
            return _closed("CANDIDATE_ACTION_DENIED")
        return check_access(valid_request, gates=gates, resolver=resolver, now=now)
    except Exception:  # malformed candidate or resolver output is closed
        return _closed("INVALID_CONTRACT")