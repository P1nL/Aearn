"""Strict learner-safe contracts for inline Tutor Learning Artifacts."""
from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from typing import Annotated, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from aearn_shared.execution import (
    SafeExecutionResultV2,
    SafeTableResultPresentationV1,
)
from app.services.tutor.branch_contracts import BranchResponseDisposition
from app.services.learning.item_bank.contracts import (
    LearningItemSqlTableV2,
    validate_demo_event_payload,
)
from app.services.learning.practice.model_review_contracts import (
    ModelCodeReviewSubmissionV1,
    ModelCodeReviewSubmissionV2,
    MODEL_REVIEW_CORE_CATEGORIES,
    ModelReviewArtifactV2,
    ModelReviewErrorCategoryV2,
)


TUTOR_LEARNING_ARTIFACT_SCHEMA_VERSION = "tutor_learning_artifact_v1"
TUTOR_LEARNING_ARTIFACT_EVENT_SCHEMA_VERSION = "tutor_learning_artifact_event_v1"
TUTOR_LEARNING_ARTIFACT_POLICY_VERSION = "tutor_learning_artifact_policy_v1"
TUTOR_LEARNING_ARTIFACT_ATTEMPT_SCHEMA_VERSION: Literal[
    "tutor_learning_artifact_attempt_v1"
] = "tutor_learning_artifact_attempt_v1"
TUTOR_LEARNING_ARTIFACT_ATTEMPT_V2_SCHEMA_VERSION: Literal[
    "tutor_learning_artifact_attempt_v2"
] = "tutor_learning_artifact_attempt_v2"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STABLE_KEY = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,159}$")
_ACTION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$")

# Tests seed these exact markers into every public projection boundary.  The
# recursive key deny-list below catches accidental real-field leakage too.
ARTIFACT_PROTECTED_MARKERS: tuple[str, ...] = (
    "__AEARN_PRIVATE_SUBMISSION__",
    "__AEARN_HIDDEN_TEST__",
    "__AEARN_PRIVATE_RUBRIC__",
    "__AEARN_REFERENCE_ANSWER__",
    "__AEARN_PROVIDER_BODY__",
    "__AEARN_PROVIDER_REASONING__",
    "__AEARN_PRIVATE_COMMAND_PATH__",
    "__AEARN_CONTAINER_SECRET__",
)

_FORBIDDEN_PUBLIC_KEYS = frozenset(
    {
        "submission",
        "submitted_code",
        "content_text",
        "private_rubric",
        "private_rubric_json",
        "private_test_bundle",
        "private_test_bundle_json",
        "hidden_test",
        "hidden_tests",
        "hidden_test_ids",
        "reference_answer",
        "reference_answer_json",
        "solution_reference",
        "provider_body",
        "provider_payload",
        "provider_response",
        "provider_reasoning",
        "reasoning",
        "reasoning_content",
        "raw_reasoning",
        "prompt",
        "raw_prompt",
        "raw_result",
        "raw_payload",
        "rubric",
        "command",
        "command_line",
        "path",
        "file_path",
        "filesystem_path",
        "working_directory",
        "mount",
        "mounts",
        "container",
        "container_id",
        "container_name",
        "image",
        "image_id",
        "image_digest",
        "secret",
        "credential",
        "api_key",
    }
)


class _StrictArtifactModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


def _require_sha256(value: str | None, *, label: str) -> str | None:
    if value is not None and not _SHA256.fullmatch(value):
        raise ValueError(f"{label} must be a SHA-256 digest")
    return value


class TutorArtifactKind(StrEnum):
    EXERCISE_WORKSPACE = "exercise_workspace"
    BROWSER_PREVIEW = "browser_preview"
    TEST_RESULT = "test_result"
    KNOWLEDGE_CHECK = "knowledge_check"
    MODEL_CODE_REVIEW = "model_code_review"
    SQL_WORKSPACE = "sql_workspace"
    DEMONSTRATION = "demonstration"
    SOURCE_INSPECTOR = "source_inspector"


class TutorArtifactPurpose(StrEnum):
    EXERCISE = "exercise"
    DEMONSTRATION = "demonstration"
    KNOWLEDGE_CHECK = "knowledge_check"
    REMEDIATION = "remediation"
    TRANSFER_CHECK = "transfer_check"
    CODE_REVIEW = "code_review"
    SQL_EXPLORATION = "sql_exploration"
    RESULT = "result"


class TutorArtifactOwnerKind(StrEnum):
    LESSON_GATE = "lesson_gate"
    REVIEW_ITEM = "review_item"
    TEACHING_PRACTICE = "teaching_practice"
    LEARNING_ITEM = "learning_item"


class TutorArtifactState(StrEnum):
    PENDING = "pending"
    READY = "ready"
    ACTIVE = "active"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"

    @property
    def terminal(self) -> bool:
        return self in {
            TutorArtifactState.COMPLETED,
            TutorArtifactState.FAILED,
            TutorArtifactState.CANCELLED,
            TutorArtifactState.SUPERSEDED,
        }


class TutorArtifactActionKind(StrEnum):
    REQUEST_HINT = "request_hint"
    REQUEST_DIRECT_ANSWER = "request_direct_answer"
    RUN = "run"
    RESPOND = "respond"
    COMPLETE_REVIEW = "complete_review"
    CANCEL = "cancel"
    ACKNOWLEDGE_DEMO_EVENT = "acknowledge_demo_event"
    COMPLETE_DEMO = "complete_demo"


class TutorArtifactDifficulty(StrEnum):
    D1 = "D1"
    D2 = "D2"
    D3 = "D3"
    D4 = "D4"
    D5 = "D5"


class TutorArtifactOptionV1(_StrictArtifactModel):
    value: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=320)


class TutorArtifactExerciseWorkspacePresentationV1(_StrictArtifactModel):
    type: Literal["exercise_workspace_v1"] = "exercise_workspace_v1"
    exercise_version_id: str = Field(min_length=1, max_length=160)
    language_id: str = Field(min_length=1, max_length=160)
    editor_mode: Literal["code", "sql", "structured_answer"]
    starter_content: str = Field(max_length=48_000)
    starter_content_hash: str = Field(min_length=64, max_length=64)
    editable: bool
    live_preview: bool = False
    runtime_profile_key: str | None = Field(default=None, min_length=1, max_length=160)

    @field_validator("language_id", "runtime_profile_key")
    @classmethod
    def validate_stable_keys(cls, value: str | None) -> str | None:
        if value is not None and not _STABLE_KEY.fullmatch(value):
            raise ValueError("artifact presentation stable key is invalid")
        return value

    @model_validator(mode="after")
    def validate_content_hash(self) -> "TutorArtifactExerciseWorkspacePresentationV1":
        if sha256_text(self.starter_content) != self.starter_content_hash:
            raise ValueError("artifact starter content hash does not match")
        return self


class TutorArtifactBrowserPreviewPresentationV1(_StrictArtifactModel):
    type: Literal["browser_preview_v1"] = "browser_preview_v1"
    source_artifact_id: str = Field(min_length=1, max_length=160)
    source_content_hash: str = Field(min_length=64, max_length=64)
    experience_tier: Literal["local_non_authoritative"] = "local_non_authoritative"
    interactive: bool

    @field_validator("source_content_hash")
    @classmethod
    def validate_source_content_hash(cls, value: str) -> str:
        return str(_require_sha256(value, label="artifact preview source hash"))


