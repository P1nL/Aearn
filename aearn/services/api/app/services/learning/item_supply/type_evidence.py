"""Three finite type profiles and content-specific relation projections.

Strict trusted-caller computations, NOT issuers or signature verifiers. A live
owner must resolve immutable native validation, execution, item-review and
relationship receipts and current fences before constructing these objects.
Hashes, role names and caller verdicts alone grant no authority.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.contracts import Digest, Identifier, Version, require_aware
from app.services.learning.item_supply.storage_contracts import StorageContract, checked_model

TYPE_EVIDENCE_POLICY_V2 = "item_supply_type_evidence_v2"
TypeProfileV2 = Literal["kc", "python", "sqlite"]
RelationshipRoleV2 = Literal["curriculum", "technical", "ambiguity", "adversarial"]
RELATIONSHIP_ROLES_V2 = frozenset(("curriculum", "technical", "ambiguity", "adversarial"))
ContentHandleV2 = Annotated[str, Field(pattern=r"^(li:[0-9a-f]{64}|lip:v2:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$")]


class ContentIdentityV2(StorageContract):
    """Trusted producer fingerprints of actual immutable decision/leakage content.

    decision_signature is content-specific, never a legacy family definition or
    seed/prose hash. answer_leakage_signature is a contextual semantic fingerprint
    of the solution/answer leakage relation, NOT the raw option letter, integer
    output or other coincidentally equal answer. This DTO validates shape only:
    the live resolver must verify the native producer and underlying content.
    """
    item_handle: ContentHandleV2
    version_id: UUID
    content_hash: Digest
    actual_public_task_hash: Digest
    actual_fixture_hash: Digest
    decision_signature: Digest
    answer_leakage_signature: Digest
    author_id: UUID


def assessment_clone(left: ContentIdentityV2, right: ContentIdentityV2) -> bool:
    # Family/fixture equality is NOT clone evidence: one supported method/schema
    # can pose genuinely different goal assessments.
    return any(getattr(left, name) == getattr(right, name) for name in (
        "item_handle", "content_hash", "actual_public_task_hash", "decision_signature", "answer_leakage_signature",
    ))


class _TypeEvidenceV2(StorageContract):
    policy_version: Literal["item_supply_type_evidence_v2"] = "item_supply_type_evidence_v2"
    content: ContentIdentityV2
    scope_hash: Digest
    objective_hash: Digest
    target_definition_hash: Digest
    course_mapping_hash: Digest
    runtime_profile_id: Identifier
    runtime_profile_hash: Digest
    scorer_version: Version
    assistance_policy_hash: Digest
    validation_receipt_hash: Digest
    item_review_bundle_hash: Digest
    receipt_id: UUID
    receipt_hash: Digest
    checked_at: datetime
    valid_until: datetime

    @model_validator(mode="after")
    def interval(self) -> _TypeEvidenceV2:
        require_aware(self.checked_at)
        require_aware(self.valid_until)
        if self.valid_until <= self.checked_at:
            raise ValueError("invalid type evidence interval")
        return self


class KCTypeEvidenceV2(_TypeEvidenceV2):
    profile: Literal["kc"] = "kc"
    truth_derivation_hash: Digest
    all_options_verification_hash: Digest
    blind_solve_receipt_hash: Digest
    ambiguity_review_receipt_hash: Digest
    misconception_review_receipt_hash: Digest


class _ExecutionTypeEvidenceV2(_TypeEvidenceV2):
    terminal_receipt_hash: Digest
    scorer_receipt_hash: Digest
    reference_submission_hash: Digest
    equivalent_submission_hash: Digest
    reference_execution_hash: Digest
    equivalent_execution_hash: Digest
    wrong_solution_control_hash: Digest
    hardcoded_control_hash: Digest
    boundary_control_hash: Digest

    @model_validator(mode="after")
    def different_equivalent_submission(self) -> _ExecutionTypeEvidenceV2:
        if (self.reference_submission_hash == self.equivalent_submission_hash
                or self.reference_execution_hash == self.equivalent_execution_hash):
            raise ValueError("different equivalent solution evidence required")
        return self


class PythonTypeEvidenceV2(_ExecutionTypeEvidenceV2):
    profile: Literal["python"] = "python"


class SQLiteTypeEvidenceV2(_ExecutionTypeEvidenceV2):
    profile: Literal["sqlite"] = "sqlite"


TypeAssessmentEvidenceV2 = Annotated[
    KCTypeEvidenceV2 | PythonTypeEvidenceV2 | SQLiteTypeEvidenceV2,
    Field(discriminator="profile"),
]


class RelationshipReviewV2(StorageContract):
    role: RelationshipRoleV2
    actor_id: UUID
    receipt_id: UUID
    receipt_hash: Digest
    # One immutable native batch may cover many exact content-pair judgments.
    covered_binding_hashes: tuple[Digest, ...] = Field(min_length=1, max_length=8312)
    conclusion: Literal["nonredundant", "conflict", "uncertain"]
    rationale_evidence_hash: Digest
    checked_at: datetime
    valid_until: datetime

    @model_validator(mode="after")
    def interval(self) -> RelationshipReviewV2:
        require_aware(self.checked_at)
        require_aware(self.valid_until)
        if self.valid_until <= self.checked_at:
            raise ValueError("invalid relationship review interval")
        return self


class ContentRelationshipEvidenceV2(StorageContract):
    """Current eligibility envelope around unchanged native content reviews.

    receipt_id/hash name the persisted stable relation/batch. Exposure fields are
    fresh server-resolved eligibility facts, deliberately outside reviewed binding.
    They are not persisted-review mutations or authority to renew review validity.
    """
    policy_version: Literal["item_supply_type_evidence_v2"] = "item_supply_type_evidence_v2"
    profile: TypeProfileV2
    # Exact objective, course/node/revision, owner/epoch and all sub-scopes.
    request_hash: Digest
    left: ContentIdentityV2
    right: ContentIdentityV2
    exposure_receipt_hash: Digest
    exposure_watermark: int = Field(ge=0)
    reviews: tuple[RelationshipReviewV2, ...] = Field(min_length=4, max_length=4)
    receipt_id: UUID
    receipt_hash: Digest
    checked_at: datetime
    valid_until: datetime

    @model_validator(mode="after")
    def interval(self) -> ContentRelationshipEvidenceV2:
        require_aware(self.checked_at)
        require_aware(self.valid_until)
        if self.valid_until <= self.checked_at:
            raise ValueError("invalid relationship interval")
        return self

    @property
    def binding_hash(self) -> str:
        value = checked_model(self, ContentRelationshipEvidenceV2)
        return relationship_binding_hash(profile=value.profile, request_hash=value.request_hash,
            left=value.left, right=value.right)


def relationship_binding_hash(*, profile: TypeProfileV2, request_hash: str,
                              left: ContentIdentityV2, right: ContentIdentityV2) -> str:
    """Stable content/objective/profile review binding, not exposure freshness.

    The outer eligibility projection binds the current complete exposure receipt
    and watermark separately. A fresh projection may reuse unmodified still-valid
    native review receipts; it never extends/re-signs their original intervals.
    """
    contents = sorted((checked_model(left, ContentIdentityV2).model_dump(mode="json"),
                       checked_model(right, ContentIdentityV2).model_dump(mode="json")),
                      key=canonical_hash)
    return canonical_hash(dict(policy_version=TYPE_EVIDENCE_POLICY_V2, profile=profile,
        request_hash=request_hash, contents=contents))


def relationship_reason(evidence: ContentRelationshipEvidenceV2, *, now: datetime) -> str | None:
    """Validate projections only; verdicts are not live attestations."""
    evidence = checked_model(evidence, ContentRelationshipEvidenceV2)
    require_aware(now)
    if not evidence.checked_at <= now < evidence.valid_until:
        return "relationship_stale"
    reviews = evidence.reviews
    if ({r.role for r in reviews} != RELATIONSHIP_ROLES_V2
            or len({r.actor_id for r in reviews}) != 4
            or len({r.receipt_id for r in reviews}) != 4
            or len({r.receipt_hash for r in reviews}) != 4
            or evidence.receipt_id in {r.receipt_id for r in reviews}
            or any(r.actor_id in {evidence.left.author_id, evidence.right.author_id} for r in reviews)):
        return "relationship_review_independence_missing"
    binding = evidence.binding_hash
    if any(binding not in r.covered_binding_hashes for r in reviews):
        return "relationship_review_binding_mismatch"
    if any(not r.checked_at <= now < r.valid_until for r in reviews):
        return "relationship_stale"
    if any(r.conclusion != "nonredundant" for r in reviews):
        return "relationship_conflict_or_uncertain"
    if assessment_clone(evidence.left, evidence.right):
        return "assessment_clone"
    return None
