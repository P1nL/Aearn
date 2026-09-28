"""Offline C review counterexamples; optional explicit disposable PostgreSQL."""
from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.db.bootstrap import apply_schema
from app.services.grounding.autonomous.contracts import SubjectScope
from app.services.grounding.autonomous.source_review_repository import (
    CompleteCapture, QualityFinding, ReviewDenied, SourceReviewRepository, _qualified,
)

NOW = datetime.now(UTC)
SCOPE = SubjectScope(subject_id="route.sql", subject_version="v1", facets=("queries",))
H = "a" * 64


class OfflineVerifier:
    """Never a real quality authority; no offline finding can write QUALIFIED."""

    calls = 0

    def verify(self, capture: CompleteCapture) -> QualityFinding:
        self.calls += 1
        assert hashlib.sha256(capture.body).hexdigest() == capture.digest
        return QualityFinding(
            mode="offline_protocol_only", version_fit="current", reading_fit="suitable",
            technical_status="correct", conflict_status="resolved", known_error="absent",
            covered_facets=("queries",), lineage_family="family.sqlite",
            evidence_hash=H,
        )


def test_offline_quality_and_missing_findings_cannot_admit():
    finding = OfflineVerifier().verify(
        CompleteCapture(uuid4(), "registered", b"test", hashlib.sha256(b"test").hexdigest(),
                        hashlib.sha256(b"test").hexdigest(), SCOPE, "source.sqlite",
                        "https://www.sqlite.org/lang_select.html",
                        ("https://www.sqlite.org/lang_select.html",), "official", "beginner",
                        "public-domain"),
    )
    assert not _qualified(finding, SCOPE)
    assert not _qualified(QualityFinding(**(finding.__dict__ | {"mode": "production",
                                                         "technical_status": "unknown"})), SCOPE)
    assert not _qualified(QualityFinding(**(finding.__dict__ | {"mode": "production",
                                                         "covered_facets": ()})), SCOPE)
    assert not _qualified(QualityFinding(**(finding.__dict__ | {"mode": "production",
                                                         "evidence_hash": "not-a-hash"})), SCOPE)


def test_optional_reviewer_scope_is_exact_and_fail_closed() -> None:
    body = "SELECT 名称 FROM books; Unreviewed paragraph.".encode("utf-8")
    capture = CompleteCapture(
        uuid4(), "registered", body, hashlib.sha256(body).hexdigest(),
        hashlib.sha256(body).hexdigest(), SCOPE, "source.sqlite",
        "https://www.sqlite.org/lang_select.html",
        ("https://www.sqlite.org/lang_select.html",), "official", "beginner", "public-domain",
    )
    excerpt = "SELECT 名称 FROM books;"

    class Scoped:
        def reviewed_usages(self, item: CompleteCapture) -> tuple[str, ...]:
            return ("supplementary_explanation",)

        def approved_excerpts(self, item: CompleteCapture) -> tuple[str, ...]:
            return (excerpt,)

    class Legacy:
        pass

    class MissingMethod:
        def reviewed_usages(self, item: CompleteCapture) -> tuple[str, ...]:
            return ("supplementary_explanation",)

    class Broader(Scoped):
        def reviewed_usages(self, item: CompleteCapture) -> tuple[str, ...]:
            return ("main_teaching", "supplementary_explanation")

    class Invented(Scoped):
        def approved_excerpts(self, item: CompleteCapture) -> tuple[str, ...]:
            return ("SELECT other FROM books;",)

    class Throws(Scoped):
        def approved_excerpts(self, item: CompleteCapture) -> tuple[str, ...]:
            raise RuntimeError("sensitive reviewer failure")

    def repo(verifier: object) -> SourceReviewRepository:
        return SourceReviewRepository(SimpleNamespace(), verifier=verifier)  # type: ignore[arg-type]

    assert repo(Legacy()).reviewed_excerpts(capture) is None
    assert repo(Scoped()).reviewed_excerpts(capture) == (excerpt,)
    for verifier in (MissingMethod(), Broader(), Invented(), Throws()):
        with pytest.raises(ReviewDenied, match="VERIFIER_SCOPE_DENIED"):
            repo(verifier).reviewed_excerpts(capture)


