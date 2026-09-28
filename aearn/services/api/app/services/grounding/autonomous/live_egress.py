"""Independent deployment-attestor client for explicitly approved B2 fetches.

This module does not install or prove a firewall. The deployment must supply a
separately operated, root-owned Unix socket (0660, dedicated trusted group) and
pin its Ed25519 verification key through reviewed configuration. The signer must independently verify the worker
network namespace and egress deny rules before signing each fresh hop challenge.
No socket/key or deployment approval is configured by default.
"""
from __future__ import annotations

import asyncio
import json
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from secrets import token_hex

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .safe_fetch import SafeFetchDenied, _public_ip, _validated_url

_MAX_RECEIPT = 4096


@dataclass(frozen=True)
class VerifiedEgressEnvelope:
    """Exact canonical signed receipt; the receiver must verify it again.

    This is transport evidence, not a grant to fetch, retain, or admit content.
    A consumer must pin the verification key independently.
    """

    canonical_receipt: bytes
    signature_hex: str

    def as_envelope(self) -> dict[str, object]:
        """Return the signer-compatible JSON shape without changing signed bytes."""
        return {"receipt": json.loads(self.canonical_receipt),
                "signature": self.signature_hex}


class LiveEgressAttestor:
    """Ask a separate privileged attestor for a nonce-bound per-hop decision.

    Construct only from deployment-owned socket/key/policy configuration. The
    caller cannot grant egress with a boolean. A signed receipt is a deployment
    assertion, not a substitute for the operator's real network isolation test.
    """

    def __init__(self, *, socket_path: Path, public_key: bytes,
                 deployment_id: str, policy_sha256: str, trusted_gid: int) -> None:
        if (os.name != "posix" or not isinstance(socket_path, Path)
                or not socket_path.is_absolute() or type(trusted_gid) is not int
                or trusted_gid <= 0 or len(public_key) != 32
                or not deployment_id.isascii() or not 1 <= len(deployment_id) <= 80
                or not all(c.isalnum() or c in ".-_" for c in deployment_id)
                or len(policy_sha256) != 64
                or not all(c in "0123456789abcdef" for c in policy_sha256)):
            raise SafeFetchDenied("EGRESS_CONFIG_DENIED")
        self._socket_path = socket_path
        self._key = Ed25519PublicKey.from_public_bytes(public_key)
        self._deployment_id = deployment_id
        self._policy_sha256 = policy_sha256
        self._trusted_gid = trusted_gid

    async def attest(self, *, host: str, ip: str) -> bool:
        """Preserve the B boolean API and its one-challenge-per-call semantics."""
        await self.attest_envelope(host=host, ip=ip)
        return True

    async def attest_envelope(self, *, host: str, ip: str) -> VerifiedEgressEnvelope:
        """Return only a freshly verified, exact host/IP-bound signed envelope."""
        try:
            canonical, checked_host = _validated_url(f"https://{host}/")
            if canonical != f"https://{host}/" or checked_host != host or _public_ip(ip) != ip:
                raise SafeFetchDenied("EGRESS_UNVERIFIED")
            # A non-root worker may connect only through the deployment-pinned
            # group; neither the socket nor its directory chain is replaceable
            # by that worker. A parent with world traverse (e.g. /run) is fine.
            get_euid = getattr(os, "geteuid", lambda: 0)
            get_egid = getattr(os, "getegid", lambda: -1)
            group_ids: list[int] = list(getattr(os, "getgroups", lambda: ())())
            if (get_euid() == 0 or self._trusted_gid not in
                    (get_egid(), *group_ids)):
                raise SafeFetchDenied("EGRESS_UNVERIFIED")
            socket_info = os.lstat(self._socket_path)
            if (not stat.S_ISSOCK(socket_info.st_mode)
                    or socket_info.st_uid != 0
                    or socket_info.st_gid != self._trusted_gid
                    or stat.S_IMODE(socket_info.st_mode) != 0o660):
                raise SafeFetchDenied("EGRESS_UNVERIFIED")
            for parent in self._socket_path.parents:
                info = os.lstat(parent)
                mode = info.st_mode
                if (info.st_uid != 0 or not stat.S_ISDIR(mode)
                        or mode & (stat.S_IWGRP | stat.S_IWOTH)
                        or not (mode & stat.S_IXOTH or
                                info.st_gid == self._trusted_gid and mode & stat.S_IXGRP)):
                    raise SafeFetchDenied("EGRESS_UNVERIFIED")
            namespace = os.stat("/proc/self/ns/net").st_ino
            nonce = token_hex(24)
            request = {
                "deployment_id": self._deployment_id, "host": host, "ip": ip,
                "namespace_inode": namespace, "nonce": nonce,
                "policy_sha256": self._policy_sha256,
            }
            open_unix = getattr(asyncio, "open_unix_connection", None)
            if open_unix is None:
                raise SafeFetchDenied("EGRESS_UNVERIFIED")
            reader, writer = await asyncio.wait_for(
                open_unix(str(self._socket_path)), 1.0,
            )
            try:
                writer.write(_canonical(request) + b"\n")
                await asyncio.wait_for(writer.drain(), 1.0)
                raw = await asyncio.wait_for(reader.readline(), 1.0)
                if not raw.endswith(b"\n") or len(raw) > _MAX_RECEIPT:
                    raise SafeFetchDenied("EGRESS_UNVERIFIED")
            finally:
                writer.close()
                await writer.wait_closed()
            envelope = json.loads(raw)
            if type(envelope) is not dict or set(envelope) != {"receipt", "signature"}:
                raise SafeFetchDenied("EGRESS_UNVERIFIED")
            receipt = envelope["receipt"]
            signature = envelope["signature"]
            if (type(receipt) is not dict or type(signature) is not str
                    or len(signature) != 128
                    or set(receipt) != set(request) | {"expires_unix", "isolation_verified"}
                    or any(receipt.get(key) != value for key, value in request.items())
                    or receipt.get("isolation_verified") is not True
                    or type(receipt.get("expires_unix")) is not int
                    or not time.time() < receipt["expires_unix"] <= time.time() + 10):
                raise SafeFetchDenied("EGRESS_UNVERIFIED")
            canonical_receipt = _canonical(receipt)
            self._key.verify(bytes.fromhex(signature), canonical_receipt)
            return VerifiedEgressEnvelope(canonical_receipt, signature)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise SafeFetchDenied("EGRESS_UNVERIFIED") from exc


def _canonical(value: dict[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
