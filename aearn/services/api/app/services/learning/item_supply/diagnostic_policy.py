"""Explicit diagnostic policy contracts. Legacy V2 bytes remain canonical.

Policy hashes select only closed server-defined contracts; neither a boolean nor
an evaluation/warning authorizes execution, billing, source use or publication.
"""
from __future__ import annotations

import json
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_bank.review_contracts import REQUIRED_REVIEW_ROLES
from app.services.learning.item_supply.contracts import Digest, Identifier
from app.services.learning.item_supply.review_contracts_v2 import (
    AdmissionEvaluationV2, BlindSolveReceiptV2, CandidateBindingV2, ReviewBundleV2, ReviewReportV2,
)
from app.services.learning.item_supply.storage_contracts import (
    AutonomousEvidencePolicyV2, StorageContract, checked_model,
)

class AutonomousEvidencePolicyV3(StorageContract):
    schema_version: Literal["autonomous_evidence_policy_v3"] = "autonomous_evidence_policy_v3"
    policy_version: Literal["autonomous_evidence_policy_v3"] = "autonomous_evidence_policy_v3"
    blind_solve_mode: Literal["completed_diagnostic"] = "completed_diagnostic"
    publication_enabled: Literal[False] = False
    required_review_roles: tuple[Literal[
        "curriculum", "difficulty", "technical", "ambiguity", "security", "adversarial"
    ], ...] = ("curriculum", "difficulty", "technical", "ambiguity", "security", "adversarial")
    risk_adapter_required: Literal[True] = True
    independent_second_bundle_required: Literal[True] = True

    @model_validator(mode="after")
    def complete_roles(self) -> AutonomousEvidencePolicyV3:
        if self.required_review_roles != (
            "curriculum", "difficulty", "technical", "ambiguity", "security", "adversarial"
        ):
            raise ValueError("v3 review roles cannot be weakened")
        return self

    @property
    def policy_hash(self) -> str:
        return canonical_hash(checked_model(self, AutonomousEvidencePolicyV3).model_dump(mode="json"))


class ReviewBundleV3(StorageContract):
    schema_version: Literal["item_supply_review_bundle_v3"] = "item_supply_review_bundle_v3"
    policy_version: Literal["autonomous_evidence_policy_v3"] = "autonomous_evidence_policy_v3"
    state: Literal["completed"] = "completed"
    mode: Literal["peer_blind"] = "peer_blind"
    publication_enabled: Literal[False] = False
    bundle_id: UUID
    bundle_version: int = Field(ge=1)
    binding: CandidateBindingV2
    author_identity: Identifier
    blind_solve: BlindSolveReceiptV2
    reports: tuple[ReviewReportV2, ...] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def identities_and_binding(self) -> ReviewBundleV3:
        if self.binding.policy_hash != AutonomousEvidencePolicyV3().policy_hash:
            raise ValueError("v3 policy binding mismatch")
        if tuple(r.role for r in self.reports) != REQUIRED_REVIEW_ROLES:
            raise ValueError("v3 bundle requires all six canonical roles")
        runs = (self.blind_solve.run,) + tuple(r.run for r in self.reports)
        identities = tuple(r.provider_identity.identity for r in runs)
        if self.author_identity in identities or len(set(identities)) != len(identities):
            raise ValueError("author, solver and reviewer identities must be separate")
        if len({r.run_id for r in runs}) != len(runs):
            raise ValueError("review runs cannot be reused")
        if self.blind_solve.binding != self.binding or any(r.binding != self.binding for r in self.reports):
            raise ValueError("v3 bundle contains stale evidence")
        if any(r.profile_hash != self.binding.profile_hash for r in runs):
            raise ValueError("v3 bundle profile mismatch")
        return self

    @property
    def correlation_groups(self) -> tuple[str, ...]:
        return tuple(sorted({r.run.provider_identity.correlation_key for r in self.reports}))

    @property
    def correlation_limited(self) -> bool:
        models = {r.run.provider_identity.model.casefold() for r in self.reports}
        return len(self.correlation_groups) != len(self.reports) or len(models) != len(self.reports)

    @property
    def bundle_hash(self) -> str:
        return canonical_hash(checked_model(self, ReviewBundleV3).model_dump(mode="json"))

    @property
    def receipt_hash(self) -> str:
        return self.bundle_hash


