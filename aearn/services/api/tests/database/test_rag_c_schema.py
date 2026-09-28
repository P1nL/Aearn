"""C schema-only disposable PostgreSQL checks; never a real source fetch."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row


@pytest.fixture()
def conn():  # type: ignore[no-untyped-def]
    dsn = os.environ.get("AEARN_RAG_C_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("C PostgreSQL requires an explicitly disposable database URL")
    name = urlsplit(dsn).path.lstrip("/")
    if not name.startswith("aearn_rag260_c_"):
        pytest.fail("C tests refuse non-aearn_rag260_c_ database")
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        assert connection.execute("SELECT current_database() AS name").fetchone()["name"] == name
        assert connection.execute(
            "SELECT to_regclass('rag_registered_source_policies') AS name"
        ).fetchone()["name"] is not None
        yield connection
        connection.rollback()


def test_default_closed_one_shot_capture_review_and_execution_denial(conn) -> None:  # type: ignore[no-untyped-def]
    key = uuid4().hex
    now = datetime.now(timezone.utc)
    root, policy, source, document = (
        f"root.c.{key}", f"policy.c.{key}", f"source.c.{key}", f"document.c.{key}"
    )
    url = "https://www.sqlite.org/lang_select.html"
    body = b"SELECT 1;"  # synthetic schema fixture, not the approved real page
    digest = hashlib.sha256(body).hexdigest()
    conn.execute(
        "INSERT INTO rag_budget_authority_roots(root_id,delegation_id,delegation_generation,"
        "delegation_expires_at,policy_id,policy_generation,period_key,period_start,"
        "period_end,cap_units,enabled) VALUES (%s,%s,1,%s,%s,1,%s,%s,%s,1,true)",
        (root, f"delegation.c.{key}", now + timedelta(days=2), policy,
         f"period.{key}", now - timedelta(hours=1), now + timedelta(days=2)),
    )
    conn.execute(
        "INSERT INTO rag_registered_source_policies(policy_id,generation,source_handle,"
        "subject_id,subject_version,facets,origin,reading_level,canonical_url,"
        "canonical_url_sha256,host,path,license_id,allowed_usages,immutable_history_allowed,"
        "max_captured_bytes,retention_until,expires_at,root_id) "
        "VALUES (%s,1,%s,'route.sql','sqlite-docs-v1',%s,'official','beginner',"
        "%s,%s,'www.sqlite.org','/lang_select.html','PublicDomain',%s,true,1024,%s,%s,%s)",
        (policy, source, ["queries"], url, hashlib.sha256(url.encode()).hexdigest(),
         ["main_teaching"], now + timedelta(days=1), now + timedelta(days=2), root),
    )
    row = conn.execute(
        "SELECT enabled,immutable_history_allowed FROM rag_registered_source_policies "
        "WHERE policy_id=%s", (policy,),
    ).fetchone()
    assert row == {"enabled": False, "immutable_history_allowed": True}
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute(
                "INSERT INTO rag_registered_source_policies SELECT (jsonb_populate_record("
                "NULL::rag_registered_source_policies, to_jsonb(p) || jsonb_build_object("
                "'policy_id',p.policy_id || '.bad', 'source_handle',p.source_handle || '.bad',"
                "'canonical_url_sha256',%s::text))).* FROM rag_registered_source_policies p "
                "WHERE p.policy_id=%s", ("0" * 64, policy),
            )
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute(
                "UPDATE rag_registered_source_policies SET source_handle='source.wrong' WHERE policy_id=%s",
                (policy,),
            )
    attempt = conn.execute(
        "INSERT INTO rag_registered_fetch_attempts(policy_id,generation,canonical_url_sha256,"
        "root_id,operation_key,request_hash) VALUES (%s,1,%s,%s,%s,%s) RETURNING id",
        (policy, hashlib.sha256(url.encode()).hexdigest(), root, f"fetch.{key}", "a" * 64),
    ).fetchone()["id"]
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute(
                "INSERT INTO rag_registered_source_captures(fetch_attempt_id,policy_id,generation,"
                "request_chain,final_url,content_type,fetched_sha256,captured_bytes,captured_body,"
                "license_id,retention_until) VALUES (%s,%s,1,%s::jsonb,%s,'text/plain',%s,%s,%s,"
                "'PublicDomain',%s)",
                (attempt, policy, json.dumps([url]), url, digest, len(body), body,
                 now + timedelta(days=1)),
            )
    conn.execute("UPDATE rag_registered_source_policies SET enabled=true WHERE policy_id=%s", (policy,))
    conn.execute(
        "UPDATE rag_registered_fetch_attempts SET state='settled',response_sha256=%s,"
        "response_bytes=%s,settled_at=%s WHERE id=%s", (digest, len(body), now, attempt),
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        with conn.transaction():
            conn.execute(
                "INSERT INTO rag_registered_fetch_attempts(policy_id,generation,canonical_url_sha256,"
                "root_id,operation_key,request_hash) VALUES (%s,1,%s,%s,%s,%s)",
                (policy, hashlib.sha256(url.encode()).hexdigest(), root, f"fetch.retry.{key}", "a" * 64),
            )
    capture = conn.execute(
        "INSERT INTO rag_registered_source_captures(fetch_attempt_id,policy_id,generation,"
        "request_chain,final_url,content_type,fetched_sha256,captured_bytes,captured_body,"
        "license_id,retention_until) VALUES (%s,%s,1,%s::jsonb,%s,'text/plain',%s,%s,%s,"
        "'PublicDomain',%s) RETURNING id",
        (attempt, policy, json.dumps([url]), url, digest, len(body), body, now + timedelta(days=1)),
    ).fetchone()["id"]
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute(
                "INSERT INTO rag_source_reviews(registered_capture_id,source_handle,document_handle,"
                "subject_id,subject_version,facets,document_revision,document_hash,lineage_family,"
                "origin,reading_level,status,quality_code,reading_fit,version_fit,technical_status,"
                "conflict_status,known_error,covered_facets,quality_evidence_hash,storage_receipt_id,"
                "license_id,allowed_usages,"
                "immutable_history_allowed,policy_id,policy_generation,root_id,review_receipt_hash) "
                "VALUES (%s,%s,%s,'route.sql','sqlite-docs-v1',%s,'v1',%s,%s,'official',"
                "'beginner','reviewed','QUALIFIED','suitable','current','correct','resolved',"
        "'absent',%s,%s,%s,'PublicDomain',%s,true,%s,1,%s,%s)",
                (capture, source, document, ["queries"], "0" * 64, f"family.c.{key}",
                 ["queries"], "a" * 64, f"storage.c.{key}", ["main_teaching"], policy, root, "b" * 64),
            )
    review = conn.execute(
        "INSERT INTO rag_source_reviews(registered_capture_id,source_handle,document_handle,"
        "subject_id,subject_version,facets,document_revision,document_hash,lineage_family,"
        "origin,reading_level,status,quality_code,reading_fit,version_fit,technical_status,"
        "conflict_status,known_error,covered_facets,quality_evidence_hash,storage_receipt_id,"
        "license_id,allowed_usages,"
        "immutable_history_allowed,policy_id,policy_generation,root_id,review_receipt_hash) "
        "VALUES (%s,%s,%s,'route.sql','sqlite-docs-v1',%s,'v1',%s,%s,'official',"
        "'beginner','reviewed','QUALIFIED','suitable','current','correct','resolved',"
        "'absent',%s,%s,%s,'PublicDomain',%s,true,%s,1,%s,%s) RETURNING id",
        (capture, source, document, ["queries"], digest, f"family.c.{key}",
         ["queries"], "a" * 64, f"storage.c.{key}", ["main_teaching"], policy, root, "b" * 64),
    ).fetchone()["id"]
    admission = conn.execute(
        "INSERT INTO rag_source_admissions(review_id,receipt_handle,allowed_usages,"
        "policy_generation,receipt_hash) VALUES (%s,%s,%s,1,%s) RETURNING id",
        (review, f"admission.c.{key}", ["main_teaching"], "c" * 64),
    ).fetchone()["id"]
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute(
                "INSERT INTO rag_source_claim_receipts(admission_id,claim_hash,demand_hash,subject_id,"
                "subject_version,source_document_hash,applicability_hash,method,"
                "execution_receipt_handle,verification_receipt_hash) "
                "VALUES (%s,%s,%s,'route.sql','sqlite-docs-v1',%s,%s,'isolated_execution',%s,%s)",
                (admission, "d" * 64, "e" * 64, digest, "f" * 64,
                 f"execution.c.{key}", "0" * 64),
            )
    conn.execute("UPDATE rag_registered_source_policies SET enabled=false WHERE policy_id=%s", (policy,))
    disabled = conn.execute(
        "SELECT enabled,revoked_at FROM rag_registered_source_policies WHERE policy_id=%s", (policy,)
    ).fetchone()
    assert disabled["enabled"] is False and disabled["revoked_at"] is not None
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute("UPDATE rag_registered_source_policies SET enabled=true WHERE policy_id=%s", (policy,))


def test_registered_url_is_one_shot_across_policy_ids(conn) -> None:  # type: ignore[no-untyped-def]
    key = uuid4().hex
    now = datetime.now(timezone.utc)
    url = "https://www.sqlite.org/lang_select.html"
    url_hash = hashlib.sha256(url.encode()).hexdigest()
    for number in (1, 2):
        policy = f"policy.c.once.{key}.{number}"
        root = f"root.c.once.{key}.{number}"
        conn.execute(
            "INSERT INTO rag_budget_authority_roots(root_id,delegation_id,delegation_generation,"
            "delegation_expires_at,policy_id,policy_generation,period_key,period_start,"
            "period_end,cap_units,enabled) VALUES (%s,%s,1,%s,%s,1,%s,%s,%s,1,true)",
            (root, f"delegation.c.{key}.{number}", now + timedelta(days=2), policy,
             f"period.c.{key}.{number}", now - timedelta(hours=1), now + timedelta(days=2)),
        )
        conn.execute(
            "INSERT INTO rag_registered_source_policies(policy_id,generation,source_handle,"
            "subject_id,subject_version,facets,origin,reading_level,canonical_url,"
            "canonical_url_sha256,host,path,license_id,allowed_usages,"
            "immutable_history_allowed,max_captured_bytes,retention_until,expires_at,root_id) "
            "VALUES (%s,1,%s,'route.sql','sqlite-docs-v1',%s,'official','beginner',"
            "%s,%s,'www.sqlite.org','/lang_select.html','PublicDomain',%s,true,1024,%s,%s,%s)",
            (policy, f"source.c.once.{key}.{number}", ["queries"], url, url_hash,
             ["main_teaching"], now + timedelta(days=1), now + timedelta(days=2), root),
        )
        attempt = (
            "INSERT INTO rag_registered_fetch_attempts(policy_id,generation,"
            "canonical_url_sha256,root_id,operation_key,request_hash) "
            "VALUES (%s,1,%s,%s,%s,%s)"
        )
        values = (policy, url_hash, root, f"fetch.c.once.{key}.{number}", "a" * 64)
        if number == 1:
            conn.execute(attempt, values)
        else:
            with pytest.raises(psycopg.errors.UniqueViolation):
                with conn.transaction():
                    conn.execute(attempt, values)
