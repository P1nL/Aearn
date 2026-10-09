"""Three OFFLINE owner tests. No live source, provider, PG or Docker attestation."""
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from psycopg.pq import TransactionStatus

from app.core.config import Settings
from app.services.learning.item_bank.contracts import LearningItemSqlDatasetV2, canonical_hash, learning_item_uuid
from app.services.learning.item_supply.budget import ReservationResult
from app.services.learning.item_supply.evidence import material_digest
from app.services.learning.item_supply.finite_candidate_factory import build_finite_generation_request
from app.services.learning.item_supply.finite_targets.python_kc import _spec, _truth
from app.services.learning.item_supply.finite_targets.python_state import _programs, python_state_expected_stdout
from app.services.learning.item_supply.finite_targets.sqlite_predicates import sqlite_oracle, sqlite_private_fixture
from app.services.learning.item_supply.generation_contracts import GenerationReceiptV2, ProviderReceiptV2, SourceReceiptV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.shared_validation import SharedValidationPipeline
from tests.learning.test_item_supply_finite_candidate_validation import _context, _source
from tests.learning.test_item_supply_generation import make_request


class OfflineConnection:
    def __init__(self):
        self.info = SimpleNamespace(transaction_status=TransactionStatus.INTRANS)
        self.preparations, self.evidence, self.sql = {}, {}, []

    @contextmanager
    def transaction(self):
        assert self.info.transaction_status == TransactionStatus.IDLE
        self.info.transaction_status = TransactionStatus.INTRANS
        try:
            yield
        finally:
            self.info.transaction_status = TransactionStatus.IDLE

    def execute(self, sql, params=()):
        assert self.info.transaction_status == TransactionStatus.INTRANS
        self.sql.append(sql)
        if 'to_regclass' in sql:
            row = {'table_id': None}
        elif 'current_database()' in sql:
            row = {'db': 'aearn_b1d_sandbox_20261001'}
        elif 'clock_timestamp()' in sql:
            row = {'now': datetime.now(UTC)}
        elif sql.startswith('INSERT INTO tutor_item_supply_shared_validation_preparations'):
            row = {'id': params[0], 'payload_hash': canonical_hash(params[13].obj)}
            self.preparations[params[0]] = row
        elif sql.startswith('SELECT payload_hash'):
            row = self.preparations.get(params[0])
        elif sql.startswith('INSERT INTO tutor_item_supply_shared_validation_evidence'):
            row = {'id': uuid4(), 'payload_hash': canonical_hash(params[2].obj)}
            self.evidence[params[0]] = row
        elif 'same_transaction' in sql:
            row = {'id': uuid4(), 'same_transaction': False}
        else:
            raise AssertionError(sql)
        return SimpleNamespace(fetchone=lambda: row)


def _candidate(target):
    spec, materials = _context(target, slot=2 if target.startswith('sqlite') else 0)
    policy = dict(kind='all_tests', policy_version='all_tests_v1', threshold=1.0)
    if spec.python_goal is not None:
        tests = [dict(id='case-' + kind, case_type=kind, input_json={},
            expected_output_json={'stdout': python_state_expected_stdout(spec.python_goal)}, order_index=i)
            for i, kind in enumerate(('visible', 'hidden'))]
        private = dict(type='code', standard_answer=_programs(spec.python_goal)[2], tests=tests, score_policy=policy)
    elif spec.sql_target is not None:
        fixture = sqlite_private_fixture(spec.sql_target)
        hidden = LearningItemSqlDatasetV2.model_validate_json(json.dumps({'tables': [{'table': 'entries', 'rows': [
            [1, 'hidden-one', 1, 0, 5], [2, 'hidden-both', 1, 1, None], [3, 'hidden-null', None, 1, 3]]}]}))
        tests = [dict(id='case-' + kind, case_type=kind, dataset=data.model_dump(mode='json'),
            expected_output=sqlite_oracle(spec.sql_target, data).model_dump(mode='json'), order_index=i)
            for i, (kind, data) in enumerate((('visible', spec.public_template.content.public_dataset), ('hidden', hidden)))]
        private = dict(type='sql_v2', standard_query=fixture.equivalent_queries[0], tests=tests, score_policy=policy)
    else:
        question, truth = _spec('trace', False), _truth('trace', False)
        accepted = {o.label: (o.rhs, o.saved, o.observation, o.reason) == truth for o in question.options}
        options = spec.public_template.content.options
        private = dict(type='knowledge_check', accepted_answers=[next(o.option_id for o in options if accepted[o.label])],
            answer_explanation_markdown=question.explanation, tests=[dict(id='option.' + o.option_id,
                case_type='visible' if i == 0 else 'hidden', input_json={'answer': o.option_id},
                expected_output_json={'accepted': accepted[o.label]}, order_index=i, is_critical=True)
                for i, o in enumerate(options)],
            score_policy=dict(kind='static_exact', policy_version='static_exact_v1', threshold=1.0))
    return spec, materials, _source(spec, private)


