"""Unprivileged client: root-owned Unix socket, pinned Ed25519 public key."""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
import secrets
import socket
import stat
import struct
import time
from uuid import UUID
from server import CAPTURE_FRAME

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from protocol import (
    BridgeDenied,
    MAX_BYTES,
    MAX_FRAME,
    TTL_SECONDS,
    Scope,
    canonical,
    decode,
    request,
)


def _trusted_path(path: Path, *, kind: str, gid: int | None = None) -> os.stat_result:
    if not path.is_absolute() or ".." in path.parts:
        raise BridgeDenied("PATH_DENIED")
    for parent in path.parents:
        if parent == Path("/"):
            break
        info = parent.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) & 0o022
        ):
            raise BridgeDenied("PATH_DENIED")
    info = path.lstat()
    if info.st_uid != 0 or (kind != "key" and stat.S_IMODE(info.st_mode) & 0o007):
        raise BridgeDenied("PATH_DENIED")
    if kind == "key":
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o022:
            raise BridgeDenied("PATH_DENIED")
    elif (
        not stat.S_ISSOCK(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o660
        or info.st_gid != gid
    ):
        raise BridgeDenied("PATH_DENIED")
    return info


class GrantClient:
    def __init__(
        self,
        *,
        socket_path: Path,
        public_key_path: Path,
        pinned_key_sha256: str,
        trusted_gid: int,
        deployment_id: str,
    ):
        if (
            os.name != "posix"
            or not hasattr(socket, "SO_PEERCRED")
            or type(trusted_gid) is not int
            or trusted_gid <= 0
            or type(pinned_key_sha256) is not str
            or len(pinned_key_sha256) != 64
        ):
            raise BridgeDenied("CLIENT_DISABLED")
        self.socket_path, self.public_key_path = socket_path, public_key_path
        self.trusted_gid, self.deployment_id = trusted_gid, deployment_id
        self.pinned_key_sha256 = pinned_key_sha256

    def _key(self) -> Ed25519PublicKey:
        _trusted_path(self.public_key_path, kind="key")
        fd = os.open(self.public_key_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != 0
                or stat.S_IMODE(info.st_mode) & 0o022
            ):
                raise BridgeDenied("KEY_DENIED")
            data = os.read(fd, 33)
            if (
                len(data) != 32
                or hashlib.sha256(data).hexdigest() != self.pinned_key_sha256
            ):
                raise BridgeDenied("KEY_DENIED")
            return Ed25519PublicKey.from_public_bytes(data)
        finally:
            os.close(fd)

    def _roundtrip(
        self, payload: dict[str, object], *, max_request: int = MAX_FRAME,
        io_timeout: float = 2.0
    ) -> object:
        key = self._key()
        info = _trusted_path(self.socket_path, kind="socket", gid=self.trusted_gid)
        raw = canonical(payload)
        if len(raw) > max_request:
            raise BridgeDenied("FRAME_DENIED")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(2)
            conn.connect(str(self.socket_path))
            # Detect pathname replacement between lstat and connect.
            pid, uid, gid = struct.unpack(
                "3i",
                conn.getsockopt(
                    socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
                ),
            )
            # Cross-container PID namespaces can map the trusted peer PID to 0.
            # Reject mismatched mapped UID/GID and retain the pinned-key check.
            if pid < 0 or uid != 0 or gid != 0:
                raise BridgeDenied("PEER_DENIED")
            again = _trusted_path(self.socket_path, kind="socket", gid=self.trusted_gid)
            if (again.st_ino, again.st_dev) != (info.st_ino, info.st_dev):
                raise BridgeDenied("PATH_DENIED")
            # Keep the connection/peer check at 2s. A bounded complete frame and
            # subsequent DB settlement may take longer, unlike a grant frame.
            conn.settimeout(io_timeout)
            conn.sendall(raw + b"\n")
            response = bytearray()
            while len(response) <= MAX_FRAME:
                block = conn.recv(min(4096, MAX_FRAME + 1 - len(response)))
                if not block:
                    break
                response.extend(block)
                if response.endswith(b"\n"):
                    break
            if not response.endswith(b"\n") or len(response) > MAX_FRAME + 1:
                raise BridgeDenied("RESPONSE_DENIED")
        envelope = decode(bytes(response[:-1]))
        if (
            type(envelope) is not dict
            or set(envelope) != {"receipt", "signature"}
            or type(envelope["signature"]) is not str
            or len(envelope["signature"]) != 128
        ):
            raise BridgeDenied("SIGNATURE_DENIED")
        try:
            key.verify(
                bytes.fromhex(envelope["signature"]), canonical(envelope["receipt"])
            )
        except (InvalidSignature, ValueError, TypeError) as exc:
            raise BridgeDenied("SIGNATURE_DENIED") from exc
        return envelope["receipt"]

    def grant(self, scope: Scope) -> tuple[dict[str, object], str]:
        nonce = secrets.token_hex(24)
        expected = request(scope, nonce, self.deployment_id)
        receipt = self._roundtrip({"op": "grant", **expected})
        now = time.time()
        if (
            type(receipt) is not dict
            or set(receipt)
            != {
                "v",
                "deployment_id",
                "scope",
                "nonce",
                "allowed",
                "max_bytes",
                "expires_unix",
            }
            or receipt["v"] != 1
            or receipt["deployment_id"] != self.deployment_id
            or receipt["scope"] != expected["scope"]
            or receipt["nonce"] != nonce
            or receipt["allowed"] is not True
            or type(receipt["max_bytes"]) is not int
            or not scope.max_bytes <= receipt["max_bytes"] <= MAX_BYTES
            or type(receipt["expires_unix"]) is not int
            or not now < receipt["expires_unix"] <= now + TTL_SECONDS
        ):
            raise BridgeDenied("GRANT_DENIED")
        return receipt, nonce

    def complete(
        self,
        scope: Scope,
        *,
        grant_nonce: str,
        body: bytes,
        content_type: str,
        attestor_proof: object,
    ) -> dict[str, object]:
        """Transfer one exact bounded capture; never send a second HTTP request.

        The host callback, not this client, decides whether the evidence is
        admissible and persists it atomically against the one-shot dispatch.
        """
        if type(body) is not bytes or not body or len(body) > scope.max_bytes:
            raise BridgeDenied("BODY_DENIED")
        nonce = secrets.token_hex(24)
        payload = {
            "op": "complete",
            **request(scope, nonce, self.deployment_id),
            "grant_nonce": grant_nonce,
            "final_url": scope.url,
            "hops": [scope.url],
            "content_type": content_type,
            "sha256": hashlib.sha256(body).hexdigest(),
            "body_b64": base64.b64encode(body).decode("ascii"),
            "attestor_proof": attestor_proof,
        }
        receipt = self._roundtrip(payload, max_request=CAPTURE_FRAME, io_timeout=30.0)
        if (
            type(receipt) is not dict
            or set(receipt)
            != {
                "v",
                "deployment_id",
                "scope",
                "nonce",
                "grant_nonce",
                "capture_id",
                "sha256",
                "captured_bytes",
            }
            or receipt["v"] != 1
            or receipt["deployment_id"] != self.deployment_id
            or receipt["scope"] != scope.wire()
            or receipt["nonce"] != nonce
            or receipt["grant_nonce"] != grant_nonce
            or receipt["sha256"] != payload["sha256"]
            or type(receipt["captured_bytes"]) is not int
            or receipt["captured_bytes"] != len(body)
            or type(receipt["capture_id"]) is not str
        ):
            raise BridgeDenied("COMPLETION_DENIED")
        try:
            if str(UUID(receipt["capture_id"])) != receipt["capture_id"]:
                raise ValueError()
        except ValueError as exc:
            raise BridgeDenied("COMPLETION_DENIED") from exc
        return receipt
