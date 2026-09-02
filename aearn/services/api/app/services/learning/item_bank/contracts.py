"""Strict, versioned contracts for the Git-owned Learning Item Bank."""
from __future__ import annotations

import hashlib
import json
import math
import re
from enum import StrEnum
from typing import Annotated, Literal, Mapping, Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aearn_shared.execution import (
    MAX_TABLE_RESULT_PAYLOAD_BYTES,
    SafeTableResultCellV1,
    SafeTableResultPresentationV1,
)

from app.services.learning.practice.model_review_contracts import (
    ModelCodeReviewSubmissionV1,
    ModelReviewArtifactV1,
    ModelReviewArtifactV2,
    ModelReviewPromptV1,
    ModelReviewRubricV1,
)


LEARNING_ITEM_SOURCE_SCHEMA_VERSION: Literal["learning_item_source_v1"] = "learning_item_source_v1"
LEARNING_ITEM_BLUEPRINT_SCHEMA_VERSION: Literal["learning_item_blueprint_v1"] = "learning_item_blueprint_v1"
LEARNING_ITEM_PUBLIC_SCHEMA_VERSION: Literal["learning_item_public_v1"] = "learning_item_public_v1"
LEARNING_ITEM_PRIVATE_SCHEMA_VERSION: Literal["learning_item_private_v1"] = "learning_item_private_v1"
LEARNING_ITEM_VALIDATION_SCHEMA_VERSION: Literal["learning_item_validation_v1"] = "learning_item_validation_v1"
LEARNING_ITEM_COMPILER_VERSION: Literal["learning_item_compiler_v1"] = "learning_item_compiler_v1"
LEARNING_ITEM_VALIDATION_POLICY_VERSION: Literal["learning_item_validation_policy_v1"] = "learning_item_validation_policy_v1"

