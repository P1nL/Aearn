"""Offline signature/proof tests; not a namespace or live-network acceptance."""
from __future__ import annotations

import json
import stat
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.services.grounding.autonomous import live_egress, pinned_tls_connector, public_dns
from app.services.grounding.autonomous.live_egress import (
    LiveEgressAttestor, VerifiedEgressEnvelope,
)
from app.services.grounding.autonomous.registered_source_policy import (
    RegisteredSourceHopGrant, RegisteredSourceHopPolicy, RegisteredSourceScope,
)
from app.services.grounding.autonomous.safe_fetch import (
    FetchLimits, PinnedResponse, SafeFetchDenied, SafeFetcher,
)

URL = "https://example.org/lesson"
IP = "93.184.215.14"


def signed_socket(monkeypatch, tmp_path, *, mutate=None):
    """Fake Unix transport with real Ed25519, not a real privileged signer."""
    private = Ed25519PrivateKey.generate()
    key = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    path = tmp_path / "attestor.sock"
    fake_os = SimpleNamespace(
        name="posix", geteuid=lambda: 1000, getegid=lambda: 2000,
        getgroups=lambda: [2000],
        lstat=lambda target: (
            SimpleNamespace(st_mode=stat.S_IFSOCK | 0o660, st_uid=0, st_gid=2000)
            if target == path else
            SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0, st_gid=0)
        ),
        stat=lambda _: SimpleNamespace(st_ino=123),
    )
    monkeypatch.setattr(live_egress, "os", fake_os)
    seen = {"requests": []}

    class Writer:
        def write(self, data):
            seen["requests"].append(json.loads(data))

        async def drain(self):
            pass

        def close(self):
            pass

        async def wait_closed(self):
            pass

    class Reader:
        async def readline(self):
            receipt = dict(seen["requests"][-1], expires_unix=int(time.time()) + 5,
                           isolation_verified=True)
            signature = private.sign(live_egress._canonical(receipt)).hex()
            if mutate is not None:
                receipt, signature = mutate(receipt, signature)
            return json.dumps({"receipt": receipt, "signature": signature}).encode() + b"\n"

    async def open_socket(_):
        return Reader(), Writer()

    monkeypatch.setattr(live_egress.asyncio, "open_unix_connection", open_socket, raising=False)
    attestor = LiveEgressAttestor(
        socket_path=path, public_key=key, deployment_id="reviewed",
        policy_sha256="a" * 64, trusted_gid=2000,
    )
    return attestor, private.public_key(), seen


@pytest.mark.asyncio
async def test_verified_envelope_exact_canonical_signature_and_fresh_challenge(monkeypatch, tmp_path):
    attestor, key, seen = signed_socket(monkeypatch, tmp_path)
    proof = await attestor.attest_envelope(host="example.org", ip=IP)
    assert type(proof) is VerifiedEgressEnvelope
    receipt = proof.as_envelope()["receipt"]
    assert receipt == seen["requests"][0] | {
        "expires_unix": receipt["expires_unix"], "isolation_verified": True,
    }
    assert receipt["namespace_inode"] == 123
    assert receipt["policy_sha256"] == "a" * 64
    assert receipt["host"] == "example.org" and receipt["ip"] == IP
    assert len(receipt["nonce"]) == 48
    assert proof.canonical_receipt == live_egress._canonical(receipt)
    key.verify(bytes.fromhex(proof.signature_hex), proof.canonical_receipt)
    # The legacy B API remains boolean and issues a *new* signed challenge.
    assert await attestor.attest(host="example.org", ip=IP) is True
    assert len(seen["requests"]) == 2
    assert seen["requests"][1]["nonce"] != receipt["nonce"]


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("host", "other.org"), ("ip", "8.8.8.8"), ("namespace_inode", 456),
    ("policy_sha256", "b" * 64), ("nonce", "0" * 48),
    ("expires_unix", 0), ("isolation_verified", False),
    ("signature", "0" * 128),
])
async def test_modified_or_expired_signed_proof_closes(monkeypatch, tmp_path, field, value):
    def tamper(receipt, signature):
        if field == "signature":
            return receipt, value
        receipt[field] = value
        return receipt, signature

    attestor, _, _ = signed_socket(monkeypatch, tmp_path, mutate=tamper)
    with pytest.raises(SafeFetchDenied, match="EGRESS_UNVERIFIED"):
        await attestor.attest_envelope(host="example.org", ip=IP)


class Resolver:
    def __init__(self):
        self.calls = 0

    async def resolve(self, host):
        self.calls += 1
        return (IP,)


class Connector:
    def __init__(self):
        self.calls = 0

    async def open(self, *, host, ip, url, deadline, headers, method="GET"):
        self.calls += 1

        async def body():
            yield b"lesson"

        return PinnedResponse(
            200, {"content-type": "text/html"}, body(), IP, IP, host, True,
            sent_headers={"accept": "text/html, text/plain, text/markdown"},
            method=method,
        )

    async def close(self, response):
        pass


class CurrentGrant:
    def resolve(self, scope, *, now):
        return RegisteredSourceHopGrant(
            scope, True, scope.max_bytes, now + timedelta(minutes=1),
        )


