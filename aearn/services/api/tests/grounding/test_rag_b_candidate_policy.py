"""Offline operator-policy tests: fake SQL only, no database or network."""
import hashlib
from datetime import timedelta
from uuid import uuid4

from app.services.grounding.autonomous.access_policy import AutonomousGates
from app.services.grounding.autonomous.candidate_policy_repository import PostgresCandidatePolicyResolver
from app.services.grounding.autonomous.contracts import ContentCapture, SourceCandidate
from app.services.grounding.autonomous.retention import check_storage
from tests.grounding.rag_material_helpers import Authority, H, NOW, SCOPE, access

URL = "https://example.org/docs/lesson"
CANDIDATE = SourceCandidate(kind="document", demand_hash=H, scope=SCOPE, url=URL,
                            discovery_receipt_id="search.001",
                            capture=ContentCapture(kind="none", captured_bytes=0))


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self):
        self.calls = 0
        self.policy = dict(current_generation=2, enabled=True, expires_at=NOW + timedelta(days=2),
                           revoked_at=None, db_now=NOW)
        self.rules = [dict(path_prefix="/docs", probe_allowed=True, store_allowed=True,
                           allowed_capture="prefix", max_captured_bytes=64, license_id="CC-BY-4.0",
                           valid_until=NOW + timedelta(days=2),
                           retention_until=NOW + timedelta(days=1), revoked_at=None)]
        self.capture = dict(canonical_url=URL, capture_kind="prefix", captured_bytes=32,
                            license_id="CC-BY-4.0", retention_until=NOW + timedelta(days=1))

    def execute(self, sql, params=None):
        self.calls += 1
        if "FROM rag_candidate_access_policies" in sql:
            return Result([self.policy] if params == ("policy.001",) else [])
        if "FROM rag_candidate_access_rules" in sql:
            return Result(self.rules if params == ("policy.001", 2, "example.org") else [])
        if "FROM rag_discovery_candidates" in sql:
            return Result([self.capture] if params[1:] == ("policy.001", 2) else [])
        if "clock_timestamp() AS db_now" in sql:
            return Result([{"db_now": NOW}])
        raise AssertionError("unexpected SQL")


def resolver(monkeypatch, conn=None):
    monkeypatch.setattr("app.services.grounding.autonomous.candidate_policy_repository.require_transaction",
                        lambda _: None)
    return PostgresCandidatePolicyResolver(conn or FakeConnection())


def probe(repo, *, item=CANDIDATE, gates=AutonomousGates(discovery=True), request=None,
          authority=None):
    return repo.check_probe(item, request or access("probe"), gates=gates,
                            authority_resolver=authority or Authority(), now=NOW)


def store(repo, *, item=CANDIDATE, kind="prefix", size=32):
    return check_storage(item, access("store"), intended_capture=kind, planned_bytes=size,
                         gates=AutonomousGates(intake=True), authority_resolver=Authority(),
                         storage_resolver=repo, now=NOW)


def test_missing_closed_and_untrusted_candidate_url_never_grant(monkeypatch):
    conn = FakeConnection()
    repo = resolver(monkeypatch, conn)
    assert probe(repo, gates=AutonomousGates()).reason == "GATE_CLOSED"
    assert conn.calls == 0
    assert probe(repo).allowed
    for url in ("https://other.org/docs/lesson", "https://example.org/docs2/lesson",
                "https://example.org/docs/%2e%2e/private", "https://example.org/docs/lesson?token=secret"):
        assert not probe(repo, item=CANDIDATE.model_copy(update={"url": url})).allowed
    conn.policy["enabled"] = False
    assert not probe(repo).allowed
    assert not store(repo).allowed


def test_probe_public_is_not_full_text_permission(monkeypatch):
    conn = FakeConnection()
    repo = resolver(monkeypatch, conn)
    assert probe(repo).allowed
    assert store(repo).allowed
    assert store(repo, kind="full", size=32).reason == "STORAGE_SCOPE_DENIED"
    assert store(repo, kind="prefix", size=65).reason == "STORAGE_SCOPE_DENIED"
    assert store(repo, kind="none", size=0).allowed
    conn.rules[0]["store_allowed"] = False
    assert probe(repo).allowed
    assert store(repo).reason == "STORAGE_POLICY_MISSING"
    conn.rules[0]["store_allowed"] = True
    conn.rules[0]["license_id"] = None
    assert not store(repo).allowed


