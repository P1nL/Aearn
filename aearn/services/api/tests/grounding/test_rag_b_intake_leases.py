"""Candidate intake fencing on an explicitly approved disposable PostgreSQL database.

No provider, network, dotenv, or bootstrap is used. Rows are unique audit fixtures
in the disposable database; immutable B1 ledger rows are deliberately not deleted.
"""

from __future__ import annotations

import hashlib
import os
from queue import Queue
from threading import Event, Thread
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.services.grounding.autonomous.access_policy import AutonomousGates
from app.services.grounding.autonomous.budget import BudgetDenied
from app.services.grounding.autonomous.contracts import (
    ContentCapture,
    RagBudgetDelegation,
    SourceCandidate,
)
from app.services.grounding.autonomous.intake_leases import (
    PostgresIntakeLeaseRepository,
    require_live_intake_lease,
)
from app.services.grounding.autonomous.jobs import DiscoveryJobRepository
from tests.grounding.rag_material_helpers import Authority, H, access, demand

GATES = AutonomousGates(discovery=True, intake=True)
URL = "https://example.org/docs/lesson"


@pytest.fixture(scope="module")
def dsn() -> str:
    value = os.environ.get("AEARN_RAG_B_TEST_DATABASE_URL")
    if not value:
        pytest.skip("intake lease PG not executed: explicit disposable DB URL required")
    expected = urlsplit(value).path.lstrip("/")
    if not expected.startswith("aearn_rag260_"):
        pytest.fail("intake lease tests refuse a non-aearn_rag260_ database")
    with psycopg.connect(value, row_factory=dict_row) as conn:
        actual = conn.execute("SELECT current_database() AS name").fetchone()
        schema = conn.execute(
            "SELECT to_regclass('rag_candidate_intake_leases') AS name"
        ).fetchone()
        if (
            actual is None
            or actual["name"] != expected
            or schema is None
            or schema["name"] is None
        ):
            pytest.fail("intake lease schema must be pre-applied by schema owner")
    return value


class AuthorityFor(Authority):
    def __init__(self, root: str, policy: str, until: datetime):
        super().__init__()
        self.root, self.policy, self.until = root, policy, until
        self.revoked = False

    def resolve(self, request):  # type: ignore[no-untyped-def]
        snapshot = super().resolve(request)
        return snapshot.model_copy(
            update={
                "budget": request.budget,
                "policy_id": self.policy,
                "authorized": not self.revoked,
            }
        )