class TutorArtifactTestResultPresentationV1(_StrictArtifactModel):
    type: Literal["test_result_v1"] = "test_result_v1"
    attempt_id: str = Field(min_length=1, max_length=160)
    status: Literal["pending", "terminal"]
    outcome: Literal["passed", "failed", "timed_out", "cancelled", "unavailable", "invalid"] | None = None
    passed_count: int = Field(default=0, ge=0, le=10_000)
    total_count: int = Field(default=0, ge=0, le=10_000)
    summary_markdown: str = Field(default="", max_length=4_000)
    result_hash: str | None = Field(default=None, min_length=64, max_length=64)

    @field_validator("result_hash")
    @classmethod
    def validate_result_hash(cls, value: str | None) -> str | None:
        return _require_sha256(value, label="artifact test result hash")

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> "TutorArtifactTestResultPresentationV1":
        if self.passed_count > self.total_count:
            raise ValueError("artifact test result passed_count exceeds total_count")
        terminal = self.status == "terminal"
        if terminal != (self.outcome is not None and self.result_hash is not None):
            raise ValueError("artifact test result terminal fields are inconsistent")
        return self


class TutorArtifactHintPageV1(_StrictArtifactModel):
    level: Literal[1, 2, 3]
    label: Literal["方向", "概念", "结构"]
    markdown: str = Field(min_length=1, max_length=2_000)


class TutorArtifactKnowledgeCheckPresentationV1(_StrictArtifactModel):
    type: Literal["knowledge_check_v1"] = "knowledge_check_v1"
    response_kind: Literal[
        "single_select",
        "multi_select",
        "prediction",
        "ordering",
        "code_range",
        "short_text",
    ]
    prompt_markdown: str = Field(min_length=1, max_length=8_000)
    options: tuple[TutorArtifactOptionV1, ...] = Field(default=(), max_length=24)
    minimum_selections: int = Field(default=1, ge=1, le=24)
    maximum_selections: int = Field(default=1, ge=1, le=24)
    maximum_text_length: int = Field(default=2_000, ge=1, le=8_000)
    hints: tuple[TutorArtifactHintPageV1, ...] = Field(default=(), max_length=3)
    revealed_hint_levels: tuple[Literal[1, 2, 3], ...] = Field(default=(), max_length=3)
    answer_locked: bool = False
    outcome: Literal["correct", "incorrect"] | None = None
    assistance_kind: Literal["independent", "hinted", "direct_answer", "remediated"] | None = None
    evaluation_markdown: str = Field(default="", max_length=4_000)
    response_receipt_id: str | None = Field(default=None, min_length=1, max_length=160)
    remediation_handle: str | None = Field(default=None, min_length=67, max_length=67)
    transfer_handle: str | None = Field(default=None, min_length=67, max_length=67)

    @model_validator(mode="after")
    def validate_response_shape(self) -> "TutorArtifactKnowledgeCheckPresentationV1":
        values = tuple(item.value for item in self.options)
        if len(values) != len(set(values)):
            raise ValueError("artifact knowledge-check options must be unique")
        select_kind = self.response_kind in {"single_select", "multi_select", "ordering"}
        if select_kind != bool(self.options):
            raise ValueError("artifact knowledge-check option shape is invalid")
        if self.maximum_selections < self.minimum_selections:
            raise ValueError("artifact selection bounds are invalid")
        if self.response_kind == "single_select" and self.maximum_selections != 1:
            raise ValueError("single-select artifact must allow exactly one selection")
        if self.response_kind == "ordering" and (
            self.minimum_selections != len(self.options)
            or self.maximum_selections != len(self.options)
        ):
            raise ValueError("ordering artifact must include every option exactly once")
        if self.options and self.maximum_selections > len(self.options):
            raise ValueError("artifact selection maximum exceeds option count")
        hint_levels = tuple(item.level for item in self.hints)
        if hint_levels != tuple(range(1, len(self.hints) + 1)):
            raise ValueError("artifact hint pages must be contiguous from H1")
        if self.revealed_hint_levels != tuple(range(1, len(self.revealed_hint_levels) + 1)):
            raise ValueError("artifact revealed hint levels must be contiguous from H1")
        if len(self.revealed_hint_levels) > len(self.hints):
            raise ValueError("artifact revealed hint level exceeds available hints")
        terminal_fields = (
            self.outcome is not None,
            self.assistance_kind is not None,
            bool(self.evaluation_markdown),
            self.response_receipt_id is not None,
        )
        if self.answer_locked and not all(terminal_fields):
            raise ValueError("artifact knowledge-check terminal fields are inconsistent")
        if not self.answer_locked and any(terminal_fields):
            raise ValueError("active artifact knowledge check cannot expose result fields")
        for handle in (self.remediation_handle, self.transfer_handle):
            if handle is not None and not re.fullmatch(r"li:[0-9a-f]{64}", handle):
                raise ValueError("artifact successor handle is invalid")
        if self.outcome == "correct" and (self.remediation_handle or self.transfer_handle):
            raise ValueError("correct knowledge check cannot expose a successor")
        return self


class TutorArtifactModelCodeReviewPresentationV1(_StrictArtifactModel):
    type: Literal["model_code_review_v1"] = "model_code_review_v1"
    exercise_version_id: str = Field(min_length=1, max_length=160)
    language_id: str = Field(min_length=1, max_length=160)
    source_code: str = Field(min_length=1, max_length=48_000)
    source_code_hash: str = Field(min_length=64, max_length=64)
    line_count: int = Field(ge=1, le=4_000)
    review_categories: tuple[str, ...] = Field(default=(), max_length=16)

    @field_validator("language_id")
    @classmethod
    def validate_language_id(cls, value: str) -> str:
        if not _STABLE_KEY.fullmatch(value):
            raise ValueError("artifact review language_id is invalid")
        return value

    @field_validator("review_categories")
    @classmethod
    def validate_review_categories(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)) or any(not _STABLE_KEY.fullmatch(value) for value in values):
            raise ValueError("artifact review categories must be stable and unique")
        return values

    @model_validator(mode="after")
    def validate_code_identity(self) -> "TutorArtifactModelCodeReviewPresentationV1":
        normalized = normalize_newlines(self.source_code)
        if sha256_text(normalized) != self.source_code_hash:
            raise ValueError("artifact source code hash does not match")
        if len(normalized.splitlines()) != self.line_count:
            raise ValueError("artifact source code line count does not match")
        return self


