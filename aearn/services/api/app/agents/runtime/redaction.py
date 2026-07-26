"""Bounded recursive redaction for shared agent-runtime payloads."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


REDACTED_FIELDS = frozenset(
    {
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
    }
)

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


def redact_value(value: object) -> object:
    """Return a bounded recursive representation without sensitive values."""
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, Mapping):
        return redact_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [redact_value(item) for item in value[:20]]
    return value


def redact_mapping(
    mapping: Mapping[Any, object],
    *,
    max_keys: int = 50,
) -> dict[str, object]:
    """Recursively redact at most ``max_keys`` mapping entries."""
    result: dict[str, object] = {}
    for index, (raw_key, value) in enumerate(mapping.items()):
        if index >= max_keys:
            break
        key = str(raw_key)
        if key.lower() in REDACTED_FIELDS:
            result[key] = "[REDACTED]"
            continue
        result[key] = redact_value(value)
    return result


def _redact_string(value: str) -> str:
    lowered = value.lower()
    if any(marker in lowered for marker in REDACTED_CONTENT_MARKERS):
        return "[REDACTED: contains sensitive content]"
    return value
