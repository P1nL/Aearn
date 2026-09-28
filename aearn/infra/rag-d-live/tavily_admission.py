"""Independent DB-only review of an already settled Tavily extraction."""
from __future__ import annotations

import argparse
from datetime import UTC, timedelta
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID

from tavily_acquire import load_tavily_config
import psycopg
from psycopg.rows import dict_row
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from app.services.grounding.autonomous.corpus_governance import CorpusGovernance, PostgresCorpusAuthority
from app.services.grounding.autonomous.source_review_repository import SourceReviewRepository
from app.services.grounding.autonomous.tavily_capture_repository import TavilyCaptureRepository
from app.services.grounding.autonomous.tavily_sqlite_review import (
    PROFILE, SignedTavilySQLiteReview, TavilySQLiteReviewVerifier,
    canonical_tavily_sqlite_review, sign_tavily_sqlite_review,
)
from automated_admission import KEY_ID, SERVICE_PUBLIC_SHA256, PURPOSE, RUN_ID, _snapshot, _existing_result
from control_runtime import _absolute, _root_file, _root_json
from review_operator import _private_output


def read_tavily_receipt(path: Path, *, run_id: str, corpus_id: UUID,
                        capture_id: UUID) -> SignedTavilySQLiteReview:
    doc, _ = _root_json(_absolute(str(path)))
    if (set(doc) != {'status', 'provider', 'run_id', 'corpus_id', 'capture_id',
                     'service_public_sha256', 'signed_review'}
            or doc['status'] != 'provisional_not_database_commit'
            or doc['provider'] != 'tavily' or doc['run_id'] != run_id
            or doc['corpus_id'] != str(corpus_id) or doc['capture_id'] != str(capture_id)
            or doc['service_public_sha256'] != SERVICE_PUBLIC_SHA256):
        raise ValueError('RECEIPT_MISMATCH')
    signed = SignedTavilySQLiteReview.model_validate_json(json.dumps(doc['signed_review']))
    if (signed.service_key_id != KEY_ID or signed.payload.capture_id != capture_id
            or signed.payload.profile != PROFILE or signed.payload.usages != (PURPOSE,)):
        raise ValueError('RECEIPT_MISMATCH')
    return signed


