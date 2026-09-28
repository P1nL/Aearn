"""Final credit must not enlarge the original source scope; synthetic PG only."""
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timezone

import psycopg
import pytest

from app.services.grounding.autonomous import registered_source_repository as module
from tests.grounding.test_rag_c_final_followup import _allowance, _chain, _issue, _seed
from tests.grounding.test_rag_c_registered_source_repository import _disposable_db, scope


@pytest.mark.parametrize("change", ["subject", "version", "facets", "usages", "bytes"])
@pytest.mark.parametrize("direct_sql", [False, True])
def test_final_credit_cannot_change_scope_or_expand_original_permission(monkeypatch, change, direct_sql):
    conn = _disposable_db()
    try:
        original, latest, target, *_ = _chain(conn)
        fresh = scope()
        altered = replace(target, policy_id=fresh.policy_id, root_id=fresh.root_id,
                          dispatch_id=fresh.dispatch_id, source_handle=fresh.source_handle)
        fields = {"subject": {"subject_id": "route.python"},
                  "version": {"subject_version": "other-version"},
                  "facets": {"facets": ("schema",)},
                  "bytes": {"max_bytes": target.max_bytes + 1}, "usages": {}}
        altered = replace(altered, **fields[change])
        _seed(conn, altered, datetime.now(timezone.utc),
              allowed_usages=["main_teaching"] if change == "usages" else None)
        repo = module.PostgresRegisteredSourceRepository("rollback-fixture")
        monkeypatch.setattr(module.psycopg, "connect", lambda *_a, **_kw: nullcontext(conn))
        error = psycopg.errors.CheckViolation if direct_sql else module.RegisteredSourceDenied
        with pytest.raises(error):
            with conn.transaction():
                if direct_sql:
                    _allowance(conn, original, latest, altered)
                else:
                    _issue(repo, original, latest, altered)
        assert conn.execute("SELECT count(*) AS n FROM rag_registered_final_followup_allowances "
                            "WHERE original_attempt_id=%s", (original.dispatch_id,)).fetchone()["n"] == 0
    finally:
        conn.rollback()
        conn.close()
