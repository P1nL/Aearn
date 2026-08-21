"""Bounded newline-delimited JSON-RPC connection for Codex App Server."""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import subprocess
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeAlias, cast

JsonObject: TypeAlias = dict[str, Any]
ServerRequestHandler: TypeAlias = Callable[[JsonObject], JsonObject | Awaitable[JsonObject]]
SENSITIVE_KEYS = frozenset({"api_key", "authorization", "auth_token", "credential", "developerinstructions", "prompt", "raw_prompt", "raw_response", "reasoning", "response", "secret", "system_prompt", "token"})


class JsonRpcError(RuntimeError):
    """Base error for the isolated stdio client."""


class JsonRpcProtocolError(JsonRpcError):
    """The peer violated the bounded JSON-RPC wire contract."""


class JsonRpcTimeoutError(JsonRpcError):
    """A request, server callback, or terminal notification timed out."""


class JsonRpcChildExitedError(JsonRpcError):
    """The child exited before the protocol operation completed."""


class JsonRpcRemoteError(JsonRpcError):
    def __init__(self, *, code: int, message: str) -> None:
        super().__init__(f"remote JSON-RPC error {code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class JsonRpcNotification:
    method: str
    params: JsonObject


@dataclass(frozen=True, slots=True)
class SanitizedProcessEvidence:
    returncode: int | None
    stderr: tuple[str, ...]
    unknown_notifications: int


def redact_protocol_value(value: object, *, secrets: Sequence[str] = (), path_roots: Sequence[Path] = ()) -> object:
    """Redact secrets, protocol bodies, and local roots from evidence."""
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for raw_key, item in list(value.items())[:50]:
            key = str(raw_key)
            normalized = key.lower().replace("_", "")
            if normalized in SENSITIVE_KEYS or key.lower() in SENSITIVE_KEYS:
                result[key] = "[REDACTED]"
            else:
                result[key] = redact_protocol_value(item, secrets=secrets, path_roots=path_roots)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact_protocol_value(item, secrets=secrets, path_roots=path_roots) for item in value[:20]]
    if isinstance(value, str):
        redacted = value
        for secret in secrets:
            if secret:
                redacted = redacted.replace(secret, "[REDACTED_SECRET]")
        for path in path_roots:
            text = str(path)
            if text:
                redacted = redacted.replace(text, "[ISOLATED_PATH]")
                redacted = redacted.replace(text.replace("\\", "/"), "[ISOLATED_PATH]")
        lowered = redacted.lower()
        if any(marker in lowered for marker in ("authorization: bearer", "deepseek_api_key=", "api_key=", "raw_prompt=")):
            return "[REDACTED_SENSITIVE_TEXT]"
        return redacted[:1000]
    return value


def _empty_user_input_response(raw_params: object) -> JsonObject:
    """Decline Codex client-side elicitation without accepting model-owned questions as authority."""
    answers: JsonObject = {}
    if isinstance(raw_params, Mapping):
        questions = raw_params.get("questions")
        if isinstance(questions, Sequence) and not isinstance(questions, (str, bytes, bytearray)):
            for question in questions[:3]:
                if not isinstance(question, Mapping):
                    continue
                question_id = question.get("id")
                if isinstance(question_id, str) and 0 < len(question_id) <= 120:
                    answers[question_id] = {"answers": []}
    return {"answers": answers}