def _setup(monkeypatch, target):
    spec, materials, source = _candidate(target)
    base, _ = make_request()
    now = datetime.now(UTC)
    values = base.profile.values.model_copy(update={'stage_deadline_ms': 600_000, 'parent_deadline_ms': 900_000})
    profile = base.profile.model_copy(update={'values': values, 'bound_at': now,
        'parent_deadline_at': now + timedelta(seconds=900)})
    request = build_finite_generation_request(spec, candidate_id=uuid4(), profile=profile, limits=base.limits, materials=materials)
    lease = JobLeaseV1(job_id=uuid4(), visibility='public', lease_owner='offline.shared.validation', generation=1,
        state_version=2, expires_at=profile.parent_deadline_at, parent_deadline=profile.parent_deadline_at, profile=profile)
    receipts = tuple(SourceReceiptV2(material_digest=material_digest(m), binding_digest=m.binding.binding_digest,
        corpus_version_id=UUID(m.binding.evidence[0].corpus_version_id), active_generation=m.binding.evidence[0].active_generation,
        checked_at_iso=now.isoformat(), claim_receipt_hashes=(m.binding.evidence[0].claim_receipt_hash,),
        mode='current_authority') for m in materials)
    receipt = GenerationReceiptV2(candidate_id=request.candidate_id, scope_hash=request.scope_hash,
        source_hash=source.source_hash, content_hash=source.content_hash, sources=receipts,
        provider=ProviderReceiptV2(provider='synthetic', provider_version='fixture.v2', configured_model='fixture',
            model='fixture', prompt_version='fixture.v2', run_id=uuid4(), mode='synthetic',
            request_attempt_bound=1, usage={'state': 'unknown'}))
    artifact = dict(id=uuid4(), root_id=uuid4(), candidate_id=request.candidate_id,
        item_id=learning_item_uuid('item', request.item_key), version_id=learning_item_uuid('version', request.item_key + '@' + request.version),
        source_hash=source.source_hash, content_hash=source.content_hash, source_json=source.model_dump(mode='json'),
        request_json=request.model_dump(mode='json'), receipt_json=receipt.model_dump(mode='json'))
    artifact['artifact_hash'] = canonical_hash({k: artifact[k + '_json'] for k in ('source', 'receipt', 'request')})
    conn = OfflineConnection()
    owner = SharedValidationPipeline(conn, Settings(learning_item_supply_enabled=True), enabled=True)
    authority = RagSourceAuthority(SimpleNamespace(conn=conn), None)
    state = {'current': True, 'reserved': [], 'settled': [], 'checkpoints': [], 'stored': [], 'runs': 0}

    def current(material, expected):
        if not state['current']:
            raise ValueError('source_current_denied')
        assert material in materials and expected in receipts
        return expected

    monkeypatch.setattr(authority, 'assert_current', current)
    monkeypatch.setattr(owner.artifacts, 'get_generation', lambda **kw: artifact)
    monkeypatch.setattr(owner.artifacts, 'request_context', lambda *a, **kw: {'coverage': spec.coverage_blueprint})
    monkeypatch.setattr(owner.runtime, 'next_stage', lambda lease: 'validating')
    monkeypatch.setattr(owner.runtime, '_control', lambda *a, **kw: {'attempt_count': 1})
    monkeypatch.setattr(owner.artifacts.runtime, '_control', lambda *a, **kw: {'attempt_count': 1})
    monkeypatch.setattr(owner.runtime, 'checkpoint', lambda *a, **kw: state['checkpoints'].append(a[1]))
    monkeypatch.setattr(owner.runtime, 'mark_preparing', lambda *a, **kw: None)
    rid = uuid4()

    def reserve(**kw):
        state['reserved'].append(kw)
        return ReservationResult(True, 'RESERVED', rid)

    def store(**kw):
        current(materials[0], receipts[0])
        state['stored'].append(kw)
        return {'id': uuid4(), 'receipt_hash': kw['payload'].evidence_hash}

    def run(**kw):
        assert conn.info.transaction_status == TransactionStatus.IDLE
        state['runs'] += 1
        raise RuntimeError('offline_runner_unavailable')

    monkeypatch.setattr(owner.budget, '_reserve_budget', reserve)
    monkeypatch.setattr(owner.budget, '_reservation_by_key', lambda *a: {'id': rid, 'lease_generation': 1})
    monkeypatch.setattr(owner.budget, '_reservation_amounts', lambda *a: state['reserved'][0]['requested'].as_dict())
    monkeypatch.setattr(owner.budget, 'settle', lambda **kw: state['settled'].append(kw))
    monkeypatch.setattr(owner.artifacts, 'store_receipt', store)
    runner = SimpleNamespace(run=run, verify=lambda *a, **kw: False)
    return owner, conn, spec, lease, authority, artifact, runner, state


