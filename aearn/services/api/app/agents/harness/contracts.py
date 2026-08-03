"""Immutable, bounded contracts for the feature-disabled Tutor Harness."""
from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Literal, Protocol

from app.core.teaching_safety import (
    check_teaching_output,
    limit_text,
    redact_value,
    sanitize_message_content,
    sanitize_summary_text,
)


MAX_TUTOR_IDENTIFIER_LENGTH = 120
MAX_TUTOR_PUBLIC_MESSAGE_LENGTH = 1600
MAX_TUTOR_CONVERSATION_TITLE_LENGTH = 48
MAX_TUTOR_PAYLOAD_FIELDS = 12
MAX_TUTOR_PAYLOAD_VALUE_LENGTH = 360


TutorRunOrigin = Literal["interactive", "proactive"]


class TutorRunStatus(str, Enum):
    QUEUED = "queued"
    LEASED = "leased"
    RUNNING = "running"
    WAITING_FOR_INPUT = "waiting_for_input"
    WAITING_FOR_CAPABILITY = "waiting_for_capability"
    AWAITING_EFFECT_COMMIT = "awaiting_effect_commit"
    COMPLETED = "completed"
    MODEL_UNAVAILABLE = "model_unavailable"
    BLOCKED_POLICY = "blocked_policy"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CANCELLED = "cancelled"
    FAILED = "failed"


class TutorTerminalOutcome(str, Enum):
    COMPLETED = "completed"
    MODEL_UNAVAILABLE = "model_unavailable"
    BLOCKED_POLICY = "blocked_policy"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CANCELLED = "cancelled"
    FAILED = "failed"


class TutorContextSection(str, Enum):
    SYSTEM = "system"
    ACTIVE_PLAN = "active_plan"
    REVIEW = "review"
    RECENT_MESSAGES = "recent_messages"
    WORKING_SUMMARY = "working_summary"
    LEARNER_MEMORY = "learner_memory"
    ACTIVITY = "activity"
    CAPABILITY_SCHEMAS = "capability_schemas"


CONTEXT_SECTION_PRIORITY: tuple[TutorContextSection, ...] = (
    TutorContextSection.SYSTEM,
    TutorContextSection.ACTIVE_PLAN,
    TutorContextSection.REVIEW,
    TutorContextSection.RECENT_MESSAGES,
    TutorContextSection.WORKING_SUMMARY,
    TutorContextSection.LEARNER_MEMORY,
    TutorContextSection.ACTIVITY,
    TutorContextSection.CAPABILITY_SCHEMAS,
)


class TutorCheckpointReason(str, Enum):
    SAFE_PROGRESS = "safe_progress"
    CAPABILITY_RESULT = "capability_result"
    TERMINAL = "terminal"


class TutorContinuationKind(str, Enum):
    """Server-authorized ways to continue one existing bounded Tutor run."""

    APPROVAL = "approval"
    CAPABILITY_RESULT = "capability_result"
    EXTERNAL_RESULT = "external_result"


class TutorCompactionTrigger(str, Enum):
    TERMINAL = "terminal"
    SAFE_CHECKPOINT = "safe_checkpoint"
    CONTEXT_HIGH_WATER = "context_high_water"


class TutorCapabilityStatus(str, Enum):
    COMPLETED = "completed"
    DENIED = "denied"
    UNAVAILABLE = "unavailable"


class TutorDecisionGateStatus(str, Enum):
    APPROVED = "approved"
    REBUILD_CONTEXT = "rebuild_context"
    DENIED = "denied"


class TutorEffectStatus(str, Enum):
    PROPOSED = "proposed"
    COMMITTED = "committed"
    DENIED = "denied"
    STALE_REJECTED = "stale_rejected"


class TokenEstimator(Protocol):
    """Deterministic token-estimation port used by the context builder."""

    def estimate_tokens(self, value: object) -> int: ...


