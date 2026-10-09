"""Pure internal v2 evaluation. No publication, human approval or DB mutation."""
from __future__ import annotations

from typing import Any, Literal, TypedDict, cast

from app.services.learning.item_bank.contracts import (
    LearningItemKind, LearningItemRiskTier, LearningItemSourceV1,
    canonical_hash, stable_key,
)
from app.services.learning.item_supply.review_contracts_v2 import (
    AdmissionEvaluationV2, AdmissionEvidenceV2, CandidateBindingV2,
    ReviewBundleV2, ValidationReceiptV2, check_subject, checked_validation_receipt,
    execution_receipt_digest, receipt_digest, validation_passed,
)
from app.services.learning.item_supply.review_provider import (
    BLIND_PROMPT_VERSION, blind_input,
)
from app.services.learning.item_supply.review_protocol import make_review_request, report_protocol, verify_review_report
from app.services.learning.item_supply.risk_registry import RiskAdapterRegistry, required_critical_risks
from app.services.learning.item_supply.storage_contracts import AutonomousEvidencePolicyV2, checked_model
from app.services.learning.item_supply.diagnostic_policy import (
    AdmissionEvaluation, AdmissionEvaluationV3, AutonomousEvidencePolicyV3, EvidencePolicy,
    ReviewBundle, ReviewBundleV3, checked_bundle, checked_policy,
)
from app.services.learning.item_supply.validation_adapter import CandidateValidationV2


class _EvaluationCommon(TypedDict):
    binding: CandidateBindingV2
    bundle_hashes: tuple[str, ...]
    evidence_hash: str
    correlation_limited: bool


def _check_bundle(
    source: LearningItemSourceV1, binding: CandidateBindingV2,
    receipt: ValidationReceiptV2, bundle: ReviewBundle, author_identity: str,
) -> None:
    if bundle.binding != binding or bundle.author_identity != author_identity:
        raise ValueError("stale bundle")
    if (bundle.blind_solve.run.input_hash != blind_input(source, binding).input_hash
            or bundle.blind_solve.run.prompt_version != BLIND_PROMPT_VERSION):
        raise ValueError("stale blind input")
    for report in bundle.reports:
        expected = make_review_request(source, binding=binding, role=report.role,
                                       validation_receipt=receipt, protocol=report_protocol(report))
        verify_review_report(report, expected)


def _independent(first: ReviewBundle, second: ReviewBundle) -> bool:
    # Include solver groups too; fresh UUIDs/role labels are insufficient.
    first_runs = (first.blind_solve.run,) + tuple(r.run for r in first.reports)
    second_runs = (second.blind_solve.run,) + tuple(r.run for r in second.reports)
    return (first.bundle_id != second.bundle_id and second.bundle_version > first.bundle_version
            and not ({r.run_id for r in first_runs} & {r.run_id for r in second_runs})
            and not ({r.provider_identity.identity for r in first_runs}
                     & {r.provider_identity.identity for r in second_runs})
            and not ({r.provider_identity.correlation_key for r in first_runs}
                     & {r.provider_identity.correlation_key for r in second_runs})
            # The same underlying model behind another endpoint/provider label
            # is correlated too, even when the configured provider names differ.
            and not ({r.provider_identity.model.casefold() for r in first_runs}
                     & {r.provider_identity.model.casefold() for r in second_runs}))


