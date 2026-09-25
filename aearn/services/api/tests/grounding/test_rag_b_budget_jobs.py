"""B1 offline authority checks and opt-in disposable PostgreSQL accounting tests."""
from __future__ import annotations

import os
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.services.grounding.autonomous.access_policy import AutonomousGates
from app.services.grounding.autonomous.budget import (
    BudgetDenied, BudgetPolicy, BudgetRepository, current_authority, fingerprint,
)
from app.services.grounding.autonomous.candidate_repository import CandidateRepository, _public_url
from app.services.grounding.autonomous.contracts import ContentCapture, SourceCandidate, SourceDiscoveryDemand
from app.services.grounding.autonomous.jobs import DiscoveryJobRepository
from tests.grounding.rag_material_helpers import Authority, H, NOW, access, demand

GATES = AutonomousGates(discovery=True)

def projection(actor_id: str = "actor.001") -> SourceDiscoveryDemand:
    return SourceDiscoveryDemand(demand_hash=H, scope=demand().scope,
                                 query_terms=("Python list",), actor_id=actor_id,
                                 policy_id="policy.001", policy_generation=2, budget=access().budget)
class Removal:
    def __init__(self, actor_id: str):
        self.actor_id = actor_id

    def authorize(self, actor_id: str) -> bool:
        return actor_id == self.actor_id


class Policy:
    def __init__(self, cap: int = 1, period_key: str = "2026-09"):
        self.cap = cap
        self.period_key = period_key
        self.roots: list[str] = []

    def resolve(self, snapshot):  # type: ignore[no-untyped-def]
        self.roots.append(snapshot.budget.root_id)
        return BudgetPolicy(snapshot.budget.root_id, self.period_key, self.cap,
                            NOW + timedelta(days=10), NOW - timedelta(days=1))


def test_closed_gate_does_not_use_resolver_or_policy() -> None:
    authority = Authority()
    with pytest.raises(BudgetDenied, match="GATE_CLOSED"):
        current_authority(request=access(), demand=demand(), gates=AutonomousGates(), resolver=authority, now=NOW)
    assert authority.calls == 0


def test_current_trusted_snapshot_rejects_spoofed_root_and_full_demand() -> None:
    authority = Authority()
    req = access().model_copy(update={"budget": access().budget.model_copy(update={"root_id": "root.fake"})})
    with pytest.raises(BudgetDenied, match="BUDGET_UNAVAILABLE"):
        current_authority(request=req, demand=demand(), gates=GATES, resolver=authority, now=NOW)
    with pytest.raises(BudgetDenied, match="POLICY_SCOPE_STALE"):
        current_authority(request=access(), demand=demand().model_copy(update={"node_ref": "node.other"}),
                          gates=GATES, resolver=authority, now=NOW)


def test_candidate_url_is_location_metadata_not_fetch_authorization() -> None:
    assert _public_url("https://Example.org/lesson") == "https://example.org/lesson"
    for url in ("https://user:pass@example.org/", "https://example.org/?token=secret",
                "https://example.org/#secret", "http://example.org/", "https://example.org:443/"):
        with pytest.raises(BudgetDenied, match="UNSAFE_CANDIDATE_LOCATION"):
            _public_url(url)


