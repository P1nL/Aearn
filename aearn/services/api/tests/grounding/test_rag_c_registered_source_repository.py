"""Registered-source repository tests never access a live URL or provider."""

from __future__ import annotations

import hashlib
import os
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.services.grounding.autonomous import registered_source_repository as module
from app.services.grounding.autonomous.registered_source_policy import (
    RegisteredSourceHopPolicy,
    RegisteredSourceScope,
)
from app.services.grounding.autonomous.safe_fetch import FetchResult, SafeFetcher

URL = "https://www.sqlite.org/lang_select.html"


def scope() -> RegisteredSourceScope:
    suffix = uuid4().hex
    return RegisteredSourceScope(
        policy_id="registered." + suffix,
        generation=1,
        source_handle="sqlite." + suffix,
        subject_id="route.sql",
        subject_version="v1",
        facets=("queries",),
        url=URL,
        host="www.sqlite.org",
        path="/lang_select.html",
        root_id="source." + suffix,
        dispatch_id=uuid4(),
        max_bytes=1024 * 1024,
    )


def test_bad_inputs_are_bounded_and_do_not_connect(monkeypatch):
    repo = module.PostgresRegisteredSourceRepository("not-a-real-dsn")
    monkeypatch.setattr(
        module.psycopg, "connect", lambda *_args, **_kwargs: pytest.fail("DB opened")
    )
    expected = scope()
    assert repo.resolve(expected, now=datetime(2026, 9, 25)) is None
    with pytest.raises(module.RegisteredSourceDenied, match="DISPATCH_DENIED"):
        repo.take_dispatch(
            expected,
            operation_key="too",
            request_hash="0" * 64,
            now=datetime.now(timezone.utc),
        )
    with pytest.raises(module.RegisteredSourceDenied, match="LIVE_BRIDGE_REQUIRED"):
        repo.settle_capture(
            expected,
            fetcher=SafeFetcher(),
            result=FetchResult(URL, (URL,), "text/html", b"x", "0" * 64, 1, 1),
            now=datetime.now(timezone.utc),
        )
    with pytest.raises(module.RegisteredSourceDenied, match="UNKNOWN_DENIED"):
        repo.mark_unknown(
            expected, error_code="raw/secret", now=datetime.now(timezone.utc)
        )


def test_missing_db_fails_closed_without_details(monkeypatch):
    def fail(*_args, **_kwargs):
        raise psycopg.OperationalError("sensitive database details")

    monkeypatch.setattr(module.psycopg, "connect", fail)
    repo = module.PostgresRegisteredSourceRepository("unused")
    item = scope()
    repo._permits[item.dispatch_id] = (item, 2)  # simulate committed dispatch
    assert repo.resolve(item, now=datetime.now(timezone.utc)) is None


