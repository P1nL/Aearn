"""Offline protocol and firewall command tests: no Docker, network, or provider."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import struct
import os
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

MODULE = Path(__file__).resolve().parents[1] / "attestor.py"
spec = importlib.util.spec_from_file_location("rag_egress_attestor", MODULE)
attestor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(attestor)


def config():
    return attestor.validate_config(
        {
            "deployment_id": "test-isolation",
            "socket_dir": "/run/rag-attestor",
            "trusted_gid": 23456,
            "worker_uid": 65534,
            "worker_gid": 65534,
            "dns_ipv4": "172.19.0.10",
            "destinations": {"docs.example.org": ["93.184.215.14"]},
        }
    )


class DefaultOffTests(unittest.TestCase):
    def test_launcher_does_not_start_without_operator_approval(self):
        run_spec = importlib.util.spec_from_file_location(
            "rag_egress_run", Path(__file__).resolve().parents[1] / "run.py"
        )
        with patch.dict(os.environ, {}, clear=True):
            import sys

            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            try:
                launcher = importlib.util.module_from_spec(run_spec)
                run_spec.loader.exec_module(launcher)
                with patch.object(launcher.os, "geteuid", return_value=0, create=True):
                    with self.assertRaisesRegex(SystemExit, "EGRESS_DEFAULT_OFF"):
                        launcher.main()
            finally:
                sys.path.pop(0)


class ConfigTests(unittest.TestCase):
    def test_explicit_values_only_and_private_destinations_denied(self):
        for field, value in (
            ("dns_ipv4", "127.0.0.1"),
            ("dns_ipv4", "169.254.169.254"),
            ("trusted_gid", True),
            ("socket_dir", "relative"),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                attestor.validate_config({**config(), field: value})
        for ip in (
            "127.0.0.1",
            "10.0.0.1",
            "172.19.0.3",
            "169.254.169.254",
            "192.168.1.1",
            "::1",
            "fd00::1",
        ):
            with self.subTest(ip=ip), self.assertRaises(ValueError):
                attestor.validate_config(
                    {**config(), "destinations": {"docs.example.org": [ip]}}
                )
        with self.assertRaises(ValueError):
            attestor.validate_config({**config(), "extra": "ignored"})

    def test_config_file_must_be_root_owned_not_writable(self):
        with (
            patch.object(attestor.Path, "lstat") as lstat,
            patch.object(attestor.Path, "is_absolute", return_value=True),
        ):
            lstat.return_value.st_mode = 0o100666
            lstat.return_value.st_uid = 0
            with self.assertRaisesRegex(ValueError, "CONFIG_NOT_ROOT_OWNED"):
                attestor.load_config(Path("/run/config.json"))


class FirewallTests(unittest.TestCase):
    def test_close_both_families_before_flush_then_exact_exceptions(self):
        commands = []

        def fake(*argv):
            commands.append(argv)
            if argv[:2] == ("iptables", "-S"):
                return (
                    b"-P OUTPUT DROP\n"
                    b"-A OUTPUT -d 172.19.0.10/32 -p udp --dport 53 -j ACCEPT\n"
                    b"-A OUTPUT -d 172.19.0.10/32 -p tcp --dport 53 -j ACCEPT\n"
                    b"-A OUTPUT -d 93.184.215.14/32 -p tcp --dport 443 -j ACCEPT\n"
                )
            if argv[:2] == ("ip6tables", "-S"):
                return b"-P OUTPUT DROP\n"
            return b""

        with (
            patch.object(attestor.os, "geteuid", return_value=0, create=True),
            patch.object(attestor, "_run", side_effect=fake),
        ):
            policy = attestor.install(config())
        self.assertEqual(
            commands[:4],
            [
                ("iptables", "-P", "OUTPUT", "DROP"),
                ("ip6tables", "-P", "OUTPUT", "DROP"),
                ("iptables", "-F", "OUTPUT"),
                ("ip6tables", "-F", "OUTPUT"),
            ],
        )
        self.assertIn(
            (
                "iptables",
                "-A",
                "OUTPUT",
                "-d",
                "93.184.215.14/32",
                "-p",
                "tcp",
                "--dport",
                "443",
                "-j",
                "ACCEPT",
            ),
            commands,
        )
        self.assertNotIn(b"ACCEPT", policy.splitlines()[0])
        self.assertEqual(
            len(policy), len(fake("iptables", "-S") + b"\n" + fake("ip6tables", "-S"))
        )

    def test_unexpected_ipv6_allow_rejected(self):
        def fake(*argv):
            if argv[0] == "ip6tables":
                return b"-P OUTPUT DROP\n-A OUTPUT -d ::1/128 -j ACCEPT\n"
            return b"-P OUTPUT DROP\n" + b"-A OUTPUT -j ACCEPT\n" * 3

        with patch.object(attestor, "_run", side_effect=fake):
            with self.assertRaisesRegex(ValueError, "OUTPUT_NOT_CLOSED"):
                attestor._closed_rules(config())


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.policy = b"-P OUTPUT DROP\n\n-P OUTPUT DROP\n"
        self.key = Ed25519PrivateKey.generate()
        with patch.object(attestor.os, "stat") as stat_call:
            stat_call.return_value.st_ino = 1234
            self.signer = attestor.Attestor(config(), self.policy, self.key)
        self.request = {
            "deployment_id": "test-isolation",
            "host": "docs.example.org",
            "ip": "93.184.215.14",
            "namespace_inode": 1234,
            "nonce": "a" * 48,
            "policy_sha256": hashlib.sha256(self.policy).hexdigest(),
        }

    def test_each_request_rechecks_policy_and_signs_only_exact_challenge(self):
        with (
            patch.object(attestor, "_rules", return_value=self.policy) as rules,
            patch.object(attestor.os, "stat") as stat_call,
        ):
            stat_call.return_value.st_ino = 1234
            envelope = self.signer.receipt(self.request)
            self.assertEqual(rules.call_count, 1)
            self.assertIsNone(
                self.signer.receipt(self.request)
            )  # one nonce, one receipt
            self.assertTrue(envelope["receipt"]["isolation_verified"])
            self.key.public_key().verify(
                bytes.fromhex(envelope["signature"]),
                attestor.canonical(envelope["receipt"]),
            )
            with patch.object(
                attestor, "_rules", return_value=self.policy + b"-A OUTPUT -j ACCEPT"
            ):
                self.assertIsNone(self.signer.receipt(self.request))
            stat_call.return_value.st_ino = 9876
            self.assertIsNone(self.signer.receipt(self.request))

    def test_peer_uid_gid_and_real_namespace_are_checked(self):
        class Peer:
            def __init__(self, pid, uid, gid):
                self.value = struct.pack("3i", pid, uid, gid)

            def getsockopt(self, *_args):
                return self.value

        with (
            patch.object(attestor.os, "stat") as stat_call,
            patch.object(attestor.socket, "SO_PEERCRED", 17, create=True),
        ):
            stat_call.return_value.st_ino = 1234
            self.assertTrue(self.signer.peer_allowed(Peer(23, 65534, 65534)))
            self.assertFalse(self.signer.peer_allowed(Peer(23, 0, 65534)))
            self.assertFalse(self.signer.peer_allowed(Peer(23, 65534, 23456)))
            stat_call.return_value.st_ino = 9999
            self.assertFalse(self.signer.peer_allowed(Peer(23, 65534, 65534)))

    def test_host_ip_nonce_namespace_and_digest_are_bound(self):
        for field, value in (
            ("host", "other.example.org"),
            ("ip", "127.0.0.1"),
            ("nonce", "short"),
            ("namespace_inode", True),
            ("policy_sha256", "0" * 64),
            ("deployment_id", "other"),
        ):
            with (
                self.subTest(field=field),
                patch.object(attestor, "_rules", return_value=self.policy),
            ):
                self.assertIsNone(self.signer.receipt({**self.request, field: value}))


if __name__ == "__main__":
    unittest.main()