class TutorArtifactModelCodeReviewPresentationV2(_StrictArtifactModel):
    type: Literal["model_code_review_v2"] = "model_code_review_v2"
    exercise_version_id: str = Field(min_length=1, max_length=160)
    presentation_hash: str = Field(min_length=64, max_length=64)
    review_target: ModelReviewArtifactV2
    review_categories: tuple[ModelReviewErrorCategoryV2, ...] = Field(min_length=7, max_length=8)
    submission_locked: bool = False
    outcome: Literal["passed", "failed"] | None = None
    score: float | None = Field(default=None, ge=0, le=1)
    evaluation_markdown: str = Field(default="", max_length=4_000)
    review_receipt_id: str | None = Field(default=None, min_length=1, max_length=160)
    result_hash: str | None = Field(default=None, min_length=64, max_length=64)
    remediation_handle: str | None = Field(default=None, min_length=67, max_length=67)

    @field_validator("review_categories")
    @classmethod
    def validate_review_categories(
        cls, values: tuple[ModelReviewErrorCategoryV2, ...]
    ) -> tuple[ModelReviewErrorCategoryV2, ...]:
        if len(values) != len(set(values)):
            raise ValueError("artifact review taxonomy must be unique")
        if not set(MODEL_REVIEW_CORE_CATEGORIES).issubset(values):
            raise ValueError("artifact review taxonomy is incomplete")
        return values

    @field_validator("presentation_hash", "result_hash")
    @classmethod
    def validate_result_hash(cls, value: str | None) -> str | None:
        return _require_sha256(value, label="artifact model review hash")

    @model_validator(mode="after")
    def validate_completion(self) -> "TutorArtifactModelCodeReviewPresentationV2":
        if self.presentation_hash != self.review_target.presentation_hash:
            raise ValueError("artifact model review presentation identity is stale")
        terminal_fields = (
            self.outcome is not None,
            self.score is not None,
            bool(self.evaluation_markdown),
            self.review_receipt_id is not None,
            self.result_hash is not None,
        )
        if self.submission_locked != all(terminal_fields):
            raise ValueError("artifact model review terminal fields are inconsistent")
        if not self.submission_locked and any(terminal_fields):
            raise ValueError("active model review cannot expose result fields")
        if self.remediation_handle is not None and not re.fullmatch(
            r"li:[0-9a-f]{64}", self.remediation_handle
        ):
            raise ValueError("artifact model review remediation handle is invalid")
        if self.submission_locked and (
            (self.outcome == "failed") != (self.remediation_handle is not None)
        ):
            raise ValueError("artifact model review remediation outcome is inconsistent")
        return self


class TutorArtifactSqlWorkspacePresentationV1(_StrictArtifactModel):
    type: Literal["sql_workspace_v1"] = "sql_workspace_v1"
    exercise_version_id: str = Field(min_length=1, max_length=160)
    dialect: Literal["sqlite"] = "sqlite"
    starter_query: str = Field(max_length=48_000)
    starter_query_hash: str = Field(min_length=64, max_length=64)
    schema_markdown: str = Field(min_length=1, max_length=12_000)
    max_rows: int = Field(default=100, ge=1, le=200)

    @model_validator(mode="after")
    def validate_query_hash(self) -> "TutorArtifactSqlWorkspacePresentationV1":
        if sha256_text(self.starter_query) != self.starter_query_hash:
            raise ValueError("artifact starter query hash does not match")
        return self


class TutorArtifactSqlWorkspacePresentationV2(_StrictArtifactModel):
    type: Literal["sql_workspace_v2"] = "sql_workspace_v2"
    exercise_version_id: str = Field(min_length=1, max_length=160)
    dialect: Literal["sqlite"] = "sqlite"
    execution_tier: Literal["teaching_local"] = "teaching_local"
    starter_query: str = Field(max_length=48_000)
    starter_query_hash: str = Field(min_length=64, max_length=64)
    tables: tuple[LearningItemSqlTableV2, ...] = Field(min_length=1, max_length=8)
    max_rows: int = Field(default=50, ge=1, le=200)
    public_result: SafeTableResultPresentationV1 | None = None
    public_result_query_hash: str | None = Field(default=None, min_length=64, max_length=64)
    public_result_attempt_id: str | None = Field(default=None, min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_workspace(self) -> "TutorArtifactSqlWorkspacePresentationV2":
        if sha256_text(self.starter_query) != self.starter_query_hash:
            raise ValueError("artifact starter query hash does not match")
        table_names = tuple(item.name for item in self.tables)
        if len(table_names) != len(set(table_names)):
            raise ValueError("artifact SQL schema tables must be unique")
        result_fields = (
            self.public_result is not None,
            self.public_result_query_hash is not None,
            self.public_result_attempt_id is not None,
        )
        if any(result_fields) and not all(result_fields):
            raise ValueError("artifact SQL public result identity is incomplete")
        if self.public_result is not None and len(self.public_result.rows) > self.max_rows:
            raise ValueError("artifact SQL public result exceeds its row bound")
        _require_sha256(
            self.public_result_query_hash,
            label="artifact SQL public query hash",
        )
        return self


class TutorArtifactDemonstrationPresentationV1(_StrictArtifactModel):
    type: Literal["demonstration_v1"] = "demonstration_v1"
    demonstration_mode: Literal["interactive", "static"]
    language_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_content: str = Field(min_length=1, max_length=48_000)
    source_content_hash: str = Field(min_length=64, max_length=64)
    expected_event_key: str | None = Field(default=None, min_length=1, max_length=160)
    duration_seconds: int | None = Field(default=None, ge=6, le=30)

    @model_validator(mode="after")
    def validate_demonstration_shape(self) -> "TutorArtifactDemonstrationPresentationV1":
        if sha256_text(self.source_content) != self.source_content_hash:
            raise ValueError("artifact demonstration content hash does not match")
        if self.language_id is not None and not _STABLE_KEY.fullmatch(self.language_id):
            raise ValueError("artifact demonstration language_id is invalid")
        if self.demonstration_mode == "interactive":
            if self.expected_event_key is None or self.duration_seconds is not None:
                raise ValueError("interactive demonstration requires only an expected event")
        elif self.duration_seconds is None or self.expected_event_key is not None:
            raise ValueError("static demonstration requires only a duration")
        return self


class TutorArtifactDemonstrationEventV2(_StrictArtifactModel):
    event_key: str = Field(min_length=1, max_length=160)
    payload_json: dict[str, object] = Field(default_factory=dict)
    payload_hash: str = Field(min_length=64, max_length=64)

    @field_validator("event_key")
    @classmethod
    def validate_event_key(cls, value: str) -> str:
        if not _STABLE_KEY.fullmatch(value):
            raise ValueError("artifact demonstration event key is invalid")
        return value

    @model_validator(mode="after")
    def validate_payload_hash(self) -> "TutorArtifactDemonstrationEventV2":
        assert_public_artifact_safe(self.payload_json)
        validate_demo_event_payload(self.payload_json)
        if canonical_hash(self.payload_json) != self.payload_hash:
            raise ValueError("artifact demonstration event payload hash does not match")
        return self


class TutorArtifactDemonstrationStepV2(_StrictArtifactModel):
    step_key: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=160)
    instruction_markdown: str = Field(min_length=1, max_length=2_000)
    source_content: str = Field(min_length=1, max_length=12_000)
    source_content_hash: str = Field(min_length=64, max_length=64)
    duration_seconds: int | None = Field(default=None, ge=6, le=30)

    @field_validator("step_key")
    @classmethod
    def validate_step_key(cls, value: str) -> str:
        if not _STABLE_KEY.fullmatch(value):
            raise ValueError("artifact demonstration step key is invalid")
        return value

    @model_validator(mode="after")
    def validate_source_hash(self) -> "TutorArtifactDemonstrationStepV2":
        if sha256_text(self.source_content) != self.source_content_hash:
            raise ValueError("artifact demonstration step source hash does not match")
        return self


