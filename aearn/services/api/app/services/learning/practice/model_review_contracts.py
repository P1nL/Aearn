"""Strict contracts for model-generated code-review exercises."""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
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
MODEL_REVIEW_ARTIFACT_SCHEMA_V2 = "model_code_review_artifact_v2"
MODEL_REVIEW_SUBMISSION_SCHEMA_V2 = "model_code_review_submission_v2"
MODEL_REVIEW_RUBRIC_SCHEMA_V2 = "model_code_review_rubric_v2"
MODEL_REVIEW_SCORE_POLICY_VERSION_V2 = "model_code_review_score_v2"
MODEL_REVIEW_REQUIRED_VALIDATION_CHECKS: tuple[str, ...] = (
    "schema",
    "parser",
    "compile_or_typecheck",
    "visible_tests",
    "hidden_tests",
    "finding_reachability",
    "rubric_consistency",
    "coverage",
    "redaction",
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$")
_TOKEN = re.compile(r"[a-z0-9_.$:-]+|[\u4e00-\u9fff]{2,}", re.IGNORECASE)
_DIFF_CONTEXT_LINES = 3


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


class ModelReviewErrorCategoryV2(StrEnum):
    REQUIREMENTS_DRIFT = "requirements_drift"
    FABRICATED_API = "fabricated_api"
    LOGIC_BOUNDARY = "logic_boundary"
    CONTRACT_INTEGRATION = "contract_integration"
    ASYNC_LIFECYCLE = "async_lifecycle"
    SECURITY_TRUST = "security_trust"
    ERROR_FALSE_SUCCESS = "error_false_success"
    WEAK_TESTING = "weak_testing"


MODEL_REVIEW_CORE_CATEGORIES: tuple[ModelReviewErrorCategoryV2, ...] = (
    ModelReviewErrorCategoryV2.REQUIREMENTS_DRIFT,
    ModelReviewErrorCategoryV2.FABRICATED_API,
    ModelReviewErrorCategoryV2.LOGIC_BOUNDARY,
    ModelReviewErrorCategoryV2.CONTRACT_INTEGRATION,
    ModelReviewErrorCategoryV2.ASYNC_LIFECYCLE,
    ModelReviewErrorCategoryV2.SECURITY_TRUST,
    ModelReviewErrorCategoryV2.ERROR_FALSE_SUCCESS,
)


class ModelReviewDiffSideV2(StrEnum):
    SOURCE = "source"
    MODIFIED = "modified"


class ModelReviewDiffLineKindV2(StrEnum):
    CONTEXT = "context"
    ADDED = "added"
    REMOVED = "removed"


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


class ModelReviewDiffLineV2(_FrozenModel):
    line_key: str = Field(min_length=1, max_length=160)
    kind: ModelReviewDiffLineKindV2
    text: str = Field(max_length=4_000)
    source_line: int | None = Field(default=None, ge=1, le=4_000)
    modified_line: int | None = Field(default=None, ge=1, le=4_000)

    @field_validator("line_key")
    @classmethod
    def validate_line_key(cls, value: str) -> str:
        if not _SAFE_KEY.fullmatch(value):
            raise ValueError("model review diff line key must be stable")
        return value

    @model_validator(mode="after")
    def validate_identity(self) -> "ModelReviewDiffLineV2":
        if self.kind is ModelReviewDiffLineKindV2.ADDED:
            valid = self.source_line is None and self.modified_line is not None
        elif self.kind is ModelReviewDiffLineKindV2.REMOVED:
            valid = self.source_line is not None and self.modified_line is None
        else:
            valid = self.source_line is not None and self.modified_line is not None
        if not valid:
            raise ValueError("model review diff line identity is inconsistent")
        return self


class ModelReviewDiffHunkV2(_FrozenModel):
    hunk_id: str = Field(min_length=1, max_length=160)
    header: str = Field(min_length=1, max_length=240)
    source_start: int = Field(ge=0, le=4_000)
    source_count: int = Field(ge=0, le=4_000)
    modified_start: int = Field(ge=0, le=4_000)
    modified_count: int = Field(ge=0, le=4_000)
    lines: tuple[ModelReviewDiffLineV2, ...] = Field(min_length=1, max_length=800)

    @field_validator("hunk_id")
    @classmethod
    def validate_hunk_id(cls, value: str) -> str:
        if not _SAFE_KEY.fullmatch(value):
            raise ValueError("model review hunk id must be stable")
        return value

    @model_validator(mode="after")
    def validate_lines(self) -> "ModelReviewDiffHunkV2":
        keys = tuple(item.line_key for item in self.lines)
        if len(keys) != len(set(keys)):
            raise ValueError("model review diff line keys must be unique")
        source = tuple(item.source_line for item in self.lines if item.source_line is not None)
        modified = tuple(item.modified_line for item in self.lines if item.modified_line is not None)
        if source and source != tuple(sorted(source)):
            raise ValueError("model review source line map must be ordered")
        if modified and modified != tuple(sorted(modified)):
            raise ValueError("model review modified line map must be ordered")
        return self


class ModelReviewArtifactV2(_FrozenModel):
    schema_version: Literal["model_code_review_artifact_v2"] = "model_code_review_artifact_v2"
    presentation_mode: Literal["code", "diff"]
    language_id: str = Field(min_length=1, max_length=80)
    runtime_label: str = Field(min_length=1, max_length=120)
    source_code: str | None = Field(default=None, max_length=48_000)
    modified_code: str = Field(min_length=1, max_length=48_000)
    source_hash: str | None = Field(default=None, min_length=64, max_length=64)
    modified_hash: str = Field(min_length=64, max_length=64)
    diff_hash: str = Field(min_length=64, max_length=64)
    line_count: int = Field(ge=1, le=4_000)
    hunks: tuple[ModelReviewDiffHunkV2, ...] = Field(min_length=1, max_length=80)

    @field_validator("source_hash", "modified_hash", "diff_hash")
    @classmethod
    def validate_hashes(cls, value: str | None) -> str | None:
        if value is not None and not _SHA256.fullmatch(value):
            raise ValueError("model review v2 identity must be SHA-256")
        return value

    @model_validator(mode="after")
    def validate_artifact_identity(self) -> "ModelReviewArtifactV2":
        source = self.source_code.replace("\r\n", "\n").replace("\r", "\n") if self.source_code is not None else None
        modified = self.modified_code.replace("\r\n", "\n").replace("\r", "\n")
        if len(modified.splitlines()) != self.line_count or code_hash(modified) != self.modified_hash:
            raise ValueError("model review modified code identity is stale")
        if self.presentation_mode == "code":
            if source is not None or self.source_hash is not None:
                raise ValueError("code review presentation cannot carry a source side")
        elif not source or self.source_hash != code_hash(source) or source == modified:
            raise ValueError("diff review presentation requires distinct source authority")
        hunk_ids = tuple(item.hunk_id for item in self.hunks)
        if len(hunk_ids) != len(set(hunk_ids)):
            raise ValueError("model review hunk ids must be unique")
        expected_mode, expected_hunks = _canonical_model_review_hunks(
            source=source,
            modified=modified,
        )
        if self.presentation_mode != expected_mode or self.hunks != expected_hunks:
            raise ValueError("model review hunk map does not match its code authority")
        expected_hash = canonical_hash(
            {
                "presentation_mode": self.presentation_mode,
                "source_hash": self.source_hash,
                "modified_hash": self.modified_hash,
                "hunks": [item.model_dump(mode="json") for item in self.hunks],
            }
        )
        if expected_hash != self.diff_hash:
            raise ValueError("model review diff hash does not match its line map")
        return self

    @property
    def presentation_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))

    def line_keys_for_range(
        self,
        *,
        hunk_id: str,
        side: ModelReviewDiffSideV2,
        start_line: int,
        end_line: int,
    ) -> tuple[str, ...]:
        hunk = next((item for item in self.hunks if item.hunk_id == hunk_id), None)
        if hunk is None:
            return ()
        attribute = "source_line" if side is ModelReviewDiffSideV2.SOURCE else "modified_line"
        return tuple(
            item.line_key
            for item in hunk.lines
            if (line := getattr(item, attribute)) is not None and start_line <= line <= end_line
        )


