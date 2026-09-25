"""Offline quarantine contracts; no DB/provider/network access."""
import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.services.grounding.autonomous.access_policy import AutonomousGates
from app.services.grounding.autonomous.contracts import ContentCapture, SourceCandidate
from app.services.grounding.autonomous.intake_leases import IntakeLease
from app.services.grounding.autonomous.provenance import (
    Attribution, prepare_capture, validate_prepared_capture,
)
from app.services.grounding.autonomous.retention import StorageGrant
from app.services.grounding.autonomous.safe_fetch import FetchResult
from app.services.grounding.autonomous.staging import CandidateStagingRepository
from tests.grounding.rag_material_helpers import Authority, H, NOW, SCOPE, access, demand

URL = "https://example.org/lesson"
CANDIDATE = SourceCandidate(kind="document", demand_hash=H, scope=SCOPE, url=URL,
                            discovery_receipt_id="search.001",
                            capture=ContentCapture(kind="none", captured_bytes=0))
BODY = b"# Heading\n\n- one\n\n```python\nprint(1)\n```\n"


def fetch(body=BODY, *, capture_kind="full", **changes):
    if capture_kind == "none":
        body = b""
    elif capture_kind == "prefix":
        body = body[:8]
    values = dict(final_url=URL, hops=(URL,), content_type="text/markdown", body=body,
                  sha256=hashlib.sha256(body).hexdigest(), compressed_bytes=len(body),
                  expanded_bytes=len(body), capture_kind=capture_kind,
                  range_end=7 if capture_kind == "prefix" else None)
    values.update(changes)
    return FetchResult(**values)


class Grants:
    def __init__(self, capture="full", revoked=False):
        self.capture = capture
        self.revoked = revoked
        self.calls = 0

    def resolve(self, candidate, request):
        self.calls += 1
        return StorageGrant(demand_hash=H, scope=SCOPE, discovery_receipt_id="search.001",
                            candidate_url_sha256=hashlib.sha256(URL.encode()).hexdigest(),
                            policy_id="policy.001", policy_generation=2,
                            allowed_capture=self.capture, max_captured_bytes=1024,
                            retention_until=NOW + timedelta(hours=1), revoked=self.revoked)


def test_none_prefix_full_are_distinct_and_fragments_only_from_full():
    none = prepare_capture(CANDIDATE, fetch(capture_kind="none"), capture_kind="none")
    prefix = prepare_capture(CANDIDATE, fetch(capture_kind="prefix"), capture_kind="prefix", prefix_bytes=8)
    full = prepare_capture(CANDIDATE, fetch(), capture_kind="full",
                           attribution=Attribution(license_id="MIT", author_name="Example",
                                                   claimed_origin_url="https://example.org/original"))
    assert none.captured_body is None and none.prefix_sha256 is None and none.full_sha256 is None
    assert none.fetched_sha256 == hashlib.sha256(b"").hexdigest()
    assert prefix.captured_body == BODY[:8] and prefix.prefix_sha256 == hashlib.sha256(BODY[:8]).hexdigest()
    assert prefix.fetched_sha256 == prefix.prefix_sha256
    assert prefix.full_sha256 is None and not prefix.fragments
    assert full.full_sha256 == full.fetched_sha256 and full.prefix_sha256 is None
    assert {part.kind for part in full.fragments} == {"heading", "list_item", "code"}
    assert full.origin_sha256 == hashlib.sha256(b"https://example.org/original").hexdigest()
    for receipt in (none, prefix, full):
        validate_prepared_capture(receipt)


def test_forged_bytes_fragments_and_chain_cannot_be_committed():
    full = prepare_capture(CANDIDATE, fetch(), capture_kind="full")
    for forged in (
        replace(full, captured_body=b"another body"),
        replace(full, fragments=full.fragments[:-1]),
        replace(full, request_chain=("https://other.org/secret",)),
    ):
        with pytest.raises(ValueError):
            validate_prepared_capture(forged)
    with pytest.raises(ValueError):
        prepare_capture(CANDIDATE, fetch(sha256="0" * 64), capture_kind="full")
    with pytest.raises(ValueError):
        prepare_capture(CANDIDATE, fetch(capture_kind="none", hops=(URL, "https://example.org/redirect?token=x"),
                                         final_url="https://example.org/redirect?token=x"), capture_kind="none")


