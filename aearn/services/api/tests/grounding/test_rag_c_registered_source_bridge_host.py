"""Offline bridge contract checks; optional PostgreSQL uses only an explicit C DB."""

from __future__ import annotations

import hashlib
import os
import socket
from contextlib import nullcontext
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from psycopg.rows import dict_row

from app.services.grounding.autonomous import registered_source_bridge_host as bridge
from app.services.grounding.autonomous.registered_source_repository import PostgresRegisteredSourceRepository
from app.services.grounding.autonomous.registered_source_policy import RegisteredSourceHopGrant, RegisteredSourceScope

URL = "https://www.sqlite.org/lang_select.html"
POLICY_DIGEST = "a" * 64
BODY = b"offline synthetic SELECT page; no HTTP request"


@dataclass(frozen=True)
class Decision:
    max_bytes: int
    expires_at: datetime


@dataclass(frozen=True)
class CaptureRecord:
    capture_id: str


def scope():
    suffix = uuid4().hex
    return SimpleNamespace(
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
        dispatch_id=str(uuid4()),
        max_bytes=1024 * 1024,
    )


def signer():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return private, bridge.SignedDispatchProofVerifier(
        public_key=public,
        deployment_id="rag-c-test",
        policy_sha256=POLICY_DIGEST,
        namespace_inode=12345,
        allowed_ips=frozenset({"8.8.8.8"}),
    )


def proof(private, item, now, *, body=BODY, **changes):
    """B signed egress fact and unsigned report from a synthetic worker."""
    timestamp = int(now.timestamp() * 1000)
    egress_receipt = {
        "deployment_id": "rag-c-test",
        "host": item.host,
        "ip": "8.8.8.8",
        "namespace_inode": 12345,
        "nonce": "f" * 48,
        "policy_sha256": POLICY_DIGEST,
        "expires_unix": int(now.timestamp()) + 4,
        "isolation_verified": True,
    }
    egress = {
        "receipt": egress_receipt,
        "signature": private.sign(bridge._canonical(egress_receipt)).hex(),
    }
    report = {
        "v": 1,
        "policy_id": item.policy_id,
        "generation": item.generation,
        "root_id": item.root_id,
        "dispatch_id": item.dispatch_id,
        "request_hash": "b" * 64,
        "nonce": "f" * 48,
        "url": item.url,
        "host": item.host,
        "ip": "8.8.8.8",
        "pre_dial_unix_ms": timestamp,
        "reported_unix_ms": timestamp,
        "tls_verified": True,
        "peer_verified": True,
        "capture_kind": "full",
        "status": 200,
        "redirects": 0,
        "content_type": "text/html",
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "body_bytes": len(body),
        "wire_bytes": len(body),
    }
    report.update(changes)
    return {"egress": egress, "worker_fetch_report": report}


def callbacks(verifier, dsn="dbname=aearn_rag260_c_bridge_test", dispatch_owner=None):
    return bridge.make_host_callbacks(
        dsn=dsn,
        verifier=verifier,
        decision_type=Decision,
        capture_record_type=CaptureRecord,
        dispatch_owner=dispatch_owner or PostgresRegisteredSourceRepository(dsn),
        worker_image_sha256="d" * 64,  # synthetic operator pin, not a deployed image
        worker_uid=getattr(os, "geteuid", lambda: 10001)() or 10001,
        worker_gid=getattr(os, "getegid", lambda: 10001)() or 10001,
    )


def test_no_config_or_invalid_scope_never_opens_db(monkeypatch):
    _, verifier = signer()
    for dsn in ("dbname=app", "dbname=aearn_rag260_other", ""):
        with pytest.raises(ValueError, match="BRIDGE_CONFIG_DENIED"):
            callbacks(verifier, dsn)
    cb = callbacks(verifier)
    monkeypatch.setattr(
        bridge.psycopg,
        "connect",
        lambda *_a, **_kw: pytest.fail("unexpected database connection"),
    )
    now = datetime.now(timezone.utc)
    item = scope()
    assert cb.resolver(replace(Decision(1, now), max_bytes=2), now) is None
    assert cb.resolver(SimpleNamespace(**{**vars(item), "path": "/wrong"}), now) is None
    assert cb.resolver(item, datetime(2026, 9, 25)) is None
    assert cb.capture_store(item, BODY, "text/html", "0" * 64, {}, now) is None
    assert cb.proof_verifier(item, {"pre_dial": True}) is False


