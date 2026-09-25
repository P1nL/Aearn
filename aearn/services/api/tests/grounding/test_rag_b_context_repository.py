"""B1 private job context: offline denial and explicitly isolated PG tests only."""
from __future__ import annotations

import os
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.services.grounding.autonomous.access_policy import (
    AccessRequest, AuthoritySnapshot, AutonomousGates,
)
from app.services.grounding.autonomous.budget import BudgetDenied, fingerprint
from app.services.grounding.autonomous.context_repository import (
    DiscoveryContextRepository, PostgresDiscoveryContextResolver,
)
from app.services.grounding.autonomous.discovery_broker import _query_operation_id
from app.services.grounding.autonomous.contracts import (
    LearningMaterialDemand, RagBudgetDelegation, SourceDiscoveryDemand,
    SourceDiscoverySuggestion,
)
from app.services.grounding.autonomous.jobs import DiscoveryJobRepository
from tests.grounding.rag_material_helpers import H, NOW, SCOPE

GATES = AutonomousGates(discovery=True)


class Binding:
    def __init__(self, owners: dict[str, UUID]):
        self.owners = owners

    def authorize(self, user_id: UUID, actor_id: str) -> bool:
        return self.owners.get(actor_id) == user_id


class Removal:
    def __init__(self, user_id: UUID):
        self.user_id = user_id

    def authorize(self, user_id: UUID) -> bool:
        return user_id == self.user_id


class Reviewed:
    def project(self, demand: LearningMaterialDemand,
                suggestion: SourceDiscoverySuggestion) -> tuple[str, ...]:
        assert suggestion.demand_hash == demand.demand_hash
        # Reviewer-owned vocabulary, independent of untrusted suggestion text.
        return ("Python list",)


class Authority:
    def __init__(self, demands: dict[str, LearningMaterialDemand], budget: RagBudgetDelegation):
        self.demands = demands
        self.budget = budget
        self.calls = 0

    def resolve(self, request: AccessRequest) -> AuthoritySnapshot:
        self.calls += 1
        material = self.demands[request.actor_id]
        return AuthoritySnapshot(
            demand=material, demand_hash=material.demand_hash, scope=material.scope,
            purpose=material.purpose, actor_id=request.actor_id, allowed_actions=("discover",),
            policy_id="policy.001", policy_generation=2, budget=self.budget,
            budget_active=True, authorized=True,
        )


def _demand(plan: str) -> LearningMaterialDemand:
    return LearningMaterialDemand(
        scope=SCOPE, demand_hash=H, plan_ref=plan, node_ref="node.001",
        draft_revision=3, purpose="main_teaching", reading_level="beginner", language="zh",
    )


def _request(actor: str, root: RagBudgetDelegation) -> AccessRequest:
    return AccessRequest(
        demand_hash=H, scope=SCOPE, purpose="main_teaching", actor_id=actor,
        action="discover", policy_id="policy.001", policy_generation=2, budget=root,
    )


def _projection(actor: str, root: RagBudgetDelegation) -> SourceDiscoveryDemand:
    return SourceDiscoveryDemand(
        demand_hash=H, scope=SCOPE, query_terms=("Python list",), actor_id=actor,
        policy_id="policy.001", policy_generation=2, budget=root,
    )


SUGGESTION = SourceDiscoverySuggestion(
    demand_hash=H, query_terms=("ignore model supplied private code",), reason="coverage_gap",
)