def test_repo_revision_and_untrusted_mirror_not_independent():
    repo = CANDIDATE.model_copy(update={"kind": "repo_file", "repo_commit": "a" * 40,
                                        "repo_path": "src/doc.md", "url": "https://example.org/repo"})
    with pytest.raises(ValueError, match="REPO_REVISION_UNVERIFIED"):
        prepare_capture(repo, fetch(capture_kind="none", hops=(repo.url,), final_url=repo.url), capture_kind="none")
    assert prepare_capture(CANDIDATE, fetch(capture_kind="none"), capture_kind="none",
                           attribution=Attribution(claimed_origin_url=URL)).origin_sha256


def test_closed_and_revoked_storage_never_touches_database():
    class NoDatabase:
        def __getattr__(self, name):
            raise AssertionError("no database access permitted")

    repository = CandidateStagingRepository(NoDatabase(), offline_protocol_test=True)
    prepared = prepare_capture(CANDIDATE, fetch(), capture_kind="full")
    candidate_id = uuid4()
    lease = IntakeLease(candidate_id, uuid4(), "worker.001", 1, NOW + timedelta(seconds=60))
    from app.services.grounding.autonomous.budget import BudgetDenied

    grant = Grants()
    with pytest.raises(BudgetDenied, match="GATE_CLOSED"):
        repository.stage(candidate_id=candidate_id, candidate=CANDIDATE, prepared=prepared,
                         lease=lease, request=access("store"), demand=demand(),
                         gates=AutonomousGates(), authority_resolver=Authority(),
                         storage_resolver=grant, now=NOW)
    assert grant.calls == 0
    with pytest.raises(BudgetDenied, match="STORAGE_POLICY_STALE"):
        repository.stage(candidate_id=candidate_id, candidate=CANDIDATE, prepared=prepared,
                         lease=lease, request=access("store"), demand=demand(),
                         gates=AutonomousGates(intake=True), authority_resolver=Authority(),
                         storage_resolver=Grants(revoked=True), now=NOW)
    with pytest.raises(BudgetDenied, match="STORAGE_SCOPE_DENIED"):
        repository.stage(candidate_id=candidate_id, candidate=CANDIDATE, prepared=prepared,
                         lease=lease, request=access("store"), demand=demand(),
                         gates=AutonomousGates(intake=True), authority_resolver=Authority(),
                         storage_resolver=Grants(capture="prefix"), now=NOW)


def test_schema_isolated_and_private_refs_separate():
    from pathlib import Path

    sql = (Path(__file__).resolve().parents[2] / "app/db/schema/280_rag_candidate_staging.sql").read_text()
    assert "REFERENCES rag_discovery_candidates(id,job_id)" in sql
    assert "CREATE TABLE IF NOT EXISTS rag_candidate_private_refs" in sql
    assert "actor_id" not in sql.split("CREATE TABLE IF NOT EXISTS rag_candidate_private_refs")[0]
    assert "grounding_corpus" not in sql and "active_pointer" not in sql
    assert "evidence_level IN ('offline_protocol_only','live_egress_attested')" in sql
    assert "captured_body=NULL" in __import__("inspect").getsource(CandidateStagingRepository.clear_expired)