class StdioJsonRpcClient:
    """Own one child process and fail closed on malformed or unknown requests."""

    def __init__(self, argv: Sequence[str], *, cwd: Path, env: Mapping[str, str], notification_methods: Sequence[str] = (), server_request_handlers: Mapping[str, ServerRequestHandler] | None = None, request_timeout_s: float = 5.0, server_request_timeout_s: float = 2.0, max_line_bytes: int = 1_048_576, secrets: Sequence[str] = (), path_roots: Sequence[Path] = (), notification_queue_size: int = 256) -> None:
        if not argv:
            raise ValueError("argv must not be empty")
        self._argv = tuple(argv)
        self._cwd = cwd
        self._env = dict(env)
        self._known_notifications = frozenset(notification_methods)
        self._handlers = dict(server_request_handlers or {})
        self._request_timeout_s = request_timeout_s
        self._server_request_timeout_s = server_request_timeout_s
        self._max_line_bytes = max_line_bytes
        self._secrets = tuple(secrets)
        self._path_roots = tuple(path_roots)
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._waiter_task: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[JsonObject]] = {}
        if notification_queue_size < 1:
            raise ValueError("notification queue size must be positive")
        self._notifications: asyncio.Queue[JsonRpcNotification] = asyncio.Queue(maxsize=notification_queue_size)
        self._next_id = 1
        self._fatal_error: JsonRpcError | None = None
        self._fatal_event = asyncio.Event()
        self._stderr: list[str] = []
        self._unknown_notifications = 0
        self._closed = False

    @property
    def process_id(self) -> int | None:
        return self._process.pid if self._process is not None else None

    @property
    def fatal_error(self) -> JsonRpcError | None:
        return self._fatal_error

    async def start(self) -> None:
        if self._process is not None:
            raise RuntimeError("client already started")
        self._process = await asyncio.create_subprocess_exec(*self._argv, cwd=str(self._cwd), env=self._env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=self._max_line_bytes + 1)
        self._reader_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._read_stderr())
        self._waiter_task = asyncio.create_task(self._watch_child())

    async def request(self, method: str, params: Mapping[str, object] | None = None, *, timeout_s: float | None = None) -> JsonObject:
        self._require_running()
        request_id = self._next_id
        self._next_id += 1
        future: asyncio.Future[JsonObject] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self._write({"id": request_id, "method": method, "params": dict(params or {})})
        try:
            return await asyncio.wait_for(future, timeout=timeout_s or self._request_timeout_s)
        except TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise JsonRpcTimeoutError(f"request timed out: {method}") from exc

    async def notify(self, method: str, params: Mapping[str, object] | None = None) -> None:
        self._require_running()
        await self._write({"method": method, "params": dict(params or {})})

    async def next_notification(self, *, timeout_s: float | None = None) -> JsonRpcNotification:
        if not self._notifications.empty():
            return self._notifications.get_nowait()
        if self._fatal_error is not None:
            raise self._fatal_error
        timeout = timeout_s or self._request_timeout_s
        notification_task = asyncio.create_task(self._notifications.get())
        fatal_task = asyncio.create_task(self._fatal_event.wait())
        done, pending = await asyncio.wait({notification_task, fatal_task}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if not done:
            raise JsonRpcTimeoutError("notification timed out")
        if notification_task in done:
            return notification_task.result()
        if not self._notifications.empty():
            return self._notifications.get_nowait()
        if self._fatal_error is not None:
            raise self._fatal_error
        raise JsonRpcProtocolError("fatal notification wait ended without an error")

    async def wait_for_notification(self, method: str, *, timeout_s: float | None = None, predicate: Callable[[JsonObject], bool] | None = None) -> JsonRpcNotification:
        deadline = asyncio.get_running_loop().time() + (timeout_s or self._request_timeout_s)
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise JsonRpcTimeoutError(f"notification timed out: {method}")
            notification = await self.next_notification(timeout_s=remaining)
            if notification.method == method and (predicate is None or predicate(notification.params)):
                return notification

    async def close(self) -> SanitizedProcessEvidence:
        if self._closed:
            return self.evidence()
        self._closed = True
        process = self._process
        if process is not None and process.returncode is None:
            if process.stdin is not None:
                process.stdin.close()
                try:
                    await process.stdin.wait_closed()
                except (BrokenPipeError, ConnectionResetError):
                    pass
            try:
                await asyncio.wait_for(process.wait(), timeout=1.5)
            except TimeoutError:
                await self._kill_process_tree(process)
        tasks = tuple(task for task in (self._reader_task, self._stderr_task, self._waiter_task) if task is not None)
        if tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=2.0)
            except TimeoutError:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        if process is not None:
            transport = getattr(process, "_transport", None)
            if transport is not None:
                transport.close()
            await asyncio.sleep(0)
        return self.evidence()

    def evidence(self) -> SanitizedProcessEvidence:
        return SanitizedProcessEvidence(returncode=self._process.returncode if self._process is not None else None, stderr=tuple(self._stderr), unknown_notifications=self._unknown_notifications)

    async def _read_stdout(self) -> None:
        process = cast(asyncio.subprocess.Process, self._process)
        stdout = cast(asyncio.StreamReader, process.stdout)
        try:
            while True:
                line = await stdout.readline()
                if not line:
                    return
                if len(line) > self._max_line_bytes:
                    raise JsonRpcProtocolError("stdout JSON-RPC line exceeded the configured limit")
                try:
                    message = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise JsonRpcProtocolError("stdout contained invalid JSON-RPC") from exc
                if not isinstance(message, dict):
                    raise JsonRpcProtocolError("JSON-RPC message must be an object")
                await self._dispatch(cast(JsonObject, message))
        except asyncio.CancelledError:
            raise
        except JsonRpcError as exc:
            await self._mark_fatal(exc)
        except Exception as exc:
            await self._mark_fatal(JsonRpcProtocolError(f"stdout reader failed: {type(exc).__name__}"))

    async def _read_stderr(self) -> None:
        process = cast(asyncio.subprocess.Process, self._process)
        stderr = cast(asyncio.StreamReader, process.stderr)
        try:
            while True:
                line = await stderr.readline()
                if not line:
                    return
                text = line.decode("utf-8", errors="replace").rstrip()
                safe = redact_protocol_value(text, secrets=self._secrets, path_roots=self._path_roots)
                self._stderr.append(str(safe)[:1000])
                if len(self._stderr) > 100:
                    del self._stderr[0]
        except asyncio.CancelledError:
            raise

    async def _watch_child(self) -> None:
        process = cast(asyncio.subprocess.Process, self._process)
        returncode = await process.wait()
        if not self._closed and self._fatal_error is None:
            await self._mark_fatal(JsonRpcChildExitedError(f"child exited with code {returncode}"))

    async def _dispatch(self, message: JsonObject) -> None:
        request_id = message.get("id")
        method = message.get("method")
        if request_id is not None and method is None:
            if not isinstance(request_id, int):
                raise JsonRpcProtocolError("response id must be an integer")
            future = self._pending.pop(request_id, None)
            if future is None:
                raise JsonRpcProtocolError("response id did not match a pending request")
            error = message.get("error")
            if isinstance(error, Mapping):
                future.set_exception(JsonRpcRemoteError(code=int(error.get("code", -32000)), message=str(redact_protocol_value(error.get("message", "remote error")))))
                return
            result = message.get("result", {})
            if not isinstance(result, dict):
                raise JsonRpcProtocolError("response result must be an object")
            future.set_result(cast(JsonObject, result))
            return
        if isinstance(method, str) and request_id is not None:
            if not isinstance(request_id, int):
                raise JsonRpcProtocolError("server request id must be an integer")
            handler = self._handlers.get(method)
            if handler is None and method == "item/tool/requestUserInput":
                await self._write({"id": request_id, "result": _empty_user_input_response(message.get("params"))})
                return
            if handler is None:
                await self._write_error(request_id, -32601, "unsupported server request")
                raise JsonRpcProtocolError(f"unknown server request: {method}")
            try:
                raw_result = handler(cast(JsonObject, message.get("params") or {}))
                result = await asyncio.wait_for(raw_result, timeout=self._server_request_timeout_s) if inspect.isawaitable(raw_result) else raw_result
                await self._write({"id": request_id, "result": result})
            except TimeoutError as exc:
                await self._write_error(request_id, -32002, "server request timed out")
                raise JsonRpcTimeoutError(f"server request timed out: {method}") from exc
            except JsonRpcError:
                raise
            except Exception as exc:
                await self._write_error(request_id, -32003, "server request failed")
                raise JsonRpcProtocolError(f"server request handler failed: {method}") from exc
            return
        if isinstance(method, str):
            params = message.get("params") or {}
            if not isinstance(params, dict):
                raise JsonRpcProtocolError("notification params must be an object")
            if self._known_notifications and method not in self._known_notifications:
                self._unknown_notifications += 1
            await self._notifications.put(JsonRpcNotification(method=method, params=cast(JsonObject, params)))
            return
        raise JsonRpcProtocolError("message was neither response, request, nor notification")

    async def _write(self, message: Mapping[str, object]) -> None:
        process = cast(asyncio.subprocess.Process, self._process)
        stdin = process.stdin
        if stdin is None or stdin.is_closing():
            raise JsonRpcChildExitedError("child stdin is unavailable")
        payload = json.dumps(message, ensure_ascii=True, separators=(",", ":")).encode("utf-8") + b"\n"
        if len(payload) > self._max_line_bytes:
            raise JsonRpcProtocolError("outbound JSON-RPC line exceeded the configured limit")
        stdin.write(payload)
        await stdin.drain()

    async def _write_error(self, request_id: int, code: int, message: str) -> None:
        await self._write({"id": request_id, "error": {"code": code, "message": message}})

    async def _mark_fatal(self, error: JsonRpcError) -> None:
        if self._fatal_error is None:
            self._fatal_error = error
            self._fatal_event.set()
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._pending.clear()
        process = self._process
        if process is not None and process.returncode is None:
            await self._kill_process_tree(process)

    async def _kill_process_tree(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        if os.name == "nt":
            await asyncio.to_thread(subprocess.run, ["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False, text=True)
        else:
            process.kill()
        try:
            await asyncio.wait_for(process.wait(), timeout=3.0)
        except TimeoutError:
            process.kill()
            await process.wait()

    def _require_running(self) -> None:
        if self._fatal_error is not None:
            raise self._fatal_error
        if self._process is None or self._process.returncode is not None or self._closed:
            raise JsonRpcChildExitedError("JSON-RPC child is not running")
