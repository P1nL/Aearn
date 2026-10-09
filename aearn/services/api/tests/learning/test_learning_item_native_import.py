"""Two OFFLINE adapter cases. Mock rows are NOT real PG/source/OS acceptance."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
import re
from types import SimpleNamespace
from uuid import uuid4

import pytest
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from app.core.config import Settings
from app.services.learning.item_bank import repository as bank_repository, validation as legacy
from app.services.learning.item_bank.contracts import (
    LearningItemValidationCheckType, canonical_hash, learning_item_handle, learning_item_uuid,
)
from app.services.learning.item_bank.native_import import NativeLearningItemBankImporter, _check_validation_binding
from app.services.learning.item_bank.repository import LearningItemBankError, PostgresLearningItemBankRepository
from app.services.learning.item_supply.finite_candidate_factory import build_finite_generation_request
from app.services.learning.item_supply.finite_candidate_validation import prepare_finite_candidate_validation
from app.services.learning.item_supply.generation_contracts import GenerationReceiptV2, ProviderReceiptV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.sandbox.execution_contracts import RUNNER_VERSION
from app.services.learning.item_supply.shared_pipeline_repository import ResolvedSharedGeneration, SharedPipelineArtifactRepository
from app.services.learning.item_supply.validation_adapter import (
    CandidateCheckV2, CandidateExecutionEvidenceV2, CandidateProbeV2, CandidateValidationV2,
)
from app.services.learning.item_supply.validators.profiles import required_probes
from tests.learning.test_item_supply_generation import make_request
from tests.learning.test_item_supply_shared_validation import _candidate


class OfflineBankConnection:
    def __init__(self):
        self.info = SimpleNamespace(transaction_status=TransactionStatus.INTRANS)
        self.tables, self.sql, self.validation = {}, [], None

    @contextmanager
    def transaction(self):
        before = deepcopy(self.tables)
        try:
            yield
        except Exception:
            self.tables = before
            raise

    def execute(self, statement, params=()):
        sql = ' '.join(statement.split())
        self.sql.append((sql, params))
        row = None
        if 'current_database()' in sql:
            row = {'db': 'aearn_b1d_sandbox_20261001'}
        elif 'clock_timestamp()' in sql:
            row = {'now': datetime.now(UTC)}
        elif 'pg_advisory_xact_lock' in sql:
            pass
        elif 'FROM tutor_item_supply_shared_pipeline_receipts r ' in sql:
            r = self.validation
            if params == (r['id'], r['generation_artifact_id'], r['job_id'], r['lease_generation']):
                row = r
        elif sql.startswith('INSERT INTO tutor_learning_item'):
            match = re.search(r'INSERT INTO (\w+)\s*\((.*?)\) VALUES\s*\((.*?)\)', sql)
            table, columns, values = match.groups()
            supplied = iter(params)
            data = {}
            for column, token in zip(columns.split(','), values.split(','), strict=True):
                token = token.strip()
                value = next(supplied) if token.startswith('%s') else (
                    None if token == 'NULL' else True if token == 'true' else
                    int(token) if token.isdigit() else token.strip("'"))
                data[column.strip()] = value.obj if isinstance(value, Jsonb) else value
            rows = self.tables.setdefault(table, [])
            existing = next((r for r in rows if r.get('id', r.get('version_id')) == data.get('id', data.get('version_id'))), None)
            if existing is None:
                rows.append(data)
                row = data
        elif 'FROM tutor_learning_item_import_receipts' in sql:
            receipt = next((r for r in self.tables.get('tutor_learning_item_import_receipts', []) if r['import_key'] == params[0]), None)
            if receipt:
                version = self.tables['tutor_learning_item_versions'][0]
                event = self.tables['tutor_learning_item_publication_events'][0]
                row = {**receipt, 'item_id': version['item_id'], 'creator_identity': version['creator_identity'],
                       'publication_event_id': event['id'], 'publication_state': event['state'], 'publication_state_version': 1}
        else:
            table = re.search(r'FROM (tutor_learning_item\w+)', sql).group(1)
            row = next(iter(self.tables.get(table, [])), None)
        return SimpleNamespace(fetchone=lambda: row)


def _native_fixture(target):
    spec, materials, source = _candidate(target)
    base, _ = make_request()
    request = build_finite_generation_request(spec, candidate_id=uuid4(), profile=base.profile,
                                              limits=base.limits, materials=materials)
    # Distinct operation profile/job: no mutation of the original author's request.
    now = datetime.now(UTC)
    profile = base.profile.model_copy(update={'bound_at': now,
        'parent_deadline_at': now + timedelta(milliseconds=base.profile.values.parent_deadline_ms)})
    lease = JobLeaseV1(job_id=uuid4(), visibility='public', lease_owner='offline.native.bank', generation=2,
        state_version=3, expires_at=profile.parent_deadline_at, parent_deadline=profile.parent_deadline_at, profile=profile)
    receipt = GenerationReceiptV2(candidate_id=request.candidate_id, scope_hash=request.scope_hash,
        source_hash=source.source_hash, content_hash=source.content_hash,
        sources=(dict(material_digest='a'*64, binding_digest='b'*64, corpus_version_id=uuid4(), active_generation=1,
            checked_at_iso=datetime.now(UTC).isoformat(), claim_receipt_hashes=('c'*64,), mode='current_authority'),),
        provider=ProviderReceiptV2(provider='offline', provider_version='offline', configured_model='offline', model='offline',
            prompt_version='offline', run_id=uuid4(), request_attempt_bound=1, usage={'state':'unknown'}, mode='provider'))
    artifact = dict(id=uuid4(), job_id=uuid4(), lease_generation=1, root_id=uuid4(),
        item_id=learning_item_uuid('item', source.public.item_key),
        version_id=learning_item_uuid('version', source.public.item_key + '@' + source.public.version),
        source_json=source.model_dump(mode='json'), request_json=request.model_dump(mode='json'), receipt_json=receipt.model_dump(mode='json'))
    artifact['artifact_hash'] = canonical_hash({k: artifact[k+'_json'] for k in ('source','request','receipt')})
    generation = ResolvedSharedGeneration(artifact, request, source, receipt, lease)
    inputs = prepare_finite_candidate_validation(source, spec=spec, materials=materials)
    if inputs.static_facts is not None:
        validation, terminals, reservation = inputs.static_facts.validation, [], None
    else:
        run_id, reservation = uuid4(), uuid4()
        execution = CandidateExecutionEvidenceV2(source_hash=source.source_hash, content_hash=source.content_hash,
            kind=source.public.kind.value, language=source.blueprint.language_id, runtime_profile_id=source.blueprint.runtime_profile_id,
            dialect='sqlite' if target.startswith('sqlite') else None, runner_version=RUNNER_VERSION,
            scorer_version=spec.coverage_blueprint.scope.scorer_version, run_id=run_id, mode='live', isolation='approved_os_boundary',
            probes=tuple(CandidateProbeV2(name=n, status='passed', proof_hash='a'*64,
                profile_version=inputs.probe_plan.profile_id) for n in required_probes(source, finite_spec=spec)))
        validation = CandidateValidationV2(state='machine_verified', source_hash=source.source_hash, content_hash=source.content_hash,
            checks=tuple(CandidateCheckV2(check_type=c, status='passed', proof_hash='a'*64) for c in LearningItemValidationCheckType),
            mode='live', execution_evidence=execution)
        terminals = [dict(lock_fingerprint=spec.coverage_blueprint.scope.runtime_profile_hash,
            run_id=str(run_id), mode='live', isolation='approved_os_boundary')]
    preparation = dict(spec=spec.model_dump(mode='json'), request=request.model_dump(mode='json'), artifact_id=str(artifact['id']),
        artifact_hash=artifact['artifact_hash'], source_hash=source.source_hash, content_hash=source.content_hash,
        lease=lease.model_dump(mode='json'), inputs=inputs.model_dump(mode='json'))
    evidence = dict(validation=validation.model_dump(mode='json'), terminals=terminals, actual=None, publication_enabled=False)
    preparation_id = uuid4()
    row = dict(id=uuid4(), generation_artifact_id=artifact['id'], job_id=lease.job_id, lease_generation=lease.generation,
        item_id=artifact['item_id'], version_id=artifact['version_id'], source_hash=source.source_hash, content_hash=source.content_hash,
        artifact_kind='validation', schema_version='candidate_validation_v2', mode='live', publication_enabled=False,
        artifact_key=f'validation.{preparation_id.hex}', payload_json=validation.model_dump(mode='json'), receipt_hash=validation.evidence_hash,
        preparation_id=preparation_id, preparation_json=preparation, preparation_hash=canonical_hash(preparation),
        evidence_id=uuid4(), evidence_json=evidence, evidence_hash=canonical_hash(evidence), reservation_id=reservation,
        same_transaction=False, evidence_same_transaction=False, preparation_same_transaction=False)
    return spec, generation, row


def test_native_v2_current_continued_receipt_ingests_exact_original_bank_without_host_execution(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail('runtime bank ingestion must not call the legacy runtime validator')

    monkeypatch.setattr(legacy, 'validate_learning_item', denied)
    monkeypatch.setattr(bank_repository, 'validate_learning_item', denied)
    # One runtime import case; SQLite would execute on host if the V1 path leaked.
    spec, generation, row = _native_fixture('sqlite-predicate-order-v1')
    conn = OfflineBankConnection()
    conn.validation = row
    artifacts = SharedPipelineArtifactRepository(conn, enabled=True)
    authority = RagSourceAuthority(SimpleNamespace(conn=conn), None)
    calls = []

    def resolve(**kw):
        assert kw['lease'] == generation.lease and kw['artifact_id'] == generation.artifact['id']
        assert kw['source_authority'] is authority
        calls.append(kw)
        return generation

    monkeypatch.setattr(artifacts, 'resolve_generation', resolve)
    monkeypatch.setattr(artifacts, 'context', lambda *a, **kw: {'coverage': spec.coverage_blueprint, 'root_id': generation.artifact['root_id']})
    owner = NativeLearningItemBankImporter(conn, Settings(learning_item_supply_enabled=True),
                                         artifacts=artifacts, source_authority=authority, enabled=True)
    args = dict(lease=generation.lease, artifact_id=generation.artifact['id'], validation_receipt_id=row['id'],
                spec=spec, import_key='offline.native.v2')
    result = owner.import_candidate(**args)
    assert result.version_id == str(generation.artifact['version_id']) and result.handle.startswith('li:')
    assert result.publication_state == 'machine_verified' and result.publication_state_version == 1
    persisted = conn.tables['tutor_learning_item_validation_receipts'][0]
    assert persisted['passed'] is None and persisted['receipt_json'] == row['payload_json']
    assert persisted['native_validation_receipt_id'] == row['id'] and generation.artifact['job_id'] != generation.lease.job_id
    assert owner.import_candidate(**args).replayed and len(calls) == 4
    assert all('practice' not in name and 'private_publication' not in name for name in conn.tables)
    before = deepcopy(conn.tables)
    # Committed but ORIGINAL-job receipt cannot substitute for fresh continuation validation.
    conn.validation = {**row, 'job_id': generation.artifact['job_id']}
    with pytest.raises(LearningItemBankError, match='CURRENT_COMMITTED_VALIDATION_REQUIRED'):
        owner.import_candidate(**args)
    assert conn.tables == before


def test_static_native_proof_is_actual_and_legacy_v1_bytes_hashes_and_import_remain_unchanged():
    spec, generation, row = _native_fixture('python-kc-binding-v1')
    data = _check_validation_binding(generation, lease=generation.lease, spec=spec, row=row)
    source = generation.source
    validation = legacy.validate_learning_item(source)
    assert data.validation.legacy_receipt == validation and data.validation.mode == 'static'
    conn = OfflineBankConnection()
    args = dict(source=source, validation=validation, import_key='offline.curated.v1', source_path='curated/item.json',
                source_file_hash='f'*64, imported_at=datetime(2026, 10, 3, tzinfo=UTC))
    result = PostgresLearningItemBankRepository(conn).import_validated_source(**args)
    expected = canonical_hash(dict(importer_version='learning_item_repository_v1', import_key=args['import_key'],
        source_path=args['source_path'], source_file_hash=args['source_file_hash'], source_hash=source.source_hash,
        content_hash=source.content_hash, validation_receipt_hash=validation.receipt_hash))
    assert conn.tables['tutor_learning_item_import_receipts'][0]['request_hash'] == expected
    persisted = conn.tables['tutor_learning_item_validation_receipts'][0]
    assert json.loads(persisted['receipt_json']) == validation.model_dump(mode='json')
    assert persisted['passed'] is True and 'native_validation_receipt_id' not in persisted
    assert result.validation_receipt_id == str(learning_item_uuid('import', f'validation:{validation.receipt_hash}'))
    assert result.version_id == str(learning_item_uuid('version', source.public.item_key + '@' + source.public.version))
    assert result.handle == learning_item_handle(source.public.item_key, source.public.version, source.content_hash)
    assert PostgresLearningItemBankRepository(conn).import_validated_source(**args).replayed
