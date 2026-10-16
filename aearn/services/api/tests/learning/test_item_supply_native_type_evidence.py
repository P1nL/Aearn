"""Offline original493 protocol+494 shapes, not live PG/provider acceptance."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.services.learning.item_bank.contracts import canonical_hash, learning_item_handle
from app.services.learning.item_bank.practice_adapter import LEARNING_ITEM_PRACTICE_ADAPTER_VERSION
from app.services.learning.item_bank.native_publication_contracts import NativeConsumptionProofV1, NativeInternalRuntimeBindingV1, NativePublicationProofV1, build_native_practice_material
from app.services.learning.item_supply.evidence import material_digest
from app.services.learning.item_supply.finite_course_mapping import _mapping_hash, _pack
from app.services.learning.item_supply.finite_course_mapping_contracts import FiniteCourseMappingReceiptV1, StoredCourseDemandV1
from app.services.learning.item_supply.finite_course_targets import get_finite_course_target
from app.services.learning.item_supply.generation_contracts import SourceReceiptV2
from app.services.learning.item_supply.native_type_contracts import IssuedNativePackCapability, NativeTypeEvidencePending
from app.services.learning.item_supply.native_type_evidence import NativeTypeEvidenceOwner, reconstruct_native_content
from app.services.learning.item_supply.native_type_fingerprints import semantic_payload
from app.services.learning.item_supply.pack_contracts import NativeScopedCandidateV2, NativeCandidateV1, PackCandidateV2
from app.services.learning.item_supply.storage import FrozenPrivateScope
from app.services.learning.item_supply.shared_pipeline_repository import SharedPipelineArtifactRepository
from app.services.learning.item_supply.storage_contracts import checked_model
from tests.learning.test_item_supply_finite_course_mapping import frozen, profile
from tests.learning.test_item_supply_shared_admission_facts import _static_protocol
from tests.learning.test_item_supply_shared_validation import _candidate


def original_row(monkeypatch, *, policy=None, wrong=False):
    issuer, args, conn = _static_protocol(monkeypatch, policy=policy, wrong=wrong)
    original_execute = conn.execute

    def legacy_schema_results(sql, params=()):
        # This existing offline493 fixture predates controlled/revision schemas.
        # Match their new schema probes exactly, not all queries or real guards.
        if sql.startswith((
            "SELECT to_regclass('public.tutor_item_supply_shared_controlled_counterexample_preparations') AS p,",
            "SELECT to_regclass('public.tutor_item_supply_shared_revision_preparations') AS p,",
        )):
            return SimpleNamespace(fetchone=lambda: {"p": None, "guard": None})
        return original_execute(sql, params)

    monkeypatch.setattr(conn, "execute", legacy_schema_results)
    facts = issuer.issue(**args)
    p = args["review_prepared"]
    material = build_native_practice_material(p.source, spec=p.spec, materials=p.request.materials)
    runtime = NativeInternalRuntimeBindingV1(target_id=p.spec.target_id, runtime_id="static-exact-v1",
        runtime_profile_hash=p.spec.coverage_blueprint.scope.runtime_profile_hash,
        scorer_version=p.spec.coverage_blueprint.scope.scorer_version)
    source_receipts = tuple(SourceReceiptV2(material_digest=material_digest(m), binding_digest=m.binding.binding_digest,
        corpus_version_id=UUID(m.binding.evidence[0].corpus_version_id), active_generation=m.binding.evidence[0].active_generation,
        checked_at_iso=facts.checked_at.isoformat(), claim_receipt_hashes=("c"*64,), mode="current_authority") for m in p.request.materials)
    exercise_id = uuid4()
    handle = learning_item_handle(p.source.public.item_key,p.source.public.version,p.source.content_hash)
    mh = canonical_hash({"adapter_version":LEARNING_ITEM_PRACTICE_ADAPTER_VERSION,
        "learning_item_version_id":str(facts.version_id),"learning_item_handle":handle,
        "learning_item_content_hash":p.source.content_hash,"exercise_version_id":str(exercise_id),
        "exercise_content_hash":material.exercise.content_hash,"rubric_hash":material.rubric.rubric_hash})
    proof = NativePublicationProofV1(proof_id=uuid4(), version_id=facts.version_id,
        item_handle=handle,
        generation_artifact_id=facts.generation_artifact_id, source_hash=p.source.source_hash, content_hash=p.source.content_hash,
        specification_hash=p.spec.specification_hash,target_id=p.spec.target_id,target_definition_hash=p.spec.target_definition_hash,
        clauses=tuple(dict(clause_id=c.clause_id,clause_hash=c.clause_hash,interpretation_hash=c.interpretation_hash) for c in facts.target_proof.mappings),
        materials=p.request.materials,source_receipts=source_receipts,lease=args["lease"],runtime=runtime,
        bank_validation_id=uuid4(),validation_receipt_id=facts.validation_receipt_id,validation_hash=facts.validation_receipt_hash,
        review_receipt_id=facts.review_receipt_id,review_hash=facts.review_receipt_hash,evaluation_receipt_id=uuid4(),
        evaluation_hash=facts.evaluation.evaluation_hash,facts_receipt_id=facts.receipt_id,facts_hash=facts.receipt_hash,
        evidence_hash=canonical_hash(facts.evidence.model_dump(mode="json")),materialization_id=uuid4(),exercise_version_id=exercise_id,
        materialization_hash=mh,
        runner_material_hash=canonical_hash(dict(material.runner_payload)),publication_event_id=uuid4(),review_event_id=uuid4(),pilot_event_id=uuid4(),
        policy_hash=facts.evaluation.binding.policy_hash,checked_at=facts.checked_at,valid_until=facts.valid_until)
    row = dict(request_json=p.request.model_dump(mode="json"),root_id=facts.root_id,job_id=p.lease.job_id,lease_generation=p.lease.generation,proof_json=proof.model_dump(mode="json"),proof_hash=proof.proof_hash,
        source_json=p.source.model_dump(mode="json"),public_json=p.source.public.model_dump(mode="json"),
        facts_json=facts.model_dump(mode="json"),facts_hash=facts.receipt_hash,
        preparation_json=issuer.validation_pipeline._payload(args["validation_prepared"]),validation_json=p.validation.model_dump(mode="json"),
        blind_json=args["review_result"].blind.model_dump(mode="json"),review_json=args["review_result"].bundle.model_dump(mode="json"),
        exercise_content_hash=material.exercise.content_hash,rubric_hash=material.rubric.rubric_hash,
        materialization_hash=proof.materialization_hash,runner_material_json=dict(material.runner_payload),published_at=facts.checked_at)
    row.update(preparation_hash=canonical_hash(row["preparation_json"]),
        preparation_profile_hash=args["validation_prepared"].lease.profile.profile_hash, continuation_row=None)
    return row, issuer, args, conn


def test_reconstructs_actual_493_protocol_not_digest_only_and_old_fact_interval_is_history(monkeypatch):
    row, _, _, _ = original_row(monkeypatch)
    resolved = reconstruct_native_content(row)
    assert resolved.facts.target_proof.mappings[0].machine_proof_hashes
    assert resolved.content.actual_public_task_hash == resolved.source.public.public_hash
    assert resolved.content.decision_signature != resolved.spec.family_definition_hash
    assert resolved.facts.validation_terminals == ()  # No fake KC OS evidence.
    assert resolved.content.author_id is not None
    assert reconstruct_native_content(row) == resolved


@pytest.mark.parametrize("field", ["proof_hash","facts_hash","public_json","validation_json","blind_json","review_json","exercise_content_hash","runner_material_json"])
def test_rejects_missing_or_wrong_actual_original_hash_and_receipt(monkeypatch,field):
    row, _, _, _ = original_row(monkeypatch)
    row[field] = {"altered": True} if field.endswith("json") else "0"*64
    with pytest.raises(NativeTypeEvidencePending,match="original_facts_invalid"):
        reconstruct_native_content(row)


def mapped_receipt(content):
    target = get_finite_course_target(content.spec.target_id)
    node = frozen(target)
    values = profile(target).model_dump(mode="json")
    values.update(runtime_profile_hash=content.spec.coverage_blueprint.scope.runtime_profile_hash,
        scorer_version=content.spec.coverage_blueprint.scope.scorer_version,
        assistance_policy_hash=content.spec.coverage_blueprint.scope.assistance_policy_hash)
    from app.services.learning.item_supply.finite_course_mapping_contracts import FiniteCourseProfileV1
    p = FiniteCourseProfileV1.model_validate_json(__import__("json").dumps(values))
    mh = _mapping_hash(node,p)
    original = canonical_hash({"id":str(node.node_id),"description":node.description})
    main = FrozenPrivateScope(uuid4(),canonical_hash("main"),original)
    remedial = FrozenPrivateScope(uuid4(),canonical_hash("remediation"),original)
    request = _pack(node,p,mh,{"practice":main,"assessment":main,"remediation":remedial})
    return FiniteCourseMappingReceiptV1(receipt_id=uuid4(),frozen_node=node,target_id=target.target_id,
        target_definition_hash=target.definition_hash,profile=p,mapping_hash=mh,pack_request=request,
        stored_demands=tuple(StoredCourseDemandV1(slot=d.slot,scope_id=d.storage_scope_id,demand_id=uuid4()) for d in request.demands),
        source_authorization_hash=canonical_hash("offline confirmed authority"),checked_at=datetime.now(UTC))


def test_real_496_private_scope_constructs_explicit_public_content_v2_not_v1(monkeypatch):
    row, issuer, args, conn = original_row(monkeypatch)
    resolved = reconstruct_native_content(row)
    mapping = mapped_receipt(resolved)
    # Constructor _candidate is exercised with actual496 _pack shapes; this is
    # an offline owner-method test, not fabricated live current authorization.
    owner = SimpleNamespace(user_id=mapping.frozen_node.user_id,epoch=1,
        _deadline=lambda *a: datetime.now(UTC)+timedelta(seconds=30))
    with pytest.raises(NativeTypeEvidencePending,match="current_consumption"):
        NativeTypeEvidenceOwner._candidate(owner,resolved,mapping,datetime.now(UTC))
    p = resolved.publication
    # Exact typed offline native-query return shape, not a bool/source grant.
    consumption = NativeConsumptionProofV1(publication_proof_id=p.proof_id,publication_proof_hash=p.proof_hash,
        version_id=p.version_id,source_hash=p.source_hash,content_hash=p.content_hash,
        specification_hash=p.specification_hash,materialization_hash=p.materialization_hash,
        current_source_receipt_hashes=tuple(canonical_hash(r.model_dump(mode="json")) for r in p.source_receipts),
        runtime_profile_hash=p.runtime.runtime_profile_hash,scorer_version=p.runtime.scorer_version,
        runtime_health_registry_hash=None,checked_at=datetime.now(UTC))
    resolved = replace(resolved,consumption=consumption)
    candidate = NativeTypeEvidenceOwner._candidate(owner,resolved,mapping,datetime.now(UTC))
    item = candidate.candidate
    assert isinstance(item,NativeScopedCandidateV2)
    assert item.visibility == "public" and item.owner_ref is None and item.item_handle.startswith("li:")
    assert item.scope.visibility == "private" and item.scope.owner_ref == "user:"+str(mapping.frozen_node.user_id)
    assert item.storage_scope_id == mapping.pack_request.demands[0].storage_scope_id
    assert item.proof.proof_hash and item.course_mapping_hash == mapping.mapping_hash
    assert checked_model(candidate,PackCandidateV2).model_dump(mode="json")["candidate"]["mapping_receipt_id"] == str(mapping.receipt_id)
    assert candidate.type_evidence.profile == "kc" and not hasattr(candidate.type_evidence,"terminal_receipt_hash")
    raw = item.model_dump(mode="json")
    raw["learner_id"] = str(uuid4())
    with pytest.raises(ValueError,match="private_context"):
        NativeScopedCandidateV2.model_validate_json(__import__("json").dumps(raw))
    legacy = item.model_dump(mode="json",exclude={"mapping_receipt_id","learner_id","epoch","storage_scope_id","course_mapping_hash"})
    legacy.update(schema_version="candidate_authority_v1",proof=None)
    with pytest.raises(ValueError):
        NativeCandidateV1.model_validate_json(__import__("json").dumps(legacy))

    # The actual front factory captures exact provisional DATA. Adjacent tail
    # projection changes only fresh observation fields and must not rebuild the
    # immutable consumption/static evidence or resolve source permission again.
    from app.services.learning.item_supply.native_type_evidence import _CurrentPackData
    from app.services.learning.item_supply.native_type_exposure import NativeExposureOwnerV2
    from app.services.learning.item_supply.native_type_exposure_contracts import NativeTypeExposureSnapshot
    from app.services.learning.item_supply.pack_contracts import CompleteExposureV2
    native = object.__new__(NativeTypeEvidenceOwner)
    native.conn, native.user_id, native.epoch = object(), mapping.frozen_node.user_id, 1
    native.current_source_binding, native._issued = None, {}
    collector = object.__new__(NativeExposureOwnerV2)
    collector.conn, collector.type_owner = native.conn, native
    collector.user_id, collector.epoch = native.user_id, native.epoch
    state = _CurrentPackData(1, mapping.receipt_id, (p.version_id,), (), collector, None,
        mapping=mapping, contents={p.version_id: resolved})
    native._pack_scope = state
    front_at = datetime.now(UTC)
    with monkeypatch.context() as front:
        front.setattr(native, '_deadline', lambda *a: front_at + timedelta(seconds=30))
        template = native._candidate(resolved, mapping, front_at)
    assert state.projections[p.version_id][0] is template
    now = front_at + timedelta(seconds=179)
    exposure = CompleteExposureV2(learner_id=native.user_id, epoch=1,
        collector_version='native-type-exposure-v2', watermark=0,
        completeness_receipt_hash=canonical_hash('offline fresh manifest'), observed_at=now,
        valid_until=now + timedelta(seconds=30), records=())
    state.observation = NativeTypeExposureSnapshot('complete', 'native_type_exposure_current', exposure, uuid4(), uuid4())
    state.source_deadlines[p.version_id] = now + timedelta(minutes=5)
    def no_immutable_reload(*a, **kw):
        raise AssertionError('tail must use exact verified front DATA')
    with monkeypatch.context() as tail:
        tail.setattr(native, 'source_deadline', no_immutable_reload)
        tail.setattr('app.services.learning.item_supply.native_type_evidence.checked_model', no_immutable_reload)
        tail.setattr('app.services.learning.item_supply.native_type_evidence.prepare_finite_candidate_validation', no_immutable_reload)
        projected = native._candidate(resolved, mapping, now)
    validated = checked_model(projected, PackCandidateV2)
    assert validated.member == template.member and validated.type_evidence.content == template.type_evidence.content
    assert validated.observed_at == now and validated.valid_until == exposure.valid_until
    assert validated.type_evidence.receipt_id != template.type_evidence.receipt_id
    assert validated.type_evidence.receipt_hash != template.type_evidence.receipt_hash
    assert validated.candidate.current_authorization.checked_at == now
    native._clear_pack_scope()
    assert not state.projections


@pytest.mark.parametrize("target",["python-kc-binding-v1","python-state-update-v1","sqlite-predicate-order-v1"])
def test_program_semantics_have_no_seed_letter_family_label_authority(target):
    spec, _, source = _candidate(target)
    semantics = semantic_payload(source,spec)
    assert set(semantics) == {"version","profile","decision"}
    assert spec.allocation.family_id not in semantics.values()
    assert source.public.title not in semantics.values()


def test_501_children_first_epoch_hook_and_no_502_forward_fk():
    sql = (Path(__file__).parents[2]/"app/db/schema/501_learning_item_native_type_evidence.sql").read_text()
    assert "a02_native_type_evidence_epoch_purge AFTER UPDATE" in sql
    assert "permitted(NEW.user_id) IS DISTINCT FROM true" in sql
    assert "REFERENCES tutor_item_supply_type_exposure_snapshots" not in sql
    deletes = [sql.index("DELETE FROM "+t) for t in ("tutor_item_supply_native_eligibility",
        "tutor_item_supply_native_relation_batches","tutor_item_supply_native_relation_preparations","tutor_item_supply_native_content_facts")]
    assert deletes == sorted(deletes)
    assert "state<>'leased'" in sql and "settlement.usage_state<>'unknown'" in sql


def test_capability_is_owner_object_identity_not_constructor_or_boolean():
    now = datetime.now(UTC)
    owner = SimpleNamespace(_guard=lambda:(now,9),_issued={})
    cap = IssuedNativePackCapability(uuid4(),SimpleNamespace(snapshot_hash="a"*64,checked_at=now,valid_until=now+timedelta(seconds=20)))
    for fake in (True,{},cap):
        with pytest.raises(NativeTypeEvidencePending,match="owner_capability"):
            NativeTypeEvidenceOwner.require_pack(owner,fake)
    owner._issued[cap.eligibility_id]=(cap,8,"a"*64,uuid4(),(),uuid4(),())
    with pytest.raises(NativeTypeEvidencePending,match="owner_capability"):
        NativeTypeEvidenceOwner.require_pack(owner,cap)


def test_501_scalar_case_in_if_comparison_is_parenthesized():
    import re
    sql=(Path(__file__).parents[2]/"app/db/schema/501_learning_item_native_type_evidence.sql").read_text()
    assert not re.search(r"(?:IS DISTINCT FROM|IS NOT DISTINCT FROM|=|<>)[ \t\r\n]+CASE\b",sql)
    assert "IS DISTINCT FROM (CASE" in sql and "control.profile_snapshot_json END) THEN" in sql
    assert "profile:=CASE" in sql and "kind:=CASE" in sql and "fixture:=CASE" in sql


def test_historical_retired_content_is_resolved_without_current_grant_and_revocation_denies_current(monkeypatch):
    from app.services.learning.item_supply.evidence import SourceEvidenceDenied
    row,_,_,protocol_conn=original_row(monkeypatch)
    resolved=reconstruct_native_content(row)
    class ReadConnection:
        def execute(self,*args):
            return SimpleNamespace(fetchall=lambda:[row])
    queries=[]
    def retired(**kwargs):
        queries.append(kwargs)
        return None
    owner=SimpleNamespace(_guard=lambda:(datetime.now(UTC),1),conn=ReadConnection(),
        query=SimpleNamespace(query_exact=retired, artifacts=SharedPipelineArtifactRepository(protocol_conn, enabled=True)),source_authority=None,_persist_content=lambda c:None)
    historic=NativeTypeEvidenceOwner.resolve_content(owner,resolved.content.version_id,current=False)
    assert historic.content==resolved.content and historic.consumption is None and not queries
    with pytest.raises(NativeTypeEvidencePending,match="current_required"):
        NativeTypeEvidenceOwner.resolve_content(owner,resolved.content.version_id,current=True)

    # Same lexical immutable DATA must still execute source -> bank/lock-post
    # fences, including this TOP's own retirement and source revocation edits.
    from app.services.learning.item_supply.native_type_evidence import _CurrentPackData
    from app.services.learning.item_supply.native_type_exposure import NativeExposureOwnerV2
    from app.services.learning.item_bank.native_publication import NativePublishedItemQuery
    p = resolved.publication
    consumption = NativeConsumptionProofV1(publication_proof_id=p.proof_id,
        publication_proof_hash=p.proof_hash, version_id=p.version_id, source_hash=p.source_hash,
        content_hash=p.content_hash, specification_hash=p.specification_hash,
        materialization_hash=p.materialization_hash,
        current_source_receipt_hashes=tuple(canonical_hash(r.model_dump(mode='json')) for r in p.source_receipts),
        runtime_profile_hash=p.runtime.runtime_profile_hash, scorer_version=p.runtime.scorer_version,
        runtime_health_registry_hash=None, checked_at=datetime.now(UTC))
    current = replace(resolved, consumption=consumption)
    state = {'source': True, 'bank': 'published'}
    order = []
    def execute(sql, params=()):
        order.append('bank')
        result = {'id': p.version_id} if 'tutor_learning_item_versions' in sql else {
            'id': p.publication_event_id, 'state': state['bank']}
        return SimpleNamespace(fetchone=lambda: result)
    def source_current(*args):
        order.append('source')
        if not state['source']:
            raise SourceEvidenceDenied()
    native = object.__new__(NativeTypeEvidenceOwner)
    native.conn, native.user_id, native.epoch = SimpleNamespace(execute=execute), uuid4(), 1
    native.current_source_binding, native._issued = None, {}
    native.source_authority = SimpleNamespace(assert_current=source_current)
    query = object.__new__(NativePublishedItemQuery)
    query._bindings = {current.spec.target_id: p.runtime}
    monkeypatch.setattr(query, '_current_runtime', lambda *args, **kwargs: None)
    native.query = query
    monkeypatch.setattr(native, '_guard', lambda: (datetime.now(UTC), 9))
    exposure_owner = object.__new__(NativeExposureOwnerV2)
    exposure_owner.conn, exposure_owner.type_owner = native.conn, native
    exposure_owner.user_id, exposure_owner.epoch = native.user_id, native.epoch
    def fresh_scope():
        native._pack_scope = _CurrentPackData(9, uuid4(), (p.version_id,), (), exposure_owner, None,
            contents={p.version_id: current})
    fresh_scope()
    native._require_scoped_content(current)
    assert order == ['source', 'bank', 'bank', 'source']
    state['bank'] = 'retired'
    with pytest.raises(NativeTypeEvidencePending, match='current_required'):
        native._require_scoped_content(current)
    assert native._pack_scope is None
    fresh_scope()
    state.update(bank='published', source=False)
    with pytest.raises(SourceEvidenceDenied):
        native._require_scoped_content(current)
    assert native._pack_scope is None
    def revoked(**kwargs):
        raise SourceEvidenceDenied()
    owner.query.query_exact=revoked
    with pytest.raises(NativeTypeEvidencePending,match="current_required"):
        NativeTypeEvidenceOwner.resolve_content(owner,resolved.content.version_id,current=True)


def test_native_exposure_current_receives_exact_json_not_boolean():
    from app.services.learning.item_supply.pack_contracts import CompleteExposureV2
    now=datetime.now(UTC)
    user=uuid4()
    exposure=CompleteExposureV2(learner_id=user,epoch=1,collector_version="native-type-exposure-v2",
        watermark=0,completeness_receipt_hash=canonical_hash("offline manifest"),observed_at=now,
        valid_until=now+timedelta(seconds=30),records=())
    data=exposure.model_dump(mode="json")
    row=dict(snapshot_json=data,snapshot_hash=canonical_hash(data),checked_at=now,valid_until=exposure.valid_until)
    response={"current":data}
    class SnapshotConnection:
        def execute(self,sql,*args):
            value=response if "type_exposure_current(" in sql else row
            return SimpleNamespace(fetchone=lambda:value)
    owner=SimpleNamespace(conn=SnapshotConnection(),user_id=user,epoch=1)
    assert NativeTypeEvidenceOwner._exposure(owner,uuid4(),now)==exposure
    response["current"]=True
    with pytest.raises(NativeTypeEvidencePending,match="current_required"):
        NativeTypeEvidenceOwner._exposure(owner,uuid4(),now)


def test_pack_inputs_samples_clock_after_current_content_issuance(monkeypatch):
    from app.services.learning.item_supply.pack_contracts import CompleteExposureV2

    row, _, _, _ = original_row(monkeypatch)
    resolved = reconstruct_native_content(row)
    mapping = mapped_receipt(resolved)
    start = datetime.now(UTC)
    issued_at = start + timedelta(milliseconds=5)
    observed_at = start + timedelta(milliseconds=10)
    p = resolved.publication
    consumption = NativeConsumptionProofV1(
        publication_proof_id=p.proof_id, publication_proof_hash=p.proof_hash,
        version_id=p.version_id, source_hash=p.source_hash, content_hash=p.content_hash,
        specification_hash=p.specification_hash, materialization_hash=p.materialization_hash,
        current_source_receipt_hashes=tuple(canonical_hash(r.model_dump(mode="json")) for r in p.source_receipts),
        runtime_profile_hash=p.runtime.runtime_profile_hash, scorer_version=p.runtime.scorer_version,
        runtime_health_registry_hash=None, checked_at=issued_at,
    )
    resolved = replace(resolved, consumption=consumption)
    clocks = iter((start, observed_at, observed_at + timedelta(milliseconds=1)))
    exposure = CompleteExposureV2(
        learner_id=mapping.frozen_node.user_id, epoch=1,
        collector_version="native-type-exposure-v2", watermark=0,
        completeness_receipt_hash=canonical_hash("offline manifest"), observed_at=start,
        valid_until=start + timedelta(seconds=30), records=(),
    )
    # Exercise the collector and real candidate validator with an advancing DB
    # clock. Repeated content is only a collection fixture, NOT a ready pack.
    owner = SimpleNamespace(
        user_id=mapping.frozen_node.user_id, epoch=1,
        _guard=lambda: (next(clocks), 1), resolve_mapping=lambda _: mapping,
        resolve_content=lambda *a, **k: resolved,
        _deadline=lambda content, now: now + timedelta(seconds=30),
        _exposure=lambda *a: exposure, _relations=lambda *a: (),
    )
    owner._candidate = lambda content, receipt, now: NativeTypeEvidenceOwner._candidate(owner, content, receipt, now)
    with pytest.raises(NativeTypeEvidencePending, match="current_consumption_mismatch"):
        NativeTypeEvidenceOwner._candidate(owner, resolved, mapping, start)
    inputs = NativeTypeEvidenceOwner._inputs(owner, mapping.receipt_id,
        tuple(uuid4() for _ in range(5)), uuid4(), (uuid4(),))
    assert len(inputs.candidates) == 5
    assert all(c.observed_at == observed_at for c in inputs.candidates)
    # Extend this existing clock test with the new lexical path. Concrete classes
    # use OFFLINE SQL/front doubles only, never actual publication authority.
    from app.services.learning.item_supply.native_type_exposure import NativeExposureOwnerV2
    from app.services.learning.item_supply.native_type_exposure_contracts import NativeTypeExposureSnapshot
    from tests.learning.test_item_supply_type_evidence_pack_v2 import inputs_v2, with_relationships
    data = with_relationships(inputs_v2())
    calls = []
    persisted = {}
    def execute(sql, params=()):
        if sql.startswith('INSERT INTO tutor_item_supply_native_eligibility'):
            persisted[params[0]] = canonical_hash(params[7].obj)
            value = None
        else:
            assert sql.startswith('SELECT snapshot_hash FROM tutor_item_supply_native_eligibility')
            value = {'snapshot_hash': persisted.get(params[0])}
        return SimpleNamespace(fetchone=lambda: value)
    native = object.__new__(NativeTypeEvidenceOwner)
    native.conn = SimpleNamespace(execute=execute)
    native.user_id, native.epoch = data.request.learner_id, data.request.epoch
    native.current_source_binding, native._pack_scope, native._issued = None, None, {}
    actual_mapping = SimpleNamespace(receipt_id=uuid4(), pack_request=data.request)
    monkeypatch.setattr(native, '_guard', lambda: (data.exposure.observed_at, 71))
    monkeypatch.setattr(native, 'resolve_mapping', lambda _id: actual_mapping)
    def content(version, current=True):
        cached = native._pack_scope.contents.get(version)
        if cached is not None:
            native._require_scoped_content(cached)
            return cached
        calls.append(('front', version))
        return SimpleNamespace(content=next(c.type_evidence.content for c in data.candidates if c.version_id == version))
    monkeypatch.setattr(native, 'resolve_content', content)
    def candidate_projection(resolved, mapping, now):
        version = resolved.content.version_id
        scope = native._pack_scope
        if scope.observation is None:
            scope.source_deadlines[version] = now + timedelta(hours=1)
        else:
            # Initial tail projection consumes the front's exact DATA bounds,
            # not another full source resolution after the 120s clock starts.
            assert NativeTypeEvidenceOwner._deadline(native, resolved, now) == min(
                now + timedelta(seconds=120), data.exposure.valid_until)
        return next(c for c in data.candidates if c.version_id == version)
    monkeypatch.setattr(native, '_candidate', candidate_projection)
    def no_projection_source_reload(*args):
        raise AssertionError('initial projection must use verified front DATA')
    monkeypatch.setattr(native, 'source_deadline', no_projection_source_reload)
    monkeypatch.setattr(native, '_require_scoped_content', lambda resolved: calls.append(('current', resolved.content.version_id)))
    monkeypatch.setattr(native, '_require_scoped_relations', lambda scope: calls.append(('relations-current', None)))
    monkeypatch.setattr(native, '_exposure', lambda *args: data.exposure)
    monkeypatch.setattr('app.services.learning.item_supply.native_type_evidence.server_clock', lambda *args: data.exposure.observed_at)
    arguments = tuple({k: v for k, v in r.model_dump().items()
        if k not in {'exposure_receipt_hash', 'exposure_watermark'}} for r in data.relationships)
    monkeypatch.setattr(native, '_relation_arguments', lambda *args: arguments)
    collector = object.__new__(NativeExposureOwnerV2)
    collector.conn, collector.type_owner = native.conn, native
    collector.user_id, collector.epoch = native.user_id, native.epoch
    monkeypatch.setattr(collector, '_lock', lambda: data.exposure.observed_at)
    history = SimpleNamespace(contents={})
    def prepare():
        calls.append(('history', None))
        return history
    monkeypatch.setattr(collector, '_prepare_history', prepare)
    snapshot_id = uuid4()
    observation = NativeTypeExposureSnapshot('complete', 'native_type_exposure_current',
        data.exposure, snapshot_id, uuid4())
    def issue(original):
        assert original is history and sum(c[0] == 'front' for c in calls) == 5
        assert calls[-1][0] == 'relations-current'
        calls.append(('snapshot', None))
        return observation
    monkeypatch.setattr(collector, '_snapshot_from_history', issue)
    original_inputs = native._inputs
    def external_inputs(*args):
        calls.append(('inputs-use', None))
        return original_inputs(*args)
    monkeypatch.setattr(native, '_inputs', external_inputs)
    versions = tuple(c.version_id for c in data.candidates)
    relations = (uuid4(),)
    with native.current_pack(actual_mapping.receipt_id, versions, relations, collector) as cap:
        assert native._pack_scope.versions == tuple(sorted(versions, key=str))
        assert collector.snapshot_v2() is observation
        assert native.resolve_pack(actual_mapping.receipt_id, versions, snapshot_id, relations) is cap
        assert native.require_pack(cap) is cap.snapshot
        assert sum(c[0] == 'front' for c in calls) == 5
        assert sum(c[0] == 'snapshot' for c in calls) == 1
        assert not any(c[0] == 'inputs-use' for c in calls)
        current_before = sum(c[0] == 'current' for c in calls)
        assert native._inputs(actual_mapping.receipt_id, versions, snapshot_id, relations) is native._pack_scope.inputs
        assert sum(c[0] == 'current' for c in calls) == current_before + 5
        assert sum(c[0] == 'inputs-use' for c in calls) == 1
        current_before = sum(c[0] == 'current' for c in calls)
        def no_unrelated_whole_pack(*a, **kw):
            raise AssertionError('one candidate DATA use must fence its own version, not all five')
        with monkeypatch.context() as per_item:
            per_item.setattr(native, 'require_pack', no_unrelated_whole_pack)
            selected = NativeTypeEvidenceOwner._candidate(native, native._pack_scope.contents[versions[0]],
                actual_mapping, data.exposure.observed_at)
            assert selected.version_id == versions[0]
        assert sum(c[0] == 'current' for c in calls) == current_before + 1
        # Bounds/UUID uniqueness precede set-equality fast paths. Valid order
        # permutations remain legal; duplicate locators never alias exact DATA.
        for bad_versions, bad_relations in ((versions + (versions[0],), relations),
                                             (versions, relations + relations)):
            with pytest.raises(NativeTypeEvidencePending, match='inputs_bound_invalid'):
                native._inputs(actual_mapping.receipt_id, bad_versions, snapshot_id, bad_relations)
            with pytest.raises(NativeTypeEvidencePending, match='inputs_bound_invalid'):
                native.resolve_pack(actual_mapping.receipt_id, bad_versions, snapshot_id, bad_relations)
        # OFFLINE source-port double: only the original core verifier's ordering
        # and exact DATA are exercised here, not live source authorization.
        from contextlib import contextmanager
        from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
        from app.services.learning.item_supply.persistent_pack_current_source import IssuedCurrentPackSourceBinding
        core = object.__new__(PersistentPackTaskOwner)
        core.conn, core.type_owner, core.user_id, core.epoch = native.conn, native, native.user_id, native.epoch
        source = object.__new__(IssuedCurrentPackSourceBinding)
        object.__setattr__(source, 'owner', core)
        native.query, native.source_authority = object(), object()
        scope = native._pack_scope
        for version, resolved in scope.contents.items():
            resolved.publication = SimpleNamespace(version_id=version, proof_id=uuid4(), proof_hash='a' * 64)
            scope.published_at[version] = data.exposure.observed_at
        expected = tuple((scope.contents[v].publication, scope.published_at[v]) for v in scope.versions)
        grouped = []
        @contextmanager
        def invocation(self, *, query, source_authority, proof_bindings):
            assert self is source and query is native.query and source_authority is native.source_authority
            assert proof_bindings == expected and len(proof_bindings) == 5
            grouped.append('full-source-before')
            try:
                yield None
            finally:
                grouped.append('full-source-after')
        with monkeypatch.context() as batch:
            # Worker may still be defining its port while this protocol test is
            # assembled; no production fallback or duck-typed port is introduced.
            batch.setattr(IssuedCurrentPackSourceBinding, 'current_pack_invocation', invocation, raising=False)
            batch.setattr(native, '_lock_scoped_bank', lambda c: grouped.append(('bank', c.content.version_id)))
            batch.setattr(native, '_require_scoped_runtime', lambda c: grouped.append(('health', c.content.version_id)))
            batch.setattr(native, '_require_scoped_relations', lambda s: grouped.append('relations'))
            batch.setattr(native, '_exposure', lambda *a: grouped.append('sql502') or data.exposure)
            native.current_source_binding = scope.source_binding = source
            try:
                native.require_pack(cap)
                native.require_pack(cap)  # independent invocation repeats BOTH source fences
            finally:
                native.current_source_binding = scope.source_binding = None
        expected_once = ['sql502', 'full-source-before']
        for v in scope.versions:
            expected_once.extend((('bank', v), ('health', v)))
        expected_once.extend(('relations', 'full-source-after', 'sql502'))
        assert grouped == expected_once + expected_once
        copied = type(cap)(cap.eligibility_id, cap.snapshot)
        with pytest.raises(NativeTypeEvidencePending, match='owner_capability_required'):
            native.require_pack(copied)
    assert native._pack_scope is None and cap.eligibility_id not in native._issued
    with pytest.raises(NativeTypeEvidencePending, match='owner_capability_required'):
        native.require_pack(cap)
    # An error unwinds and clears the same lexical data, not just normal return.
    calls.clear()
    with pytest.raises(RuntimeError, match='caller-stopped'):
        with native.current_pack(actual_mapping.receipt_id, versions, relations, collector):
            raise RuntimeError('caller-stopped')
    assert native._pack_scope is None and not native._issued


def _continued_publication_row(monkeypatch):
    """Synthetic immutable DATA rows, with the real491 pure binding constructor."""
    import json
    from app.services.learning.item_bank.contracts import learning_item_uuid
    from app.services.learning.item_supply.generation_contracts import GenerationReceiptV2, GenerationRequestV2, ProviderReceiptV2, ProviderUsageV2
    from app.services.learning.item_supply.jobs import JobLeaseV1
    from app.services.learning.item_supply.policies import CoverageObligationV1, derive_runtime_contract_hash
    from app.services.learning.item_supply.provider_adapter import GENERATION_ADAPTER_VERSION, GENERATION_PROMPT_VERSION
    from app.services.learning.item_supply.shared_continuation import bind_shared_candidate_continuation
    from tests.learning import test_item_supply_shared_admission_facts as protocol

    spec, materials, source = _candidate("python-kc-binding-v1")
    monkeypatch.setattr(protocol, "_candidate", lambda _: (spec, materials, source))
    calls = 0

    def identities():
        nonlocal calls
        calls += 1
        if calls == 5:
            return learning_item_uuid("item", source.public.item_key)
        if calls == 6:
            return learning_item_uuid("version", f"{source.public.item_key}@{source.public.version}")
        return uuid4()

    monkeypatch.setattr(protocol, "uuid4", identities)
    row, _, _, _ = original_row(monkeypatch)
    request = GenerationRequestV2.model_validate_json(json.dumps(row["request_json"]))
    old_profile = request.profile.model_copy(update={"profile_hash": "3"*64,
        "bound_at": request.profile.bound_at-timedelta(hours=1),
        "parent_deadline_at": request.profile.parent_deadline_at-timedelta(hours=1)})
    request = request.model_copy(update={"profile": old_profile})
    proof = NativePublicationProofV1.model_validate_json(json.dumps(row["proof_json"]))
    receipt = GenerationReceiptV2(candidate_id=request.candidate_id, scope_hash=request.scope_hash,
        source_hash=source.source_hash, content_hash=source.content_hash, sources=proof.source_receipts,
        provider=ProviderReceiptV2(provider="offline", provider_version=GENERATION_ADAPTER_VERSION,
            configured_model="offline-protocol", model="offline-protocol", prompt_version=GENERATION_PROMPT_VERSION,
            run_id=uuid4(), request_attempt_bound=1, usage=ProviderUsageV2(state="unknown"), mode="provider"))
    coverage = spec.coverage_blueprint
    obligation = CoverageObligationV1(blueprint_hash=coverage.blueprint_hash, scope_hash=coverage.scope.scope_hash,
        objective_hash=coverage.objective_hash, purpose=coverage.scope.purpose.value,
        runtime_contract_hash=derive_runtime_contract_hash(coverage.scope), visibility="public", policy_version=coverage.policy_version)
    facts = row["facts_json"]
    original = dict(id=UUID(facts["generation_artifact_id"]), root_id=row["root_id"], job_id=uuid4(), lease_generation=1,
        candidate_id=request.candidate_id, item_id=UUID(facts["item_id"]), version_id=UUID(facts["version_id"]),
        source_hash=source.source_hash, content_hash=source.content_hash, source_json=row["source_json"],
        request_json=request.model_dump(mode="json"), receipt_json=receipt.model_dump(mode="json"),
        canonical_key=obligation.canonical_key, coverage_json=coverage.model_dump(mode="json"), provider_key="offline",
        target_id=spec.target_id, target_definition_hash=spec.target_definition_hash,
        generation_completed=True, generation_settled=True)
    original["artifact_hash"] = canonical_hash({k: original[k+"_json"] for k in ("source", "receipt", "request")})
    adopted = JobLeaseV1.model_validate_json(json.dumps(facts["lease"])).model_copy(update={"state_version": 1})
    binding, _, _, _, _ = bind_shared_candidate_continuation(
        artifact=original, spec=spec, lease=adopted, operation_key="offline.native.history")
    row.update(job_id=original["job_id"], request_json=original["request_json"], continuation_original=original,
        continuation_row=dict(job_id=adopted.job_id, root_id=binding.root_id, generation_artifact_id=binding.generation_artifact_id,
            original_job_id=binding.original_job_id, original_lease_generation=binding.original_lease_generation,
            item_id=binding.item_id, version_id=binding.version_id, source_hash=binding.source_hash,
            content_hash=binding.content_hash, operation_key=binding.operation_key, publication_enabled=False,
            binding_json=binding.model_dump(mode="json"), binding_hash=binding.binding_hash))
    facts.update(artifact_hash=original["artifact_hash"], continuation_binding_hash=binding.binding_hash)
    row["preparation_json"].update(request=original["request_json"], artifact_hash=original["artifact_hash"],
        continuation_binding_hash=binding.binding_hash)
    _rehash_native_history(row)
    return row


def _rehash_native_history(row):
    import json
    from app.services.learning.item_supply.shared_admission_facts_contracts import IssuedSharedAdmissionFactsV1
    facts = IssuedSharedAdmissionFactsV1.model_validate_json(json.dumps(row["facts_json"]))
    row["facts_hash"] = facts.receipt_hash
    row["proof_json"]["facts_hash"] = facts.receipt_hash
    row["proof_hash"] = NativePublicationProofV1.model_validate_json(json.dumps(row["proof_json"])).proof_hash
    row["preparation_hash"] = canonical_hash(row["preparation_json"])


def test_native_owner_reads_original491_continued_publication_as_history(monkeypatch):
    row = _continued_publication_row(monkeypatch)
    queries = []

    class ReadHistory:
        def execute(self, sql, params):
            queries.append(sql)
            return SimpleNamespace(fetchall=lambda: [row])

    owner = SimpleNamespace(_guard=lambda: (datetime.now(UTC), 1), conn=ReadHistory(),
        query=SimpleNamespace(artifacts=SimpleNamespace(published_generation_policy=lambda _: __import__(
            "app.services.learning.item_supply.diagnostic_policy", fromlist=["policy_for_hash"]
        ).policy_for_hash(row["proof_json"]["policy_hash"]))), _persist_content=lambda _: None)
    result = NativeTypeEvidenceOwner.resolve_content(owner, UUID(row["proof_json"]["version_id"]), current=False)
    assert result.consumption is None  # historical DATA is not current/execution authority
    assert row["request_json"]["profile"] != result.facts.lease.profile.model_dump(mode="json")
    assert row["preparation_json"]["lease"]["profile"] == result.facts.lease.profile.model_dump(mode="json")
    assert "LEFT JOIN tutor_item_supply_shared_candidate_continuations adoption" in queries[0]
    assert "generation_completed" in queries[0] and "generation_settled" in queries[0]


def test_native_continuation_rejects_changed_preparation_profile(monkeypatch):
    row = _continued_publication_row(monkeypatch)
    row["preparation_json"]["lease"]["profile"]["profile_hash"] = "0"*64
    row["preparation_profile_hash"] = "0"*64
    _rehash_native_history(row)
    with pytest.raises(NativeTypeEvidencePending, match="original_facts_invalid"):
        reconstruct_native_content(row)


def test_native_continuation_requires_actual491_row_and_original_binding(monkeypatch):
    row = _continued_publication_row(monkeypatch)
    continuation = row["continuation_row"]
    row["continuation_row"] = None
    with pytest.raises(NativeTypeEvidencePending, match="original_facts_invalid"):
        reconstruct_native_content(row)
    row["continuation_row"] = continuation
    continuation["binding_json"]["original_request_hash"] = "0"*64
    # Rehash every consumer DTO: none can substitute for the independent original.
    forged_hash = canonical_hash(continuation["binding_json"])
    continuation["binding_hash"] = forged_hash
    row["preparation_json"]["continuation_binding_hash"] = forged_hash
    row["facts_json"]["continuation_binding_hash"] = forged_hash
    _rehash_native_history(row)
    with pytest.raises(NativeTypeEvidencePending, match="original_facts_invalid"):
        reconstruct_native_content(row)


def test_native_same_job_still_requires_exact_original_author_profile(monkeypatch):
    row, _, _, _ = original_row(monkeypatch)
    row["request_json"]["profile"]["profile_hash"] = "0"*64
    row["preparation_json"]["request"] = row["request_json"]
    _rehash_native_history(row)
    with pytest.raises(NativeTypeEvidencePending, match="original_facts_invalid"):
        reconstruct_native_content(row)


def test_committed547_marker_cannot_replace_original_history(monkeypatch):
    row, _, _, _ = original_row(monkeypatch)
    row["committed_admission_history"] = {}
    with pytest.raises(NativeTypeEvidencePending, match="original_facts_invalid"):
        reconstruct_native_content(row)


def test_committed547_checks_issuance_interval_without_reviving_expired_lease(monkeypatch):
    import json
    from app.services.learning.item_supply.jobs import JobLeaseV1
    from app.services.learning.item_supply.native_committed_admission_history import _historical_interval

    row, _, _, _ = original_row(monkeypatch)
    original = JobLeaseV1.model_validate_json(json.dumps(row["facts_json"]["lease"]))
    past = datetime(2000, 1, 1, tzinfo=UTC)
    end = past + timedelta(minutes=5)
    # Offline DATA only: no owner/frame/registry, and no query clock is overridden.
    historical = original.model_copy(update={"expires_at": end, "parent_deadline": end,
        "profile": original.profile.model_copy(update={"bound_at": past, "parent_deadline_at": end})})
    _historical_interval(historical, past, past + timedelta(seconds=1), end)
    with pytest.raises(ValueError, match="original bound"):
        _historical_interval(historical, past, end, end)


def test_committed547_review_top_start_is_not_profile_issuance(monkeypatch):
    import json
    from app.services.learning.item_supply.jobs import JobLeaseV1
    from app.services.learning.item_supply.native_committed_admission_history import _historical_review_interval

    row, _, _, _ = original_row(monkeypatch)
    lease = JobLeaseV1.model_validate_json(json.dumps(row["facts_json"]["lease"]))
    bound = lease.profile.bound_at
    top_start = bound - timedelta(seconds=19)
    receipt_at = bound + timedelta(seconds=78)
    _historical_review_interval(lease, top_start, receipt_at, lease.expires_at)
    for before, after in ((top_start, bound - timedelta(seconds=1)),
                          (top_start, lease.expires_at), (receipt_at + timedelta(seconds=1), receipt_at)):
        with pytest.raises(ValueError, match="original bound|audit order"):
            _historical_review_interval(lease, before, after, lease.expires_at)



def test_current_source_attach_rejects_json_foreign_and_copied_capabilities():
    from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
    from app.services.learning.item_supply.persistent_pack_current_source import IssuedCurrentPackSourceBinding
    from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError

    owner = object.__new__(NativeTypeEvidenceOwner)
    owner.conn, owner.user_id, owner.epoch = object(), uuid4(), 1
    owner.current_source_binding = None
    core = object.__new__(PersistentPackTaskOwner)
    core.conn, core.user_id, core.epoch = owner.conn, owner.user_id, owner.epoch
    core.type_owner, core._current_source_bindings = owner, {}
    copied = object.__new__(IssuedCurrentPackSourceBinding)
    object.__setattr__(copied, "owner", core)
    object.__setattr__(copied, "binding_id", uuid4())
    with pytest.raises(NativeTypeEvidencePending, match="original_owner_required"):
        owner.attach_current_source_binding({"source_current": True})
    core.type_owner = object()
    with pytest.raises(NativeTypeEvidencePending, match="original_owner_required"):
        owner.attach_current_source_binding(copied)
    core.type_owner = owner
    with pytest.raises(PipelineRepositoryError, match="ORIGINAL_ISSUER_REQUIRED"):
        owner.attach_current_source_binding(copied)
    assert owner.current_source_binding is None
    # Direct assignment cannot bypass the registered issuer at actual use either.
    owner.current_source_binding = copied
    with pytest.raises(PipelineRepositoryError, match="ORIGINAL_ISSUER_REQUIRED"):
        owner.source_deadline(None)


def test_current_source_foreign_owner_is_rejected_on_mapping_use(monkeypatch):
    from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
    from app.services.learning.item_supply.persistent_pack_current_source import IssuedCurrentPackSourceBinding

    owner = object.__new__(NativeTypeEvidenceOwner)
    owner.conn, owner.user_id, owner.epoch = object(), uuid4(), 1
    foreign_core = object.__new__(PersistentPackTaskOwner)
    foreign_core.type_owner = object()
    cap = object.__new__(IssuedCurrentPackSourceBinding)
    object.__setattr__(cap, "owner", foreign_core)
    owner.current_source_binding = cap
    monkeypatch.setattr(owner, "_guard", lambda: (datetime.now(UTC), 1))
    with pytest.raises(NativeTypeEvidencePending, match="original_owner_required"):
        owner.resolve_mapping(uuid4())


def _private_mapping_graph(monkeypatch):
    from app.services.learning.item_bank.private_native_publication import PrivateNativePublicationQuery
    from app.services.learning.item_supply.finite_course_mapping import FiniteCourseMappingOwner
    from app.services.learning.item_supply.private_native_type_evidence import PrivateNativeTypeEvidenceOwner

    conn, settings, user = object(), object(), uuid4()
    mapping = object.__new__(FiniteCourseMappingOwner)
    mapping.conn = conn
    query = object.__new__(PrivateNativePublicationQuery)
    query.conn, query.settings, query.user_id, query.epoch = conn, settings, user, 1
    query.source_authority = object()
    public = object.__new__(NativeTypeEvidenceOwner)
    public.conn, public.settings, public.user_id, public.epoch = conn, settings, user, 1
    public.mapping_owner, public.current_source_binding = mapping, None
    private = PrivateNativeTypeEvidenceOwner(conn, settings, query=query, mapping_owner=mapping,
        public_owner=public, enabled=True)
    monkeypatch.setattr(private, '_guard', lambda: (datetime.now(UTC), 1))
    monkeypatch.setattr(public, '_guard', lambda: (datetime.now(UTC), 1))
    return private, public, mapping


def test_private_mapping_source_delegation_and_unchanged_raw_path(monkeypatch):
    from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
    from app.services.learning.item_supply.persistent_pack_current_source import IssuedCurrentPackSourceBinding
    from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending
    from app.services.learning.item_supply.private_native_type_evidence import PrivateNativeTypeEvidenceOwner

    private, public, mapping = _private_mapping_graph(monkeypatch)
    receipt, calls = object(), []
    monkeypatch.setattr(mapping, 'resolve', lambda **kw: calls.append('raw') or SimpleNamespace(receipt=receipt))
    mapping_id = uuid4()
    assert private.resolve_mapping(mapping_id) is receipt
    assert calls == ['raw']
    core = object.__new__(PersistentPackTaskOwner)
    core.conn, core.type_owner, core.user_id, core.epoch = public.conn, public, public.user_id, public.epoch
    cap = object.__new__(IssuedCurrentPackSourceBinding)
    object.__setattr__(cap, 'owner', core)
    object.__setattr__(cap, 'source_deadline', datetime.now(UTC)+timedelta(seconds=60))
    public.current_source_binding = cap
    monkeypatch.setattr(public, 'resolve_mapping', lambda key: calls.append(('original-public', key)) or receipt)
    assert private.resolve_mapping(mapping_id) is receipt
    assert calls == ['raw', ('original-public', mapping_id)]
    object.__setattr__(cap, 'source_deadline', datetime.now(UTC)-timedelta(seconds=1))
    with pytest.raises(PrivateNativePending, match='current_mapping_required'):
        private.resolve_mapping(mapping_id)
    public.mapping_owner = object()
    with pytest.raises(PrivateNativePending, match='original_public_exposure_owner_required'):
        private.resolve_mapping(mapping_id)
    with pytest.raises(PrivateNativePending, match='original_public_exposure_owner_required'):
        PrivateNativeTypeEvidenceOwner(private.conn, private.settings, query=private.query,
            mapping_owner=mapping, public_owner=public)
    assert calls.count('raw') == 1


def test_private_attached_invalid_source_never_falls_back_to_raw_mapping(monkeypatch):
    from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
    from app.services.learning.item_supply.persistent_pack_current_source import IssuedCurrentPackSourceBinding
    from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError

    private, public, mapping = _private_mapping_graph(monkeypatch)
    def no_raw(**kw):
        pytest.fail('invalid attached SOURCE must not fall back to raw mapping')
    monkeypatch.setattr(mapping, 'resolve', no_raw)
    public.current_source_binding = {'source_current': True}
    with pytest.raises(NativeTypeEvidencePending, match='original_owner_required'):
        private.resolve_mapping(uuid4())
    core = object.__new__(PersistentPackTaskOwner)
    core.conn, core.type_owner, core.user_id, core.epoch = public.conn, public, public.user_id, public.epoch
    core._current_source_bindings = {}
    cap = object.__new__(IssuedCurrentPackSourceBinding)
    mapping_id = uuid4()
    for key, value in dict(owner=core, binding_id=uuid4(), task=SimpleNamespace(mapping_receipt_id=mapping_id)).items():
        object.__setattr__(cap, key, value)
    public.current_source_binding = cap
    with pytest.raises(PipelineRepositoryError, match='ORIGINAL_ISSUER_REQUIRED'):
        private.resolve_mapping(mapping_id)
    core.type_owner = object()
    with pytest.raises(NativeTypeEvidencePending, match='original_owner_required'):
        private.resolve_mapping(mapping_id)


def test_private_facts_mapping_port_bound_graph_and_standalone_strict(monkeypatch):
    from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending, PrivateSlotRef
    from app.services.learning.item_supply.private_native_admission_facts import PrivateNativeAdmissionFactsOwner

    private, _, mapping = _private_mapping_graph(monkeypatch)
    facts = object.__new__(PrivateNativeAdmissionFactsOwner)
    facts.conn, facts.settings, facts.mapping_owner = private.conn, private.settings, mapping
    facts.source_authority, facts.type_owner = private.query.source_authority, None
    ref = PrivateSlotRef(pack_task_id=uuid4(), slot_id=uuid4(), business_item_id=uuid4(), root_id=uuid4(),
        mapping_receipt_id=uuid4(), user_id=private.user_id, epoch=1, scope_id=uuid4(), goal_scope_id=uuid4(), slot='assessment')
    monkeypatch.setattr(mapping, 'resolve', lambda **kw: SimpleNamespace(receipt=None))
    with pytest.raises(PrivateNativePending, match='mapping_scope_required'):
        facts.resolve_mapping(ref)
    facts.bind_type_owner(private)
    calls, receipt = [], object()
    monkeypatch.setattr(private, 'resolve_mapping', lambda key: calls.append(key) or receipt)
    assert facts.resolve_mapping(ref) is receipt
    assert calls == [ref.mapping_receipt_id]
    with pytest.raises(PrivateNativePending, match='epoch_required'):
        facts.resolve_mapping(ref.model_copy(update={'epoch': 2}))
    private.mapping_owner = object()
    with pytest.raises(PrivateNativePending, match='same_type_mapping_owner_required'):
        facts.resolve_mapping(ref)


def test_private_author_preio_fences_every_ordered_source_then_exits_to_idle(monkeypatch):
    from contextlib import contextmanager
    from psycopg.pq import TransactionStatus
    from app.services.learning.item_supply.private_enhancement_service import PrivateEnhancementService
    from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending
    from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority

    events = []
    conn = SimpleNamespace(info=SimpleNamespace(transaction_status=TransactionStatus.IDLE))
    @contextmanager
    def transaction():
        conn.info.transaction_status = TransactionStatus.INTRANS
        try:
            yield
        finally:
            conn.info.transaction_status = TransactionStatus.IDLE
            events.append('transaction-exit')
    conn.transaction = transaction
    conn.execute = lambda *args: SimpleNamespace(fetchone=lambda:
        None if 'private_initial_author_recovery_binding_v1' in args[0] else {'ok': True})
    service = object.__new__(PrivateEnhancementService)
    service.conn, service._started, service._results = conn, set(), {}
    service._recovery_bindings = {}
    authority = object.__new__(RagSourceAuthority)
    monkeypatch.setattr(authority, 'assert_current', lambda m, r: events.append((m, r)))
    result = object()
    def run(original, provider):
        assert conn.info.transaction_status == TransactionStatus.IDLE
        assert events[-2:] == ['scope-exit', 'transaction-exit']
        events.append('io')
        return result
    service.facts_owner = SimpleNamespace(source_authority=authority,
        pipeline=SimpleNamespace(run_generation=run), _guard=lambda *args: events.append('private-control'))
    monkeypatch.setattr(service, '_guard', lambda: datetime.now(UTC))
    monkeypatch.setattr(service, '_require_generation', lambda p: object())
    @contextmanager
    def source_front(ref):
        try:
            yield SimpleNamespace(require=lambda: events.append('current-source'),
                source_deadline=datetime.now(UTC)+timedelta(seconds=60))
        finally:
            events.append('scope-exit')
    monkeypatch.setattr(service, '_generation_source_front', source_front)
    request = SimpleNamespace(candidate_id=uuid4(), materials=('m1', 'm2'))
    original = SimpleNamespace(request=request, sources=('r1', 'r2'), lease=object())
    p = SimpleNamespace(ref=SimpleNamespace(pack_task_id=uuid4()), original=original)
    assert service.run_generation(p) is result
    assert events[:5] == ['private-control', ('m1', 'r1'), ('m2', 'r2'), 'current-source', 'private-control']
    with pytest.raises(PrivateNativePending, match='idle_once_required'):
        service.run_generation(p)
    request.candidate_id, original.sources = uuid4(), ('r1',)
    with pytest.raises(PrivateNativePending, match='complete_author_sources_required'):
        service.run_generation(p)
    assert events.count('io') == 1


def test_private_facts_samples_clock_after_slot_wait_and_rechecks_lease(monkeypatch):
    from psycopg.pq import TransactionStatus
    from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending, PrivateSlotRef
    from app.services.learning.item_supply import private_native_admission_facts as facts_module

    entered = datetime.now(UTC)
    clock, wait = [entered], [timedelta(seconds=3)]
    ref = PrivateSlotRef(pack_task_id=uuid4(), slot_id=uuid4(), business_item_id=uuid4(), root_id=uuid4(),
        mapping_receipt_id=uuid4(), user_id=uuid4(), epoch=1, scope_id=uuid4(), goal_scope_id=uuid4(), slot='assessment')
    lease = SimpleNamespace(visibility='private', owner_id=ref.user_id, owner_epoch=ref.epoch, job_id=uuid4(),
        expires_at=entered+timedelta(seconds=5), parent_deadline=entered+timedelta(seconds=10))
    def slot_wait(*args):
        clock[0] += wait[0]
        return SimpleNamespace(fetchone=lambda: {'ok': True})
    owner = object.__new__(facts_module.PrivateNativeAdmissionFactsOwner)
    owner.enabled, owner.type_owner = True, None
    owner.conn = SimpleNamespace(autocommit=False, info=SimpleNamespace(transaction_status=TransactionStatus.INTRANS), execute=slot_wait)
    owner.settings = SimpleNamespace(learning_item_supply_enabled=True, learning_item_v2_admission_enabled=True)
    contexts = []
    owner.pipeline = SimpleNamespace(artifacts=SimpleNamespace(_context=lambda lease, scope, now, mode: contexts.append(now)),
        budget=SimpleNamespace(_job_meta=lambda *args, **kw: {'root_id': ref.root_id}))
    owner.mapping_owner = SimpleNamespace(resolve=lambda **kw: SimpleNamespace(receipt=SimpleNamespace(
        pack_request=SimpleNamespace(demands=(SimpleNamespace(slot=ref.slot, storage_scope_id=ref.goal_scope_id),)))))
    monkeypatch.setattr(facts_module, 'server_clock', lambda *args: clock[0])
    assert owner._guard(ref, lease) == entered+timedelta(seconds=3)
    assert contexts == [entered, entered+timedelta(seconds=3)]
    clock[0], wait[0] = entered, timedelta(seconds=6)
    with pytest.raises(PrivateNativePending, match='current_lease_required'):
        owner._guard(ref, lease)


def _private_phase_data(monkeypatch, *, source_seconds=None, tagged=False):
    from app.services.learning.item_supply.finite_course_mapping import _mapping_hash, _pack
    from app.services.learning.item_supply.finite_course_mapping_contracts import StoredCourseDemandV1
    from app.services.learning.item_supply.finite_course_targets import finite_course_targets
    from app.services.learning.item_supply.parameter_profiles import freeze_profile
    from app.services.learning.item_supply.private_native_pack_executor import PrivateNativePackExecutor
    from app.services.learning.item_supply import private_development_model_accounting as accounting

    target = next(t for t in finite_course_targets() if t.target_id == 'python-kc-binding-v1')
    node, course_profile = frozen(target), profile(target)
    storage_hash = canonical_hash('phase-original-storage')
    primary = FrozenPrivateScope(uuid4(), storage_hash, canonical_hash('original-node'))
    remedial = FrozenPrivateScope(uuid4(), canonical_hash('remedial-storage'), canonical_hash('original-node'))
    pack = _pack(node, course_profile, _mapping_hash(node, course_profile),
        {'practice': primary, 'assessment': primary, 'remediation': remedial})
    mapping = SimpleNamespace(pack_request=pack, stored_demands=tuple(StoredCourseDemandV1(
        slot=d.slot, scope_id=d.storage_scope_id, demand_id=uuid4()) for d in pack.demands))
    task = SimpleNamespace(pack_task_id=uuid4(), user_id=node.user_id, epoch=node.epoch, scope_id=primary.id,
        mapping_receipt_id=uuid4(), demand_id=mapping.stored_demands[0].demand_id)
    slot = SimpleNamespace(slot_id=uuid4())
    spec, materials, _ = _candidate(target.target_id)
    now = datetime.now(UTC)
    state = dict(now=now, events=[], lease_delay=timedelta(), root_id=uuid4())
    def execute(sql, params=()):
        if sql.startswith('SELECT scope_hash'):
            return SimpleNamespace(fetchone=lambda: {'scope_hash': storage_hash})
        assert sql.startswith('SELECT max(profile_version)')
        return SimpleNamespace(fetchone=lambda: {'v': None})
    executor = object.__new__(PrivateNativePackExecutor)
    executor.conn = SimpleNamespace(execute=execute)
    public = None
    if source_seconds is not None:
        from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
        from app.services.learning.item_supply.persistent_pack_current_source import IssuedCurrentPackSourceBinding
        public = object.__new__(NativeTypeEvidenceOwner)
        public.conn, public.user_id, public.epoch = executor.conn, node.user_id, node.epoch
        core = object.__new__(PersistentPackTaskOwner)
        core.conn, core.type_owner, core.user_id, core.epoch = executor.conn, public, node.user_id, node.epoch
        cap = object.__new__(IssuedCurrentPackSourceBinding)
        object.__setattr__(cap, 'owner', core)
        object.__setattr__(cap, 'source_deadline', now+timedelta(seconds=source_seconds))
        public.current_source_binding = cap
    def ensure_root(**kwargs):
        state['root_args'] = kwargs
        state['events'].append('root')
        return state['root_id']
    def enqueue(**kwargs):
        state['profile'], state['job_id'] = kwargs['profile'], uuid4()
        state['events'].append('enqueue')
        return state['job_id']
    def claim(**kwargs):
        snapshot = freeze_profile(state['profile'], bound_at=state['now']+state['lease_delay'])
        state['lease'] = SimpleNamespace(job_id=state['job_id'], profile=snapshot, parent_deadline=snapshot.parent_deadline_at)
        return state['lease']
    def prepare_batch(owner, **kwargs):
        state['events'].append('batch')
        return accounting.PrivateDevelopmentBatchRef(uuid4(), state['root_id'], uuid4(), (), (), now, now+timedelta(seconds=7200))
    monkeypatch.setattr(accounting.PrivateDevelopmentModelAccountingOwner, 'prepare_batch', prepare_batch)
    monkeypatch.setattr(accounting.PrivateDevelopmentModelAccountingOwner, 'bind_job',
        lambda owner, **kwargs: state['events'].append('accounting-bind'))
    executor.runtime = SimpleNamespace(ensure_private_root=ensure_root, enqueue=enqueue, claim=claim)
    executor.service = SimpleNamespace(_guard=lambda: state['now'], development_accounting_enabled=tagged,
        type_owner=SimpleNamespace(resolve_mapping=lambda key: mapping, public_owner=public),
        bind_slot_phase=lambda **kw: state['events'].append('slot-bind') or object(), record_wait_window=lambda **kw: None)
    executor.facts = SimpleNamespace(source_authority=SimpleNamespace(authorize=lambda material: None))
    executor.provider = SimpleNamespace(provider_key='deepseek', configured_model='deepseek-flash')
    executor.development_accounting_enabled = tagged
    monkeypatch.setattr(executor, '_fund', lambda *args: state['events'].append('ordinary-fund'))
    return executor, task, slot, spec, materials, mapping, state


def test_private_phase_actual_practice_anchor_preserves_canonical_obligation_and_legacy_profile(monkeypatch):
    from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending

    executor, task, slot, spec, materials, mapping, state = _private_phase_data(monkeypatch)
    executor._phase(task, slot, spec, materials)
    assert state['root_args']['demand_id'] == task.demand_id == mapping.stored_demands[0].demand_id
    assert task.demand_id != mapping.stored_demands[1].demand_id
    expected = mapping.pack_request.demands[1].demand
    obligation = state['root_args']['obligation']
    assert (obligation.blueprint_hash, obligation.objective_hash, obligation.policy_version) == (
        expected.blueprint_hash, expected.objective_hash, expected.policy_version)
    assert state['profile'].last_stable.parent_deadline_ms == 6000000
    state['events'].clear()
    original = mapping.stored_demands
    mapping.stored_demands = (*original, original[0])
    with pytest.raises(PrivateNativePending, match='original_assessment_storage_required'):
        executor._phase(task, slot, spec, materials)
    assert state['events'] == []
    mapping.stored_demands = original
    practice = mapping.pack_request.demands[0]
    changed = practice.demand.model_copy(update={'scope': practice.demand.scope.model_copy(
        update={'assistance_policy_hash': canonical_hash('different-assistance')})})
    mapping.pack_request = mapping.pack_request.model_copy(update={'demands': (
        practice.model_copy(update={'demand': changed}), *mapping.pack_request.demands[1:])})
    with pytest.raises(PrivateNativePending, match='original_assessment_storage_required'):
        executor._phase(task, slot, spec, materials)
    assert state['events'] == []


def test_private_phase_source_and_batch_fit_precedes_binding_and_rechecks_actual_lease(monkeypatch):
    from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending

    executor, task, slot, spec, materials, _, state = _private_phase_data(monkeypatch, source_seconds=300, tagged=True)
    executor._phase(task, slot, spec, materials)
    assert state['events'] == ['root', 'batch', 'enqueue', 'accounting-bind', 'slot-bind']
    for name in ('initial', 'current', 'last_stable', 'floor', 'ceiling'):
        values = getattr(state['profile'], name)
        assert values.request_timeout_ms == 100000
        assert values.parent_deadline_ms == values.stage_deadline_ms == 200000
    assert state['lease'].profile.parent_deadline_at <= state['now']+timedelta(seconds=300)
    state['events'].clear()
    state['lease_delay'] = timedelta(seconds=101)
    with pytest.raises(PrivateNativePending, match='current_phase_deadline_required'):
        executor._phase(task, slot, spec, materials)
    assert state['events'] == ['root', 'batch', 'enqueue']


def test_private_phase_short_attached_source_denies_before_enqueue_without_accounting(monkeypatch):
    from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending

    executor, task, slot, spec, materials, _, state = _private_phase_data(monkeypatch, source_seconds=60)
    with pytest.raises(PrivateNativePending, match='current_phase_deadline_required'):
        executor._phase(task, slot, spec, materials)
    assert state['events'] == ['root', 'ordinary-fund']


def test_private_ordinary_fund_binds_finite_legacy_resource_cap_without_changing_typed_caps(monkeypatch):
    from app.services.learning.item_supply.private_native_pack_executor import PrivateNativePackExecutor
    from app.services.learning.item_supply import private_development_model_accounting as accounting

    now, root, inserts, global_caps, user_caps = datetime.now(UTC), uuid4(), [], [], []
    task = SimpleNamespace(user_id=uuid4(), epoch=1, scope_id=uuid4())
    suffix = ' AND ordinary_window_filter'
    def execute(sql, params=()):
        if sql.startswith('SELECT id FROM tutor_item_supply_private_budget_windows'):
            assert sql.endswith(suffix) and params == (root, now, now)
            return SimpleNamespace(fetchall=lambda: [])
        inserts.append((sql, params))
    executor = object.__new__(PrivateNativePackExecutor)
    executor.conn = SimpleNamespace(execute=execute)
    executor.service = SimpleNamespace(_guard=lambda: now)
    executor.provider = SimpleNamespace(provider_key='deepseek')
    executor.budget = SimpleNamespace(register_global_limit=lambda **kw: global_caps.append(kw),
        register_user_limit=lambda **kw: user_caps.append(kw))
    monkeypatch.setattr(accounting, 'ordinary_private_window_filter', lambda conn: suffix)
    executor._fund(root, task)
    assert len(inserts) == 1
    sql, params = inserts[0]
    assert 'request_cap,token_cap,resource_cap)' in sql and sql.count('%s') == len(params) == 11
    assert params == (task.user_id, 1, task.scope_id, root, 'enhancement', 'deepseek', now,
        now+timedelta(seconds=7200), 64, (262144+61440)*64, 5)
    expected = dict(requests=64, input_tokens=262144*64, output_tokens=61440*64,
        candidates=5, revision_rounds=8, investigation_rounds=8, execution_seconds=0, fetches=0)
    assert len(global_caps) == 32 and len(user_caps) == 8
    assert all(row['cap_amount'] == expected[row['resource_kind']] for row in (*global_caps, *user_caps))


def _private_base_union_fixture(monkeypatch):
    from app.services.learning.item_supply import private_native_base_fallback as fallback
    from app.services.learning.item_supply.private_enhancement_service import PrivateEnhancementService
    from app.services.learning.item_supply.pack_contracts import NativeExposureV2
    from app.services.learning.item_supply.persistent_pack_contracts import PersistentPackTaskRef
    from tests.learning.test_item_supply_type_evidence_pack_v2 import inputs_v2, with_relationships

    # Offline original-owner port doubles and review DATA, not native permission.
    base = inputs_v2(target_id='python-kc-binding-v1')
    seed = base.candidates[0]
    history = seed.type_evidence.content.model_copy(update={'item_handle': 'li:'+'f'*64,
        'version_id': uuid4(), 'content_hash': 'b'*64, 'actual_public_task_hash': 'c'*64,
        'decision_signature': 'd'*64, 'answer_leakage_signature': 'e'*64})
    event = NativeExposureV2(event_id=uuid4(), item_handle=history.item_handle, content_hash=history.content_hash,
        family_id=seed.member.family_id, semantic_signature=seed.member.semantic_signature, content=history, kind='shown')
    base = base.model_copy(update={'exposure': base.exposure.model_copy(update={'records': (event,), 'watermark': 1})})
    assessments = [c.type_evidence.content for c in base.candidates if c.candidate.slot == 'assessment']
    base = with_relationships(base, extra_pairs=tuple((a, history) for a in assessments))
    union = base.exposure.model_copy(update={'completeness_receipt_hash': 'a'*64})
    ids = tuple(c.version_id for c in base.candidates)
    relation_id, mapping_id = base.relationships[0].receipt_id, uuid4()
    task = PersistentPackTaskRef(pack_task_id=uuid4(), user_id=base.request.learner_id, epoch=base.request.epoch,
        demand_id=uuid4(), mapping_receipt_id=mapping_id,scope_id=uuid4(),public_task_id=uuid4(),
        intent_hash=canonical_hash('offline original union task'))
    mapping = SimpleNamespace(receipt_id=mapping_id, pack_request=base.request)
    calls, collected, captured = [], [], []
    def execute(sql, params=()):
        if sql.startswith('SELECT id FROM tutor_item_supply_native_relation_batches'):
            return SimpleNamespace(fetchall=lambda: [{'id': relation_id}])
        if sql.startswith('SELECT id FROM tutor_item_supply_private_native_quality_evidence'):
            return SimpleNamespace(fetchall=lambda: [])
        assert sql.startswith('SELECT id FROM tutor_item_supply_private_persistent_pack_journal')
        return SimpleNamespace(fetchone=lambda: None)
    public = object.__new__(NativeTypeEvidenceOwner)
    public.conn, public.current_source_binding = SimpleNamespace(execute=execute), None
    current_contents = {c.version_id: SimpleNamespace(content=c.type_evidence.content) for c in base.candidates}
    def resolve_content(version, *, current):
        calls.append((version, current))
        if version == history.version_id:
            assert current is False
            return SimpleNamespace(content=history)
        assert current is True
        return current_contents[version]
    def relation_arguments(receipts, bound_mapping, contents, now):
        assert receipts == (relation_id,) and bound_mapping is mapping
        assert set(contents) == {*ids, history.version_id}
        assert now == base.exposure.observed_at+timedelta(milliseconds=1)
        return tuple(r.model_dump(exclude={'exposure_receipt_hash', 'exposure_watermark'}) for r in base.relationships)
    monkeypatch.setattr(public, 'resolve_content', resolve_content)
    monkeypatch.setattr(public, 'resolve_mapping', lambda value: mapping)
    monkeypatch.setattr(public, '_relation_arguments', relation_arguments)
    monkeypatch.setattr(public, 'resolve_pack', lambda *args: SimpleNamespace(eligibility_id=uuid4()))
    monkeypatch.setattr(public, 'require_pack', lambda cap: None)
    monkeypatch.setattr(public, '_inputs', lambda *args: base)
    service = object.__new__(PrivateEnhancementService)
    service.conn, service.settings = public.conn, object()
    monkeypatch.setattr(service, '_guard', lambda: None)
    service.core = SimpleNamespace(_task=lambda ref: SimpleNamespace(enhancement='prefer_private'),
        _private_event=lambda *args, **kwargs: None)
    service.base_service = SimpleNamespace(type_owner=public,
        _reservation=lambda demand: {'request_json': {'mapping_receipt_id': str(mapping_id),
            'candidate_version_ids': [str(v) for v in ids]}},
        exposure_owner=SimpleNamespace(snapshot_v2=lambda: SimpleNamespace(snapshot_id=uuid4())))
    def snapshot_complete():
        collected.append('union')
        return SimpleNamespace(snapshot_id=uuid4(), exposure=union)
    service.exposure_owner = SimpleNamespace(snapshot_complete=snapshot_complete)
    clocks = iter((base.exposure.observed_at+timedelta(milliseconds=1),
        base.exposure.observed_at+timedelta(milliseconds=2)))
    service.type_owner = SimpleNamespace(_guard=lambda: (next(clocks), 81))
    original_build = fallback.build_pack
    def observe(inputs, *, now):
        result = original_build(inputs, now=now)
        captured.append((inputs, result))
        assert result.snapshot is not None, (result.status, result.reasons)
        return result
    monkeypatch.setattr(fallback, 'build_pack', observe)
    owner = fallback.PrivateNativeBaseFallbackOwner(service)
    return SimpleNamespace(owner=owner, task=task, public=public, service=service, mapping=mapping,
        base=base, union=union, ids=ids, relation_id=relation_id, history=history,
        calls=calls, collected=collected, captured=captured)


def test_private_base_union_uses_original_public_relation_projection_and_history(monkeypatch):
    from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending

    fixture = _private_base_union_fixture(monkeypatch)
    # The actual builder succeeds with the new context. No real journal receipt
    # exists in this pure fixture, so the original permission receiver still denies.
    with pytest.raises(PrivateNativePending, match='current_original_receipt_required'):
        fixture.owner.resolve(fixture.task)
    inputs, result = fixture.captured[0]
    assert result.snapshot is not None and fixture.collected == ['union']
    assert fixture.calls == [(v, True) for v in fixture.ids]+[(fixture.history.version_id, False)]
    assert inputs.exposure == fixture.union
    for projected, old in zip(inputs.relationships, fixture.base.relationships, strict=True):
        assert projected.exposure_receipt_hash == fixture.union.completeness_receipt_hash
        assert projected.exposure_watermark == fixture.union.watermark
        assert (projected.receipt_id, projected.receipt_hash, projected.checked_at, projected.valid_until, projected.reviews) == (
            old.receipt_id, old.receipt_hash, old.checked_at, old.valid_until, old.reviews)


def _private_base_union_scoped_fixture(monkeypatch, *, issued=False):
    from app.services.learning.item_supply.native_type_evidence import _CurrentPackData
    from app.services.learning.item_supply.native_type_contracts import IssuedNativePackCapability
    from app.services.learning.item_supply.native_type_exposure import NativeExposureOwnerV2
    from app.services.learning.item_supply.native_type_exposure_contracts import NativeTypeExposureSnapshot
    from app.services.learning.item_supply.pack_builder import build_pack

    fixture = _private_base_union_fixture(monkeypatch)
    public, service, base = fixture.public, fixture.service, fixture.base
    public.settings, public.user_id, public.epoch = service.settings, fixture.task.user_id, fixture.task.epoch
    exposure_owner = object.__new__(NativeExposureOwnerV2)
    exposure_owner.conn, exposure_owner.type_owner = public.conn, public
    exposure_owner.user_id, exposure_owner.epoch = public.user_id, public.epoch
    observation = NativeTypeExposureSnapshot('complete', 'offline-original-scope', base.exposure, uuid4())
    service.base_service.exposure_owner = exposure_owner
    monkeypatch.setattr(exposure_owner, 'snapshot_v2', lambda: observation)
    snapshot = build_pack(base, now=base.exposure.observed_at).snapshot
    assert snapshot is not None
    cap = IssuedNativePackCapability(uuid4(), snapshot)
    contents = {c.version_id: SimpleNamespace(content=c.type_evidence.content, publication=SimpleNamespace(
        version_id=c.version_id, proof_id=c.proof_id, publication_event_id=c.publication_id,
        materialization_id=c.materialization_id)) for c in base.candidates}
    scoped = _CurrentPackData(81, fixture.task.mapping_receipt_id, tuple(sorted(fixture.ids, key=str)),
        (fixture.relation_id,), exposure_owner, None, mapping=fixture.mapping, contents=contents,
        historical={fixture.history.version_id: SimpleNamespace(content=fixture.history,
            publication=SimpleNamespace(version_id=fixture.history.version_id))},
        observation=observation, inputs=base, capability=cap)
    public._pack_scope = scoped
    monkeypatch.setattr(public, '_guard', lambda: (base.exposure.observed_at, 81))
    monkeypatch.setattr(public, 'resolve_pack', lambda *args: NativeTypeEvidenceOwner.resolve_pack(public, *args))
    verifies = []
    monkeypatch.setattr(public, 'require_pack', lambda value: verifies.append(value))
    def no_reread(*args, **kwargs):
        pytest.fail('same original scope must not rerun strict immutable DATA reads')
    for name in ('_inputs', 'resolve_content', 'resolve_mapping'):
        monkeypatch.setattr(public, name, no_reread)
    fixture.scoped,fixture.public_cap,fixture.verifies=scoped,cap,verifies
    if issued:
        # These are pure receiver doubles, not live SQL/current-source evidence.
        fixture.current = dict(public_ok=True, private_ok=True, private_relations=(), txid=81, journals=0)
        original_execute = public.conn.execute
        def execute(sql, params=()):
            if sql.startswith('SELECT id FROM tutor_item_supply_private_persistent_pack_journal'):
                fixture.current['journals'] += 1
                return SimpleNamespace(fetchone=lambda: {'id': uuid4()})
            if sql.startswith('SELECT id FROM tutor_item_supply_private_native_quality_evidence'):
                return SimpleNamespace(fetchall=lambda: [{'id': r} for r in fixture.current['private_relations']])
            if sql.startswith('SELECT item_supply_internal.private_native_base_union_current'):
                verifies.append('final-private-receiver')
                return SimpleNamespace(fetchone=lambda: {'ok': fixture.current['private_ok']})
            return original_execute(sql, params)
        public.conn.execute = execute
        def require_public(value):
            verifies.append(value)
            if not fixture.current['public_ok']:
                raise NativeTypeEvidencePending('offline_public_current_or_expiry_denied')
        monkeypatch.setattr(public, 'require_pack', require_public)
        service.type_owner._guard = lambda: (base.exposure.observed_at+timedelta(milliseconds=1), fixture.current['txid'])
    return fixture


def test_private_base_union_same_scope_reuses_data_but_keeps_final_require_and_denies_missing_data(monkeypatch):
    from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending

    fixture=_private_base_union_scoped_fixture(monkeypatch)
    public,service,base=fixture.public,fixture.service,fixture.base
    scoped,cap,verifies=fixture.scoped,fixture.public_cap,fixture.verifies
    original_execute = public.conn.execute
    journal_id = uuid4()
    def execute(sql, params=()):
        if sql.startswith('SELECT id FROM tutor_item_supply_private_persistent_pack_journal'):
            return SimpleNamespace(fetchone=lambda: {'id': journal_id})
        if sql.startswith('SELECT item_supply_internal.private_native_base_union_current'):
            verifies.append('final-private-receiver')
            return SimpleNamespace(fetchone=lambda: {'ok': False})
        return original_execute(sql, params)
    public.conn.execute = execute
    clocks = iter(base.exposure.observed_at+timedelta(milliseconds=i) for i in (1, 2, 3))
    service.type_owner._guard = lambda: (next(clocks), 81)
    # The fixture grants no native permission: final original SQL still denies.
    with pytest.raises(PrivateNativePending, match='current_whole_union_receiver_required'):
        fixture.owner.resolve(fixture.task)
    assert verifies == [cap, cap, 'final-private-receiver']
    assert fixture.calls == [] and fixture.captured[0][1].snapshot is not None
    scoped.inputs = None
    with pytest.raises(PrivateNativePending, match='same_scope_union_data_required'):
        fixture.owner.resolve(fixture.task)
    assert len(fixture.collected) == 1 and fixture.calls == []


def test_private_base_union_issued_same_scope_preserves_data_and_repeats_both_current_receivers(monkeypatch):
    from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending

    fixture = _private_base_union_scoped_fixture(monkeypatch, issued=True)
    owner, public_cap = fixture.owner, fixture.public_cap
    cap = owner.resolve(fixture.task)
    original_data = (cap.receipt_id, cap.snapshot, cap.inputs, cap.exposure_snapshot_id,
        cap.snapshot.checked_at, cap.snapshot.valid_until)
    assert owner._issued[cap.receipt_id] == (cap, 81)  # Actual two-tuple issuer ABI.
    assert owner.resolve(fixture.task) is cap
    assert owner.resolve(fixture.task) is cap
    assert (cap.receipt_id, cap.snapshot, cap.inputs, cap.exposure_snapshot_id,
        cap.snapshot.checked_at, cap.snapshot.valid_until) == original_data
    assert fixture.verifies == [public_cap, public_cap, 'final-private-receiver']*3
    assert cap.snapshot is original_data[1] and cap.inputs is original_data[2]
    fixture.current['private_ok'] = False
    with pytest.raises(PrivateNativePending, match='current_whole_union_receiver_required'):
        owner.resolve(fixture.task)
    fixture.current['public_ok'] = False
    with pytest.raises(NativeTypeEvidencePending, match='offline_public_current_or_expiry_denied'):
        owner.resolve(fixture.task)
    assert fixture.verifies == [public_cap, public_cap, 'final-private-receiver']*4+[public_cap]
    assert len(fixture.collected) == len(fixture.captured) == fixture.current['journals'] == 1
    assert fixture.calls == []


@pytest.mark.parametrize('damage', ('issuer', 'registry_abi', 'seal', 'private_relations', 'graph', 'scope', 'missing_cap'))
def test_private_base_union_same_scope_corruption_denies_without_rebuilding(monkeypatch, damage):
    from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending

    fixture = _private_base_union_scoped_fixture(monkeypatch, issued=True)
    owner, scoped = fixture.owner, fixture.scoped
    cap = owner.resolve(fixture.task)
    cached = owner._scope_union
    if damage == 'issuer':
        owner._issued[cap.receipt_id] = (replace(cap), 81)
    elif damage == 'registry_abi':
        owner._issued[cap.receipt_id] = (cap, 81, cached.seal)
    elif damage == 'seal':
        cached.payload['checked_at'] = (cap.snapshot.checked_at+timedelta(seconds=1)).isoformat()
    elif damage == 'private_relations':
        fixture.current['private_relations'] = (uuid4(),)
        owner._scope_union = replace(cached, private_relations=fixture.current['private_relations'])
    elif damage == 'graph':
        fixture.service.core = SimpleNamespace(**vars(fixture.service.core))
    elif damage == 'scope':
        owner._scope_union = replace(cached, scope=replace(scoped))
    else:
        scoped.capability = None
    with pytest.raises(PrivateNativePending, match='same_scope_union_data_required'):
        owner.resolve(fixture.task)
    assert len(fixture.collected) == len(fixture.captured) == fixture.current['journals'] == 1
    assert fixture.calls == []


def test_private_base_union_new_scope_issues_new_data_instead_of_reusing_previous_scope(monkeypatch):
    fixture = _private_base_union_scoped_fixture(monkeypatch, issued=True)
    first = fixture.owner.resolve(fixture.task)
    new_public = IssuedNativePackCapability(uuid4(), fixture.public_cap.snapshot)
    fixture.public._pack_scope = replace(fixture.scoped, capability=new_public)
    second = fixture.owner.resolve(fixture.task)
    assert second is not first and second.receipt_id != first.receipt_id
    assert second.public_capability is new_public
    assert fixture.owner._recent_scope is fixture.public._pack_scope
    assert len(fixture.collected) == len(fixture.captured) == fixture.current['journals'] == 2
    assert fixture.calls == []


def test_private_facts_current_source_front_reissues_exact_core_and_rejects_copy_ref_and_service_core(monkeypatch):
    from contextlib import contextmanager
    from app.services.learning.item_supply.private_native_admission_facts import PrivateNativeAdmissionFactsOwner
    from app.services.learning.item_supply.private_enhancement_service import PrivateEnhancementService
    from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending, PrivateSlotRef
    from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
    from app.services.learning.item_supply.persistent_pack_contracts import PersistentPackTaskRef
    from app.services.learning.item_supply.persistent_pack_current_source import IssuedCurrentPackSourceBinding, SOURCE_DATA, _seal
    from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority

    private, public, mapping = _private_mapping_graph(monkeypatch)
    authority = object.__new__(RagSourceAuthority)
    authority._current = SimpleNamespace(conn=private.conn)
    private.query.source_authority = public.source_authority = authority
    facts = object.__new__(PrivateNativeAdmissionFactsOwner)
    facts.conn, facts.settings, facts.mapping_owner = private.conn, private.settings, mapping
    facts.source_authority, facts.type_owner = authority, private
    ref = PrivateSlotRef(pack_task_id=uuid4(), slot_id=uuid4(), business_item_id=uuid4(), root_id=uuid4(),
        mapping_receipt_id=uuid4(), user_id=private.user_id, epoch=1, scope_id=uuid4(), goal_scope_id=uuid4(), slot='assessment')
    task = PersistentPackTaskRef(pack_task_id=ref.pack_task_id, user_id=ref.user_id, epoch=ref.epoch,
        scope_id=ref.scope_id, mapping_receipt_id=ref.mapping_receipt_id, demand_id=uuid4(), intent_hash='a'*64, public_task_id=uuid4())
    core = object.__new__(PersistentPackTaskOwner)
    core.conn, core.settings, core.type_owner = facts.conn, facts.settings, public
    core.user_id, core.epoch, core._current_source_bindings = ref.user_id, ref.epoch, {}
    old = IssuedCurrentPackSourceBinding(core, uuid4(), task, 'b'*64, 'c'*64, 'd'*64,
        datetime.now(UTC)+timedelta(hours=1), (), (), SimpleNamespace(model_dump=lambda **kw: {'offline': 'mapping-data'}))
    core._current_source_bindings[old.binding_id] = (old, _seal(old))
    public.current_source_binding = old
    events = []
    def issue(bound_task, *, source_data_id):
        assert bound_task == task and source_data_id == SOURCE_DATA
        actual = replace(old, binding_id=uuid4())
        core._current_source_bindings[actual.binding_id] = (actual, _seal(actual))
        events.append('issue')
        return actual
    def attach(actual):
        assert actual is not old and actual.owner is core
        public.current_source_binding = actual
        events.append('attach')
    @contextmanager
    def scope(actual):
        assert public.current_source_binding is actual
        events.append('scope-enter')
        try:
            yield
        finally:
            events.append('scope-exit')
    monkeypatch.setattr(core, 'issue_current_source_binding', issue)
    monkeypatch.setattr(core, '_task', lambda value: SimpleNamespace(enhancement='prefer_private'))
    monkeypatch.setattr(public, 'attach_current_source_binding', attach)
    monkeypatch.setattr(IssuedCurrentPackSourceBinding, 'current_scope', scope)
    service = object.__new__(PrivateEnhancementService)
    service.facts_owner, service.core = facts, core
    with service._generation_source_front(ref) as actual:
        assert actual.owner is core and actual is not old
    assert events == ['issue', 'attach', 'scope-enter', 'scope-exit']
    assert public.current_source_binding is None
    events.clear()
    public.current_source_binding = old
    with pytest.raises(PrivateNativePending, match='original_task_source_binding_required'):
        with facts.current_source_front(ref.model_copy(update={'pack_task_id': uuid4()})):
            pytest.fail('wrong ref must not enter source scope')
    public.current_source_binding = replace(old)
    with pytest.raises(PrivateNativePending, match='original_task_source_binding_required'):
        with facts.current_source_front(ref):
            pytest.fail('copied cap must not enter source scope')
    assert events == []
    public.current_source_binding = old
    service.core = object()
    with pytest.raises(PrivateNativePending, match='original_task_source_binding_required'):
        with service._generation_source_front(ref):
            pytest.fail('service must retain its exact core identity')
    assert public.current_source_binding is None
    facts.type_owner = None
    with facts.current_source_front(ref) as absent:
        assert absent is None


def test_private_review_preio_exact_sources_postwait_clock_idle_once_and_independent_settlement(monkeypatch):
    from contextlib import contextmanager
    from psycopg.pq import TransactionStatus
    from app.services.learning.item_supply import private_native_admission_facts as facts_module
    from app.services.learning.item_supply.finite_candidate_factory import build_finite_generation_request
    from app.services.learning.item_supply.generation_contracts import GenerationReceiptV2, ProviderReceiptV2, ProviderUsageV2
    from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending
    from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
    from tests.learning.test_item_supply_generation import make_request

    initial, _ = make_request()
    spec, materials, source = _candidate('python-kc-binding-v1')
    request = build_finite_generation_request(spec, candidate_id=uuid4(), profile=initial.profile,
        limits=initial.limits, materials=materials)
    now = datetime.now(UTC)
    receipts = tuple(SourceReceiptV2(material_digest=material_digest(m), binding_digest=m.binding.binding_digest,
        corpus_version_id=UUID(m.binding.evidence[0].corpus_version_id), active_generation=m.binding.evidence[0].active_generation,
        checked_at_iso=now.isoformat(), claim_receipt_hashes=('c'*64,), mode='current_authority') for m in materials)
    generation = GenerationReceiptV2(candidate_id=request.candidate_id, scope_hash=request.scope_hash, sources=receipts,
        provider=ProviderReceiptV2(provider='offline', provider_version='offline-v1', configured_model='offline', model='offline',
            prompt_version='offline-v1', run_id=uuid4(), request_attempt_bound=1, usage=ProviderUsageV2(state='unknown'), mode='synthetic'))
    artifact = {'request_json': request.model_dump(mode='json'), 'receipt_json': generation.model_dump(mode='json')}
    events, clock, margin, settlements = [], [now], [timedelta(milliseconds=1)], []
    conn = SimpleNamespace(info=SimpleNamespace(transaction_status=TransactionStatus.IDLE))
    @contextmanager
    def transaction():
        conn.info.transaction_status = TransactionStatus.INTRANS
        try:
            yield
        finally:
            conn.info.transaction_status = TransactionStatus.IDLE
            events.append('transaction-exit')
    conn.transaction = transaction
    conn.execute = lambda *args: SimpleNamespace(fetchone=lambda: {'ok': True})
    facts = object.__new__(facts_module.PrivateNativeAdmissionFactsOwner)
    facts.conn, facts._started = conn, set()
    solver = SimpleNamespace(blind_protocol='single_choice_v1')
    monkeypatch.setattr(facts, '_require', lambda p: (object(), solver, tuple(object() for _ in range(6))))
    monkeypatch.setattr(facts, '_artifact', lambda *args: artifact)
    monkeypatch.setattr(facts, '_guard', lambda *args: events.append('private-control') or clock[0])
    monkeypatch.setattr(facts_module, 'server_clock', lambda *args: events.append('server-clock') or clock[0])
    authority = object.__new__(RagSourceAuthority)
    def assert_current(material, expected):
        index = materials.index(material)
        assert expected == receipts[index]
        events.append(('source', index))
        clock[0] += timedelta(milliseconds=10)
    monkeypatch.setattr(authority, 'assert_current', assert_current)
    facts.source_authority = authority
    @contextmanager
    def current_front(ref):
        assert conn.info.transaction_status == TransactionStatus.INTRANS
        try:
            yield SimpleNamespace(require=lambda: events.append('current-source'), source_deadline=clock[0]+margin[0])
        finally:
            events.append('scope-exit')
    monkeypatch.setattr(facts, 'current_source_front', current_front)
    lease = SimpleNamespace(expires_at=now+timedelta(hours=1), parent_deadline=now+timedelta(hours=1))
    original = SimpleNamespace(lease=lease, artifact_id=uuid4(), source=source, binding=object(), author_identity='offline.author', reservation_id=uuid4())
    p = SimpleNamespace(preparation_id=uuid4(), ref=SimpleNamespace(pack_task_id=uuid4()), original=original,
        request=request.model_copy(update={'candidate_id': uuid4()}), spec=spec)
    with pytest.raises(PrivateNativePending, match='exact_prepared_sources_required'):
        facts.run_review(p)
    assert facts._started == set()
    p.request = request
    events.clear()
    with pytest.raises(PrivateNativePending, match='current_source_required'):
        facts.run_review(p)
    assert facts._started == set() and events[-4:] == ['private-control', 'server-clock', 'scope-exit', 'transaction-exit']
    margin[0] = timedelta(minutes=1)
    events.clear()
    class BlindBoundaryReached(Exception):
        pass
    def blind(*args, **kwargs):
        assert conn.info.transaction_status == TransactionStatus.IDLE
        assert events[-2:] == ['scope-exit', 'transaction-exit']
        events.append('blind-boundary')
        raise BlindBoundaryReached
    monkeypatch.setattr(facts_module, 'blind_solve_candidate', blind)
    with pytest.raises(BlindBoundaryReached):
        facts.run_review(p)
    assert events[:len(materials)] == [('source', i) for i in range(len(materials))]
    assert p.preparation_id in facts._started
    with pytest.raises(PrivateNativePending, match='idle_once_required'):
        facts.run_review(p)
    facts.pipeline = SimpleNamespace(budget=SimpleNamespace(settle=lambda **kw: settlements.append(kw)))
    with conn.transaction():
        facts.settle_review(p)
    assert len(settlements) == 1 and settlements[0]['usage_state'] == 'unknown'


def test_private_initial_recovery_cap_identity_and_exact_first_claim(monkeypatch):
    from dataclasses import replace
    from app.services.learning.item_bank.contracts import canonical_hash
    from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending
    from app.services.learning.item_supply.private_enhancement_service import (
        PrivateEnhancementService, IssuedPrivateInitialAuthorRecovery, RECOVERY_SLOT,
    )

    service = object.__new__(PrivateEnhancementService)
    task, core, approval = SimpleNamespace(pack_task_id=uuid4(), user_id=uuid4(), epoch=1), object(), uuid4()
    payload = {'offline_fixture': 'new-approval'}
    cap = IssuedPrivateInitialAuthorRecovery(service,task,RECOVERY_SLOT,approval)
    service.core, service._recoveries = core, {approval: (cap,canonical_hash(payload),core)}
    calls, claimed = [], set()
    job, batch, origin = uuid4(), uuid4(), uuid4()
    lease = SimpleNamespace(job_id=job)
    def execute(sql, params):
        if 'first_claim' in sql:
            assert params == (approval,job,batch,origin,'private.initial.author.recovery.'+approval.hex)
            assert job not in claimed
            claimed.add(job)
            calls.append('exact-first-claim')
            row = {'job_id': job}
        else:
            row = {'payload_json': payload}
        return SimpleNamespace(fetchone=lambda: row)
    service.conn = SimpleNamespace(execute=execute)
    service.facts_owner = SimpleNamespace(pipeline=SimpleNamespace(runtime=SimpleNamespace(
        _lease=lambda row, visibility: lease if row['job_id']==job and visibility=='private' else pytest.fail('wrong lease'),
        _control=lambda actual, **kw: calls.append('original-control') if actual is lease else pytest.fail('wrong control'))))
    monkeypatch.setattr(service,'_guard',lambda: datetime.now(UTC))
    monkeypatch.setattr(service,'_recovery_receivers',lambda: None)
    monkeypatch.setattr(service,'_recovery_source',lambda actual: SimpleNamespace(origin_id=lambda: origin))
    with pytest.raises(PrivateNativePending,match='original_issued_cap_required'):
        service._require_initial_recovery(replace(cap))
    with pytest.raises(PrivateNativePending,match='original_issued_cap_required'):
        service._require_initial_recovery(replace(cap,owner=object()))
    assert service.claim_initial_author_recovery(cap,job_id=job,batch_id=batch) is lease
    assert calls == ['exact-first-claim','original-control']
    # A retained DATA id cannot recreate this service's issued object registry.
    service._recoveries.clear()
    with pytest.raises(PrivateNativePending,match='original_issued_cap_required'):
        service.claim_initial_author_recovery(cap,job_id=job,batch_id=batch)
    assert calls == ['exact-first-claim','original-control']


def test_private_initial_recovery_author_consumes_inside_preio_before_idle_once(monkeypatch):
    from contextlib import contextmanager
    from psycopg.pq import TransactionStatus
    from app.services.learning.item_supply.private_enhancement_service import (
        IssuedPrivateInitialAuthorRecovery,
    )
    from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending

    from tests.learning.test_private_author_continuation import _task
    from tests.learning.test_private_generation_durability import fixture as durability_fixture

    # Real typed live objects; only SQL/source/provider ports are offline seams.
    fixture = durability_fixture(monkeypatch, run=False)
    service, p, result = fixture.service, fixture.p, fixture.result
    events, key, binding = [], p.original.request.candidate_id, uuid4()
    conn = SimpleNamespace(autocommit=False, info=SimpleNamespace(transaction_status=TransactionStatus.IDLE))
    @contextmanager
    def transaction():
        conn.info.transaction_status=TransactionStatus.INTRANS
        try:
            yield
        finally:
            conn.info.transaction_status=TransactionStatus.IDLE
            events.append('commit-before-io')
    def execute(sql, params=()):
        if 'private_generation_durability_ready()' in sql:
            assert conn.info.transaction_status==TransactionStatus.INTRANS
            events.append('ready')
            return SimpleNamespace(fetchone=lambda: {'ready': True})
        if 'recovery_consume' in sql:
            assert conn.info.transaction_status==TransactionStatus.INTRANS
            assert params==(binding,origin)
            events.append('consume')
        else:
            assert 'private_pack_auxiliary_committed' in sql
        return SimpleNamespace(fetchone=lambda: {'ok': True})
    conn.transaction, conn.execute = transaction, execute
    now, origin = datetime.now(UTC), uuid4()
    cap = IssuedPrivateInitialAuthorRecovery(service,_task(),p.ref.slot_id,uuid4())
    service.conn, service._started, service._results = conn,set(),{}
    service._recovery_bindings={key:(p,cap,binding)}
    @contextmanager
    def front(ref):
        try:
            yield SimpleNamespace(require=lambda: None,source_deadline=now+timedelta(hours=1),origin_id=lambda: origin)
        finally:
            events.append('scope-exit')
    def run(original, provider):
        assert original is p.original and provider is service._prepared[key][2]
        assert conn.info.transaction_status==TransactionStatus.IDLE
        assert events[-3:]==['consume','scope-exit','commit-before-io']
        assert key in service._started
        events.append('original-pipeline-io')
        return result
    service.facts_owner=SimpleNamespace(_guard=lambda *a: now,source_authority=SimpleNamespace(
        assert_current=lambda m,r: events.append('ordered-source')),pipeline=SimpleNamespace(run_generation=run))
    monkeypatch.setattr(service,'_guard',lambda: now)
    monkeypatch.setattr(service,'_select_initial_recovery_source',lambda actual: None)
    monkeypatch.setattr(service,'_generation_source_front',front)
    monkeypatch.setattr(service,'_prepared_recovery',lambda actual:(cap,binding))
    assert service.run_generation(p) is result
    observed = service._observed_generation_outputs[key]
    assert observed.prepared is p and observed.result is result
    assert events.index('ready') < events.index('consume')
    with pytest.raises(PrivateNativePending,match='idle_once_required'):
        service.run_generation(p)
    assert events.count('consume')==events.count('original-pipeline-io')==1


def test_private_initial_recovery_finish_and_quality_reuse_live_work_no_claim(monkeypatch):
    from contextlib import contextmanager
    from psycopg.pq import TransactionStatus
    import app.services.learning.item_supply.private_native_pack_executor as module
    import app.services.learning.item_supply.private_development_model_accounting as accounting
    from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending

    events, now, key, artifact, validation = [], datetime.now(UTC), uuid4(), uuid4(), uuid4()
    conn=SimpleNamespace(info=SimpleNamespace(transaction_status=TransactionStatus.IDLE))
    @contextmanager
    def transaction():
        conn.info.transaction_status=TransactionStatus.INTRANS
        try:
            yield
        finally:
            conn.info.transaction_status=TransactionStatus.IDLE
            events.append('commit')
    @contextmanager
    def source(task):
        yield
    conn.transaction=transaction
    conn.execute=lambda *args:SimpleNamespace(fetchone=lambda:{'id':artifact})
    profile=SimpleNamespace(profile_hash='offline',bound_at=now,parent_deadline_at=now+timedelta(hours=1),
        values=SimpleNamespace(request_timeout_ms=100000,stage_deadline_ms=3600000))
    lease=SimpleNamespace(job_id=uuid4(),profile=profile,expires_at=now+timedelta(hours=1),parent_deadline=now+timedelta(hours=1))
    work=SimpleNamespace(task=SimpleNamespace(pack_task_id=uuid4()),slot=SimpleNamespace(slot_id=uuid4()),
        ref=SimpleNamespace(slot_id=uuid4()),lease=lease,spec=SimpleNamespace(public_template=SimpleNamespace(version='v1')))
    work.ref.slot_id=work.slot.slot_id
    author=SimpleNamespace(original=SimpleNamespace(request=SimpleNamespace(candidate_id=key),reservation_id=uuid4()))
    result, cap = SimpleNamespace(state='staged'), object()
    owner=object.__new__(module.PrivateNativePackExecutor)
    owner.conn, owner.settings=conn,object()
    owner._initial_authors={key:(author,cap,work)}
    owner._initial_finished,owner._initial_success,owner._initial_reviews,owner._review=set(),{},{},{}
    current=SimpleNamespace(source_deadline=now+timedelta(hours=1),require=lambda:None)
    def no_claim(*a,**kw):
        pytest.fail('same live recovery quality must not create/claim/inherit a phase')
    owner.runtime=SimpleNamespace(next_stage=lambda actual:'validating',claim=no_claim)
    owner.progress=SimpleNamespace(inherit_generation=no_claim)
    monkeypatch.setattr(owner,'_phase',no_claim)
    monkeypatch.setattr(owner,'_refresh',lambda actual:actual)
    monkeypatch.setattr(owner,'_stage',lambda actual,stage,**kw:events.append(stage))
    monkeypatch.setattr(owner,'_identity',lambda *a:object())
    def persist(prepared, actual):
        assert prepared is author and actual is result
        events.append('original-persist')
        return artifact
    owner.service=SimpleNamespace(_results={key:result},_fresh_recovery_source=source,persist_generation=persist,
        _recovery_source=lambda task:current,_guard=lambda:now,_select_initial_recovery_source=lambda actual:None)
    owner.facts=SimpleNamespace(_guard=lambda *a:now,validate=lambda **kw:(validation,object()))
    outcome=owner.finish_initial_author_recovery(author,result)
    assert outcome.status=='review_pending' and events==['original-persist','author','commit']
    assert owner._initial_success[key]==(author,work,artifact)
    with pytest.raises(PrivateNativePending,match='original_live_author_required'):
        owner.finish_initial_author_recovery(author,result)
    prepared_review=SimpleNamespace(preparation_id=uuid4(),ref=work.ref)
    def prepare_review(**kw):
        assert kw['ref'] is work.ref and kw['lease'] is lease and kw['artifact_id']==artifact
        return prepared_review
    owner.facts.prepare_review=prepare_review
    monkeypatch.setattr(accounting,'accounting_batch_for_lease',lambda *a,**kw:{'valid_until':now+timedelta(hours=1)})
    monkeypatch.setattr(module,'BoundedOpenAIReviewClient',lambda *a,**kw:object())
    monkeypatch.setattr(module,'JsonBlindSolverV2',lambda *a,**kw:object())
    monkeypatch.setattr(module,'JsonReviewerV2',lambda *a,**kw:object())
    with conn.transaction():
        assert owner.prepare_initial_recovery_review(author) is prepared_review
    assert owner._initial_reviews[work.slot.slot_id][0] is prepared_review
    current.source_deadline=now+timedelta(seconds=100)
    with pytest.raises(PrivateNativePending,match='quality_current_work_required'):
        owner.prepare_initial_recovery_review(author)
    owner.facts._started=set()
    def preio_denied(prepared):
        raise PrivateNativePending('original_preio_denied')
    owner.facts.run_review=preio_denied
    owner.facts.settle_review=lambda actual:pytest.fail('no settlement before original review started')
    with pytest.raises(PrivateNativePending,match='original_preio_denied'):
        owner.run_initial_recovery_review(prepared_review)
    def started_then_failed(prepared):
        owner.facts._started.add(prepared.preparation_id)
        raise RuntimeError('offline-review-started-failure')
    owner.facts.run_review=started_then_failed
    owner.facts.settle_review=lambda actual:events.append('independent-review-settlement')
    with pytest.raises(RuntimeError,match='offline-review-started-failure'):
        owner.run_initial_recovery_review(prepared_review)
    assert events[-2:]==['independent-review-settlement','commit']
    owner._initial_success.clear()
    with pytest.raises(PrivateNativePending,match='quality_live_work_required'):
        owner.prepare_initial_recovery_review(author)


def test_private_wait_reuses_same_top_contents_keeps_each_source_deadline_and_denies_missing(monkeypatch):
    from app.services.learning.item_supply.native_type_evidence import _CurrentPackData
    from app.services.learning.item_supply.native_type_contracts import IssuedNativePackCapability, NativeResolvedContent
    from app.services.learning.item_supply.native_type_exposure import NativeExposureOwnerV2
    from app.services.learning.item_supply.native_type_exposure_contracts import NativeTypeExposureSnapshot
    from app.services.learning.item_supply.pack_builder import build_pack
    from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending

    fixture = _private_base_union_fixture(monkeypatch)
    service, public, base = fixture.service, fixture.public, fixture.base
    now = base.exposure.observed_at
    public.settings, public.user_id, public.epoch = service.settings, fixture.task.user_id, fixture.task.epoch
    service.core.type_owner = public
    service.base_service.persistent_owner = service.core
    exposure = object.__new__(NativeExposureOwnerV2)
    exposure.conn, exposure.type_owner = service.conn, public
    exposure.user_id, exposure.epoch = public.user_id, public.epoch
    service.base_service.exposure_owner = exposure
    snapshot = build_pack(base, now=now).snapshot
    assert snapshot is not None
    cap = IssuedNativePackCapability(uuid4(), snapshot)
    union = SimpleNamespace(snapshot=snapshot, public_capability=cap)
    contents = {c.version_id: NativeResolvedContent(source=None, spec=None, facts=None,
        content=c.type_evidence.content, publication=SimpleNamespace(version_id=c.version_id,
            proof_id=c.proof_id, publication_event_id=c.publication_id, materialization_id=c.materialization_id))
        for c in snapshot.selected}
    observation = NativeTypeExposureSnapshot('complete', 'offline-wait-scope', base.exposure, uuid4())
    scoped = _CurrentPackData(81, fixture.task.mapping_receipt_id, fixture.ids, (fixture.relation_id,),
        exposure, None, mapping=fixture.mapping, contents=contents, observation=observation,
        inputs=base, capability=cap)
    public._pack_scope = scoped
    monkeypatch.setattr(public, '_guard', lambda: (now, 81))
    events = []
    monkeypatch.setattr(NativeTypeEvidenceOwner, '_require_pack_identity',
        lambda owner, issued: events.append(('identity', issued)))
    def no_decode(*args, **kwargs):
        pytest.fail('wait must not repeat immutable selected-content decoding in the exact scope')
    monkeypatch.setattr(public, 'resolve_content', no_decode)
    monkeypatch.setattr(public, 'source_deadline', lambda content:
        events.append(('current-source-deadline', content)) or now+timedelta(hours=2))
    fallback = SimpleNamespace(resolve=lambda task: events.append('union-resolve') or union,
        require=lambda issued: events.append('union-require'))
    monkeypatch.setattr(service, 'base_fallback_owner', lambda: fallback)
    service.conn.execute = lambda sql, params=(): SimpleNamespace(fetchall=lambda: [{'id': uuid4()}])
    lease = SimpleNamespace(parent_deadline=now+timedelta(hours=1),
        profile=SimpleNamespace(bound_at=now, values=SimpleNamespace(stage_deadline_ms=3600000)))
    service.record_wait_window(task_ref=fixture.task, lease=lease)
    assert events[:2] == ['union-resolve', 'union-require']
    assert [row[1] for row in events if isinstance(row, tuple) and row[0]=='current-source-deadline'] == list(contents.values())
    assert ('identity', cap) in events
    missing = next(iter(contents))
    saved = contents.pop(missing)
    with pytest.raises(PrivateNativePending, match='private_wait_exact_scoped_contents_required'):
        service._wait_source_contents(fixture.task, union)
    contents[missing] = saved
    public._pack_scope = None
    strict = []
    monkeypatch.setattr(public, 'resolve_content', lambda version, *, current:
        strict.append((version, current)) or contents[version])
    assert service._wait_source_contents(fixture.task, union) == [contents[c.version_id] for c in snapshot.selected]
    assert strict == [(c.version_id, True) for c in snapshot.selected]
