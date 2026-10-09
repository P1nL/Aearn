"""Two pure/offline continuation tests: no DB, source, provider or runner IO."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from psycopg.pq import TransactionStatus

from app.core.config import Settings
from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.generation_contracts import GenerationRequestV2
from app.services.learning.item_supply.parameter_profiles import ExecutionParameterProfileV1, ProfileKeyV1, freeze_profile
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.policies import CoverageObligationV1, RetryPolicyV1, derive_runtime_contract_hash
from app.services.learning.item_supply.provider_adapter import GENERATION_ADAPTER_VERSION, GENERATION_PROMPT_VERSION
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.shared_continuation import SharedCandidateContinuationOwner, bind_shared_candidate_continuation
from tests.learning.test_item_supply_shared_validation import _setup


def _fixture(monkeypatch):
    _, _, spec, lease, _, artifact, _, _ = _setup(monkeypatch, 'python-kc-binding-v1')
    now = datetime.now(UTC)
    values = lease.profile.values
    profile = ExecutionParameterProfileV1(profile_key=ProfileKeyV1(provider='synthetic.provider',
        model_version='fixture.v1', agent_role='generator', item_kind='knowledge_check', risk_tier='low',
        difficulty='basic', input_size_bucket='small', runtime='static-exact-v1'), version=1, state='stable',
        initial=values, current=values, last_stable=values, floor=values, ceiling=values,
        measurement_window_started_at=now, change_reason='offline.fixture', trusted_initial_evidence=('offline.fixture',))
    old_profile = freeze_profile(profile, bound_at=now - timedelta(hours=1))
    fresh_profile = freeze_profile(profile, bound_at=now)
    fresh_lease = lease.model_copy(update={'job_id': uuid4(), 'profile': fresh_profile,
        'parent_deadline': fresh_profile.parent_deadline_at, 'expires_at': fresh_profile.parent_deadline_at})
    request = GenerationRequestV2.model_validate_json(json.dumps(artifact['request_json'])).model_copy(update={'profile': old_profile})
    artifact['request_json'] = request.model_dump(mode='json')
    artifact['receipt_json']['provider'].update(mode='provider', provider=profile.profile_key.provider,
        provider_version=GENERATION_ADAPTER_VERSION, prompt_version=GENERATION_PROMPT_VERSION)
    artifact['artifact_hash'] = canonical_hash({k: artifact[k + '_json'] for k in ('source', 'receipt', 'request')})
    coverage = spec.coverage_blueprint
    scope = coverage.scope
    obligation = CoverageObligationV1(blueprint_hash=coverage.blueprint_hash, scope_hash=scope.scope_hash,
        objective_hash=coverage.objective_hash, purpose=scope.purpose.value,
        runtime_contract_hash=derive_runtime_contract_hash(scope), visibility='public', policy_version=coverage.policy_version)
    artifact.update(job_id=uuid4(), lease_generation=1, canonical_key=obligation.canonical_key,
        coverage_json=coverage.model_dump(mode='json'), provider_key=profile.profile_key.provider,
        target_id=spec.target_id, target_definition_hash=spec.target_definition_hash,
        generation_completed=True, generation_settled=True)
    return artifact, spec, fresh_lease, profile


class OfflineConnection:
    def __init__(self, artifact):
        self.info = SimpleNamespace(transaction_status=TransactionStatus.INTRANS)
        self.artifact, self.binding, self.sql = artifact, None, []
        self.rollbacks = 0

    @contextmanager
    def transaction(self):
        before = deepcopy(self.binding)
        try:
            yield
        except Exception:
            self.binding = before
            self.rollbacks += 1
            raise

    def execute(self, sql, params=()):
        self.sql.append(sql)
        if 'current_database()' in sql:
            row = {'db': 'aearn_b1d_sandbox_20261001'}
        elif 'clock_timestamp()' in sql:
            row = {'now': datetime.now(UTC)}
        elif sql.startswith('SELECT a.*'):
            row = self.artifact
        elif sql.startswith('SELECT job_id FROM tutor_item_supply_shared_candidate_continuations'):
            row = None if self.binding is None else {'job_id': self.binding['binding_json']['adoption_lease']['job_id']}
        elif sql.startswith('INSERT INTO tutor_item_supply_shared_candidate_continuations'):
            payload = params[-1].obj
            self.binding = {'binding_json': payload, 'binding_hash': canonical_hash(payload)}
            row = self.binding
        elif sql.startswith('SELECT binding_json,binding_hash'):
            row = self.binding
        else:
            raise AssertionError(sql)
        return SimpleNamespace(fetchone=lambda: row)


def test_expired_author_job_data_preserves_original_identity_and_rejects_root_relabel(monkeypatch):
    artifact, spec, lease, _ = _fixture(monkeypatch)
    original = deepcopy(artifact)
    binding, source, request, _, inputs = bind_shared_candidate_continuation(
        artifact=artifact, spec=spec, lease=lease, operation_key='explicit.recovery.1')
    assert request.profile.parent_deadline_at < datetime.now(UTC) < lease.parent_deadline
    assert binding.original_job_id != binding.adoption_lease.job_id
    assert binding.generation_artifact_id == artifact['id'] and binding.candidate_id == artifact['candidate_id']
    assert binding.root_id == artifact['root_id'] and source.source_hash == binding.source_hash
    assert not binding.execution_authority_reusable and not binding.publication_enabled
    assert inputs.static_facts.validation.mode == 'static' and artifact == original
    relabeled = {**artifact, 'canonical_key': '0' * 64}
    with pytest.raises(PipelineRepositoryError, match='ORIGINAL_MISMATCH'):
        bind_shared_candidate_continuation(artifact=relabeled, spec=spec, lease=lease, operation_key='explicit.recovery.1')
    incomplete = {**artifact, 'generation_completed': False}
    with pytest.raises(PipelineRepositoryError, match='ORIGINAL_MISMATCH'):
        bind_shared_candidate_continuation(artifact=incomplete, spec=spec, lease=lease, operation_key='explicit.recovery.1')


def test_atomic_same_root_claim_and_restarted_current_source_read(monkeypatch):
    artifact, spec, lease, profile = _fixture(monkeypatch)
    conn = OfflineConnection(artifact)
    owner = SharedCandidateContinuationOwner(conn, Settings(learning_item_supply_enabled=True), enabled=True)
    authority = RagSourceAuthority(SimpleNamespace(conn=conn), None)
    state = {'current': True, 'wrong_claim': True, 'enqueue': []}

    def current(material, receipt):
        if not state['current']:
            raise ValueError('source_expired_no_renewal')
        return receipt

    def enqueue(**kw):
        state['enqueue'].append(kw)
        assert kw['root_id'] == artifact['root_id'] and kw['visibility'] == 'public'
        assert not any(k in kw for k in ('parent_job_id', 'user_id', 'epoch', 'scope_id'))
        return lease.job_id

    monkeypatch.setattr(authority, 'assert_current', current)
    monkeypatch.setattr(owner.runtime, 'enqueue', enqueue)
    monkeypatch.setattr(owner.runtime, 'claim', lambda **kw: lease.model_copy(update={'job_id': uuid4()}) if state['wrong_claim'] else lease)
    monkeypatch.setattr(owner.runtime, '_control', lambda *a, **kw: {})
    meta = {'root_id': artifact['root_id'], 'coverage': spec.coverage_blueprint, 'canonical_key': artifact['canonical_key']}
    monkeypatch.setattr(owner.artifacts, 'context', lambda *a, **kw: meta)
    args = dict(artifact_id=artifact['id'], spec=spec, operation_key='explicit.recovery.1', profile=profile,
        retry_policy=RetryPolicyV1(max_transient_attempts=2, initial_backoff_ms=10, maximum_backoff_ms=10),
        source_authority=authority, lease_owner=lease.lease_owner, lease_seconds=300)
    assert owner.adopt(**args) is None and conn.binding is None and conn.rollbacks == 1
    state['wrong_claim'] = False
    adopted = owner.adopt(**args)
    assert adopted.original_artifact['job_id'] == artifact['job_id'] and adopted.lease.job_id == lease.job_id
    # A new owner can resolve immutable DATA, but no runtime/terminal object is reconstructed.
    restarted = SharedCandidateContinuationOwner(conn, owner.settings, enabled=True)
    monkeypatch.setattr(restarted.artifacts, 'context', lambda *a, **kw: meta)
    monkeypatch.setattr(restarted.runtime, '_control', lambda *a, **kw: {})
    resolved = restarted.resolve(lease=lease, artifact_id=artifact['id'], spec=spec, source_authority=authority)
    assert resolved.binding == adopted.binding and not resolved.binding.execution_authority_reusable
    state['current'] = False
    with pytest.raises(ValueError, match='source_expired_no_renewal'):
        restarted.resolve(lease=lease, artifact_id=artifact['id'], spec=spec, source_authority=authority)
    assert not any('INSERT INTO tutor_item_supply_shared_reservations' in sql or 'private_' in sql for sql in conn.sql)
    assert not any('UPDATE ' in sql or 'INSERT INTO tutor_item_supply_shared_generation_artifacts' in sql for sql in conn.sql)
