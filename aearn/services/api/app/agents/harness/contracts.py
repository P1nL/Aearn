"""Immutable, bounded contracts for the feature-disabled Tutor Harness."""
from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Literal, Protocol, get_args

from app.core.teaching_safety import (
    check_teaching_output,
    limit_text,
    redact_value,
    sanitize_message_content,
    sanitize_summary_text,
)
from app.services.llm.contracts import LLMUsage


MAX_TUTOR_IDENTIFIER_LENGTH = 120
MAX_TUTOR_PUBLIC_MESSAGE_LENGTH = 1600
MAX_TUTOR_PUBLIC_THINKING_TEXT_LENGTH = 1280
MAX_TUTOR_PUBLIC_THINKING_STEPS = 4
MAX_TUTOR_PUBLIC_THINKING_STEP_LENGTH = 320
MAX_TUTOR_CONVERSATION_TITLE_LENGTH = 48
MAX_TUTOR_PAYLOAD_FIELDS = 12
MAX_TUTOR_PAYLOAD_VALUE_LENGTH = 360
TUTOR_CONTEXT_SUMMARY_SCHEMA_VERSION = "tutor_context_summary_v2"
TUTOR_CONTEXT_SUMMARY_POLICY_VERSION = "tutor_context_summary_policy_v2"
MAX_TUTOR_CONTEXT_COMPACTION_MESSAGES = 24
MAX_TUTOR_CONTEXT_COMPACTION_CANDIDATES = 32


TutorRunOrigin = Literal["interactive", "proactive"]
TutorPlanningQuestionKey = Literal[
    "language_id",
    "goal_text",
    "target_level",
    "weekly_minutes",
    "experience_level",
    "teaching_preferences",
    "pace_constraints",
]
TUTOR_PLANNING_QUESTION_KEYS: frozenset[str] = frozenset(
    get_args(TutorPlanningQuestionKey)
)


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


class TutorContextError(RuntimeError):
    """A bounded context invariant failed before the provider boundary."""

    def __init__(self, safe_code: str) -> None:
        self.safe_code = _safe_identifier(safe_code)
        super().__init__(self.safe_code)


class TutorTerminalOutcome(str, Enum):
    COMPLETED = "completed"
    MODEL_UNAVAILABLE = "model_unavailable"
    BLOCKED_POLICY = "blocked_policy"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CANCELLED = "cancelled"
    FAILED = "failed"


class TutorContextSection(str, Enum):
    SYSTEM = "system"
    REQUIRED_FACTS = "required_facts"
    ACTION_RECEIPTS = "action_receipts"
    ACTIVE_PLAN = "active_plan"
    REVIEW = "review"
    RECENT_MESSAGES = "recent_messages"
    WORKING_SUMMARY = "working_summary"
    LEARNER_MEMORY = "learner_memory"
    ACTIVITY = "activity"
    CAPABILITY_SCHEMAS = "capability_schemas"


