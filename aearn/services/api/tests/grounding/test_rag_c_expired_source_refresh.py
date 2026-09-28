"""Generation-five source freshness grant tests; no HTTP or provider calls."""
from __future__ import annotations

import hashlib
import json
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest

from app.db.schema import load_schema_fragments
from app.services.grounding.autonomous import registered_source_repository as module
from tests.grounding.test_rag_c_final_followup import _attempt, _auth, _seed, _unknown
from tests.grounding.test_rag_c_registered_source_repository import _disposable_db, scope


def _db_now(conn):
    return conn.execute("SELECT clock_timestamp() AS now").fetchone()["now"]


def _seed_window(conn, item, *, now, until):
    conn.execute(
        "INSERT INTO rag_budget_authority_roots "
        "(root_id,delegation_id,delegation_generation,delegation_expires_at,policy_id,"
        "policy_generation,period_key,period_start,period_end,cap_units,enabled) "
        "VALUES (%s,%s,1,%s,%s,%s,%s,%s,%s,1,true)",
        (
            item.root_id,
            "delegation." + uuid4().hex,
            until,
            item.policy_id,
            item.generation,
            "period." + uuid4().hex,
            now - timedelta(minutes=1),
            until,
        ),
    )
    conn.execute(
        "INSERT INTO rag_registered_source_policies "
        "(policy_id,generation,source_handle,subject_id,subject_version,facets,origin,"
        "reading_level,canonical_url,canonical_url_sha256,host,path,license_id,allowed_usages,"
        "immutable_history_allowed,max_captured_bytes,retention_until,expires_at,root_id,enabled) "
        "VALUES (%s,%s,%s,%s,%s,%s,'official','beginner',%s,%s,%s,%s,'Public-Domain',"
        "ARRAY['supplementary_explanation'],true,%s,%s,%s,%s,true)",
        (
            item.policy_id,
            item.generation,
            item.source_handle,
            item.subject_id,
            item.subject_version,
            list(item.facets),
            item.url,
            hashlib.sha256(item.url.encode()).hexdigest(),
            item.host,
            item.path,
            item.max_bytes,
            until,
            until,
            item.root_id,
        ),
    )