def test_bridge_grant_queries_exact_supplemental_dispatch(monkeypatch):
    """A terminal original row must not shadow a same-policy new dispatch."""
    _, verifier = signer()
    item = scope()
    exact = bridge._registered_scope(item)
    assert type(exact) is RegisteredSourceScope
    now = datetime.now(timezone.utc)
    until = now + timedelta(hours=1)
    owner = PostgresRegisteredSourceRepository("dbname=aearn_rag260_c_bridge_test")
    monkeypatch.setattr(
        owner, "resolve",
        lambda *_a, **_kw: RegisteredSourceHopGrant(exact, True, item.max_bytes, until),
    )
    monkeypatch.setattr(
        bridge, "_current",
        lambda *_a, **_kw: {
            "canonical_url_sha256": hashlib.sha256(URL.encode()).hexdigest(),
            "retention_until": until,
            "expires_at": until,
        },
    )

    class Connection:
        def execute(self, sql, params=None):
            if "current_database()" in sql:
                return SimpleNamespace(fetchone=lambda: {"name": "aearn_rag260_c_bridge_test"})
            assert "FROM rag_registered_fetch_attempts" in sql
            assert "WHERE id=%s AND policy_id=%s" in sql
            assert params[0] == exact.dispatch_id
            return SimpleNamespace(fetchone=lambda: {
                "id": exact.dispatch_id, "root_id": exact.root_id,
                "state": "dispatched", "request_hash": "b" * 64,
            })

    monkeypatch.setattr(bridge.psycopg, "connect", lambda *_a, **_kw: nullcontext(Connection()))
    assert callbacks(verifier, dispatch_owner=owner).resolver(item, now) == Decision(
        item.max_bytes, until,
    )


@pytest.mark.parametrize(
    "change",
    [
        {"dispatch_id": str(uuid4())},
        {"request_hash": "not-a-hash"},
        {"root_id": "other.root"},
        {"generation": 2},
        {"url": "https://www.sqlite.org/other"},
        {"ip": "127.0.0.1"},
        {"ip": "fd00::1"},
        {"status": 302},
        {"redirects": 1},
        {"tls_verified": False},
        {"peer_verified": False},
        {"body_bytes": 0},
        {"wire_bytes": 1024 * 1024 + 1},
        {"capture_kind": "prefix"},
        {"nonce": "0" * 48},
    ],
)
def test_signed_but_invalid_statement_denied(change):
    private, verifier = signer()
    item = scope()
    now = datetime.now(timezone.utc)
    assert verifier.verify(item, proof(private, item, now, **change), now=now) is None


def test_signed_predial_and_unsigned_report_are_distinct_and_peer_required(monkeypatch):
    private, verifier = signer()
    item = scope()
    now = datetime.now(timezone.utc)
    valid = proof(private, item, now)
    assert verifier.verify(item, valid, now=now) is not None
    assert verifier.verify(item, valid, now=now + timedelta(minutes=2)) is None
    assert verifier.verify(scope(), valid, now=now) is None
    assert verifier.verify(item, valid["egress"], now=now) is None
    assert verifier.verify(item, {**valid, "extra": True}, now=now) is None
    assert (
        verifier.verify(
            item,
            {**valid, "egress": {**valid["egress"], "signature": "0" * 128}},
            now=now,
        )
        is None
    )
    cb = callbacks(verifier)
    monkeypatch.setattr(
        bridge.psycopg,
        "connect",
        lambda *_a, **_kw: pytest.fail("unauthenticated report opened DB"),
    )
    digest = hashlib.sha256(BODY).hexdigest()
    # A structurally valid fake worker report never authenticates itself.
    assert cb.proof_verifier(item, valid) is True  # syntax and B signature only
    assert cb.capture_store(item, BODY, "text/html", digest, valid, now) is None
    assert (
        cb.capture_store(
            item, BODY, "text/html", digest, valid, now, peer_socket=object()
        )
        is None
    )
    assert (
        cb.capture_store(item, BODY, "text/html", digest, valid["egress"], now) is None
    )
    bad_nonce = {**valid["egress"]["receipt"], "nonce": "x" * 48}
    assert (
        verifier.verify(
            item,
            {
                "egress": {
                    "receipt": bad_nonce,
                    "signature": private.sign(bridge._canonical(bad_nonce)).hex(),
                },
                "worker_fetch_report": valid["worker_fetch_report"],
            },
            now=now,
        )
        is None
    )


@pytest.mark.parametrize(
    "change",
    [
        {"host": "docs.python.org"},
        {"ip": "9.9.9.9"},
        {"ip": "127.0.0.1"},
        {"namespace_inode": 12346},
        {"deployment_id": "another-deployment"},
        {"policy_sha256": "0" * 64},
        {"nonce": "0" * 47},
        {"expires_unix": 0},
    ],
)
def test_actual_b_predial_signed_envelope_requires_pins_and_fresh_nonce(change):
    private, verifier = signer()
    item = scope()
    now = datetime.now(timezone.utc)
    original = proof(private, item, now)["egress"]["receipt"]
    receipt = {**original, **change}
    envelope = {
        "receipt": receipt,
        "signature": private.sign(bridge._canonical(receipt)).hex(),
    }
    assert verifier.verify(item, envelope, now=now) is None


