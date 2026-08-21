"""Process ownership and lifecycle supervision for Codex App Server."""
from __future__ import annotations

import asyncio
import importlib
import os
import threading
import uuid
from typing import Any, BinaryIO
from collections.abc import Callable, Mapping
from pathlib import Path

from .codex_config import CodexRuntimeConfig, CodexRuntimeHome, ensure_codex_runtime_home, probe_codex_executable
from .codex_connection import JsonObject, JsonRpcError, JsonRpcNotification, ServerRequestHandler, StdioJsonRpcClient
from .contracts import RuntimeHealthSnapshot, RuntimeHealthStatus, RuntimeToolCall, RuntimeToolRegistry


class RuntimeUnavailableError(RuntimeError):
    pass


class RuntimeOwnershipError(RuntimeError):
    pass


class RuntimeGenerationError(RuntimeError):
    pass


ConnectionFactory = Callable[[CodexRuntimeConfig, CodexRuntimeHome, Mapping[str, str], ServerRequestHandler], StdioJsonRpcClient]


class _OwnershipRegistry:
    _lock = threading.Lock()
    _owners: dict[str, str] = {}

    @classmethod
    def acquire(cls, key: str, owner_id: str) -> bool:
        with cls._lock:
            current = cls._owners.get(key)
            if current is not None and current != owner_id:
                return False
            cls._owners[key] = owner_id
            return True

    @classmethod
    def release(cls, key: str, owner_id: str) -> None:
        with cls._lock:
            if cls._owners.get(key) == owner_id:
                cls._owners.pop(key, None)


