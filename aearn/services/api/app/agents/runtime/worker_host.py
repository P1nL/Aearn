"""Process-local owner used only by the dedicated tutor-codex Celery worker."""
from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from collections.abc import AsyncIterator, Callable
from concurrent.futures import Future
from typing import Any, Coroutine, TypeVar, cast

from app.core.config import get_settings

from .codex_adapter import CodexAppServerRuntime
from .codex_config import CodexRuntimeConfig
from .codex_supervisor import CodexRuntimeSupervisor
from .contracts import (
    AgentRuntimePort,
    RuntimeEvent,
    RuntimeEventKind,
    RuntimeHealthSnapshot,
    RuntimeInput,
    RuntimeTerminalStatus,
    RuntimeThreadHandle,
    RuntimeThreadRequest,
    RuntimeTurnRequest,
    RuntimeTurnResult,
)

RuntimeFactory = Callable[[], AgentRuntimePort]
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RuntimeTurnControlDirective:
    input_revision: int
    steer_input: tuple[RuntimeInput, ...] = ()
    interrupt: bool = False


RuntimeControlReader = Callable[[str, int], RuntimeTurnControlDirective]
RuntimeEventObserver = Callable[[RuntimeEvent, int], None]


class CodexRuntimeWorkerHost:
    def __init__(self, *, runtime_factory: RuntimeFactory | None = None) -> None:
        self._runtime_factory = runtime_factory or _default_runtime_factory
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._runtime: AgentRuntimePort | None = None
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._last_generation = 0

    def health(self, *, timeout_s: float = 20.0) -> dict[str, object]:
        snapshot = self.health_snapshot(timeout_s=timeout_s)
        return _health_payload(snapshot)

    def health_snapshot(self, *, timeout_s: float = 20.0) -> RuntimeHealthSnapshot:
        self._ensure_started(timeout_s=timeout_s)
        snapshot: RuntimeHealthSnapshot = self._submit(lambda runtime: runtime.start(), timeout_s=timeout_s)
        if not isinstance(snapshot, RuntimeHealthSnapshot):
            raise TypeError("Codex worker health returned an unexpected result")
        with self._lock:
            self._last_generation = snapshot.generation
        return snapshot

    def start_thread(
        self,
        request: RuntimeThreadRequest,
        *,
        timeout_s: float = 30.0,
    ) -> RuntimeThreadHandle:
        self._ensure_started(timeout_s=timeout_s)
        handle: RuntimeThreadHandle = self._submit(lambda runtime: runtime.start_thread(request), timeout_s=timeout_s)
        if not isinstance(handle, RuntimeThreadHandle):
            raise TypeError("Codex worker thread start returned an unexpected result")
        with self._lock:
            self._last_generation = handle.generation
        return handle

    def resume_thread(self, thread_id: str, *, timeout_s: float = 30.0) -> RuntimeThreadHandle:
        self._ensure_started(timeout_s=timeout_s)
        handle: RuntimeThreadHandle = self._submit(
            lambda runtime: runtime.resume_thread(thread_id), timeout_s=timeout_s
        )
        if not isinstance(handle, RuntimeThreadHandle):
            raise TypeError("Codex worker thread resume returned an unexpected result")
        with self._lock:
            self._last_generation = handle.generation
        return handle

    def compact_thread(self, thread: RuntimeThreadHandle, *, timeout_s: float = 30.0) -> None:
        self._ensure_started(timeout_s=timeout_s)
        self._submit(lambda runtime: runtime.compact_thread(thread), timeout_s=timeout_s)

    def run_turn(
        self,
        request: RuntimeTurnRequest,
        *,
        control_reader: RuntimeControlReader,
        initial_input_revision: int,
        event_observer: RuntimeEventObserver | None = None,
        poll_interval_s: float = 0.2,
        timeout_s: float = 330.0,
    ) -> RuntimeTurnResult:
        result: RuntimeTurnResult = self._submit(
            lambda runtime: _run_controlled_turn(
                runtime,
                request,
                control_reader=control_reader,
                initial_input_revision=initial_input_revision,
                event_observer=event_observer,
                poll_interval_s=poll_interval_s,
            ),
            timeout_s=timeout_s,
        )
        if not isinstance(result, RuntimeTurnResult):
            raise TypeError("Codex worker turn returned an unexpected result")
        return result

    def current_generation(self) -> int:
        with self._lock:
            return self._last_generation

    def shutdown(self, *, timeout_s: float = 10.0) -> dict[str, object]:
        with self._lock:
            loop = self._loop
            runtime = self._runtime
            thread = self._thread
        if loop is None or runtime is None or thread is None:
            return {"status": "stopped", "generation": 0}
        future = asyncio.run_coroutine_threadsafe(runtime.shutdown(), loop)
        future.result(timeout=timeout_s)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=timeout_s)
        with self._lock:
            self._loop = None
            self._runtime = None
            self._thread = None
            self._ready.clear()
        return {"status": "stopped", "generation": 0}

    def _ensure_started(self, *, timeout_s: float) -> None:
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._thread_main, name="aearn-codex-runtime", daemon=True)
                self._thread.start()
        if not self._ready.wait(timeout_s):
            raise TimeoutError("Codex runtime worker loop did not start")

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        runtime = self._runtime_factory()
        with self._lock:
            self._loop = loop
            self._runtime = runtime
            self._ready.set()
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()

    def _submit(self, operation: Callable[[AgentRuntimePort], Coroutine[Any, Any, T]], *, timeout_s: float) -> T:
        with self._lock:
            loop = self._loop
            runtime = self._runtime
        if loop is None or runtime is None:
            raise RuntimeError("Codex runtime worker loop is unavailable")
        coroutine = operation(runtime)
        future: Future[T] = asyncio.run_coroutine_threadsafe(coroutine, loop)
        return cast(T, future.result(timeout=timeout_s))