def evaluate_admission(
    source: LearningItemSourceV1, *, binding: CandidateBindingV2,
    policy: EvidencePolicy, validation_receipt: ValidationReceiptV2,
    author_identity: str, bundle: ReviewBundle, evidence: AdmissionEvidenceV2,
    second_bundle: ReviewBundle | None = None, risk_registry: RiskAdapterRegistry | None = None,
    enabled: bool = False,
) -> AdmissionEvaluation:
    warnings: tuple[Literal["blind_solution_incorrect"], ...] = ()

    def result(**kwargs: Any) -> AdmissionEvaluation:
        if type(policy) is AutonomousEvidencePolicyV3:
            return AdmissionEvaluationV3(**kwargs, diagnostic_warnings=warnings)
        return AdmissionEvaluationV2(**kwargs)

    binding = checked_model(binding, CandidateBindingV2)
    if enabled is not True:
        return result(binding=binding, disposition="blocked", safe_reasons=("feature_disabled",))
    try:
        source = checked_model(source, LearningItemSourceV1)
        policy = checked_policy(policy)
        validation_receipt = checked_validation_receipt(validation_receipt)
        evidence = checked_model(evidence, AdmissionEvidenceV2)
        bundle = checked_bundle(bundle)
        second = checked_bundle(second_bundle) if second_bundle is not None else None
        expected_bundle = ReviewBundleV3 if type(policy) is AutonomousEvidencePolicyV3 else ReviewBundleV2
        if type(bundle) is not expected_bundle or (second is not None and type(second) is not expected_bundle):
            raise ValueError("cross-policy bundle")
        author = stable_key(author_identity, label="v2 author identity")
        check_subject(source, binding, validation_receipt)
        if (binding.policy_hash != policy.policy_hash or evidence.binding != binding
                or evidence.validation_receipt_hash != receipt_digest(validation_receipt)):
            raise ValueError("stale evidence")
        execution_hash = execution_receipt_digest(validation_receipt)
        if (execution_hash is not None and evidence.execution_receipt_hash is not None
                and evidence.execution_receipt_hash != execution_hash):
            raise ValueError("stale admission execution receipt")
        if isinstance(validation_receipt, CandidateValidationV2) and validation_receipt.execution_evidence is not None:
            execution_probes = {probe.name: probe for probe in validation_receipt.execution_evidence.probes}
            # Independent profile facts must point at the executed receipt,
            # not arbitrary hashes paired with caller-supplied green booleans.
            probe_names = {"equivalent": "equivalent", "known_wrong": "wrong_rejected",
                           "boundary": "boundary", "scorer_counterexample": "scorer_counterexample"}
            for probe in evidence.probes:
                name = probe_names.get(probe.probe)
                if name is not None and probe.receipt_hash != execution_probes[name].proof_hash:
                    raise ValueError("stale admission execution probe")
        _check_bundle(source, binding, validation_receipt, bundle, author)
        if second is not None:
            _check_bundle(source, binding, validation_receipt, second, author)
    except Exception:
        return result(binding=binding, disposition="quarantine", safe_reasons=("invalid_or_stale_evidence",))

    bundles = (bundle,) if second is None else (bundle, second)
    common: _EvaluationCommon = dict(
        binding=binding, bundle_hashes=tuple(b.bundle_hash for b in bundles),
        evidence_hash=canonical_hash(evidence.model_dump(mode="json")),
        correlation_limited=any(b.correlation_limited for b in bundles),
    )
    blockers: list[str] = []
    if not validation_passed(validation_receipt):
        blockers.append("deterministic_failure")
    if any(not b.blind_solve.score.passed for b in bundles):
        if type(policy) is AutonomousEvidencePolicyV3:
            warnings = ("blind_solution_incorrect",)
        else:
            blockers.append("blind_solve_failed")
    if any(r.material_failure for b in bundles for r in b.reports):
        blockers.append("material_review_failure")
    if evidence.known_misjudgments:
        blockers.append("scorer_misjudgment")
    if any(not probe.passed for probe in evidence.probes):
        blockers.append("profile_probe_failed")
    if blockers:
        return result(**common, disposition="quarantine", safe_reasons=tuple(blockers))

    missing: list[str] = []
    if not evidence.source_current or not evidence.source_claim_receipt_hashes:
        missing.append("current_source_claim_missing")
    if evidence.coverage_proof_hash is None:
        missing.append("coverage_proof_missing")
    if not evidence.scorer_available:
        missing.append("trusted_scorer_missing")
    probes = {probe.probe for probe in evidence.probes if probe.passed}
    if not {"correct", "incorrect", "ambiguity"} <= probes:
        missing.append("low_profile_incomplete")
    execution_required = (binding.risk_tier is not LearningItemRiskTier.LOW
                          or source.public.kind is not LearningItemKind.KNOWLEDGE_CHECK)
    if execution_required:
        if (not evidence.execution_isolated or evidence.execution_receipt_hash is None
                or not evidence.runner_available or not evidence.scorer_available):
            missing.append("trusted_isolated_execution_missing")
        if not {"equivalent", "known_wrong", "boundary", "scorer_counterexample"} <= probes:
            missing.append("medium_profile_incomplete")
    if missing:
        return result(**common, disposition="evidence_pending", safe_reasons=tuple(missing))

    if binding.risk_tier is LearningItemRiskTier.HIGH:
        high_failures: list[str] = []
        required = set(required_critical_risks(source)) | set(evidence.critical_risks)
        by_risk = {fact.risk: fact for fact in evidence.risk_evidence}
        registry = risk_registry or RiskAdapterRegistry()
        if any(risk not in by_risk or not registry.verifies(binding, by_risk[risk]) for risk in required):
            high_failures.append("critical_risk_adapter_unverified")
        if second is None or not _independent(bundle, second):
            high_failures.append("independent_second_bundle_missing")
        if high_failures:
            return result(**common, disposition="quarantine", safe_reasons=tuple(high_failures))

    return result(**common, disposition="eligible_internal", safe_reasons=("publication_port_pending",))


def evaluate_admission_v2(
    source: LearningItemSourceV1, *, binding: CandidateBindingV2,
    policy: AutonomousEvidencePolicyV2, validation_receipt: ValidationReceiptV2,
    author_identity: str, bundle: ReviewBundleV2, evidence: AdmissionEvidenceV2,
    second_bundle: ReviewBundleV2 | None = None, risk_registry: RiskAdapterRegistry | None = None,
    enabled: bool = False,
) -> AdmissionEvaluationV2:
    """Legacy strict entry point cannot opt into V3, including copied/subclass DTOs."""
    if type(policy) is not AutonomousEvidencePolicyV2:
        return AdmissionEvaluationV2(binding=checked_model(binding, CandidateBindingV2),
            disposition="quarantine", safe_reasons=("invalid_or_stale_evidence",))
    return cast(AdmissionEvaluationV2, evaluate_admission(source, binding=binding, policy=policy,
        validation_receipt=validation_receipt, author_identity=author_identity, bundle=bundle,
        evidence=evidence, second_bundle=second_bundle, risk_registry=risk_registry, enabled=enabled))