class ModelReviewFindingV2(_FrozenModel):
    client_finding_id: str = Field(min_length=1, max_length=160)
    hunk_id: str = Field(min_length=1, max_length=160)
    side: ModelReviewDiffSideV2 = ModelReviewDiffSideV2.MODIFIED
    start_line: int = Field(ge=1, le=4_000)
    end_line: int = Field(ge=1, le=4_000)
    category: ModelReviewErrorCategoryV2
    severity: ModelReviewSeverity
    explanation: str = Field(min_length=8, max_length=1_200)

    @field_validator("client_finding_id", "hunk_id")
    @classmethod
    def validate_keys(cls, value: str) -> str:
        if not _SAFE_KEY.fullmatch(value):
            raise ValueError("model review v2 finding identity must be stable")
        return value

    @model_validator(mode="after")
    def validate_range(self) -> "ModelReviewFindingV2":
        if self.end_line < self.start_line:
            raise ValueError("model review v2 finding range is invalid")
        return self

    @property
    def evidence_tokens(self) -> frozenset[str]:
        return normalized_tokens(self.explanation)


class ModelCodeReviewSubmissionV2(_FrozenModel):
    schema_version: Literal["model_code_review_submission_v2"] = "model_code_review_submission_v2"
    presentation_hash: str = Field(min_length=64, max_length=64)
    verdict: ModelReviewVerdict
    findings: tuple[ModelReviewFindingV2, ...] = Field(default=(), max_length=12)

    @field_validator("presentation_hash")
    @classmethod
    def validate_presentation_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("model review v2 presentation hash must be SHA-256")
        return value

    @model_validator(mode="after")
    def validate_shape(self) -> "ModelCodeReviewSubmissionV2":
        ids = tuple(item.client_finding_id for item in self.findings)
        if len(ids) != len(set(ids)):
            raise ValueError("model review v2 finding ids must be unique")
        if self.verdict is ModelReviewVerdict.CORRECTNESS_ISSUE and not self.findings:
            raise ValueError("correctness_issue verdict requires a finding")
        if self.verdict in {
            ModelReviewVerdict.NO_CORRECTNESS_ISSUE,
            ModelReviewVerdict.IMPROVEMENT_ONLY,
            ModelReviewVerdict.UNCERTAIN,
        } and self.findings:
            raise ValueError("non-correctness verdict cannot carry scored findings")
        return self

    def validate_presentation(self, presentation: ModelReviewArtifactV2) -> None:
        if self.presentation_hash != presentation.presentation_hash:
            raise ValueError("model review submission targets a stale presentation")
        for finding in self.findings:
            if (
                presentation.presentation_mode == "code"
                and finding.side is ModelReviewDiffSideV2.SOURCE
            ):
                raise ValueError("code-only model review has no source side")
            line_keys = presentation.line_keys_for_range(
                hunk_id=finding.hunk_id,
                side=finding.side,
                start_line=finding.start_line,
                end_line=finding.end_line,
            )
            if len(line_keys) != finding.end_line - finding.start_line + 1:
                raise ValueError("model review finding does not map exactly to the current hunk")

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @property
    def submission_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