async def _next_runtime_event(iterator: AsyncIterator[RuntimeEvent]) -> RuntimeEvent:
    return await anext(iterator)


async def _run_controlled_turn(
    runtime: AgentRuntimePort,
    request: RuntimeTurnRequest,
    *,
    control_reader: RuntimeControlReader,
    initial_input_revision: int,
    event_observer: RuntimeEventObserver | None = None,
    poll_interval_s: float = 0.2,
) -> RuntimeTurnResult:
    turn_task = asyncio.create_task(runtime.run_turn(request))
    event_iterator = runtime.events().__aiter__()
    event_task: asyncio.Task[RuntimeEvent] = asyncio.create_task(_next_runtime_event(event_iterator))
    turn_id: str | None = None
    applied_revision = initial_input_revision
    observed_sequence = 0
    max_observed_sequence = 0
    interrupt_sent = False
    try:
        while not turn_task.done():
            done, _pending = await asyncio.wait(
                {turn_task, event_task},
                timeout=poll_interval_s,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if event_task in done:
                try:
                    event = event_task.result()
                except StopAsyncIteration:
                    event_task = asyncio.create_task(_next_runtime_event(event_iterator))
                else:
                    observed_sequence += 1
                    sequence = event.sequence or observed_sequence
                    max_observed_sequence = max(max_observed_sequence, sequence)
                    if event_observer is not None:
                        event_observer(event, sequence)
                    if (
                        event.kind is RuntimeEventKind.TURN_STARTED
                        and event.thread_id == request.thread.thread_id
                        and event.turn_id
                    ):
                        turn_id = event.turn_id
                    event_task = asyncio.create_task(_next_runtime_event(event_iterator))
            if turn_id is None or interrupt_sent:
                continue
            directive = control_reader(turn_id, applied_revision)
            if directive.interrupt:
                await runtime.interrupt(request.thread, turn_id)
                interrupt_sent = True
                continue
            if directive.steer_input and directive.input_revision > applied_revision:
                try:
                    await runtime.steer(request.thread, turn_id, directive.steer_input)
                    applied_revision = directive.input_revision
                except Exception:
                    try:
                        await runtime.interrupt(request.thread, turn_id)
                        interrupt_sent = True
                    except Exception:
                        turn_task.cancel()
                        await asyncio.gather(turn_task, return_exceptions=True)
                        event = RuntimeEvent(
                            RuntimeEventKind.TURN_COMPLETED,
                            request.thread.thread_id,
                            turn_id,
                            terminal_status=RuntimeTerminalStatus.UNAVAILABLE,
                            safe_code="runtime_control_failed",
                            sequence=max_observed_sequence + 1,
                        )
                        return RuntimeTurnResult(
                            request.thread,
                            turn_id,
                            RuntimeTerminalStatus.UNAVAILABLE,
                            (event,),
                            "runtime_control_failed",
                        )
        return await turn_task
    except Exception:
        if turn_id is not None and not turn_task.done():
            try:
                await runtime.interrupt(request.thread, turn_id)
                return await asyncio.wait_for(turn_task, timeout=5.0)
            except Exception:
                pass
        if not turn_task.done():
            turn_task.cancel()
            await asyncio.gather(turn_task, return_exceptions=True)
        event = RuntimeEvent(
            RuntimeEventKind.TURN_COMPLETED,
            request.thread.thread_id,
            turn_id,
            terminal_status=RuntimeTerminalStatus.UNAVAILABLE,
            safe_code="runtime_control_failed",
            sequence=max_observed_sequence + 1,
        )
        return RuntimeTurnResult(
            request.thread,
            turn_id or "",
            RuntimeTerminalStatus.UNAVAILABLE,
            (event,),
            "runtime_control_failed",
        )
    finally:
        if not event_task.done():
            event_task.cancel()
        await asyncio.gather(event_task, return_exceptions=True)
        close_event_iterator = getattr(event_iterator, "aclose", None)
        if close_event_iterator is not None:
            await close_event_iterator()
        if not turn_task.done():
            turn_task.cancel()
            await asyncio.gather(turn_task, return_exceptions=True)

def _default_runtime_factory() -> AgentRuntimePort:
    config = CodexRuntimeConfig.from_settings(get_settings())
    return CodexAppServerRuntime(CodexRuntimeSupervisor(config), event_queue_size=config.notification_queue_size)


def _health_payload(snapshot: RuntimeHealthSnapshot) -> dict[str, object]:
    return {
        "status": snapshot.status.value,
        "generation": snapshot.generation,
        "version": snapshot.version,
        "model": snapshot.model,
        "model_provider": snapshot.model_provider,
        "safe_error_code": snapshot.safe_error_code,
        "unknown_notifications": snapshot.unknown_notifications,
    }


_host = CodexRuntimeWorkerHost()


def get_codex_runtime_worker_host() -> CodexRuntimeWorkerHost:
    return _host


def run_codex_worker_operation(operation: str) -> dict[str, object]:
    if operation == "health":
        return _host.health()
    if operation == "shutdown":
        return _host.shutdown()
    return {"status": "blocked_policy", "safe_error_code": "unsupported_codex_worker_operation"}