_STABLE_KEY = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,159}$")
_HANDLE = re.compile(r"^li:[0-9a-f]{64}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SQL_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LearningItemKind(StrEnum):
    CODE = "code"
    SQL = "sql"
    DEMO = "demo"
    KNOWLEDGE_CHECK = "knowledge_check"
    MODEL_REVIEW = "model_review"


class LearningItemPurpose(StrEnum):
    EXERCISE = "exercise"
    DEMONSTRATION = "demonstration"
    KNOWLEDGE_CHECK = "knowledge_check"
    REMEDIATION = "remediation"
    TRANSFER_CHECK = "transfer_check"
    CODE_REVIEW = "code_review"
    SQL_EXPLORATION = "sql_exploration"


class LearningItemDifficulty(StrEnum):
    D1 = "D1"
    D2 = "D2"
    D3 = "D3"
    D4 = "D4"
    D5 = "D5"


class LearningItemRiskTier(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class LearningItemReviewRole(StrEnum):
    CURRICULUM = "curriculum"
    DIFFICULTY = "difficulty"
    TECHNICAL = "technical"
    AMBIGUITY = "ambiguity"
    SECURITY = "security"
    ADVERSARIAL = "adversarial"


class LearningItemInteraction(StrEnum):
    EDIT = "edit"
    RUN = "run"
    QUERY = "query"
    RESPOND = "respond"
    REVIEW = "review"
    OBSERVE = "observe"


class LearningItemValidationCheckType(StrEnum):
    SCHEMA = "schema"
    SOURCE_REFERENCES = "source_references"
    DIFFICULTY_PROFILE = "difficulty_profile"
    PUBLIC_PRIVATE_BOUNDARY = "public_private_boundary"
    MARKDOWN_SAFETY = "markdown_safety"
    HINT_LEAKAGE = "hint_leakage"
    PRACTICE_CONTRACT = "practice_contract"
    STANDARD_ANSWER = "standard_answer"
    STARTER_NOT_PASSING = "starter_not_passing"
    RUNTIME_OR_EVENT = "runtime_or_event"
    SCORER = "scorer"


REQUIRED_LEARNING_ITEM_VALIDATION_CHECKS: tuple[
    LearningItemValidationCheckType, ...
] = tuple(LearningItemValidationCheckType)


class LearningItemSourceReferenceV1(_StrictModel):
    source_id: str = Field(min_length=1, max_length=160)
    source_version: str = Field(min_length=1, max_length=160)
    locator: str = Field(min_length=1, max_length=320)
    content_hash: str = Field(min_length=64, max_length=64)

    @field_validator("source_id", "source_version")
    @classmethod
    def validate_key(cls, value: str) -> str:
        return stable_key(value, label="source reference key")

    @field_validator("locator")
    @classmethod
    def validate_locator(cls, value: str) -> str:
        return bounded_text(value, label="source locator", maximum=320)

    @field_validator("content_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return require_sha256(value, label="source content hash")


class LearningItemDifficultyProfileV1(_StrictModel):
    base: LearningItemDifficulty
    reasoning_depth: int = Field(ge=1, le=5)
    concept_count: int = Field(ge=1, le=5)
    context_novelty: int = Field(ge=1, le=5)
    transfer_distance: int = Field(ge=1, le=5)
    response_complexity: int = Field(ge=1, le=5)
    scaffolding: int = Field(ge=1, le=5)

    @property
    def computed_base(self) -> LearningItemDifficulty:
        score = (
            self.reasoning_depth
            + self.concept_count
            + self.context_novelty
            + self.transfer_distance
            + self.response_complexity
            + (6 - self.scaffolding)
        ) / 6
        band = max(1, min(5, int(score + 0.5)))
        return LearningItemDifficulty(f"D{band}")


class LearningItemPublicationPolicyV1(_StrictModel):
    risk_tier: LearningItemRiskTier
    required_review_roles: tuple[LearningItemReviewRole, ...] = Field(min_length=1, max_length=6)
    agent_review_required: Literal[True] = True
    pilot_required: Literal[True] = True
    human_approval_required: bool

    @field_validator("required_review_roles")
    @classmethod
    def validate_roles(
        cls,
        values: tuple[LearningItemReviewRole, ...],
    ) -> tuple[LearningItemReviewRole, ...]:
        required = tuple(LearningItemReviewRole)
        if values != required:
            raise ValueError("publication policy must require all six review roles in canonical order")
        return values

    @model_validator(mode="after")
    def validate_risk_policy(self) -> "LearningItemPublicationPolicyV1":
        if self.risk_tier is LearningItemRiskTier.HIGH and not self.human_approval_required:
            raise ValueError("high-risk learning items require human approval")
        if self.risk_tier is not LearningItemRiskTier.HIGH and self.human_approval_required:
            raise ValueError("only high-risk learning items may require human approval")
        return self


class LearningItemRemediationPolicyV1(_StrictModel):
    first_failure: Literal["hint_then_remediate", "explain_then_remediate", "direct_explanation"]
    second_failure: Literal["explain_then_transfer", "direct_explanation"]
    successor_item_key: str | None = Field(default=None, min_length=1, max_length=160)

    @field_validator("successor_item_key")
    @classmethod
    def validate_successor(cls, value: str | None) -> str | None:
        return stable_key(value, label="remediation successor") if value is not None else None


class LearningItemBlueprintV1(_StrictModel):
    schema_version: Literal["learning_item_blueprint_v1"] = LEARNING_ITEM_BLUEPRINT_SCHEMA_VERSION
    blueprint_key: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=1, max_length=160)
    knowledge_key: str = Field(min_length=1, max_length=160)
    item_kind: LearningItemKind
    purpose: LearningItemPurpose
    language_id: str = Field(min_length=1, max_length=160)
    difficulty_profile: LearningItemDifficultyProfileV1
    prerequisite_keys: tuple[str, ...] = Field(default=(), max_length=24)
    required_capabilities: tuple[str, ...] = Field(min_length=1, max_length=24)
    runtime_profile_id: str | None = Field(default=None, min_length=1, max_length=160)
    allowed_interactions: tuple[LearningItemInteraction, ...] = Field(min_length=1, max_length=6)
    remediation_policy: LearningItemRemediationPolicyV1 | None = None
    publication_policy: LearningItemPublicationPolicyV1
    source_references: tuple[LearningItemSourceReferenceV1, ...] = Field(min_length=1, max_length=12)

    @field_validator("blueprint_key", "version", "knowledge_key", "language_id")
    @classmethod
    def validate_keys(cls, value: str) -> str:
        return stable_key(value, label="blueprint key")

    @field_validator("runtime_profile_id")
    @classmethod
    def validate_runtime_profile(cls, value: str | None) -> str | None:
        return stable_key(value, label="runtime profile") if value is not None else None

    @field_validator("prerequisite_keys", "required_capabilities")
    @classmethod
    def validate_key_list(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(stable_key(value, label="blueprint list key") for value in values)
        if len(normalized) != len(set(normalized)):
            raise ValueError("blueprint key lists must be unique")
        return normalized

    @field_validator("allowed_interactions")
    @classmethod
    def validate_interactions(
        cls,
        values: tuple[LearningItemInteraction, ...],
    ) -> tuple[LearningItemInteraction, ...]:
        if len(values) != len(set(values)):
            raise ValueError("allowed interactions must be unique")
        return values

    @field_validator("source_references")
    @classmethod
    def validate_sources(
        cls,
        values: tuple[LearningItemSourceReferenceV1, ...],
    ) -> tuple[LearningItemSourceReferenceV1, ...]:
        identities = tuple((item.source_id, item.source_version, item.locator) for item in values)
        if len(identities) != len(set(identities)):
            raise ValueError("source references must be unique")
        return values

    @model_validator(mode="after")
    def validate_shape(self) -> "LearningItemBlueprintV1":
        purpose_by_kind = {
            LearningItemKind.CODE: {
                LearningItemPurpose.EXERCISE,
                LearningItemPurpose.REMEDIATION,
                LearningItemPurpose.TRANSFER_CHECK,
            },
            LearningItemKind.SQL: {
                LearningItemPurpose.EXERCISE,
                LearningItemPurpose.REMEDIATION,
                LearningItemPurpose.TRANSFER_CHECK,
                LearningItemPurpose.SQL_EXPLORATION,
            },
            LearningItemKind.DEMO: {LearningItemPurpose.DEMONSTRATION},
            LearningItemKind.KNOWLEDGE_CHECK: {
                LearningItemPurpose.KNOWLEDGE_CHECK,
                LearningItemPurpose.REMEDIATION,
                LearningItemPurpose.TRANSFER_CHECK,
            },
            LearningItemKind.MODEL_REVIEW: {
                LearningItemPurpose.CODE_REVIEW,
                LearningItemPurpose.REMEDIATION,
            },
        }
        if self.purpose not in purpose_by_kind[self.item_kind]:
            raise ValueError("learning item purpose is incompatible with item kind")
        if self.item_kind in {LearningItemKind.CODE, LearningItemKind.SQL, LearningItemKind.DEMO}:
            if self.runtime_profile_id is None:
                raise ValueError("runtime-backed learning item needs a runtime profile")
        elif self.runtime_profile_id is not None:
            raise ValueError("static learning item cannot declare a runtime profile")
        if frozenset(self.allowed_interactions) != _expected_interactions(self.item_kind):
            raise ValueError("learning item interactions do not match item kind")
        return self

    @property
    def blueprint_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


class LearningItemHintV1(_StrictModel):
    level: Literal[1, 2, 3]
    markdown: str = Field(min_length=1, max_length=2_000)

    @field_validator("markdown")
    @classmethod
    def normalize_markdown(cls, value: str) -> str:
        return normalized_text(value, label="hint markdown", maximum=2_000)


class LearningItemOptionV1(_StrictModel):
    option_id: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=480)

    @field_validator("option_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return stable_key(value, label="option id")

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        return normalized_text(value, label="option label", maximum=480)


class LearningItemCodePatternV1(_StrictModel):
    type: Literal["literal", "regex"]
    value: str = Field(min_length=1, max_length=2_000)

    @field_validator("value")
    @classmethod
    def normalize_value(cls, value: str) -> str:
        return normalized_code(value, label="code pattern", maximum=2_000)


class LearningItemCodeBlankV1(_StrictModel):
    blank_key: str = Field(min_length=1, max_length=160)
    expected_concept: str = Field(min_length=1, max_length=240)
    acceptable_patterns: tuple[LearningItemCodePatternV1, ...] = Field(min_length=1, max_length=12)
    is_core: bool = True

    @field_validator("blank_key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        return stable_key(value, label="blank key")

    @field_validator("expected_concept")
    @classmethod
    def normalize_concept(cls, value: str) -> str:
        return normalized_text(value, label="expected concept", maximum=240)


class LearningItemDemoEventV1(_StrictModel):
    event_name: str = Field(min_length=1, max_length=160)
    payload_json: dict[str, object] = Field(default_factory=dict)

    @field_validator("event_name")
    @classmethod
    def validate_event_name(cls, value: str) -> str:
        return stable_key(value, label="demo event name")

    @field_validator("payload_json")
    @classmethod
    def validate_payload(cls, value: dict[str, object]) -> dict[str, object]:
        return validate_demo_event_payload(value)


class LearningItemDemoStepV2(_StrictModel):
    step_key: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=160)
    instruction_markdown: str = Field(min_length=1, max_length=2_000)
    source_code: str = Field(min_length=1, max_length=48_000)
    duration_seconds: int | None = Field(default=None, ge=6, le=30)

    @field_validator("step_key")
    @classmethod
    def validate_step_key(cls, value: str) -> str:
        return stable_key(value, label="demo step key")

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return bounded_text(value, label="demo step title", maximum=160)

    @field_validator("instruction_markdown")
    @classmethod
    def normalize_instruction(cls, value: str) -> str:
        return normalized_text(value, label="demo step instruction", maximum=2_000)

    @field_validator("source_code")
    @classmethod
    def normalize_source(cls, value: str) -> str:
        return normalized_code(value, label="demo step source", maximum=48_000)


class LearningItemCodeContentV1(_StrictModel):
    type: Literal["code"] = "code"
    language_id: str = Field(min_length=1, max_length=160)
    editor_language: str = Field(min_length=1, max_length=80)
    exercise_type: Literal["code_completion", "browser_preview"]
    starter_code: str = Field(min_length=1, max_length=48_000)
    code_blanks: tuple[LearningItemCodeBlankV1, ...] = Field(min_length=1, max_length=24)
    required_patterns: tuple[str, ...] = Field(default=(), max_length=24)
    browser_rule_family: Literal["js_event_flow", "static_preview"] | None = None
    preview_html: dict[str, str] = Field(default_factory=dict)

    @field_validator("language_id", "editor_language")
    @classmethod
    def validate_keys(cls, value: str) -> str:
        return stable_key(value, label="code language")

    @field_validator("starter_code")
    @classmethod
    def normalize_starter(cls, value: str) -> str:
        return normalized_code(value, label="starter code", maximum=48_000)

    @field_validator("required_patterns")
    @classmethod
    def validate_patterns(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(
            normalized_code(value, label="required pattern", maximum=2_000)
            for value in values
        )
        if len(normalized) != len(set(normalized)):
            raise ValueError("required patterns must be unique")
        return normalized

    @field_validator("preview_html")
    @classmethod
    def validate_preview(cls, value: dict[str, str]) -> dict[str, str]:
        if set(value) - {"success", "failure"}:
            raise ValueError("preview_html has unknown keys")
        return {
            key: normalized_code(item, label="preview HTML", maximum=12_000)
            for key, item in value.items()
        }

    @model_validator(mode="after")
    def validate_browser_shape(self) -> "LearningItemCodeContentV1":
        if self.exercise_type == "browser_preview" and self.browser_rule_family is None:
            raise ValueError("browser preview item requires a browser rule family")
        if self.exercise_type == "code_completion" and self.browser_rule_family is not None:
            raise ValueError("non-browser code item cannot declare a browser rule family")
        keys = tuple(item.blank_key for item in self.code_blanks)
        if len(keys) != len(set(keys)):
            raise ValueError("code blank keys must be unique")
        return self


class LearningItemSqlContentV1(_StrictModel):
    type: Literal["sql"] = "sql"
    dialect: Literal["sqlite"] = "sqlite"
    starter_query: str = Field(min_length=1, max_length=48_000)
    schema_markdown: str = Field(min_length=1, max_length=12_000)
    comparison: Literal["ordered", "unordered"] = "ordered"
    max_rows: int = Field(default=50, ge=1, le=200)

    @field_validator("starter_query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        return normalized_code(value, label="starter query", maximum=48_000)

    @field_validator("schema_markdown")
    @classmethod
    def normalize_schema(cls, value: str) -> str:
        return normalized_text(value, label="schema markdown", maximum=12_000)


class LearningItemSqlColumnV2(_StrictModel):
    name: str = Field(min_length=1, max_length=64)
    data_type: Literal["INTEGER", "REAL", "TEXT"]
    nullable: bool = True
    primary_key: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not _SQL_IDENTIFIER.fullmatch(value):
            raise ValueError("SQL column name must be a simple bounded identifier")
        return value

    @model_validator(mode="after")
    def validate_primary_key(self) -> "LearningItemSqlColumnV2":
        if self.primary_key and self.nullable:
            raise ValueError("SQL primary-key columns cannot be nullable")
        return self


class LearningItemSqlForeignKeyV2(_StrictModel):
    column: str = Field(min_length=1, max_length=64)
    references_table: str = Field(min_length=1, max_length=64)
    references_column: str = Field(min_length=1, max_length=64)

    @field_validator("column", "references_table", "references_column")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        if not _SQL_IDENTIFIER.fullmatch(value):
            raise ValueError("SQL foreign-key identifiers must be simple and bounded")
        return value


class LearningItemSqlTableV2(_StrictModel):
    name: str = Field(min_length=1, max_length=64)
    columns: tuple[LearningItemSqlColumnV2, ...] = Field(min_length=1, max_length=32)
    foreign_keys: tuple[LearningItemSqlForeignKeyV2, ...] = Field(default=(), max_length=16)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not _SQL_IDENTIFIER.fullmatch(value):
            raise ValueError("SQL table name must be a simple bounded identifier")
        return value

    @model_validator(mode="after")
    def validate_table(self) -> "LearningItemSqlTableV2":
        column_names = tuple(item.name for item in self.columns)
        if len(column_names) != len(set(column_names)):
            raise ValueError("SQL table columns must be unique")
        foreign_columns = tuple(item.column for item in self.foreign_keys)
        if len(foreign_columns) != len(set(foreign_columns)):
            raise ValueError("SQL table foreign-key columns must be unique")
        if any(item.column not in column_names for item in self.foreign_keys):
            raise ValueError("SQL foreign key must reference a local column")
        return self


class LearningItemSqlDatasetTableV2(_StrictModel):
    table: str = Field(min_length=1, max_length=64)
    rows: tuple[tuple[SafeTableResultCellV1, ...], ...] = Field(default=(), max_length=200)

    @field_validator("table")
    @classmethod
    def validate_table_name(cls, value: str) -> str:
        if not _SQL_IDENTIFIER.fullmatch(value):
            raise ValueError("SQL dataset table must be a simple bounded identifier")
        return value


class LearningItemSqlDatasetV2(_StrictModel):
    tables: tuple[LearningItemSqlDatasetTableV2, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_tables(self) -> "LearningItemSqlDatasetV2":
        names = tuple(item.table for item in self.tables)
        if len(names) != len(set(names)):
            raise ValueError("SQL dataset tables must be unique")
        payload = canonical_json(self.model_dump(mode="json")).encode("utf-8")
        if len(payload) > MAX_TABLE_RESULT_PAYLOAD_BYTES:
            raise ValueError("SQL dataset exceeds the bounded payload size")
        return self


class LearningItemSqlContentV2(_StrictModel):
    type: Literal["sql_v2"] = "sql_v2"
    dialect: Literal["sqlite"] = "sqlite"
    starter_query: str = Field(min_length=1, max_length=48_000)
    tables: tuple[LearningItemSqlTableV2, ...] = Field(min_length=1, max_length=8)
    public_dataset: LearningItemSqlDatasetV2
    comparison: Literal["ordered", "unordered"] = "ordered"
    max_rows: int = Field(default=50, ge=1, le=200)

    @field_validator("starter_query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        return normalized_code(value, label="starter query", maximum=48_000)

    @model_validator(mode="after")
    def validate_schema_and_dataset(self) -> "LearningItemSqlContentV2":
        _validate_sql_schema(self.tables)
        _validate_sql_dataset(self.tables, self.public_dataset, maximum_rows=50)
        return self


class LearningItemDemoContentV1(_StrictModel):
    type: Literal["demo"] = "demo"
    language_id: str = Field(min_length=1, max_length=160)
    source_code: str = Field(min_length=1, max_length=48_000)
    read_only: Literal[True] = True
    completion_mode: Literal["exact_event", "static_duration"]
    expected_event: LearningItemDemoEventV1 | None = None
    duration_seconds: int | None = Field(default=None, ge=6, le=30)

    @field_validator("language_id")
    @classmethod
    def validate_language(cls, value: str) -> str:
        return stable_key(value, label="demo language")

    @field_validator("source_code")
    @classmethod
    def normalize_source(cls, value: str) -> str:
        return normalized_code(value, label="demo source", maximum=48_000)

    @model_validator(mode="after")
    def validate_completion(self) -> "LearningItemDemoContentV1":
        if self.completion_mode == "exact_event":
            if self.expected_event is None or self.duration_seconds is not None:
                raise ValueError("exact-event demo requires only an expected event")
        elif self.expected_event is not None or self.duration_seconds is None:
            raise ValueError("static demo requires only a bounded duration")
        return self


class LearningItemDemoContentV2(_StrictModel):
    type: Literal["demo_v2"] = "demo_v2"
    language_id: str = Field(min_length=1, max_length=160)
    source_version: str = Field(min_length=1, max_length=160)
    read_only: Literal[True] = True
    completion_mode: Literal["exact_event", "static_duration"]
    steps: tuple[LearningItemDemoStepV2, ...] = Field(min_length=1, max_length=8)
    expected_event: LearningItemDemoEventV1 | None = None

    @field_validator("language_id", "source_version")
    @classmethod
    def validate_keys(cls, value: str) -> str:
        return stable_key(value, label="demo descriptor key")

    @field_validator("steps")
    @classmethod
    def validate_steps(
        cls,
        values: tuple[LearningItemDemoStepV2, ...],
    ) -> tuple[LearningItemDemoStepV2, ...]:
        keys = tuple(item.step_key for item in values)
        if len(keys) != len(set(keys)):
            raise ValueError("demo step keys must be unique")
        if sum(len(item.source_code) for item in values) > 48_000:
            raise ValueError("demo descriptor source is too large")
        return values

    @model_validator(mode="after")
    def validate_completion(self) -> "LearningItemDemoContentV2":
        durations = tuple(item.duration_seconds for item in self.steps)
        if self.completion_mode == "exact_event":
            if self.expected_event is None or len(self.steps) != 1 or any(
                item is not None for item in durations
            ):
                raise ValueError(
                    "exact-event demo requires one untimed step and one expected event"
                )
        elif self.expected_event is not None:
            raise ValueError("static demo cannot declare an expected event")
        return self


class LearningItemKnowledgeCheckContentV1(_StrictModel):
    type: Literal["knowledge_check"] = "knowledge_check"
    response_kind: Literal[
        "single_choice", "multiple_choice", "prediction", "ordering", "code_range", "short_text"
    ]
    prompt_markdown: str = Field(min_length=1, max_length=8_000)
    options: tuple[LearningItemOptionV1, ...] = Field(default=(), max_length=12)

    @field_validator("prompt_markdown")
    @classmethod
    def normalize_prompt(cls, value: str) -> str:
        return normalized_text(value, label="knowledge-check prompt", maximum=8_000)

    @model_validator(mode="after")
    def validate_options(self) -> "LearningItemKnowledgeCheckContentV1":
        ids = tuple(item.option_id for item in self.options)
        labels = tuple(normalize_answer(item.label) for item in self.options)
        if len(ids) != len(set(ids)) or len(labels) != len(set(labels)):
            raise ValueError("knowledge-check options must be unique")
        option_kinds = {"single_choice", "multiple_choice", "ordering"}
        if self.response_kind not in option_kinds and self.options:
            raise ValueError("text, prediction, and code-range checks cannot declare options")
        if self.response_kind in option_kinds and not 2 <= len(self.options) <= 12:
            raise ValueError("choice and ordering checks require 2..12 options")
        return self


class LearningItemModelReviewContentV1(_StrictModel):
    type: Literal["model_review"] = "model_review"
    prompt: ModelReviewPromptV1
    artifact: ModelReviewArtifactV1


class LearningItemModelReviewContentV2(_StrictModel):
    type: Literal["model_review_v2"] = "model_review_v2"
    prompt: ModelReviewPromptV1
    artifact: ModelReviewArtifactV2


LearningItemPublicContentV1 = Annotated[
    LearningItemCodeContentV1
    | LearningItemSqlContentV1
    | LearningItemSqlContentV2
    | LearningItemDemoContentV1
    | LearningItemDemoContentV2
    | LearningItemKnowledgeCheckContentV1
    | LearningItemModelReviewContentV1
    | LearningItemModelReviewContentV2,
    Field(discriminator="type"),
]


class LearningItemPublicV1(_StrictModel):
    schema_version: Literal["learning_item_public_v1"] = LEARNING_ITEM_PUBLIC_SCHEMA_VERSION
    item_key: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=1, max_length=160)
    kind: LearningItemKind
    purpose: LearningItemPurpose
    title: str = Field(min_length=1, max_length=240)
    difficulty: LearningItemDifficulty
    instruction_markdown: str = Field(min_length=1, max_length=8_000)
    allowed_interactions: tuple[LearningItemInteraction, ...] = Field(min_length=1, max_length=6)
    hints: tuple[LearningItemHintV1, ...] = Field(default=(), max_length=3)
    remediation_item_key: str | None = Field(default=None, min_length=1, max_length=160)
    source_references: tuple[LearningItemSourceReferenceV1, ...] = Field(min_length=1, max_length=12)
    content: LearningItemPublicContentV1

    @field_validator("item_key", "version")
    @classmethod
    def validate_keys(cls, value: str) -> str:
        return stable_key(value, label="learning item identity")

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return bounded_text(value, label="learning item title", maximum=240)

    @field_validator("instruction_markdown")
    @classmethod
    def normalize_instruction(cls, value: str) -> str:
        return normalized_text(value, label="instruction markdown", maximum=8_000)

    @field_validator("remediation_item_key")
    @classmethod
    def validate_remediation(cls, value: str | None) -> str | None:
        return stable_key(value, label="remediation item key") if value is not None else None

    @field_validator("allowed_interactions")
    @classmethod
    def validate_interactions(
        cls,
        values: tuple[LearningItemInteraction, ...],
    ) -> tuple[LearningItemInteraction, ...]:
        if len(values) != len(set(values)):
            raise ValueError("public item interactions must be unique")
        return values

    @field_validator("hints")
    @classmethod
    def validate_hints(cls, values: tuple[LearningItemHintV1, ...]) -> tuple[LearningItemHintV1, ...]:
        levels = tuple(item.level for item in values)
        if levels != tuple(range(1, len(values) + 1)):
            raise ValueError("hint levels must be unique and contiguous from H1")
        return values

    @model_validator(mode="after")
    def validate_kind_shape(self) -> "LearningItemPublicV1":
        if _content_kind(self.content) is not self.kind:
            raise ValueError("public item kind does not match content")
        if frozenset(self.allowed_interactions) != _expected_interactions(self.kind):
            raise ValueError("public item interactions do not match kind")
        return self

    @property
    def public_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


class LearningItemRuntimeTestCaseV1(_StrictModel):
    id: str = Field(min_length=1, max_length=160)
    case_type: Literal["visible", "hidden", "preview_assertion"]
    input_json: dict[str, object] = Field(default_factory=dict)
    expected_output_json: dict[str, object] = Field(default_factory=dict)
    weight: float = Field(default=1.0, gt=0, le=100)
    is_critical: bool = False
    order_index: int = Field(ge=0, le=1_000)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return stable_key(value, label="test case id")

    @field_validator("input_json", "expected_output_json")
    @classmethod
    def validate_json(cls, value: dict[str, object]) -> dict[str, object]:
        require_json_object(value, label="test case JSON", maximum=32_000)
        return value


class LearningItemScorePolicyV1(_StrictModel):
    kind: Literal["all_tests", "static_exact", "model_code_review"]
    policy_version: str = Field(min_length=1, max_length=160)
    threshold: float = Field(gt=0, le=1)

    @field_validator("policy_version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        return stable_key(value, label="score policy version")


class LearningItemCodePrivateV1(_StrictModel):
    type: Literal["code"] = "code"
    standard_answer: str = Field(min_length=1, max_length=48_000)
    tests: tuple[LearningItemRuntimeTestCaseV1, ...] = Field(min_length=1, max_length=48)
    score_policy: LearningItemScorePolicyV1

    @field_validator("standard_answer")
    @classmethod
    def normalize_answer_code(cls, value: str) -> str:
        return normalized_code(value, label="code standard answer", maximum=48_000)

    @model_validator(mode="after")
    def validate_tests(self) -> "LearningItemCodePrivateV1":
        _require_test_bundle(self.tests)
        if self.score_policy.kind != "all_tests":
            raise ValueError("code item requires all-tests score policy")
        return self


class LearningItemSqlPrivateV1(_StrictModel):
    type: Literal["sql"] = "sql"
    standard_query: str = Field(min_length=1, max_length=48_000)
    setup_sql: tuple[str, ...] = Field(min_length=1, max_length=24)
    tests: tuple[LearningItemRuntimeTestCaseV1, ...] = Field(min_length=1, max_length=48)
    score_policy: LearningItemScorePolicyV1

    @field_validator("standard_query")
    @classmethod
    def normalize_standard_query(cls, value: str) -> str:
        return normalized_code(value, label="SQL standard answer", maximum=48_000)

    @field_validator("setup_sql")
    @classmethod
    def normalize_setup(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(normalized_code(value, label="SQL setup", maximum=48_000) for value in values)

    @model_validator(mode="after")
    def validate_tests(self) -> "LearningItemSqlPrivateV1":
        _require_test_bundle(self.tests)
        if self.score_policy.kind != "all_tests":
            raise ValueError("SQL item requires all-tests score policy")
        return self


class LearningItemSqlTestCaseV2(_StrictModel):
    id: str = Field(min_length=1, max_length=160)
    case_type: Literal["visible", "hidden"]
    dataset: LearningItemSqlDatasetV2
    expected_output: SafeTableResultPresentationV1
    weight: float = Field(default=1.0, gt=0, le=100)
    is_critical: bool = False
    order_index: int = Field(ge=0, le=1_000)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return stable_key(value, label="SQL test case id")


class LearningItemSqlPrivateV2(_StrictModel):
    type: Literal["sql_v2"] = "sql_v2"
    standard_query: str = Field(min_length=1, max_length=48_000)
    tests: tuple[LearningItemSqlTestCaseV2, ...] = Field(min_length=1, max_length=48)
    score_policy: LearningItemScorePolicyV1

    @field_validator("standard_query")
    @classmethod
    def normalize_standard_query(cls, value: str) -> str:
        return normalized_code(value, label="SQL standard answer", maximum=48_000)

    @model_validator(mode="after")
    def validate_tests(self) -> "LearningItemSqlPrivateV2":
        _require_sql_test_bundle(self.tests)
        if self.score_policy.kind != "all_tests":
            raise ValueError("SQL item requires all-tests score policy")
        return self


class LearningItemDemoPrivateV1(_StrictModel):
    type: Literal["demo"] = "demo"
    expected_events: tuple[LearningItemDemoEventV1, ...] = Field(default=(), max_length=8)
    validation_policy_version: str = Field(min_length=1, max_length=160)

    @field_validator("validation_policy_version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        return stable_key(value, label="demo validation policy")


class LearningItemDemoPrivateV2(_StrictModel):
    type: Literal["demo_v2"] = "demo_v2"
    expected_events: tuple[LearningItemDemoEventV1, ...] = Field(default=(), max_length=1)
    validation_policy_version: str = Field(min_length=1, max_length=160)

    @field_validator("validation_policy_version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        return stable_key(value, label="demo validation policy")


class LearningItemKnowledgeCheckPrivateV1(_StrictModel):
    type: Literal["knowledge_check"] = "knowledge_check"
    accepted_answers: tuple[str, ...] = Field(min_length=1, max_length=12)
    answer_explanation_markdown: str = Field(min_length=1, max_length=4_000)
    tests: tuple[LearningItemRuntimeTestCaseV1, ...] = Field(min_length=1, max_length=24)
    score_policy: LearningItemScorePolicyV1

    @field_validator("accepted_answers")
    @classmethod
    def validate_answers(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(bounded_text(value, label="accepted answer", maximum=480) for value in values)
        identities = tuple(normalize_answer(value) for value in normalized)
        if len(identities) != len(set(identities)):
            raise ValueError("accepted answers must be unique")
        return normalized

    @field_validator("answer_explanation_markdown")
    @classmethod
    def normalize_explanation(cls, value: str) -> str:
        return normalized_text(value, label="answer explanation", maximum=4_000)

    @model_validator(mode="after")
    def validate_tests(self) -> "LearningItemKnowledgeCheckPrivateV1":
        _require_test_bundle(self.tests)
        if self.score_policy.kind != "static_exact":
            raise ValueError("knowledge check requires static-exact score policy")
        return self


class LearningItemModelReviewPrivateV1(_StrictModel):
    type: Literal["model_review"] = "model_review"
    rubric: ModelReviewRubricV1
    reference_submission: ModelCodeReviewSubmissionV1
    tests: tuple[LearningItemRuntimeTestCaseV1, ...] = Field(min_length=1, max_length=48)
    score_policy: LearningItemScorePolicyV1
    validation_profile_version: str = Field(min_length=1, max_length=160)

    @field_validator("validation_profile_version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        return stable_key(value, label="model review validation profile")

    @model_validator(mode="after")
    def validate_tests(self) -> "LearningItemModelReviewPrivateV1":
        _require_test_bundle(self.tests)
        if self.score_policy.kind != "model_code_review":
            raise ValueError("model review requires model-review score policy")
        return self


LearningItemPrivateContentV1 = Annotated[
    LearningItemCodePrivateV1
    | LearningItemSqlPrivateV1
    | LearningItemSqlPrivateV2
    | LearningItemDemoPrivateV1
    | LearningItemDemoPrivateV2
    | LearningItemKnowledgeCheckPrivateV1
    | LearningItemModelReviewPrivateV1,
    Field(discriminator="type"),
]


class LearningItemPrivateV1(_StrictModel):
    schema_version: Literal["learning_item_private_v1"] = LEARNING_ITEM_PRIVATE_SCHEMA_VERSION
    item_key: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=1, max_length=160)
    kind: LearningItemKind
    content: LearningItemPrivateContentV1

    @field_validator("item_key", "version")
    @classmethod
    def validate_keys(cls, value: str) -> str:
        return stable_key(value, label="private item identity")

    @model_validator(mode="after")
    def validate_kind_shape(self) -> "LearningItemPrivateV1":
        if _content_kind(self.content) is not self.kind:
            raise ValueError("private item kind does not match content")
        return self

    @property
    def private_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


class LearningItemSourceV1(_StrictModel):
    schema_version: Literal["learning_item_source_v1"] = LEARNING_ITEM_SOURCE_SCHEMA_VERSION
    blueprint: LearningItemBlueprintV1
    public: LearningItemPublicV1
    private: LearningItemPrivateV1

    @model_validator(mode="after")
    def validate_identity(self) -> "LearningItemSourceV1":
        if (self.public.item_key, self.public.version, self.public.kind) != (
            self.private.item_key,
            self.private.version,
            self.private.kind,
        ):
            raise ValueError("public and private item identity must match")
        if self.blueprint.item_kind is not self.public.kind:
            raise ValueError("blueprint item kind does not match item")
        if self.blueprint.purpose is not self.public.purpose:
            raise ValueError("blueprint purpose does not match item")
        if self.blueprint.difficulty_profile.base is not self.public.difficulty:
            raise ValueError("blueprint difficulty does not match item")
        if self.blueprint.allowed_interactions != self.public.allowed_interactions:
            raise ValueError("blueprint interactions do not match item")
        if self.blueprint.source_references != self.public.source_references:
            raise ValueError("blueprint source references do not match item")
        content_language = _content_language(self.public.content)
        if content_language is not None and content_language != self.blueprint.language_id:
            raise ValueError("blueprint language does not match item content")
        if self.public.remediation_item_key != (
            self.blueprint.remediation_policy.successor_item_key
            if self.blueprint.remediation_policy is not None
            else None
        ):
            raise ValueError("public remediation identity does not match blueprint")
        if isinstance(self.public.content, LearningItemSqlContentV2):
            if not isinstance(self.private.content, LearningItemSqlPrivateV2):
                raise ValueError("SQL v2 public content requires SQL v2 private content")
            for test in self.private.content.tests:
                _validate_sql_dataset(
                    self.public.content.tables,
                    test.dataset,
                    maximum_rows=200,
                )
        return self

    @property
    def source_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))

    @property
    def content_hash(self) -> str:
        return canonical_hash(
            {
                "item_key": self.public.item_key,
                "version": self.public.version,
                "blueprint_hash": self.blueprint.blueprint_hash,
                "public_hash": self.public.public_hash,
                "private_hash": self.private.private_hash,
            }
        )


class LearningItemVersionIdentityV1(_StrictModel):
    item_key: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=1, max_length=160)
    content_hash: str = Field(min_length=64, max_length=64)
    handle: str = Field(min_length=67, max_length=67)

    @field_validator("item_key", "version")
    @classmethod
    def validate_keys(cls, value: str) -> str:
        return stable_key(value, label="version identity")

    @field_validator("content_hash")
    @classmethod
    def validate_content_hash(cls, value: str) -> str:
        return require_sha256(value, label="item content hash")

    @field_validator("handle")
    @classmethod
    def validate_handle(cls, value: str) -> str:
        if not _HANDLE.fullmatch(value):
            raise ValueError("learning item handle is invalid")
        return value

    @model_validator(mode="after")
    def validate_derived_handle(self) -> "LearningItemVersionIdentityV1":
        expected = learning_item_handle(self.item_key, self.version, self.content_hash)
        if self.handle != expected:
            raise ValueError("learning item handle does not match identity")
        return self


class LearningItemValidationCheckV1(_StrictModel):
    check_type: LearningItemValidationCheckType
    status: Literal["passed", "failed", "not_applicable"]
    safe_code: str | None = Field(default=None, min_length=1, max_length=160)
    proof_hash: str = Field(min_length=64, max_length=64)

    @field_validator("safe_code")
    @classmethod
    def validate_safe_code(cls, value: str | None) -> str | None:
        return stable_key(value, label="validation safe code") if value is not None else None

    @field_validator("proof_hash")
    @classmethod
    def validate_proof(cls, value: str) -> str:
        return require_sha256(value, label="validation proof hash")

    @model_validator(mode="after")
    def validate_status(self) -> "LearningItemValidationCheckV1":
        if (self.status == "failed") != (self.safe_code is not None):
            raise ValueError("failed validation checks require exactly one safe code")
        return self


class LearningItemValidationReceiptV1(_StrictModel):
    schema_version: Literal["learning_item_validation_v1"] = LEARNING_ITEM_VALIDATION_SCHEMA_VERSION
    policy_version: Literal["learning_item_validation_policy_v1"] = LEARNING_ITEM_VALIDATION_POLICY_VERSION
    compiler_version: Literal["learning_item_compiler_v1"] = LEARNING_ITEM_COMPILER_VERSION
    item_handle: str = Field(min_length=67, max_length=67)
    content_hash: str = Field(min_length=64, max_length=64)
    checks: tuple[LearningItemValidationCheckV1, ...] = Field(min_length=1, max_length=16)

    @field_validator("item_handle")
    @classmethod
    def validate_handle(cls, value: str) -> str:
        if not _HANDLE.fullmatch(value):
            raise ValueError("validation item handle is invalid")
        return value

    @field_validator("content_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return require_sha256(value, label="validation content hash")

    @field_validator("checks")
    @classmethod
    def validate_checks(
        cls,
        values: tuple[LearningItemValidationCheckV1, ...],
    ) -> tuple[LearningItemValidationCheckV1, ...]:
        kinds = tuple(item.check_type for item in values)
        if kinds != REQUIRED_LEARNING_ITEM_VALIDATION_CHECKS:
            raise ValueError(
                "validation receipt must contain the complete canonical check set"
            )
        return values

    @property
    def passed(self) -> bool:
        return all(item.status != "failed" for item in self.checks)

    @property
    def receipt_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def raw_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def learning_item_handle(item_key: str, version: str, content_hash: str) -> str:
    digest = canonical_hash(
        {
            "namespace": "aearn.learning_item",
            "item_key": stable_key(item_key, label="item key"),
            "version": stable_key(version, label="item version"),
            "content_hash": require_sha256(content_hash, label="item content hash"),
        }
    )
    return f"li:{digest}"


def learning_item_uuid(
    kind: Literal[
        "blueprint",
        "item",
        "version",
        "private",
        "import",
        "review",
        "adjudication",
        "pilot",
        "approval",
        "materialization",
    ],
    identity: str,
) -> UUID:
    return uuid5(NAMESPACE_URL, f"aearn:learning-item-bank:{kind}:{identity}")


def stable_key(value: str, *, label: str) -> str:
    normalized = str(value).strip().lower()
    if not _STABLE_KEY.fullmatch(normalized):
        raise ValueError(f"{label} must be a stable key")
    return normalized


def bounded_text(value: str, *, label: str, maximum: int) -> str:
    normalized = normalize_newlines(str(value)).strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{label} is empty or too large")
    return normalized


def normalized_text(value: str, *, label: str, maximum: int) -> str:
    return bounded_text(value, label=label, maximum=maximum)


def normalized_code(value: str, *, label: str, maximum: int) -> str:
    normalized = normalize_newlines(str(value)).strip("\n")
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{label} is empty or too large")
    return normalized


def normalize_newlines(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def normalize_answer(value: str) -> str:
    return " ".join(normalize_newlines(str(value)).strip().casefold().split())


def parse_code_range_answer(value: str) -> tuple[int, int, str]:
    match = re.fullmatch(
        r"([1-9][0-9]{0,3}):([1-9][0-9]{0,3}):([a-z0-9][a-z0-9._:-]{0,159})",
        normalize_answer(value),
    )
    if match is None:
        raise ValueError("code-range accepted answer must use start:end:category")
    start_line, end_line = int(match.group(1)), int(match.group(2))
    if start_line > 4_000 or end_line > 4_000 or end_line < start_line:
        raise ValueError("code-range accepted answer is outside the supported line range")
    return start_line, end_line, match.group(3)


def require_sha256(value: str, *, label: str) -> str:
    normalized = str(value).strip().lower()
    if not _SHA256.fullmatch(normalized):
        raise ValueError(f"{label} must be SHA-256")
    return normalized


def require_json_object(value: Mapping[str, object], *, label: str, maximum: int) -> None:
    encoded = canonical_json(dict(value))
    if len(encoded) > maximum:
        raise ValueError(f"{label} is too large")


_DEMO_EVENT_MAX_BYTES = 2_048
_DEMO_EVENT_MAX_DEPTH = 6
_DEMO_EVENT_MAX_MEMBERS = 64
_DEMO_EVENT_MAX_SAFE_INTEGER = 9_007_199_254_740_991


def validate_demo_event_payload(value: Mapping[str, object]) -> dict[str, object]:
    """Normalize the one JSON shape shared by published demo and Preview events.

    This is intentionally stricter than a generic JSON object: the isolated
    Preview bridge has the same byte, depth, fan-out, and JS-number bounds, so
    a published descriptor can always be completed by the Desktop without a
    parser/bridge mismatch.
    """

    payload = dict(value)
    try:
        encoded = canonical_json(payload).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("demo event payload has an unsupported JSON shape") from exc
    if len(encoded) > _DEMO_EVENT_MAX_BYTES:
        raise ValueError("demo event payload is too large")
    if not _is_safe_demo_json(payload, depth=0):
        raise ValueError("demo event payload has an unsupported JSON shape")
    return payload


def _is_safe_demo_json(value: object, *, depth: int) -> bool:
    if depth > _DEMO_EVENT_MAX_DEPTH:
        return False
    if value is None or isinstance(value, (bool, str)):
        return True
    if isinstance(value, int):
        return -_DEMO_EVENT_MAX_SAFE_INTEGER <= value <= _DEMO_EVENT_MAX_SAFE_INTEGER
    if isinstance(value, float):
        return math.isfinite(value) and abs(value) <= _DEMO_EVENT_MAX_SAFE_INTEGER
    if isinstance(value, Mapping):
        return (
            len(value) <= _DEMO_EVENT_MAX_MEMBERS
            and all(
                isinstance(key, str)
                and 1 <= len(key.encode("utf-8")) <= 160
                and _is_safe_demo_json(item, depth=depth + 1)
                for key, item in value.items()
            )
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return (
            len(value) <= _DEMO_EVENT_MAX_MEMBERS
            and all(_is_safe_demo_json(item, depth=depth + 1) for item in value)
        )
    return False


def _validate_sql_schema(schema: Sequence[LearningItemSqlTableV2]) -> None:
    table_names = tuple(item.name for item in schema)
    if len(table_names) != len(set(table_names)):
        raise ValueError("SQL schema tables must be unique")
    tables = {item.name: item for item in schema}
    for table in schema:
        columns_by_name = {column.name: column for column in table.columns}
        for foreign_key in table.foreign_keys:
            referenced = tables.get(foreign_key.references_table)
            if referenced is None:
                raise ValueError("SQL foreign key references an unknown table")
            referenced_by_name = {
                column.name: column for column in referenced.columns
            }
            referenced_column = referenced_by_name.get(
                foreign_key.references_column
            )
            referenced_primary = tuple(
                column.name for column in referenced.columns if column.primary_key
            )
            if (
                referenced_column is None
                or referenced_primary != (foreign_key.references_column,)
                or columns_by_name[foreign_key.column].data_type
                != referenced_column.data_type
            ):
                raise ValueError(
                    "SQL foreign key must reference one matching published primary key"
                )


def _validate_sql_dataset(
    schema: Sequence[LearningItemSqlTableV2],
    dataset: LearningItemSqlDatasetV2,
    *,
    maximum_rows: int,
) -> None:
    schema_by_name = {item.name: item for item in schema}
    data_by_name = {item.table: item for item in dataset.tables}
    if set(schema_by_name) != set(data_by_name):
        raise ValueError("SQL dataset must provide every published table exactly once")

    values_by_table: dict[str, dict[str, set[object]]] = {}
    for table_name, table in schema_by_name.items():
        data = data_by_name[table_name]
        if len(data.rows) > maximum_rows:
            raise ValueError("SQL dataset row count exceeds its bound")
        column_names = tuple(column.name for column in table.columns)
        SafeTableResultPresentationV1(columns=column_names, rows=data.rows)
        column_values: dict[str, set[object]] = {
            name: set() for name in column_names
        }
        primary_indexes = tuple(
            index for index, column in enumerate(table.columns) if column.primary_key
        )
        primary_values: set[tuple[object, ...]] = set()
        for row in data.rows:
            if len(row) != len(table.columns):
                raise ValueError("SQL dataset row width does not match its schema")
            for index, (column, value) in enumerate(zip(table.columns, row, strict=True)):
                if not _sql_cell_matches_column(value, column):
                    raise ValueError("SQL dataset cell does not match its published type")
                column_values[column.name].add(value)
            if primary_indexes:
                identity = tuple(row[index] for index in primary_indexes)
                if any(value is None for value in identity) or identity in primary_values:
                    raise ValueError("SQL dataset primary keys must be non-null and unique")
                primary_values.add(identity)
        values_by_table[table_name] = column_values

    for table in schema:
        data = data_by_name[table.name]
        column_indexes = {
            column.name: index for index, column in enumerate(table.columns)
        }
        for foreign_key in table.foreign_keys:
            target_values = values_by_table[foreign_key.references_table][
                foreign_key.references_column
            ]
            source_index = column_indexes[foreign_key.column]
            for row in data.rows:
                value = row[source_index]
                if value is not None and value not in target_values:
                    raise ValueError("SQL dataset foreign key does not reference a published row")


def _sql_cell_matches_column(
    value: SafeTableResultCellV1,
    column: LearningItemSqlColumnV2,
) -> bool:
    if value is None:
        return column.nullable and not column.primary_key
    if column.data_type == "TEXT":
        return isinstance(value, str)
    if column.data_type == "INTEGER":
        return isinstance(value, int) and not isinstance(value, bool)
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and (not isinstance(value, float) or math.isfinite(value))
    )


def _expected_interactions(kind: LearningItemKind) -> frozenset[LearningItemInteraction]:
    return {
        LearningItemKind.CODE: frozenset({LearningItemInteraction.EDIT, LearningItemInteraction.RUN}),
        LearningItemKind.SQL: frozenset({LearningItemInteraction.QUERY, LearningItemInteraction.RUN}),
        LearningItemKind.DEMO: frozenset({LearningItemInteraction.OBSERVE}),
        LearningItemKind.KNOWLEDGE_CHECK: frozenset({LearningItemInteraction.RESPOND}),
        LearningItemKind.MODEL_REVIEW: frozenset({LearningItemInteraction.REVIEW}),
    }[kind]


def _content_language(content: LearningItemPublicContentV1) -> str | None:
    if isinstance(
        content,
        (LearningItemCodeContentV1, LearningItemDemoContentV1, LearningItemDemoContentV2),
    ):
        return content.language_id
    if isinstance(
        content,
        (LearningItemModelReviewContentV1, LearningItemModelReviewContentV2),
    ):
        return content.artifact.language_id
    if isinstance(content, (LearningItemSqlContentV1, LearningItemSqlContentV2)):
        return "sql"
    return None


def _content_kind(
    content: LearningItemPublicContentV1 | LearningItemPrivateContentV1,
) -> LearningItemKind:
    if isinstance(content, (LearningItemDemoContentV1, LearningItemDemoContentV2)):
        return LearningItemKind.DEMO
    if isinstance(content, (LearningItemDemoPrivateV1, LearningItemDemoPrivateV2)):
        return LearningItemKind.DEMO
    if isinstance(
        content,
        (LearningItemModelReviewContentV1, LearningItemModelReviewContentV2),
    ):
        return LearningItemKind.MODEL_REVIEW
    if isinstance(content, (LearningItemSqlContentV2, LearningItemSqlPrivateV2)):
        return LearningItemKind.SQL
    return LearningItemKind(content.type)


def _require_test_bundle(tests: Sequence[LearningItemRuntimeTestCaseV1]) -> None:
    ids = tuple(item.id for item in tests)
    orders = tuple(item.order_index for item in tests)
    if len(ids) != len(set(ids)):
        raise ValueError("private test ids must be unique")
    if orders != tuple(range(len(tests))):
        raise ValueError("private test order must be contiguous from zero")
    if not any(item.case_type == "visible" for item in tests):
        raise ValueError("private test bundle requires a visible case")
    if not any(item.case_type == "hidden" for item in tests):
        raise ValueError("private test bundle requires a hidden case")


def _require_sql_test_bundle(tests: Sequence[LearningItemSqlTestCaseV2]) -> None:
    ids = tuple(item.id for item in tests)
    orders = tuple(item.order_index for item in tests)
    if len(ids) != len(set(ids)):
        raise ValueError("SQL private test ids must be unique")
    if orders != tuple(range(len(tests))):
        raise ValueError("SQL private test order must be contiguous from zero")
    if not any(item.case_type == "visible" for item in tests):
        raise ValueError("SQL private tests require a visible case")
    if not any(item.case_type == "hidden" for item in tests):
        raise ValueError("SQL private tests require a hidden case")


__all__ = (
    "LEARNING_ITEM_BLUEPRINT_SCHEMA_VERSION",
    "LEARNING_ITEM_COMPILER_VERSION",
    "LEARNING_ITEM_PRIVATE_SCHEMA_VERSION",
    "LEARNING_ITEM_PUBLIC_SCHEMA_VERSION",
    "LEARNING_ITEM_SOURCE_SCHEMA_VERSION",
    "LEARNING_ITEM_VALIDATION_POLICY_VERSION",
    "LEARNING_ITEM_VALIDATION_SCHEMA_VERSION",
    "REQUIRED_LEARNING_ITEM_VALIDATION_CHECKS",
    "LearningItemBlueprintV1",
    "LearningItemCodeContentV1",
    "LearningItemCodePrivateV1",
    "LearningItemDemoContentV1",
    "LearningItemDemoContentV2",
    "LearningItemDemoEventV1",
    "LearningItemDemoPrivateV1",
    "LearningItemDemoPrivateV2",
    "LearningItemDemoStepV2",
    "LearningItemDifficulty",
    "LearningItemDifficultyProfileV1",
    "LearningItemHintV1",
    "LearningItemInteraction",
    "LearningItemKind",
    "LearningItemKnowledgeCheckContentV1",
    "LearningItemKnowledgeCheckPrivateV1",
    "LearningItemModelReviewContentV1",
    "LearningItemModelReviewContentV2",
    "LearningItemModelReviewPrivateV1",
    "LearningItemOptionV1",
    "LearningItemPrivateV1",
    "LearningItemPublicationPolicyV1",
    "LearningItemPublicV1",
    "LearningItemPurpose",
    "LearningItemRemediationPolicyV1",
    "LearningItemReviewRole",
    "LearningItemRiskTier",
    "LearningItemRuntimeTestCaseV1",
    "LearningItemScorePolicyV1",
    "LearningItemSourceReferenceV1",
    "LearningItemSourceV1",
    "LearningItemSqlColumnV2",
    "LearningItemSqlContentV1",
    "LearningItemSqlContentV2",
    "LearningItemSqlDatasetTableV2",
    "LearningItemSqlDatasetV2",
    "LearningItemSqlForeignKeyV2",
    "LearningItemSqlPrivateV1",
    "LearningItemSqlPrivateV2",
    "LearningItemSqlTableV2",
    "LearningItemSqlTestCaseV2",
    "LearningItemValidationCheckType",
    "LearningItemValidationCheckV1",
    "LearningItemValidationReceiptV1",
    "LearningItemVersionIdentityV1",
    "bounded_text",
    "canonical_hash",
    "canonical_json",
    "learning_item_handle",
    "learning_item_uuid",
    "normalize_answer",
    "normalize_newlines",
    "parse_code_range_answer",
    "raw_sha256",
    "require_sha256",
    "stable_key",
    "validate_demo_event_payload",
)
