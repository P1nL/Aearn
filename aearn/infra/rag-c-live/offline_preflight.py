"""Two-container offline firewall/peer diagnostic; no HTTP or live dispatch.

The installer is the B signer rule installer. A default-DROP policy is verified
from the kernel after install, then unprivileged SYN probes must each increment
that family's OUTPUT DROP policy counter. Route failures do not count as proof.
"""

from __future__ import annotations

import os
import ipaddress
from pathlib import Path
import re
import socket
import stat
import struct
import subprocess
import sys

from attestor import _closed_rules, install, load_config

CONFIG = Path("/etc/rag-c/egress.json")
BRIDGE = Path("/run/rag-c-control")
SOCKET = BRIDGE / "peer.sock"
DENIED_V4 = ("127.0.0.1", "10.1.2.3", "172.16.1.2", "192.168.1.2", "169.254.169.254")
DENIED_V6 = ("::1", "fc00::1", "fe80::1")
POLICY = re.compile(r"\AChain OUTPUT \(policy DROP (\d+) packets, \d+ bytes\)")


def output_drops(family: int) -> int:
    tool = "iptables" if family == socket.AF_INET else "ip6tables"
    output = subprocess.check_output(
        [tool, "-w", "-L", "OUTPUT", "-n", "-v", "-x"],
        stderr=subprocess.DEVNULL,
        timeout=3,
        text=True,
    )
    match = POLICY.match(output)
    if match is None:
        raise ValueError("RULE_COUNTER_UNKNOWN")
    return int(match.group(1))


def probe(address: str, port: int, family: int) -> None:
    """Root verifies each worker probe caused a real kernel policy drop."""
    before = output_drops(family)
    child = subprocess.run(
        [
            "/usr/bin/setpriv",
            "--no-new-privs",
            "--bounding-set=-all",
            "--reuid",
            str(WORKER_UID),
            "--regid",
            str(WORKER_GID),
            "--groups",
            str(BRIDGE_GID),
            sys.executable,
            __file__,
            "--probe",
            address,
            str(port),
            str(family),
        ],
        capture_output=True,
        text=True,
        timeout=4,
        check=False,
    )
    after = output_drops(family)
    if child.returncode != 0 or child.stdout.strip() != "BLOCKED" or after <= before:
        raise ValueError("NEGATIVE_PROBE_UNPROVEN")


def probe_target(address: str, port: int, family: int) -> tuple:
    if family == socket.AF_INET6:
        scope_id = 0
        if ipaddress.IPv6Address(address).is_link_local:
            interfaces = [index for index, name in socket.if_nameindex() if name != "lo"]
            if len(interfaces) != 1:
                raise ValueError("PROBE_INTERFACE_UNPROVEN")
            scope_id = interfaces[0]
        return (address, port, 0, scope_id)
    return (address, port)


def unprivileged_probe(address: str, port: int, family: int) -> None:
    if os.geteuid() == 0:
        raise ValueError("WORKER_PRIVILEGE_DENIED")
    status = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        key, _, value = line.partition(":")
        status[key] = value.strip()
    if (
        int(status.get("CapEff", "-1"), 16) != 0
        or int(status.get("CapBnd", "-1"), 16) != 0
        or status.get("NoNewPrivs") != "1"
    ):
        raise ValueError("WORKER_CAPABILITY_DENIED")
    with socket.socket(family, socket.SOCK_STREAM) as conn:
        conn.settimeout(0.6)
        try:
            conn.connect(probe_target(address, port, family))
        except (OSError, TimeoutError):
            print("BLOCKED")
            return
    raise ValueError("NEGATIVE_PROBE_CONNECTED")


def peer_probe() -> None:
    directory = BRIDGE.lstat()
    info = SOCKET.lstat()
    if (
        directory.st_uid != 0
        or directory.st_gid != BRIDGE_GID
        or stat.S_IMODE(directory.st_mode) != 0o750
        or info.st_uid != 0
        or info.st_gid != BRIDGE_GID
        or not stat.S_ISSOCK(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o660
    ):
        raise ValueError("MOUNT_PEER_DENIED")
    # Run peer check as the same unprivileged UID/GID that control expects.
    child = subprocess.run(
        [
            "/usr/bin/setpriv",
            "--no-new-privs",
            "--bounding-set=-all",
            "--reuid",
            str(WORKER_UID),
            "--regid",
            str(WORKER_GID),
            "--groups",
            str(BRIDGE_GID),
            sys.executable,
            __file__,
            "--peer",
        ],
        capture_output=True,
        text=True,
        timeout=4,
        check=False,
    )
    if child.returncode != 0 or child.stdout.strip() != "PEER_VERIFIED":
        raise ValueError("MOUNT_PEER_DENIED")


def unprivileged_peer() -> None:
    import secrets

    nonce = secrets.token_bytes(24)
    with socket.socket(socket.AF_UNIX) as conn:
        conn.settimeout(2)
        conn.connect(str(SOCKET))
        pid, uid, gid = struct.unpack(
            "3i",
            conn.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
            ),
        )
        if pid < 0 or uid != 0 or gid != 0:
            raise ValueError("CONTROL_PEER_DENIED")
        conn.sendall(nonce)
        response = bytearray()
        while len(response) < 32:
            chunk = conn.recv(32 - len(response))
            if not chunk:
                raise ValueError("CONTROL_PEER_DENIED")
            response.extend(chunk)
        if response[:24] != nonce:
            raise ValueError("CONTROL_PEER_DENIED")
        control_namespace = struct.unpack("!Q", response[24:])[0]
        if control_namespace == os.stat("/proc/self/ns/net").st_ino:
            raise ValueError("SHARED_NETWORK_NAMESPACE_DENIED")
    print("PEER_VERIFIED")


def run() -> None:
    if os.environ.get("RAG_C_PREFLIGHT_ONLY") != "yes" or os.geteuid() != 0:
        raise ValueError("DEFAULT_OFF")
    config = load_config(CONFIG)
    if set(config["destinations"]) != {"www.sqlite.org"}:
        raise ValueError("EXACT_TARGET_DENIED")
    global WORKER_UID, WORKER_GID, BRIDGE_GID
    WORKER_UID = config["worker_uid"]
    WORKER_GID = config["worker_gid"]
    BRIDGE_GID = config["trusted_gid"]
    install(config)
    _closed_rules(config)
    peer_probe()
    for address in DENIED_V4:
        probe(address, 5432, socket.AF_INET)
    probe(config["dns_ipv4"], 5432, socket.AF_INET)
    for address in config["destinations"]["www.sqlite.org"]:
        for port in (80, 8443):
            probe(address, port, socket.AF_INET)
    for address in DENIED_V6:
        probe(address, 443, socket.AF_INET6)
    _closed_rules(config)
    print("OFFLINE_PREFLIGHT_ONLY; LIVE_NOT_AUTHORIZED", flush=True)


def main() -> None:
    try:
        if len(sys.argv) == 5 and sys.argv[1] == "--probe":
            unprivileged_probe(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))
        elif sys.argv[1:] == ["--peer"]:
            unprivileged_peer()
        elif len(sys.argv) == 1:
            run()
        else:
            raise ValueError("INVALID_MODE")
    except (OSError, ValueError, subprocess.SubprocessError, TimeoutError):
        # Never reveal IP, URL, raw request, config, or environment in logs.
        raise SystemExit("OFFLINE_PREFLIGHT_DENIED") from None


if __name__ == "__main__":
    main()