class AdmissionEvaluationV3(StorageContract):
    schema_version: Literal["item_supply_admission_evaluation_v3"] = "item_supply_admission_evaluation_v3"
    policy_version: Literal["autonomous_evidence_policy_v3"] = "autonomous_evidence_policy_v3"
    state: Literal["evaluated"] = "evaluated"
    mode: Literal["internal_only"] = "internal_only"
    publication_enabled: Literal[False] = False
    binding: CandidateBindingV2
    disposition: Literal["blocked", "evidence_pending", "quarantine", "eligible_internal"]
    safe_reasons: tuple[Identifier, ...] = Field(min_length=1, max_length=32)
    bundle_hashes: tuple[Digest, ...] = Field(default=(), max_length=2)
    evidence_hash: Digest | None = None
    correlation_limited: bool = False
    diagnostic_warnings: tuple[Literal["blind_solution_incorrect"], ...] = Field(default=(), max_length=1)

    @property
    def evaluation_hash(self) -> str:
        return canonical_hash(checked_model(self, AdmissionEvaluationV3).model_dump(mode="json"))

    @property
    def receipt_hash(self) -> str:
        return self.evaluation_hash


EvidencePolicy = AutonomousEvidencePolicyV2 | AutonomousEvidencePolicyV3
ReviewBundle = ReviewBundleV2 | ReviewBundleV3
AdmissionEvaluation = AdmissionEvaluationV2 | AdmissionEvaluationV3
AdmissionEvaluationField = Annotated[AdmissionEvaluation, Field(discriminator="schema_version")]


def policy_for_hash(digest: str) -> EvidencePolicy:
    for policy in (AutonomousEvidencePolicyV2(), AutonomousEvidencePolicyV3()):
        if digest == policy.policy_hash:
            return policy
    raise ValueError("unknown autonomous evidence policy")


def checked_policy(policy: EvidencePolicy) -> EvidencePolicy:
    if type(policy) is AutonomousEvidencePolicyV3:
        return checked_model(policy, AutonomousEvidencePolicyV3)
    return checked_model(policy, AutonomousEvidencePolicyV2)


def checked_bundle(bundle: ReviewBundle) -> ReviewBundle:
    if type(bundle) is ReviewBundleV3:
        return checked_model(bundle, ReviewBundleV3)
    return checked_model(bundle, ReviewBundleV2)


def parse_bundle(raw: Any) -> ReviewBundle:
    kind = ReviewBundleV3 if raw.get("schema_version") == "item_supply_review_bundle_v3" else ReviewBundleV2
    return kind.model_validate_json(json.dumps(raw))


def completed_blind_allowed(blind: BlindSolveReceiptV2, policy: EvidencePolicy) -> bool:
    policy = checked_policy(policy)
    blind = checked_model(blind, BlindSolveReceiptV2)
    return (blind.binding.policy_hash == policy.policy_hash
            and (blind.score.passed or type(policy) is AutonomousEvidencePolicyV3))


def diagnostic_warnings(evaluation: AdmissionEvaluation) -> tuple[str, ...]:
    if type(evaluation) is AdmissionEvaluationV3:
        return checked_model(evaluation, AdmissionEvaluationV3).diagnostic_warnings
    checked_model(evaluation, AdmissionEvaluationV2)
    return ()


class SharedGenerationPolicyBindingV3(StorageContract):
    """Frozen BEFORE first author IO on the existing canonical budget root."""
    schema_version: Literal["shared_generation_policy_binding_v3"] = "shared_generation_policy_binding_v3"
    policy: AutonomousEvidencePolicyV3
    root_id: UUID
    job_id: UUID
    candidate_id: UUID
    request_hash: Digest
    blueprint_hash: Digest
    profile_hash: Digest
    lease_generation: int = Field(ge=1)

    @property
    def binding_hash(self) -> str:
        return canonical_hash(checked_model(self, SharedGenerationPolicyBindingV3).model_dump(mode="json"))