CONTEXT_SECTION_PRIORITY: tuple[TutorContextSection, ...] = (
    TutorContextSection.SYSTEM,
    TutorContextSection.REQUIRED_FACTS,
    TutorContextSection.ACTION_RECEIPTS,
    TutorContextSection.RECENT_MESSAGES,
    TutorContextSection.ACTIVE_PLAN,
    TutorContextSection.REVIEW,
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
    """Server-authorized reasons for accepting one more input on the same run."""

    CLARIFICATION = "clarification"
    PLANNING_INPUT = "planning_input"
    APPROVAL = "approval"
    CAPABILITY_RESULT = "capability_result"
    EXTERNAL_RESULT = "external_result"


class TutorTurnCompletionReason(str, Enum):
    """Learner-safe reason a completed source turn yielded a blocking request."""

    AWAITING_USER = "awaiting_user"
    AWAITING_APPROVAL = "awaiting_approval"
    AWAITING_AUTHORITY = "awaiting_authority"


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


class TutorProviderAttemptOutcome(str, Enum):
    ACCEPTED = "accepted"
    REPAIRABLE_REJECTED = "repairable_rejected"
    TERMINAL_REJECTED = "terminal_rejected"
    TRANSPORT_FAILED = "transport_failed"


class TokenEstimator(Protocol):
    """Deterministic token-estimation port used by the context builder."""

    def estimate_tokens(self, value: object) -> int: ...


class TutorContextBudgetMode(str, Enum):
    COMPACT = "compact"
    NORMAL = "normal"
    COMPLEX = "complex"
    EXTENDED = "extended"


@dataclass(frozen=True)
class TutorProviderContextCapability:
    context_window_tokens: int
    max_output_reserve_tokens: int
    protocol_reserve_tokens: int
    safety_margin_tokens: int
    maximum_dynamic_target_tokens: int
    capability_version: str

    def __post_init__(self) -> None:
        for name in (
            "context_window_tokens",
            "max_output_reserve_tokens",
            "protocol_reserve_tokens",
            "safety_margin_tokens",
            "maximum_dynamic_target_tokens",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.input_hard_limit <= self.protocol_reserve_tokens + self.safety_margin_tokens:
            raise ValueError("provider capability must leave positive required input capacity")
        if self.maximum_dynamic_target_tokens > self.dynamic_hard_limit:
            raise ValueError("maximum_dynamic_target_tokens exceeds provider input capacity")
        object.__setattr__(self, "capability_version", _safe_identifier(self.capability_version))

    @property
    def input_hard_limit(self) -> int:
        return self.context_window_tokens - self.max_output_reserve_tokens

    @property
    def dynamic_hard_limit(self) -> int:
        return self.input_hard_limit - self.protocol_reserve_tokens - self.safety_margin_tokens


@dataclass(frozen=True)
class TutorContextBudgetPolicy:
    capability: TutorProviderContextCapability
    mode_targets: tuple[tuple[TutorContextBudgetMode, int], ...]
    warning_ratio: float = 0.8
    critical_ratio: float = 0.95
    max_expansions: int = 1
    estimator_version: str = "utf8_bytes_v1"
    policy_version: str = "tutor_context_budget_v1"
    fixed_mode: TutorContextBudgetMode | None = None

    def __post_init__(self) -> None:
        if not 0 < self.warning_ratio < self.critical_ratio <= 1:
            raise ValueError("context warning/critical ratios are invalid")
        if self.max_expansions < 0:
            raise ValueError("max_expansions must be non-negative")
        targets: dict[TutorContextBudgetMode, int] = {}
        for mode, target in self.mode_targets:
            if mode in targets or target <= 0:
                raise ValueError("context mode targets must be unique and positive")
            targets[mode] = target
        if set(targets) != set(TutorContextBudgetMode):
            raise ValueError("context mode targets must cover every budget mode")
        normalized_targets = tuple((mode, targets[mode]) for mode in TutorContextBudgetMode)
        if any(
            normalized_targets[index][1] >= normalized_targets[index + 1][1]
            for index in range(len(normalized_targets) - 1)
        ):
            raise ValueError("context mode targets must increase by mode")
        object.__setattr__(self, "mode_targets", normalized_targets)
        object.__setattr__(self, "estimator_version", _safe_identifier(self.estimator_version))
        object.__setattr__(self, "policy_version", _safe_identifier(self.policy_version))

    def target_for(self, mode: TutorContextBudgetMode) -> int:
        for candidate, target in self.mode_targets:
            if candidate is mode:
                return target
        raise ValueError("context budget mode target is unavailable")


@dataclass(frozen=True)
class TutorContextBudgetPlan:
    mode: TutorContextBudgetMode
    physical_input_limit: int
    required_token_estimate: int
    optional_token_budget: int
    total_input_warning_tokens: int
    total_input_critical_tokens: int
    expansion_count: int
    estimator_version: str
    capability_version: str
    policy_version: str
    estimated_total_input_tokens: int

    def __post_init__(self) -> None:
        for name in (
            "physical_input_limit",
            "required_token_estimate",
            "total_input_warning_tokens",
            "total_input_critical_tokens",
            "estimated_total_input_tokens",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.optional_token_budget < 0 or self.expansion_count < 0:
            raise ValueError("context optional budget and expansion count must be non-negative")
        if not (
            self.total_input_warning_tokens
            < self.total_input_critical_tokens
            <= self.physical_input_limit
        ):
            raise ValueError("context warning/critical token limits are invalid")
        if self.required_token_estimate > self.estimated_total_input_tokens:
            raise ValueError("estimated total input cannot be below the required estimate")
        if self.estimated_total_input_tokens > self.physical_input_limit:
            raise ValueError("estimated total input exceeds the provider hard limit")
        object.__setattr__(self, "estimator_version", _safe_identifier(self.estimator_version))
        object.__setattr__(self, "capability_version", _safe_identifier(self.capability_version))
        object.__setattr__(self, "policy_version", _safe_identifier(self.policy_version))

    @property
    def warning_reached(self) -> bool:
        return self.estimated_total_input_tokens >= self.total_input_warning_tokens

    @property
    def critical_reached(self) -> bool:
        return self.estimated_total_input_tokens >= self.total_input_critical_tokens


@dataclass(frozen=True)
class TutorPolicySnapshot:
    deadline: datetime
    max_iterations: int = 3
    max_model_calls: int = 3
    max_capability_calls: int = 0
    max_effects: int = 0
    context_token_budget: int = 1200
    lease_duration_seconds: int = 30
    context_budget_policy: TutorContextBudgetPolicy | None = None

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
    semantic_class: Literal[
        "ordinary",
        "confirmed_fact_source",
        "correction",
        "unresolved_question",
    ] = "ordinary"

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _safe_identifier(self.source_id))


@dataclass(frozen=True)
class TutorContextCompactionCandidate:
    message_id: str
    content_hash: str
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "message_id", _safe_identifier(self.message_id))
        content_hash = str(self.content_hash or "").lower()
        if not _is_sha256(content_hash):
            raise ValueError("compaction candidate content_hash must be SHA-256")
        object.__setattr__(self, "content_hash", content_hash)
        if self.created_at.tzinfo is None:
            raise ValueError("compaction candidate timestamp must be timezone-aware")
        object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))


