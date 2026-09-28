"""Opt-in, message-rendered diagnostics. Never serialize arbitrary LogRecord extras.

Callers pass server-owned labels/IDs only; untrusted action identifiers must use
safe_diagnostic_identifier(..., trusted=False). No exception text or traceback.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re

_IDENTIFIER = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:@\[\]-]{0,127}\Z")
_TEXT_FIELDS = frozenset({
    "stage", "code", "primary_code", "primary_stage", "state", "request_id",
    "job_id", "run_id", "conversation_id", "user_id", "runtime_kind",
    "document_kind", "action_category", "field_path", "action_identifier",
    "catalog_digest", "skill_reference", "manifest_hash", "instruction_hash",
    "exception_class", "cause_class", "termination_reason",
    "artifact_id", "capture_state", "provider_type", "model", "protocol", "expected_type",
})
_NUMBER_FIELDS = frozenset({
    "runtime_generation", "total_text_chars", "effective_max_reasoning_chars",
    "effective_max_total_chars", "effective_timeout_seconds", "raw_notification_count",
    "source_delta_count", "projection_event_count", "item_count", "tool_count",
    "projection_sequence", "tool_repair_count",
    "visible_chars", "reasoning_chars", "effective_max_output_tokens",
    "effective_max_visible_chars", "duration_ms", "attempt", "input_revision", "lease_generation",
    "iteration_count", "model_call_count", "capability_call_count", "effect_count",
    "required_fact_count", "required_fact_selected_count", "required_fact_missing_count",
    "confirmed_question_reasked_count", "summary_blocked_by_unprojected_fact",
    "decision_iteration", "max_attempts", "repair_attempt", "remaining_repair_attempts",
    "captured_bytes", "string_length", "serialized_length", "list_count",
})


def safe_diagnostic_identifier(value: str, *, trusted: bool = True) -> str:
    """Bound server identifiers; hash arbitrary/untrusted strings without echoing them."""
    if trusted and _IDENTIFIER.fullmatch(value) and not value.lower().startswith(("sk-", "bearer")):
        return value
    return "sha256:" + hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def log_safe_event(
    logger: logging.Logger, event: str, *, level: int = logging.WARNING,
    exception: BaseException | None = None, **fields: object,
) -> None:
    """Emit one bounded JSON message under ordinary/Celery formatters.

    Unknown keys and non-scalar values are discarded except server-schema expectations.
    expected_rule/expected_values MUST originate from local schema/rule constants, not
    provider validation messages, rejected values, prompts or user input. Exception
    and explicit cause contribute class names only, never args/messages/frames.
    """
    data: dict[str, object] = {"event": safe_diagnostic_identifier(event)}
    for key in _TEXT_FIELDS:
        value = fields.get(key)
        if isinstance(value, str):
            data[key] = safe_diagnostic_identifier(value)
    for key in _NUMBER_FIELDS:
        value = fields.get(key)
        if type(value) in (int, float) and isinstance(value, (int, float)):
            if isinstance(value, float) and not math.isfinite(value):
                continue
            data[key] = round(min(max(value, 0), 1_000_000_000), 3)
    for key in ("retry_allowed", "truncated"):
        if type(fields.get(key)) is bool:
            data[key] = fields[key]
    rule = fields.get("expected_rule")
    if isinstance(rule, str) and len(rule) <= 512 and not any(ord(c) < 32 for c in rule):
        data["expected_rule"] = rule
    values = fields.get("expected_values")
    if isinstance(values, (tuple, list)) and len(values) <= 32:
        if all(isinstance(value, str) and _IDENTIFIER.fullmatch(value) for value in values):
            data["expected_values"] = list(values)
    json_types = {"null", "string", "integer", "number", "boolean", "array", "object"}
    observed = fields.get("observed_type")
    if isinstance(observed, str) and observed in json_types:
        data["observed_type"] = observed
    types = fields.get("expected_types")
    if (isinstance(types, (tuple, list)) and len(types) <= len(json_types)
            and all(isinstance(item, str) and item in json_types for item in types)):
        data["expected_types"] = list(types)
    argument = fields.get("argument_key")
    if isinstance(argument, str) and re.fullmatch(r"profile_json|module_[1-8]", argument):
        data["argument_key"] = argument
    if exception is not None:
        data["exception_class"] = safe_diagnostic_identifier(type(exception).__name__)
        if exception.__cause__ is not None:
            data["cause_class"] = safe_diagnostic_identifier(type(exception.__cause__).__name__)
    logger.log(level, "%s", json.dumps(data, sort_keys=True, separators=(",", ":")))
