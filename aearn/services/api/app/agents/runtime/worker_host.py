"""Process-local owner used only by the dedicated tutor-codex Celery worker."""
from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import Any

from app.core.config import get_settings

from .codex_adapter import CodexAppServerRuntime
from .codex_config import CodexRuntimeConfig
from .codex_supervisor import CodexRuntimeSupervisor
from .contracts import AgentRuntimePort, RuntimeHealthSnapshot

RuntimeFactory = Callable[[], AgentRuntimePort]


class CodexRuntimeWorkerHost:
    def __init__(self, *, runtime_factory: RuntimeFactory | None = None) -> None:
        self._runtime_factory = runtime_factory or _default_runtime_factory
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._runtime: AgentRuntimePort | None = None
        self._ready = threading.Event()
        self._lock = threading.Lock()

    def health(self, *, timeout_s: float = 20.0) -> dict[str, object]:
        self._ensure_started(timeout_s=timeout_s)
        snapshot = self._submit(lambda runtime: runtime.start(), timeout_s=timeout_s)
        return _health_payload(snapshot)

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

    def _submit(self, operation: Callable[[AgentRuntimePort], Any], *, timeout_s: float) -> RuntimeHealthSnapshot:
        with self._lock:
            loop = self._loop
            runtime = self._runtime
        if loop is None or runtime is None:
            raise RuntimeError("Codex runtime worker loop is unavailable")
        coroutine = operation(runtime)
        future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        result = future.result(timeout=timeout_s)
        if not isinstance(result, RuntimeHealthSnapshot):
            raise TypeError("Codex worker operation returned an unexpected result")
        return result


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


def run_codex_worker_operation(operation: str) -> dict[str, object]:
    if operation == "health":
        return _host.health()
    if operation == "shutdown":
        return _host.shutdown()
    return {"status": "blocked_policy", "safe_error_code": "unsupported_codex_worker_operation"}
