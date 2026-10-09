"""Three OFFLINE protocol cases. Fake PG/C/provider data is NOT live acceptance."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from psycopg.pq import TransactionStatus

from app.core.config import Settings
from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_bank.review_contracts import REQUIRED_REVIEW_ROLES
from app.services.learning.item_supply.finite_candidate_factory import build_finite_generation_request
from app.services.learning.item_supply.finite_candidate_validation import prepare_finite_candidate_validation
from app.services.learning.item_supply.finite_review_descriptor import finite_review_context
from app.services.learning.item_supply.finite_static_blind_scorer import FiniteStaticBlindScorer
from app.services.learning.item_supply.finite_task_ambiguity import FiniteTaskAmbiguityOwner, build_finite_ambiguity_plan
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.policies import ResourceAmounts
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.repository import ItemSupplyRuntimeRepository
from app.services.learning.item_supply.review_contracts_v2 import CandidateBindingV2, ProviderIdentityV2
from app.services.learning.item_supply.review_provider import JsonBlindSolverV2, JsonReviewerV2, blind_solve_candidate
from app.services.learning.item_supply.sandbox.execution import SandboxCandidateExecutionPort
from app.services.learning.item_supply.shared_admission_facts import SharedAdmissionFactsOwner, SharedAdmissionFactsPending, _target_proof
from app.services.learning.item_supply.shared_admission_facts_contracts import SharedFactsBudgetV1
from app.services.learning.item_supply.shared_pipeline_repository import ResolvedSharedGeneration, SharedPipelineArtifactRepository
from app.services.learning.item_supply.shared_review import PreparedSharedReview, SharedReviewPipeline, SharedReviewResult
from app.services.learning.item_supply.shared_validation import SharedValidationPipeline
from app.services.learning.item_supply.shared_validation_contracts import PreparedSharedValidation, SharedValidationResult
from app.services.learning.item_supply.storage_contracts import AutonomousEvidencePolicyV2
from app.services.learning.item_supply.diagnostic_policy import AutonomousEvidencePolicyV3, SharedGenerationPolicyBindingV3
from app.services.learning.item_supply.review_provider import review_candidate_for_policy
from app.services.llm.llm_client import LLMJsonResponse
from app.services.learning.item_supply.parameter_profiles import FrozenProfileSnapshot, ParameterValuesV1
from app.services.learning.item_supply.generation_contracts import GenerationLimitsV2
from tests.learning.test_item_supply_shared_validation import _candidate


class ProtocolClient:
    model = "offline-protocol"
    request_attempt_bound = 1

    def __init__(self, payload):
        self.payload = payload

    def complete_json(self, *args, **kwargs):
        return LLMJsonResponse(content=self.payload, model=self.model)


class ProtocolConnection:
    """Only exact SQL result shape; no PG grant, durable commit, or source authority."""
    autocommit = False

    def __init__(self):
        self.info = SimpleNamespace(transaction_status=TransactionStatus.INTRANS)
        self.stages, self.facts, self.preparation, self.reservation, self.settlement = {}, {}, {}, {}, {}
        self.current = True
        self.policy_bindings = {}

    def execute(self, sql, params=()):
        row, rows = None, []
        if "SELECT to_regclass" in sql:
            row = {"table_id": "tutor_item_supply_shared_generation_policy_bindings" if self.policy_bindings else None}
        elif "FROM tutor_item_supply_shared_generation_policy_bindings" in sql:
            row = self.policy_bindings.get(params[0])
        elif "SELECT current_database()" in sql:
            row = {"db": "aearn_b1d_sandbox_20261001"}
        elif "clock_timestamp() AS now" in sql:
            row = {"now": datetime.now(UTC)}
        elif "FROM tutor_item_supply_shared_pipeline_receipts" in sql:
            row = self.stages.get(params[0])
        elif "SELECT e.payload_hash" in sql:
            row = self.preparation
        elif "FROM tutor_item_supply_shared_reservations" in sql:
            row = self.reservation
        elif "runtime_global_reservation_amounts" in sql:
            rows = [{"resource_kind": k, "reserved_amount": v} for k, v in self.resources.as_dict().items()]
        elif "FROM tutor_item_supply_shared_runtime_settlements" in sql:
            row = self.settlement
        elif "runtime_settlement_amounts" in sql:
            rows = []  # Explicit UNKNOWN provider aggregate, never fabricated zero.
        elif sql.startswith("INSERT INTO tutor_item_supply_shared_admission_facts"):
            data = params[-1].obj
            row = {"payload_json": data, "payload_hash": canonical_hash(data)}
            self.facts[params[0]] = row
        elif "FROM tutor_item_supply_shared_admission_facts" in sql:
            row = self.facts.get(params[0])
        else:
            raise AssertionError(sql)
        return SimpleNamespace(fetchone=lambda: row, fetchall=lambda: rows)


def _static_protocol(monkeypatch, *, policy=None, wrong=False):
    policy = AutonomousEvidencePolicyV2() if policy is None else policy
    spec, materials, source = _candidate("python-kc-binding-v1")
    inputs = prepare_finite_candidate_validation(source, spec=spec, materials=materials)
    now = datetime.now(UTC)
    deadline = now + timedelta(minutes=10)
    values = ParameterValuesV1(connection_timeout_ms=50, first_token_timeout_ms=50, stream_idle_timeout_ms=50,
        request_timeout_ms=1000, stage_deadline_ms=600_000, parent_deadline_ms=600_000,
        discussion_rounds=1, revision_rounds=1, investigation_rounds=1)
    profile = FrozenProfileSnapshot(profile_key_hash="1" * 64, profile_version=1, profile_hash="2" * 64,
        values=values, bound_at=now, parent_deadline_at=deadline)
    request = build_finite_generation_request(spec, candidate_id=uuid4(), profile=profile,
                                               limits=GenerationLimitsV2(max_input_bytes=100_000, max_output_tokens=2000, max_output_bytes=100_000), materials=materials)
    lease = JobLeaseV1(job_id=uuid4(), visibility="public", lease_owner="protocol.shared.facts",
        generation=1, state_version=3, expires_at=deadline, parent_deadline=deadline, profile=profile)
    artifact_id, root_id, item_id, version_id = (uuid4() for _ in range(4))
    binding = CandidateBindingV2(candidate_key=str(item_id), version_key=str(version_id),
        source_hash=source.source_hash, content_hash=source.content_hash, profile_hash=profile.profile_hash,
        policy_hash=policy.policy_hash, runtime_key="static-exact-v1",
        risk_tier=source.blueprint.publication_policy.risk_tier)
    scorer = FiniteStaticBlindScorer(binding=binding, spec=spec, materials=materials)
    identities = tuple(ProviderIdentityV2(identity="protocol." + str(i), provider="offline", model="offline-protocol") for i in range(7))
    solver = JsonBlindSolverV2(ProtocolClient({"answer": next(o.option_id for o in source.public.content.options if o.option_id != inputs.static_facts.correct_option_id) if wrong else inputs.static_facts.correct_option_id}),
        identity=identities[0], profile_hash=profile.profile_hash, timeout_seconds=10, max_output_tokens=1024)
    reviewers = tuple(JsonReviewerV2(ProtocolClient({"verdict": "approved", "findings": []}), role=role,
        identity=identity, profile_hash=profile.profile_hash, timeout_seconds=10, max_output_tokens=1024)
        for role, identity in zip(REQUIRED_REVIEW_ROLES, identities[1:], strict=True))
    validation = inputs.static_facts.validation
    with finite_review_context(source, spec=spec, materials=materials):
        blind = blind_solve_candidate(source, binding=binding, author_identity="protocol.author", solver=solver, scorer=scorer)
        bundle = review_candidate_for_policy(source, binding=binding, validation_receipt=validation,
            author_identity="protocol.author", blind_solve_receipt=blind, reviewers=reviewers, policy=policy)
    ambiguity_owner = FiniteTaskAmbiguityOwner(None, parent_deadline_at=deadline)
    plan = build_finite_ambiguity_plan(source, spec=spec, inputs=inputs)
    ambiguity = ambiguity_owner.run(source, plan, spec=spec, inputs=inputs, run_id=uuid4())
    conn = ProtocolConnection()
    settings = Settings(learning_item_supply_enabled=True, learning_item_network_enabled=True,
        learning_item_v2_admission_enabled=True, learning_item_generation_enabled=False,
        learning_item_bank_agent_review_enabled=False, llm_enabled=False)
    vp, rp = SharedValidationPipeline(conn, settings, enabled=True), SharedReviewPipeline(conn, settings, enabled=True)
    authority = RagSourceAuthority(SimpleNamespace(conn=conn, governance=SimpleNamespace(source_reviews=SimpleNamespace(
        resolve=lambda *a: SimpleNamespace(grant=SimpleNamespace(retained_until=deadline))))), SimpleNamespace())
    claims = SimpleNamespace(claim_receipt_hashes=("c" * 64,))
    monkeypatch.setattr(RagSourceAuthority, "assert_current", lambda *a: claims)
    v = PreparedSharedValidation(uuid4(), lease.model_copy(update={"state_version": 2}), artifact_id,
        "a" * 64, source, request, spec, inputs, None, None)
    vr = SharedValidationResult(validation, None, (), "static_verified")
    validation_id, blind_id, review_id = (uuid4() for _ in range(3))
    resources = ResourceAmounts(requests=7, input_tokens=700, output_tokens=700)
    p = PreparedSharedReview(lease, artifact_id, "a" * 64, validation_id, spec, source, request,
        validation, binding, "protocol.author", uuid4(), identities, resources, resources, inputs, plan, ambiguity.run_id)
    rr = SharedReviewResult(blind, bundle, "peer_review_staged", ambiguity)
    vp._prepared[v.preparation_id] = (v, canonical_hash({"payload": vp._payload(v), "reservation_id": str(None)}), authority, None)
    vp._results[v.preparation_id] = (vr, canonical_hash(vp._result_payload(vr)))
    rp._prepared[p.reservation_id] = (p, rp._seal(p), authority, solver, reviewers, scorer, None, ambiguity_owner)
    rp._results[p.reservation_id] = (rr, rp._result_hash(rr))
    artifact = dict(root_id=root_id, artifact_hash="a" * 64, item_id=item_id, version_id=version_id)
    original = SimpleNamespace(sources=tuple(claims for _ in materials))
    monkeypatch.setattr(SharedPipelineArtifactRepository, "resolve_generation", lambda *a, **kw:
        ResolvedSharedGeneration(artifact, request, source, original, kw["lease"]))
    monkeypatch.setattr(SharedPipelineArtifactRepository, "context", lambda *a, **kw: {"root_id": root_id, "coverage": spec.coverage_blueprint})
    def current(*args, **kwargs):
        if not conn.current:
            raise SharedAdmissionFactsPending("PROTOCOL_CURRENT_FENCE_LOST")
    monkeypatch.setattr(SharedReviewPipeline, "_fence", current)
    monkeypatch.setattr(ItemSupplyRuntimeRepository, "_control", current)
    for rid, value in ((validation_id, validation), (blind_id, blind), (review_id, bundle)):
        conn.stages[rid] = dict(payload_json=value.model_dump(mode="json"), receipt_hash=canonical_hash(value.model_dump(mode="json")),
            same_transaction=False, lease_owner=lease.lease_owner, continuation_binding_hash=None)
    conn.preparation = dict(payload_hash=canonical_hash(vp._result_payload(vr)), preparation_hash=canonical_hash(vp._payload(v)), same_transaction=False)
    if type(policy) is AutonomousEvidencePolicyV3:
        frozen = SharedGenerationPolicyBindingV3(policy=policy, root_id=root_id, job_id=lease.job_id,
            candidate_id=request.candidate_id, request_hash=canonical_hash(request.model_dump(mode="json")),
            blueprint_hash=spec.coverage_blueprint.blueprint_hash, profile_hash=profile.profile_hash, lease_generation=lease.generation)
        conn.policy_bindings[request.candidate_id] = dict(payload_json=frozen.model_dump(mode="json"),
            payload_hash=frozen.binding_hash, policy_hash=policy.policy_hash, request_hash=frozen.request_hash,
            job_id=lease.job_id, root_id=root_id, lease_generation=lease.generation,
            profile_hash=frozen.profile_hash, candidate_id=frozen.candidate_id)
    conn.resources = resources
    conn.reservation = dict(id=p.reservation_id, root_id=root_id, lease_generation=lease.generation)
    conn.settlement = dict(id=uuid4(), same_transaction=False, usage_state="unknown", receipt_hash=None, cost_amount=None)
    owner = SharedAdmissionFactsOwner(conn, validation_pipeline=vp, review_pipeline=rp, enabled=True)
    args = dict(lease=lease, validation_prepared=v, validation_result=vr, validation_receipt_id=validation_id,
                review_prepared=p, review_result=rr, blind_receipt_id=blind_id, review_receipt_id=review_id)
    return owner, args, conn


def test_protocol_only_static_issue_verify_original_owners_and_native_context(monkeypatch):
    owner, args, conn = _static_protocol(monkeypatch)
    facts = owner.issue(**args)
    assert facts.target_proof.claim_scope == "per_item_registered_target_not_inventory"
    assert tuple(m.clause_id for m in facts.target_proof.mappings) == ("kc-c1", "kc-c2", "kc-c3")
    assert facts.evaluation.disposition == "eligible_internal"
    assert not facts.evidence.runner_available and not facts.validation_terminals and not facts.blind_terminals
    assert facts.review_budget.usage_state == "unknown" and facts.review_budget.actual is None
    assert owner.verify(facts, lease=args["lease"]) == facts.evidence
    with pytest.raises(SharedAdmissionFactsPending, match="ALREADY_ISSUED"):
        owner.issue(**args)
    clone = replace(args["review_result"])
    with pytest.raises(ValueError, match="RESULT_UNAVAILABLE"):
        owner.review_pipeline._result(args["review_prepared"], clone)
    cold = SharedAdmissionFactsOwner(conn, validation_pipeline=owner.validation_pipeline, review_pipeline=owner.review_pipeline, enabled=True)
    with pytest.raises(SharedAdmissionFactsPending, match="ORIGINAL_ISSUER"):
        cold.verify(facts, lease=args["lease"])
    conn.current = False
    with pytest.raises(SharedAdmissionFactsPending, match="CURRENT_FENCE_LOST"):
        owner.verify(facts, lease=args["lease"])


def test_protocol_only_runtime_clause_projection_never_authenticates_fake_runner():
    for target in ("python-state-update-v1", "sqlite-predicate-order-v1"):
        spec, materials, source = _candidate(target)
        inputs = prepare_finite_candidate_validation(source, spec=spec, materials=materials)
        plan = build_finite_ambiguity_plan(source, spec=spec, inputs=inputs)
        # Pure declaration composition: deliberately NOT sealed runtime facts.
        reports = tuple(SimpleNamespace(role=role, material_failure=False, findings=(), report_hash=canonical_hash(role.value))
                        for role in REQUIRED_REVIEW_ROLES)
        p = SimpleNamespace(spec=spec, source=source, inputs=inputs, validation=SimpleNamespace(evidence_hash="d" * 64))
        result = SimpleNamespace(bundle=SimpleNamespace(reports=reports), blind=SimpleNamespace(receipt_hash="e" * 64),
                                 ambiguity=SimpleNamespace(plan=plan, receipt_hash="f" * 64))
        proof = _target_proof(p, result, ("b" * 64,))
        assert proof.target_definition_hash == spec.target_definition_hash and len(proof.mappings) == 3
        reports[0].findings = (SimpleNamespace(safe_code="coverage_gap"),)
        assert _target_proof(p, result, ("b" * 64,)) is None
        port = SandboxCandidateExecutionPort(SimpleNamespace(verify=lambda *a, **k: True), finite_spec=spec, probe_plan=inputs.probe_plan)
        with pytest.raises(SharedAdmissionFactsPending, match="ACTUAL_ORIGINAL_RUNNER"):
            SharedAdmissionFactsOwner._runner(port)


def test_default_off_and_unknown_usage_do_not_create_authority():
    owner = SharedAdmissionFactsOwner(SimpleNamespace(), validation_pipeline=SimpleNamespace(), review_pipeline=SimpleNamespace())
    with pytest.raises(SharedAdmissionFactsPending, match="OWNERS_REQUIRED"):
        owner._transaction()
    # Protocol-only: supply/network are not admission permission. No DB IO.
    conn = ProtocolConnection()
    settings = Settings(learning_item_supply_enabled=True, learning_item_network_enabled=True,
        learning_item_v2_admission_enabled=False, learning_item_generation_enabled=False, llm_enabled=False)
    owner = SharedAdmissionFactsOwner(conn,
        validation_pipeline=SharedValidationPipeline(conn, settings, enabled=True),
        review_pipeline=SharedReviewPipeline(conn, settings, enabled=True), enabled=True)
    with pytest.raises(SharedAdmissionFactsPending, match="V2_ADMISSION_DISABLED"):
        owner._transaction()
    args = dict(reservation_id=uuid4(), settlement_id=uuid4(), settlement_key="review.protocol",
        reserved=ResourceAmounts(requests=7), usage_state="unknown", actual=None, receipt_hash=None)
    assert SharedFactsBudgetV1(**args).actual is None
    with pytest.raises(ValueError, match="usage_state_mismatch"):
        SharedFactsBudgetV1(**{**args, "actual": ResourceAmounts()})
