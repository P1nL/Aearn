"""Server-owned contracts for Lesson exercise Gates and module diagnostics."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Mapping, Sequence

from app.services.learning.contracts import bounded_text, stable_key


_SHA256 = frozenset("0123456789abcdef")


class ExerciseType(StrEnum):
    CODE_COMPLETION = "code_completion"
    SQL_QUERY = "sql_query"
    BROWSER_PREVIEW = "browser_preview"
    STATIC_CODE_REASONING = "static_code_reasoning"


class ExerciseSourceKind(StrEnum):
    CURATED_FIXTURE = "curated_fixture"
    REGISTERED_AUTHOR = "registered_author"


class ExerciseValidationStatus(StrEnum):
    READY = "ready"
    REJECTED = "rejected"


class GateRequirementKind(StrEnum):
    REQUIRED = "required"
    RECOMMENDED = "recommended"
    DIAGNOSTIC = "diagnostic"


class GateState(StrEnum):
    AVAILABLE = "available"
    IN_PROGRESS = "in_progress"
    PASSED = "passed"
    REMEDIATION_REQUIRED = "remediation_required"


class ExecutionRequirement(StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    FORBIDDEN = "forbidden"


class ExerciseAttemptType(StrEnum):
    RUN = "run"
    SUBMIT = "submit"
    DIAGNOSTIC_SUBMIT = "diagnostic_submit"


class ExerciseAttemptOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"


class DiagnosticSessionState(StrEnum):
    ACTIVE = "active"
    FAILED = "failed"
    PASSED_PENDING_CONFIRMATION = "passed_pending_confirmation"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class ExerciseVersion:
    language_id: str
    exercise_key: str
    exercise_type: ExerciseType
    version: str
    source_kind: ExerciseSourceKind
    title: str
    learner_prompt: Mapping[str, object]
    starter_artifact: Mapping[str, object]
    required_capabilities: tuple[str, ...]
    runtime_profile_id: str | None
    execution_required: bool
    public_feedback_policy_version: str
    validation_status: ExerciseValidationStatus = ExerciseValidationStatus.READY

    def __post_init__(self) -> None:
        object.__setattr__(self, "language_id", stable_key(self.language_id, label="language_id"))
        object.__setattr__(self, "exercise_key", stable_key(self.exercise_key, label="exercise_key"))
        object.__setattr__(self, "version", stable_key(self.version, label="exercise version"))
        object.__setattr__(self, "title", bounded_text(self.title, label="exercise title", maximum=240))
        object.__setattr__(
            self,
            "public_feedback_policy_version",
            stable_key(self.public_feedback_policy_version, label="feedback policy version"),
        )
        capabilities = tuple(stable_key(item, label="required capability") for item in self.required_capabilities)
        if not capabilities or len(capabilities) != len(set(capabilities)):
            raise ValueError("exercise required capabilities must be non-empty and unique")
        object.__setattr__(self, "required_capabilities", capabilities)
        if self.runtime_profile_id is not None:
            object.__setattr__(
                self,
                "runtime_profile_id",
                stable_key(self.runtime_profile_id, label="runtime_profile_id"),
            )
        if self.execution_required != (self.runtime_profile_id is not None):
            raise ValueError("execution-required exercises need exactly one runtime profile")
        _require_json_object(self.learner_prompt, label="learner_prompt")
        _require_json_object(self.starter_artifact, label="starter_artifact")

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.public_payload())

    def public_payload(self) -> dict[str, object]:
        return {
            "language_id": self.language_id,
            "exercise_key": self.exercise_key,
            "exercise_type": self.exercise_type.value,
            "version": self.version,
            "source_kind": self.source_kind.value,
            "title": self.title,
            "learner_prompt": dict(self.learner_prompt),
            "starter_artifact": dict(self.starter_artifact),
            "required_capabilities": list(self.required_capabilities),
            "runtime_profile_id": self.runtime_profile_id,
            "execution_required": self.execution_required,
            "public_feedback_policy_version": self.public_feedback_policy_version,
            "validation_status": self.validation_status.value,
        }


@dataclass(frozen=True, slots=True)
class ExercisePrivateRubric:
    rubric_version: str
    private_test_bundle: tuple[Mapping[str, object], ...]
    reference_answer: Mapping[str, object]
    score_policy: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "rubric_version", stable_key(self.rubric_version, label="rubric version"))
        if not self.private_test_bundle:
            raise ValueError("private rubric must contain at least one test")
        for index, item in enumerate(self.private_test_bundle):
            _require_json_object(item, label=f"private_test_bundle[{index}]")
        _require_json_object(self.reference_answer, label="reference_answer")
        _require_json_object(self.score_policy, label="score_policy")

    @property
    def rubric_hash(self) -> str:
        return canonical_hash(
            {
                "rubric_version": self.rubric_version,
                "private_test_bundle": [dict(item) for item in self.private_test_bundle],
                "reference_answer": dict(self.reference_answer),
                "score_policy": dict(self.score_policy),
            }
        )


@dataclass(frozen=True, slots=True)
class LessonGateBinding:
    gate_key: str
    exercise_key: str
    exercise_version: str
    requirement_kind: GateRequirementKind
    pass_policy_version: str
    pass_threshold: float
    execution_requirement: ExecutionRequirement
    slot_contract_hash: str
    remediation_exercise_key: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "gate_key", stable_key(self.gate_key, label="gate_key"))
        object.__setattr__(self, "exercise_key", stable_key(self.exercise_key, label="exercise_key"))
        object.__setattr__(self, "exercise_version", stable_key(self.exercise_version, label="exercise_version"))
        object.__setattr__(
            self,
            "pass_policy_version",
            stable_key(self.pass_policy_version, label="pass_policy_version"),
        )
        _require_sha256(self.slot_contract_hash, label="slot_contract_hash")
        if not 0 < self.pass_threshold <= 1:
            raise ValueError("pass threshold must be within (0, 1]")
        if self.remediation_exercise_key is not None:
            object.__setattr__(
                self,
                "remediation_exercise_key",
                stable_key(self.remediation_exercise_key, label="remediation_exercise_key"),
            )

    @property
    def binding_contract_hash(self) -> str:
        return canonical_hash(
            {
                "gate_key": self.gate_key,
                "exercise_key": self.exercise_key,
                "exercise_version": self.exercise_version,
                "requirement_kind": self.requirement_kind.value,
                "pass_policy_version": self.pass_policy_version,
                "pass_threshold": self.pass_threshold,
                "execution_requirement": self.execution_requirement.value,
                "slot_contract_hash": self.slot_contract_hash,
                "remediation_exercise_key": self.remediation_exercise_key,
            }
        )


@dataclass(frozen=True, slots=True)
class ExerciseAttemptResult:
    outcome: ExerciseAttemptOutcome
    score: float
    safe_feedback: Mapping[str, object]
    capability_scores: Mapping[str, float]
    policy_version: str
    terminal_at: datetime
    execution_receipt_hash: str | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.score <= 1:
            raise ValueError("attempt result score must be within 0..1")
        object.__setattr__(self, "policy_version", stable_key(self.policy_version, label="policy_version"))
        _require_json_object(self.safe_feedback, label="safe_feedback")
        for capability, score in self.capability_scores.items():
            stable_key(capability, label="capability score key")
            if not 0 <= score <= 1:
                raise ValueError("capability score must be within 0..1")
        if self.execution_receipt_hash is not None:
            _require_sha256(self.execution_receipt_hash, label="execution_receipt_hash")

    @property
    def result_hash(self) -> str:
        return canonical_hash(
            {
                "outcome": self.outcome.value,
                "score": self.score,
                "safe_feedback": dict(self.safe_feedback),
                "capability_scores": dict(self.capability_scores),
                "policy_version": self.policy_version,
                "terminal_at": self.terminal_at.isoformat(),
                "execution_receipt_hash": self.execution_receipt_hash,
            }
        )


@dataclass(frozen=True, slots=True)
class ModuleDiagnosticItem:
    item_key: str
    capability_key: str
    knowledge_key: str
    exercise_key: str
    exercise_version: str
    threshold: float

    def __post_init__(self) -> None:
        for field, value in (
            ("item_key", self.item_key),
            ("capability_key", self.capability_key),
            ("knowledge_key", self.knowledge_key),
            ("exercise_key", self.exercise_key),
            ("exercise_version", self.exercise_version),
        ):
            object.__setattr__(self, field, stable_key(value, label=field))
        if not 0 < self.threshold <= 1:
            raise ValueError("diagnostic item threshold must be within (0, 1]")


@dataclass(frozen=True, slots=True)
class ModuleDiagnosticVersion:
    language_id: str
    module_key: str
    version: str
    policy_version: str
    core_capabilities: tuple[str, ...]
    pass_threshold: float
    require_all_core: bool
    independent_only: bool
    cooldown_seconds: int
    items: tuple[ModuleDiagnosticItem, ...]

    def __post_init__(self) -> None:
        for field, value in (
            ("language_id", self.language_id),
            ("module_key", self.module_key),
            ("version", self.version),
            ("policy_version", self.policy_version),
        ):
            object.__setattr__(self, field, stable_key(value, label=field))
        capabilities = tuple(stable_key(item, label="core capability") for item in self.core_capabilities)
        if not capabilities or len(capabilities) != len(set(capabilities)):
            raise ValueError("diagnostic core capabilities must be non-empty and unique")
        object.__setattr__(self, "core_capabilities", capabilities)
        if not 0 < self.pass_threshold <= 1:
            raise ValueError("diagnostic pass threshold must be within (0, 1]")
        if self.cooldown_seconds < 0 or self.cooldown_seconds > 31 * 24 * 3600:
            raise ValueError("diagnostic cooldown is invalid")
        if not self.items:
            raise ValueError("diagnostic version must contain items")
        item_capabilities = tuple(item.capability_key for item in self.items)
        if set(item_capabilities) != set(capabilities):
            raise ValueError("diagnostic items must cover every core capability exactly once")
        if len(item_capabilities) != len(set(item_capabilities)):
            raise ValueError("diagnostic capability items must be unique")

    @property
    def content_hash(self) -> str:
        return canonical_hash(
            {
                "language_id": self.language_id,
                "module_key": self.module_key,
                "version": self.version,
                "policy_version": self.policy_version,
                "core_capabilities": list(self.core_capabilities),
                "pass_threshold": self.pass_threshold,
                "require_all_core": self.require_all_core,
                "independent_only": self.independent_only,
                "cooldown_seconds": self.cooldown_seconds,
                "items": [
                    {
                        "item_key": item.item_key,
                        "capability_key": item.capability_key,
                        "knowledge_key": item.knowledge_key,
                        "exercise_key": item.exercise_key,
                        "exercise_version": item.exercise_version,
                        "threshold": item.threshold,
                    }
                    for item in self.items
                ],
            }
        )


def canonical_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def canonical_submission_hash(value: str) -> str:
    normalized = str(value).replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def capability_score_summary(results: Sequence[ExerciseAttemptResult]) -> dict[str, float]:
    summary: dict[str, float] = {}
    for result in results:
        for capability, score in result.capability_scores.items():
            summary[capability] = max(summary.get(capability, 0.0), score)
    return summary


def _require_json_object(value: Mapping[str, object], *, label: str) -> None:
    try:
        encoded = json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be JSON serializable") from exc
    if len(encoded) > 64_000:
        raise ValueError(f"{label} is too large")


def _require_sha256(value: str, *, label: str) -> None:
    if len(value) != 64 or any(character not in _SHA256 for character in value):
        raise ValueError(f"{label} must be SHA-256")