def seeded(dsn: str):  # type: ignore[no-untyped-def]
    key = uuid4().hex
    now = datetime.now(timezone.utc)
    until = now + timedelta(days=2)
    root, policy = f"root.{key}", f"policy.{key}"
    budget = RagBudgetDelegation(
        root_id=root, delegation_id=f"delegation.{key}", generation=1, expires_at=until
    )
    probe = access("probe").model_copy(update={"budget": budget, "policy_id": policy})
    store = probe.model_copy(update={"action": "store"})
    authority = AuthorityFor(root, policy, until)
    handle = f"search.{key}"
    candidate = SourceCandidate(
        kind="document",
        demand_hash=H,
        scope=demand().scope,
        url=URL,
        discovery_receipt_id=handle,
        capture=ContentCapture(kind="none", captured_bytes=0),
    )
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        conn.execute(
            "INSERT INTO rag_budget_authority_roots(root_id,delegation_id,delegation_generation,"
            "delegation_expires_at,policy_id,policy_generation,period_key,period_start,period_end,"
            "cap_units,enabled) VALUES (%s,%s,1,%s,%s,2,%s,%s,%s,5,true)",
            (
                root,
                budget.delegation_id,
                until,
                policy,
                key,
                now - timedelta(days=1),
                until,
            ),
        )
        conn.execute(
            "INSERT INTO rag_budget_periods(root_id,period_key,cap_units,period_end) "
            "VALUES (%s,%s,5,%s)",
            (root, key, until),
        )
        job = conn.execute(
            "INSERT INTO rag_discovery_jobs(operation_key,request_hash,query_hash,demand_hash,"
            "subject_id,subject_version,purpose,policy_id,policy_generation,root_id,"
            "delegation_id,delegation_generation,state,terminal_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,2,%s,%s,1,'completed',%s) RETURNING id",
            (
                f"job.{key}",
                "a" * 64,
                "b" * 64,
                H,
                demand().scope.subject_id,
                demand().scope.subject_version,
                demand().purpose,
                policy,
                root,
                budget.delegation_id,
                now,
            ),
        ).fetchone()["id"]
        reservation = conn.execute(
            "INSERT INTO rag_budget_reservations(root_id,period_key,operation_key,request_hash,"
            "job_id,reserved_units,state,settled_units,settlement_receipt_hash) "
            "VALUES (%s,%s,%s,%s,%s,1,'settled',1,%s) RETURNING id",
            (root, key, f"reserve.{key}", "c" * 64, job, "d" * 64),
        ).fetchone()["id"]
        attempt = conn.execute(
            "INSERT INTO rag_budget_attempts(reservation_id,job_id,attempt_key,state,"
            "dispatch_owner_id,dispatch_generation,dispatched_at) "
            "VALUES (%s,%s,%s,'settled','worker.001',1,%s) RETURNING id",
            (reservation, job, f"attempt.{key}", now),
        ).fetchone()["id"]
        receipt = conn.execute(
            "INSERT INTO rag_discovery_receipts(job_id,attempt_id,receipt_handle,result_code,"
            "response_hash) VALUES (%s,%s,%s,'SEARCH_OK',%s) RETURNING id",
            (job, attempt, handle, "e" * 64),
        ).fetchone()["id"]
        import hashlib

        candidate_id = conn.execute(
            "INSERT INTO rag_discovery_candidates(job_id,discovery_receipt_id,canonical_url,"
            "canonical_url_hash,kind,demand_hash,subject_id,subject_version) "
            "VALUES (%s,%s,%s,%s,'document',%s,%s,%s) RETURNING id",
            (
                job,
                receipt,
                URL,
                hashlib.sha256(URL.encode()).hexdigest(),
                H,
                demand().scope.subject_id,
                demand().scope.subject_version,
            ),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO rag_candidate_access_policies(policy_id,current_generation,"
            "expires_at,enabled) VALUES (%s,2,%s,true)",
            (policy, until),
        )
        conn.execute(
            "INSERT INTO rag_candidate_access_rules(policy_id,generation,host,path_prefix,"
            "probe_allowed,store_allowed,allowed_capture,max_captured_bytes,license_id,"
            "valid_until,retention_until) VALUES (%s,2,'example.org','/docs',true,true,"
            "'prefix',64,'CC-BY-4.0',%s,%s)",
            (policy, until, until),
        )
    return candidate_id, job, candidate, probe, store, authority, policy


def claim(repo, fixture, *, owner="worker.001", candidate_id=None, lease_seconds=60):  # type: ignore[no-untyped-def]
    cid, _, item, probe, store, authority, _ = fixture
    return repo.claim(
        candidate_id=cid if candidate_id is None else candidate_id,
        candidate=item,
        probe=probe,
        store=store,
        demand=demand(),
        gates=GATES,
        authority_resolver=authority,
        capture_kind="prefix",
        planned_bytes=32,
        owner_id=owner,
        lease_seconds=lease_seconds,
    )


def test_competing_claim_release_generation_capture_and_completed_job(dsn: str) -> None:
    fixture = seeded(dsn)
    cid, job, _, _, _, _, _ = fixture
    with (
        psycopg.connect(dsn, row_factory=dict_row) as first,
        psycopg.connect(dsn, row_factory=dict_row) as second,
    ):
        repo = PostgresIntakeLeaseRepository(first)
        lease = claim(repo, fixture)
        assert lease is not None and (
            lease.candidate_id,
            lease.job_id,
            lease.generation,
        ) == (cid, job, 1)
        first.commit()
        assert (
            claim(PostgresIntakeLeaseRepository(second), fixture, owner="worker.002")
            is None
        )
        assert (
            DiscoveryJobRepository(second).claim(
                job_id=job,
                request=fixture[3].model_copy(update={"action": "discover"}),
                demand=demand(),
                gates=GATES,
                resolver=fixture[5],
                owner_id="worker.002",
                now=datetime.now(timezone.utc),
            )
            is None
        )
        assert (
            second.execute(
                "SELECT state FROM rag_discovery_jobs WHERE id=%s", (job,)
            ).fetchone()["state"]
            == "completed"
        )
        second.commit()  # A rejected contender must release its read/row locks.
        with pytest.raises(BudgetDenied, match="INTAKE_CAPTURE_MISSING"):
            repo.finish(lease=lease, success=True)
        repo.release(lease=lease)
        first.commit()
        newer = claim(
            PostgresIntakeLeaseRepository(second), fixture, owner="worker.002"
        )
        assert newer is not None and newer.generation == 2
        second.commit()
        with pytest.raises(BudgetDenied, match="INTAKE_LEASE_STALE"):
            repo.release(lease=lease)
        with first.transaction():
            require_live_intake_lease(first, newer, datetime.now(timezone.utc))
        first.commit()  # Release the lease-row lock before the second connection finishes.
        second.execute(
            "INSERT INTO rag_candidate_captures(candidate_id,job_id,evidence_level,final_url,"
            "request_chain,chain_sha256,media_type,fetched_sha256,capture_kind,"
            "captured_bytes,policy_id,policy_generation,retention_until) "
            "VALUES (%s,%s,'offline_protocol_only',%s,%s::jsonb,%s,'text/plain',%s,"
            "'none',0,%s,2,%s)",
            (
                cid,
                job,
                URL,
                '["https://example.org/docs/lesson"]',
                "f" * 64,
                "a" * 64,
                fixture[6],
                datetime.now(timezone.utc) + timedelta(days=1),
            ),
        )
        PostgresIntakeLeaseRepository(second).finish(lease=newer, success=True)
        second.commit()
        assert claim(repo, fixture) is None
        with pytest.raises(BudgetDenied, match="INTAKE_LEASE_STALE"):
            repo.release(lease=newer)


def test_revocation_malicious_id_and_no_new_dispatch(dsn: str) -> None:
    fixture = seeded(dsn)
    cid, job, item, probe, store, authority, policy = fixture
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        repo = PostgresIntakeLeaseRepository(conn)
        assert claim(repo, fixture, candidate_id=uuid4()) is None
        with pytest.raises(BudgetDenied, match="INTAKE_CANDIDATE_STALE"):
            repo.claim(
                candidate_id=cid,
                candidate=item.model_copy(update={"url": "https://evil.example.org/"}),
                probe=probe,
                store=store,
                demand=demand(),
                gates=GATES,
                authority_resolver=authority,
                capture_kind="prefix",
                planned_bytes=32,
                owner_id="worker.001",
            )
        authority.revoked = True
        with pytest.raises(BudgetDenied, match="ACTOR_ACTION_DENIED"):
            claim(repo, fixture)
        authority.revoked = False
        conn.execute(
            "UPDATE rag_candidate_access_policies SET enabled=false,revoked_at=clock_timestamp() WHERE policy_id=%s",
            (policy,),
        )
        with pytest.raises(BudgetDenied, match="DISCOVERY_POLICY_DENIED"):
            claim(repo, fixture)
        assert (
            conn.execute(
                "SELECT state FROM rag_discovery_jobs WHERE id=%s", (job,)
            ).fetchone()["state"]
            == "completed"
        )
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM rag_candidate_intake_leases WHERE candidate_id=%s",
                (cid,),
            ).fetchone()["n"]
            == 0
        )


