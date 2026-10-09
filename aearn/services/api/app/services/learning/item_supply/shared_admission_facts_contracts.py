"""API-private native per-item facts; serialized audit is never an issuer capability."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.admission_facts_contracts import RunnerTerminalProofV1
from app.services.learning.item_supply.contracts import Digest
from app.services.learning.item_supply.finite_targets.contracts import TargetId
from app.services.learning.item_supply.finite_task_ambiguity import FiniteAmbiguityReceiptV1
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.policies import ResourceAmounts
from app.services.learning.item_supply.review_contracts_v2 import AdmissionEvidenceV2
from app.services.learning.item_supply.diagnostic_policy import AdmissionEvaluationField
from app.services.learning.item_supply.storage_contracts import StorageContract, checked_model


class SharedClauseProofV1(StorageContract):
    clause_id: str
    clause_hash: Digest
    interpretation_hash: Digest
    # All components of the closed scorer are conjunctive. These are actual
    # probe hashes (or complete static-option facts), not authored coverage tags.
    machine_proof_hashes: tuple[Digest, ...] = Field(min_length=1, max_length=32)
    curriculum_report_hash: Digest
    technical_report_hash: Digest
    ambiguity_report_hash: Digest


class SharedTargetProofV1(StorageContract):
    schema_version: Literal["shared_finite_target_proof_v1"] = "shared_finite_target_proof_v1"
    claim_scope: Literal["per_item_registered_target_not_inventory"] = "per_item_registered_target_not_inventory"
    target_id: TargetId
    target_definition_hash: Digest
    specification_hash: Digest
    source_hash: Digest
    public_task_hash: Digest
    instance_hash: Digest
    coverage_blueprint_hash: Digest
    inputs_hash: Digest
    validation_receipt_hash: Digest
    blind_receipt_hash: Digest
    ambiguity_receipt_hash: Digest
    mappings: tuple[SharedClauseProofV1, ...] = Field(min_length=3, max_length=3)
    publication_enabled: Literal[False] = False

    @property
    def proof_hash(self) -> str:
        return canonical_hash(checked_model(self, SharedTargetProofV1).model_dump(mode="json"))


class SharedFactsBudgetV1(StorageContract):
    reservation_id: UUID
    settlement_id: UUID
    settlement_key: str
    reserved: ResourceAmounts
    usage_state: Literal["known", "unknown"]
    actual: ResourceAmounts | None
    receipt_hash: Digest | None

    @model_validator(mode="after")
    def honest_usage(self) -> SharedFactsBudgetV1:
        if (self.usage_state == "unknown") != (self.actual is None and self.receipt_hash is None):
            raise ValueError("shared_facts_usage_state_mismatch")
        if self.usage_state == "known" and (self.actual is None or self.receipt_hash is None):
            raise ValueError("shared_facts_known_usage_missing")
        return self


class IssuedSharedAdmissionFactsV1(StorageContract):
    schema_version: Literal["issued_shared_admission_facts_v1"] = "issued_shared_admission_facts_v1"
    receipt_id: UUID
    root_id: UUID
    generation_artifact_id: UUID
    artifact_hash: Digest
    item_id: UUID
    version_id: UUID
    lease: JobLeaseV1
    continuation_binding_hash: Digest | None
    target_id: TargetId
    target_definition_hash: Digest
    specification_hash: Digest
    public_task_hash: Digest
    instance_hash: Digest
    inputs_hash: Digest
    coverage_blueprint_hash: Digest
    profile_hash: Digest
    runtime_profile_hash: Digest
    scorer_version: str
    validation_preparation_id: UUID
    validation_receipt_id: UUID
    blind_receipt_id: UUID
    review_receipt_id: UUID
    validation_receipt_hash: Digest
    blind_receipt_hash: Digest
    review_receipt_hash: Digest
    validation_budget: SharedFactsBudgetV1 | None
    review_budget: SharedFactsBudgetV1
    # Review provider aggregate remains UNKNOWN; independently known execution
    # usage is a subcomponent and must never release the provider allocation.
    review_execution_usage: ResourceAmounts
    validation_terminals: tuple[RunnerTerminalProofV1, ...] = Field(max_length=32)
    blind_terminals: tuple[RunnerTerminalProofV1, ...] = Field(max_length=1)
    ambiguity: FiniteAmbiguityReceiptV1
    scorer_counts: dict[str, int]
    target_proof: SharedTargetProofV1 | None
    evidence: AdmissionEvidenceV2
    evaluation: AdmissionEvaluationField
    checked_at: datetime
    valid_until: datetime
    publication_enabled: Literal[False] = False

    @model_validator(mode="after")
    def native_shape(self) -> IssuedSharedAdmissionFactsV1:
        if (self.lease.visibility != "public" or self.checked_at.tzinfo is None
                or self.valid_until.tzinfo is None or self.checked_at >= self.valid_until
                or self.evaluation.binding != self.evidence.binding
                or self.profile_hash != self.lease.profile.profile_hash
                or self.validation_receipt_hash != self.evidence.validation_receipt_hash
                or self.evidence.coverage_proof_hash != (None if self.target_proof is None else self.target_proof.proof_hash)):
            raise ValueError("shared_facts_identity_mismatch")
        if self.target_id == "python-kc-binding-v1":
            if (self.validation_budget is not None or self.validation_terminals or self.blind_terminals
                    or self.ambiguity.mode != "static_options" or self.evidence.runner_available
                    or self.evidence.execution_isolated or self.evidence.execution_receipt_hash is not None):
                raise ValueError("shared_static_facts_cannot_claim_execution")
        elif (self.validation_budget is None or not self.validation_terminals
              or len(self.blind_terminals) != 1 or self.ambiguity.mode != "sealed_pair"):
            raise ValueError("shared_runtime_facts_missing_original_proofs")
        return self

    @property
    def receipt_hash(self) -> str:
        return canonical_hash(checked_model(self, IssuedSharedAdmissionFactsV1).model_dump(mode="json"))
