"""Bounded coalescing for provider Runtime text deltas."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from enum import StrEnum

from .contracts import RuntimeEvent, RuntimeEventKind


class RuntimeDeltaFlushReason(StrEnum):
    BOUNDARY = "boundary"
    TIMER = "timer"
    SIZE_CHARS = "size_chars"
    SIZE_BYTES = "size_bytes"
    TERMINAL = "terminal"
    ERROR = "error"
    DISABLED = "disabled"


class RuntimeDeltaBudgetError(RuntimeError):
    """Safe bounded-stream failure without Runtime text."""

    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


@dataclass(frozen=True, slots=True)
class RuntimeDeltaCoalescingConfig:
    enabled: bool = True
    flush_delay_ms: int = 25
    flush_chars: int = 1_024
    flush_bytes: int = 4_096
    max_pending_bytes: int = 16_000

    def __post_init__(self) -> None:
        if not 1 <= self.flush_delay_ms <= 1_000:
            raise ValueError("runtime delta flush delay must be within 1..1000ms")
        if not 1 <= self.flush_chars <= 4_096:
            raise ValueError("runtime delta flush chars must be within 1..4096")
        if not 64 <= self.flush_bytes <= 16_000:
            raise ValueError("runtime delta flush bytes must be within 64..16000")
        if not self.flush_bytes <= self.max_pending_bytes <= 16_000:
            raise ValueError("runtime delta pending bytes must cover the flush threshold")


@dataclass(frozen=True, slots=True)
class RuntimeDeltaMetrics:
    source_delta_count: int
    projection_event_count: int
    coalesced_flush_count: int
    maximum_pending_bytes: int
    flush_reasons: tuple[tuple[str, int], ...]


@dataclass(slots=True)
class _PendingRuntimeDelta:
    event: RuntimeEvent
    text_parts: list[str]
    first_at: float
    last_at: float
    chars: int
    utf8_bytes: int
    source_sequence_start: int
    source_sequence_end: int
    source_delta_count: int


@dataclass(slots=True)
class RuntimeDeltaCoalescer:
    config: RuntimeDeltaCoalescingConfig
    _pending: _PendingRuntimeDelta | None = None
    _projection_sequence: int = 0
    _source_delta_count: int = 0
    _coalesced_flush_count: int = 0
    _maximum_pending_bytes: int = 0
    _flush_reasons: dict[str, int] = field(default_factory=dict)

    @property
    def pending_deadline(self) -> float | None:
        if self._pending is None:
            return None
        return self._pending.first_at + (self.config.flush_delay_ms / 1_000)

    def seconds_until_flush(self, now: float) -> float | None:
        deadline = self.pending_deadline
        if deadline is None:
            return None
        return max(0.0, deadline - now)

    def push(self, event: RuntimeEvent, *, now: float) -> tuple[RuntimeEvent, ...]:
        if not self.config.enabled or not _is_coalescible_delta(event):
            emitted = list(
                self.flush(
                    RuntimeDeltaFlushReason.DISABLED
                    if not self.config.enabled
                    else _boundary_flush_reason(event)
                )
            )
            emitted.append(self._project(event))
            return tuple(emitted)

        text = event.visible_text or ""
        utf8_bytes = len(text.encode("utf-8"))
        if utf8_bytes > self.config.max_pending_bytes:
            raise RuntimeDeltaBudgetError("runtime_pending_bytes_exhausted")
        self._source_delta_count += 1
        if self._pending is None:
            self._pending = _PendingRuntimeDelta(
                event=event,
                text_parts=[text],
                first_at=now,
                last_at=now,
                chars=len(text),
                utf8_bytes=utf8_bytes,
                source_sequence_start=_required_source_sequence(event),
                source_sequence_end=_required_source_sequence(event),
                source_delta_count=1,
            )
        elif _coalescing_key(self._pending.event) == _coalescing_key(event):
            next_bytes = self._pending.utf8_bytes + utf8_bytes
            if next_bytes > self.config.max_pending_bytes:
                raise RuntimeDeltaBudgetError("runtime_pending_bytes_exhausted")
            self._pending.text_parts.append(text)
            self._pending.last_at = now
            self._pending.chars += len(text)
            self._pending.utf8_bytes = next_bytes
            self._pending.source_sequence_end = _required_source_sequence(event)
            self._pending.source_delta_count += 1
        else:
            emitted = list(self.flush(RuntimeDeltaFlushReason.BOUNDARY))
            self._pending = _PendingRuntimeDelta(
                event=event,
                text_parts=[text],
                first_at=now,
                last_at=now,
                chars=len(text),
                utf8_bytes=utf8_bytes,
                source_sequence_start=_required_source_sequence(event),
                source_sequence_end=_required_source_sequence(event),
                source_delta_count=1,
            )
            self._maximum_pending_bytes = max(
                self._maximum_pending_bytes,
                self._pending.utf8_bytes,
            )
            if self._pending.chars >= self.config.flush_chars:
                emitted.extend(self.flush(RuntimeDeltaFlushReason.SIZE_CHARS))
            elif self._pending.utf8_bytes >= self.config.flush_bytes:
                emitted.extend(self.flush(RuntimeDeltaFlushReason.SIZE_BYTES))
            return tuple(emitted)

        self._maximum_pending_bytes = max(
            self._maximum_pending_bytes,
            self._pending.utf8_bytes,
        )
        if self._pending.chars >= self.config.flush_chars:
            return self.flush(RuntimeDeltaFlushReason.SIZE_CHARS)
        if self._pending.utf8_bytes >= self.config.flush_bytes:
            return self.flush(RuntimeDeltaFlushReason.SIZE_BYTES)
        return ()

    def flush_due(self, *, now: float) -> tuple[RuntimeEvent, ...]:
        deadline = self.pending_deadline
        if deadline is None or now < deadline:
            return ()
        return self.flush(RuntimeDeltaFlushReason.TIMER)

    def flush(self, reason: RuntimeDeltaFlushReason) -> tuple[RuntimeEvent, ...]:
        pending = self._pending
        if pending is None:
            return ()
        self._pending = None
        text = "".join(pending.text_parts)
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self._coalesced_flush_count += 1
        self._flush_reasons[reason.value] = self._flush_reasons.get(reason.value, 0) + 1
        event = replace(
            pending.event,
            visible_text=text,
            content_sha256=content_hash,
            source_sequence_start=pending.source_sequence_start,
            source_sequence_end=pending.source_sequence_end,
            source_delta_count=pending.source_delta_count,
            source_content_sha256=content_hash,
        )
        return (self._project(event),)

    def metrics(self) -> RuntimeDeltaMetrics:
        return RuntimeDeltaMetrics(
            source_delta_count=self._source_delta_count,
            projection_event_count=self._projection_sequence,
            coalesced_flush_count=self._coalesced_flush_count,
            maximum_pending_bytes=self._maximum_pending_bytes,
            flush_reasons=tuple(sorted(self._flush_reasons.items())),
        )

    def _project(self, event: RuntimeEvent) -> RuntimeEvent:
        self._projection_sequence += 1
        return replace(
            event,
            sequence=self._projection_sequence,
            projection_sequence=self._projection_sequence,
        )


def _is_coalescible_delta(event: RuntimeEvent) -> bool:
    return (
        event.kind in {RuntimeEventKind.REASONING_DELTA, RuntimeEventKind.MESSAGE_DELTA}
        and event.visible_text is not None
        and event.source_sequence_start is not None
        and event.source_sequence_start == event.source_sequence_end
        and event.source_delta_count == 1
    )


def _required_source_sequence(event: RuntimeEvent) -> int:
    value = event.source_sequence_start
    if value is None or value < 1:
        raise ValueError("runtime source sequence is required before coalescing")
    return value


def _coalescing_key(event: RuntimeEvent) -> tuple[object, ...]:
    channel = (
        "reasoning"
        if event.kind is RuntimeEventKind.REASONING_DELTA
        else "final_answer"
    )
    return (
        event.thread_id,
        event.turn_id,
        event.item_id,
        event.kind,
        channel,
        event.item_index,
        event.phase,
    )


def _boundary_flush_reason(event: RuntimeEvent) -> RuntimeDeltaFlushReason:
    if event.kind is RuntimeEventKind.TURN_COMPLETED:
        return RuntimeDeltaFlushReason.TERMINAL
    return RuntimeDeltaFlushReason.BOUNDARY
