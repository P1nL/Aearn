"""Strict contracts for model-generated code-review exercises."""
from __future__ import annotations

import json
import re
from enum import StrEnum
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.learning.practice.contracts import canonical_hash


MODEL_REVIEW_PROMPT_SCHEMA = "model_code_review_prompt_v1"
MODEL_REVIEW_ARTIFACT_SCHEMA = "model_code_review_artifact_v1"
MODEL_REVIEW_SUBMISSION_SCHEMA = "model_code_review_submission_v1"
MODEL_REVIEW_RUBRIC_SCHEMA = "model_code_review_rubric_v1"
MODEL_REVIEW_SCORE_POLICY_VERSION = "model_code_review_score_v1"
MODEL_REVIEW_FEEDBACK_POLICY_VERSION = "model_code_review_feedback_v1"
MODEL_REVIEW_VALIDATION_POLICY_VERSION = "model_code_review_validation_v1"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$")
_TOKEN = re.compile(r"[a-z0-9_.$:-]+|[\u4e00-\u9fff]{2,}", re.IGNORECASE)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ModelReviewScenarioKind(StrEnum):
    SINGLE_CORRECTNESS_ISSUE = "single_correctness_issue"
    MULTIPLE_CORRECTNESS_ISSUES = "multiple_correctness_issues"
    IMPROVEMENT_ONLY = "improvement_only"
    FULLY_CORRECT = "fully_correct"
    SUSPICIOUS_BUT_CORRECT = "suspicious_but_correct"
    FIX_INTRODUCES_REGRESSION = "fix_introduces_regression"


class ModelReviewVerdict(StrEnum):
    CORRECTNESS_ISSUE = "correctness_issue"
    NO_CORRECTNESS_ISSUE = "no_correctness_issue"
    IMPROVEMENT_ONLY = "improvement_only"
    UNCERTAIN = "uncertain"


class ModelReviewFindingKind(StrEnum):
    CORRECTNESS = "correctness"
    IMPROVEMENT = "improvement"


