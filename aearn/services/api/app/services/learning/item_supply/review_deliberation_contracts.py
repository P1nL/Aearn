"""Private versioned dispute data. None of these DTOs is an admission capability."""
from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.services.learning.item_bank.contracts import LearningItemReviewRole, LearningItemSourceV1, canonical_hash
from app.services.learning.item_supply.contracts import Digest, Identifier
from app.services.learning.item_supply.diagnostic_policy import ReviewBundleV3
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.policies import ResourceAmounts
from app.services.learning.item_supply.review_contracts_v2 import (
    CandidateBindingV2, ReviewBundleV2, ReviewDiagnosticReferenceV1, ValidationReceiptV2, check_subject,
)
from app.services.learning.item_supply.storage_contracts import StorageContract, checked_model

BundleField = Annotated[ReviewBundleV2 | ReviewBundleV3, Field(discriminator="schema_version")]
DeliberationAction = Literal["investigate", "revise", "validate", "review"]


class DeliberationSubjectV1(StorageContract):
    source: LearningItemSourceV1 = Field(repr=False)
    binding: CandidateBindingV2

    @model_validator(mode="after")
    def exact_source(self) -> DeliberationSubjectV1:
        check_subject(self.source, self.binding)
        return self


class ReviewDisputeV1(StorageContract):
    """An exact original finding, not a merged majority vote or a new finding."""
    dispute_key: Digest
    role: LearningItemReviewRole
    report_hash: Digest
    run_id: UUID
    finding_index: int | None = Field(default=None, ge=0, le=23)
    finding_hash: Digest | None = None
    safe_code: Identifier
    references: tuple[ReviewDiagnosticReferenceV1, ...] = Field(default=(), max_length=6)

    @model_validator(mode="after")
    def finding_identity(self) -> ReviewDisputeV1:
        if (self.finding_index is None) != (self.finding_hash is None):
            raise ValueError("incomplete dispute finding identity")
        return self


class NeutralReviewRequirementV1(StorageContract):
    """Server test categories/locations only; no peer verdict, prose or blind answer."""
    check: Literal[
        "verify_deterministic_contract", "verify_security_boundary", "verify_unique_answer",
        "verify_public_scoring_consistency", "verify_public_private_boundary", "verify_adversarial_cases",
        "verify_technical_contract", "verify_objective_coverage", "verify_difficulty_contract",
        "verify_interpretations", "verify_source_claims", "verify_full_contract",
    ]
    pointers: tuple[str, ...] = Field(default=(), max_length=6)


class ReviewDeliberationPlanV1(StorageContract):
    schema_version: Literal["item_supply_review_deliberation_plan_v1"] = "item_supply_review_deliberation_plan_v1"
    visibility: Literal["private_only"] = "private_only"
    publication_enabled: Literal[False] = False
    admission_eligible: Literal[False] = False
    lease: JobLeaseV1
    budget_root_id: UUID
    resource_ceiling: ResourceAmounts
    subject: DeliberationSubjectV1
    validation: ValidationReceiptV2 = Field(repr=False)
    initial_bundle: BundleField = Field(repr=False)
    disputes: tuple[ReviewDisputeV1, ...] = Field(max_length=144)
    state: Literal["disputed_pending", "admission_pending"]

    @model_validator(mode="after")
    def binding_and_state(self) -> ReviewDeliberationPlanV1:
        if (self.lease.profile.profile_hash != self.subject.binding.profile_hash
                or self.initial_bundle.binding != self.subject.binding
                or bool(self.disputes) != (self.state == "disputed_pending")):
            raise ValueError("stale deliberation plan")
        check_subject(self.subject.source, self.subject.binding, self.validation)
        return self

    @property
    def plan_hash(self) -> str:
        return canonical_hash(checked_model(self, ReviewDeliberationPlanV1).model_dump(mode="json"))


class InvestigationRequestV1(StorageContract):
    schema_version: Literal["item_supply_live_investigation_request_v1"] = "item_supply_live_investigation_request_v1"
    purpose: Literal["bounded_live_dispute_investigation"] = "bounded_live_dispute_investigation"
    # This marker is NOT a grant. Original source/claim/lease owners recheck it.
    authority: Literal["original_owner_required"] = "original_owner_required"
    plan_hash: Digest
    round_number: int = Field(ge=2, le=64)
    subject: DeliberationSubjectV1
    bundle: BundleField = Field(repr=False)
    disputes: tuple[ReviewDisputeV1, ...] = Field(min_length=1, max_length=144)


class InvestigationEvidenceV1(StorageContract):
    schema_version: Literal["item_supply_live_investigation_evidence_v1"] = "item_supply_live_investigation_evidence_v1"
    request_hash: Digest
    binding: CandidateBindingV2
    evidence_version: Identifier
    # These hashes alone cannot pass original owner.verify_result.
    evidence_hashes: tuple[Digest, ...] = Field(min_length=1, max_length=32)
    addressed_disputes: tuple[Digest, ...] = Field(min_length=1, max_length=144)


class RevisionRequestV1(StorageContract):
    schema_version: Literal["item_supply_dispute_revision_request_v1"] = "item_supply_dispute_revision_request_v1"
    investigation: InvestigationRequestV1 = Field(repr=False)
    evidence: InvestigationEvidenceV1


class IndependentRecheckRequestV1(StorageContract):
    schema_version: Literal["item_supply_independent_recheck_request_v1"] = "item_supply_independent_recheck_request_v1"
    plan_hash: Digest
    round_number: int = Field(ge=2, le=64)
    subject: DeliberationSubjectV1
    requirements: tuple[NeutralReviewRequirementV1, ...] = Field(max_length=144)
    validation: ValidationReceiptV2 | None = Field(default=None, repr=False)
    # Deliberately no initial bundle, peer reports/verdicts or blind solution.


class DeliberationRoundV1(StorageContract):
    round_number: int = Field(ge=2, le=64)
    evidence: InvestigationEvidenceV1
    subject: DeliberationSubjectV1
    validation: ValidationReceiptV2 = Field(repr=False)
    bundle: BundleField = Field(repr=False)
    disputes: tuple[ReviewDisputeV1, ...] = Field(max_length=144)


class ReviewDeliberationResultV1(StorageContract):
    schema_version: Literal["item_supply_review_deliberation_result_v1"] = "item_supply_review_deliberation_result_v1"
    visibility: Literal["private_only"] = "private_only"
    publication_enabled: Literal[False] = False
    admission_eligible: Literal[False] = False
    plan: ReviewDeliberationPlanV1 = Field(repr=False)
    rounds: tuple[DeliberationRoundV1, ...] = Field(default=(), max_length=63, repr=False)
    state: Literal["disputed_pending", "admission_pending"]
    safe_reason: Identifier
    reserved_resources: ResourceAmounts
    usage_state: Literal["unknown", "not_called"]
