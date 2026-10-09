"""Bounded OFFLINE cases. Protocol doubles are not real C/PG/OS/model proof."""
from datetime import UTC, datetime, timedelta
from dataclasses import replace
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from aearn_shared.execution import SandboxResultV1
from psycopg.pq import TransactionStatus

from app.core.config import Settings
from app.services.learning.item_bank.contracts import LearningItemReviewRole, LearningItemValidationCheckType, canonical_hash
from app.services.learning.item_supply.budget import ReservationResult
from app.services.learning.item_supply.finite_candidate_factory import build_finite_generation_request
from app.services.learning.item_supply.finite_candidate_validation import prepare_finite_candidate_validation
from app.services.learning.item_supply.finite_review_descriptor import finite_review_context
from app.services.learning.item_supply.finite_static_blind_scorer import FiniteStaticBlindScorer
from app.services.learning.item_supply.generation_contracts import GenerationReceiptV2, ProviderReceiptV2, ProviderUsageV2, SourceReceiptV2
from app.services.learning.item_supply.evidence import material_digest
from app.services.learning.item_supply.diagnostic_policy import AutonomousEvidencePolicyV3, SharedGenerationPolicyBindingV3
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.review_contracts_v2 import CandidateBindingV2, ProviderIdentityV2, ReviewInputV2, check_subject
from app.services.learning.item_supply.review_provider import BoundedOpenAIReviewClient, JsonBlindSolverV2, JsonReviewerV2, blind_input
from app.services.learning.item_supply.sandbox.blind_scorer import SandboxBlindAnswerScorer
from app.services.learning.item_supply.sandbox.execution import _candidate_cases
from app.services.learning.item_supply.sandbox.python_goal_scorer import source_scorer_version
from app.services.learning.item_supply.shared_review import SharedReviewPipeline, _combined_resources
from app.services.learning.item_supply.finite_task_ambiguity import FiniteTaskAmbiguityOwner, build_finite_ambiguity_plan
from app.services.learning.item_supply.policies import ResourceAmounts
from app.services.learning.item_supply.shared_continuation import SharedCandidateContinuationOwner
from app.services.learning.item_supply.shared_pipeline_repository import ResolvedSharedGeneration
from app.services.learning.item_supply.validation_adapter import CandidateCheckV2, CandidateExecutionEvidenceV2, CandidateProbeV2, CandidateValidationV2
from app.services.learning.item_supply.validators.profiles import required_probes
from tests.learning.test_item_supply_generation import make_request
from tests.learning.test_item_supply_python_goal_scorer import ProtocolReceipt
from tests.learning.test_item_supply_shared_validation import OfflineConnection, _candidate


def binding(source, profile_hash="1"*64):
    return CandidateBindingV2(candidate_key="candidate.offline", version_key="version.offline",
        source_hash=source.source_hash, content_hash=source.content_hash, policy_hash="2"*64,
        profile_hash=profile_hash, runtime_key=source.blueprint.runtime_profile_id or "static-exact-v1",
        risk_tier=source.blueprint.publication_policy.risk_tier)


def declared_validation(source, spec):
    """Explicit fake terminal facts to check only the new required-probe routing."""
    evidence = CandidateExecutionEvidenceV2(source_hash=source.source_hash, content_hash=source.content_hash,
        kind=source.public.kind.value, language=source.blueprint.language_id,
        runtime_profile_id=source.blueprint.runtime_profile_id, dialect="sqlite" if spec.sql_target else None,
        runner_version="offline.protocol", scorer_version=source_scorer_version(source), run_id=uuid4(),
        mode="live", isolation="approved_os_boundary", probes=tuple(CandidateProbeV2(name=n, status="passed",
            proof_hash="3"*64, profile_version="offline.protocol") for n in required_probes(source, finite_spec=spec)))
    digest = canonical_hash(evidence.model_dump(mode="json"))
    return CandidateValidationV2(state="machine_verified", source_hash=source.source_hash,
        content_hash=source.content_hash, mode="live", execution_evidence=evidence,
        checks=tuple(CandidateCheckV2(check_type=k, status="passed", proof_hash=digest) for k in LearningItemValidationCheckType))


