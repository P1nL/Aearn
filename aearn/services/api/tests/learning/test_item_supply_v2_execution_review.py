"""Pure wiring fixtures only: no actual OS receipt, PG, or provider acceptance."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.learning.item_bank.compiler import LearningItemSourceLoader, curated_learning_item_source_root
from app.services.learning.item_bank.contracts import (
    LearningItemReviewRole, LearningItemRiskTier, LearningItemSourceV1,
    LearningItemValidationCheckType, canonical_hash,
)
from app.services.learning.item_supply.admission import evaluate_admission_v2
from app.services.learning.item_supply.pipeline import ItemSupplyPipeline
from app.services.learning.item_supply.policies import ResourceAmounts
from app.services.learning.item_supply.review_contracts_v2 import (
    AdmissionEvidenceV2, BlindScoreV2, CandidateBindingV2, ProbeOutcomeV2, ProviderIdentityV2,
    ReviewBundleV2, ReviewInputV2, ValidationReceiptV2, execution_receipt_digest, receipt_digest,
)
from app.services.learning.item_supply.review_provider import (
    AutonomousReviewError, JsonBlindSolverV2, JsonReviewerV2, blind_solve_candidate, review_candidate, review_resource_plan,
)
from app.services.learning.item_supply.storage_contracts import AutonomousEvidencePolicyV2
from app.services.learning.item_supply.validation_adapter import (
    CandidateCheckV2, CandidateExecutionEvidenceV2, CandidateProbeV2, CandidateValidationV2, validate_candidate,
)
from app.services.learning.item_supply.validators.profiles import required_probes
from app.services.llm.llm_client import LLMJsonResponse

POLICY = AutonomousEvidencePolicyV2()
PROFILE_HASH = canonical_hash("pure-frozen-profile")


def source_fixture(*, sql: bool = False, risk: LearningItemRiskTier = LearningItemRiskTier.MEDIUM) -> LearningItemSourceV1:
    source = LearningItemSourceLoader().load(curated_learning_item_source_root(), "sql-filter-track-v2.yaml").source
    payload = source.model_dump(mode="json")
    payload["blueprint"]["publication_policy"].update(
        risk_tier=risk.value, human_approval_required=risk is LearningItemRiskTier.HIGH,
    )
    if not sql:
        payload["blueprint"].update(item_kind="code", purpose="exercise", language_id="python",
            runtime_profile_id="python_stdout_test", required_capabilities=["python.assignment"],
            allowed_interactions=["edit", "run"])
        payload["public"].update(kind="code", purpose="exercise", allowed_interactions=["edit", "run"])
        payload["public"]["content"] = {
            "type": "code", "language_id": "python", "editor_language": "python", "exercise_type": "code_completion",
            "starter_code": "print(0)", "code_blanks": [{"blank_key": "value", "expected_concept": "assignment",
                "acceptable_patterns": [{"type": "literal", "value": "1"}], "is_core": True}],
        }
        payload["private"].update(kind="code")
        payload["private"]["content"] = {
            "type": "code", "standard_answer": "print(1)",
            "tests": [{"id": case, "case_type": visibility, "expected_output_json": {"stdout": "1"}, "order_index": order}
                for order, (case, visibility) in enumerate((("visible", "visible"), ("hidden", "hidden")))],
            "score_policy": {"kind": "all_tests", "policy_version": "all_tests_v1", "threshold": 1.0},
        }
    return LearningItemSourceV1.model_validate(payload)


def binding_for(source: LearningItemSourceV1) -> CandidateBindingV2:
    return CandidateBindingV2(candidate_key="candidate-1", version_key="version-1", source_hash=source.source_hash,
        content_hash=source.content_hash, policy_hash=POLICY.policy_hash, profile_hash=PROFILE_HASH,
        runtime_key=source.blueprint.runtime_profile_id or "static-exact-v1", risk_tier=source.blueprint.publication_policy.risk_tier)


def live_validation_fixture(source: LearningItemSourceV1) -> CandidateValidationV2:
    # Typed live-shaped facts are unit fixtures, NOT authenticated real execution.
    execution = CandidateExecutionEvidenceV2(
        source_hash=source.source_hash, content_hash=source.content_hash,
        kind=source.public.kind.value, language=source.blueprint.language_id,
        runtime_profile_id=source.blueprint.runtime_profile_id, dialect="sqlite" if source.public.kind.value == "sql" else None,
        runner_version="unit-runner-v1", scorer_version="unit-scorer-v1", run_id=uuid4(),
        mode="live", isolation="approved_os_boundary",
        probes=tuple(CandidateProbeV2(name=name, status="passed", proof_hash=canonical_hash((source.source_hash, name)),
            profile_version="unit-probe-v1") for name in required_probes(source)),
    )
    digest = canonical_hash(execution.model_dump(mode="json"))
    return CandidateValidationV2(state="machine_verified", source_hash=source.source_hash, content_hash=source.content_hash,
        mode="live", execution_evidence=execution,
        checks=tuple(CandidateCheckV2(check_type=kind, status="passed", proof_hash=digest) for kind in LearningItemValidationCheckType))


@dataclass
class OfflineClient:
    model: str
    content: dict[str, object]
    request_attempt_bound: int = 1
    inputs: list[dict[str, object]] = field(default_factory=list)

    def complete_json(self, messages: Sequence[Mapping[str, str]], *, max_tokens: int | None = None,
        timeout_seconds: float | None = None, output_schema: Mapping[str, object] | None = None,
        schema_name: str = "response", capture_provider_body: bool = True) -> LLMJsonResponse:
        assert max_tokens == 512 and timeout_seconds == 10 and capture_provider_body is False
        assert output_schema is not None
        assert canonical_hash(output_schema) == canonical_hash(json.loads(messages[0]["content"].split("exact output schema:\n")[1]))
        assert "unit-answer" not in messages[0]["content"]
        if schema_name == "item_supply_blind_answer_v2":
            assert "complete executable source code" in messages[0]["content"]
            assert "single executable SQL query" in messages[0]["content"]
            assert "must not contain predicted output, result values/rows, explanations, Markdown, or code fences" in messages[0]["content"]
        self.inputs.append(json.loads(messages[1]["content"]))
        return LLMJsonResponse(content=self.content, model=self.model)


class OfflineScorer:
    def score(self, source: LearningItemSourceV1, *, answer: str) -> BlindScoreV2:
        return BlindScoreV2(passed=answer == "unit-answer", scorer_identity="unit-scorer", scorer_version="unit-scorer-v1",
            receipt_hash=canonical_hash((source.source_hash, answer)))


def ports(*, prefix: str = "first", model: str = "unit-model"):
    clients = [OfflineClient(model, {"answer": "unit-answer"})] + [
        OfflineClient(model, {"verdict": "approved", "findings": []}) for _ in range(6)]
    def identity(name: str) -> ProviderIdentityV2:
        return ProviderIdentityV2(identity=prefix + "-" + name, provider="unit-provider", model=model)
    solver = JsonBlindSolverV2(clients[0], identity=identity("solver"), profile_hash=PROFILE_HASH,
        timeout_seconds=10, max_output_tokens=512)
    reviewers = tuple(JsonReviewerV2(client, role=role, identity=identity(role.value), profile_hash=PROFILE_HASH,
        timeout_seconds=10, max_output_tokens=512) for role, client in zip(LearningItemReviewRole, clients[1:], strict=True))
    return solver, reviewers, clients


def bundle_for(source: LearningItemSourceV1, validation: ValidationReceiptV2, binding: CandidateBindingV2,
    *, prefix: str = "first", model: str = "unit-model", version: int = 1) -> ReviewBundleV2:
    solver, reviewers, _ = ports(prefix=prefix, model=model)
    blind = blind_solve_candidate(source, binding=binding, author_identity="author", solver=solver, scorer=OfflineScorer())
    return review_candidate(source, binding=binding, validation_receipt=validation, author_identity="author",
        blind_solve_receipt=blind, reviewers=reviewers, bundle_version=version)


def evidence_for(validation: CandidateValidationV2, binding: CandidateBindingV2) -> AdmissionEvidenceV2:
    assert validation.execution_evidence is not None
    probes = {probe.name: probe.proof_hash for probe in validation.execution_evidence.probes}
    names = {"correct": "reference", "incorrect": "wrong_rejected", "ambiguity": None,
        "equivalent": "equivalent", "known_wrong": "wrong_rejected", "boundary": "boundary",
        "scorer_counterexample": "scorer_counterexample"}
    return AdmissionEvidenceV2(binding=binding, validation_receipt_hash=receipt_digest(validation), source_current=True,
        source_claim_receipt_hashes=(canonical_hash("unit-current-claim"),), coverage_proof_hash=canonical_hash("unit-coverage"),
        probes=tuple(ProbeOutcomeV2.model_validate({"probe": name, "passed": True,
            "receipt_hash": probes[execution_name] if execution_name else canonical_hash("unit-ambiguity")})
            for name, execution_name in names.items()),
        execution_receipt_hash=execution_receipt_digest(validation), execution_isolated=True,
        runner_available=True, scorer_available=True)


def evaluate(source, validation, binding, bundle, evidence, **kwargs):
    return evaluate_admission_v2(source, binding=binding, policy=POLICY, validation_receipt=validation,
        author_identity="author", bundle=bundle, evidence=evidence, enabled=True, **kwargs)


def test_live_python_and_sql_enter_blind_six_roles_without_legacy_receipt() -> None:
    for sql in (False, True):
        source = source_fixture(sql=sql)
        binding = binding_for(source)
        validation = live_validation_fixture(source)
        solver, reviewers, clients = ports()
        plan = review_resource_plan(source, binding=binding, validation_receipt=validation, solver=solver, reviewers=reviewers)
        assert plan.requests == 7 and plan.output_tokens == 7 * 512
        assert plan.input_tokens > len(validation.model_dump_json().encode("utf-8")) * 6
        blind = blind_solve_candidate(source, binding=binding, author_identity="author", solver=solver, scorer=OfflineScorer())
        bundle = review_candidate(source, binding=binding, validation_receipt=validation, author_identity="author",
            blind_solve_receipt=blind, reviewers=reviewers)
        assert validation.legacy_receipt is None
        assert "validation_receipt" not in clients[0].inputs[0]
        for client in clients[1:]:
            payload = client.inputs[0]
            assert payload["validation_receipt"]["schema_version"] == "candidate_validation_v2"
            assert payload["validation_receipt"]["execution_evidence"]["kind"] == source.public.kind.value
            assert payload["validation_receipt_hash"] == validation.evidence_hash
            assert "reports" not in payload and "blind_solve" not in payload
        result = evaluate(source, validation, binding, bundle, evidence_for(validation, binding))
        assert result.disposition == "eligible_internal" and not result.publication_enabled


def test_static_knowledge_v1_and_v2_keep_their_own_discriminator_and_digest() -> None:
    source = LearningItemSourceLoader().load(curated_learning_item_source_root(), "knowledge-class-attribute-v1.json").source
    validation = validate_candidate(source)
    assert validation.legacy_receipt is not None
    binding = binding_for(source)
    assert receipt_digest(validation) == validation.evidence_hash
    assert receipt_digest(validation.legacy_receipt) == validation.legacy_receipt.receipt_hash
    assert receipt_digest(validation) != receipt_digest(validation.legacy_receipt)
    assert execution_receipt_digest(validation) is None
    broken_check = validation.legacy_receipt.checks[0].model_copy(update={"status": "failed", "safe_code": "unit_failure"})
    broken_legacy = validation.legacy_receipt.model_copy(update={"checks": (broken_check,) + validation.legacy_receipt.checks[1:]})
    with pytest.raises(ValueError):
        bundle_for(source, validation.model_copy(update={"legacy_receipt": broken_legacy}), binding)
    for receipt in (validation.legacy_receipt, validation):
        bundle = bundle_for(source, receipt, binding)
        facts = AdmissionEvidenceV2(binding=binding, validation_receipt_hash=receipt_digest(receipt), source_current=True,
            source_claim_receipt_hashes=(canonical_hash("unit-claim"),), coverage_proof_hash=canonical_hash("unit-coverage"),
            scorer_available=True, probes=tuple(ProbeOutcomeV2.model_validate({"probe": name, "passed": True,
                "receipt_hash": canonical_hash(name)}) for name in ("correct", "incorrect", "ambiguity")))
        assert evaluate(source, receipt, binding, bundle, facts).disposition == "eligible_internal"


def test_stale_runtime_and_execution_hash_are_not_overridden_by_votes() -> None:
    source = source_fixture()
    binding = binding_for(source)
    validation = live_validation_fixture(source)
    with pytest.raises(ValueError):
        bundle_for(source, validation, binding.model_copy(update={"runtime_key": "other-runtime"}))
    bundle = bundle_for(source, validation, binding)
    stale = evidence_for(validation, binding).model_copy(update={"execution_receipt_hash": canonical_hash("stale-run")})
    assert evaluate(source, validation, binding, bundle, stale).safe_reasons == ("invalid_or_stale_evidence",)
    assert evaluate(source, validation, binding, bundle, stale).disposition == "quarantine"


def test_nested_extras_are_rejected_before_provider_input_normalization() -> None:
    source = source_fixture()
    binding = binding_for(source)
    validation = live_validation_fixture(source)
    assert validation.execution_evidence is not None
    tainted = validation.model_copy(update={"execution_evidence": validation.execution_evidence.model_copy(update={"forged": True})})
    with pytest.raises(ValueError):
        ReviewInputV2(binding=binding, role=LearningItemReviewRole.TECHNICAL, source=source, validation_receipt=tainted)
    tainted_source = source.model_copy(update={"public": source.public.model_copy(update={"forged": True})})
    with pytest.raises(ValueError):
        ReviewInputV2(binding=binding, role=LearningItemReviewRole.TECHNICAL, source=tainted_source, validation_receipt=validation)
    with pytest.raises(ValueError):
        ReviewInputV2(binding=binding, role=LearningItemReviewRole.TECHNICAL, source=source, validation_receipt=validation,
            validation_receipt_hash=canonical_hash("wrong-digest"))


def test_missing_or_unrelated_independent_medium_probes_never_green() -> None:
    source = source_fixture()
    binding = binding_for(source)
    validation = live_validation_fixture(source)
    bundle = bundle_for(source, validation, binding)
    facts = evidence_for(validation, binding)
    missing = facts.model_copy(update={"probes": facts.probes[:3], "execution_receipt_hash": None})
    result = evaluate(source, validation, binding, bundle, missing)
    assert result.disposition == "evidence_pending"
    assert set(result.safe_reasons) == {"trusted_isolated_execution_missing", "medium_profile_incomplete"}
    unrelated = facts.model_copy(update={"probes": facts.probes[:3] + (
        facts.probes[3].model_copy(update={"receipt_hash": canonical_hash("not-executed")}),) + facts.probes[4:]})
    assert evaluate(source, validation, binding, bundle, unrelated).disposition == "quarantine"
    assert validation.execution_evidence is not None
    partial = validation.model_copy(update={"execution_evidence": validation.execution_evidence.model_copy(update={
        "probes": tuple(probe for probe in validation.execution_evidence.probes if probe.name != "equivalent")})})
    with pytest.raises(ValueError):
        bundle_for(source, partial, binding)
    tiny = JsonReviewerV2(clients := OfflineClient("unit-model", {"verdict": "approved", "findings": []}),
        role=LearningItemReviewRole.TECHNICAL, identity=ProviderIdentityV2(identity="tiny-review", provider="unit-provider", model="unit-model"),
        profile_hash=PROFILE_HASH, timeout_seconds=10, max_output_tokens=512, max_input_bytes=1024)
    with pytest.raises(AutonomousReviewError):
        tiny.input_resource_plan(ReviewInputV2(binding=binding, role=tiny.role, source=source, validation_receipt=validation))
    assert not clients.inputs


def test_high_requires_real_second_independence_and_each_risk_adapter() -> None:
    source = source_fixture(risk=LearningItemRiskTier.HIGH)
    binding = binding_for(source)
    validation = live_validation_fixture(source)
    bundle = bundle_for(source, validation, binding)
    facts = evidence_for(validation, binding)
    result = evaluate(source, validation, binding, bundle, facts)
    assert result.disposition == "quarantine"
    assert "independent_second_bundle_missing" in result.safe_reasons
    second = bundle_for(source, validation, binding, prefix="second", model="unit-independent-model", version=2)
    result = evaluate(source, validation, binding, bundle, facts, second_bundle=second)
    assert result.disposition == "quarantine"
    assert result.safe_reasons == ("critical_risk_adapter_unverified",)


def test_live_review_preserves_author_role_and_hard_blocker_fences() -> None:
    source = source_fixture()
    binding = binding_for(source)
    validation = live_validation_fixture(source)
    solver, reviewers, clients = ports()
    blind = blind_solve_candidate(source, binding=binding, author_identity="author", solver=solver, scorer=OfflineScorer())
    with pytest.raises(AutonomousReviewError):
        review_candidate(source, binding=binding, validation_receipt=validation, author_identity=reviewers[0].provider_identity.identity,
            blind_solve_receipt=blind, reviewers=reviewers)
    with pytest.raises(AutonomousReviewError):
        review_candidate(source, binding=binding, validation_receipt=validation, author_identity="author",
            blind_solve_receipt=blind, reviewers=reviewers[:-1])
    assert not any(client.inputs for client in clients[1:])
    clients[1].content = {"verdict": "approved", "findings": [{"severity": "minor", "blocking": False,
        "safe_code": "security", "evidence_hash": canonical_hash("unit-security")} ]}
    bundle = review_candidate(source, binding=binding, validation_receipt=validation, author_identity="author",
        blind_solve_receipt=blind, reviewers=reviewers)
    assert evaluate(source, validation, binding, bundle, evidence_for(validation, binding)).safe_reasons == ("material_review_failure",)


def test_prepare_review_reads_whole_v2_and_rejects_bad_json_before_reserving(monkeypatch) -> None:
    # This tests only local wiring; namespace/current-source checks are not
    # claimed here. No psycopg connection or trusted live authorizer is created.
    source = source_fixture()
    validation = live_validation_fixture(source)
    solver, reviewers, _ = ports()
    candidate_id, version_id, artifact_id, scope_id = uuid4(), uuid4(), uuid4(), uuid4()
    artifact = {"candidate_id": candidate_id, "version_id": version_id, "source_json": source.model_dump(mode="json"),
        "receipt_json": {"candidate_id": str(candidate_id), "scope_hash": canonical_hash("scope"),
            "provider": {"provider": "unit-provider", "provider_version": "unit-v1", "configured_model": "unit-model",
                "model": "unit-model", "prompt_version": "unit-author-v1", "run_id": str(uuid4()), "request_attempt_bound": 1,
                "usage": {"state": "unknown"}, "mode": "synthetic"},
            "sources": [{"material_digest": canonical_hash("material"), "binding_digest": canonical_hash("binding"),
                "corpus_version_id": str(uuid4()), "active_generation": 1, "checked_at_iso": "unit-check",
                "claim_receipt_hashes": [canonical_hash("claim")], "mode": "synthetic"}]}}
    lease = SimpleNamespace(owner_id=uuid4(), owner_epoch=1, profile=SimpleNamespace(profile_hash=PROFILE_HASH))
    stored = {"payload_json": validation.model_dump(mode="json")}
    reservations = []
    pipeline = object.__new__(ItemSupplyPipeline)
    pipeline.settings = SimpleNamespace(learning_item_supply_enabled=True, learning_item_generation_enabled=True,
        learning_item_network_enabled=True, learning_item_v2_admission_enabled=True)
    pipeline.conn = SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchone=lambda: stored))
    pipeline.runtime = SimpleNamespace(refresh_lease=lambda lease, **kwargs: lease, next_stage=lambda lease: "reviewing")
    pipeline.artifacts = SimpleNamespace(get_generation=lambda **kwargs: artifact)
    def reserve(**kwargs):
        reservations.append(kwargs)
        return SimpleNamespace(allowed=True, reservation_id=uuid4())
    pipeline.budget = SimpleNamespace(reserve=reserve)
    monkeypatch.setattr(pipeline, "_fence_source", lambda *args: None)
    resources = ResourceAmounts(requests=7, input_tokens=100, output_tokens=3584)
    prepared = pipeline.prepare_review(lease=lease, scope_id=scope_id, artifact_id=artifact_id, mode="synthetic",
        resources=resources, solver=solver, reviewers=reviewers)
    assert prepared is not None and prepared.validation == validation and prepared.validation.legacy_receipt is None
    assert len(reservations) == 1 and prepared.attempt_bounds == (1,) * 7
    stored["payload_json"]["execution_evidence"]["forged"] = True
    with pytest.raises(ValueError):
        pipeline.prepare_review(lease=lease, scope_id=scope_id, artifact_id=artifact_id, mode="synthetic",
            resources=resources, solver=solver, reviewers=reviewers)
    assert len(reservations) == 1