class TutorArtifactDemonstrationPresentationV2(_StrictArtifactModel):
    type: Literal["demonstration_v2"] = "demonstration_v2"
    descriptor_version: Literal["demonstration_descriptor_v1"] = "demonstration_descriptor_v1"
    demonstration_mode: Literal["interactive", "static"]
    source_version: str = Field(min_length=1, max_length=160)
    language_id: str = Field(min_length=1, max_length=160)
    steps: tuple[TutorArtifactDemonstrationStepV2, ...] = Field(min_length=1, max_length=8)
    expected_event: TutorArtifactDemonstrationEventV2 | None = None
    total_duration_seconds: int | None = Field(default=None, ge=6, le=240)
    completion_policy_version: Literal["demonstration_completion_policy_v1"] = (
        "demonstration_completion_policy_v1"
    )

    @field_validator("source_version", "language_id")
    @classmethod
    def validate_stable_keys(cls, value: str) -> str:
        if not _STABLE_KEY.fullmatch(value):
            raise ValueError("artifact demonstration descriptor key is invalid")
        return value

    @model_validator(mode="after")
    def validate_descriptor_shape(self) -> "TutorArtifactDemonstrationPresentationV2":
        keys = tuple(item.step_key for item in self.steps)
        if len(keys) != len(set(keys)):
            raise ValueError("artifact demonstration step keys must be unique")
        durations = tuple(item.duration_seconds for item in self.steps)
        if self.demonstration_mode == "interactive":
            if (
                len(self.steps) != 1
                or self.expected_event is None
                or self.total_duration_seconds is not None
                or any(item is not None for item in durations)
            ):
                raise ValueError("interactive demonstration descriptor is inconsistent")
        else:
            if self.expected_event is not None or any(item is None for item in durations):
                raise ValueError("static demonstration descriptor is inconsistent")
            if self.total_duration_seconds != sum(int(item) for item in durations if item is not None):
                raise ValueError("static demonstration total duration does not match its steps")
        return self


class TutorArtifactSourceInspectorPresentationV1(_StrictArtifactModel):
    type: Literal["source_inspector_v1"] = "source_inspector_v1"
    document_id: str = Field(min_length=1, max_length=160)
    document_content_hash: str = Field(min_length=64, max_length=64)
    block_id: str = Field(min_length=1, max_length=160)
    excerpt: str = Field(min_length=1, max_length=800)
    citation_ids: tuple[str, ...] = Field(default=(), max_length=12)

    @field_validator("document_content_hash")
    @classmethod
    def validate_document_content_hash(cls, value: str) -> str:
        return str(_require_sha256(value, label="artifact document content hash"))

    @field_validator("citation_ids")
    @classmethod
    def validate_citation_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)) or any(not value or len(value) > 160 for value in values):
            raise ValueError("artifact citation ids must be bounded and unique")
        return values


TutorArtifactPresentationV1 = Annotated[
    TutorArtifactExerciseWorkspacePresentationV1
    | TutorArtifactBrowserPreviewPresentationV1
    | TutorArtifactTestResultPresentationV1
    | TutorArtifactKnowledgeCheckPresentationV1
    | TutorArtifactModelCodeReviewPresentationV1
    | TutorArtifactModelCodeReviewPresentationV2
    | TutorArtifactSqlWorkspacePresentationV1
    | TutorArtifactSqlWorkspacePresentationV2
    | TutorArtifactDemonstrationPresentationV1
    | TutorArtifactDemonstrationPresentationV2
    | TutorArtifactSourceInspectorPresentationV1,
    Field(discriminator="type"),
]


class TutorArtifactSourceReferenceV1(_StrictArtifactModel):
    kind: Literal[
        "lesson_document",
        "exercise_version",
        "attempt_result",
        "review_session",
        "teaching_checkpoint",
        "source_citation",
        "artifact",
    ]
    reference_id: str = Field(min_length=1, max_length=160)
    reference_version: int | None = Field(default=None, ge=1)
    content_hash: str | None = Field(default=None, min_length=64, max_length=64)
    label: str = Field(min_length=1, max_length=240)

    @field_validator("content_hash")
    @classmethod
    def validate_content_hash(cls, value: str | None) -> str | None:
        return _require_sha256(value, label="artifact source reference hash")


class TutorArtifactAttemptSummaryV1(_StrictArtifactModel):
    attempt_id: str = Field(min_length=1, max_length=160)
    attempt_type: Literal["run", "submit", "diagnostic_submit", "review_submit"]
    status: Literal["pending", "terminal"]
    outcome: Literal["passed", "failed", "timed_out", "cancelled", "unavailable", "invalid"] | None = None
    score: float | None = Field(default=None, ge=0, le=1)
    result_hash: str | None = Field(default=None, min_length=64, max_length=64)
    accepted_at: str = Field(min_length=1, max_length=80)
    terminal_at: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator("result_hash")
    @classmethod
    def validate_result_hash(cls, value: str | None) -> str | None:
        return _require_sha256(value, label="artifact Attempt result hash")

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> "TutorArtifactAttemptSummaryV1":
        terminal = self.status == "terminal"
        if terminal != (
            self.outcome is not None
            and self.score is not None
            and self.result_hash is not None
            and self.terminal_at is not None
        ):
            raise ValueError("artifact attempt terminal fields are inconsistent")
        return self


class TutorArtifactAttemptResultV1(_StrictArtifactModel):
    outcome: Literal["passed", "failed", "timed_out", "cancelled", "unavailable", "invalid"]
    score: float = Field(ge=0, le=1)
    safe_feedback: dict[str, object] = Field(default_factory=dict)
    capability_scores: dict[str, float] = Field(default_factory=dict)
    policy_version: str = Field(min_length=1, max_length=160)
    result_hash: str = Field(min_length=64, max_length=64)
    terminal_at: str = Field(min_length=1, max_length=80)

    @field_validator("policy_version")
    @classmethod
    def validate_policy_version(cls, value: str) -> str:
        if not _STABLE_KEY.fullmatch(value):
            raise ValueError("artifact Attempt policy version is invalid")
        return value

    @field_validator("capability_scores")
    @classmethod
    def validate_capability_scores(cls, values: dict[str, float]) -> dict[str, float]:
        if len(values) > 64:
            raise ValueError("artifact Attempt capability scores are too large")
        if any(not _STABLE_KEY.fullmatch(key) for key in values):
            raise ValueError("artifact Attempt capability score key is invalid")
        return values

    @model_validator(mode="after")
    def validate_safe_result(self) -> "TutorArtifactAttemptResultV1":
        if not _SHA256.fullmatch(self.result_hash):
            raise ValueError("artifact Attempt result hash is invalid")
        assert_public_artifact_safe(self.model_dump(mode="json"))
        return self


