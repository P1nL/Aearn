"""Independent C authority regressions; no network or database access."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

import psycopg
import pytest
from psycopg.rows import dict_row

from app.db.bootstrap import apply_schema

from app.services.grounding.autonomous.corpus_governance import (
    CorpusGovernanceDenied,
    PostgresCorpusAuthority,
)


class _Rows:
    def __init__(self, rows: dict[str, Any]) -> None:
        self.rows = rows

    def execute(self, sql: str, _params: tuple[str, ...] | None = None) -> SimpleNamespace:
        if "rag_registered_source_policies" in sql:
            row = self.rows["policy"]
        elif "rag_budget_authority_roots" in sql:
            row = self.rows["root"]
        else:
            row = {"now": self.rows["now"]}
        return SimpleNamespace(fetchone=lambda: row)


def test_corpus_activation_root_must_match_registered_policy_generation() -> None:
    """An enabled root delegated to another policy cannot authorize this corpus."""
    now = datetime.now(UTC)
    rows = {
        "now": now,
        "policy": {
            "generation": 1,
            "root_id": "root.registered",
            "subject_id": "route.sql",
            "subject_version": "v1",
            "enabled": True,
            "revoked_at": None,
            "expires_at": now + timedelta(hours=1),
            "retention_until": now + timedelta(hours=1),
            "immutable_history_allowed": True,
        },
        "root": {
            "root_id": "root.registered",
            "enabled": True,
            "policy_id": "policy.other",
            "policy_generation": 2,
            "delegation_expires_at": now + timedelta(hours=1),
            "period_start": now - timedelta(hours=1),
            "period_end": now + timedelta(hours=1),
        },
    }
    with pytest.raises(CorpusGovernanceDenied, match="AUTHORITY_STALE"):
        PostgresCorpusAuthority().require_current(
            _Rows(rows),  # type: ignore[arg-type]
            policy_id="policy.registered",
            generation=1,
            root_id="root.registered",
            subject_id="route.sql",
            subject_version="v1",
            now=now,
        )


@pytest.fixture()
def conn() -> Any:
    import os

    dsn = os.environ.get("AEARN_RAG_C_TEST_DATABASE_URL")
    if dsn is None:
        pytest.skip("explicit disposable C database required")
    name = urlsplit(dsn).path.lstrip("/")
    if not name.startswith("aearn_rag260_c_"):
        pytest.fail("C regression refuses non-disposable database")
    with psycopg.connect(dsn, row_factory=dict_row) as db:
        row = db.execute("SELECT current_database() AS name").fetchone()
        if row is None or row["name"] != name:
            pytest.fail("current_database() mismatch")
        apply_schema(db)
        apply_schema(db)
        yield db
        db.rollback()


@pytest.mark.parametrize("case", ["valid_chunk", "invented_chunk", "root_mismatch"])
def test_current_capture_and_chunk_authority(conn: Any, case: str) -> None:
    """Exact text passes; invented content and a relabeled root fail closed."""
    from uuid import uuid4
    from hashlib import sha256
    from app.services.grounding.autonomous.corpus_governance import CorpusGovernance
    from app.services.grounding.autonomous.source_review_repository import (
        ReviewDenied, SourceReviewRepository,
    )
    from app.services.grounding.corpus_contracts import (
        CorpusCandidate, CorpusChunk, CorpusDocument, CorpusSource,
    )
    from tests.grounding.test_rag_c_corpus_governance import SyntheticQualityVerifier

    def sha(text: str) -> str:
        return sha256(text.encode()).hexdigest()

    suffix = uuid4().hex[:12]
    root, policy, source, document = (f"{p}.{suffix}" for p in ("root", "policy", "source", "document"))
    url = "https://www.sqlite.org/lang_select.html"
    body = "SELECT title FROM books;"
    invented = "DELETE all records without a WHERE clause;"
    now = datetime.now(UTC)
    end = now + timedelta(days=2)
    conn.execute(
        """INSERT INTO rag_budget_authority_roots
        (root_id,delegation_id,delegation_generation,delegation_expires_at,policy_id,
         policy_generation,period_key,period_start,period_end,cap_units,enabled)
        VALUES (%s,%s,1,%s,%s,1,%s,%s,%s,100,true)""",
        (root, f"delegate.{suffix}", end, policy, suffix, now - timedelta(hours=1), end),
    )
    conn.execute(
        """INSERT INTO rag_registered_source_policies
        (policy_id,generation,source_handle,subject_id,subject_version,facets,origin,
         reading_level,canonical_url,canonical_url_sha256,host,path,license_id,
         allowed_usages,immutable_history_allowed,max_captured_bytes,retention_until,
         expires_at,root_id,enabled)
        VALUES (%s,1,%s,'route.sql','v1',ARRAY['queries'],'official','beginner',
                %s,%s,'www.sqlite.org','/lang_select.html','PublicDomain',
                ARRAY['main_teaching'],true,1048576,%s,%s,%s,true)""",
        (policy, source, url, sha(url), end, end, root),
    )
    attempt, capture, review, admission = (uuid4() for _ in range(4))
    conn.execute(
        """INSERT INTO rag_registered_fetch_attempts
        (id,policy_id,generation,canonical_url_sha256,root_id,operation_key,request_hash,
         state,response_sha256,response_bytes,settled_at)
        VALUES (%s,%s,1,%s,%s,%s,%s,'settled',%s,%s,now())""",
        (attempt, policy, sha(url), root, f"attempt.{suffix}", sha(suffix), sha(body), len(body)),
    )
    conn.execute(
        """INSERT INTO rag_registered_source_captures
        (id,fetch_attempt_id,policy_id,generation,request_chain,final_url,content_type,
         fetched_sha256,captured_bytes,captured_body,license_id,retention_until)
        VALUES (%s,%s,%s,1,%s::jsonb,%s,'text/plain',%s,%s,%s,'PublicDomain',%s)""",
        (capture, attempt, policy, '["' + url + '"]', url, sha(body), len(body), body.encode(), end),
    )
    reviewer = SourceReviewRepository(conn, verifier=SyntheticQualityVerifier(f"family.{suffix}"))
    if case == "root_mismatch":
        conn.execute("UPDATE rag_budget_authority_roots SET policy_id=%s WHERE root_id=%s",
                     ("policy.other", root))
        with pytest.raises(ReviewDenied, match="ROOT_DENIED"):
            reviewer._capture(capture, "registered", now)
        return
    _, cap = reviewer._capture(capture, "registered", now)
    conn.execute(
        """INSERT INTO rag_source_reviews
        (id,registered_capture_id,source_handle,document_handle,subject_id,subject_version,
         facets,document_revision,document_hash,lineage_family,origin,reading_level,status,
         quality_code,reading_fit,version_fit,technical_status,conflict_status,known_error,
         covered_facets,quality_evidence_hash,storage_receipt_id,license_id,allowed_usages,
         immutable_history_allowed,policy_id,policy_generation,root_id,review_receipt_hash)
        VALUES (%s,%s,%s,%s,'route.sql','v1',ARRAY['queries'],%s,%s,%s,'official',
                'beginner','reviewed','QUALIFIED','suitable','current','correct',
                'resolved','absent',ARRAY['queries'],%s,%s,'PublicDomain',ARRAY['main_teaching'],
                true,%s,1,%s,%s)""",
        (review, capture, source, document, sha(body), sha(body), f"family.{suffix}",
         sha("synthetic-quality"), cap["storage_receipt_id"], policy, root, sha("review")),
    )
    conn.execute(
        """INSERT INTO rag_source_admissions
        (id,review_id,receipt_handle,allowed_usages,policy_generation,receipt_hash)
        VALUES (%s,%s,%s,ARRAY['main_teaching'],1,%s)""",
        (admission, review, f"receipt.{suffix}", sha("admission")),
    )
    candidate = CorpusCandidate(
        corpus_id=uuid4(), subject_id="route.sql", subject_version="v1",
        registry_digest=sha("sql-registry-v1"), retrieval_policy_version="fts-v1",
        coverage_policy_version="dynamic-c-v1",
    )
    common = dict(corpus_id=candidate.corpus_id, subject_id="route.sql", subject_version="v1")
    source_row = CorpusSource(
        **common, source_id=source, source_hash=sha(source), trust_tier="official",
        source_kind="documentation", source_version=sha(body),
        allowed_domains=("www.sqlite.org",), seed_urls=(url,), facets=("queries",),
    )
    document_row = CorpusDocument(
        **common, document_id=document, source_id=source, source_hash=source_row.source_hash,
        trust_tier="official", canonical_url=url, final_url=url, content_type="text/plain",
        document_version=sha(body), fetched_at=now, document_hash=sha(body), parse_status="parsed",
    )
    chunk_content = invented if case == "invented_chunk" else body
    chunk = CorpusChunk(
        **common, chunk_id=f"chunk.{suffix}", document_id=document, source_id=source,
        source_hash=source_row.source_hash, trust_tier="official", document_hash=sha(body),
        ordinal=0, title="SQL queries", section_path="SELECT", content=chunk_content,
        facets=("queries",), topic_tags=(), chunk_hash=sha(chunk_content),
    )
    service = CorpusGovernance(
        conn, authority=PostgresCorpusAuthority(), source_reviews=reviewer,
        isolated_operator_enabled=True,
    )
    def create() -> None:
        service.create_candidate(
            candidate, sources=[source_row], documents=[document_row], chunks=[chunk],
            admissions={document: admission}, purpose="main_teaching",
            idempotency_key=f"create-{suffix}",
        )

    if case == "invented_chunk":
        with pytest.raises(CorpusGovernanceDenied, match="CHUNK_INVALID"):
            create()
        assert service.repo.active("route.sql") is None
    else:
        create()
        service.validate(candidate.corpus_id, expected_generation=0,
                         purpose="main_teaching", idempotency_key=f"validate-{suffix}")
        assert service.repo.version(candidate.corpus_id).state == "validated"
