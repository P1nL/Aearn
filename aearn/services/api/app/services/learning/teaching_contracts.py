"""Typed contracts for durable teaching-session authority and Turn stimuli."""
from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_STABLE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,159}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TeachingSessionStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    BLOCKED = "blocked"


class TeachingSessionMode(StrEnum):
    GUIDED = "guided"
    FREE_READING = "free_reading"


class TeachingPauseReason(StrEnum):
    SOFT_PAUSE = "soft_pause"
    EVIDENCE_PAUSE = "evidence_pause"
    AUTHORITY_PAUSE = "authority_pause"
    SESSION_PAUSE = "session_pause"
    COMPLETION_PAUSE = "completion_pause"


class TeachingControlKey(StrEnum):
    OPEN_SESSION = "open_session"
    CONTINUE = "continue"
    RETURN_FOCUS = "return_focus"
    CHANGE_EXAMPLE = "change_example"
    ESCALATE_GUIDED = "escalate_guided"
    SWITCH_MODE = "switch_mode"
    PAUSE = "pause"
    RESUME = "resume"
    ENTER_NEXT_KNOWLEDGE = "enter_next_knowledge"


class TeachingDomainEventKind(StrEnum):
    GATE_TERMINAL = "gate_terminal"
    REVIEW_TERMINAL = "review_terminal"
    PROGRESS_CHANGED = "progress_changed"
    ASSIGNMENT_CHANGED = "assignment_changed"
    AUTHORITY_REFRESH = "authority_refresh"