class ModelReviewAcceptedRangeV2(_FrozenModel):
    hunk_id: str = Field(min_length=1, max_length=160)
    side: ModelReviewDiffSideV2
    start_line: int = Field(ge=1, le=4_000)
    end_line: int = Field(ge=1, le=4_000)

    @model_validator(mode="after")
    def validate_range(self) -> "ModelReviewAcceptedRangeV2":
        if self.end_line < self.start_line:
            raise ValueError("model review rubric range is invalid")
        return self


class ModelReviewExpectedFindingV2(_FrozenModel):
    finding_key: str = Field(min_length=1, max_length=160)
    category: ModelReviewErrorCategoryV2
    severity: ModelReviewSeverity
    accepted_ranges: tuple[ModelReviewAcceptedRangeV2, ...] = Field(min_length=1, max_length=16)
    required_concepts: tuple[str, ...] = Field(min_length=1, max_length=24)
    minimum_concept_matches: int = Field(default=1, ge=1, le=8)

    @field_validator("finding_key")
    @classmethod
    def validate_finding_key(cls, value: str) -> str:
        if not _SAFE_KEY.fullmatch(value):
            raise ValueError("model review v2 rubric key must be stable")
        return value

    @field_validator("required_concepts")
    @classmethod
    def validate_concepts(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value for item in values for value in sorted(normalized_tokens(item)))
        if not normalized or len(normalized) != len(set(normalized)):
            raise ValueError("model review v2 concepts must be non-empty and unique")
        return normalized


