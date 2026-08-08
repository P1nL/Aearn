"""Provider-neutral immutable LLM response contracts."""
from __future__ import annotations

from dataclasses import dataclass


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