class TutorArtifactAttemptDetailV1(_StrictArtifactModel):
    schema_version: Literal["tutor_learning_artifact_attempt_v1"] = (
        TUTOR_LEARNING_ARTIFACT_ATTEMPT_SCHEMA_VERSION
    )
    artifact_id: str = Field(min_length=1, max_length=160)
    artifact_version: int = Field(ge=1)
    conversation_id: str = Field(min_length=1, max_length=160)
    learning_track_id: str = Field(min_length=1, max_length=160)
    knowledge_key: str = Field(min_length=1, max_length=160)
    teaching_session_id: str = Field(min_length=1, max_length=160)
    attempt_id: str = Field(min_length=1, max_length=160)
    attempt_type: Literal["run", "submit", "diagnostic_submit", "review_submit"]
    exercise_version_id: str = Field(min_length=1, max_length=160)
    submission_hash: str = Field(min_length=64, max_length=64)
    independence: Literal["independent", "hinted", "remediated"]
    assistance_kind: Literal[
        "independent",
        "hinted",
        "validation_evidence_viewed",
        "remediated",
    ]
    status: Literal["pending", "terminal"]
    execution_job_state: Literal[
        "pending",
        "claimed",
        "launch_reserved",
        "running",
        "completed",
        "timed_out",
        "cancelled",
        "unavailable",
        "launch_uncertain",
        "failed",
    ] | None = None
    accepted_at: str = Field(min_length=1, max_length=80)
    result: TutorArtifactAttemptResultV1 | None = None

    @field_validator("knowledge_key")
    @classmethod
    def validate_attempt_knowledge_key(cls, value: str) -> str:
        if not _STABLE_KEY.fullmatch(value):
            raise ValueError("artifact Attempt knowledge key is invalid")
        return value

    @model_validator(mode="after")
    def validate_attempt_detail(self) -> "TutorArtifactAttemptDetailV1":
        if not _SHA256.fullmatch(self.submission_hash):
            raise ValueError("artifact Attempt submission hash is invalid")
        if (self.status == "terminal") != (self.result is not None):
            raise ValueError("artifact Attempt detail terminal fields are inconsistent")
        assert_public_artifact_safe(self.model_dump(mode="json"))
        return self


class TutorArtifactAttemptResultV2(_StrictArtifactModel):
    """Terminal result with only the typed learner-safe execution authority."""

    outcome: Literal["passed", "failed", "timed_out", "cancelled", "unavailable", "invalid"]
    score: float = Field(ge=0, le=1)
    execution_result: SafeExecutionResultV2 | None = None
    capability_scores: dict[str, float] = Field(default_factory=dict)
    policy_version: str = Field(min_length=1, max_length=160)
    result_hash: str = Field(min_length=64, max_length=64)
    terminal_at: str = Field(min_length=1, max_length=80)

    @field_validator("policy_version")
    @classmethod
    def validate_policy_version(cls, value: str) -> str:
        if not _STABLE_KEY.fullmatch(value):
            raise ValueError("artifact Attempt policy version is invalid")
        return value

    @field_validator("capability_scores")
    @classmethod
    def validate_capability_scores(cls, values: dict[str, float]) -> dict[str, float]:
        if len(values) > 64:
            raise ValueError("artifact Attempt capability scores are too large")
        if any(not _STABLE_KEY.fullmatch(key) for key in values):
            raise ValueError("artifact Attempt capability score key is invalid")
        return values

    @model_validator(mode="after")
    def validate_safe_result(self) -> "TutorArtifactAttemptResultV2":
        if not _SHA256.fullmatch(self.result_hash):
            raise ValueError("artifact Attempt result hash is invalid")
        assert_public_artifact_safe(self.model_dump(mode="json"))
        return self


class TutorArtifactAttemptDetailV2(_StrictArtifactModel):
    schema_version: Literal["tutor_learning_artifact_attempt_v2"] = (
        TUTOR_LEARNING_ARTIFACT_ATTEMPT_V2_SCHEMA_VERSION
    )
    artifact_id: str = Field(min_length=1, max_length=160)
    artifact_version: int = Field(ge=1)
    conversation_id: str = Field(min_length=1, max_length=160)
    learning_track_id: str = Field(min_length=1, max_length=160)
    knowledge_key: str = Field(min_length=1, max_length=160)
    teaching_session_id: str = Field(min_length=1, max_length=160)
    attempt_id: str = Field(min_length=1, max_length=160)
    attempt_type: Literal["run", "submit", "diagnostic_submit", "review_submit"]
    exercise_version_id: str = Field(min_length=1, max_length=160)
    submission_hash: str = Field(min_length=64, max_length=64)
    independence: Literal["independent", "hinted", "remediated"]
    assistance_kind: Literal[
        "independent", "hinted", "validation_evidence_viewed", "remediated"
    ]
    status: Literal["pending", "terminal"]
    execution_job_state: Literal[
        "pending", "claimed", "launch_reserved", "running", "completed",
        "timed_out", "cancelled", "unavailable", "launch_uncertain", "failed",
    ] | None = None
    accepted_at: str = Field(min_length=1, max_length=80)
    result: TutorArtifactAttemptResultV2 | None = None

    @field_validator("knowledge_key")
    @classmethod
    def validate_attempt_knowledge_key(cls, value: str) -> str:
        if not _STABLE_KEY.fullmatch(value):
            raise ValueError("artifact Attempt knowledge key is invalid")
        return value

    @model_validator(mode="after")
    def validate_attempt_detail(self) -> "TutorArtifactAttemptDetailV2":
        if not _SHA256.fullmatch(self.submission_hash):
            raise ValueError("artifact Attempt submission hash is invalid")
        if (self.status == "terminal") != (self.result is not None):
            raise ValueError("artifact Attempt detail terminal fields are inconsistent")
        assert_public_artifact_safe(self.model_dump(mode="json"))
        return self


class TutorArtifactBranchSummaryV1(_StrictArtifactModel):
    branch_id: str = Field(min_length=1, max_length=160)
    state: Literal["active", "resolved"]
    disposition: BranchResponseDisposition | None = None
    round_count: int = Field(ge=1, le=100)
    item_count: int = Field(ge=1, le=400)
    collapsed: bool

    @model_validator(mode="after")
    def validate_branch_summary(self) -> "TutorArtifactBranchSummaryV1":
        if self.collapsed != (self.state == "resolved"):
            raise ValueError("artifact branch collapsed state is inconsistent")
        if self.state == "resolved" and self.disposition is None:
            raise ValueError("resolved artifact branch requires a disposition")
        return self


class TutorArtifactBranchSummaryV2(_StrictArtifactModel):
    schema_version: Literal["tutor_artifact_branch_summary_v2"] = "tutor_artifact_branch_summary_v2"
    branch_id: str = Field(min_length=1, max_length=160)
    state: Literal["superseded"] = "superseded"
    disposition: BranchResponseDisposition | None = None
    round_count: int = Field(ge=1, le=100)
    item_count: int = Field(ge=1, le=400)
    collapsed: Literal[True] = True


