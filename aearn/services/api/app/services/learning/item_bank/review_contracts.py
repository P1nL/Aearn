"""Strict contracts for Learning Item review, pilot, and approval authority."""
from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.learning.item_bank.contracts import (
    LearningItemReviewRole,
    LearningItemRiskTier,
    LearningItemSourceV1,
    LearningItemValidationCheckType,
    LearningItemValidationReceiptV1,
    bounded_text,
    canonical_hash,
    learning_item_handle,
    require_sha256,
    stable_key,
)

LEARNING_ITEM_REVIEW_INPUT_SCHEMA_VERSION: Literal["learning_item_review_input_v1"] = (
    "learning_item_review_input_v1"
)
LEARNING_ITEM_REVIEW_REPORT_SCHEMA_VERSION: Literal["learning_item_review_report_v1"] = (
    "learning_item_review_report_v1"
)
LEARNING_ITEM_REVIEW_POLICY_VERSION: Literal["learning_item_agent_review_policy_v1"] = (
    "learning_item_agent_review_policy_v1"
)
LEARNING_ITEM_ADJUDICATION_SCHEMA_VERSION: Literal["learning_item_review_adjudication_v1"] = (
    "learning_item_review_adjudication_v1"
)
LEARNING_ITEM_PILOT_SCHEMA_VERSION: Literal["learning_item_pilot_receipt_v1"] = (
    "learning_item_pilot_receipt_v1"
)
LEARNING_ITEM_PILOT_POLICY_VERSION: Literal["learning_item_pilot_policy_v1"] = (
    "learning_item_pilot_policy_v1"
)
LEARNING_ITEM_HUMAN_APPROVAL_SCHEMA_VERSION: Literal["learning_item_human_approval_v1"] = (
    "learning_item_human_approval_v1"
)
LEARNING_ITEM_HUMAN_APPROVAL_POLICY_VERSION: Literal[
    "learning_item_human_approval_policy_v1"
] = "learning_item_human_approval_policy_v1"

REQUIRED_REVIEW_ROLES: tuple[LearningItemReviewRole, ...] = (
    LearningItemReviewRole.CURRICULUM,
    LearningItemReviewRole.DIFFICULTY,
    LearningItemReviewRole.TECHNICAL,
    LearningItemReviewRole.AMBIGUITY,
    LearningItemReviewRole.SECURITY,
    LearningItemReviewRole.ADVERSARIAL,
)
_HANDLE = re.compile(r"^li:[0-9a-f]{64}$")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LearningItemReviewSeverity(StrEnum):
    NONE = "none"
    INFO = "info"
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"


class LearningItemReviewVerdict(StrEnum):
    APPROVED = "approved"
    CHANGES_REQUIRED = "changes_required"
    REJECTED = "rejected"


class LearningItemReviewBlockerKind(StrEnum):
    DETERMINISTIC_FAILURE = "deterministic_failure"
    SECURITY = "security"
    UNIQUE_ANSWER = "unique_answer"
    RUBRIC_MISMATCH = "rubric_mismatch"
    DATA_LEAKAGE = "data_leakage"
    TECHNICAL_FAILURE = "technical_failure"
    CURRICULUM_MISMATCH = "curriculum_mismatch"
    DIFFICULTY_MISMATCH = "difficulty_mismatch"
    AMBIGUITY = "ambiguity"
    ADVERSARIAL_EXPLOIT = "adversarial_exploit"
    REVIEW_CHANGES_REQUIRED = "review_changes_required"


VETO_BLOCKER_KINDS = frozenset(
    {
        LearningItemReviewBlockerKind.DETERMINISTIC_FAILURE,
        LearningItemReviewBlockerKind.SECURITY,
        LearningItemReviewBlockerKind.UNIQUE_ANSWER,
        LearningItemReviewBlockerKind.RUBRIC_MISMATCH,
        LearningItemReviewBlockerKind.DATA_LEAKAGE,
    }
)


class LearningItemPilotDecision(StrEnum):
    COLLECTING = "collecting"
    PROMOTE = "promote"
    AWAITING_HUMAN_APPROVAL = "awaiting_human_approval"
    QUARANTINE = "quarantine"
    RETIRE = "retire"