def test_expired_claim_reclaimed_without_reopening_discovery(dsn: str) -> None:
    fixture = seeded(dsn)
    cid, job, *_ = fixture
    with (
        psycopg.connect(dsn, row_factory=dict_row) as first,
        psycopg.connect(dsn, row_factory=dict_row) as second,
    ):
        old = claim(PostgresIntakeLeaseRepository(first), fixture, lease_seconds=1)
        assert old is not None
        first.commit()
        time.sleep(1.2)  # The DB clock, not a caller-supplied timestamp, expires it.
        new = claim(PostgresIntakeLeaseRepository(second), fixture, owner="worker.002")
        assert new is not None and new.generation == old.generation + 1
        second.commit()
        with pytest.raises(BudgetDenied, match="INTAKE_LEASE_STALE"):
            require_live_intake_lease(first, old, datetime.now(timezone.utc))
        with pytest.raises(BudgetDenied, match="INTAKE_LEASE_STALE"):
            PostgresIntakeLeaseRepository(first).release(lease=old)
        assert (
            first.execute(
                "SELECT state FROM rag_discovery_jobs WHERE id=%s", (job,)
            ).fetchone()["state"]
            == "completed"
        )
        assert (
            first.execute(
                "SELECT count(*) AS n FROM rag_candidate_intake_leases WHERE candidate_id=%s",
                (cid,),
            ).fetchone()["n"]
            == 1
        )


