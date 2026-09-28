"""Offline harness regression checks. No Docker, socket, DNS or GET."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import socket
import struct
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The offline tests don't import cryptography or call the real B installer.
sys.modules["attestor"] = types.SimpleNamespace(
    _closed_rules=lambda _: None, install=lambda _: None, load_config=lambda _: None
)
probe = load("rag_c_offline_probe", "offline_preflight.py")
control = load("rag_c_control_peer", "control_peer.py")
inputs = load("rag_c_check_inputs", "check_inputs.py")


class PreflightTests(unittest.TestCase):
    def test_default_off_before_config_or_rules(self):
        with (
            patch.dict(probe.os.environ, {}, clear=True),
            patch.object(probe.os, "geteuid", return_value=0, create=True),
        ):
            with self.assertRaisesRegex(ValueError, "DEFAULT_OFF"):
                probe.run()

    def test_target_scope_refused_before_install(self):
        config = {"destinations": {"other.example": ["8.8.8.8"]}}
        with (
            patch.dict(probe.os.environ, {"RAG_C_PREFLIGHT_ONLY": "yes"}),
            patch.object(probe.os, "geteuid", return_value=0, create=True),
            patch.object(probe, "load_config", return_value=config),
            patch.object(probe, "install") as install,
        ):
            with self.assertRaisesRegex(ValueError, "EXACT_TARGET_DENIED"):
                probe.run()
            install.assert_not_called()

    def test_no_counter_increment_is_not_proof(self):
        probe.WORKER_UID, probe.WORKER_GID, probe.BRIDGE_GID = 65534, 65534, 23456
        result = MagicMock(returncode=0, stdout="BLOCKED\n")
        with (
            patch.object(probe, "output_drops", side_effect=[7, 7]),
            patch.object(probe.subprocess, "run", return_value=result),
        ):
            with self.assertRaisesRegex(ValueError, "NEGATIVE_PROBE_UNPROVEN"):
                probe.probe("127.0.0.1", 5432, socket.AF_INET)

    def test_counter_increment_with_failed_worker_is_not_proof(self):
        probe.WORKER_UID, probe.WORKER_GID, probe.BRIDGE_GID = 65534, 65534, 23456
        result = MagicMock(returncode=1, stdout="")
        with (
            patch.object(probe, "output_drops", side_effect=[7, 8]),
            patch.object(probe.subprocess, "run", return_value=result),
        ):
            with self.assertRaisesRegex(ValueError, "NEGATIVE_PROBE_UNPROVEN"):
                probe.probe("127.0.0.1", 5432, socket.AF_INET)

    def test_counter_increment_and_worker_denial(self):
        probe.WORKER_UID, probe.WORKER_GID, probe.BRIDGE_GID = 65534, 65534, 23456
        result = MagicMock(returncode=0, stdout="BLOCKED\n")
        with (
            patch.object(probe, "output_drops", side_effect=[7, 8]),
            patch.object(probe.subprocess, "run", return_value=result),
        ):
            probe.probe("127.0.0.1", 5432, socket.AF_INET)

    def test_probe_matrix_avoids_target_443(self):
        config = {
            "destinations": {"www.sqlite.org": ["8.8.8.8"]},
            "dns_ipv4": "1.1.1.1",
            "worker_uid": 65534,
            "worker_gid": 65534,
            "trusted_gid": 23456,
        }
        with (
            patch.dict(probe.os.environ, {"RAG_C_PREFLIGHT_ONLY": "yes"}),
            patch.object(probe.os, "geteuid", return_value=0, create=True),
            patch.object(probe, "load_config", return_value=config),
            patch.object(probe, "install"),
            patch.object(probe, "_closed_rules"),
            patch.object(probe, "peer_probe"),
            patch.object(probe, "probe") as calls,
        ):
            probe.run()
        targets = [(c.args[0], c.args[1]) for c in calls.call_args_list]
        self.assertIn(("8.8.8.8", 80), targets)
        self.assertIn(("8.8.8.8", 8443), targets)
        self.assertNotIn(("8.8.8.8", 443), targets)
        self.assertIn(("169.254.169.254", 5432), targets)
        self.assertIn(("fc00::1", 443), targets)

    def test_ipv6_link_local_probe_uses_single_interface_scope(self):
        with patch.object(probe.socket, "if_nameindex", return_value=[(1, "lo"), (2, "eth0")]):
            self.assertEqual(probe.probe_target("fe80::1", 443, socket.AF_INET6), ("fe80::1", 443, 0, 2))
            self.assertEqual(probe.probe_target("fc00::1", 443, socket.AF_INET6), ("fc00::1", 443, 0, 0))
        for interfaces in ([(1, "lo")], [(1, "lo"), (2, "eth0"), (3, "eth1")]):
            with patch.object(probe.socket, "if_nameindex", return_value=interfaces):
                with self.assertRaisesRegex(ValueError, "PROBE_INTERFACE_UNPROVEN"):
                    probe.probe_target("fe80::1", 443, socket.AF_INET6)

    def test_pid_zero_peer_identity_is_preserved(self):
        conn = MagicMock()
        conn.getsockopt.return_value = struct.pack("3i", 0, 65534, 65534)
        with patch.object(control.socket, "SO_PEERCRED", 17, create=True):
            self.assertEqual(control.peer_identity(conn), (0, 65534, 65534))

    def test_equal_network_namespace_rejected_after_pid_zero_peer(self):
        nonce = b"n" * 24
        conn = MagicMock()
        conn.getsockopt.return_value = struct.pack("3i", 0, 0, 0)
        conn.recv.return_value = nonce + struct.pack("!Q", 42)
        sock = MagicMock()
        sock.__enter__.return_value = conn
        with (
            patch.object(probe.socket, "AF_UNIX", 1, create=True),
            patch.object(probe.socket, "SO_PEERCRED", 17, create=True),
            patch.object(probe.socket, "socket", return_value=sock),
            patch("secrets.token_bytes", return_value=nonce),
            patch.object(
                probe.os, "stat", return_value=types.SimpleNamespace(st_ino=42)
            ),
        ):
            with self.assertRaisesRegex(ValueError, "SHARED_NETWORK_NAMESPACE_DENIED"):
                probe.unprivileged_peer()

    def test_image_tags_and_mutable_refs_rejected(self):
        for value in (
            "example.invalid/control:latest",
            "example.invalid/control@sha256:short",
        ):
            with self.assertRaisesRegex(ValueError, "IMAGE_NOT_PINN"):
                inputs.check_digest_ref(value)
        inputs.check_digest_ref("example.invalid/control@sha256:" + "a" * 64)

    def test_input_check_requires_all_four_digests_before_config(self):
        env = {
            "RAG_C_CONTROL_BASE": "control:latest",
            "RAG_C_EGRESS_BASE": "egress:latest",
            "RAG_C_CONTROL_IMAGE": "control:latest",
            "RAG_C_EGRESS_IMAGE": "egress:latest",
        }
        with patch.object(inputs, "root_config") as config:
            with self.assertRaisesRegex(ValueError, "IMAGE_NOT_PINN"):
                inputs.check_inputs(env)
            config.assert_not_called()

    def test_compose_has_no_live_profile_or_host_network(self):
        compose = (ROOT / "compose.offline.yaml").read_text(encoding="utf-8")
        self.assertIn("profiles: [offline-preflight]", compose)
        self.assertIn("internal: true", compose)
        self.assertNotIn("network_mode: host", compose)
        self.assertNotIn("docker.sock", compose)
        self.assertNotIn("POSTGRES", compose)
        self.assertIn("cap_add: [CHOWN]", compose)
        self.assertIn("cap_add: [NET_ADMIN, SETUID, SETGID, SETPCAP]", compose)


if __name__ == "__main__":
    unittest.main()
