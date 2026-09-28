"""Immutable capability descriptors and bounded schemas for the Tutor catalog."""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aearn_shared.execution import ExecutionEffectProposalV1


EXACT_SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
CATALOG_IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
CONTRACT_IDENTIFIER_PATTERN = re.compile(r"^tutor\.[a-z][a-z0-9-]*\.v[1-9]\d*$")
_IMAGE_TARGET_PATTERN = re.compile(r"(?i)(?:^|[\\/])[^\\/\s]+\.(?:avif|gif|ico|jpe?g|png|svg|webp)$")
_URL_TARGET_PATTERN = re.compile(r"(?i)\b(?:https?|ftp)://")
_PATH_TARGET_PATTERN = re.compile(r"(?:^|\s)(?:[A-Za-z]:[\\/]|[~/][^\s]*|\.[\\/]|\.\.[\\/])")
_SQL_TARGET_PATTERN = re.compile(
    r"(?is)^\s*(?:select\b.+\bfrom\b|insert\s+into\b|update\s+\S+\s+set\b|delete\s+from\b|drop\s+(?:table|database)\b|alter\s+table\b)"
)
_COMMAND_TARGET_PATTERN = re.compile(
    r"(?i)^\s*(?:bash|cmd(?:\.exe)?|curl|node|npm|powershell|pwsh|python(?:\.exe)?|rm|sh|wget)\b\s+"
)


class CapabilityMode(str, Enum):
    READ = "read"
    EFFECT_PROPOSAL = "effect_proposal"