def _persist_capture(conn, fixture):  # type: ignore[no-untyped-def]
    cid, job, _, _, _, _, policy = fixture
    body = b"x" * 32
    conn.execute(
        "INSERT INTO rag_candidate_captures(candidate_id,job_id,evidence_level,final_url,"
        "request_chain,chain_sha256,media_type,fetched_sha256,capture_kind,"
        "captured_bytes,prefix_sha256,captured_body,policy_id,policy_generation,retention_until) "
        "VALUES (%s,%s,'offline_protocol_only',%s,%s::jsonb,%s,'text/plain',%s,"
        "'prefix',32,%s,%s,%s,2,%s)",
        (
            cid,
            job,
            URL,
            '["https://example.org/docs/lesson"]',
            "f" * 64,
            "a" * 64,
            hashlib.sha256(body).hexdigest(),
            body,
            policy,
            datetime.now(timezone.utc) + timedelta(days=1),
        ),
    )


def test_reconcile_does_not_steal_live_owner_and_never_recaptures(dsn: str) -> None:
    fixture = seeded(dsn)
    cid, job, *_ = fixture
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        repo = PostgresIntakeLeaseRepository(conn)
        lease = claim(repo, fixture)
        assert lease is not None
        _persist_capture(
            conn, fixture
        )  # stage() committed, worker crashed before finish().
        before = conn.execute(
            "SELECT state,settled_units FROM rag_budget_reservations WHERE job_id=%s",
            (job,),
        ).fetchone()
        assert repo.reconcile_captured(candidate_id=cid) is False
        assert conn.execute(
            "SELECT state,generation FROM rag_candidate_intake_leases WHERE candidate_id=%s",
            (cid,),
        ).fetchone() == {"state": "leased", "generation": lease.generation}
        assert (
            conn.execute(
                "SELECT state,settled_units FROM rag_budget_reservations WHERE job_id=%s",
                (job,),
            ).fetchone()
            == before
        )
        repo.finish(lease=lease, success=True)
        assert repo.reconcile_captured(candidate_id=cid) is True  # idempotent audit
        assert claim(repo, fixture) is None  # no re-fetch after a capture


