"""Domain-neutral registered semantic-child DATA compiler; no issuer or IO.

PRIVATE owners retain their own storage-scope bridge, runtime/source/review and
receiver gates. PUBLIC coverage intent in a finite spec is not public permission
and is never relabeled PRIVATE here. No lease, mode or receipt capability exists.
"""
from __future__ import annotations
from typing import Literal
from uuid import UUID
from pydantic import Field, model_validator
from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.contracts import Digest, Identifier
from app.services.learning.item_supply.finite_candidate_factory import (
    FLEXIBLE_FACTORY_VERSION, FiniteCandidateSpecV1, FiniteSlotAllocationV2,
    build_finite_candidate_spec, build_finite_slot_allocation,
)
from app.services.learning.item_supply.finite_targets.contracts import TaskKind
from app.services.learning.item_supply.finite_task_families import families_for_course
from app.services.learning.item_supply.generation_contracts import PublicMaterialV2
from app.services.learning.item_supply.storage_contracts import StorageContract, checked_model

COMPILER_VERSION: Literal["registered-semantic-child-data-v1"] = "registered-semantic-child-data-v1"

class RegisteredSemanticChildInputV1(StorageContract):
    schema_version: Literal["registered_semantic_child_input_v1"] = "registered_semantic_child_input_v1"
    business_item_id: UUID
    root_id: UUID
    parent_version_id: UUID
    parent_specification: FiniteCandidateSpecV1 = Field(repr=False)
    materials: tuple[PublicMaterialV2, ...] = Field(min_length=1, max_length=16, repr=False)
    selected_task_kind: TaskKind
    child_item_key: Identifier
    child_version: Identifier

    @model_validator(mode="after")
    def registered_distinct_child(self) -> RegisteredSemanticChildInputV1:
        parent = checked_model(self.parent_specification,FiniteCandidateSpecV1)
        old_family = next(f for f in families_for_course(parent.target_id) if f.family_id == parent.allocation.family_id)
        if self.child_version == parent.public_template.version or self.selected_task_kind == old_family.task_kind:
            raise ValueError("new immutable version and different registered task-kind required")
        if self.selected_task_kind not in registered_semantic_child_kinds(parent):
            raise ValueError("registered task-kind incompatible with unchanged role/variant")
        return self

class RegisteredSemanticChildPlanV1(StorageContract):
    schema_version: Literal["registered_semantic_child_plan_v1"] = "registered_semantic_child_plan_v1"
    compiler_version: Literal["registered-semantic-child-data-v1"] = COMPILER_VERSION
    business_item_id: UUID
    root_id: UUID
    parent_version_id: UUID
    parent_specification_hash: Digest
    task_kind: TaskKind
    child_specification: FiniteCandidateSpecV1 = Field(repr=False)

    @property
    def plan_hash(self) -> str:
        return canonical_hash(checked_model(self,RegisteredSemanticChildPlanV1).model_dump(mode="json"))


def registered_semantic_child_kinds(parent: FiniteCandidateSpecV1) -> tuple[TaskKind, ...]:
    """Declaration-only role-compatible choices. No exposure/current/quality claim."""
    parent = checked_model(parent,FiniteCandidateSpecV1)
    old = next(f for f in families_for_course(parent.target_id) if f.family_id == parent.allocation.family_id)
    role = parent.allocation.variant_id.rsplit(":",1)[1]
    index = 1 if role == "guided-remediation" else int(role[-1])
    choices = []
    for family in families_for_course(parent.target_id):
        if family.task_kind == old.task_kind:
            continue
        try:
            allocation = build_finite_slot_allocation(target_id=parent.target_id,family_id=family.family_id,
                slot=parent.allocation.slot,slot_index=index)
        except ValueError:
            continue  # Original KC remediation rule: only diagnose is legal.
        if allocation.variant_id != parent.allocation.variant_id:
            raise ValueError("registered variant changed")
        choices.append(family.task_kind)
    return tuple(choices)


def compile_registered_semantic_child(request: RegisteredSemanticChildInputV1) -> RegisteredSemanticChildPlanV1:
    """Use ORIGINAL factory, never free-form content, a new seed or a new wallet.

    Caller must bind all IDs to its actual durable owner, freeze this DATA before
    any paid stage, and independently check actual finding/current exposure. This
    compiler deliberately has no way to issue those authorities or bypass them.
    """
    request = checked_model(request,RegisteredSemanticChildInputV1)
    parent = request.parent_specification
    family = next(f for f in families_for_course(parent.target_id) if f.task_kind == request.selected_task_kind)
    role = parent.allocation.variant_id.rsplit(":",1)[1]
    allocation = build_finite_slot_allocation(target_id=parent.target_id,family_id=family.family_id,
        slot=parent.allocation.slot,slot_index=1 if role == "guided-remediation" else int(role[-1]))
    scope = parent.coverage_blueprint.scope
    child = build_finite_candidate_spec(target_id=parent.target_id,variant_id=parent.allocation.variant_id,
        seed=parent.seed,item_key=request.child_item_key,version=request.child_version,materials=request.materials,
        runtime_profile_hash=None if parent.blueprint.runtime_profile_id is None else scope.runtime_profile_hash,
        scorer_version=scope.scorer_version,assistance_policy_hash=scope.assistance_policy_hash,
        policy_version=parent.coverage_blueprint.policy_version,difficulty_profile=parent.blueprint.difficulty_profile,
        publication_policy=parent.blueprint.publication_policy,public_spec_version=FLEXIBLE_FACTORY_VERSION,allocation=allocation)
    if (type(child.allocation) is not FiniteSlotAllocationV2
            or child.coverage_blueprint != parent.coverage_blueprint or child.target_id != parent.target_id
            or child.target_definition_hash != parent.target_definition_hash or child.seed != parent.seed
            or child.allocation.variant_id != parent.allocation.variant_id or child.allocation.slot != parent.allocation.slot
            or child.blueprint.model_dump(mode="json",exclude={"blueprint_key","version"})
                != parent.blueprint.model_dump(mode="json",exclude={"blueprint_key","version"})
            or canonical_hash(child.public_template.content.model_dump(mode="json"))
                == canonical_hash(parent.public_template.content.model_dump(mode="json"))):
        raise ValueError("registered substantive child must preserve complete objective/risk/source and seed/variant")
    return RegisteredSemanticChildPlanV1(business_item_id=request.business_item_id,root_id=request.root_id,
        parent_version_id=request.parent_version_id,parent_specification_hash=parent.specification_hash,
        task_kind=family.task_kind,child_specification=child)


def verify_registered_semantic_child(request: RegisteredSemanticChildInputV1, plan: RegisteredSemanticChildPlanV1) -> None:
    """Pure exact replay of DATA compilation, not JSON capability restoration."""
    request = checked_model(request,RegisteredSemanticChildInputV1)
    plan = checked_model(plan,RegisteredSemanticChildPlanV1)
    if plan != compile_registered_semantic_child(request):
        raise ValueError("complete original registered semantic child plan mismatch")

