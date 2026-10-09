"""OFFLINE native consumer seams; SQL doubles/DTOs are NOT publication authority.

No PostgreSQL, Docker, network, provider, secrets, learner Attempt or Gate IO.
"""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from psycopg.pq import TransactionStatus

from app.services.learning.item_bank import native_publication as publication
from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash, learning_item_handle, learning_item_uuid
from app.services.learning.item_bank.native_publication_contracts import (
    NativeInternalRuntimeBindingV1, NativePublicationPending, NativePublicationProofV1, build_native_practice_material,
)
from app.services.learning.item_bank.publication import PrivatePublicationError, source_bindings
from app.services.learning.item_supply.finite_candidate_factory import (
    FACTORY_VERSION, FLEXIBLE_FACTORY_VERSION, PYTHON_FACTORY_VERSION_V2,
    build_finite_candidate_spec, build_finite_generation_request,
)
from app.services.learning.item_supply.finite_candidate_validation import prepare_finite_candidate_validation
from app.services.learning.item_supply.finite_course_mapping_contracts import FiniteCourseProfileV1
from app.services.learning.item_supply.finite_course_targets import finite_course_targets
from app.services.learning.item_supply.evidence import material_digest
from app.services.learning.item_supply.generation_contracts import (
    GenerationReceiptV2, GenerationResultV2, ProviderReceiptV2, SourceReceiptV2,
)
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.policies import CoverageObligationV1, derive_runtime_contract_hash
from app.services.learning.item_supply.provider_adapter import GENERATION_ADAPTER_VERSION, GENERATION_PROMPT_VERSION
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.shared_continuation import bind_shared_candidate_continuation
from app.services.learning.item_supply.shared_pipeline_repository import SharedPipelineArtifactRepository
from app.services.learning.item_supply.shared_review import SharedReviewPipeline
from app.services.learning.item_supply.storage_contracts import AutonomousEvidencePolicyV2
from tests.learning import test_item_supply_shared_admission_facts as facts_fixtures
from tests.learning.test_item_supply_finite_course_mapping import profile as course_profile
from tests.learning.test_learning_item_native_publication import (
    test_static_native_chain_atomic_rollback_and_durable_current_query_after_producer_expiry as _assert_static_publication_chain,
)
from tests.learning.test_item_supply_shared_validation import _candidate
from tests.learning.test_item_supply_generation import make_request


TARGETS = tuple(t.target_id for t in finite_course_targets())


def flexible_candidate(target, version=FLEXIBLE_FACTORY_VERSION):
    """Reuse existing OFFLINE private truth, changing only explicit public spec."""
    old, materials, source = _candidate(target)
    scope = old.coverage_blueprint.scope
    spec = build_finite_candidate_spec(target_id=target, variant_id=old.allocation.variant_id,
        seed=old.seed, item_key=old.public_template.item_key, version=old.public_template.version,
        materials=materials, runtime_profile_hash=None if target == 'python-kc-binding-v1' else scope.runtime_profile_hash,
        scorer_version=scope.scorer_version, assistance_policy_hash=scope.assistance_policy_hash,
        policy_version=old.coverage_blueprint.policy_version, difficulty_profile=old.blueprint.difficulty_profile,
        publication_policy=old.blueprint.publication_policy, public_spec_version=version)
    data = source.model_dump(mode='json')
    data.update(blueprint=spec.blueprint.model_dump(mode='json'), public=spec.public_template.model_dump(mode='json'))
    data['public']['title'] = 'Offline generated presentation'
    data['public']['instruction_markdown'] = '阅读任务后提交答案。\n\n' + data['public']['instruction_markdown'] + '\n\n完成后可自行核对格式。'
    return spec, materials, LearningItemSourceV1.model_validate(data)


def artifact_hash(artifact):
    return canonical_hash({k: artifact[k + '_json'] for k in ('source', 'receipt', 'request')})