class TutorPublicArtifactItem(_StrictArtifactModel):
    kind: Literal["artifact"] = "artifact"
    id: str = Field(min_length=1, max_length=160)
    conversation_id: str = Field(min_length=1, max_length=160)
    turn_id: str | None = Field(default=None, min_length=1, max_length=160)
    learning_track_id: str = Field(min_length=1, max_length=160)
    knowledge_key: str = Field(min_length=1, max_length=160)
    teaching_session_id: str = Field(min_length=1, max_length=160)
    checkpoint_id: str = Field(min_length=1, max_length=160)
    artifact_version: Literal[1] = 1
    artifact_kind: TutorArtifactKind
    purpose: TutorArtifactPurpose
    owner_kind: TutorArtifactOwnerKind
    owner_id: str = Field(min_length=1, max_length=160)
    owner_version: int = Field(ge=1)
    state: TutorArtifactState
    blocking: bool
    title: str = Field(min_length=1, max_length=240)
    instruction_markdown: str = Field(min_length=1, max_length=8_000)
    difficulty: TutorArtifactDifficulty | None = None
    presentation: TutorArtifactPresentationV1
    allowed_actions: tuple[TutorArtifactActionKind, ...] = Field(default=(), max_length=6)
    source_references: tuple[TutorArtifactSourceReferenceV1, ...] = Field(default=(), max_length=12)
    active_attempt: TutorArtifactAttemptSummaryV1 | None = None
    branch_summary: TutorArtifactBranchSummaryV1 | TutorArtifactBranchSummaryV2 | None = None
    version: int = Field(ge=1)
    created_at: str = Field(min_length=1, max_length=80)
    updated_at: str = Field(min_length=1, max_length=80)
    terminal_at: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator("knowledge_key")
    @classmethod
    def validate_knowledge_key(cls, value: str) -> str:
        if not _STABLE_KEY.fullmatch(value):
            raise ValueError("artifact knowledge key is invalid")
        return value

    @field_validator("allowed_actions")
    @classmethod
    def validate_actions(cls, actions: tuple[TutorArtifactActionKind, ...]) -> tuple[TutorArtifactActionKind, ...]:
        if len(actions) != len(set(actions)):
            raise ValueError("artifact allowed actions must be unique")
        return actions

    @model_validator(mode="after")
    def validate_state_and_presentation(self) -> "TutorPublicArtifactItem":
        expected_presentation = {
            TutorArtifactKind.EXERCISE_WORKSPACE: "exercise_workspace_v1",
            TutorArtifactKind.BROWSER_PREVIEW: "browser_preview_v1",
            TutorArtifactKind.TEST_RESULT: "test_result_v1",
            TutorArtifactKind.KNOWLEDGE_CHECK: "knowledge_check_v1",
            TutorArtifactKind.MODEL_CODE_REVIEW: "model_code_review_v1",
            TutorArtifactKind.SQL_WORKSPACE: "sql_workspace_v1",
            TutorArtifactKind.DEMONSTRATION: "demonstration_v1",
            TutorArtifactKind.SOURCE_INSPECTOR: "source_inspector_v1",
        }[self.artifact_kind]
        presentation_matches = self.presentation.type == expected_presentation
        if self.artifact_kind is TutorArtifactKind.DEMONSTRATION:
            presentation_matches = self.presentation.type in {
                "demonstration_v1",
                "demonstration_v2",
            }
        if self.artifact_kind is TutorArtifactKind.KNOWLEDGE_CHECK:
            presentation_matches = isinstance(
                self.presentation,
                TutorArtifactKnowledgeCheckPresentationV1,
            )
        if self.artifact_kind is TutorArtifactKind.MODEL_CODE_REVIEW:
            presentation_matches = isinstance(
                self.presentation,
                (
                    TutorArtifactModelCodeReviewPresentationV1,
                    TutorArtifactModelCodeReviewPresentationV2,
                ),
            )
        if self.artifact_kind is TutorArtifactKind.SQL_WORKSPACE:
            presentation_matches = isinstance(
                self.presentation,
                (
                    TutorArtifactSqlWorkspacePresentationV1,
                    TutorArtifactSqlWorkspacePresentationV2,
                ),
            )
        if not presentation_matches:
            raise ValueError("artifact kind does not match its presentation")
        if self.state.terminal != (self.terminal_at is not None):
            raise ValueError("artifact terminal timestamp is inconsistent")
        if self.state.terminal and self.allowed_actions:
            raise ValueError("terminal artifact cannot expose actions")
        if (
            self.artifact_kind is TutorArtifactKind.KNOWLEDGE_CHECK
            and self.owner_kind is TutorArtifactOwnerKind.LEARNING_ITEM
            and isinstance(self.presentation, TutorArtifactKnowledgeCheckPresentationV1)
        ):
            if (self.state is TutorArtifactState.COMPLETED) != self.presentation.answer_locked:
                raise ValueError("knowledge-check Artifact lock state is inconsistent")
        if isinstance(self.presentation, TutorArtifactModelCodeReviewPresentationV2):
            if (
                (self.state is TutorArtifactState.COMPLETED)
                != self.presentation.submission_locked
            ):
                raise ValueError("model-review Artifact lock state is inconsistent")
            if (
                not self.state.terminal
                and TutorArtifactActionKind.COMPLETE_REVIEW not in self.allowed_actions
            ):
                raise ValueError("active model-review Artifact lacks complete-review authority")
        if isinstance(self.presentation, TutorArtifactSqlWorkspacePresentationV2):
            if self.presentation.public_result_attempt_id is not None and (
                self.active_attempt is None
                or self.active_attempt.attempt_id
                != self.presentation.public_result_attempt_id
            ):
                raise ValueError("SQL public result does not match the active Attempt")
        if (
            self.state.terminal
            and self.active_attempt is not None
            and self.active_attempt.status != "terminal"
        ):
            raise ValueError("terminal artifact cannot retain a pending Attempt")
        if self.artifact_kind is TutorArtifactKind.TEST_RESULT:
            if (
                self.purpose is not TutorArtifactPurpose.RESULT
                or self.state is not TutorArtifactState.COMPLETED
                or self.blocking
                or self.allowed_actions
                or self.active_attempt is None
                or self.active_attempt.status != "terminal"
                or not isinstance(
                    self.presentation,
                    TutorArtifactTestResultPresentationV1,
                )
                or self.presentation.status != "terminal"
                or self.presentation.attempt_id != self.active_attempt.attempt_id
                or self.presentation.outcome != self.active_attempt.outcome
                or self.presentation.result_hash != self.active_attempt.result_hash
            ):
                raise ValueError("test-result Artifact authority shape is invalid")
            source_refs = [
                item for item in self.source_references if item.kind == "artifact"
            ]
            attempt_refs = [
                item
                for item in self.source_references
                if item.kind == "attempt_result"
            ]
            if (
                len(source_refs) != 1
                or source_refs[0].reference_version is None
                or len(attempt_refs) != 1
                or attempt_refs[0].reference_id != self.active_attempt.attempt_id
                or attempt_refs[0].content_hash != self.active_attempt.result_hash
            ):
                raise ValueError("test-result Artifact source authority is invalid")
        reference_identities = {
            (
                item.kind,
                item.reference_id,
                item.reference_version,
                item.content_hash,
            )
            for item in self.source_references
        }
        if len(reference_identities) != len(self.source_references):
            raise ValueError("artifact source references must be unique")
        return self


class TutorArtifactActionResponseV1(_StrictArtifactModel):
    artifact: TutorPublicArtifactItem
    artifact_event_id: str = Field(min_length=1, max_length=160)
    artifact_event_sequence: int = Field(ge=1)
    idempotent_replayed: bool

    @model_validator(mode="after")
    def validate_event_identity(self) -> "TutorArtifactActionResponseV1":
        if self.artifact_event_sequence != self.artifact.version:
            raise ValueError("artifact action response event does not own its version")
        return self


