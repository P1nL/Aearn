"""Focused provider-capture persistence tests; never call Tavily or a source URL."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4

os.environ["DATABASE_URL"] = "postgresql://disabled:disabled@127.0.0.1:1/unreachable"
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["LLM_TYPE"] = "disabled"

import psycopg
import pytest
from psycopg.rows import dict_row

from app.db.bootstrap import apply_schema
from app.services.grounding.autonomous.source_review_repository import SourceReviewRepository
from app.services.grounding.autonomous.tavily_capture_repository import (
    TavilyCaptureDenied,
    TavilyCaptureRepository,
)
from app.services.grounding.autonomous.tavily_extract import TavilyExtractResult

_URL = "https://www.sqlite.org/lang_select.html"


@pytest.fixture()
def pg():  # type: ignore[no-untyped-def]
    dsn = os.environ.get("AEARN_RAG_C_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("set explicit AEARN_RAG_C_TEST_DATABASE_URL for C disposable PostgreSQL")
    expected = urlsplit(dsn).path.lstrip("/")
    if not expected.startswith("aearn_rag260_c_"):
        pytest.fail("C test database must be named aearn_rag260_c_*")
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        actual = conn.execute("SELECT current_database() AS name").fetchone()
        assert actual is not None and actual["name"] == expected
        apply_schema(conn)
        apply_schema(conn)
        try:
            yield conn
        finally:
            conn.rollback()


def _seed(pg, *, cap_units: int = 2) -> tuple[str, str, datetime]:  # type: ignore[no-untyped-def]
    suffix = uuid4().hex
    policy_id = "provider." + suffix
    root_id = "root." + suffix
    now = pg.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
    until = now + timedelta(hours=2)
    pg.execute(
        "INSERT INTO rag_budget_authority_roots "
        "(root_id,delegation_id,delegation_generation,delegation_expires_at,policy_id,"
        "policy_generation,period_key,period_start,period_end,cap_units,enabled) "
        "VALUES (%s,%s,1,%s,%s,1,%s,%s,%s,%s,true)",
        (
            root_id,
            "delegation." + suffix,
            until,
            policy_id,
            "period." + suffix,
            now - timedelta(minutes=1),
            until,
            cap_units,
        ),
    )
    pg.execute(
        "INSERT INTO rag_registered_source_policies "
        "(policy_id,generation,source_handle,subject_id,subject_version,facets,origin,"
        "reading_level,canonical_url,canonical_url_sha256,host,path,license_id,allowed_usages,"
        "immutable_history_allowed,max_captured_bytes,retention_until,expires_at,root_id,enabled) "
        "VALUES (%s,1,%s,'route.sql','v1',ARRAY['queries'],'official','beginner',%s,%s,"
        "'www.sqlite.org','/lang_select.html','public-domain',"
        "ARRAY['supplementary_explanation'],true,8388608,%s,%s,%s,true)",
        (
            policy_id,
            "source." + suffix,
            _URL,
            hashlib.sha256(_URL.encode()).hexdigest(),
            until,
            until,
            root_id,
        ),
    )
    return policy_id, root_id, until


def _result(pg, content: str, *, content_format: str = "markdown") -> TavilyExtractResult:  # type: ignore[no-untyped-def]
    received = pg.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
    body = content.encode()
    return TavilyExtractResult(
        url=_URL,
        content=content,
        content_format=content_format,
        extract_depth="advanced",
        request_id="123e4567-e89b-12d3-a456-426614174111",
        usage_credits=0,
        content_sha256=hashlib.sha256(body).hexdigest(),
        response_sha256="b" * 64,
        received_at=received,
    )


def _direct_history(pg, policy_id: str, until: datetime) -> UUID:  # type: ignore[no-untyped-def]
    body = b"existing direct capture history"
    digest = hashlib.sha256(body).hexdigest()
    policy = pg.execute(
        "SELECT root_id,canonical_url_sha256 FROM rag_registered_source_policies "
        "WHERE policy_id=%s",
        (policy_id,),
    ).fetchone()
    attempt = pg.execute(
        "INSERT INTO rag_registered_fetch_attempts "
        "(policy_id,generation,canonical_url_sha256,root_id,operation_key,request_hash) "
        "VALUES (%s,1,%s,%s,%s,%s) RETURNING id",
        (
            policy_id,
            policy["canonical_url_sha256"],
            policy["root_id"],
            "direct." + uuid4().hex,
            "a" * 64,
        ),
    ).fetchone()
    pg.execute(
        "UPDATE rag_registered_fetch_attempts SET state='settled',response_sha256=%s,"
        "response_bytes=%s,settled_at=clock_timestamp() WHERE id=%s",
        (digest, len(body), attempt["id"]),
    )
    capture = pg.execute(
        "INSERT INTO rag_registered_source_captures "
        "(fetch_attempt_id,policy_id,generation,request_chain,final_url,content_type,"
        "fetched_sha256,captured_bytes,captured_body,license_id,retention_until) "
        "VALUES (%s,%s,1,%s,%s,'text/plain',%s,%s,%s,'public-domain',%s) RETURNING id",
        (attempt["id"], policy_id, json.dumps([_URL]), _URL, digest, len(body), body, until),
    ).fetchone()
    return capture["id"]


def test_provider_dispatch_settle_resolve_and_direct_history_is_unchanged(pg) -> None:  # type: ignore[no-untyped-def]
    policy_id, _, until = _seed(pg)
    direct_capture_id = _direct_history(pg, policy_id, until)
    repository = TavilyCaptureRepository(pg)
    attempt_id = repository.dispatch(
        policy_id=policy_id,
        generation=1,
        operation_key="extract." + uuid4().hex,
        request_sha256="c" * 64,
    )
    capture_id = uuid4()
    assert repository.settle(
        attempt_id=attempt_id,
        result=_result(pg, "# SQLite SELECT\nProvider markdown."),
        capture_id=capture_id,
    ) == capture_id

    now = pg.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
    resolved = repository.resolve_capture(capture_id, now)
    assert resolved is not None
    capture, policy = resolved
    assert capture.body == b"# SQLite SELECT\nProvider markdown."
    assert policy["content_format"] == "markdown"
    assert policy["usage_credits"] == 0
    digest = repository.provenance_digest(capture, expected_format="markdown")
    assert digest is not None and len(digest) == 64
    assert repository.provenance_digest(capture, expected_format="text") is None
    assert SourceReviewRepository(
        pg, registered_provider_captures=repository,
    )._capture(capture_id, "registered", now)[0] == capture

    direct = pg.execute(
        "SELECT fetch_attempt_id,provider_attempt_id,evidence_level,captured_body "
        "FROM rag_registered_source_captures WHERE id=%s",
        (direct_capture_id,),
    ).fetchone()
    assert direct["fetch_attempt_id"] is not None
    assert direct["provider_attempt_id"] is None
    assert direct["evidence_level"] == "live_egress_attested"
    assert bytes(direct["captured_body"]) == b"existing direct capture history"


def test_terminal_replay_and_root_attempt_cap_are_denied(pg) -> None:  # type: ignore[no-untyped-def]
    policy_id, _, _ = _seed(pg, cap_units=1)
    repository = TavilyCaptureRepository(pg)
    expected_attempt_id = uuid4()
    attempt_id = repository.dispatch(
        policy_id=policy_id,
        generation=1,
        operation_key="extract." + uuid4().hex,
        request_sha256="d" * 64,
        attempt_id=expected_attempt_id,
    )
    assert attempt_id == expected_attempt_id
    with pytest.raises(TavilyCaptureDenied, match="POLICY_DENIED"):
        repository.dispatch(
            policy_id=policy_id,
            generation=1,
            operation_key="extract." + uuid4().hex,
            request_sha256="e" * 64,
        )
    repository.fail(attempt_id=attempt_id, error_code="transport_unavailable", unknown=True)
    with pytest.raises(TavilyCaptureDenied, match="ATTEMPT_DENIED"):
        repository.fail(attempt_id=attempt_id, error_code="transport_unavailable", unknown=True)
    row = pg.execute(
        "SELECT state,safe_error,usage_credits FROM rag_provider_extraction_attempts WHERE id=%s",
        (attempt_id,),
    ).fetchone()
    assert row == {
        "state": "unknown",
        "safe_error": "transport_unavailable",
        "usage_credits": None,
    }


def test_revocation_denies_current_provider_capture_without_deleting_history(pg) -> None:  # type: ignore[no-untyped-def]
    policy_id, _, _ = _seed(pg)
    repository = TavilyCaptureRepository(pg)
    attempt_id = repository.dispatch(
        policy_id=policy_id,
        generation=1,
        operation_key="extract." + uuid4().hex,
        request_sha256="f" * 64,
        content_format="text",
    )
    capture_id = uuid4()
    repository.settle(
        attempt_id=attempt_id,
        result=_result(pg, "provider text", content_format="text"),
        capture_id=capture_id,
    )
    pg.execute(
        "UPDATE rag_registered_source_policies SET enabled=false WHERE policy_id=%s",
        (policy_id,),
    )
    now = pg.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
    with pytest.raises(TavilyCaptureDenied, match="CAPTURE_DENIED"):
        repository.resolve_capture(capture_id, now)
    stored = pg.execute(
        "SELECT captured_body,evidence_level FROM rag_registered_source_captures WHERE id=%s",
        (capture_id,),
    ).fetchone()
    assert bytes(stored["captured_body"]) == b"provider text"
    assert stored["evidence_level"] == "provider_extracted"
