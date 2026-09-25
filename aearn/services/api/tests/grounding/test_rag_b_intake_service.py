"""B2 coordinator fake-port acceptance; no network or database."""

from __future__ import annotations

from datetime import timedelta
from hashlib import sha256
from uuid import uuid4

import pytest

from app.services.grounding.autonomous.access_policy import AutonomousGates
from app.services.grounding.autonomous.budget import BudgetDenied
from app.services.grounding.autonomous.contracts import ContentCapture, SourceCandidate
from app.services.grounding.autonomous.intake_service import IntakeService
from app.services.grounding.autonomous.intake_leases import IntakeLease
from app.services.grounding.autonomous.retention import StorageGrant
from app.services.grounding.autonomous.safe_fetch import (
    FetchLimits,
    PinnedResponse,
    SafeFetcher,
)
from tests.grounding.rag_material_helpers import (
    Authority,
    H,
    NOW,
    SCOPE,
    access,
    demand,
)

URL = "https://example.org/lesson"
IP = "93.184.215.14"
BODY = b"# Lesson\n\n- list\n\n```python\nprint(1)\n```\n"
CANDIDATE = SourceCandidate(
    kind="document",
    demand_hash=H,
    scope=SCOPE,
    url=URL,
    discovery_receipt_id="search.001",
    capture=ContentCapture(kind="none", captured_bytes=0),
)
GATES = AutonomousGates(discovery=True, intake=True)
ID = uuid4()
LEASE = IntakeLease(ID, uuid4(), "worker.001", 1, NOW + timedelta(minutes=1))


async def chunks():
    yield BODY


class Resolver:
    def __init__(self):
        self.calls = 0

    async def resolve(self, hostname):
        self.calls += 1
        return (IP,)


class Egress:
    async def attest(self, *, host, ip):
        return True


class Connector:
    def __init__(self, after_fetch=None):
        self.calls = 0
        self.after_fetch = after_fetch

    async def open(self, *, host, ip, url, deadline, headers, method="GET"):
        self.calls += 1
        if self.after_fetch:
            self.after_fetch()
        if method == "HEAD":
            async def empty():
                if False:
                    yield b""
            status, reply, body = 200, {"content-type": "text/markdown", "content-length": str(len(BODY))}, empty()
        elif "range" in headers:
            size = int(headers["range"].split("-")[1]) + 1
            async def limited():
                yield BODY[:size]
            status, reply, body = 206, {"content-type": "text/markdown", "content-length": str(size),
                                       "content-range": f"bytes 0-{size - 1}/{len(BODY)}"}, limited()
        else:
            status, reply, body = 200, {"content-type": "text/markdown"}, chunks()
        return PinnedResponse(
            status,
            reply,
            body,
            IP,
            IP,
            host,
            True,
            sent_headers=headers, method=method,
        )

    async def close(self, response):
        pass


class Grants:
    def __init__(self, capture="full", license_id=None):
        self.capture = capture
        self.license_id = license_id
        self.revoked = False

    def resolve(self, candidate, request):
        return StorageGrant(
            demand_hash=H,
            scope=SCOPE,
            discovery_receipt_id="search.001",
            candidate_url_sha256=sha256(URL.encode()).hexdigest(),
            policy_id="policy.001",
            policy_generation=2,
            allowed_capture=self.capture,
            max_captured_bytes=1024,
            license_id=self.license_id,
            retention_until=NOW + timedelta(hours=1),
            revoked=self.revoked,
        )


class Readiness:
    def __init__(self):
        self.calls = 0
        self.allowed = True
        self.observed = []

    def verify(self, *, candidate_id, candidate, lease, demand, authority, now):
        self.calls += 1
        self.observed.append(
            (
                candidate_id,
                candidate.discovery_receipt_id,
                lease.job_id,
                lease.generation,
                authority.budget.root_id,
            )
        )
        return self.allowed