def registered_fetcher(monkeypatch, attestor):
    # Only DNS/TLS adapters are test doubles; the signed attestor class is real.
    monkeypatch.setattr(public_dns, "PublicDnsResolver", Resolver)
    monkeypatch.setattr(pinned_tls_connector, "PinnedTlsConnector", Connector)
    scope = RegisteredSourceScope(
        policy_id="policy-001", generation=1, source_handle="sqlite-docs",
        subject_id="route.sql", subject_version="1", facets=("queries",),
        url=URL, host="example.org", path="/lesson", root_id="root-001",
        dispatch_id=uuid4(),
    )
    resolver, connector = Resolver(), Connector()
    fetcher = SafeFetcher(
        resolver=resolver, connector=connector, egress=attestor,
        hop_policy=RegisteredSourceHopPolicy(scope, CurrentGrant(),
                                             lambda: datetime.now(timezone.utc)),
        limits=FetchLimits(redirects=0),
    )
    return fetcher, resolver, connector


@pytest.mark.asyncio
async def test_registered_full_fetch_exposes_only_concrete_signed_proof(monkeypatch, tmp_path):
    attestor, key, seen = signed_socket(monkeypatch, tmp_path)
    fetcher, resolver, connector = registered_fetcher(monkeypatch, attestor)
    assert fetcher.live_ready
    result = await fetcher.fetch(URL)
    assert result.body == b"lesson" and result.sha256 == sha256(b"lesson").hexdigest()
    assert result.egress_proof is not None
    key.verify(bytes.fromhex(result.egress_proof.signature_hex),
               result.egress_proof.canonical_receipt)
    assert result.egress_proof.as_envelope()["receipt"]["host"] == "example.org"
    assert len(seen["requests"]) == resolver.calls == connector.calls == 1
    assert result.evidence_level == "live_egress_attested"
    assert "egress_proof" not in repr(result)


@pytest.mark.asyncio
async def test_invalid_proof_denies_before_connection(monkeypatch, tmp_path):
    attestor, _, _ = signed_socket(
        monkeypatch, tmp_path, mutate=lambda receipt, _: (receipt, "0" * 128),
    )
    fetcher, resolver, connector = registered_fetcher(monkeypatch, attestor)
    with pytest.raises(SafeFetchDenied, match="EGRESS_UNVERIFIED"):
        await fetcher.fetch(URL)
    assert resolver.calls == 1 and connector.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("changes,code", [
    ({"connected_ip": "8.8.8.8"}, "CONNECTION_DENIED"),
    ({"peer_ip": "8.8.8.8"}, "CONNECTION_DENIED"),
    ({"tls_hostname": "other.org"}, "CONNECTION_DENIED"),
    ({"tls_verified": False}, "CONNECTION_DENIED"),
    ({"status": 302, "headers": {"location": "/other"}}, "REDIRECT_DENIED"),
])
async def test_same_pre_dial_proof_never_escapes_wrong_peer_or_redirect(
    monkeypatch, tmp_path, changes, code,
):
    attestor, _, seen = signed_socket(monkeypatch, tmp_path)
    fetcher, resolver, connector = registered_fetcher(monkeypatch, attestor)
    open_original = Connector.open

    async def changed_open(self, **kwargs):
        return replace(await open_original(self, **kwargs), **changes)

    monkeypatch.setattr(Connector, "open", changed_open)
    with pytest.raises(SafeFetchDenied, match=code):
        await fetcher.fetch(URL)
    # The signed proof was requested pre-dial once, but is not returned for a
    # wrong connected/peer host or a redirect, and no second request is made.
    assert len(seen["requests"]) == resolver.calls == connector.calls == 1


@pytest.mark.asyncio
async def test_structural_fake_cannot_supply_a_live_proof(monkeypatch, tmp_path):
    attestor, _, _ = signed_socket(monkeypatch, tmp_path)
    fetcher, resolver, connector = registered_fetcher(monkeypatch, attestor)

    class FakeEgress:
        async def attest(self, *, host, ip):
            return True

        async def attest_envelope(self, *, host, ip):
            return VerifiedEgressEnvelope(b"{}", "0" * 128)

    fetcher.egress = FakeEgress()
    assert not fetcher.live_ready
    with pytest.raises(SafeFetchDenied, match="LIVE_EGRESS_UNVERIFIED"):
        await fetcher.fetch(URL)
    assert resolver.calls == connector.calls == 0

@pytest.mark.asyncio
async def test_registered_proof_expiring_during_second_grant_denies_before_dial(monkeypatch, tmp_path):
    from app.services.grounding.autonomous import safe_fetch

    attestor, _, _ = signed_socket(monkeypatch, tmp_path)
    fetcher, _, connector = registered_fetcher(monkeypatch, attestor)
    after_expiry = time.time_ns() + 20_000_000_000
    monkeypatch.setattr(safe_fetch.time, "time_ns", lambda: after_expiry)
    with pytest.raises(SafeFetchDenied, match="EGRESS_UNVERIFIED"):
        await fetcher.fetch(URL)
    assert connector.calls == 0