class RuntimeProcessLock:
    """Hold a one-byte OS lock for the lifetime of one worker process owner."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._file: BinaryIO | None = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        file = self.path.open("a+b")
        try:
            file.seek(0, os.SEEK_END)
            if file.tell() == 0:
                file.write(b"0")
                file.flush()
            file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl: Any = importlib.import_module("fcntl")
                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            file.close()
            return False
        self._file = file
        return True

    def release(self) -> None:
        file = self._file
        if file is None:
            return
        try:
            file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl: Any = importlib.import_module("fcntl")
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)
        finally:
            file.close()
            self._file = None


class CodexToolDispatcher:
    def __init__(self) -> None:
        self._registries: dict[str, RuntimeToolRegistry] = {}
        self._thread_registries: dict[str, RuntimeToolRegistry] = {}

    def prepare(self, thread_id: str, registry: RuntimeToolRegistry) -> None:
        if thread_id in self._thread_registries:
            raise RuntimeOwnershipError("tool registry already owns this thread")
        self._thread_registries[thread_id] = registry

    def register(self, turn_id: str, registry: RuntimeToolRegistry) -> None:
        if turn_id in self._registries:
            raise RuntimeOwnershipError("tool registry already owns this turn")
        self._registries[turn_id] = registry

    def unregister(self, thread_id: str, turn_id: str) -> None:
        self._registries.pop(turn_id, None)
        self._thread_registries.pop(thread_id, None)

    async def handle(self, params: JsonObject) -> JsonObject:
        thread_id = params.get("threadId")
        turn_id = params.get("turnId")
        call_id = params.get("callId")
        tool = params.get("tool")
        arguments = params.get("arguments")
        if not all(isinstance(value, str) and value for value in (thread_id, turn_id, call_id, tool)) or not isinstance(arguments, dict):
            raise RuntimeUnavailableError("invalid_dynamic_tool_request")
        registry = self._registries.get(str(turn_id)) or self._thread_registries.get(str(thread_id))
        if registry is None:
            raise RuntimeUnavailableError("tool_registry_unavailable")
        result = await registry.invoke(RuntimeToolCall(str(thread_id), str(turn_id), str(call_id), str(tool), arguments))
        return {"contentItems": [{"type": "inputText", "text": result.content}], "success": result.success}


class CodexRuntimeSupervisor:
    def __init__(self, config: CodexRuntimeConfig, *, connection_factory: ConnectionFactory | None = None) -> None:
        self.config = config
        self._connection_factory = connection_factory or _default_connection_factory
        self._owner_id = uuid.uuid4().hex
        self._ownership_key = str(config.home_root.expanduser().resolve()).lower()
        self._lock = asyncio.Lock()
        self._connection: StdioJsonRpcClient | None = None
        self._home: CodexRuntimeHome | None = None
        self._generation = 0
        self._version: str | None = None
        self._health = RuntimeHealthSnapshot(RuntimeHealthStatus.STOPPED, 0)
        self._dispatcher = CodexToolDispatcher()
        self._active_turns: set[tuple[str, str]] = set()
        self._owns_runtime = False
        self._process_lock = RuntimeProcessLock(config.home_root.expanduser().resolve() / "runtime-owner.lock")

    @property
    def generation(self) -> int:
        return self._generation

    async def start(self) -> RuntimeHealthSnapshot:
        async with self._lock:
            if self._connection is not None and self._connection.fatal_error is None:
                return self._health
            self._health = RuntimeHealthSnapshot(RuntimeHealthStatus.STARTING, self._generation)
            if not self.config.enabled:
                return self._set_unavailable("runtime_disabled")
            if not _OwnershipRegistry.acquire(self._ownership_key, self._owner_id):
                return self._set_unavailable("ownership_conflict")
            self._owns_runtime = True
            if not self._process_lock.acquire():
                self._release_ownership()
                return self._set_unavailable("ownership_conflict")
            try:
                probe = probe_codex_executable(self.config.executable_path)
                if probe.status != "ready" or probe.executable_path is None or probe.version is None:
                    return await self._startup_failed(probe.error_code or "codex_unavailable")
                if self.config.allowed_versions and probe.version not in self.config.allowed_versions:
                    return await self._startup_failed("unsupported_codex_version")
                if not os.environ.get(self.config.env_key):
                    return await self._startup_failed("provider_credential_missing")
                self._home = ensure_codex_runtime_home(self.config)
                env = os.environ.copy()
                env["CODEX_HOME"] = str(self._home.codex_home)
                connection = self._connection_factory(self.config, self._home, env, self._dispatcher.handle)
                self._connection = connection
                await asyncio.wait_for(connection.start(), timeout=self.config.startup_timeout_s)
                initialize = await connection.request("initialize", {"clientInfo": {"name": "aearn-codex-runtime", "version": "0.1.0"}, "capabilities": {"experimentalApi": True}}, timeout_s=self.config.startup_timeout_s)
                if Path(str(initialize.get("codexHome", ""))).resolve() != self._home.codex_home:
                    await connection.close()
                    return await self._startup_failed("isolated_home_mismatch")
                await connection.notify("initialized", {})
                await connection.request("account/read", {"refreshToken": False}, timeout_s=self.config.request_timeout_s)
                self._generation += 1
                self._version = probe.version
                self._health = RuntimeHealthSnapshot(RuntimeHealthStatus.READY, self._generation, version=probe.version, model=self.config.model, model_provider=self.config.model_provider, metadata={"config_fingerprint": self._home.config_fingerprint})
                return self._health
            except (JsonRpcError, OSError, TimeoutError, ValueError):
                return await self._startup_failed("runtime_preflight_failed")

    async def health(self) -> RuntimeHealthSnapshot:
        connection = self._connection
        if connection is not None and connection.fatal_error is not None:
            async with self._lock:
                await self._invalidate("child_connection_failed")
        return self._health

    def require_connection(self, generation: int | None = None) -> StdioJsonRpcClient:
        if self._connection is None or self._health.status is not RuntimeHealthStatus.READY:
            raise RuntimeUnavailableError(self._health.safe_error_code or "runtime_unavailable")
        if generation is not None and generation != self._generation:
            raise RuntimeGenerationError("stale_runtime_generation")
        return self._connection

    def prepare_turn(self, thread_id: str, registry: RuntimeToolRegistry, generation: int) -> None:
        self.require_connection(generation)
        self._dispatcher.prepare(thread_id, registry)

    def register_turn(self, thread_id: str, turn_id: str, registry: RuntimeToolRegistry, generation: int) -> None:
        self.require_connection(generation)
        self._dispatcher.register(turn_id, registry)
        self._active_turns.add((thread_id, turn_id))

    def unregister_turn(self, thread_id: str, turn_id: str) -> None:
        self._dispatcher.unregister(thread_id, turn_id)
        self._active_turns.discard((thread_id, turn_id))

    async def request(self, method: str, params: Mapping[str, object], *, generation: int | None = None, timeout_s: float | None = None) -> JsonObject:
        return await self.require_connection(generation).request(method, params, timeout_s=timeout_s or self.config.request_timeout_s)

    async def next_notification(self, *, generation: int, timeout_s: float | None = None) -> JsonRpcNotification:
        return await self.require_connection(generation).next_notification(timeout_s=timeout_s or self.config.turn_timeout_s)

    async def shutdown(self) -> None:
        async with self._lock:
            connection = self._connection
            if connection is not None:
                for thread_id, turn_id in tuple(self._active_turns):
                    try:
                        await connection.request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id}, timeout_s=min(3.0, self.config.shutdown_timeout_s))
                    except JsonRpcError:
                        pass
                await connection.close()
            self._connection = None
            self._active_turns.clear()
            self._dispatcher = CodexToolDispatcher()
            self._health = RuntimeHealthSnapshot(RuntimeHealthStatus.STOPPED, self._generation, version=self._version, model=self.config.model, model_provider=self.config.model_provider)
            self._release_ownership()

    async def _startup_failed(self, code: str) -> RuntimeHealthSnapshot:
        if self._connection is not None:
            await self._connection.close()
        self._connection = None
        self._release_ownership()
        return self._set_unavailable(code)

    async def _invalidate(self, code: str) -> None:
        if self._connection is not None:
            await self._connection.close()
        self._connection = None
        self._active_turns.clear()
        self._dispatcher = CodexToolDispatcher()
        self._release_ownership()
        self._set_unavailable(code)

    def _set_unavailable(self, code: str) -> RuntimeHealthSnapshot:
        self._health = RuntimeHealthSnapshot(RuntimeHealthStatus.UNAVAILABLE, self._generation, version=self._version, model=self.config.model, model_provider=self.config.model_provider, safe_error_code=code)
        return self._health

    def _release_ownership(self) -> None:
        if self._owns_runtime:
            self._process_lock.release()
            _OwnershipRegistry.release(self._ownership_key, self._owner_id)
            self._owns_runtime = False


def _default_connection_factory(config: CodexRuntimeConfig, home: CodexRuntimeHome, env: Mapping[str, str], tool_handler: ServerRequestHandler) -> StdioJsonRpcClient:
    if config.executable_path is None:
        raise RuntimeUnavailableError("codex_executable_missing")
    return StdioJsonRpcClient([str(config.executable_path), "app-server", "--stdio", "--strict-config"], cwd=home.workspace, env=env, notification_methods=("thread/started", "turn/started", "item/agentMessage/delta", "item/reasoning/textDelta", "item/reasoning/summaryTextDelta", "item/started", "item/completed", "turn/completed", "warning"), server_request_handlers={"item/tool/call": tool_handler}, request_timeout_s=config.request_timeout_s, server_request_timeout_s=config.request_timeout_s, notification_queue_size=config.notification_queue_size, secrets=(env.get(config.env_key, ""),), path_roots=(home.root,))
