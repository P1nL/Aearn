"""Pure owner wiring only: no live DB, HTTP, Unix peer, namespace or TLS proof."""
from __future__ import annotations

import asyncio
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.services.grounding.autonomous import registered_source_bridge_host as host
from app.services.grounding.autonomous.registered_source_policy import RegisteredSourceHopGrant, RegisteredSourceScope
from app.services.grounding.autonomous.registered_source_repository import PostgresRegisteredSourceRepository

INFRA = Path(__file__).resolve().parents[4] / "infra"
sys.path[:0] = [str(INFRA / "rag-c-live"), str(INFRA / "rag-c-source-control")]
import control_runtime as control  # noqa: E402
from protocol import Scope  # noqa: E402
import worker_once as worker  # noqa: E402


def scope(*, python=True) -> Scope:
    return Scope.from_wire({
        "policy_id": "source.p6.python.assessment" if python else "source.p6.sqlite.assessment", "generation": 1,
        "source_handle": "source.official.test", "subject_id": "route.python" if python else "route.sql",
        "subject_version": "test-v1", "facets": ["fundamentals"] if python else ["queries"],
        "url": "https://docs.python.org/3/library/functions.html" if python else worker.URL,
        "host": "docs.python.org" if python else worker.HOST,
        "path": "/3/library/functions.html" if python else "/lang_select.html",
        "root_id": "source.test-root", "dispatch_id": str(uuid4()), "max_bytes": 1024 * 1024,
    })


def verifier():
    key = Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return key, host.SignedDispatchProofVerifier(public_key=key, deployment_id="source-test-v1", policy_sha256="a" * 64,
        namespace_inode=1234, allowed_ips=frozenset({"8.8.8.8"}))


def callback(item, *, owned=True, database=host.OWNED_B1D_DATABASE):
    _, signature = verifier()
    dsn = "dbname=" + database
    owner = PostgresRegisteredSourceRepository(dsn)
    cb = host.make_host_callbacks(dsn=dsn, verifier=signature, decision_type=lambda n, end: (n, end),
        capture_record_type=lambda value: value, worker_uid=10001, worker_gid=10001,
        dispatch_owner=owner, worker_image_sha256="d" * 64, owned_b1d_assessment=owned)
    return cb, owner, host._registered_scope(item)


def control_config(item, tmp_path, *, database=host.OWNED_B1D_DATABASE, owned=True):
    key, _ = verifier()
    config = {"approved": True, "database_name": database, "dsn_secret_path": str(tmp_path / "dsn"),
        "directory": str(tmp_path / "socket"), "arm_path": str(tmp_path / "arm.json"), "scope": item.wire(),
        "b_attestor": {"public_key_hex": key.hex(), "public_key_sha256": hashlib.sha256(key).hexdigest(),
            "deployment_id": "source-test-v1", "policy_sha256": "a" * 64, "namespace_inode": 1234, "allowed_ips": ["8.8.8.8"]},
        "worker_uid": 10001, "worker_gid": 10001, "trusted_gid": 10002,
        "worker_image_sha256": "d" * 64, "deployment_id": "control-test-v1"}
    if owned:
        config["owned_b1d_assessment"] = True
    return config


def test_control_and_callback_opt_in_is_exact_default_off(monkeypatch, tmp_path):
    monkeypatch.setattr(host.psycopg, "connect", lambda *a, **kw: pytest.fail("pure tests must never connect"))
    for python in (True, False):
        item = scope(python=python)
        cfg = control_config(item, tmp_path)
        instance = control.ControlRuntime(cfg, "dbname=" + host.OWNED_B1D_DATABASE)
        assert instance.scope == item
        with pytest.raises(ValueError, match="DATABASE_DENIED"):
            control.ControlRuntime({k: v for k, v in cfg.items() if k != "owned_b1d_assessment"}, "dbname=" + host.OWNED_B1D_DATABASE)
    legacy = control_config(scope(python=False), tmp_path, database="aearn_rag260_c_legacy", owned=False)
    assert control.ControlRuntime(legacy, "dbname=aearn_rag260_c_legacy").scope.subject_id == "route.sql"
    with pytest.raises(ValueError, match="SCOPE_DENIED"):
        control.ControlRuntime({**legacy, "scope": scope().wire()}, "dbname=aearn_rag260_c_legacy")
    for database in ("postgres", host.OWNED_B1D_DATABASE + "_other", "aearn_rag260_c_legacy"):
        assert not host.transport_database_allowed(database, owned_b1d_assessment=True)
    with pytest.raises(ValueError, match="BRIDGE_CONFIG_DENIED"):
        callback(scope(), owned=False)