def test_missing_binding_or_a_authority_never_issues() -> None:
    repo = DiscoveryContextRepository(None)  # type: ignore[arg-type]
    user = uuid4()
    actor = "actor.001"
    root = RagBudgetDelegation(root_id="root.001", delegation_id="delegation.001",
                               generation=1, expires_at=NOW + timedelta(days=1))
    kwargs = dict(job_id=uuid4(), user_id=user, request=_request(actor, root),
                  demand=_demand("plan.001"), suggestion=SUGGESTION, gates=GATES,
                  projection=Reviewed(), binding=Binding({actor: user}), now=NOW)
    with pytest.raises(BudgetDenied, match="AUTHORITY_MISSING"):
        repo.issue_for_job(**kwargs, resolver=None)
    with pytest.raises(BudgetDenied, match="USER_BINDING_MISSING"):
        repo.issue_for_job(**{**kwargs, "binding": None},
                           resolver=Authority({actor: _demand("plan.001")}, root))
    denied = Authority({actor: _demand("plan.001")}, root)
    with pytest.raises(BudgetDenied, match="GATE_CLOSED"):
        repo.issue_for_job(**{**kwargs, "gates": AutonomousGates()}, resolver=denied)
    assert denied.calls == 0
    with pytest.raises(BudgetDenied, match="PROJECTION_DENIED"):
        repo.issue_for_job(**{**kwargs, "projection": None},
                           resolver=Authority({actor: _demand("plan.001")}, root))
    with pytest.raises(BudgetDenied, match="REMOVAL_AUTHORITY_MISSING"):
        repo.export_user_refs(user_id=user, authority=None)
    selector = PostgresDiscoveryContextResolver(
        repo, authority=denied, binding=Binding({actor: user}),
        gates=lambda: AutonomousGates(), clock=lambda: NOW,
    )
    assert selector.resolve_job(uuid4()) is None
    assert denied.calls == 0
    assert selector.resolve_issued(_demand("plan.001"), _projection(actor, root)) is None
    missing = PostgresDiscoveryContextResolver(
        repo, authority=denied, binding=None, gates=lambda: GATES, clock=lambda: NOW,
    )
    assert missing.resolve_job(uuid4()) is None
    assert denied.calls == 0