def consumer_fixture(monkeypatch, target='python-kc-binding-v1', version=FLEXIBLE_FACTORY_VERSION):
    spec, materials, source = flexible_candidate(target, version)
    base, _ = make_request()
    now = datetime.now(UTC)
    profile = base.profile.model_copy(update={'bound_at': now, 'parent_deadline_at': now + timedelta(seconds=900),
        'values': base.profile.values.model_copy(update={'stage_deadline_ms': 600_000, 'parent_deadline_ms': 900_000})})
    request = build_finite_generation_request(spec, candidate_id=uuid4(), profile=profile, limits=base.limits, materials=materials)
    lease = JobLeaseV1(job_id=uuid4(), visibility='public', lease_owner='offline.native.consumers', generation=1,
        state_version=3, expires_at=profile.parent_deadline_at, parent_deadline=profile.parent_deadline_at, profile=profile)
    receipts = tuple(SourceReceiptV2(material_digest=material_digest(m), binding_digest=m.binding.binding_digest,
        corpus_version_id=UUID(m.binding.evidence[0].corpus_version_id), active_generation=m.binding.evidence[0].active_generation,
        checked_at_iso=now.isoformat(), claim_receipt_hashes=(m.binding.evidence[0].claim_receipt_hash,),
        mode='current_authority') for m in materials)
    receipt = GenerationReceiptV2(candidate_id=request.candidate_id, scope_hash=request.scope_hash,
        source_hash=source.source_hash, content_hash=source.content_hash, sources=receipts,
        provider=ProviderReceiptV2(provider='offline', provider_version=GENERATION_ADAPTER_VERSION,
            prompt_version=GENERATION_PROMPT_VERSION, model='offline', configured_model='offline',
            run_id=uuid4(), request_attempt_bound=1, usage={'state': 'unknown'}, mode='provider'))
    artifact = dict(id=uuid4(), root_id=uuid4(), candidate_id=request.candidate_id,
        item_id=learning_item_uuid('item', request.item_key), version_id=learning_item_uuid('version', f'{request.item_key}@{request.version}'),
        source_hash=source.source_hash, content_hash=source.content_hash,
        source_json=source.model_dump(mode='json'), request_json=request.model_dump(mode='json'),
        receipt_json=receipt.model_dump(mode='json'))
    artifact['artifact_hash'] = artifact_hash(artifact)
    def execute(sql, params=()):
        if 'current_database()' in sql:
            row = {'db': 'aearn_b1d_sandbox_20261001'}
        elif 'clock_timestamp()' in sql:
            row = {'now': datetime.now(UTC)}
        else:
            raise AssertionError(sql)
        return SimpleNamespace(fetchone=lambda: row)
    conn = SimpleNamespace(info=SimpleNamespace(transaction_status=TransactionStatus.INTRANS), execute=execute)
    repo = SharedPipelineArtifactRepository(conn, enabled=True)
    authority = RagSourceAuthority(SimpleNamespace(conn=conn), None)
    def current(material, expected):
        assert material in materials and expected in receipts
        return expected
    monkeypatch.setattr(authority, 'assert_current', current)
    monkeypatch.setattr(repo, 'get_generation', lambda **kw: artifact)
    meta = {'coverage': spec.coverage_blueprint, 'root_id': artifact['root_id'],
        'blueprint_id': uuid4(), 'provider_key': receipt.provider.provider,
        'target': next(t for t in finite_course_targets() if t.target_id == target)}
    monkeypatch.setattr(repo, 'request_context', lambda *a, **kw: meta)
    monkeypatch.setattr(repo, 'context', lambda *a, **kw: meta)
    monkeypatch.setattr(repo, 'reservation', lambda *a, **kw: uuid4())
    monkeypatch.setattr(repo.runtime, '_control', lambda *a, **kw: {})
    return repo, conn, spec, source, request, receipt, lease, authority, artifact, meta


@pytest.mark.parametrize('target', TARGETS)
def test_v3_store_and_resolve_preserve_actual_generated_source(monkeypatch, target):
    repo, conn, spec, source, request, receipt, lease, authority, artifact, _ = consumer_fixture(monkeypatch, target)
    now = datetime.now(UTC)
    calls = []

    def execute(sql, params=()):
        calls.append(sql)
        assert sql.startswith('INSERT INTO tutor_item_supply_shared_generation_artifacts')
        assert params[-3].obj == source.model_dump(mode='json')
        return SimpleNamespace(fetchone=lambda: artifact)

    monkeypatch.setattr(conn, 'execute', execute)
    result = GenerationResultV2(state='staged', safe_reason='staged', source=source, receipt=receipt)
    assert repo.store_generation(lease=lease, request=request, result=result, artifact_key='offline.v3',
        now=now, source_authority=authority) == artifact
    resolved = repo.resolve_generation(lease=lease, artifact_id=artifact['id'], now=now,
        source_authority=authority, spec=spec)
    assert resolved.source == source and resolved.source.public != spec.public_template
    assert resolved.source.public.public_hash != spec.public_template.public_hash
    assert resolved.receipt.source_hash == source.source_hash and len(calls) == 1
    inputs = prepare_finite_candidate_validation(source, spec=spec, materials=request.materials)
    assert inputs.public_task_hash == source.public.public_hash
    assert not inputs.publication_enabled


