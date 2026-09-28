"""Default-off trusted-host Unix grant and bounded capture completion authority.

The host resolver/store are injected. This module never opens PostgreSQL, TCP or
HTTP, and cannot substitute for the current DB/attestor implementations.
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
import re
import socket
import stat
import struct
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from protocol import (
    BridgeDenied,
    MAX_BYTES,
    MAX_FRAME,
    TTL_SECONDS,
    Scope,
    canonical,
    decode,
    parse_request,
)

# Base64 expansion of the full C body cap, plus bounded scope/report/proof JSON.
# Grant requests and signed responses remain on the separate 4 KiB MAX_FRAME.
CAPTURE_FRAME = 4 * ((MAX_BYTES + 2) // 3) + 16_384
# C may spend up to 300s fetching, plus bounded framing/settlement overhead.
# This is only the one-use completion nonce lifetime, NOT the 4s dial grant TTL.
COMPLETION_WINDOW = 360


@dataclass(frozen=True)
class Decision:
    max_bytes: int
    expires_at: datetime


@dataclass(frozen=True)
class CaptureRecord:
    """Returned only after host callback atomically commits one immutable capture."""

    capture_id: str


Resolver = Callable[[Scope, datetime], Decision | None]
# Attestor verifier validates B's signature, expected exact host/IP, namespace,
# deployment, policy digest, challenge freshness, and actual pre-dial timing.
ProofVerifier = Callable[[Scope, object], bool]
# Store callback MUST recheck current DB/root/dispatch, grant, storage/license,
# and atomically consume the one-shot dispatch with body + immutable metadata.
CaptureStore = Callable[
    [Scope, bytes, str, str, object, datetime, socket.socket | None], CaptureRecord | None
]


def _peer(conn: socket.socket, uid: int, gid: int) -> bool:
    if not hasattr(socket, "SO_PEERCRED"):
        return False
    try:
        pid, actual_uid, actual_gid = struct.unpack(
            "3i",
            conn.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
            ),
        )
        # A peer in a separate Docker PID namespace can be reported as pid 0.
        # UID/GID are still mapped and must match the reviewed dedicated worker.
        return pid >= 0 and actual_uid == uid and actual_gid == gid
    except (OSError, struct.error):
        return False


class GrantServer:
    def __init__(
        self,
        *,
        resolver: Resolver,
        deployment_id: str,
        worker_uid: int,
        worker_gid: int,
        trusted_gid: int,
        proof_verifier: ProofVerifier | None = None,
        capture_store: CaptureStore | None = None,
    ):
        if (
            not callable(resolver)
            or any(
                type(v) is not int or v <= 0
                for v in (worker_uid, worker_gid, trusted_gid)
            )
            or type(deployment_id) is not str
            or not re.fullmatch(r"[a-z][a-z0-9._:-]{2,159}", deployment_id)
        ):
            raise BridgeDenied("INVALID_CONFIG")
        self.resolver, self.proof_verifier = resolver, proof_verifier
        self.capture_store = capture_store
        self.deployment_id = deployment_id
        self.worker_uid, self.worker_gid, self.trusted_gid = (
            worker_uid,
            worker_gid,
            trusted_gid,
        )
        self.key = Ed25519PrivateKey.generate()
        self._seen: dict[str, float] = {}
        self._issued: dict[str, tuple[Scope, float]] = {}

    def _nonce(self, nonce: str) -> None:
        now = time.time()
        self._seen = {n: until for n, until in self._seen.items() if until > now}
        self._issued = {n: grant for n, grant in self._issued.items() if grant[1] > now}
        if nonce in self._seen or len(self._seen) >= 4096:
            raise BridgeDenied("REPLAY_DENIED")
        self._seen[nonce] = now + COMPLETION_WINDOW

    def _sign(self, receipt: dict[str, object]) -> bytes:
        result = canonical(
            {"receipt": receipt, "signature": self.key.sign(canonical(receipt)).hex()}
        )
        if len(result) > MAX_FRAME:
            raise BridgeDenied("RESPONSE_DENIED")
        return result

    def _grant(self, value: dict[str, object]) -> bytes:
        scope, nonce = parse_request(value, self.deployment_id)
        self._nonce(nonce)
        started = time.time()
        result = self.resolver(scope, datetime.now(timezone.utc))
        after = time.time()
        if (
            type(result) is not Decision
            or type(result.max_bytes) is not int
            or not scope.max_bytes <= result.max_bytes <= MAX_BYTES
            or not isinstance(result.expires_at, datetime)
            or result.expires_at.tzinfo is None
            or result.expires_at.utcoffset() is None
            or after - started > TTL_SECONDS
        ):
            raise BridgeDenied("GRANT_DENIED")
        expiry = min(int(result.expires_at.timestamp()), int(after) + TTL_SECONDS)
        if expiry <= after:
            raise BridgeDenied("GRANT_DENIED")
        self._issued[nonce] = (scope, after + COMPLETION_WINDOW)
        return self._sign(
            {
                "v": 1,
                "deployment_id": self.deployment_id,
                "scope": scope.wire(),
                "nonce": nonce,
                "allowed": True,
                "max_bytes": result.max_bytes,
                "expires_unix": expiry,
            }
        )

    def _complete(self, value: dict[str, object], conn: socket.socket | None = None) -> bytes:
        if (
            not callable(self.proof_verifier)
            or not callable(self.capture_store)
            or set(value)
            != {
                "v",
                "deployment_id",
                "nonce",
                "grant_nonce",
                "scope",
                "final_url",
                "hops",
                "content_type",
                "sha256",
                "body_b64",
                "attestor_proof",
            }
            or type(value["v"]) is not int
            or value["v"] != 1
            or value["deployment_id"] != self.deployment_id
        ):
            raise BridgeDenied("COMPLETION_DENIED")
        # Reuse the nonce parser so completion has the same strict challenge syntax.
        scope, nonce = parse_request(
            {key: value[key] for key in ("v", "deployment_id", "nonce", "scope")},
            self.deployment_id,
        )
        self._nonce(nonce)
        grant_nonce = value["grant_nonce"]
        if (
            type(grant_nonce) is not str
            or self._issued.get(grant_nonce, (None, 0))[0] != scope
        ):
            raise BridgeDenied("COMPLETION_DENIED")
        # Consume in-memory issue even on failed proof/store. Durable DB dispatch
        # must independently ensure no second GET/capture on restart or crash.
        del self._issued[grant_nonce]
        if (
            value["final_url"] != scope.url
            or value["hops"] != [scope.url]
            or type(value["content_type"]) is not str
            or value["content_type"] not in ("text/html", "text/plain", "text/markdown")
            or type(value["sha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is None
            or type(value["body_b64"]) is not str
            or len(value["body_b64"]) > 4 * ((scope.max_bytes + 2) // 3)
            or len(canonical(value["attestor_proof"])) > 2048
        ):
            raise BridgeDenied("COMPLETION_DENIED")
        try:
            body = base64.b64decode(value["body_b64"], validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise BridgeDenied("COMPLETION_DENIED") from exc
        if (
            not body
            or len(body) > scope.max_bytes
            or hashlib.sha256(body).hexdigest() != value["sha256"]
            or self.proof_verifier(scope, value["attestor_proof"]) is not True
        ):
            raise BridgeDenied("COMPLETION_DENIED")
        result = self.capture_store(
            scope,
            body,
            value["content_type"],
            value["sha256"],
            value["attestor_proof"],
            datetime.now(timezone.utc),
            conn,
        )
        if (
            type(result) is not CaptureRecord
            or type(result.capture_id) is not str
            or str(UUID(result.capture_id)) != result.capture_id
        ):
            raise BridgeDenied("COMPLETION_DENIED")
        return self._sign(
            {
                "v": 1,
                "deployment_id": self.deployment_id,
                "scope": scope.wire(),
                "nonce": nonce,
                "grant_nonce": grant_nonce,
                "capture_id": result.capture_id,
                "sha256": value["sha256"],
                "captured_bytes": len(body),
            }
        )

    def handle(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(2)
            if not _peer(conn, self.worker_uid, self.worker_gid):
                return
            raw = bytearray()
            while len(raw) <= CAPTURE_FRAME:
                block = conn.recv(min(16384, CAPTURE_FRAME + 1 - len(raw)))
                if not block:
                    return
                raw.extend(block)
                if raw.endswith(b"\n"):
                    break
            if not raw.endswith(b"\n") or len(raw) > CAPTURE_FRAME + 1:
                return
            value = decode(bytes(raw[:-1]), max_bytes=CAPTURE_FRAME)
            if type(value) is not dict or "op" not in value:
                return
            op = value.pop("op")
            if op == "grant" and len(raw) <= MAX_FRAME + 1:
                response = self._grant(value)
            elif op == "complete":
                response = self._complete(value, conn)
            else:
                return
            conn.sendall(response + b"\n")
        except Exception:
            # Fixed refusal only; no body, URL, key or raw exception in logs.
            pass
        finally:
            conn.close()

    def serve(self, directory: Path, *, approved: bool = False) -> None:
        if not approved or os.geteuid() != 0 or os.name != "posix":
            raise BridgeDenied("DEFAULT_OFF")
        if (
            not directory.is_absolute()
            or ".." in directory.parts
            or directory == Path("/")
        ):
            raise BridgeDenied("INVALID_DIRECTORY")
        for part in (directory, *tuple(directory.parents)[:-1]):
            info = part.lstat()
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_uid != 0
                or stat.S_IMODE(info.st_mode) & 0o022
            ):
                raise BridgeDenied("INVALID_DIRECTORY")
        info = directory.lstat()
        if stat.S_IMODE(info.st_mode) != 0o750 or info.st_gid != self.trusted_gid:
            raise BridgeDenied("INVALID_DIRECTORY")
        sock_path, key_path = directory / "grant.sock", directory / "public.key"
        if (
            sock_path.exists()
            or sock_path.is_symlink()
            or key_path.exists()
            or key_path.is_symlink()
        ):
            raise BridgeDenied("PATH_OCCUPIED")
        old_mask = os.umask(0o077)
        try:
            fd = os.open(
                key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            try:
                os.write(
                    fd,
                    self.key.public_key().public_bytes(
                        encoding=serialization.Encoding.Raw,
                        format=serialization.PublicFormat.Raw,
                    ),
                )
            finally:
                os.close(fd)
            os.chown(key_path, 0, 0)
            os.chmod(key_path, 0o644)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                listener.bind(str(sock_path))
                os.chown(sock_path, 0, self.trusted_gid)
                os.chmod(sock_path, 0o660)
                listener.listen(8)
                while True:
                    conn, _ = listener.accept()
                    self.handle(conn)
        finally:
            os.umask(old_mask)
