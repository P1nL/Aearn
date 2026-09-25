"""Offline composition checks; real provider and PostgreSQL are not used."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

from app.services.grounding.autonomous import worker_composition as module
from app.services.grounding.autonomous.discovery_broker import (
    AttemptTicket,
    CorpusAssessment,
    SearchResult,
    WorkClaim,
    WorkDecision,
)
from app.services.grounding.autonomous.discovery_work import WorkContext
from tests.grounding.rag_material_helpers import NOW, demand
from tests.grounding.test_rag_b_discovery_work import projection


class Approval:
    def __init__(self, allowed=True):
        self.allowed = allowed
        self.calls = 0

    def permitted(self):
        self.calls += 1
        return self.allowed


@contextmanager
def connection():
    yield SimpleNamespace(autocommit=False)


def config(**changed):
    args = dict(
        connect=connection,
        private_authority=lambda conn: None,
        actor_binding=lambda conn: None,
        qualification=lambda conn: object(),
        cost_approval=lambda conn: Approval(),
        network_approval=lambda conn: Approval(),
        tavily_key="fakeTestKey123",
        owner_id="worker.001",
        clock=lambda: NOW,
    )
    args.update(changed)
    return module.OperatorWorkerConfig(**args)


def enable(monkeypatch):
    monkeypatch.setenv("RAG_SOURCE_DISCOVERY_ENABLED", "true")
    for key in (
        "RAG_AUTO_INTAKE_ENABLED",
        "RAG_AUTO_ACTIVATION_ENABLED",
        "RAG_EVIDENCE_CONSUMER_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)


def test_default_closed_and_explicit_selectors(monkeypatch):
    monkeypatch.delenv("RAG_SOURCE_DISCOVERY_ENABLED", raising=False)
    monkeypatch.setattr(module, "_load_operator_config", lambda: None)
    job = str(uuid4())
    assert (
        module.run_rag_worker_operation(operation="dispatch", job_id=job)
        == module._blocked()
    )
    enable(monkeypatch)
    for args in (
        dict(operation="dispatch", job_id="bad"),
        dict(operation="dispatch", job_id=job, candidate_id=job),
        dict(operation="intake", candidate_id=job),
        dict(operation="intake", candidate_id="bad"),
        dict(operation="retention", limit=1),
        dict(operation="retention", limit=True),
        dict(operation="retention", limit=101),
        dict(operation="unknown", job_id=job),
        dict(operation="dispatch", job_id=job),
    ):
        assert module.run_rag_worker_operation(**args) == module._blocked()


def test_no_credential_or_independent_approval_means_no_context_or_transport(
    monkeypatch,
):
    enable(monkeypatch)
    monkeypatch.setattr(module, "_select_context", lambda *args: 1 / 0)
    monkeypatch.setattr(module, "HttpxTavilyTransport", lambda **kw: 1 / 0)
    for supplied in (
        config(tavily_key=""),
        config(cost_approval=lambda conn: None),
        config(network_approval=lambda conn: Approval(False)),
    ):
        monkeypatch.setattr(
            module, "_load_operator_config", lambda supplied=supplied: supplied
        )
        assert (
            module.run_rag_worker_operation(operation="dispatch", job_id=str(uuid4()))
            == module._blocked()
        )


def test_same_usage_authority_and_dispatch_before_provider(monkeypatch):
    enable(monkeypatch)
    job = uuid4()
    claim = WorkClaim(
        job_id=f"job.{job.hex}",
        reservation_id=f"reservation.{uuid4().hex}",
        lease_owner="worker.001",
        lease_generation=1,
    )
    ticket = AttemptTicket(
        job_id=claim.job_id, attempt_id=f"attempt.{uuid4().hex}", lease_generation=1
    )
    context = WorkContext(demand(), projection())
    usage = object()
    events = []
    cost, network = Approval(), Approval()
    supplied = config(
        cost_approval=lambda conn: cost, network_approval=lambda conn: network
    )
    monkeypatch.setattr(module, "_load_operator_config", lambda: supplied)
    monkeypatch.setattr(
        module, "_select_context", lambda *args: (context, object(), object())
    )
    monkeypatch.setattr(
        module,
        "QualifiedCorpusAdapter",
        lambda authority: SimpleNamespace(
            assess=lambda value: CorpusAssessment(
                demand=value,
                status="gap",
                receipt_id="receipt.001",
                gap_reason="coverage_gap",
            )
        ),
    )
    monkeypatch.setattr(module, "HttpxTavilyTransport", lambda **kwargs: object())
    monkeypatch.setattr(module, "TavilyUsageAuthority", lambda transport: usage)

    class Work:
        def __init__(self, **kwargs):
            assert kwargs["usage"] is usage

        def claim_or_reuse(self, *args):
            events.append("claim")
            return WorkDecision(status="claimed", claim=claim)

        def prepare_attempt(self, received):
            events.append("attempt")
            return ticket

        def take_dispatch(self, *args):
            events.append("CAS")
            return True

        def record_outcome(self, received, issued, settlement, candidates):
            events.append("settle")
            assert settlement.status == "completed" and candidates == ()
            return True

        def record_unknown(self, *args):
            events.append("unknown")

    class Bridge:
        def __init__(self, *, dispatch, usage_authority, enabled):
            assert usage_authority is usage and enabled
            self.dispatch = dispatch

        def search(self, *args):
            assert self.dispatch.take_dispatch(*args)
            events.append("provider")
            return SearchResult(
                status="completed", usage_units=1, usage_receipt_id="usage.001"
            )

    monkeypatch.setattr(module, "PostgresDiscoveryWork", Work)
    monkeypatch.setattr(module, "PreparedTavilySearchBridge", Bridge)
    assert (
        module.run_rag_worker_operation(operation="dispatch", job_id=str(job))
        == module._blocked()
    )
    assert events == ["claim", "attempt", "CAS", "provider", "settle"]
    assert cost.calls >= 3 and network.calls >= 3


def test_failed_settlement_holds_unknown(monkeypatch):
    enable(monkeypatch)
    job = uuid4()
    claim = WorkClaim(
        job_id=f"job.{job.hex}",
        reservation_id=f"reservation.{uuid4().hex}",
        lease_owner="worker.001",
        lease_generation=1,
    )
    ticket = AttemptTicket(
        job_id=claim.job_id, attempt_id=f"attempt.{uuid4().hex}", lease_generation=1
    )
    context = WorkContext(demand(), projection())
    events = []
    monkeypatch.setattr(module, "_load_operator_config", lambda: config())
    monkeypatch.setattr(
        module, "_select_context", lambda *args: (context, object(), object())
    )
    monkeypatch.setattr(
        module,
        "QualifiedCorpusAdapter",
        lambda authority: SimpleNamespace(
            assess=lambda value: CorpusAssessment(
                demand=value,
                status="gap",
                receipt_id="receipt.001",
                gap_reason="coverage_gap",
            )
        ),
    )
    monkeypatch.setattr(module, "HttpxTavilyTransport", lambda **kwargs: object())
    monkeypatch.setattr(module, "TavilyUsageAuthority", lambda transport: object())

    class Work:
        def __init__(self, **kwargs):
            pass

        def claim_or_reuse(self, *args):
            return WorkDecision(status="claimed", claim=claim)

        def prepare_attempt(self, received):
            return ticket

        def record_outcome(self, *args):
            events.append("settlement rejected")
            return False

        def record_unknown(self, received, issued):
            assert issued == ticket
            events.append("unknown held")

    monkeypatch.setattr(module, "PostgresDiscoveryWork", Work)
    monkeypatch.setattr(
        module,
        "PreparedTavilySearchBridge",
        lambda **kw: SimpleNamespace(
            search=lambda *args: SearchResult(status="uncertain")
        ),
    )
    assert (
        module.run_rag_worker_operation(operation="dispatch", job_id=str(job))
        == module._blocked()
    )
    assert events == ["settlement rejected", "unknown held"]


def test_isolated_pg_missing_current_c_authority_is_closed(monkeypatch):
    """Optional read-only smoke. Requires a separately provisioned disposable DB.

    This never bootstraps, seeds, deletes, calls Tavily, or targets the default DB.
    """
    import os
    from urllib.parse import parse_qs, urlparse

    import psycopg
    import pytest
    from psycopg.rows import dict_row

    dsn = os.environ.get("AEARN_RAG_B_WORKER_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("isolated PostgreSQL URL not supplied")
    parsed = urlparse(dsn)
    if (
        parsed.scheme not in {"postgresql", "postgres"}
        or parsed.hostname not in {"localhost", "127.0.0.1"}
        or not parsed.path.lstrip("/").startswith("aearn_rag260_")
        or parsed.fragment
        or set(parse_qs(parsed.query)) - {"sslmode"}
    ):
        pytest.skip("not an explicit local aearn_rag260_ database")
    with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=3) as check:
        assert check.execute("SELECT current_database() AS name").fetchone()[
            "name"
        ] == parsed.path.lstrip("/")
    enable(monkeypatch)
    supplied = config(
        connect=lambda: psycopg.connect(dsn, row_factory=dict_row, connect_timeout=3),
        qualification=lambda conn: None,
    )
    monkeypatch.setattr(module, "_load_operator_config", lambda: supplied)
    monkeypatch.setattr(module, "HttpxTavilyTransport", lambda **kw: 1 / 0)
    assert (
        module.run_rag_worker_operation(operation="dispatch", job_id=str(uuid4()))
        == module._blocked()
    )


def test_missing_current_c_qualification_blocks_without_transport(monkeypatch):
    enable(monkeypatch)
    job = str(uuid4())
    monkeypatch.setattr(
        module, "_load_operator_config", lambda: config(qualification=lambda conn: None)
    )
    monkeypatch.setattr(
        module,
        "_select_context",
        lambda *args: (WorkContext(demand(), projection()), object(), object()),
    )
    monkeypatch.setattr(module, "HttpxTavilyTransport", lambda **kw: 1 / 0)
    assert (
        module.run_rag_worker_operation(operation="dispatch", job_id=job)
        == module._blocked()
    )


def test_shared_job_can_choose_current_campaign_owner(monkeypatch):
    from contextlib import nullcontext

    job = uuid4()
    issued = WorkContext(demand(), projection())
    campaign_authority = object()
    campaign_context = SimpleNamespace(resolve_job=lambda selected: issued)
    private_context = SimpleNamespace(resolve_job=lambda selected: issued)
    monkeypatch.setattr(
        module, "PostgresCampaignAuthority", lambda conn, clock: campaign_authority
    )
    monkeypatch.setattr(module, "campaign_projection", lambda authority: object())
    monkeypatch.setattr(
        module, "PostgresCampaignContextResolver", lambda *args, **kw: campaign_context
    )
    monkeypatch.setattr(module, "DiscoveryContextRepository", lambda conn: object())
    monkeypatch.setattr(
        module, "PostgresDiscoveryContextResolver", lambda *args, **kw: private_context
    )
    conn = SimpleNamespace(transaction=lambda: nullcontext())
    assert module._select_context(conn, job, object(), object(), lambda: NOW) == (
        issued,
        campaign_context,
        campaign_authority,
    )


def test_retention_requires_reviewed_approval_and_uses_expiry_cleanup(monkeypatch):
    # Cleanup remains possible when intake is off, but never via env alone.
    monkeypatch.delenv("RAG_AUTO_INTAKE_ENABLED", raising=False)
    monkeypatch.delenv("RAG_SOURCE_DISCOVERY_ENABLED", raising=False)
    events = []
    monkeypatch.setattr(
        module,
        "CandidateStagingRepository",
        lambda conn: SimpleNamespace(
            clear_expired=lambda *, limit: events.append(limit) or 2,
        ),
    )
    monkeypatch.setattr(module, "_load_operator_config", lambda: config())
    assert (
        module.run_rag_worker_operation(operation="retention", limit=3)
        == module._blocked()
    )
    assert events == []
    denied = Approval(False)
    monkeypatch.setattr(
        module,
        "_load_operator_config",
        lambda: config(
            retention_approval=lambda conn: denied,
        ),
    )
    assert (
        module.run_rag_worker_operation(operation="retention", limit=3)
        == module._blocked()
    )
    assert events == []
    allowed = Approval()
    monkeypatch.setattr(
        module,
        "_load_operator_config",
        lambda: config(
            retention_approval=lambda conn: allowed,
        ),
    )
    assert module.run_rag_worker_operation(operation="retention", limit=3) == {
        "status": "completed",
        "processed": 2,
    }
    assert allowed.calls == 2
    assert events == [3]


def test_retention_rechecks_operator_policy_and_rejects_autocommit(monkeypatch):
    events = []
    monkeypatch.setattr(
        module,
        "CandidateStagingRepository",
        lambda conn: SimpleNamespace(
            clear_expired=lambda *, limit: events.append(limit) or 1,
        ),
    )

    class Withdrawn(Approval):
        def permitted(self):
            self.calls += 1
            return self.calls == 1

    withdrawn = Withdrawn()
    monkeypatch.setattr(
        module,
        "_load_operator_config",
        lambda: config(
            retention_approval=lambda conn: withdrawn,
        ),
    )
    assert (
        module.run_rag_worker_operation(operation="retention", limit=1)
        == module._blocked()
    )
    assert withdrawn.calls == 2 and events == []

    @contextmanager
    def autocommit():
        yield SimpleNamespace(autocommit=True)

    monkeypatch.setattr(
        module,
        "_load_operator_config",
        lambda: config(
            connect=autocommit,
            retention_approval=lambda conn: Approval(),
        ),
    )
    assert (
        module.run_rag_worker_operation(operation="retention", limit=1)
        == module._blocked()
    )
    assert events == []


def test_intake_does_not_reuse_dispatch_or_retention(monkeypatch):
    monkeypatch.setenv("RAG_AUTO_INTAKE_ENABLED", "true")
    monkeypatch.setenv("RAG_SOURCE_DISCOVERY_ENABLED", "true")
    monkeypatch.setattr(
        module,
        "_load_operator_config",
        lambda: config(
            retention_approval=lambda conn: Approval(),
        ),
    )
    monkeypatch.setattr(module, "_dispatch", lambda *args: 1 / 0)
    monkeypatch.setattr(module, "_retention", lambda *args: 1 / 0)
    assert (
        module.run_rag_worker_operation(
            operation="intake",
            candidate_id=str(uuid4()),
        )
        == module._blocked()
    )


def test_intake_needs_reviewed_factory_not_environment_alone(monkeypatch):
    enable(monkeypatch)
    monkeypatch.setenv("RAG_AUTO_INTAKE_ENABLED", "true")
    monkeypatch.setattr(module, "_load_operator_config", lambda: config())
    monkeypatch.setattr(module, "LiveEgressAttestor", lambda: 1 / 0)
    assert (
        module.run_rag_worker_operation(
            operation="intake",
            candidate_id=str(uuid4()),
        )
        == module._blocked()
    )


def test_intake_fenced_claim_reconcile_finish_and_failure_release(monkeypatch):
    import hashlib

    enable(monkeypatch)
    monkeypatch.setenv("RAG_AUTO_INTAKE_ENABLED", "true")
    candidate_id, job_id = uuid4(), uuid4()
    context = WorkContext(demand(), projection())
    url = "https://example.org/lesson"
    row = dict(
        job_id=job_id,
        exact_job_id=job_id,
        canonical_url=url,
        canonical_url_hash=hashlib.sha256(url.encode()).hexdigest(),
        demand_hash=context.demand.demand_hash,
        subject_id=context.demand.scope.subject_id,
        subject_version=context.demand.scope.subject_version,
        kind="document",
        receipt_handle="receipt.test",
        repo_commit=None,
        repo_path=None,
    )
    events = []
    active = []
    state = {"captured": False, "fail": False}

    class Conn:
        autocommit = False

        def execute(self, sql, args):
            assert "rag_discovery_candidates c" in sql and args == (candidate_id,)
            return SimpleNamespace(fetchone=lambda: row)

    @contextmanager
    def connect():
        conn = Conn()
        active.append(conn)
        try:
            yield conn
        finally:
            active.remove(conn)

    class Attestor:
        pass

    class Leases:
        def __init__(self, conn):
            assert conn in active

        def reconcile_captured(self, *, candidate_id):
            events.append("reconcile")
            return state["captured"]

        def claim(self, **kwargs):
            assert kwargs["candidate_id"] == candidate_id
            assert kwargs["candidate"].url == url
            assert kwargs["candidate"].discovery_receipt_id == "receipt.test"
            assert (
                kwargs["probe"].action == "probe" and kwargs["store"].action == "store"
            )
            assert kwargs["demand"] == context.demand
            events.append("claim")
            return object()

        def finish(self, *, lease, success):
            assert success is True
            events.append("finish")

        def release(self, *, lease):
            events.append("release")

    class Fetcher:
        def __init__(self, **kwargs):
            assert isinstance(kwargs["egress"], Attestor)
            assert kwargs["limits"].expanded_bytes == 1_000_000
            self.live_ready = True

    class Service:
        def __init__(self, **kwargs):
            assert kwargs["staging"].live_fetcher is kwargs["fetcher"]

        async def intake(self, **kwargs):
            assert len(active) == 1  # staging only; claim was committed/closed
            assert kwargs["candidate_id"] == candidate_id
            events.append("fetch")
            if state["fail"]:
                raise RuntimeError("fake fetch failure")
            return uuid4()

    monkeypatch.setattr(module, "LiveEgressAttestor", Attestor)
    monkeypatch.setattr(
        module, "_CurrentIntakeAuthority",
        lambda *args: SimpleNamespace(bind=lambda conn: object()),
    )
    monkeypatch.setattr(module, "current_authority", lambda **kw: object())
    monkeypatch.setattr(
        module, "_select_context", lambda *args: (context, object(), object())
    )
    monkeypatch.setattr(module, "PostgresIntakeLeaseRepository", Leases)
    monkeypatch.setattr(module, "FreshCandidatePolicy", lambda connect: object())
    monkeypatch.setattr(module, "CandidateHopPolicy", lambda **kw: object())
    monkeypatch.setattr(module, "SafeFetcher", Fetcher)
    monkeypatch.setattr(
        module, "CandidateStagingRepository", lambda conn, **kw: SimpleNamespace(**kw)
    )
    monkeypatch.setattr(module, "IntakeService", Service)
    supplied = config(
        connect=connect,
        storage_approval=lambda conn: Approval(),
        intake_attestor=Attestor,
        intake_capture="none",
    )
    monkeypatch.setattr(module, "_load_operator_config", lambda: supplied)
    selector = str(candidate_id)
    assert module.run_rag_worker_operation(
        operation="intake", candidate_id=selector
    ) == {
        "status": "completed",
        "processed": 1,
    }
    assert events == ["reconcile", "claim", "fetch", "finish"] and not active
    events.clear()
    state["captured"] = True
    assert module.run_rag_worker_operation(
        operation="intake", candidate_id=selector
    ) == {
        "status": "no_work",
        "processed": 0,
    }
    assert events == ["reconcile"] and not active
    events.clear()
    state.update(captured=False, fail=True)
    assert (
        module.run_rag_worker_operation(operation="intake", candidate_id=selector)
        == module._blocked()
    )
    assert events == ["reconcile", "claim", "fetch", "release"] and not active
    events.clear()
    row["demand_hash"] = "0" * 64
    assert (
        module.run_rag_worker_operation(operation="intake", candidate_id=selector)
        == module._blocked()
    )
    assert not events and not active


def test_current_intake_authority_reopens_context_and_three_approvals(monkeypatch):
    enable(monkeypatch)
    monkeypatch.setenv("RAG_AUTO_INTAKE_ENABLED", "true")
    context = WorkContext(demand(), projection())
    job_id = uuid4()
    cost, network, storage = Approval(), Approval(), Approval()
    calls = []

    @contextmanager
    def fresh_connection():
        calls.append("open")
        yield SimpleNamespace(autocommit=False)
        calls.append("close")

    trusted = object()
    monkeypatch.setattr(
        module,
        "_select_context",
        lambda *args: (context, object(), SimpleNamespace(resolve=lambda req: trusted)),
    )
    supplied = config(
        connect=fresh_connection,
        cost_approval=lambda conn: cost,
        network_approval=lambda conn: network,
        storage_approval=lambda conn: storage,
    )
    resolver = module._CurrentIntakeAuthority(supplied, job_id, context)
    assert resolver.resolve(object()) is trusted
    assert calls == ["open", "close"]
    assert (cost.calls, network.calls, storage.calls) == (1, 1, 1)
    storage.allowed = False
    assert resolver.resolve(object()) is None
    assert calls == ["open", "close", "open", "close"]
    storage.allowed = True
    monkeypatch.setattr(
        module,
        "_select_context",
        lambda *args: (
            WorkContext(
                demand(), projection().model_copy(update={"actor_id": "stale.actor"})
            ),
            object(),
            SimpleNamespace(resolve=lambda req: trusted),
        ),
    )
    assert resolver.resolve(object()) is None
    monkeypatch.setenv("RAG_AUTO_INTAKE_ENABLED", "false")
    before = len(calls)
    assert resolver.resolve(object()) is None
    assert len(calls) == before  # withdrawn gate denies before connecting


def test_bound_intake_authority_uses_staging_connection(monkeypatch):
    enable(monkeypatch)
    monkeypatch.setenv("RAG_AUTO_INTAKE_ENABLED", "true")
    context = WorkContext(demand(), projection())
    staging_connection = SimpleNamespace(autocommit=False)
    approvals = Approval()
    selected_on = []
    trusted = object()

    def select(conn, *args):
        selected_on.append(conn)
        return context, object(), SimpleNamespace(resolve=lambda req: trusted)

    monkeypatch.setattr(module, "_select_context", select)

    def no_nested_connection():
        raise AssertionError("fresh connection under staging locks")

    supplied = config(
        connect=no_nested_connection,
        cost_approval=lambda conn: approvals,
        network_approval=lambda conn: approvals,
        storage_approval=lambda conn: approvals,
    )
    resolver = module._CurrentIntakeAuthority(supplied, uuid4(), context)
    assert resolver.bind(staging_connection).resolve(object()) is trusted
    assert selected_on == [staging_connection]
    assert approvals.calls == 3
