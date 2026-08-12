"""Immutable contracts for the Tutor controlled Action Runtime."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agents.harness.capabilities import (
    GROUNDING_RETRIEVE_DESCRIPTOR,
    LEARNING_PLAN_DRAFT_DESCRIPTOR,
    LearningPlanDraftCapabilityOutput,
    contains_forbidden_execution_target,
    is_catalog_identifier,
    is_exact_semver,
)
from app.agents.harness.contracts import TutorContextSource, TutorPayloadField, TutorRunSnapshot
from app.core.teaching_safety import sanitize_summary_text


ACTION_CONTRACT_SCHEMA_VERSION = "tutor-action-contract-v1"
ACTION_RECEIPT_SCHEMA_VERSION = "tutor-action-receipt-v1"
MAX_ACTION_SAFE_SUMMARY_LENGTH = 160

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ActionSideEffectClass(StrEnum):
    READ_ONLY = "read_only"
    PROPOSAL = "proposal"
    TRANSACTIONAL = "transactional"
    EXTERNAL_EXECUTION = "external_execution"


class ActionRetryClass(StrEnum):
    NEVER = "never"
    SAFE_READ = "safe_read"
    IDEMPOTENT = "idempotent"


class ActionNetworkClass(StrEnum):
    NONE = "none"
    APPROVED_REGISTRY = "approved_registry"
    EXECUTOR_MANAGED = "executor_managed"


class ActionLifecycleStatus(StrEnum):
    REQUESTED = "requested"
    ADMITTED = "admitted"
    RUNNING = "running"
    SUCCEEDED_UNVERIFIED = "succeeded_unverified"
    VERIFIED = "verified"
    RETRYABLE_FAILED = "retryable_failed"
    PERMANENT_FAILED = "permanent_failed"
    DENIED = "denied"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    SUPERSEDED = "superseded"

    @property
    def terminal(self) -> bool:
        return self in {
            ActionLifecycleStatus.VERIFIED,
            ActionLifecycleStatus.RETRYABLE_FAILED,
            ActionLifecycleStatus.PERMANENT_FAILED,
            ActionLifecycleStatus.DENIED,
            ActionLifecycleStatus.CANCELLED,
            ActionLifecycleStatus.TIMED_OUT,
            ActionLifecycleStatus.SUPERSEDED,
        }


class ActionExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    RETRYABLE_FAILED = "retryable_failed"
    PERMANENT_FAILED = "permanent_failed"
    DENIED = "denied"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    SUPERSEDED = "superseded"


class ActionVerificationStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"
    NOT_REQUIRED = "not_required"


class ActionRecoveryKind(StrEnum):
    NONE = "none"
    RETRY = "retry"
    REBUILD_CONTEXT = "rebuild_context"
    REQUEST_CLARIFICATION = "request_clarification"
    SAFE_STOP = "safe_stop"


class ActionAuthorityKind(StrEnum):
    CAPABILITY_INVOCATION = "capability_invocation"
    PLAN_DRAFT = "plan_draft"
    EXECUTION_JOB = "execution_job"
    EFFECT_RECEIPT = "effect_receipt"
    GROUNDING_RESULT = "grounding_result"


class _FrozenActionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)




class GroundingRetrieveActionOutput(_FrozenActionModel):
    status: Literal["completed"]
    source_ids: tuple[str, ...] = Field(default=(), max_length=4)
    citation_ids: tuple[str, ...] = Field(default=(), max_length=4)
    content_hashes: tuple[str, ...] = Field(default=(), max_length=4)

    @field_validator("source_ids", "citation_ids")
    @classmethod
    def _validate_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_safe_id(value, label="grounding evidence id") for value in values)
        if len(normalized) != len(set(normalized)):
            raise ValueError("grounding evidence ids must be unique")
        return normalized

    @field_validator("content_hashes")
    @classmethod
    def _validate_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_sha256(value, label="grounding content hash") for value in values)

    def model_post_init(self, __context: object) -> None:
        del __context
        if not (len(self.source_ids) == len(self.citation_ids) == len(self.content_hashes)):
            raise ValueError("grounding action evidence must be paired")


class RunnerExecuteActionInput(_FrozenActionModel):
    intent_proof_id: str = Field(min_length=1, max_length=160)

    @field_validator("intent_proof_id")
    @classmethod
    def _validate_proof_id(cls, value: str) -> str:
        return _safe_id(value, label="runner intent proof id")


class RunnerExecuteActionOutput(_FrozenActionModel):
    status: str = Field(min_length=1, max_length=40)
    execution_job_id: str = Field(min_length=1, max_length=160)
    execution_state: str = Field(min_length=1, max_length=40)

    @field_validator("execution_job_id")
    @classmethod
    def _validate_job_id(cls, value: str) -> str:
        return _safe_id(value, label="execution job id")

    @field_validator("status", "execution_state")
    @classmethod
    def _validate_state(cls, value: str) -> str:
        return _safe_id(value, label="runner execution state")


@dataclass(frozen=True, slots=True)
class ActionResourceProfile:
    """Developer-owned maximum resource envelope for one action."""

    profile_id: str
    network_class: ActionNetworkClass = ActionNetworkClass.NONE
    allow_approved_sources: bool = False
    allowed_artifact_kinds: tuple[str, ...] = ()
    execution_profile_ids: tuple[str, ...] = ()
    temporary_workspace: bool = False
    max_input_bytes: int = 16_384
    max_output_bytes: int = 16_384
    max_cost_units: int = 1
    max_concurrency: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_id", _safe_id(self.profile_id, label="resource profile id"))
        for name in ("allowed_artifact_kinds", "execution_profile_ids"):
            values = tuple(_safe_id(item, label=name) for item in getattr(self, name))
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must contain unique values")
            object.__setattr__(self, name, values)
        for name in ("max_input_bytes", "max_output_bytes", "max_cost_units", "max_concurrency"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")

    @property
    def fingerprint(self) -> str:
        return _hash(
            {
                "profile_id": self.profile_id,
                "network_class": self.network_class.value,
                "allow_approved_sources": self.allow_approved_sources,
                "allowed_artifact_kinds": self.allowed_artifact_kinds,
                "execution_profile_ids": self.execution_profile_ids,
                "temporary_workspace": self.temporary_workspace,
                "max_input_bytes": self.max_input_bytes,
                "max_output_bytes": self.max_output_bytes,
                "max_cost_units": self.max_cost_units,
                "max_concurrency": self.max_concurrency,
            }
        )


@dataclass(frozen=True, slots=True)
class ActionResourceRequest:
    source_ids: tuple[str, ...] = ()
    artifact_ids: tuple[str, ...] = ()
    artifact_kinds: tuple[str, ...] = ()
    execution_profile_id: str | None = None
    network_class: ActionNetworkClass = ActionNetworkClass.NONE
    temporary_workspace: bool = False
    input_bytes: int = 0
    expected_output_bytes: int = 0
    cost_units: int = 0

    def __post_init__(self) -> None:
        for name in ("source_ids", "artifact_ids", "artifact_kinds"):
            values = tuple(_safe_id(item, label=name) for item in getattr(self, name))
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must contain unique values")
            object.__setattr__(self, name, values)
        if self.execution_profile_id is not None:
            object.__setattr__(
                self,
                "execution_profile_id",
                _safe_id(self.execution_profile_id, label="execution profile id"),
            )
        for name in ("input_bytes", "expected_output_bytes", "cost_units"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")

    @property
    def fingerprint(self) -> str:
        return _hash(
            {
                "source_ids": self.source_ids,
                "artifact_ids": self.artifact_ids,
                "artifact_kinds": self.artifact_kinds,
                "execution_profile_id": self.execution_profile_id,
                "network_class": self.network_class.value,
                "temporary_workspace": self.temporary_workspace,
                "input_bytes": self.input_bytes,
                "expected_output_bytes": self.expected_output_bytes,
                "cost_units": self.cost_units,
            }
        )


@dataclass(frozen=True, slots=True)
class ActionRetryPolicy:
    retry_class: ActionRetryClass = ActionRetryClass.NEVER
    max_attempts: int = 1
    backoff_seconds: tuple[int, ...] = ()
    retryable_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 4:
            raise ValueError("action max_attempts must be within 1..4")
        if self.retry_class is ActionRetryClass.NEVER and self.max_attempts != 1:
            raise ValueError("non-retryable action must have one attempt")
        backoff = tuple(self.backoff_seconds)
        if len(backoff) > self.max_attempts - 1 or any(value < 0 or value > 300 for value in backoff):
            raise ValueError("action retry backoff is invalid")
        codes = tuple(_safe_id(item, label="retryable code") for item in self.retryable_codes)
        if len(codes) != len(set(codes)):
            raise ValueError("retryable codes must be unique")
        object.__setattr__(self, "backoff_seconds", backoff)
        object.__setattr__(self, "retryable_codes", codes)


@dataclass(frozen=True, slots=True)
class ActionDescriptor:
    action_id: str
    version: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    owner_adapter_id: str
    owner_adapter_version: str
    allowed_origins: tuple[str, ...]
    allowed_task_kinds: tuple[str, ...]
    resource_profile: ActionResourceProfile
    timeout_seconds: int
    side_effect_class: ActionSideEffectClass
    retry_policy: ActionRetryPolicy
    verifier_id: str
    verifier_version: str
    recovery_kinds: tuple[ActionRecoveryKind, ...]
    public_projection_policy: str = "bounded_safe_metadata"

    def __post_init__(self) -> None:
        if not is_catalog_identifier(self.action_id):
            raise ValueError("action id must be a stable catalog identifier")
        for name in ("version", "owner_adapter_version", "verifier_version"):
            if not is_exact_semver(getattr(self, name)):
                raise ValueError(f"{name} must be exact SemVer")
        for name in ("owner_adapter_id", "verifier_id", "public_projection_policy"):
            object.__setattr__(self, name, _safe_id(getattr(self, name), label=name))
        if not issubclass(self.input_model, BaseModel) or not issubclass(self.output_model, BaseModel):
            raise TypeError("action schemas must use Pydantic models")
        origins = tuple(_safe_id(value, label="action origin") for value in self.allowed_origins)
        task_kinds = tuple(_safe_id(value, label="action task kind") for value in self.allowed_task_kinds)
        if not origins or len(origins) != len(set(origins)):
            raise ValueError("allowed action origins must be non-empty and unique")
        if not task_kinds or len(task_kinds) != len(set(task_kinds)):
            raise ValueError("allowed action task kinds must be non-empty and unique")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 3600:
            raise ValueError("action timeout must be within 1..3600 seconds")
        recovery = tuple(self.recovery_kinds)
        if len(recovery) != len(set(recovery)):
            raise ValueError("action recovery kinds must be unique")
        object.__setattr__(self, "allowed_origins", origins)
        object.__setattr__(self, "allowed_task_kinds", task_kinds)
        object.__setattr__(self, "recovery_kinds", recovery)

    @property
    def reference(self) -> str:
        return f"{self.action_id}@{self.version}"

    @property
    def contract_hash(self) -> str:
        return _hash(self.catalog_definition())

    def catalog_definition(self) -> dict[str, object]:
        return {
            "schema_version": ACTION_CONTRACT_SCHEMA_VERSION,
            "action_id": self.action_id,
            "version": self.version,
            "input_schema": self.input_model.model_json_schema(),
            "output_schema": self.output_model.model_json_schema(),
            "owner_adapter_id": self.owner_adapter_id,
            "owner_adapter_version": self.owner_adapter_version,
            "allowed_origins": self.allowed_origins,
            "allowed_task_kinds": self.allowed_task_kinds,
            "resource_profile_fingerprint": self.resource_profile.fingerprint,
            "timeout_seconds": self.timeout_seconds,
            "side_effect_class": self.side_effect_class.value,
            "retry_class": self.retry_policy.retry_class.value,
            "max_attempts": self.retry_policy.max_attempts,
            "verifier_id": self.verifier_id,
            "verifier_version": self.verifier_version,
            "recovery_kinds": tuple(item.value for item in self.recovery_kinds),
            "public_projection_policy": self.public_projection_policy,
        }


@dataclass(frozen=True, slots=True)
class ActionAuthorityReference:
    kind: ActionAuthorityKind
    reference_id: str
    reference_hash: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "reference_id", _safe_id(self.reference_id, label="authority reference id"))
        if self.reference_hash is not None:
            object.__setattr__(self, "reference_hash", _sha256(self.reference_hash, label="authority reference hash"))


@dataclass(frozen=True, slots=True)
class ActionInvocation:
    invocation_id: str
    idempotency_key: str
    stable_action_key: str
    action_id: str
    action_version: str
    run_id: str
    conversation_id: str
    user_id: str
    origin: str
    task_kind: str
    input_revision: int
    lease_owner_id: str
    lease_generation: int
    action_generation: int
    catalog_digest: str
    policy_fingerprint: str
    arguments: Mapping[str, object]
    resource_request: ActionResourceRequest
    requested_at: datetime
    selected_skill_reference: str | None = None
    parent_invocation_id: str | None = None
    retry_index: int = 0

    def __post_init__(self) -> None:
        for name in (
            "invocation_id",
            "idempotency_key",
            "stable_action_key",
            "run_id",
            "conversation_id",
            "user_id",
            "origin",
            "task_kind",
            "lease_owner_id",
        ):
            object.__setattr__(self, name, _safe_id(getattr(self, name), label=name))
        if not is_catalog_identifier(self.action_id) or not is_exact_semver(self.action_version):
            raise ValueError("action invocation reference is invalid")
        if self.input_revision < 0 or self.lease_generation < 1 or self.action_generation < 1 or self.retry_index < 0:
            raise ValueError("action invocation generation metadata is invalid")
        object.__setattr__(self, "catalog_digest", _sha256(self.catalog_digest, label="catalog digest"))
        object.__setattr__(self, "policy_fingerprint", _sha256(self.policy_fingerprint, label="policy fingerprint"))
        if self.selected_skill_reference is not None:
            object.__setattr__(
                self,
                "selected_skill_reference",
                _safe_id(self.selected_skill_reference, label="selected Skill reference"),
            )
        if self.parent_invocation_id is not None:
            object.__setattr__(
                self,
                "parent_invocation_id",
                _safe_id(self.parent_invocation_id, label="parent invocation id"),
            )
        if self.requested_at.tzinfo is None:
            raise ValueError("action requested_at must be timezone-aware")
        object.__setattr__(self, "requested_at", self.requested_at.astimezone(UTC))
        object.__setattr__(self, "arguments", dict(self.arguments))

    @property
    def request_hash(self) -> str:
        return _hash(
            {
                "action_id": self.action_id,
                "action_version": self.action_version,
                "input_revision": self.input_revision,
                "arguments": self.arguments,
                "resource_request_hash": self.resource_request.fingerprint,
            }
        )


@dataclass(frozen=True, slots=True)
class ActionExecutionResult:
    status: ActionExecutionStatus
    authority: ActionAuthorityReference | None = None
    output: Mapping[str, object] | None = None
    safe_summary: str = ""
    diagnostic_code: str | None = None
    duration_ms: int = 0

    def __post_init__(self) -> None:
        if self.duration_ms < 0:
            raise ValueError("action duration must be non-negative")
        object.__setattr__(self, "safe_summary", _safe_summary(self.safe_summary))
        if self.diagnostic_code is not None:
            object.__setattr__(self, "diagnostic_code", _safe_id(self.diagnostic_code, label="action diagnostic code"))
        if self.status is ActionExecutionStatus.SUCCEEDED and self.authority is None:
            raise ValueError("successful action execution requires an authority reference")
        if self.output is not None:
            object.__setattr__(self, "output", dict(self.output))

    @property
    def result_hash(self) -> str:
        return _hash(
            {
                "status": self.status.value,
                "authority_kind": self.authority.kind.value if self.authority else None,
                "authority_id": self.authority.reference_id if self.authority else None,
                "authority_hash": self.authority.reference_hash if self.authority else None,
                "output": self.output,
                "safe_summary": self.safe_summary,
                "diagnostic_code": self.diagnostic_code,
            }
        )


@dataclass(frozen=True, slots=True)
class ActionVerificationResult:
    status: ActionVerificationStatus
    verifier_id: str
    verifier_version: str
    authority: ActionAuthorityReference | None = None
    safe_summary: str = ""
    diagnostic_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "verifier_id", _safe_id(self.verifier_id, label="verifier id"))
        if not is_exact_semver(self.verifier_version):
            raise ValueError("verifier version must be exact SemVer")
        object.__setattr__(self, "safe_summary", _safe_summary(self.safe_summary))
        if self.diagnostic_code is not None:
            object.__setattr__(self, "diagnostic_code", _safe_id(self.diagnostic_code, label="verification code"))
        if self.status is ActionVerificationStatus.VERIFIED and self.authority is None:
            raise ValueError("verified action requires an authority reference")

    @property
    def verification_hash(self) -> str:
        return _hash(
            {
                "status": self.status.value,
                "verifier_id": self.verifier_id,
                "verifier_version": self.verifier_version,
                "authority_kind": self.authority.kind.value if self.authority else None,
                "authority_id": self.authority.reference_id if self.authority else None,
                "authority_hash": self.authority.reference_hash if self.authority else None,
                "safe_summary": self.safe_summary,
                "diagnostic_code": self.diagnostic_code,
            }
        )


@dataclass(frozen=True, slots=True)
class ActionRecoveryDirective:
    kind: ActionRecoveryKind
    code: str
    retry_after_seconds: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _safe_id(self.code, label="recovery code"))
        if not 0 <= self.retry_after_seconds <= 300:
            raise ValueError("recovery retry delay must be within 0..300 seconds")
        if self.kind is not ActionRecoveryKind.RETRY and self.retry_after_seconds != 0:
            raise ValueError("only retry recovery may include a delay")


@dataclass(frozen=True, slots=True)
class ActionReceipt:
    invocation_id: str
    action_id: str
    action_version: str
    stable_action_key: str
    status: ActionLifecycleStatus
    input_revision: int
    action_generation: int
    retry_index: int
    authority: ActionAuthorityReference | None
    safe_summary: str
    result_hash: str | None
    verification_status: ActionVerificationStatus
    verification_hash: str | None
    diagnostic_code: str | None
    recovery: ActionRecoveryDirective
    terminal_at: datetime | None
    receipt_schema_version: str = ACTION_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("invocation_id", "stable_action_key", "receipt_schema_version"):
            object.__setattr__(self, name, _safe_id(getattr(self, name), label=name))
        if not is_catalog_identifier(self.action_id) or not is_exact_semver(self.action_version):
            raise ValueError("action receipt reference is invalid")
        if self.input_revision < 0 or self.action_generation < 1 or self.retry_index < 0:
            raise ValueError("action receipt generation metadata is invalid")
        object.__setattr__(self, "safe_summary", _safe_summary(self.safe_summary))
        if self.result_hash is not None:
            object.__setattr__(self, "result_hash", _sha256(self.result_hash, label="action result hash"))
        if self.verification_hash is not None:
            object.__setattr__(
                self,
                "verification_hash",
                _sha256(self.verification_hash, label="action verification hash"),
            )
        if self.diagnostic_code is not None:
            object.__setattr__(self, "diagnostic_code", _safe_id(self.diagnostic_code, label="receipt code"))
        if self.status.terminal != (self.terminal_at is not None):
            raise ValueError("action receipt terminal timestamp does not match lifecycle status")
        if self.terminal_at is not None:
            if self.terminal_at.tzinfo is None:
                raise ValueError("action terminal_at must be timezone-aware")
            object.__setattr__(self, "terminal_at", self.terminal_at.astimezone(UTC))

    @property
    def receipt_hash(self) -> str:
        return _hash(self.as_safe_dict())

    def as_safe_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.receipt_schema_version,
            "invocation_id": self.invocation_id,
            "action_id": self.action_id,
            "action_version": self.action_version,
            "stable_action_key": self.stable_action_key,
            "status": self.status.value,
            "input_revision": self.input_revision,
            "action_generation": self.action_generation,
            "retry_index": self.retry_index,
            "authority_kind": self.authority.kind.value if self.authority else None,
            "authority_id": self.authority.reference_id if self.authority else None,
            "authority_hash": self.authority.reference_hash if self.authority else None,
            "safe_summary": self.safe_summary,
            "result_hash": self.result_hash,
            "verification_status": self.verification_status.value,
            "verification_hash": self.verification_hash,
            "diagnostic_code": self.diagnostic_code,
            "recovery_kind": self.recovery.kind.value,
            "recovery_code": self.recovery.code,
            "retry_after_seconds": self.recovery.retry_after_seconds,
            "terminal_at": self.terminal_at.isoformat() if self.terminal_at is not None else None,
        }

    def as_context_source(self) -> TutorContextSource:
        return TutorContextSource(
            source_id=f"action-receipt:{self.invocation_id}",
            content={
                "kind": "executed_action_receipt",
                "action_id": self.action_id,
                "action_version": self.action_version,
                "stable_action_key": self.stable_action_key,
                "status": self.status.value,
                "input_revision": self.input_revision,
                "action_generation": self.action_generation,
                "retry_index": self.retry_index,
                "safe_summary": self.safe_summary,
                "authority_kind": self.authority.kind.value if self.authority else None,
                "authority_id": self.authority.reference_id if self.authority else None,
                "verification_status": self.verification_status.value,
                "diagnostic_code": self.diagnostic_code,
                "recovery_kind": self.recovery.kind.value,
                "recovery_code": self.recovery.code,
            },
        )


@dataclass(frozen=True, slots=True)
class ActionFenceSnapshot:
    input_revision: int
    lease_generation: int
    lease_current: bool = True
    cancelled: bool = False
    superseded: bool = False

    def __post_init__(self) -> None:
        if self.input_revision < 0 or self.lease_generation < 1:
            raise ValueError("action fence metadata is invalid")


class ActionFence(Protocol):
    def snapshot(self, invocation: ActionInvocation) -> ActionFenceSnapshot: ...


def build_action_invocation(
    *,
    descriptor: ActionDescriptor,
    run: TutorRunSnapshot,
    invocation_id: str,
    idempotency_key: str,
    arguments: Mapping[str, object],
    resource_request: ActionResourceRequest,
    task_kind: str,
    catalog_digest: str,
    policy_fingerprint: str,
    selected_skill_reference: str | None,
    action_generation: int,
    requested_at: datetime,
    parent_invocation_id: str | None = None,
    retry_index: int = 0,
) -> ActionInvocation:
    validated = validate_action_arguments(descriptor, arguments)
    if run.lease is None:
        raise ValueError("action invocation requires an owned Tutor lease")
    return ActionInvocation(
        invocation_id=invocation_id,
        idempotency_key=idempotency_key,
        stable_action_key=stable_action_key(
            descriptor=descriptor,
            arguments=validated,
            resource_request=resource_request,
        ),
        action_id=descriptor.action_id,
        action_version=descriptor.version,
        run_id=run.run_id,
        conversation_id=run.conversation_id,
        user_id=run.user_id,
        origin=run.origin,
        task_kind=task_kind,
        input_revision=run.input_revision,
        lease_owner_id=run.lease.owner_id,
        lease_generation=run.lease.generation,
        action_generation=action_generation,
        catalog_digest=catalog_digest,
        policy_fingerprint=policy_fingerprint,
        arguments=validated,
        resource_request=resource_request,
        requested_at=requested_at,
        selected_skill_reference=selected_skill_reference,
        parent_invocation_id=parent_invocation_id,
        retry_index=retry_index,
    )


def stable_action_key(
    *,
    descriptor: ActionDescriptor,
    arguments: Mapping[str, object],
    resource_request: ActionResourceRequest,
) -> str:
    digest = _hash(
        {
            "action": descriptor.reference,
            "arguments": dict(arguments),
            "resource_fingerprint": resource_request.fingerprint,
        }
    )
    return f"action-{digest[:32]}"


def action_arguments_from_payload_fields(fields: Sequence[TutorPayloadField]) -> dict[str, object]:
    return {field.key: field.value for field in fields}


def default_action_descriptors() -> tuple[ActionDescriptor, ...]:
    grounding = ActionDescriptor(
        action_id=GROUNDING_RETRIEVE_DESCRIPTOR.capability_id,
        version=GROUNDING_RETRIEVE_DESCRIPTOR.version,
        input_model=GROUNDING_RETRIEVE_DESCRIPTOR.input_model,
        output_model=GroundingRetrieveActionOutput,
        owner_adapter_id="grounding-registry",
        owner_adapter_version="1.0.0",
        allowed_origins=("interactive",),
        allowed_task_kinds=("general_tutor", "plan_drafting", "lesson_teaching", "remediation"),
        resource_profile=ActionResourceProfile(
            profile_id="grounding-approved-registry-v1",
            network_class=ActionNetworkClass.APPROVED_REGISTRY,
            allow_approved_sources=True,
            max_input_bytes=4_096,
            max_output_bytes=16_384,
        ),
        timeout_seconds=15,
        side_effect_class=ActionSideEffectClass.READ_ONLY,
        retry_policy=ActionRetryPolicy(
            retry_class=ActionRetryClass.SAFE_READ,
            max_attempts=2,
            backoff_seconds=(1,),
            retryable_codes=("grounding_lookup_unavailable",),
        ),
        verifier_id="grounding-citation-verifier",
        verifier_version="1.0.0",
        recovery_kinds=(ActionRecoveryKind.RETRY, ActionRecoveryKind.SAFE_STOP),
    )
    plan = ActionDescriptor(
        action_id=LEARNING_PLAN_DRAFT_DESCRIPTOR.capability_id,
        version=LEARNING_PLAN_DRAFT_DESCRIPTOR.version,
        input_model=LEARNING_PLAN_DRAFT_DESCRIPTOR.input_model,
        output_model=LearningPlanDraftCapabilityOutput,
        owner_adapter_id="learning-plan-authority",
        owner_adapter_version="1.0.0",
        allowed_origins=("interactive",),
        allowed_task_kinds=("plan_drafting",),
        resource_profile=ActionResourceProfile(
            profile_id="learning-plan-draft-v1",
            allow_approved_sources=True,
            allowed_artifact_kinds=("planning_facts", "plan_draft"),
            max_input_bytes=16_384,
            max_output_bytes=16_384,
        ),
        timeout_seconds=30,
        side_effect_class=ActionSideEffectClass.PROPOSAL,
        retry_policy=ActionRetryPolicy(retry_class=ActionRetryClass.NEVER),
        verifier_id="learning-plan-contract-verifier",
        verifier_version="1.0.0",
        recovery_kinds=(ActionRecoveryKind.REBUILD_CONTEXT, ActionRecoveryKind.REQUEST_CLARIFICATION),
    )
    runner = ActionDescriptor(
        action_id="runner.execute",
        version="1.0.0",
        input_model=RunnerExecuteActionInput,
        output_model=RunnerExecuteActionOutput,
        owner_adapter_id="execution-intent-job-authority",
        owner_adapter_version="1.0.0",
        allowed_origins=("interactive", "exercise_gate"),
        allowed_task_kinds=("exercise_feedback", "model_code_review", "remediation"),
        resource_profile=ActionResourceProfile(
            profile_id="reviewed-executor-v1",
            network_class=ActionNetworkClass.EXECUTOR_MANAGED,
            allowed_artifact_kinds=("exercise_submission", "execution_intent"),
            temporary_workspace=True,
            max_input_bytes=262_144,
            max_output_bytes=65_536,
        ),
        timeout_seconds=120,
        side_effect_class=ActionSideEffectClass.EXTERNAL_EXECUTION,
        retry_policy=ActionRetryPolicy(
            retry_class=ActionRetryClass.IDEMPOTENT,
            max_attempts=2,
            backoff_seconds=(1,),
            retryable_codes=("executor_temporarily_unavailable", "execution_job_retryable"),
        ),
        verifier_id="runner-terminal-result-verifier",
        verifier_version="1.0.0",
        recovery_kinds=(ActionRecoveryKind.RETRY, ActionRecoveryKind.SAFE_STOP),
    )
    return (grounding, plan, runner)


def validate_action_resources(
    *,
    descriptor: ActionDescriptor,
    request: ActionResourceRequest,
    approved_source_ids: Collection[str] = (),
    approved_artifact_ids: Collection[str] = (),
) -> None:
    profile = descriptor.resource_profile
    if request.network_class is not profile.network_class:
        raise ValueError("action network class exceeds descriptor policy")
    if request.temporary_workspace and not profile.temporary_workspace:
        raise ValueError("action temporary workspace is not allowed")
    if request.input_bytes > profile.max_input_bytes or request.expected_output_bytes > profile.max_output_bytes:
        raise ValueError("action byte budget exceeds descriptor policy")
    if request.cost_units > profile.max_cost_units:
        raise ValueError("action cost budget exceeds descriptor policy")
    if request.source_ids:
        if not profile.allow_approved_sources or not set(request.source_ids).issubset(approved_source_ids):
            raise ValueError("action source scope is not approved")
    if request.artifact_ids and not set(request.artifact_ids).issubset(approved_artifact_ids):
        raise ValueError("action artifact scope is not approved")
    if request.artifact_kinds and not set(request.artifact_kinds).issubset(profile.allowed_artifact_kinds):
        raise ValueError("action artifact kind is not approved")
    if request.execution_profile_id is not None and (
        not profile.execution_profile_ids or request.execution_profile_id not in profile.execution_profile_ids
    ):
        raise ValueError("action execution profile is not approved")


def validate_action_arguments(descriptor: ActionDescriptor, arguments: Mapping[str, object]) -> dict[str, object]:
    validated = descriptor.input_model.model_validate(dict(arguments)).model_dump(mode="json")
    if _contains_forbidden_target(validated):
        raise ValueError("action arguments contain an undeclared execution target")
    return validated


def allowed_action_transition(current: ActionLifecycleStatus, target: ActionLifecycleStatus) -> bool:
    transitions = {
        ActionLifecycleStatus.REQUESTED: {ActionLifecycleStatus.ADMITTED, ActionLifecycleStatus.DENIED},
        ActionLifecycleStatus.ADMITTED: {
            ActionLifecycleStatus.RUNNING,
            ActionLifecycleStatus.CANCEL_REQUESTED,
            ActionLifecycleStatus.SUPERSEDED,
        },
        ActionLifecycleStatus.RUNNING: {
            ActionLifecycleStatus.SUCCEEDED_UNVERIFIED,
            ActionLifecycleStatus.RETRYABLE_FAILED,
            ActionLifecycleStatus.PERMANENT_FAILED,
            ActionLifecycleStatus.DENIED,
            ActionLifecycleStatus.TIMED_OUT,
            ActionLifecycleStatus.CANCEL_REQUESTED,
            ActionLifecycleStatus.SUPERSEDED,
        },
        ActionLifecycleStatus.CANCEL_REQUESTED: {
            ActionLifecycleStatus.CANCELLED,
            ActionLifecycleStatus.SUCCEEDED_UNVERIFIED,
        },
        ActionLifecycleStatus.SUCCEEDED_UNVERIFIED: {
            ActionLifecycleStatus.VERIFIED,
            ActionLifecycleStatus.RETRYABLE_FAILED,
            ActionLifecycleStatus.PERMANENT_FAILED,
            ActionLifecycleStatus.CANCEL_REQUESTED,
            ActionLifecycleStatus.SUPERSEDED,
        },
    }
    return target in transitions.get(current, set())


def _contains_forbidden_target(value: object) -> bool:
    if isinstance(value, str):
        return contains_forbidden_execution_target(value)
    if isinstance(value, Mapping):
        return any(_contains_forbidden_target(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return any(_contains_forbidden_target(item) for item in value)
    return False


def _safe_id(value: object, *, label: str) -> str:
    normalized = str(value or "").strip()
    if not _SAFE_ID.fullmatch(normalized):
        raise ValueError(f"{label} must be a bounded stable identifier")
    return normalized


def _sha256(value: object, *, label: str) -> str:
    normalized = str(value or "").lower()
    if not _SHA256.fullmatch(normalized):
        raise ValueError(f"{label} must be SHA-256")
    return normalized


def _safe_summary(value: object) -> str:
    summary = sanitize_summary_text(value, max_length=MAX_ACTION_SAFE_SUMMARY_LENGTH)
    if contains_forbidden_execution_target(summary):
        return "结果已通过安全边界记录。"
    return summary


def _hash(value: object) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