class ModelReviewRubricV2(_FrozenModel):
    schema_version: Literal["model_code_review_rubric_v2"] = "model_code_review_rubric_v2"
    expected_verdict: ModelReviewVerdict
    expected_findings: tuple[ModelReviewExpectedFindingV2, ...] = Field(default=(), max_length=16)
    score_policy_version: Literal["model_code_review_score_v2"] = "model_code_review_score_v2"

    @model_validator(mode="after")
    def validate_expected_shape(self) -> "ModelReviewRubricV2":
        keys = tuple(item.finding_key for item in self.expected_findings)
        if len(keys) != len(set(keys)):
            raise ValueError("model review v2 expected finding keys must be unique")
        if self.expected_verdict is ModelReviewVerdict.CORRECTNESS_ISSUE:
            if not self.expected_findings:
                raise ValueError("model review v2 correctness rubric requires findings")
        elif self.expected_findings:
            raise ValueError("model review v2 non-correctness rubric cannot score findings")
        return self


def parse_model_review_submission(value: str | Mapping[str, object]) -> ModelCodeReviewSubmissionV1:
    payload = json.loads(value) if isinstance(value, str) else dict(value)
    if not isinstance(payload, Mapping):
        raise ValueError("model review submission must be a JSON object")
    return ModelCodeReviewSubmissionV1.model_validate(payload)


def parse_model_review_rubric(value: Mapping[str, object]) -> ModelReviewRubricV1:
    return ModelReviewRubricV1.model_validate(dict(value))



def parse_model_review_submission_v2(
    value: str | Mapping[str, object],
) -> ModelCodeReviewSubmissionV2:
    payload = json.loads(value) if isinstance(value, str) else dict(value)
    if not isinstance(payload, Mapping):
        raise ValueError("model review v2 submission must be a JSON object")
    return ModelCodeReviewSubmissionV2.model_validate(payload)


