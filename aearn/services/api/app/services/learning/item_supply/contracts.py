"""Strict offline objective contracts, with no IO or trust issuance."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.grounding.autonomous.contracts import FrozenContract, Usage
from app.services.grounding.subject_registry import get_grounding_subject
from app.services.learning.item_bank.contracts import (
    LearningItemInteraction,
    LearningItemKind,
    LearningItemPurpose,
    canonical_hash,
)
from app.services.runners.language_capabilities import LANGUAGE_CAPABILITIES

Identifier = Annotated[str, Field(min_length=1, max_length=160, pattern=r"^[a-z0-9][a-z0-9._:-]*$")]
Version = Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]
Digest = Annotated[str, Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")]
ItemHandle = Annotated[str, Field(min_length=67, max_length=67, pattern=r"^li:[0-9a-f]{64}$")]
Slot = Literal["practice", "assessment", "remediation"]
Visibility = Literal["public", "private"]
SafeReason = Literal[
    "insufficient_coverage", "prerequisite_gap", "scope_mismatch", "identity_mismatch",
    "proof_missing", "proof_mismatch", "not_published", "not_materialized",
    "runtime_unavailable", "authorization_missing", "authorization_mismatch",
    "authorization_inactive", "stale", "private_owner_mismatch", "exposure_denied",
    "duplicate_candidate", "source_usage_denied", "capability_missing",
    "assessment_unsupported", "language_unsupported",
]
MAX_CANDIDATES = 256


def require_aware(value: datetime) -> datetime:
    if (type(value) is not datetime or value.year < 1970
            or value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("invalid aware time")
    return value


class SupplyContract(FrozenContract):
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="always", validate_default=True,
    )

    @model_validator(mode="after")
    def safe_scalars(self) -> SupplyContract:
        def check(value: object) -> None:
            if isinstance(value, str) and any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError("invalid contract scalar")
            if isinstance(value, tuple):
                for entry in value:
                    check(entry)
        for name in type(self).model_fields:
            check(getattr(self, name))
        return self


T = TypeVar("T", bound=SupplyContract)


def revalidate_contract(value: T, kind: type[T]) -> T:
    """Recheck copy/construct and reject hidden nested extra fields."""
    def inspect(node: object) -> None:
        if isinstance(node, BaseModel):
            if not isinstance(node, SupplyContract):
                raise ValueError("invalid contract type")
            if set(node.__dict__) - set(type(node).model_fields) or node.__pydantic_extra__:
                raise ValueError("invalid contract fields")
            for child in node.__dict__.values():
                inspect(child)
        elif isinstance(node, (tuple, list)):
            for child in node:
                inspect(child)
    try:
        if type(value) is not kind:
            raise ValueError("invalid contract type")
        inspect(value)
        # Validate the original instance: serializing first can discard subclass
        # fields under a base annotation and launder forbidden nested state.
        return kind.model_validate(value)
    except (ValueError, TypeError, AttributeError, RecursionError):
        raise ValueError("invalid supply contract") from None


def _validated_hash(value: T, kind: type[T]) -> str:
    try:
        checked = revalidate_contract(value, kind)
        return canonical_hash(checked.model_dump(mode="json"))
    except (ValueError, TypeError, AttributeError, OverflowError, RecursionError):
        raise ValueError("invalid supply contract") from None


class SupplyScopeV1(SupplyContract):
    schema_version: Literal["supply_scope_v1"] = "supply_scope_v1"
    course_family: Identifier
    course_version: Version
    knowledge_key: Identifier
    language_id: Identifier
    subject_id: Identifier
    subject_version: Version
    required_facets: tuple[Identifier, ...] = Field(min_length=1, max_length=24)
    dialect: Literal["sqlite"] | None = None
    runtime_profile_id: Identifier
    runtime_profile_hash: Digest
    item_kind: LearningItemKind
    purpose: LearningItemPurpose
    interaction: LearningItemInteraction
    required_capabilities: tuple[Identifier, ...] = Field(min_length=1, max_length=24)
    assessment_contract_version: Version
    scorer_version: Version
    assistance_policy_hash: Digest
    visibility: Visibility = "public"
    owner_ref: Identifier | None = None

    @model_validator(mode="after")
    def exact_scope(self) -> SupplyScopeV1:
        subject = get_grounding_subject(self.subject_id)
        if (self.language_id not in LANGUAGE_CAPABILITIES or subject is None
                or subject.subject_id != self.subject_id or self.language_id not in subject.language_ids):
            raise ValueError("invalid language subject scope")
        if (len(set(self.required_facets)) != len(self.required_facets)
                or set(self.required_facets) - set(subject.required_facets + subject.optional_facets)):
            raise ValueError("invalid subject facets")
        if ((self.language_id == "sql" and self.dialect != "sqlite")
                or (self.language_id != "sql" and self.dialect is not None)):
            raise ValueError("invalid dialect scope")
        if len(set(self.required_capabilities)) != len(self.required_capabilities):
            raise ValueError("duplicate capability")
        if (self.visibility == "public" and self.owner_ref is not None
                or self.visibility == "private" and self.owner_ref is None):
            raise ValueError("invalid owner scope")
        return self

    @property
    def scope_hash(self) -> str:
        return _validated_hash(self, SupplyScopeV1)


class ObjectiveClauseV1(SupplyContract):
    clause_id: Identifier
    clause_hash: Digest
    prerequisite_clause_ids: tuple[Identifier, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def unique_dependencies(self) -> ObjectiveClauseV1:
        if len(set(self.prerequisite_clause_ids)) != len(self.prerequisite_clause_ids):
            raise ValueError("duplicate prerequisite")
        return self


class MinimumCoverageV1(SupplyContract):
    policy_version: Literal["minimum_coverage_v1"] = "minimum_coverage_v1"
    practice: int = Field(default=2, ge=2, le=16)
    assessment: int = Field(default=2, ge=2, le=16)
    remediation: int = Field(default=1, ge=1, le=16)


class CoverageBlueprintV1(SupplyContract):
    schema_version: Literal["coverage_blueprint_v1"] = "coverage_blueprint_v1"
    scope: SupplyScopeV1
    objective_hash: Digest
    clauses: tuple[ObjectiveClauseV1, ...] = Field(min_length=1, max_length=64)
    minimum: MinimumCoverageV1 = Field(default_factory=MinimumCoverageV1)
    matrix_hash: Digest
    policy_version: Version

    @model_validator(mode="after")
    def valid_graph(self) -> CoverageBlueprintV1:
        # Structure is validated before sets and graph traversal.
        ids = {clause.clause_id for clause in self.clauses}
        if len(ids) != len(self.clauses):
            raise ValueError("duplicate clause")
        if any(set(clause.prerequisite_clause_ids) - ids for clause in self.clauses):
            raise ValueError("unknown prerequisite")
        pending = {clause.clause_id: set(clause.prerequisite_clause_ids) for clause in self.clauses}
        completed: set[str] = set()
        while pending:
            ready = {key for key, parents in pending.items() if parents <= completed}
            if not ready:
                raise ValueError("cyclic prerequisites")
            completed.update(ready)
            pending = {key: parents for key, parents in pending.items() if key not in ready}
        return self

    @property
    def blueprint_hash(self) -> str:
        return _validated_hash(self, CoverageBlueprintV1)


class AssessmentSupplyDemandV1(SupplyContract):
    schema_version: Literal["assessment_supply_demand_v1"] = "assessment_supply_demand_v1"
    demand_id: Identifier
    learner_ref: Identifier
    scope: SupplyScopeV1
    objective_hash: Digest
    blueprint_hash: Digest
    matrix_hash: Digest
    policy_version: Version
    input_revision: int = Field(ge=1, le=1_000_000)

    @property
    def demand_hash(self) -> str:
        return _validated_hash(self, AssessmentSupplyDemandV1)


class ClauseCoverageV1(SupplyContract):
    clause_id: Identifier
    clause_hash: Digest


class SourceAuthorizationFactsV1(SupplyContract):
    """Caller-resolved current facts, NOT a grant or cryptographic verifier."""
    authorization_hash: Digest
    source_ref: Identifier
    source_version: Version
    source_usage: Usage
    scope_hash: Digest
    objective_hash: Digest
    content_hash: Digest
    evidence_hash: Digest
    checked_at: datetime
    valid_until: datetime
    active: bool = False

    @model_validator(mode="after")
    def valid_times(self) -> SourceAuthorizationFactsV1:
        require_aware(self.checked_at)
        require_aware(self.valid_until)
        if self.valid_until <= self.checked_at:
            raise ValueError("invalid authorization interval")
        return self


class ObjectiveCoverageProofV1(SupplyContract):
    schema_version: Literal["objective_coverage_proof_v1"] = "objective_coverage_proof_v1"
    proof_id: Identifier
    blueprint_hash: Digest
    scope_hash: Digest
    objective_hash: Digest
    item_handle: ItemHandle
    content_hash: Digest
    clauses: tuple[ClauseCoverageV1, ...] = Field(min_length=1, max_length=64)
    slot: Slot
    candidate_family_id: Identifier
    matrix_hash: Digest
    policy_version: Version
    runtime_profile_id: Identifier
    runtime_profile_hash: Digest
    assessment_contract_version: Version
    scorer_version: Version
    assistance_policy_hash: Digest
    source_ref: Identifier
    source_version: Version
    source_usage: Usage
    evidence_hash: Digest
    authorization_hash: Digest
    authorization_checked_at: datetime
    authorization_valid_until: datetime
    issuer_version: Version
    checked_at: datetime
    valid_until: datetime

    @model_validator(mode="after")
    def valid_proof(self) -> ObjectiveCoverageProofV1:
        for value in (self.checked_at, self.valid_until, self.authorization_checked_at,
                      self.authorization_valid_until):
            require_aware(value)
        if (self.valid_until <= self.checked_at
                or self.authorization_valid_until <= self.authorization_checked_at):
            raise ValueError("invalid proof interval")
        if len({clause.clause_id for clause in self.clauses}) != len(self.clauses):
            raise ValueError("duplicate proof clause")
        return self

    @property
    def proof_hash(self) -> str:
        return _validated_hash(self, ObjectiveCoverageProofV1)


class CandidateAuthorityV1(SupplyContract):
    """Exact actual item coordinates plus trusted-caller facts; deny by default."""
    schema_version: Literal["candidate_authority_v1"] = "candidate_authority_v1"
    scope: SupplyScopeV1
    item_handle: ItemHandle
    content_hash: Digest
    candidate_family_id: Identifier
    objective_hash: Digest
    blueprint_hash: Digest
    matrix_hash: Digest
    policy_version: Version
    slot: Slot
    clauses: tuple[ClauseCoverageV1, ...] = Field(min_length=1, max_length=64)
    source_ref: Identifier
    source_version: Version
    source_usage: Usage
    evidence_hash: Digest
    visibility: Visibility
    owner_ref: Identifier | None = None
    proof: ObjectiveCoverageProofV1 | None = None
    current_authorization: SourceAuthorizationFactsV1 | None = None
    published: bool = False
    materialized: bool = False
    runtime_available: bool = False
    available_capabilities: tuple[Identifier, ...] = Field(default=(), max_length=24)

    @model_validator(mode="after")
    def valid_candidate(self) -> CandidateAuthorityV1:
        if len(set(self.available_capabilities)) != len(self.available_capabilities):
            raise ValueError("duplicate available capability")
        if self.visibility != self.scope.visibility or self.owner_ref != self.scope.owner_ref:
            raise ValueError("invalid candidate owner")
        if len({clause.clause_id for clause in self.clauses}) != len(self.clauses):
            raise ValueError("duplicate candidate clause")
        return self


class SupplyGapV1(SupplyContract):
    clause_id: Identifier
    slot: Slot
    required: int = Field(ge=1, le=16)
    available: int = Field(ge=0, le=16)
    reason: SafeReason

    @model_validator(mode="after")
    def actual_gap(self) -> SupplyGapV1:
        if self.available >= self.required:
            raise ValueError("invalid supply gap")
        return self


class AssessmentSupplyResultV1(SupplyContract):
    schema_version: Literal["assessment_supply_result_v1"] = "assessment_supply_result_v1"
    status: Literal["ready_exact", "gap", "pending", "failed", "stale"]
    demand_hash: Digest
    blueprint_hash: Digest
    selected_handles: tuple[ItemHandle, ...] = Field(default=(), max_length=MAX_CANDIDATES)
    gaps: tuple[SupplyGapV1, ...] = Field(default=(), max_length=192)
    reasons: tuple[SafeReason, ...] = Field(default=(), max_length=24)

    @model_validator(mode="after")
    def coherent_result(self) -> AssessmentSupplyResultV1:
        if len(set(self.selected_handles)) != len(self.selected_handles):
            raise ValueError("duplicate selected handle")
        if len(set(self.reasons)) != len(self.reasons):
            raise ValueError("duplicate reason")
        if self.status == "ready_exact" and self.gaps:
            raise ValueError("invalid ready result")
        return self