@dataclass(frozen=True)
class TutorPolicySnapshot:
    deadline: datetime
    max_iterations: int = 3
    max_model_calls: int = 3
    max_capability_calls: int = 0
    max_effects: int = 0
    context_token_budget: int = 1200
    lease_duration_seconds: int = 30

    def __post_init__(self) -> None:
        for name in ("max_iterations", "max_model_calls", "max_capability_calls", "max_effects"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.context_token_budget <= 0:
            raise ValueError("context_token_budget must be positive")
        if self.lease_duration_seconds <= 0:
            raise ValueError("lease_duration_seconds must be positive")


@dataclass(frozen=True)
class TutorLease:
    run_id: str
    owner_id: str
    expires_at: datetime
    generation: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _safe_identifier(self.run_id))
        object.__setattr__(self, "owner_id", _safe_identifier(self.owner_id))
        if self.generation < 1:
            raise ValueError("lease generation must be positive")


@dataclass(frozen=True)
class TutorInputEvent:
    run_id: str
    message_id: str
    revision: int
    content: str
    received_at: datetime
    role: str = "user"

    def __post_init__(self) -> None:
        if self.revision < 1:
            raise ValueError("input revision must be positive")
        if self.role != "user":
            raise ValueError("Tutor input events must be learner messages")
        object.__setattr__(self, "run_id", _safe_identifier(self.run_id))
        object.__setattr__(self, "message_id", _safe_identifier(self.message_id))
        object.__setattr__(
            self,
            "content",
            sanitize_message_content(role="user", content=str(self.content), max_length=MAX_TUTOR_PUBLIC_MESSAGE_LENGTH),
        )


@dataclass(frozen=True)
class TutorContextSource:
    source_id: str
    content: object

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _safe_identifier(self.source_id))


@dataclass(frozen=True)
class TutorContextInput:
    run_id: str
    conversation_id: str
    input_revision: int
    system_descriptors: tuple[TutorContextSource, ...] = ()
    active_plan: tuple[TutorContextSource, ...] = ()
    review_snapshot: tuple[TutorContextSource, ...] = ()
    recent_messages: tuple[TutorContextSource, ...] = ()
    working_summary: tuple[TutorContextSource, ...] = ()
    learner_memory: tuple[TutorContextSource, ...] = ()
    activity_facts: tuple[TutorContextSource, ...] = ()
    capability_schemas: tuple[TutorContextSource, ...] = ()

    def __post_init__(self) -> None:
        if self.input_revision < 0:
            raise ValueError("input_revision must be non-negative")
        object.__setattr__(self, "run_id", _safe_identifier(self.run_id))
        object.__setattr__(self, "conversation_id", _safe_identifier(self.conversation_id))
        for name in (
            "system_descriptors",
            "active_plan",
            "review_snapshot",
            "recent_messages",
            "working_summary",
            "learner_memory",
            "activity_facts",
            "capability_schemas",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))

    def section_sources(self) -> tuple[tuple[TutorContextSection, tuple[TutorContextSource, ...]], ...]:
        return (
            (TutorContextSection.SYSTEM, self.system_descriptors),
            (TutorContextSection.ACTIVE_PLAN, self.active_plan),
            (TutorContextSection.REVIEW, self.review_snapshot),
            (TutorContextSection.RECENT_MESSAGES, self.recent_messages),
            (TutorContextSection.WORKING_SUMMARY, self.working_summary),
            (TutorContextSection.LEARNER_MEMORY, self.learner_memory),
            (TutorContextSection.ACTIVITY, self.activity_facts),
            (TutorContextSection.CAPABILITY_SCHEMAS, self.capability_schemas),
        )


@dataclass(frozen=True)
class TutorContextItem:
    section: TutorContextSection
    source_id: str
    content: str
    source_hash: str
    token_estimate: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _safe_identifier(self.source_id))
        object.__setattr__(self, "content", limit_text(self.content, MAX_TUTOR_PUBLIC_MESSAGE_LENGTH))
        if self.token_estimate < 1:
            raise ValueError("token_estimate must be positive")

    def as_prompt_value(self) -> dict[str, str]:
        return {
            "section": self.section.value,
            "source_id": self.source_id,
            "content": self.content,
        }


