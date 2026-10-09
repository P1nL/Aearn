"""Immutable declaration DTOs, deliberately independent of runtime/DB/plugins.

Hashes identify definitions, not approved families, executable profiles or proof.
"""
from __future__ import annotations

import hashlib
import json
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TargetId = Literal[
    "python-state-update-v1", "sqlite-predicate-order-v1", "python-kc-binding-v1",
]
TaskKind = Literal[
    "accumulate", "refresh", "swap", "transfer", "conjunction", "override_fallback",
    "exclusive", "keyset_after", "trace", "diagnose", "repair", "counterexample",
]
ClauseId = Literal[
    "PY-C1", "PY-C2", "PY-C3", "SQL-C1", "SQL-C2", "SQL-C3", "KC-C1", "KC-C2", "KC-C3",
]
Identifier = Annotated[str, Field(min_length=1, max_length=160, pattern=r"^[a-z][a-z0-9._:-]*$")]
Digest = Annotated[str, Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")]
Text = Annotated[str, Field(min_length=1, max_length=1200)]
Slot = Literal["practice", "assessment", "remediation"]
Purpose = Literal["exercise", "knowledge_check", "remediation"]

TASK_KINDS: MappingProxyType[str, tuple[TaskKind, ...]] = MappingProxyType({
    "python-state-update-v1": ("accumulate", "refresh", "swap", "transfer"),
    "sqlite-predicate-order-v1": ("conjunction", "override_fallback", "exclusive", "keyset_after"),
    "python-kc-binding-v1": ("trace", "diagnose", "repair", "counterexample"),
})
CLAUSE_IDS: MappingProxyType[str, tuple[ClauseId, ...]] = MappingProxyType({
    "python-state-update-v1": ("PY-C1", "PY-C2", "PY-C3"),
    "sqlite-predicate-order-v1": ("SQL-C1", "SQL-C2", "SQL-C3"),
    "python-kc-binding-v1": ("KC-C1", "KC-C2", "KC-C3"),
})


def _digest(domain: str, payload: object) -> str:
    encoded = json.dumps(
        {"domain": domain, "payload": payload}, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class FiniteDeclaration(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="always",
        validate_default=True,
    )
    definition_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["declaration_pending"] = "declaration_pending"

    @model_validator(mode="after")
    def safe_text(self) -> FiniteDeclaration:
        def check(value: object) -> None:
            if isinstance(value, str) and (
                not value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value)
            ):
                raise ValueError("invalid declaration text")
            if isinstance(value, tuple):
                for child in value:
                    check(child)
        for name in type(self).model_fields:
            check(getattr(self, name))
        return self

    def _checked(self) -> FiniteDeclaration:
        # model_copy/model_construct are not validation boundaries. Do not let
        # serialization silently drop a hidden nested field before hashing.
        remaining = 256

        def inspect(value: object, depth: int = 0) -> None:
            nonlocal remaining
            remaining -= 1
            if remaining < 0 or depth > 8:
                raise ValueError("declaration exceeds finite structure bounds")
            if isinstance(value, BaseModel):
                if (not isinstance(value, FiniteDeclaration)
                        or set(value.__dict__) - set(type(value).model_fields)
                        or value.__pydantic_extra__):
                    raise ValueError("invalid declaration fields")
                for child in value.__dict__.values():
                    inspect(child, depth + 1)
            elif isinstance(value, tuple):
                for child in value:
                    inspect(child, depth + 1)
        inspect(self)
        return type(self).model_validate(self)

    @property
    def definition_hash(self) -> str:
        return _digest("finite-declaration-v1", self._checked().model_dump(mode="json"))


class FiniteClauseV1(FiniteDeclaration):
    schema_version: Literal["finite_clause_v1"] = "finite_clause_v1"
    clause_id: ClauseId
    statement: Text


class FiniteClauseReferenceV1(FiniteDeclaration):
    schema_version: Literal["finite_clause_reference_v1"] = "finite_clause_reference_v1"
    clause_id: ClauseId
    clause_definition_hash: Digest


class FiniteAssessmentDeclarationV1(FiniteDeclaration):
    schema_version: Literal["finite_assessment_declaration_v1"] = "finite_assessment_declaration_v1"
    item_kind: Literal["code", "sql", "knowledge_check"]
    content_type: Literal["code_completion", "sql_v2", "single_choice"]
    interaction: Literal["edit", "query", "respond"]
    purpose: Literal["exercise", "knowledge_check"]
    assessment_contract_version: TargetId
    scorer_domain: TargetId
    execution_contract: Literal["python_stdout_test", "sql_query_test", "knowledge_check_v1"]
    runtime_profile_id: Literal["python-stdout-v1", "sqlite-query-v1"] | None
    executable_profile_hash: None = None

    @model_validator(mode="after")
    def common_domain(self) -> FiniteAssessmentDeclarationV1:
        profiles = {
            "python-state-update-v1": (
                "code", "code_completion", "edit", "exercise", "python_stdout_test", "python-stdout-v1",
            ),
            "sqlite-predicate-order-v1": (
                "sql", "sql_v2", "query", "exercise", "sql_query_test", "sqlite-query-v1",
            ),
            "python-kc-binding-v1": (
                "knowledge_check", "single_choice", "respond", "knowledge_check", "knowledge_check_v1", None,
            ),
        }
        actual = (self.item_kind, self.content_type, self.interaction, self.purpose,
                  self.execution_contract, self.runtime_profile_id)
        if (self.scorer_domain != self.assessment_contract_version
                or actual != profiles[self.assessment_contract_version]):
            raise ValueError("inconsistent finite assessment declaration")
        return self


class FiniteCourseTargetV1(FiniteDeclaration):
    schema_version: Literal["finite_course_target_v1"] = "finite_course_target_v1"
    target_id: TargetId
    display_id: Literal["PY-STATE-01", "SQL-PRED-ORDER-01", "PY-KC-BIND-01"]
    goal_text: Text
    language_id: Literal["python", "sql"]
    subject_id: Literal["route.python", "route.sql"]
    required_facets: tuple[Identifier, ...] = Field(min_length=1, max_length=4)
    required_capabilities: tuple[Identifier, ...] = Field(min_length=1, max_length=4)
    clauses: tuple[FiniteClauseV1, ...] = Field(min_length=3, max_length=3)
    assessment: FiniteAssessmentDeclarationV1

    @model_validator(mode="after")
    def exact_group(self) -> FiniteCourseTargetV1:
        coordinates = {
            "python-state-update-v1": ("PY-STATE-01", "python", "route.python"),
            "sqlite-predicate-order-v1": ("SQL-PRED-ORDER-01", "sql", "route.sql"),
            "python-kc-binding-v1": ("PY-KC-BIND-01", "python", "route.python"),
        }
        if ((self.display_id, self.language_id, self.subject_id) != coordinates[self.target_id]
                or self.assessment.assessment_contract_version != self.target_id
                or tuple(clause.clause_id for clause in self.clauses) != CLAUSE_IDS[self.target_id]):
            raise ValueError("inconsistent finite course declaration")
        for values in (self.required_facets, self.required_capabilities):
            if len(set(values)) != len(values):
                raise ValueError("duplicate finite requirement")
        return self

    @property
    def clause_refs(self) -> tuple[FiniteClauseReferenceV1, ...]:
        self._checked()
        return tuple(FiniteClauseReferenceV1(
            clause_id=clause.clause_id, clause_definition_hash=clause.definition_hash,
        ) for clause in self.clauses)


class FiniteStructureV1(FiniteDeclaration):
    schema_version: Literal["finite_structure_v1"] = "finite_structure_v1"
    behavior_id: Identifier
    steps: tuple[Text, ...] = Field(min_length=2, max_length=6)
    invariants: tuple[Text, ...] = Field(min_length=1, max_length=6)
    semantic_failure_modes: tuple[Text, ...] = Field(min_length=2, max_length=8)


class FiniteTaskFamilyV1(FiniteDeclaration):
    schema_version: Literal["finite_task_family_v1"] = "finite_task_family_v1"
    target_id: TargetId
    family_id: Identifier
    task_kind: TaskKind
    target_definition_hash: Digest
    assessment_definition_hash: Digest
    clause_refs: tuple[FiniteClauseReferenceV1, ...] = Field(min_length=3, max_length=3)
    structure: FiniteStructureV1
    public_task: Text
    fixture_requirements: tuple[Text, ...] = Field(min_length=2, max_length=8)
    executable_fixture_hash: None = None

    @model_validator(mode="after")
    def exact_family(self) -> FiniteTaskFamilyV1:
        if (self.task_kind not in TASK_KINDS[self.target_id]
                or self.family_id != f"{self.target_id}:{self.task_kind}"
                or tuple(ref.clause_id for ref in self.clause_refs) != CLAUSE_IDS[self.target_id]):
            raise ValueError("inconsistent finite family declaration")
        return self

    @property
    def structure_signature(self) -> str:
        self._checked()
        return self.structure.definition_hash

    @property
    def public_task_hash(self) -> str:
        self._checked()
        return _digest("finite-public-task-declaration-v1", self.public_task)

    @property
    def fixture_specification_hash(self) -> str:
        self._checked()
        return _digest("finite-fixture-requirements-v1", self.fixture_requirements)


class FiniteSlotAllocationV1(FiniteDeclaration):
    schema_version: Literal["finite_slot_allocation_v1"] = "finite_slot_allocation_v1"
    target_id: TargetId
    family_id: Identifier
    family_definition_hash: Digest
    variant_id: Identifier
    slot: Slot
    purpose: Purpose
    clause_refs: tuple[FiniteClauseReferenceV1, ...] = Field(min_length=3, max_length=3)
    guidance: Literal["unguided", "state_table_and_localization_hints"]
    binding_requirement: Literal["native_scope", "purpose_child_scope"]

    @model_validator(mode="after")
    def exact_allocation(self) -> FiniteSlotAllocationV1:
        roles: dict[str, tuple[int, Slot]] = {
            "practice-1": (0, "practice"), "practice-2": (1, "practice"),
            "assessment-1": (2, "assessment"), "assessment-2": (3, "assessment"),
            "guided-remediation": (1, "remediation"),
        }
        role = self.variant_id.removeprefix(f"{self.target_id}:")
        if role not in roles:
            raise ValueError("unknown finite variant")
        index, slot = roles[role]
        remedial = slot == "remediation"
        purpose = ("remediation" if remedial else
                   "knowledge_check" if self.target_id == "python-kc-binding-v1" else "exercise")
        if (self.variant_id != f"{self.target_id}:{role}" or self.slot != slot
                or self.family_id != f"{self.target_id}:{TASK_KINDS[self.target_id][index]}"
                or self.purpose != purpose
                or self.guidance != ("state_table_and_localization_hints" if remedial else "unguided")
                or self.binding_requirement != ("purpose_child_scope" if remedial else "native_scope")
                or tuple(ref.clause_id for ref in self.clause_refs) != CLAUSE_IDS[self.target_id]):
            raise ValueError("inconsistent finite allocation declaration")
        return self


class FiniteFamilyPairDeclarationV1(FiniteDeclaration):
    schema_version: Literal["finite_family_pair_declaration_v1"] = "finite_family_pair_declaration_v1"
    target_id: TargetId
    left_family_id: Identifier
    right_family_id: Identifier
    left_structure_signature: Digest
    right_structure_signature: Digest
    required_evidence: tuple[
        Literal["lawful_transfer_counterexamples"], Literal["curriculum_clause_mapping"],
        Literal["technical_review"], Literal["ambiguity_review"], Literal["adversarial_review"],
    ] = ("lawful_transfer_counterexamples", "curriculum_clause_mapping", "technical_review",
         "ambiguity_review", "adversarial_review")

    @model_validator(mode="after")
    def ordered_pair(self) -> FiniteFamilyPairDeclarationV1:
        ids = tuple(f"{self.target_id}:{kind}" for kind in TASK_KINDS[self.target_id])
        if (self.left_family_id not in ids or self.right_family_id not in ids
                or ids.index(self.left_family_id) >= ids.index(self.right_family_id)):
            raise ValueError("invalid finite family pair")
        # Equal/different signatures NEVER settle independence here.
        return self
