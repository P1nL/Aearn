"""Main-only current source composition. Inert without --preflight; no GET/provider.

Public verification keys only. Never imports the old operator's private signer or
replays source dispatch. New owner scripts may reuse these exact compositions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import site
import sys
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[4]
DB = 'aearn_b1d_sandbox_20261001'
CURRENT = ROOT / '.runtime/e-resume-20261006'
CAPTURES = ROOT / '.runtime/source-refresh-20261006-capture-498-1'
TARGETS = ('python-kc-binding-v1', 'python-state-update-v1', 'sqlite-predicate-order-v1')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def configure_imports():
    os.environ['PYTHON_DOTENV_DISABLED'] = '1'
    sys.path[:0] = [str(ROOT / 'aearn/services/api'), str(ROOT / 'aearn/services/executor')]
    site.addsitedir(str(ROOT / 'aearn/services/executor/.venv/Lib/site-packages'))


def connection():
    import psycopg
    from psycopg.rows import dict_row
    cfg = read(ROOT / '.runtime/item-supply-sandbox-20261001/database.json')
    if cfg['database'] != DB:
        raise ValueError('explicit_isolated_database_required')
    conn = psycopg.connect(host=cfg['host'], port=cfg['port'], dbname=cfg['database'],
        user=cfg['role'], password=cfg['password'], row_factory=dict_row,
        connect_timeout=5, options='-c statement_timeout=30000 -c lock_timeout=5000',
        application_name='aearn-native-type-current-source')
    del cfg
    with conn.transaction():
        if conn.execute('SELECT current_database() AS n').fetchone()['n'] != DB:
            conn.close()
            raise ValueError('explicit_isolated_database_required')
    return conn


def public_authority(conn):
    from app.services.grounding.autonomous.registered_source_bridge_host import SignedDispatchProofVerifier
    from app.services.grounding.autonomous.registered_source_provenance import PostgresCurrentCaptureProvenanceResolver
    from app.services.grounding.autonomous.capture_provenance_composition import PinnedCaptureProvenanceComposition
    from app.services.grounding.autonomous.assessment_receipt_repository import AssessmentReceiptRepository
    from app.services.grounding.autonomous.public_python_teaching_review import SignedTeachingReview, PublicPythonTeachingVerifier
    from app.services.grounding.assessment_material_factory import compose_assessment_authority

    pin = read(ROOT / '.runtime/e-closure-20261003/source-service-public-pin.json')
    public = Path(pin['service_public_key']).read_bytes()
    if len(public) != 32 or hashlib.sha256(public).hexdigest() != pin['service_public_sha256']:
        raise ValueError('source_public_key_pin_mismatch')
    keys = {pin['service_key_id']: public}

    def provenance(name):
        meta = read(CAPTURES / name / 'external-pins.json')
        attestor = meta['b_attestor']
        key = bytes.fromhex(attestor['public_key_hex'])
        if len(key) != 32 or hashlib.sha256(key).hexdigest() != attestor['public_key_sha256']:
            raise ValueError('capture_public_key_pin_mismatch')
        verifier = SignedDispatchProofVerifier(public_key=key, deployment_id=attestor['deployment_id'],
            policy_sha256=attestor['policy_sha256'], namespace_inode=attestor['namespace_inode'],
            allowed_ips=frozenset(attestor['allowed_ips']))
        return PostgresCurrentCaptureProvenanceResolver(conn, verifier=verifier,
            worker_image_sha256=meta['worker_image_sha256'])

    captures = {UUID(read(CAPTURES / name / 'capture.json')['capture_id']): provenance(name)
        for name in ('python_reference', 'sqlite_select', 'sqlite_expression', 'sqlite_functions')}
    composition = PinnedCaptureProvenanceComposition(conn, captures=captures)
    receipts = AssessmentReceiptRepository(conn, service_keys=keys, provenance=composition, enabled=True)
    teaching = PublicPythonTeachingVerifier(conn,
        review=SignedTeachingReview.model_validate_json((CURRENT / 'public-python-teaching-source-1/signed.json').read_text(encoding='utf8')),
        service_keys=keys, provenance=provenance('learnx_python'), enabled=True)
    return compose_assessment_authority(conn, receipts=receipts, teaching_verifier=teaching, enabled=True)[1]


def current_materials():
    from app.services.learning.item_supply.generation_contracts import PublicMaterialV2
    raw = {**read(CURRENT / 'public-python-mixed-corpus-1/materials.json'),
        'sqlite-predicate-order-v1': read(CURRENT / 'public-sqlite-course-source-1/materials.json')}
    return {target: tuple(PublicMaterialV2.model_validate_json(json.dumps(item)) for item in raw[target])
        for target in TARGETS}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--preflight', action='store_true')
    args = parser.parse_args()
    if not args.preflight:
        print(json.dumps({'status': 'not_executed', 'database_io': False, 'provider_calls': 0}))
        return 0
    configure_imports()
    from app.services.learning.item_bank.contracts import canonical_hash
    output = ROOT / '.runtime/e-native-type-20261006' / ('source-preflight-' + uuid4().hex[:12])
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'pending', 'provider_calls': 0, 'GETs': 0, 'signing_key_reads': 0,
        'database': DB, 'database_transaction': 'rollback_only', 'public_release': False, 'E_complete': False}
    try:
        materials = current_materials()
        with connection() as conn:
            with conn.transaction(force_rollback=True):
                authority = public_authority(conn)
                current = {target: [authority.authorize(m).model_dump(mode='json') for m in materials[target]]
                    for target in TARGETS}
                checked = conn.execute('SELECT clock_timestamp() AS n').fetchone()['n'].isoformat()
                report.update(status='passed_current_public_sources_only', checked_at=checked,
                    material_counts={t: len(materials[t]) for t in TARGETS},
                    current_receipt_hashes={t: [canonical_hash(r) for r in current[t]] for t in TARGETS})
    except Exception as exc:
        report.update(status='failed_retained_no_retry', error_type=type(exc).__name__,
            safe_reason=str(exc).splitlines()[0][:160] if isinstance(exc, ValueError) else 'DETAILS_WITHHELD',
            sqlstate=getattr(exc, 'sqlstate', None))
    (output / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(report, ensure_ascii=False))
    print(str(output / 'result.json'))
    return 0 if report['status'] == 'passed_current_public_sources_only' else 1


if __name__ == '__main__':
    raise SystemExit(main())
