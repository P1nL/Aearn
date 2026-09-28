"""Offline protocol and Linux Unix peer tests. No Docker, PG, provider or network."""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
import socket
import struct
import sys
import threading
import time
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from client import GrantClient
from protocol import (
    BridgeDenied,
    MAX_BYTES,
    MAX_FRAME,
    TTL_SECONDS,
    Scope,
    canonical,
    decode,
    parse_request,
    request,
)
from server import CAPTURE_FRAME, COMPLETION_WINDOW, CaptureRecord, Decision, GrantServer


def scope() -> Scope:
    return Scope.from_wire(
        {
            "policy_id": "policy:one",
            "generation": 1,
            "source_handle": "source:one",
            "subject_id": "route.sql",
            "subject_version": "v1",
            "facets": ["queries"],
            "url": "https://www.sqlite.org/lang_select.html",
            "host": "www.sqlite.org",
            "path": "/lang_select.html",
            "root_id": "root:one",
            "dispatch_id": str(uuid4()),
            "max_bytes": MAX_BYTES,
        }
    )


class WireTests(unittest.TestCase):
    def test_scope_exact_and_canonical_wire(self):
        value = scope().wire()
        self.assertEqual(Scope.from_wire(value).wire(), value)
        for change in (
            {"path": "/other"},
            {"host": "127.0.0.1"},
            {"facets": ["queries", "queries"]},
            {"max_bytes": True},
            {"url": "https://www.sqlite.org/other"},
            {"dispatch_id": "fake"},
            {"extra": True},
        ):
            with self.subTest(change=change), self.assertRaises(BridgeDenied):
                Scope.from_wire({**value, **change})

    def test_body_cap_is_eight_mib_but_smaller_scopes_remain_valid(self):
        value = scope().wire()
        self.assertEqual(value["max_bytes"], 8 * 1024 * 1024)
        self.assertEqual(Scope.from_wire({**value, "max_bytes": 2 * 1024 * 1024}).max_bytes,
                         2 * 1024 * 1024)
        with self.assertRaises(BridgeDenied):
            Scope.from_wire({**value, "max_bytes": MAX_BYTES + 1})

    def test_duplicate_fields_and_noncanonical_refused(self):
        with self.assertRaises(BridgeDenied):
            decode(b'{"nonce":"a","nonce":"b"}')
        with self.assertRaises(BridgeDenied):
            decode(b'{ "a":1}')
        with self.assertRaises(BridgeDenied):
            parse_request(
                {**request(scope(), "a" * 48, "test-deployment"), "unexpected": True},
                "test-deployment",
            )


