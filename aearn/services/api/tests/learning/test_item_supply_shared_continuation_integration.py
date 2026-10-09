"""Two affected offline integration cases; no PG, provider, Docker or old-suite run."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from psycopg.pq import TransactionStatus

from app.core.config import Settings
from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.generation_contracts import GenerationRequestV2
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.shared_continuation import SharedCandidateContinuationOwner, bind_shared_candidate_continuation
from app.services.learning.item_supply.shared_validation import SharedValidationPipeline
from tests.learning.test_item_supply_shared_continuation import OfflineConnection, _fixture
from tests.learning.test_item_supply_generation import make_request
from tests.learning import test_item_supply_shared_validation as validation_fixture


class StageConnection(OfflineConnection):
    def __init__(self, artifact):
        super().__init__(artifact)
        self.preparations, self.evidence, self.receipts, self.checkpoints = {}, {}, [], []

    @contextmanager
    def transaction(self):
        previous = self.info.transaction_status
        self.info.transaction_status = TransactionStatus.INTRANS
        try:
            with super().transaction():
                yield
        finally:
            self.info.transaction_status = previous

    def execute(self, sql, params=()):
        assert self.info.transaction_status == TransactionStatus.INTRANS
        if sql.startswith('SELECT * FROM tutor_item_supply_shared_generation_artifacts'):
            row = self.artifact if params == (self.artifact['id'], self.artifact['job_id'], self.artifact['lease_generation']) else None
        elif sql.startswith('SELECT stage FROM tutor_item_supply_shared_checkpoints'):
            return SimpleNamespace(fetchall=lambda: [{'stage': cp.stage} for cp in self.checkpoints])
        elif 'to_regprocedure' in sql:
            row = {'installed': True}
        elif 'shared_continuation_generation_inherited' in sql:
            row = {'inherited': self.binding is not None and self.artifact['generation_completed']}
        elif sql.startswith('INSERT INTO tutor_item_supply_shared_validation_preparations'):
            row = {'id': params[0], 'payload_hash': canonical_hash(params[13].obj)}
            assert params[15] == self.binding['binding_hash']
            self.preparations[params[0]] = row
        elif sql.startswith('SELECT payload_hash FROM tutor_item_supply_shared_validation_preparations'):
            row = self.preparations.get(params[0])
        elif sql.startswith('INSERT INTO tutor_item_supply_shared_validation_evidence'):
            row = {'id': uuid4(), 'payload_hash': canonical_hash(params[2].obj)}
            self.evidence[params[0]] = row
        elif sql.startswith('INSERT INTO tutor_item_supply_shared_pipeline_receipts'):
            row = {'id': uuid4(), 'job_id': params[0], 'lease_generation': params[2],
                'generation_artifact_id': params[4], 'receipt_hash': canonical_hash(params[12].obj),
                'continuation_binding_hash': params[13], 'payload_json': params[12].obj}
            self.receipts.append(row)
        else:
            return super().execute(sql, params)
        self.sql.append(sql)
        return SimpleNamespace(fetchone=lambda: row)


def _connected(monkeypatch):
    # Keep the borrowed fixture's new deadline within its exact frozen bound_at;
    # separate wall-clock reads otherwise differ by microseconds at the cap.
    clock = {}

    def frozen_request():
        request, payload = make_request()
        clock['now'] = request.profile.bound_at
        return request, payload

    monkeypatch.setattr(validation_fixture, 'make_request', frozen_request)
    monkeypatch.setattr(validation_fixture, 'datetime', SimpleNamespace(now=lambda tz: clock['now']))
    artifact, spec, lease, _ = _fixture(monkeypatch)
    conn = StageConnection(artifact)
    binding, _, _, _, _ = bind_shared_candidate_continuation(artifact=artifact, spec=spec,
        lease=lease, operation_key='explicit.connected.1')
    conn.binding = {'binding_json': binding.model_dump(mode='json'), 'binding_hash': binding.binding_hash}
    settings = Settings(learning_item_supply_enabled=True)
    adoption = SharedCandidateContinuationOwner(conn, settings, enabled=True)
    pipeline = SharedValidationPipeline(conn, settings, enabled=True, continuation_owner=adoption)
    authority = RagSourceAuthority(SimpleNamespace(conn=conn), None)
    state = {'current': True}
    meta = {'root_id': artifact['root_id'], 'canonical_key': artifact['canonical_key'], 'coverage': spec.coverage_blueprint}

    def current(material, receipt):
        if not state['current']:
            raise ValueError('source_current_denied')
        return receipt

    monkeypatch.setattr(authority, 'assert_current', current)
    for repository in (adoption.artifacts, pipeline.artifacts):
        monkeypatch.setattr(repository, 'context', lambda *a, **kw: meta)
        monkeypatch.setattr(repository.runtime, '_control', lambda *a, **kw: {'attempt_count': 1})
    monkeypatch.setattr(adoption.runtime, '_control', lambda *a, **kw: {'attempt_count': 1})
    monkeypatch.setattr(pipeline.runtime, '_control', lambda *a, **kw: {'attempt_count': 1})

    def checkpoint(current_lease, value, **kw):
        assert pipeline.runtime.next_stage(current_lease) == 'validating' and value.stage == 'validating'
        conn.checkpoints.append(value)

    monkeypatch.setattr(pipeline.runtime, 'checkpoint', checkpoint)
    return pipeline, adoption, authority, conn, artifact, spec, lease, binding, state, meta


def test_continued_static_validation_current_receipt_then_reviewing_without_generation_checkpoint(monkeypatch):
    pipeline, adoption, authority, conn, artifact, spec, lease, binding, state, _ = _connected(monkeypatch)
    original = deepcopy(artifact)
    assert pipeline.runtime.next_stage(lease) == 'validating'
    prepared = pipeline.prepare_validation(lease=lease, artifact_id=artifact['id'], spec=spec, source_authority=authority)
    assert prepared.request.profile.parent_deadline_at < datetime.now(UTC) < prepared.lease.parent_deadline
    assert prepared.request.profile != prepared.lease.profile
    assert pipeline._payload(prepared)['continuation_binding_hash'] == binding.binding_hash
    assert prepared.reservation_id is None and prepared.resources is None
    conn.info.transaction_status = TransactionStatus.IDLE
    result = pipeline.run_validation(prepared)
    with conn.transaction():
        pipeline.settle_validation(prepared, result)
    state['current'] = False
    with conn.transaction(), pytest.raises(ValueError, match='source_current_denied'):
        pipeline.commit_validation(prepared, result)
    assert not conn.receipts and not conn.checkpoints
    state['current'] = True
    with conn.transaction():
        committed = pipeline.commit_validation(prepared, result)
        assert pipeline.runtime.next_stage(lease) == 'reviewing'
    assert committed.state == 'machine_verified'
    assert conn.receipts[0]['job_id'] == lease.job_id != artifact['job_id']
    assert conn.receipts[0]['generation_artifact_id'] == artifact['id']
    assert conn.receipts[0]['continuation_binding_hash'] == binding.binding_hash
    assert [cp.stage for cp in conn.checkpoints] == ['validating']
    assert artifact == original and not binding.execution_authority_reusable
    assert not any('INSERT INTO tutor_item_supply_shared_generation_artifacts' in sql for sql in conn.sql)


def test_same_job_resolution_stays_strict_cross_job_requires_concrete_current_same_root_owner(monkeypatch):
    pipeline, adoption, authority, conn, artifact, spec, lease, _, _, meta = _connected(monkeypatch)
    repository = pipeline.artifacts
    request = GenerationRequestV2.model_validate_json(json.dumps(artifact['request_json']))
    old_lease = lease.model_copy(update={'job_id': artifact['job_id'], 'generation': artifact['lease_generation'],
        'profile': request.profile, 'parent_deadline': request.profile.parent_deadline_at, 'expires_at': request.profile.parent_deadline_at})
    # Current-control time checks are mocked in this offline repository shape test.
    resolved = repository.resolve_generation(lease=old_lease, artifact_id=artifact['id'], spec=spec,
        now=datetime.now(UTC), source_authority=authority)
    assert resolved.continuation_binding is None and resolved.request.profile == request.profile
    with pytest.raises(PipelineRepositoryError, match='SHARED_ARTIFACT_UNAVAILABLE'):
        repository.resolve_generation(lease=lease, artifact_id=artifact['id'], spec=spec,
            now=datetime.now(UTC), source_authority=authority)
    with pytest.raises(PipelineRepositoryError, match='CONTINUATION_OWNER_REQUIRED'):
        repository.resolve_generation(lease=lease, artifact_id=artifact['id'], spec=spec,
            now=datetime.now(UTC), source_authority=authority, continuation_owner=SimpleNamespace(conn=conn))
    meta['root_id'] = uuid4()  # Same artifact UUID must not authorize another root.
    with pytest.raises(PipelineRepositoryError, match='CURRENT_BINDING_MISMATCH'):
        repository.resolve_generation(lease=lease, artifact_id=artifact['id'], spec=spec,
            now=datetime.now(UTC), source_authority=authority, continuation_owner=adoption)
