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