class ModelReviewSeverity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ModelReviewFindingStatus(StrEnum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    DUPLICATE = "duplicate"


class ModelReviewAssistanceKind(StrEnum):
    INDEPENDENT = "independent"
    HINTED = "hinted"
    VALIDATION_EVIDENCE_VIEWED = "validation_evidence_viewed"
    REMEDIATED = "remediated"


class ModelReviewPromptV1(_FrozenModel):
    schema_version: Literal["model_code_review_prompt_v1"] = "model_code_review_prompt_v1"
    requirements: tuple[str, ...] = Field(min_length=1, max_length=12)
    review_scope: tuple[str, ...] = Field(min_length=1, max_length=8)
    evidence_boundary: Literal["prepublication_verified"] = "prepublication_verified"
    learner_instruction: str = Field(min_length=1, max_length=1_200)

    @field_validator("requirements", "review_scope")
    @classmethod
    def validate_items(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        if any(not value or len(value) > 600 for value in normalized) or len(normalized) != len(set(normalized)):
            raise ValueError("model review prompt items must be bounded and unique")
        return normalized


class ModelReviewArtifactV1(_FrozenModel):
    schema_version: Literal["model_code_review_artifact_v1"] = "model_code_review_artifact_v1"
    language_id: str = Field(min_length=1, max_length=80)
    runtime_label: str = Field(min_length=1, max_length=120)
    model_code: str = Field(min_length=1, max_length=48_000)
    code_hash: str = Field(min_length=64, max_length=64)
    line_count: int = Field(ge=1, le=4_000)

    @field_validator("code_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("model review code hash must be SHA-256")
        return value

    @model_validator(mode="after")
    def validate_code_identity(self) -> "ModelReviewArtifactV1":
        normalized = self.model_code.replace("\r\n", "\n").replace("\r", "\n")
        if len(normalized.splitlines()) != self.line_count:
            raise ValueError("model review line count does not match code")
        if canonical_hash({"code": normalized}) != self.code_hash:
            raise ValueError("model review code hash does not match code")
        return self


class ModelReviewFindingV1(_FrozenModel):
    client_finding_id: str = Field(min_length=1, max_length=160)
    finding_kind: ModelReviewFindingKind
    start_line: int = Field(ge=1, le=4_000)
    end_line: int = Field(ge=1, le=4_000)
    category: str = Field(min_length=1, max_length=120)
    severity: ModelReviewSeverity
    trigger_condition: str = Field(min_length=1, max_length=1_200)
    principle: str = Field(min_length=1, max_length=1_200)
    impact: str = Field(min_length=1, max_length=1_200)
    validation_method: str = Field(min_length=1, max_length=1_200)
    suggested_fix: str = Field(min_length=1, max_length=1_200)
    supplemental_note: str | None = Field(default=None, max_length=1_200)

    @field_validator("client_finding_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not _SAFE_KEY.fullmatch(value):
            raise ValueError("client finding id must be a bounded opaque identifier")
        return value

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        normalized = value.strip().lower().replace(" ", "_")
        if not _SAFE_KEY.fullmatch(normalized):
            raise ValueError("model review category must be a stable key")
        return normalized

    @model_validator(mode="after")
    def validate_range_and_kind(self) -> "ModelReviewFindingV1":
        if self.end_line < self.start_line:
            raise ValueError("finding end_line must not precede start_line")
        if self.finding_kind is ModelReviewFindingKind.IMPROVEMENT and self.severity not in {
            ModelReviewSeverity.INFO,
            ModelReviewSeverity.LOW,
        }:
            raise ValueError("improvement finding severity must be info or low")
        return self

    @property
    def evidence_tokens(self) -> frozenset[str]:
        return normalized_tokens(
            " ".join(
                (
                    self.trigger_condition,
                    self.principle,
                    self.impact,
                    self.validation_method,
                    self.suggested_fix,
                )
            )
        )


class ModelCodeReviewSubmissionV1(_FrozenModel):
    schema_version: Literal["model_code_review_submission_v1"] = "model_code_review_submission_v1"
    verdict: ModelReviewVerdict
    findings: tuple[ModelReviewFindingV1, ...] = Field(default=(), max_length=12)
    supplemental_note: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def validate_shape(self) -> "ModelCodeReviewSubmissionV1":
        ids = tuple(item.client_finding_id for item in self.findings)
        if len(ids) != len(set(ids)):
            raise ValueError("client finding ids must be unique")
        correctness_count = sum(item.finding_kind is ModelReviewFindingKind.CORRECTNESS for item in self.findings)
        improvement_count = len(self.findings) - correctness_count
        if self.verdict is ModelReviewVerdict.CORRECTNESS_ISSUE and correctness_count == 0:
            raise ValueError("correctness_issue verdict requires a correctness finding")
        if self.verdict is ModelReviewVerdict.NO_CORRECTNESS_ISSUE and correctness_count:
            raise ValueError("no_correctness_issue verdict cannot contain correctness findings")
        if self.verdict is ModelReviewVerdict.IMPROVEMENT_ONLY and (not improvement_count or correctness_count):
            raise ValueError("improvement_only verdict requires only improvement findings")
        return self

    def validate_line_count(self, line_count: int) -> None:
        if line_count < 1 or any(item.end_line > line_count for item in self.findings):
            raise ValueError("finding line range exceeds the published code")

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @property
    def submission_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


class ModelReviewLineRangeV1(_FrozenModel):
    start_line: int = Field(ge=1, le=4_000)
    end_line: int = Field(ge=1, le=4_000)

    @model_validator(mode="after")
    def validate_range(self) -> "ModelReviewLineRangeV1":
        if self.end_line < self.start_line:
            raise ValueError("accepted line range is invalid")
        return self


class ModelReviewExpectedFindingV1(_FrozenModel):
    finding_key: str = Field(min_length=1, max_length=160)
    finding_kind: ModelReviewFindingKind
    category: str = Field(min_length=1, max_length=120)
    severity: ModelReviewSeverity
    accepted_line_ranges: tuple[ModelReviewLineRangeV1, ...] = Field(min_length=1, max_length=8)
    matcher_tokens: tuple[str, ...] = Field(min_length=1, max_length=24)
    reachability_proof_ids: tuple[str, ...] = Field(default=(), max_length=12)
    minimum_token_matches: int = Field(default=1, ge=1, le=8)

    @field_validator("finding_key", "category")
    @classmethod
    def validate_keys(cls, value: str) -> str:
        normalized = value.strip().lower().replace(" ", "_")
        if not _SAFE_KEY.fullmatch(normalized):
            raise ValueError("expected finding key must be stable")
        return normalized

    @field_validator("matcher_tokens")
    @classmethod
    def validate_tokens(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value for item in values for value in sorted(normalized_tokens(item)))
        if not normalized or len(normalized) != len(set(normalized)):
            raise ValueError("matcher tokens must be non-empty and unique")
        return normalized

    @field_validator("reachability_proof_ids")
    @classmethod
    def validate_proofs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        if any(not _SAFE_KEY.fullmatch(value) for value in normalized) or len(normalized) != len(set(normalized)):
            raise ValueError("reachability proof ids must be bounded and unique")
        return normalized


class ModelReviewRubricV1(_FrozenModel):
    schema_version: Literal["model_code_review_rubric_v1"] = "model_code_review_rubric_v1"
    scenario_kind: ModelReviewScenarioKind
    expected_verdict: ModelReviewVerdict
    expected_findings: tuple[ModelReviewExpectedFindingV1, ...] = Field(default=(), max_length=16)
    visible_evidence_ids: tuple[str, ...] = Field(default=(), max_length=12)
    coverage_policy: str = Field(min_length=1, max_length=160)
    template_id: str | None = Field(default=None, min_length=1, max_length=160)
    template_version: str | None = Field(default=None, min_length=1, max_length=160)
    template_contract_hash: str | None = Field(default=None, min_length=64, max_length=64)
    score_policy_version: Literal["model_code_review_score_v1"] = "model_code_review_score_v1"
    feedback_policy_version: Literal["model_code_review_feedback_v1"] = "model_code_review_feedback_v1"

    @field_validator("template_contract_hash")
    @classmethod
    def validate_template_hash(cls, value: str | None) -> str | None:
        if value is not None and not _SHA256.fullmatch(value):
            raise ValueError("model review template contract hash must be SHA-256")
        return value

    @model_validator(mode="after")
    def validate_scenario(self) -> "ModelReviewRubricV1":
        template_identity = (self.template_id, self.template_version, self.template_contract_hash)
        if any(item is not None for item in template_identity) and not all(item is not None for item in template_identity):
            raise ValueError("model review template identity must be complete")
        keys = tuple(item.finding_key for item in self.expected_findings)
        if len(keys) != len(set(keys)):
            raise ValueError("expected finding keys must be unique")
        correctness = tuple(
            item for item in self.expected_findings if item.finding_kind is ModelReviewFindingKind.CORRECTNESS
        )
        if self.scenario_kind in {
            ModelReviewScenarioKind.FULLY_CORRECT,
            ModelReviewScenarioKind.SUSPICIOUS_BUT_CORRECT,
        }:
            if correctness or self.expected_verdict is not ModelReviewVerdict.NO_CORRECTNESS_ISSUE:
                raise ValueError("correct scenarios cannot contain expected correctness findings")
        elif self.scenario_kind is ModelReviewScenarioKind.IMPROVEMENT_ONLY:
            if correctness or not self.expected_findings or self.expected_verdict is not ModelReviewVerdict.IMPROVEMENT_ONLY:
                raise ValueError("improvement-only scenario must contain only improvements")
        elif not correctness or self.expected_verdict is not ModelReviewVerdict.CORRECTNESS_ISSUE:
            raise ValueError("error scenarios require expected correctness findings")
        for item in correctness:
            if not item.reachability_proof_ids:
                raise ValueError("correctness finding requires reachability proof")
        return self


class ModelReviewValidationCheckV1(_FrozenModel):
    check_type: Literal[
        "schema",
        "parser",
        "compile_or_typecheck",
        "visible_tests",
        "hidden_tests",
        "finding_reachability",
        "rubric_consistency",
        "coverage",
        "redaction",
    ]
    status: Literal["passed", "not_applicable"]
    proof_hash: str = Field(min_length=64, max_length=64)

    @field_validator("proof_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("validation proof hash must be SHA-256")
        return value


class ModelReviewValidationReceiptV1(_FrozenModel):
    schema_version: Literal["model_code_review_validation_v1"] = "model_code_review_validation_v1"
    candidate_hash: str = Field(min_length=64, max_length=64)
    validation_profile_version: str = Field(min_length=1, max_length=160)
    checks: tuple[ModelReviewValidationCheckV1, ...] = Field(min_length=1, max_length=16)

    @field_validator("candidate_hash")
    @classmethod
    def validate_candidate_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("candidate hash must be SHA-256")
        return value

    @model_validator(mode="after")
    def validate_checks(self) -> "ModelReviewValidationReceiptV1":
        kinds = tuple(item.check_type for item in self.checks)
        if len(kinds) != len(set(kinds)):
            raise ValueError("validation checks must be unique")
        return self

    @property
    def receipt_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


class ModelReviewFindingFeedbackV1(_FrozenModel):
    client_finding_id: str
    status: ModelReviewFindingStatus
    safe_reason_code: str


class ModelReviewScoreBreakdownV1(_FrozenModel):
    policy_version: Literal["model_code_review_score_v1"] = "model_code_review_score_v1"
    verdict: float = Field(ge=0, le=1)
    discovery: float = Field(ge=0, le=1)
    omission: float = Field(ge=0, le=1)
    severity: float = Field(ge=0, le=1)
    evidence: float = Field(ge=0, le=1)
    validation_method: float = Field(ge=0, le=1)
    suggested_fix: float = Field(ge=0, le=1)
    false_positive: float = Field(ge=0, le=1)
    duplicate: float = Field(ge=0, le=1)


class ModelReviewSafeFeedbackV1(_FrozenModel):
    status: Literal["model_code_review_evaluated"] = "model_code_review_evaluated"
    message: str = Field(min_length=1, max_length=320)
    execution_claim: Literal["not_run"] = "not_run"
    assistance_kind: ModelReviewAssistanceKind
    score_breakdown: ModelReviewScoreBreakdownV1
    finding_feedback: tuple[ModelReviewFindingFeedbackV1, ...]
    omission_band: Literal["none", "limited", "major"]
    next_action: Literal["advance_next", "review_variant", "show_hint"]


def parse_model_review_submission(value: str | Mapping[str, object]) -> ModelCodeReviewSubmissionV1:
    payload = json.loads(value) if isinstance(value, str) else dict(value)
    if not isinstance(payload, Mapping):
        raise ValueError("model review submission must be a JSON object")
    return ModelCodeReviewSubmissionV1.model_validate(payload)


def parse_model_review_rubric(value: Mapping[str, object]) -> ModelReviewRubricV1:
    return ModelReviewRubricV1.model_validate(dict(value))


def normalized_tokens(value: str) -> frozenset[str]:
    return frozenset(token.casefold() for token in _TOKEN.findall(value) if len(token) >= 2)


def code_hash(code: str) -> str:
    normalized = code.replace("\r\n", "\n").replace("\r", "\n")
    return canonical_hash({"code": normalized})
