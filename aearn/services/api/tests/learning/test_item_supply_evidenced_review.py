"""Labeled OFFLINE protocol/prompt cases, never measured model precision."""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from psycopg.pq import TransactionStatus

from app.core.config import Settings
from app.services.learning.item_bank.contracts import LearningItemReviewRole, LearningItemRiskTier, canonical_hash
from app.services.learning.item_supply.admission import evaluate_admission
from app.services.learning.item_supply.diagnostic_policy import AutonomousEvidencePolicyV3, checked_bundle
from app.services.learning.item_supply.review_contracts_v2 import (
    EvidencedReviewInputV1, EvidencedReviewReportV1, ReviewBundleV2, ReviewInputV2,
)
from app.services.learning.item_supply.review_protocol import (
    configured_review_protocol, make_review_request, verify_review_report,
)
from app.services.learning.item_supply.review_provider import (
    AutonomousReviewError, BoundedOpenAIReviewClient, JsonReviewerV2, blind_solve_candidate,
    review_candidate_for_policy, review_resource_plan,
)
from app.services.learning.item_supply.review_rubrics import (
    EVIDENCED_REVIEW_PROTOCOL, HARD_CODES, ROLE_CODES, evidenced_review_instruction,
)
from app.services.learning.item_supply.storage_contracts import AutonomousEvidencePolicyV2
from app.services.llm.llm_client import LLMJsonResponse
from tests.learning.test_item_supply_autonomous_review import (
    DIGEST, FakeScorer, adapters, evidence, high_facts, identity, make_bundle, subject,
)

APPROVAL = {"schema_version": "item_supply_evidenced_review_output_v1", "verdict": "approved", "findings": []}


