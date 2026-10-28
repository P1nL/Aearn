"""Aearn-owned adapter from runtime contracts to Codex App Server wire methods."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import AsyncIterator, Mapping
from dataclasses import replace

from app.core.safe_diagnostics import log_safe_event, safe_diagnostic_identifier

from .codex_connection import JsonRpcError, JsonRpcNotification, JsonRpcTimeoutError
from .codex_supervisor import CodexRuntimeSupervisor, RuntimeUnavailableError
from .contracts import AgentRuntimePort, RuntimeEvent, RuntimeEventKind, RuntimeHealthSnapshot, RuntimeHealthStatus, RuntimeInput, RuntimeTerminalStatus, RuntimeThreadHandle, RuntimeThreadRequest, RuntimeToolCall, RuntimeToolRegistry, RuntimeToolResult, RuntimeTurnMetrics, RuntimeTurnRequest, RuntimeTurnResult
from .delta_coalescer import (
    RuntimeDeltaBudgetError,
    RuntimeDeltaCoalescer,
    RuntimeDeltaCoalescingConfig,
    RuntimeDeltaFlushReason,
)

_TOOL_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_EVENT_BACKPRESSURE_TIMEOUT_SECONDS = 1.0
_TURN_STOP_TIMEOUT_SECONDS = 3.0
_OWNED_SHUTDOWN_TIMEOUT_SECONDS = 6.0
_NOTIFICATION_POLL_SECONDS = 0.25
logger = logging.getLogger(__name__)


class _TurnToolGuard:
    """Turn-local fatal signal and callback fence, including pre-register callbacks."""

    def __init__(self, tools: RuntimeToolRegistry) -> None:
        self.tools = tools
        self.fatal: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self.closed = False
        self._lock = asyncio.Lock()

    async def invoke(self, call: RuntimeToolCall) -> RuntimeToolResult:
        async with self._lock:
            if self.closed or self.fatal.done():
                return RuntimeToolResult(False, '{"status":"fatal"}', "runtime_tool_stopped")
            try:
                result = await self.tools.invoke(call)
            except Exception:
                result = RuntimeToolResult(False, '{"status":"fatal"}', "runtime_tool_failed")
            if not result.success:
                self.fatal.set_result(result.safe_code or "runtime_tool_failed")
            return result


class _RuntimeEventSubscription(AsyncIterator[RuntimeEvent]):
    def __init__(
        self,
        subscribers: set[asyncio.Queue[RuntimeEvent]],
        *,
        queue_size: int,
    ) -> None:
        self._subscribers = subscribers
        self._queue: asyncio.Queue[RuntimeEvent] = asyncio.Queue(maxsize=queue_size)
        self._closed = False
        subscribers.add(self._queue)

    def __aiter__(self) -> _RuntimeEventSubscription:
        return self

    async def __anext__(self) -> RuntimeEvent:
        if self._closed:
            raise StopAsyncIteration
        return await self._queue.get()

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._subscribers.discard(self._queue)


class RuntimeBusyError(RuntimeError):
    pass


class CodexAppServerRuntime(AgentRuntimePort):
    def __init__(self, supervisor: CodexRuntimeSupervisor, *, event_queue_size: int = 256) -> None:
        self.supervisor = supervisor
        self._turn_lock = asyncio.Lock()
        self._event_queue_size = event_queue_size
        self._event_subscribers: set[asyncio.Queue[RuntimeEvent]] = set()
        self._reuse_blocked = False

    def _require_reusable(self) -> None:
        if self._reuse_blocked:
            raise RuntimeUnavailableError("runtime_stop_unconfirmed")

    async def start(self) -> RuntimeHealthSnapshot:
        self._require_reusable()
        return await self.supervisor.start()

    async def health(self) -> RuntimeHealthSnapshot:
        if self._reuse_blocked:
            snapshot = await self.supervisor.health()
            return replace(snapshot, status=RuntimeHealthStatus.UNAVAILABLE,
                           safe_error_code="runtime_stop_unconfirmed")
        return await self.supervisor.health()

    async def start_thread(self, request: RuntimeThreadRequest) -> RuntimeThreadHandle:
        self._require_reusable()
        health = await self.supervisor.start()
        if health.status.value != "ready":
            raise RuntimeUnavailableError(health.safe_error_code or "runtime_unavailable")
        params: dict[str, object] = {"model": self.supervisor.config.model, "modelProvider": self.supervisor.config.model_provider, "cwd": request.cwd, "approvalPolicy": "never", "sandbox": "read-only", "ephemeral": request.ephemeral, "serviceName": "aearn_runtime_adapter", "dynamicTools": [_tool_wire(tool) for tool in request.tools]}
        if request.base_instructions is not None:
            params["baseInstructions"] = request.base_instructions
        result = await self.supervisor.request("thread/start", params, generation=health.generation)
        thread_id = str((result.get("thread") or {}).get("id", ""))
        if not thread_id or result.get("model") != self.supervisor.config.model or result.get("modelProvider") != self.supervisor.config.model_provider:
            raise RuntimeUnavailableError("thread_start_contract_mismatch")
        return RuntimeThreadHandle(thread_id, health.generation)

    async def resume_thread(self, thread_id: str) -> RuntimeThreadHandle:
        self._require_reusable()
        health = await self.supervisor.start()
        if health.status.value != "ready":
            raise RuntimeUnavailableError(health.safe_error_code or "runtime_unavailable")
        result = await self.supervisor.request("thread/resume", {"threadId": thread_id, "model": self.supervisor.config.model, "modelProvider": self.supervisor.config.model_provider}, generation=health.generation)
        returned = str((result.get("thread") or {}).get("id", ""))
        if returned != thread_id:
            raise RuntimeUnavailableError("thread_resume_contract_mismatch")
        return RuntimeThreadHandle(thread_id, health.generation)

    async def compact_thread(self, thread: RuntimeThreadHandle) -> None:
        self._require_reusable()
        await self.supervisor.request(
            "thread/compact/start",
            {"threadId": thread.thread_id},
            generation=thread.generation,
        )

    async def run_turn(self, request: RuntimeTurnRequest) -> RuntimeTurnResult:
        if self._turn_lock.locked():
            raise RuntimeBusyError("runtime_writer_busy")
        async with self._turn_lock:
            self._require_reusable()
            if request.completion_driven and not self.supervisor.config.completion_driven_enabled:
                raise RuntimeUnavailableError("runtime_completion_profile_disabled")
            self.supervisor.require_connection(request.thread.generation)
            guarded_tools = _TurnToolGuard(request.tools)
            self.supervisor.prepare_turn(
                request.thread.thread_id, guarded_tools, request.thread.generation
            )
            turn_id = ""
            collected: list[RuntimeEvent] = []
            item_phases: dict[str, str] = {}
            terminal = RuntimeTerminalStatus.FAILED
            safe_error: str | None = None
            raw_notification_count = 0
            source_sequence = 0
            source_delta_count = 0
            visible_text_chars = 0
            message_text_chars = 0
            reasoning_text_chars = 0
            terminal_observed = False
            termination_reason = "natural_terminal"
            cleanup_cancelled = False
            item_ids: set[str] = set()
            tool_ids: set[str] = set()
            text_lengths: dict[tuple[str | None, str], int] = {}
            loop = asyncio.get_running_loop()
            started_at = loop.time()
            turn_timeout = self.supervisor.config.turn_timeout_s
            if request.completion_driven:
                turn_timeout = self.supervisor.config.completion_turn_timeout_s
            if request.timeout_seconds is not None:
                turn_timeout = min(turn_timeout, request.timeout_seconds)
            turn_deadline = started_at + turn_timeout
            visible_text_limit = self.supervisor.config.max_visible_text_chars
            if request.max_visible_text_chars is not None:
                visible_text_limit = min(
                    visible_text_limit,
                    request.max_visible_text_chars,
                )
            split_text_budget = request.max_reasoning_text_chars is not None
            total_text_limit = (
                self.supervisor.config.max_visible_text_chars
                if split_text_budget else visible_text_limit
            )
            reasoning_text_limit = min(
                total_text_limit, request.max_reasoning_text_chars or total_text_limit
            )
            notification_task: asyncio.Task[JsonRpcNotification] | None = None
            coalescer = RuntimeDeltaCoalescer(
                RuntimeDeltaCoalescingConfig(
                    enabled=self.supervisor.config.delta_coalescing_enabled,
                    flush_delay_ms=self.supervisor.config.delta_flush_delay_ms,
                    flush_chars=self.supervisor.config.delta_flush_chars,
                    flush_bytes=self.supervisor.config.delta_flush_bytes,
                    max_pending_bytes=self.supervisor.config.max_pending_bytes,
                )
            )

            async def publish(events: tuple[RuntimeEvent, ...]) -> bool:
                nonlocal terminal, safe_error
                for projected in events:
                    collected.append(projected)
                    await self._publish_event(projected)
                    if projected.kind is RuntimeEventKind.TURN_COMPLETED:
                        terminal = (
                            projected.terminal_status or RuntimeTerminalStatus.FAILED
                        )
                        safe_error = projected.safe_code
                        return True
                return False

            try:
                turn_params: dict[str, object] = {
                    "threadId": request.thread.thread_id,
                    "input": [
                        {"type": "text", "text": item.text}
                        for item in request.input
                    ],
                }
                if request.effort is not None:
                    turn_params["effort"] = request.effort
                async with asyncio.timeout(turn_timeout):
                    turn = await self.supervisor.request(
                        "turn/start",
                        turn_params,
                        generation=request.thread.generation,
                        timeout_s=min(turn_timeout, self.supervisor.config.request_timeout_s),
                    )
                turn_id = str((turn.get("turn") or {}).get("id", ""))
                if not turn_id:
                    raise RuntimeUnavailableError("turn_start_contract_mismatch")
                self.supervisor.register_turn(
                    request.thread.thread_id,
                    turn_id,
                    guarded_tools,
                    request.thread.generation,
                )
                while True:
                    if guarded_tools.fatal.done():
                        raise RuntimeUnavailableError(guarded_tools.fatal.result())
                    now = loop.time()
                    remaining = turn_deadline - now
                    if remaining <= 0:
                        raise RuntimeUnavailableError("runtime_turn_time_exhausted")
                    if notification_task is None:
                        notification_task = asyncio.create_task(
                            self.supervisor.next_notification(
                                generation=request.thread.generation,
                                timeout_s=min(remaining, _NOTIFICATION_POLL_SECONDS),
                            )
                        )
                    flush_wait = coalescer.seconds_until_flush(now)
                    wait_timeout = remaining if flush_wait is None else min(remaining, flush_wait)
                    waiters: set[asyncio.Future[JsonRpcNotification] | asyncio.Future[str]] = {
                        notification_task, guarded_tools.fatal,
                    }
                    done, _pending = await asyncio.wait(
                        waiters,
                        timeout=wait_timeout,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if guarded_tools.fatal in done:
                        raise RuntimeUnavailableError(guarded_tools.fatal.result())
                    if notification_task not in done:
                        if await publish(coalescer.flush_due(now=loop.time())):
                            break
                        continue
                    try:
                        notification = notification_task.result()
                    except JsonRpcTimeoutError as exc:
                        if loop.time() >= turn_deadline:
                            raise RuntimeUnavailableError(
                                "runtime_turn_time_exhausted"
                            ) from exc
                        continue
                    finally:
                        notification_task = None

                    raw_notification_count += 1
                    if raw_notification_count > self.supervisor.config.max_raw_notifications:
                        raise RuntimeUnavailableError("runtime_raw_notification_runaway")
                    event = _map_notification(
                        notification,
                        request.thread.thread_id,
                        turn_id,
                        item_phases=item_phases,
                    )
                    if notification.method in {"turn/completed", "item/completed"}:
                        log_safe_event(
                            logger, "codex_terminal_notification", level=logging.INFO,
                            action_category=("turn_completed" if notification.method == "turn/completed" else "item_completed"),
                            state="accepted" if event is not None else "filtered",
                            action_identifier=safe_diagnostic_identifier(turn_id, trusted=False),
                            runtime_generation=request.thread.generation,
                            raw_notification_count=raw_notification_count,
                            duration_ms=max(0, round((turn_timeout - remaining) * 1000)),
                        )
                    if event is None:
                        continue
                    if event.kind is RuntimeEventKind.TURN_COMPLETED:
                        terminal_observed = True
                    source_sequence += 1
                    source_hash = _source_event_hash(event)
                    event = replace(
                        event,
                        source_sequence_start=source_sequence,
                        source_sequence_end=source_sequence,
                        source_delta_count=1,
                        source_content_sha256=source_hash,
                    )
                    if event.item_id is not None:
                        item_ids.add(event.item_id)
                        if len(item_ids) > self.supervisor.config.max_items:
                            raise RuntimeUnavailableError("runtime_item_budget_exhausted")
                    text_increment = 0
                    text_channel = (
                        "message" if event.item_type == "agentMessage" else
                        "summary" if event.kind is RuntimeEventKind.REASONING_SUMMARY_DELTA
                        else "reasoning"
                    )
                    text_key = (event.item_id, text_channel)
                    if event.kind in {
                        RuntimeEventKind.TOOL_STARTED,
                        RuntimeEventKind.TOOL_COMPLETED,
                    }:
                        tool_ids.add(event.item_id or f"source:{source_sequence}")
                        if len(tool_ids) > self.supervisor.config.max_tools:
                            raise RuntimeUnavailableError("runtime_tool_budget_exhausted")
                    if event.kind in {
                        RuntimeEventKind.REASONING_DELTA,
                        RuntimeEventKind.REASONING_SUMMARY_DELTA,
                        RuntimeEventKind.MESSAGE_DELTA,
                    }:
                        source_delta_count += 1
                        text_increment = len(event.visible_text or "")
                        text_lengths[text_key] = text_lengths.get(text_key, 0) + text_increment
                    elif (
                        event.kind
                        in {
                            RuntimeEventKind.REASONING_COMPLETED,
                            RuntimeEventKind.MESSAGE_COMPLETED,
                        }
                    ):
                        # Completed content calibrates missing suffixes, never charges
                        # delta+completed twice or refunds previously generated text.
                        text_increment = max(
                            0, len(event.visible_text or "") - text_lengths.get(text_key, 0)
                        )
                        text_lengths[text_key] = text_lengths.get(text_key, 0) + text_increment
                    visible_text_chars += text_increment
                    if text_channel == "message":
                        message_text_chars += text_increment
                    else:
                        reasoning_text_chars += text_increment
                    if visible_text_chars > total_text_limit or (
                        split_text_budget and (
                            message_text_chars > visible_text_limit
                            or reasoning_text_chars > reasoning_text_limit
                        )
                    ):
                        raise RuntimeUnavailableError("runtime_text_budget_exhausted")
                    if await publish(coalescer.push(event, now=loop.time())):
                        break
            except (RuntimeUnavailableError, RuntimeDeltaBudgetError, TimeoutError) as exc:
                terminal = RuntimeTerminalStatus.UNAVAILABLE
                safe_error = "runtime_turn_time_exhausted" if isinstance(exc, TimeoutError) else str(exc)
                if guarded_tools.fatal.done() and guarded_tools.fatal.result() == safe_error:
                    terminal = RuntimeTerminalStatus.FAILED
                guarded_tools.closed = True
                if not terminal_observed:
                    termination_reason, cleanup_cancelled = await self._stop_turn(request.thread, turn_id, notification_task)
                for pending_event in coalescer.flush(RuntimeDeltaFlushReason.ERROR):
                    collected.append(pending_event)
                    self._publish_event_best_effort(pending_event)
                failure_event = RuntimeEvent(
                    RuntimeEventKind.TURN_COMPLETED,
                    request.thread.thread_id,
                    turn_id or None,
                    terminal_status=terminal,
                    safe_code=safe_error,
                )
                for projected in coalescer.push(failure_event, now=loop.time()):
                    collected.append(projected)
                    self._publish_event_best_effort(projected)
            except JsonRpcError:
                terminal = RuntimeTerminalStatus.UNAVAILABLE
                safe_error = "runtime_connection_failed"
                guarded_tools.closed = True
                if not terminal_observed:
                    termination_reason, cleanup_cancelled = await self._stop_turn(request.thread, turn_id, notification_task)
                for pending_event in coalescer.flush(RuntimeDeltaFlushReason.ERROR):
                    collected.append(pending_event)
                    self._publish_event_best_effort(pending_event)
                failure_event = RuntimeEvent(
                    RuntimeEventKind.TURN_COMPLETED,
                    request.thread.thread_id,
                    turn_id or None,
                    terminal_status=terminal,
                    safe_code=safe_error,
                )
                for projected in coalescer.push(failure_event, now=loop.time()):
                    collected.append(projected)
                    self._publish_event_best_effort(projected)
            except asyncio.CancelledError:
                safe_error = "runtime_turn_cancelled"
                raise
            finally:
                guarded_tools.closed = True
                # Cancellation (including external worker cancellation) must not
                # release ownership while generation may still be active.
                if not terminal_observed and termination_reason == "natural_terminal":
                    termination_reason, cleanup_cancelled = await self._stop_turn(request.thread, turn_id, notification_task)
                if notification_task is not None:
                    await asyncio.gather(notification_task, return_exceptions=True)
                self.supervisor.unregister_turn(request.thread.thread_id, turn_id)
                if not guarded_tools.fatal.done():
                    guarded_tools.fatal.cancel()
                log_safe_event(
                    logger, "codex_runtime_turn_budget", level=logging.INFO,
                    code=safe_error, termination_reason=termination_reason,
                    action_identifier=safe_diagnostic_identifier(turn_id or request.thread.thread_id, trusted=False),
                    runtime_generation=request.thread.generation,
                    visible_chars=message_text_chars, reasoning_chars=reasoning_text_chars,
                    total_text_chars=visible_text_chars,
                    effective_max_visible_chars=visible_text_limit,
                    effective_max_reasoning_chars=reasoning_text_limit,
                    effective_max_total_chars=total_text_limit,
                    effective_timeout_seconds=turn_timeout,
                    raw_notification_count=raw_notification_count,
                    source_delta_count=source_delta_count,
                    projection_event_count=len(collected),
                    item_count=len(item_ids), tool_count=len(tool_ids),
                    duration_ms=max(0, round((loop.time() - started_at) * 1_000)),
                )
                if cleanup_cancelled:
                    raise asyncio.CancelledError

            coalescing = coalescer.metrics()
            metrics = RuntimeTurnMetrics(
                raw_notification_count=raw_notification_count,
                source_event_count=source_sequence,
                source_delta_count=source_delta_count,
                projection_event_count=len(collected),
                coalesced_flush_count=coalescing.coalesced_flush_count,
                maximum_pending_bytes=coalescing.maximum_pending_bytes,
                item_count=len(item_ids),
                tool_count=len(tool_ids),
                visible_text_chars=visible_text_chars,
                duration_ms=max(0, round((loop.time() - started_at) * 1_000)),
                flush_reasons=coalescing.flush_reasons,
                message_text_chars=message_text_chars,
                reasoning_text_chars=reasoning_text_chars,
                effective_max_visible_text_chars=visible_text_limit,
                effective_max_reasoning_text_chars=reasoning_text_limit,
                effective_max_total_text_chars=total_text_limit,
                effective_timeout_seconds=turn_timeout,
                termination_reason=termination_reason,
            )
            return RuntimeTurnResult(
                request.thread,
                turn_id,
                terminal,
                tuple(collected),
                safe_error,
                metrics,
            )

    async def _stop_turn(
        self, thread: RuntimeThreadHandle, turn_id: str,
        notification_task: asyncio.Task[JsonRpcNotification] | None,
    ) -> tuple[str, bool]:
        """ACK is not terminal evidence. Fence callbacks before this bounded drain."""
        async def stop() -> str:
            try:
                if not turn_id:
                    raise RuntimeUnavailableError("runtime_stop_turn_unknown")
                deadline = asyncio.get_running_loop().time() + _TURN_STOP_TIMEOUT_SECONDS
                async with asyncio.timeout(_TURN_STOP_TIMEOUT_SECONDS):
                    await self.supervisor.request(
                        "turn/interrupt", {"threadId": thread.thread_id, "turnId": turn_id},
                        generation=thread.generation, timeout_s=_TURN_STOP_TIMEOUT_SECONDS,
                    )
                pending = notification_task
                while asyncio.get_running_loop().time() < deadline:
                    try:
                        if pending is not None:
                            notification = await asyncio.shield(pending)
                            pending = None
                        else:
                            notification = await self.supervisor.next_notification(
                                generation=thread.generation, timeout_s=_NOTIFICATION_POLL_SECONDS,
                            )
                    except JsonRpcTimeoutError:
                        pending = None
                        continue
                    event = _map_notification(notification, thread.thread_id, turn_id)
                    if (
                        notification.params.get("threadId") == thread.thread_id
                        and event is not None
                        and event.kind is RuntimeEventKind.TURN_COMPLETED
                        and (notification.params.get("turn") or {}).get("status")
                        in {"completed", "interrupted", "failed"}
                    ):
                        return "interrupt_terminal_confirmed"
            except (Exception, asyncio.CancelledError):
                pass
            # Unknown start ID, failed interrupt, ACK-only, or broken connection:
            # stop only this supervisor's owned process, never reuse uncertain state.
            self._reuse_blocked = True
            try:
                async with asyncio.timeout(_OWNED_SHUTDOWN_TIMEOUT_SECONDS):
                    await self.supervisor.shutdown()
                self._reuse_blocked = False
                return "owned_runtime_stopped"
            except (Exception, asyncio.CancelledError):
                return "runtime_reuse_blocked"

        cleanup = asyncio.create_task(stop())
        cancelled = False
        # A second cancellation cannot detach cleanup and release the turn lock.
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                cancelled = True
        return cleanup.result(), cancelled

    async def steer(self, thread: RuntimeThreadHandle, turn_id: str, input: tuple[RuntimeInput, ...]) -> None:
        self._require_reusable()
        await self.supervisor.request("turn/steer", {"threadId": thread.thread_id, "turnId": turn_id, "input": [{"type": "text", "text": item.text} for item in input]}, generation=thread.generation)

    async def interrupt(self, thread: RuntimeThreadHandle, turn_id: str) -> None:
        self._require_reusable()
        await self.supervisor.request("turn/interrupt", {"threadId": thread.thread_id, "turnId": turn_id}, generation=thread.generation)

    def events(self) -> AsyncIterator[RuntimeEvent]:
        return _RuntimeEventSubscription(
            self._event_subscribers,
            queue_size=self._event_queue_size,
        )

    async def _publish_event(self, event: RuntimeEvent) -> None:
        for queue in tuple(self._event_subscribers):
            try:
                await asyncio.wait_for(
                    queue.put(event),
                    timeout=_EVENT_BACKPRESSURE_TIMEOUT_SECONDS,
                )
            except TimeoutError as exc:
                raise RuntimeUnavailableError("runtime_event_backpressure_exhausted") from exc

    def _publish_event_best_effort(self, event: RuntimeEvent) -> None:
        for queue in tuple(self._event_subscribers):
            if not queue.full():
                queue.put_nowait(event)

    async def shutdown(self) -> None:
        await self.supervisor.shutdown()
        # A previous incomplete close may be idempotently acknowledged on retry.
        # That is not new stop evidence: poisoned adapters require host recreation.


def _tool_wire(tool: object) -> Mapping[str, object]:
    from .contracts import RuntimeToolDefinition
    if not isinstance(tool, RuntimeToolDefinition):
        raise TypeError("runtime tool definition is invalid")
    return {"name": tool.name, "description": tool.description, "inputSchema": dict(tool.input_schema)}


def _map_notification(
    notification: JsonRpcNotification,
    thread_id: str,
    turn_id: str,
    *,
    item_phases: dict[str, str] | None = None,
) -> RuntimeEvent | None:
    params = notification.params
    method = notification.method
    notification_thread = str(params.get("threadId") or thread_id)
    if notification_thread != thread_id:
        return None
    if method == "turn/started":
        wire_turn = params.get("turn") or {}
        if str(wire_turn.get("id", "")) != turn_id:
            return None
        return RuntimeEvent(RuntimeEventKind.TURN_STARTED, thread_id, turn_id)
    if method == "item/agentMessage/delta":
        if str(params.get("turnId", "")) != turn_id:
            return None
        delta = str(params.get("delta", ""))
        item_id = str(params.get("itemId") or "") or None
        phase = str(params.get("phase") or "") or None
        if phase is None and item_id is not None and item_phases is not None:
            phase = item_phases.get(item_id)
        return RuntimeEvent(
            RuntimeEventKind.MESSAGE_DELTA,
            thread_id,
            turn_id,
            item_id=item_id,
            visible_text=delta,
            content_sha256=_hash(delta),
            item_type="agentMessage",
            phase=phase,
            item_index=_optional_nonnegative_int(params.get("index")),
        )
    if method in {"item/reasoning/textDelta", "item/reasoning/summaryTextDelta"}:
        if str(params.get("turnId", "")) != turn_id:
            return None
        delta = str(params.get("delta", ""))
        kind = (
            RuntimeEventKind.REASONING_DELTA
            if method == "item/reasoning/textDelta"
            else RuntimeEventKind.REASONING_SUMMARY_DELTA
        )
        return RuntimeEvent(
            kind,
            thread_id,
            turn_id,
            item_id=str(params.get("itemId") or "") or None,
            visible_text=delta,
            content_sha256=_hash(delta),
            item_type="reasoning",
            item_index=_optional_nonnegative_int(params.get("index")),
        )
    if method in {"item/started", "item/completed"}:
        if str(params.get("turnId", "")) != turn_id:
            return None
        item = params.get("item") or {}
        item_type = str(item.get("type", ""))
        item_id = str(item.get("id", "")) or None
        if item_type == "reasoning":
            if method == "item/started":
                return RuntimeEvent(RuntimeEventKind.REASONING_STARTED, thread_id, turn_id, item_id=item_id, item_type=item_type)
            raw_text = item.get("text")
            text = raw_text if isinstance(raw_text, str) else None
            return RuntimeEvent(
                RuntimeEventKind.REASONING_COMPLETED,
                thread_id,
                turn_id,
                item_id=item_id,
                visible_text=text,
                content_sha256=_hash(text) if text is not None else None,
                item_type=item_type,
                item_index=_optional_nonnegative_int(item.get("index")),
            )
        if item_type == "contextCompaction":
            return RuntimeEvent(
                RuntimeEventKind.CONTEXT_COMPACTION_STARTED if method == "item/started" else RuntimeEventKind.CONTEXT_COMPACTION_COMPLETED,
                thread_id,
                turn_id,
                item_id=item_id,
                item_type=item_type,
                safe_code="local",
                item_index=_optional_nonnegative_int(item.get("index")),
            )
        if item_type == "agentMessage" and method == "item/started":
            phase = str(item.get("phase") or "") or None
            if item_id is not None and phase is not None and item_phases is not None:
                item_phases[item_id] = phase
            return RuntimeEvent(
                RuntimeEventKind.MESSAGE_STARTED,
                thread_id,
                turn_id,
                item_id=item_id,
                item_type=item_type,
                phase=phase,
                item_index=_optional_nonnegative_int(item.get("index")),
            )
        if item_type == "dynamicToolCall":
            kind = RuntimeEventKind.TOOL_STARTED if method == "item/started" else RuntimeEventKind.TOOL_COMPLETED
            return RuntimeEvent(
                kind,
                thread_id,
                turn_id,
                item_id=item_id,
                safe_code=str(item.get("status") or "") or None,
                tool_name=_safe_tool_name(item.get("tool") or item.get("name")),
                input_sha256=_hash_json(item.get("arguments")),
                result_sha256=(
                    _hash_json(item.get("result") if item.get("result") is not None else item.get("content"))
                    if method == "item/completed"
                    else None
                ),
                item_index=_optional_nonnegative_int(item.get("index")),
            )
        if item_type == "agentMessage" and method == "item/completed":
            phase = str(item.get("phase") or "") or None
            if phase is None and item_id is not None and item_phases is not None:
                phase = item_phases.get(item_id)
            raw_text = item.get("text")
            text = raw_text if isinstance(raw_text, str) else None
            return RuntimeEvent(
                RuntimeEventKind.MESSAGE_COMPLETED,
                thread_id,
                turn_id,
                item_id=item_id,
                visible_text=text,
                content_sha256=_hash(text) if text is not None else None,
                item_type=item_type,
                phase=phase,
                item_index=_optional_nonnegative_int(item.get("index")),
            )
        return None
    if method == "turn/completed":
        wire_turn = params.get("turn") or {}
        if str(wire_turn.get("id", "")) != turn_id:
            return None
        status = str(wire_turn.get("status", "failed"))
        terminal = {"completed": RuntimeTerminalStatus.COMPLETED, "interrupted": RuntimeTerminalStatus.INTERRUPTED, "failed": RuntimeTerminalStatus.FAILED}.get(status, RuntimeTerminalStatus.FAILED)
        error = wire_turn.get("error")
        code = str(error.get("code")) if isinstance(error, dict) and error.get("code") else None
        return RuntimeEvent(RuntimeEventKind.TURN_COMPLETED, thread_id, turn_id, terminal_status=terminal, safe_code=code)
    if method == "warning":
        return RuntimeEvent(RuntimeEventKind.WARNING, thread_id, turn_id, safe_code="runtime_warning")
    return None


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_json(value: object) -> str | None:
    if value is None:
        return None
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _source_event_hash(event: RuntimeEvent) -> str:
    safe = {
        "kind": event.kind.value,
        "thread": hashlib.sha256(event.thread_id.encode("utf-8")).hexdigest(),
        "turn": _hash(event.turn_id) if event.turn_id else None,
        "item": _hash(event.item_id) if event.item_id else None,
        "content": event.content_sha256,
        "code": event.safe_code,
        "terminal": (
            event.terminal_status.value if event.terminal_status is not None else None
        ),
        "tool": event.tool_name,
        "input": event.input_sha256,
        "result": event.result_sha256,
        "item_type": event.item_type,
        "phase": event.phase,
        "index": event.item_index,
    }
    encoded = json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _optional_nonnegative_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _safe_tool_name(value: object) -> str | None:
    name = str(value or "")
    return name if _TOOL_NAME.fullmatch(name) is not None else None