@dataclass(frozen=True)
class TutorContextSectionMetadata:
    section: TutorContextSection
    selected_count: int
    skipped_count: int
    source_ids: tuple[str, ...] = ()
    source_hashes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.selected_count < 0 or self.skipped_count < 0:
            raise ValueError("context selection counts must be non-negative")
        object.__setattr__(self, "source_ids", tuple(_safe_identifier(value) for value in self.source_ids))
        object.__setattr__(self, "source_hashes", tuple(limit_text(value, 64) for value in self.source_hashes))


@dataclass(frozen=True)
class TutorCheckpointMetadata:
    token_budget: int
    consumed_tokens: int
    sections: tuple[TutorContextSectionMetadata, ...] = ()

    def __post_init__(self) -> None:
        if self.token_budget <= 0:
            raise ValueError("token_budget must be positive")
        if self.consumed_tokens < 0 or self.consumed_tokens > self.token_budget:
            raise ValueError("consumed_tokens must be within token_budget")
        object.__setattr__(self, "sections", tuple(self.sections))

    @property
    def source_ids(self) -> tuple[str, ...]:
        return tuple(source_id for section in self.sections for source_id in section.source_ids)

    @property
    def source_hashes(self) -> tuple[str, ...]:
        return tuple(source_hash for section in self.sections for source_hash in section.source_hashes)

    def as_dict(self) -> dict[str, object]:
        return {
            "token_budget": self.token_budget,
            "consumed_tokens": self.consumed_tokens,
            "sections": [
                {
                    "section": section.section.value,
                    "selected_count": section.selected_count,
                    "skipped_count": section.skipped_count,
                    "source_ids": list(section.source_ids),
                    "source_hashes": list(section.source_hashes),
                }
                for section in self.sections
            ],
        }


@dataclass(frozen=True)
class TutorCompactionRequest:
    idempotency_key: str
    run_id: str
    conversation_id: str
    input_revision: int
    trigger: TutorCompactionTrigger
    source_ids: tuple[str, ...]
    source_hashes: tuple[str, ...]
    token_budget: int
    consumed_tokens: int

    def __post_init__(self) -> None:
        if self.input_revision < 0:
            raise ValueError("input_revision must be non-negative")
        if self.token_budget <= 0 or self.consumed_tokens < 0 or self.consumed_tokens > self.token_budget:
            raise ValueError("compaction request budget is invalid")
        object.__setattr__(self, "idempotency_key", limit_text(self.idempotency_key, 160))
        object.__setattr__(self, "run_id", _safe_identifier(self.run_id))
        object.__setattr__(self, "conversation_id", _safe_identifier(self.conversation_id))
        object.__setattr__(self, "source_ids", tuple(_safe_identifier(value) for value in self.source_ids))
        object.__setattr__(self, "source_hashes", tuple(limit_text(value, 64) for value in self.source_hashes))


@dataclass(frozen=True)
class TutorContextSelection:
    items: tuple[TutorContextItem, ...]
    checkpoint_metadata: TutorCheckpointMetadata
    high_water_compaction_request: TutorCompactionRequest | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))

    def as_prompt_context(self) -> list[dict[str, str]]:
        return [item.as_prompt_value() for item in self.items]


@dataclass(frozen=True)
class TutorCheckpoint:
    run_id: str
    input_revision: int
    reason: TutorCheckpointReason
    status: TutorRunStatus
    metadata: TutorCheckpointMetadata
    created_at: datetime

    def __post_init__(self) -> None:
        if self.input_revision < 0:
            raise ValueError("input_revision must be non-negative")
        object.__setattr__(self, "run_id", _safe_identifier(self.run_id))


@dataclass(frozen=True)
class TutorSkillReference:
    skill_id: str
    version: str = "current"

    def __post_init__(self) -> None:
        object.__setattr__(self, "skill_id", _safe_identifier(self.skill_id))
        object.__setattr__(self, "version", _safe_identifier(self.version))


