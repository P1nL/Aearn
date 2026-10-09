"""Private finite transfer PLANS; none of these DTOs is a pack witness or verdict."""
from __future__ import annotations

from typing import Literal

from aearn_shared.execution import SandboxInputV1
from pydantic import Field, model_validator

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1
from app.services.learning.item_supply.finite_targets.contracts import Digest, TargetId
from app.services.learning.item_supply.storage_contracts import StorageContract, checked_model


class FiniteTransferCheckV1(StorageContract):
    """Expected facts for a later funded verifier, never an issued terminal."""
    kind: Literal["python", "sqlite", "static_proposition"]
    purpose: Literal["reference_success", "transfer_semantic_mismatch"]
    family_id: str
    specification_hash: Digest
    blueprint_version: str
    public_task_json: str = Field(min_length=2, max_length=32000)
    public_task_hash: Digest
    fixture_hash: Digest
    submission: str = Field(min_length=1, max_length=16000, repr=False)
    request: SandboxInputV1 | None = Field(repr=False)
    runtime_lock_hash: Digest | None
    scorer_version: str
    expected_json: str = Field(min_length=2, max_length=48000, repr=False)
    required_terminal: Literal["successful_supported_semantics", "not_run_static"]
    status: Literal["not_performed"] = "not_performed"

    @model_validator(mode="after")
    def execution_shape(self) -> FiniteTransferCheckV1:
        if self.kind == "static_proposition":
            if self.request is not None or self.runtime_lock_hash is not None or self.required_terminal != "not_run_static":
                raise ValueError("static_transfer_must_not_invent_execution")
        elif (self.request is None or self.request.submission != self.submission
              or self.runtime_lock_hash in (None, "0" * 64)
              or self.required_terminal != "successful_supported_semantics"):
            raise ValueError("finite_transfer_runtime_plan_missing")
        return self

    @property
    def check_hash(self) -> str:
        return canonical_hash(checked_model(self, FiniteTransferCheckV1).model_dump(mode="json"))


class FiniteTransferAlignmentV1(StorageContract):
    rule: Literal["injective_names_and_declared_literals", "injective_typed_column_roles", "complete_option_propositions"]
    symbol_pairs: tuple[tuple[str, str], ...] = Field(max_length=8)
    # Source parameter, target parameter (or unchanged), original literal, adapted literal.
    constant_pairs: tuple[tuple[str, str, int, int], ...] = Field(max_length=4)
    unchanged_structure_hash: Digest | None
    reasoning_steps: Literal["no_steps_added_removed_or_reordered"] = "no_steps_added_removed_or_reordered"


class FiniteFamilyTransferDirectionV1(StorageContract):
    source_family_id: str
    target_family_id: str
    source_definition_hash: Digest
    target_definition_hash: Digest
    source_structure_signature: Digest
    target_structure_signature: Digest
    source_reference: FiniteTransferCheckV1
    target_reference: FiniteTransferCheckV1
    alignment: FiniteTransferAlignmentV1
    adapted_submission: str | None = Field(repr=False)
    transfer_check: FiniteTransferCheckV1 | None = Field(repr=False)
    # Independent closed arithmetic/relational predictions, NOT execution evidence.
    semantic_difference_json: str | None = Field(default=None, max_length=48000, repr=False)
    construction: Literal["planned", "unresolved", "conflict"]
    reasons: tuple[str, ...] = Field(min_length=1, max_length=8)
    execution_status: Literal["not_performed"] = "not_performed"
    review_status: Literal["four_role_reviews_pending"] = "four_role_reviews_pending"

    @model_validator(mode="after")
    def no_unproven_witness(self) -> FiniteFamilyTransferDirectionV1:
        if (self.source_family_id == self.target_family_id
                or self.source_reference.family_id != self.source_family_id
                or self.target_reference.family_id != self.target_family_id):
            raise ValueError("finite_transfer_direction_identity")
        if self.construction == "planned":
            if (self.adapted_submission is None or self.transfer_check is None
                    or self.transfer_check.submission != self.adapted_submission
                    or self.transfer_check.family_id != self.target_family_id
                    or self.transfer_check.public_task_hash != self.target_reference.public_task_hash
                    or self.semantic_difference_json is None):
                raise ValueError("finite_transfer_prediction_missing")
        elif self.transfer_check is not None:
            raise ValueError("unresolved_transfer_cannot_schedule_negative")
        return self

    @property
    def inputs_hash(self) -> str:
        return canonical_hash(checked_model(self, FiniteFamilyTransferDirectionV1).model_dump(mode="json"))


class FiniteFamilyPairPlanV1(StorageContract):
    left_family_id: str
    right_family_id: str
    directions: tuple[FiniteFamilyTransferDirectionV1, FiniteFamilyTransferDirectionV1]
    construction: Literal["execution_and_review_pending", "unresolved", "conflict"]
    required_reviews: tuple[Literal["curriculum"], Literal["technical"], Literal["ambiguity"], Literal["adversarial"]] = (
        "curriculum", "technical", "ambiguity", "adversarial")

    @model_validator(mode="after")
    def two_directions(self) -> FiniteFamilyPairPlanV1:
        if tuple((d.source_family_id, d.target_family_id) for d in self.directions) != (
                (self.left_family_id, self.right_family_id), (self.right_family_id, self.left_family_id)):
            raise ValueError("finite_transfer_pair_requires_both_directions")
        expected = ("conflict" if any(d.construction == "conflict" for d in self.directions)
                    else "unresolved" if any(d.construction == "unresolved" for d in self.directions)
                    else "execution_and_review_pending")
        if self.construction != expected:
            raise ValueError("finite_transfer_pair_conclusion_unproven")
        return self


class FiniteFamilyTransferPlanV1(StorageContract):
    schema_version: Literal["finite_family_transfer_plan_v1"] = "finite_family_transfer_plan_v1"
    target_id: TargetId
    target_definition_hash: Digest
    runtime_lock_hash: Digest | None
    specifications: tuple[FiniteCandidateSpecV1, ...] = Field(min_length=4, max_length=4, repr=False)
    material_digests: tuple[Digest, ...] = Field(min_length=1, max_length=12)
    pairs: tuple[FiniteFamilyPairPlanV1, ...] = Field(min_length=6, max_length=6)
    binding_kind: Literal["exact_public_specs_private_reference_declarations"] = "exact_public_specs_private_reference_declarations"
    # In particular: not a generated LearningItemSource/current C/content proof.
    authority: Literal["not_family_pair_evidence"] = "not_family_pair_evidence"
    publication_enabled: Literal[False] = False

    @property
    def inputs_hash(self) -> str:
        return canonical_hash(checked_model(self, FiniteFamilyTransferPlanV1).model_dump(mode="json"))
