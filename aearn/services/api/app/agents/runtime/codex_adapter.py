"""Aearn-owned adapter from runtime contracts to Codex App Server wire methods."""
from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator, Mapping

from .codex_connection import JsonRpcError, JsonRpcNotification
from .codex_supervisor import CodexRuntimeSupervisor, RuntimeUnavailableError
from .contracts import AgentRuntimePort, RuntimeEvent, RuntimeEventKind, RuntimeHealthSnapshot, RuntimeInput, RuntimeTerminalStatus, RuntimeThreadHandle, RuntimeThreadRequest, RuntimeTurnRequest, RuntimeTurnResult


class RuntimeBusyError(RuntimeError):
    pass


class CodexAppServerRuntime(AgentRuntimePort):
    def __init__(self, supervisor: CodexRuntimeSupervisor, *, event_queue_size: int = 256) -> None:
        self.supervisor = supervisor
        self._turn_lock = asyncio.Lock()
        self._events: asyncio.Queue[RuntimeEvent] = asyncio.Queue(maxsize=event_queue_size)

    async def start(self) -> RuntimeHealthSnapshot:
        return await self.supervisor.start()

    async def health(self) -> RuntimeHealthSnapshot:
        return await self.supervisor.health()

    async def start_thread(self, request: RuntimeThreadRequest) -> RuntimeThreadHandle:
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
        health = await self.supervisor.start()
        if health.status.value != "ready":
            raise RuntimeUnavailableError(health.safe_error_code or "runtime_unavailable")
        result = await self.supervisor.request("thread/resume", {"threadId": thread_id, "model": self.supervisor.config.model, "modelProvider": self.supervisor.config.model_provider}, generation=health.generation)
        returned = str((result.get("thread") or {}).get("id", ""))
        if returned != thread_id:
            raise RuntimeUnavailableError("thread_resume_contract_mismatch")
        return RuntimeThreadHandle(thread_id, health.generation)

    async def run_turn(self, request: RuntimeTurnRequest) -> RuntimeTurnResult:
        if self._turn_lock.locked():
            raise RuntimeBusyError("runtime_writer_busy")
        async with self._turn_lock:
            self.supervisor.require_connection(request.thread.generation)
            self.supervisor.prepare_turn(request.thread.thread_id, request.tools, request.thread.generation)
            turn_id = ""
            collected: list[RuntimeEvent] = []
            terminal = RuntimeTerminalStatus.FAILED
            safe_error: str | None = None
            try:
                turn = await self.supervisor.request("turn/start", {"threadId": request.thread.thread_id, "input": [{"type": "text", "text": item.text} for item in request.input]}, generation=request.thread.generation)
                turn_id = str((turn.get("turn") or {}).get("id", ""))
                if not turn_id:
                    raise RuntimeUnavailableError("turn_start_contract_mismatch")
                self.supervisor.register_turn(request.thread.thread_id, turn_id, request.tools, request.thread.generation)
                while True:
                    notification = await self.supervisor.next_notification(generation=request.thread.generation, timeout_s=self.supervisor.config.turn_timeout_s)
                    event = _map_notification(notification, request.thread.thread_id, turn_id)
                    if event is None:
                        continue
                    if len(collected) >= 2_000:
                        raise RuntimeUnavailableError("runtime_event_budget_exhausted")
                    collected.append(event)
                    try:
                        self._events.put_nowait(event)
                    except asyncio.QueueFull as exc:
                        raise RuntimeUnavailableError("runtime_event_backpressure_exhausted") from exc
                    if event.kind is RuntimeEventKind.TURN_COMPLETED:
                        terminal = event.terminal_status or RuntimeTerminalStatus.FAILED
                        safe_error = event.safe_code
                        break
            except RuntimeUnavailableError as exc:
                terminal = RuntimeTerminalStatus.UNAVAILABLE
                safe_error = str(exc)
                failure_event = RuntimeEvent(RuntimeEventKind.TURN_COMPLETED, request.thread.thread_id, turn_id or None, terminal_status=terminal, safe_code=safe_error)
                collected.append(failure_event)
                if not self._events.full():
                    self._events.put_nowait(failure_event)
            except JsonRpcError:
                terminal = RuntimeTerminalStatus.UNAVAILABLE
                safe_error = "runtime_connection_failed"
                failure_event = RuntimeEvent(RuntimeEventKind.TURN_COMPLETED, request.thread.thread_id, turn_id or None, terminal_status=terminal, safe_code=safe_error)
                collected.append(failure_event)
                if not self._events.full():
                    self._events.put_nowait(failure_event)
            finally:
                self.supervisor.unregister_turn(request.thread.thread_id, turn_id)
            return RuntimeTurnResult(request.thread, turn_id, terminal, tuple(collected), safe_error)

    async def steer(self, thread: RuntimeThreadHandle, turn_id: str, input: tuple[RuntimeInput, ...]) -> None:
        await self.supervisor.request("turn/steer", {"threadId": thread.thread_id, "turnId": turn_id, "input": [{"type": "text", "text": item.text} for item in input]}, generation=thread.generation)

    async def interrupt(self, thread: RuntimeThreadHandle, turn_id: str) -> None:
        await self.supervisor.request("turn/interrupt", {"threadId": thread.thread_id, "turnId": turn_id}, generation=thread.generation)

    async def events(self) -> AsyncIterator[RuntimeEvent]:
        while True:
            yield await self._events.get()

    async def shutdown(self) -> None:
        await self.supervisor.shutdown()


def _tool_wire(tool: object) -> Mapping[str, object]:
    from .contracts import RuntimeToolDefinition
    if not isinstance(tool, RuntimeToolDefinition):
        raise TypeError("runtime tool definition is invalid")
    return {"name": tool.name, "description": tool.description, "inputSchema": dict(tool.input_schema)}


def _map_notification(notification: JsonRpcNotification, thread_id: str, turn_id: str) -> RuntimeEvent | None:
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
        return RuntimeEvent(RuntimeEventKind.MESSAGE_DELTA, thread_id, turn_id, item_id=str(params.get("itemId") or "") or None, visible_text=delta, content_sha256=_hash(delta))
    if method in {"item/started", "item/completed"}:
        if str(params.get("turnId", "")) != turn_id:
            return None
        item = params.get("item") or {}
        item_type = str(item.get("type", ""))
        item_id = str(item.get("id", "")) or None
        if item_type == "dynamicToolCall":
            kind = RuntimeEventKind.TOOL_STARTED if method == "item/started" else RuntimeEventKind.TOOL_COMPLETED
            return RuntimeEvent(kind, thread_id, turn_id, item_id=item_id, safe_code=str(item.get("status") or "") or None)
        if item_type == "agentMessage" and method == "item/completed":
            text = str(item.get("text", ""))
            return RuntimeEvent(RuntimeEventKind.MESSAGE_COMPLETED, thread_id, turn_id, item_id=item_id, visible_text=text, content_sha256=_hash(text))
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