class Stage:
    offline_protocol_test = True

    def __init__(self):
        self.calls = 0
        self.capture = None

    def stage(self, **kwargs):
        self.calls += 1
        self.capture = kwargs["prepared"]
        assert self.capture.request_chain[0] == kwargs["candidate"].url
        assert kwargs["candidate_id"] == ID
        return ID


def rig(*, after_fetch=None, readiness=None, enabled=True):
    dns, connector, preflight, stage = (
        Resolver(),
        Connector(after_fetch),
        readiness or Readiness(),
        Stage(),
    )
    fetcher = SafeFetcher(
        resolver=dns,
        connector=connector,
        egress=Egress(),
        limits=FetchLimits(expanded_bytes=1024),
        offline_protocol_test=True,
    )
    service = IntakeService(
        fetcher=fetcher,
        staging=stage,
        readiness=preflight,
        clock=lambda: NOW,
        offline_protocol_test=enabled,
    )
    return service, dns, connector, preflight, stage


async def run(service, *, capture_kind="full", prefix_bytes=0, **changes):
    args = dict(
        candidate_id=ID,
        candidate=CANDIDATE,
        lease=LEASE,
        demand=demand(),
        probe=access("probe"),
        store=access("store"),
        capture_kind=capture_kind,
        prefix_bytes=prefix_bytes,
        gates=GATES,
        authority_resolver=Authority(),
        storage_resolver=Grants(),
    )
    args.update(changes)
    return await service.intake(**args)


@pytest.mark.asyncio
async def test_full_capture_and_original_receipt_are_bound_offline():
    service, dns, connector, readiness, stage = rig()
    assert await run(service) == ID
    assert connector.calls == dns.calls == 1 and readiness.calls == 4
    assert len(set(readiness.observed)) == 1 and stage.calls == 1
    assert stage.capture.capture_kind == "full"
    assert stage.capture.evidence_level == "offline_protocol_only"
    assert stage.capture.fetched_sha256 == sha256(BODY).hexdigest()
    assert stage.capture.fragments and stage.capture.captured_body == BODY


@pytest.mark.asyncio
async def test_reviewed_storage_license_is_recorded_without_page_attribution():
    service, _, _, _, stage = rig()
    assert await run(service, storage_resolver=Grants(license_id="MIT")) == ID
    assert stage.capture.license_id == "MIT"
    from app.services.grounding.autonomous.provenance import Attribution

    service, _, _, _, stage = rig()
    with pytest.raises(BudgetDenied, match="STORAGE_LICENSE_MISMATCH"):
        await run(
            service, storage_resolver=Grants(license_id="MIT"),
            attribution=Attribution(license_id="Apache-2.0"),
        )
    assert stage.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,prefix", [("none", 0), ("prefix", 8)])
async def test_minimal_probe_modes_use_bounded_transport(kind, prefix):
    service, dns, connector, readiness, stage = rig()
    assert await run(service, capture_kind=kind, prefix_bytes=prefix,
                     storage_resolver=Grants(capture=kind)) == ID
    assert dns.calls == connector.calls == stage.calls == 1 and readiness.calls == 4
    assert stage.capture.capture_kind == kind
    assert stage.capture.fetched_sha256 == sha256(BODY[:prefix] if prefix else b"").hexdigest()
    assert stage.capture.captured_body == (BODY[:prefix] if prefix else None)


@pytest.mark.asyncio
async def test_live_closed_before_any_port():
    service, dns, connector, readiness, stage = rig(enabled=False)
    with pytest.raises(BudgetDenied, match="LIVE_EGRESS_UNVERIFIED"):
        await run(service)
    assert (
        not dns.calls
        and not connector.calls
        and not readiness.calls
        and not stage.calls
    )