def _validated_handle(value: str, *, label: str) -> str:
    normalized = str(value).strip().lower()
    if not _HANDLE.fullmatch(normalized):
        raise ValueError(f"{label} is invalid")
    return normalized


class LearningItemBlindReviewInputV1(_StrictModel):
    """Exact blind input: no creator identity and no peer review reports."""

    schema_version: Literal["learning_item_review_input_v1"] = (
        LEARNING_ITEM_REVIEW_INPUT_SCHEMA_VERSION
    )
    item_handle: str = Field(min_length=67, max_length=67)
    content_hash: str = Field(min_length=64, max_length=64)
    role: LearningItemReviewRole
    risk_tier: LearningItemRiskTier
    source: LearningItemSourceV1
    validation_receipt: LearningItemValidationReceiptV1

    @field_validator("item_handle")
    @classmethod
    def validate_handle(cls, value: str) -> str:
        return _validated_handle(value, label="Learning Item review handle")

    @field_validator("content_hash")
    @classmethod
    def validate_content_hash(cls, value: str) -> str:
        return require_sha256(value, label="Learning Item review content hash")

    @model_validator(mode="after")
    def validate_binding(self) -> "LearningItemBlindReviewInputV1":
        expected_handle = learning_item_handle(
            self.source.public.item_key,
            self.source.public.version,
            self.source.content_hash,
        )
        if self.item_handle != expected_handle or self.content_hash != self.source.content_hash:
            raise ValueError("Learning Item review input is not bound to source content")
        if (
            self.validation_receipt.item_handle != self.item_handle
            or self.validation_receipt.content_hash != self.content_hash
        ):
            raise ValueError("Learning Item review validation receipt is stale")
        if self.risk_tier is not self.source.blueprint.publication_policy.risk_tier:
            raise ValueError("Learning Item review risk tier is stale")
        if self.role not in self.source.blueprint.publication_policy.required_review_roles:
            raise ValueError("Learning Item review role is not required")
        return self

    @property
    def review_input_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