@pytest.fixture(scope="module")
def isolated_db():  # type: ignore[no-untyped-def]
    dsn = os.environ.get("AEARN_RAG_B_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("B1 PostgreSQL not executed: explicitly confirm disposable AEARN_RAG_B_TEST_DATABASE_URL")
    name = urlsplit(dsn).path.lstrip("/")
    if not name.startswith("aearn_rag260_"):
        pytest.fail("B1 tests refuse non-aearn_rag260_ database")
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        actual = conn.execute("SELECT current_database() AS name").fetchone()["name"]
        if actual != name:
            pytest.fail("B1 current_database() mismatch")
        present = conn.execute("SELECT to_regclass('rag_budget_periods') AS name").fetchone()["name"]
        if present is None:
            pytest.fail("B1 schema not pre-applied by main session")
    return dsn


@pytest.fixture()
def conn(isolated_db):  # type: ignore[no-untyped-def]
    with psycopg.connect(isolated_db, row_factory=dict_row) as connection:
        yield connection
        connection.rollback()


def _setup(conn, key: str):  # type: ignore[no-untyped-def]
    jobs = DiscoveryJobRepository(conn)
    job = jobs.enqueue(request=access(), demand=demand(), gates=GATES, resolver=Authority(),
                       operation_key=key, request_hash=fingerprint(key, H), projection=projection(), now=NOW)
    lease = jobs.claim(job_id=job, request=access(), demand=demand(), gates=GATES,
                       resolver=Authority(), owner_id="worker.001", now=NOW)
    assert lease is not None
    return jobs, job, lease


def test_reservation_attempt_unknown_replay_and_reconciliation(conn) -> None:  # type: ignore[no-untyped-def]
    key = f"job.{uuid4().hex}"
    jobs, job, lease = _setup(conn, key)
    repo = BudgetRepository(conn)
    policy = Policy(cap=1)
    kwargs = dict(request=access(), demand=demand(), gates=GATES, resolver=Authority(),
                  policy_resolver=policy, job_id=job, operation_key=f"reserve.{key}",
                  request_hash=fingerprint(key, "search"), units=1, now=NOW)
    reserve = repo.reserve(**kwargs)
    assert reserve.allowed and reserve.reservation_id
    assert repo.reserve(**kwargs).reservation_id == reserve.reservation_id
    assert policy.roots == ["root.001", "root.001"]
    with pytest.raises(BudgetDenied, match="RESERVATION_CONFLICT"):
        repo.reserve(**{**kwargs, "request_hash": "b" * 64})
    attempt = repo.record_attempt(reservation_id=reserve.reservation_id, attempt_key=f"attempt.{key}",
                                  lease=lease, now=NOW)
    replay = repo.record_attempt(reservation_id=reserve.reservation_id, attempt_key=f"attempt.{key}",
                                 lease=lease, now=NOW)
    assert replay.attempt_id == attempt.attempt_id and not replay.created
    dispatch = dict(projection=projection(), request=access(), demand=demand(), gates=GATES,
                    resolver=Authority(), lease=lease, reservation_id=reserve.reservation_id,
                    attempt_id=attempt.attempt_id, now=NOW)
    assert repo.take_dispatch(**dispatch)
    assert not BudgetRepository(conn).take_dispatch(**dispatch)  # restart/replay cannot send again
    assert repo.settle(attempt_id=attempt.attempt_id, lease=lease, usage=None,
                       receipt_hash=None, now=NOW).state == "unknown"
    _, second, _ = _setup(conn, f"second.{uuid4().hex}")
    denied = repo.reserve(**{**kwargs, "job_id": second, "operation_key": f"reserve.{uuid4().hex}"})
    assert denied.reason == "CAP_EXHAUSTED"
    assert repo.settle(attempt_id=attempt.attempt_id, lease=lease, usage=1,
                       receipt_hash="c" * 64, now=NOW).charged_units == 1
    assert repo.settle(attempt_id=attempt.attempt_id, lease=lease, usage=1,
                       receipt_hash="c" * 64, now=NOW).state == "settled"
    with pytest.raises(BudgetDenied, match="SETTLEMENT_CONFLICT"):
        repo.settle(attempt_id=attempt.attempt_id, lease=lease, usage=0, receipt_hash="d" * 64, now=NOW)
    candidates = CandidateRepository(conn)
    receipt_id = candidates.record_receipt(lease=lease, request=access(), demand=demand(),
                                            gates=GATES, resolver=Authority(), attempt_id=attempt.attempt_id,
                                            receipt_handle=f"search.{uuid4().hex}", result_code="SEARCH_OK",
                                            response_hash="d" * 64, now=NOW)
    handle = conn.execute("SELECT receipt_handle FROM rag_discovery_receipts WHERE id=%s", (receipt_id,)).fetchone()["receipt_handle"]
    item = SourceCandidate(kind="document", demand_hash=H, scope=demand().scope,
                           url="https://docs.example.org/lesson", discovery_receipt_id=handle,
                           capture=ContentCapture(kind="none", captured_bytes=0))
    candidate_id = candidates.record_candidate(lease=lease, request=access(), demand=demand(),
                                                gates=GATES, resolver=Authority(), candidate=item, now=NOW)
    assert candidates.record_candidate(lease=lease, request=access(), demand=demand(),
                                       gates=GATES, resolver=Authority(), candidate=item, now=NOW) == candidate_id
    jobs.complete(lease=lease, request=access(), demand=demand(), gates=GATES,
                  resolver=Authority(), now=NOW, success=True)
    with pytest.raises(BudgetDenied, match="LEASE_STALE"):
        candidates.record_candidate(lease=lease, request=access(), demand=demand(),
                                    gates=GATES, resolver=Authority(), candidate=item, now=NOW)


def test_lease_fence_and_private_unlink(conn) -> None:  # type: ignore[no-untyped-def]
    jobs, job, old = _setup(conn, f"job.{uuid4().hex}")
    new = jobs.claim(job_id=job, request=access(), demand=demand(), gates=GATES,
                     resolver=Authority(), owner_id="worker.002", now=NOW + timedelta(seconds=61))
    assert new is not None and new.generation == old.generation + 1
    with pytest.raises(BudgetDenied, match="LEASE_STALE"):
        jobs.complete(lease=old, request=access(), demand=demand(), gates=GATES,
                      resolver=Authority(), now=NOW + timedelta(seconds=61), success=True)
    assert jobs.unlink_ref(job_id=job, actor_id="actor.001", authority=Removal("actor.001"))
    assert conn.execute("SELECT count(*) AS n FROM rag_discovery_jobs WHERE id=%s", (job,)).fetchone()["n"] == 1



def test_unknown_after_lost_lease_overage_is_charged_and_never_released(conn) -> None:  # type: ignore[no-untyped-def]
    key = f"job.{uuid4().hex}"
    jobs, job, old = _setup(conn, key)
    budget = BudgetRepository(conn)
    policy = Policy(cap=1)
    reserve = budget.reserve(request=access(), demand=demand(), gates=GATES, resolver=Authority(),
                             policy_resolver=policy, job_id=job, operation_key=f"reserve.{key}",
                             request_hash=fingerprint(key, "overage"), units=1, now=NOW)
    assert reserve.reservation_id is not None
    attempt = budget.record_attempt(reservation_id=reserve.reservation_id,
                                    attempt_key=f"attempt.{key}", lease=old, now=NOW)
    assert attempt.created
    assert budget.take_dispatch(projection=projection(), request=access(), demand=demand(),
                                gates=GATES, resolver=Authority(), lease=old,
                                reservation_id=reserve.reservation_id, attempt_id=attempt.attempt_id, now=NOW)
    budget.mark_unknown(attempt_id=attempt.attempt_id, error_code="PROVIDER_TIMEOUT", now=NOW)
    with pytest.raises(BudgetDenied, match="LEASE_STALE"):
        budget.settle(attempt_id=attempt.attempt_id, lease=old, usage=2,
                      receipt_hash="e" * 64, now=NOW + timedelta(seconds=61))
    new = jobs.claim(job_id=job, request=access(), demand=demand(), gates=GATES,
                     resolver=Authority(), owner_id="worker.002", now=NOW + timedelta(seconds=61))
    assert new is not None
    settled = budget.settle(attempt_id=attempt.attempt_id, lease=new, usage=2,
                            receipt_hash="e" * 64, now=NOW + timedelta(seconds=61))
    assert settled.charged_units == 2 and settled.overage_units == 1
    _, another, _ = _setup(conn, f"job.{uuid4().hex}")
    denied = budget.reserve(request=access(), demand=demand(), gates=GATES, resolver=Authority(),
                            policy_resolver=policy, job_id=another,
                            operation_key=f"reserve.{uuid4().hex}", request_hash="f" * 64,
                            units=1, now=NOW + timedelta(seconds=61))
    assert denied.reason == "CAP_EXHAUSTED"
    row = conn.execute("SELECT state,settled_units FROM rag_budget_reservations WHERE id=%s",
                       (reserve.reservation_id,)).fetchone()
    assert row == {"state": "settled", "settled_units": 2}


def test_persistent_root_is_default_off_and_exact_snapshot_bound(conn) -> None:  # type: ignore[no-untyped-def]
    from app.services.grounding.autonomous.budget import PostgresBudgetPolicyResolver

    from app.services.grounding.autonomous.access_policy import AuthoritySnapshot

    root = access().budget.model_copy(update={"root_id": f"root.test.{uuid4().hex}"})
    scoped_request = access().model_copy(update={"budget": root})
    scoped_projection = projection().model_copy(update={"budget": root})

    class RootAuthority:
        def resolve(self, request):  # type: ignore[no-untyped-def]
            original = Authority().resolve(request)
            return AuthoritySnapshot.model_validate(
                original.model_copy(update={"budget": root}).model_dump(mode="python")
            )

    job = DiscoveryJobRepository(conn).enqueue(
        request=scoped_request, demand=demand(), gates=GATES, resolver=RootAuthority(),
        operation_key=f"job.{uuid4().hex}", request_hash="a" * 64,
        projection=scoped_projection, now=NOW,
    )
    conn.execute(
        "INSERT INTO rag_budget_authority_roots(root_id,delegation_id,delegation_generation,"
        "delegation_expires_at,policy_id,policy_generation,period_key,period_start,period_end,cap_units) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (root.root_id, root.delegation_id, root.generation, root.expires_at,
         "policy.001", 2, "2026-09", NOW - timedelta(days=1), NOW + timedelta(days=10), 1),
    )
    repo = BudgetRepository(conn)
    kwargs = dict(request=scoped_request, demand=demand(), gates=GATES, resolver=RootAuthority(),
                  policy_resolver=PostgresBudgetPolicyResolver(conn), job_id=job,
                  operation_key=f"reserve.{uuid4().hex}", request_hash="e" * 64, units=1, now=NOW)
    with pytest.raises(BudgetDenied, match="BUDGET_POLICY_UNAVAILABLE"):
        repo.reserve(**kwargs)
    conn.execute("UPDATE rag_budget_authority_roots SET enabled=true WHERE root_id=%s", (root.root_id,))
    assert repo.reserve(**kwargs).allowed
    conn.execute("UPDATE rag_budget_authority_roots SET delegation_generation=2 WHERE root_id=%s", (root.root_id,))
    with pytest.raises(BudgetDenied, match="BUDGET_POLICY_UNAVAILABLE"):
        repo.reserve(**{**kwargs, "operation_key": f"reserve.{uuid4().hex}"})



