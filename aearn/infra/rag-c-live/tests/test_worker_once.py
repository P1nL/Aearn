"""Offline one-shot composition tests: no Docker, DNS, socket or GET."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'services' / 'api'))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'rag-c-source-control'))
from protocol import Scope
from app.services.grounding.autonomous.registered_source_policy import (
    RegisteredSourceHopGrant, RegisteredSourceHopPolicy, RegisteredSourceScope,
)
from app.services.grounding.autonomous.safe_fetch import FetchLimits, FetchResult, SafeFetchDenied
from protocol import BridgeDenied
from app.services.grounding.autonomous.live_egress import VerifiedEgressEnvelope

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('rag_c_worker_once', ROOT / 'worker_once.py')
assert spec and spec.loader
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def config() -> dict:
    return {
        'enabled': True,
        'scope': {
            'policy_id': 'sqlite.policy', 'generation': 1,
            'source_handle': 'sqlite.select', 'subject_id': 'route.sql',
            'subject_version': '2026-09', 'facets': ['queries'],
            'url': worker.URL, 'host': worker.HOST, 'path': '/lang_select.html',
            'root_id': 'sqlite.root', 'dispatch_id': str(uuid4()),
            'max_bytes': 1024 * 1024,
        },
        'request_hash': 'a' * 64, 'worker_uid': 65534,
        'worker_gid': 65534, 'supplementary_gids': [23456, 24567],
        'expected_namespace_inode': 12345,
        'worker_image_ref': 'example.invalid/egress@sha256:' + 'f' * 64,
        'worker_code_sha256': hashlib.sha256((ROOT / 'worker_once.py').read_bytes()).hexdigest(),
        'b_socket': '/run/rag-b/sign.sock',
        'b_public_key_hex': 'ab' * 32,
        'b_public_key_sha256': hashlib.sha256(bytes.fromhex('ab' * 32)).hexdigest(),
        'b_deployment_id': 'sqlite.egress', 'b_policy_sha256': 'b' * 64,
        'b_trusted_gid': 24567, 'c_socket': '/run/rag-c-control/grant.sock',
        'c_public_key_path': '/run/rag-c-control/public.key',
        'c_public_key_sha256': 'c' * 64, 'c_deployment_id': 'sqlite.bridge',
        'c_trusted_gid': 23456, 'allowed_ips': ['8.8.8.8'],
    }


def result(*, timestamp: int | None = None, expiry: int | None = None) -> FetchResult:
    body = b'<p>SELECT</p>'
    receipt = {
        'host': worker.HOST, 'ip': '8.8.8.8', 'nonce': 'd' * 48,
        'expires_unix': expiry if expiry is not None else int(time.time()) + 3,
    }
    proof = VerifiedEgressEnvelope(
        json.dumps(receipt, sort_keys=True, separators=(',', ':')).encode(), 'e' * 128,
    )
    return FetchResult(
        worker.URL, (worker.URL,), 'text/html', body,
        hashlib.sha256(body).hexdigest(), len(body), len(body),
        'live_egress_attested', object(), 'full', None, proof,
        timestamp if timestamp is not None else time.time_ns() // 1_000_000,
    )


class WorkerOnceTests(unittest.TestCase):
    def test_import_and_cli_are_default_off(self):
        with patch.object(worker.sys, 'argv', ['worker_once.py']):
            with self.assertRaisesRegex(SystemExit, 'WORKER_DEFAULT_OFF'):
                worker.main()
        with patch.object(worker, '_identity') as identity:
            with self.assertRaisesRegex(worker.WorkerDenied, 'WORKER_DEFAULT_OFF'):
                asyncio.run(worker.run_once({'enabled': False}))
            identity.assert_not_called()

    def test_cli_preserves_only_allowlisted_code_and_trusted_stage(self):
        for code in ('TLS_CERTIFICATE_DENIED', 'TLS_HANDSHAKE_DENIED',
                     'CONNECTION_DENIED', 'STATUS_DENIED'):
            with self.subTest(code=code):
                async def denied(_config, *, on_stage, on_progress):
                    on_stage('fetch')
                    raise SafeFetchDenied(code) from RuntimeError(
                        'private URL, body, and key must stay hidden'
                    )

                with (patch.object(worker.sys, 'argv', ['worker_once.py', '--once']),
                      patch.object(worker, 'load_config', return_value=config()),
                      patch.object(worker, 'run_once', side_effect=denied)):
                    with self.assertRaises(SystemExit) as caught:
                        worker.main()
                self.assertEqual(
                    str(caught.exception),
                    f'WORKER_ONE_SHOT_DENIED stage=fetch code={code}',
                )

        for failure, stage, expected in (
            (worker.WorkerDenied('CONFIG_DENIED'), 'config', 'CONFIG_DENIED'),
            (BridgeDenied('COMPLETION_DENIED'), 'settlement', 'COMPLETION_DENIED'),
            (SafeFetchDenied('LEAK=https://example.invalid/body/key'),
             'fetch', 'WORKER_ONE_SHOT_DENIED'),
            (RuntimeError('LEAK=https://example.invalid/body/key'),
             'fetch', 'WORKER_ONE_SHOT_DENIED'),
            (SystemExit('LEAK=https://example.invalid/body/key'),
             'fetch', 'WORKER_ONE_SHOT_DENIED'),
        ):
            with self.subTest(failure=type(failure).__name__, stage=stage):
                async def denied(_config, *, on_stage, on_progress):
                    on_stage(stage)
                    raise failure

                with (patch.object(worker.sys, 'argv', ['worker_once.py', '--once']),
                      patch.object(worker, 'load_config', return_value=config()),
                      patch.object(worker, 'run_once', side_effect=denied)):
                    with self.assertRaises(SystemExit) as caught:
                        worker.main()
                self.assertEqual(
                    str(caught.exception),
                    f'WORKER_ONE_SHOT_DENIED stage={stage} code={expected}',
                )

        with (patch.object(worker.sys, 'argv', ['worker_once.py', '--once']),
              patch.object(worker, 'load_config', side_effect=worker.WorkerDenied('CONFIG_DENIED'))):
            with self.assertRaises(SystemExit) as caught:
                worker.main()
        self.assertEqual(
            str(caught.exception),
            'WORKER_ONE_SHOT_DENIED stage=config code=CONFIG_DENIED',
        )

    def test_config_requires_explicit_enable_exact_fields_and_no_duplicates(self):
        cfg = config()
        for mutation in (dict(cfg, enabled=False), dict(cfg, extra=1)):
            with patch.object(worker, '_root_file', return_value=json.dumps(mutation).encode()):
                with self.assertRaisesRegex(worker.WorkerDenied, 'CONFIG_DENIED'):
                    worker.load_config()
        with patch.object(worker, '_root_file', return_value=b'{"enabled":true,"enabled":true}'):
            with self.assertRaisesRegex(worker.WorkerDenied, 'CONFIG_DENIED'):
                worker.load_config()
        with patch.object(worker, '_root_file', return_value=json.dumps(cfg).encode()):
            self.assertEqual(worker.load_config()['scope'], cfg['scope'])

    def test_pins_include_code_and_final_image_digest_not_tags(self):
        cfg = config()
        self.assertEqual(worker._pins(cfg)[1], 'f' * 64)
        for change in (
            {'worker_image_ref': 'egress:latest'},
            {'worker_code_sha256': '0' * 64},
            {'b_public_key_sha256': '0' * 64},
            {'allowed_ips': ['127.0.0.1']},
        ):
            with self.subTest(change=change):
                with self.assertRaisesRegex(worker.WorkerDenied, 'PIN_DENIED'):
                    worker._pins(dict(cfg, **change))

    def test_identity_denies_mismatch_before_grant(self):
        cfg = config()
        with patch.object(worker.os, 'name', 'posix'):
            with self.assertRaisesRegex(worker.WorkerDenied, 'ISOLATION_DENIED'):
                worker._identity(cfg)  # Windows host is never an egress worker.

    def test_grants_are_two_current_consumable_receipts_no_retry(self):
        scope = Scope.from_wire(config()['scope'])
        domain = RegisteredSourceScope(**{**vars(scope), 'dispatch_id': __import__('uuid').UUID(scope.dispatch_id)})
        class Client:
            calls = 0
            def grant(self, value):
                self.calls += 1
                return ({'expires_unix': int(time.time()) + 3,
                         'max_bytes': value.max_bytes}, str(self.calls))
        client = Client()
        bridge = worker._BridgeResolver(client, scope, domain)
        for expected in (1, 2):
            grant = bridge.resolve(domain, now=datetime.now(timezone.utc))
            self.assertEqual(grant.scope, domain)
            self.assertEqual(bridge.latest_nonce, str(expected))
        self.assertIsNone(bridge.resolve(domain, now=datetime.now(timezone.utc)))
        self.assertEqual(client.calls, 2)
        class Refuses(Client):
            def grant(self, value):
                raise ValueError('no permission')
        denied = worker._BridgeResolver(Refuses(), scope, domain)
        with self.assertRaises(ValueError):
            denied.resolve(domain, now=datetime.now(timezone.utc))
        self.assertEqual(denied.calls, 1)

    def test_report_requires_real_pre_dial_and_completed_result(self):
        cfg = config()
        scope = Scope.from_wire(cfg['scope'])
        good = result()
        report = worker._report(cfg, scope, good, VerifiedEgressEnvelope, FetchResult)
        self.assertEqual(report['pre_dial_unix_ms'], good.pre_dial_unix_ms)
        self.assertEqual(report['body_sha256'], good.sha256)
        self.assertEqual(report['wire_bytes'], good.compressed_bytes)
        self.assertEqual(report['nonce'], 'd' * 48)
        self.assertEqual(report['request_hash'], cfg['request_hash'])
        for bad in (
            result(timestamp=None).__class__(**{**vars(good), 'pre_dial_unix_ms': None}),
            FetchResult(**{**vars(good), 'sha256': '0' * 64}),
            FetchResult(**{**vars(good), 'evidence_level': 'offline_protocol_only'}),
            FetchResult(**{**vars(good), 'hops': (worker.URL, worker.URL)}),
            result(timestamp=(int(time.time()) - 20) * 1000),
        ):
            with self.assertRaisesRegex(worker.WorkerDenied, 'FETCH_REPORT_DENIED'):
                worker._report(cfg, scope, bad, VerifiedEgressEnvelope, FetchResult)

    def test_optional_deadline_is_bounded_in_root_config_before_any_io(self):
        cfg = config()
        with patch.object(worker, '_root_file', return_value=json.dumps(cfg).encode()):
            self.assertEqual(worker._deadline_seconds(worker.load_config()), 10.0)
        cfg['deadline_seconds'] = 300
        with patch.object(worker, '_root_file', return_value=json.dumps(cfg).encode()):
            self.assertEqual(worker._deadline_seconds(worker.load_config()), 300.0)
        for bad in (True, False, None, '300', 0, -1, 300.001, 301,
                    float('nan'), float('inf'), float('-inf'), 10**100):
            with self.subTest(value=repr(bad)):
                cfg['deadline_seconds'] = bad
                with patch.object(worker, '_root_file', return_value=json.dumps(cfg).encode()):
                    with self.assertRaisesRegex(worker.WorkerDenied, 'CONFIG_DENIED'):
                        worker.load_config()
                with patch.object(worker, '_identity') as identity:
                    with self.assertRaisesRegex(worker.WorkerDenied, 'CONFIG_DENIED'):
                        asyncio.run(worker.run_once(cfg))
                    identity.assert_not_called()

    def test_deadline_reaches_fetch_limits_without_changing_hard_bounds(self):
        observed = []

        class Port:
            def __init__(self, *args, **kwargs):
                pass

        class RefusingFetcher:
            def __init__(self, *, limits, request_gzip, registered_full_deadline_seconds, **kwargs):
                observed.append((limits, request_gzip, registered_full_deadline_seconds))
                self.live_ready = False

        for deadline in (None, 30, 300):
            cfg = config()
            cfg['scope']['max_bytes'] = 8 * 1024 * 1024
            if deadline is not None:
                cfg['deadline_seconds'] = deadline
            with (patch.object(worker, '_identity'),
                  patch.object(worker, '_pins', return_value=(b'k' * 32, 'f' * 64)),
                  patch.object(worker, '_ports', return_value=(
                      Port, object, Port, Port, RegisteredSourceHopGrant,
                      Port, RegisteredSourceScope, FetchLimits,
                      FetchResult, RefusingFetcher, Port, Scope))):
                with self.assertRaisesRegex(worker.WorkerDenied, 'TRANSPORT_DENIED'):
                    asyncio.run(worker.run_once(cfg))
            limits, request_gzip, override = observed[-1]
            self.assertIs(request_gzip, True)
            self.assertEqual(limits.deadline_seconds, 10.0 if deadline is None else 30.0)
            self.assertEqual(override, 300.0 if deadline == 300 else None)
            self.assertEqual(limits.compressed_bytes, 8 * 1024 * 1024)
            self.assertEqual(limits.expanded_bytes, 8 * 1024 * 1024)
            self.assertEqual(limits.redirects, 0)

    def test_cli_fetch_progress_is_closed_numeric_projection_only(self):
        async def denied(_config, *, on_stage, on_progress):
            on_stage('fetch')
            on_progress('body', 16384, 2033807, 'identity')
            on_progress('LEAK=https://secret.invalid/', 0, None, 'identity')
            on_progress('body', True, 1, 'identity')
            on_progress('body', 0, -1, 'identity')
            on_progress('body', 0, 1, 'SECRET')
            raise SafeFetchDenied('DEADLINE_EXCEEDED') from RuntimeError('private body')

        with (patch.object(worker.sys, 'argv', ['worker_once.py', '--once']),
              patch.object(worker, 'load_config', return_value=config()),
              patch.object(worker, 'run_once', side_effect=denied)):
            with self.assertRaises(SystemExit) as caught:
                worker.main()
        self.assertEqual(str(caught.exception),
                         'WORKER_ONE_SHOT_DENIED stage=fetch code=DEADLINE_EXCEEDED'
                         ' fetch_stage=body wire_bytes=16384 content_length=2033807 encoding=identity')

    def test_eight_mib_scope_passes_worker_gate_without_fetch(self):
        cfg = config()
        cfg['scope']['max_bytes'] = 8 * 1024 * 1024
        stages = []

        class RefusingClient:
            def __init__(self, **kwargs):
                raise worker.WorkerDenied('GRANT_DENIED')

        with (patch.object(worker, '_identity'),
              patch.object(worker, '_pins', return_value=(b'k' * 32, 'f' * 64)),
              patch.object(worker, '_ports', return_value=(
                  object, object, object, object, RegisteredSourceHopGrant,
                  RegisteredSourceHopPolicy, RegisteredSourceScope, object,
                  FetchResult, object, RefusingClient, Scope))):
            with self.assertRaisesRegex(worker.WorkerDenied, 'GRANT_DENIED'):
                asyncio.run(worker.run_once(cfg, on_stage=stages.append))
        self.assertEqual(stages[-1], 'grant_setup')
        self.assertNotIn('fetch', stages)

    def test_exact_scope_denied_before_any_fetch(self):
        cfg = config()
        cfg['scope']['facets'] = ['schema']
        stages = []
        with (patch.object(worker, '_identity'), patch.object(worker, '_pins', return_value=(b'k' * 32, 'f' * 64)),
              patch.object(worker, '_ports', return_value=(object, object, object, object,
                  RegisteredSourceHopGrant, RegisteredSourceHopPolicy, RegisteredSourceScope,
                  object, FetchResult, object, object, Scope))):
            with self.assertRaisesRegex(worker.WorkerDenied, 'SCOPE_DENIED'):
                asyncio.run(worker.run_once(cfg, on_stage=stages.append))
        self.assertEqual(stages, ['identity', 'pins', 'deployment', 'scope'])


if __name__ == '__main__':
    unittest.main()