def test_current_review_read_locks_admission_before_verification(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    statements: list[str] = []

    def execute(query: str, _params: object) -> SimpleNamespace:
        statements.append(query)
        return SimpleNamespace(fetchone=lambda: None)

    repo = SourceReviewRepository(SimpleNamespace(execute=execute), verifier=OfflineVerifier())  # type: ignore[arg-type]
    monkeypatch.setattr(repo, "_schema_ready", lambda: True)
    assert repo.resolve("source.sqlite", "document.sqlite") is None
    assert len(statements) == 1
    assert "JOIN rag_source_admissions a" in statements[0]
    assert "FOR SHARE OF r,a" in statements[0]


def test_automated_scope_cannot_admit_main_from_broad_policy(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    body = b"SELECT title FROM books;"
    capture = CompleteCapture(
        uuid4(), "registered", body, hashlib.sha256(body).hexdigest(),
        hashlib.sha256(body).hexdigest(), SCOPE, "source.sqlite",
        "https://www.sqlite.org/lang_select.html",
        ("https://www.sqlite.org/lang_select.html",), "official", "beginner", "public-domain",
    )

    class Scoped:
        def verify(self, item: CompleteCapture) -> QualityFinding:
            return QualityFinding(
                mode="production", version_fit="current", reading_fit="suitable",
                technical_status="correct", conflict_status="resolved", known_error="absent",
                covered_facets=("queries",), lineage_family="family.sqlite", evidence_hash=H,
            )

        def reviewed_usages(self, item: CompleteCapture) -> tuple[str, ...]:
            return ("supplementary_explanation",)

        def approved_excerpts(self, item: CompleteCapture) -> tuple[str, ...]:
            return ("SELECT title FROM books;",)

    now = datetime.now(UTC)
    conn = SimpleNamespace(
        autocommit=False, execute=lambda _query: SimpleNamespace(fetchone=lambda: {"now": now}),
    )
    repo = SourceReviewRepository(conn, verifier=Scoped())  # type: ignore[arg-type]
    monkeypatch.setattr(repo, "_schema_ready", lambda: True)
    monkeypatch.setattr(repo, "_capture", lambda *_: (
        capture, {"allowed_usages": ["main_teaching", "supplementary_explanation"],
                  "immutable_history_allowed": True},
    ))
    with pytest.raises(ReviewDenied, match="REVIEW_DENIED"):
        repo.review_and_admit(capture_id=capture.capture_id, lane="registered",
                              document_handle="doc.sqlite", requested_usages=("main_teaching",), now=now)


@pytest.fixture()
def pg():  # type: ignore[no-untyped-def]
    dsn = os.environ.get("AEARN_RAG_C_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("set explicit AEARN_RAG_C_TEST_DATABASE_URL for C disposable PostgreSQL")
    parsed = urlsplit(dsn)
    if not parsed.path.lstrip("/").startswith("aearn_rag260_c_"):
        pytest.fail("C test database must be named aearn_rag260_c_*")
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        actual = conn.execute("SELECT current_database() AS name").fetchone()
        assert actual is not None and actual["name"] == parsed.path.lstrip("/")
        apply_schema(conn)
        apply_schema(conn)
        try:
            yield conn
        finally:
            conn.rollback()


def _registered_capture(conn):  # type: ignore[no-untyped-def]
    suffix = uuid4().hex
    policy = "policy." + suffix
    root = "root." + suffix
    handle = "source." + suffix
    url = "https://www.sqlite.org/lang_select.html"
    body = b"offline fixture only; not a SQLite quality finding"
    digest = hashlib.sha256(body).hexdigest()
    end = datetime.now(UTC) + timedelta(hours=2)
    conn.execute(
        "INSERT INTO rag_budget_authority_roots(root_id,delegation_id,delegation_generation,"
        "delegation_expires_at,policy_id,policy_generation,period_key,period_start,period_end,"
        "cap_units,enabled) VALUES (%s,%s,1,%s,%s,1,%s,%s,%s,1,true)",
        (root, "delegation." + suffix, end, policy, "test", datetime.now(UTC) - timedelta(hours=1), end),
    )
    conn.execute(
        "INSERT INTO rag_registered_source_policies(policy_id,generation,source_handle,"
        "subject_id,subject_version,facets,origin,reading_level,canonical_url,canonical_url_sha256,"
        "host,path,license_id,allowed_usages,immutable_history_allowed,max_captured_bytes,"
        "retention_until,expires_at,root_id,enabled) "
        "VALUES (%s,1,%s,'route.sql','v1',ARRAY['queries'],'official','beginner',%s,%s,"
        "'www.sqlite.org','/lang_select.html','public-domain',ARRAY['main_teaching'],"
        "true,1048576,%s,%s,%s,true)",
        (policy, handle, url, hashlib.sha256(url.encode()).hexdigest(), end, end, root),
    )
    attempt = conn.execute(
        "INSERT INTO rag_registered_fetch_attempts(policy_id,generation,canonical_url_sha256,"
        "root_id,operation_key,request_hash) VALUES (%s,1,%s,%s,%s,%s) RETURNING id",
        (policy, hashlib.sha256(url.encode()).hexdigest(), root, "attempt." + suffix, digest),
    ).fetchone()
    assert attempt is not None
    conn.execute(
        "UPDATE rag_registered_fetch_attempts SET state='settled',response_sha256=%s,"
        "response_bytes=%s,settled_at=clock_timestamp() WHERE id=%s",
        (digest, len(body), attempt["id"]),
    )
    captured = conn.execute(
        "INSERT INTO rag_registered_source_captures(fetch_attempt_id,policy_id,generation,"
        "request_chain,final_url,content_type,fetched_sha256,captured_bytes,captured_body,"
        "license_id,retention_until) VALUES (%s,%s,1,%s,%s,'text/plain',%s,%s,%s,"
        "'public-domain',%s) RETURNING id",
        (attempt["id"], policy, '["' + url + '"]', url, digest, len(body), body, end),
    ).fetchone()
    assert captured is not None
    return captured["id"]


def test_pg_offline_fake_never_creates_review_or_admission(pg):  # type: ignore[no-untyped-def]
    capture_id = _registered_capture(pg)
    fake = OfflineVerifier()
    repo = SourceReviewRepository(pg, verifier=fake)
    with pytest.raises(ReviewDenied) as exc:
        repo.review_and_admit(capture_id=capture_id, lane="registered",
                              document_handle="doc." + uuid4().hex,
                              requested_usages=("main_teaching",), now=datetime.now(UTC))
    assert exc.value.args[0] in {"REVIEW_DENIED", "REVIEW_AUTHORITY_MISSING"}
    assert repo.resolve("source.untrusted", "doc.untrusted") is None
    assert pg.execute("SELECT count(*) AS count FROM rag_source_reviews").fetchone()["count"] == 0
    assert pg.execute("SELECT count(*) AS count FROM rag_source_admissions").fetchone()["count"] == 0
    # If the schema owner has installed all persisted findings, the fake ran on
    # actual full fixture bytes; it still never asserted real quality.
    if repo._schema_ready():
        assert fake.calls == 1


def test_pg_no_verifier_and_assessment_usage_fail_closed(pg):  # type: ignore[no-untyped-def]
    capture_id = _registered_capture(pg)
    repo = SourceReviewRepository(pg)
    with pytest.raises(ReviewDenied, match="REVIEW_AUTHORITY_MISSING"):
        repo.review_and_admit(capture_id=capture_id, lane="registered",
                              document_handle="doc." + uuid4().hex,
                              requested_usages=("assessment_evidence",), now=datetime.now(UTC))
