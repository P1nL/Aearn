"""C retention: synthetic bytes only, explicit disposable DB, rollback owned rows."""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row

from app.db.bootstrap import apply_schema
from app.services.grounding.autonomous.registered_source_retention import (
    RegisteredRetentionDenied,
    clear_registered_captures,
    require_indefinite_history_grant,
)
from app.services.grounding.autonomous.source_review_repository import (
    ReviewDenied,
    SourceReviewRepository,
)

URL = "https://example.org"  # synthetic unique URLs for batch cleanup, never fetched
BODY = b"synthetic test bytes; not fetched"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_default_denial_and_history_prelink() -> None:
    class Fake:
        autocommit = False
        info = SimpleNamespace(transaction_status=TransactionStatus.INTRANS)

        def __init__(self, row):
            self.row = row
            self.queries = []

        def execute(self, query, _params=None):
            self.queries.append(query)
            return SimpleNamespace(fetchone=lambda: self.row)

    db = Fake(None)
    with pytest.raises(RegisteredRetentionDenied, match="OPERATOR_APPROVAL_REQUIRED"):
        clear_registered_captures(db)
    assert not db.queries
    with pytest.raises(RegisteredRetentionDenied, match="INVALID_CLEANUP_LIMIT"):
        clear_registered_captures(db, limit=True, operator_approved=True)
    with pytest.raises(RegisteredRetentionDenied, match="HISTORY_GRANT_MISSING"):
        require_indefinite_history_grant(db, admission_id=uuid4())
    db.row = dict(reviewed_history=True, policy_history=False,
                  review_generation=1, policy_generation=1)
    with pytest.raises(RegisteredRetentionDenied, match="HISTORY_GRANT_MISSING"):
        require_indefinite_history_grant(db, admission_id=uuid4())
    db.row["policy_history"] = True
    db.row["policy_generation"] = 2
    with pytest.raises(RegisteredRetentionDenied, match="HISTORY_GRANT_MISSING"):
        require_indefinite_history_grant(db, admission_id=uuid4())
    db.row["policy_generation"] = 1
    require_indefinite_history_grant(db, admission_id=uuid4())
    db.info.transaction_status = TransactionStatus.IDLE
    with pytest.raises(RegisteredRetentionDenied, match="TRANSACTION_REQUIRED"):
        clear_registered_captures(db, operator_approved=True)