class TutorArtifactCreate(_StrictArtifactModel):
    user_id: str = Field(min_length=1, max_length=160)
    conversation_id: str = Field(min_length=1, max_length=160)
    turn_id: str | None = Field(default=None, min_length=1, max_length=160)
    learning_track_id: str = Field(min_length=1, max_length=160)
    knowledge_key: str = Field(min_length=1, max_length=160)
    teaching_session_id: str = Field(min_length=1, max_length=160)
    checkpoint_id: str = Field(min_length=1, max_length=160)
    track_version: int = Field(ge=1)
    progress_version: int = Field(ge=1)
    assignment_version: int = Field(ge=1)
    owner_kind: TutorArtifactOwnerKind
    owner_id: str = Field(min_length=1, max_length=160)
    owner_version: int = Field(ge=1)
    owner_context_version: int | None = Field(default=None, ge=1)
    artifact_kind: TutorArtifactKind
    purpose: TutorArtifactPurpose
    state: TutorArtifactState = TutorArtifactState.ACTIVE
    blocking: bool = True
    title: str = Field(min_length=1, max_length=240)
    instruction_markdown: str = Field(min_length=1, max_length=8_000)
    difficulty: TutorArtifactDifficulty | None = None
    presentation: TutorArtifactPresentationV1
    allowed_actions: tuple[TutorArtifactActionKind, ...] = Field(default=(), max_length=6)
    source_references: tuple[TutorArtifactSourceReferenceV1, ...] = Field(default=(), max_length=12)
    active_attempt: TutorArtifactAttemptSummaryV1 | None = None

    @model_validator(mode="after")
    def validate_create_shape(self) -> "TutorArtifactCreate":
        terminal_result = (
            self.state is TutorArtifactState.COMPLETED
            and self.artifact_kind is TutorArtifactKind.TEST_RESULT
            and self.purpose is TutorArtifactPurpose.RESULT
            and not self.blocking
            and not self.allowed_actions
            and self.active_attempt is not None
            and self.active_attempt.status == "terminal"
        )
        if self.state.terminal and not terminal_result:
            raise ValueError("only immutable completed test-result artifacts may start terminal")
        if terminal_result:
            if not isinstance(
                self.presentation,
                TutorArtifactTestResultPresentationV1,
            ):
                raise ValueError("terminal test-result Artifact presentation is invalid")
            if (
                self.active_attempt is None
                or self.presentation.attempt_id != self.active_attempt.attempt_id
                or self.presentation.outcome != self.active_attempt.outcome
                or self.presentation.result_hash != self.active_attempt.result_hash
            ):
                raise ValueError(
                    "terminal test-result Artifact Attempt identity is inconsistent"
                )
        if len(self.allowed_actions) != len(set(self.allowed_actions)):
            raise ValueError("artifact allowed actions must be unique")
        if (
            self.active_attempt is not None
            and self.active_attempt.status != "pending"
            and not terminal_result
        ):
            raise ValueError("new artifact active attempt must be pending")
        if not _STABLE_KEY.fullmatch(self.knowledge_key):
            raise ValueError("artifact knowledge key is invalid")
        reference_identities = {
            (
                item.kind,
                item.reference_id,
                item.reference_version,
                item.content_hash,
            )
            for item in self.source_references
        }
        if len(reference_identities) != len(self.source_references):
            raise ValueError("artifact source references must be unique")
        return self


class TutorArtifactRequestHintAction(_StrictArtifactModel):
    action: Literal["request_hint"] = "request_hint"
    hint_level: int | None = Field(default=None, ge=1, le=3)


class TutorArtifactRequestDirectAnswerAction(_StrictArtifactModel):
    action: Literal["request_direct_answer"] = "request_direct_answer"


class TutorArtifactRunAction(_StrictArtifactModel):
    action: Literal["run"] = "run"
    submission: str = Field(min_length=1, max_length=48_000)


class TutorArtifactSingleSelectResponse(_StrictArtifactModel):
    kind: Literal["single_select"] = "single_select"
    value: str = Field(min_length=1, max_length=160)


class TutorArtifactMultiSelectResponse(_StrictArtifactModel):
    kind: Literal["multi_select"] = "multi_select"
    values: tuple[str, ...] = Field(min_length=1, max_length=24)

    @field_validator("values")
    @classmethod
    def validate_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)) or any(not value or len(value) > 160 for value in values):
            raise ValueError("artifact response values must be bounded and unique")
        return values


class TutorArtifactTextResponse(_StrictArtifactModel):
    kind: Literal["prediction", "short_text"]
    text: str = Field(min_length=1, max_length=8_000)


class TutorArtifactOrderingResponse(_StrictArtifactModel):
    kind: Literal["ordering"] = "ordering"
    values: tuple[str, ...] = Field(min_length=1, max_length=24)

    @field_validator("values")
    @classmethod
    def validate_order(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)) or any(not value or len(value) > 160 for value in values):
            raise ValueError("artifact ordering response must be bounded and unique")
        return values


class TutorArtifactCodeRangeResponse(_StrictArtifactModel):
    kind: Literal["code_range"] = "code_range"
    start_line: int = Field(ge=1, le=4_000)
    end_line: int = Field(ge=1, le=4_000)
    category: str = Field(min_length=1, max_length=160)
    note: str = Field(min_length=1, max_length=2_000)

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        if not _STABLE_KEY.fullmatch(value):
            raise ValueError("artifact code-range category is invalid")
        return value

    @model_validator(mode="after")
    def validate_range(self) -> "TutorArtifactCodeRangeResponse":
        if self.end_line < self.start_line:
            raise ValueError("artifact code range is invalid")
        return self


TutorArtifactResponseV1 = Annotated[
    TutorArtifactSingleSelectResponse
    | TutorArtifactMultiSelectResponse
    | TutorArtifactTextResponse
    | TutorArtifactOrderingResponse
    | TutorArtifactCodeRangeResponse,
    Field(discriminator="kind"),
]


class TutorArtifactRespondAction(_StrictArtifactModel):
    action: Literal["respond"] = "respond"
    response: TutorArtifactResponseV1


ModelCodeReviewSubmission = Annotated[
    ModelCodeReviewSubmissionV1 | ModelCodeReviewSubmissionV2,
    Field(discriminator="schema_version"),
]


class TutorArtifactCompleteReviewAction(_StrictArtifactModel):
    action: Literal["complete_review"] = "complete_review"
    review_submission: ModelCodeReviewSubmission


class TutorArtifactCancelAction(_StrictArtifactModel):
    action: Literal["cancel"] = "cancel"
    reason: Literal["learner_cancelled"] = "learner_cancelled"


class TutorArtifactAcknowledgeDemoEventAction(_StrictArtifactModel):
    action: Literal["acknowledge_demo_event"] = "acknowledge_demo_event"
    event_key: str = Field(min_length=1, max_length=160)
    event_nonce: str = Field(min_length=16, max_length=160)