def map_model_review_category_v2(value: str) -> ModelReviewErrorCategoryV2:
    normalized = value.casefold().replace("-", "_").replace(" ", "_")
    exact = {item.value: item for item in ModelReviewErrorCategoryV2}
    if normalized in exact:
        return exact[normalized]
    keyword_map: tuple[tuple[tuple[str, ...], ModelReviewErrorCategoryV2], ...] = (
        (("requirement", "spec", "scope", "drift"), ModelReviewErrorCategoryV2.REQUIREMENTS_DRIFT),
        (("api", "method", "symbol", "fabricat", "hallucin"), ModelReviewErrorCategoryV2.FABRICATED_API),
        (("async", "await", "lifecycle", "race", "state"), ModelReviewErrorCategoryV2.ASYNC_LIFECYCLE),
        (("security", "auth", "trust", "secret", "inject"), ModelReviewErrorCategoryV2.SECURITY_TRUST),
        (("error", "exception", "false_success", "silent"), ModelReviewErrorCategoryV2.ERROR_FALSE_SUCCESS),
        (("contract", "integration", "schema", "boundary"), ModelReviewErrorCategoryV2.CONTRACT_INTEGRATION),
        (("test", "coverage"), ModelReviewErrorCategoryV2.WEAK_TESTING),
    )
    for keywords, category in keyword_map:
        if any(item in normalized for item in keywords):
            return category
    return ModelReviewErrorCategoryV2.LOGIC_BOUNDARY


def upgrade_model_review_rubric_v1(
    rubric: ModelReviewRubricV1,
    presentation: ModelReviewArtifactV2,
) -> ModelReviewRubricV2:
    expected: list[ModelReviewExpectedFindingV2] = []
    for item in rubric.expected_findings:
        if item.finding_kind is not ModelReviewFindingKind.CORRECTNESS:
            continue
        ranges: list[ModelReviewAcceptedRangeV2] = []
        for accepted in item.accepted_line_ranges:
            for hunk in presentation.hunks:
                matched_lines = tuple(
                    line.modified_line
                    for line in hunk.lines
                    if line.modified_line is not None
                    and accepted.start_line <= line.modified_line <= accepted.end_line
                )
                if matched_lines:
                    ranges.append(
                        ModelReviewAcceptedRangeV2(
                            hunk_id=hunk.hunk_id,
                            side=ModelReviewDiffSideV2.MODIFIED,
                            start_line=min(matched_lines),
                            end_line=max(matched_lines),
                        )
                    )
        if not ranges:
            raise ValueError("legacy model review rubric cannot map to the v2 presentation")
        expected.append(
            ModelReviewExpectedFindingV2(
                finding_key=item.finding_key,
                category=map_model_review_category_v2(item.category),
                severity=item.severity,
                accepted_ranges=tuple(ranges),
                required_concepts=item.matcher_tokens,
                minimum_concept_matches=item.minimum_token_matches,
            )
        )
    expected_verdict = rubric.expected_verdict
    if expected_verdict is ModelReviewVerdict.IMPROVEMENT_ONLY:
        expected_verdict = ModelReviewVerdict.NO_CORRECTNESS_ISSUE
    return ModelReviewRubricV2(
        expected_verdict=expected_verdict,
        expected_findings=tuple(expected),
    )



def build_model_review_artifact_v2_contract(
    *,
    language_id: str,
    runtime_label: str,
    modified_code: str,
    source_code: str | None = None,
) -> ModelReviewArtifactV2:
    """Build the one canonical v2 code/diff projection used by every layer."""

    modified = _normalize_model_review_code(modified_code)
    source = (
        _normalize_model_review_code(source_code)
        if source_code is not None
        else None
    )
    if not modified or len(modified.splitlines()) > 4_000:
        raise ValueError("model review modified code is empty or too large")
    if source is not None and (
        not source
        or source == modified
        or len(source.splitlines()) > 4_000
    ):
        raise ValueError("model review diff source is empty, unchanged, or too large")
    mode, hunks = _canonical_model_review_hunks(
        source=source,
        modified=modified,
    )
    source_hash = code_hash(source) if source is not None else None
    modified_hash = code_hash(modified)
    identity = {
        "presentation_mode": mode,
        "source_hash": source_hash,
        "modified_hash": modified_hash,
        "hunks": [item.model_dump(mode="json") for item in hunks],
    }
    return ModelReviewArtifactV2(
        presentation_mode=mode,
        language_id=language_id,
        runtime_label=runtime_label,
        source_code=source,
        modified_code=modified,
        source_hash=source_hash,
        modified_hash=modified_hash,
        diff_hash=canonical_hash(identity),
        line_count=len(modified.splitlines()),
        hunks=hunks,
    )


