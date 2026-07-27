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
import re
from datetime import UTC, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$")
_RUNTIME_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*-v[1-9][0-9]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PROTOCOL_VERSION = re.compile(r"^[a-z][a-z0-9-]*-v[1-9][0-9]*$")
_USER = re.compile(r"^[1-9][0-9]{0,6}:[1-9][0-9]{0,6}$")
_IMAGE_REPOSITORY_SEGMENT = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_IMAGE_REGISTRY_SEGMENT = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*(?::[0-9]{1,5})?$")


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
    def validate_times(self) -> "ExecutionIntentProofV1":
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
    def validate_counts(self) -> "SandboxResultV1":
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
    def validate_counts(self) -> "SafeExecutionResultV1":
        if self.passed_test_count > self.total_test_count:
            raise ValueError("passed tests cannot exceed total tests")
        return self

    @classmethod
    def from_sandbox_result(cls, result: SandboxResultV1) -> "SafeExecutionResultV1":
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


class ExecutionJobV1(_FrozenModel):
    """Safe durable queue fact. Image, command, code, and paths are absent."""

    job_id: str = Field(min_length=1, max_length=160)
    effect_id: str = Field(min_length=1, max_length=160)
    intent_proof_id: str = Field(min_length=1, max_length=160)
    user_id: str = Field(min_length=1, max_length=160)
    conversation_id: str = Field(min_length=1, max_length=160)
    run_id: str = Field(min_length=1, max_length=160)
    runtime_id: str = Field(min_length=1, max_length=120)
    lock_fingerprint: str = Field(min_length=64, max_length=64)
    state: ExecutionJobState
    lease_owner_id: str | None = Field(default=None, max_length=160)
    lease_generation: int = Field(default=0, ge=0)
    lease_expires_at: datetime | None = None
    launch_token: str | None = Field(default=None, max_length=160)
    launch_generation: int = Field(default=0, ge=0)
    cancellation_requested_at: datetime | None = None
    result: SafeExecutionResultV1 | None = None
    safe_diagnostic_code: str | None = Field(default=None, max_length=120)

    @field_validator("job_id", "effect_id", "intent_proof_id", "user_id", "conversation_id", "run_id")
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        return _identifier(value, label="execution job field")

    @field_validator("runtime_id")
    @classmethod
    def validate_runtime_id(cls, value: str) -> str:
        return _runtime_id(value)

    @field_validator("lock_fingerprint")
    @classmethod
    def validate_lock_fingerprint(cls, value: str) -> str:
        return _sha256(value, label="lock fingerprint")

    @field_validator("lease_owner_id", "launch_token", "safe_diagnostic_code")
    @classmethod
    def validate_optional_identifiers(cls, value: str | None) -> str | None:
        return None if value is None else _identifier(value, label="execution job identifier")


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
