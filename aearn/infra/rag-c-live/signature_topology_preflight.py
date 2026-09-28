"""Offline Docker signer functional gate: no DNS, HTTP, grant or database."""
# This diagnostic uses assertions for its acceptance criteria. Never run optimized.
if not __debug__:
    raise SystemExit('OFFLINE_GATE_OPTIMIZATION_DENIED')

import argparse
import asyncio
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import time
from uuid import uuid4

IMAGE = "sha256:0103b7bce00513d954560e81c9228eafb24b1ac80acf93d5b69952107225c580"
SCRIPT = Path(__file__).resolve()
SOCKET = Path("/offline/attestor/attest.sock")
HOST, IP, DEPLOYMENT = "www.example.org", "8.8.8.8", "offline-signature-topology-test"
UID, GID = 65534, 23456


def docker(*args, timeout=15):
    result = subprocess.run(["docker", *args], check=True, capture_output=True, text=True, timeout=timeout)
    return (result.stdout + result.stderr).strip() if args[0] == "logs" else result.stdout.strip()


def server():
    from attestor import Attestor, _root_dir, _write_root_file, install
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    config = dict(deployment_id=DEPLOYMENT, socket_dir=str(SOCKET.parent),
                  trusted_gid=GID, worker_uid=UID, worker_gid=UID,
                  dns_ipv4="1.1.1.1", destinations={HOST: [IP]})
    policy = install(config)  # Actual B OUTPUT DROP in Docker --network none.
    directory = _root_dir(config)
    key = Ed25519PrivateKey.generate()  # TEST key only; no production mounts.

    class ObservedAttestor(Attestor):
        def peer_allowed(self, connection):
            pid, uid, gid = struct.unpack("3i", connection.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
            allowed = super().peer_allowed(connection)
            print(json.dumps(dict(event="peer", pid_visible=pid > 0,
                                  uid_match=uid == UID, gid_match=gid == UID,
                                  proc_netns_match=allowed if pid > 0 and uid == UID and gid == UID else False,
                                  allowed=allowed)), flush=True)
            return allowed

    attestor = ObservedAttestor(config, policy, key)
    _write_root_file(directory / "public.key", key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw))
    _write_root_file(directory / "policy.sha256", attestor.digest.encode())

    async def serve():
        listener = await asyncio.start_unix_server(attestor.handle, path=str(SOCKET))
        os.chown(SOCKET, 0, GID)
        os.chmod(SOCKET, 0o660)
        print("OFFLINE_SIGNER_READY", flush=True)
        async with listener:
            await listener.serve_forever()

    asyncio.run(serve())


def client(mode):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from app.services.grounding.autonomous.live_egress import LiveEgressAttestor
    from app.services.grounding.autonomous.safe_fetch import SafeFetchDenied

    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
    assert os.geteuid() == UID and os.getegid() == UID and GID in os.getgroups()
    assert int(status["CapEff"], 16) == int(status["CapBnd"], 16) == 0
    assert status["NoNewPrivs"].strip() == "1"
    public = (SOCKET.parent / "public.key").read_bytes()  # Ephemeral test pin only.
    policy = (SOCKET.parent / "policy.sha256").read_text()
    if mode == "wrong-key":
        public = Ed25519PrivateKey.generate().public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    attestor = LiveEgressAttestor(socket_path=SOCKET, public_key=public,
                                  deployment_id=DEPLOYMENT, policy_sha256=policy,
                                  trusted_gid=GID)
    try:
        envelope = asyncio.run(attestor.attest_envelope(host=HOST, ip=IP))
    except SafeFetchDenied:
        assert mode != "positive"
        print("OFFLINE_EXPECTED_REJECTION:" + mode)
        return
    assert mode == "positive", "MISMATCH_ACCEPTED"
    receipt = envelope.as_envelope()["receipt"]
    assert receipt["host"] == HOST and receipt["ip"] == IP
    assert receipt["namespace_inode"] == os.stat("/proc/self/ns/net").st_ino
    assert receipt["isolation_verified"] is True
    assert time.time() < receipt["expires_unix"] <= time.time() + 4
    assert len(receipt["nonce"]) == 48
    print("OFFLINE_FRESH_PINNED_SIGNATURE_VERIFIED")


def host(image):
    if image != IMAGE or docker("image", "inspect", image, "--format", "{{.Id}}") != IMAGE:
        raise ValueError("PINNED_IMAGE_UNAVAILABLE")
    prefix = "aearn-offline-sign-" + uuid4().hex[:12]
    name, volume = prefix + "-signer", prefix + "-socket"
    created_volume = created_server = False
    try:
        docker("volume", "create", volume)
        created_volume = True
        docker("run", "-d", "--name", name, "--network", "none",
               "--cap-drop", "ALL", "--cap-add", "NET_ADMIN", "--cap-add", "SYS_PTRACE", "--cap-add", "CHOWN",
               "--security-opt", "no-new-privileges", "--read-only",
               "--mount", f"type=volume,src={volume},dst=/offline",
               "--mount", f"type=bind,src={SCRIPT},dst=/preflight.py,readonly",
               image, "/preflight.py", "server")
        created_server = True
        for _ in range(50):
            if "OFFLINE_SIGNER_READY" in docker("logs", name):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("OFFLINE_SIGNER_NOT_READY: " + docker("logs", name))

        def worker(mode, shared_pid):
            args = ["run", "--rm", "--network", f"container:{name}"]
            if shared_pid:
                args += ["--pid", f"container:{name}"]
            args += ["--user", f"{UID}:{UID}", "--group-add", str(GID),
                     "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--read-only",
                     "--mount", f"type=volume,src={volume},dst=/offline,readonly",
                     "--mount", f"type=bind,src={SCRIPT},dst=/preflight.py,readonly",
                     image, "/preflight.py", "client", mode]
            out = docker(*args)
            expected = ("OFFLINE_FRESH_PINNED_SIGNATURE_VERIFIED" if mode == "positive"
                        else "OFFLINE_EXPECTED_REJECTION:" + mode)
            assert expected in out, "OFFLINE_GATE_FAILED:" + mode
            print(expected)

        worker("separate-pid", False)
        worker("positive", True)
        worker("wrong-key", True)
        events = [json.loads(line) for line in docker("logs", name).splitlines() if line.startswith('{"event": "peer"')]
        assert len(events) == 3 and events[0]["allowed"] is False
        assert events[0]["pid_visible"] is False
        assert all(events[1][k] for k in ("allowed", "pid_visible", "uid_match", "gid_match", "proc_netns_match"))
        assert events[2]["allowed"] is True  # signer signed, client rejected wrong pin
        print("OFFLINE_SIGNER_GATE_PASS; NO_SOURCE_OR_GRANT_AUTHORITY")
    finally:
        if created_server:
            docker("rm", "-f", name)
        if created_volume:
            docker("volume", "rm", volume)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("host", "server", "client"))
    parser.add_argument("client_mode", nargs="?", choices=("positive", "wrong-key", "separate-pid"))
    parser.add_argument("--image", default=IMAGE)
    args = parser.parse_args()
    if args.mode == "host":
        host(args.image)
    elif args.mode == "server":
        server()
    else:
        assert args.client_mode is not None
        client(args.client_mode)
