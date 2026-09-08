"""Aearn-owned contracts for pluggable agent runtimes."""
from __future__ import annotations

import re
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable

_TOOL_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class RuntimeHealthStatus(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    READY = "ready"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class RuntimeTerminalStatus(StrEnum):
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class RuntimeEventKind(StrEnum):
    TURN_STARTED = "turn_started"
    REASONING_STARTED = "reasoning_started"
    REASONING_DELTA = "reasoning_delta"
    REASONING_COMPLETED = "reasoning_completed"
    REASONING_SUMMARY_STARTED = "reasoning_summary_started"
    REASONING_SUMMARY_DELTA = "reasoning_summary_delta"
    REASONING_SUMMARY_COMPLETED = "reasoning_summary_completed"
    MESSAGE_STARTED = "message_started"
    MESSAGE_DELTA = "message_delta"
    MESSAGE_COMPLETED = "message_completed"
    CONTEXT_COMPACTION_STARTED = "context_compaction_started"
    CONTEXT_COMPACTION_COMPLETED = "context_compaction_completed"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    TURN_COMPLETED = "turn_completed"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class RuntimeInput:
    text: str

    def __post_init__(self) -> None:
        if not self.text.strip() or len(self.text) > 20_000:
            raise ValueError("runtime input text must contain 1..20000 characters")


@dataclass(frozen=True, slots=True)
class RuntimeToolDefinition:
    name: str
    description: str
    input_schema: Mapping[str, object]

    def __post_init__(self) -> None:
        if _TOOL_NAME.fullmatch(self.name) is None:
            raise ValueError("runtime tool name is invalid")
        if not self.description.strip() or len(self.description) > 500:
            raise ValueError("runtime tool description must contain 1..500 characters")
        if self.input_schema.get("type") != "object":
            raise ValueError("runtime tool input schema must describe an object")


@dataclass(frozen=True, slots=True)
class RuntimeToolCall:
    thread_id: str
    turn_id: str
    call_id: str
    tool_name: str
    arguments: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class RuntimeToolResult:
    success: bool
    content: str
    safe_code: str | None = None

    def __post_init__(self) -> None:
        if not self.content or len(self.content) > 8_000:
            raise ValueError("runtime tool result content must contain 1..8000 characters")
        if self.safe_code is not None and (not self.safe_code or len(self.safe_code) > 80):
            raise ValueError("runtime tool safe code is invalid")


@runtime_checkable
class RuntimeToolRegistry(Protocol):
    async def invoke(self, call: RuntimeToolCall) -> RuntimeToolResult: ...


@dataclass(frozen=True, slots=True)
class RuntimeThreadRequest:
    cwd: str
    tools: tuple[RuntimeToolDefinition, ...] = ()
    base_instructions: str | None = None
    ephemeral: bool = False

    def __post_init__(self) -> None:
        if not self.cwd:
            raise ValueError("runtime thread cwd is required")
        if self.base_instructions is not None and len(self.base_instructions) > 20_000:
            raise ValueError("runtime base instructions are too large")


@dataclass(frozen=True, slots=True)
class RuntimeThreadHandle:
    thread_id: str
    generation: int

    def __post_init__(self) -> None:
        if not self.thread_id or self.generation < 1:
            raise ValueError("runtime thread handle is invalid")


@dataclass(frozen=True, slots=True)
class RuntimeTurnRequest:
    thread: RuntimeThreadHandle
    input: tuple[RuntimeInput, ...]
    tools: RuntimeToolRegistry
    effort: Literal["low"] | None = None
    timeout_seconds: float | None = None
    max_visible_text_chars: int | None = None

    def __post_init__(self) -> None:
        if not self.input or len(self.input) > 20:
            raise ValueError("runtime turn requires 1..20 input items")
        if self.effort not in {None, "low"}:
            raise ValueError("runtime turn effort is invalid")
        if self.timeout_seconds is not None and not 0.1 <= self.timeout_seconds <= 3_600:
            raise ValueError("runtime turn timeout is invalid")
        if (
            self.max_visible_text_chars is not None
            and not 256 <= self.max_visible_text_chars <= 8_000_000
        ):
            raise ValueError("runtime turn visible text budget is invalid")

@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    kind: RuntimeEventKind
    thread_id: str
    turn_id: str | None = None
    item_id: str | None = None
    visible_text: str | None = None
    content_sha256: str | None = None
    safe_code: str | None = None
    terminal_status: RuntimeTerminalStatus | None = None
    tool_name: str | None = None
    input_sha256: str | None = None
    result_sha256: str | None = None
    item_type: str | None = None
    phase: str | None = None
    item_index: int | None = None
    source_sequence_start: int | None = None
    source_sequence_end: int | None = None
    source_delta_count: int = 1
    source_content_sha256: str | None = None
    projection_sequence: int | None = None
    sequence: int | None = None

    def __post_init__(self) -> None:
        if not self.thread_id:
            raise ValueError("runtime event thread id is required")
        if self.item_index is not None and self.item_index < 0:
            raise ValueError("runtime event item index must be non-negative")
        source_values = (self.source_sequence_start, self.source_sequence_end)
        if any(value is not None for value in source_values):
            if (
                self.source_sequence_start is None
                or self.source_sequence_end is None
                or self.source_sequence_start < 1
                or self.source_sequence_end < self.source_sequence_start
                or self.source_delta_count < 1
                or self.source_delta_count
                != self.source_sequence_end - self.source_sequence_start + 1
            ):
                raise ValueError("runtime event source range is invalid")
        elif self.source_delta_count != 1:
            raise ValueError("runtime event source count requires a source range")
        if self.projection_sequence is not None and self.projection_sequence < 1:
            raise ValueError("runtime event projection sequence is invalid")
        if self.sequence is not None and self.sequence < 1:
            raise ValueError("runtime event sequence is invalid")
        if (
            self.projection_sequence is not None
            and self.sequence is not None
            and self.projection_sequence != self.sequence
        ):
            raise ValueError("runtime event sequence must equal projection sequence")
        for value in (self.content_sha256, self.source_content_sha256):
            if value is not None and re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValueError("runtime event content hash is invalid")


@dataclass(frozen=True, slots=True)
class RuntimeTurnMetrics:
    raw_notification_count: int = 0
    source_event_count: int = 0
    source_delta_count: int = 0
    projection_event_count: int = 0
    coalesced_flush_count: int = 0
    maximum_pending_bytes: int = 0
    item_count: int = 0
    tool_count: int = 0
    visible_text_chars: int = 0
    duration_ms: int = 0
    flush_reasons: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class RuntimeTurnResult:
    thread: RuntimeThreadHandle
    turn_id: str
    terminal_status: RuntimeTerminalStatus
    events: tuple[RuntimeEvent, ...]
    safe_error_code: str | None = None
    metrics: RuntimeTurnMetrics = field(default_factory=RuntimeTurnMetrics)


@dataclass(frozen=True, slots=True)
class RuntimeHealthSnapshot:
    status: RuntimeHealthStatus
    generation: int
    version: str | None = None
    model: str | None = None
    model_provider: str | None = None
    safe_error_code: str | None = None
    unknown_notifications: int = 0
    metadata: Mapping[str, object] = field(default_factory=dict)


@runtime_checkable
class AgentRuntimePort(Protocol):
    async def start(self) -> RuntimeHealthSnapshot: ...
    async def health(self) -> RuntimeHealthSnapshot: ...
    async def start_thread(self, request: RuntimeThreadRequest) -> RuntimeThreadHandle: ...
    async def resume_thread(self, thread_id: str) -> RuntimeThreadHandle: ...
    async def compact_thread(self, thread: RuntimeThreadHandle) -> None: ...
    async def run_turn(self, request: RuntimeTurnRequest) -> RuntimeTurnResult: ...
    async def steer(self, thread: RuntimeThreadHandle, turn_id: str, input: tuple[RuntimeInput, ...]) -> None: ...
    async def interrupt(self, thread: RuntimeThreadHandle, turn_id: str) -> None: ...
    def events(self) -> AsyncIterator[RuntimeEvent]: ...
    async def shutdown(self) -> None: ...
