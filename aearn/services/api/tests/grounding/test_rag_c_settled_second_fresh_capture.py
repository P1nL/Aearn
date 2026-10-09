"""Focused offline checks and main-only, rollback-only exact B1d PG checks."""
from __future__ import annotations

import hashlib
import os
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.services.grounding.autonomous import registered_source_repository as module
from app.services.grounding.autonomous.registered_source_policy import RegisteredSourceScope

SCHEMA = Path(__file__).resolve().parents[2] / "app" / "db" / "schema"
FRAGMENT = SCHEMA / "484_rag_c_settled_second_fresh_capture.sql"
URL = "https://docs.python.org/3/builtins/functions.html"


def _scope() -> RegisteredSourceScope:
    suffix = uuid4().hex
    return RegisteredSourceScope(
        policy_id="fresh." + suffix, generation=3, source_handle="python." + suffix,
        subject_id="route.python", subject_version="1.0", facets=("fundamentals",),
        url=URL, host="docs.python.org", path="/3/builtins/functions.html",
        root_id="fresh.root." + suffix, dispatch_id=uuid4(),
    )


def _args(item=None):
    now = datetime.now(timezone.utc)
    return dict(
        allowance_id=uuid4(), authorization_id=uuid4(), original_attempt_id=uuid4(),
        latest_attempt_id=uuid4(), latest_capture_id=uuid4(), latest_capture_sha256="a" * 64,
        scope=item or _scope(), request_hash="b" * 64,
        expires_at=now + timedelta(minutes=5),
        approval_ref="standingpolicy.settledsecondfreshness.focused-test", now=now,
    )


def test_input_scope_and_generation_denied_before_any_io(monkeypatch):
    monkeypatch.setattr(module.psycopg, "connect", lambda *_a, **_kw: pytest.fail("DB opened"))
    repo = module.PostgresRegisteredSourceRepository("offline-only")
    args = _args()
    for changes in (
        {"scope": replace(args["scope"], generation=5)},
        {"scope": replace(args["scope"], subject_id="route.sql")},
        {"latest_capture_sha256": "not-a-hash"},
        {"approval_ref": "standingpolicy.sourcefreshness.wrong-branch"},
    ):
        with pytest.raises(module.RegisteredSourceDenied, match="SETTLED_SECOND_FRESH_DENIED"):
            repo.authorize_settled_second_fresh_once(**(args | changes))


def test_issuer_exact_pair_atomic_failure_and_no_network_permit(monkeypatch):
    calls = []
    exits = []
    args = _args()

    class Connection:
        fail_auth = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, *_rest):
            exits.append(exc_type)

        def execute(self, query, params=()):
            calls.append((query, params))
            if self.fail_auth and query.startswith("INSERT INTO rag_registered_supplemental"):
                raise psycopg.IntegrityError("private database diagnostics")
            return SimpleNamespace(fetchone=lambda: {"id": args["original_attempt_id"]})

    conn = Connection()
    monkeypatch.setattr(module.psycopg, "connect", lambda *_a, **_kw: conn)
    monkeypatch.setattr(module, "_clock", lambda *_a: args["now"])
    monkeypatch.setattr(module, "_current", lambda *_a, **_kw: {
        "canonical_url_sha256": hashlib.sha256(URL.encode()).hexdigest(),
    })
    repo = module.PostgresRegisteredSourceRepository("offline-only")
    assert repo.authorize_settled_second_fresh_once(**args) == args["authorization_id"]
    assert calls[0][0].endswith("FOR UPDATE")
    assert len(calls) == 3 and exits == [None]
    assert "settled_second_capture_id,settled_second_capture_sha256" in calls[1][0]
    assert calls[1][1][-2:] == (args["latest_capture_id"], args["latest_capture_sha256"])
    assert calls[2][1][-1] == args["allowance_id"]
    assert repo._permits == {}
    conn.fail_auth = True
    with pytest.raises(module.RegisteredSourceDenied, match="^SETTLED_SECOND_FRESH_DENIED$"):
        repo.authorize_settled_second_fresh_once(**args)
    assert exits[-1] is psycopg.IntegrityError and repo._permits == {}