@pytest.mark.parametrize("wrong", [False, True])
def test_native_python_sql_blind_route_is_one_answer_and_exact_descriptor_context(wrong):
    for target in ("python-state-update-v1", "sqlite-predicate-order-v1"):
        spec, materials, source = _candidate(target)
        current = binding(source)
        if wrong:
            current = current.model_copy(update={"policy_hash": AutonomousEvidencePolicyV3().policy_hash})
        issued = []
        _, _, _, tests = _candidate_cases(source)

        def run(*, request, run_id, probe_name):
            facts = []
            for test in tests:
                fact = dict(id=test["id"], status="success", code="python_terminal" if spec.python_goal else "sqlite_terminal")
                if spec.python_goal:
                    fact.update(stdout=test["expected_output_json"]["stdout"], goal_contract_id="python-state-update-v1",
                        goal_contract_hash=spec.python_goal.target_hash, goal_status="satisfied", goal_satisfied=True)
                    if wrong:
                        fact.update(goal_status="unsatisfied", goal_satisfied=False)
                else:
                    fact.update(columns=test["expected_output"]["columns"], rows=[] if wrong else test["expected_output"]["rows"])
                facts.append(fact)
            result = SandboxResultV1(status="success", diagnostic_code="item_supply_facts_v1", stdout=json.dumps({"cases": facts}))
            receipt = ProtocolReceipt(run_id, probe_name, canonical_hash(request.model_dump(mode="json")), result)
            issued.append(receipt)
            return receipt

        runner = SimpleNamespace(run=run, verify=lambda receipt, **kw: any(r is receipt for r in issued))
        scorer = SandboxBlindAnswerScorer(runner, binding=current, finite_spec=spec,
            parent_deadline_at=datetime.now(UTC)+timedelta(minutes=2))
        assert scorer.resource_plan(source).execution_seconds == 10
        inputs = prepare_finite_candidate_validation(source, spec=spec, materials=materials)
        ambiguity_plan = build_finite_ambiguity_plan(source, spec=spec, inputs=inputs)
        ambiguity_owner = FiniteTaskAmbiguityOwner(runner, parent_deadline_at=datetime.now(UTC)+timedelta(minutes=2))
        combined = _combined_resources(ResourceAmounts(requests=7, input_tokens=700, output_tokens=70),
            scorer.resource_plan(source), ambiguity_owner.resource_plan(ambiguity_plan))
        assert combined.requests == 7 and combined.execution_seconds == 30
        assert ambiguity_owner._runner is scorer._runner is runner
        assert not issued  # Full bound planned before any one-answer execution.
        answer = source.private.content.standard_answer if spec.python_goal else source.private.content.standard_query
        score = scorer.score(source, answer=answer)
        assert score.passed is (not wrong) and scorer.verify(score, source) and len(issued) == 1
        assert scorer.score(source, answer=answer) == score and len(issued) == 1
        with pytest.raises(ValueError, match="allowance_spent"):
            scorer.score(source, answer=answer + " ")
        validation = declared_validation(source, spec)
        with pytest.raises(ValueError, match="exact_context_required"):
            check_subject(source, current, validation)
        with finite_review_context(source, spec=spec, materials=materials):
            review = ReviewInputV2(binding=current, role=LearningItemReviewRole.TECHNICAL, source=source, validation_receipt=validation)
            descriptor = review.scoring_descriptor
            assert set(descriptor["required_probe_names"]) == set(required_probes(source, finite_spec=spec))
            assert "finite_ambiguity_verified_separately_by_original_owner" in descriptor["unresolved_boundaries"]
            assert "standard_answer" not in json.dumps(descriptor)
            assert "private" not in blind_input(source, current).model_dump()
            if wrong:
                from app.services.learning.item_supply.admission import evaluate_admission
                from app.services.learning.item_supply.review_contracts_v2 import (
                    AdmissionEvidenceV2, ProbeOutcomeV2, ProviderRunV2, BlindSolveReceiptV2, execution_receipt_digest,
                )
                from app.services.learning.item_supply.review_provider import BLIND_PROMPT_VERSION, review_candidate_for_policy
                from tests.learning.test_item_supply_shared_admission_facts import ProtocolClient
                blind = BlindSolveReceiptV2(binding=current, run=ProviderRunV2(
                    provider_identity=ProviderIdentityV2(identity="offline.blind", provider="offline", model="offline"),
                    run_id=uuid4(), prompt_version=BLIND_PROMPT_VERSION, input_hash=blind_input(source,current).input_hash,
                    output_hash=canonical_hash(answer), profile_hash=current.profile_hash, timeout_seconds=1.0, max_output_tokens=100),
                    solution_hash=canonical_hash(answer), score=score)
                roles = tuple(JsonReviewerV2(ProtocolClient({"verdict":"approved","findings":[]}), role=role,
                    identity=ProviderIdentityV2(identity="offline."+role.value,provider="offline",model="offline-protocol"),
                    profile_hash=current.profile_hash,timeout_seconds=1.0,max_output_tokens=100) for role in LearningItemReviewRole)
                bundle = review_candidate_for_policy(source,binding=current,validation_receipt=validation,
                    author_identity="offline.author",blind_solve_receipt=blind,reviewers=roles,policy=AutonomousEvidencePolicyV3())
                raw_probes = {probe.name:probe.proof_hash for probe in validation.execution_evidence.probes}
                mapping = {"correct":"reference","incorrect":"wrong_rejected","equivalent":"equivalent",
                    "known_wrong":"wrong_rejected","boundary":"boundary","scorer_counterexample":"scorer_counterexample"}
                facts = AdmissionEvidenceV2(binding=current,validation_receipt_hash=validation.evidence_hash,
                    source_current=True,source_claim_receipt_hashes=("a"*64,),coverage_proof_hash="b"*64,
                    probes=tuple(ProbeOutcomeV2(probe=k,passed=True,receipt_hash=raw_probes[v]) for k,v in mapping.items())+
                        (ProbeOutcomeV2(probe="ambiguity",passed=True,receipt_hash="c"*64),),
                    execution_receipt_hash=execution_receipt_digest(validation),execution_isolated=True,runner_available=True,scorer_available=True)
                result = evaluate_admission(source,binding=current,policy=AutonomousEvidencePolicyV3(),validation_receipt=validation,
                    author_identity="offline.author",bundle=bundle,evidence=facts,enabled=True)
                assert result.disposition=="eligible_internal" and result.diagnostic_warnings==("blind_solution_incorrect",)
                assert not result.publication_enabled and len(issued)==1