@dataclass(frozen=True)
class TutorPayloadField:
    key: str
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", _safe_identifier(self.key))
        object.__setattr__(self, "value", sanitize_summary_text(self.value, max_length=MAX_TUTOR_PAYLOAD_VALUE_LENGTH))


@dataclass(frozen=True)
class TutorCapabilityRequest:
    request_id: str
    capability_id: str
    arguments: tuple[TutorPayloadField, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _safe_identifier(self.request_id))
        object.__setattr__(self, "capability_id", _safe_identifier(self.capability_id))
        object.__setattr__(self, "arguments", _bounded_payload_fields(self.arguments))


@dataclass(frozen=True)
class TutorCapabilityResult:
    request_id: str
    status: TutorCapabilityStatus
    safe_result: tuple[TutorPayloadField, ...] = ()
    continue_run: bool = False
    diagnostic_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _safe_identifier(self.request_id))
        object.__setattr__(self, "safe_result", _bounded_payload_fields(self.safe_result))
        if self.diagnostic_code is not None:
            object.__setattr__(self, "diagnostic_code", _safe_identifier(self.diagnostic_code))


@dataclass(frozen=True)
class TutorEffectProposal:
    effect_id: str
    effect_type: str
    expected_input_revision: int
    payload: tuple[TutorPayloadField, ...] = ()

    def __post_init__(self) -> None:
        if self.expected_input_revision < 0:
            raise ValueError("expected_input_revision must be non-negative")
        object.__setattr__(self, "effect_id", _safe_identifier(self.effect_id))
        object.__setattr__(self, "effect_type", _safe_identifier(self.effect_type))
        object.__setattr__(self, "payload", _bounded_payload_fields(self.payload))


@dataclass(frozen=True)
class TutorEffectResult:
    effect_id: str
    status: TutorEffectStatus
    commit_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "effect_id", _safe_identifier(self.effect_id))
        if self.commit_id is not None:
            object.__setattr__(self, "commit_id", _safe_identifier(self.commit_id))


@dataclass(frozen=True)
class TutorDecision:
    public_message: str | None = None
    conversation_title: str | None = None
    skill_references: tuple[TutorSkillReference, ...] = ()
    capability_requests: tuple[TutorCapabilityRequest, ...] = ()
    effect_proposals: tuple[TutorEffectProposal, ...] = ()
    checkpoint_reason: TutorCheckpointReason | None = None
    continuation_kind: TutorContinuationKind | None = None
    terminal_outcome: TutorTerminalOutcome | None = None

    def __post_init__(self) -> None:
        if self.public_message is not None:
            public_message = sanitize_summary_text(self.public_message, max_length=MAX_TUTOR_PUBLIC_MESSAGE_LENGTH)
            object.__setattr__(self, "public_message", public_message or None)
        if self.conversation_title is not None:
            object.__setattr__(self, "conversation_title", normalize_tutor_conversation_title(self.conversation_title))
        object.__setattr__(self, "skill_references", tuple(self.skill_references[:4]))
        object.__setattr__(self, "capability_requests", tuple(self.capability_requests[:4]))
        object.__setattr__(self, "effect_proposals", tuple(self.effect_proposals[:4]))
        _ensure_unique((item.skill_id for item in self.skill_references), "skill references")
        _ensure_unique((item.request_id for item in self.capability_requests), "capability request ids")
        _ensure_unique((item.effect_id for item in self.effect_proposals), "effect proposal ids")
        if self.continuation_kind is not None:
            if self.checkpoint_reason is not TutorCheckpointReason.CAPABILITY_RESULT:
                raise ValueError("Tutor continuation requires a capability-result checkpoint")
            if self.terminal_outcome is not None:
                raise ValueError("Tutor continuation cannot also be terminal")
        if self.terminal_outcome is not None and self.continuation_kind is not None:
            raise ValueError("Tutor decision cannot combine terminal and continuation intent")
        if not any(
            (
                self.public_message,
                self.skill_references,
                self.capability_requests,
                self.effect_proposals,
                self.checkpoint_reason,
                self.continuation_kind,
                self.terminal_outcome,
            )
        ):
            raise ValueError("Tutor decision must contain a bounded action or terminal intent")


