"""Provider-neutral immutable LLM response contracts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, get_args


@dataclass(frozen=True)
class LLMUsage:
    """Normalized provider-reported token usage without prompt or response content."""

    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    reasoning_tokens: int | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "total_tokens",
            "reasoning_tokens",
        ):
            value = getattr(self, field_name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer when present")
        if self.cached_input_tokens is not None:
            if self.input_tokens is None:
                raise ValueError("cached_input_tokens requires input_tokens")
            if self.cached_input_tokens > self.input_tokens:
                raise ValueError("cached_input_tokens must not exceed input_tokens")

    @property
    def usage_available(self) -> bool:
        return any(
            value is not None
            for value in (
                self.input_tokens,
                self.cached_input_tokens,
                self.output_tokens,
                self.total_tokens,
                self.reasoning_tokens,
            )
        )

    @property
    def uncached_input_tokens(self) -> int | None:
        if self.input_tokens is None:
            return None
        return self.input_tokens - (self.cached_input_tokens or 0)

    @property
    def calculated_total_tokens(self) -> int | None:
        if self.input_tokens is None or self.output_tokens is None:
            return None
        return self.input_tokens + self.output_tokens


LLMResponseStatus = Literal[
    "completed", "incomplete", "failed", "in_progress", "queued", "cancelled",
    "missing_terminal", "unknown",
]
LLMIncompleteReason = Literal[
    "max_output_tokens", "content_filter", "context_length_exceeded", "unknown",
]
LLMReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]


@dataclass(frozen=True)
class LLMResponseDiagnostics:
    """Allowlisted provider metadata only; never provider text or error details."""

    response_status: LLMResponseStatus = "unknown"
    incomplete_reason: LLMIncompleteReason | None = None
    requested_max_output_tokens: int | None = None
    requested_reasoning_effort: LLMReasoningEffort | None = None
    visible_output_chars: int | None = None

    def __post_init__(self) -> None:
        for name, allowed, optional in (
            ("response_status", get_args(LLMResponseStatus), False),
            ("incomplete_reason", get_args(LLMIncompleteReason), True),
            ("requested_reasoning_effort", get_args(LLMReasoningEffort), True),
        ):
            value = getattr(self, name)
            if optional and value is None:
                continue
            if not isinstance(value, str) or value not in allowed:
                raise ValueError(f"{name} must be an allowlisted literal")
        for name in ("requested_max_output_tokens", "visible_output_chars"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"{name} must be a non-negative integer when present")