def _make_expiring_chain(conn, monkeypatch):
    now = _db_now(conn)
    base = scope()
    path = "/fixture-source-refresh-" + uuid4().hex + ".html"
    url = "https://www.sqlite.org" + path
    original, second, third, fourth = [
        replace(
            base,
            generation=generation,
            url=url,
            path=path,
            policy_id="registered." + uuid4().hex,
            root_id="source." + uuid4().hex,
            dispatch_id=uuid4(),
        )
        for generation in (1, 2, 3, 4)
    ]
    for item in (original, second, third):
        _seed(conn, item, now)
    _attempt(conn, original)
    _unknown(conn, original)
    unused_auth, second_auth = uuid4(), uuid4()
    _auth(conn, replace(original, dispatch_id=uuid4()), unused_auth, original.dispatch_id, now)
    conn.execute(
        "INSERT INTO rag_registered_supplemental_revocations "
        "(authorization_id,prior_attempt_id,approval_ref) VALUES (%s,%s,%s)",
        (unused_auth, original.dispatch_id, "fixture.operator.unused.correction"),
    )
    _auth(conn, second, second_auth, original.dispatch_id, now, replacement=unused_auth)
    _attempt(conn, second, auth_id=second_auth)
    _unknown(conn, second)

    repo = module.PostgresRegisteredSourceRepository("rollback-fixture")
    monkeypatch.setattr(module.psycopg, "connect", lambda *_a, **_kw: nullcontext(conn))
    third_allowance, third_auth = uuid4(), uuid4()
    repo.authorize_final_followup(
        allowance_id=third_allowance,
        authorization_id=third_auth,
        original_attempt_id=original.dispatch_id,
        latest_attempt_id=second.dispatch_id,
        scope=third,
        request_hash="b" * 64,
        expires_at=now + timedelta(minutes=10),
        approval_ref="fixture.operator.explicit.final.credit",
        now=datetime.now(timezone.utc),
    )
    _attempt(conn, third, auth_id=third_auth)
    _unknown(conn, third)

    old_end = _db_now(conn) + timedelta(seconds=4)
    _seed_window(conn, fourth, now=_db_now(conn), until=old_end)
    fourth_allowance, fourth_auth = uuid4(), uuid4()
    repo.authorize_final_followup(
        allowance_id=fourth_allowance,
        authorization_id=fourth_auth,
        original_attempt_id=original.dispatch_id,
        latest_attempt_id=third.dispatch_id,
        scope=fourth,
        request_hash="b" * 64,
        expires_at=old_end - timedelta(milliseconds=100),
        approval_ref="standingpolicy.deploymentcorrection.fixture20260928",
        now=datetime.now(timezone.utc),
    )
    _attempt(conn, fourth, auth_id=fourth_auth)
    body = b"generation-four settled freshness fixture"
    digest = hashlib.sha256(body).hexdigest()
    proof = b'{"fixture":"signed-worker-envelope"}'
    fetched_at = _db_now(conn)
    conn.execute("SELECT pg_sleep(0.01)")
    settled_at = _db_now(conn)
    conn.execute(
        "UPDATE rag_registered_fetch_attempts SET state='settled',response_sha256=%s,"
        "response_bytes=%s,settled_at=%s WHERE id=%s",
        (digest, len(body), settled_at, fourth.dispatch_id),
    )
    capture_id = conn.execute(
        "INSERT INTO rag_registered_source_captures "
        "(fetch_attempt_id,policy_id,generation,request_chain,final_url,content_type,"
        "fetched_sha256,captured_bytes,captured_body,license_id,retention_until,fetched_at,"
        "transport_proof,transport_proof_sha256,attestor_key_sha256,worker_image_sha256) "
        "VALUES (%s,%s,4,%s::jsonb,%s,'text/plain',%s,%s,%s,'Public-Domain',%s,%s,%s,%s,%s,%s) "
        "RETURNING id",
        (
            fourth.dispatch_id,
            fourth.policy_id,
            json.dumps([url]),
            url,
            digest,
            len(body),
            body,
            old_end,
            fetched_at,
            proof,
            hashlib.sha256(proof).hexdigest(),
            "a" * 64,
            "c" * 64,
        ),
    ).fetchone()["id"]
    fifth = replace(
        fourth,
        generation=5,
        policy_id="registered." + uuid4().hex,
        root_id="source." + uuid4().hex,
        dispatch_id=uuid4(),
    )
    return SimpleNamespace(
        repo=repo,
        original=original,
        second=second,
        third=third,
        fourth=fourth,
        fifth=fifth,
        capture_id=capture_id,
        old_end=old_end,
    )


def _wait_until_expired(conn, end):
    conn.execute(
        "SELECT pg_sleep(GREATEST(EXTRACT(EPOCH FROM (%s-clock_timestamp())),0)+0.05)",
        (end,),
    )


def _seed_fifth(conn, fifth):
    now = _db_now(conn)
    until = now + timedelta(hours=23)
    _seed_window(conn, fifth, now=now, until=until)
    return now + timedelta(hours=1)