def test_two_actors_share_job_but_private_unlink_is_scoped(conn) -> None:  # type: ignore[no-untyped-def]
    from app.services.grounding.autonomous.access_policy import AuthoritySnapshot

    class MultiActor:
        def resolve(self, request):  # type: ignore[no-untyped-def]
            original = Authority().resolve(request)
            return AuthoritySnapshot.model_validate(
                original.model_copy(update={"actor_id": request.actor_id}).model_dump(mode="python")
            )

    repo = DiscoveryJobRepository(conn)
    key = f"job.{uuid4().hex}"
    digest = fingerprint(key, H)
    first = repo.enqueue(request=access(), demand=demand(), gates=GATES, resolver=MultiActor(),
                         operation_key=key, request_hash=digest, projection=projection(), now=NOW)
    second_request = access().model_copy(update={"actor_id": "actor.002"})
    second = repo.enqueue(request=second_request, demand=demand(), gates=GATES, resolver=MultiActor(),
                          operation_key=key, request_hash=digest, projection=projection("actor.002"), now=NOW)
    assert first == second
    with pytest.raises(BudgetDenied, match="REMOVAL_AUTHORITY_MISSING"):
        repo.unlink_actor(actor_id="actor.001", authority=None)
    with pytest.raises(BudgetDenied, match="REMOVAL_DENIED"):
        repo.unlink_actor(actor_id="actor.002", authority=Removal("actor.001"))
    assert repo.unlink_ref(job_id=first, actor_id="actor.001", authority=Removal("actor.001"))
    assert not repo.unlink_ref(job_id=first, actor_id="actor.001", authority=Removal("actor.001"))
    links = conn.execute("SELECT actor_id FROM rag_discovery_job_refs WHERE job_id=%s", (first,)).fetchall()
    assert links == [{"actor_id": "actor.002"}]
    assert repo.unlink_actor(actor_id="actor.002", authority=Removal("actor.002")) == 1
    assert conn.execute("SELECT count(*) AS n FROM rag_discovery_jobs WHERE id=%s", (first,)).fetchone()["n"] == 1



