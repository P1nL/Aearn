"""Offline-only C composition tests; no PG, Docker, socket, DNS or HTTP."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import stat
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
API = ROOT.parents[1] / "services" / "api"
sys.path.insert(0, str(ROOT.parent / "rag-c-source-control"))
sys.path.insert(0, str(API))
MODULE = importlib.util.spec_from_file_location("rag_c_control_runtime", ROOT / "control_runtime.py")
assert MODULE and MODULE.loader
runtime = importlib.util.module_from_spec(MODULE)
MODULE.loader.exec_module(runtime)


def config():
    root = Path.cwd().anchor
    scope = {
        "policy_id": "registered.once", "generation": 1,
        "source_handle": "sqlite.select", "subject_id": "route.sql",
        "subject_version": "v1", "facets": ["queries"],
        "url": "https://www.sqlite.org/lang_select.html", "host": "www.sqlite.org",
        "path": "/lang_select.html", "root_id": "source.once",
        "dispatch_id": str(uuid4()), "max_bytes": 1024 * 1024,
    }
    b_key = bytes.fromhex("a1" * 32)
    pin = {
        "public_key_hex": b_key.hex(),
        "public_key_sha256": hashlib.sha256(b_key).hexdigest(),
        "deployment_id": "b-one", "policy_sha256": "a" * 64,
        "namespace_inode": 12345, "allowed_ips": ["8.8.8.8"],
    }
    return {
        "approved": True, "database_name": "aearn_rag260_c_test",
        "dsn_secret_path": str(Path(root) / "operator" / "dsn"),
        "directory": str(Path(root) / "run" / "rag-c-control"),
        "arm_path": str(Path(root) / "operator" / "arm.json"),
        "scope": scope, "b_attestor": pin, "worker_uid": 12001,
        "worker_gid": 12002, "trusted_gid": 12003,
        "worker_image_sha256": "b" * 64, "deployment_id": "c-one",
    }


class ControlRuntimeTests(unittest.TestCase):
    def build(self, data=None):
        data = data or config()
        # Preserve real GrantServer/signature and verifier construction; replace
        # only the DB callback so a test can assert the dispatch ordering.
        def fake_callbacks(**kwargs):
            owner = kwargs["dispatch_owner"]
            return SimpleNamespace(
                resolver=lambda scope, now: (
                    runtime.Decision(scope.max_bytes, now.replace(year=now.year + 1))
                    if owner.resolve(runtime.RegisteredSourceScope(
                        **{**vars(scope), "dispatch_id": uuid4_from(scope.dispatch_id)}), now=now)
                    else None
                ),
                proof_verifier=lambda *_: False,
                capture_store=lambda *_: None,
            )
        with patch.object(runtime, "make_host_callbacks", side_effect=fake_callbacks) as callbacks:
            instance = runtime.ControlRuntime(data, "dbname=aearn_rag260_c_test")
        self.assertIs(callbacks.call_args.kwargs["dispatch_owner"], instance._owner)
        self.assertEqual(callbacks.call_args.kwargs["worker_image_sha256"], "b" * 64)
        return instance

    def test_default_off_no_config_read_or_db(self):
        with patch.object(runtime, "_root_json") as read:
            with self.assertRaisesRegex(runtime.BridgeDenied, "DEFAULT_OFF"):
                runtime.build_runtime(Path("unused"))
            read.assert_not_called()

    def test_exact_config_and_secret_not_logged_or_worker_sourced(self):
        data = config()
        path = Path(data["dsn_secret_path"])
        with (patch.object(runtime, "_root_json", return_value=(data, None)),
              patch.object(runtime, "_root_file", return_value=(b"dbname=aearn_rag260_c_test", None)) as secret):
            instance = runtime.build_runtime(Path("unused"), approved=True)
        secret.assert_called_once_with(path, limit=4096)
        self.assertFalse(instance._attempted)
        self.assertEqual(instance._owner._dsn, "dbname=aearn_rag260_c_test")
        with patch.object(instance.server, "serve") as serve:
            instance.serve()
        serve.assert_called_once_with(instance.directory, approved=False)
        for changes in ({"extra": 1}, {"approved": False},
                        {"database_name": "production"},
                        {"b_attestor": {**data["b_attestor"], "extra": 1}},
                        {"worker_image_sha256": "latest"},
                        {"scope": {**data["scope"], "path": "/other"}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.build({**data, **changes})

    def test_first_grant_dispatches_once_then_two_permits_only(self):
        instance = self.build()
        issued = []
        remaining = 0
        def take(scope, **kwargs):
            nonlocal remaining
            issued.append((scope, kwargs))
            remaining = 2
            return scope.dispatch_id
        def resolve(scope, **kwargs):
            nonlocal remaining
            if not remaining:
                return None
            remaining -= 1
            return True
        instance._owner.take_dispatch = take
        instance._owner.resolve = resolve
        arm = {"request_hash": "c" * 64, "operation_key": "one.operation"}
        with patch.object(instance, "_approved_arm", return_value=arm) as read:
            for index in range(3):
                result = instance.server.resolver(instance.scope, runtime.datetime_now())
                self.assertEqual(result is not None, index < 2)
            read.assert_called_once()
        self.assertEqual(len(issued), 1)
        self.assertEqual(issued[0][0].dispatch_id, uuid4_from(instance.scope.dispatch_id))
        self.assertEqual(issued[0][1]["request_hash"], "c" * 64)
        self.assertTrue(instance._attempted)

    def test_root_arm_optional_supplemental_uuid_reaches_dispatch_only(self):
        instance = self.build()
        pub = instance.server.key.public_key().public_bytes(
            encoding=runtime.serialization.Encoding.Raw,
            format=runtime.serialization.PublicFormat.Raw)
        authorization_id = uuid4()
        arm = {
            "public_key_sha256": hashlib.sha256(pub).hexdigest(),
            "deployment_id": "c-one", "scope": instance.scope.wire(),
            "request_hash": "c" * 64, "operation_key": "one.operation",
            "expires_unix": int(time.time()) + 60,
            "b_attestor": instance._pin, "worker_image_sha256": instance._image,
            "supplemental_authorization_id": str(authorization_id),
        }
        key_info = SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_uid=0, st_ctime_ns=100)
        arm_info = SimpleNamespace(st_ctime_ns=101)
        with (patch.object(Path, "lstat", return_value=key_info),
              patch.object(Path, "read_bytes", return_value=pub),
              patch.object(runtime, "_root_json", return_value=(arm, arm_info)) as read):
            self.assertEqual(instance._approved_arm(), arm)
            for invalid in ("not-a-uuid", str(authorization_id).upper(), authorization_id, None):
                with self.subTest(invalid=invalid), patch.object(
                    runtime, "_root_json", return_value=(
                        {**arm, "supplemental_authorization_id": invalid}, arm_info)
                ), self.assertRaisesRegex(ValueError, "ARM_DENIED"):
                    instance._approved_arm()
            instance._owner.take_dispatch = MagicMock(return_value=uuid4_from(instance.scope.dispatch_id))
            instance._owner.resolve = MagicMock(return_value=True)
            self.assertIsNotNone(instance.server.resolver(instance.scope, runtime.datetime_now()))
            self.assertEqual(
                instance._owner.take_dispatch.call_args.kwargs["supplemental_authorization_id"],
                authorization_id,
            )
            self.assertEqual(instance._owner.take_dispatch.call_count, 1)
            self.assertEqual(read.call_count, 2)

    def test_wrong_scope_or_missing_arm_never_dispatches(self):
        instance = self.build()
        instance._owner.take_dispatch = MagicMock()
        wrong = runtime.Scope.from_wire({**instance.scope.wire(), "generation": 2})
        self.assertIsNone(instance.server.resolver(wrong, runtime.datetime_now()))
        with patch.object(instance, "_approved_arm", side_effect=ValueError("ARM_DENIED")):
            self.assertIsNone(instance.server.resolver(instance.scope, runtime.datetime_now()))
        instance._owner.take_dispatch.assert_not_called()
        self.assertFalse(instance._attempted)

    def test_dispatch_failure_terminal_even_with_second_arm(self):
        instance = self.build()
        instance._owner.take_dispatch = MagicMock(side_effect=ValueError("ALREADY_DISPATCHED"))
        instance._owner.resolve = MagicMock(return_value=None)
        with patch.object(instance, "_approved_arm", return_value={
            "request_hash": "c" * 64, "operation_key": "one.operation",
        }) as arm:
            self.assertIsNone(instance.server.resolver(instance.scope, runtime.datetime_now()))
            self.assertIsNone(instance.server.resolver(instance.scope, runtime.datetime_now()))
        arm.assert_called_once()
        instance._owner.take_dispatch.assert_called_once()
        self.assertTrue(instance._attempted)

    def test_arm_binds_independently_published_key_scope_b_and_image(self):
        instance = self.build()
        pub = instance.server.key.public_key().public_bytes(
            encoding=runtime.serialization.Encoding.Raw,
            format=runtime.serialization.PublicFormat.Raw)
        arm = {
            "public_key_sha256": hashlib.sha256(pub).hexdigest(),
            "deployment_id": "c-one", "scope": instance.scope.wire(),
            "request_hash": "c" * 64, "operation_key": "one.operation",
            "expires_unix": int(time.time()) + 60,
            "b_attestor": instance._pin, "worker_image_sha256": instance._image,
        }
        key_info = SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_uid=0, st_ctime_ns=100)
        arm_info = SimpleNamespace(st_ctime_ns=101)
        with (patch.object(Path, "lstat", return_value=key_info),
              patch.object(Path, "read_bytes", return_value=pub),
              patch.object(runtime, "_root_json", return_value=(arm, arm_info))):
            self.assertEqual(instance._approved_arm(), arm)
            for change in ({"request_hash": "not-a-hash"},
                           {"scope": {**arm["scope"], "generation": 2}},
                           {"worker_image_sha256": "d" * 64},
                           {"b_attestor": {**arm["b_attestor"], "policy_sha256": "d" * 64}},
                           {"public_key_sha256": "d" * 64},
                           {"expires_unix": int(time.time()) - 1},
                           {"extra": True}):
                with self.subTest(change=change), patch.object(
                    runtime, "_root_json", return_value=({**arm, **change}, arm_info)
                ), self.assertRaisesRegex(ValueError, "ARM_DENIED"):
                    instance._approved_arm()
            with patch.object(runtime, "_root_json", return_value=(arm, key_info)):
                with self.assertRaisesRegex(ValueError, "ARM_DENIED"):
                    instance._approved_arm()


def uuid4_from(value):
    from uuid import UUID
    return UUID(value)


# Explicit UTC factory, not a frozen fixture outside the DB clock tolerance.
def _datetime_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)

runtime.datetime_now = _datetime_now

if __name__ == "__main__":
    unittest.main()