@pytest.mark.parametrize('target,version', [(t, FACTORY_VERSION) for t in TARGETS] + [
    ('python-state-update-v1', PYTHON_FACTORY_VERSION_V2)])
def test_old_versions_keep_whole_public_strictness(monkeypatch, target, version):
    repo, _, spec, source, request, receipt, lease, authority, artifact, _ = consumer_fixture(monkeypatch, target, version)
    with pytest.raises(PipelineRepositoryError, match='SHARED_GENERATION_IDENTITY_MISMATCH'):
        repo.store_generation(lease=lease, request=request,
            result=GenerationResultV2(state='staged', safe_reason='staged', source=source, receipt=receipt),
            artifact_key='offline.legacy', now=datetime.now(UTC), source_authority=authority)
    with pytest.raises(PipelineRepositoryError, match='SHARED_GENERATION_RESOLUTION_MISMATCH'):
        repo.resolve_generation(lease=lease, artifact_id=artifact['id'], now=datetime.now(UTC),
            source_authority=authority, spec=spec)


@pytest.mark.parametrize('mutation', ['source_hash', 'artifact_hash', 'template', 'structured_content'])
def test_v3_resolution_rejects_changed_immutable_identity_or_task(monkeypatch, mutation):
    repo, _, spec, _, _, _, lease, authority, artifact, _ = consumer_fixture(monkeypatch)
    if mutation == 'source_hash':
        artifact['source_hash'] = '0' * 64
    elif mutation == 'artifact_hash':
        artifact['artifact_hash'] = '0' * 64
    elif mutation == 'template':
        artifact['request_json']['public_template']['title'] = 'not the server template'
        artifact['artifact_hash'] = artifact_hash(artifact)
    else:
        artifact['source_json']['public']['content']['options'][0]['label'] += ' mutated'
        changed = LearningItemSourceV1.model_validate(artifact['source_json'])
        artifact.update(source_hash=changed.source_hash, content_hash=changed.content_hash)
        artifact['receipt_json'].update(source_hash=changed.source_hash, content_hash=changed.content_hash)
        artifact['artifact_hash'] = artifact_hash(artifact)
    with pytest.raises(PipelineRepositoryError, match='SHARED_GENERATION_RESOLUTION_MISMATCH'):
        repo.resolve_generation(lease=lease, artifact_id=artifact['id'], now=datetime.now(UTC),
            source_authority=authority, spec=spec)


def test_v3_generation_request_template_stays_exact_and_private_path_stays_closed(monkeypatch):
    repo, _, _, source, request, receipt, lease, authority, artifact, _ = consumer_fixture(monkeypatch)
    altered = request.model_copy(update={'public_template': source.public})
    with pytest.raises(PipelineRepositoryError, match='SHARED_GENERATION_IDENTITY_MISMATCH'):
        repo.store_generation(lease=lease, request=altered,
            result=GenerationResultV2(state='staged', safe_reason='staged', source=source, receipt=receipt),
            artifact_key='offline.bad.template', now=datetime.now(UTC), source_authority=authority)
    # No trusted finite spec in the private artifact: author version is not authority.
    with pytest.raises(PrivatePublicationError, match='PRIVATE_PUBLICATION_GENERATION_MISMATCH'):
        source_bindings({**artifact, 'mode': 'live'}, source)


