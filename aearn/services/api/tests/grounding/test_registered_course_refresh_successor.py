"""Offline544 issuer protocol checks; no DB/transport/capture is fabricated as evidence."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from psycopg.pq import TransactionStatus

from app.services.grounding.autonomous import registered_course_refresh_successor as refresh
from app.services.grounding.autonomous.registered_course_refresh import CourseRefreshDenied
from app.services.grounding.autonomous.budget import PostgresBudgetPolicyResolver

NOW = datetime(2026, 10, 13, 10, tzinfo=UTC)


def fixture():
    return {
        "attempts": [
            {"id": str(refresh.ORIGINAL_ID), "generation": 1, "state": "settled",
             "root_id": refresh.ORIGINAL_ROOT, "supplemental_authorization_id": None},
            {"id": str(refresh.LATEST_ID), "generation": 2, "state": "settled",
             "policy_id": "source.previous", "supplemental_authorization_id": "26b2b080-1aa2-5fdd-a530-6fcbc5cb89e8"},
        ],
        "policies": [{"policy_id": "source.previous", "source_handle": "source.course.python_reference",
                      "subject_id": "route.python", "subject_version": "1.0", "facets": ["fundamentals"],
                      "host": "docs.python.org", "path": "/3/reference/simple_stmts.html", "max_captured_bytes": 4194304,
                      "origin": "official", "reading_level": "beginner", "license_id": "psf-2.0",
                      "allowed_usages": ["assessment_evidence", "main_teaching"]}],
        "captures": [{"id": "7fabac26-245d-48d3-8d0e-8a176cbf4a86",
                      "fetch_attempt_id": str(refresh.LATEST_ID), "fetched_sha256": "a" * 64}],
    }


class ProtocolDB:
    def __init__(self):
        self.info = SimpleNamespace(transaction_status=TransactionStatus.INTRANS)
        self.autocommit = False
        self.snapshot = fixture()
        self.calls = []
        self.row = None
        self.consumed = False

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        self.row = None
        if "current_database()" in sql:
            self.row = {"name": refresh.DATABASE}
        elif "SELECT id,root_id" in sql:
            self.row = {"id": refresh.ORIGINAL_ID, "root_id": refresh.ORIGINAL_ROOT}
        elif "SELECT 1 FROM rag_registered_course_refresh_authorizations" in sql:
            self.row = {"exists": 1} if self.consumed else None
        elif " AS snapshot" in sql:
            self.row = {"snapshot": self.snapshot, "hash": "b" * 64}
        elif "clock_timestamp()" in sql:
            self.row = {"now": NOW}
        return self

    def fetchone(self):
        return self.row


def issue(conn, **kwargs):
    return refresh.issue(conn, target_key="python_reference", source_permission_expires_at=NOW + timedelta(days=8),
                         retention_permission_expires_at=NOW + timedelta(days=6), **kwargs)


def test_exact_history_carries_both_dispatches_and_never_erases_unknown():
    assert refresh.resource_debits(fixture()) == (2, 0)
    altered = fixture()
    altered["attempts"][1]["state"] = "unknown"
    with pytest.raises(CourseRefreshDenied, match="LINEAGE_DENIED"):
        refresh.resource_debits(altered)
    altered = fixture()
    altered["attempts"].append(deepcopy(altered["attempts"][-1]))
    with pytest.raises(CourseRefreshDenied, match="LINEAGE_DENIED"):
        refresh.resource_debits(altered)


def test_exact_issuer_manifest_and_no_new_wallet_or_capture():
    conn = ProtocolDB()
    result = issue(conn, enabled=True)
    assert result.authorization_id == refresh.SUCCESSOR_ID
    assert result.carried_dispatch_units == 2 and result.carried_unknown_units == 0
    assert result.source_expires_at == NOW + timedelta(days=6)
    assert result.dispatch_expires_at == NOW + timedelta(minutes=30)
    entry = result.manifest_entry()
    assert entry["scope"]["generation"] == 3
    assert entry["course_refresh_authorization_id"] == str(refresh.SUCCESSOR_ID)
    assert UUID(entry["scope"]["dispatch_id"]) == result.scope.dispatch_id
    sql = "\n".join(q for q, _ in conn.calls)
    assert "FOR UPDATE" in sql and "rag_registered_course_refresh_check(r,true)" in sql
    assert "INSERT INTO rag_registered_source_captures" not in sql
    assert "INSERT INTO rag_budget_periods" not in sql and "INSERT INTO rag_budget_reservations" not in sql
    assert "UPDATE rag_" not in sql and "DELETE FROM" not in sql
    budget = ProtocolDB()
    assert PostgresBudgetPolicyResolver(budget).resolve(
        SimpleNamespace(budget=SimpleNamespace(root_id=result.scope.root_id))) is None


def test_default_other_target_once_and_transaction_denials():
    with pytest.raises(CourseRefreshDenied, match="DEFAULT_OFF"):
        issue(None)
    with pytest.raises(CourseRefreshDenied, match="DEFAULT_OFF"):
        refresh.issue(None, target_key="sqlite_select", source_permission_expires_at=NOW,
                      retention_permission_expires_at=NOW, enabled=True)
    conn = ProtocolDB()
    conn.consumed = True
    with pytest.raises(CourseRefreshDenied, match="ONCE_CONSUMED"):
        issue(conn, enabled=True)
    assert not any("INSERT" in q for q, _ in conn.calls)
    conn = ProtocolDB()
    conn.info.transaction_status = TransactionStatus.IDLE
    with pytest.raises(CourseRefreshDenied, match="CALLER_TRANSACTION_REQUIRED"):
        issue(conn, enabled=True)
    assert not conn.calls


def test_sql_changes_only_exact_successor_branch_and_preserves_old_receiver():
    from pathlib import Path
    import hashlib

    schema = Path(__file__).resolve().parents[2] / "app/db/schema"
    sql = (schema / "544_rag_registered_course_refresh_successor.sql").read_text(encoding="utf-8")
    body = sql.split("$body544$")[1]
    assert hashlib.sha256(body.encode()).hexdigest() == "ba17bd890627d091faacae9cbcfe98d8cceac5cb7a4cc091a93982293cc2288a"
    body = body.replace("DECLARE db_now timestamptz;\nDECLARE successor boolean := grant_row.id='fbfabcf0-f336-5b12-9824-8b0b2782b69c'::uuid;\nDECLARE predecessor rag_registered_course_refresh_authorizations%ROWTYPE;", "DECLARE db_now timestamptz;")
    body = body.replace("expected_count:=CASE WHEN successor THEN 2 WHEN grant_row.target_key='sqlite_select' THEN 3 ELSE 1 END;", "expected_count:=CASE WHEN grant_row.target_key='sqlite_select' THEN 3 ELSE 1 END;")
    body = body.replace("AND r.id<>grant_row.id\n        AND NOT (successor AND r.id='46207149-ab55-5054-9821-da9059c0a77a'::uuid)) OR", "AND r.id<>grant_row.id) OR")
    start = body.index(" IF successor THEN")
    end = body.index(" ELSIF expected_count=1 THEN", start) + len(" ELSIF expected_count=1 THEN")
    body = body[:start] + " IF expected_count=1 THEN" + body[end:]
    body = body.replace("grant_row.root_id<>(CASE WHEN successor THEN 'root.course-refresh.20261006.python_reference.successor.20261013'\n      ELSE 'root.course-refresh.20261006.'||grant_row.target_key END) OR", "grant_row.root_id<>'root.course-refresh.20261006.'||grant_row.target_key OR")
    old = (schema / "498_rag_registered_course_refresh.sql").read_text(encoding="utf-8")
    original = old.split("LANGUAGE plpgsql SET TimeZone='UTC' AS $$")[1].split("$$;")[0]
    assert body == original
    assert "CREATE TABLE" not in sql and "INSERT INTO" not in sql
    assert "544 once UNIQUE has dependent FK" in sql
    assert "i.indisunique AND i.indisvalid AND i.indisready" in sql