@pytest.mark.asyncio
async def test_preflight_denials_do_not_open_connector():
    for changes, reason in (
        ({"gates": AutonomousGates(intake=True)}, "GATE_CLOSED"),
        ({"storage_resolver": Grants(capture="none")}, "STORAGE_SCOPE_DENIED"),
    ):
        service, dns, connector, _, stage = rig()
        with pytest.raises(BudgetDenied, match=reason):
            await run(service, **changes)
        assert not dns.calls and not connector.calls and not stage.calls
    readiness = Readiness()
    readiness.allowed = False
    service, dns, connector, _, stage = rig(readiness=readiness)
    with pytest.raises(BudgetDenied, match="INTAKE_READINESS_UNVERIFIED"):
        await run(service)
    assert (
        readiness.calls == 1
        and not dns.calls
        and not connector.calls
        and not stage.calls
    )


@pytest.mark.asyncio
async def test_revocation_or_lease_loss_after_fetch_never_stages():
    storage = Grants()
    service, _, connector, _, stage = rig(
        after_fetch=lambda: setattr(storage, "revoked", True)
    )
    with pytest.raises(BudgetDenied, match="STORAGE_POLICY_STALE"):
        await run(service, storage_resolver=storage)
    assert connector.calls == 1 and not stage.calls
    readiness = Readiness()
    service, _, connector, _, stage = rig(
        readiness=readiness, after_fetch=lambda: setattr(readiness, "allowed", False)
    )
    with pytest.raises(BudgetDenied, match="INTAKE_READINESS_UNVERIFIED"):
        await run(service)
    assert readiness.calls == 4 and connector.calls == 1 and not stage.calls


@pytest.mark.asyncio
async def test_scope_and_capture_limits_fail_before_network():
    service, dns, connector, readiness, stage = rig()
    for changes in (
        {"store": access("store").model_copy(update={"actor_id": "actor.002"})},
        {
            "candidate": CANDIDATE.model_copy(
                update={
                    "capture": ContentCapture(
                        kind="full", captured_bytes=3, full_sha256=H
                    )
                }
            )
        },
    ):
        with pytest.raises(BudgetDenied, match="INTAKE_SCOPE_INVALID"):
            await run(service, **changes)
    assert (
        not dns.calls
        and not connector.calls
        and not readiness.calls
        and not stage.calls
    )


@pytest.mark.asyncio
async def test_repo_revision_mismatch_does_not_stage():
    repo = CANDIDATE.model_copy(
        update={
            "kind": "repo_file",
            "repo_commit": "a" * 40,
            "repo_path": "src/lesson.md",
        }
    )
    service, _, connector, _, stage = rig()
    with pytest.raises(ValueError, match="REPO_REVISION_UNVERIFIED"):
        await run(service, candidate=repo)
    assert connector.calls == 1 and not stage.calls


class FakeRows:
    def __init__(self, value):
        self.value = value

    def fetchone(self):
        return self.value


