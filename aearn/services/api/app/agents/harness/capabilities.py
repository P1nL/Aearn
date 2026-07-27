"""Immutable capability descriptors and bounded schemas for the Tutor catalog."""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


RUNNER_EXECUTE_EFFECT_TYPE = "runner.execute"
RUNNER_EXECUTE_EFFECT_DESCRIPTOR = EffectDescriptor(
    effect_type=RUNNER_EXECUTE_EFFECT_TYPE,
    version="1.0.0",
    description="Record one server-approved interactive execution intent for the isolated executor.",
    proposal_model=ExecutionEffectProposalV1,
    policy_tags=("interactive-execution",),
    implementation_owner="container-executor",
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

    return (GROUNDING_RETRIEVE_DESCRIPTOR,)


def default_effect_descriptors() -> tuple[EffectDescriptor, ...]:
    """Return effect metadata only; a handler remains separately feature-gated."""

    return (RUNNER_EXECUTE_EFFECT_DESCRIPTOR,)
