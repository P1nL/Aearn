"""Strict trusted-caller pack projections. None of these DTOs issues authority.

The live integration owner must resolve every referenced persisted receipt and
current source/runtime/exposure fence. Offline construction is not ready_exact.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.contracts import (
    AssessmentSupplyDemandV1, CandidateAuthorityV1, CoverageBlueprintV1, Digest,
    Identifier, ObjectiveCoverageProofV1, Slot, SupplyContract, SupplyScopeV1, ClauseCoverageV1,
    SourceAuthorizationFactsV1, Usage, Version, require_aware,
)
from app.services.learning.item_supply.finite_targets.contracts import TargetId
from app.services.learning.item_supply.storage_contracts import StorageContract, checked_model
from app.services.learning.item_supply.type_evidence import (
    ContentIdentityV2, ContentRelationshipEvidenceV2, TypeAssessmentEvidenceV2,
)

NativeHandle = Annotated[str, Field(pattern=r"^(li:[0-9a-f]{64}|lip:v2:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$")]


class NativeProofV1(ObjectiveCoverageProofV1):
    item_handle: NativeHandle

    @property
    def proof_hash(self) -> str:
        return canonical_hash(checked_model(self, NativeProofV1).model_dump(mode="json"))


class NativeCandidateV1(CandidateAuthorityV1):
    item_handle: NativeHandle
    proof: NativeProofV1 | None = None

    @model_validator(mode="after")
    def native_namespace(self) -> NativeCandidateV1:
        if self.item_handle.startswith("lip:") != (self.visibility == "private"):
            raise ValueError("pack native handle namespace mismatch")
        return self


class AuthorizedSubDemandV1(StorageContract):
    slot: Slot
    storage_scope_id: UUID
    demand: AssessmentSupplyDemandV1
    blueprint: CoverageBlueprintV1
    mapping_receipt_hash: Digest


class PackRequestV1(StorageContract):
    target_id: TargetId
    target_definition_hash: Digest
    learner_id: UUID
    epoch: int = Field(ge=1)
    track_id: UUID
    revision_id: UUID
    node_id: UUID
    storage_scope_id: UUID
    course_mapping_hash: Digest
    # Ordered exact T clause-definition -> actual P1 clause identity mapping.
    clause_mapping: tuple[tuple[str, Digest, Identifier, Digest], ...] = Field(min_length=3, max_length=3)
    demands: tuple[AuthorizedSubDemandV1, ...] = Field(min_length=3, max_length=3)

    @property
    def request_hash(self) -> str:
        return canonical_hash(checked_model(self, PackRequestV1).model_dump(mode="json"))


class FamilyMemberEvidenceV1(StorageContract):
    family_id: Identifier
    family_definition_hash: Digest
    allocation_variant_id: Identifier
    allocation_definition_hash: Digest
    allocation_receipt_hash: Digest
    target_definition_hash: Digest
    actual_public_task_hash: Digest
    actual_fixture_hash: Digest
    semantic_signature: Digest
    course_mapping_hash: Digest
    candidate_content_hash: Digest
    receipt_hash: Digest


class _FamilyTransferWitness(StorageContract):
    source_family_id: Identifier
    target_family_id: Identifier
    source_submission_hash: Digest
    adapted_submission_hash: Digest
    source_fixture_hash: Digest
    target_fixture_hash: Digest
    outcome: Literal["successful_semantic_mismatch"]


class ExecutedFamilyTransferWitnessV1(_FamilyTransferWitness):
    evidence_kind: Literal["sealed_code_execution"] = "sealed_code_execution"
    source_terminal_receipt_hash: Digest
    source_scorer_receipt_hash: Digest
    terminal_receipt_hash: Digest
    scorer_receipt_hash: Digest


class StaticFamilyTransferWitnessV1(_FamilyTransferWitness):
    # Static KC must not fabricate runner/OS terminal fields.
    evidence_kind: Literal["static_response_counterexample"] = "static_response_counterexample"
    source_response_verification_hash: Digest
    target_response_verification_hash: Digest
    truth_derivation_hash: Digest


FamilyTransferWitnessV1 = Annotated[
    ExecutedFamilyTransferWitnessV1 | StaticFamilyTransferWitnessV1,
    Field(discriminator="evidence_kind"),
]


class FamilyPairEvidenceV1(StorageContract):
    left_family_id: Identifier
    right_family_id: Identifier
    left_semantic_signature: Digest
    right_semantic_signature: Digest
    course_mapping_hash: Digest
    relation: Literal["independent", "conflict"]
    witnesses: tuple[FamilyTransferWitnessV1, ...] = Field(min_length=2, max_length=2)
    review_receipts: tuple[tuple[Literal["curriculum", "technical", "ambiguity", "adversarial"], Digest], ...] = Field(min_length=4, max_length=4)
    receipt_hash: Digest
    checked_at: datetime
    valid_until: datetime

    @model_validator(mode="after")
    def current_interval(self) -> FamilyPairEvidenceV1:
        require_aware(self.checked_at)
        require_aware(self.valid_until)
        if self.valid_until <= self.checked_at:
            raise ValueError("invalid family pair observation")
        return self


class PackCandidateV1(StorageContract):
    candidate: NativeCandidateV1
    member: FamilyMemberEvidenceV1
    publication_id: UUID
    materialization_id: UUID
    proof_id: UUID
    version_id: UUID
    owner_id: UUID | None
    epoch: int | None = Field(default=None, ge=1)
    storage_scope_id: UUID
    original_publication_hash: Digest
    original_materialization_hash: Digest
    original_proof_hash: Digest
    complete_source_set_hash: Digest
    runtime_or_static_observation_hash: Digest
    observed_at: datetime
    valid_until: datetime

    @model_validator(mode="after")
    def observed_interval(self) -> PackCandidateV1:
        require_aware(self.observed_at)
        require_aware(self.valid_until)
        if self.valid_until <= self.observed_at:
            raise ValueError("invalid pack candidate observation")
        return self


class NativeExposureV1(StorageContract):
    event_id: UUID
    item_handle: NativeHandle
    content_hash: Digest
    family_id: Identifier
    semantic_signature: Digest
    kind: Literal["shown", "hint", "direct_answer", "attempted", "transfer"]


class CompleteExposureV1(StorageContract):
    learner_id: UUID
    epoch: int = Field(ge=1)
    collector_version: Identifier
    watermark: int = Field(ge=0)
    completeness_receipt_hash: Digest
    observed_at: datetime
    valid_until: datetime
    records: tuple[NativeExposureV1, ...] = Field(default=(), max_length=4096)

    @model_validator(mode="after")
    def current_complete_observation(self) -> CompleteExposureV1:
        require_aware(self.observed_at)
        require_aware(self.valid_until)
        if self.valid_until <= self.observed_at or len({r.event_id for r in self.records}) != len(self.records):
            raise ValueError("invalid complete exposure observation")
        return self


class PackInputsV1(StorageContract):
    request: PackRequestV1
    candidates: tuple[PackCandidateV1, ...] = Field(max_length=16)
    family_pairs: tuple[FamilyPairEvidenceV1, ...] = Field(max_length=6)
    exposure: CompleteExposureV1 | None = None

    @property
    def inputs_hash(self) -> str:
        return canonical_hash(checked_model(self, PackInputsV1).model_dump(mode="json"))


class PackSnapshotV1(StorageContract):
    request: PackRequestV1
    inputs_hash: Digest
    selected: tuple[PackCandidateV1, ...] = Field(min_length=5, max_length=5)
    family_pair_receipt_hashes: tuple[Digest, ...] = Field(min_length=6, max_length=6)
    exposure_receipt_hash: Digest
    exposure_watermark: int = Field(ge=0)
    checked_at: datetime
    valid_until: datetime
    authority_status: Literal["trusted_caller_computation_only"] = "trusted_caller_computation_only"

    @model_validator(mode="after")
    def exact_snapshot(self) -> PackSnapshotV1:
        require_aware(self.checked_at)
        require_aware(self.valid_until)
        if self.valid_until <= self.checked_at or len({r.candidate.item_handle for r in self.selected}) != 5:
            raise ValueError("invalid computed pack snapshot")
        return self

    @property
    def snapshot_hash(self) -> str:
        return canonical_hash(checked_model(self, PackSnapshotV1).model_dump(mode="json"))


class PackResultV1(StorageContract):
    status: Literal["complete", "gap", "stale"]
    request_hash: Digest
    snapshot: PackSnapshotV1 | None = None
    reasons: tuple[Identifier, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def coherent(self) -> PackResultV1:
        if (self.status == "complete") != (self.snapshot is not None) or (self.status == "complete" and self.reasons):
            raise ValueError("invalid computed pack result")
        return self


class CrossPoolMappingV1(StorageContract):
    base_request_hash: Digest
    enhancement_request_hash: Digest
    mapping_receipt_hash: Digest
    checked_at: datetime
    valid_until: datetime

    @model_validator(mode="after")
    def mapping_interval(self) -> CrossPoolMappingV1:
        require_aware(self.checked_at)
        require_aware(self.valid_until)
        if self.valid_until <= self.checked_at:
            raise ValueError("invalid cross-pool mapping interval")
        return self


class PackSelectionV1(StorageContract):
    status: Literal["computed_base", "computed_enhancement", "unavailable"]
    pack: PackSnapshotV1 | None = None
    reasons: tuple[Identifier, ...] = Field(default=(), max_length=32)
    authority_status: Literal["trusted_caller_computation_only"] = "trusted_caller_computation_only"
    cross_pool_mapping_hash: Digest | None = None
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def selection_shape(self) -> PackSelectionV1:
        if (self.status == "unavailable") != (self.pack is None):
            raise ValueError("invalid pack selection")
        if self.pack is not None:
            if self.valid_until is None or self.valid_until > self.pack.valid_until:
                raise ValueError("invalid selection validity")
            require_aware(self.valid_until)
        if self.status == "computed_enhancement" and self.cross_pool_mapping_hash is None:
            raise ValueError("enhancement mapping required")
        return self


class FamilyMemberEvidenceV2(FamilyMemberEvidenceV1):
    """Explicit flexible allocation; never reinterpret the V1 initial registry."""
    # Inherited semantic_signature can be coarse/legacy family identity. V2
    # clone/relation decisions use type_evidence.content.decision_signature.
    schema_version: Literal["family_member_evidence_v2"] = "family_member_evidence_v2"
    slot: Slot
    purpose: Literal["knowledge_check", "exercise", "remediation"]


class NativeScopedProofV2(NativeProofV1):
    """Shared immutable item proof in a private, exact frozen learning context."""
    context_schema_version: Literal["native_scoped_objective_coverage_v2"] = "native_scoped_objective_coverage_v2"
    mapping_receipt_id: UUID
    learner_id: UUID
    epoch: int = Field(ge=1)
    storage_scope_id: UUID
    course_mapping_hash: Digest

    @property
    def proof_hash(self) -> str:
        return canonical_hash(checked_model(self, NativeScopedProofV2).model_dump(mode="json"))


class NativeScopedCandidateV2(SupplyContract):
    """Content remains public; consumer scope/receipt remains private.

    Separate explicit version, never a weakened V1 namespace/owner validator.
    These projections are trusted computations, NOT reservation capabilities.
    """
    schema_version: Literal["native_scoped_candidate_v2"] = "native_scoped_candidate_v2"
    scope: SupplyScopeV1
    item_handle: NativeHandle
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
    visibility: Literal["public"] = "public"
    owner_ref: None = None
    proof: NativeScopedProofV2
    current_authorization: SourceAuthorizationFactsV1
    published: bool = False
    materialized: bool = False
    runtime_available: bool = False
    available_capabilities: tuple[Identifier, ...] = Field(default=(), max_length=24)
    mapping_receipt_id: UUID
    learner_id: UUID
    epoch: int = Field(ge=1)
    storage_scope_id: UUID
    course_mapping_hash: Digest

    @model_validator(mode="after")
    def shared_item_private_context(self) -> NativeScopedCandidateV2:
        p = self.proof
        if (not self.item_handle.startswith("li:") or self.scope.visibility != "private"
                or self.scope.owner_ref != "user:" + str(self.learner_id)
                or p.scope_hash != self.scope.scope_hash or p.item_handle != self.item_handle
                or p.content_hash != self.content_hash
                or (p.mapping_receipt_id, p.learner_id, p.epoch, p.storage_scope_id, p.course_mapping_hash)
                != (self.mapping_receipt_id, self.learner_id, self.epoch, self.storage_scope_id, self.course_mapping_hash)
                or len({c.clause_id for c in self.clauses}) != len(self.clauses)
                or len(set(self.available_capabilities)) != len(self.available_capabilities)):
            raise ValueError("native_shared_item_private_context_mismatch")
        return self


class PackCandidateV2(StorageContract):
    schema_version: Literal["pack_candidate_v2"] = "pack_candidate_v2"
    candidate: NativeCandidateV1 | NativeScopedCandidateV2
    member: FamilyMemberEvidenceV2
    type_evidence: TypeAssessmentEvidenceV2
    publication_id: UUID
    materialization_id: UUID
    proof_id: UUID
    version_id: UUID
    owner_id: UUID | None
    epoch: int | None = Field(default=None, ge=1)
    storage_scope_id: UUID
    original_publication_hash: Digest
    original_materialization_hash: Digest
    original_proof_hash: Digest
    complete_source_set_hash: Digest
    runtime_or_static_observation_hash: Digest
    observed_at: datetime
    valid_until: datetime

    @model_validator(mode="after")
    def observed_interval(self) -> PackCandidateV2:
        require_aware(self.observed_at)
        require_aware(self.valid_until)
        if self.valid_until <= self.observed_at:
            raise ValueError("invalid pack candidate observation")
        return self


class NativeExposureV2(NativeExposureV1):
    content: ContentIdentityV2

    @model_validator(mode="after")
    def actual_exposed_content(self) -> NativeExposureV2:
        if (self.item_handle, self.content_hash) != (
                self.content.item_handle, self.content.content_hash):
            raise ValueError("exposure actual content mismatch")
        return self


class CompleteExposureV2(CompleteExposureV1):
    schema_version: Literal["complete_exposure_v2"] = "complete_exposure_v2"
    records: tuple[NativeExposureV2, ...] = Field(default=(), max_length=4096)


class PackInputsV2(StorageContract):
    schema_version: Literal["pack_inputs_v2"] = "pack_inputs_v2"
    request: PackRequestV1
    candidates: tuple[PackCandidateV2, ...] = Field(max_length=16)
    # Every candidate pair plus two assessments against 4096 exposures.
    relationships: tuple[ContentRelationshipEvidenceV2, ...] = Field(default=(), max_length=8312)
    exposure: CompleteExposureV2 | None = None
    # Optional historical method; cannot replace actual V2 content relationships.
    legacy_family_pairs: tuple[FamilyPairEvidenceV1, ...] = Field(default=(), max_length=6)

    @property
    def inputs_hash(self) -> str:
        return canonical_hash(checked_model(self, PackInputsV2).model_dump(mode="json"))


class PackSnapshotV2(StorageContract):
    schema_version: Literal["pack_snapshot_v2"] = "pack_snapshot_v2"
    request: PackRequestV1
    inputs_hash: Digest
    selected: tuple[PackCandidateV2, ...] = Field(min_length=5, max_length=5)
    relationship_receipt_hashes: tuple[Digest, ...] = Field(min_length=7, max_length=8199)
    type_evidence_receipt_hashes: tuple[Digest, ...] = Field(min_length=5, max_length=5)
    exposure_receipt_hash: Digest
    exposure_watermark: int = Field(ge=0)
    checked_at: datetime
    valid_until: datetime
    authority_status: Literal["trusted_caller_computation_only"] = "trusted_caller_computation_only"

    @model_validator(mode="after")
    def exact_snapshot(self) -> PackSnapshotV2:
        require_aware(self.checked_at)
        require_aware(self.valid_until)
        if (self.valid_until <= self.checked_at
                or len({r.candidate.item_handle for r in self.selected}) != 5
                or len({r.candidate.content_hash for r in self.selected}) != 5):
            raise ValueError("invalid computed V2 pack snapshot")
        return self

    @property
    def snapshot_hash(self) -> str:
        return canonical_hash(checked_model(self, PackSnapshotV2).model_dump(mode="json"))


class PackResultV2(StorageContract):
    schema_version: Literal["pack_result_v2"] = "pack_result_v2"
    status: Literal["complete", "gap", "stale"]
    request_hash: Digest
    snapshot: PackSnapshotV2 | None = None
    reasons: tuple[Identifier, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def coherent(self) -> PackResultV2:
        if (self.status == "complete") != (self.snapshot is not None) or (self.status == "complete" and self.reasons):
            raise ValueError("invalid computed V2 pack result")
        return self


class PackSelectionV2(StorageContract):
    schema_version: Literal["pack_selection_v2"] = "pack_selection_v2"
    status: Literal["computed_base", "computed_enhancement", "unavailable"]
    pack: PackSnapshotV2 | None = None
    reasons: tuple[Identifier, ...] = Field(default=(), max_length=32)
    authority_status: Literal["trusted_caller_computation_only"] = "trusted_caller_computation_only"
    cross_pool_mapping_hash: Digest | None = None
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def selection_shape(self) -> PackSelectionV2:
        if (self.status == "unavailable") != (self.pack is None):
            raise ValueError("invalid V2 pack selection")
        if self.pack is not None:
            if self.valid_until is None or self.valid_until > self.pack.valid_until:
                raise ValueError("invalid V2 selection validity")
            require_aware(self.valid_until)
        if self.status == "computed_enhancement" and self.cross_pool_mapping_hash is None:
            raise ValueError("enhancement mapping required")
        return self
