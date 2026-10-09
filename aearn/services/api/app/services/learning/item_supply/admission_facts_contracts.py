"""Typed pre-admission target facts, not publication inventory or model metadata."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from aearn_shared.execution import SandboxInputV1, SandboxResultV1
from pydantic import Field, model_validator

from app.services.learning.item_bank.contracts import LearningItemBlueprintV1, canonical_hash
from app.services.learning.item_supply.contracts import AssessmentSupplyDemandV1, CoverageBlueprintV1, Digest
from app.services.learning.item_supply.generation_contracts import SourceReceiptV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.policies import ResourceAmounts
from app.services.learning.item_supply.review_contracts_v2 import AdmissionEvidenceV2, BlindScoreV2, CandidateBindingV2
from app.services.learning.item_supply.storage_contracts import StorageContract, checked_model
from app.services.learning.item_supply.validation_adapter import CandidateExecutionEvidenceV2
from app.services.learning.item_supply.sandbox.python_goal_scorer import PYTHON_GOAL_SCORER_HASH


class TaskTargetV1(StorageContract):
    profile_id: Literal["sqlite_filter_order_duplicates_v1"] = "sqlite_filter_order_duplicates_v1"
    table: Literal["learners"] = "learners"
    filter_column: Literal["track"] = "track"
    filter_value: Literal["sql"] = "sql"
    projection: tuple[Literal["name"], ...] = ("name",)
    order_by: Literal["id"] = "id"
    order_direction: Literal["ascending"] = "ascending"
    duplicates: Literal["keep"] = "keep"

    @property
    def target_hash(self) -> str:
        return canonical_hash(checked_model(self,TaskTargetV1).model_dump(mode="json"))


class PythonTaskTargetV1(StorageContract):
    profile_id: Literal["python_assignment_sum_print_v1"] = "python_assignment_sum_print_v1"
    goal_contract_id: Literal["python-assignment-sum-print-v1"] = "python-assignment-sum-print-v1"
    assignment_variable: Literal["numbers"] = "numbers"
    numbers: tuple[Literal[3], Literal[-1], Literal[0], Literal[3]] = (3, -1, 0, 3)
    sum_function: Literal["sum"] = "sum"
    output_function: Literal["print"] = "print"
    intermediate_variable: Literal["total"] = "total"
    allowed_forms: Literal["direct_or_single_total_sequential_only"] = "direct_or_single_total_sequential_only"
    scorer_contract_hash: Digest = PYTHON_GOAL_SCORER_HASH

    @property
    def target_hash(self) -> str:
        return canonical_hash(checked_model(self, PythonTaskTargetV1).model_dump(mode="json"))


class TaskAmbiguityPlanV1(StorageContract):
    schema_version: Literal["task_ambiguity_plan_v1"] = "task_ambiguity_plan_v1"
    source_hash: Digest
    content_hash: Digest
    public_task_hash: Digest
    target: TaskTargetV1 | PythonTaskTargetV1
    scorer_version: str
    correct: SandboxInputV1
    counterexample: SandboxInputV1
    expected_json: str = Field(min_length=2,max_length=24000)

    @property
    def plan_hash(self) -> str:
        return canonical_hash(checked_model(self,TaskAmbiguityPlanV1).model_dump(mode="json"))


class RunnerTerminalProofV1(StorageContract):
    schema_version: Literal["item_supply_runner_terminal_v1"]
    run_id: UUID
    probe_name: str
    request_hash: Digest
    lock_fingerprint: Digest
    result: SandboxResultV1
    elapsed_seconds: float = Field(ge=0,le=10)
    mode: Literal["live"]
    isolation: Literal["approved_os_boundary"]
    seal: str = Field(min_length=1,max_length=256)


class TaskAmbiguityReceiptV1(StorageContract):
    schema_version: Literal["task_ambiguity_receipt_v1"] = "task_ambiguity_receipt_v1"
    plan: TaskAmbiguityPlanV1
    run_id: UUID
    started_at: datetime
    completed_at: datetime
    parent_deadline_at: datetime
    terminals: tuple[RunnerTerminalProofV1, ...] = Field(min_length=2,max_length=2)
    correct_case_results: tuple[bool, ...]
    counterexample_case_results: tuple[bool, ...]
    scorer_outcomes: tuple[Literal["passed","failed"], ...] = Field(min_length=2,max_length=2)
    derivation: Literal["declarative_task_and_independent_duplicate_order_pair", "explicit_python_goal_same_stdout_pair"] = "declarative_task_and_independent_duplicate_order_pair"

    @property
    def receipt_hash(self) -> str:
        return canonical_hash(checked_model(self,TaskAmbiguityReceiptV1).model_dump(mode="json"))


class ClauseTargetMappingV1(StorageContract):
    clause_id: str
    clause_hash: Digest
    capability: Literal["sql.select.where","sql.order_by","python.assignment"]
    declaration_hash: Digest
    execution_proof_hash: Digest


class BlindExecutionProofV1(StorageContract):
    source_hash: Digest
    content_hash: Digest
    binding_hash: Digest
    answer_hash: Digest
    run_id: UUID
    probe_name: Literal["blind_answer"]
    request_hash: Digest
    terminal_hash: Digest
    lock_fingerprint: Digest
    seal: str
    mode: Literal["live"]
    isolation: Literal["approved_os_boundary"]
    result_status: str
    elapsed_seconds: float = Field(ge=0,le=10)
    scorer_status: Literal["passed","failed"]


class AmbiguityBudgetBindingV1(StorageContract):
    reservation_id: UUID
    settlement_id: UUID
    root_id: UUID
    reserved: ResourceAmounts
    actual_execution: ResourceAmounts
    reserved_at: datetime
    settled_at: datetime
    receipt_hash: Digest
    http_usage_state: Literal["unknown_retained"] = "unknown_retained"
    budget_kind: Literal["existing_review_aggregate"] = "existing_review_aggregate"



class PreAdmissionCoverageReceiptV1(StorageContract):
    schema_version: Literal["pre_admission_coverage_receipt_v1"] = "pre_admission_coverage_receipt_v1"
    binding: CandidateBindingV2
    scope_hash: Digest
    objective_hash: Digest
    demand: AssessmentSupplyDemandV1
    coverage_blueprint: CoverageBlueprintV1
    item_blueprint: LearningItemBlueprintV1
    active_node_snapshot: dict[str, Any]
    target: TaskTargetV1 | PythonTaskTargetV1
    mappings: tuple[ClauseTargetMappingV1, ...] = Field(min_length=1,max_length=2)
    source_receipts: tuple[SourceReceiptV2, ...] = Field(min_length=1,max_length=12)
    execution: CandidateExecutionEvidenceV2
    execution_terminals: tuple[RunnerTerminalProofV1, ...] = Field(min_length=1,max_length=64)
    scorer_counts: dict[str,int]
    ambiguity_receipt_hash: Digest
    ambiguity_budget: AmbiguityBudgetBindingV1
    blind_score: BlindScoreV2
    blind_terminals: tuple[BlindExecutionProofV1, ...] = Field(min_length=1,max_length=1)
    checked_at: datetime
    valid_until: datetime
    publication_enabled: Literal[False] = False
    coverage_kind: Literal["candidate_target_mapping_not_inventory"] = "candidate_target_mapping_not_inventory"

    @model_validator(mode="after")
    def target_capabilities(self) -> PreAdmissionCoverageReceiptV1:
        capabilities = ("python.assignment",) if isinstance(self.target, PythonTaskTargetV1) else ("sql.select.where", "sql.order_by")
        if tuple(mapping.capability for mapping in self.mappings) != capabilities:
            raise ValueError("pre_admission_target_capability_mismatch")
        return self

    @property
    def receipt_hash(self) -> str:
        return canonical_hash(checked_model(self,PreAdmissionCoverageReceiptV1).model_dump(mode="json"))


class IssuedAdmissionFactsV1(StorageContract):
    schema_version: Literal["issued_admission_facts_v1"] = "issued_admission_facts_v1"
    receipt_id: UUID
    user_id: UUID
    epoch: int = Field(ge=1)
    scope_id: UUID
    generation_artifact_id: UUID
    version_id: UUID
    lease: JobLeaseV1
    coverage: PreAdmissionCoverageReceiptV1
    ambiguity: TaskAmbiguityReceiptV1
    evidence: AdmissionEvidenceV2
    derivations: dict[str,str]
    publication_enabled: Literal[False] = False

    @property
    def receipt_hash(self) -> str:
        return canonical_hash(checked_model(self,IssuedAdmissionFactsV1).model_dump(mode="json"))