def test_python_review_projects_compiled_goal_without_hiding_public_shape_mismatch():
    """Pure prompt/rule regression; no runtime artifacts, execution or provider IO."""
    from app.services.learning.item_supply.review_provider import _ReviewVote, _review_instruction
    from app.services.learning.item_supply.sandbox.finite_probe_plans import native_python_tests
    from app.services.learning.item_supply.sandbox.python_state_scorer import compile_python_state_test_bundle
    from tests.learning.test_item_supply_python_state import _goal_module

    spec, materials, source = _candidate("python-state-update-v1")
    current = binding(source)
    original = source.model_dump(mode="json")
    blind_before = blind_input(source, current).model_dump(mode="json")
    tests = native_python_tests(source)
    cases = compile_python_state_test_bundle(tests)
    with finite_review_context(source, spec=spec, materials=materials):
        review = ReviewInputV2(binding=current, role=LearningItemReviewRole.TECHNICAL,
            source=source, validation_receipt=declared_validation(source, spec))
        adapter = JsonReviewerV2(SimpleNamespace(model="offline.model", request_attempt_bound=1),
            role=review.role, identity=ProviderIdentityV2(identity="offline.review", provider="offline", model="offline.model", model_version="v1"),
            profile_hash=current.profile_hash, timeout_seconds=10, max_output_tokens=512)
        messages, _, _, _ = adapter._input_envelope(review, instruction=_review_instruction(review.role), output_type=_ReviewVote)
        payload = json.loads(messages[1]["content"])
        effective = payload["scoring_descriptor"]["python_state_scoring"]
        assert effective["compiled_test_bundle_hash"] == canonical_hash(tests)
        assert effective["compiled_runtime_cases_hash"] == canonical_hash(cases)
        assert effective["public_goal_contract"] == spec.python_goal.model_dump(mode="json")
        assert effective["required_terminal_facts"]["goal_satisfied"] is True
        assert all(case["goal_contract_hash"] == spec.python_goal.target_hash for case in effective["case_bindings"])
        assert "same fixed public goal" in effective["case_scope"]
        assert "Tuple initialization" in effective["task_shape_limitation"]
        assert "does not resolve it" in effective["task_shape_limitation"]
        assert "expected_output_json" not in json.dumps(effective)
        assert source.private.content.standard_answer not in json.dumps(effective, ensure_ascii=False)
        assert "not source text, a peer report, an approval" in messages[0]["content"]
        assert review.input_hash == canonical_hash(payload)

    # An explicit public permission is wider than the closed accumulate matcher.
    goal = spec.python_goal
    reference = source.private.content.standard_answer
    parallel_init = (f"{goal.variables['total']}, {goal.variables['increase']} = "
                     f"{goal.values['initial']}, {goal.values['increase']}\n" + "\n".join(reference.splitlines()[2:]))
    assert "两项同时赋值" in source.public.instruction_markdown
    assert _goal_module().inspect_python_state_goal(parallel_init, goal.model_dump(mode="json"))["goal_status"] == "unsatisfied"
    assert source.model_dump(mode="json") == original
    assert blind_input(source, current).model_dump(mode="json") == blind_before
    assert all(test.input_json == {} for test in source.private.content.tests)


