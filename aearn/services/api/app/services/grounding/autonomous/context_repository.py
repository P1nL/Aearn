"""Server-only persistent discovery context; never an authority resolver itself.

Bind a verified users.id to an actor *before* creating job/candidate refs. The
mapping is explicit: existing actor-only refs are not silently claimed. All
entrypoints are internal and caller-transaction-owned; no provider or network.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from datetime import datetime
from typing import Any, Callable, Protocol
from uuid import UUID

from psycopg import Connection

from .access_policy import (
    AccessRequest, AuthorityResolver, AutonomousGates, QueryProjectionResolver,
    issue_discovery_demand,
)
from .budget import (
    BudgetDenied, PostgresBudgetPolicyResolver, current_authority, require_transaction,
)
from .contracts import (
    HANDLE, LearningMaterialDemand, RagBudgetDelegation, SourceDiscoveryDemand,
    SourceDiscoverySuggestion, SubjectScope, revalidate,
)
from .discovery_broker import _query_operation_id
from .discovery_work import WorkContext
from .jobs import DiscoveryJobRepository, projected_query_hash


class UserActorBindingResolver(Protocol):
    """Trusted server identity port, not a model/request actor-handle parser."""

    def authorize(self, user_id: UUID, actor_id: str) -> bool: ...


class UserRemovalAuthority(Protocol):
    """Trusted reset/delete owner decision, independent of model input."""

    def authorize(self, user_id: UUID) -> bool: ...


@dataclass(frozen=True)
class JobContext:
    request: AccessRequest
    demand: LearningMaterialDemand
    projection: SourceDiscoveryDemand


@dataclass(frozen=True)
class UserDiscoveryRefs:
    """Non-sensitive export pointers only; never shared query/body/receipt text."""

    job_ids: tuple[UUID, ...]
    candidate_ids: tuple[UUID, ...]


class DiscoveryContextRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn

    @staticmethod
    def _binding(user_id: UUID, actor_id: str, binding: UserActorBindingResolver | None) -> None:
        if (type(user_id) is not UUID or not isinstance(actor_id, str)
                or re.fullmatch(HANDLE, actor_id) is None or binding is None):
            raise BudgetDenied("USER_BINDING_MISSING")
        try:
            if binding.authorize(user_id, actor_id) is True:
                return
        except Exception as exc:
            raise BudgetDenied("USER_BINDING_MISSING") from exc
        raise BudgetDenied("USER_BINDING_DENIED")

    @staticmethod
    def _removal(user_id: UUID, authority: UserRemovalAuthority | None) -> None:
        if type(user_id) is not UUID or authority is None:
            raise BudgetDenied("REMOVAL_AUTHORITY_MISSING")
        try:
            if authority.authorize(user_id) is True:
                return
        except Exception as exc:
            raise BudgetDenied("REMOVAL_AUTHORITY_MISSING") from exc
        raise BudgetDenied("REMOVAL_DENIED")

    def _lock_private_refs(self) -> None:
        # Legacy writers do not lock the owner row. Serialize explicit binding
        # and user unlink with actor-only reference inserts; never claim an
        # already existing unowned reference through a racing first write.
        self.conn.execute(
            "LOCK TABLE rag_discovery_job_refs, rag_candidate_private_refs "
            "IN SHARE ROW EXCLUSIVE MODE"
        )

    def bind_actor(
        self, *, user_id: UUID, actor_id: str, binding: UserActorBindingResolver | None,
    ) -> None:
        """Explicit server mapping before enqueue; refuses legacy unowned refs."""
        self._binding(user_id, actor_id, binding)
        require_transaction(self.conn)
        with self.conn.transaction():
            self._binding(user_id, actor_id, binding)
            self._lock_private_refs()
            user = self.conn.execute(
                "SELECT id FROM users WHERE id=%s AND deleted_at IS NULL FOR KEY SHARE", (user_id,),
            ).fetchone()
            if user is None:
                raise BudgetDenied("USER_NOT_FOUND")
            owner = self.conn.execute(
                "SELECT user_id FROM rag_discovery_actor_owners WHERE actor_id=%s FOR UPDATE",
                (actor_id,),
            ).fetchone()
            if owner is not None:
                if owner["user_id"] != user_id:
                    raise BudgetDenied("ACTOR_OWNER_CONFLICT")
                return
            legacy = self.conn.execute(
                "SELECT 1 FROM rag_discovery_job_refs WHERE actor_id=%s "
                "UNION ALL SELECT 1 FROM rag_candidate_private_refs WHERE actor_id=%s LIMIT 1",
                (actor_id, actor_id),
            ).fetchone()
            if legacy is not None:
                raise BudgetDenied("UNBOUND_LEGACY_REFS")
            self.conn.execute(
                "INSERT INTO rag_discovery_actor_owners(actor_id,user_id) VALUES (%s,%s) "
                "ON CONFLICT (actor_id) DO NOTHING", (actor_id, user_id),
            )
            owner = self.conn.execute(
                "SELECT user_id FROM rag_discovery_actor_owners WHERE actor_id=%s", (actor_id,),
            ).fetchone()
            if owner is None or owner["user_id"] != user_id:
                raise BudgetDenied("ACTOR_OWNER_CONFLICT")

    def issue_for_job(
        self, *, job_id: UUID, user_id: UUID, request: AccessRequest,
        demand: LearningMaterialDemand, suggestion: SourceDiscoverySuggestion,
        gates: AutonomousGates, resolver: AuthorityResolver | None,
        projection: QueryProjectionResolver | None, binding: UserActorBindingResolver | None,
        now: datetime,
    ) -> JobContext:
        """Persist exact trusted demand and reviewed projection against an enqueued job.

        The input request is only a lookup; A's resolver must confirm the full
        demand/action/policy/delegation, and the current DB root must match.
        """
        if type(job_id) is not UUID or resolver is None:
            raise BudgetDenied("AUTHORITY_MISSING")
        try:
            request = revalidate(request, AccessRequest)
        except (ValueError, TypeError) as exc:
            raise BudgetDenied("INVALID_CONTRACT") from exc
        if request.action != "discover":
            raise BudgetDenied("ACTION_DENIED")
        self._binding(user_id, request.actor_id, binding)
        valid_demand = revalidate(demand, LearningMaterialDemand)
        valid_suggestion = revalidate(suggestion, SourceDiscoverySuggestion)
        snapshot = current_authority(
            request=request, demand=valid_demand, gates=gates, resolver=resolver, now=now,
        )
        issued = issue_discovery_demand(
            valid_demand, valid_suggestion, actor_id=snapshot.actor_id,
            policy_id=snapshot.policy_id, policy_generation=snapshot.policy_generation,
            budget=snapshot.budget, gates=gates, resolver=resolver, projection=projection, now=now,
        )
        if issued is None:
            raise BudgetDenied("PROJECTION_DENIED")
        query_hash = projected_query_hash(issued, snapshot, valid_demand)
        require_transaction(self.conn)
        with self.conn.transaction():
            self._binding(user_id, request.actor_id, binding)
            refreshed = current_authority(
                request=request, demand=valid_demand, gates=gates, resolver=resolver, now=now,
            )
            if refreshed != snapshot or PostgresBudgetPolicyResolver(self.conn).resolve(refreshed) is None:
                raise BudgetDenied("AUTHORITY_CHANGED")
            owner = self.conn.execute(
                "SELECT user_id FROM rag_discovery_actor_owners WHERE actor_id=%s FOR SHARE",
                (snapshot.actor_id,),
            ).fetchone()
            if owner is None or owner["user_id"] != user_id:
                raise BudgetDenied("USER_BINDING_MISSING")
            active_user = self.conn.execute(
                "SELECT id FROM users WHERE id=%s AND deleted_at IS NULL FOR KEY SHARE",
                (user_id,),
            ).fetchone()
            if active_user is None:
                raise BudgetDenied("USER_NOT_FOUND")
            row = self.conn.execute(
                "SELECT * FROM rag_discovery_jobs WHERE id=%s FOR SHARE", (job_id,),
            ).fetchone()
            if row is None:
                raise BudgetDenied("JOB_NOT_FOUND")
            DiscoveryJobRepository._scope(row, refreshed, valid_demand)
            if row["query_hash"] != query_hash:
                raise BudgetDenied("PROJECTION_SCOPE_STALE")
            ref = self.conn.execute(
                "SELECT 1 FROM rag_discovery_job_refs WHERE job_id=%s AND actor_id=%s "
                "AND demand_hash=%s", (job_id, snapshot.actor_id, valid_demand.demand_hash),
            ).fetchone()
            if ref is None:
                raise BudgetDenied("JOB_REF_MISSING")
            self.conn.execute(
                "INSERT INTO rag_discovery_query_contexts(job_id,reviewed_terms,query_hash) "
                "VALUES (%s,%s,%s) ON CONFLICT (job_id) DO NOTHING",
                (job_id, list(issued.query_terms), query_hash),
            )
            query = self.conn.execute(
                "SELECT reviewed_terms,query_hash FROM rag_discovery_query_contexts WHERE job_id=%s",
                (job_id,),
            ).fetchone()
            if query is None or (tuple(query["reviewed_terms"]), query["query_hash"]) != (
                issued.query_terms, query_hash,
            ):
                raise BudgetDenied("PROJECTION_CONFLICT")
            self.conn.execute(
                "INSERT INTO rag_discovery_private_contexts "
                "(job_id,actor_id,user_id,demand_hash,plan_ref,node_ref,draft_revision,"
                "reading_level,language,facets) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (job_id,actor_id) DO NOTHING",
                (job_id, snapshot.actor_id, user_id, valid_demand.demand_hash,
                 valid_demand.plan_ref, valid_demand.node_ref, valid_demand.draft_revision,
                 valid_demand.reading_level, valid_demand.language, list(valid_demand.scope.facets)),
            )
            private = self.conn.execute(
                "SELECT * FROM rag_discovery_private_contexts WHERE job_id=%s AND actor_id=%s",
                (job_id, snapshot.actor_id),
            ).fetchone()
            if private is None or self._demand(private, row) != valid_demand or private["user_id"] != user_id:
                raise BudgetDenied("CONTEXT_CONFLICT")
        return JobContext(request, valid_demand, issued)

    @staticmethod
    def _demand(private: dict[str, Any], job: dict[str, Any]) -> LearningMaterialDemand:
        return LearningMaterialDemand(
            scope=SubjectScope(subject_id=job["subject_id"],
                               subject_version=job["subject_version"],
                               facets=tuple(private["facets"])),
            demand_hash=private["demand_hash"], plan_ref=private["plan_ref"],
            node_ref=private["node_ref"], draft_revision=private["draft_revision"],
            purpose=job["purpose"], reading_level=private["reading_level"],
            language=private["language"],
        )

    def resolve_job(
        self, *, job_id: UUID, user_id: UUID, actor_id: str,
        gates: AutonomousGates, resolver: AuthorityResolver | None,
        binding: UserActorBindingResolver | None, now: datetime,
    ) -> JobContext:
        """Restart path: use persisted full demand, then A authority *again*."""
        if type(job_id) is not UUID or resolver is None:
            raise BudgetDenied("AUTHORITY_MISSING")
        try:
            enabled = revalidate(gates, AutonomousGates)
        except (ValueError, TypeError) as exc:
            raise BudgetDenied("GATE_CLOSED") from exc
        if not enabled.discovery:
            raise BudgetDenied("GATE_CLOSED")
        self._binding(user_id, actor_id, binding)
        require_transaction(self.conn)
        with self.conn.transaction():
            row = self.conn.execute(
                "SELECT j.*, q.reviewed_terms, q.query_hash AS stored_query_hash, "
                "p.actor_id AS private_actor_id,p.user_id,p.demand_hash AS private_demand_hash,"
                "p.plan_ref,p.node_ref,p.draft_revision,p.reading_level,p.language,p.facets "
                "FROM rag_discovery_jobs j "
                "JOIN rag_discovery_query_contexts q ON q.job_id=j.id "
                "JOIN rag_discovery_private_contexts p ON p.job_id=j.id "
                "JOIN users u ON u.id=p.user_id AND u.deleted_at IS NULL "
                "WHERE j.id=%s AND p.actor_id=%s AND p.user_id=%s",
                (job_id, actor_id, user_id),
            ).fetchone()
            if row is None:
                raise BudgetDenied("CONTEXT_NOT_FOUND")
            # Use the private column, never a model-provided hash/root. The
            # reconstituted request is still only a request to A's resolver.
            private = dict(row)
            private["demand_hash"] = row["private_demand_hash"]
            demand = self._demand(private, row)
            root = self.conn.execute(
                "SELECT delegation_id,delegation_generation,delegation_expires_at "
                "FROM rag_budget_authority_roots WHERE root_id=%s AND enabled=true",
                (row["root_id"],),
            ).fetchone()
            if root is None or (root["delegation_id"], root["delegation_generation"]) != (
                row["delegation_id"], row["delegation_generation"],
            ):
                raise BudgetDenied("BUDGET_UNAVAILABLE")
            budget = RagBudgetDelegation(
                root_id=row["root_id"], delegation_id=root["delegation_id"],
                generation=root["delegation_generation"], expires_at=root["delegation_expires_at"],
            )
            request = AccessRequest(
                actor_id=actor_id, action="discover", demand_hash=demand.demand_hash,
                scope=demand.scope, purpose=demand.purpose, policy_id=row["policy_id"],
                policy_generation=row["policy_generation"], budget=budget,
            )
            snapshot = current_authority(
                request=request, demand=demand, gates=gates, resolver=resolver, now=now,
            )
            if PostgresBudgetPolicyResolver(self.conn).resolve(snapshot) is None:
                raise BudgetDenied("BUDGET_UNAVAILABLE")
            DiscoveryJobRepository._scope(row, snapshot, demand)
            projection = SourceDiscoveryDemand(
                demand_hash=demand.demand_hash, scope=demand.scope,
                query_terms=tuple(row["reviewed_terms"]), actor_id=actor_id,
                policy_id=snapshot.policy_id, policy_generation=snapshot.policy_generation,
                budget=snapshot.budget,
            )
            if row["stored_query_hash"] != row["query_hash"] or (
                projected_query_hash(projection, snapshot, demand) != row["query_hash"]
            ):
                raise BudgetDenied("PROJECTION_SCOPE_STALE")
            return JobContext(request, demand, projection)

    def export_user_refs(
        self, *, user_id: UUID, authority: UserRemovalAuthority | None,
    ) -> UserDiscoveryRefs:
        """Only bound actors; orphan legacy refs intentionally remain unexported."""
        self._removal(user_id, authority)
        require_transaction(self.conn)
        with self.conn.transaction():
            self._removal(user_id, authority)
            job_rows = self.conn.execute(
                "SELECT DISTINCT r.job_id FROM rag_discovery_job_refs r "
                "JOIN rag_discovery_actor_owners o ON o.actor_id=r.actor_id "
                "WHERE o.user_id=%s ORDER BY r.job_id", (user_id,),
            ).fetchall()
            candidate_rows = self.conn.execute(
                "SELECT DISTINCT r.candidate_id FROM rag_candidate_private_refs r "
                "JOIN rag_discovery_actor_owners o ON o.actor_id=r.actor_id "
                "WHERE o.user_id=%s ORDER BY r.candidate_id", (user_id,),
            ).fetchall()
            return UserDiscoveryRefs(
                tuple(row["job_id"] for row in job_rows),
                tuple(row["candidate_id"] for row in candidate_rows),
            )

    def unlink_user(
        self, *, user_id: UUID, authority: UserRemovalAuthority | None,
    ) -> UserDiscoveryRefs:
        """Call inside reset/delete transaction; remove private refs, not shared facts.

        Returning IDs lets a caller audit that an export and unlink agreed. The
        caller owns commit/rollback. No actor-only legacy refs are inferred.
        """
        self._removal(user_id, authority)
        require_transaction(self.conn)
        with self.conn.transaction():
            self._removal(user_id, authority)
            self._lock_private_refs()
            owners = self.conn.execute(
                "SELECT actor_id FROM rag_discovery_actor_owners WHERE user_id=%s "
                "ORDER BY actor_id FOR UPDATE", (user_id,),
            ).fetchall()
            refs = self.export_user_refs(user_id=user_id, authority=authority)
            for row in owners:
                actor_id = row["actor_id"]
                self.conn.execute(
                    "DELETE FROM rag_discovery_private_contexts WHERE actor_id=%s AND user_id=%s",
                    (actor_id, user_id),
                )
                self.conn.execute(
                    "DELETE FROM rag_candidate_private_refs WHERE actor_id=%s", (actor_id,),
                )
                self.conn.execute(
                    "DELETE FROM rag_discovery_job_refs WHERE actor_id=%s", (actor_id,),
                )
            self.conn.execute("DELETE FROM rag_discovery_actor_owners WHERE user_id=%s", (user_id,))
            return refs

class PostgresDiscoveryContextResolver:
    """Server-owned job selector for the B1 DiscoveryContextResolver port.

    Selection is not issuance: resolve_issued can only replay an already
    persisted, server-reviewed context. Creating a new job still requires a
    separate trusted issuer and the enqueue/context-write transaction. A stored
    hash, job ID or actor handle never grants access.
    """

    def __init__(
        self, repository: DiscoveryContextRepository, *,
        authority: AuthorityResolver | None,
        binding: UserActorBindingResolver | None,
        gates: Callable[[], AutonomousGates | None] | None,
        clock: Callable[[], datetime] | None,
    ) -> None:
        self.repository = repository
        self.authority = authority
        self.binding = binding
        self.gates = gates
        self.clock = clock

    def resolve_issued(
        self, demand: LearningMaterialDemand, projection: SourceDiscoveryDemand,
    ) -> WorkContext | None:
        """Recheck a persisted issuance only; cannot authorize first enqueue."""
        if self.authority is None or self.binding is None:
            return None
        try:
            valid_demand = revalidate(demand, LearningMaterialDemand)
            valid_projection = revalidate(projection, SourceDiscoveryDemand)
            operation_key = _query_operation_id(valid_demand, valid_projection)
            conn = self.repository.conn
            require_transaction(conn)
            with conn.transaction():
                row = conn.execute(
                    "SELECT id FROM rag_discovery_jobs WHERE operation_key=%s",
                    (operation_key,),
                ).fetchone()
                if row is None:
                    return None
                selected = self.resolve_job(row["id"])
                if (selected is not None and selected.demand == valid_demand
                        and selected.projection == valid_projection):
                    return selected
        except Exception:
            return None
        return None

    def resolve_job(self, job_id: UUID) -> WorkContext | None:
        """Choose one *currently* authorized private owner for a shared job.

        The caller owns the surrounding transaction. SHARE row locks keep a
        selected user/context from disappearing during the worker's fenced
        claim, while unlink_user serializes with private reference writes.
        """
        if (type(job_id) is not UUID or self.authority is None or self.binding is None
                or self.gates is None or self.clock is None):
            return None
        try:
            provided_gates = self.gates()
            if provided_gates is None:
                return None
            enabled = revalidate(provided_gates, AutonomousGates)
            if not enabled.discovery:
                return None
            now = self.clock()
            if not isinstance(now, datetime) or now.tzinfo is None:
                return None
            conn = self.repository.conn
            require_transaction(conn)
            with conn.transaction():
                # Both the owner mapping and exact job ref must exist. Never
                # claim an unbound legacy actor or infer a UUID from a handle.
                rows = conn.execute(
                    "SELECT p.actor_id,p.user_id FROM rag_discovery_private_contexts p "
                    "JOIN rag_discovery_actor_owners o ON o.actor_id=p.actor_id "
                    "AND o.user_id=p.user_id "
                    "JOIN rag_discovery_job_refs r ON r.job_id=p.job_id "
                    "AND r.actor_id=p.actor_id AND r.demand_hash=p.demand_hash "
                    "JOIN users u ON u.id=p.user_id AND u.deleted_at IS NULL "
                    "JOIN rag_discovery_query_contexts q ON q.job_id=p.job_id "
                    "WHERE p.job_id=%s ORDER BY p.issued_at,p.actor_id "
                    "FOR SHARE OF p,o,u",
                    (job_id,),
                ).fetchall()
                for row in rows:
                    try:
                        context = self.repository.resolve_job(
                            job_id=job_id, user_id=row["user_id"], actor_id=row["actor_id"],
                            gates=enabled, resolver=self.authority, binding=self.binding, now=now,
                        )
                    except BudgetDenied:
                        # A revoked actor cannot block another valid owner of
                        # the same shared, reviewed job from being selected.
                        continue
                    return WorkContext(context.demand, context.projection)
        except Exception:
            # Missing schema, resolver error or malformed persisted state must
            # deny, never surface exception text or pick a hash-only fallback.
            return None
        return None