def admit(args: argparse.Namespace) -> dict[str, object]:
    if not args.execute or os.name != 'posix' or os.geteuid() != 0:
        raise ValueError('DEFAULT_OFF')
    if RUN_ID.fullmatch(args.run_id) is None or args.expected_active_generation < 0:
        raise ValueError('INPUT_DENIED')
    config, dsn, scope = load_tavily_config(args.config)
    private_bytes = _root_file(_absolute(str(args.service_private_key)), limit=64)[0]
    public = _root_file(_absolute(str(args.service_public_key)), limit=64)[0]
    private = Ed25519PrivateKey.from_private_bytes(private_bytes)
    if (hashlib.sha256(public).hexdigest() != SERVICE_PUBLIC_SHA256
            or private.public_key().public_bytes(serialization.Encoding.Raw,
                serialization.PublicFormat.Raw) != public):
        raise ValueError('SERVICE_PIN_DENIED')
    output = _private_output(_absolute(str(args.receipt_output)))
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        if conn.execute('SELECT current_database() AS name').fetchone()['name'] != config['database_name']:
            raise ValueError('DATABASE_DENIED')
        now = conn.execute('SELECT clock_timestamp() AS now').fetchone()['now'].astimezone(UTC)
        provenance = TavilyCaptureRepository(conn)
        reviewer = SourceReviewRepository(conn, registered_provider_captures=provenance)
        capture, row = reviewer._capture(args.capture_id, 'registered', now)
        if (capture.source_handle != scope.source_handle
                or capture.scope.subject_id != scope.subject_id
                or capture.scope.subject_version != scope.subject_version
                or capture.scope.facets != scope.facets or capture.final_url != scope.url
                or row['policy_id'] != scope.policy_id or row['policy_generation'] != scope.generation
                or row['root_id'] != scope.root_id or row['provider_attempt_id'] != UUID(scope.dispatch_id)
                or len(capture.body) > scope.max_bytes):
            raise ValueError('SCOPE_DENIED')
        governance = CorpusGovernance(conn, authority=PostgresCorpusAuthority(),
            source_reviews=reviewer, isolated_operator_enabled=True)
        active = governance.repo.active(scope.subject_id)
        receipt_exists = output.exists()
        if receipt_exists:
            signed = read_tavily_receipt(output, run_id=args.run_id,
                corpus_id=args.corpus_id, capture_id=args.capture_id)
        else:
            if conn.execute('SELECT 1 FROM grounding_corpus_versions WHERE id=%s', (args.corpus_id,)).fetchone():
                raise ValueError('RECEIPT_MISSING')
            if (active.generation if active else 0) != args.expected_active_generation:
                raise ValueError('ACTIVE_GENERATION_STALE')
            expires = min(now + timedelta(hours=24), row['expires_at'],
                          row['policy_retention'], row['retention_until'])
            signed = sign_tavily_sqlite_review(capture, provenance=provenance,
                private_key=private, service_key_id=KEY_ID, now=now, expires_at=expires, enabled=True)
        verifier = TavilySQLiteReviewVerifier(review=signed, service_key_id=KEY_ID,
            service_public_key=public, provenance=provenance, enabled=True)
        reviewer.verifier = verifier
        excerpts = reviewer.reviewed_excerpts(capture)
        if not excerpts or verifier.verify(capture).mode != 'production':
            raise ValueError('REVIEW_DENIED')
        candidate, source, document, chunks, document_id = _snapshot(
            capture=capture, row=row, scope=scope, corpus_id=args.corpus_id, excerpts=excerpts)
        if receipt_exists:
            completed = _existing_result(conn, governance, active=active, corpus_id=args.corpus_id,
                capture_id=args.capture_id, run_id=args.run_id, expected_generation=args.expected_active_generation)
            if completed is not None:
                return {**completed, 'provider': 'tavily', 'representation': 'provider_extracted_markdown'}
        if (active.generation if active else 0) != args.expected_active_generation:
            raise ValueError('ACTIVE_GENERATION_STALE')
        if not receipt_exists:
            raw = json.dumps({'status': 'provisional_not_database_commit', 'provider': 'tavily',
                'run_id': args.run_id, 'corpus_id': str(args.corpus_id), 'capture_id': str(args.capture_id),
                'service_public_sha256': SERVICE_PUBLIC_SHA256,
                'signed_review': json.loads(canonical_tavily_sqlite_review(signed))},
                sort_keys=True, separators=(',', ':')).encode()
            if len(raw) > 8192:
                raise ValueError('RECEIPT_OVERSIZE')
            fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as out:
                out.write(raw)
                out.flush()
                os.fsync(out.fileno())
        review_id = reviewer.review_and_admit(capture_id=args.capture_id, lane='registered',
            document_handle=document_id, requested_usages=(PURPOSE,), now=now)
        admission = conn.execute('SELECT id FROM rag_source_admissions WHERE review_id=%s AND active '
            'AND revoked_at IS NULL AND allowed_usages=ARRAY[%s]::text[]', (review_id, PURPOSE)).fetchone()
        if admission is None:
            raise ValueError('ADMISSION_DENIED')
        governance.create_candidate(candidate, sources=(source,), documents=(document,), chunks=chunks,
            admissions={document_id: admission['id']}, purpose=PURPOSE, idempotency_key=f'{args.run_id}.create')
        governance.validate(args.corpus_id, expected_generation=0, purpose=PURPOSE,
            idempotency_key=f'{args.run_id}.validate')
        sealed = governance.repo.version(args.corpus_id)
        if sealed.summary_hash is None or sealed.coverage_summary != {
                'required': 2, 'covered': 1, 'gap': 1, 'partial': True}:
            raise ValueError('PARTIAL_COVERAGE_DENIED')
        governance.activate(args.corpus_id, expected_generation=args.expected_active_generation,
            summary_hash=sealed.summary_hash, purpose=PURPOSE, idempotency_key=f'{args.run_id}.activate')
    return {'status': 'partial_queries_activated_isolated_db', 'provider': 'tavily',
        'representation': 'provider_extracted_markdown', 'capture_id': str(args.capture_id),
        'corpus_id': str(args.corpus_id), 'gap': 'schema', 'consumer_enabled': False}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute', action='store_true')
    for name in ('config', 'service-private-key', 'service-public-key', 'receipt-output'):
        p.add_argument('--' + name, type=Path, required=True)
    for name in ('capture-id', 'corpus-id'):
        p.add_argument('--' + name, type=UUID, required=True)
    p.add_argument('--run-id', required=True)
    p.add_argument('--expected-active-generation', type=int, required=True)
    try:
        print(json.dumps(admit(p.parse_args()), sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({'status': 'blocked', 'code': 'TAVILY_ADMISSION_DENIED'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