def test_v3_review_and_continuation_bind_actual_public_hash(monkeypatch):
    repo, conn, spec, source, request, receipt, lease, authority, artifact, meta = consumer_fixture(monkeypatch)
    inputs = prepare_finite_candidate_validation(source, spec=spec, materials=request.materials)
    validation = inputs.static_facts.validation
    reviewer = SharedReviewPipeline(conn, SimpleNamespace(), enabled=True)
    reviewer.artifacts = repo
    monkeypatch.setattr(reviewer.runtime, 'next_stage', lambda *a: 'reviewing')
    monkeypatch.setattr(reviewer.runtime, '_control', lambda *a, **kw: {})
    monkeypatch.setattr(conn, 'execute', lambda *a, **kw: SimpleNamespace(fetchone=lambda: {
        'payload_json': validation.model_dump(mode='json'), 'receipt_hash': validation.evidence_hash,
        'same_transaction': False, 'now': datetime.now(UTC)}))
    loaded = reviewer._load(lease=lease, artifact_id=artifact['id'], validation_receipt_id=uuid4(), spec=spec, authority=authority)
    assert loaded[1] == source and loaded[1].public.public_hash == inputs.public_task_hash
    scope = spec.coverage_blueprint.scope
    obligation = CoverageObligationV1(blueprint_hash=spec.coverage_blueprint.blueprint_hash,
        scope_hash=scope.scope_hash, objective_hash=spec.coverage_blueprint.objective_hash, purpose=scope.purpose.value,
        runtime_contract_hash=derive_runtime_contract_hash(scope), visibility='public', policy_version=spec.coverage_blueprint.policy_version)
    artifact.update(job_id=uuid4(), lease_generation=1, provider_key=receipt.provider.provider,
        canonical_key=obligation.canonical_key, coverage_json=spec.coverage_blueprint.model_dump(mode='json'),
        target_id=spec.target_id, target_definition_hash=meta['target'].definition_hash,
        generation_completed=True, generation_settled=True)
    original = deepcopy(artifact)
    binding, continued, _, _, prepared = bind_shared_candidate_continuation(
        artifact=artifact, spec=spec, lease=lease, operation_key='offline.v3.continue')
    assert continued == source and prepared.public_task_hash == source.public.public_hash
    assert binding.source_hash == source.source_hash and artifact == original
    assert not binding.execution_authority_reusable


def test_mapping_explicit_v3_is_bounded_to_three_targets_and_legacy_bytes_unchanged():
    for target in finite_course_targets():
        old = course_profile(target)
        old_json, old_hash = old.model_dump_json(), old.profile_hash
        upgraded = FiniteCourseProfileV1.model_validate({**old.model_dump(), 'public_spec_version': FLEXIBLE_FACTORY_VERSION})
        assert upgraded.target_id == target.target_id and upgraded.profile_hash != old_hash
        assert old.model_dump_json() == old_json and old.profile_hash == old_hash
        if target.target_id != 'python-state-update-v1':
            with pytest.raises(ValueError, match='Python public-spec revision'):
                FiniteCourseProfileV1.model_validate({**old.model_dump(), 'public_spec_version': PYTHON_FACTORY_VERSION_V2})
    with pytest.raises(ValueError):
        FiniteCourseProfileV1.model_validate({**old.model_dump(), 'target_id': 'unsupported-target', 'public_spec_version': FLEXIBLE_FACTORY_VERSION})


def native_query_fixture(monkeypatch):
    """Actual query code over explicit OFFLINE immutable-facts/publication rows."""
    monkeypatch.setattr(facts_fixtures, '_candidate', flexible_candidate)
    owner, args, conn = facts_fixtures._static_protocol(monkeypatch)
    facts = owner.issue(**args)
    p = args['review_prepared']
    spec, source = p.spec, p.source
    material = build_native_practice_material(source, spec=spec, materials=p.request.materials)
    runtime = NativeInternalRuntimeBindingV1(target_id=spec.target_id, runtime_id='static-exact-v1',
        runtime_profile_hash=spec.coverage_blueprint.scope.runtime_profile_hash,
        scorer_version=spec.coverage_blueprint.scope.scorer_version)
    handle = learning_item_handle(source.public.item_key, source.public.version, source.content_hash)
    proof = NativePublicationProofV1(proof_id=uuid4(), version_id=facts.version_id, item_handle=handle,
        generation_artifact_id=facts.generation_artifact_id, source_hash=source.source_hash, content_hash=source.content_hash,
        specification_hash=spec.specification_hash, target_id=spec.target_id, target_definition_hash=spec.target_definition_hash,
        clauses=tuple({'clause_id': m.clause_id, 'clause_hash': m.clause_hash, 'interpretation_hash': m.interpretation_hash}
            for m in facts.target_proof.mappings), materials=p.request.materials,
        source_receipts=tuple(SourceReceiptV2(material_digest='a' * 64, binding_digest=m.binding.binding_digest,
            corpus_version_id=UUID(m.binding.evidence[0].corpus_version_id), active_generation=m.binding.evidence[0].active_generation,
            checked_at_iso=facts.checked_at.isoformat(), claim_receipt_hashes=('c' * 64,), mode='current_authority') for m in p.request.materials),
        lease=p.lease, runtime=runtime, bank_validation_id=uuid4(), validation_receipt_id=facts.validation_receipt_id,
        validation_hash=facts.validation_receipt_hash, review_receipt_id=facts.review_receipt_id, review_hash=facts.review_receipt_hash,
        evaluation_receipt_id=uuid4(), evaluation_hash=facts.evaluation.evaluation_hash, facts_receipt_id=facts.receipt_id,
        facts_hash=facts.receipt_hash, evidence_hash=canonical_hash(facts.evidence.model_dump(mode='json')),
        materialization_id=uuid4(), exercise_version_id=uuid4(), materialization_hash='b' * 64,
        runner_material_hash=canonical_hash(dict(material.runner_payload)), publication_event_id=uuid4(),
        review_event_id=uuid4(), pilot_event_id=uuid4(), policy_hash=AutonomousEvidencePolicyV2().policy_hash,
        checked_at=facts.checked_at, valid_until=facts.valid_until)
    row = dict(proof_json=proof.model_dump(mode='json'), proof_hash=proof.proof_hash,
        source_json=source.model_dump(mode='json'), public_json=source.public.model_dump(mode='json'),
        exercise_content_hash=material.exercise.content_hash, rubric_hash=material.rubric.rubric_hash,
        materialization_hash=proof.materialization_hash, runner_material_json=dict(material.runner_payload), occurred_at=facts.checked_at)
    original_execute = conn.execute

    def execute(sql, params=()):
        if sql.startswith('SELECT p.proof_json'):
            return SimpleNamespace(fetchone=lambda: row)
        if sql.startswith('SELECT id FROM tutor_learning_item_versions'):
            return SimpleNamespace(fetchone=lambda: {'id': proof.version_id})
        if sql.startswith('SELECT id,state FROM tutor_learning_item_publication_events'):
            return SimpleNamespace(fetchone=lambda: {'id': proof.publication_event_id, 'state': 'published'})
        return original_execute(sql, params)

    monkeypatch.setattr(conn, 'execute', execute)
    authority = owner.validation_pipeline._issued(args['validation_prepared'])[0]
    monkeypatch.setattr(authority, 'assert_current', lambda *a: proof.source_receipts[0])
    query = publication.NativePublishedItemQuery(conn, approved_internal_bindings=(runtime,), enabled=True)
    return query, conn, row, proof, facts, spec, source, authority