def _issue_refresh(conn, chain, expires_at, *, approval_ref=None):
    allowance_id, authorization_id = uuid4(), uuid4()
    approval = approval_ref or "standingpolicy.sourcefreshness.fixture20260928"
    url_hash = hashlib.sha256(chain.fifth.url.encode()).hexdigest()
    conn.execute(
        "INSERT INTO rag_registered_final_followup_allowances "
        "(id,original_attempt_id,latest_attempt_id,authorization_id,dispatch_id,policy_id,"
        "generation,canonical_url_sha256,root_id,request_hash,expires_at,approval_ref) "
        "VALUES (%s,%s,%s,%s,%s,%s,5,%s,%s,%s,%s,%s)",
        (
            allowance_id,
            chain.original.dispatch_id,
            chain.fourth.dispatch_id,
            authorization_id,
            chain.fifth.dispatch_id,
            chain.fifth.policy_id,
            url_hash,
            chain.fifth.root_id,
            "d" * 64,
            expires_at,
            approval,
        ),
    )
    conn.execute(
        "INSERT INTO rag_registered_supplemental_authorizations "
        "(id,dispatch_id,policy_id,generation,canonical_url_sha256,root_id,request_hash,"
        "prior_attempt_id,expires_at,approval_ref,explicit_followup_id) "
        "VALUES (%s,%s,%s,5,%s,%s,%s,%s,%s,%s,%s)",
        (
            authorization_id,
            chain.fifth.dispatch_id,
            chain.fifth.policy_id,
            url_hash,
            chain.fifth.root_id,
            "d" * 64,
            chain.original.dispatch_id,
            expires_at,
            approval,
            allowance_id,
        ),
    )
    return allowance_id, authorization_id


def test_expired_settled_fourth_allows_one_fifth_dispatch_and_preserves_history(monkeypatch):
    conn = _disposable_db()
    try:
        chain = _make_expiring_chain(conn, monkeypatch)
        _wait_until_expired(conn, chain.old_end)
        expires_at = _seed_fifth(conn, chain.fifth)
        old_attempts = conn.execute(
            "SELECT to_jsonb(a) AS row FROM rag_registered_fetch_attempts a "
            "WHERE canonical_url_sha256=%s ORDER BY generation",
            (hashlib.sha256(chain.fifth.url.encode()).hexdigest(),),
        ).fetchall()
        old_allowances = conn.execute(
            "SELECT to_jsonb(a) AS row FROM rag_registered_final_followup_allowances a "
            "WHERE original_attempt_id=%s ORDER BY generation",
            (chain.original.dispatch_id,),
        ).fetchall()
        old_capture = conn.execute(
            "SELECT to_jsonb(c) AS row FROM rag_registered_source_captures c WHERE id=%s",
            (chain.capture_id,),
        ).fetchone()

        with conn.transaction():
            _, authorization_id = _issue_refresh(conn, chain, expires_at)
        assert chain.repo.take_dispatch(
            chain.fifth,
            operation_key="freshness." + uuid4().hex,
            request_hash="d" * 64,
            now=datetime.now(timezone.utc),
            supplemental_authorization_id=authorization_id,
        ) == chain.fifth.dispatch_id
        assert conn.execute(
            "SELECT generation,state FROM rag_registered_fetch_attempts "
            "WHERE canonical_url_sha256=%s ORDER BY generation",
            (hashlib.sha256(chain.fifth.url.encode()).hexdigest(),),
        ).fetchall() == [
            {"generation": 1, "state": "unknown"},
            {"generation": 2, "state": "unknown"},
            {"generation": 3, "state": "unknown"},
            {"generation": 4, "state": "settled"},
            {"generation": 5, "state": "dispatched"},
        ]
        assert conn.execute(
            "SELECT to_jsonb(a) AS row FROM rag_registered_fetch_attempts a "
            "WHERE canonical_url_sha256=%s AND generation<=4 ORDER BY generation",
            (hashlib.sha256(chain.fifth.url.encode()).hexdigest(),),
        ).fetchall() == old_attempts
        assert conn.execute(
            "SELECT to_jsonb(a) AS row FROM rag_registered_final_followup_allowances a "
            "WHERE original_attempt_id=%s AND generation<=4 ORDER BY generation",
            (chain.original.dispatch_id,),
        ).fetchall() == old_allowances
        assert conn.execute(
            "SELECT to_jsonb(c) AS row FROM rag_registered_source_captures c WHERE id=%s",
            (chain.capture_id,),
        ).fetchone() == old_capture

        with pytest.raises(psycopg.IntegrityError):
            with conn.transaction():
                _issue_refresh(conn, chain, expires_at)
        with pytest.raises(psycopg.IntegrityError):
            with conn.transaction():
                conn.execute(
                    "INSERT INTO rag_registered_final_followup_allowances "
                    "(id,original_attempt_id,latest_attempt_id,authorization_id,dispatch_id,"
                    "policy_id,generation,canonical_url_sha256,root_id,request_hash,expires_at,"
                    "approval_ref) VALUES (%s,%s,%s,%s,%s,%s,6,%s,%s,%s,%s,%s)",
                    (
                        uuid4(),
                        chain.original.dispatch_id,
                        chain.fourth.dispatch_id,
                        uuid4(),
                        uuid4(),
                        chain.fifth.policy_id,
                        hashlib.sha256(chain.fifth.url.encode()).hexdigest(),
                        chain.fifth.root_id,
                        "e" * 64,
                        expires_at,
                        "standingpolicy.sourcefreshness.no-generation-six",
                    ),
                )
    finally:
        conn.rollback()
        conn.close()