def test_fragment_preserves_420_branch_and_database_enforced_capture_identity():
    sql = FRAGMENT.read_text(encoding="utf-8")
    old = (SCHEMA / "420_rag_c_expired_source_refresh.sql").read_text(encoding="utf-8")
    tail = "  IF grant_row.generation=5 THEN"
    assert sql[sql.index(tail):].strip() == old[old.index(tail):].strip()
    assert "FOREIGN KEY(settled_second_capture_id,latest_attempt_id,settled_second_capture_sha256)" in sql
    assert "original_row.state<>'unknown'" in sql and "latest_row.state<>'settled'" in sql
    assert "policy_row.allowed_usages<>ARRAY['assessment_evidence']" in sql
    assert "WHERE supplemental_authorization_id=replaced_auth.id OR id=replaced_auth.dispatch_id" in sql
    assert "settled second freshness cannot fund another followup" in sql
    python_check = sql.split("CREATE OR REPLACE FUNCTION rag_registered_settled_second_fresh_once_check(", 1)[1]
    python_check = python_check.split("-- All 400 allowance/auth/dispatch guards", 1)[0]
    assert "policy_row.source_handle IS DISTINCT FROM latest_policy.source_handle" in python_check
    assert "history_policy.source_handle" not in python_check
    assert "history_policy.license_id" in python_check and "history_policy.allowed_usages" in python_check
    assert "latest_row.generation<>1" in python_check and "latest_policy.generation<>1" in python_check
    assert "ROW(latest_row.id,latest_row.policy_id,1," in python_check
    assert "ROW(latest_policy.policy_id,1)" in python_check
    assert "<> (CASE WHEN latest_auth.replaces_authorization_id IS NULL THEN 1 ELSE 2 END) THEN" in python_check
    assert sql.index("FOR UPDATE;") < sql.index("db_now := clock_timestamp();")
    assert "INSERT INTO" not in sql and "CREATE TABLE" not in sql


def _seed_target(conn, latest_policy, item, until):
    conn.execute(
        "INSERT INTO rag_budget_authority_roots "
        "(root_id,delegation_id,delegation_generation,delegation_expires_at,policy_id,"
        "policy_generation,period_key,period_start,period_end,cap_units,enabled) "
        "SELECT %s,%s,delegation_generation,%s,%s,%s,period_key,clock_timestamp(),%s,cap_units,true "
        "FROM rag_budget_authority_roots WHERE root_id=%s",
        (item.root_id, "fresh.delegation." + uuid4().hex, until, item.policy_id,
         item.generation, until, latest_policy["root_id"]),
    )
    conn.execute(
        "INSERT INTO rag_registered_source_policies "
        "(policy_id,generation,source_handle,subject_id,subject_version,facets,origin,reading_level,"
        "canonical_url,canonical_url_sha256,host,path,license_id,allowed_usages,"
        "immutable_history_allowed,max_captured_bytes,retention_until,expires_at,root_id,enabled) "
        "SELECT %s,%s,source_handle,subject_id,subject_version,facets,origin,reading_level,"
        "canonical_url,canonical_url_sha256,host,path,license_id,allowed_usages,"
        "immutable_history_allowed,max_captured_bytes,%s,%s,%s,true "
        "FROM rag_registered_source_policies WHERE policy_id=%s",
        (item.policy_id, item.generation, until, until, item.root_id, latest_policy["policy_id"]),
    )


