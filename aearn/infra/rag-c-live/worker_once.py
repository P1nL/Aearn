"""Default-off C one-shot worker; import is inert and never performs a GET.

Deployment layout (not wired into the offline image): this file is reviewed at
/opt/rag-c-live/worker_once.py, API sources at /opt/aearn/services/api, and
C bridge client/protocol/server at /opt/rag-c-source-control. The control
container alone owns the disposable database and the committed dispatch. The
worker gets only its two Unix sockets, DNS and the single public HTTPS target.

An operator MUST independently pin the actual final image digest, B's ephemeral
signer key/policy/namespace, and C's ephemeral bridge key/deployment in the
root-owned, read-only /etc/rag-c/worker-once.json before this module is invoked.
An in-container process cannot inspect Docker's actual image digest; the code
hash check below is an additional integrity brake, not image provenance or an
operator approval. No launcher, Compose live profile or auto retry is provided.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Callable

CONFIG = Path('/etc/rag-c/worker-once.json')
URL = 'https://www.sqlite.org/lang_select.html'
HOST = 'www.sqlite.org'
MAX_BODY_BYTES = 8 * 1024 * 1024
HASH = re.compile(r'[0-9a-f]{64}\Z')
IMAGE = re.compile(r'[^\s@]+@sha256:([0-9a-f]{64})\Z')
FIELDS = frozenset({
    'enabled', 'scope', 'request_hash', 'worker_uid', 'worker_gid',
    'supplementary_gids', 'expected_namespace_inode', 'worker_image_ref',
    'worker_code_sha256', 'b_socket', 'b_public_key_hex', 'b_public_key_sha256',
    'b_deployment_id', 'b_policy_sha256', 'b_trusted_gid', 'c_socket',
    'c_public_key_path', 'c_public_key_sha256', 'c_deployment_id', 'c_trusted_gid',
    'allowed_ips',
})
FIELDS_WITH_DEADLINE = FIELDS | {'deadline_seconds'}
FIELDS_ASSESSMENT = FIELDS | {'owned_b1d_assessment'}
FIELDS_ASSESSMENT_DEADLINE = FIELDS_WITH_DEADLINE | {'owned_b1d_assessment'}
FIELDS_COURSE = FIELDS | {'owned_b1d_course_sources'}
FIELDS_COURSE_DEADLINE = FIELDS_WITH_DEADLINE | {'owned_b1d_course_sources'}
DEFAULT_DEADLINE_SECONDS = 10.0
MAX_DEADLINE_SECONDS = 300.0


class WorkerDenied(ValueError):
    """Only bounded codes, never URL, body, keys or underlying exceptions."""


_WORKER_CODES = frozenset({
    'CONFIG_DENIED', 'ISOLATION_DENIED', 'DEPLOYMENT_DENIED', 'PIN_DENIED',
    'WORKER_DEFAULT_OFF', 'SCOPE_DENIED', 'TRANSPORT_DENIED',
    'GRANT_DENIED', 'FETCH_REPORT_DENIED',
})
_FETCH_CODES = frozenset({
    'URL_DENIED', 'ADDRESS_DENIED', 'DNS_DENIED', 'HEADER_DENIED',
    'DEADLINE_EXCEEDED', 'BODY_DENIED', 'COMPRESSED_LIMIT', 'EXPANDED_LIMIT',
    'CAPTURE_SCOPE_INVALID', 'REGISTERED_SCOPE_DENIED', 'LIVE_EGRESS_UNVERIFIED',
    'LIVE_RECEIPT_LIMIT', 'PORT_MISSING', 'CANCELLED', 'TRANSPORT_DENIED',
    'REDIRECT_LOOP', 'EGRESS_UNVERIFIED', 'CONNECTION_DENIED',
    'TLS_CERTIFICATE_DENIED', 'TLS_HANDSHAKE_DENIED', 'REDIRECT_DENIED',
    'RANGE_IGNORED', 'STATUS_DENIED', 'TYPE_DENIED', 'ENCODING_DENIED', 'HEAD_DENIED',
    'RANGE_DENIED', 'REDIRECT_LIMIT', 'HOP_GRANT_DENIED',
    'PROBE_POLICY_DENIED', 'RESPONSE_DENIED', 'EGRESS_CONFIG_DENIED',
})
_BRIDGE_CODES = frozenset({
    'CLIENT_DISABLED', 'PATH_DENIED', 'KEY_DENIED', 'FRAME_DENIED',
    'PEER_DENIED', 'RESPONSE_DENIED', 'SIGNATURE_DENIED', 'GRANT_DENIED',
    'BODY_DENIED', 'COMPLETION_DENIED', 'INVALID_FRAME', 'INVALID_SCOPE',
    'INVALID_REQUEST',
})


def _failure_code(exc: BaseException) -> str:
    """Only expose exact trusted exception types with explicit fixed codes."""
    if type(exc) is WorkerDenied and str(exc) in _WORKER_CODES:
        return str(exc)
    fetch_module = sys.modules.get('app.services.grounding.autonomous.safe_fetch')
    if (fetch_module is not None
            and type(exc) is getattr(fetch_module, 'SafeFetchDenied', None)
            and type(exc.code) is str and exc.code in _FETCH_CODES):
        return exc.code
    bridge_module = sys.modules.get('protocol')
    if (bridge_module is not None
            and type(exc) is getattr(bridge_module, 'BridgeDenied', None)
            and str(exc) in _BRIDGE_CODES):
        return str(exc)
    return 'WORKER_ONE_SHOT_DENIED'


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise WorkerDenied('CONFIG_DENIED')
        result[key] = value
    return result


def _root_file(path: Path) -> bytes:
    """Single open of a root-owned non-writable regular file under trusted dirs."""
    if os.name != 'posix' or not path.is_absolute() or '..' in path.parts:
        raise WorkerDenied('CONFIG_DENIED')
    for parent in path.parents:
        info = parent.lstat()
        if (info.st_uid != 0 or not stat.S_ISDIR(info.st_mode)
                or stat.S_IMODE(info.st_mode) & 0o022):
            raise WorkerDenied('CONFIG_DENIED')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if (info.st_uid != 0 or not stat.S_ISREG(info.st_mode)
                or stat.S_IMODE(info.st_mode) != 0o444 or info.st_size > 8192):
            raise WorkerDenied('CONFIG_DENIED')
        raw = os.read(fd, 8193)
        if len(raw) != info.st_size or len(raw) > 8192:
            raise WorkerDenied('CONFIG_DENIED')
        return raw
    finally:
        os.close(fd)


def _deadline_seconds(config: dict[str, Any]) -> float:
    value = config.get('deadline_seconds', DEFAULT_DEADLINE_SECONDS)
    if type(value) not in (int, float) or not 0 < value <= MAX_DEADLINE_SECONDS:
        raise WorkerDenied('CONFIG_DENIED')
    return float(value)


def load_config(path: Path = CONFIG) -> dict[str, Any]:
    try:
        data = json.loads(_root_file(path), object_pairs_hook=_unique)
        if (type(data) is not dict
                or frozenset(data) not in (FIELDS, FIELDS_WITH_DEADLINE, FIELDS_ASSESSMENT, FIELDS_ASSESSMENT_DEADLINE,
                                           FIELDS_COURSE, FIELDS_COURSE_DEADLINE)
                or data['enabled'] is not True):
            raise WorkerDenied('CONFIG_DENIED')
        _deadline_seconds(data)
        _owned_assessment(data)
        return data
    except (OSError, UnicodeError, TypeError, ValueError, KeyError) as exc:
        raise WorkerDenied('CONFIG_DENIED') from exc


def _identity(config: dict[str, Any]) -> None:
    """Fail closed before DNS, grant, attestor or TCP if isolation differs."""
    try:
        uid, gid = config['worker_uid'], config['worker_gid']
        bridge_gid, signer_gid = config['c_trusted_gid'], config['b_trusted_gid']
        groups = config['supplementary_gids']
        namespace = config['expected_namespace_inode']
        if (os.name != 'posix' or any(type(n) is not int or not 0 < n < 2**31
                                       for n in (uid, gid, bridge_gid, signer_gid))
                or type(groups) is not list or groups != sorted(set(groups))
                or len(groups) > 2 or set(groups) != {bridge_gid, signer_gid}
                or type(namespace) is not int or namespace <= 0
                or (os.getuid(), os.geteuid(), os.getgid(), os.getegid())
                != (uid, uid, gid, gid) or uid == 0
                or sorted(os.getgroups()) != groups
                or os.stat('/proc/self/ns/net').st_ino != namespace):
            raise WorkerDenied('ISOLATION_DENIED')
        status = {}
        for line in Path('/proc/self/status').read_text(encoding='ascii').splitlines():
            key, _, value = line.partition(':')
            status[key] = value.strip()
        if (int(status.get('CapEff', '-1'), 16) != 0
                or int(status.get('CapBnd', '-1'), 16) != 0
                or status.get('NoNewPrivs') != '1'):
            raise WorkerDenied('ISOLATION_DENIED')
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise WorkerDenied('ISOLATION_DENIED') from exc


def _ports() -> tuple[Any, ...]:
    """Fixed /opt import layout only; never load modules from config or cwd."""
    api = Path('/opt/aearn/services/api')
    bridge = Path('/opt/rag-c-source-control')
    if not api.is_dir() or not bridge.is_dir():
        raise WorkerDenied('DEPLOYMENT_DENIED')
    # The operator must mount reviewed immutable /opt trees, not a host source
    # bind. This function adds fixed import roots only after identity validation.
    sys.path[:0] = [str(api), str(bridge)]
    from app.services.grounding.autonomous.live_egress import LiveEgressAttestor, VerifiedEgressEnvelope
    from app.services.grounding.autonomous.pinned_tls_connector import PinnedTlsConnector
    from app.services.grounding.autonomous.public_dns import PublicDnsResolver
    from app.services.grounding.autonomous.registered_source_policy import (
        RegisteredSourceHopGrant, RegisteredSourceHopPolicy, RegisteredSourceScope,
    )
    from app.services.grounding.autonomous.safe_fetch import FetchLimits, FetchResult, SafeFetcher
    from client import GrantClient
    from protocol import Scope
    return (LiveEgressAttestor, VerifiedEgressEnvelope, PinnedTlsConnector,
            PublicDnsResolver, RegisteredSourceHopGrant, RegisteredSourceHopPolicy,
            RegisteredSourceScope, FetchLimits, FetchResult, SafeFetcher, GrantClient, Scope)


def _pins(config: dict[str, Any]) -> tuple[bytes, str]:
    """Validate all operator pins and the current code before any grant or DNS."""
    try:
        ref = config['worker_image_ref']
        match = IMAGE.fullmatch(ref) if type(ref) is str else None
        image = match.group(1) if match else None
        source_hash = config['worker_code_sha256']
        key = bytes.fromhex(config['b_public_key_hex'])
        addresses = config['allowed_ips']
        if (image is None or type(source_hash) is not str
                or HASH.fullmatch(source_hash) is None
                or hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != source_hash
                or len(key) != 32
                or hashlib.sha256(key).hexdigest() != config['b_public_key_sha256']
                or any(type(config[k]) is not str or HASH.fullmatch(config[k]) is None
                       for k in ('request_hash', 'b_policy_sha256', 'c_public_key_sha256'))
                or type(addresses) is not list or not 1 <= len(addresses) <= 16
                or len(set(addresses)) != len(addresses)
                or any(type(ip) is not str or str(ipaddress.IPv4Address(ip)) != ip
                       or not ipaddress.IPv4Address(ip).is_global for ip in addresses)):
            raise WorkerDenied('PIN_DENIED')
        for name in ('b_socket', 'c_socket', 'c_public_key_path'):
            value = config[name]
            if (type(value) is not str or not value.startswith('/') or '\x00' in value
                    or '..' in Path(value).parts):
                raise WorkerDenied('PIN_DENIED')
        for name in ('b_deployment_id', 'c_deployment_id'):
            value = config[name]
            if (type(value) is not str or re.fullmatch(r'[a-z][a-z0-9._:-]{2,79}', value) is None):
                raise WorkerDenied('PIN_DENIED')
        return key, image
    except (OSError, TypeError, ValueError, KeyError, OverflowError) as exc:
        raise WorkerDenied('PIN_DENIED') from exc


class _BridgeResolver:
    """Exactly two fresh, signed, current grants. No cached or third grant."""

    def __init__(self, client: Any, wire_scope: Any, domain_scope: Any):
        self.client = client
        self.wire_scope = wire_scope
        self.domain_scope = domain_scope
        self.calls = 0
        self.latest_nonce: str | None = None

    def resolve(self, scope: Any, *, now: datetime) -> Any:
        if (scope != self.domain_scope or self.calls >= 2
                or now.tzinfo is None or now.utcoffset() is None):
            return None
        self.calls += 1  # Consume even if the bridge times out or refuses.
        receipt, nonce = self.client.grant(self.wire_scope)
        self.latest_nonce = nonce
        expiry = datetime.fromtimestamp(receipt['expires_unix'], tz=timezone.utc)
        from app.services.grounding.autonomous.registered_source_policy import RegisteredSourceHopGrant
        return RegisteredSourceHopGrant(scope, True, receipt['max_bytes'], expiry)


def _report(config: dict[str, Any], scope: Any, result: Any,
            proof_type: type, result_type: type) -> dict[str, object]:
    """Worker-attributed report of *completed* SafeFetcher invariants only."""
    proof = result.egress_proof
    if (type(result) is not result_type or result.evidence_level != 'live_egress_attested'
            or result.capture_kind != 'full' or type(proof) is not proof_type
            or result.final_url != scope.url or result.hops != (scope.url,)
            or result.content_type not in ('text/html', 'text/plain', 'text/markdown')
            or type(result.body) is not bytes or not 0 < len(result.body) <= scope.max_bytes
            or result.expanded_bytes != len(result.body)
            or type(result.compressed_bytes) is not int
            or not 0 < result.compressed_bytes <= scope.max_bytes
            or hashlib.sha256(result.body).hexdigest() != result.sha256
            or type(result.pre_dial_unix_ms) is not int):
        raise WorkerDenied('FETCH_REPORT_DENIED')
    receipt = json.loads(proof.canonical_receipt)
    now_ms = __import__('time').time_ns() // 1_000_000
    if (type(receipt) is not dict or receipt.get('host') != scope.host
            or receipt.get('ip') not in config['allowed_ips']
            or type(receipt.get('nonce')) is not str
            or not result.pre_dial_unix_ms <= now_ms
            or not (receipt.get('expires_unix', 0) - 4) * 1000
            <= result.pre_dial_unix_ms < receipt['expires_unix'] * 1000):
        raise WorkerDenied('FETCH_REPORT_DENIED')
    # SafeFetcher accepts a full 200 only after exact pinned peer/TLS/header
    # checks and full bounded consumption; these are worker assertions, NOT
    # independently signed HTTP facts. The IP/nonce come from the B envelope.
    return {
        'v': 1, 'policy_id': scope.policy_id, 'generation': scope.generation,
        'root_id': scope.root_id, 'dispatch_id': scope.dispatch_id,
        'request_hash': config['request_hash'], 'url': result.final_url,
        'host': scope.host, 'ip': receipt['ip'], 'nonce': receipt['nonce'],
        'status': 200, 'redirects': len(result.hops) - 1,
        'tls_verified': True, 'peer_verified': True, 'capture_kind': result.capture_kind,
        'content_type': result.content_type, 'body_sha256': result.sha256,
        'body_bytes': result.expanded_bytes, 'wire_bytes': result.compressed_bytes,
        'pre_dial_unix_ms': result.pre_dial_unix_ms, 'reported_unix_ms': now_ms,
    }


def _owned_assessment(config: dict[str, Any]) -> bool:
    value = config.get('owned_b1d_assessment', False)
    course = config.get('owned_b1d_course_sources', False)
    if type(value) is not bool or type(course) is not bool or value and course:
        raise WorkerDenied('CONFIG_DENIED')
    return value


def _scope_allowed(config: dict[str, Any], scope: Any) -> bool:
    _owned_assessment(config)  # Validate both independent opt-ins before scope use.
    if config.get('owned_b1d_course_sources', False):
        targets = {
            ('https://docs.python.org/3/reference/simple_stmts.html', 'docs.python.org', '/3/reference/simple_stmts.html', 'route.python', ('fundamentals',)),
            ('https://www.sqlite.org/lang_expr.html', 'www.sqlite.org', '/lang_expr.html', 'route.sql', ('queries',)),
            ('https://www.sqlite.org/lang_corefunc.html', 'www.sqlite.org', '/lang_corefunc.html', 'route.sql', ('queries',)),
            ('https://en.wikibooks.org/wiki/Python_Programming/Variables_and_Strings', 'en.wikibooks.org', '/wiki/Python_Programming/Variables_and_Strings', 'route.python', ('fundamentals',)),
            ('https://learnxinyminutes.com/python/', 'learnxinyminutes.com', '/python/', 'route.python', ('fundamentals',)),
        }
        return ((scope.url, scope.host, scope.path, scope.subject_id, scope.facets) in targets
                and 0 < scope.max_bytes <= MAX_BODY_BYTES)
    if _owned_assessment(config):
        # Mirror the host's finite target tuples. The actual exact DB is checked
        # only by the credential-owning control; the worker never gets a DSN.
        targets = {
            ('https://docs.python.org/3/library/functions.html', 'docs.python.org', '/3/library/functions.html', 'route.python', ('fundamentals',)),
            ('https://docs.python.org/3/builtins/functions.html', 'docs.python.org', '/3/builtins/functions.html', 'route.python', ('fundamentals',)),
            (URL, HOST, '/lang_select.html', 'route.sql', ('queries',)),
        }
        return ((scope.url, scope.host, scope.path, scope.subject_id, scope.facets) in targets
                and 0 < scope.max_bytes <= MAX_BODY_BYTES)
    return (scope.url == URL and scope.host == HOST and scope.path == '/lang_select.html'
            and scope.subject_id == 'route.sql' and scope.facets == ('queries',)
            and scope.max_bytes <= MAX_BODY_BYTES)


def _capture_resolver(config: dict[str, Any], resolver_type: Any) -> Any:
    if _owned_assessment(config) or config.get('owned_b1d_course_sources', False):
        return resolver_type(operator_allowed_ips=tuple(config['allowed_ips']))
    return resolver_type()


async def run_once(config: dict[str, Any], *,
                   on_stage: Callable[[str], None] | None = None,
                   on_progress: Callable[[str, int, int | None, str], None] | None = None) -> str:
    """No dispatch creation, GET retry, body file, database or provider fallback."""
    def stage(value: str) -> None:
        if on_stage is not None:
            on_stage(value)

    if type(config) is not dict or config.get('enabled') is not True:
        raise WorkerDenied('WORKER_DEFAULT_OFF')
    deadline_seconds = _deadline_seconds(config)
    _owned_assessment(config)
    stage('identity')
    _identity(config)
    stage('pins')
    key, _image = _pins(config)
    stage('deployment')
    (Attestor, Proof, Connector, Resolver, Grant, Hop, DomainScope, Limits,
     Result, Fetcher, Client, WireScope) = _ports()
    stage('scope')
    scope = WireScope.from_wire(config['scope'])
    if not _scope_allowed(config, scope):
        raise WorkerDenied('SCOPE_DENIED')
    domain_scope = DomainScope(**{**vars(scope), 'dispatch_id': __import__('uuid').UUID(scope.dispatch_id)})
    stage('grant_setup')
    client = Client(
        socket_path=Path(config['c_socket']),
        public_key_path=Path(config['c_public_key_path']),
        pinned_key_sha256=config['c_public_key_sha256'],
        trusted_gid=config['c_trusted_gid'], deployment_id=config['c_deployment_id'],
    )
    grants = _BridgeResolver(client, scope, domain_scope)
    fetcher = Fetcher(
        resolver=_capture_resolver(config, Resolver), connector=Connector(max_body_bytes=scope.max_bytes,
                                                 on_progress=on_progress),
        egress=Attestor(socket_path=Path(config['b_socket']), public_key=key,
                        deployment_id=config['b_deployment_id'],
                        policy_sha256=config['b_policy_sha256'],
                        trusted_gid=config['b_trusted_gid']),
        hop_policy=Hop(domain_scope, resolver=grants),
        limits=Limits(compressed_bytes=scope.max_bytes, expanded_bytes=scope.max_bytes,
                      redirects=0, deadline_seconds=min(deadline_seconds, 30.0)),
        request_gzip=True,
        registered_full_deadline_seconds=deadline_seconds if deadline_seconds > 30 else None,
        on_progress=on_progress,
    )
    if fetcher.live_ready is not True:
        raise WorkerDenied('TRANSPORT_DENIED')
    # One invocation only; SafeFetcher validates both bridge grants, pinned
    # DNS/IP, B pre-dial signature, TLS peer, no redirects and both byte caps.
    stage('fetch')
    result = await fetcher.fetch(scope.url, capture_kind='full')
    stage('postfetch')
    if grants.calls != 2 or grants.latest_nonce is None:
        raise WorkerDenied('GRANT_DENIED')
    _identity(config)
    stage('report')
    report = _report(config, scope, result, Proof, Result)
    proof = {'egress': result.egress_proof.as_envelope(), 'worker_fetch_report': report}
    stage('settlement')
    receipt = client.complete(scope, grant_nonce=grants.latest_nonce,
                              body=result.body, content_type=result.content_type,
                              attestor_proof=proof)
    return receipt['capture_id']


def main() -> None:
    if sys.argv[1:] != ['--once']:
        raise SystemExit('WORKER_DEFAULT_OFF')
    current_stage = 'config'
    progress = ''

    def set_stage(stage: str) -> None:
        nonlocal current_stage
        current_stage = stage

    def set_progress(stage: str, wire_bytes: int, length: int | None, encoding: str) -> None:
        nonlocal progress
        # Defence in depth: never interpolate arbitrary transport data or objects.
        if (type(stage) is not str or stage not in {'dns', 'signature', 'tls', 'headers', 'body'}
                or type(wire_bytes) is not int or not 0 <= wire_bytes <= MAX_BODY_BYTES
                or (length is not None and (type(length) is not int or not 0 <= length <= MAX_BODY_BYTES))
                or type(encoding) is not str or encoding not in {'unknown', 'identity', 'gzip'}):
            return
        progress = (f' fetch_stage={stage} wire_bytes={wire_bytes}'
                    f' content_length={length if length is not None else "unknown"} encoding={encoding}')

    try:
        config = load_config()
        # No raw response, exception text, URL or config enters stdout/stderr.
        asyncio.run(run_once(config, on_stage=set_stage, on_progress=set_progress))
    except BaseException as exc:
        raise SystemExit(
            f'WORKER_ONE_SHOT_DENIED stage={current_stage} code={_failure_code(exc)}{progress}'
        ) from None
    print('WORKER_ONE_SHOT_SETTLED')


if __name__ == '__main__':
    main()