def test_state_preparation_is_local_sealed_and_failed_io_stays_unknown(monkeypatch):
    owner, conn, spec, lease, authority, artifact, runner, state = _setup(monkeypatch, 'python-state-update-v1')
    p = owner.prepare_validation(lease=lease, artifact_id=artifact['id'], spec=spec, source_authority=authority, runner=runner)
    assert p.lease.owner_id is None and p.resources.requests == p.resources.input_tokens == p.resources.output_tokens == 0
    assert p.inputs.probe_plan == owner._issued(p)[1]._plan
    with pytest.raises(PipelineRepositoryError, match='PREPARED_UNAVAILABLE'):
        owner._issued(replace(p))
    with pytest.raises(PipelineRepositoryError, match='IDLE_TRANSACTION'):
        owner.run_validation(p)
    conn.info.transaction_status = TransactionStatus.IDLE
    result = owner.run_validation(p)
    assert result.validation is None and result.actual is None and state['runs'] == 1
    with pytest.raises(PipelineRepositoryError, match='RESULT_UNAVAILABLE'):
        owner._result(p, replace(result))
    with conn.transaction():
        owner.settle_validation(p, result)
    assert state['settled'][0]['usage_state'] == 'unknown' and state['settled'][0]['cost_amount'] is None
    assert not state['checkpoints'] and not state['stored']
    assert not any('private_' in sql for sql in conn.sql)


def test_sql_native_identity_and_current_source_fence_before_commit(monkeypatch):
    owner, conn, spec, lease, authority, artifact, runner, state = _setup(monkeypatch, 'sqlite-predicate-order-v1')
    p = owner.prepare_validation(lease=lease, artifact_id=artifact['id'], spec=spec, source_authority=authority, runner=runner)
    assert p.request.candidate_id == artifact['candidate_id'] and p.source.public == spec.public_template
    assert p.inputs.probe_plan.boundary == p.source.private.content.standard_query
    conn.info.transaction_status = TransactionStatus.IDLE
    result = owner.run_validation(p)
    with conn.transaction():
        owner.settle_validation(p, result)
    state['current'] = False
    with conn.transaction(), pytest.raises(ValueError, match='source_current_denied'):
        owner.commit_validation(p, result)
    assert not state['stored'] and not state['checkpoints'] and len(state['settled']) == 1
    state['current'] = True
    artifact['candidate_id'] = uuid4()
    with conn.transaction(), pytest.raises(PipelineRepositoryError, match='SHARED_GENERATION_RESOLUTION_MISMATCH'):
        owner.commit_validation(p, result)


def test_static_kc_exact_facts_current_fence_no_runner_or_budget(monkeypatch):
    owner, conn, spec, lease, authority, artifact, runner, state = _setup(monkeypatch, 'python-kc-binding-v1')
    off = SharedValidationPipeline(conn, owner.settings)
    assert off.prepare_validation(lease=lease, artifact_id=artifact['id'], spec=spec, source_authority=authority) is None
    with pytest.raises(PipelineRepositoryError, match='STATIC_RUNNER_DENIED'):
        owner.prepare_validation(lease=lease, artifact_id=artifact['id'], spec=spec, source_authority=authority, runner=runner)
    p = owner.prepare_validation(lease=lease, artifact_id=artifact['id'], spec=spec, source_authority=authority)
    conn.info.transaction_status = TransactionStatus.IDLE
    result = owner.run_validation(p)
    assert result.validation.mode == 'static' and result.validation.execution_evidence is None
    assert p.reservation_id is p.resources is None and not result.terminal_receipts
    state['current'] = False
    with conn.transaction(), pytest.raises(ValueError, match='source_current_denied'):
        owner.commit_validation(p, result)
    state['current'] = True
    with conn.transaction():
        owner.settle_validation(p, result)
    with conn.transaction():
        stage = owner.commit_validation(p, result)
    assert stage.state == 'machine_verified' and stage.validation_receipt_id and stage.evidence_id
    assert [c.stage for c in state['checkpoints']] == ['validating']
    assert state['runs'] == 0 and not state['reserved'] and not state['settled']
    assert not p.inputs.publication_enabled and not p.inputs.static_facts.admission_eligible