class ClientTests(unittest.TestCase):
    def test_completion_frame_and_settlement_have_longer_io_timeout_than_grant(self):
        class Key:
            def verify(self, *_args):
                pass  # This test checks socket deadlines, not signature verification.

        class Connection:
            def __init__(self):
                self.timeouts = []
                self.response = b""

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

            def settimeout(self, value):
                self.timeouts.append(value)

            def connect(self, _path):
                pass

            def getsockopt(self, *_args):
                return struct.pack("3i", 1, 0, 0)

            def sendall(self, raw):
                payload = decode(raw.rstrip(b"\n"), max_bytes=CAPTURE_FRAME)
                receipt = {
                    "v": 1, "deployment_id": payload["deployment_id"],
                    "scope": payload["scope"], "nonce": payload["nonce"],
                }
                if payload["op"] == "grant":
                    receipt.update(allowed=True, max_bytes=MAX_BYTES,
                                   expires_unix=int(time.time()) + 3)
                else:
                    receipt.update(grant_nonce=payload["grant_nonce"],
                                   capture_id=str(uuid4()), sha256=payload["sha256"],
                                   captured_bytes=3)
                self.response = canonical({"receipt": receipt, "signature": "0" * 128}) + b"\n"

            def recv(self, _count):
                result, self.response = self.response, b""
                return result

        client = object.__new__(GrantClient)
        client.socket_path = Path("/fixture.sock")
        client.public_key_path = Path("/fixture.key")
        client.trusted_gid = 1003
        client.deployment_id = "test-deployment"
        connections = []

        def socket_factory(*_args):
            connection = Connection()
            connections.append(connection)
            return connection

        with patch.object(client, "_key", return_value=Key()), \
             patch("client._trusted_path", return_value=SimpleNamespace(st_ino=1, st_dev=1)), \
             patch("client.socket.socket", side_effect=socket_factory), \
             patch.object(socket, "SO_PEERCRED", 17, create=True), \
             patch.object(socket, "AF_UNIX", 1, create=True):
            requested = scope()
            _receipt, grant_nonce = client.grant(requested)
            client.complete(requested, grant_nonce=grant_nonce, body=b"sql",
                            content_type="text/html", attestor_proof={"fixture": True})
        self.assertEqual([conn.timeouts for conn in connections], [[2, 2.0], [2, 30.0]])

    def test_eight_mib_grant_receipt_is_allowed_without_widening_grant_frame(self):
        client = object.__new__(GrantClient)
        client.deployment_id = "test-deployment"
        requested = scope()

        def roundtrip(payload, *, max_request=MAX_FRAME):
            self.assertEqual(max_request, MAX_FRAME)
            self.assertLessEqual(len(canonical(payload)), MAX_FRAME)
            return {
                "v": 1, "deployment_id": "test-deployment",
                "scope": payload["scope"], "nonce": payload["nonce"],
                "allowed": True, "max_bytes": MAX_BYTES,
                "expires_unix": int(time.time()) + 3,
            }

        with patch.object(client, "_roundtrip", side_effect=roundtrip):
            receipt, _ = client.grant(requested)
        self.assertEqual(receipt["max_bytes"], MAX_BYTES)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.scope = scope()
        self.calls = []
        self.stored = []
        self.approved = True
        self.srv = GrantServer(
            resolver=lambda s, now: (
                self.calls.append(s) or Decision(MAX_BYTES, now + timedelta(minutes=1))
            ),
            deployment_id="test-deployment",
            worker_uid=1001,
            worker_gid=1002,
            trusted_gid=1003,
            proof_verifier=lambda s, proof: (
                self.approved and proof == {"verified": "test"}
            ),
            capture_store=self._store,
        )

    def _store(self, s, body, content_type, digest, proof, now, peer_socket):
        self.stored.append((s, body, content_type, digest, proof, now, peer_socket))
        return CaptureRecord(str(uuid4()))

    def _grant(self):
        nonce = os.urandom(24).hex()
        value = request(self.scope, nonce, "test-deployment")
        envelope = decode(self.srv._grant(value))
        self.srv.key.public_key().verify(
            bytes.fromhex(envelope["signature"]), canonical(envelope["receipt"])
        )
        return nonce, envelope["receipt"]

    def _completion(self, grant_nonce, body=b"SELECT * FROM x", **updates):
        value = {
            "v": 1,
            "deployment_id": "test-deployment",
            "nonce": os.urandom(24).hex(),
            "grant_nonce": grant_nonce,
            "scope": self.scope.wire(),
            "final_url": self.scope.url,
            "hops": [self.scope.url],
            "content_type": "text/html",
            "sha256": hashlib.sha256(body).hexdigest(),
            "body_b64": base64.b64encode(body).decode(),
            "attestor_proof": {"verified": "test"},
        }
        return {**value, **updates}

    def test_grant_current_callback_and_nonce_replay(self):
        nonce, receipt = self._grant()
        self.assertEqual(self.calls, [self.scope])
        self.assertLessEqual(receipt["expires_unix"], time.time() + 4)
        with self.assertRaisesRegex(BridgeDenied, "REPLAY_DENIED"):
            self.srv._grant(request(self.scope, nonce, "test-deployment"))

    def test_capture_requires_exact_digest_proof_and_one_issued_grant(self):
        nonce, _ = self._grant()
        wire = self._completion(nonce)
        receipt = decode(self.srv._complete(wire))["receipt"]
        self.assertEqual(receipt["sha256"], wire["sha256"])
        self.assertEqual(receipt["captured_bytes"], len(b"SELECT * FROM x"))
        self.assertEqual(self.stored[0][1], b"SELECT * FROM x")
        with self.assertRaises(BridgeDenied):
            self.srv._complete(self._completion(nonce))
        self.assertEqual(len(self.stored), 1)

    def test_eight_mib_completion_fits_separate_frame_and_settles(self):
        nonce, _ = self._grant()
        body = b"x" * MAX_BYTES
        completion = self._completion(nonce, body, attestor_proof={
            "verified": "test", "metadata": "m" * 1500,
        })
        self.srv.proof_verifier = lambda s, proof: proof == completion["attestor_proof"]
        raw = canonical({"op": "complete", **completion})
        self.assertEqual(CAPTURE_FRAME, 4 * ((MAX_BYTES + 2) // 3) + 16_384)
        self.assertGreater(len(raw), MAX_FRAME)
        self.assertLessEqual(len(raw), CAPTURE_FRAME)
        parsed = decode(raw, max_bytes=CAPTURE_FRAME)
        parsed.pop("op")
        receipt = decode(self.srv._complete(parsed))["receipt"]
        self.assertEqual(receipt["captured_bytes"], MAX_BYTES)
        self.assertEqual(self.stored[0][1], body)

    def test_lower_policy_and_scope_still_deny_oversize(self):
        self.srv.resolver = lambda s, now: Decision(MAX_BYTES - 1, now + timedelta(minutes=1))
        with self.assertRaisesRegex(BridgeDenied, "GRANT_DENIED"):
            self._grant()
        self.assertFalse(self.stored)

        self.scope = Scope.from_wire({**self.scope.wire(), "max_bytes": 1024 * 1024})
        nonce, _ = self._grant()
        with self.assertRaisesRegex(BridgeDenied, "COMPLETION_DENIED"):
            self.srv._complete(self._completion(nonce, b"x" * (self.scope.max_bytes + 1)))
        self.assertFalse(self.stored)

    def test_denials_never_store_and_consume_issue(self):
        invalid = [
            lambda w: {**w, "hops": [self.scope.url, "https://other.example/"]},
            lambda w: {**w, "sha256": "0" * 64},
            lambda w: {**w, "content_type": "application/octet-stream"},
            lambda w: {**w, "final_url": "https://other.example/"},
            lambda w: {
                **w,
                "body_b64": base64.b64encode(b"x" * (MAX_BYTES + 1)).decode(),
            },
            lambda w: {**w, "attestor_proof": {"unverified": True}},
        ]
        for alter in invalid:
            with self.subTest(alter=alter):
                nonce, _ = self._grant()
                with self.assertRaises(BridgeDenied):
                    self.srv._complete(alter(self._completion(nonce)))
                self.assertNotIn(nonce, self.srv._issued)
        self.assertFalse(self.stored)

    def test_expired_issue_and_current_resolver_denial(self):
        nonce, _ = self._grant()
        self.srv._issued[nonce] = (self.scope, time.time() - 1)
        with self.assertRaises(BridgeDenied):
            self.srv._complete(self._completion(nonce))
        self.assertFalse(self.stored)
        self.srv.resolver = lambda s, now: None
        with self.assertRaises(BridgeDenied):
            self._grant()

    def test_completion_window_extends_only_settlement_not_signed_dial_grant(self):
        self.assertEqual(TTL_SECONDS, 4)
        self.assertEqual(COMPLETION_WINDOW, 360)
        started = time.time()
        with patch('server.time.time', return_value=started):
            nonce, receipt = self._grant()
        self.assertLessEqual(receipt['expires_unix'], started + 4)
        self.assertEqual(self.srv._issued[nonce][1], started + 360)
        with patch('server.time.time', return_value=started + 300):
            with self.assertRaisesRegex(BridgeDenied, 'REPLAY_DENIED'):
                self.srv._grant(request(self.scope, nonce, 'test-deployment'))
            self.srv._complete(self._completion(nonce))
            with self.assertRaises(BridgeDenied):
                self.srv._complete(self._completion(nonce))
        self.assertEqual(len(self.stored), 1)

    def test_completion_at_hard_expiry_is_denied_and_nonce_cache_stays_bounded(self):
        started = time.time()
        with patch('server.time.time', return_value=started):
            nonce, _ = self._grant()
        with patch('server.time.time', return_value=started + 360):
            with self.assertRaisesRegex(BridgeDenied, 'COMPLETION_DENIED'):
                self.srv._complete(self._completion(nonce))
        self.assertFalse(self.stored)
        with patch('server.time.time', return_value=started):
            self.srv._seen = {f'{i:048x}': started + 360 for i in range(4096)}
            with self.assertRaisesRegex(BridgeDenied, 'REPLAY_DENIED'):
                self.srv._nonce('f' * 48)
        self.assertEqual(len(self.srv._seen), 4096)

    def test_serve_never_starts_without_operator_approval(self):
        with self.assertRaisesRegex(BridgeDenied, "DEFAULT_OFF"):
            self.srv.serve(Path("/run/rag-control"))

    def test_default_off_completion_without_host_authorities(self):
        self.srv.proof_verifier = None
        nonce, _ = self._grant()
        with self.assertRaises(BridgeDenied):
            self.srv._complete(self._completion(nonce))
        self.assertFalse(self.stored)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux SO_PEERCRED only")
    def test_unix_socket_rejects_wrong_peer_without_resolver(self):
        self.srv.worker_uid = os.getuid() + 1
        left, right = socket.socketpair(socket.AF_UNIX)
        try:
            # Current UID cannot equal fake configured worker UID on normal runner.
            thread = threading.Thread(target=self.srv.handle, args=(left,))
            right.sendall(
                canonical(
                    {
                        "op": "grant",
                        **request(self.scope, os.urandom(24).hex(), "test-deployment"),
                    }
                )
                + b"\n"
            )
            thread.start()
            right.shutdown(socket.SHUT_WR)
            try:
                self.assertEqual(right.recv(10), b"")
            except ConnectionResetError:
                pass
            thread.join(timeout=3)
            self.assertEqual(self.calls, [])
        finally:
            left.close()
            right.close()

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux Unix socket only")
    def test_unix_frame_complete_offline_with_peer_fixture(self):
        nonce, _ = self._grant()
        left, right = socket.socketpair(socket.AF_UNIX)
        with patch("server._peer", return_value=True):
            thread = threading.Thread(target=self.srv.handle, args=(left,))
            thread.start()
            right.sendall(
                canonical({"op": "complete", **self._completion(nonce)}) + b"\n"
            )
            self.assertIn("receipt", decode(right.recv(4096).rstrip(b"\n")))
            thread.join(timeout=3)
        right.close()


class PublicKeyModeTests(unittest.TestCase):
    def test_root_owned_public_key_may_be_world_readable_not_writable(self):
        import stat
        from types import SimpleNamespace
        from client import _trusted_path

        key_path = Path.cwd() / "public.key"
        for mode, allowed in ((0o644, True), (0o640, True), (0o664, False), (0o646, False)):
            def info(path):
                return SimpleNamespace(st_uid=0, st_gid=0, st_mode=(
                    stat.S_IFREG | mode if path == key_path else stat.S_IFDIR | 0o755
                ))
            with patch("client.Path.lstat", autospec=True, side_effect=info):
                if allowed:
                    self.assertEqual(_trusted_path(key_path, kind="key").st_uid, 0)
                else:
                    with self.assertRaises(BridgeDenied):
                        _trusted_path(key_path, kind="key")


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux SO_PEERCRED only")
class CrossNamespacePeerTests(unittest.TestCase):
    def test_pid_zero_with_exact_worker_uid_gid_is_allowed(self):
        from server import _peer

        class Remote:
            def getsockopt(self, *_):
                return struct.pack("3i", 0, 65534, 23456)

        self.assertTrue(_peer(Remote(), 65534, 23456))
        self.assertFalse(_peer(Remote(), 65535, 23456))
        self.assertFalse(_peer(Remote(), 65534, 23457))


if __name__ == "__main__":
    unittest.main()