class TutorArtifactDemoInteractionEvidenceV1(_StrictArtifactModel):
    kind: Literal["interactive_event"] = "interactive_event"
    event_key: str = Field(min_length=1, max_length=160)
    payload_json: dict[str, object] = Field(default_factory=dict)
    payload_hash: str = Field(min_length=64, max_length=64)
    preview_nonce: str = Field(min_length=64, max_length=64)
    # The native receipt columns are PostgreSQL INTEGER and the Desktop bridge
    # transports JavaScript numbers, so reject identities neither side can own.
    preview_generation: int = Field(ge=1, le=2_147_483_647)
    preview_sequence: int = Field(ge=1, le=2_147_483_647)

    @field_validator("event_key")
    @classmethod
    def validate_event_key(cls, value: str) -> str:
        if not _STABLE_KEY.fullmatch(value):
            raise ValueError("artifact demonstration event key is invalid")
        return value

    @model_validator(mode="after")
    def validate_evidence(self) -> "TutorArtifactDemoInteractionEvidenceV1":
        if not _SHA256.fullmatch(self.preview_nonce):
            raise ValueError("artifact demonstration Preview nonce is invalid")
        assert_public_artifact_safe(self.payload_json)
        validate_demo_event_payload(self.payload_json)
        if canonical_hash(self.payload_json) != self.payload_hash:
            raise ValueError("artifact demonstration event payload hash does not match")
        return self


class TutorArtifactDemoVisibleClockEvidenceV1(_StrictArtifactModel):
    kind: Literal["visible_clock"] = "visible_clock"
    clock_session_id: str = Field(min_length=1, max_length=160)
    visible_elapsed_ms: int = Field(ge=6_000, le=240_000)
    foreground: Literal[True] = True
    current: Literal[True] = True
    visible: Literal[True] = True
    render_ready: Literal[True] = True

    @field_validator("clock_session_id")
    @classmethod
    def validate_clock_session_id(cls, value: str) -> str:
        if not _ACTION_ID.fullmatch(value):
            raise ValueError("artifact demonstration clock identity is invalid")
        return value


TutorArtifactDemoCompletionEvidenceV1 = Annotated[
    TutorArtifactDemoInteractionEvidenceV1 | TutorArtifactDemoVisibleClockEvidenceV1,
    Field(discriminator="kind"),
]


class TutorArtifactCompleteDemoAction(_StrictArtifactModel):
    action: Literal["complete_demo"] = "complete_demo"
    evidence: TutorArtifactDemoCompletionEvidenceV1


TutorArtifactActionV1 = Annotated[
    TutorArtifactRequestHintAction
    | TutorArtifactRequestDirectAnswerAction
    | TutorArtifactRunAction
    | TutorArtifactRespondAction
    | TutorArtifactCompleteReviewAction
    | TutorArtifactCancelAction
    | TutorArtifactAcknowledgeDemoEventAction
    | TutorArtifactCompleteDemoAction,
    Field(discriminator="action"),
]


class TutorArtifactActionRequest(_StrictArtifactModel):
    user_id: str = Field(min_length=1, max_length=160)
    learning_track_id: str = Field(min_length=1, max_length=160)
    teaching_session_id: str = Field(min_length=1, max_length=160)
    client_action_id: str = Field(min_length=1, max_length=160)
    expected_artifact_version: int = Field(ge=1)
    action: TutorArtifactActionV1

    @field_validator("client_action_id")
    @classmethod
    def validate_client_action_id(cls, value: str) -> str:
        if not _ACTION_ID.fullmatch(value):
            raise ValueError("artifact client_action_id is invalid")
        return value


_PUBLIC_ARTIFACT_ADAPTER: TypeAdapter[TutorPublicArtifactItem] = TypeAdapter(TutorPublicArtifactItem)


def validate_public_artifact(payload: object) -> dict[str, object]:
    artifact = _PUBLIC_ARTIFACT_ADAPTER.validate_python(payload)
    dumped = artifact.model_dump(mode="json", exclude_none=False)
    assert_public_artifact_safe(dumped)
    return dict(dumped)


def assert_public_artifact_safe(payload: object) -> None:
    _assert_safe_keys(payload)
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    lowered = serialized.casefold()
    marker = next((item for item in ARTIFACT_PROTECTED_MARKERS if item.casefold() in lowered), None)
    if marker is not None:
        raise ValueError("public artifact contains a protected marker")


def _assert_safe_keys(value: object) -> None:
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key).casefold()
            if key in _FORBIDDEN_PUBLIC_KEYS:
                raise ValueError(f"public artifact contains protected field: {key}")
            _assert_safe_keys(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _assert_safe_keys(item)


def presentation_kind(presentation: TutorArtifactPresentationV1) -> str:
    return str(presentation.type)


def canonical_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_newlines(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def canonical_response_text(response: TutorArtifactResponseV1) -> str:
    return json.dumps(response.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = (
    "ARTIFACT_PROTECTED_MARKERS",
    "TUTOR_LEARNING_ARTIFACT_ATTEMPT_SCHEMA_VERSION",
    "TUTOR_LEARNING_ARTIFACT_ATTEMPT_V2_SCHEMA_VERSION",
    "TUTOR_LEARNING_ARTIFACT_EVENT_SCHEMA_VERSION",
    "TUTOR_LEARNING_ARTIFACT_POLICY_VERSION",
    "TUTOR_LEARNING_ARTIFACT_SCHEMA_VERSION",
    "TutorArtifactActionKind",
    "TutorArtifactActionRequest",
    "TutorArtifactActionResponseV1",
    "TutorArtifactActionV1",
    "TutorArtifactAcknowledgeDemoEventAction",
    "TutorArtifactAttemptDetailV1",
    "TutorArtifactAttemptDetailV2",
    "TutorArtifactAttemptResultV1",
    "TutorArtifactAttemptResultV2",
    "TutorArtifactAttemptSummaryV1",
    "TutorArtifactBranchSummaryV1",
    "TutorArtifactBranchSummaryV2",
    "TutorArtifactCancelAction",
    "TutorArtifactCompleteDemoAction",
    "TutorArtifactCompleteReviewAction",
    "TutorArtifactCreate",
    "TutorArtifactModelCodeReviewPresentationV2",
    "TutorArtifactDemoCompletionEvidenceV1",
    "TutorArtifactDemoInteractionEvidenceV1",
    "TutorArtifactDemoVisibleClockEvidenceV1",
    "TutorArtifactDemonstrationEventV2",
    "TutorArtifactDemonstrationPresentationV1",
    "TutorArtifactDemonstrationPresentationV2",
    "TutorArtifactDemonstrationStepV2",
    "TutorArtifactDifficulty",
    "TutorArtifactKind",
    "TutorArtifactOwnerKind",
    "TutorArtifactPresentationV1",
    "TutorArtifactPurpose",
    "TutorArtifactRequestDirectAnswerAction",
    "TutorArtifactRequestHintAction",
    "TutorArtifactRespondAction",
    "TutorArtifactResponseV1",
    "TutorArtifactRunAction",
    "TutorArtifactSourceReferenceV1",
    "TutorArtifactSqlWorkspacePresentationV2",
    "TutorArtifactState",
    "TutorPublicArtifactItem",
    "assert_public_artifact_safe",
    "canonical_hash",
    "canonical_response_text",
    "normalize_newlines",
    "presentation_kind",
    "sha256_text",
    "validate_public_artifact",
)