def test_narrower_denial_shadows_broad_rule_and_generation(monkeypatch):
    conn = FakeConnection()
    repo = resolver(monkeypatch, conn)
    conn.rules.append({**conn.rules[0], "path_prefix": "/docs/lesson", "revoked_at": NOW})
    assert not probe(repo).allowed
    assert not store(repo).allowed
    conn.rules.pop()
    conn.policy["current_generation"] = 3
    assert not probe(repo).allowed
    assert not store(repo).allowed


def test_expiry_and_revocation_drive_shared_scrub_without_actor_link(monkeypatch):
    conn = FakeConnection()
    repo = resolver(monkeypatch, conn)
    candidate_id = uuid4()
    assert not repo.globally_revoked(candidate_id, "policy.001", 2)
    conn.capture["license_id"] = None
    assert repo.globally_revoked(candidate_id, "policy.001", 2)
    conn.capture["license_id"] = "CC-BY-4.0"
    conn.rules[0]["revoked_at"] = NOW
    assert repo.globally_revoked(candidate_id, "policy.001", 2)
    conn.rules[0]["revoked_at"] = None
    conn.policy["expires_at"] = NOW
    assert repo.globally_revoked(candidate_id, "policy.001", 2)
    conn.policy["expires_at"] = NOW + timedelta(days=2)
    conn.capture["captured_bytes"] = 65
    assert repo.globally_revoked(candidate_id, "policy.001", 2)
    assert hashlib.sha256(URL.encode()).hexdigest() == repo.resolve(CANDIDATE, access("store")).candidate_url_sha256


def test_no_policy_or_invalid_scope_fails_closed(monkeypatch):
    conn = FakeConnection()
    repo = resolver(monkeypatch, conn)
    conn.rules = []
    assert not probe(repo).allowed
    assert not store(repo).allowed
    assert repo.globally_revoked(uuid4(), "policy.001", 2)


def test_pg_operator_grant_revoke_only_on_explicit_isolated_db():
    import os
    from datetime import datetime, timezone
    from urllib.parse import urlsplit

    import psycopg
    import pytest
    from psycopg.rows import dict_row

    dsn = os.environ.get("AEARN_RAG_B_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("policy PostgreSQL not executed: explicit disposable DB URL required")
    expected = urlsplit(dsn).path.lstrip("/")
    if not expected.startswith("aearn_rag260_"):
        pytest.fail("policy test refuses non-aearn_rag260_* database")
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        actual = conn.execute("SELECT current_database() AS name").fetchone()
        schema = conn.execute("SELECT to_regclass('rag_candidate_access_rules') AS name").fetchone()
        if (actual is None or actual["name"] != expected or schema is None
                or schema["name"] is None):
            pytest.fail("policy schema must be pre-applied by main session")
        policy_id = "policy." + uuid4().hex
        until = datetime.now(timezone.utc) + timedelta(days=2)
        conn.execute(
            "INSERT INTO rag_candidate_access_policies(policy_id,current_generation,expires_at) "
            "VALUES (%s,2,%s)", (policy_id, until),
        )
        conn.execute(
            "INSERT INTO rag_candidate_access_rules "
            "(policy_id,generation,host,path_prefix,probe_allowed,store_allowed,"
            "allowed_capture,max_captured_bytes,license_id,valid_until,retention_until) "
            "VALUES (%s,2,'example.org','/docs',true,true,'prefix',64,'CC-BY-4.0',%s,%s)",
            (policy_id, until, until),
        )
        repo = PostgresCandidatePolicyResolver(conn)
        request = access("probe").model_copy(update={"policy_id": policy_id})

        class OperatorAuthority(Authority):
            def resolve(self, request):
                return super().resolve(request).model_copy(update={"policy_id": policy_id})

        authority = OperatorAuthority()
        # Bootstrap inserted a disabled header; approval must be explicit.
        assert not probe(repo, request=request, authority=authority).allowed
        conn.execute("UPDATE rag_candidate_access_policies SET enabled=true WHERE policy_id=%s", (policy_id,))
        assert probe(repo, request=request, authority=authority).allowed
        conn.execute("UPDATE rag_candidate_access_rules SET revoked_at=CURRENT_TIMESTAMP "
                     "WHERE policy_id=%s AND generation=2 AND host='example.org' AND path_prefix='/docs'",
                     (policy_id,))
        assert not probe(repo, request=request, authority=authority).allowed
        assert repo.resolve(CANDIDATE, access("store").model_copy(update={"policy_id": policy_id})) is None
        with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
            conn.execute("UPDATE rag_candidate_access_rules SET revoked_at=NULL "
                         "WHERE policy_id=%s AND generation=2 AND host='example.org' AND path_prefix='/docs'",
                         (policy_id,))
        conn.rollback()  # Only this test's uncommitted operator fixture is discarded.