@pytest.fixture(scope="module")
def isolated_db() -> str:
    dsn = os.environ.get("AEARN_RAG_B_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("context PostgreSQL not executed: explicitly isolated DB URL required")
    expected = urlsplit(dsn).path.lstrip("/")
    if not expected.startswith("aearn_rag260_"):
        pytest.fail("context tests refuse a non-aearn_rag260_ database")
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        actual = conn.execute("SELECT current_database() AS name").fetchone()
        schema = conn.execute("SELECT to_regclass('rag_discovery_private_contexts') AS name").fetchone()
        if actual is None or actual["name"] != expected or schema is None or schema["name"] is None:
            pytest.fail("context schema must be pre-applied by main session")
    return dsn


@pytest.fixture()
def conn(isolated_db: str):  # type: ignore[no-untyped-def]
    with psycopg.connect(isolated_db, row_factory=dict_row) as connection:
        yield connection
        connection.rollback()


def test_two_users_restart_and_exact_unlink_keeps_shared_job(conn) -> None:  # type: ignore[no-untyped-def]
    users = (uuid4(), uuid4())
    actors = ("actor." + uuid4().hex, "actor." + uuid4().hex)
    root = RagBudgetDelegation(
        root_id="root." + uuid4().hex, delegation_id="delegation." + uuid4().hex,
        generation=1, expires_at=NOW + timedelta(days=1),
    )
    demands = {actors[0]: _demand("plan.first"), actors[1]: _demand("plan.second")}
    binding = Binding(dict(zip(actors, users)))
    authority = Authority(demands, root)
    repo = DiscoveryContextRepository(conn)
    for user in users:
        conn.execute("INSERT INTO users(id,display_name) VALUES (%s,%s)", (user, "isolated-test"))
    conn.execute(
        "INSERT INTO rag_budget_authority_roots(root_id,delegation_id,delegation_generation,"
        "delegation_expires_at,policy_id,policy_generation,period_key,period_start,period_end,cap_units,enabled) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true)",
        (root.root_id, root.delegation_id, root.generation, root.expires_at,
         "policy.001", 2, "2026-09", NOW - timedelta(days=1), NOW + timedelta(days=2), 1),
    )
    for user, actor in zip(users, actors):
        repo.bind_actor(user_id=user, actor_id=actor, binding=binding)
    jobs = DiscoveryJobRepository(conn)
    key = _query_operation_id(demands[actors[0]], _projection(actors[0], root))
    job_id = None
    for user, actor in zip(users, actors):
        request = _request(actor, root)
        job_id = jobs.enqueue(
            request=request, demand=demands[actor], gates=GATES, resolver=authority,
            operation_key=key, request_hash=fingerprint(key, H),
            projection=_projection(actor, root), now=NOW,
        )
        result = repo.issue_for_job(
            job_id=job_id, user_id=user, request=request, demand=demands[actor],
            suggestion=SUGGESTION, gates=GATES, resolver=authority,
            projection=Reviewed(), binding=binding, now=NOW,
        )
        assert result.demand == demands[actor]
        assert result.projection.query_terms == ("Python list",)
    assert job_id is not None
    # A shared candidate may have two private actor refs; user unlink must
    # preserve the other reference and the immutable shared receipt/candidate.
    conn.execute(
        "INSERT INTO rag_budget_periods(root_id,period_key,cap_units,period_end) "
        "VALUES (%s,'2026-09',1,%s)", (root.root_id, NOW + timedelta(days=2)),
    )
    reservation = conn.execute(
        "INSERT INTO rag_budget_reservations(root_id,period_key,operation_key,request_hash,job_id,reserved_units) "
        "VALUES (%s,'2026-09',%s,%s,%s,1) RETURNING id",
        (root.root_id, "reserve." + uuid4().hex, H, job_id),
    ).fetchone()["id"]
    attempt = conn.execute(
        "INSERT INTO rag_budget_attempts(reservation_id,job_id,attempt_key) "
        "VALUES (%s,%s,%s) RETURNING id",
        (reservation, job_id, "attempt." + uuid4().hex),
    ).fetchone()["id"]
    receipt = conn.execute(
        "INSERT INTO rag_discovery_receipts(job_id,attempt_id,receipt_handle,result_code,response_hash) "
        "VALUES (%s,%s,%s,'SEARCH_COMPLETED',%s) RETURNING id",
        (job_id, attempt, "receipt." + uuid4().hex, H),
    ).fetchone()["id"]
    candidate = conn.execute(
        "INSERT INTO rag_discovery_candidates(job_id,discovery_receipt_id,canonical_url,"
        "canonical_url_hash,kind,demand_hash,subject_id,subject_version) "
        "VALUES (%s,%s,'https://example.org/lesson',%s,'landing',%s,%s,%s) RETURNING id",
        (job_id, receipt, H, H, SCOPE.subject_id, SCOPE.subject_version),
    ).fetchone()["id"]
    for actor in actors:
        conn.execute(
            "INSERT INTO rag_candidate_private_refs(actor_id,candidate_id) VALUES (%s,%s)",
            (actor, candidate),
        )
    first = repo.resolve_job(
        job_id=job_id, user_id=users[0], actor_id=actors[0], gates=GATES,
        resolver=authority, binding=binding, now=NOW,
    )
    assert first.demand.plan_ref == "plan.first"
    selector = PostgresDiscoveryContextResolver(
        repo, authority=authority, binding=binding, gates=lambda: GATES, clock=lambda: NOW,
    )
    selected = selector.resolve_job(job_id)
    assert selected is not None
    assert selected.projection.actor_id in actors
    assert selected.demand == demands[selected.projection.actor_id]
    assert selector.resolve_issued(selected.demand, selected.projection) == selected
    assert selector.resolve_issued(
        _demand("plan.invented"), selected.projection,
    ) is None
    # A stale first owner's full demand must not authorize a shared job;
    # a still-authorized second owner may be selected instead.
    authority.demands = {**demands, actors[0]: _demand("plan.revoked")}
    selected = selector.resolve_job(job_id)
    assert selected is not None and selected.projection.actor_id == actors[1]
    authority.demands = demands
    unbound = PostgresDiscoveryContextResolver(
        repo, authority=authority, binding=Binding({}), gates=lambda: GATES, clock=lambda: NOW,
    )
    assert unbound.resolve_job(job_id) is None
    with pytest.raises(BudgetDenied, match="POLICY_SCOPE_STALE"):
        repo.resolve_job(
            job_id=job_id, user_id=users[0], actor_id=actors[0], gates=GATES,
            resolver=Authority({**demands, actors[0]: _demand("plan.changed")}, root),
            binding=binding, now=NOW,
        )
    with pytest.raises(BudgetDenied, match="PROJECTION_CONFLICT|CONTEXT_CONFLICT|POLICY_SCOPE_STALE"):
        repo.issue_for_job(
            job_id=job_id, user_id=users[0], request=_request(actors[0], root),
            demand=_demand("plan.changed"), suggestion=SUGGESTION, gates=GATES,
            resolver=Authority({**demands, actors[0]: _demand("plan.changed")}, root),
            projection=Reviewed(), binding=binding, now=NOW,
        )
    exported = repo.export_user_refs(user_id=users[0], authority=Removal(users[0]))
    assert exported.job_ids == (job_id,) and exported.candidate_ids == (candidate,)
    assert repo.unlink_user(user_id=users[0], authority=Removal(users[0])) == exported
    assert conn.execute(
        "SELECT 1 FROM rag_candidate_private_refs WHERE actor_id=%s AND candidate_id=%s",
        (actors[0], candidate),
    ).fetchone() is None
    assert conn.execute(
        "SELECT 1 FROM rag_candidate_private_refs WHERE actor_id=%s AND candidate_id=%s",
        (actors[1], candidate),
    ).fetchone() is not None
    with pytest.raises(BudgetDenied, match="CONTEXT_NOT_FOUND"):
        repo.resolve_job(
            job_id=job_id, user_id=users[0], actor_id=actors[0], gates=GATES,
            resolver=authority, binding=binding, now=NOW,
        )
    assert repo.resolve_job(
        job_id=job_id, user_id=users[1], actor_id=actors[1], gates=GATES,
        resolver=authority, binding=binding, now=NOW,
    ).demand.plan_ref == "plan.second"
    assert conn.execute("SELECT id FROM rag_discovery_jobs WHERE id=%s", (job_id,)).fetchone()
    assert repo.export_user_refs(user_id=users[1], authority=Removal(users[1])).job_ids == (job_id,)
    selected = selector.resolve_job(job_id)
    assert selected is not None and selected.projection.actor_id == actors[1]
    repo.unlink_user(user_id=users[1], authority=Removal(users[1]))
    assert selector.resolve_job(job_id) is None
    assert conn.execute("SELECT id FROM rag_discovery_jobs WHERE id=%s", (job_id,)).fetchone()


def test_legacy_actor_cannot_be_auto_bound(conn) -> None:  # type: ignore[no-untyped-def]
    user = uuid4()
    actor = "actor." + uuid4().hex
    conn.execute("INSERT INTO users(id,display_name) VALUES (%s,'isolated-test')", (user,))
    # A legacy ref with this actor would be rejected by bind_actor rather than
    # inferred as owned by this UUID. Build only the smallest legitimate job.
    root = RagBudgetDelegation(root_id="root." + uuid4().hex,
                               delegation_id="delegation." + uuid4().hex,
                               generation=1, expires_at=NOW + timedelta(days=1))
    material = _demand("plan.legacy")
    job_id = DiscoveryJobRepository(conn).enqueue(
        request=_request(actor, root), demand=material, gates=GATES,
        resolver=Authority({actor: material}, root), operation_key="job." + uuid4().hex,
        request_hash=H, projection=_projection(actor, root), now=NOW,
    )
    assert job_id
    with pytest.raises(BudgetDenied, match="UNBOUND_LEGACY_REFS"):
        DiscoveryContextRepository(conn).bind_actor(
            user_id=user, actor_id=actor, binding=Binding({actor: user}),
        )
