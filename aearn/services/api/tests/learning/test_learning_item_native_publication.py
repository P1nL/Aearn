"""Two OFFLINE contract cases. Mock DB/C/provider facts are not live acceptance."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.core.config import Settings
from app.services.learning.item_bank import native_publication as publication
from app.services.learning.item_bank.contracts import canonical_hash, learning_item_handle
from app.services.learning.item_bank.governance_repository import LearningItemGovernanceError, PostgresLearningItemGovernanceRepository
from app.services.learning.item_bank.native_import import NativeLearningItemBankImporter
from app.services.learning.item_bank.native_publication import NativeLearningItemPublicationService, NativePublishedItemQuery
from app.services.learning.item_bank.native_publication_contracts import NativeInternalRuntimeBindingV1, build_native_practice_material
from app.services.learning.item_bank.repository import LearningItemImportResult, PostgresLearningItemBankRepository
from app.services.learning.item_supply.evidence import material_digest
from app.services.learning.item_supply.diagnostic_policy import AutonomousEvidencePolicyV3
from app.services.learning.item_supply.generation_contracts import GenerationReceiptV2, ProviderReceiptV2, SourceReceiptV2
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.sandbox.python_goal_scorer import compile_goal_tests
from app.services.learning.item_supply.shared_admission_facts import SharedAdmissionFactsPending
from app.services.learning.item_supply.shared_pipeline_repository import ResolvedSharedGeneration, SharedPipelineArtifactRepository
from app.services.learning.practice.contracts import ExerciseSourceKind
from tests.learning.test_item_supply_shared_admission_facts import _static_protocol
from tests.learning.test_item_supply_shared_validation import _candidate


def test_native_material_compiles_python_goal_without_mutation_and_legacy_paths_deny(monkeypatch):
    spec, materials, source = _candidate('python-state-update-v1')
    original_hash = source.source_hash
    material = build_native_practice_material(source, spec=spec, materials=materials)
    tests = compile_goal_tests(source)
    assert material.exercise.source_kind is ExerciseSourceKind.REGISTERED_AUTHOR
    assert material.rubric.private_test_bundle == tests
    assert material.runner_payload['test_cases'] == list(tests)
    assert all(t['input_json']['goal_contract'] == spec.python_goal.model_dump(mode='json') for t in tests)
    assert source.source_hash == original_hash and source.private.content.tests[0].input_json == {}
    assert material.standard_submission == source.private.content.standard_answer
    sqls = []

    def execute(sql, params=()):
        sqls.append(sql)
        return SimpleNamespace(fetchone=lambda: {'native': True}, fetchall=lambda: [])

    conn = SimpleNamespace(execute=execute)
    governance = PostgresLearningItemGovernanceRepository(conn)
    handle = learning_item_handle(source.public.item_key, source.public.version, source.content_hash)
    with pytest.raises(LearningItemGovernanceError, match='current native publication authority'):
        governance.start_pilot(handle=handle, transition_key='offline.no.v1.pilot', occurred_at=datetime.now(UTC))
    assert PostgresLearningItemBankRepository(conn).published_candidates(
        knowledge_key=source.blueprint.knowledge_key, available_capabilities=source.blueprint.required_capabilities) == ()
    assert "native_validation.schema_version='candidate_validation_v2'" in sqls[-1]


@pytest.mark.parametrize("diagnostic", [False, True])
def test_static_native_chain_atomic_rollback_and_durable_current_query_after_producer_expiry(monkeypatch, diagnostic):
    owner, args, conn = _static_protocol(monkeypatch, policy=AutonomousEvidencePolicyV3() if diagnostic else None, wrong=diagnostic)
    prepared = args['review_prepared']
    spec, source, request, lease = prepared.spec, prepared.source, prepared.request, args['lease']
    authority = owner.validation_pipeline._issued(args['validation_prepared'])[0]
    monkeypatch.setattr(authority._current.governance.source_reviews, 'resolve',
        lambda *a: SimpleNamespace(grant=SimpleNamespace(retained_until=lease.parent_deadline + timedelta(hours=1))))
    facts = owner.issue(**args)
    assert facts.evaluation.disposition == 'eligible_internal'
    receipts = tuple(SourceReceiptV2(material_digest=material_digest(m), binding_digest=m.binding.binding_digest,
        corpus_version_id=UUID(m.binding.evidence[0].corpus_version_id), active_generation=m.binding.evidence[0].active_generation,
        checked_at_iso=facts.checked_at.isoformat(), claim_receipt_hashes=('c' * 64,), mode='current_authority') for m in request.materials)
    source_current = {'allowed': True}

    def current(self, material, expected):
        if not source_current['allowed']:
            raise ValueError('current_source_revoked')
        if source_current.pop('quarantine_on_check', False):
            state['events'].append(dict(id=uuid4(), state='quarantined', state_version=5))
        return next(r for r in receipts if r.material_digest == material_digest(material))

    monkeypatch.setattr(RagSourceAuthority, 'assert_current', current)
    receipt = GenerationReceiptV2(candidate_id=request.candidate_id, scope_hash=request.scope_hash,
        source_hash=source.source_hash, content_hash=source.content_hash, sources=receipts,
        provider=ProviderReceiptV2(provider='offline', provider_version='offline.v2', configured_model='offline',
            model='offline', prompt_version='offline.v2', run_id=uuid4(), request_attempt_bound=1,
            usage={'state': 'unknown'}, mode='provider'))
    artifact = {'id': facts.generation_artifact_id, 'root_id': facts.root_id, 'item_id': facts.item_id,
        'version_id': facts.version_id, 'artifact_hash': prepared.artifact_hash}
    generation = ResolvedSharedGeneration(artifact, request, source, receipt, lease)
    settings = Settings(learning_item_supply_enabled=True, learning_item_v2_admission_enabled=True)
    artifacts = SharedPipelineArtifactRepository(conn, enabled=True)
    importer = NativeLearningItemBankImporter(conn, settings, artifacts=artifacts, source_authority=authority, enabled=True)
    monkeypatch.setattr(importer, '_load', lambda **kw: SimpleNamespace(generation=generation, validation=prepared.validation))
    handle = learning_item_handle(source.public.item_key, source.public.version, source.content_hash)
    bank_validation_id, exercise_id, evaluation_id, initial_id = (uuid4() for _ in range(4))
    imported = LearningItemImportResult(str(facts.item_id), str(facts.version_id), handle, source.content_hash,
        str(bank_validation_id), str(uuid4()), str(initial_id), 'machine_verified', 1, False)
    bank = dict(id=facts.version_id, handle=handle, content_hash=source.content_hash,
        creator_identity=f'native.author.{receipt.provider.run_id.hex}', validation_id=bank_validation_id,
        receipt_hash=prepared.validation.evidence_hash, receipt_json=prepared.validation.model_dump(mode='json'),
        native_generation_artifact_id=facts.generation_artifact_id, native_validation_receipt_id=facts.validation_receipt_id,
        native_specification_hash=spec.specification_hash)
    original_execute = conn.execute
    state = {'events': [dict(id=initial_id, state='machine_verified', state_version=1)],
        'proofs': {}, 'materials': [], 'exercise': [], 'evaluations': [], 'fail_final': True}

    @contextmanager
    def transaction():
        before = deepcopy(state)
        try:
            yield
        except Exception:
            state.clear()
            state.update(before)
            raise

    def execute(sql, params=()):
        row, rows = None, []
        if 'FROM tutor_item_supply_shared_pipeline_receipts WHERE id=ANY' in sql:
            expected = ((facts.validation_receipt_id, 'validation'), (facts.blind_receipt_id, 'blind_solve'), (facts.review_receipt_id, 'review_bundle'))
            rows = [{**conn.stages[rid], 'id': rid, 'artifact_kind': kind, 'job_id': lease.job_id,
                'lease_generation': lease.generation, 'generation_artifact_id': facts.generation_artifact_id,
                'version_id': facts.version_id, 'source_hash': source.source_hash, 'content_hash': source.content_hash}
                for rid, kind in expected]
        elif 'SELECT v.id,v.handle' in sql:
            assert params == (facts.version_id, str(bank_validation_id))
            row = bank
        elif sql.startswith('SELECT * FROM tutor_learning_item_publication_events'):
            row = state['events'][-1]
        elif sql.startswith('SELECT id FROM tutor_learning_item_versions'):
            assert 'FOR SHARE' in sql and params == (facts.version_id, handle)
            row = {'id': facts.version_id}
        elif sql.startswith('SELECT id,state FROM tutor_learning_item_publication_events'):
            row = state['events'][-1]
        elif sql.startswith('SELECT proof_json,proof_hash'):
            row = state['proofs'].get(params[0])
        elif sql.startswith('INSERT INTO tutor_learning_item_native_publication_proofs'):
            payload = params[-2].obj
            state['proofs'][params[0]] = {'proof_json': payload, 'proof_hash': canonical_hash(payload), 'runner_material_json': params[-1].obj}
        elif sql.startswith('INSERT INTO tutor_learning_item_practice_materializations'):
            assert 'native_publication_txid' in sql and sql.endswith(',txid_current())')
            state['materials'].append(params)
        elif sql.startswith('INSERT INTO tutor_learning_item_publication_events'):
            assert params[9] == 'native_v2' and params[12] == facts.evaluation.policy_version
            state['events'].append(dict(id=params[0], state=params[6], state_version=params[5], occurred_at=params[-1]))
            if params[6] == 'published' and state['fail_final']:
                conn.current = False
        elif sql.startswith('SELECT p.proof_json'):
            proof = next(iter(state['proofs'].values()))
            material = build_native_practice_material(source, spec=spec, materials=request.materials)
            row = {**proof, 'public_json': source.public.model_dump(mode='json'), 'source_json': source.model_dump(mode='json'),
                'request_json': request.model_dump(mode='json'), 'root_id': facts.root_id, 'job_id': lease.job_id, 'lease_generation': lease.generation,
                'exercise_content_hash': material.exercise.content_hash, 'rubric_hash': material.rubric.rubric_hash,
                'materialization_hash': proof['proof_json']['materialization_hash'], 'occurred_at': facts.checked_at}
        else:
            return original_execute(sql, params)
        return SimpleNamespace(fetchone=lambda: row, fetchall=lambda: rows)

    def materialize(self, exercise, rubric, *, now):
        state['exercise'].append((exercise, rubric))
        return str(exercise_id)

    def store_evaluation(**kw):
        assert kw['payload'] == facts.evaluation and kw['lease'] == lease
        state['evaluations'].append(kw['payload'])
        return {'id': evaluation_id}

    monkeypatch.setattr(conn, 'transaction', transaction, raising=False)
    monkeypatch.setattr(conn, 'execute', execute)
    monkeypatch.setattr(artifacts, 'store_receipt', store_evaluation)
    monkeypatch.setattr(publication.PostgresExerciseGateRepository, 'ensure_exercise_authority', materialize)
    runtime = NativeInternalRuntimeBindingV1(target_id=spec.target_id, runtime_id='static-exact-v1',
        runtime_profile_hash=spec.coverage_blueprint.scope.runtime_profile_hash, scorer_version=spec.coverage_blueprint.scope.scorer_version)
    monkeypatch.setattr(owner, 'verify', lambda *a, **kw: pytest.fail('class-bound facts verification required'))
    publisher = NativeLearningItemPublicationService(conn, settings, importer=importer, facts_owner=owner,
        approved_internal_bindings=(runtime,), enabled=True)
    with pytest.raises(SharedAdmissionFactsPending, match='CURRENT_FENCE_LOST'):
        publisher.publish_internal(imported, lease=lease, spec=spec, facts_receipt=facts)
    assert len(state['events']) == 1 and not state['proofs'] and not state['materials'] and not state['exercise']
    conn.current, state['fail_final'] = True, False
    proof = publisher.publish_internal(imported, lease=lease, spec=spec, facts_receipt=facts)
    assert [e['state'] for e in state['events']] == ['machine_verified', 'agent_reviewed', 'pilot', 'published']
    assert state['exercise'][0][0].source_kind is ExerciseSourceKind.REGISTERED_AUTHOR
    assert proof.runtime.runtime_lock is None and not proof.publication_enabled and not proof.inventory_ready
    # Producer lease expiry/completion does not renew or invalidate immutable
    # publication history. Current source/scorer proof is independently checked.
    conn.current = False
    monkeypatch.setattr(publication, 'server_clock', lambda *a: facts.valid_until + timedelta(seconds=1))
    query = NativePublishedItemQuery(conn, approved_internal_bindings=(runtime,), enabled=True)
    selected = query.query_exact(handle=handle, spec=spec, source_authority=authority)
    assert selected is not None and selected.public == source.public
    assert selected.evidence_policy_version == facts.evaluation.policy_version
    assert selected.diagnostic_warnings == (("blind_solution_incorrect",) if diagnostic else ())
    assert selected.consumption_proof.checked_at > proof.valid_until and selected.consumption_proof.runtime_health_registry_hash is None
    assert proof.valid_until == facts.valid_until and not selected.inventory_ready
    source_current['allowed'] = False
    with pytest.raises(ValueError, match='current_source_revoked'):
        query.query_exact(handle=handle, spec=spec, source_authority=authority)
    # The row was published at discovery, but becomes quarantined during the
    # current-source read. This is a pure ordering seam, not a live PG race test.
    source_current.update(allowed=True, quarantine_on_check=True)
    assert query.query_exact(handle=handle, spec=spec, source_authority=authority) is None
