"""Offline synthetic pinned-proof tests; no real source/namespace acceptance."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from psycopg.rows import dict_row

from app.services.grounding.autonomous.contracts import SubjectScope
from app.services.grounding.autonomous.registered_source_bridge_host import (
    SignedDispatchProofVerifier, _canonical,
)
from app.services.grounding.autonomous.registered_source_provenance import (
    PostgresCurrentCaptureProvenanceResolver as Resolver,
)
from app.services.grounding.autonomous.source_review_repository import CompleteCapture
from app.services.grounding.autonomous.sqlite_select_quality import (
    OperatorQualityJudgment, SignedSQLiteSelectOperatorReview,
    SQLiteSelectOperatorReviewPayload, TrustedOperatorSQLiteSelectQualityVerifier,
    canonical_operator_review_payload,
)

URL = "https://www.sqlite.org/lang_select.html"
BODY = b"SQLite SELECT synthetic fixture"
IMAGE = "b" * 64


class FakeConnection:
    autocommit = False

    def __init__(self, now, row, policy, attempt, root):
        self.now, self.row, self.policy, self.attempt, self.root = (
            now, row, policy, attempt, root,
        )
        self.result = None
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append(sql)
        if "FROM rag_registered_source_captures" in sql:
            self.result = self.row
        elif "FROM rag_registered_source_policies" in sql:
            self.result = self.policy
        elif "FROM rag_registered_fetch_attempts" in sql:
            self.result = self.attempt
        elif "FROM rag_budget_authority_roots" in sql:
            self.result = self.root
        elif "clock_timestamp() AS now" in sql:
            self.result = {"now": self.now}
        elif "clock_timestamp() AS db_now" in sql:
            self.result = {"db_now": self.now}
        else:
            raise AssertionError("unexpected SQL")
        return self

    def fetchone(self):
        return self.result


def fixture():
    # Explicit synthetic test key, never loaded from deployment configuration.
    private = Ed25519PrivateKey.from_private_bytes(b"\x07" * 32)
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    verifier = SignedDispatchProofVerifier(
        public_key=public, deployment_id="test.deployment",
        policy_sha256="a" * 64, namespace_inode=123,
        allowed_ips=frozenset({"93.184.215.14"}),
    )
    now = datetime.now(timezone.utc)
    settled = now - timedelta(minutes=10)
    pre_dial = int((settled - timedelta(seconds=1)).timestamp() * 1000)
    dispatch = uuid4()
    capture_id = uuid4()
    digest = hashlib.sha256(BODY).hexdigest()
    request_hash = "c" * 64
    receipt = {
        "deployment_id": "test.deployment", "host": "www.sqlite.org",
        "ip": "93.184.215.14", "namespace_inode": 123,
        "nonce": "d" * 48, "policy_sha256": "a" * 64,
        "expires_unix": pre_dial // 1000 + 3, "isolation_verified": True,
    }
    report = {
        "v": 1, "policy_id": "test.policy", "generation": 1,
        "root_id": "test.root", "dispatch_id": str(dispatch),
        "request_hash": request_hash, "url": URL, "host": "www.sqlite.org",
        "ip": receipt["ip"], "nonce": receipt["nonce"], "status": 200,
        "redirects": 0, "tls_verified": True, "peer_verified": True,
        "capture_kind": "full", "content_type": "text/html",
        "body_sha256": digest, "body_bytes": len(BODY),
        "wire_bytes": len(BODY), "pre_dial_unix_ms": pre_dial,
        "reported_unix_ms": pre_dial + 500,
    }
    proof = {
        "egress": {"receipt": receipt, "signature": private.sign(_canonical(receipt)).hex()},
        "worker_fetch_report": report,
    }
    proof_bytes = _canonical(proof)
    policy = {
        "policy_id": "test.policy", "generation": 1,
        "source_handle": "sqlite.test", "subject_id": "route.sql",
        "subject_version": "v1", "facets": ["queries"],
        "canonical_url": URL, "canonical_url_sha256": hashlib.sha256(URL.encode()).hexdigest(),
        "host": "www.sqlite.org", "path": "/lang_select.html",
        "root_id": "test.root", "max_captured_bytes": 1048576,
        "enabled": True, "revoked_at": None, "license_id": "Public-Domain",
        "allowed_usages": ["main_teaching"], "immutable_history_allowed": True,
        "retention_until": now + timedelta(hours=1),
        "expires_at": now + timedelta(hours=1), "origin": "official",
        "reading_level": "beginner",
    }
    root = {
        "enabled": True, "delegation_expires_at": now + timedelta(hours=1),
        "period_start": now - timedelta(hours=1),
        "period_end": now + timedelta(hours=1),
        "policy_id": policy["policy_id"], "policy_generation": 1,
    }
    attempt = {
        "id": dispatch, "policy_id": policy["policy_id"], "generation": 1,
        "canonical_url_sha256": policy["canonical_url_sha256"],
        "root_id": policy["root_id"], "state": "settled",
        "response_sha256": digest, "response_bytes": len(BODY),
        "request_hash": request_hash, "settled_at": settled,
        "dispatched_at": settled - timedelta(seconds=2),
    }
    row = {
        "id": capture_id, "policy_id": policy["policy_id"], "generation": 1,
        "fetch_attempt_id": dispatch, "captured_body": BODY,
        "captured_bytes": len(BODY), "fetched_sha256": digest,
        "request_chain": [URL], "final_url": URL,
        "content_type": "text/html", "license_id": policy["license_id"],
        "retention_until": policy["retention_until"],
        "cleared_at": None, "evidence_level": "live_egress_attested",
        "transport_proof": proof_bytes,
        "transport_proof_sha256": hashlib.sha256(proof_bytes).hexdigest(),
        "attestor_key_sha256": hashlib.sha256(public).hexdigest(),
        "worker_image_sha256": IMAGE,
    }
    capture = CompleteCapture(
        capture_id, "registered", BODY, digest, digest,
        SubjectScope(subject_id="route.sql", subject_version="v1", facets=("queries",)),
        policy["source_handle"], URL, (URL,), policy["origin"],
        policy["reading_level"], policy["license_id"],
    )
    return FakeConnection(now, row, policy, attempt, root), verifier, capture, proof


def test_historical_signed_proof_is_valid_only_under_current_grants():
    conn, verifier, capture, _ = fixture()
    resolver = Resolver(conn, verifier=verifier, worker_image_sha256=IMAGE)
    assert resolver.resolve(capture) == conn.row["transport_proof_sha256"]
    assert any("FOR SHARE" in sql for sql in conn.statements)
    assert not any("COMMIT" in sql or "INSERT" in sql for sql in conn.statements)
    conn.policy["enabled"] = False
    assert resolver.resolve(capture) is None


@pytest.mark.parametrize("where,field,value", [
    ("row", "transport_proof", None),
    ("row", "transport_proof_sha256", None),
    ("row", "attestor_key_sha256", "0" * 64),
    ("row", "worker_image_sha256", "0" * 64),
    ("row", "cleared_at", datetime.now(timezone.utc)),
    ("row", "content_type", "text/plain"),
    ("row", "license_id", "Unknown"),
    ("row", "request_chain", ["https://www.sqlite.org/other"]),
    ("attempt", "state", "unknown"),
    ("attempt", "request_hash", "f" * 64),
    ("attempt", "response_bytes", 1),
    ("policy", "subject_version", "v2"),
    ("policy", "facets", ["schema"]),
    ("policy", "root_id", "other.root"),
    ("root", "enabled", False),
])
def test_mismatched_current_fact_denied(where, field, value):
    conn, verifier, capture, _ = fixture()
    getattr(conn, where)[field] = value
    assert Resolver(conn, verifier=verifier, worker_image_sha256=IMAGE).resolve(capture) is None


def test_signed_report_and_canonical_proof_are_both_required():
    conn, verifier, capture, proof = fixture()
    altered = copy.deepcopy(proof)
    altered["egress"]["receipt"]["nonce"] = "e" * 48
    conn.row["transport_proof"] = _canonical(altered)
    conn.row["transport_proof_sha256"] = hashlib.sha256(conn.row["transport_proof"]).hexdigest()
    assert Resolver(conn, verifier=verifier, worker_image_sha256=IMAGE).resolve(capture) is None
    conn, verifier, capture, proof = fixture()
    noncanonical = json.dumps(proof).encode()
    conn.row["transport_proof"] = noncanonical
    conn.row["transport_proof_sha256"] = hashlib.sha256(noncanonical).hexdigest()
    assert Resolver(conn, verifier=verifier, worker_image_sha256=IMAGE).resolve(capture) is None


def test_capture_body_scope_and_dispatch_order_denied():
    conn, verifier, capture, _ = fixture()
    resolver = Resolver(conn, verifier=verifier, worker_image_sha256=IMAGE)
    assert resolver.resolve(replace(capture, body=b"invented")) is None
    assert resolver.resolve(replace(capture, revision="other")) is None
    assert resolver.resolve(replace(capture, lane="candidate")) is None
    conn.attempt["dispatched_at"] = conn.attempt["settled_at"]
    assert resolver.resolve(capture) is None


def test_external_configuration_and_transaction_required():
    conn, verifier, capture, _ = fixture()
    with pytest.raises(ValueError, match="PROVENANCE_CONFIG_DENIED"):
        Resolver(conn, verifier=None, worker_image_sha256=IMAGE)
    with pytest.raises(ValueError, match="PROVENANCE_CONFIG_DENIED"):
        Resolver(conn, verifier=verifier, worker_image_sha256="invalid")
    conn.autocommit = True
    assert Resolver(conn, verifier=verifier, worker_image_sha256=IMAGE).resolve(capture) is None


def test_pg_requires_explicit_disposable_c_database_and_rolls_back():
    dsn = os.getenv("AEARN_RAG_C_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("C PostgreSQL not executed: explicit disposable DSN required")
    expected = urlsplit(dsn).path.lstrip("/")
    if not expected.startswith("aearn_rag260_c_"):
        pytest.fail("refusing non-C disposable database")
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        identity = conn.execute("SELECT current_database() AS name").fetchone()
        if identity is None or identity["name"] != expected:
            pytest.fail("disposable database identity mismatch")
        conn.rollback()
        # Missing capture is denied without implicit fixture writes or commit.
        fake, verifier, capture, _ = fixture()
        assert Resolver(conn, verifier=verifier, worker_image_sha256=IMAGE).resolve(capture) is None
        conn.rollback()


def test_pg_signed_capture_current_grants_then_revocation_rollback():
    """Optional real SQL integration, entirely inside an explicit C DB rollback."""
    dsn = os.getenv("AEARN_RAG_C_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("C PostgreSQL not executed: explicit disposable DSN required")
    expected = urlsplit(dsn).path.lstrip("/")
    if not expected.startswith("aearn_rag260_c_"):
        pytest.fail("refusing non-C disposable database")
    from psycopg.types.json import Jsonb

    sample, verifier, capture, _ = fixture()
    suffix = uuid4().hex
    policy = sample.policy
    policy["policy_id"] = "test." + suffix
    policy["source_handle"] = "sqlite." + suffix
    policy["root_id"] = "root." + suffix
    report = json.loads(sample.row["transport_proof"])
    report["worker_fetch_report"]["policy_id"] = policy["policy_id"]
    report["worker_fetch_report"]["root_id"] = policy["root_id"]
    proof_bytes = _canonical(report)
    proof_hash = hashlib.sha256(proof_bytes).hexdigest()
    capture = replace(capture, source_handle=policy["source_handle"])
    try:
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            identity = conn.execute("SELECT current_database() AS name").fetchone()
            if identity is None or identity["name"] != expected:
                pytest.fail("disposable database identity mismatch")
            schema = conn.execute(
                "SELECT to_regclass('rag_registered_source_captures') AS name"
            ).fetchone()
            if schema is None or schema["name"] is None:
                pytest.fail("pre-applied C schema required")
            conn.execute(
                "INSERT INTO rag_budget_authority_roots "
                "(root_id,delegation_id,delegation_generation,delegation_expires_at,"
                "policy_id,policy_generation,period_key,period_start,period_end,cap_units,enabled) "
                "VALUES (%s,%s,1,%s,%s,1,%s,%s,%s,1,true)",
                (policy["root_id"], "delegation." + suffix,
                 policy["expires_at"], policy["policy_id"], "period." + suffix,
                 sample.root["period_start"], policy["expires_at"]),
            )
            conn.execute(
                "INSERT INTO rag_registered_source_policies "
                "(policy_id,generation,source_handle,subject_id,subject_version,facets,"
                "origin,reading_level,canonical_url,canonical_url_sha256,host,path,license_id,"
                "allowed_usages,immutable_history_allowed,max_captured_bytes,retention_until,"
                "expires_at,root_id,enabled) "
                "VALUES (%s,1,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true,%s,%s,%s,%s,true)",
                (policy["policy_id"], policy["source_handle"], policy["subject_id"],
                 policy["subject_version"], policy["facets"], policy["origin"],
                 policy["reading_level"], URL, policy["canonical_url_sha256"],
                 policy["host"], policy["path"], policy["license_id"],
                 policy["allowed_usages"], policy["max_captured_bytes"],
                 policy["retention_until"], policy["expires_at"], policy["root_id"]),
            )
            attempt = sample.attempt
            conn.execute(
                "INSERT INTO rag_registered_fetch_attempts "
                "(id,policy_id,generation,canonical_url_sha256,root_id,operation_key,"
                "request_hash,dispatched_at) VALUES (%s,%s,1,%s,%s,%s,%s,%s)",
                (attempt["id"], policy["policy_id"], policy["canonical_url_sha256"],
                 policy["root_id"], "attempt." + suffix, attempt["request_hash"],
                 attempt["dispatched_at"]),
            )
            conn.execute(
                "UPDATE rag_registered_fetch_attempts SET state='settled',response_sha256=%s,"
                "response_bytes=%s,settled_at=%s WHERE id=%s",
                (capture.digest, len(BODY), attempt["settled_at"], attempt["id"]),
            )
            conn.execute(
                "INSERT INTO rag_registered_source_captures "
                "(id,fetch_attempt_id,policy_id,generation,request_chain,final_url,content_type,"
                "fetched_sha256,captured_bytes,captured_body,license_id,retention_until,"
                "transport_proof,transport_proof_sha256,attestor_key_sha256,worker_image_sha256) "
                "VALUES (%s,%s,%s,1,%s,%s,'text/html',%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (capture.capture_id, attempt["id"], policy["policy_id"], Jsonb([URL]),
                 URL, capture.digest, len(BODY), BODY, policy["license_id"],
                 policy["retention_until"], proof_bytes, proof_hash,
                 sample.row["attestor_key_sha256"], IMAGE),
            )
            resolver = Resolver(conn, verifier=verifier, worker_image_sha256=IMAGE)
            assert resolver.resolve(capture) == proof_hash
            # Synthetic reviewer key and judgment exercise wiring, not an
            # actual review of SQLite's page or independent technical truth.
            reviewer = Ed25519PrivateKey.from_private_bytes(b"\x09" * 32)
            reviewer_public = reviewer.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw,
            )
            payload = SQLiteSelectOperatorReviewPayload(
                format="aearn.sqlite-select.operator-review.v1",
                capture_id=capture.capture_id, lane="registered",
                source_handle=capture.source_handle, scope=capture.scope,
                revision=capture.revision, body_sha256=capture.digest,
                body_bytes=len(capture.body), final_url=URL,
                request_chain=(URL,), origin=capture.origin,
                reading_level=capture.reading_level, license_id=capture.license_id,
                provenance_digest=proof_hash,
                judgment=OperatorQualityJudgment(
                    version_fit="current", reading_fit="suitable",
                    technical_status="correct", conflict_status="resolved",
                    known_error="absent", covered_facets=("queries",),
                    lineage_family="sqlite.synthetic",
                ),
                reviewed_at=datetime.now(timezone.utc) - timedelta(seconds=1),
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            review = SignedSQLiteSelectOperatorReview(
                reviewer_key_id="test.reviewer", payload=payload,
                signature_hex=reviewer.sign(canonical_operator_review_payload(payload)).hex(),
            )
            quality = TrustedOperatorSQLiteSelectQualityVerifier(
                review=review, reviewer_key_id="test.reviewer",
                reviewer_public_key=reviewer_public, provenance=resolver,
                enabled=True,
            )
            assert quality.audit(capture).code == "OPERATOR_REVIEWED"
            conn.execute(
                "UPDATE rag_registered_source_policies SET enabled=false WHERE policy_id=%s",
                (policy["policy_id"],),
            )
            assert resolver.resolve(capture) is None
            assert quality.audit(capture).code == "INDEPENDENT_AUTHORITY_MISSING"
            conn.rollback()
    except psycopg.Error:
        # Fail rather than silently treating schema/fixture failure as a skip.
        raise