@dataclass(frozen=True)
class TutorContextCompactionPlan:
    summary_schema_version: str
    summary_policy_version: str
    candidates: tuple[TutorContextCompactionCandidate, ...]
    prior_summary_id: str | None = None
    prior_summary_hash: str | None = None
    protected_message_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            self.summary_schema_version != TUTOR_CONTEXT_SUMMARY_SCHEMA_VERSION
            or self.summary_policy_version != TUTOR_CONTEXT_SUMMARY_POLICY_VERSION
        ):
            raise ValueError("structured compaction schema or policy version is unsupported")
        candidates = tuple(self.candidates)
        if not candidates or len(candidates) > MAX_TUTOR_CONTEXT_COMPACTION_CANDIDATES:
            raise ValueError("compaction candidates must be non-empty and bounded")
        identities = tuple(candidate.message_id for candidate in candidates)
        if len(identities) != len(set(identities)):
            raise ValueError("compaction candidate identities must be unique")
        if tuple(sorted(candidates, key=lambda item: (item.created_at, item.message_id))) != candidates:
            raise ValueError("compaction candidates must follow conversation timeline order")
        object.__setattr__(self, "candidates", candidates)
        candidate_ids = frozenset(candidate.message_id for candidate in candidates)
        protected = tuple(_safe_identifier(value) for value in self.protected_message_ids)
        if len(protected) != len(set(protected)) or not set(protected).issubset(candidate_ids):
            raise ValueError("protected compaction message identities are invalid")
        object.__setattr__(self, "protected_message_ids", protected)
        if (self.prior_summary_id is None) != (self.prior_summary_hash is None):
            raise ValueError("prior summary identity and hash must be paired")
        if self.prior_summary_id is not None:
            object.__setattr__(self, "prior_summary_id", _safe_identifier(self.prior_summary_id))
            prior_hash = str(self.prior_summary_hash or "").lower()
            if not _is_sha256(prior_hash):
                raise ValueError("prior summary hash must be SHA-256")
            object.__setattr__(self, "prior_summary_hash", prior_hash)


@dataclass(frozen=True)
class TutorContextCompactionInput:
    summary_schema_version: str
    summary_policy_version: str
    source_hash: str
    retired_message_ids: tuple[str, ...]
    retired_message_hashes: tuple[str, ...]
    covered_through_created_at: datetime
    covered_through_message_id: str
    prior_summary_id: str | None = None
    prior_summary_hash: str | None = None

    def __post_init__(self) -> None:
        if (
            self.summary_schema_version != TUTOR_CONTEXT_SUMMARY_SCHEMA_VERSION
            or self.summary_policy_version != TUTOR_CONTEXT_SUMMARY_POLICY_VERSION
        ):
            raise ValueError("structured compaction schema or policy version is unsupported")
        object.__setattr__(self, "summary_schema_version", _safe_identifier(self.summary_schema_version))
        object.__setattr__(self, "summary_policy_version", _safe_identifier(self.summary_policy_version))
        source_hash = str(self.source_hash or "").lower()
        if not _is_sha256(source_hash):
            raise ValueError("context summary source_hash must be SHA-256")
        object.__setattr__(self, "source_hash", source_hash)
        message_ids = tuple(_safe_identifier(value) for value in self.retired_message_ids)
        message_hashes = tuple(str(value or "").lower() for value in self.retired_message_hashes)
        if not message_ids or len(message_ids) != len(message_hashes):
            raise ValueError("retired message evidence must be non-empty and paired")
        if len(message_ids) != len(set(message_ids)) or any(not _is_sha256(value) for value in message_hashes):
            raise ValueError("retired message evidence is malformed")
        object.__setattr__(self, "retired_message_ids", message_ids)
        object.__setattr__(self, "retired_message_hashes", message_hashes)
        covered_message_id = _safe_identifier(self.covered_through_message_id)
        if message_ids[-1] != covered_message_id:
            raise ValueError("coverage cursor must end at the final retired message")
        object.__setattr__(self, "covered_through_message_id", covered_message_id)
        if self.covered_through_created_at.tzinfo is None:
            raise ValueError("coverage timestamp must be timezone-aware")
        if (self.prior_summary_id is None) != (self.prior_summary_hash is None):
            raise ValueError("prior summary identity and hash must be paired")
        if self.prior_summary_id is not None:
            object.__setattr__(self, "prior_summary_id", _safe_identifier(self.prior_summary_id))
            prior_hash = str(self.prior_summary_hash or "").lower()
            if not _is_sha256(prior_hash):
                raise ValueError("prior summary hash must be SHA-256")
            object.__setattr__(self, "prior_summary_hash", prior_hash)