@pytest.fixture()
def conn():  # type: ignore[no-untyped-def]
    dsn = os.environ.get("AEARN_RAG_C_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("explicit disposable AEARN_RAG_C_TEST_DATABASE_URL required")
    expected = urlsplit(dsn).path.lstrip("/")
    if not expected.startswith("aearn_rag260_c_"):
        pytest.fail("refusing non-disposable C database")
    with psycopg.connect(dsn, row_factory=dict_row) as db:
        found = db.execute("SELECT current_database() AS name").fetchone()
        if found is None or found["name"] != expected:
            pytest.fail("current_database() mismatch")
        apply_schema(db)
        apply_schema(db)
        yield db
        db.rollback()


def seed(conn, *, retention: datetime, history: bool = True) -> tuple[UUID, str]:
    suffix = uuid4().hex
    path = f"/retention/{suffix}"
    url = URL + path
    root, policy, source = (f"{prefix}.{suffix}" for prefix in ("root", "policy", "source"))
    attempt, capture = uuid4(), uuid4()
    now = datetime.now(UTC)
    horizon = now + timedelta(days=1)
    conn.execute(
        """INSERT INTO rag_budget_authority_roots
           (root_id,delegation_id,delegation_generation,delegation_expires_at,
            policy_id,policy_generation,period_key,period_start,period_end,
            cap_units,enabled)
           VALUES (%s,%s,1,%s,%s,1,%s,%s,%s,1,true)""",
        (root, f"delegation.{suffix}", horizon, policy, f"period.{suffix}",
         now-timedelta(minutes=1), horizon),
    )
    conn.execute(
        """INSERT INTO rag_registered_source_policies
           (policy_id,generation,source_handle,subject_id,subject_version,facets,
            origin,reading_level,canonical_url,canonical_url_sha256,host,path,
            license_id,allowed_usages,immutable_history_allowed,max_captured_bytes,
            retention_until,expires_at,root_id,enabled)
           VALUES (%s,1,%s,'route.sql','v1',ARRAY['queries'],'official','beginner',
                   %s,%s,'example.org',%s,'PublicDomain',
                   ARRAY['main_teaching'],%s,1024,%s,%s,%s,true)""",
        (policy, source, url, sha(url.encode()), path, history, retention, retention, root),
    )
    conn.execute(
        """INSERT INTO rag_registered_fetch_attempts
           (id,policy_id,generation,canonical_url_sha256,root_id,operation_key,
            request_hash,state,response_sha256,response_bytes,settled_at)
           VALUES (%s,%s,1,%s,%s,%s,%s,'settled',%s,%s,clock_timestamp())""",
        (attempt, policy, sha(url.encode()), root, f"operation.{suffix}",
         sha(suffix.encode()), sha(BODY), len(BODY)),
    )
    conn.execute(
        """INSERT INTO rag_registered_source_captures
           (id,fetch_attempt_id,policy_id,generation,request_chain,final_url,
            content_type,fetched_sha256,captured_bytes,captured_body,license_id,
            retention_until)
           VALUES (%s,%s,%s,1,%s::jsonb,%s,'text/plain',%s,%s,%s,'PublicDomain',%s)""",
        (capture, attempt, policy, json.dumps([url]), url, sha(BODY), len(BODY),
         BODY, retention),
    )
    return capture, policy


def test_pg_revocation_clears_body_and_denies_current_read(conn) -> None:  # type: ignore[no-untyped-def]
    capture, policy = seed(conn, retention=datetime.now(UTC)+timedelta(hours=1))
    assert SourceReviewRepository(conn)._capture(capture, "registered", datetime.now(UTC))[0]
    conn.execute("UPDATE rag_registered_source_policies SET enabled=false WHERE policy_id=%s", (policy,))
    report = clear_registered_captures(conn, operator_approved=True)
    assert report.capture_bodies_cleared == 1
    assert report.historical_chunks_preserved == 0
    assert report.blocked_formal_documents == 0
    assert report.status == "cleared" and not report.more_pending
    row = conn.execute(
        "SELECT captured_body,cleared_at,fetched_sha256,fetch_attempt_id FROM "
        "rag_registered_source_captures WHERE id=%s", (capture,),
    ).fetchone()
    assert row is not None and row["captured_body"] is None and row["cleared_at"]
    assert row["fetched_sha256"] == sha(BODY) and row["fetch_attempt_id"]
    with pytest.raises(ReviewDenied, match="CAPTURE_DENIED"):
        SourceReviewRepository(conn)._capture(capture, "registered", datetime.now(UTC))
    assert clear_registered_captures(conn, operator_approved=True).capture_bodies_cleared == 0
    conn.rollback()


def test_pg_deadline_and_bounded_batch(conn) -> None:  # type: ignore[no-untyped-def]
    until = datetime.now(UTC) + timedelta(seconds=2)
    first, _ = seed(conn, retention=until)
    second, _ = seed(conn, retention=until)
    before = clear_registered_captures(conn, limit=1, operator_approved=True)
    assert before.capture_bodies_cleared == 0
    time.sleep(2.1)
    one = clear_registered_captures(conn, limit=1, operator_approved=True)
    assert one.capture_bodies_cleared == 1 and one.more_pending and one.status == "partial"
    two = clear_registered_captures(conn, limit=1, operator_approved=True)
    assert two.capture_bodies_cleared == 1 and not two.more_pending
    records = conn.execute(
        "SELECT id,captured_body,cleared_at,fetched_sha256 FROM "
        "rag_registered_source_captures WHERE id=ANY(%s)", ([first, second],),
    ).fetchall()
    assert len(records) == 2
    assert all(row["captured_body"] is None and row["cleared_at"]
               and row["fetched_sha256"] == sha(BODY) for row in records)
    conn.rollback()


@pytest.mark.parametrize(("blocked", "preserved", "status"), [
    (1, 0, "blocked_formal_history"),
    (0, 2, "cleared"),
])
def test_formal_history_is_distinct_from_capture_retention(
    blocked: int, preserved: int, status: str,
) -> None:
    capture = uuid4()

    class Cursor:
        def __init__(self, rows=None, row=None):
            self.rows = rows or []
            self.row = row

        def fetchall(self):
            return self.rows

        def fetchone(self):
            return self.row

    class Fake:
        autocommit = False
        info = SimpleNamespace(transaction_status=TransactionStatus.INTRANS)

        def __init__(self):
            self.sql = []

        def transaction(self):
            from contextlib import nullcontext
            return nullcontext()

        def execute(self, sql, _params=None):
            self.sql.append(sql)
            if "SELECT capture.id" in sql:
                return Cursor(rows=[{"id": capture}])
            if "AS preserved" in sql:
                return Cursor(row={"preserved": preserved, "blocked": blocked})
            if "UPDATE rag_registered_source_captures" in sql:
                return Cursor(rows=[{"id": capture}])
            if "AS pending" in sql:
                return Cursor(row={"pending": False})
            pytest.fail("unexpected SQL")

    db = Fake()
    report = clear_registered_captures(db, operator_approved=True)
    assert report.status == status
    assert report.capture_bodies_cleared == 1
    assert report.blocked_formal_documents == blocked
    assert report.historical_chunks_preserved == preserved
    assert all("UPDATE grounding_corpus" not in sql and "DELETE FROM grounding_corpus" not in sql
               for sql in db.sql)


def test_registered_review_read_refuses_cleared_body_offline() -> None:
    now = datetime.now(UTC)
    row = dict(generation=1, policy_generation=1, enabled=True,
               revoked_at=None, expires_at=now+timedelta(days=1),
               policy_retention=now+timedelta(days=1),
               retention_until=now+timedelta(days=1), cleared_at=now)

    class Fake:
        def execute(self, _sql, _params):
            return SimpleNamespace(fetchone=lambda: row)

    with pytest.raises(ReviewDenied, match="CAPTURE_DENIED"):
        SourceReviewRepository(Fake())._capture(uuid4(), "registered", now)
