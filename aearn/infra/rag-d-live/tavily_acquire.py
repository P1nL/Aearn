"""Explicit Tavily acquisition for the internal D lane. No direct-fetch fallback."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from uuid import UUID

API = Path(__file__).resolve().parents[2] / 'services' / 'api'
C = Path(__file__).resolve().parents[1] / 'rag-c-live'
CONTROL = Path(__file__).resolve().parents[1] / 'rag-c-source-control'
for path in (API, C, CONTROL):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402
from app.services.grounding.autonomous.tavily_capture_repository import TavilyCaptureRepository  # noqa: E402
from app.services.grounding.autonomous.tavily_extract import HttpxTavilyExtractTransport, TavilyExtractError  # noqa: E402
from control_runtime import DB, _absolute, _root_file, _root_json  # noqa: E402
from protocol import Scope  # noqa: E402
from review_operator import _private_output  # noqa: E402

CONFIG_FIELDS = {'format', 'provider', 'approved', 'database_name', 'dsn_secret_path', 'scope'}


class TavilyOperatorDenied(ValueError):
    pass


def load_tavily_config(path: Path) -> tuple[dict, str, Scope]:
    config, _ = _root_json(_absolute(str(path)))
    if (set(config) != CONFIG_FIELDS or config['format'] != 'aearn.tavily-acquisition.v1'
            or config['provider'] != 'tavily' or config['approved'] is not True
            or type(config['database_name']) is not str or DB.fullmatch(config['database_name']) is None):
        raise TavilyOperatorDenied('TAVILY_CONFIG_DENIED')
    dsn = _root_file(_absolute(config['dsn_secret_path']), limit=4096)[0].decode().strip()
    if psycopg.conninfo.conninfo_to_dict(dsn).get('dbname') != config['database_name']:
        raise TavilyOperatorDenied('DATABASE_DENIED')
    return config, dsn, Scope.from_wire(config['scope'])


def acquire(args: argparse.Namespace) -> dict[str, object]:
    if not args.execute or os.name != 'posix' or os.geteuid() != 0:
        raise TavilyOperatorDenied('TAVILY_OPERATOR_DEFAULT_OFF')
    config, dsn, scope = load_tavily_config(args.config)
    output = _private_output(_absolute(str(args.output)))
    if output.exists():
        raise TavilyOperatorDenied('OPERATION_OUTPUT_EXISTS')
    key = _root_file(_absolute(str(args.api_key_file)), limit=512)[0].decode().strip()
    transport = HttpxTavilyExtractTransport(api_key=key, enabled=True, max_content_bytes=scope.max_bytes)
    body = {'urls': [scope.url], 'extract_depth': 'advanced', 'format': 'markdown',
            'timeout': 60, 'include_images': False, 'include_favicon': False, 'include_usage': True}
    request_hash = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        if conn.execute('SELECT current_database() AS name').fetchone()['name'] != config['database_name']:
            raise TavilyOperatorDenied('DATABASE_DENIED')
        attempt_id = TavilyCaptureRepository(conn).dispatch(
            policy_id=scope.policy_id, generation=scope.generation,
            operation_key=args.operation_key, request_sha256=request_hash,
            content_format='markdown', extract_depth='advanced', attempt_id=UUID(scope.dispatch_id),
        )
    try:
        result = transport.extract(scope.url, extract_depth='advanced', content_format='markdown')
    except TavilyExtractError as exc:
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            TavilyCaptureRepository(conn).fail(attempt_id=attempt_id, error_code=exc.code,
                                               unknown=exc.code in {'tavily_extract_timeout', 'transport_unavailable'})
        raise TavilyOperatorDenied('TAVILY_' + exc.code.upper()) from None
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        capture_id = TavilyCaptureRepository(conn).settle(
            attempt_id=attempt_id, result=result, capture_id=args.capture_id,
        )
    summary = {
        'status': 'provider_capture_settled', 'provider': 'tavily',
        'representation': 'provider_extracted_markdown', 'origin_html_capture': False,
        'origin_transport_attested': False,
        'attempt_id': str(attempt_id), 'capture_id': str(capture_id),
        'provider_request_id': result.request_id, 'usage_credits': result.usage_credits,
        'captured_bytes': len(result.content.encode()), 'content_sha256': result.content_sha256,
        'response_sha256': result.response_sha256, 'received_at': result.received_at.isoformat(),
        'api_requests': 1, 'direct_origin_fetch_requests': 0,
        'reviewed': False, 'public_release': False,
    }
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as out:
        json.dump(summary, out, sort_keys=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--api-key-file', type=Path, required=True)
    parser.add_argument('--capture-id', type=UUID, required=True)
    parser.add_argument('--operation-key', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(acquire(args), sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({'status': 'blocked', 'code': str(exc) if type(exc) is TavilyOperatorDenied
                          else 'TAVILY_ACQUISITION_FAILED'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
