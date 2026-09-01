"""Closed schemas for the feature-disabled container execution boundary.

These types are pure transport/domain contracts. They do not import database,
environment, subprocess, or container-client modules. Raw submissions and
hidden test bundles are represented only by ``SandboxInputV1``; that model is
executor-local transient input and must never be persisted in an intent, job,
trace, event, or audit record.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import Enum
from typing import Annotated, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$")
_RUNTIME_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*-v[1-9][0-9]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PROTOCOL_VERSION = re.compile(r"^[a-z][a-z0-9-]*-v[1-9][0-9]*$")
_USER = re.compile(r"^[1-9][0-9]{0,6}:[1-9][0-9]{0,6}$")
_IMAGE_REPOSITORY_SEGMENT = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_IMAGE_REGISTRY_SEGMENT = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*(?::[0-9]{1,5})?$")
_SAFE_HIDDEN_CASE_ID = re.compile(r"^non-visible-[1-9][0-9]{0,2}$")

MAX_TABLE_RESULT_COLUMNS = 32
MAX_TABLE_RESULT_ROWS = 200
MAX_TABLE_RESULT_COLUMN_CHARS = 120
MAX_TABLE_RESULT_CELL_CHARS = 500
MAX_TABLE_RESULT_NUMBER_ABS = 9_007_199_254_740_991
MAX_TABLE_RESULT_PAYLOAD_BYTES = 65_536


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


def _identifier(value: object, *, label: str) -> str:
    normalized = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(normalized):
        raise ValueError(f"{label} must be a bounded opaque identifier")
    return normalized


def _sha256(value: object, *, label: str) -> str:
    normalized = str(value or "").lower()
    if not _SHA256.fullmatch(normalized):
        raise ValueError(f"{label} must be a SHA-256 hex digest")
    return normalized


def _runtime_id(value: object) -> str:
    normalized = str(value or "").lower()
    if not _RUNTIME_ID.fullmatch(normalized):
        raise ValueError("runtime id must be a reviewed versioned runtime identifier")
    return normalized


def _protocol_version(value: object) -> str:
    normalized = str(value or "").lower()
    if not _PROTOCOL_VERSION.fullmatch(normalized):
        raise ValueError("protocol version must be a fixed reviewed identifier")
    return normalized


def _fixed_entrypoint(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(str(value).strip() for value in values)
    if any(not value or len(value) > 120 or "\n" in value or "\r" in value for value in normalized):
        raise ValueError("fixed entrypoint values must be bounded")
    if not normalized or not normalized[0].startswith("/"):
        raise ValueError("fixed entrypoint must be an in-image absolute path")
    return normalized


class ExecutionAction(str, Enum):
    RUN = "run"
    TEST = "test"
    DEBUG = "debug"
    EXPLAIN = "explain"


class ExecutionJobState(str, Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    LAUNCH_RESERVED = "launch_reserved"
    RUNNING = "running"
    COMPLETED = "completed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    UNAVAILABLE = "unavailable"
    LAUNCH_UNCERTAIN = "launch_uncertain"
    FAILED = "failed"


class SafeExecutionStatus(str, Enum):
    SUCCESS = "success"
    COMPILE_ERROR = "compile_error"
    RUNTIME_ERROR = "runtime_error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class RuntimeLimitProfileV1(_FrozenModel):
    """Developer-owned hard limits that form part of the reviewed lock."""

    cpu_millis: int = Field(ge=50, le=4000)
    memory_mb: int = Field(ge=32, le=2048)
    pids_limit: int = Field(ge=8, le=256)
    nofile_limit: int = Field(ge=32, le=4096)
    wall_clock_seconds: int = Field(ge=1, le=120)
    max_output_bytes: int = Field(ge=256, le=65536)
    work_tmpfs_mb: int = Field(ge=16, le=512)
    temp_tmpfs_mb: int = Field(ge=8, le=256)


class RuntimeCatalogEntryV1(_FrozenModel):
    """A Git-owned runtime definition, independent from image enablement."""

    runtime_id: str = Field(min_length=1, max_length=120)
    protocol_version: str = Field(min_length=1, max_length=120)
    fixed_entrypoint: tuple[str, ...] = Field(min_length=1, max_length=8)
    non_root_user: str = Field(min_length=3, max_length=32)
    limits: RuntimeLimitProfileV1
    harness_path: str = Field(min_length=1, max_length=240)
    prohibitions: tuple[str, ...] = Field(min_length=1, max_length=12)

    @field_validator("runtime_id")
    @classmethod
    def validate_runtime_id(cls, value: str) -> str:
        return _runtime_id(value)

    @field_validator("protocol_version")
    @classmethod
    def validate_protocol(cls, value: str) -> str:
        return _protocol_version(value)

    @field_validator("fixed_entrypoint")
    @classmethod
    def validate_entrypoint(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _fixed_entrypoint(values)

    @field_validator("non_root_user")
    @classmethod
    def validate_non_root_user(cls, value: str) -> str:
        if not _USER.fullmatch(value):
            raise ValueError("runtime user must be a fixed non-root uid:gid")
        return value

    @field_validator("harness_path")
    @classmethod
    def validate_harness_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/").strip()
        if normalized.startswith("/") or ".." in normalized.split("/") or not normalized.endswith("/"):
            raise ValueError("harness path must be a safe repository-relative directory")
        return normalized

    @field_validator("prohibitions")
    @classmethod
    def validate_prohibitions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_identifier(value, label="runtime prohibition") for value in values)
        if len(normalized) != len(set(normalized)):
            raise ValueError("runtime prohibitions must be unique")
        return normalized


class RuntimeImageLockV1(_FrozenModel):
    """One reviewed immutable image lock; tags and local image ids are invalid."""

    runtime_id: str = Field(min_length=1, max_length=120)
    protocol_version: str = Field(min_length=1, max_length=120)
    image_reference: str = Field(min_length=1, max_length=320)
    fixed_entrypoint: tuple[str, ...] = Field(min_length=1, max_length=8)
    non_root_user: str = Field(min_length=3, max_length=32)
    limits: RuntimeLimitProfileV1

    @field_validator("runtime_id")
    @classmethod
    def validate_runtime_id(cls, value: str) -> str:
        return _runtime_id(value)

    @field_validator("protocol_version")
    @classmethod
    def validate_protocol(cls, value: str) -> str:
        return _protocol_version(value)

    @field_validator("image_reference")
    @classmethod
    def validate_image_reference(cls, value: str) -> str:
        normalized = value.strip().lower()
        repository, separator, digest = normalized.partition("@sha256:")
        if not separator or not repository or not digest or "@" in repository:
            raise ValueError("image reference must use repository@sha256:<digest>")
        if not _is_immutable_repository(repository):
            raise ValueError("image repository is invalid")
        last_segment = repository.rsplit("/", 1)[-1]
        if ":" in last_segment:
            raise ValueError("image tags and local image ids are not allowed")
        if not _SHA256.fullmatch(digest) or len(set(digest)) == 1:
            raise ValueError("image digest must be a non-placeholder SHA-256 digest")
        return normalized

    @field_validator("fixed_entrypoint")
    @classmethod
    def validate_entrypoint(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _fixed_entrypoint(values)

    @field_validator("non_root_user")
    @classmethod
    def validate_non_root_user(cls, value: str) -> str:
        if not _USER.fullmatch(value):
            raise ValueError("runtime user must be a fixed non-root uid:gid")
        return value

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ExecutionBudgetV1(_FrozenModel):
    """Server-issued budget evidence bound into an intent proof."""

    max_execution_count: int = Field(default=1, ge=1, le=1)
    max_wall_clock_seconds: int = Field(ge=1, le=120)
    max_output_bytes: int = Field(ge=256, le=65536)

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ExecutionIntentProofV1(_FrozenModel):
    """Server-issued scope proof. It intentionally has no runtime or image field."""

    proof_id: str = Field(min_length=1, max_length=160)
    user_id: str = Field(min_length=1, max_length=160)
    conversation_id: str = Field(min_length=1, max_length=160)
    run_id: str = Field(min_length=1, max_length=160)
    source_message_id: str = Field(min_length=1, max_length=160)
    exercise_id: str = Field(min_length=1, max_length=160)
    input_revision: int = Field(ge=0)
    origin: Literal["interactive"]
    action: ExecutionAction
    catalog_digest: str = Field(min_length=64, max_length=64)
    policy_fingerprint: str = Field(min_length=64, max_length=64)
    budget_fingerprint: str = Field(min_length=64, max_length=64)
    issued_at: datetime
    expires_at: datetime

    @field_validator("proof_id", "user_id", "conversation_id", "run_id", "source_message_id", "exercise_id")
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        return _identifier(value, label="execution proof field")

    @field_validator("catalog_digest", "policy_fingerprint", "budget_fingerprint")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _sha256(value, label="execution proof fingerprint")

    @model_validator(mode="after")
    def validate_times(self) -> ExecutionIntentProofV1:
        issued_at = _utc(self.issued_at)
        expires_at = _utc(self.expires_at)
        if expires_at <= issued_at:
            raise ValueError("execution intent proof expiry must be after issuance")
        if (expires_at - issued_at).total_seconds() > 900:
            raise ValueError("execution intent proof lifetime is too long")
        return self


class ExecutionEffectProposalV1(_FrozenModel):
    """The only model-visible effect payload: a server proof reference."""

    intent_proof_id: str = Field(min_length=1, max_length=160)

    @field_validator("intent_proof_id")
    @classmethod
    def validate_intent_proof_id(cls, value: str) -> str:
        return _identifier(value, label="intent proof id")


class SafeTestFeedbackV1(_FrozenModel):
    case_id: str = Field(min_length=1, max_length=120)
    passed: bool
    visible: bool
    message: str = Field(default="", max_length=320)
    duration_ms: int = Field(default=0, ge=0, le=120_000)

    @field_validator("case_id")
    @classmethod
    def validate_case_id(cls, value: str) -> str:
        return _identifier(value, label="test case id")


class SafeExecutionLocationV1(_FrozenModel):
    """Learner-visible source coordinates only; paths and runtime frames are forbidden."""

    line: int = Field(ge=1, le=1_000_000)
    column: int | None = Field(default=None, ge=1, le=100_000)
    end_line: int | None = Field(default=None, ge=1, le=1_000_000)
    end_column: int | None = Field(default=None, ge=1, le=100_000)

    @model_validator(mode="after")
    def validate_range(self) -> SafeExecutionLocationV1:
        if self.end_column is not None and self.end_line is None:
            raise ValueError("execution location end_column requires end_line")
        if self.end_line is not None and self.end_line < self.line:
            raise ValueError("execution location end_line precedes line")
        if (
            self.end_line == self.line
            and self.column is not None
            and self.end_column is not None
            and self.end_column < self.column
        ):
            raise ValueError("execution location end_column precedes column")
        return self


class SafeTestFeedbackV2(_FrozenModel):
    case_id: str = Field(min_length=1, max_length=120)
    passed: bool
    visible: bool
    message: str = Field(default="", max_length=320)
    duration_ms: int = Field(default=0, ge=0, le=120_000)
    location: SafeExecutionLocationV1 | None = None

    @field_validator("case_id")
    @classmethod
    def validate_case_id(cls, value: str) -> str:
        return _identifier(value, label="test case id")

    @model_validator(mode="after")
    def validate_visibility(self) -> SafeTestFeedbackV2:
        if not self.visible and self.location is not None:
            raise ValueError("non-visible feedback cannot expose a source location")
        return self


class SandboxTestFeedbackV1(_FrozenModel):
    """Bounded raw harness feedback. Convert it before durable storage."""

    case_id: str = Field(min_length=1, max_length=120)
    passed: bool
    visibility: Literal["visible", "hidden"]
    message: str = Field(default="", max_length=4_000)
    duration_ms: int = Field(default=0, ge=0, le=120_000)

    @field_validator("case_id")
    @classmethod
    def validate_case_id(cls, value: str) -> str:
        return _identifier(value, label="sandbox test case id")


class SandboxInputV1(_FrozenModel):
    """Transient executor-to-image input; never persist or log this model."""

    schema_version: Literal["sandbox-input-v1"] = "sandbox-input-v1"
    runtime_id: str = Field(min_length=1, max_length=120)
    action: ExecutionAction
    submission: str = Field(min_length=1, max_length=48_000)
    visible_test_bundle_json: str = Field(default="[]", max_length=48_000)
    hidden_test_bundle_json: str = Field(default="[]", max_length=48_000)
    source_reference_hash: str = Field(min_length=64, max_length=64)
    test_reference_hash: str = Field(min_length=64, max_length=64)

    @field_validator("runtime_id")
    @classmethod
    def validate_runtime_id(cls, value: str) -> str:
        return _runtime_id(value)

    @field_validator("source_reference_hash", "test_reference_hash")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _sha256(value, label="trusted input reference")

    def wire_bytes(self) -> bytes:
        return self.model_dump_json(exclude_none=True).encode("utf-8")


class SandboxResultV1(_FrozenModel):
    """Bounded raw result accepted from a fixed in-image protocol harness."""

    schema_version: Literal["sandbox-result-v1"] = "sandbox-result-v1"
    status: SafeExecutionStatus
    stdout: str = Field(default="", max_length=65_536)
    stderr: str = Field(default="", max_length=65_536)
    test_feedback: tuple[SandboxTestFeedbackV1, ...] = Field(default=(), max_length=64)
    passed_test_count: int = Field(default=0, ge=0, le=10_000)
    total_test_count: int = Field(default=0, ge=0, le=10_000)
    duration_ms: int = Field(default=0, ge=0, le=120_000)
    diagnostic_code: str = Field(default="sandbox_result", min_length=1, max_length=120)

    @field_validator("diagnostic_code")
    @classmethod
    def validate_diagnostic(cls, value: str) -> str:
        return _identifier(value, label="sandbox diagnostic code")

    @model_validator(mode="after")
    def validate_counts(self) -> SandboxResultV1:
        if self.passed_test_count > self.total_test_count:
            raise ValueError("passed tests cannot exceed total tests")
        return self


class SafeExecutionResultV1(_FrozenModel):
    """Learner-safe bounded result persisted by the executor and read by API."""

    status: SafeExecutionStatus
    stdout: str = Field(default="", max_length=4_000)
    stderr: str = Field(default="", max_length=2_000)
    test_feedback: tuple[SafeTestFeedbackV1, ...] = Field(default=(), max_length=64)
    passed_test_count: int = Field(default=0, ge=0, le=10_000)
    total_test_count: int = Field(default=0, ge=0, le=10_000)
    duration_ms: int = Field(default=0, ge=0, le=120_000)
    diagnostic_code: str = Field(default="execution_result", min_length=1, max_length=120)

    @field_validator("diagnostic_code")
    @classmethod
    def validate_diagnostic(cls, value: str) -> str:
        return _identifier(value, label="safe execution diagnostic code")

    @model_validator(mode="after")
    def validate_counts(self) -> SafeExecutionResultV1:
        if self.passed_test_count > self.total_test_count:
            raise ValueError("passed tests cannot exceed total tests")
        return self

    @classmethod
    def from_sandbox_result(cls, result: SandboxResultV1) -> SafeExecutionResultV1:
        from aearn_shared.execution.redaction import sanitize_execution_text

        feedback: list[SafeTestFeedbackV1] = []
        for index, item in enumerate(result.test_feedback, start=1):
            if item.visibility == "hidden":
                feedback.append(
                    SafeTestFeedbackV1(
                        # A hidden-case identifier is part of hidden test data;
                        # replace it with a deterministic opaque public ordinal.
                        case_id=f"non-visible-{index}",
                        passed=item.passed,
                        visible=False,
                        message="Hidden test passed." if item.passed else "A non-visible scenario still failed.",
                        duration_ms=item.duration_ms,
                    )
                )
            else:
                feedback.append(
                    SafeTestFeedbackV1(
                        case_id=item.case_id,
                        passed=item.passed,
                        visible=True,
                        message=sanitize_execution_text(item.message, limit=320),
                        duration_ms=item.duration_ms,
                    )
                )
        return cls(
            status=result.status,
            stdout=sanitize_execution_text(result.stdout, limit=4_000),
            stderr=sanitize_execution_text(result.stderr, limit=2_000),
            test_feedback=tuple(feedback),
            passed_test_count=result.passed_test_count,
            total_test_count=result.total_test_count,
            duration_ms=result.duration_ms,
            diagnostic_code=result.diagnostic_code,
        )


SafeTableResultColumnV1: TypeAlias = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=MAX_TABLE_RESULT_COLUMN_CHARS),
]
SafeTableResultTextCellV1: TypeAlias = Annotated[
    StrictStr,
    StringConstraints(max_length=MAX_TABLE_RESULT_CELL_CHARS),
]
SafeTableResultIntegerCellV1: TypeAlias = Annotated[
    StrictInt,
    Field(ge=-MAX_TABLE_RESULT_NUMBER_ABS, le=MAX_TABLE_RESULT_NUMBER_ABS),
]
SafeTableResultFloatCellV1: TypeAlias = Annotated[
    StrictFloat,
    Field(ge=-MAX_TABLE_RESULT_NUMBER_ABS, le=MAX_TABLE_RESULT_NUMBER_ABS),
]
SafeTableResultCellV1: TypeAlias = (
    SafeTableResultTextCellV1
    | StrictBool
    | SafeTableResultIntegerCellV1
    | SafeTableResultFloatCellV1
    | None
)


class SafeExecutionPresentationNoneV1(_FrozenModel):
    """Explicit absence of a rich result presentation."""

    kind: Literal["none"] = "none"


class SafeTableResultPresentationV1(_FrozenModel):
    """Bounded learner-visible positional table data, never hidden scorer data."""

    kind: Literal["table_result_v1"] = "table_result_v1"
    columns: tuple[SafeTableResultColumnV1, ...] = Field(
        min_length=1,
        max_length=MAX_TABLE_RESULT_COLUMNS,
    )
    rows: tuple[tuple[SafeTableResultCellV1, ...], ...] = Field(
        default=(),
        max_length=MAX_TABLE_RESULT_ROWS,
    )

    @field_validator("columns")
    @classmethod
    def validate_columns(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        from aearn_shared.execution.redaction import contains_protected_execution_text

        if len(values) != len(set(values)):
            raise ValueError("table result columns must be unique")
        if any(contains_protected_execution_text(value) for value in values):
            raise ValueError("table result columns contain protected execution content")
        return values

    @field_validator("rows")
    @classmethod
    def validate_cells(
        cls,
        rows: tuple[tuple[SafeTableResultCellV1, ...], ...],
    ) -> tuple[tuple[SafeTableResultCellV1, ...], ...]:
        from aearn_shared.execution.redaction import contains_protected_execution_text

        for row in rows:
            for cell in row:
                if isinstance(cell, float) and not math.isfinite(cell):
                    raise ValueError("table result numbers must be finite")
                if isinstance(cell, str) and contains_protected_execution_text(cell):
                    raise ValueError("table result cells contain protected execution content")
        return rows

    @model_validator(mode="after")
    def validate_shape_and_payload(self) -> SafeTableResultPresentationV1:
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("table result rows must align with columns")
        payload = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(payload) > MAX_TABLE_RESULT_PAYLOAD_BYTES:
            raise ValueError("table result payload exceeds the learner-safe bound")
        return self


SafeExecutionPresentationV1: TypeAlias = Annotated[
    SafeExecutionPresentationNoneV1 | SafeTableResultPresentationV1,
    Field(discriminator="kind"),
]


class SafeExecutionResultV2(_FrozenModel):
    """Strict learner-safe result with one closed, bounded presentation variant."""

    schema_version: Literal["safe-execution-result-v2"]
    status: SafeExecutionStatus
    stdout: str = Field(default="", max_length=4_000)
    stderr: str = Field(default="", max_length=2_000)
    test_feedback: tuple[SafeTestFeedbackV2, ...] = Field(default=(), max_length=64)
    passed_test_count: int = Field(default=0, ge=0, le=10_000)
    total_test_count: int = Field(default=0, ge=0, le=10_000)
    duration_ms: int = Field(default=0, ge=0, le=120_000)
    diagnostic_code: str = Field(default="execution_result", min_length=1, max_length=120)
    presentation: SafeExecutionPresentationV1

    @field_validator("diagnostic_code")
    @classmethod
    def validate_diagnostic(cls, value: str) -> str:
        return _identifier(value, label="safe execution diagnostic code")

    @field_validator("stdout", "stderr")
    @classmethod
    def validate_output_text(cls, value: str) -> str:
        from aearn_shared.execution.redaction import contains_protected_execution_text

        if contains_protected_execution_text(value):
            raise ValueError("safe execution output contains protected content")
        return value

    @model_validator(mode="after")
    def validate_result(self) -> SafeExecutionResultV2:
        from aearn_shared.execution.redaction import contains_protected_execution_text

        if self.passed_test_count > self.total_test_count:
            raise ValueError("passed tests cannot exceed total tests")
        if len(self.test_feedback) > self.total_test_count:
            raise ValueError("test feedback cannot exceed total tests")

        seen_ids: set[str] = set()
        hidden_ordinal = 0
        feedback_passed = 0
        for item in self.test_feedback:
            if item.case_id in seen_ids:
                raise ValueError("test feedback case ids must be unique")
            seen_ids.add(item.case_id)
            feedback_passed += int(item.passed)
            if item.visible:
                if contains_protected_execution_text(item.case_id) or contains_protected_execution_text(item.message):
                    raise ValueError("visible test feedback contains protected content")
                continue
            hidden_ordinal += 1
            expected_id = f"non-visible-{hidden_ordinal}"
            expected_message = (
                "A non-visible scenario passed."
                if item.passed
                else "A non-visible scenario still failed."
            )
            if not _SAFE_HIDDEN_CASE_ID.fullmatch(item.case_id) or item.case_id != expected_id:
                raise ValueError("non-visible feedback must use opaque sequential ordinals")
            if item.message != expected_message:
                raise ValueError("non-visible feedback must use the fixed safe message")

        if feedback_passed > self.passed_test_count:
            raise ValueError("passing feedback cannot exceed the passed test count")
        feedback_failed = len(self.test_feedback) - feedback_passed
        if feedback_failed > self.total_test_count - self.passed_test_count:
            raise ValueError("failing feedback cannot exceed the failed test count")
        if isinstance(self.presentation, SafeTableResultPresentationV1) and self.status is not SafeExecutionStatus.SUCCESS:
            raise ValueError("table result presentation requires successful runtime execution")
        return self

    @classmethod
    def from_v1(cls, result: SafeExecutionResultV1) -> SafeExecutionResultV2:
        """Convert a validated historical v1 result into the strict v2 shape."""

        return adapt_safe_execution_result_v1(result)

    @classmethod
    def from_sandbox_result(cls, result: SandboxResultV1) -> SafeExecutionResultV2:
        """Redact raw fixed-harness output and emit the new durable result version."""

        return adapt_safe_execution_result_v1(SafeExecutionResultV1.from_sandbox_result(result))


SafeExecutionResult: TypeAlias = SafeExecutionResultV1 | SafeExecutionResultV2


def adapt_safe_execution_result_v1(result: SafeExecutionResultV1) -> SafeExecutionResultV2:
    """Safely upgrade a historical v1 result without inventing rich presentation data."""

    from aearn_shared.execution.redaction import (
        contains_protected_execution_text,
        sanitize_execution_text,
    )

    feedback: list[SafeTestFeedbackV2] = []
    hidden_ordinal = 0
    for index, item in enumerate(result.test_feedback, start=1):
        if not item.visible:
            hidden_ordinal += 1
            feedback.append(
                SafeTestFeedbackV2(
                    case_id=f"non-visible-{hidden_ordinal}",
                    passed=item.passed,
                    visible=False,
                    message=(
                        "A non-visible scenario passed."
                        if item.passed
                        else "A non-visible scenario still failed."
                    ),
                    duration_ms=item.duration_ms,
                )
            )
            continue
        case_id = item.case_id
        if contains_protected_execution_text(case_id):
            case_id = f"visible-{index}"
        feedback.append(
            SafeTestFeedbackV2(
                case_id=case_id,
                passed=item.passed,
                visible=True,
                message=sanitize_execution_text(item.message, limit=320),
                duration_ms=item.duration_ms,
            )
        )
    return SafeExecutionResultV2(
        schema_version="safe-execution-result-v2",
        status=result.status,
        stdout=sanitize_execution_text(result.stdout, limit=4_000),
        stderr=sanitize_execution_text(result.stderr, limit=2_000),
        test_feedback=tuple(feedback),
        passed_test_count=result.passed_test_count,
        total_test_count=result.total_test_count,
        duration_ms=result.duration_ms,
        diagnostic_code=result.diagnostic_code,
        presentation=SafeExecutionPresentationNoneV1(),
    )


def parse_safe_execution_result(value: object) -> SafeExecutionResultV2:
    """Read strict v2 data or explicitly adapt an unversioned historical v1 row."""

    if isinstance(value, SafeExecutionResultV2):
        return value
    if isinstance(value, SafeExecutionResultV1):
        return adapt_safe_execution_result_v1(value)
    if not isinstance(value, Mapping):
        raise TypeError("safe execution result must be an object")
    if "schema_version" not in value:
        return adapt_safe_execution_result_v1(SafeExecutionResultV1.model_validate(value))
    if value.get("schema_version") != "safe-execution-result-v2":
        raise ValueError("safe execution result schema version is unsupported")
    return SafeExecutionResultV2.model_validate(value)


class ExecutionJobV1(_FrozenModel):
    """Safe durable queue fact for either a Tutor effect or exercise Attempt."""

    job_id: str = Field(min_length=1, max_length=160)
    intent_proof_id: str = Field(min_length=1, max_length=160)
    user_id: str = Field(min_length=1, max_length=160)
    runtime_id: str = Field(min_length=1, max_length=120)
    lock_fingerprint: str = Field(min_length=64, max_length=64)
    state: ExecutionJobState
    owner_kind: Literal["tutor_effect", "exercise_attempt", "model_review_validation"] = "tutor_effect"
    effect_id: str | None = Field(default=None, max_length=160)
    conversation_id: str | None = Field(default=None, max_length=160)
    run_id: str | None = Field(default=None, max_length=160)
    exercise_attempt_id: str | None = Field(default=None, max_length=160)
    model_review_validation_id: str | None = Field(default=None, max_length=160)
    lease_owner_id: str | None = Field(default=None, max_length=160)
    lease_generation: int = Field(default=0, ge=0)
    lease_expires_at: datetime | None = None
    launch_token: str | None = Field(default=None, max_length=160)
    launch_generation: int = Field(default=0, ge=0)
    cancellation_requested_at: datetime | None = None
    result: SafeExecutionResult | None = None
    safe_diagnostic_code: str | None = Field(default=None, max_length=120)

    @field_validator("job_id", "intent_proof_id", "user_id")
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        return _identifier(value, label="execution job field")

    @field_validator(
        "effect_id",
        "conversation_id",
        "run_id",
        "exercise_attempt_id",
        "model_review_validation_id",
        "lease_owner_id",
        "launch_token",
        "safe_diagnostic_code",
    )
    @classmethod
    def validate_optional_identifiers(cls, value: str | None) -> str | None:
        return None if value is None else _identifier(value, label="execution job identifier")

    @field_validator("runtime_id")
    @classmethod
    def validate_runtime_id(cls, value: str) -> str:
        return _runtime_id(value)

    @field_validator("lock_fingerprint")
    @classmethod
    def validate_lock_fingerprint(cls, value: str) -> str:
        return _sha256(value, label="lock fingerprint")

    @model_validator(mode="after")
    def validate_owner(self) -> ExecutionJobV1:
        tutor_shape = self.effect_id is not None and self.conversation_id is not None and self.run_id is not None
        gate_shape = self.exercise_attempt_id is not None
        review_shape = self.model_review_validation_id is not None and self.conversation_id is not None and self.run_id is not None
        if self.owner_kind == "tutor_effect" and (not tutor_shape or gate_shape or self.model_review_validation_id is not None):
            raise ValueError("Tutor execution job owner shape is invalid")
        if self.owner_kind == "exercise_attempt" and (tutor_shape or not gate_shape or self.model_review_validation_id is not None):
            raise ValueError("exercise Attempt job owner shape is invalid")
        if self.owner_kind == "model_review_validation" and (
            self.effect_id is not None or gate_shape or not review_shape
        ):
            raise ValueError("model review validation job owner shape is invalid")
        return self


class ExecutionJobClaimV1(_FrozenModel):
    job_id: str = Field(min_length=1, max_length=160)
    executor_id: str = Field(min_length=1, max_length=160)
    lease_generation: int = Field(ge=1)
    lease_expires_at: datetime

    @field_validator("job_id", "executor_id")
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        return _identifier(value, label="execution claim field")


class ExecutionHealthV1(_FrozenModel):
    executor_id: str = Field(min_length=1, max_length=160)
    service_version: str = Field(min_length=1, max_length=120)
    registry_fingerprint: str = Field(min_length=64, max_length=64)
    status: Literal["available", "unavailable", "quarantined"]
    verified_runtime_ids: tuple[str, ...] = Field(default=(), max_length=7)
    availability_code: str = Field(min_length=1, max_length=120)
    last_heartbeat_at: datetime

    @field_validator("executor_id", "service_version", "availability_code")
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        return _identifier(value, label="executor health field")

    @field_validator("registry_fingerprint")
    @classmethod
    def validate_registry_fingerprint(cls, value: str) -> str:
        return _sha256(value, label="registry fingerprint")

    @field_validator("verified_runtime_ids")
    @classmethod
    def validate_runtimes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_runtime_id(value) for value in values)
        if len(normalized) != len(set(normalized)):
            raise ValueError("verified runtimes must be unique")
        return normalized


def _is_immutable_repository(repository: str) -> bool:
    if (
        not repository
        or len(repository) > 240
        or "://" in repository
        or repository.startswith(("/", "."))
        or "//" in repository
        or any(character.isspace() for character in repository)
    ):
        return False
    segments = repository.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        return False
    for index, segment in enumerate(segments):
        if index == 0 and ":" in segment:
            if not _IMAGE_REGISTRY_SEGMENT.fullmatch(segment):
                return False
        elif not _IMAGE_REPOSITORY_SEGMENT.fullmatch(segment):
            return False
    return True


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