class _FrozenSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class GroundingRetrieveInput(_FrozenSchema):
    """Only registry-scoped query facts are accepted by the first capability."""

    language_id_or_alias: str = Field(min_length=1, max_length=40)
    query_text: str = Field(min_length=1, max_length=280)
    topic_tags: tuple[str, ...] = Field(default=(), max_length=4)
    top_k: int = Field(default=2, ge=1, le=4)

    @field_validator("language_id_or_alias", "query_text")
    @classmethod
    def _reject_execution_targets(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if contains_forbidden_execution_target(normalized):
            raise ValueError("grounding request cannot contain an executable target")
        return normalized

    @field_validator("topic_tags")
    @classmethod
    def _validate_topic_tags(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(" ".join(value.split()).lower() for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("grounding topic tags must be unique")
        if any(not CATALOG_IDENTIFIER_PATTERN.fullmatch(value) for value in normalized):
            raise ValueError("grounding topic tags must be stable identifiers")
        return normalized


class GroundingCitationOutput(_FrozenSchema):
    source_id: str = Field(min_length=1, max_length=120)
    citation_id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=120)
    canonical_url: str = Field(min_length=1, max_length=240)
    section_path: tuple[str, ...] = Field(default=(), max_length=4)
    trust_tier: Literal["official", "trusted_de_facto", "internal"]
    content_hash: str = Field(min_length=64, max_length=64)
    relevance_score: float = Field(ge=0, allow_inf_nan=False)
    match_reasons: tuple[str, ...] = Field(default=(), max_length=4)

    @field_validator("content_hash")
    @classmethod
    def _validate_content_hash(cls, value: str) -> str:
        normalized = value.lower()
        if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
            raise ValueError("grounding content hash must be a SHA-256 hex digest")
        return normalized

    @field_validator("section_path")
    @classmethod
    def _validate_section_path(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(" ".join(value.split()) for value in values)
        if any(not value or len(value) > 120 for value in normalized):
            raise ValueError("grounding section paths must be bounded text")
        return normalized

    @field_validator("match_reasons")
    @classmethod
    def _validate_match_reasons(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(" ".join(value.split()).lower() for value in values)
        if len(set(normalized)) != len(normalized) or any(
            not CATALOG_IDENTIFIER_PATTERN.fullmatch(value) for value in normalized
        ):
            raise ValueError("grounding match reasons must be unique stable identifiers")
        return normalized


class GroundingSnippetOutput(_FrozenSchema):
    content: str = Field(min_length=1, max_length=180)
    citation: GroundingCitationOutput


class GroundingRetrieveOutput(_FrozenSchema):
    status: Literal["completed"]
    snippets: tuple[GroundingSnippetOutput, ...] = Field(default=(), max_length=4)


_LEARNING_PLAN_PROFILE_JSON_DESCRIPTION = (
    "Compact JSON object with exactly language_id, goal_text, target_level, weekly_minutes, "
    "experience_level, teaching_preferences, pace_summary, and title. "
    "Copy confirmed fact values exactly: pace_constraints maps to pace_summary; other keys stay unchanged. "
    "Never paraphrase or summarize; generate only missing or explicitly reopened fields."
)
_LEARNING_PLAN_MODULE_JSON_DESCRIPTION = (
    "JSON: module_key,title,description,is_core,is_skippable,nodes. Node: knowledge_key (step ID),title,description,"
    "is_core,prerequisite_keys,required_capabilities; optional catalog_knowledge_key selects published content."
)


class LearningPlanDraftCapabilityInput(_FrozenSchema):
    """Compact strings keep the generic Tutor envelope bounded at 12 fields."""

    profile_json: str = Field(min_length=2, max_length=360, description=_LEARNING_PLAN_PROFILE_JSON_DESCRIPTION)
    module_1: str = Field(min_length=2, max_length=360, description=_LEARNING_PLAN_MODULE_JSON_DESCRIPTION)
    module_2: str = Field(min_length=2, max_length=360, description=_LEARNING_PLAN_MODULE_JSON_DESCRIPTION)
    module_3: str | None = Field(default=None, min_length=2, max_length=360, description=_LEARNING_PLAN_MODULE_JSON_DESCRIPTION)
    module_4: str | None = Field(default=None, min_length=2, max_length=360, description=_LEARNING_PLAN_MODULE_JSON_DESCRIPTION)
    module_5: str | None = Field(default=None, min_length=2, max_length=360, description=_LEARNING_PLAN_MODULE_JSON_DESCRIPTION)
    module_6: str | None = Field(default=None, min_length=2, max_length=360, description=_LEARNING_PLAN_MODULE_JSON_DESCRIPTION)
    module_7: str | None = Field(default=None, min_length=2, max_length=360, description=_LEARNING_PLAN_MODULE_JSON_DESCRIPTION)
    module_8: str | None = Field(default=None, min_length=2, max_length=360, description=_LEARNING_PLAN_MODULE_JSON_DESCRIPTION)

    @field_validator("profile_json", "module_1", "module_2", "module_3", "module_4", "module_5", "module_6", "module_7", "module_8")
    @classmethod
    def _validate_compact_json(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if contains_forbidden_execution_target(normalized):
            raise ValueError("learning plan draft input cannot contain an execution target")
        return normalized

    @model_validator(mode="after")
    def _validate_contiguous_modules(self) -> "LearningPlanDraftCapabilityInput":
        values = (
            self.module_1,
            self.module_2,
            self.module_3,
            self.module_4,
            self.module_5,
            self.module_6,
            self.module_7,
            self.module_8,
        )
        seen_empty = False
        for value in values:
            if value is None:
                seen_empty = True
            elif seen_empty:
                raise ValueError("learning plan draft modules must be contiguous")
        return self

    def module_values(self) -> tuple[str, ...]:
        return tuple(
            value
            for value in (
                self.module_1,
                self.module_2,
                self.module_3,
                self.module_4,
                self.module_5,
                self.module_6,
                self.module_7,
                self.module_8,
            )
            if value is not None
        )


class LearningPlanDraftCapabilityInputV110(LearningPlanDraftCapabilityInput):
    """Version 1.1.0: bounded full-plan strings; all domain rules remain downstream."""

    profile_json: str = Field(min_length=2, max_length=1024, description=_LEARNING_PLAN_PROFILE_JSON_DESCRIPTION)
    module_1: str = Field(min_length=2, max_length=1024, description=_LEARNING_PLAN_MODULE_JSON_DESCRIPTION)
    module_2: str = Field(min_length=2, max_length=1024, description=_LEARNING_PLAN_MODULE_JSON_DESCRIPTION)
    module_3: str | None = Field(default=None, min_length=2, max_length=1024, description=_LEARNING_PLAN_MODULE_JSON_DESCRIPTION)
    module_4: str | None = Field(default=None, min_length=2, max_length=1024, description=_LEARNING_PLAN_MODULE_JSON_DESCRIPTION)
    module_5: str | None = Field(default=None, min_length=2, max_length=1024, description=_LEARNING_PLAN_MODULE_JSON_DESCRIPTION)
    module_6: str | None = Field(default=None, min_length=2, max_length=1024, description=_LEARNING_PLAN_MODULE_JSON_DESCRIPTION)
    module_7: str | None = Field(default=None, min_length=2, max_length=1024, description=_LEARNING_PLAN_MODULE_JSON_DESCRIPTION)
    module_8: str | None = Field(default=None, min_length=2, max_length=1024, description=_LEARNING_PLAN_MODULE_JSON_DESCRIPTION)


def plan_draft_input_model(version: str) -> type[LearningPlanDraftCapabilityInput]:
    if version == "1.0.0":
        return LearningPlanDraftCapabilityInput
    if version == "1.1.0":
        return LearningPlanDraftCapabilityInputV110
    raise ValueError("unsupported plan draft capability version")


class LearningPlanDraftCapabilityOutput(_FrozenSchema):
    status: Literal["completed"]
    draft_id: str = Field(min_length=1, max_length=120)
    draft_version: int = Field(ge=1)
    content_hash: str = Field(min_length=64, max_length=64)
    quality_status: Literal["passed"]

    @field_validator("content_hash")
    @classmethod
    def _validate_content_hash(cls, value: str) -> str:
        return _sha256_reference(value, label="learning plan draft content hash")


@dataclass(frozen=True)
class CapabilityDescriptor:
    """A developer-owned in-process capability definition."""

    capability_id: str
    version: str
    mode: CapabilityMode
    description: str
    input_model: type[BaseModel]
    result_model: type[BaseModel]
    policy_tags: tuple[str, ...] = ()
    allowed_effect_types: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not is_catalog_identifier(self.capability_id):
            raise ValueError("capability id must be a stable catalog identifier")
        if not is_exact_semver(self.version):
            raise ValueError("capability version must be exact SemVer")
        if not self.description.strip() or contains_forbidden_execution_target(self.description):
            raise ValueError("capability description is unsafe")
        if not issubclass(self.input_model, BaseModel) or not issubclass(self.result_model, BaseModel):
            raise TypeError("capability schemas must use Pydantic models")
        _ensure_unique_schema_fields(self.input_model)
        _ensure_unique_schema_fields(self.result_model)
        normalized_tags = tuple(self.policy_tags)
        if len(set(normalized_tags)) != len(normalized_tags) or any(
            not is_catalog_identifier(tag) for tag in normalized_tags
        ):
            raise ValueError("capability policy tags must be unique stable identifiers")
        normalized_effects = tuple(self.allowed_effect_types)
        if len(set(normalized_effects)) != len(normalized_effects) or any(
            not is_catalog_identifier(effect_type) for effect_type in normalized_effects
        ):
            raise ValueError("capability effect types must be unique stable identifiers")
        object.__setattr__(self, "policy_tags", normalized_tags)
        object.__setattr__(self, "allowed_effect_types", normalized_effects)

    @property
    def reference(self) -> str:
        return f"{self.capability_id}@{self.version}"

    @property
    def input_field_names(self) -> frozenset[str]:
        return frozenset(self.input_model.model_fields)

    def catalog_definition(self) -> dict[str, object]:
        return {
            "id": self.capability_id,
            "version": self.version,
            "mode": self.mode.value,
            "description": self.description,
            "policy_tags": list(self.policy_tags),
            "allowed_effect_types": list(self.allowed_effect_types),
            "input_schema": self.input_model.model_json_schema(),
            "result_schema": self.result_model.model_json_schema(),
        }


@dataclass(frozen=True)
class EffectDescriptor:
    """Catalog metadata for a future proposal type; Child 01 registers none."""

    effect_type: str
    version: str
    description: str
    proposal_model: type[BaseModel]
    policy_tags: tuple[str, ...] = ()
    implementation_owner: str = ""

    def __post_init__(self) -> None:
        if not is_catalog_identifier(self.effect_type):
            raise ValueError("effect type must be a stable catalog identifier")
        if not is_exact_semver(self.version):
            raise ValueError("effect version must be exact SemVer")
        if not self.description.strip() or contains_forbidden_execution_target(self.description):
            raise ValueError("effect description is unsafe")
        if not issubclass(self.proposal_model, BaseModel):
            raise TypeError("effect proposal schema must use a Pydantic model")
        _ensure_unique_schema_fields(self.proposal_model)
        if not self.implementation_owner or not is_catalog_identifier(self.implementation_owner):
            raise ValueError("effect implementation owner must be a stable identifier")
        tags = tuple(self.policy_tags)
        if len(set(tags)) != len(tags) or any(not is_catalog_identifier(tag) for tag in tags):
            raise ValueError("effect policy tags must be unique stable identifiers")
        object.__setattr__(self, "policy_tags", tags)


class CapabilitySchemaExporter:
    """Export Pydantic contracts in the MCP-compatible tool schema shape."""

    @staticmethod
    def export(descriptor: CapabilityDescriptor) -> dict[str, object]:
        return {
            "name": descriptor.capability_id,
            "description": descriptor.description,
            "inputSchema": descriptor.input_model.model_json_schema(),
        }


def is_exact_semver(value: object) -> bool:
    return isinstance(value, str) and bool(EXACT_SEMVER_PATTERN.fullmatch(value))


def is_catalog_identifier(value: object) -> bool:
    return isinstance(value, str) and bool(CATALOG_IDENTIFIER_PATTERN.fullmatch(value))


def is_tutor_contract_identifier(value: object) -> bool:
    return isinstance(value, str) and bool(CONTRACT_IDENTIFIER_PATTERN.fullmatch(value))


def contains_forbidden_execution_target(value: object) -> bool:
    """Reject values that look like a model-selected execution target."""

    text = str(value or "").strip()
    if not text:
        return False
    return bool(
        _URL_TARGET_PATTERN.search(text)
        or _PATH_TARGET_PATTERN.search(text)
        or _IMAGE_TARGET_PATTERN.search(text)
        or _SQL_TARGET_PATTERN.search(text)
        or _COMMAND_TARGET_PATTERN.search(text)
    )


def _ensure_unique_schema_fields(model: type[BaseModel]) -> None:
    schema_fields = tuple(
        field.alias if isinstance(field.alias, str) and field.alias else name
        for name, field in model.model_fields.items()
    )
    if len(schema_fields) != len(set(schema_fields)):
        raise ValueError("Pydantic schema fields must not expose duplicate names")


_SAFE_REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,119}$")
_SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _bounded_learner_text(value: str, *, label: str, maximum: int) -> str:
    normalized = " ".join(str(value).split())
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{label} must be bounded learner-safe text")
    if contains_forbidden_execution_target(normalized):
        raise ValueError(f"{label} cannot contain an execution target")
    return normalized


def _stable_reference(value: str, *, label: str) -> str:
    normalized = str(value).strip()
    if not _SAFE_REFERENCE_PATTERN.fullmatch(normalized):
        raise ValueError(f"{label} must be a stable bounded reference")
    return normalized


def _sha256_reference(value: str, *, label: str) -> str:
    normalized = str(value).strip().lower()
    if not _SHA256_HEX_PATTERN.fullmatch(normalized):
        raise ValueError(f"{label} must be a SHA-256 hex digest")
    return normalized


class TutorPlanDiffItemV1(_FrozenSchema):
    """One bounded learner-safe before/after item for an immutable plan revision."""

    field: str = Field(min_length=1, max_length=80)
    before: str | None = Field(default=None, max_length=120)
    after: str | None = Field(default=None, max_length=120)

    @field_validator("field")
    @classmethod
    def _validate_field(cls, value: str) -> str:
        return _stable_reference(value, label="plan diff field")

    @field_validator("before", "after")
    @classmethod
    def _validate_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _bounded_learner_text(value, label="plan diff text", maximum=120)

    @model_validator(mode="after")
    def _require_change(self) -> "TutorPlanDiffItemV1":
        if self.before is None and self.after is None:
            raise ValueError("plan diff item must contain a before or after value")
        return self


class TutorPlanActivateProposalV1(_FrozenSchema):
    """Exact effect payload for a new immutable active Tutor plan revision."""

    title: str = Field(min_length=1, max_length=120)
    outline: tuple[str, ...] = Field(min_length=1, max_length=4)
    change_reason: str = Field(min_length=1, max_length=160)
    diff: tuple[TutorPlanDiffItemV1, ...] = Field(min_length=1, max_length=4)
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=4)
    evidence_hashes: tuple[str, ...] = Field(min_length=1, max_length=4)
    policy_version: str = Field(min_length=1, max_length=120)

    @field_validator("title", "change_reason")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        maximum = 120 if len(value) <= 120 else 160
        return _bounded_learner_text(value, label="plan text", maximum=maximum)

    @field_validator("outline")
    @classmethod
    def _validate_outline(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_bounded_learner_text(value, label="plan outline item", maximum=96) for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("plan outline items must be unique")
        return normalized

    @field_validator("evidence_ids")
    @classmethod
    def _validate_evidence_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_stable_reference(value, label="plan evidence id") for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("plan evidence ids must be unique")
        return normalized

    @field_validator("evidence_hashes")
    @classmethod
    def _validate_evidence_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_sha256_reference(value, label="plan evidence hash") for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("plan evidence hashes must be unique")
        return normalized

    @field_validator("policy_version")
    @classmethod
    def _validate_policy_version(cls, value: str) -> str:
        return _stable_reference(value, label="plan policy version")

    @model_validator(mode="after")
    def _validate_evidence_shape(self) -> "TutorPlanActivateProposalV1":
        if len(self.evidence_ids) != len(self.evidence_hashes):
            raise ValueError("plan evidence ids and hashes must have equal lengths")
        return self


class TutorPlanRollbackProposalV1(_FrozenSchema):
    """Exact effect payload for a one-predecessor-only Tutor plan rollback."""

    reason: str = Field(min_length=1, max_length=160)
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=4)
    evidence_hashes: tuple[str, ...] = Field(min_length=1, max_length=4)
    policy_version: str = Field(min_length=1, max_length=120)

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        return _bounded_learner_text(value, label="plan rollback reason", maximum=160)

    @field_validator("evidence_ids")
    @classmethod
    def _validate_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_stable_reference(value, label="plan rollback evidence id") for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("plan rollback evidence ids must be unique")
        return normalized

    @field_validator("evidence_hashes")
    @classmethod
    def _validate_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_sha256_reference(value, label="plan rollback evidence hash") for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("plan rollback evidence hashes must be unique")
        return normalized

    @field_validator("policy_version")
    @classmethod
    def _validate_policy_version(cls, value: str) -> str:
        return _stable_reference(value, label="plan rollback policy version")

    @model_validator(mode="after")
    def _validate_evidence_shape(self) -> "TutorPlanRollbackProposalV1":
        if len(self.evidence_ids) != len(self.evidence_hashes):
            raise ValueError("plan rollback evidence ids and hashes must have equal lengths")
        return self


class TutorObjectiveMemoryRecordProposalV1(_FrozenSchema):
    """Only objective learner facts may be recorded through a Tutor effect."""

    memory_kind: Literal["objective_fact"]
    category: str = Field(min_length=1, max_length=80)
    fact: str = Field(min_length=1, max_length=180)
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=4)
    evidence_hashes: tuple[str, ...] = Field(min_length=1, max_length=4)
    policy_version: str = Field(min_length=1, max_length=120)

    @field_validator("category", "policy_version")
    @classmethod
    def _validate_identifiers(cls, value: str) -> str:
        return _stable_reference(value, label="memory identifier")

    @field_validator("fact")
    @classmethod
    def _validate_fact(cls, value: str) -> str:
        return _bounded_learner_text(value, label="memory fact", maximum=180)

    @field_validator("evidence_ids")
    @classmethod
    def _validate_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_stable_reference(value, label="memory evidence id") for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("memory evidence ids must be unique")
        return normalized

    @field_validator("evidence_hashes")
    @classmethod
    def _validate_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_sha256_reference(value, label="memory evidence hash") for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("memory evidence hashes must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_evidence_shape(self) -> "TutorObjectiveMemoryRecordProposalV1":
        if len(self.evidence_ids) != len(self.evidence_hashes):
            raise ValueError("memory evidence ids and hashes must have equal lengths")
        return self


class TutorActivityRecordProposalV1(_FrozenSchema):
    """Learner-safe activity and optional inbox projection request."""

    category: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=160)
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=4)
    evidence_hashes: tuple[str, ...] = Field(min_length=1, max_length=4)
    inbox_message: str | None = Field(default=None, max_length=160)
    policy_version: str = Field(min_length=1, max_length=120)

    @field_validator("category", "policy_version")
    @classmethod
    def _validate_identifiers(cls, value: str) -> str:
        return _stable_reference(value, label="activity identifier")

    @field_validator("reason", "inbox_message")
    @classmethod
    def _validate_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _bounded_learner_text(value, label="activity text", maximum=160)

    @field_validator("evidence_ids")
    @classmethod
    def _validate_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_stable_reference(value, label="activity evidence id") for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("activity evidence ids must be unique")
        return normalized

    @field_validator("evidence_hashes")
    @classmethod
    def _validate_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_sha256_reference(value, label="activity evidence hash") for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("activity evidence hashes must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_evidence_shape(self) -> "TutorActivityRecordProposalV1":
        if len(self.evidence_ids) != len(self.evidence_hashes):
            raise ValueError("activity evidence ids and hashes must have equal lengths")
        return self


TUTOR_PLAN_ACTIVATE_EFFECT_TYPE = "tutor.plan.activate"
TUTOR_PLAN_ROLLBACK_EFFECT_TYPE = "tutor.plan.rollback"
TUTOR_MEMORY_RECORD_EFFECT_TYPE = "tutor.memory.record"
TUTOR_ACTIVITY_RECORD_EFFECT_TYPE = "tutor.activity.record"

TUTOR_PLAN_ACTIVATE_EFFECT_DESCRIPTOR = EffectDescriptor(
    effect_type=TUTOR_PLAN_ACTIVATE_EFFECT_TYPE,
    version="1.0.0",
    description="Create one immutable learner-safe Tutor plan revision and activate its pointer.",
    proposal_model=TutorPlanActivateProposalV1,
    policy_tags=("learner-state",),
    implementation_owner="tutor-learner-state",
)
TUTOR_PLAN_ROLLBACK_EFFECT_DESCRIPTOR = EffectDescriptor(
    effect_type=TUTOR_PLAN_ROLLBACK_EFFECT_TYPE,
    version="1.0.0",
    description="Move the active Tutor plan pointer to its recorded predecessor with evidence.",
    proposal_model=TutorPlanRollbackProposalV1,
    policy_tags=("learner-state",),
    implementation_owner="tutor-learner-state",
)
TUTOR_MEMORY_RECORD_EFFECT_DESCRIPTOR = EffectDescriptor(
    effect_type=TUTOR_MEMORY_RECORD_EFFECT_TYPE,
    version="1.0.0",
    description="Record one evidence-backed objective learner memory fact without an inference.",
    proposal_model=TutorObjectiveMemoryRecordProposalV1,
    policy_tags=("learner-state",),
    implementation_owner="tutor-learner-state",
)
TUTOR_ACTIVITY_RECORD_EFFECT_DESCRIPTOR = EffectDescriptor(
    effect_type=TUTOR_ACTIVITY_RECORD_EFFECT_TYPE,
    version="1.0.0",
    description="Record one learner-safe activity item with an optional inbox projection.",
    proposal_model=TutorActivityRecordProposalV1,
    policy_tags=("learner-state",),
    implementation_owner="tutor-learner-state",
)


RUNNER_EXECUTE_EFFECT_TYPE = "runner.execute"
RUNNER_EXECUTE_EFFECT_DESCRIPTOR = EffectDescriptor(
    effect_type=RUNNER_EXECUTE_EFFECT_TYPE,
    version="1.0.0",
    description="Record one server-approved interactive execution intent for the isolated executor.",
    proposal_model=ExecutionEffectProposalV1,
    policy_tags=("interactive-execution",),
    implementation_owner="container-executor",
)


LEARNING_PLAN_DRAFT_CAPABILITY_ID = "learning.plan.draft"
LEARNING_PLAN_DRAFT_DESCRIPTOR = CapabilityDescriptor(
    capability_id=LEARNING_PLAN_DRAFT_CAPABILITY_ID,
    version="1.0.0",
    mode=CapabilityMode.READ,
    description="Validate and persist one bounded learning plan draft for the active planning session.",
    input_model=LearningPlanDraftCapabilityInput,
    result_model=LearningPlanDraftCapabilityOutput,
    policy_tags=("plan-drafting",),
)


LEARNING_PLAN_DRAFT_V110_DESCRIPTOR = CapabilityDescriptor(
    capability_id=LEARNING_PLAN_DRAFT_CAPABILITY_ID,
    version="1.1.0",
    mode=CapabilityMode.READ,
    description="Validate and persist one bounded material-aware learning plan draft for the active planning session.",
    input_model=LearningPlanDraftCapabilityInputV110,
    result_model=LearningPlanDraftCapabilityOutput,
    policy_tags=("plan-drafting",),
)


GROUNDING_RETRIEVE_CAPABILITY_ID = "grounding.retrieve"
GROUNDING_RETRIEVE_DESCRIPTOR = CapabilityDescriptor(
    capability_id=GROUNDING_RETRIEVE_CAPABILITY_ID,
    version="1.0.0",
    mode=CapabilityMode.READ,
    description="Retrieve bounded cited facts from the approved grounding source registry.",
    input_model=GroundingRetrieveInput,
    result_model=GroundingRetrieveOutput,
    policy_tags=("registry-grounding",),
)


def default_capability_descriptors() -> tuple[CapabilityDescriptor, ...]:
    """Return the approved bounded capability descriptors."""

    return (GROUNDING_RETRIEVE_DESCRIPTOR, LEARNING_PLAN_DRAFT_DESCRIPTOR, LEARNING_PLAN_DRAFT_V110_DESCRIPTOR)


def default_effect_descriptors() -> tuple[EffectDescriptor, ...]:
    """Return effect metadata only; a handler remains separately feature-gated."""

    return (
        RUNNER_EXECUTE_EFFECT_DESCRIPTOR,
        TUTOR_PLAN_ACTIVATE_EFFECT_DESCRIPTOR,
        TUTOR_PLAN_ROLLBACK_EFFECT_DESCRIPTOR,
        TUTOR_MEMORY_RECORD_EFFECT_DESCRIPTOR,
        TUTOR_ACTIVITY_RECORD_EFFECT_DESCRIPTOR,
    )