class TeachingObjective(_Strict):
    objective_id: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=240)
    source_handles: tuple[str, ...] = Field(default=(), max_length=8)

    @field_validator("objective_id")
    @classmethod
    def objective_key(cls, value: str) -> str:
        return stable(value, "objective_id")

    @field_validator("summary")
    @classmethod
    def objective_summary(cls, value: str) -> str:
        return text(value, 240, "objective summary")

    @field_validator("source_handles")
    @classmethod
    def objective_handles(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return stable_tuple(value, "source handle")


class TeachingFocus(_Strict):
    focus_id: str = Field(min_length=1, max_length=160)
    focus_kind: Literal["knowledge", "lesson_block", "question", "prerequisite", "feedback"]
    summary: str = Field(min_length=1, max_length=240)
    source_handles: tuple[str, ...] = Field(default=(), max_length=8)

    @field_validator("focus_id")
    @classmethod
    def focus_key(cls, value: str) -> str:
        return stable(value, "focus_id")

    @field_validator("summary")
    @classmethod
    def focus_summary(cls, value: str) -> str:
        return text(value, 240, "focus summary")

    @field_validator("source_handles")
    @classmethod
    def focus_handles(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return stable_tuple(value, "source handle")


class TeachingQuestion(_Strict):
    question_id: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=180)
    state: Literal["open", "answered", "deferred"] = "open"
    source_message_id: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("question_id")
    @classmethod
    def question_key(cls, value: str) -> str:
        return stable(value, "question_id")

    @field_validator("summary")
    @classmethod
    def question_summary(cls, value: str) -> str:
        return text(value, 180, "question summary")


class TeachingEvidenceCursor(_Strict):
    evidence_kind: Literal["gate", "review", "progress", "assignment"]
    source_id: str = Field(min_length=1, max_length=160)
    source_version: int = Field(ge=1)


class TeachingAuthoritySnapshot(_Strict):
    track_version: int = Field(ge=1)
    plan_revision_id: str = Field(min_length=1, max_length=120)
    progress_version: int = Field(ge=1)
    assignment_id: str = Field(min_length=1, max_length=120)
    assignment_version: int = Field(ge=1)
    document_id: str = Field(min_length=1, max_length=120)
    document_content_hash: str = Field(min_length=64, max_length=64)

    @field_validator("document_content_hash")
    @classmethod
    def document_hash(cls, value: str) -> str:
        value = value.strip().lower()
        if not _SHA256.fullmatch(value):
            raise ValueError("document_content_hash must be SHA-256")
        return value

class TeachingCheckpointState(_Strict):
    objective: TeachingObjective
    active_focus: TeachingFocus | None = None
    suspended_focuses: tuple[TeachingFocus, ...] = Field(default=(), max_length=8)
    unresolved_questions: tuple[TeachingQuestion, ...] = Field(default=(), max_length=12)
    covered_concepts: tuple[str, ...] = Field(default=(), max_length=32)
    evidence_cursors: tuple[TeachingEvidenceCursor, ...] = Field(default=(), max_length=16)
    pause_reason: TeachingPauseReason = TeachingPauseReason.SOFT_PAUSE
    recommended_action_key: str | None = Field(default=None, min_length=1, max_length=160)

    @field_validator("covered_concepts")
    @classmethod
    def concept_keys(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return stable_tuple(value, "covered concept")

    @field_validator("recommended_action_key")
    @classmethod
    def action_key(cls, value: str | None) -> str | None:
        return stable(value, "recommended_action_key") if value is not None else None

    @model_validator(mode="after")
    def unique_lineage(self) -> "TeachingCheckpointState":
        focus_ids = [item.focus_id for item in self.suspended_focuses]
        if self.active_focus is not None:
            focus_ids.append(self.active_focus.focus_id)
        if len(focus_ids) != len(set(focus_ids)):
            raise ValueError("focus identities must be unique")
        question_ids = [item.question_id for item in self.unresolved_questions]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("question identities must be unique")
        return self


class TeachingSessionSummaryV1(_Strict):
    schema_version: Literal["teaching_session_summary_v1"] = "teaching_session_summary_v1"
    teaching_session_id: str = Field(min_length=1, max_length=120)
    knowledge_key: str = Field(min_length=1, max_length=160)
    session_version: int = Field(ge=1)
    status: TeachingSessionStatus
    mode: TeachingSessionMode
    objective: TeachingObjective
    active_focus: TeachingFocus | None = None
    suspended_focuses: tuple[TeachingFocus, ...] = Field(default=(), max_length=8)
    unresolved_questions: tuple[TeachingQuestion, ...] = Field(default=(), max_length=12)
    covered_concepts: tuple[str, ...] = Field(default=(), max_length=32)
    evidence_cursors: tuple[TeachingEvidenceCursor, ...] = Field(default=(), max_length=16)
    pause_reason: TeachingPauseReason
    recommended_action_key: str | None = Field(default=None, min_length=1, max_length=160)
    source_checkpoint_id: str = Field(min_length=1, max_length=120)
    predecessor_checkpoint_id: str | None = Field(default=None, min_length=1, max_length=120)
    source_checkpoint_hash: str = Field(min_length=64, max_length=64)
    authority_snapshot_hash: str = Field(min_length=64, max_length=64)

    @field_validator("knowledge_key")
    @classmethod
    def summary_knowledge_key(cls, value: str) -> str:
        return stable(value, "knowledge_key")

    @field_validator("covered_concepts")
    @classmethod
    def summary_concepts(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return stable_tuple(value, "covered concept")

    @field_validator("recommended_action_key")
    @classmethod
    def summary_action_key(cls, value: str | None) -> str | None:
        return stable(value, "recommended_action_key") if value is not None else None

    @field_validator("source_checkpoint_hash", "authority_snapshot_hash")
    @classmethod
    def summary_hash(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _SHA256.fullmatch(normalized):
            raise ValueError("teaching summary hashes must be SHA-256")
        return normalized


class LearnerMessageStimulus(_Strict):
    kind: Literal["learner_message"] = "learner_message"
    message_id: str = Field(min_length=1, max_length=120)
    input_revision: int = Field(ge=1)


class TeachingControlStimulus(_Strict):
    kind: Literal["teaching_control"] = "teaching_control"
    control_key: TeachingControlKey
    client_action_id: str = Field(min_length=1, max_length=160)
    expected_session_version: int = Field(ge=1)
    expected_track_version: int = Field(ge=1)
    expected_progress_version: int = Field(ge=1)
    expected_assignment_version: int = Field(ge=1)
    safe_payload: dict[str, object] = Field(default_factory=dict)

    @field_validator("safe_payload")
    @classmethod
    def safe_control_payload(cls, value: dict[str, object]) -> dict[str, object]:
        allowed = {"target_mode", "target_knowledge_key", "reason_code", "source_handle"}
        if not set(value).issubset(allowed):
            raise ValueError("teaching control safe_payload contains unsupported fields")
        if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > 2048:
            raise ValueError("teaching control safe_payload is too large")
        return value


class DomainEventStimulus(_Strict):
    kind: Literal["domain_event"] = "domain_event"
    event_kind: TeachingDomainEventKind
    source_id: str = Field(min_length=1, max_length=160)
    source_version: int = Field(ge=1)
    safe_handles: tuple[str, ...] = Field(default=(), max_length=8)

    @field_validator("safe_handles")
    @classmethod
    def domain_handles(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return stable_tuple(value, "safe handle")


TutorTurnStimulus = Annotated[
    LearnerMessageStimulus | TeachingControlStimulus | DomainEventStimulus,
    Field(discriminator="kind"),
]


def canonical_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def stable(value: str, label: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _STABLE.fullmatch(normalized):
        raise ValueError(f"{label} must be a stable lowercase identifier")
    return normalized


def stable_tuple(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    normalized = tuple(stable(item, label) for item in values)
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{label}s must be unique")
    return normalized


def text(value: str, maximum: int, label: str) -> str:
    normalized = " ".join(str(value or "").split())
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{label} must contain 1..{maximum} characters")
    return normalized


class TeachingAction(StrEnum):
    ORIENT = "orient"
    EXPLAIN_CONCEPT = "explain_concept"
    ANSWER_QUESTION = "answer_question"
    SHOW_EXAMPLE = "show_example"
    COMPARE_EXAMPLES = "compare_examples"
    CHECK_UNDERSTANDING = "check_understanding"
    RECOMMEND_PRACTICE = "recommend_practice"
    EXPLAIN_FEEDBACK = "explain_feedback"
    REMEDIATE_PREREQUISITE = "remediate_prerequisite"
    SUMMARIZE_PROGRESS = "summarize_progress"
    RECOMMEND_PAUSE = "recommend_pause"
    WAIT_FOR_INPUT = "wait_for_input"


class TeachingFocusResolution(StrEnum):
    STAY = "stay"
    PUSH_CHILD = "push_child"
    RESOLVE_AND_RESUME_PARENT = "resolve_and_resume_parent"
    REPLACE_OBJECTIVE = "replace_objective"
    ABANDON_BRANCH = "abandon_branch"
    WAIT = "wait"


class TeachingMove(StrEnum):
    TARGETED_EXPLANATION = "targeted_explanation"
    WORKED_EXAMPLE = "worked_example"
    COUNTEREXAMPLE = "counterexample"
    MISCONCEPTION_CONTRAST = "misconception_contrast"
    GUIDED_DERIVATION = "guided_derivation"
    PREDICTION = "prediction"
    ERROR_DETECTION = "error_detection"
    MICRO_TRANSFER = "micro_transfer"
    LEARNER_FEEDBACK = "learner_feedback"


class TeachingLearnerResponseMode(StrEnum):
    NONE = "none"
    COMPOSER = "composer"


class TeachingStepDecision(_Strict):
    action: TeachingAction
    objective_id: str = Field(min_length=1, max_length=160)
    focus_id: str = Field(min_length=1, max_length=160)
    source_handles: tuple[str, ...] = Field(default=(), max_length=8)
    public_message: str = Field(min_length=1, max_length=4000)
    focus_resolution: TeachingFocusResolution
    pause_kind: TeachingPauseReason
    escalation_hint: str | None = Field(default=None, min_length=1, max_length=180)
    teaching_moves: tuple[TeachingMove, ...] | None = Field(default=None, max_length=4)
    learner_response_mode: TeachingLearnerResponseMode | None = None

    @field_validator("objective_id", "focus_id")
    @classmethod
    def stable_identity(cls, value: str) -> str:
        return stable(value, "teaching identity")

    @field_validator("source_handles")
    @classmethod
    def bounded_handles(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return stable_tuple(value, "source handle")

    @field_validator("public_message")
    @classmethod
    def bounded_message(cls, value: str) -> str:
        return text(value, 4000, "public_message")

    @field_validator("escalation_hint")
    @classmethod
    def bounded_hint(cls, value: str | None) -> str | None:
        return text(value, 180, "escalation_hint") if value is not None else None

    @model_validator(mode="after")
    def validate_semantics(self) -> "TeachingStepDecision":
        if self.focus_resolution is TeachingFocusResolution.PUSH_CHILD and self.focus_id == self.objective_id:
            raise ValueError("push_child requires a child focus identity")
        if self.pause_kind is TeachingPauseReason.COMPLETION_PAUSE and self.action is not TeachingAction.SUMMARIZE_PROGRESS:
            raise ValueError("completion_pause requires summarize_progress")
        return self


class TeachingActionDescriptor(_Strict):
    key: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=80)
    emphasis: Literal["primary", "secondary", "quiet"]
    enabled: bool = True
    disabled_reason: str | None = Field(default=None, min_length=1, max_length=160)
    target_kind: Literal["teaching_control", "navigation", "artifact"]
    target_id: str | None = Field(default=None, min_length=1, max_length=160)
    expected_versions: dict[str, int] = Field(default_factory=dict)

    @field_validator("key")
    @classmethod
    def descriptor_key(cls, value: str) -> str:
        return stable(value, "action key")

    @field_validator("label")
    @classmethod
    def descriptor_label(cls, value: str) -> str:
        return text(value, 80, "action label")

    @field_validator("expected_versions")
    @classmethod
    def version_map(cls, value: dict[str, int]) -> dict[str, int]:
        allowed = {"session", "track", "progress", "assignment"}
        if not set(value).issubset(allowed) or any(item < 1 for item in value.values()):
            raise ValueError("expected_versions contains invalid fields")
        return value


class TeachingActionShelfV1(_Strict):
    schema_version: Literal["teaching_action_shelf_v1"] = "teaching_action_shelf_v1"
    teaching_session_id: str = Field(min_length=1, max_length=120)
    session_version: int = Field(ge=1)
    checkpoint_id: str = Field(min_length=1, max_length=120)
    state: Literal["ready", "runtime_active", "blocking_request", "completion", "free_reading"]
    primary_action: TeachingActionDescriptor | None = None
    secondary_actions: tuple[TeachingActionDescriptor, ...] = Field(default=(), max_length=3)
    overflow_actions: tuple[TeachingActionDescriptor, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def unique_actions(self) -> "TeachingActionShelfV1":
        actions = tuple(item for item in (self.primary_action, *self.secondary_actions, *self.overflow_actions) if item is not None)
        keys = tuple(item.key for item in actions)
        if len(keys) != len(set(keys)):
            raise ValueError("Action Shelf keys must be unique")
        if self.primary_action is not None and self.primary_action.emphasis != "primary":
            raise ValueError("primary_action must use primary emphasis")
        if self.state in {"runtime_active", "blocking_request"} and actions:
            raise ValueError("runtime/request authority excludes ordinary Action Shelf actions")
        return self