def _disposable_db():
    dsn = os.getenv("AEARN_RAG_C_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("explicit disposable C PostgreSQL URL required")
    expected = urlsplit(dsn).path.lstrip("/")
    if not expected.startswith("aearn_rag260_c_"):
        pytest.fail("refusing non-C database")
    conn = psycopg.connect(dsn, row_factory=dict_row)
    try:
        row = conn.execute("SELECT current_database() AS name").fetchone()
        if row is None or row["name"] != expected:
            pytest.fail("C database identity mismatch")
        return conn, dsn
    except BaseException:
        conn.close()
        raise


def test_pg_resolve_commit_capture_replay_and_revocation_in_rollback(monkeypatch):
    """An owned rollback transaction; no network and no persistent fixture."""
    conn, dsn = _disposable_db()
    try:
        now = datetime.now(timezone.utc)
        until = now + timedelta(hours=1)
        item = scope()
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
            "expires_at,root_id,enabled) VALUES (%s,1,%s,%s,%s,%s,'official','beginner',"
            "%s,%s,%s,%s,'Public-Domain',%s,true,%s,%s,%s,%s,true)",
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
        owner = PostgresRegisteredSourceRepository(dsn)
        private, verifier = signer()
        cb = callbacks(verifier, dsn, owner)
        monkeypatch.setattr(
            bridge.psycopg, "connect", lambda *_a, **_kw: nullcontext(conn)
        )
        exact = bridge._registered_scope(item)
        assert type(exact) is RegisteredSourceScope
        owner.take_dispatch(exact, operation_key="once." + uuid4().hex,
                            request_hash="b" * 64, now=now)
        assert cb.resolver(item, now) == Decision(item.max_bytes, until)
        assert cb.resolver(item, now) == Decision(item.max_bytes, until)
        assert cb.resolver(item, now) is None  # no third grant / second GET
        assert callbacks(verifier, dsn).resolver(item, now) is None  # crash loses permit
        evidence = proof(private, item, datetime.now(timezone.utc))
        digest = hashlib.sha256(BODY).hexdigest()
        if (
            os.name != "posix"
            or not hasattr(socket, "SO_PEERCRED")
            or os.geteuid() == 0
        ):
            pytest.skip("real non-root Unix peer required for capture")
        server_peer, worker_peer = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            assert (
                cb.capture_store(item, BODY, "text/html", digest, evidence, now) is None
            )
            assert (
                cb.capture_store(
                    item,
                    BODY,
                    "text/html",
                    "0" * 64,
                    evidence,
                    now,
                    peer_socket=server_peer,
                )
                is None
            )
            assert (
                cb.capture_store(
                    item,
                    BODY,
                    "text/html",
                    digest,
                    proof(
                        private, item, datetime.now(timezone.utc), request_hash="c" * 64
                    ),
                    now,
                    peer_socket=server_peer,
                )
                is None
            )
            captured = cb.capture_store(
                item,
                BODY,
                "text/html",
                digest,
                evidence,
                now,
                peer_socket=server_peer,
            )
            assert isinstance(captured, CaptureRecord)
            assert cb.resolver(item, now) is None
            assert (
                cb.capture_store(
                    item,
                    BODY,
                    "text/html",
                    digest,
                    evidence,
                    now,
                    peer_socket=server_peer,
                )
                is None
            )
        finally:
            server_peer.close()
            worker_peer.close()
        row = conn.execute(
            "SELECT state,response_sha256 FROM rag_registered_fetch_attempts WHERE id=%s",
            (item.dispatch_id,),
        ).fetchone()
        assert row == {"state": "settled", "response_sha256": digest}
        capture = conn.execute(
            "SELECT fetched_sha256,captured_bytes,transport_proof,transport_proof_sha256,"
            "attestor_key_sha256,worker_image_sha256 FROM rag_registered_source_captures "
            "WHERE fetch_attempt_id=%s",
            (item.dispatch_id,),
        ).fetchone()
        assert capture["fetched_sha256"] == digest and capture["captured_bytes"] == len(BODY)
        assert bytes(capture["transport_proof"]) == bridge._canonical(evidence)
        assert capture["transport_proof_sha256"] == hashlib.sha256(bridge._canonical(evidence)).hexdigest()
        assert capture["attestor_key_sha256"] == verifier._key_sha256
        assert capture["worker_image_sha256"] == "d" * 64
        conn.execute(
            "UPDATE rag_registered_source_policies SET enabled=false,revoked_at=%s "
            "WHERE policy_id=%s",
            (now, item.policy_id),
        )
        assert cb.resolver(item, now) is None
    finally:
        conn.rollback()
        conn.close()