class FakeConnection:
    """A closed-world SQL seam, not PostgreSQL acceptance."""

    autocommit = False

    def __init__(self, *, attempt_state="settled", db_now=NOW, stale_lease=False):
        from psycopg.pq import TransactionStatus

        self.info = type(
            "Info", (), {"transaction_status": TransactionStatus.INTRANS}
        )()
        self.attempt_state = attempt_state
        self.db_now = db_now
        self.stale_lease = stale_lease
        self.closed = False
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def transaction(self):
        return self

    def execute(self, sql, params=()):
        self.calls.append(sql)
        if sql.startswith("SELECT clock_timestamp()"):
            return FakeRows({"db_now": self.db_now})
        if "FROM rag_candidate_intake_leases" in sql:
            return FakeRows(None if self.stale_lease else {"candidate_id": ID})
        if "rag_budget_authority_roots" in sql:
            return FakeRows(
                dict(
                    root_id="root.001",
                    delegation_id="delegation.001",
                    delegation_generation=1,
                    delegation_expires_at=access().budget.expires_at,
                    policy_id="policy.001",
                    policy_generation=2,
                    period_key="2026-09",
                    period_start=NOW - timedelta(days=1),
                    period_end=NOW + timedelta(days=1),
                    cap_units=10,
                )
            )
        if "SELECT * FROM rag_discovery_jobs" in sql:
            return FakeRows(
                dict(
                    root_id="root.001",
                    demand_hash=H,
                    subject_id=SCOPE.subject_id,
                    subject_version=SCOPE.subject_version,
                    purpose="main_teaching",
                    policy_id="policy.001",
                    policy_generation=2,
                    delegation_id="delegation.001",
                    delegation_generation=1,
                    state="completed",
                )
            )
        if "FROM rag_discovery_candidates" in sql:
            return FakeRows(
                dict(
                    canonical_url=URL,
                    canonical_url_hash=sha256(URL.encode()).hexdigest(),
                    kind="document",
                    demand_hash=H,
                    subject_id=SCOPE.subject_id,
                    subject_version=SCOPE.subject_version,
                    repo_commit=None,
                    repo_path=None,
                    receipt_handle="search.001",
                    attempt_state=self.attempt_state,
                    reserved_job=LEASE.job_id,
                    reserved_root="root.001",
                    reserved_period="2026-09",
                    reservation_state="settled",
                    job_state="completed",
                )
            )
        raise AssertionError("unexpected SQL")


def test_postgres_readiness_fake_rows_bind_receipt_settlement_root_and_lease():
    from app.services.grounding.autonomous.intake_service import PostgresIntakeReadiness

    snapshot = Authority().resolve(access("store"))
    good, bad = FakeConnection(), FakeConnection(attempt_state="unknown")
    for conn, expected in ((good, True), (bad, False)):
        port = PostgresIntakeReadiness(lambda conn=conn: conn)
        assert (
            port.verify(
                candidate_id=ID,
                candidate=CANDIDATE,
                lease=LEASE,
                demand=demand(),
                authority=snapshot,
                now=NOW,
            )
            is expected
        )
        assert conn.closed and len(conn.calls) == 9


def test_postgres_readiness_uses_database_clock_not_caller_time():
    from app.services.grounding.autonomous.intake_service import PostgresIntakeReadiness

    conn = FakeConnection(db_now=LEASE.expires_at + timedelta(seconds=1))
    assert not PostgresIntakeReadiness(lambda: conn).verify(
        candidate_id=ID, candidate=CANDIDATE, lease=LEASE, demand=demand(),
        authority=Authority().resolve(access("store")), now=NOW,
    )
    assert conn.closed and len(conn.calls) == 3

@pytest.mark.asyncio
@pytest.mark.parametrize("kind,size", [("none", 0), ("prefix", 8)])
async def test_minimal_capture_revocation_after_transport_never_stages(kind, size):
    grant = Grants(capture=kind)
    service, dns, connector, _, stage = rig(
        after_fetch=lambda: setattr(grant, "revoked", True)
    )
    with pytest.raises(BudgetDenied, match="STORAGE_POLICY_STALE"):
        await run(service, capture_kind=kind, prefix_bytes=size,
                  storage_resolver=grant)
    assert dns.calls == connector.calls == 1 and stage.calls == 0


def test_postgres_readiness_denies_stale_candidate_lease_generation():
    from app.services.grounding.autonomous.intake_service import PostgresIntakeReadiness

    conn = FakeConnection(stale_lease=True)
    assert not PostgresIntakeReadiness(lambda: conn).verify(
        candidate_id=ID, candidate=CANDIDATE, lease=LEASE, demand=demand(),
        authority=Authority().resolve(access("store")), now=NOW,
    )
    assert conn.closed
    assert not PostgresIntakeReadiness(lambda: FakeConnection()).verify(
        candidate_id=uuid4(), candidate=CANDIDATE, lease=LEASE, demand=demand(),
        authority=Authority().resolve(access("store")), now=NOW,
    )