def _canonical_model_review_hunks(
    *,
    source: str | None,
    modified: str,
) -> tuple[Literal["code", "diff"], tuple[ModelReviewDiffHunkV2, ...]]:
    if source is None:
        lines = modified.splitlines()
        return (
            "code",
            (
                ModelReviewDiffHunkV2(
                    hunk_id="code.h1",
                    header=f"@@ -1,{len(lines)} +1,{len(lines)} @@",
                    source_start=1,
                    source_count=len(lines),
                    modified_start=1,
                    modified_count=len(lines),
                    lines=tuple(
                        ModelReviewDiffLineV2(
                            line_key=f"code.m{index}",
                            kind=ModelReviewDiffLineKindV2.CONTEXT,
                            text=line,
                            source_line=index,
                            modified_line=index,
                        )
                        for index, line in enumerate(lines, start=1)
                    ),
                ),
            ),
        )
    if not source or source == modified:
        raise ValueError("model review diff source is empty or unchanged")
    source_lines = source.splitlines()
    modified_lines = modified.splitlines()
    matcher = SequenceMatcher(a=source_lines, b=modified_lines, autojunk=False)
    groups = tuple(matcher.get_grouped_opcodes(_DIFF_CONTEXT_LINES))
    hunks: list[ModelReviewDiffHunkV2] = []
    for hunk_index, group in enumerate(groups, start=1):
        first = group[0]
        last = group[-1]
        source_start = first[1] + 1
        modified_start = first[3] + 1
        source_count = last[2] - first[1]
        modified_count = last[4] - first[3]
        projected: list[ModelReviewDiffLineV2] = []
        serial = 0
        for tag, i1, i2, j1, j2 in group:
            if tag in {"equal", "delete", "replace"}:
                for index in range(i1, i2):
                    serial += 1
                    if tag == "equal":
                        projected.append(
                            ModelReviewDiffLineV2(
                                line_key=f"h{hunk_index}.l{serial}",
                                kind=ModelReviewDiffLineKindV2.CONTEXT,
                                text=source_lines[index],
                                source_line=index + 1,
                                modified_line=j1 + (index - i1) + 1,
                            )
                        )
                    else:
                        projected.append(
                            ModelReviewDiffLineV2(
                                line_key=f"h{hunk_index}.l{serial}",
                                kind=ModelReviewDiffLineKindV2.REMOVED,
                                text=source_lines[index],
                                source_line=index + 1,
                                modified_line=None,
                            )
                        )
            if tag in {"insert", "replace"}:
                for index in range(j1, j2):
                    serial += 1
                    projected.append(
                        ModelReviewDiffLineV2(
                            line_key=f"h{hunk_index}.l{serial}",
                            kind=ModelReviewDiffLineKindV2.ADDED,
                            text=modified_lines[index],
                            source_line=None,
                            modified_line=index + 1,
                        )
                    )
        hunks.append(
            ModelReviewDiffHunkV2(
                hunk_id=f"diff.h{hunk_index}",
                header=(
                    f"@@ -{source_start},{source_count} "
                    f"+{modified_start},{modified_count} @@"
                ),
                source_start=source_start,
                source_count=source_count,
                modified_start=modified_start,
                modified_count=modified_count,
                lines=tuple(projected),
            )
        )
    if not hunks:
        raise ValueError("model review diff must contain a changed hunk")
    return "diff", tuple(hunks)


def _normalize_model_review_code(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")

def normalized_tokens(value: str) -> frozenset[str]:
    return frozenset(token.casefold() for token in _TOKEN.findall(value) if len(token) >= 2)


def code_hash(code: str) -> str:
    normalized = code.replace("\r\n", "\n").replace("\r", "\n")
    return canonical_hash({"code": normalized})