@dataclass(frozen=True)
class TutorDecisionGateResult:
    status: TutorDecisionGateStatus
    diagnostic_code: str | None = None

    def __post_init__(self) -> None:
        if self.diagnostic_code is not None:
            object.__setattr__(self, "diagnostic_code", _safe_identifier(self.diagnostic_code))


@dataclass(frozen=True)
class TutorProviderResult:
    decision: TutorDecision | None
    model: str | None = None
    terminal_outcome: TutorTerminalOutcome | None = None
    safe_code: str | None = None

    def __post_init__(self) -> None:
        if (self.decision is None) == (self.terminal_outcome is None):
            raise ValueError("provider result must contain either a decision or terminal outcome")
        if self.model is not None:
            object.__setattr__(self, "model", _safe_identifier(self.model))
        if self.safe_code is not None:
            object.__setattr__(self, "safe_code", _safe_identifier(self.safe_code))

    @classmethod
    def model_unavailable(cls, *, safe_code: str = "MODEL_UNAVAILABLE") -> "TutorProviderResult":
        return cls(
            decision=None,
            terminal_outcome=TutorTerminalOutcome.MODEL_UNAVAILABLE,
            safe_code=safe_code,
        )


@dataclass(frozen=True)
class TutorRunSnapshot:
    run_id: str
    conversation_id: str
    user_id: str
    input_revision: int
    policy: TutorPolicySnapshot
    origin: TutorRunOrigin
    status: TutorRunStatus = TutorRunStatus.QUEUED
    lease: TutorLease | None = None
    iteration_count: int = 0
    model_call_count: int = 0
    capability_call_count: int = 0
    effect_count: int = 0
    cancelled: bool = False
    # Only a persisted server-authorized checkpoint may expose this on a live run.
    continuation_kind: TutorContinuationKind | None = None

    def __post_init__(self) -> None:
        if self.input_revision < 0:
            raise ValueError("input_revision must be non-negative")
        for name in ("iteration_count", "model_call_count", "capability_call_count", "effect_count"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.origin not in {"interactive", "proactive"}:
            raise ValueError("Tutor run origin is invalid")
        object.__setattr__(self, "run_id", _safe_identifier(self.run_id))
        object.__setattr__(self, "conversation_id", _safe_identifier(self.conversation_id))
        object.__setattr__(self, "user_id", _safe_identifier(self.user_id))


@dataclass(frozen=True)
class TutorRunResult:
    run_id: str
    status: TutorRunStatus
    input_revision: int
    iteration_count: int
    model_call_count: int
    capability_call_count: int
    effect_count: int
    terminal_outcome: TutorTerminalOutcome | None = None
    public_message: str | None = None
    # The decision candidate is persisted only with the same successful public reply.
    conversation_title: str | None = None
    # A normal completed TurnRun has no continuation.
    continuation_kind: TutorContinuationKind | None = None
    diagnostic_code: str | None = None
    effect_results: tuple[TutorEffectResult, ...] = ()

    def __post_init__(self) -> None:
        if self.input_revision < 0:
            raise ValueError("input_revision must be non-negative")
        for name in ("iteration_count", "model_call_count", "capability_call_count", "effect_count"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        object.__setattr__(self, "run_id", _safe_identifier(self.run_id))
        if self.public_message is not None:
            object.__setattr__(
                self,
                "public_message",
                sanitize_summary_text(self.public_message, max_length=MAX_TUTOR_PUBLIC_MESSAGE_LENGTH) or None,
            )
        if self.conversation_title is not None:
            object.__setattr__(self, "conversation_title", normalize_tutor_conversation_title(self.conversation_title))
        if self.continuation_kind is not None:
            if self.status is not TutorRunStatus.WAITING_FOR_INPUT or self.terminal_outcome is not None:
                raise ValueError("Tutor continuation result must be a non-terminal waiting state")
        if self.diagnostic_code is not None:
            object.__setattr__(self, "diagnostic_code", _safe_identifier(self.diagnostic_code))
        object.__setattr__(self, "effect_results", tuple(self.effect_results))


def empty_checkpoint_metadata(*, token_budget: int) -> TutorCheckpointMetadata:
    return TutorCheckpointMetadata(token_budget=token_budget, consumed_tokens=0, sections=())


def build_compaction_request(
    *,
    run_id: str,
    conversation_id: str,
    input_revision: int,
    trigger: TutorCompactionTrigger,
    metadata: TutorCheckpointMetadata,
) -> TutorCompactionRequest:
    payload = {
        "run_id": _safe_identifier(run_id),
        "conversation_id": _safe_identifier(conversation_id),
        "input_revision": input_revision,
        "trigger": trigger.value,
        "source_ids": list(metadata.source_ids),
        "source_hashes": list(metadata.source_hashes),
        "token_budget": metadata.token_budget,
        "consumed_tokens": metadata.consumed_tokens,
    }
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:24]
    return TutorCompactionRequest(
        idempotency_key=f"tutor-compaction:{digest}",
        run_id=run_id,
        conversation_id=conversation_id,
        input_revision=input_revision,
        trigger=trigger,
        source_ids=metadata.source_ids,
        source_hashes=metadata.source_hashes,
        token_budget=metadata.token_budget,
        consumed_tokens=metadata.consumed_tokens,
    )


def terminal_status(outcome: TutorTerminalOutcome) -> TutorRunStatus:
    return TutorRunStatus(outcome.value)


def normalize_tutor_conversation_title(value: object) -> str:
    """Normalize one learner-safe model title candidate for later guarded persistence."""

    normalized = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not normalized:
        raise ValueError("conversation_title must not be blank")
    if any(character in normalized for character in "\r\n\t"):
        raise ValueError("conversation_title must be a single line")
    if len(normalized) > MAX_TUTOR_CONVERSATION_TITLE_LENGTH:
        raise ValueError("conversation_title exceeds the visible character limit")
    check = check_teaching_output(normalized)
    if check.blocked:
        raise ValueError("conversation_title failed the teaching safety policy")
    return normalized


def payload_fields_from_mapping(value: Mapping[str, object] | None) -> tuple[TutorPayloadField, ...]:
    if not isinstance(value, Mapping):
        return ()
    fields: list[TutorPayloadField] = []
    for raw_key in sorted(value, key=lambda item: str(item))[:MAX_TUTOR_PAYLOAD_FIELDS]:
        raw_value = redact_value(value[raw_key])
        try:
            serialized = json.dumps(raw_value, ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError):
            serialized = str(raw_value)
        fields.append(TutorPayloadField(key=str(raw_key), value=serialized))
    return tuple(fields)


def payload_mapping_from_fields(fields: tuple[TutorPayloadField, ...] | list[TutorPayloadField]) -> dict[str, object] | None:
    """Decode the canonical JSON field representation used by provider payloads."""

    decoded: dict[str, object] = {}
    for field in fields:
        if field.key in decoded:
            return None
        try:
            decoded[field.key] = json.loads(field.value)
        except json.JSONDecodeError:
            return None
    return decoded


def _bounded_payload_fields(fields: object) -> tuple[TutorPayloadField, ...]:
    if not isinstance(fields, tuple | list):
        return ()
    return tuple(item for item in fields if isinstance(item, TutorPayloadField))[:MAX_TUTOR_PAYLOAD_FIELDS]


def _safe_identifier(value: object) -> str:
    redacted = redact_value(str(value or ""))
    return limit_text(str(redacted), MAX_TUTOR_IDENTIFIER_LENGTH) or "unknown"


def _ensure_unique(values: Iterable[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {label}")
        seen.add(value)