@dataclass(frozen=True)
class TutorContextInput:
    run_id: str
    conversation_id: str
    input_revision: int
    current_input_required: bool
    current_input: TutorContextSource | None = None
    system_descriptors: tuple[TutorContextSource, ...] = ()
    required_facts: tuple[TutorContextSource, ...] = ()
    action_receipts: tuple[TutorContextSource, ...] = ()
    active_plan: tuple[TutorContextSource, ...] = ()
    review_snapshot: tuple[TutorContextSource, ...] = ()
    recent_messages: tuple[TutorContextSource, ...] = ()
    working_summary: tuple[TutorContextSource, ...] = ()
    learner_memory: tuple[TutorContextSource, ...] = ()
    activity_facts: tuple[TutorContextSource, ...] = ()
    capability_schemas: tuple[TutorContextSource, ...] = ()
    compaction_plan: TutorContextCompactionPlan | None = None
    authoritative_snapshot_schema_version: str | None = None
    authoritative_snapshot_hash: str | None = None
    fact_revision: int = 0
    confirmed_question_reasked_count: int = 0
    summary_blocked_by_unprojected_fact: int = 0

    def __post_init__(self) -> None:
        if self.input_revision < 0:
            raise ValueError("input_revision must be non-negative")
        if self.current_input_required and self.current_input is None:
            raise TutorContextError("TUTOR_CURRENT_INPUT_MISSING")
        if not self.current_input_required and self.current_input is not None:
            raise TutorContextError("TUTOR_CURRENT_INPUT_UNEXPECTED")
        object.__setattr__(self, "run_id", _safe_identifier(self.run_id))
        object.__setattr__(self, "conversation_id", _safe_identifier(self.conversation_id))
        for name in (
            "system_descriptors",
            "required_facts",
            "action_receipts",
            "active_plan",
            "review_snapshot",
            "recent_messages",
            "working_summary",
            "learner_memory",
            "activity_facts",
            "capability_schemas",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if self.fact_revision < 0 or self.confirmed_question_reasked_count < 0 or self.summary_blocked_by_unprojected_fact < 0:
            raise ValueError("authoritative context counters must be non-negative")
        for name in ("authoritative_snapshot_schema_version", "authoritative_snapshot_hash"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, limit_text(str(value), 160))

    def section_sources(self) -> tuple[tuple[TutorContextSection, tuple[TutorContextSource, ...]], ...]:
        return (
            (TutorContextSection.SYSTEM, self.system_descriptors),
            (TutorContextSection.REQUIRED_FACTS, self.required_facts),
            (TutorContextSection.ACTION_RECEIPTS, self.action_receipts),
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
class TutorCurrentInput:
    source_id: str
    content: str
    source_hash: str
    token_estimate: int
    truncated: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _safe_identifier(self.source_id))
        object.__setattr__(self, "content", limit_text(self.content, MAX_TUTOR_PUBLIC_MESSAGE_LENGTH))
        object.__setattr__(self, "source_hash", limit_text(self.source_hash, 64))
        if not self.content:
            raise ValueError("current input content must not be blank")
        if self.token_estimate < 1:
            raise ValueError("current input token_estimate must be positive")

    def as_prompt_value(self) -> dict[str, str]:
        return {"role": "user", "content": self.content}


@dataclass(frozen=True)
class TutorCurrentInputMetadata:
    source_id: str
    source_hash: str
    token_estimate: int
    truncated: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _safe_identifier(self.source_id))
        object.__setattr__(self, "source_hash", limit_text(self.source_hash, 64))
        if self.token_estimate < 1:
            raise ValueError("current input token_estimate must be positive")


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
    current_input: TutorCurrentInputMetadata | None = None
    sections: tuple[TutorContextSectionMetadata, ...] = ()
    budget_mode: TutorContextBudgetMode | None = None
    estimated_total_input_tokens: int | None = None
    optional_token_budget: int | None = None
    warning_reached: bool = False
    critical_reached: bool = False
    expansion_count: int = 0
    estimator_version: str | None = None
    capability_version: str | None = None
    budget_policy_version: str | None = None
    truncated_count: int = 0
    compaction_input: TutorContextCompactionInput | None = None
    authoritative_snapshot_schema_version: str | None = None
    authoritative_snapshot_hash: str | None = None
    fact_revision: int = 0
    required_fact_count: int = 0
    required_fact_selected_count: int = 0
    required_fact_missing_count: int = 0
    confirmed_question_reasked_count: int = 0
    summary_blocked_by_unprojected_fact: int = 0

    def __post_init__(self) -> None:
        if self.token_budget <= 0:
            raise ValueError("token_budget must be positive")
        if self.consumed_tokens < 0 or self.consumed_tokens > self.token_budget:
            raise ValueError("consumed_tokens must be within token_budget")
        if self.estimated_total_input_tokens is not None and self.estimated_total_input_tokens <= 0:
            raise ValueError("estimated_total_input_tokens must be positive")
        if self.optional_token_budget is not None and self.optional_token_budget < 0:
            raise ValueError("optional_token_budget must be non-negative")
        if self.expansion_count < 0 or self.truncated_count < 0:
            raise ValueError("expansion_count and truncated_count must be non-negative")
        for name in (
            "fact_revision", "required_fact_count", "required_fact_selected_count",
            "required_fact_missing_count", "confirmed_question_reasked_count",
            "summary_blocked_by_unprojected_fact",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.required_fact_selected_count + self.required_fact_missing_count != self.required_fact_count:
            raise ValueError("required fact selection counts are inconsistent")
        if self.critical_reached and not self.warning_reached:
            raise ValueError("critical context state must also reach warning")
        for name in ("estimator_version", "capability_version", "budget_policy_version"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _safe_identifier(value))
        object.__setattr__(self, "sections", tuple(self.sections))

    @property
    def source_ids(self) -> tuple[str, ...]:
        current = (self.current_input.source_id,) if self.current_input is not None else ()
        return current + tuple(source_id for section in self.sections for source_id in section.source_ids)

    @property
    def source_hashes(self) -> tuple[str, ...]:
        current = (self.current_input.source_hash,) if self.current_input is not None else ()
        return current + tuple(source_hash for section in self.sections for source_hash in section.source_hashes)

    def as_dict(self) -> dict[str, object]:
        return {
            "token_budget": self.token_budget,
            "consumed_tokens": self.consumed_tokens,
            "current_input": (
                {
                    "source_id": self.current_input.source_id,
                    "source_hash": self.current_input.source_hash,
                    "token_estimate": self.current_input.token_estimate,
                    "truncated": self.current_input.truncated,
                }
                if self.current_input is not None
                else None
            ),
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
            "budget_mode": self.budget_mode.value if self.budget_mode is not None else None,
            "estimated_total_input_tokens": self.estimated_total_input_tokens,
            "optional_token_budget": self.optional_token_budget,
            "warning_reached": self.warning_reached,
            "critical_reached": self.critical_reached,
            "expansion_count": self.expansion_count,
            "estimator_version": self.estimator_version,
            "capability_version": self.capability_version,
            "budget_policy_version": self.budget_policy_version,
            "truncated_count": self.truncated_count,
            "authoritative_snapshot_schema_version": self.authoritative_snapshot_schema_version,
            "authoritative_snapshot_hash": self.authoritative_snapshot_hash,
            "fact_revision": self.fact_revision,
            "required_fact_count": self.required_fact_count,
            "required_fact_selected_count": self.required_fact_selected_count,
            "required_fact_missing_count": self.required_fact_missing_count,
            "confirmed_question_reasked_count": self.confirmed_question_reasked_count,
            "summary_blocked_by_unprojected_fact": self.summary_blocked_by_unprojected_fact,
            "summary_schema_version": (
                self.compaction_input.summary_schema_version if self.compaction_input is not None else None
            ),
            "summary_policy_version": (
                self.compaction_input.summary_policy_version if self.compaction_input is not None else None
            ),
            "summary_source_hash": (
                self.compaction_input.source_hash if self.compaction_input is not None else None
            ),
            "prior_summary_id": (
                self.compaction_input.prior_summary_id if self.compaction_input is not None else None
            ),
            "prior_summary_hash": (
                self.compaction_input.prior_summary_hash if self.compaction_input is not None else None
            ),
            "retired_message_ids": (
                list(self.compaction_input.retired_message_ids) if self.compaction_input is not None else []
            ),
            "retired_message_hashes": (
                list(self.compaction_input.retired_message_hashes) if self.compaction_input is not None else []
            ),
            "covered_through_created_at": (
                self.compaction_input.covered_through_created_at.isoformat()
                if self.compaction_input is not None
                else None
            ),
            "covered_through_message_id": (
                self.compaction_input.covered_through_message_id if self.compaction_input is not None else None
            ),
        }


@dataclass(frozen=True)
class TutorCompactionRequest:
    idempotency_key: str
    curation_idempotency_key: str
    run_id: str
    conversation_id: str
    input_revision: int
    trigger: TutorCompactionTrigger
    projection_kind: Literal["memory_or_summary", "context_summary"]
    source_ids: tuple[str, ...]
    source_hashes: tuple[str, ...]
    token_budget: int
    consumed_tokens: int
    summary_schema_version: str | None = None
    summary_policy_version: str | None = None
    summary_source_hash: str | None = None
    prior_summary_id: str | None = None
    prior_summary_hash: str | None = None
    covered_through_created_at: datetime | None = None
    covered_through_message_id: str | None = None

    def __post_init__(self) -> None:
        if self.input_revision < 0:
            raise ValueError("input_revision must be non-negative")
        if self.token_budget <= 0 or self.consumed_tokens < 0 or self.consumed_tokens > self.token_budget:
            raise ValueError("compaction request budget is invalid")
        object.__setattr__(self, "idempotency_key", limit_text(self.idempotency_key, 160))
        object.__setattr__(self, "curation_idempotency_key", limit_text(self.curation_idempotency_key, 160))
        object.__setattr__(self, "run_id", _safe_identifier(self.run_id))
        object.__setattr__(self, "conversation_id", _safe_identifier(self.conversation_id))
        source_ids = tuple(_safe_identifier(value) for value in self.source_ids)
        source_hashes = tuple(str(value or "").lower() for value in self.source_hashes)
        if len(source_ids) != len(source_hashes):
            raise ValueError("compaction source evidence is malformed")
        object.__setattr__(self, "source_ids", source_ids)
        object.__setattr__(self, "source_hashes", source_hashes)
        if self.projection_kind == "context_summary":
            if any(not _is_sha256(value) for value in source_hashes):
                raise ValueError("structured compaction source hashes must be SHA-256")
            if (
                not source_ids
                or self.summary_schema_version is None
                or self.summary_policy_version is None
                or self.summary_source_hash is None
                or self.covered_through_created_at is None
                or self.covered_through_message_id is None
            ):
                raise ValueError("structured context summary request is incomplete")
            object.__setattr__(self, "summary_schema_version", _safe_identifier(self.summary_schema_version))
            object.__setattr__(self, "summary_policy_version", _safe_identifier(self.summary_policy_version))
            summary_source_hash = str(self.summary_source_hash or "").lower()
            if not _is_sha256(summary_source_hash):
                raise ValueError("summary source hash must be SHA-256")
            object.__setattr__(self, "summary_source_hash", summary_source_hash)
            if self.covered_through_created_at.tzinfo is None:
                raise ValueError("summary coverage timestamp must be timezone-aware")
            covered_message_id = _safe_identifier(self.covered_through_message_id)
            if source_ids[-1] != covered_message_id:
                raise ValueError("summary coverage must end at the final source message")
            object.__setattr__(self, "covered_through_message_id", covered_message_id)
            if (self.prior_summary_id is None) != (self.prior_summary_hash is None):
                raise ValueError("prior summary evidence must be paired")
            if self.prior_summary_id is not None:
                object.__setattr__(self, "prior_summary_id", _safe_identifier(self.prior_summary_id))
                prior_hash = str(self.prior_summary_hash or "").lower()
                if not _is_sha256(prior_hash):
                    raise ValueError("prior summary hash must be SHA-256")
                object.__setattr__(self, "prior_summary_hash", prior_hash)
        elif any(not _is_safe_hash(value) for value in source_hashes):
            raise ValueError("legacy compaction source hashes are malformed")
        elif any(
            value is not None
            for value in (
                self.summary_schema_version,
                self.summary_policy_version,
                self.summary_source_hash,
                self.prior_summary_id,
                self.prior_summary_hash,
                self.covered_through_created_at,
                self.covered_through_message_id,
            )
        ):
            raise ValueError("legacy curation request cannot carry structured summary evidence")


@dataclass(frozen=True)
class TutorContextSelection:
    items: tuple[TutorContextItem, ...]
    checkpoint_metadata: TutorCheckpointMetadata
    current_input: TutorCurrentInput | None = None
    high_water_compaction_request: TutorCompactionRequest | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        metadata = self.checkpoint_metadata.current_input
        if (self.current_input is None) != (metadata is None):
            raise ValueError("current input and checkpoint metadata must agree")
        if self.current_input is not None and metadata is not None:
            if (
                self.current_input.source_id != metadata.source_id
                or self.current_input.source_hash != metadata.source_hash
                or self.current_input.token_estimate != metadata.token_estimate
                or self.current_input.truncated != metadata.truncated
            ):
                raise ValueError("current input metadata does not match selection")

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
    public_thinking_text: str = ""
    public_thinking_steps: tuple[str, ...] = ()
    conversation_title: str | None = None
    question_key: TutorPlanningQuestionKey | None = None
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
        legacy_steps = _bounded_public_thinking_steps(self.public_thinking_steps)
        public_thinking_text = _bounded_public_thinking_text(self.public_thinking_text)
        if not public_thinking_text and legacy_steps:
            public_thinking_text = "\n\n".join(legacy_steps)
        object.__setattr__(self, "public_thinking_text", public_thinking_text)
        object.__setattr__(self, "public_thinking_steps", legacy_steps)
        if self.conversation_title is not None:
            object.__setattr__(self, "conversation_title", normalize_tutor_conversation_title(self.conversation_title))
        if self.question_key is not None:
            object.__setattr__(self, "question_key", _safe_identifier(self.question_key))
        if self.continuation_kind is TutorContinuationKind.PLANNING_INPUT:
            if self.question_key is None:
                raise ValueError("planning_input continuation requires question_key")
            if self.question_key not in TUTOR_PLANNING_QUESTION_KEYS:
                raise ValueError("planning_input continuation question_key is not allowlisted")
        elif self.question_key is not None:
            raise ValueError("question_key is reserved for planning_input continuation")
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
class TutorProviderAttemptReceipt:
    attempt_index: int
    outcome: TutorProviderAttemptOutcome
    provider_type: str
    protocol: str
    usage: LLMUsage | None = None
    model: str | None = None
    diagnostic_code: str | None = None

    def __post_init__(self) -> None:
        if self.attempt_index < 1:
            raise ValueError("provider attempt_index must be positive")
        object.__setattr__(self, "provider_type", _safe_identifier(self.provider_type))
        object.__setattr__(self, "protocol", _safe_identifier(self.protocol))
        if self.model is not None:
            object.__setattr__(self, "model", _safe_identifier(self.model))
        if self.diagnostic_code is not None:
            object.__setattr__(
                self, "diagnostic_code", _safe_identifier(self.diagnostic_code)
            )
        if (
            self.outcome is TutorProviderAttemptOutcome.ACCEPTED
            and self.diagnostic_code is not None
        ):
            raise ValueError("accepted provider attempt cannot have a diagnostic code")
        if (
            self.outcome is not TutorProviderAttemptOutcome.ACCEPTED
            and self.diagnostic_code is None
        ):
            raise ValueError("rejected provider attempt requires a diagnostic code")
        if (
            self.outcome is TutorProviderAttemptOutcome.TRANSPORT_FAILED
            and self.usage is not None
        ):
            raise ValueError("transport failure cannot report provider envelope usage")


@dataclass(frozen=True)
class TutorProviderResult:
    decision: TutorDecision | None
    model: str | None = None
    terminal_outcome: TutorTerminalOutcome | None = None
    safe_code: str | None = None
    attempts: tuple[TutorProviderAttemptReceipt, ...] = ()

    def __post_init__(self) -> None:
        if (self.decision is None) == (self.terminal_outcome is None):
            raise ValueError(
                "provider result must contain either a decision or terminal outcome"
            )
        if self.model is not None:
            object.__setattr__(self, "model", _safe_identifier(self.model))
        if self.safe_code is not None:
            object.__setattr__(self, "safe_code", _safe_identifier(self.safe_code))
        object.__setattr__(self, "attempts", tuple(self.attempts))
        _ensure_unique(
            (str(item.attempt_index) for item in self.attempts),
            "provider attempt indexes",
        )

    @classmethod
    def model_unavailable(
        cls,
        *,
        safe_code: str = "MODEL_UNAVAILABLE",
        attempts: tuple[TutorProviderAttemptReceipt, ...] = (),
    ) -> "TutorProviderResult":
        return cls(
            decision=None,
            terminal_outcome=TutorTerminalOutcome.MODEL_UNAVAILABLE,
            safe_code=safe_code,
            attempts=attempts,
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
    interaction_protocol_version: Literal["legacy_v1", "thread_turn_v2"] = "legacy_v1"
    runtime_kind: Literal["harness_v1", "codex_sidecar_v1"] = "harness_v1"

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
    public_thinking_text: str = ""
    public_thinking_steps: tuple[str, ...] = ()
    # The decision candidate is persisted only with the same successful public reply.
    conversation_title: str | None = None
    # A normal completed TurnRun has no continuation.
    continuation_kind: TutorContinuationKind | None = None
    completion_reason: TutorTurnCompletionReason | None = None
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
        legacy_steps = _bounded_public_thinking_steps(self.public_thinking_steps)
        public_thinking_text = _bounded_public_thinking_text(self.public_thinking_text)
        if not public_thinking_text and legacy_steps:
            public_thinking_text = "\n\n".join(legacy_steps)
        object.__setattr__(self, "public_thinking_text", public_thinking_text)
        object.__setattr__(self, "public_thinking_steps", legacy_steps)
        if self.conversation_title is not None:
            object.__setattr__(self, "conversation_title", normalize_tutor_conversation_title(self.conversation_title))
        if self.continuation_kind is not None:
            if self.status is not TutorRunStatus.WAITING_FOR_INPUT or self.terminal_outcome is not None:
                raise ValueError("Tutor continuation result must be a non-terminal waiting state")
        if self.completion_reason is not None:
            if self.status is not TutorRunStatus.COMPLETED or self.terminal_outcome is not TutorTerminalOutcome.COMPLETED:
                raise ValueError("Tutor completion reason requires a completed terminal source turn")
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
    compaction = metadata.compaction_input
    source_ids = compaction.retired_message_ids if compaction is not None else metadata.source_ids
    source_hashes = compaction.retired_message_hashes if compaction is not None else metadata.source_hashes
    projection_kind: Literal["memory_or_summary", "context_summary"] = (
        "context_summary" if compaction is not None else "memory_or_summary"
    )
    payload = {
        "run_id": _safe_identifier(run_id),
        "conversation_id": _safe_identifier(conversation_id),
        "input_revision": input_revision,
        "trigger": trigger.value,
        "projection_kind": projection_kind,
        "source_ids": list(source_ids),
        "source_hashes": list(source_hashes),
        "token_budget": metadata.token_budget,
        "consumed_tokens": metadata.consumed_tokens,
        "summary_source_hash": compaction.source_hash if compaction is not None else None,
    }
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:24]
    if compaction is None:
        curation_idempotency_key = f"tutor-compaction:{digest}"
    else:
        curation_payload = {
            "run_id": _safe_identifier(run_id),
            "conversation_id": _safe_identifier(conversation_id),
            "input_revision": input_revision,
            "summary_schema_version": compaction.summary_schema_version,
            "summary_policy_version": compaction.summary_policy_version,
            "prior_summary_id": compaction.prior_summary_id,
            "prior_summary_hash": compaction.prior_summary_hash,
            "source_ids": list(compaction.retired_message_ids),
            "source_hashes": list(compaction.retired_message_hashes),
            "covered_through_created_at": compaction.covered_through_created_at.astimezone(UTC).isoformat(),
            "covered_through_message_id": compaction.covered_through_message_id,
            "summary_source_hash": compaction.source_hash,
        }
        curation_digest = hashlib.sha256(
            json.dumps(curation_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:24]
        curation_idempotency_key = f"tutor-summary:{curation_digest}"
    return TutorCompactionRequest(
        idempotency_key=f"tutor-compaction:{digest}",
        curation_idempotency_key=curation_idempotency_key,
        run_id=run_id,
        conversation_id=conversation_id,
        input_revision=input_revision,
        trigger=trigger,
        projection_kind=projection_kind,
        source_ids=source_ids,
        source_hashes=source_hashes,
        token_budget=metadata.token_budget,
        consumed_tokens=metadata.consumed_tokens,
        summary_schema_version=(compaction.summary_schema_version if compaction is not None else None),
        summary_policy_version=(compaction.summary_policy_version if compaction is not None else None),
        summary_source_hash=(compaction.source_hash if compaction is not None else None),
        prior_summary_id=(compaction.prior_summary_id if compaction is not None else None),
        prior_summary_hash=(compaction.prior_summary_hash if compaction is not None else None),
        covered_through_created_at=(compaction.covered_through_created_at if compaction is not None else None),
        covered_through_message_id=(compaction.covered_through_message_id if compaction is not None else None),
    )


def build_tutor_message_evidence_hash(
    *,
    message_id: str,
    role: str,
    content: str,
    created_at: datetime,
) -> str:
    if role not in {"learner", "tutor"}:
        raise ValueError("Tutor message evidence role is invalid")
    if created_at.tzinfo is None:
        raise ValueError("Tutor message evidence timestamp must be timezone-aware")
    payload = {
        "message_id": _safe_identifier(message_id),
        "role": role,
        "content": str(content),
        "created_at": created_at.astimezone(UTC).isoformat(),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_tutor_context_summary_source_hash(
    *,
    summary_schema_version: str,
    summary_policy_version: str,
    prior_summary_id: str | None,
    prior_summary_hash: str | None,
    retired_message_ids: tuple[str, ...],
    retired_message_hashes: tuple[str, ...],
    covered_through_created_at: datetime,
    covered_through_message_id: str,
) -> str:
    if covered_through_created_at.tzinfo is None:
        raise ValueError("summary coverage timestamp must be timezone-aware")
    normalized_prior_summary_id = _safe_identifier(prior_summary_id) if prior_summary_id is not None else None
    normalized_prior_summary_hash = str(prior_summary_hash or "").lower() or None
    normalized_message_ids = [_safe_identifier(value) for value in retired_message_ids]
    normalized_message_hashes = [str(value or "").lower() for value in retired_message_hashes]
    if (normalized_prior_summary_id is None) != (normalized_prior_summary_hash is None):
        raise ValueError("prior summary evidence must be paired")
    if not normalized_message_ids or len(normalized_message_ids) != len(normalized_message_hashes):
        raise ValueError("retired message evidence must be non-empty and paired")
    if any(not _is_sha256(value) for value in normalized_message_hashes):
        raise ValueError("retired message hashes must be SHA-256")
    if normalized_prior_summary_hash is not None and not _is_sha256(normalized_prior_summary_hash):
        raise ValueError("prior summary hash must be SHA-256")
    payload: dict[str, object] = {
        "summary_schema_version": _safe_identifier(summary_schema_version),
        "summary_policy_version": _safe_identifier(summary_policy_version),
        "prior_summary_id": normalized_prior_summary_id,
        "prior_summary_hash": normalized_prior_summary_hash,
        "retired_message_ids": normalized_message_ids,
        "retired_message_hashes": normalized_message_hashes,
        "covered_through_created_at": covered_through_created_at.astimezone(UTC).isoformat(),
        "covered_through_message_id": _safe_identifier(covered_through_message_id),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _is_sha256(value: object) -> bool:
    normalized = str(value or "").lower()
    return len(normalized) == 64 and all(character in "0123456789abcdef" for character in normalized)


def _is_safe_hash(value: object) -> bool:
    normalized = str(value or "").lower()
    return 24 <= len(normalized) <= 64 and all(character in "0123456789abcdef" for character in normalized)


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


def _bounded_public_thinking_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text:
        return ""
    if len(text) > MAX_TUTOR_PUBLIC_THINKING_TEXT_LENGTH:
        text = text[:MAX_TUTOR_PUBLIC_THINKING_TEXT_LENGTH]
    check = check_teaching_output(text)
    if check.blocked:
        return ""
    return text


def _bounded_public_thinking_steps(steps: object) -> tuple[str, ...]:
    if not isinstance(steps, tuple | list):
        return ()
    normalized: list[str] = []
    for raw_step in steps[:MAX_TUTOR_PUBLIC_THINKING_STEPS]:
        if not isinstance(raw_step, str):
            continue
        step = sanitize_summary_text(
            raw_step,
            max_length=MAX_TUTOR_PUBLIC_THINKING_STEP_LENGTH,
        )
        if step:
            normalized.append(step)
    return tuple(normalized)


def _safe_identifier(value: object) -> str:
    redacted = redact_value(str(value or ""))
    return limit_text(str(redacted), MAX_TUTOR_IDENTIFIER_LENGTH) or "unknown"


def _ensure_unique(values: Iterable[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {label}")
        seen.add(value)