def test_pg_main_only_exact_history_fresh_once_replay_and_direct_sql_guards(monkeypatch):
    """Main runs BEFORE real gen3 issue; never contacts HTTP/Docker or changes old rows.

    The explicit DSN must target aearn_b1d_sandbox_20261001. Main applies the
    full manifest twice separately; this check additionally replays 484 twice.
    All test target policies, grants and unknown attempts are rolled back.
    """
    dsn = os.getenv("AEARN_SETTLED_SOURCE_FRESH_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("main-only PG not executed: explicit exact B1d DSN required")
    expected = "aearn_b1d_sandbox_20261001"
    assert urlsplit(dsn).path.lstrip("/") == expected
    conn = psycopg.connect(dsn, row_factory=dict_row)
    try:
        assert conn.execute("SELECT current_database() AS name").fetchone()["name"] == expected
        original_id = UUID("9ce4a81f-cd57-4f46-ac2e-be5c7f18faf7")
        latest_id = UUID("b45551d5-8dff-4ad9-877d-4da31eb2f017")
        capture_id = UUID("a66f5719-180b-4392-bc85-a91bb6199aa4")
        capture_hash = "961bf099b8ed807bbc636d2c86a16f9b140a6073533a5da38e77693ea94cd4db"
        policy = conn.execute(
            "SELECT p.* FROM rag_registered_source_policies p "
            "JOIN rag_registered_fetch_attempts a ON a.policy_id=p.policy_id WHERE a.id=%s",
            (latest_id,),
        ).fetchone()
        assert policy is not None and policy["canonical_url"] == URL
        assert conn.execute(
            "SELECT count(*) AS n FROM rag_registered_final_followup_allowances "
            "WHERE original_attempt_id=%s", (original_id,),
        ).fetchone()["n"] == 0, "run only before real freshness issuance"
        # Snapshot old policies/roots/attempts/auths/revocations/capture including raw
        # evidence as hashes only; no secret or body is emitted by this test.
        snapshot_sql = """
          SELECT encode(digest(string_agg(row_json::text, '' ORDER BY row_json::text), 'sha256'),'hex') AS h
          FROM (
            SELECT to_jsonb(a) AS row_json FROM rag_registered_fetch_attempts a WHERE id=ANY(%s)
            UNION ALL SELECT to_jsonb(a) FROM rag_registered_supplemental_authorizations a WHERE prior_attempt_id=%s
            UNION ALL SELECT to_jsonb(r) FROM rag_registered_supplemental_revocations r WHERE prior_attempt_id=%s
            UNION ALL SELECT to_jsonb(c) FROM rag_registered_source_captures c WHERE id=%s
            UNION ALL SELECT to_jsonb(p) FROM rag_registered_source_policies p WHERE policy_id IN
              (SELECT policy_id FROM rag_registered_fetch_attempts WHERE id=ANY(%s))
            UNION ALL SELECT to_jsonb(r) FROM rag_budget_authority_roots r WHERE root_id IN
              (SELECT root_id FROM rag_registered_fetch_attempts WHERE id=ANY(%s))
          ) history
        """
        snapshot_args = ([original_id, latest_id], original_id, original_id, capture_id,
                         [original_id, latest_id], [original_id, latest_id])
        before = conn.execute(snapshot_sql, snapshot_args).fetchone()["h"]
        for _ in range(2):
            conn.execute(FRAGMENT.read_text(encoding="utf-8"))
        assert conn.execute(
            "SELECT count(*) AS n FROM rag_registered_final_followup_allowances "
            "WHERE original_attempt_id=%s", (original_id,),
        ).fetchone()["n"] == 0
        item = replace(_scope(), source_handle=policy["source_handle"], max_bytes=policy["max_captured_bytes"])
        until = conn.execute("SELECT clock_timestamp() AS t").fetchone()["t"] + timedelta(minutes=5)
        _seed_target(conn, policy, item, until)
        args = _args(item) | dict(original_attempt_id=original_id, latest_attempt_id=latest_id,
                                 latest_capture_id=capture_id, latest_capture_sha256=capture_hash,
                                 expires_at=until)
        repo = module.PostgresRegisteredSourceRepository("rollback-only")
        monkeypatch.setattr(module.psycopg, "connect", lambda *_a, **_kw: nullcontext(conn))
        with pytest.raises(module.RegisteredSourceDenied):
            with conn.transaction():
                repo.authorize_settled_second_fresh_once(**(args | {"latest_capture_sha256": "0" * 64}))
        with pytest.raises(module.RegisteredSourceDenied):
            with conn.transaction():
                repo.authorize_settled_second_fresh_once(**(args | {"expires_at": until + timedelta(minutes=1)}))
        auth_id = repo.authorize_settled_second_fresh_once(**args)
        with pytest.raises(module.RegisteredSourceDenied):
            with conn.transaction():
                repo.authorize_settled_second_fresh_once(**args)
        with pytest.raises(psycopg.IntegrityError):
            with conn.transaction():
                conn.execute("UPDATE rag_registered_final_followup_allowances "
                             "SET settled_second_capture_id=NULL,settled_second_capture_sha256=NULL "
                             "WHERE id=%s", (args["allowance_id"],))
        # Expiry between issuance and direct SQL dispatch cannot bypass the
        # database checker. Roll back the new test root only, then dispatch.
        with pytest.raises(psycopg.IntegrityError):
            with conn.transaction():
                conn.execute("UPDATE rag_budget_authority_roots SET period_end=clock_timestamp() WHERE root_id=%s", (item.root_id,))
                conn.execute(
                    "INSERT INTO rag_registered_fetch_attempts "
                    "(id,policy_id,generation,canonical_url_sha256,root_id,operation_key,request_hash,"
                    "supplemental_authorization_id) VALUES (%s,%s,3,%s,%s,%s,%s,%s)",
                    (item.dispatch_id, item.policy_id, hashlib.sha256(URL.encode()).hexdigest(),
                     item.root_id, "fresh.direct." + uuid4().hex, args["request_hash"], auth_id),
                )
        assert repo.take_dispatch(item, operation_key="fresh.test." + uuid4().hex,
                                  request_hash=args["request_hash"], now=datetime.now(timezone.utc),
                                  supplemental_authorization_id=auth_id) == item.dispatch_id
        assert repo.mark_unknown(item, error_code="FIXTURE_NO_HTTP", now=datetime.now(timezone.utc))
        fourth = replace(item, policy_id="fresh.fourth." + uuid4().hex,
                         root_id="fresh.fourth.root." + uuid4().hex, generation=4, dispatch_id=uuid4())
        _seed_target(conn, policy, fourth, until)
        with pytest.raises(module.RegisteredSourceDenied):
            with conn.transaction():
                repo.authorize_final_followup(
                    allowance_id=uuid4(), authorization_id=uuid4(), original_attempt_id=original_id,
                    latest_attempt_id=item.dispatch_id, scope=fourth, request_hash="c" * 64,
                    expires_at=until, approval_ref="standingpolicy.deploymentcorrection.fixture",
                    now=datetime.now(timezone.utc),
                )
        # Exclude only this newly issued test authorization from the old snapshot.
        old_only = snapshot_sql.replace("a WHERE prior_attempt_id=%s", "a WHERE prior_attempt_id=%s AND explicit_followup_id IS NULL")
        assert conn.execute(old_only, snapshot_args).fetchone()["h"] == before
    finally:
        conn.rollback()
        conn.close()


def _sql_correction_args(item=None):
    item = item or replace(
        _scope(), source_handle="source.e.firstbatch.sqlite.20261003",
        subject_id="route.sql", facets=("queries",),
        url="https://www.sqlite.org/lang_select.html", host="www.sqlite.org", path="/lang_select.html",
    )
    args = _args(item)
    args["original_capture_id"] = args.pop("latest_capture_id")
    args["original_capture_sha256"] = args.pop("latest_capture_sha256")
    return args | dict(latest_authorization_id=uuid4(),
                       approval_ref="standingpolicy.settledsourcecorrection.focused-test")


def test_sql_correction_issuer_is_separate_exact_and_never_a_diagnostic_boolean(monkeypatch):
    calls = []
    args = _sql_correction_args()
    repo = module.PostgresRegisteredSourceRepository("offline-only")
    monkeypatch.setattr(module.psycopg, "connect", lambda *_a, **_kw: pytest.fail("DB opened"))
    for changes in (
        {"scope": replace(args["scope"], generation=2)},
        {"approval_ref": "standingpolicy.settledsecondfreshness.wrong-branch"},
        {"latest_authorization_id": args["authorization_id"]},
    ):
        with pytest.raises(module.RegisteredSourceDenied, match="SETTLED_SOURCE_CORRECTION_DENIED"):
            repo.authorize_settled_source_correction_once(**(args | changes))

    def execute(query, params):
        calls.append((query, params))
        return SimpleNamespace(fetchone=lambda: {"id": args["original_attempt_id"]})

    conn = SimpleNamespace(execute=execute)
    monkeypatch.setattr(module.psycopg, "connect", lambda *_a, **_kw: nullcontext(conn))
    monkeypatch.setattr(module, "_clock", lambda *_a: args["now"])
    monkeypatch.setattr(module, "_current", lambda *_a, **_kw: {
        "canonical_url_sha256": hashlib.sha256(args["scope"].url.encode()).hexdigest(),
    })
    assert repo.authorize_settled_source_correction_once(**args) == args["authorization_id"]
    assert len(calls) == 3 and calls[0][0].endswith("FOR UPDATE")
    assert "settled_source_failed_authorization_id" in calls[1][0]
    assert calls[1][1][-3:] == (args["original_capture_id"], args["original_capture_sha256"],
                               args["latest_authorization_id"])
    assert repo._permits == {}
    sql = FRAGMENT.read_text(encoding="utf-8")
    assert "FOREIGN KEY(latest_attempt_id,settled_source_failed_authorization_id,canonical_url_sha256)" in sql
    assert "FOREIGN KEY(settled_source_capture_id,original_attempt_id,settled_source_capture_sha256)" in sql
    assert "latest_row.error_code IS DISTINCT FROM 'EGRESS_UNVERIFIED_SIGNATURE_PID_NAMESPACE'" in sql
    assert "policy_row.source_handle IS DISTINCT FROM latest_policy.source_handle" in sql
    assert "settled source correction cannot fund another followup" in sql


def test_pg_main_only_sql_settled_original_and_failed_supplemental_correction(monkeypatch):
    """Before real SQL gen3 issue only; preserve actual failure/capture, rollback new rows."""
    dsn = os.getenv("AEARN_SETTLED_SOURCE_FRESH_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("main-only SQL correction PG not executed: explicit exact B1d DSN required")
    expected = "aearn_b1d_sandbox_20261001"
    assert urlsplit(dsn).path.lstrip("/") == expected
    conn = psycopg.connect(dsn, row_factory=dict_row)
    try:
        assert conn.execute("SELECT current_database() AS name").fetchone()["name"] == expected
        original_id = UUID("8256098c-ddaa-4dd0-b387-0eea34b7596c")
        latest_id = UUID("e9541237-1d9d-4eb4-84f1-e5c10a233481")
        latest_auth = UUID("8549d0bc-6aba-48aa-b9e5-a26a6d1f657e")
        capture_id = UUID("b70b1d8f-383f-443b-8f25-de5145439dd4")
        capture_hash = "a6d38ca170dff62177e74e63297b44e567f673e7d2111de923e33b481560c140"
        policy = conn.execute(
            "SELECT p.* FROM rag_registered_source_policies p "
            "JOIN rag_registered_fetch_attempts a ON a.policy_id=p.policy_id WHERE a.id=%s",
            (latest_id,),
        ).fetchone()
        assert policy["generation"] == 1 and policy["source_handle"] == "source.e.firstbatch.sqlite.20261003"
        assert conn.execute(
            "SELECT count(*) AS n FROM rag_registered_final_followup_allowances WHERE original_attempt_id=%s",
            (original_id,),
        ).fetchone()["n"] == 0, "run only before real SQL correction issuance"
        snapshot_sql = """
          SELECT encode(digest(string_agg(row_json::text, '' ORDER BY row_json::text), 'sha256'),'hex') AS h
          FROM (
            SELECT to_jsonb(a) AS row_json FROM rag_registered_fetch_attempts a WHERE id=ANY(%s)
            UNION ALL SELECT to_jsonb(a) FROM rag_registered_supplemental_authorizations a WHERE id=%s
            UNION ALL SELECT to_jsonb(c) FROM rag_registered_source_captures c WHERE id=%s
            UNION ALL SELECT to_jsonb(p) FROM rag_registered_source_policies p WHERE policy_id IN
              (SELECT policy_id FROM rag_registered_fetch_attempts WHERE id=ANY(%s))
            UNION ALL SELECT to_jsonb(r) FROM rag_budget_authority_roots r WHERE root_id IN
              (SELECT root_id FROM rag_registered_fetch_attempts WHERE id=ANY(%s))
          ) history
        """
        snapshot_args = ([original_id, latest_id], latest_auth, capture_id,
                         [original_id, latest_id], [original_id, latest_id])
        before = conn.execute(snapshot_sql, snapshot_args).fetchone()["h"]
        for _ in range(2):
            conn.execute(FRAGMENT.read_text(encoding="utf-8"))
        assert conn.execute(
            "SELECT count(*) AS n FROM rag_registered_final_followup_allowances WHERE original_attempt_id=%s",
            (original_id,),
        ).fetchone()["n"] == 0
        args = _sql_correction_args()
        item = replace(args["scope"], max_bytes=policy["max_captured_bytes"])
        until = conn.execute("SELECT clock_timestamp() AS t").fetchone()["t"] + timedelta(minutes=5)
        _seed_target(conn, policy, item, until)
        args.update(scope=item, original_attempt_id=original_id, latest_attempt_id=latest_id,
                    latest_authorization_id=latest_auth, original_capture_id=capture_id,
                    original_capture_sha256=capture_hash, expires_at=until)
        repo = module.PostgresRegisteredSourceRepository("rollback-only")
        monkeypatch.setattr(module.psycopg, "connect", lambda *_a, **_kw: nullcontext(conn))
        with pytest.raises(module.RegisteredSourceDenied):
            with conn.transaction():
                repo.authorize_settled_source_correction_once(**(args | {"latest_authorization_id": uuid4()}))
        auth_id = repo.authorize_settled_source_correction_once(**args)
        with pytest.raises(module.RegisteredSourceDenied):
            with conn.transaction():
                repo.authorize_settled_source_correction_once(**args)
        # Use direct SQL, not the issuer, to verify immutable variant and expiry fences.
        with pytest.raises(psycopg.IntegrityError):
            with conn.transaction():
                conn.execute("UPDATE rag_registered_final_followup_allowances "
                             "SET settled_source_failed_authorization_id=%s WHERE id=%s",
                             (uuid4(), args["allowance_id"]))
        with pytest.raises(psycopg.IntegrityError):
            with conn.transaction():
                conn.execute("UPDATE rag_budget_authority_roots SET period_end=clock_timestamp() WHERE root_id=%s", (item.root_id,))
                conn.execute(
                    "INSERT INTO rag_registered_fetch_attempts "
                    "(id,policy_id,generation,canonical_url_sha256,root_id,operation_key,request_hash,"
                    "supplemental_authorization_id) VALUES (%s,%s,3,%s,%s,%s,%s,%s)",
                    (item.dispatch_id, item.policy_id, hashlib.sha256(item.url.encode()).hexdigest(),
                     item.root_id, "correction.direct." + uuid4().hex, args["request_hash"], auth_id),
                )
        assert repo.take_dispatch(item, operation_key="correction.test." + uuid4().hex,
                                  request_hash=args["request_hash"], now=datetime.now(timezone.utc),
                                  supplemental_authorization_id=auth_id) == item.dispatch_id
        assert repo.mark_unknown(item, error_code="FIXTURE_NO_HTTP", now=datetime.now(timezone.utc))
        fourth = replace(item, policy_id="correction.fourth." + uuid4().hex,
                         root_id="correction.fourth.root." + uuid4().hex, generation=4, dispatch_id=uuid4())
        _seed_target(conn, policy, fourth, until)
        with pytest.raises(module.RegisteredSourceDenied):
            with conn.transaction():
                repo.authorize_final_followup(
                    allowance_id=uuid4(), authorization_id=uuid4(), original_attempt_id=original_id,
                    latest_attempt_id=item.dispatch_id, scope=fourth, request_hash="c" * 64,
                    expires_at=until, approval_ref="standingpolicy.deploymentcorrection.fixture",
                    now=datetime.now(timezone.utc),
                )
        assert conn.execute(snapshot_sql, snapshot_args).fetchone()["h"] == before
    finally:
        conn.rollback()
        conn.close()