class LabeledClient:
    model = "test-model"
    request_attempt_bound = 1

    def __init__(self, label="known_good", mutation=None):
        self.label, self.mutation = label, mutation
        self.calls = []

    def complete_json(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        payload = json.loads(messages[1]["content"])
        output = copy.deepcopy(APPROVAL)
        if self.label == "field_bound_material_claim":
            # Fictional CLAIM for protocol validation, not evidence of model accuracy.
            refs = {ref["pointer"]: ref for ref in payload["evidence_index"]}
            output.update(verdict="changes_required", findings=[{
                "severity": "major", "blocking": True, "safe_code": "rubric_mismatch",
                "evidence_hash": payload["review_input"]["binding"]["content_hash"],
                "problem": "UNIT_CLAIM: a correct public answer is rejected by the private rule.",
                "expected_behavior": "UNIT_EXPECTATION: every stated correct answer must satisfy that rule.",
                "counterexample": "UNIT_COUNTEREXAMPLE: public answer class would be rejected, but must be accepted.",
                "references": [refs["/source/public/content/prompt_markdown"], refs["/source/private/content/accepted_answers"]],
            }])
        if self.mutation:
            self.mutation(output, payload)
        self.output = output
        return LLMJsonResponse(content=output, model=self.model)


def evidenced_ports(*, label="known_good", fail_role=None, model="test-model", prefix="first"):
    solver, _, _ = adapters(prefix=prefix, model=model)
    clients, roles = [], []
    for role in LearningItemReviewRole:
        mutation = (lambda out, payload: out.update(verdict="rejected")) if role is fail_role else None
        client = LabeledClient(label if role is LearningItemReviewRole.TECHNICAL else "known_good", mutation)
        client.model = model
        clients.append(client)
        roles.append(JsonReviewerV2(client, role=role, identity=identity(prefix+"-"+role.value, model=model),
            profile_hash=DIGEST, timeout_seconds=1.0, max_output_tokens=1024, review_protocol=EVIDENCED_REVIEW_PROTOCOL))
    return solver, tuple(roles), clients


def bundle_fixture(*, policy=None, label="known_good", risk=LearningItemRiskTier.LOW,
                   fail_role=None, model="test-model", prefix="first", bundle_version=1):
    policy = policy or AutonomousEvidencePolicyV2()
    source, validation, binding = subject(risk)
    binding = binding.model_copy(update={"policy_hash": policy.policy_hash})
    solver, reviewers, clients = evidenced_ports(label=label, fail_role=fail_role, model=model, prefix=prefix)
    blind = blind_solve_candidate(source, binding=binding, author_identity="author", solver=solver, scorer=FakeScorer())
    bundle = review_candidate_for_policy(source, binding=binding, validation_receipt=validation,
        author_identity="author", blind_solve_receipt=blind, reviewers=reviewers, policy=policy, bundle_version=bundle_version)
    return source, validation, binding, bundle, clients


@pytest.mark.parametrize("policy", [AutonomousEvidencePolicyV2(), AutonomousEvidencePolicyV3()])
def test_new_report_roundtrip_outer_policy_and_true_output_hash(policy):
    source, validation, binding, bundle, clients = bundle_fixture(policy=policy)
    assert checked_bundle(type(bundle).model_validate_json(bundle.model_dump_json())) == bundle
    assert bundle.correlation_limited and len(bundle.reports) == 6
    for report, client in zip(bundle.reports, clients, strict=True):
        request = make_review_request(source, binding=binding, role=report.role,
                                      validation_receipt=validation, protocol="evidenced-v1")
        assert isinstance(request, EvidencedReviewInputV1)
        assert isinstance(report, EvidencedReviewReportV1)
        verify_review_report(report, request)
        assert report.run.output_hash == canonical_hash(client.output)
        assert report.run.output_hash != canonical_hash({"verdict": "approved", "findings": []})
        payload = json.loads(client.calls[0][0][1]["content"])
        assert "blind_solve" not in payload["review_input"] and "reports" not in payload["review_input"]
    result = evaluate_admission(source, binding=binding, validation_receipt=validation, policy=policy,
        author_identity="author", bundle=bundle, evidence=evidence(binding, validation), enabled=True)
    assert result.disposition == "eligible_internal" and not result.publication_enabled


def test_labeled_material_claim_remains_veto_not_consensus_override():
    s, v, b, bundle, _ = bundle_fixture(label="field_bound_material_claim")
    result = evaluate_admission(s, binding=b, validation_receipt=v, policy=AutonomousEvidencePolicyV2(),
        author_identity="author", bundle=bundle, evidence=evidence(b, v), enabled=True)
    assert result.disposition == "quarantine" and "material_review_failure" in result.safe_reasons


def test_common_hard_defect_is_not_suppressed_by_technical_role():
    s, v, b = subject()
    def cross_role(out, payload):
        finding = out["findings"][0]
        finding["safe_code"] = "data_leakage"
        finding["problem"] = "UNIT_CLAIM: the public prompt exposes the private accepted answer."
        finding["expected_behavior"] = "UNIT_EXPECTATION: public prompts must not disclose private answers."
        finding["counterexample"] = "UNIT_COUNTEREXAMPLE: a learner copies the exposed private answer without solving."
    client = LabeledClient("field_bound_material_claim", cross_role)
    reviewer = JsonReviewerV2(client, role=LearningItemReviewRole.TECHNICAL, identity=identity("cross-role"),
        profile_hash=DIGEST, timeout_seconds=1.0, max_output_tokens=1024, review_protocol="evidenced-v1")
    request = make_review_request(s, binding=b, role=reviewer.role, validation_receipt=v, protocol="evidenced-v1")
    report = reviewer.review(request)
    assert report.material_failure and report.findings[0].safe_code == "data_leakage"


@pytest.mark.parametrize("label", ["tampered_hash", "unrelated_title", "empty_denial", "contradictory_approval", "missing_counterexample"])
def test_labeled_invalid_claims_fail_once_no_receipt_or_bundle(label):
    s, v, b = subject()
    _, roles, _ = evidenced_ports()
    def mutate(out, payload):
        if label == "empty_denial":
            out.update(verdict="rejected", findings=[])
        elif label == "contradictory_approval":
            out["verdict"] = "approved"
        elif label == "missing_counterexample":
            out["findings"][0]["counterexample"] = None
        elif label == "tampered_hash":
            out["findings"][0]["references"][0]["value_hash"] = "0"*64
        else:
            out["findings"][0]["references"] = [next(ref for ref in payload["evidence_index"] if ref["pointer"] == "/source/public/title")]
    client = LabeledClient("field_bound_material_claim", mutate)
    role = roles[2]
    reviewer = JsonReviewerV2(client, role=role.role, identity=role.provider_identity,
        profile_hash=DIGEST, timeout_seconds=1.0, max_output_tokens=1024, review_protocol="evidenced-v1")
    request = make_review_request(s, binding=b, role=role.role, validation_receipt=v, protocol="evidenced-v1")
    with pytest.raises(AutonomousReviewError):
        reviewer.review(request)
    assert len(client.calls) == 1


def test_later_role_failure_preserves_completed_private_receipts_no_bundle():
    s, v, b = subject()
    solver, reviewers, clients = evidenced_ports(fail_role=LearningItemReviewRole.AMBIGUITY)
    plan = review_resource_plan(s, binding=b, validation_receipt=v, solver=solver, reviewers=reviewers)
    assert plan.requests == 7 and plan.output_tokens == 7*1024 and not any(c.calls for c in clients)
    blind = blind_solve_candidate(s, binding=b, author_identity="author", solver=solver, scorer=FakeScorer())
    with pytest.raises(AutonomousReviewError, match="^review_bundle_failed$") as caught:
        review_candidate_for_policy(s, binding=b, validation_receipt=v, author_identity="author",
            blind_solve_receipt=blind, reviewers=reviewers, policy=AutonomousEvidencePolicyV2())
    assert tuple(r.role for r in caught.value.partial_reports) == tuple(LearningItemReviewRole)[:3]
    assert [len(c.calls) for c in clients] == [1, 1, 1, 1, 0, 0]
    assert "UNIT_" not in str(caught.value)


def test_specialized_rubrics_share_every_hard_code_and_finite_boundaries():
    prompts = [evidenced_review_instruction(role) for role in LearningItemReviewRole]
    assert len(set(prompts)) == 6
    for role, prompt in zip(LearningItemReviewRole, prompts, strict=True):
        assert HARD_CODES <= ROLE_CODES[role]
        assert all(token in prompt for token in ("KC", "SQLite", "sql_v2", "major", "critical", "counterexample", "expected_behavior"))
        assert "Equal numeric parts" in prompt and "complete labeled options/outcomes" in prompt
    assert "multiple_choice legitimately" in prompts[3]
    assert "explicitly bounded syntax" in prompts[-1]


@pytest.mark.parametrize("target", ["python-kc-binding-v1", "python-state-update-v1", "sqlite-predicate-order-v1"])
def test_labeled_finite_known_good_inputs_keep_exact_scoring_descriptor(target):
    from app.services.learning.item_supply.finite_candidate_validation import prepare_finite_candidate_validation
    from app.services.learning.item_supply.finite_review_descriptor import finite_review_context
    from tests.learning.test_item_supply_shared_review import _candidate, binding, declared_validation
    spec, materials, source = _candidate(target)
    validation = (prepare_finite_candidate_validation(source, spec=spec, materials=materials).static_facts.validation
                  if target == "python-kc-binding-v1" else declared_validation(source, spec))
    bound = binding(source, DIGEST)
    _, roles, _ = evidenced_ports()
    with finite_review_context(source, spec=spec, materials=materials):
        request = make_review_request(source, binding=bound, role=roles[2].role,
                                      validation_receipt=validation, protocol="evidenced-v1")
        report = roles[2].review(request)
        assert report.verdict.value == "approved" and report.findings == ()
        assert request.review_input.scoring_descriptor is not None
        assert "scoring_descriptor" in json.loads(roles[2]._client.calls[0][0][1]["content"])["review_input"]
    # These labeled protocol doubles DO NOT measure real reviewer correctness.


def test_private_owner_keeps_partial_roles_and_blocks_same_reservation_retry(monkeypatch):
    from app.services.learning.item_supply.pipeline import ItemSupplyPipeline, PreparedReview
    from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
    from tests.learning.test_item_supply_shared_validation import OfflineConnection
    s, v, b = subject()
    solver, roles, _ = evidenced_ports(fail_role=LearningItemReviewRole.AMBIGUITY)
    conn = OfflineConnection()
    conn.info.transaction_status = TransactionStatus.IDLE
    owner = ItemSupplyPipeline(conn, Settings())
    lease = SimpleNamespace(profile=None)
    p = PreparedReview(lease, uuid4(), uuid4(), s, v, b, "author", uuid4(), "synthetic",
                       (1,)*7, review_protocol="evidenced-v1")
    monkeypatch.setattr(owner.runtime, "refresh_lease", lambda *a, **k: lease)
    with pytest.raises(AutonomousReviewError):
        owner.run_review(p, solver=solver, scorer=FakeScorer(), reviewers=roles)
    assert len(owner.partial_review_reports[p.reservation_id]) == 3
    with pytest.raises(PipelineRepositoryError, match="REVIEW_ALREADY_DISPATCHED"):
        owner.run_review(p, solver=solver, scorer=FakeScorer(), reviewers=roles)
    with pytest.raises(PipelineRepositoryError, match="REVIEW_PROTOCOL_CHANGED"):
        owner.run_review(p, solver=solver, scorer=FakeScorer(), reviewers=adapters()[1])
    assert configured_review_protocol(roles) == "evidenced-v1"


@pytest.mark.parametrize("case", ["mixed_protocol", "reservation_replay"])
def test_private_prepare_rejects_mixed_protocol_before_reserve_and_replay_before_dispatch(monkeypatch, case):
    from app.services.learning.item_supply.budget import ReservationResult
    from app.services.learning.item_supply.generation import generate_candidate
    from app.services.learning.item_supply.pipeline import ItemSupplyPipeline
    from app.services.learning.item_supply.policies import ResourceAmounts
    from tests.learning.test_item_supply_generation import SyntheticAuthority, SyntheticProvider
    from tests.learning.test_item_supply_pipeline import enabled_settings, pure_generation, review_ports
    from app.services.learning.item_supply.validation_adapter import validate_candidate

    generation, payload = pure_generation()
    # Pure synthetic generation supplies an authentic-shaped fixture receipt;
    # no production source/runtime checks are bypassed or loosened.
    result = generate_candidate(generation.request, provider=SyntheticProvider(payload),
                                source_authority=SyntheticAuthority(), enabled=True)
    source = result.source
    validation = validate_candidate(source)
    conn = SimpleNamespace(execute=lambda *a: SimpleNamespace(
        fetchone=lambda: {"payload_json": validation.model_dump(mode="json")}))
    owner = ItemSupplyPipeline(conn, enabled_settings())
    monkeypatch.setattr(owner.runtime, "refresh_lease", lambda lease, **kw: lease)
    monkeypatch.setattr(owner.runtime, "next_stage", lambda lease: "reviewing")
    monkeypatch.setattr(owner.artifacts, "get_generation", lambda **kw: {
        "source_json": source.model_dump(mode="json"), "receipt_json": result.receipt.model_dump(mode="json"),
        "candidate_id": generation.request.candidate_id, "version_id": uuid4()})
    solver, roles, clients = review_ports(source, generation.lease.profile.profile_hash, conn)
    reservations = []
    def reserve(**kw):
        reservations.append(kw)
        return ReservationResult(True, "REPLAY", uuid4())
    monkeypatch.setattr(owner.budget, "reserve", reserve)
    args = dict(lease=generation.lease, scope_id=generation.scope_id, artifact_id=uuid4(),
        mode="synthetic", resources=ResourceAmounts(requests=7, input_tokens=1, output_tokens=1),
        solver=solver, reviewers=roles)
    if case == "mixed_protocol":
        roles[0]._review_protocol = "evidenced-v1"
        with pytest.raises(ValueError, match="mixed or unknown review protocols"):
            owner.prepare_review(**args)
        assert not reservations
    else:
        assert owner.prepare_review(**args) is None and len(reservations) == 1
    assert not any(client.seen for client in clients)


def test_exact_legacy_input_report_bundle_output_hashes_are_unchanged():
    source, validation, binding = subject()
    bundle = make_bundle(source, validation, binding)
    old = ReviewInputV2(binding=binding, role=bundle.reports[0].role, source=source, validation_receipt=validation)
    assert old.input_hash == "544eaec7b469a8400f2300d0610368ddd45d2a3443abc7867c81623e7f8c5f27"
    raw = bundle.model_dump(mode="json")
    raw["bundle_id"] = "00000000-0000-0000-0000-000000000001"
    for n, run in enumerate([raw["blind_solve"]["run"], *[r["run"] for r in raw["reports"]]], 2):
        run["run_id"] = f"00000000-0000-0000-0000-{n:012d}"
    assert canonical_hash(raw) == "21c790328f9b24e68e752aa798c4a0c077ae5aa3ea5ae865cebf003e0883a41c"
    assert canonical_hash(raw["reports"][0]) == "5cf3423e7145f7d19bdbd1054ace69012ae1c31d2a3829b021ce91897f0cf5e7"
    assert raw["reports"][0]["run"]["output_hash"] == "c53393b6086419fdf0afa9e97f80143ab64773e260c94432922e0e85432dd67e"
    assert ReviewBundleV2.model_validate_json(json.dumps(raw)).model_dump(mode="json") == raw


def test_evidenced_high_risk_same_model_second_bundle_remains_quarantined():
    s, v, b, first, _ = bundle_fixture(risk=LearningItemRiskTier.HIGH)
    _, _, _, second, _ = bundle_fixture(risk=LearningItemRiskTier.HIGH, prefix="second", bundle_version=2)
    facts, registry, _ = high_facts(b, v)
    denied = evaluate_admission(s, binding=b, validation_receipt=v, policy=AutonomousEvidencePolicyV2(),
        author_identity="author", bundle=first, second_bundle=second, evidence=facts, risk_registry=registry, enabled=True)
    assert denied.disposition == "quarantine" and "independent_second_bundle_missing" in denied.safe_reasons


@pytest.mark.parametrize("model", ["deepseek-flash", "deepseek-v4-pro", "unsupported-model"])
def test_bounded_fresh_transport_high_thinking_unchanged_limits(model):
    s, v, b = subject()
    from tests.learning.test_item_supply_generation import make_request
    request, _ = make_request()
    profile = request.profile.model_copy(update={"profile_hash": DIGEST})
    calls = []
    def transport(url, headers, body, timeout):
        calls.append((body, timeout))
        if model == "deepseek-flash":
            return {"model": model, "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": json.dumps(APPROVAL)}]}]}
        return {"model": model, "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(APPROVAL)}}]}
    settings = Settings(llm_type="deepseek", deepseek_api_key="offline-not-secret", deepseek_model=model,
        deepseek_base_url="https://invalid.example", llm_timeout_seconds=90)
    client = BoundedOpenAIReviewClient(settings, profile=profile, transport=transport)
    reviewer = JsonReviewerV2(client, role=LearningItemReviewRole.TECHNICAL,
        identity=identity("fresh.technical", "deepseek", model), profile_hash=DIGEST,
        timeout_seconds=0.5, max_output_tokens=128, review_protocol="evidenced-v1")
    review_input = make_review_request(s, binding=b, role=reviewer.role, validation_receipt=v, protocol="evidenced-v1")
    if model == "unsupported-model":
        with pytest.raises(AutonomousReviewError):
            reviewer.review(review_input)
        assert not calls
        return
    report = reviewer.review(review_input)
    body, timeout = calls[0]
    assert len(calls) == 1 and timeout == 0.5 and report.run.max_output_tokens == 128
    assert "temperature" not in body and client.request_attempt_bound == 1
    if model == "deepseek-flash":
        assert body["reasoning"] == {"effort": "high"} and body["max_output_tokens"] == 128
    else:
        assert body["thinking"] == {"type": "enabled"} and body["reasoning_effort"] == "high" and body["max_tokens"] == 128
