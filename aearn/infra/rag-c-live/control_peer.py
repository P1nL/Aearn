"""Offline shared-mount/peer diagnostic. Never resolves policy or stores a capture."""

from __future__ import annotations

import os
from pathlib import Path
import socket
import stat
import struct

SOCKET_DIR = Path("/run/rag-c-control")
SOCKET = SOCKET_DIR / "peer.sock"


def peer_identity(conn: socket.socket) -> tuple[int, int, int]:
    raw = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    return struct.unpack("3i", raw)


def initialize(uid: int, gid: int, bridge_gid: int) -> None:
    if os.geteuid() != 0 or not all(0 < n < 2**31 for n in (uid, gid, bridge_gid)):
        raise ValueError("CONTROL_IDENTITY_DENIED")
    info = SOCKET_DIR.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or SOCKET.exists():
        raise ValueError("CONTROL_MOUNT_DENIED")
    os.chown(SOCKET_DIR, 0, bridge_gid)
    os.chmod(SOCKET_DIR, 0o750)


def serve(uid: int, gid: int, bridge_gid: int) -> None:
    initialize(uid, gid, bridge_gid)
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(str(SOCKET))
        os.chown(SOCKET, 0, bridge_gid)
        os.chmod(SOCKET, 0o660)
        server.listen(1)
        server.settimeout(120)
        print("CONTROL_PEER_READY", flush=True)
        while True:
            with server.accept()[0] as conn:
                conn.settimeout(2)
                pid, actual_uid, actual_gid = peer_identity(conn)
                # Docker Desktop across PID namespaces may legitimately report 0.
                if pid < 0 or (actual_uid, actual_gid) != (uid, gid):
                    continue
                nonce = conn.recv(24)
                if len(nonce) != 24:
                    continue
                namespace = os.stat("/proc/self/ns/net").st_ino
                conn.sendall(nonce + struct.pack("!Q", namespace))
                print("CONTROL_PEER_ACCEPTED", flush=True)


def main() -> None:
    try:
        uid = int(os.environ["RAG_C_WORKER_UID"])
        gid = int(os.environ["RAG_C_WORKER_GID"])
        bridge_gid = int(os.environ["RAG_C_BRIDGE_GID"])
        serve(uid, gid, bridge_gid)
    except (OSError, ValueError, KeyError, TimeoutError):
        raise SystemExit("CONTROL_PROOF_DENIED") from None


if __name__ == "__main__":
    main()
