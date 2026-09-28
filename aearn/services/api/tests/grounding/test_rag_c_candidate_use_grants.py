"""Synthetic B-to-C fixture only; no provider, real capture, or reviewer authority."""
from __future__ import annotations

import os
from urllib.parse import urlsplit
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.db.bootstrap import apply_schema

from app.services.grounding.autonomous.candidate_use_grants import PostgresCandidateGrantResolver
from app.services.grounding.autonomous.corpus_governance import (
    CorpusGovernance, CorpusGovernanceDenied, PostgresCandidateCorpusAuthority,
)
from app.services.grounding.autonomous.source_review_repository import SourceReviewRepository
from app.services.grounding.corpus_contracts import CorpusCandidate, CorpusChunk, CorpusDocument, CorpusSource
from tests.grounding.test_rag_c_corpus_governance import SyntheticQualityVerifier, sha


@pytest.fixture()
def pg_conn():  # type: ignore[no-untyped-def]
    dsn = os.environ.get("AEARN_RAG_C_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("explicit disposable C test database required")
    expected = urlsplit(dsn).path.lstrip("/")
    if not expected.startswith("aearn_rag260_c_"):
        pytest.fail("C test database must be disposable")
    with psycopg.connect(dsn, row_factory=dict_row) as db:
        assert db.execute("SELECT current_database() AS name").fetchone()["name"] == expected
        apply_schema(db)
        apply_schema(db)
        try:
            yield db
        finally:
            db.rollback()


def _seed(conn):  # type: ignore[no-untyped-def]
    suffix = uuid4().hex[:12]
    now, end = datetime.now(UTC), datetime.now(UTC) + timedelta(days=2)
    root, policy = f"root.{suffix}", f"policy.{suffix}"
    budget_policy = f"budget.{suffix}"  # B1 and B2 policies are distinct authorities.
    source, doc = f"source.{suffix}", f"document.{suffix}"
    url = "https://example.org/select"
    body = "SELECT title FROM books WHERE id = 1;"  # never fetched
    digest = sha(body)
    conn.execute("""INSERT INTO rag_budget_authority_roots
        (root_id,delegation_id,delegation_generation,delegation_expires_at,policy_id,
         policy_generation,period_key,period_start,period_end,cap_units,enabled)
        VALUES (%s,%s,1,%s,%s,1,%s,%s,%s,10,true)""",
        (root, f"delegate.{suffix}", end, budget_policy, suffix, now-timedelta(hours=1), end))
    conn.execute("INSERT INTO rag_budget_periods(root_id,period_key,cap_units,period_end) VALUES (%s,%s,10,%s)",
                 (root, suffix, end))
    job = conn.execute("""INSERT INTO rag_discovery_jobs
        (operation_key,request_hash,query_hash,demand_hash,subject_id,subject_version,purpose,
         policy_id,policy_generation,root_id,delegation_id,delegation_generation,state,terminal_at)
        VALUES (%s,%s,%s,%s,'route.sql','v1','main_teaching',%s,1,%s,%s,1,'completed',%s) RETURNING id""",
        (f"job.{suffix}", digest, digest, digest, budget_policy, root, f"delegate.{suffix}", now)).fetchone()["id"]
    reservation = conn.execute("""INSERT INTO rag_budget_reservations
        (root_id,period_key,operation_key,request_hash,job_id,reserved_units,state,settled_units,settlement_receipt_hash)
        VALUES (%s,%s,%s,%s,%s,1,'settled',1,%s) RETURNING id""",
        (root, suffix, f"reserve.{suffix}", digest, job, digest)).fetchone()["id"]
    attempt = conn.execute("""INSERT INTO rag_budget_attempts
        (reservation_id,job_id,attempt_key,state,dispatch_owner_id,dispatch_generation,dispatched_at)
        VALUES (%s,%s,%s,'settled','worker.fixture',1,%s) RETURNING id""",
        (reservation, job, f"attempt.{suffix}", now)).fetchone()["id"]
    receipt = conn.execute("""INSERT INTO rag_discovery_receipts
        (job_id,attempt_id,receipt_handle,result_code,response_hash)
        VALUES (%s,%s,%s,'SEARCH_COMPLETED',%s) RETURNING id""",
        (job, attempt, f"receipt.{suffix}", digest)).fetchone()["id"]
    candidate = conn.execute("""INSERT INTO rag_discovery_candidates
        (job_id,discovery_receipt_id,canonical_url,canonical_url_hash,kind,demand_hash,subject_id,subject_version)
        VALUES (%s,%s,%s,%s,'document',%s,'route.sql','v1') RETURNING id""",
        (job, receipt, url, sha(url), digest)).fetchone()["id"]
    conn.execute("""INSERT INTO rag_candidate_access_policies
        (policy_id,current_generation,enabled,expires_at) VALUES (%s,1,true,%s)""", (policy, end))
    conn.execute("""INSERT INTO rag_candidate_access_rules
        (policy_id,generation,host,path_prefix,probe_allowed,store_allowed,allowed_capture,
         max_captured_bytes,license_id,valid_until,retention_until)
        VALUES (%s,1,'example.org','/select',true,true,'full',1048576,'PublicDomain',%s,%s)""",
        (policy, end, end))
    conn.execute("""INSERT INTO rag_candidate_intake_leases
        (candidate_id,job_id,state,generation) VALUES (%s,%s,'done',1)""", (candidate, job))
    captured = conn.execute("""INSERT INTO rag_candidate_captures
        (candidate_id,job_id,evidence_level,final_url,request_chain,chain_sha256,
         media_type,fetched_sha256,capture_kind,captured_bytes,full_sha256,captured_body,
         policy_id,policy_generation,retention_until,license_id)
        VALUES (%s,%s,'live_egress_attested',%s,%s,%s,'text/plain',%s,'full',%s,%s,%s,%s,1,%s,'PublicDomain')
        RETURNING id""",
        (candidate, job, url, '["https://example.org/select"]', digest,
         digest, len(body.encode()), digest, body.encode(), policy, end)).fetchone()["id"]
    return suffix, root, policy, source, doc, url, body, captured, end


def test_b_formal_grant_to_partial_corpus_and_revoke(pg_conn):  # type: ignore[no-untyped-def]
    conn = pg_conn
    suffix, root, policy, source, doc, url, body, capture_id, end = _seed(conn)
    grants = PostgresCandidateGrantResolver(conn)
    assert grants.resolve(capture_id) is None  # B temporary store is not formal use.
    conn.execute("""INSERT INTO rag_candidate_use_grants
        (capture_id,capture_sha256,policy_id,policy_generation,root_id,license_id,
         source_handle,subject_id,subject_version,facets,origin,reading_level,
         allowed_usages,immutable_history_allowed,retained_until,storage_receipt_id,
         approval_ref,active)
        VALUES (%s,%s,%s,1,%s,'PublicDomain',%s,'route.sql','v1',ARRAY['queries'],
                'tutorial','beginner',ARRAY['main_teaching'],true,%s,%s,%s,true)""",
        (capture_id, sha(body), policy, root, source, end,
         f"store.{suffix}", f"operator-approved-fixture.{suffix}"))
    assert grants.resolve(capture_id) is not None
    conn.execute("UPDATE rag_budget_authority_roots SET policy_generation=2 WHERE root_id=%s", (root,))
    assert grants.resolve(capture_id) is None  # B1 root identity must match the job.
    conn.execute("UPDATE rag_budget_authority_roots SET policy_generation=1 WHERE root_id=%s", (root,))
    reviewer = SourceReviewRepository(conn, verifier=SyntheticQualityVerifier(f"family.{suffix}"),
                                      candidate_grants=grants)
    review_id = reviewer.review_and_admit(capture_id=capture_id, lane="candidate",
        document_handle=doc, requested_usages=("main_teaching",), now=datetime.now(UTC))
    admission = conn.execute("SELECT id FROM rag_source_admissions WHERE review_id=%s", (review_id,)).fetchone()["id"]
    candidate = CorpusCandidate(corpus_id=uuid4(), subject_id="route.sql", subject_version="v1",
        registry_digest=sha("sql-registry-v1"), retrieval_policy_version="fts-v1",
        coverage_policy_version="dynamic-c-v1")
    common = dict(corpus_id=candidate.corpus_id, subject_id="route.sql", subject_version="v1")
    source_row = CorpusSource(**common, source_id=source, source_hash=sha(source),
        trust_tier="trusted_de_facto", source_kind="documentation", source_version=sha(body),
        allowed_domains=("example.org",), seed_urls=(url,), facets=("queries",))
    doc_row = CorpusDocument(**common, document_id=doc, source_id=source,
        source_hash=source_row.source_hash, trust_tier="trusted_de_facto", canonical_url=url,
        final_url=url, content_type="text/plain", document_version=sha(body),
        fetched_at=datetime.now(UTC), document_hash=sha(body), parse_status="parsed")
    def chunk(text: str) -> CorpusChunk:
        return CorpusChunk(**common, chunk_id=f"chunk.{suffix}", document_id=doc,
            source_id=source, source_hash=source_row.source_hash, trust_tier="trusted_de_facto",
            document_hash=sha(body), ordinal=0, title="SQL queries", section_path="SELECT",
            content=text, facets=("queries",), topic_tags=(), chunk_hash=sha(text))
    service = CorpusGovernance(conn, authority=PostgresCandidateCorpusAuthority(),
        source_reviews=reviewer, isolated_operator_enabled=True)
    with pytest.raises(CorpusGovernanceDenied, match="CHUNK_INVALID"):
        service.create_candidate(candidate, sources=[source_row], documents=[doc_row],
            chunks=[chunk("invented SELECT" )], admissions={doc: admission},
            purpose="main_teaching", idempotency_key=f"invented-{suffix}")
    service.create_candidate(candidate, sources=[source_row], documents=[doc_row],
        chunks=[chunk(body)], admissions={doc: admission}, purpose="main_teaching",
        idempotency_key=f"create-{suffix}")
    service.validate(candidate.corpus_id, expected_generation=0,
        purpose="main_teaching", idempotency_key=f"validate-{suffix}")
    version = service.repo.version(candidate.corpus_id)
    assert version.coverage_summary == {"required": 2, "covered": 1, "gap": 1, "partial": True}
    service.activate(candidate.corpus_id, expected_generation=0,
        summary_hash=version.summary_hash or "", purpose="main_teaching",
        idempotency_key=f"activate-{suffix}")
    conn.execute("UPDATE rag_candidate_use_grants SET active=false,revoked_at=now() WHERE capture_id=%s",
                 (capture_id,))
    assert grants.resolve(capture_id) is None
    with pytest.raises(CorpusGovernanceDenied, match="REVIEW_UNVERIFIED"):
        service._audit(candidate.corpus_id, purpose="main_teaching")
    with pytest.raises(psycopg.Error):
        with conn.transaction():
            conn.execute("UPDATE rag_candidate_use_grants SET active=true WHERE capture_id=%s", (capture_id,))