def test_refresh_denies_unexpired_or_cleared_history_and_missing_or_expired_grant(monkeypatch):
    conn = _disposable_db()
    try:
        chain = _make_expiring_chain(conn, monkeypatch)
        expires_at = _seed_fifth(conn, chain.fifth)
        with pytest.raises(psycopg.IntegrityError):
            with conn.transaction():
                _issue_refresh(conn, chain, expires_at)
        _wait_until_expired(conn, chain.old_end)
        with pytest.raises(psycopg.IntegrityError):
            with conn.transaction():
                _issue_refresh(conn, chain, _db_now(conn) - timedelta(seconds=1))
        with pytest.raises(psycopg.IntegrityError):
            with conn.transaction():
                conn.execute(
                    "INSERT INTO rag_registered_fetch_attempts "
                    "(id,policy_id,generation,canonical_url_sha256,root_id,operation_key,request_hash) "
                    "VALUES (%s,%s,5,%s,%s,%s,%s)",
                    (
                        chain.fifth.dispatch_id,
                        chain.fifth.policy_id,
                        hashlib.sha256(chain.fifth.url.encode()).hexdigest(),
                        chain.fifth.root_id,
                        "freshness.missing." + uuid4().hex,
                        "d" * 64,
                    ),
                )
        conn.execute(
            "UPDATE rag_registered_source_captures "
            "SET captured_body=NULL,cleared_at=clock_timestamp() WHERE id=%s",
            (chain.capture_id,),
        )
        with pytest.raises(psycopg.IntegrityError):
            with conn.transaction():
                _issue_refresh(conn, chain, expires_at)
        assert conn.execute(
            "SELECT count(*) AS n FROM rag_registered_final_followup_allowances "
            "WHERE original_attempt_id=%s AND generation=5",
            (chain.original.dispatch_id,),
        ).fetchone()["n"] == 0
    finally:
        conn.rollback()
        conn.close()


def test_replayed_410_denies_until_420_is_restored_and_bootstrap_grants_nothing(monkeypatch):
    conn = _disposable_db()
    try:
        chain = _make_expiring_chain(conn, monkeypatch)
        _wait_until_expired(conn, chain.old_end)
        expires_at = _seed_fifth(conn, chain.fifth)
        fragments = {fragment.name: fragment.sql for fragment in load_schema_fragments()}
        conn.execute(fragments["410_rag_c_deployment_correction.sql"])
        with pytest.raises(psycopg.IntegrityError):
            with conn.transaction():
                _issue_refresh(conn, chain, expires_at)
        conn.execute(fragments["420_rag_c_expired_source_refresh.sql"])
        assert conn.execute(
            "SELECT count(*) AS n FROM rag_registered_final_followup_allowances "
            "WHERE original_attempt_id=%s AND generation=5",
            (chain.original.dispatch_id,),
        ).fetchone()["n"] == 0
        with conn.transaction():
            _issue_refresh(conn, chain, expires_at)
        assert conn.execute(
            "SELECT count(*) AS n FROM rag_registered_final_followup_allowances "
            "WHERE original_attempt_id=%s AND generation=5",
            (chain.original.dispatch_id,),
        ).fetchone()["n"] == 1
    finally:
        conn.rollback()
        conn.close()