def test_reconcile_expired_or_idle_capture_after_revocation_and_clear(dsn: str) -> None:
    for release_before_reconcile in (False, True):
        fixture = seeded(dsn)
        cid, job, _, _, _, _, policy = fixture
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            repo = PostgresIntakeLeaseRepository(conn)
            assert (
                repo.reconcile_captured(candidate_id=cid) is False
            )  # no capture/lease
            lease = claim(repo, fixture, lease_seconds=1)
            assert lease is not None
            _persist_capture(conn, fixture)
            if release_before_reconcile:
                repo.release(lease=lease)
            conn.execute(
                "UPDATE rag_candidate_captures SET captured_body=NULL,cleared_at=clock_timestamp() "
                "WHERE candidate_id=%s",
                (cid,),
            )
            conn.execute(
                "UPDATE rag_candidate_access_policies SET enabled=false,revoked_at=clock_timestamp() "
                "WHERE policy_id=%s",
                (policy,),
            )
            before = conn.execute(
                "SELECT state,settled_units FROM rag_budget_reservations WHERE job_id=%s",
                (job,),
            ).fetchone()
            if not release_before_reconcile:
                assert repo.reconcile_captured(candidate_id=cid) is False
                conn.commit()
                time.sleep(1.2)
            assert repo.reconcile_captured(candidate_id=cid) is True
            state = conn.execute(
                "SELECT state,generation FROM rag_candidate_intake_leases WHERE candidate_id=%s",
                (cid,),
            ).fetchone()
            assert state == {"state": "done", "generation": lease.generation + 1}
            assert repo.reconcile_captured(candidate_id=cid) is True
            assert (
                conn.execute(
                    "SELECT state,settled_units FROM rag_budget_reservations WHERE job_id=%s",
                    (job,),
                ).fetchone()
                == before
            )
            assert (
                conn.execute(
                    "SELECT state FROM rag_discovery_jobs WHERE id=%s", (job,)
                ).fetchone()["state"]
                == "completed"
            )


def test_claim_rechecks_actor_revocation_after_lease_lock_wait(dsn: str) -> None:
    fixture = seeded(dsn)
    cid, job, _, _, _, authority, _ = fixture
    results: Queue[tuple[str, object]] = Queue()
    at_lease_lock = Event()
    resume = Event()

    class LeaseLockWait:
        """Pause exactly at the lease-row lock, after first authorization."""

        def __init__(self, conn):  # type: ignore[no-untyped-def]
            self.conn = conn

        def __getattr__(self, name):  # type: ignore[no-untyped-def]
            return getattr(self.conn, name)

        def execute(self, sql, params=None):  # type: ignore[no-untyped-def]
            if sql.startswith(
                "SELECT state,generation,expires_at FROM rag_candidate_intake_leases"
            ):
                at_lease_lock.set()
                if not resume.wait(timeout=5):
                    raise AssertionError("lease-lock barrier timed out")
            return self.conn.execute(sql, params)

    def contender() -> None:
        try:
            with psycopg.connect(dsn, row_factory=dict_row) as conn:
                try:
                    lease = claim(
                        PostgresIntakeLeaseRepository(LeaseLockWait(conn)),
                        fixture,
                        owner="worker.002",
                    )
                    results.put(("lease", lease))
                except BudgetDenied as exc:
                    results.put(("denied", str(exc)))
        except Exception as exc:
            results.put(("error", exc))

    with psycopg.connect(dsn, row_factory=dict_row) as holder:
        repo = PostgresIntakeLeaseRepository(holder)
        original = claim(repo, fixture)
        assert original is not None
        repo.release(lease=original)
        holder.commit()
        worker = Thread(target=contender, daemon=True)
        worker.start()
        try:
            assert at_lease_lock.wait(timeout=5), "contender never reached lease lock"
            authority.revoked = True  # Trusted A authority changes during the wait.
        finally:
            resume.set()
            worker.join(timeout=5)
        assert not worker.is_alive()
        assert results.get(timeout=1) == ("denied", "ACTOR_ACTION_DENIED")
        row = holder.execute(
            "SELECT state,generation FROM rag_candidate_intake_leases WHERE candidate_id=%s",
            (cid,),
        ).fetchone()
        assert row == {"state": "idle", "generation": original.generation}
        assert (
            holder.execute(
                "SELECT state FROM rag_discovery_jobs WHERE id=%s", (job,)
            ).fetchone()["state"]
            == "completed"
        )
