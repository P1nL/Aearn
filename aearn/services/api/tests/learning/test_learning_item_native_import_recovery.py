"""One OFFLINE EAC7 recovery case; no real PG, provider or execution evidence."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.services.learning.item_bank.contracts import canonical_hash, learning_item_uuid
from app.services.learning.item_bank.native_import import NativeLearningItemBankImporter
from app.services.learning.item_bank.repository import LearningItemImportConflict, PostgresLearningItemBankRepository
from app.services.learning.item_bank.validation import validate_learning_item
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.shared_pipeline_repository import SharedPipelineArtifactRepository
from tests.learning.test_learning_item_native_import import OfflineBankConnection, _native_fixture


class RecoveryConnection(OfflineBankConnection):
    """Model operation identity / V1 partial uniqueness, not SQL enforcement."""

    def execute(self, statement, params=()):
        sql = ' '.join(statement.split())
        rows = self.tables.get('tutor_learning_item_validation_receipts', [])
        if sql.startswith('SELECT events.id,events.version_id'):
            events = self.tables.get('tutor_learning_item_publication_events', [])
            row = None
            if events:
                event = max(events, key=lambda e: e['state_version'])
                validation = next(r for r in rows if r['id'] == event['authority_reference_id'])
                imports = self.tables.get('tutor_learning_item_import_receipts', [])
                row = {**event, 'schema_version': validation['schema_version'], 'passed': validation['passed'],
                       'receipt_hash': validation['receipt_hash'],
                       'native_generation_artifact_id': validation['native_generation_artifact_id'],
                       'validation_source_hash': validation['receipt_json']['source_hash'],
                       'initial_native_import': any(i['initial_publication_event_id'] == event['id']
                            and i['validation_receipt_id'] == validation['id'] and i['importer_version'] == params[0]
                            and i['source_hash'] == params[1] and i['content_hash'] == params[2] for i in imports)}
        elif sql.startswith('SELECT id,version_id,receipt_hash,native_validation_receipt_id'):
            row = next((r for r in rows if str(r.get('native_validation_receipt_id')) == str(params[0])), None)
        elif sql.startswith('SELECT id,receipt_hash FROM tutor_learning_item_validation_receipts'):
            row = next((r for r in rows if (r['version_id'], r['policy_version'], r['compiler_version']) == params), None)
        elif sql.startswith('INSERT INTO tutor_learning_item_validation_receipts'):
            if params[4] == 'learning_item_validation_v1':
                assert "ON CONFLICT (version_id,policy_version,compiler_version) WHERE schema_version='learning_item_validation_v1'" in sql
                conflict = any(r['schema_version'] == 'learning_item_validation_v1'
                    and (r['version_id'], r['policy_version'], r['compiler_version']) == (params[1], params[5], params[6]) for r in rows)
            else:
                assert "ON CONFLICT(native_validation_receipt_id) WHERE schema_version='candidate_validation_v2'" in sql
                conflict = any(r.get('native_validation_receipt_id') == params[10] for r in rows)
            if not conflict:
                return super().execute(statement, params)
            row = None
        else:
            return super().execute(statement, params)
        self.sql.append((sql, params))
        return SimpleNamespace(fetchone=lambda: row)


def _next_operation(generation, prior):
    # Original generation/request/provider run stays untouched. Only this mock
    # current operation, its committed validation and provenance are replaced.
    lease = generation.lease.model_copy(update={'job_id': uuid4(), 'generation': 1})
    generation = replace(generation, lease=lease)
    row = deepcopy(prior)
    row.update(id=uuid4(), job_id=lease.job_id, lease_generation=lease.generation,
               preparation_id=uuid4(), evidence_id=uuid4())
    row['artifact_key'] = f"validation.{row['preparation_id'].hex}"
    row['preparation_json']['lease'] = lease.model_dump(mode='json')
    row['preparation_hash'] = canonical_hash(row['preparation_json'])
    execution = row['payload_json']['execution_evidence']
    if execution is not None:
        run_id = str(uuid4())
        execution['run_id'] = run_id
        execution['probes'][0]['proof_hash'] = canonical_hash({'offline_new_run': run_id})
        for terminal in row['evidence_json']['terminals']:
            terminal['run_id'] = run_id
        row['reservation_id'] = uuid4()
    row['receipt_hash'] = canonical_hash(row['payload_json'])
    row['evidence_json']['validation'] = deepcopy(row['payload_json'])
    row['evidence_hash'] = canonical_hash(row['evidence_json'])
    return generation, row


def test_unpublished_native_import_recovers_with_fresh_operation_without_rewriting_initial_authority(monkeypatch):
    for target in ('python-state-update-v1', 'python-kc-binding-v1'):
        spec, original, first_row = _native_fixture(target)
        conn = RecoveryConnection()
        conn.validation = first_row
        current = {'generation': original}
        artifacts = SharedPipelineArtifactRepository(conn, enabled=True)
        authority = RagSourceAuthority(SimpleNamespace(conn=conn), None)
        monkeypatch.setattr(artifacts, 'resolve_generation', lambda **kw: current['generation'])
        monkeypatch.setattr(artifacts, 'context', lambda *a, **kw: {
            'coverage': spec.coverage_blueprint, 'root_id': original.artifact['root_id']})
        owner = NativeLearningItemBankImporter(conn, Settings(learning_item_supply_enabled=True),
                                              artifacts=artifacts, source_authority=authority, enabled=True)
        args = dict(lease=original.lease, artifact_id=original.artifact['id'], validation_receipt_id=first_row['id'],
                    spec=spec, import_key='offline.recovery.original')
        first = owner.import_candidate(**args)
        committed = deepcopy(conn.tables)
        original_event = committed['tutor_learning_item_publication_events'][0]

        current['generation'], conn.validation = _next_operation(original, first_row)
        second_row = conn.validation
        args.update(lease=current['generation'].lease, validation_receipt_id=second_row['id'])
        # New operation cannot silently replace the request bound to an old key.
        with pytest.raises(LearningItemImportConflict, match='IMPORT_REPLAY_CONFLICT'):
            owner.import_candidate(**args)
        assert conn.tables == committed
        args['import_key'] = 'offline.recovery.current'
        second = owner.import_candidate(**args)
        assert second.version_id == first.version_id and second.handle == first.handle
        assert second.validation_receipt_id != first.validation_receipt_id
        assert second.validation_receipt_id == str(learning_item_uuid('import', f"native-validation:{second_row['id']}"))
        assert second.publication_event_id == first.publication_event_id
        assert conn.tables['tutor_learning_item_publication_events'] == [original_event]
        for table in ('tutor_learning_item_versions', 'tutor_learning_item_public_contents', 'tutor_learning_item_private_contents'):
            assert conn.tables[table] == committed[table]
        validations = conn.tables['tutor_learning_item_validation_receipts']
        imports = conn.tables['tutor_learning_item_import_receipts']
        assert len(validations) == len(imports) == 2
        assert validations[0] == committed['tutor_learning_item_validation_receipts'][0]
        assert imports[0] == committed['tutor_learning_item_import_receipts'][0]
        assert validations[1]['native_validation_receipt_id'] == second_row['id']
        assert validations[1]['receipt_json'] == second_row['payload_json']
        assert imports[1]['validation_receipt_id'] == second.validation_receipt_id
        assert imports[1]['initial_publication_event_id'] == original_event['id']
        assert (validations[0]['receipt_hash'] == validations[1]['receipt_hash']) == (target == 'python-kc-binding-v1')
        assert current['generation'].request == original.request and current['generation'].artifact == original.artifact
        assert owner.import_candidate(**args).replayed

        # Recovery is not a quarantine/publish refresh or a second initial event.
        conn.tables['tutor_learning_item_publication_events'].append({**original_event,
            'id': str(uuid4()), 'state': 'quarantined', 'state_version': 2, 'predecessor_event_id': original_event['id']})
        before_denied = deepcopy(conn.tables)
        with pytest.raises(LearningItemImportConflict, match='UNPUBLISHED_RECOVERY_REQUIRED'):
            owner.import_candidate(**{**args, 'import_key': 'offline.recovery.denied'})
        assert conn.tables == before_denied

    # Exact old V1 deterministic policy conflict stays a conflict, not a second
    # row. This directly covers the sole V1 ON CONFLICT predicate change.
    legacy = validate_learning_item(original.source)
    v1_conn = RecoveryConnection()
    bank = PostgresLearningItemBankRepository(v1_conn)
    version_id = str(original.artifact['version_id'])
    first_id = bank._ensure_validation(legacy, version_id=version_id)
    assert bank._ensure_validation(legacy, version_id=version_id) == first_id
    changed = legacy.model_copy(update={'checks': (legacy.checks[0].model_copy(update={'proof_hash': 'f'*64}), *legacy.checks[1:])})
    with pytest.raises(LearningItemImportConflict, match='conflicts with stored receipt'):
        bank._ensure_validation(changed, version_id=version_id)
    assert len(v1_conn.tables['tutor_learning_item_validation_receipts']) == 1

    # DDL shape only; main must verify these indexes against real PostgreSQL.
    ddl = (Path(__file__).parents[2] / 'app/db/schema/492_learning_item_native_validation_import.sql').read_text(encoding='utf-8')
    assert 'DROP CONSTRAINT IF EXISTS uq_tutor_learning_item_validation_policy;' in ddl
    assert 'DROP CONSTRAINT IF EXISTS tutor_learning_item_validation_receipts_receipt_hash_key;' in ddl
    assert "ON tutor_learning_item_validation_receipts(version_id,policy_version,compiler_version)\n  WHERE schema_version='learning_item_validation_v1';" in ddl
    assert "ON tutor_learning_item_validation_receipts(receipt_hash)\n  WHERE schema_version='learning_item_validation_v1';" in ddl
    assert "ON tutor_learning_item_validation_receipts(native_validation_receipt_id)\n  WHERE schema_version='candidate_validation_v2';" in ddl
