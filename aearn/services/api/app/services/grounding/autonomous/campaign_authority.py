"""Operator-owned, default-off campaign authority for the shared B1 broker.

This module has no bootstrap seed, scheduler, route, provider or credential access.
An operator must provision a service principal and immutable campaign definition,
then explicitly enable principal/campaign/period/cost and the canonical root.
The operator's provisioning/enablement path is deliberately not exposed here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Protocol
from uuid import UUID

from psycopg import Connection

from .access_policy import (
    AccessRequest, AuthoritySnapshot, AutonomousGates, QueryProjectionResolver,
    check_access,
)
from .budget import fingerprint, require_transaction
from .contracts import (
    HANDLE, LearningMaterialDemand, RagBudgetDelegation, SourceDiscoveryDemand,
    SourceDiscoverySuggestion, SubjectScope, revalidate,
)
from .discovery_broker import (
    BrokerResult, DiscoveryBroker, DiscoveryRequest, QualifiedCorpusPort,
    _query_operation_id,
)
from .discovery_work import WorkContext
from .jobs import projected_query_hash
from .query_projection import (
    ServerQueryProjectionResolver, TrustedQueryContext,
)


@dataclass(frozen=True)
class CampaignContext:
    campaign_id: str
    operator_id: str
    demand: LearningMaterialDemand
    actor_id: str
    policy_id: str
    policy_generation: int
    budget: RagBudgetDelegation
    intake_approved: bool


def _identity(campaign_id: str) -> str:
    return fingerprint("operator-campaign-v1", campaign_id)


def campaign_demand(
    *, campaign_id: str, revision: int, scope: SubjectScope,
    purpose: str, reading_level: str, language: str,
) -> LearningMaterialDemand:
    """Derive the exact reviewed demand/hash for operator provisioning.

    Invalid scope, purpose, reading level or language fails Pydantic validation;
    this helper does not provision, authorize or enable a campaign.
    """
    return _demand({
        "campaign_id": campaign_id, "revision": revision,
        "subject_id": scope.subject_id, "subject_version": scope.subject_version,
        "facets": scope.facets, "purpose": purpose,
        "reading_level": reading_level, "language": language,
    })


def _demand(row: dict[str, Any]) -> LearningMaterialDemand:
    identity = _identity(row["campaign_id"])
    return LearningMaterialDemand(
        scope=SubjectScope(
            subject_id=row["subject_id"], subject_version=row["subject_version"],
            facets=tuple(row["facets"]),
        ),
        demand_hash=fingerprint(
            "operator-campaign-demand-v1", row["campaign_id"], row["revision"],
            row["subject_id"], row["subject_version"], tuple(row["facets"]),
            row["purpose"], row["reading_level"], row["language"],
        ),
        plan_ref="campaign." + identity,
        node_ref="campaign.node." + identity,
        draft_revision=row["revision"], purpose=row["purpose"],
        reading_level=row["reading_level"], language=row["language"],
    )


class PostgresCampaignAuthority:
    """A AuthorityResolver + trusted query context; never maps to users.id.

    Reads the definition, operator-owned principal and current canonical budget
    on every call. Probe/store also require this exact campaign's current
    intake approval. The caller must provide a transaction-owning connection;
    no cached enabled flag, delegation or query terms authorize later work.
    """

    def __init__(self, conn: Connection[dict[str, Any]], *, clock: Callable[[], datetime]) -> None:
        self.conn, self.clock = conn, clock

    def load(self, campaign_id: str) -> CampaignContext | None:
        if not isinstance(campaign_id, str) or re.fullmatch(HANDLE, campaign_id) is None:
            return None
        with self.conn.transaction():
            row = self.conn.execute(
                "SELECT c.*,p.operator_id,p.enabled AS principal_enabled,"
                "r.delegation_id,r.delegation_generation,r.delegation_expires_at,"
                "r.policy_id AS root_policy_id,r.policy_generation AS root_policy_generation,"
                "r.period_start,r.period_end,r.enabled AS root_enabled "
                "FROM rag_campaign_definitions c "
                "JOIN rag_campaign_principals p ON p.actor_id=c.actor_id "
                "JOIN rag_budget_authority_roots r ON r.root_id=c.root_id "
                "WHERE c.campaign_id=%s FOR SHARE OF c,p,r",
                (campaign_id,),
            ).fetchone()
        if row is None:
            return None
        now = self.clock()
        if (not isinstance(now, datetime) or now.tzinfo is None
                or not all(row[key] is True for key in (
                    "enabled", "principal_enabled", "period_approved", "cost_approved", "root_enabled",
                ))
                or not row["actor_id"].startswith("service.")
                or row["root_policy_id"] != row["policy_id"]
                or row["root_policy_generation"] != row["policy_generation"]
                or not row["period_start"] <= now < row["period_end"]
                or now >= row["delegation_expires_at"]):
            return None
        try:
            demand = _demand(row)
            if demand.demand_hash != row["demand_hash"]:
                return None
            return CampaignContext(
                campaign_id=row["campaign_id"], operator_id=row["operator_id"],
                demand=demand, actor_id=row["actor_id"],
                policy_id=row["policy_id"], policy_generation=row["policy_generation"],
                budget=RagBudgetDelegation(
                    root_id=row["root_id"], delegation_id=row["delegation_id"],
                    generation=row["delegation_generation"], expires_at=row["delegation_expires_at"],
                ),
                intake_approved=row["intake_approved"] is True,
            )
        except (ValueError, TypeError, KeyError):
            return None

    def resolve(self, request: AccessRequest) -> AuthoritySnapshot | None:
        try:
            req = revalidate(request, AccessRequest)
            if req.action not in {"discover", "probe", "store"}:
                return None
            # Hash is a lookup hint only. The entire current demand and scope
            # are rebuilt from the operator definition and compared by A.
            with self.conn.transaction():
                row = self.conn.execute(
                    "SELECT campaign_id FROM rag_campaign_definitions WHERE demand_hash=%s AND actor_id=%s",
                    (req.demand_hash, req.actor_id),
                ).fetchone()
                context = self.load(row["campaign_id"]) if row is not None else None
            if (context is None or req.scope != context.demand.scope
                    or req.purpose != context.demand.purpose
                    or req.policy_id != context.policy_id
                    or req.policy_generation != context.policy_generation
                    or req.budget != context.budget
                    or (req.action in {"probe", "store"} and not context.intake_approved)):
                return None
            return AuthoritySnapshot(
                demand=context.demand, demand_hash=context.demand.demand_hash,
                scope=context.demand.scope, purpose=context.demand.purpose,
                actor_id=context.actor_id, allowed_actions=(req.action,),
                policy_id=context.policy_id, policy_generation=context.policy_generation,
                budget=context.budget, budget_active=True, authorized=True,
            )
        except Exception:
            return None

    def resolve_query(self, demand: LearningMaterialDemand) -> TrustedQueryContext | None:
        try:
            valid = revalidate(demand, LearningMaterialDemand)
            with self.conn.transaction():
                row = self.conn.execute(
                    "SELECT campaign_id FROM rag_campaign_definitions WHERE demand_hash=%s",
                    (valid.demand_hash,),
                ).fetchone()
                context = self.load(row["campaign_id"]) if row is not None else None
            if context is None or context.demand != valid:
                return None
            return TrustedQueryContext(
                demand=valid, approved_facets=valid.scope.facets,
                receipt_id="campaign.review." + _identity(context.campaign_id), authorized=True,
            )
        except Exception:
            return None


class CampaignQueryAuthority:
    def __init__(self, authority: PostgresCampaignAuthority) -> None:
        self.authority = authority

    def resolve(self, demand: LearningMaterialDemand) -> TrustedQueryContext | None:
        return self.authority.resolve_query(demand)


class PostgresCampaignContextResolver:
    """DiscoveryContextResolver for service-owned issuance, not user refs.

    resolve_issued is called *inside* PostgresDiscoveryWork's enqueue/reserve
    transaction. Its append-only context is rolled back if either step fails.
    resolve_job requires a persisted issuance and an exact matching job scope.
    """

    def __init__(
        self, conn: Connection[dict[str, Any]], *, authority: PostgresCampaignAuthority,
        gates: Callable[[], AutonomousGates | None],
        projection: QueryProjectionResolver,
    ) -> None:
        self.conn, self.authority = conn, authority
        self.gates, self.projection = gates, projection

    def _current(self, demand: LearningMaterialDemand, projection: SourceDiscoveryDemand) -> CampaignContext | None:
        row = self.conn.execute(
            "SELECT campaign_id FROM rag_campaign_definitions WHERE demand_hash=%s AND actor_id=%s",
            (demand.demand_hash, projection.actor_id),
        ).fetchone()
        context = self.authority.load(row["campaign_id"]) if row is not None else None
        if context is None or context.demand != demand:
            return None
        access = AccessRequest(
            demand_hash=demand.demand_hash, scope=demand.scope, purpose=demand.purpose,
            actor_id=context.actor_id, action="discover", policy_id=context.policy_id,
            policy_generation=context.policy_generation, budget=context.budget,
        )
        if not check_access(access, gates=self.gates(), resolver=self.authority,
                            now=self.authority.clock(), demand=demand).allowed:
            return None
        # Compare against a fresh server-generated projection, not stored terms
        # or a model-supplied query. The reason is not a source of query terms.
        suggestion = SourceDiscoverySuggestion(
            demand_hash=demand.demand_hash, query_terms=("curriculum",), reason="coverage_gap",
        )
        terms = self.projection.project(demand, suggestion)
        if terms is None or projection != SourceDiscoveryDemand(
            demand_hash=demand.demand_hash, scope=demand.scope, query_terms=terms,
            actor_id=context.actor_id, policy_id=context.policy_id,
            policy_generation=context.policy_generation, budget=context.budget,
        ):
            return None
        return context

    def resolve_issued(self, demand: LearningMaterialDemand,
                       projection: SourceDiscoveryDemand) -> WorkContext | None:
        try:
            full = revalidate(demand, LearningMaterialDemand)
            issued = revalidate(projection, SourceDiscoveryDemand)
            require_transaction(self.conn)
            context = self._current(full, issued)
            if context is None:
                return None
            operation_key = _query_operation_id(full, issued)
            query_hash = projected_query_hash(issued, self.authority.resolve(AccessRequest(
                demand_hash=full.demand_hash, scope=full.scope, purpose=full.purpose,
                actor_id=issued.actor_id, action="discover", policy_id=issued.policy_id,
                policy_generation=issued.policy_generation, budget=issued.budget,
            )), full)
            self.conn.execute(
                "INSERT INTO rag_campaign_issued_contexts "
                "(operation_key,campaign_id,actor_id,demand_hash,subject_id,subject_version,facets,"
                "purpose,reading_level,language,draft_revision,reviewed_terms,query_hash,policy_id,"
                "policy_generation,root_id,delegation_id,delegation_generation) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (operation_key) DO NOTHING",
                (operation_key, context.campaign_id, context.actor_id, full.demand_hash,
                 full.scope.subject_id, full.scope.subject_version, list(full.scope.facets),
                 full.purpose, full.reading_level, full.language, full.draft_revision,
                 list(issued.query_terms), query_hash, issued.policy_id, issued.policy_generation,
                 issued.budget.root_id, issued.budget.delegation_id, issued.budget.generation),
            )
            row = self.conn.execute(
                "SELECT * FROM rag_campaign_issued_contexts WHERE operation_key=%s", (operation_key,),
            ).fetchone()
            if row is None or not self._matches(row, context, issued, query_hash):
                return None
            return WorkContext(full, issued)
        except Exception:
            return None

    @staticmethod
    def _matches(row: dict[str, Any], context: CampaignContext,
                 projection: SourceDiscoveryDemand, query_hash: str) -> bool:
        demand = context.demand
        return (
            row["campaign_id"], row["actor_id"], row["demand_hash"], row["subject_id"],
            row["subject_version"], tuple(row["facets"]), row["purpose"], row["reading_level"],
            row["language"], row["draft_revision"], tuple(row["reviewed_terms"]),
            row["query_hash"], row["policy_id"], row["policy_generation"], row["root_id"],
            row["delegation_id"], row["delegation_generation"],
        ) == (
            context.campaign_id, context.actor_id, demand.demand_hash, demand.scope.subject_id,
            demand.scope.subject_version, demand.scope.facets, demand.purpose, demand.reading_level,
            demand.language, demand.draft_revision, projection.query_terms, query_hash,
            context.policy_id, context.policy_generation, context.budget.root_id,
            context.budget.delegation_id, context.budget.generation,
        )

    def resolve_job(self, job_id: UUID) -> WorkContext | None:
        try:
            if type(job_id) is not UUID:
                return None
            require_transaction(self.conn)
            row = self.conn.execute(
                "SELECT i.*,j.id AS job_id,j.operation_key AS job_operation_key,"
                "j.query_hash AS job_query_hash,j.demand_hash AS job_demand_hash,"
                "j.root_id AS job_root_id,j.policy_generation AS job_policy_generation "
                "FROM rag_discovery_jobs j JOIN rag_campaign_issued_contexts i "
                "ON i.operation_key=j.operation_key "
                "JOIN rag_discovery_job_refs r ON r.job_id=j.id AND r.actor_id=i.actor_id "
                "AND r.demand_hash=i.demand_hash WHERE j.id=%s FOR SHARE OF i,j,r",
                (job_id,),
            ).fetchone()
            context = self.authority.load(row["campaign_id"]) if row is not None else None
            if context is None or row is None:
                return None
            projection = SourceDiscoveryDemand(
                demand_hash=context.demand.demand_hash, scope=context.demand.scope,
                query_terms=tuple(row["reviewed_terms"]), actor_id=context.actor_id,
                policy_id=context.policy_id, policy_generation=context.policy_generation,
                budget=context.budget,
            )
            if (row["job_operation_key"] != _query_operation_id(context.demand, projection)
                    or row["job_query_hash"] != row["query_hash"]
                    or row["job_demand_hash"] != context.demand.demand_hash
                    or row["job_root_id"] != context.budget.root_id
                    or row["job_policy_generation"] != context.policy_generation
                    or not self._matches(row, context, projection, row["query_hash"])):
                return None
            return self.resolve_issued(context.demand, projection)
        except Exception:
            return None


class OperatorInvocationAuthority(Protocol):
    """Trusted caller identity/permission, independent of campaign row ownership."""

    def authorize(self, operator_id: str, campaign_id: str) -> bool: ...


class CampaignDiscoveryService:
    """Explicit operator invocation; shared broker/work/job/budget as on-demand."""

    def __init__(
        self, *, authority: PostgresCampaignAuthority, corpus: QualifiedCorpusPort,
        broker: DiscoveryBroker, invoker: OperatorInvocationAuthority | None,
    ) -> None:
        self.authority, self.corpus, self.broker = authority, corpus, broker
        self.invoker = invoker

    def discover(self, campaign_id: str, *, operator_id: str) -> BrokerResult:
        closed = BrokerResult(status="closed")
        try:
            with self.authority.conn.transaction():
                context = self.authority.load(campaign_id)
                if (context is None or self.invoker is None
                        or operator_id != context.operator_id
                        or self.invoker.authorize(operator_id, campaign_id) is not True):
                    return closed
                assessment = self.corpus.assess(context.demand)
                if assessment is None or assessment.demand != context.demand:
                    return closed
                # Broker rechecks the corpus and all gates; do not short-circuit.
                reason = assessment.gap_reason if assessment.status == "gap" else "coverage_gap"
                if reason is None:
                    return closed
                request = DiscoveryRequest(
                    demand=context.demand,
                    suggestion=SourceDiscoverySuggestion(
                        demand_hash=context.demand.demand_hash,
                        query_terms=("curriculum",), reason=reason,
                    ),
                    actor_id=context.actor_id, policy_id=context.policy_id,
                    policy_generation=context.policy_generation, budget=context.budget,
                )
            return self.broker.discover(request)
        except Exception:
            return closed


def campaign_projection(authority: PostgresCampaignAuthority) -> ServerQueryProjectionResolver:
    """Wire this to broker and campaign context resolver, never model terms."""
    return ServerQueryProjectionResolver(CampaignQueryAuthority(authority))
