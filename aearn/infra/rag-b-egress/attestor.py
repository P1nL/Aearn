"""Operator-owned, default-off namespace firewall and per-hop signing attestor.

No provider requests or network probes occur in this module. Run only in a dedicated
container network namespace after explicit operator approval; see README.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import stat
import struct
import subprocess
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

MAX_REQUEST = 2048
NONCE = re.compile(r"[0-9a-f]{48}\Z")
DEPLOYMENT = re.compile(r"[A-Za-z0-9._-]{1,80}\Z")
HOST = re.compile(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?\Z")


def canonical(value: dict[str, object]) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def _ipv4(value: object, *, public: bool) -> str:
    if type(value) is not str:
        raise ValueError("INVALID_IP")
    ip = ipaddress.ip_address(value)
    if not isinstance(ip, ipaddress.IPv4Address) or str(ip) != value:
        raise ValueError("INVALID_IP")
    if public and not ip.is_global:
        raise ValueError("NON_PUBLIC_DESTINATION")
    if not public and (
        ip.is_loopback
        or ip.is_unspecified
        or ip.is_multicast
        or ip.is_link_local
        or ip.is_reserved
    ):
        raise ValueError("INVALID_RESOLVER")
    return value


def validate_config(value: object) -> dict[str, object]:
    if type(value) is not dict or set(value) != {
        "deployment_id",
        "socket_dir",
        "trusted_gid",
        "worker_uid",
        "worker_gid",
        "dns_ipv4",
        "destinations",
    }:
        raise ValueError("INVALID_CONFIG")
    deployment = value["deployment_id"]
    if type(deployment) is not str or not DEPLOYMENT.fullmatch(deployment):
        raise ValueError("INVALID_DEPLOYMENT")
    directory = value["socket_dir"]
    if (
        type(directory) is not str
        or not PurePosixPath(directory).is_absolute()
        or ".." in PurePosixPath(directory).parts
        or directory == "/"
    ):
        raise ValueError("INVALID_SOCKET_DIR")
    for field in ("trusted_gid", "worker_uid", "worker_gid"):
        if type(value[field]) is not int or not 0 < value[field] < 2**31:
            raise ValueError("INVALID_ID")
    _ipv4(value["dns_ipv4"], public=False)
    destinations = value["destinations"]
    if type(destinations) is not dict or not 1 <= len(destinations) <= 16:
        raise ValueError("INVALID_DESTINATIONS")
    approved: dict[str, list[str]] = {}
    for host, ips in destinations.items():
        if (
            type(host) is not str
            or not HOST.fullmatch(host)
            or host.startswith(".")
            or ".." in host
            or "." not in host
            or type(ips) is not list
            or not 1 <= len(ips) <= 16
        ):
            raise ValueError("INVALID_DESTINATION")
        approved[host] = [_ipv4(ip, public=True) for ip in ips]
        if len(set(approved[host])) != len(ips):
            raise ValueError("DUPLICATE_IP")
    return {**value, "destinations": approved}


def load_config(path: Path) -> dict[str, object]:
    # Configuration is an operator artifact, never read from dotenv or worker input.
    if not path.is_absolute():
        raise ValueError("CONFIG_NOT_ABSOLUTE")
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != 0
        or stat.S_IMODE(info.st_mode) & 0o022
    ):
        raise ValueError("CONFIG_NOT_ROOT_OWNED")
    for parent in path.parents:
        if parent == Path("/"):
            break
        info = parent.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) & 0o022
        ):
            raise ValueError("CONFIG_PARENT_DENIED")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) & 0o022
        ):
            raise ValueError("CONFIG_NOT_ROOT_OWNED")
        with os.fdopen(fd, "r", encoding="utf-8") as source:
            fd = -1
            return validate_config(json.load(source))
    finally:
        if fd >= 0:
            os.close(fd)


def _run(*args: str) -> bytes:
    return subprocess.check_output(args, stderr=subprocess.DEVNULL, timeout=3)


def _rules() -> bytes:
    return _run("iptables", "-S", "OUTPUT") + b"\n" + _run("ip6tables", "-S", "OUTPUT")


def _closed_rules(config: dict[str, object]) -> bytes:
    v4 = _run("iptables", "-S", "OUTPUT").decode("ascii").splitlines()
    v6 = _run("ip6tables", "-S", "OUTPUT").decode("ascii").splitlines()
    if not v4 or v4[0] != "-P OUTPUT DROP" or not v6 or v6 != ["-P OUTPUT DROP"]:
        raise ValueError("OUTPUT_NOT_CLOSED")
    expected_count = 1 + 2 + sum(len(ips) for ips in config["destinations"].values())
    if len(v4) != expected_count:
        raise ValueError("UNEXPECTED_OUTPUT_RULE")
    dns = config["dns_ipv4"]
    for proto in ("udp", "tcp"):
        _run(
            "iptables",
            "-C",
            "OUTPUT",
            "-d",
            f"{dns}/32",
            "-p",
            proto,
            "--dport",
            "53",
            "-j",
            "ACCEPT",
        )
    for ips in config["destinations"].values():
        for ip in ips:
            _run(
                "iptables",
                "-C",
                "OUTPUT",
                "-d",
                f"{ip}/32",
                "-p",
                "tcp",
                "--dport",
                "443",
                "-j",
                "ACCEPT",
            )
    # Count + each expected rule exists: no extra rule can survive installation.
    # The exact snapshot is rechecked for every signing request.
    return _rules()


def install(config: dict[str, object]) -> bytes:
    """Install only in the caller's dedicated network namespace as root.

    Close both families BEFORE flushing. On any failure leave both policies DROP;
    an operator must destroy the container, not proceed to start the worker.
    """
    if os.geteuid() != 0:
        raise ValueError("ROOT_REQUIRED")
    _run("iptables", "-P", "OUTPUT", "DROP")
    _run("ip6tables", "-P", "OUTPUT", "DROP")
    _run("iptables", "-F", "OUTPUT")
    _run("ip6tables", "-F", "OUTPUT")
    dns = config["dns_ipv4"]
    for proto in ("udp", "tcp"):
        _run(
            "iptables",
            "-A",
            "OUTPUT",
            "-d",
            f"{dns}/32",
            "-p",
            proto,
            "--dport",
            "53",
            "-j",
            "ACCEPT",
        )
    for ips in config["destinations"].values():
        for ip in ips:
            _run(
                "iptables",
                "-A",
                "OUTPUT",
                "-d",
                f"{ip}/32",
                "-p",
                "tcp",
                "--dport",
                "443",
                "-j",
                "ACCEPT",
            )
    return _closed_rules(config)


def _root_dir(config: dict[str, object]) -> Path:
    directory = Path(config["socket_dir"])
    parent = directory.parent
    while parent != Path("/"):
        info = parent.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) & 0o022
        ):
            raise ValueError("UNTRUSTED_PARENT")
        parent = parent.parent
    if directory.exists() or directory.is_symlink():
        raise ValueError("SOCKET_DIR_EXISTS")
    directory.mkdir(mode=0o750)
    os.chown(directory, 0, config["trusted_gid"])
    os.chmod(directory, 0o750)
    return directory


def _write_root_file(path: Path, content: bytes) -> None:
    with path.open("xb") as file:
        file.write(content)
    os.chown(path, 0, 0)
    os.chmod(path, 0o644)


class Attestor:
    def __init__(
        self, config: dict[str, object], policy: bytes, key: Ed25519PrivateKey
    ):
        self.config = config
        self.policy = policy
        self.digest = hashlib.sha256(policy).hexdigest()
        self.key = key
        self.namespace = os.stat("/proc/self/ns/net").st_ino
        self._seen_nonces: dict[str, float] = {}
        self.allowed = {
            (host, ip) for host, ips in config["destinations"].items() for ip in ips
        }

    def receipt(self, request: object) -> dict[str, object] | None:
        if (
            type(request) is not dict
            or set(request)
            != {
                "deployment_id",
                "host",
                "ip",
                "namespace_inode",
                "nonce",
                "policy_sha256",
            }
            or request["deployment_id"] != self.config["deployment_id"]
            or type(request["namespace_inode"]) is not int
            or request["namespace_inode"] != self.namespace
            or request["policy_sha256"] != self.digest
            or type(request["nonce"]) is not str
            or not NONCE.fullmatch(request["nonce"])
            or type(request["host"]) is not str
            or type(request["ip"]) is not str
            or (request["host"], request["ip"]) not in self.allowed
        ):
            return None
        try:
            if (
                _rules() != self.policy
                or os.stat("/proc/self/ns/net").st_ino != self.namespace
            ):
                return None
        except (OSError, subprocess.SubprocessError):
            return None
        now = time.monotonic()
        self._seen_nonces = {
            nonce: until for nonce, until in self._seen_nonces.items() if until > now
        }
        if request["nonce"] in self._seen_nonces or len(self._seen_nonces) >= 4096:
            return None
        self._seen_nonces[request["nonce"]] = now + 10
        receipt = {
            **request,
            "expires_unix": int(time.time()) + 4,
            "isolation_verified": True,
        }
        return {
            "receipt": receipt,
            "signature": self.key.sign(canonical(receipt)).hex(),
        }

    def peer_allowed(self, connection: object) -> bool:
        try:
            raw = connection.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
            )
            pid, uid, gid = struct.unpack("3i", raw)
            return (
                pid > 0
                and uid == self.config["worker_uid"]
                and gid == self.config["worker_gid"]
                and os.stat(f"/proc/{pid}/ns/net").st_ino == self.namespace
            )
        except (AttributeError, OSError, struct.error):
            return False

    async def handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            if not self.peer_allowed(writer.get_extra_info("socket")):
                return
            raw = await asyncio.wait_for(reader.readline(), 1)
            if len(raw) > MAX_REQUEST or not raw.endswith(b"\n"):
                return
            envelope = self.receipt(json.loads(raw))
            if envelope is not None:
                writer.write(canonical(envelope) + b"\n")
                await asyncio.wait_for(writer.drain(), 1)
        except (Exception, asyncio.TimeoutError):
            # No URL, host, key, body, raw request or exception in diagnostics.
            pass
        finally:
            writer.close()
            await writer.wait_closed()


async def serve(config: dict[str, object]) -> None:
    policy = install(config)
    directory = _root_dir(config)
    key = Ed25519PrivateKey.generate()
    attestor = Attestor(config, policy, key)
    _write_root_file(
        directory / "public.key",
        key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
        ),
    )
    _write_root_file(directory / "policy.sha256", attestor.digest.encode("ascii"))
    sock = directory / "attest.sock"
    server = await asyncio.start_unix_server(
        attestor.handle, path=str(sock), limit=MAX_REQUEST + 1
    )
    os.chown(sock, 0, config["trusted_gid"])
    os.chmod(sock, 0o660)
    print("EGRESS_ATTESTOR_READY", flush=True)
    async with server:
        await server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("RAG_EGRESS_OPERATOR_APPROVED") != "yes":
        raise SystemExit("EGRESS_DEFAULT_OFF")
    try:
        config = load_config(args.config)
        asyncio.run(serve(config))
    except (OSError, ValueError, subprocess.SubprocessError):
        # Stable code only. Never print paths, settings, subprocess stderr or request.
        raise SystemExit("EGRESS_SETUP_DENIED") from None


if __name__ == "__main__":
    main()
