"""Campaign authority protocol and optional isolated PostgreSQL tests; no provider/network."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import timedelta
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.services.grounding.autonomous.access_policy import (
    AccessRequest, AutonomousGates, check_access, issue_discovery_demand,
)
from app.services.grounding.autonomous.campaign_authority import (
    CampaignDiscoveryService, PostgresCampaignAuthority,
    PostgresCampaignContextResolver, campaign_demand, campaign_projection,
)
from app.services.grounding.autonomous.contracts import (
    SourceDiscoveryDemand, SourceDiscoverySuggestion,
)
from app.services.grounding.autonomous.discovery_broker import (
    BrokerResult, CorpusAssessment, _query_operation_id,
)
from tests.grounding.rag_material_helpers import NOW, SCOPE


class Result:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class MemoryConnection:
    def __init__(self, row):
        self.config = row
        self.issued = {}
        self.job = None
        self.writes = 0

    def transaction(self):
        return nullcontext()

    def execute(self, sql, params=()):
        if "SELECT c.*,p.operator_id" in sql:
            return Result(self.config if params[0] == self.config["campaign_id"] else None)
        if "SELECT campaign_id FROM rag_campaign_definitions" in sql:
            return Result({"campaign_id": self.config["campaign_id"]}
                          if params == (self.config["demand_hash"],) or
                          params == (self.config["demand_hash"], self.config["actor_id"])
                          else None)
        if "INSERT INTO rag_campaign_issued_contexts" in sql:
            key = params[0]
            if key not in self.issued:
                self.writes += 1
                names = (
                    "operation_key", "campaign_id", "actor_id", "demand_hash", "subject_id",
                    "subject_version", "facets", "purpose", "reading_level", "language",
                    "draft_revision", "reviewed_terms", "query_hash", "policy_id",
                    "policy_generation", "root_id", "delegation_id", "delegation_generation",
                )
                self.issued[key] = dict(zip(names, params, strict=True))
            return Result(None)
        if "SELECT * FROM rag_campaign_issued_contexts" in sql:
            return Result(self.issued.get(params[0]))
        if "FROM rag_discovery_jobs j JOIN rag_campaign_issued_contexts i" in sql:
            return Result(self.job if self.job and params[0] == self.job["job_id"] else None)
        raise AssertionError("unexpected query")


def definition():
    material = campaign_demand(
        campaign_id="python.core", revision=2, scope=SCOPE,
        purpose="main_teaching", reading_level="beginner", language="zh",
    )
    return {
        "campaign_id": "python.core", "operator_id": "operator.reviewed",
        "actor_id": "service.python.core", "revision": 2,
        "subject_id": SCOPE.subject_id, "subject_version": SCOPE.subject_version,
        "facets": list(SCOPE.facets), "purpose": material.purpose,
        "reading_level": material.reading_level, "language": material.language,
        "demand_hash": material.demand_hash, "policy_id": "policy.001",
        "policy_generation": 2, "root_id": "root.001", "delegation_id": "delegation.001",
        "delegation_generation": 1, "delegation_expires_at": NOW + timedelta(days=7),
        "root_policy_id": "policy.001", "root_policy_generation": 2,
        "period_start": NOW - timedelta(days=1), "period_end": NOW + timedelta(days=7),
        "principal_enabled": True, "enabled": True, "period_approved": True,
        "cost_approved": True, "root_enabled": True, "intake_approved": False,
    }


def authority(monkeypatch, row):
    monkeypatch.setattr(
        "app.services.grounding.autonomous.campaign_authority.require_transaction",
        lambda conn: None,
    )
    conn = MemoryConnection(row)
    return conn, PostgresCampaignAuthority(conn, clock=lambda: NOW)


def request(context):
    return AccessRequest(
        demand_hash=context.demand.demand_hash, scope=context.demand.scope,
        purpose=context.demand.purpose, actor_id=context.actor_id,
        action="discover", policy_id=context.policy_id,
        policy_generation=context.policy_generation, budget=context.budget,
    )


def suggestion(demand):
    return SourceDiscoverySuggestion(
        demand_hash=demand.demand_hash, query_terms=("curriculum",), reason="coverage_gap",
    )


def test_operator_definition_is_complete_and_versioned() -> None:
    one = campaign_demand(campaign_id="python.core", revision=2, scope=SCOPE,
                          purpose="main_teaching", reading_level="beginner", language="zh")
    two = campaign_demand(campaign_id="python.core", revision=2, scope=SCOPE,
                          purpose="main_teaching", reading_level="beginner", language="zh")
    changed = campaign_demand(campaign_id="python.core", revision=3, scope=SCOPE,
                              purpose="main_teaching", reading_level="beginner", language="zh")
    assert one == two and changed.demand_hash != one.demand_hash
    assert one.plan_ref.startswith("campaign.") and one.node_ref.startswith("campaign.node.")
    with pytest.raises(ValueError):
        campaign_demand(campaign_id="python.core", revision=2, scope=SCOPE,
                        purpose="invalid", reading_level="beginner", language="zh")


@pytest.mark.parametrize("disabled", [
    "principal_enabled", "enabled", "period_approved", "cost_approved", "root_enabled",
])
def test_each_operator_and_budget_switch_closes(monkeypatch, disabled) -> None:
    row = definition()
    row[disabled] = False
    _, owner = authority(monkeypatch, row)
    assert owner.load("python.core") is None
    assert owner.load("invalid actor id") is None


def test_period_and_root_generation_cannot_be_bypassed(monkeypatch) -> None:
    row = definition()
    conn, owner = authority(monkeypatch, row)
    context = owner.load("python.core")
    assert context is not None
    assert check_access(request(context), gates=AutonomousGates(discovery=True),
                        resolver=owner, now=NOW, demand=context.demand).allowed
    assert not check_access(request(context), gates=AutonomousGates(),
                            resolver=owner, now=NOW, demand=context.demand).allowed
    assert owner.resolve(request(context).model_copy(update={"action": "store"})) is None
    assert not check_access(request(context).model_copy(update={"demand_hash": "a" * 64}),
                            gates=AutonomousGates(discovery=True), resolver=owner,
                            now=NOW, demand=context.demand).allowed
    conn.config["root_policy_generation"] += 1
    assert owner.load("python.core") is None
    conn.config["root_policy_generation"] -= 1
    conn.config["period_end"] = NOW
    assert owner.load("python.core") is None


@pytest.mark.parametrize("action", ["probe", "store"])
def test_intake_authority_requires_current_campaign_approval_and_action_gate(monkeypatch, action) -> None:
    conn, owner = authority(monkeypatch, definition())
    context = owner.load("python.core")
    assert context is not None
    req = request(context).model_copy(update={"action": action})
    gates = AutonomousGates(discovery=True, intake=True)
    assert owner.resolve(req) is None  # schema defaults intake approval off
    assert not check_access(req, gates=gates, resolver=owner, now=NOW,
                            demand=context.demand).allowed
    assert check_access(request(context), gates=AutonomousGates(discovery=True),
                        resolver=owner, now=NOW, demand=context.demand).allowed

    conn.config["intake_approved"] = True
    snapshot = owner.resolve(req)
    assert snapshot is not None
    assert snapshot.allowed_actions == (action,)
    assert snapshot.demand == context.demand
    assert check_access(req, gates=gates, resolver=owner, now=NOW,
                        demand=context.demand).allowed
    assert not check_access(req, gates=AutonomousGates(), resolver=owner,
                            now=NOW, demand=context.demand).allowed
    if action == "probe":
        # Probe is subject to discovery, not the distinct intake gate.
        assert check_access(req, gates=AutonomousGates(discovery=True), resolver=owner,
                            now=NOW, demand=context.demand).allowed
    else:
        assert check_access(req, gates=AutonomousGates(intake=True), resolver=owner,
                            now=NOW, demand=context.demand).allowed

    conn.config["intake_approved"] = False
    assert owner.resolve(req) is None  # a previously returned snapshot cannot authorize the next call
    assert not check_access(req, gates=gates, resolver=owner, now=NOW,
                            demand=context.demand).allowed
    assert check_access(request(context), gates=AutonomousGates(discovery=True),
                        resolver=owner, now=NOW, demand=context.demand).allowed


@pytest.mark.parametrize("action", ["probe", "store"])
def test_intake_authority_rechecks_scope_actor_policy_budget_and_full_demand(monkeypatch, action) -> None:
    conn, owner = authority(monkeypatch, definition())
    conn.config["intake_approved"] = True
    context = owner.load("python.core")
    assert context is not None
    req = request(context).model_copy(update={"action": action})
    gates = AutonomousGates(discovery=True, intake=True)
    for field, value in (
        ("scope", context.demand.scope.model_copy(update={"subject_version": "other"})),
        ("purpose", "supplementary_explanation"),
        ("actor_id", "service.other"),
        ("policy_generation", context.policy_generation + 1),
        ("budget", context.budget.model_copy(update={"generation": 99})),
    ):
        stale = req.model_copy(update={field: value})
        assert owner.resolve(stale) is None
        assert not check_access(stale, gates=gates, resolver=owner, now=NOW,
                                demand=context.demand).allowed
    altered = context.demand.model_copy(update={"reading_level": "advanced"})
    assert not check_access(req, gates=gates, resolver=owner, now=NOW,
                            demand=altered).allowed  # hash alone cannot promote altered demand
    conn.config["cost_approved"] = False
    assert owner.resolve(req) is None


def test_campaign_projection_ignores_suggestion_terms_and_rechecks_full_demand(monkeypatch) -> None:
    conn, owner = authority(monkeypatch, definition())
    context = owner.load("python.core")
    assert context is not None
    projection = campaign_projection(owner)
    model_text = SourceDiscoverySuggestion(
        demand_hash=context.demand.demand_hash,
        query_terms=("secret private dialogue",), reason="coverage_gap",
    )
    issued = issue_discovery_demand(
        context.demand, model_text, actor_id=context.actor_id,
        policy_id=context.policy_id, policy_generation=context.policy_generation,
        budget=context.budget, gates=AutonomousGates(discovery=True),
        resolver=owner, projection=projection, now=NOW,
    )
    assert issued is not None
    assert issued.query_terms == ("Python", "syntax", "中文 教程")
    assert "secret" not in repr(issued)
    conn.config["demand_hash"] = "b" * 64
    assert projection.project(context.demand, model_text) is None


def test_persisted_campaign_context_replay_and_revocation(monkeypatch) -> None:
    conn, owner = authority(monkeypatch, definition())
    context = owner.load("python.core")
    assert context is not None
    projection = campaign_projection(owner)
    issued = issue_discovery_demand(
        context.demand, suggestion(context.demand), actor_id=context.actor_id,
        policy_id=context.policy_id, policy_generation=context.policy_generation,
        budget=context.budget, gates=AutonomousGates(discovery=True),
        resolver=owner, projection=projection, now=NOW,
    )
    assert issued is not None
    resolver = PostgresCampaignContextResolver(
        conn, authority=owner, gates=lambda: AutonomousGates(discovery=True), projection=projection,
    )
    assert resolver.resolve_issued(context.demand, issued) is not None
    assert resolver.resolve_issued(context.demand, issued) is not None
    assert conn.writes == 1
    operation = _query_operation_id(context.demand, issued)
    row = dict(conn.issued[operation])
    job_id = uuid4()
    conn.job = {
        **row, "job_id": job_id, "job_operation_key": operation,
        "job_query_hash": row["query_hash"], "job_demand_hash": row["demand_hash"],
        "job_root_id": row["root_id"], "job_policy_generation": row["policy_generation"],
    }
    assert resolver.resolve_job(job_id) is not None
    tampered = SourceDiscoveryDemand.model_validate({
        **issued.model_dump(), "query_terms": ("private user token",),
    })
    assert resolver.resolve_issued(context.demand, tampered) is None
    conn.config["enabled"] = False
    assert resolver.resolve_job(job_id) is None
    assert conn.writes == 1  # revoke does not delete accounting/issuance


class Corpus:
    def __init__(self):
        self.calls = 0

    def assess(self, demand):
        self.calls += 1
        return CorpusAssessment(demand=demand, status="gap", receipt_id="corpus.review",
                                gap_reason="coverage_gap")


class Broker:
    def __init__(self):
        self.calls = []

    def discover(self, request):
        self.calls.append(request)
        return BrokerResult(status="closed")


class Invoker:
    def authorize(self, operator_id, campaign_id):
        return operator_id == "operator.reviewed" and campaign_id == "python.core"


def test_only_exact_operator_invocation_reaches_shared_broker(monkeypatch) -> None:
    conn, owner = authority(monkeypatch, definition())
    corpus, broker = Corpus(), Broker()
    service = CampaignDiscoveryService(
        authority=owner, corpus=corpus, broker=broker, invoker=None,  # type: ignore[arg-type]
    )
    assert service.discover("python.core", operator_id="operator.reviewed").status == "closed"
    assert not broker.calls and corpus.calls == 0
    service.invoker = Invoker()
    service.discover("python.core", operator_id="operator.other")
    assert not broker.calls and corpus.calls == 0
    service.discover("python.core", operator_id="operator.reviewed")
    assert len(broker.calls) == 1 and corpus.calls == 1
    assert broker.calls[0].actor_id == "service.python.core"
    assert broker.calls[0].demand == owner.load("python.core").demand
    conn.config["cost_approved"] = False
    service.discover("python.core", operator_id="operator.reviewed")
    assert len(broker.calls) == 1


def test_schema_has_no_seed_or_user_impersonation() -> None:
    sql = (Path(__file__).parents[2] / "app/db/schema/310_rag_campaign_authority.sql").read_text()
    assert "INSERT INTO rag_campaign" not in sql
    assert "users(id)" not in sql and "DEFAULT false" in sql
    assert "trg_rag_campaign_issued_guard" in sql


@pytest.fixture(scope="module")
def isolated_campaign_db() -> str:
    dsn = os.environ.get("AEARN_RAG_B_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("campaign PG not executed: explicit disposable AEARN_RAG_B_TEST_DATABASE_URL required")
    expected = urlsplit(dsn).path.lstrip("/")
    if not expected.startswith("aearn_rag260_"):
        pytest.fail("campaign PG refuses non-aearn_rag260_ database")
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        actual = conn.execute("SELECT current_database() AS name").fetchone()
        schema = conn.execute("SELECT to_regclass('rag_campaign_definitions') AS name").fetchone()
        if actual is None or actual["name"] != expected or schema is None or schema["name"] is None:
            pytest.fail("campaign PG requires the exact pre-bootstrapped disposable database")
    return dsn


def test_pg_campaign_intake_approval_is_current_and_definition_immutable(
    isolated_campaign_db: str,
) -> None:
    # Own unique rows only; no bootstrap, provider, or persistent fixture changes.
    key = uuid4().hex
    with psycopg.connect(isolated_campaign_db, row_factory=dict_row) as conn:
        try:
            root, policy = f"root.{key}", f"policy.{key}"
            until = NOW + timedelta(days=7)
            conn.execute(
                "INSERT INTO rag_budget_authority_roots "
                "(root_id,delegation_id,delegation_generation,delegation_expires_at,"
                "policy_id,policy_generation,period_key,period_start,period_end,cap_units,enabled) "
                "VALUES (%s,%s,1,%s,%s,2,%s,%s,%s,5,true)",
                (root, f"delegation.{key}", until, policy, key,
                 NOW - timedelta(days=1), until),
            )

            def seed(suffix: str) -> str:
                campaign = f"campaign.{suffix}.{key}"
                actor = f"service.{suffix}.{key}"
                demand = campaign_demand(
                    campaign_id=campaign, revision=2, scope=SCOPE,
                    purpose="main_teaching", reading_level="beginner", language="zh",
                )
                conn.execute(
                    "INSERT INTO rag_campaign_principals(actor_id,operator_id,enabled) "
                    "VALUES (%s,%s,true)", (actor, f"operator.{key}"),
                )
                conn.execute(
                    "INSERT INTO rag_campaign_definitions "
                    "(campaign_id,actor_id,revision,subject_id,subject_version,facets,"
                    "purpose,reading_level,language,demand_hash,policy_id,policy_generation,"
                    "root_id,enabled,period_approved,cost_approved) "
                    "VALUES (%s,%s,2,%s,%s,%s,%s,%s,%s,%s,%s,2,%s,true,true,true)",
                    (campaign, actor, demand.scope.subject_id, demand.scope.subject_version,
                     list(demand.scope.facets), demand.purpose, demand.reading_level,
                     demand.language, demand.demand_hash, policy, root),
                )
                return campaign

            approved_campaign, other_campaign = seed("first"), seed("second")
            owner = PostgresCampaignAuthority(conn, clock=lambda: NOW)

            def assert_actions(campaign: str, *, intake: bool) -> None:
                context = owner.load(campaign)
                assert context is not None
                assert context.demand == campaign_demand(
                    campaign_id=campaign, revision=2, scope=SCOPE,
                    purpose="main_teaching", reading_level="beginner", language="zh",
                )
                discover = request(context)
                snapshot = owner.resolve(discover)
                assert snapshot is not None and snapshot.allowed_actions == ("discover",)
                for action in ("probe", "store"):
                    candidate = discover.model_copy(update={"action": action})
                    found = owner.resolve(candidate)
                    assert (found is not None) is intake
                    if found is not None:
                        assert found.allowed_actions == (action,)
                        assert found.demand == context.demand
                        assert found.scope == context.demand.scope
                        assert found.actor_id == context.actor_id

            default_row = conn.execute(
                "SELECT intake_approved FROM rag_campaign_definitions WHERE campaign_id=%s",
                (approved_campaign,),
            ).fetchone()
            assert default_row is not None and default_row["intake_approved"] is False
            assert_actions(approved_campaign, intake=False)
            assert_actions(other_campaign, intake=False)

            conn.execute(
                "UPDATE rag_campaign_definitions SET intake_approved=true WHERE campaign_id=%s",
                (approved_campaign,),
            )
            assert_actions(approved_campaign, intake=True)
            assert_actions(other_campaign, intake=False)  # same root, different campaign

            # Only approval switches can change; every failed edit rolls back its savepoint.
            for column, replacement in (
                ("revision", 3), ("subject_version", "3.13"),
                ("demand_hash", "f" * 64), ("policy_id", f"policy.other.{key}"),
                ("root_id", f"root.other.{key}"),
            ):
                with pytest.raises(psycopg.errors.CheckViolation):
                    with conn.transaction():
                        conn.execute(
                            f"UPDATE rag_campaign_definitions SET {column}=%s WHERE campaign_id=%s",
                            (replacement, approved_campaign),
                        )
            assert_actions(approved_campaign, intake=True)
            conn.execute(
                "UPDATE rag_campaign_definitions SET intake_approved=false WHERE campaign_id=%s",
                (approved_campaign,),
            )
            assert_actions(approved_campaign, intake=False)
        finally:
            conn.rollback()  # no persistent rows, including root and principals