def test_worker_config_opt_in_preserves_exact_targets_and_strict_fields(monkeypatch):
    config = {field: None for field in worker.FIELDS}
    config.update(enabled=True, scope=scope().wire(), owned_b1d_assessment=True, deadline_seconds=90)
    monkeypatch.setattr(worker, "_root_file", lambda path: json.dumps(config).encode())
    assert worker.load_config()["owned_b1d_assessment"] is True
    for python in (True, False):
        item = scope(python=python)
        assert worker._scope_allowed(config, item)
        assert host.owned_b1d_scope_allowed(host._registered_scope(item))
    assert not worker._scope_allowed({}, scope())
    canonical = Scope.from_wire({**scope().wire(), "url": "https://docs.python.org/3/builtins/functions.html",
                                 "path": "/3/builtins/functions.html"})
    assert worker._scope_allowed(config, canonical)
    assert host.owned_b1d_scope_allowed(host._registered_scope(canonical))
    assert not worker._scope_allowed({}, canonical)
    assert worker._scope_allowed({}, scope(python=False))
    invalid = Scope.from_wire({**scope().wire(), "facets": ["queries"]})
    assert not worker._scope_allowed(config, invalid)
    assert not host.owned_b1d_scope_allowed(host._registered_scope(invalid))
    config["owned_b1d_assessment"] = 1
    with pytest.raises(worker.WorkerDenied):
        worker.load_config()


def test_owned_pinned_dns_intersection_is_stable_and_legacy_unchanged(monkeypatch):
    from app.services.grounding.autonomous.public_dns import PublicDnsResolver
    from app.services.grounding.autonomous.safe_fetch import SafeFetchDenied

    async def check():
        # Only synthetic getaddrinfo rows: no DNS request or transport occurs.
        answers = ["8.8.4.4", "1.1.1.1", "8.8.8.8"]
        async def getaddrinfo(*args, **kwargs):
            return [(2, 1, 6, "", (ip, 443)) for ip in answers]
        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", getaddrinfo)
        config = {"owned_b1d_assessment": True, "allowed_ips": ["8.8.8.8", "1.1.1.1"]}
        resolver = worker._capture_resolver(config, PublicDnsResolver)
        assert type(resolver) is PublicDnsResolver
        assert await resolver.resolve("docs.python.org") == ("8.8.8.8", "1.1.1.1")
        answers.reverse()
        assert await resolver.resolve("docs.python.org") == ("8.8.8.8", "1.1.1.1")
        delegate = worker._capture_resolver({}, PublicDnsResolver)
        assert type(delegate) is PublicDnsResolver
        assert await delegate.resolve("docs.python.org") == tuple(answers)
        assert await PublicDnsResolver().resolve("docs.python.org") == tuple(answers)
        answers[:] = ["9.9.9.9"]
        with pytest.raises(SafeFetchDenied) as empty:
            await resolver.resolve("docs.python.org")
        assert empty.value.code == "ADDRESS_DENIED"
        # A pinned public answer cannot conceal a private answer in the same RRset.
        answers[:] = ["8.8.8.8", "127.0.0.1"]
        with pytest.raises(SafeFetchDenied):
            await resolver.resolve("docs.python.org")
    asyncio.run(check())


def test_owned_grants_use_current_policy_and_exact_database(monkeypatch):
    item = scope()
    cb, owner, domain = callback(item)
    now = datetime.now(timezone.utc)
    until = now + timedelta(minutes=5)
    calls = []
    monkeypatch.setattr(owner, "resolve", lambda value, **kw: calls.append(value) or RegisteredSourceHopGrant(domain, True, item.max_bytes, until))
    policy = {"origin": "official", "allowed_usages": ["assessment_evidence"],
        "canonical_url_sha256": hashlib.sha256(item.url.encode()).hexdigest(), "retention_until": until, "expires_at": until}
    monkeypatch.setattr(host, "_current", lambda *a, **kw: policy)
    class Connection:
        def execute(self, sql, args=None):
            if "current_database()" in sql:
                return SimpleNamespace(fetchone=lambda: {"name": host.OWNED_B1D_DATABASE})
            assert args[0] == domain.dispatch_id and "WHERE id=%s AND policy_id=%s" in sql
            return SimpleNamespace(fetchone=lambda: {"id": domain.dispatch_id, "root_id": domain.root_id,
                "state": "dispatched", "request_hash": "b" * 64})
    monkeypatch.setattr(host.psycopg, "connect", lambda *a, **kw: nullcontext(Connection()))
    assert cb.resolver(item, now) == (item.max_bytes, until)
    wrong = Scope.from_wire({**item.wire(), "subject_id": "route.sql"})
    assert cb.resolver(wrong, now) is None and len(calls) == 1
    policy["allowed_usages"] = ["supplementary"]
    assert cb.resolver(item, now) is None
    assert cb.capture_store(item, b"unit", "text/html", hashlib.sha256(b"unit").hexdigest(), {}, now) is None


