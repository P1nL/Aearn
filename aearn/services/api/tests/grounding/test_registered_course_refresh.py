"""Three offline498 checks. Protocol DB stubs/SQL structure are NOT real PG evidence."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.services.grounding.autonomous import registered_course_refresh as refresh
from app.services.grounding.autonomous import registered_source_repository as registered
from app.services.grounding.autonomous.budget import PostgresBudgetPolicyResolver
from app.services.grounding.autonomous.registered_source_repository import (
    PostgresRegisteredSourceRepository, RegisteredSourceDenied,
)

NOW = datetime(2026, 10, 6, 9, tzinfo=UTC)


def fixture(target):
    """Explicit protocol fixture; no copied runtime/private key/source response."""
    original, middle, latest, capture = (str(uuid4()) for _ in range(4))
    count = 3 if target == "sqlite_select" else 1
    latest = latest if count == 3 else original
    attempts = [{"id": original, "root_id": "root.old.source", "policy_id": "source.old", "state": "settled",
                 "generation": 1, "supplemental_authorization_id": None}]
    if count == 3:
        attempts += [{"id": middle, "state": "unknown", "generation": 1,
                      "error_code": "EGRESS_UNVERIFIED_SIGNATURE_PID_NAMESPACE"},
                     {"id": latest, "policy_id": "source.old", "state": "settled", "generation": 3}]
    url, subject, facet, license_id, _profile = refresh.TARGETS[target]
    policy = {"policy_id": "source.old", "source_handle": "source.old.handle", "subject_id": subject,
              "subject_version": "1.0", "facets": [facet], "host": url.split("/")[2],
              "path": "/" + url.split("/", 3)[3], "max_captured_bytes": 4194304,
              "license_id": license_id, "reading_level": "beginner", "origin": "tutorial" if target == "learnx_python" else "official",
              "allowed_usages": ["main_teaching"] if target == "learnx_python" else ["assessment_evidence"]}
    return {"attempts": attempts, "policies": [policy],
            "captures": [{"id": capture, "fetch_attempt_id": latest, "fetched_sha256": "a" * 64}]}


def test_source_dispatch_debits_carry_unknown_and_permissions_are_bounded():
    assert len(refresh.TARGETS) == 5
    for target in refresh.TARGETS:
        counts = refresh.resource_debits(fixture(target), target)
        assert counts == ((3, 1) if target == "sqlite_select" else (1, 0))
    malformed = fixture("sqlite_select")
    malformed["attempts"][1]["state"] = "settled"
    with pytest.raises(refresh.CourseRefreshDenied, match="LINEAGE_DENIED"):
        refresh.resource_debits(malformed, "sqlite_select")
    assert refresh.deadline(NOW, NOW + timedelta(days=9), NOW + timedelta(days=9)) == NOW + timedelta(days=7)
    assert refresh.deadline(NOW, NOW + timedelta(hours=8), NOW + timedelta(days=9)) == NOW + timedelta(hours=8)
    with pytest.raises(refresh.CourseRefreshDenied, match="EXPIRED"):
        refresh.deadline(NOW, NOW, NOW + timedelta(days=9))
    # No connection attempt is possible with default-off issuance.
    with pytest.raises(RegisteredSourceDenied, match="DEFAULT_OFF"):
        PostgresRegisteredSourceRepository("unreachable").issue_course_refresh_once(
            target_key="python_reference", source_permission_expires_at=NOW,
            retention_permission_expires_at=NOW, now=NOW)


class ProtocolDB:
    """Records program SQL ordering only; cannot establish database constraint safety."""
    def __init__(self, target):
        self.snapshot = fixture(target)
        self.calls = []
        self.row = None
        self.autocommit = False
        self.info = SimpleNamespace(transaction_status=0)

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        if "current_database()" in sql:
            self.row = {"name": refresh.DATABASE}
        elif "SELECT id,root_id" in sql:
            self.row = self.snapshot["attempts"][0]
        elif " AS snapshot" in sql:
            self.row = {"snapshot": self.snapshot, "hash": "b" * 64}
        elif "clock_timestamp()" in sql:
            self.row = {"now": NOW}
        else:
            self.row = None
        return self

    def fetchone(self):
        return self.row


def test_trusted_issuer_derives_identity_and_appends_no_generic_budget_window():
    for target in ("python_reference", "sqlite_select"):
        conn = ProtocolDB(target)
        result = refresh.issue(conn, target_key=target, source_permission_expires_at=NOW + timedelta(days=9),
                               retention_permission_expires_at=NOW + timedelta(days=9), enabled=True)
        assert result.source_expires_at == NOW + timedelta(days=7)
        assert result.dispatch_expires_at == NOW + timedelta(minutes=30)
        assert result.carried_dispatch_units == (3 if target == "sqlite_select" else 1)
        assert result.carried_unknown_units == (1 if target == "sqlite_select" else 0)
        entry = result.manifest_entry()
        assert entry["scope"]["generation"] == (4 if target == "sqlite_select" else 2)
        assert entry["scope"]["max_bytes"] == 4194304
        assert entry["course_refresh_authorization_id"] == str(result.authorization_id)
        sql = "\n".join(q for q, _ in conn.calls)
        assert "FOR UPDATE" in sql
        assert "INSERT INTO rag_registered_course_refresh_authorizations" in sql
        assert "rag_registered_course_refresh_check(r,true)" in sql
        assert "INSERT INTO rag_budget_periods" not in sql
        assert "INSERT INTO rag_budget_reservations" not in sql
        assert "UPDATE rag_" not in sql and "DELETE FROM" not in sql
        # Same canonical lineage cannot obtain a different program-owned identity.
        replay = ProtocolDB(target)
        replay.snapshot = conn.snapshot
        again = refresh.issue(replay, target_key=target, source_permission_expires_at=NOW + timedelta(days=9),
                              retention_permission_expires_at=NOW + timedelta(days=9), enabled=True)
        assert again.authorization_id == result.authorization_id
        # Generic budget resolver rejects the reserved access namespace without
        # reading/provisioning a budget, even if498 has not yet been installed.
        budget = ProtocolDB(target)
        assert PostgresBudgetPolicyResolver(budget).resolve(
            SimpleNamespace(budget=SimpleNamespace(root_id=result.scope.root_id))) is None
        assert len(budget.calls) == 1  # require_transaction SELECT1 only


def test_sql_issuance_and_dispatch_share_checker_and_legacy_recovery_is_preserved():
    schema = Path(__file__).parents[2] / "app/db/schema"
    sql = (schema / "498_rag_registered_course_refresh.sql").read_text(encoding="utf-8")
    # PL/pgSQL IF comparisons must group the whole CASE expression (42601).
    assert "latest_policy.origin<>(CASE WHEN grant_row.target_key='learnx_python' THEN 'tutorial' ELSE 'official' END) OR" in sql
    assert ("latest_policy.allowed_usages<>(CASE WHEN grant_row.target_key='learnx_python' THEN ARRAY['main_teaching']\n"
            "      WHEN grant_row.target_key='sqlite_select' THEN ARRAY['assessment_evidence']\n"
            "      ELSE ARRAY['assessment_evidence','main_teaching'] END) OR") in sql
    assert "<>CASE" not in sql
    old = (schema / "400_rag_c_final_followup.sql").read_text(encoding="utf-8")
    function = "CREATE OR REPLACE FUNCTION rag_registered_supplemental_recovery_guard()"
    old_body = old[old.index(function):old.index("-- Preserve the original index name")].strip()
    new_body = sql[sql.index(function):sql.index("-- Do not change400's partial index", sql.index(function))].strip()
    branch = """  IF NEW.course_refresh_authorization_id IS NOT NULL THEN
    PERFORM rag_registered_course_refresh_check(r,true)
      FROM rag_registered_course_refresh_authorizations r WHERE id=NEW.course_refresh_authorization_id;
    RETURN NEW; -- Exact binding is also enforced by FK and independent auth guard.
  END IF;