class LearningItemReviewFindingV1(_StrictModel):
    finding_key: str = Field(min_length=1, max_length=160)
    severity: LearningItemReviewSeverity
    safe_code: str = Field(min_length=1, max_length=160)
    blocking: bool = False
    blocker_kind: LearningItemReviewBlockerKind | None = None
    safe_summary: str = Field(min_length=1, max_length=480)
    evidence_hash: str = Field(min_length=64, max_length=64)

    @field_validator("finding_key", "safe_code")
    @classmethod
    def validate_key(cls, value: str) -> str:
        return stable_key(value, label="Learning Item review finding key")

    @field_validator("safe_summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        return bounded_text(value, label="Learning Item review finding summary", maximum=480)

    @field_validator("evidence_hash")
    @classmethod
    def validate_evidence_hash(cls, value: str) -> str:
        return require_sha256(value, label="Learning Item review evidence hash")

    @model_validator(mode="after")
    def validate_blocker(self) -> "LearningItemReviewFindingV1":
        if self.severity is LearningItemReviewSeverity.NONE:
            raise ValueError("review findings cannot use none severity")
        if self.blocking != (self.blocker_kind is not None):
            raise ValueError("blocking findings require exactly one blocker kind")
        if self.blocking and self.severity not in {
            LearningItemReviewSeverity.MAJOR,
            LearningItemReviewSeverity.CRITICAL,
        }:
            raise ValueError("blocking findings must be major or critical")
        return self


class LearningItemReviewReportV1(_StrictModel):
    schema_version: Literal["learning_item_review_report_v1"] = (
        LEARNING_ITEM_REVIEW_REPORT_SCHEMA_VERSION
    )
    policy_version: Literal["learning_item_agent_review_policy_v1"] = (
        LEARNING_ITEM_REVIEW_POLICY_VERSION
    )
    item_handle: str = Field(min_length=67, max_length=67)
    content_hash: str = Field(min_length=64, max_length=64)
    review_input_hash: str = Field(min_length=64, max_length=64)
    role: LearningItemReviewRole
    reviewer_identity: str = Field(min_length=1, max_length=160)
    verdict: LearningItemReviewVerdict
    findings: tuple[LearningItemReviewFindingV1, ...] = Field(default=(), max_length=24)

    @field_validator("item_handle")
    @classmethod
    def validate_handle(cls, value: str) -> str:
        return _validated_handle(value, label="Learning Item review report handle")

    @field_validator("content_hash", "review_input_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return require_sha256(value, label="Learning Item review report hash")

    @field_validator("reviewer_identity")
    @classmethod
    def validate_reviewer(cls, value: str) -> str:
        return stable_key(value, label="Learning Item reviewer identity")

    @field_validator("findings")
    @classmethod
    def validate_findings(
        cls, values: tuple[LearningItemReviewFindingV1, ...]
    ) -> tuple[LearningItemReviewFindingV1, ...]:
        keys = tuple(item.finding_key for item in values)
        if len(keys) != len(set(keys)):
            raise ValueError("Learning Item review finding keys must be unique")
        return values

    @model_validator(mode="after")
    def validate_verdict(self) -> "LearningItemReviewReportV1":
        blocking = any(item.blocking for item in self.findings)
        material = any(_severity_rank(item.severity) >= 3 for item in self.findings)
        if self.verdict is LearningItemReviewVerdict.APPROVED and (blocking or material):
            raise ValueError("approved reviews cannot contain material findings")
        if self.verdict is LearningItemReviewVerdict.CHANGES_REQUIRED and (blocking or not material):
            raise ValueError("changes-required reviews need non-blocking material findings")
        if self.verdict is LearningItemReviewVerdict.REJECTED and not blocking:
            raise ValueError("rejected reviews require a blocking finding")
        return self

    @property
    def highest_severity(self) -> LearningItemReviewSeverity:
        return max(
            (item.severity for item in self.findings),
            key=_severity_rank,
            default=LearningItemReviewSeverity.NONE,
        )

    @property
    def blocker_kinds(self) -> tuple[LearningItemReviewBlockerKind, ...]:
        return tuple(
            sorted(
                {item.blocker_kind for item in self.findings if item.blocker_kind is not None},
                key=lambda item: item.value,
            )
        )

    @property
    def report_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


class LearningItemReviewAdjudicationV1(_StrictModel):
    schema_version: Literal["learning_item_review_adjudication_v1"] = (
        LEARNING_ITEM_ADJUDICATION_SCHEMA_VERSION
    )
    policy_version: Literal["learning_item_agent_review_policy_v1"] = (
        LEARNING_ITEM_REVIEW_POLICY_VERSION
    )
    item_handle: str = Field(min_length=67, max_length=67)
    content_hash: str = Field(min_length=64, max_length=64)
    risk_tier: LearningItemRiskTier
    required_roles: tuple[LearningItemReviewRole, ...] = REQUIRED_REVIEW_ROLES
    report_hashes: dict[LearningItemReviewRole, str]
    verdict: Literal["approved", "rejected"]
    highest_severity: LearningItemReviewSeverity
    blocker_kinds: tuple[LearningItemReviewBlockerKind, ...] = ()
    machine_execution_verified: bool

    @field_validator("item_handle")
    @classmethod
    def validate_handle(cls, value: str) -> str:
        return _validated_handle(value, label="Learning Item adjudication handle")

    @field_validator("content_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return require_sha256(value, label="Learning Item adjudication content hash")

    @field_validator("required_roles")
    @classmethod
    def validate_roles(
        cls, values: tuple[LearningItemReviewRole, ...]
    ) -> tuple[LearningItemReviewRole, ...]:
        if values != REQUIRED_REVIEW_ROLES:
            raise ValueError("Learning Item adjudication requires all six review roles")
        return values

    @field_validator("report_hashes")
    @classmethod
    def validate_report_hashes(
        cls, value: dict[LearningItemReviewRole, str]
    ) -> dict[LearningItemReviewRole, str]:
        if set(value) != set(REQUIRED_REVIEW_ROLES):
            raise ValueError("Learning Item adjudication report set is incomplete")
        return {
            role: require_sha256(item, label="Learning Item review report hash")
            for role, item in value.items()
        }

    @field_validator("blocker_kinds")
    @classmethod
    def validate_blockers(
        cls, values: tuple[LearningItemReviewBlockerKind, ...]
    ) -> tuple[LearningItemReviewBlockerKind, ...]:
        if len(values) != len(set(values)):
            raise ValueError("Learning Item adjudication blocker kinds must be unique")
        return tuple(sorted(values, key=lambda item: item.value))

    @model_validator(mode="after")
    def validate_decision(self) -> "LearningItemReviewAdjudicationV1":
        if self.verdict == "approved":
            if self.blocker_kinds or _severity_rank(self.highest_severity) >= 3:
                raise ValueError("approved adjudication cannot contain blockers")
            if self.risk_tier is LearningItemRiskTier.MEDIUM and not self.machine_execution_verified:
                raise ValueError("medium-risk adjudication requires machine execution")
        elif not self.blocker_kinds:
            raise ValueError("rejected adjudication requires a structured blocker")
        return self

    @property
    def adjudication_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


class LearningItemPilotTelemetryV1(_StrictModel):
    item_handle: str = Field(min_length=67, max_length=67)
    content_hash: str = Field(min_length=64, max_length=64)
    observation_window_hash: str = Field(min_length=64, max_length=64)
    sample_count: int = Field(ge=1, le=1_000_000)
    completed_count: int = Field(ge=0, le=1_000_000)
    ambiguity_count: int = Field(default=0, ge=0, le=1_000_000)
    rubric_mismatch_count: int = Field(default=0, ge=0, le=1_000_000)
    technical_failure_count: int = Field(default=0, ge=0, le=1_000_000)
    difficulty_mismatch_count: int = Field(default=0, ge=0, le=1_000_000)
    unexpected_outcome_count: int = Field(default=0, ge=0, le=1_000_000)
    security_incident_count: int = Field(default=0, ge=0, le=1_000_000)
    leakage_incident_count: int = Field(default=0, ge=0, le=1_000_000)
    cohort_complete: bool = False

    @field_validator("item_handle")
    @classmethod
    def validate_handle(cls, value: str) -> str:
        return _validated_handle(value, label="Learning Item pilot handle")

    @field_validator("content_hash", "observation_window_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return require_sha256(value, label="Learning Item pilot hash")

    @model_validator(mode="after")
    def validate_counts(self) -> "LearningItemPilotTelemetryV1":
        counts = (
            self.completed_count,
            self.ambiguity_count,
            self.rubric_mismatch_count,
            self.technical_failure_count,
            self.difficulty_mismatch_count,
            self.unexpected_outcome_count,
            self.security_incident_count,
            self.leakage_incident_count,
        )
        if any(item > self.sample_count for item in counts):
            raise ValueError("Learning Item pilot counters cannot exceed sample count")
        if self.cohort_complete and self.completed_count == 0:
            raise ValueError("completed pilot cohorts need completed samples")
        return self

    @property
    def telemetry_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


class LearningItemPilotReceiptV1(_StrictModel):
    schema_version: Literal["learning_item_pilot_receipt_v1"] = (
        LEARNING_ITEM_PILOT_SCHEMA_VERSION
    )
    policy_version: Literal["learning_item_pilot_policy_v1"] = (
        LEARNING_ITEM_PILOT_POLICY_VERSION
    )
    risk_tier: LearningItemRiskTier
    telemetry: LearningItemPilotTelemetryV1
    decision: LearningItemPilotDecision

    @property
    def receipt_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


class LearningItemHumanApprovalV1(_StrictModel):
    schema_version: Literal["learning_item_human_approval_v1"] = (
        LEARNING_ITEM_HUMAN_APPROVAL_SCHEMA_VERSION
    )
    policy_version: Literal["learning_item_human_approval_policy_v1"] = (
        LEARNING_ITEM_HUMAN_APPROVAL_POLICY_VERSION
    )
    item_handle: str = Field(min_length=67, max_length=67)
    content_hash: str = Field(min_length=64, max_length=64)
    pilot_receipt_hash: str = Field(min_length=64, max_length=64)
    approver_identity: str = Field(min_length=1, max_length=160)
    approval_code: str = Field(default="approved", min_length=1, max_length=160)
    approved: Literal[True] = True

    @field_validator("item_handle")
    @classmethod
    def validate_handle(cls, value: str) -> str:
        return _validated_handle(value, label="Learning Item human approval handle")

    @field_validator("content_hash", "pilot_receipt_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return require_sha256(value, label="Learning Item human approval hash")

    @field_validator("approver_identity", "approval_code")
    @classmethod
    def validate_key(cls, value: str) -> str:
        return stable_key(value, label="Learning Item human approval key")

    @property
    def approval_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


def validation_proves_machine_execution(
    source: LearningItemSourceV1,
    validation: LearningItemValidationReceiptV1,
) -> bool:
    """Return exact deterministic execution evidence for medium-risk promotion."""

    statuses = {item.check_type: item.status for item in validation.checks}
    if source.public.kind.value in {"code", "sql"}:
        required = {
            LearningItemValidationCheckType.PRACTICE_CONTRACT,
            LearningItemValidationCheckType.STANDARD_ANSWER,
            LearningItemValidationCheckType.STARTER_NOT_PASSING,
            LearningItemValidationCheckType.RUNTIME_OR_EVENT,
            LearningItemValidationCheckType.SCORER,
        }
        return all(statuses.get(item) == "passed" for item in required)
    if source.public.kind.value == "model_review":
        required = {
            LearningItemValidationCheckType.PRACTICE_CONTRACT,
            LearningItemValidationCheckType.SCORER,
        }
        return all(statuses.get(item) == "passed" for item in required)
    return False


def evaluate_pilot(
    *, risk_tier: LearningItemRiskTier, telemetry: LearningItemPilotTelemetryV1
) -> LearningItemPilotReceiptV1:
    """Apply the versioned low/medium/high pilot policy without model input."""

    if telemetry.security_incident_count or telemetry.leakage_incident_count:
        decision = LearningItemPilotDecision.RETIRE
    elif any(
        (
            telemetry.ambiguity_count,
            telemetry.rubric_mismatch_count,
            telemetry.technical_failure_count,
            telemetry.difficulty_mismatch_count,
            telemetry.unexpected_outcome_count,
        )
    ):
        decision = LearningItemPilotDecision.QUARANTINE
    else:
        minimum_completed = 1 if risk_tier is LearningItemRiskTier.LOW else 3
        if not telemetry.cohort_complete or telemetry.completed_count < minimum_completed:
            decision = LearningItemPilotDecision.COLLECTING
        elif risk_tier is LearningItemRiskTier.HIGH:
            decision = LearningItemPilotDecision.AWAITING_HUMAN_APPROVAL
        else:
            decision = LearningItemPilotDecision.PROMOTE
    return LearningItemPilotReceiptV1(
        risk_tier=risk_tier,
        telemetry=telemetry,
        decision=decision,
    )


def _severity_rank(value: LearningItemReviewSeverity) -> int:
    return {
        LearningItemReviewSeverity.NONE: 0,
        LearningItemReviewSeverity.INFO: 1,
        LearningItemReviewSeverity.MINOR: 2,
        LearningItemReviewSeverity.MAJOR: 3,
        LearningItemReviewSeverity.CRITICAL: 4,
    }[value]


__all__ = (
    "LEARNING_ITEM_HUMAN_APPROVAL_POLICY_VERSION",
    "LEARNING_ITEM_PILOT_POLICY_VERSION",
    "LEARNING_ITEM_REVIEW_POLICY_VERSION",
    "REQUIRED_REVIEW_ROLES",
    "VETO_BLOCKER_KINDS",
    "LearningItemBlindReviewInputV1",
    "LearningItemHumanApprovalV1",
    "LearningItemPilotDecision",
    "LearningItemPilotReceiptV1",
    "LearningItemPilotTelemetryV1",
    "LearningItemReviewAdjudicationV1",
    "LearningItemReviewBlockerKind",
    "LearningItemReviewFindingV1",
    "LearningItemReviewReportV1",
    "LearningItemReviewSeverity",
    "LearningItemReviewVerdict",
    "evaluate_pilot",
    "validation_proves_machine_execution",
)