def test_owned_policy_is_rechecked_after_attempt_lock(monkeypatch):
    item = scope(python=False)
    cb, owner, domain = callback(item)
    now = datetime.now(timezone.utc)
    until = now + timedelta(minutes=5)
    monkeypatch.setattr(owner, "resolve", lambda *a, **kw: RegisteredSourceHopGrant(domain, True, item.max_bytes, until))
    policy = {"origin": "official", "allowed_usages": ["assessment_evidence"],
        "canonical_url_sha256": hashlib.sha256(item.url.encode()).hexdigest(), "retention_until": until, "expires_at": until}
    checks = iter((policy, {**policy, "allowed_usages": ["main_teaching"]}))
    monkeypatch.setattr(host, "_current", lambda *a, **kw: next(checks))
    class Connection:
        def execute(self, sql, args=None):
            value = {"name": host.OWNED_B1D_DATABASE} if "current_database()" in sql else {
                "id": domain.dispatch_id, "root_id": domain.root_id, "state": "dispatched", "request_hash": "b" * 64}
            return SimpleNamespace(fetchone=lambda: value)
    monkeypatch.setattr(host.psycopg, "connect", lambda *a, **kw: nullcontext(Connection()))
    assert cb.resolver(item, now) is None


def test_python_worker_reaches_two_grants_report_and_settlement_with_inert_ports(monkeypatch):
    # Every IO port below is a unit stand-in; this cannot prove TLS or SO_PEERCRED.
    item = scope()
    config = {"enabled": True, "owned_b1d_assessment": True, "scope": item.wire(), "deadline_seconds": 90,
        "c_socket": "/run/source/bridge.sock", "c_public_key_path": "/run/source/public.key", "c_public_key_sha256": "a" * 64,
        "c_trusted_gid": 10002, "c_deployment_id": "source-test-v1", "b_socket": "/run/source/attest.sock",
        "b_deployment_id": "source-test-v1", "b_policy_sha256": "a" * 64, "b_trusted_gid": 10003,
        "allowed_ips": ["8.8.8.8"], "request_hash": "b" * 64}
    records = []
    class Client:
        def __init__(self, **kw):
            pass
        def grant(self, target):
            records.append("grant")
            assert target == item
            return {"expires_unix": int(datetime.now(timezone.utc).timestamp()) + 4, "max_bytes": item.max_bytes}, "c" * 48
        def complete(self, target, **kw):
            records.append("settled")
            assert target == item and kw["grant_nonce"] == "c" * 48
            assert kw["attestor_proof"]["worker_fetch_report"]["host"] == "docs.python.org"
            return {"capture_id": "unit-capture-no-live-proof"}
    class Port:
        def __init__(self, *args, **kw):
            self.args, self.kw = args, kw
    class Proof:
        def __init__(self):
            self.canonical_receipt = json.dumps({"host": item.host, "ip": "8.8.8.8", "nonce": "e" * 48,
                "expires_unix": int(datetime.now(timezone.utc).timestamp()) + 4})
        def as_envelope(self):
            return {"unit_only": True}
    class Result:
        pass
    class Fetcher(Port):
        live_ready = True  # Unit-only interface fixture, never live evidence.
        async def fetch(self, url, *, capture_kind):
            records.append("fetch-port")
            assert url == item.url and capture_kind == "full"
            hop = self.kw["hop_policy"]
            for _ in range(2):
                assert hop.kw["resolver"].resolve(hop.args[0], now=datetime.now(timezone.utc)) is not None
            value = Result()
            value.egress_proof = Proof()
            value.evidence_level, value.capture_kind = "live_egress_attested", "full"
            value.final_url, value.hops, value.content_type, value.body = item.url, (item.url,), "text/html", b"unit HTML"
            value.expanded_bytes = value.compressed_bytes = len(value.body)
            value.sha256 = hashlib.sha256(value.body).hexdigest()
            value.pre_dial_unix_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            return value
    monkeypatch.setattr(worker, "_identity", lambda c: None)
    monkeypatch.setattr(worker, "_pins", lambda c: (b"unit-key", "d" * 64))
    monkeypatch.setattr(worker, "_ports", lambda: (Port, Proof, Port, Port, RegisteredSourceHopGrant, Port,
        RegisteredSourceScope, Port, Result, Fetcher, Client, Scope))
    assert asyncio.run(worker.run_once(config)) == "unit-capture-no-live-proof"
    assert records == ["fetch-port", "grant", "grant", "settled"]
