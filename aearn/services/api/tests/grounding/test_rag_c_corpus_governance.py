"""Explicit disposable C PostgreSQL only; no provider, network or live capture."""
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
from psycopg.pq import TransactionStatus

from app.db.bootstrap import apply_schema
from app.services.grounding.autonomous.corpus_governance import (
    CorpusGovernance, CorpusGovernanceDenied, OfflineCorpusAuthority, PostgresCorpusAuthority,
    PostgresQualificationAuthority,
)
from app.services.grounding.corpus_contracts import CorpusCandidate, CorpusChunk, CorpusDocument, CorpusSource
from app.services.grounding.autonomous.contracts import LearningMaterialDemand, SubjectScope
from app.services.grounding.autonomous.qualified_corpus import QualifiedCorpusAdapter
from app.services.grounding.autonomous.source_review_repository import (
    CompleteCapture, QualityFinding, SourceReviewRepository,
)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class SyntheticQualityVerifier:
    """A test fixture only; no production quality reviewer is installed."""

    def __init__(self, family: str) -> None:
        self.family = family

    def verify(self, capture: CompleteCapture) -> QualityFinding:
        return QualityFinding(
            mode="production", version_fit="current", reading_fit="suitable",
            technical_status="correct", conflict_status="resolved", known_error="absent",
            covered_facets=("queries",), lineage_family=self.family,
            evidence_hash=sha("synthetic-quality"),
        )


class SyntheticExcerptVerifier(SyntheticQualityVerifier):
    """Test-only reviewed substring; no human or real quality assertion."""

    def __init__(self, family: str, excerpt: str) -> None:
        super().__init__(family)
        self.excerpt = excerpt

    def reviewed_usages(self, capture: CompleteCapture) -> tuple[str, ...]:
        return ("supplementary_explanation",)

    def approved_excerpts(self, capture: CompleteCapture) -> tuple[str, ...]:
        return (self.excerpt,)


def test_offline_fake_is_not_live() -> None:
    assert OfflineCorpusAuthority is not PostgresCorpusAuthority
    assert CorpusGovernance.__init__.__kwdefaults__["isolated_operator_enabled"] is False
    fake_connection = SimpleNamespace(
        autocommit=False, info=SimpleNamespace(transaction_status=TransactionStatus.INTRANS),
    )
    with pytest.raises(CorpusGovernanceDenied, match="AUTHORITY_MISSING"):
        CorpusGovernance(fake_connection)._transaction()
    with pytest.raises(CorpusGovernanceDenied, match="AUTHORITY_MISSING"):
        CorpusGovernance(fake_connection, authority=OfflineCorpusAuthority(),
                         isolated_operator_enabled=True)._transaction()
    fake_connection.execute = lambda _sql: SimpleNamespace(fetchone=lambda: {"name": "aearn"})
    with pytest.raises(CorpusGovernanceDenied, match="ISOLATED_DATABASE_REQUIRED"):
        CorpusGovernance(fake_connection, authority=PostgresCorpusAuthority(),
                         source_reviews=SourceReviewRepository(fake_connection, verifier=SyntheticQualityVerifier("fixture.family")),
                         isolated_operator_enabled=True)._transaction()


@pytest.fixture()
def conn():  # type: ignore[no-untyped-def]
    dsn = os.environ.get("AEARN_RAG_C_TEST_DATABASE_URL")
    if dsn is None:
        pytest.skip("explicit disposable AEARN_RAG_C_TEST_DATABASE_URL required")
    name = urlsplit(dsn).path.lstrip("/")
    if not name.startswith("aearn_rag260_c_"):
        pytest.fail("refusing non-disposable C database")
    with psycopg.connect(dsn, row_factory=dict_row) as db:
        found = db.execute("SELECT current_database() AS name").fetchone()
        if found is None or found["name"] != name:
            pytest.fail("current_database() mismatch")
        apply_schema(db)
        apply_schema(db)
        yield db
        db.rollback()


