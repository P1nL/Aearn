"""Aearn-owned contracts for pluggable agent runtimes."""
from __future__ import annotations

import re
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

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
    MESSAGE_DELTA = "message_delta"
    MESSAGE_COMPLETED = "message_completed"
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

    def __post_init__(self) -> None:
        if not self.input or len(self.input) > 20:
            raise ValueError("runtime turn requires 1..20 input items")


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


@dataclass(frozen=True, slots=True)
class RuntimeTurnResult:
    thread: RuntimeThreadHandle
    turn_id: str
    terminal_status: RuntimeTerminalStatus
    events: tuple[RuntimeEvent, ...]
    safe_error_code: str | None = None


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
    async def run_turn(self, request: RuntimeTurnRequest) -> RuntimeTurnResult: ...
    async def steer(self, thread: RuntimeThreadHandle, turn_id: str, input: tuple[RuntimeInput, ...]) -> None: ...
    async def interrupt(self, thread: RuntimeThreadHandle, turn_id: str) -> None: ...
    def events(self) -> AsyncIterator[RuntimeEvent]: ...
    async def shutdown(self) -> None: ...
