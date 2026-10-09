"""Focused offline v2 review contract checks; no DB, provider or bootstrap."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import json

import pytest

from app.core.config import Settings

from app.services.learning.item_bank.autonomous_policy import evaluate_autonomous_admission
from app.services.learning.item_bank.compiler import LearningItemCompiler, curated_learning_item_source_root
from app.services.learning.item_bank.contracts import (
    LearningItemReviewRole, LearningItemRiskTier, LearningItemSourceV1,
    LearningItemValidationReceiptV1, canonical_hash,
)
from app.services.learning.item_bank.review_contracts import LearningItemReviewSeverity
from app.services.learning.item_bank.validation import validate_learning_item
from app.services.learning.item_supply.admission import evaluate_admission_v2
from app.services.learning.item_supply.review_contracts_v2 import (
    AdmissionEvidenceV2, BlindScoreV2, CandidateBindingV2, ProbeOutcomeV2,
    ProviderIdentityV2, ReviewBundleV2, RiskEvidenceV2,
)
from app.services.learning.item_supply.review_provider import (
    AutonomousReviewError, BoundedOpenAIReviewClient, JsonBlindSolverV2, JsonReviewerV2, blind_input,
    blind_solve_candidate, review_candidate,
)
from app.services.learning.item_supply.risk_adapters import (
    VerifiedRiskReceiptV2, registered_receipt_adapter,
)
from app.services.learning.item_supply.risk_registry import RiskAdapterRegistry
from app.services.learning.item_supply.storage_contracts import AutonomousEvidencePolicyV2, checked_model
from app.services.llm.llm_client import LLMJsonResponse, OpenAICompatibleClient

DIGEST = canonical_hash("frozen-profile")
POLICY = AutonomousEvidencePolicyV2()


@dataclass
class FakeJsonClient:
    model: str = "test-model"
    request_attempt_bound: int = 1
    content: dict[str, object] = field(default_factory=lambda: {"verdict": "approved", "findings": []})
    seen: list[Sequence[Mapping[str, str]]] = field(default_factory=list)
    kwargs: list[dict[str, object]] = field(default_factory=list)

    def complete_json(
        self, messages: Sequence[Mapping[str, str]], *, max_tokens: int | None = None,
        timeout_seconds: float | None = None, output_schema: Mapping[str, object] | None = None,
        schema_name: str = "response", capture_provider_body: bool = True,
    ) -> LLMJsonResponse:
        self.seen.append(messages)
        self.kwargs.append(dict(max_tokens=max_tokens, timeout_seconds=timeout_seconds,
                                capture_provider_body=capture_provider_body))
        return LLMJsonResponse(content=self.content, model=self.model)


class FakeScorer:
    def score(self, source: LearningItemSourceV1, *, answer: str) -> BlindScoreV2:
        return BlindScoreV2(passed=answer == "class", scorer_identity="test-scorer",
                            scorer_version="test-v1", receipt_hash=canonical_hash((source.content_hash, answer)))


def subject(risk: LearningItemRiskTier = LearningItemRiskTier.LOW) -> tuple[
    LearningItemSourceV1, LearningItemValidationReceiptV1, CandidateBindingV2,
]:
    compiled = LearningItemCompiler().compile_file(curated_learning_item_source_root(),
                                                  "knowledge-class-attribute-v1.json", require_valid=True)
    data = compiled.loaded.source.model_dump(mode="json")
    data["blueprint"]["publication_policy"]["risk_tier"] = risk.value
    data["blueprint"]["publication_policy"]["human_approval_required"] = risk is LearningItemRiskTier.HIGH
    source = LearningItemSourceV1.model_validate(data)
    receipt = validate_learning_item(source)
    binding = CandidateBindingV2(candidate_key="candidate-1", version_key="candidate-version-1",
                                 content_hash=source.content_hash, source_hash=source.source_hash,
                                 policy_hash=POLICY.policy_hash, profile_hash=DIGEST,
                                 runtime_key="static-exact-v1", risk_tier=risk)
    return source, receipt, binding


def identity(name: str, provider: str = "test-provider", model: str = "test-model") -> ProviderIdentityV2:
    return ProviderIdentityV2(identity=name, provider=provider, model=model)


def adapters(provider: str = "test-provider", prefix: str = "first", model: str = "test-model") -> tuple[
    JsonBlindSolverV2, tuple[JsonReviewerV2, ...], list[FakeJsonClient],
]:
    clients = [FakeJsonClient(model=model, content={"answer": "class"})] + [FakeJsonClient(model=model) for _ in range(6)]
    solver = JsonBlindSolverV2(clients[0], identity=identity(prefix + "-solver", provider, model),
                              profile_hash=DIGEST, timeout_seconds=15.0, max_output_tokens=1024)
    reviewers = tuple(JsonReviewerV2(client, role=role, identity=identity(prefix + "-" + role.value, provider, model),
                                     profile_hash=DIGEST, timeout_seconds=15.0, max_output_tokens=1024)
                      for role, client in zip(LearningItemReviewRole, clients[1:], strict=True))
    return solver, reviewers, clients


def make_bundle(source: LearningItemSourceV1, receipt: LearningItemValidationReceiptV1,
                binding: CandidateBindingV2, *, provider: str = "test-provider",
                prefix: str = "first", version: int = 1, model: str = "test-model") -> ReviewBundleV2:
    solver, reviewers, _ = adapters(provider, prefix, model)
    blind = blind_solve_candidate(source, binding=binding, author_identity="author", solver=solver, scorer=FakeScorer())
    return review_candidate(source, binding=binding, validation_receipt=receipt, author_identity="author",
                            blind_solve_receipt=blind, reviewers=reviewers, bundle_version=version)


def evidence(binding: CandidateBindingV2, receipt: LearningItemValidationReceiptV1,
             *, medium: bool = False) -> AdmissionEvidenceV2:
    names = ("correct", "incorrect", "ambiguity")
    if medium:
        names += ("equivalent", "known_wrong", "boundary", "scorer_counterexample")
    return AdmissionEvidenceV2(
        binding=binding, validation_receipt_hash=receipt.receipt_hash, source_current=True,
        source_claim_receipt_hashes=(canonical_hash("current-claim"),), coverage_proof_hash=canonical_hash("proof"),
        probes=tuple(ProbeOutcomeV2.model_validate({"probe": name, "passed": True, "receipt_hash": canonical_hash(name)})
                     for name in names), execution_receipt_hash=canonical_hash("execution") if medium else None,
        execution_isolated=medium, runner_available=medium, scorer_available=True,
    )


def evaluate(source: LearningItemSourceV1, receipt: LearningItemValidationReceiptV1,
             binding: CandidateBindingV2, bundle: ReviewBundleV2, facts: AdmissionEvidenceV2,
             **kwargs: object):
    return evaluate_admission_v2(source, binding=binding, policy=POLICY, validation_receipt=receipt,
                                 author_identity="author", bundle=bundle, evidence=facts, enabled=True, **kwargs)


def test_public_only_blind_solver_and_six_peer_blind_actual_adapters() -> None:
    source, receipt, binding = subject()
    solver, reviewers, clients = adapters()
    blind = blind_solve_candidate(source, binding=binding, author_identity="author", solver=solver, scorer=FakeScorer())
    bundle = review_candidate(source, binding=binding, validation_receipt=receipt, author_identity="author",
                              blind_solve_receipt=blind, reviewers=reviewers)
    solver_text = clients[0].seen[0][1]["content"]
    for forbidden in ("accepted_answers", "answer_explanation_markdown", "hidden_wrong", "hints", "rubric", "reports"):
        assert forbidden not in solver_text
    assert "Which attribute" in solver_text
    assert bundle.correlation_limited and len(bundle.correlation_groups) == 1
    for client in clients:
        assert client.kwargs == [dict(max_tokens=1024, timeout_seconds=15.0, capture_provider_body=False)]
    for client in clients[1:]:
        assert "blind_solve" not in client.seen[0][1]["content"]
        assert "reports" not in client.seen[0][1]["content"]
    stored = bundle.model_dump(mode="json")
    assert "answer" not in stored["blind_solve"]
    assert bundle.blind_solve.run.input_tokens is None
    assert bundle.receipt_hash == bundle.bundle_hash


def test_author_cannot_solve_or_review_before_transport() -> None:
    source, receipt, binding = subject()
    solver, reviewers, clients = adapters(prefix="author")
    with pytest.raises(AutonomousReviewError):
        blind_solve_candidate(source, binding=binding, author_identity="author-solver", solver=solver, scorer=FakeScorer())
    assert not clients[0].seen
    blind = make_bundle(source, receipt, binding).blind_solve
    with pytest.raises(AutonomousReviewError):
        review_candidate(source, binding=binding, validation_receipt=receipt, author_identity="author-curriculum",
                          blind_solve_receipt=blind, reviewers=reviewers)
    assert all(not client.seen for client in clients[1:])


def test_missing_roles_rejected_before_transport() -> None:
    source, receipt, binding = subject()
    solver, reviewers, clients = adapters()
    blind = blind_solve_candidate(source, binding=binding, author_identity="author", solver=solver, scorer=FakeScorer())
    with pytest.raises(AutonomousReviewError):
        review_candidate(source, binding=binding, validation_receipt=receipt, author_identity="author",
                          blind_solve_receipt=blind, reviewers=reviewers[:-1])
    assert all(not client.seen for client in clients[1:])


def test_provider_cannot_choose_identity_or_raw_body_and_errors_are_safe() -> None:
    source, _, binding = subject()
    solver, _, clients = adapters()
    clients[0].content = {"answer": "class", "run_id": "provider-forged-secret"}
    with pytest.raises(AutonomousReviewError) as caught:
        solver.solve(blind_input(source, binding))
    assert str(caught.value) == "review_provider_failed"
    assert "secret" not in str(caught.value)


def test_low_eligible_is_internal_only_and_default_off() -> None:
    source, receipt, binding = subject()
    bundle = make_bundle(source, receipt, binding)
    facts = evidence(binding, receipt)
    result = evaluate(source, receipt, binding, bundle, facts)
    assert result.disposition == "eligible_internal" and result.publication_enabled is False
    assert result.safe_reasons == ("publication_port_pending",)
    assert result.correlation_limited
    off = evaluate_admission_v2(source, binding=binding, policy=POLICY, validation_receipt=receipt,
                                author_identity="author", bundle=bundle, evidence=facts)
    assert off.disposition == "blocked"


def test_major_finding_vetoes_even_approved_majority() -> None:
    source, receipt, binding = subject()
    solver, reviewers, clients = adapters()
    clients[3].content = {"verdict": "approved", "findings": [
        {"severity": "major", "blocking": False, "safe_code": "ambiguity", "evidence_hash": canonical_hash("finding")},
    ]}
    blind = blind_solve_candidate(source, binding=binding, author_identity="author", solver=solver, scorer=FakeScorer())
    bundle = review_candidate(source, binding=binding, validation_receipt=receipt, author_identity="author",
                              blind_solve_receipt=blind, reviewers=reviewers)
    result = evaluate(source, receipt, binding, bundle, evidence(binding, receipt))
    assert result.disposition == "quarantine" and "material_review_failure" in result.safe_reasons

    # A hard blocker cannot be downgraded by the provider's severity/boolean.
    hard = bundle.reports[2].findings[0].model_copy(update={
        "severity": LearningItemReviewSeverity.MINOR, "safe_code": "security", "blocking": False,
    })
    payload = {"verdict": "approved", "findings": [hard.model_dump(mode="json")]}
    report = bundle.reports[2].model_copy(update={
        "findings": (hard,), "run": bundle.reports[2].run.model_copy(update={"output_hash": canonical_hash(payload)}),
    })
    downgraded = bundle.model_copy(update={"reports": bundle.reports[:2] + (report,) + bundle.reports[3:]})
    assert evaluate(source, receipt, binding, downgraded, evidence(binding, receipt)).disposition == "quarantine"


def test_old_content_hash_and_old_review_input_fail_closed() -> None:
    source, receipt, binding = subject()
    bundle = make_bundle(source, receipt, binding)
    stale = binding.model_copy(update={"content_hash": canonical_hash("stale")})
    assert evaluate(source, receipt, stale, bundle, evidence(binding, receipt)).disposition == "quarantine"
    report = bundle.reports[0]
    report = report.model_copy(update={"run": report.run.model_copy(update={"input_hash": canonical_hash("old-input")})})
    old = bundle.model_copy(update={"reports": (report,) + bundle.reports[1:]})
    assert evaluate(source, receipt, binding, old, evidence(binding, receipt)).disposition == "quarantine"


@pytest.mark.parametrize("missing", ["source", "proof", "probes", "scorer"])
def test_low_requires_current_source_coverage_and_profile(missing: str) -> None:
    source, receipt, binding = subject()
    facts = evidence(binding, receipt)
    updates = {"source": {"source_current": False}, "proof": {"coverage_proof_hash": None},
               "probes": {"probes": ()}, "scorer": {"scorer_available": False}}
    result = evaluate(source, receipt, binding, make_bundle(source, receipt, binding), facts.model_copy(update=updates[missing]))
    assert result.disposition == "evidence_pending"


def test_medium_requires_real_isolation_and_scorer_counterexamples() -> None:
    source, receipt, binding = subject(LearningItemRiskTier.MEDIUM)
    bundle = make_bundle(source, receipt, binding)
    assert evaluate(source, receipt, binding, bundle, evidence(binding, receipt)).disposition == "evidence_pending"
    facts = evidence(binding, receipt, medium=True)
    assert evaluate(source, receipt, binding, bundle, facts).disposition == "eligible_internal"
    host = facts.model_copy(update={"execution_isolated": False})
    assert evaluate(source, receipt, binding, bundle, host).disposition == "evidence_pending"
    assert evaluate(source, receipt, binding, bundle, facts.model_copy(update={"known_misjudgments": 1})).disposition == "quarantine"


def high_facts(binding: CandidateBindingV2, receipt: LearningItemValidationReceiptV1):
    receipts: dict[str, VerifiedRiskReceiptV2] = {}

    class Resolver:
        def resolve(self, receipt_hash: str) -> VerifiedRiskReceiptV2 | None:
            return receipts.get(receipt_hash)

    adapters = tuple(registered_receipt_adapter(risk, supported_profile_hashes=(DIGEST,), resolver=Resolver())
                     for risk in ("source_security", "privacy"))
    risks = tuple(RiskEvidenceV2(binding=binding, risk=adapter.risk, adapter_version=adapter.version,
                                 profile_hash=DIGEST, verifier_identity="trusted-verifier", verifier_version="v2",
                                 receipt_hash=canonical_hash(adapter.risk), passed=True) for adapter in adapters)
    for adapter, risk in zip(adapters, risks, strict=True):
        receipts[risk.receipt_hash] = VerifiedRiskReceiptV2(binding=binding, risk=risk.risk, verifier_identity=risk.verifier_identity,
                                                          verifier_version=risk.verifier_version, receipt_hash=risk.receipt_hash,
                                                          checks=adapter.required_checks, passed=True, reproducible=True)
    facts = evidence(binding, receipt, medium=True).model_copy(update={"risk_evidence": risks})
    return facts, RiskAdapterRegistry(adapters), receipts


def test_high_missing_adapter_and_same_model_second_bundle_quarantined() -> None:
    source, receipt, binding = subject(LearningItemRiskTier.HIGH)
    bundle = make_bundle(source, receipt, binding)
    facts, registry, _ = high_facts(binding, receipt)
    second = make_bundle(source, receipt, binding, prefix="second", version=2)
    result = evaluate(source, receipt, binding, bundle, facts, second_bundle=second, risk_registry=registry)
    assert result.disposition == "quarantine" and "independent_second_bundle_missing" in result.safe_reasons
    separate = make_bundle(source, receipt, binding, provider="separate-provider", prefix="second", version=2)
    assert evaluate(source, receipt, binding, bundle, facts, second_bundle=separate).disposition == "quarantine"
    assert evaluate(source, receipt, binding, bundle, facts, second_bundle=separate,
                    risk_registry=registry).disposition == "quarantine"


def test_high_reproducible_registered_receipts_and_independent_second_bundle() -> None:
    source, receipt, binding = subject(LearningItemRiskTier.HIGH)
    bundle = make_bundle(source, receipt, binding)
    second = make_bundle(source, receipt, binding, provider="separate-provider", prefix="second", version=2,
                         model="independent-test-model")
    facts, registry, receipts = high_facts(binding, receipt)
    assert evaluate(source, receipt, binding, bundle, facts, second_bundle=second, risk_registry=registry).disposition == "eligible_internal"
    receipts.clear()
    assert evaluate(source, receipt, binding, bundle, facts, second_bundle=second, risk_registry=registry).disposition == "quarantine"


def test_risk_adapter_unsupported_profile_default_deny() -> None:
    _, receipt, binding = subject(LearningItemRiskTier.HIGH)
    facts, registry, _ = high_facts(binding, receipt)
    risk = facts.risk_evidence[0]
    assert registry.verifies(binding, risk)
    assert not registry.verifies(binding, risk.model_copy(update={"profile_hash": canonical_hash("unsupported")}))
    assert not RiskAdapterRegistry().verifies(binding, risk)


def test_v1_policy_and_p2_decision_remain_separate() -> None:
    source, receipt, binding = subject(LearningItemRiskTier.HIGH)
    assert source.blueprint.publication_policy.human_approval_required
    assert evaluate_autonomous_admission(POLICY, admission_key="legacy", enabled=True).decision == "evidence_pending"
    with pytest.raises(ValueError):
        checked_model(receipt, ReviewBundleV2)
    bundle = make_bundle(source, receipt, binding)
    with pytest.raises(ValueError):
        checked_model(bundle.model_copy(update={"publication_enabled": True}), ReviewBundleV2)


def test_bundle_new_version_immutable_hash_and_safe_extra_rejection() -> None:
    source, receipt, binding = subject()
    first = make_bundle(source, receipt, binding)
    second = make_bundle(source, receipt, binding, prefix="second", version=2)
    assert first.bundle_hash != second.bundle_hash
    with pytest.raises(ValueError):
        first.bundle_version = 9
    with pytest.raises(ValueError):
        checked_model(first.model_copy(update={"peer_reports": "forged"}), ReviewBundleV2)


def test_duplicate_reviewer_identity_and_answer_in_finding_code_rejected() -> None:
    source, receipt, binding = subject()
    solver, reviewers, clients = adapters()
    duplicate = JsonReviewerV2(clients[-1], role=LearningItemReviewRole.ADVERSARIAL,
                               identity=reviewers[0].provider_identity, profile_hash=DIGEST,
                               timeout_seconds=15.0, max_output_tokens=1024)
    blind = blind_solve_candidate(source, binding=binding, author_identity="author", solver=solver, scorer=FakeScorer())
    with pytest.raises(AutonomousReviewError):
        review_candidate(source, binding=binding, validation_receipt=receipt, author_identity="author",
                          blind_solve_receipt=blind, reviewers=reviewers[:-1] + (duplicate,))
    assert not clients[1].seen
    clients[1].content = {"verdict": "approved", "findings": [
        {"severity": "minor", "blocking": False, "safe_code": "private-answer-secret", "evidence_hash": canonical_hash("secret")},
    ]}
    with pytest.raises(AutonomousReviewError):
        review_candidate(source, binding=binding, validation_receipt=receipt, author_identity="author",
                          blind_solve_receipt=blind, reviewers=reviewers)


def test_deterministic_failure_and_corrupt_report_digest_cannot_be_voted_away() -> None:
    source, receipt, binding = subject()
    bundle = make_bundle(source, receipt, binding)
    first_check = receipt.checks[0].model_copy(update={"status": "failed", "safe_code": "schema_failure"})
    failed = receipt.model_copy(update={"checks": (first_check,) + receipt.checks[1:]})
    result = evaluate(source, failed, binding, bundle, evidence(binding, failed))
    assert result.disposition == "quarantine"
    first_report = bundle.reports[0]
    first_report = first_report.model_copy(update={"run": first_report.run.model_copy(update={"output_hash": canonical_hash("forged-output")})})
    bad_bundle = bundle.model_copy(update={"reports": (first_report,) + bundle.reports[1:]})
    assert evaluate(source, receipt, binding, bad_bundle, evidence(binding, receipt)).disposition == "quarantine"


def test_bounded_production_review_uses_frozen_transport_limits_and_single_attempt(monkeypatch) -> None:
    source, _, binding = subject()
    settings = Settings(llm_type="deepseek", deepseek_api_key="fake-key",
                        deepseek_base_url="https://example.com", deepseek_model="test-model",
                        llm_timeout_seconds=90)
    calls = []

    def transport(url, headers, body, timeout):
        calls.append((body, timeout))
        return {"model": "test-model", "choices": [{"message": {"content": json.dumps({"answer": "class"})}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 2}}

    from tests.learning.test_item_supply_generation import make_request
    request, _ = make_request()
    profile = request.profile.model_copy(update={"profile_hash": DIGEST})
    client = BoundedOpenAIReviewClient(settings, profile=profile, transport=transport)
    solver = JsonBlindSolverV2(client, identity=identity("solver", "deepseek"), profile_hash=DIGEST,
                              timeout_seconds=0.5, max_output_tokens=128)
    result = solver.solve(blind_input(source, binding))
    assert calls[0][1] == 0.5 and calls[0][0]["max_tokens"] == 128
    assert calls[0][0]["thinking"] == {"type": "disabled"}
    assert result.run.input_tokens == 7 and result.run.output_tokens == 2
    assert client.request_attempt_bound == 1 and settings.llm_timeout_seconds == 90

    # Exercise actual core retry selection without network, not a fake transport
    # that bypasses the HTTP retry branch entirely.
    from app.services.llm import llm_client
    attempts = []

    def failing_http(url, headers, payload, timeout, *, diagnostic_capture=None, max_attempts=3):
        attempts.append(max_attempts)
        raise TimeoutError("private provider diagnostics")

    monkeypatch.setattr(llm_client, "_post_json", failing_http)
    failed = JsonBlindSolverV2(BoundedOpenAIReviewClient(settings, profile=profile), identity=identity("solver", "deepseek"),
                              profile_hash=DIGEST, timeout_seconds=0.5, max_output_tokens=128)
    with pytest.raises(AutonomousReviewError, match="^review_provider_failed$"):
        failed.solve(blind_input(source, binding))
    assert attempts == [1]
    calls.clear()

    with pytest.raises(AutonomousReviewError, match="^bounded_review_client_required$"):
        JsonBlindSolverV2(OpenAICompatibleClient(settings, transport=transport),
                          identity=identity("solver", "deepseek"), profile_hash=DIGEST,
                          timeout_seconds=0.5, max_output_tokens=128)
    assert not calls