def _disposable_db():
    dsn = os.getenv("AEARN_RAG_C_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("C PostgreSQL not executed: explicit disposable DB URL required")
    expected = urlsplit(dsn).path.lstrip("/")
    if not expected.startswith("aearn_rag260_c_"):
        pytest.fail("refusing a non-C disposable database")
    conn = psycopg.connect(dsn, row_factory=dict_row)
    try:
        actual = conn.execute("SELECT current_database() AS name").fetchone()
        schema = conn.execute(
            "SELECT to_regclass('rag_registered_source_captures') AS name"
        ).fetchone()
        if (
            actual is None
            or actual["name"] != expected
            or schema is None
            or schema["name"] is None
        ):
            pytest.fail("explicit database identity and pre-applied C schema required")
        return conn
    except BaseException:
        conn.close()
        raise


def _seed(conn, item, now):
    until = now + timedelta(hours=1)
    conn.execute(
        "INSERT INTO rag_budget_authority_roots "
        "(root_id,delegation_id,delegation_generation,delegation_expires_at,"
        "policy_id,policy_generation,period_key,period_start,period_end,cap_units,enabled) "
        "VALUES (%s,%s,1,%s,%s,1,%s,%s,%s,1,true)",
        (
            item.root_id,
            "delegation." + uuid4().hex,
            until,
            item.policy_id,
            "period." + uuid4().hex,
            now - timedelta(minutes=1),
            until,
        ),
    )
    conn.execute(
        "INSERT INTO rag_registered_source_policies "
        "(policy_id,generation,source_handle,subject_id,subject_version,facets,"
        "origin,reading_level,canonical_url,canonical_url_sha256,host,path,license_id,"
        "allowed_usages,immutable_history_allowed,max_captured_bytes,retention_until,"
        "expires_at,root_id,enabled) "
        "VALUES (%s,1,%s,%s,%s,%s,'official','beginner',%s,%s,%s,%s,'Public-Domain',"
        "%s,true,%s,%s,%s,%s,true)",
        (
            item.policy_id,
            item.source_handle,
            item.subject_id,
            item.subject_version,
            list(item.facets),
            item.url,
            hashlib.sha256(item.url.encode()).hexdigest(),
            item.host,
            item.path,
            ["main_teaching"],
            item.max_bytes,
            until,
            until,
            item.root_id,
        ),
    )


def test_pg_one_shot_current_policy_and_blocked_capture_rollback(monkeypatch):
    """All fixtures and attempt/capture writes stay in an owned rollback transaction.

    The connection substitution lets this test read its uncommitted fixtures; it
    does NOT prove the production fresh-connection/committed-dispatch boundary.
    """
    conn = _disposable_db()
    try:
        now = datetime.now(timezone.utc)
        item = scope()
        _seed(conn, item, now)
        repo = module.PostgresRegisteredSourceRepository("unused-in-rollback-test")
        monkeypatch.setattr(
            module.psycopg, "connect", lambda *_a, **_kw: nullcontext(conn)
        )
        assert repo.resolve(item, now=now) is None  # no durable dispatch yet
        assert (
            repo.take_dispatch(
                item,
                operation_key="one-shot." + uuid4().hex,
                request_hash="a" * 64,
                now=now,
            )
            == item.dispatch_id
        )
        with pytest.raises(module.RegisteredSourceDenied, match="ALREADY_DISPATCHED"):
            repo.take_dispatch(
                item,
                operation_key="replay." + uuid4().hex,
                request_hash="a" * 64,
                now=now,
            )
        assert repo.resolve(item, now=now) is not None
        assert repo.resolve(replace(item, root_id="other.root"), now=now) is None
        # Even a matching fake in-process token may not be turned into a live
        # capture: the signed cross-namespace dispatch-bound proof is absent.
        body = b"offline fake; never requested"
        digest = hashlib.sha256(body).hexdigest()
        fetcher = SafeFetcher(hop_policy=RegisteredSourceHopPolicy(item, resolver=repo))
        result = FetchResult(
            URL,
            (URL,),
            "text/html",
            body,
            digest,
            len(body),
            len(body),
            "live_egress_attested",
            object(),
            "full",
        )
        with pytest.raises(module.RegisteredSourceDenied, match="LIVE_BRIDGE_REQUIRED"):
            repo.settle_capture(item, fetcher=fetcher, result=result, now=now)
        attempt = conn.execute(
            "SELECT state FROM rag_registered_fetch_attempts WHERE id=%s",
            (item.dispatch_id,),
        ).fetchone()
        assert attempt is not None and attempt["state"] == "dispatched"
        count = conn.execute(
            "SELECT count(*) AS n FROM rag_registered_source_captures "
            "WHERE fetch_attempt_id=%s",
            (item.dispatch_id,),
        ).fetchone()
        assert count is not None and count["n"] == 0
    finally:
        conn.rollback()
        conn.close()


def test_pg_revocation_and_unknown_never_reopen_dispatch(monkeypatch):
    conn = _disposable_db()
    try:
        now = datetime.now(timezone.utc)
        item = scope()
        _seed(conn, item, now)
        repo = module.PostgresRegisteredSourceRepository("unused-in-rollback-test")
        monkeypatch.setattr(
            module.psycopg, "connect", lambda *_a, **_kw: nullcontext(conn)
        )
        repo.take_dispatch(
            item,
            operation_key="one-shot." + uuid4().hex,
            request_hash="b" * 64,
            now=now,
        )
        conn.execute(
            "UPDATE rag_registered_source_policies SET enabled=false,revoked_at=%s "
            "WHERE policy_id=%s",
            (now, item.policy_id),
        )
        assert repo.resolve(item, now=now) is None
        assert repo.mark_unknown(item, error_code="TRANSPORT_UNKNOWN", now=now)
        assert not repo.mark_unknown(item, error_code="TRANSPORT_UNKNOWN", now=now)
        with pytest.raises(module.RegisteredSourceDenied):
            repo.take_dispatch(
                item,
                operation_key="replay." + uuid4().hex,
                request_hash="b" * 64,
                now=now,
            )
    finally:
        conn.rollback()
        conn.close()


def test_dispatch_commits_before_fresh_per_hop_reads(monkeypatch):
    item = scope()
    now = datetime.now(timezone.utc)
    expiry = now + timedelta(hours=1)
    state = {"committed": False, "opened": [], "reads": 0}
    policy = {
        "generation": 1,
        "source_handle": item.source_handle,
        "subject_id": item.subject_id,
        "subject_version": item.subject_version,
        "facets": list(item.facets),
        "canonical_url": item.url,
        "canonical_url_sha256": hashlib.sha256(item.url.encode()).hexdigest(),
        "host": item.host,
        "path": item.path,
        "root_id": item.root_id,
        "enabled": True,
        "revoked_at": None,
        "license_id": "Public-Domain",
        "allowed_usages": ["main_teaching"],
        "immutable_history_allowed": True,
        "max_captured_bytes": item.max_bytes,
        "retention_until": expiry,
        "expires_at": expiry,
    }
    root = {
        "enabled": True,
        "delegation_expires_at": expiry,
        "period_start": now - timedelta(minutes=1),
        "period_end": expiry,
        "policy_id": item.policy_id,
        "policy_generation": item.generation,
    }

    class Row:
        def __init__(self, data):
            self.data = data

        def fetchone(self):
            return self.data

    class Connection:
        def __init__(self):
            state["opened"].append(self)

        def __enter__(self):
            return self

        def __exit__(self, kind, _value, _tb):
            if kind is None:
                state["committed"] = True

        def execute(self, sql, _params=None):
            if "clock_timestamp()" in sql:
                return Row({"db_now": now})
            if "FROM rag_registered_source_policies" in sql:
                return Row(policy)
            if "FROM rag_budget_authority_roots" in sql:
                return Row(root)
            if "INSERT INTO rag_registered_fetch_attempts" in sql:
                assert not state["committed"]
                return Row({"id": item.dispatch_id})
            if "FROM rag_registered_fetch_attempts a" in sql:
                assert state["committed"]
                state["reads"] += 1
                return Row(
                    {
                        "id": item.dispatch_id,
                        "state": "dispatched",
                        "root_id": item.root_id,
                        "supplemental_expires_at": None,
                    }
                )
            raise AssertionError("unexpected SQL")

    monkeypatch.setattr(module.psycopg, "connect", lambda *_a, **_kw: Connection())
    repo = module.PostgresRegisteredSourceRepository("injected")
    assert (
        repo.take_dispatch(
            item, operation_key="once." + uuid4().hex, request_hash="c" * 64, now=now
        )
        == item.dispatch_id
    )
    assert state["committed"]
    assert repo.resolve(item, now=now) is not None
    assert repo.resolve(item, now=now) is not None
    assert repo.resolve(item, now=now) is None  # third check cannot start a second GET
    restarted = module.PostgresRegisteredSourceRepository("injected")
    assert restarted.resolve(item, now=now) is None  # crash/restart loses permit
    assert len(state["opened"]) == 3 and state["reads"] == 2
    assert len(set(map(id, state["opened"]))) == 3


def test_pg_supplemental_dispatch_is_bound_to_terminal_original(monkeypatch):
    """Only an explicit, exact, unexpired operator row allows one more URL dispatch."""
    conn = _disposable_db()
    try:
        now = datetime.now(timezone.utc)
        original = scope()
        _seed(conn, original, now)
        repo = module.PostgresRegisteredSourceRepository("unused-in-rollback-test")
        monkeypatch.setattr(module.psycopg, "connect", lambda *_a, **_kw: nullcontext(conn))
        old_request_hash = "a" * 64
        repo.take_dispatch(
            original, operation_key="original." + uuid4().hex,
            request_hash=old_request_hash, now=now,
        )
        assert repo.mark_unknown(original, error_code="TRANSPORT_UNKNOWN", now=now)

        supplemental = scope()  # new policy/root, same exact URL; old row stays unknown
        _seed(conn, supplemental, now)
        request_hash = "b" * 64
        with pytest.raises(module.RegisteredSourceDenied, match="ALREADY_DISPATCHED"):
            repo.take_dispatch(
                supplemental, operation_key="unapproved." + uuid4().hex,
                request_hash=request_hash, now=now,
            )
        authorization_id = uuid4()
        approval_ref = "2026-09-25-extra1-consumed-extra2-one-remaining"
        conn.execute(
            "INSERT INTO rag_registered_supplemental_authorizations "
            "(id,dispatch_id,policy_id,generation,canonical_url_sha256,root_id,"
            "request_hash,prior_attempt_id,expires_at,approval_ref) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                authorization_id, supplemental.dispatch_id, supplemental.policy_id,
                supplemental.generation, hashlib.sha256(URL.encode()).hexdigest(),
                supplemental.root_id, request_hash, original.dispatch_id,
                now + timedelta(minutes=20), approval_ref,
            ),
        )
        with pytest.raises(module.RegisteredSourceDenied, match="SUPPLEMENTAL_DENIED"):
            repo.take_dispatch(
                supplemental, operation_key="wrong-hash." + uuid4().hex,
                request_hash="c" * 64, now=now,
                supplemental_authorization_id=authorization_id,
            )
        with pytest.raises(module.RegisteredSourceDenied, match="SUPPLEMENTAL_DENIED"):
            repo.take_dispatch(
                replace(supplemental, dispatch_id=uuid4()),
                operation_key="wrong-id." + uuid4().hex, request_hash=request_hash,
                now=now, supplemental_authorization_id=authorization_id,
            )
        # No new row on the denied paths; exact authorization grants just one insert.
        assert repo.take_dispatch(
            supplemental, operation_key="approved." + uuid4().hex,
            request_hash=request_hash, now=now,
            supplemental_authorization_id=authorization_id,
        ) == supplemental.dispatch_id
        assert repo.resolve(supplemental, now=now) is not None
        assert repo.resolve(supplemental, now=now) is not None
        assert repo.resolve(supplemental, now=now) is None
        assert module.PostgresRegisteredSourceRepository("unused").resolve(supplemental, now=now) is None
        with pytest.raises(module.RegisteredSourceDenied, match="ALREADY_DISPATCHED"):
            repo.take_dispatch(
                supplemental, operation_key="replay." + uuid4().hex,
                request_hash=request_hash, now=now,
                supplemental_authorization_id=authorization_id,
            )
        # A populated database must survive 320 -> 350 full-schema replay twice:
        # 320 sees the existing named partial index and must not recreate global uniqueness.
        from app.db.schema import load_schema_fragments

        fragments = {fragment.name: fragment.sql for fragment in load_schema_fragments()}
        for _ in range(2):
            conn.execute(fragments["320_rag_registered_source.sql"])
            conn.execute(fragments["350_rag_c_supplemental_dispatch.sql"])
            conn.execute(fragments["390_rag_c_supplemental_recovery.sql"])
        assert conn.execute(
            "SELECT count(*) AS n FROM rag_registered_fetch_attempts "
            "WHERE canonical_url_sha256=%s",
            (hashlib.sha256(URL.encode()).hexdigest(),),
        ).fetchone()["n"] == 2
        old = conn.execute(
            "SELECT state,supplemental_authorization_id FROM rag_registered_fetch_attempts WHERE id=%s",
            (original.dispatch_id,),
        ).fetchone()
        assert old == {"state": "unknown", "supplemental_authorization_id": None}
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(
                    "UPDATE rag_registered_fetch_attempts "
                    "SET supplemental_authorization_id=%s WHERE id=%s",
                    (authorization_id, original.dispatch_id),
                )
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(
                    "UPDATE rag_registered_supplemental_authorizations SET approval_ref=%s WHERE id=%s",
                    ("changed-approved-reference", authorization_id),
                )
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(
                    "DELETE FROM rag_registered_supplemental_authorizations WHERE id=%s",
                    (authorization_id,),
                )
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(
                    "INSERT INTO rag_registered_supplemental_authorizations "
                    "(id,dispatch_id,policy_id,generation,canonical_url_sha256,root_id,"
                    "request_hash,prior_attempt_id,expires_at,approval_ref) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        uuid4(), uuid4(), supplemental.policy_id, supplemental.generation,
                        hashlib.sha256(URL.encode()).hexdigest(), supplemental.root_id,
                        "d" * 64, original.dispatch_id, now + timedelta(minutes=20),
                        approval_ref,
                    ),
                )
    finally:
        conn.rollback()
        conn.close()