def _seed_sql(conn, *, verifier=None, purpose="main_teaching",
              body_text=None, chunk_text=None):  # type: ignore[no-untyped-def]

    suffix = uuid4().hex[:12]
    root, policy, source, doc = (f"{prefix}.{suffix}" for prefix in ("root", "policy", "source", "document"))
    url = "https://www.sqlite.org/lang_select.html"
    body = body_text or "SELECT title FROM books WHERE id = 1;"  # synthetic local fixture
    now = datetime.now(UTC)
    end = now + timedelta(days=2)
    conn.execute("""INSERT INTO rag_budget_authority_roots
        (root_id,delegation_id,delegation_generation,delegation_expires_at,policy_id,
         policy_generation,period_key,period_start,period_end,cap_units,enabled)
        VALUES (%s,%s,1,%s,%s,1,%s,%s,%s,100,true)""",
        (root, f"delegate.{suffix}", end, policy, suffix, now-timedelta(hours=1), end))
    conn.execute("""INSERT INTO rag_registered_source_policies
        (policy_id,generation,source_handle,subject_id,subject_version,facets,origin,
         reading_level,canonical_url,canonical_url_sha256,host,path,license_id,
         allowed_usages,immutable_history_allowed,max_captured_bytes,retention_until,
         expires_at,root_id,enabled)
        VALUES (%s,1,%s,'route.sql','v1',ARRAY['queries'],'official','beginner',
                %s,%s,'www.sqlite.org','/lang_select.html','PublicDomain',
                %s,true,1048576,%s,%s,%s,true)""",
        (policy, source, url, sha(url), [purpose], end, end, root))
    attempt, capture, review, admission = (uuid4() for _ in range(4))
    conn.execute("""INSERT INTO rag_registered_fetch_attempts
        (id,policy_id,generation,canonical_url_sha256,root_id,operation_key,request_hash,
         state,response_sha256,response_bytes,settled_at)
        VALUES (%s,%s,1,%s,%s,%s,%s,'settled',%s,%s,now())""",
        (attempt, policy, sha(url), root, f"attempt.{suffix}", sha(suffix), sha(body), len(body)))
    conn.execute("""INSERT INTO rag_registered_source_captures
        (id,fetch_attempt_id,policy_id,generation,request_chain,final_url,content_type,
         fetched_sha256,captured_bytes,captured_body,license_id,retention_until)
        VALUES (%s,%s,%s,1,'["https://www.sqlite.org/lang_select.html"]'::jsonb,
                %s,'text/plain',%s,%s,%s,'PublicDomain',%s)""",
        (capture, attempt, policy, url, sha(body), len(body), body.encode(), end))
    reviewer = SourceReviewRepository(conn, verifier=(verifier(f"family.{suffix}") if verifier
        else SyntheticQualityVerifier(f"family.{suffix}")))
    _, capture_authority = reviewer._capture(capture, "registered", now)
    conn.execute("""INSERT INTO rag_source_reviews
        (id,registered_capture_id,source_handle,document_handle,subject_id,subject_version,
         facets,document_revision,document_hash,lineage_family,origin,reading_level,status,
         quality_code,reading_fit,version_fit,technical_status,conflict_status,known_error,
         covered_facets,quality_evidence_hash,storage_receipt_id,license_id,allowed_usages,
         immutable_history_allowed,policy_id,
         policy_generation,root_id,review_receipt_hash)
        VALUES (%s,%s,%s,%s,'route.sql','v1',ARRAY['queries'],%s,%s,%s,'official',
                'beginner','reviewed','QUALIFIED','suitable','current','correct',
                'resolved','absent',ARRAY['queries'],%s,%s,'PublicDomain',%s,
                true,%s,1,%s,%s)""",
        (review, capture, source, doc, sha(body), sha(body), f"family.{suffix}",
         sha('synthetic-quality'), capture_authority["storage_receipt_id"],
         [purpose], policy, root, sha('review')))
    conn.execute("""INSERT INTO rag_source_admissions
        (id,review_id,receipt_handle,allowed_usages,policy_generation,receipt_hash)
        VALUES (%s,%s,%s,%s,1,%s)""",
        (admission, review, f"receipt.{suffix}", [purpose], sha('admission')))
    candidate = CorpusCandidate(corpus_id=uuid4(), subject_id="route.sql", subject_version="v1",
        registry_digest=sha("sql-registry-v1"), retrieval_policy_version="fts-v1",
        coverage_policy_version="dynamic-c-v1")
    common = dict(corpus_id=candidate.corpus_id, subject_id="route.sql", subject_version="v1")
    source_row = CorpusSource(**common, source_id=source, source_hash=sha(source),
        trust_tier="official", source_kind="documentation", source_version=sha(body),
        allowed_domains=("www.sqlite.org",), seed_urls=(url,), facets=("queries",))
    doc_row = CorpusDocument(**common, document_id=doc, source_id=source,
        source_hash=source_row.source_hash, trust_tier="official", canonical_url=url,
        final_url=url, content_type="text/plain", document_version=sha(body), fetched_at=now,
        document_hash=sha(body), parse_status="parsed")
    chunk = CorpusChunk(**common, chunk_id=f"chunk.{suffix}", document_id=doc,
        source_id=source, source_hash=source_row.source_hash, trust_tier="official",
        document_hash=sha(body), ordinal=0, title="SQL queries", section_path="SELECT",
        content=chunk_text or body, facets=("queries",), topic_tags=(),
        chunk_hash=sha(chunk_text or body))
    service = CorpusGovernance(conn, authority=PostgresCorpusAuthority(),
                               source_reviews=reviewer, isolated_operator_enabled=True)
    service.create_candidate(candidate, sources=[source_row], documents=[doc_row],
        chunks=[chunk], admissions={doc: admission}, purpose=purpose,
        idempotency_key=f"create-{suffix}")
    return service, candidate, policy, suffix