def test_v3_native_query_returns_actual_public_not_canonical_template(monkeypatch):
    query, _, _, proof, _, spec, source, authority = native_query_fixture(monkeypatch)
    selected = query.query_exact(handle=proof.item_handle, spec=spec, source_authority=authority)
    assert selected is not None and selected.public == source.public
    assert selected.public.public_hash != spec.public_template.public_hash
    assert not selected.publication_enabled and not selected.inventory_ready


@pytest.mark.parametrize('mutation', ['missing_facts', 'missing_hash', 'wrong_hash', 'review_identity', 'bank_public', 'source_snapshot'])
def test_v3_native_query_rejects_unreviewed_public_or_missing_actual_proof(monkeypatch, mutation):
    query, conn, row, proof, facts, spec, _, authority = native_query_fixture(monkeypatch)
    if mutation == 'missing_facts':
        conn.facts.clear()
    elif mutation == 'missing_hash':
        del conn.facts[facts.receipt_id]['payload_json']['public_task_hash']
    elif mutation == 'wrong_hash':
        conn.facts[facts.receipt_id]['payload_json']['public_task_hash'] = spec.public_template.public_hash
    elif mutation == 'review_identity':
        conn.facts[facts.receipt_id]['payload_json']['review_receipt_id'] = str(uuid4())
    elif mutation == 'bank_public':
        # Still machine-acceptable V3 prose, but not the reviewed immutable source.
        row['public_json']['title'] = 'Another unreviewed V3 presentation'
    else:
        row['source_json']['public']['title'] = 'Changed immutable generation'
    if mutation in ('wrong_hash', 'review_identity'):
        # Even self-consistent OFFLINE DTO/digests do not replace actual content
        # and original review bindings. No production row is modified here.
        stored = conn.facts[facts.receipt_id]
        stored['payload_hash'] = canonical_hash(stored['payload_json'])
        row['proof_json']['facts_hash'] = stored['payload_hash']
        row['proof_hash'] = canonical_hash(row['proof_json'])
    with pytest.raises(NativePublicationPending, match='native_published_'):
        query.query_exact(handle=proof.item_handle, spec=spec, source_authority=authority)


def test_v3_static_publisher_and_current_query_compose_with_original_facts_owner(monkeypatch):
    """Reuse the legacy OFFLINE owner seam, not a fake reconstructed capability.

    Exercises the concrete V3 publisher and 493-bound current reader, including
    final-fence rollback, producer expiry and source revocation/quarantine.
    """
    monkeypatch.setattr(facts_fixtures, '_candidate', flexible_candidate)
    _assert_static_publication_chain(monkeypatch)