def test_static_kc_blind_has_no_os_and_verifies_current_instance_only():
    spec, materials, source = _candidate("python-kc-binding-v1")
    current = binding(source)
    scorer = FiniteStaticBlindScorer(binding=current, spec=spec, materials=materials)
    assert not any(scorer.resource_plan(source).as_dict().values())
    score = scorer.score(source, answer=source.private.content.accepted_answers[0])
    assert score.passed and scorer.verify(score, source)
    assert not scorer.verify(score.model_copy(update={"receipt_hash": "f"*64}), source)
    facts = prepare_finite_candidate_validation(source, spec=spec, materials=materials).static_facts
    with finite_review_context(source, spec=spec, materials=materials):
        request = ReviewInputV2(binding=current, role=LearningItemReviewRole.TECHNICAL, source=source, validation_receipt=facts.validation)
        assert request.scoring_descriptor["runtime_profile_id"] == "static-exact-v1"
        assert not request.scoring_descriptor["required_probe_names"]
        assert "correct_option_id" not in json.dumps(request.scoring_descriptor)


@pytest.mark.parametrize("mode", ["legacy", "diagnostic_wrong", "diagnostic_timeout", "evidenced", "evidenced_partial"])
def test_shared_current_profile_fences_single_dispatch_and_unknown_settlement(monkeypatch, mode):
    spec, materials, source = _candidate("python-kc-binding-v1")
    base, _ = make_request()
    profile = base.profile
    lease = JobLeaseV1(job_id=uuid4(), visibility="public", lease_owner="worker.review.offline", generation=1,
        state_version=3, expires_at=profile.parent_deadline_at, parent_deadline=profile.parent_deadline_at, profile=profile)
    original_profile = profile.model_copy(update={"bound_at": profile.bound_at-timedelta(minutes=3),
        "parent_deadline_at": profile.parent_deadline_at-timedelta(minutes=3)})
    request = build_finite_generation_request(spec, candidate_id=uuid4(), profile=original_profile, limits=base.limits, materials=materials)
    validation = prepare_finite_candidate_validation(source, spec=spec, materials=materials).static_facts.validation
    class Conn(OfflineConnection):
        def execute(self, sql, params=()):
            if "SELECT to_regclass" in sql and mode != "legacy":
                return SimpleNamespace(fetchone=lambda: {"table_id": "tutor_item_supply_shared_generation_policy_bindings"})
            if "FROM tutor_item_supply_shared_generation_policy_bindings" in sql:
                return SimpleNamespace(fetchone=lambda: conn.policy_binding)
            if "SELECT r.payload_json" in sql:
                assert params[2:] == (lease.job_id, lease.generation)
                return SimpleNamespace(fetchone=lambda: dict(payload_json=validation.model_dump(mode="json"),
                    receipt_hash=validation.evidence_hash, same_transaction=False))
            return super().execute(sql, params)
    conn = Conn()
    calls, settled, stored = [], [], []
    fresh = mode.startswith("evidenced")
    model = "deepseek-v4-pro" if fresh else "fixture"
    settings = Settings(llm_type="deepseek", deepseek_api_key="offline-not-secret", deepseek_base_url="https://invalid.example",
        deepseek_model=model, learning_item_supply_enabled=True, learning_item_network_enabled=True)
    def transport(url, headers, body, timeout):
        assert conn.info.transaction_status == TransactionStatus.IDLE
        calls.append(body)
        if mode == "diagnostic_timeout" and len(calls) == 1:
            raise TimeoutError("offline bounded timeout")
        content = {"answer": (next(o.option_id for o in source.public.content.options if o.option_id != source.private.content.accepted_answers[0]) if mode == "diagnostic_wrong" else source.private.content.accepted_answers[0])} if len(calls) == 1 else {"verdict": "approved", "findings": []}
        if fresh and len(calls) > 1:
            content["schema_version"] = "item_supply_evidenced_review_output_v1"
            assert body["thinking"] == {"type": "enabled"} and body["reasoning_effort"] == "high"
            if mode == "evidenced_partial" and len(calls) == 5:
                content["verdict"] = "rejected"  # Invalid empty denial, no bundle.
        return {"model": model, "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(content)}}]}
    client = BoundedOpenAIReviewClient(settings, profile=profile, transport=transport)
    def identity(name):
        return ProviderIdentityV2(identity=name, provider=client.configured_provider, model=model)
    kwargs = dict(profile_hash=profile.profile_hash, timeout_seconds=1.0, max_output_tokens=2000)
    solver = JsonBlindSolverV2(client, identity=identity("blind.offline"), **kwargs)
    reviewers = tuple(JsonReviewerV2(client, role=role, identity=identity("review."+role.value),
        review_protocol="evidenced-v1" if fresh else "legacy-v2", **kwargs) for role in LearningItemReviewRole)
    continuation = SharedCandidateContinuationOwner(conn, settings, enabled=True)
    owner = SharedReviewPipeline(conn, settings, enabled=True, continuation_owner=continuation,
        trusted_model_bindings={(client.configured_provider,"model-v1"):model})
    authority = RagSourceAuthority(SimpleNamespace(conn=conn), None)
    receipts = tuple(SourceReceiptV2(material_digest=material_digest(m), binding_digest=m.binding.binding_digest,
        corpus_version_id=UUID(m.binding.evidence[0].corpus_version_id), active_generation=m.binding.evidence[0].active_generation,
        checked_at_iso=datetime.now(UTC).isoformat(), claim_receipt_hashes=(m.binding.evidence[0].claim_receipt_hash,),
        mode="current_authority") for m in materials)
    generation = GenerationReceiptV2(candidate_id=request.candidate_id, scope_hash=request.scope_hash,
        source_hash=source.source_hash, content_hash=source.content_hash, sources=receipts,
        provider=ProviderReceiptV2(provider=client.configured_provider, provider_version="offline-v1", configured_model=model, model=model,
            prompt_version="offline-v1", run_id=uuid4(), request_attempt_bound=1, usage=ProviderUsageV2(state="unknown"), mode="provider"))
    artifact = dict(id=uuid4(), root_id=uuid4(), item_id=uuid4(), version_id=uuid4(), job_id=uuid4(), lease_generation=7,
        source_hash=source.source_hash, content_hash=source.content_hash, source_json=source.model_dump(mode="json"),
        request_json=request.model_dump(mode="json"), receipt_json=generation.model_dump(mode="json"))
    artifact["artifact_hash"] = canonical_hash({k:artifact[k+"_json"] for k in ("source","receipt","request")})
    if mode != "legacy":
        frozen = SharedGenerationPolicyBindingV3(policy=AutonomousEvidencePolicyV3(), root_id=artifact["root_id"],
            job_id=artifact["job_id"], candidate_id=request.candidate_id, lease_generation=artifact["lease_generation"],
            request_hash=canonical_hash(request.model_dump(mode="json")),
            blueprint_hash=spec.coverage_blueprint.blueprint_hash, profile_hash=original_profile.profile_hash)
        conn.policy_binding = dict(payload_json=frozen.model_dump(mode="json"), payload_hash=frozen.binding_hash,
            policy_hash=frozen.policy.policy_hash, request_hash=frozen.request_hash, job_id=frozen.job_id, lease_generation=frozen.lease_generation,
            root_id=frozen.root_id, profile_hash=frozen.profile_hash, candidate_id=frozen.candidate_id)
    state = {"current":True, "stage":"validating"}
    def current(*a):
        if not state["current"]:
            raise ValueError("source_current_denied")
    monkeypatch.setattr(authority,"assert_current",current)
    def resolve(**kw):
        assert kw["continuation_owner"] is continuation and kw["lease"] == lease
        # Deliberate resolver protocol double; real491 adoption is main-owned.
        return ResolvedSharedGeneration(artifact, request, source, generation, lease,
                                        SimpleNamespace(binding_hash="c"*64))
    monkeypatch.setattr(owner.artifacts,"resolve_generation",resolve)
    monkeypatch.setattr(owner.artifacts,"context",lambda *a,**kw: dict(root_id=artifact["root_id"], coverage=spec.coverage_blueprint,
        key=SimpleNamespace(provider=client.configured_provider,model_version="model-v1"),provider_key=client.configured_provider))
    monkeypatch.setattr(owner.runtime,"next_stage",lambda lease:state["stage"])
    monkeypatch.setattr(owner.runtime,"_control",lambda *a,**kw: {})
    rid=uuid4()
    amounts=[]
    def reserve(**kw):
        amounts.append(kw["amounts"])
        return ReservationResult(True,"RESERVED",rid)
    monkeypatch.setattr(owner.budget,"reserve",reserve)
    monkeypatch.setattr(owner.budget,"_reservation_by_key",lambda *a:dict(id=rid,lease_generation=1))
    monkeypatch.setattr(owner.budget,"_reservation_amounts",lambda *a:amounts[0].as_dict())
    monkeypatch.setattr(owner.budget,"settle",lambda **kw:settled.append(kw))
    def store(**kw):
        stored.append(kw)
        return {"id":uuid4()}
    monkeypatch.setattr(owner.artifacts,"store_receipt",store)
    call=dict(lease=lease,artifact_id=artifact["id"],validation_receipt_id=uuid4(),spec=spec,source_authority=authority,solver=solver,reviewers=reviewers)
    with pytest.raises(PipelineRepositoryError,match="STAGE_MISMATCH"):
        owner.prepare_review(**call)
    assert not amounts and not calls
    state["stage"]="reviewing"
    owner._models[(client.configured_provider,"model-v1")]="wrong"
    with pytest.raises(PipelineRepositoryError,match="PROFILE_MISMATCH"):
        owner.prepare_review(**call)
    assert not amounts and not calls
    owner._models[(client.configured_provider,"model-v1")]=model
    p=owner.prepare_review(**call)
    assert p.review_protocol == ("evidenced-v1" if fresh else "legacy-v2")
    assert p.resources.requests==7 and p.resources.execution_seconds==0
    assert p.ambiguity_plan.correct is None and p.inputs.static_facts is not None
    assert p.request.profile == original_profile and p.lease.profile == profile
    assert artifact["job_id"] != p.lease.job_id and p.request.profile.parent_deadline_at < datetime.now(UTC)
    conn.info.transaction_status=TransactionStatus.IDLE
    state["current"]=False
    with pytest.raises(ValueError,match="source_current_denied"):
        owner.run_review(p)
    assert not calls
    state["current"]=True
    result=owner.run_review(p)
    if mode == "evidenced_partial":
        assert result.bundle is None and result.safe_reason == "review_pending"
        assert len(result.partial_reports) == 3 and len(calls) == 5
        assert result.blind is not None
        with conn.transaction():
            owner.settle_review(p, result)
            failed = owner.commit_review(p, result)
        assert failed.review_receipt_id is None and all(row["kind"] != "review_bundle" for row in stored)
        assert settled[0]["usage_state"] == "unknown" and settled[0]["actual"] is None
        with pytest.raises(PipelineRepositoryError, match="ALREADY_DISPATCHED"):
            owner.run_review(p)
        assert len(calls) == 5
        return
    if mode == "diagnostic_timeout":
        assert result.blind is result.bundle is None and result.safe_reason == "blind_solve_pending"
        assert len(calls) == 1  # No retry/solver voting and no manufactured score/run.
        with conn.transaction():
            owner.settle_review(p,result)
            failed = owner.commit_review(p,result)
        assert failed.blind_receipt_id is failed.review_receipt_id is None
        assert settled[0]["usage_state"] == "unknown" and not stored
        with pytest.raises(PipelineRepositoryError,match="ALREADY_DISPATCHED"):
            owner.run_review(p)
        return
    assert result.blind.score.passed is (mode != "diagnostic_wrong")
    if mode == "diagnostic_wrong":
        assert result.bundle.policy_version == "autonomous_evidence_policy_v3"
        for message in calls[1:]:
            public_review = json.loads(message["messages"][1]["content"])
            assert "blind_solve" not in public_review and "solution_hash" not in public_review and "score" not in public_review
    assert result.bundle is not None and len(calls)==7
    assert result.ambiguity.mode == "static_options" and result.ambiguity.terminals == ()
    with pytest.raises(PipelineRepositoryError,match="ALREADY_DISPATCHED"):
        owner.run_review(p)
    with conn.transaction():
        owner.settle_review(p,result)
    assert settled[0]["usage_state"]=="unknown" and settled[0]["actual"] is None
    state["current"]=False
    with conn.transaction(),pytest.raises(ValueError,match="source_current_denied"):
        owner.commit_review(p,result)
    assert not stored
    state["current"]=True
    with conn.transaction():
        stage=owner.commit_review(p,result)
        evidence=owner.verified_review_evidence(p,result,runner=None)
        assert evidence.execution_usage.execution_seconds == 0
        assert evidence.blind_terminals == evidence.ambiguity_terminals == ()
        with pytest.raises(PipelineRepositoryError,match="RESULT_UNAVAILABLE"):
            owner.verified_review_evidence(p,replace(result),runner=None)
        with pytest.raises(PipelineRepositoryError,match="AMBIGUITY_RESULT_UNVERIFIED"):
            owner.verified_review_evidence(p,result,runner=SimpleNamespace())
    assert [r["kind"] for r in stored]==["blind_solve","review_bundle"]
    assert not stage.publication_enabled and "finite_ambiguity_owner_pending" not in stage.pending_boundaries
    assert "shared_final_facts_pending" in stage.pending_boundaries
