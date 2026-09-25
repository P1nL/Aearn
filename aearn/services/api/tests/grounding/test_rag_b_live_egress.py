"""Offline unit tests for signed egress protocol; never a deployment proof."""
from __future__ import annotations

import json
import stat
import time
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.services.grounding.autonomous import live_egress
from app.services.grounding.autonomous.live_egress import LiveEgressAttestor
from app.services.grounding.autonomous.safe_fetch import SafeFetchDenied


@pytest.mark.asyncio
async def test_default_environment_has_no_egress_attestation(tmp_path):
    private = Ed25519PrivateKey.generate()
    key = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    if live_egress.os.name != "posix":
        with pytest.raises(SafeFetchDenied, match="EGRESS_CONFIG_DENIED"):
            LiveEgressAttestor(socket_path=tmp_path / "missing", public_key=key,
                               deployment_id="test", policy_sha256="a" * 64,
                               trusted_gid=2000)
    else:
        attestor = LiveEgressAttestor(socket_path=tmp_path / "missing", public_key=key,
                                     deployment_id="test", policy_sha256="a" * 64,
                               trusted_gid=2000)
        with pytest.raises(SafeFetchDenied, match="EGRESS_UNVERIFIED"):
            await attestor.attest(host="example.org", ip="93.184.215.14")


@pytest.mark.asyncio
async def test_nonce_scoped_signature_and_namespace_are_required(monkeypatch, tmp_path):
    """Fake local socket tests message validation, not network-layer isolation."""
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
        stat=lambda target: SimpleNamespace(st_ino=123),
    )
    monkeypatch.setattr(live_egress, "os", fake_os)
    attestor = LiveEgressAttestor(socket_path=path, public_key=key,
                                 deployment_id="reviewed", policy_sha256="a" * 64,
                                 trusted_gid=2000)
    saved = {"wrong_namespace": False}

    class Writer:
        def write(self, data):
            saved["request"] = json.loads(data)

        async def drain(self):
            pass

        def close(self):
            pass

        async def wait_closed(self):
            pass

    class Reader:
        async def readline(self):
            receipt = dict(saved["request"], expires_unix=int(time.time()) + 5,
                           isolation_verified=True)
            # Even a valid signature from the pinned key cannot be replayed
            # for a different namespace, nonce or target.
            if saved["wrong_namespace"]:
                receipt["namespace_inode"] = 456
            payload = live_egress._canonical(receipt)
            return json.dumps({"receipt": receipt,
                               "signature": private.sign(payload).hex()}).encode() + b"\n"

    async def fake_socket(_):
        return Reader(), Writer()

    monkeypatch.setattr(live_egress.asyncio, "open_unix_connection", fake_socket, raising=False)
    assert await attestor.attest(host="example.org", ip="93.184.215.14") is True
    first_nonce = saved["request"]["nonce"]
    saved["wrong_namespace"] = True
    with pytest.raises(SafeFetchDenied, match="EGRESS_UNVERIFIED"):
        await attestor.attest(host="example.org", ip="93.184.215.14")
    assert saved["request"]["namespace_inode"] == 123
    assert saved["request"]["nonce"] != first_nonce


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"euid": 0},
    {"egid": 1001, "groups": ()},
    {"socket_gid": 2001},
    {"socket_mode": 0o666},
    {"socket_mode": 0o600},
    {"parent_mode": 0o770},
    {"parent_mode": 0o777},
    {"parent_mode": 0o750, "parent_gid": 2001},
])
async def test_untrusted_identity_or_overwide_permissions_denied_before_connect(
    monkeypatch, tmp_path, change,
):
    """Offline permission matrix: no socket connection on a denied path."""
    private = Ed25519PrivateKey.generate()
    key = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    path = tmp_path / "attestor.sock"
    values = dict(euid=1000, egid=2000, groups=(2000,), socket_gid=2000,
                  socket_mode=0o660, parent_mode=0o750, parent_gid=2000)
    values.update(change)
    fake_os = SimpleNamespace(
        name="posix", geteuid=lambda: values["euid"],
        getegid=lambda: values["egid"], getgroups=lambda: values["groups"],
        lstat=lambda target: (
            SimpleNamespace(st_mode=stat.S_IFSOCK | values["socket_mode"],
                            st_uid=0, st_gid=values["socket_gid"])
            if target == path else
            SimpleNamespace(st_mode=stat.S_IFDIR | values["parent_mode"],
                            st_uid=0, st_gid=values["parent_gid"])
            if target == path.parent else
            SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0, st_gid=0)
        ),
        stat=lambda target: SimpleNamespace(st_ino=123),
    )
    monkeypatch.setattr(live_egress, "os", fake_os)
    attestor = LiveEgressAttestor(socket_path=path, public_key=key,
                                 deployment_id="reviewed", policy_sha256="a" * 64,
                                 trusted_gid=2000)
    calls = []

    async def forbidden_socket(_):
        calls.append(True)
        raise AssertionError("denied before connect")

    monkeypatch.setattr(live_egress.asyncio, "open_unix_connection", forbidden_socket,
                        raising=False)
    with pytest.raises(SafeFetchDenied, match="EGRESS_UNVERIFIED"):
        await attestor.attest(host="example.org", ip="93.184.215.14")
    assert not calls


def test_trusted_group_must_be_explicit_and_non_root(monkeypatch, tmp_path):
    private = Ed25519PrivateKey.generate()
    key = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    monkeypatch.setattr(live_egress, "os", SimpleNamespace(name="posix"))
    for gid in (0, -1, True):
        with pytest.raises(SafeFetchDenied, match="EGRESS_CONFIG_DENIED"):
            LiveEgressAttestor(socket_path=tmp_path / "attestor.sock", public_key=key,
                               deployment_id="reviewed", policy_sha256="a" * 64,
                               trusted_gid=gid)