def test_two_connections_dispatch_cas_once_after_restart(isolated_db) -> None:  # type: ignore[no-untyped-def]
    """Intentional append-only audit rows live only in the explicit disposable DB."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    key = f"job.{uuid4().hex}"
    with psycopg.connect(isolated_db, row_factory=dict_row) as first:
        _, job, lease = _setup(first, key)
        budget = BudgetRepository(first)
        reserved = budget.reserve(request=access(), demand=demand(), gates=GATES, resolver=Authority(),
                                  policy_resolver=Policy(cap=1_000_000, period_key=f"test.{uuid4().hex}"), job_id=job,
                                  operation_key=f"reserve.{key}", request_hash=fingerprint(key, "concurrent"),
                                  units=1, now=NOW)
        assert reserved.reservation_id is not None
        attempt = budget.record_attempt(reservation_id=reserved.reservation_id,
                                        attempt_key=f"attempt.{key}", lease=lease, now=NOW)
        first.commit()
    start = Event()

    def take() -> bool:
        with psycopg.connect(isolated_db, row_factory=dict_row) as connection:
            start.wait(timeout=5)
            result = BudgetRepository(connection).take_dispatch(
                projection=projection(), request=access(), demand=demand(), gates=GATES,
                resolver=Authority(), lease=lease, reservation_id=reserved.reservation_id,
                attempt_id=attempt.attempt_id, now=NOW,
            )
            connection.commit()  # CAS must commit before any hypothetical provider I/O.
            return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(take), pool.submit(take)]
        start.set()
        assert sorted(f.result(timeout=10) for f in futures) == [False, True]
    with psycopg.connect(isolated_db, row_factory=dict_row) as restarted:
        assert not BudgetRepository(restarted).take_dispatch(
            projection=projection(), request=access(), demand=demand(), gates=GATES,
            resolver=Authority(), lease=lease, reservation_id=reserved.reservation_id,
            attempt_id=attempt.attempt_id, now=NOW,
        )
        BudgetRepository(restarted).mark_unknown(attempt_id=attempt.attempt_id,
                                                 error_code="TEST_NO_PROVIDER_CALL", now=NOW)
        restarted.commit()


def test_postgres_work_atomic_discovery_lifecycle(isolated_db) -> None:  # type: ignore[no-untyped-def]
    """Opt-in disposable PG: synthetic verified usage, never a live Tavily claim."""
    from app.services.grounding.autonomous.access_policy import AuthoritySnapshot
    from app.services.grounding.autonomous.budget import PostgresBudgetPolicyResolver
    from app.services.grounding.autonomous.discovery_broker import SearchSettlement, _query_operation_id
    from app.services.grounding.autonomous.discovery_work import PostgresDiscoveryWork, WorkContext

    class Context:
        def __init__(self, value: WorkContext) -> None:
            self.value = value

        def resolve_issued(self, full, issued):  # type: ignore[no-untyped-def]
            return self.value if (full, issued) == (self.value.demand, self.value.projection) else None

        def resolve_job(self, job_id):  # type: ignore[no-untyped-def]
            return self.value

    class Permission:
        def permitted(self) -> bool:
            return True

    class VerifiedUsage:
        def __init__(self) -> None:
            self.receipts: dict[object, tuple[str, int]] = {}

        def verify_usage(self, attempt_id, receipt_id, units) -> bool:  # type: ignore[no-untyped-def]
            return self.receipts.get(attempt_id) == (receipt_id, units)

        def verify_account_exhausted(self, attempt_id, receipt_id) -> bool:  # type: ignore[no-untyped-def]
            return False

    period_key = f"test.{uuid4().hex}"
    root = access().budget.model_copy(update={"root_id": f"root.test.{uuid4().hex}"})

    class RootAuthority:
        def resolve(self, request):  # type: ignore[no-untyped-def]
            original = Authority().resolve(request)
            return AuthoritySnapshot.model_validate(
                original.model_copy(update={"budget": root}).model_dump(mode="python")
            )
    with psycopg.connect(isolated_db, row_factory=dict_row) as connection:
        # The disposable test deliberately provisions authority; bootstrap does not.
        with connection.transaction():
            connection.execute(
                "INSERT INTO rag_budget_authority_roots(root_id,delegation_id,delegation_generation,"
                "delegation_expires_at,policy_id,policy_generation,period_key,period_start,period_end,"
                "cap_units,enabled) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true) "
                "ON CONFLICT (root_id) DO UPDATE SET period_key=EXCLUDED.period_key,"
                "period_start=EXCLUDED.period_start,period_end=EXCLUDED.period_end,"
                "cap_units=EXCLUDED.cap_units,enabled=true",
                (root.root_id, root.delegation_id, root.generation, root.expires_at,
                 "policy.001", 2, period_key, NOW - timedelta(days=1), NOW + timedelta(days=10), 2),
            )
        issued = projection().model_copy(update={"budget": root})
        verified = VerifiedUsage()
        context = Context(WorkContext(demand(), issued))
        work = PostgresDiscoveryWork(
            conn=connection, authority=RootAuthority(), context=context,
            policy=PostgresBudgetPolicyResolver(connection),
            gates=lambda: GATES, permission=Permission(), usage=verified,
            owner_id="worker.001", clock=lambda: NOW,
        )
        decision = work.claim_or_reuse(demand(), issued, _query_operation_id(demand(), issued))
        assert decision.status == "claimed" and decision.claim is not None
        claim = decision.claim
        ticket = work.prepare_attempt(claim)
        assert ticket is not None
        assert work.take_dispatch(issued, claim, ticket)
        # The first dispatch is committed; a new process/connection sees the CAS.
        with psycopg.connect(isolated_db, row_factory=dict_row) as restarted:
            assert restarted.execute(
                "SELECT state FROM rag_budget_attempts WHERE id=%s",
                (UUID(hex=ticket.attempt_id.removeprefix("attempt.")),),
            ).fetchone()["state"] == "dispatched"
        assert not work.take_dispatch(issued, claim, ticket)
        attempt_id = UUID(hex=ticket.attempt_id.removeprefix("attempt."))
        verified.receipts[attempt_id] = ("usage.test_verified", 1)
        lead = SourceCandidate(
            kind="landing", demand_hash=H, scope=demand().scope,
            url="https://example.org/lesson", discovery_receipt_id=ticket.attempt_id,
            capture=ContentCapture(kind="none", captured_bytes=0),
        )
        assert not work.record_outcome(
            claim, ticket, SearchSettlement(status="completed", usage_units=1,
                                            usage_receipt_id="usage.forged"), (lead,),
        )
        assert work.record_outcome(
            claim, ticket, SearchSettlement(status="completed", usage_units=1,
                                            usage_receipt_id="usage.test_verified"), (lead,),
        )
        assert work.claim_or_reuse(demand(), issued, _query_operation_id(demand(), issued)).status == "existing"
        with connection.transaction():
            result = connection.execute(
                "SELECT j.state AS job_state,r.state AS reservation_state,r.settled_units,a.state AS attempt_state,"
                "count(DISTINCT dr.id) AS receipts,count(DISTINCT c.id) AS candidates "
                "FROM rag_discovery_jobs j JOIN rag_budget_reservations r ON r.job_id=j.id "
                "JOIN rag_budget_attempts a ON a.reservation_id=r.id "
                "LEFT JOIN rag_discovery_receipts dr ON dr.attempt_id=a.id "
                "LEFT JOIN rag_discovery_candidates c ON c.discovery_receipt_id=dr.id "
                "WHERE j.id=%s GROUP BY j.id,r.id,a.id",
                (UUID(hex=claim.job_id.removeprefix("job.")),),
            ).fetchone()
        assert result == dict(job_state="completed", reservation_state="settled", settled_units=1,
                              attempt_state="settled", receipts=1, candidates=1)

        # A separately billed query with zero leads must settle and terminalize,
        # not leave a permanently leased job with an already-settled attempt.
        empty_projection = issued.model_copy(update={"query_terms": ("Python", "dict")})
        context.value = WorkContext(demand(), empty_projection)
        empty = work.claim_or_reuse(demand(), empty_projection,
                                    _query_operation_id(demand(), empty_projection))
        assert empty.status == "claimed" and empty.claim is not None
        empty_ticket = work.prepare_attempt(empty.claim)
        assert empty_ticket is not None and work.take_dispatch(empty_projection, empty.claim, empty_ticket)
        verified.receipts[UUID(hex=empty_ticket.attempt_id.removeprefix("attempt."))] = ("usage.empty_verified", 1)
        assert work.record_outcome(
            empty.claim, empty_ticket,
            SearchSettlement(status="completed", usage_units=1, usage_receipt_id="usage.empty_verified"), (),
        )
        with connection.transaction():
            empty_row = connection.execute(
                "SELECT j.state,r.state AS reservation_state,r.settled_units,"
                "(SELECT count(*) FROM rag_discovery_candidates WHERE job_id=j.id) AS candidates "
                "FROM rag_discovery_jobs j JOIN rag_budget_reservations r ON r.job_id=j.id WHERE j.id=%s",
                (UUID(hex=empty.claim.job_id.removeprefix("job.")),),
            ).fetchone()
        assert empty_row == dict(state="failed", reservation_state="settled", settled_units=1,
                                 candidates=0)