@pytest.fixture(scope="module")
def isolated_db():
    import os
    from urllib.parse import urlsplit

    import psycopg
    from psycopg.rows import dict_row

    dsn = os.environ.get("AEARN_RAG_B_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("B2 PostgreSQL not executed: explicit disposable AEARN_RAG_B_TEST_DATABASE_URL required")
    name = urlsplit(dsn).path.lstrip("/")
    if not name.startswith("aearn_rag260_"):
        pytest.fail("B2 refuses non-aearn_rag260_* database")
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        if conn.execute("SELECT current_database() AS name").fetchone()["name"] != name:
            pytest.fail("B2 current_database() mismatch")
        if conn.execute("SELECT to_regclass('rag_candidate_captures') AS name").fetchone()["name"] is None:
            pytest.fail("B2 schema must be applied by the schema owner first")
    return dsn


def test_pg_stage_fenced_replay_private_refs_and_cleanup(isolated_db, monkeypatch):
    import psycopg
    from psycopg.rows import dict_row
    from uuid import uuid4

    from app.services.grounding.autonomous.budget import BudgetDenied, BudgetPolicy, BudgetRepository, fingerprint
    from app.services.grounding.autonomous.contracts import SourceDiscoveryDemand
    from app.services.grounding.autonomous.candidate_repository import CandidateRepository
    from app.services.grounding.autonomous.jobs import DiscoveryJobRepository
    from app.services.grounding.autonomous.intake_leases import PostgresIntakeLeaseRepository
    from tests.grounding import rag_material_helpers

    db_now = datetime.now(timezone.utc)
    monkeypatch.setattr(rag_material_helpers, "BUDGET", access().budget.model_copy(
        update={"expires_at": db_now + timedelta(days=1)}
    ))

    class Policy:
        def resolve(self, snapshot):
            return BudgetPolicy(snapshot.budget.root_id, "2026-09", 1000,
                                    db_now + timedelta(days=10), db_now - timedelta(days=1))

    with psycopg.connect(isolated_db, row_factory=dict_row) as conn:
        key = uuid4().hex
        jobs = DiscoveryJobRepository(conn)
        projection = SourceDiscoveryDemand(demand_hash=H, scope=SCOPE, query_terms=("Python list",),
                                           actor_id="actor.001", policy_id="policy.001",
                                           policy_generation=2, budget=access().budget)
        job = jobs.enqueue(request=access(), demand=demand(), gates=AutonomousGates(discovery=True),
                           resolver=Authority(), operation_key=f"stage.{key}", request_hash=fingerprint(key),
                           projection=projection, now=db_now)
        lease = jobs.claim(job_id=job, request=access(), demand=demand(),
                           gates=AutonomousGates(discovery=True), resolver=Authority(),
                           owner_id="worker.001", now=db_now)
        assert lease is not None
        # Staging rechecks the persisted current root, not the fake reserve port.
        snapshot = Authority().resolve(access())
        assert snapshot is not None
        conn.execute(
            "INSERT INTO rag_budget_authority_roots(root_id,delegation_id,"
            "delegation_generation,delegation_expires_at,policy_id,policy_generation,"
            "period_key,period_start,period_end,cap_units,enabled) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true) "
            "ON CONFLICT (root_id) DO UPDATE SET delegation_id=excluded.delegation_id,"
            "delegation_generation=excluded.delegation_generation,"
            "delegation_expires_at=excluded.delegation_expires_at,policy_id=excluded.policy_id,"
            "policy_generation=excluded.policy_generation,period_key=excluded.period_key,"
            "period_start=excluded.period_start,period_end=excluded.period_end,"
            "cap_units=excluded.cap_units,enabled=true",
            (snapshot.budget.root_id, snapshot.budget.delegation_id,
             snapshot.budget.generation, snapshot.budget.expires_at,
             snapshot.policy_id, snapshot.policy_generation, "2026-09",
             db_now - timedelta(days=1), db_now + timedelta(days=10), 1000),
        )
        reserve = BudgetRepository(conn).reserve(request=access(), demand=demand(),
                                                 gates=AutonomousGates(discovery=True), resolver=Authority(),
                                                 policy_resolver=Policy(), job_id=job,
                                                 operation_key=f"reserve.{key}",
                                                 request_hash=fingerprint(key, "reserve"), units=1, now=db_now)
        assert reserve.reservation_id
        budget = BudgetRepository(conn)
        attempt = budget.record_attempt(reservation_id=reserve.reservation_id, attempt_key=f"attempt.{key}",
                                        lease=lease, now=db_now)
        assert budget.take_dispatch(projection=projection, request=access(), demand=demand(),
                                    gates=AutonomousGates(discovery=True), resolver=Authority(),
                                    lease=lease, reservation_id=reserve.reservation_id,
                                    attempt_id=attempt.attempt_id, now=db_now)
        budget.settle(attempt_id=attempt.attempt_id, lease=lease, usage=1,
                      receipt_hash="f" * 64, now=db_now)
        receipt_handle = f"search.{key}"
        candidates = CandidateRepository(conn)
        candidates.record_receipt(lease=lease, request=access(), demand=demand(),
                                  gates=AutonomousGates(discovery=True), resolver=Authority(),
                                  attempt_id=attempt.attempt_id, receipt_handle=receipt_handle,
                                  result_code="SEARCH_OK", response_hash="e" * 64, now=db_now)
        item = CANDIDATE.model_copy(update={"discovery_receipt_id": receipt_handle})
        candidate_id = candidates.record_candidate(lease=lease, request=access(), demand=demand(),
                                                   gates=AutonomousGates(discovery=True), resolver=Authority(),
                                                   candidate=item, now=db_now)
        jobs.complete(lease=lease, request=access(), demand=demand(),
                      gates=AutonomousGates(discovery=True), resolver=Authority(), now=db_now, success=True)
        policy_until = datetime.now(timezone.utc) + timedelta(hours=2)
        conn.execute(
            "INSERT INTO rag_candidate_access_policies(policy_id,current_generation,expires_at,enabled) "
            "VALUES ('policy.001',2,%s,true)", (policy_until,),
        )
        conn.execute(
            "INSERT INTO rag_candidate_access_rules(policy_id,generation,host,path_prefix,"
            "probe_allowed,store_allowed,allowed_capture,max_captured_bytes,license_id,"
            "valid_until,retention_until) VALUES ('policy.001',2,'example.org','/lesson',"
            "true,true,'full',1024,'MIT',%s,%s)", (policy_until, policy_until),
        )
        intake_lease = PostgresIntakeLeaseRepository(conn).claim(
            candidate_id=candidate_id, candidate=item, probe=access("probe"), store=access("store"),
            demand=demand(), gates=AutonomousGates(discovery=True, intake=True),
            authority_resolver=Authority(), capture_kind="full", planned_bytes=len(BODY),
            owner_id="worker.001",
        )
        assert intake_lease is not None
        # Grant must refer to this exact B1 receipt, not the static offline fixture.
        until = datetime.now(timezone.utc) + timedelta(hours=1)
        class ExactGrants(Grants):
            def resolve(self, candidate, request):
                return StorageGrant(demand_hash=H, scope=SCOPE, discovery_receipt_id=receipt_handle,
                                    candidate_url_sha256=hashlib.sha256(URL.encode()).hexdigest(),
                                    policy_id="policy.001", policy_generation=2, allowed_capture="full",
                                    max_captured_bytes=1024, retention_until=until, revoked=False)

        stage = CandidateStagingRepository(conn, offline_protocol_test=True)
        prepared = prepare_capture(item, fetch(), capture_kind="full")
        kwargs = dict(candidate_id=candidate_id, candidate=item, prepared=prepared, lease=intake_lease,
                      request=access("store"), demand=demand(), gates=AutonomousGates(intake=True),
                      authority_resolver=Authority(), storage_resolver=ExactGrants(), now=db_now)
        capture_id = stage.stage(**kwargs)
        assert stage.stage(**kwargs) == capture_id
        assert conn.execute("SELECT count(*) AS n FROM rag_candidate_fragments WHERE capture_id=%s",
                            (capture_id,)).fetchone()["n"] == len(prepared.fragments)
        assert conn.execute("SELECT count(*) AS n FROM rag_candidate_private_refs WHERE actor_id=%s",
                            ("actor.001",)).fetchone()["n"] == 1
        with pytest.raises(BudgetDenied, match="STORAGE_LICENSE_MISMATCH"):
            stage.stage(**{**kwargs, "prepared": replace(prepared, license_id="MIT")})
        # Direct SQL cannot clear a capture while leaving readable fragments.
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute("UPDATE rag_candidate_captures SET captured_body=NULL,"
                             "cleared_at=clock_timestamp() WHERE id=%s", (capture_id,))
        class GlobalRevocation:
            def globally_revoked(self, candidate_id, policy_id, generation):
                assert policy_id == "policy.001" and generation == 2
                return True

        assert stage.clear_revoked(candidate_id=candidate_id, resolver=GlobalRevocation())
        assert conn.execute("SELECT captured_body FROM rag_candidate_captures WHERE id=%s",
                            (capture_id,)).fetchone()["captured_body"] is None
        assert conn.execute("SELECT count(*) AS n FROM rag_candidate_fragments WHERE capture_id=%s "
                            "AND text_content IS NOT NULL", (capture_id,)).fetchone()["n"] == 0
        with pytest.raises(BudgetDenied, match="CAPTURE_CONFLICT"):
            stage.stage(**kwargs)
        assert stage.unlink_actor(actor_id="actor.001") == 1
        assert conn.execute("SELECT id FROM rag_candidate_captures WHERE id=%s",
                            (capture_id,)).fetchone() is not None
        PostgresIntakeLeaseRepository(conn).release(lease=intake_lease)
        with pytest.raises(BudgetDenied, match="INTAKE_LEASE_STALE"):
            stage.stage(**kwargs)
        conn.rollback()  # discard only rows owned by this test


def test_live_label_without_fetcher_receipt_cannot_stage():
    from app.services.grounding.autonomous.budget import BudgetDenied

    repository = CandidateStagingRepository(None)  # type: ignore[arg-type]
    forged = replace(prepare_capture(CANDIDATE, fetch(), capture_kind="full"),
                     evidence_level="live_egress_attested", live_receipt=object())
    with pytest.raises(BudgetDenied, match="LIVE_EGRESS_UNVERIFIED"):
        repository.stage(candidate_id=uuid4(), candidate=CANDIDATE, prepared=forged,
                         lease=IntakeLease(uuid4(), uuid4(), "worker.001", 1, NOW + timedelta(seconds=60)),
                         request=access("store"), demand=demand(),
                         gates=AutonomousGates(intake=True), authority_resolver=Authority(),
                         storage_resolver=Grants(), now=NOW)


def test_default_staging_rejects_offline_receipts_without_db_access():
    from app.services.grounding.autonomous.budget import BudgetDenied

    repository = CandidateStagingRepository(None)  # type: ignore[arg-type]
    with pytest.raises(BudgetDenied, match="LIVE_EGRESS_UNVERIFIED"):
        repository.stage(candidate_id=uuid4(), candidate=CANDIDATE,
                         prepared=prepare_capture(CANDIDATE, fetch(capture_kind="none"), capture_kind="none"),
                         lease=IntakeLease(uuid4(), uuid4(), "worker.001", 1, NOW + timedelta(seconds=60)),
                         request=access("store"), demand=demand(),
                         gates=AutonomousGates(intake=True), authority_resolver=Authority(),
                         storage_resolver=Grants(), now=NOW)


def test_commit_rechecks_storage_after_lease_and_scope_lock(monkeypatch):
    from contextlib import nullcontext
    from app.services.grounding.autonomous import staging
    from app.services.grounding.autonomous.budget import BudgetDenied

    candidate_id, job_id = uuid4(), uuid4()
    lease = IntakeLease(candidate_id, job_id, "worker.001", 1, NOW + timedelta(seconds=60))

    class Result:
        def __init__(self, row):
            self.row = row

        def fetchone(self):
            return self.row

    class Conn:
        def __init__(self):
            self.commands = []

        def transaction(self):
            return nullcontext()

        def execute(self, sql, params=()):
            self.commands.append(sql)
            if sql.startswith("SELECT clock_timestamp()"):
                return Result(dict(db_now=NOW))
            if sql.startswith("SELECT * FROM rag_discovery_jobs"):
                return Result(dict(demand_hash=H, subject_id=SCOPE.subject_id,
                                   subject_version=SCOPE.subject_version, purpose="main_teaching",
                                   policy_id="policy.001", policy_generation=2, root_id="root.001",
                                   delegation_id="delegation.001", delegation_generation=1,
                                   state="completed"))
            if sql.startswith("SELECT * FROM rag_discovery_candidates"):
                return Result(dict(canonical_url=URL, canonical_url_hash=hashlib.sha256(URL.encode()).hexdigest(),
                                   demand_hash=H, subject_id=SCOPE.subject_id,
                                   subject_version=SCOPE.subject_version, kind="document",
                                   repo_commit=None, repo_path=None, discovery_receipt_id=uuid4()))
            if "FROM rag_discovery_receipts r" in sql:
                return Result(dict(receipt_handle="search.001", attempt_state="settled",
                                   reservation_state="settled", reserved_job=job_id,
                                   reserved_root="root.001", reserved_period="2026-09"))
            raise AssertionError("content insert attempted after revocation")

    class Revoking(Grants):
        def resolve(self, candidate, request):
            self.calls += 1
            return StorageGrant(demand_hash=H, scope=SCOPE, discovery_receipt_id="search.001",
                                candidate_url_sha256=hashlib.sha256(URL.encode()).hexdigest(),
                                policy_id="policy.001", policy_generation=2, allowed_capture="full",
                                max_captured_bytes=1024, retention_until=NOW + timedelta(hours=1),
                                revoked=self.calls > 1)

    monkeypatch.setattr(staging, "require_transaction", lambda conn: None)
    monkeypatch.setattr(staging, "require_live_intake_lease", lambda conn, lease, now: None)
    monkeypatch.setattr(staging, "PostgresBudgetPolicyResolver", lambda conn: type(
        "Root", (), {"resolve": lambda self, snapshot: type("Policy", (), {
            "root_id": "root.001", "period_start": NOW - timedelta(days=1),
            "period_end": NOW + timedelta(days=1), "period_key": "2026-09",
        })()})())
    conn = Conn()
    grants = Revoking()
    with pytest.raises(BudgetDenied, match="STORAGE_POLICY_STALE"):
        staging.CandidateStagingRepository(conn, offline_protocol_test=True).stage(  # type: ignore[arg-type]
            candidate_id=candidate_id, candidate=CANDIDATE,
            prepared=prepare_capture(CANDIDATE, fetch(), capture_kind="full"), lease=lease,
            request=access("store"), demand=demand(), gates=AutonomousGates(intake=True),
            authority_resolver=Authority(), storage_resolver=grants, now=NOW,
        )
    assert grants.calls == 2
    assert not any(command.startswith("INSERT") for command in conn.commands)


def test_one_actor_denial_cannot_scrub_shared_capture(monkeypatch):
    from contextlib import nullcontext
    from app.services.grounding.autonomous import staging

    class Result:
        def fetchone(self):
            return dict(id=uuid4(), policy_id="policy.001", policy_generation=2, cleared_at=None)

    class Conn:
        def __init__(self):
            self.commands = []

        def transaction(self):
            return nullcontext()

        def execute(self, sql, params=()):
            self.commands.append(sql)
            if sql.startswith("SELECT"):
                return Result()
            raise AssertionError("shared capture scrubbed without global revocation")

    class StillShared:
        def globally_revoked(self, candidate_id, policy_id, generation):
            return False

    monkeypatch.setattr(staging, "require_transaction", lambda conn: None)
    conn = Conn()
    assert not staging.CandidateStagingRepository(conn).clear_revoked(
        candidate_id=uuid4(), resolver=StillShared(),
    )  # type: ignore[arg-type]
    assert len(conn.commands) == 1


def test_global_revocation_scrubs_content_but_preserves_audit(monkeypatch):
    from contextlib import nullcontext
    from app.services.grounding.autonomous import staging

    capture_id = uuid4()

    class Result:
        def fetchone(self):
            return dict(id=capture_id, policy_id="policy.001", policy_generation=2, cleared_at=None)

    class Conn:
        def __init__(self):
            self.commands = []

        def transaction(self):
            return nullcontext()

        def execute(self, sql, params=()):
            self.commands.append(sql)
            if sql.startswith("SELECT"):
                return Result()
            return None

    class Revoked:
        def globally_revoked(self, candidate_id, policy_id, generation):
            return True

    monkeypatch.setattr(staging, "require_transaction", lambda conn: None)
    conn = Conn()
    assert staging.CandidateStagingRepository(conn).clear_revoked(
        candidate_id=uuid4(), resolver=Revoked(),
    )  # type: ignore[arg-type]
    assert len(conn.commands) == 3
    assert "text_content=NULL" in conn.commands[1]
    assert "captured_body=NULL" in conn.commands[2]
    assert all("DELETE" not in command for command in conn.commands)


def test_minimal_provenance_rejects_full_then_truncate_and_false_full_digest():
    with pytest.raises(ValueError, match="FETCH_BODY_INVALID"):
        prepare_capture(CANDIDATE, fetch(), capture_kind="prefix", prefix_bytes=8)
    with pytest.raises(ValueError, match="FETCH_BODY_INVALID"):
        prepare_capture(CANDIDATE, fetch(), capture_kind="none")
    minimal = prepare_capture(CANDIDATE, fetch(capture_kind="none"), capture_kind="none")
    prefix = prepare_capture(CANDIDATE, fetch(capture_kind="prefix"),
                             capture_kind="prefix", prefix_bytes=8)
    assert minimal.fetched_sha256 == hashlib.sha256(b"").hexdigest()
    assert minimal.full_sha256 is None and minimal.captured_body is None
    assert prefix.fetched_sha256 == prefix.prefix_sha256
    assert prefix.full_sha256 is None and prefix.fetched_sha256 != hashlib.sha256(BODY).hexdigest()
    for altered in (
        replace(minimal, fetched_sha256=hashlib.sha256(BODY).hexdigest()),
        replace(prefix, fetched_sha256=hashlib.sha256(BODY).hexdigest()),
        replace(prefix, full_sha256=hashlib.sha256(BODY).hexdigest()),
    ):
        with pytest.raises(ValueError, match="CAPTURE_INVALID"):
            validate_prepared_capture(altered)