"""
    assert new_body.replace(branch, "") == old_body
    assert "DROP INDEX IF EXISTS uq_rag_supplemental_one_original" not in sql
    for filename, name, marker, discriminator, comment in (
        ("350_rag_c_supplemental_dispatch.sql", "rag_registered_supplemental_guard", "-- The 320 fragment", "NEW", "auth"),
        ("350_rag_c_supplemental_dispatch.sql", "rag_registered_supplemental_dispatch_guard", "DROP TRIGGER IF EXISTS trg_rag_registered_supplemental_dispatch_guard", "auth_row", "dispatch"),
        ("390_rag_c_supplemental_recovery.sql", "rag_registered_supplemental_recovery_dispatch_guard", "DROP TRIGGER IF EXISTS trg_00_rag_registered_supplemental_recovery_dispatch_guard", "auth_row", "dispatch"),
    ):
        legacy = (schema / filename).read_text(encoding="utf-8")
        start = "CREATE OR REPLACE FUNCTION " + name + "()"
        old_function = legacy[legacy.index(start):legacy.index(marker, legacy.index(start))].strip()
        new_function = sql[sql.index(start):sql.index("END $$;", sql.index(start)) + len("END $$;")].strip()
        extra = (f"  IF {discriminator}.course_refresh_authorization_id IS NOT NULL THEN\n"
                 "    PERFORM rag_registered_course_refresh_check(r,true)\n"
                 f"      FROM rag_registered_course_refresh_authorizations r WHERE id={discriminator}.course_refresh_authorization_id;\n"
                 f"    RETURN NEW; -- Independent498 {comment} guard/composite FK binds every coordinate.\n"
                 "  END IF;\n")
        assert new_function.replace(extra, "") == old_function
    assert "PERFORM rag_registered_course_refresh_check(NEW,true)" in sql
    assert sql.count("PERFORM rag_registered_course_refresh_check(grant_row,true)") == 2
    assert "UNIQUE(authorization_id,canonical_original_attempt_id)" in sql
    assert "UNIQUE(authorization_id,canonical_url_sha256)" in sql
    assert "grant_row.lineage_snapshot IS DISTINCT FROM snapshot" in sql
    assert "carried_unknown_units<>actual_unknown" in sql
    assert "FOR UPDATE" in sql and "SET TimeZone='UTC'" in sql
    assert "s.course_refresh_authorization_id IS NULL" in sql
    assert "INSERT INTO rag_budget_periods" not in sql


def test_actual_take_dispatch_keeps_latest_binding_but_locks_original_and_cannot_refill(monkeypatch):
    # Real Python method; only the SQL transport is stubbed. No PG/network claim.
    issuer = ProtocolDB("sqlite_select")
    result = refresh.issue(issuer, target_key="sqlite_select", source_permission_expires_at=NOW + timedelta(days=7),
                           retention_permission_expires_at=NOW + timedelta(days=7), enabled=True)
    original = UUID(issuer.snapshot["attempts"][0]["id"])
    latest = UUID(issuer.snapshot["attempts"][-1]["id"])
    assert latest != original
    url_hash = "e" * 64
    auth = dict(dispatch_id=result.scope.dispatch_id, policy_id=result.scope.policy_id,
                generation=result.scope.generation, canonical_url_sha256=url_hash, root_id=result.scope.root_id,
                request_hash=result.request_hash, expires_at=result.dispatch_expires_at, prior_attempt_id=latest,
                course_refresh_authorization_id=result.authorization_id)
    grant = dict(id=result.authorization_id, dispatch_id=result.scope.dispatch_id,
                 supplemental_authorization_id=result.supplemental_authorization_id,
                 request_hash=result.request_hash, operation_key=result.operation_key)

    class DispatchDB:
        row = None
        consumed = False

        def __init__(self):
            self.calls = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, params=()):
            self.calls.append((sql, params))
            if "SELECT * FROM rag_registered_supplemental_authorizations" in sql:
                self.row = auth
            elif "SELECT canonical_original_attempt_id,latest_attempt_id" in sql:
                self.row = dict(canonical_original_attempt_id=original, latest_attempt_id=latest)
            elif "SELECT state,supplemental_authorization_id,canonical_url_sha256" in sql:
                assert params == (original,) and "FOR UPDATE" in sql
                self.row = dict(state="settled", supplemental_authorization_id=None, canonical_url_sha256=url_hash)
            elif "SELECT 1 FROM rag_registered_supplemental_revocations" in sql:
                self.row = None
            elif "SELECT * FROM rag_registered_course_refresh_authorizations" in sql:
                self.row = grant
            elif "SELECT rag_registered_course_refresh_check(r,true)" in sql:
                assert params == (result.authorization_id,)
                self.row = None
            elif "INSERT INTO rag_registered_fetch_attempts" in sql:
                assert params[-1] == result.supplemental_authorization_id
                assert params[-2] == result.request_hash
                self.row = None if self.consumed else {"id": result.scope.dispatch_id}
                self.consumed = True
            else:
                raise AssertionError(sql)
            return self

        def fetchone(self):
            return self.row

    db = DispatchDB()
    monkeypatch.setattr(registered.psycopg, "connect", lambda *_a, **_k: db)
    monkeypatch.setattr(registered, "_current", lambda *_a, **_k: {"canonical_url_sha256": url_hash})
    monkeypatch.setattr(registered, "_clock", lambda *_a: NOW)
    repo = PostgresRegisteredSourceRepository("offline-protocol-only")
    kwargs = dict(operation_key=result.operation_key, request_hash=result.request_hash, now=NOW,
                  supplemental_authorization_id=result.supplemental_authorization_id)
    assert repo.take_dispatch(result.scope, **kwargs) == result.scope.dispatch_id
    assert repo._permits[result.scope.dispatch_id] == (result.scope, 2)
    # Once both local checks are consumed, a duplicate dispatch must not refill.
    repo._permits[result.scope.dispatch_id] = (result.scope, 0)
    with pytest.raises(RegisteredSourceDenied, match="SUPPLEMENTAL_DENIED"):
        repo.take_dispatch(result.scope, **{**kwargs, "request_hash": "0" * 64})
    with pytest.raises(RegisteredSourceDenied, match="ALREADY_DISPATCHED"):
        repo.take_dispatch(result.scope, **kwargs)
    assert repo._permits[result.scope.dispatch_id] == (result.scope, 0)
    checker = next(i for i, (sql, _) in enumerate(db.calls) if "SELECT rag_registered_course_refresh_check" in sql)
    insertion = next(i for i, (sql, _) in enumerate(db.calls) if "INSERT INTO rag_registered_fetch_attempts" in sql)
    assert checker < insertion
