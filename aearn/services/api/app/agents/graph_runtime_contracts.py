"""Shared graph runtime contracts for LangGraph orchestration.

Defines state, intent, result, and fallback types shared across
learning, onboarding, and review graph modules. Graph nodes produce
intents; service layers execute them against repositories.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum


MAX_USER_TEXT_LENGTH = 4000
MAX_SUMMARY_LENGTH = 2000
MAX_ID_LENGTH = 80
MAX_ERROR_LENGTH = 160
MAX_INTENT_PAYLOAD_KEYS = 20
MAX_INTENTS_PER_RUN = 10
MAX_ERRORS_PER_RUN = 5
MAX_DIAGNOSTICS_LENGTH = 500

REDACTED_FIELDS = frozenset({
    "solution_reference",
    "hidden_tests",
    "hidden_test_source",
    "raw_prompt",
    "system_prompt",
    "provider_payload",
    "api_key",
    "secret",
    "auth_token",
    "stack_trace",
    "traceback",
})

REDACTED_CONTENT_MARKERS = (
    "solution_reference",
    "solution reference",
    "hidden_test",
    "hidden test",
    "raw_prompt",
    "raw prompt",
    "system prompt",
    "api_key",
    "api key",
    "secret_key",
    "secret key",
    "auth_token",
    "auth token",
    "provider payload",
    "provider error",
)


class IntentType(str, Enum):
    STAGE_UPDATE = "stage_update"
    TOOL_CALL = "tool_call"
    FEEDBACK_REQUEST = "feedback_request"
    PERSISTENCE = "persistence"
    PROFILE_UPDATE = "profile_update"
    SIDE_EFFECT = "side_effect"


@dataclass(frozen=True)
class GraphIntent:
    intent_type: IntentType
    target: str
    payload: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "intent_type": self.intent_type.value,
            "target": self.target,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True)
class GraphRuntimeState:
    session_id: str
    user_id: str
    session_type: str
    current_stage: str
    user_text: str
    context_summary: str = ""
    scoped_ids: Mapping[str, str] = field(default_factory=dict)
    session_facts: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "session_type": self.session_type,
            "current_stage": self.current_stage,
            "user_text": self.user_text,
            "context_summary": self.context_summary,
            "scoped_ids": dict(self.scoped_ids),
            "session_facts": dict(self.session_facts),
        }


@dataclass(frozen=True)
class GraphRunResult:
    next_stage: str
    intents: tuple[GraphIntent, ...] = ()
    diagnostics: str = ""
    safe_context: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "next_stage": self.next_stage,
            "intents": [intent.to_dict() for intent in self.intents],
            "diagnostics": self.diagnostics,
            "safe_context": dict(self.safe_context),
        }


@dataclass(frozen=True)
class GraphFallback:
    reason: str
    fallback_stage: str
    safe_message: str = ""
    recoverable: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "reason": self.reason,
            "fallback_stage": self.fallback_stage,
            "safe_message": self.safe_message,
            "recoverable": self.recoverable,
        }


# --- State construction ---


def build_runtime_state(
    *,
    session_id: str,
    user_id: str,
    session_type: str,
    current_stage: str,
    user_text: str,
    context_summary: str = "",
    scoped_ids: Mapping[str, str] | None = None,
    session_facts: Mapping[str, object] | None = None,
) -> GraphRuntimeState:
    return GraphRuntimeState(
        session_id=_bound_id(session_id),
        user_id=_bound_id(user_id),
        session_type=_bound_id(session_type),
        current_stage=_bound_id(current_stage),
        user_text=_bound_text(user_text, MAX_USER_TEXT_LENGTH),
        context_summary=_bound_text(context_summary, MAX_SUMMARY_LENGTH),
        scoped_ids=_bound_id_mapping(scoped_ids or {}),
        session_facts=_redact_mapping(session_facts or {}),
    )


# --- Intent construction ---


def make_intent(
    intent_type: IntentType,
    target: str,
    payload: Mapping[str, object] | None = None,
) -> GraphIntent:
    safe_payload = _redact_mapping(payload or {}, max_keys=MAX_INTENT_PAYLOAD_KEYS)
    return GraphIntent(
        intent_type=intent_type,
        target=_bound_text(target, MAX_ID_LENGTH),
        payload=safe_payload,
    )


# --- Result construction ---


def build_run_result(
    *,
    next_stage: str,
    intents: Sequence[GraphIntent] = (),
    diagnostics: str = "",
    safe_context: Mapping[str, object] | None = None,
) -> GraphRunResult:
    bounded_intents = tuple(intents[:MAX_INTENTS_PER_RUN])
    return GraphRunResult(
        next_stage=_bound_text(next_stage, MAX_ID_LENGTH),
        intents=bounded_intents,
        diagnostics=_bound_text(diagnostics, MAX_DIAGNOSTICS_LENGTH),
        safe_context=_redact_mapping(safe_context or {}),
    )


# --- Fallback construction ---


def build_fallback(
    *,
    reason: str,
    fallback_stage: str,
    safe_message: str = "",
    recoverable: bool = True,
) -> GraphFallback:
    return GraphFallback(
        reason=_redact_error(reason),
        fallback_stage=_bound_text(fallback_stage, MAX_ID_LENGTH),
        safe_message=_bound_text(safe_message, MAX_ERROR_LENGTH),
        recoverable=recoverable,
    )


# --- Validation ---


def validate_intents(intents: Sequence[GraphIntent]) -> list[str]:
    errors: list[str] = []
    if len(intents) > MAX_INTENTS_PER_RUN:
        errors.append(f"too many intents: {len(intents)} > {MAX_INTENTS_PER_RUN}")
    for i, intent in enumerate(intents):
        if not intent.target:
            errors.append(f"intent[{i}] has empty target")
        if intent.intent_type not in IntentType:
            errors.append(f"intent[{i}] has invalid type")
    return errors


def validate_run_result(result: GraphRunResult) -> list[str]:
    errors: list[str] = []
    if not result.next_stage:
        errors.append("run result has empty next_stage")
    errors.extend(validate_intents(result.intents))
    return errors


# --- Redaction and sanitization ---


def redact_value(value: object) -> object:
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, Mapping):
        return _redact_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [redact_value(item) for item in value[:20]]
    return value


def _redact_mapping(
    mapping: Mapping[str, object],
    *,
    max_keys: int = 50,
) -> dict[str, object]:
    result: dict[str, object] = {}
    for i, (key, value) in enumerate(mapping.items()):
        if i >= max_keys:
            break
        if key.lower() in REDACTED_FIELDS:
            result[key] = "[REDACTED]"
            continue
        result[key] = redact_value(value)
    return result


def _redact_string(value: str) -> str:
    lowered = value.lower()
    for marker in REDACTED_CONTENT_MARKERS:
        if marker in lowered:
            return "[REDACTED: contains sensitive content]"
    return value


def _redact_error(error: str) -> str:
    bounded = _bound_text(error, MAX_ERROR_LENGTH)
    lowered = bounded.lower()
    if any(marker in lowered for marker in ("traceback", "stack_trace", "api_key", "secret")):
        return "internal error (details redacted)"
    return bounded


# --- Bounding helpers ---


def _bound_text(value: str, max_length: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_length:
        return text
    return text[:max_length]


def _bound_id(value: str) -> str:
    return _bound_text(value, MAX_ID_LENGTH)


def _bound_id_mapping(mapping: Mapping[str, str]) -> dict[str, str]:
    return {
        _bound_id(key): _bound_id(str(value))
        for key, value in list(mapping.items())[:20]
    }