def test_partial_sql_and_revocation(conn) -> None:  # type: ignore[no-untyped-def]
    service, candidate, policy, suffix = _seed_sql(conn)
    with pytest.raises(CorpusGovernanceDenied, match="COVERAGE_GAP"):
        service._audit(candidate.corpus_id, purpose="main_teaching", full_required=True)
    with pytest.raises(CorpusGovernanceDenied, match="PURPOSE_DENIED"):
        service.validate(candidate.corpus_id, expected_generation=0,
                         purpose="assessment_evidence", idempotency_key=f"wrong-{suffix}")
    service.validate(candidate.corpus_id, expected_generation=0,
                     purpose="main_teaching", idempotency_key=f"validate-{suffix}")
    version = service.repo.version(candidate.corpus_id)
    assert version.coverage_summary == {"required": 2, "covered": 1, "gap": 1, "partial": True}
    service.activate(candidate.corpus_id, expected_generation=0,
                     summary_hash=version.summary_hash or "", purpose="main_teaching",
                     idempotency_key=f"activate-{suffix}")
    assert service.repo.active("route.sql").generation == 1
    authority = PostgresQualificationAuthority(service)
    adapter = QualifiedCorpusAdapter(authority)
    def demand(facets: tuple[str, ...]) -> LearningMaterialDemand:
        return LearningMaterialDemand(
            scope=SubjectScope(subject_id="route.sql", subject_version="v1", facets=facets),
            demand_hash=sha("demand"), plan_ref="plan.sql", node_ref="node.sql",
            draft_revision=1, purpose="main_teaching", reading_level="beginner", language="en",
        )
    assert adapter.assess(demand(("queries",))).status == "sufficient"
    gap = adapter.assess(demand(("queries", "schema")))
    assert gap is not None and gap.status == "gap" and gap.gap_reason == "coverage_gap"
    conn.execute("UPDATE rag_registered_source_policies SET enabled=false,revoked_at=now() WHERE policy_id=%s", (policy,))
    with pytest.raises(CorpusGovernanceDenied, match="SOURCE_STALE|AUTHORITY_STALE|REVIEW_UNVERIFIED"):
        service.rollback("route.sql", candidate.corpus_id, expected_generation=1,
                         summary_hash=version.summary_hash or "", purpose="main_teaching",
                         idempotency_key=f"rollback-{suffix}")
    assert service.repo.active("route.sql").generation == 1


def test_automated_excerpt_only_corpus(conn) -> None:  # type: ignore[no-untyped-def]
    excerpt = "SELECT title FROM books WHERE id = 1;"
    body = excerpt + " Unreviewed but present in complete source."
    def factory(family: str) -> SyntheticExcerptVerifier:
        return SyntheticExcerptVerifier(family, excerpt)
    with pytest.raises(CorpusGovernanceDenied, match="CHUNK_INVALID"):
        with conn.transaction():  # rollback the entire synthetic seed, including exact-URL policy
            _seed_sql(conn, verifier=factory, purpose="supplementary_explanation",
                      body_text=body, chunk_text=body)
    # An operator policy/review row for main teaching cannot widen this reviewer.
    with pytest.raises(CorpusGovernanceDenied, match="REVIEW_UNVERIFIED"):
        with conn.transaction():
            _seed_sql(conn, verifier=factory, purpose="main_teaching",
                      body_text=body, chunk_text=excerpt)
    service, candidate, _, suffix = _seed_sql(
        conn, verifier=factory, purpose="supplementary_explanation",
        body_text=body, chunk_text=excerpt,
    )
    service.validate(candidate.corpus_id, expected_generation=0,
                     purpose="supplementary_explanation", idempotency_key=f"validate-{suffix}")
    version = service.repo.version(candidate.corpus_id)
    service.activate(candidate.corpus_id, expected_generation=0,
                     summary_hash=version.summary_hash or "",
                     purpose="supplementary_explanation", idempotency_key=f"activate-{suffix}")
    with pytest.raises(CorpusGovernanceDenied, match="ADMISSION_STALE"):
        service._audit(candidate.corpus_id, purpose="main_teaching")
