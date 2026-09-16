"""Explicitly approved real deepseek-flash Responses smoke."""
from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.services.llm.llm_urls import deepseek_responses_url, normalize_deepseek_base_url

from .isolated_home import IsolatedCodexHome, build_isolated_codex_home
from .preflight import CodexExecutableProbe, probe_codex_executable
from .runtime import JsonRpcError, StdioJsonRpcClient, ToolScenarioHost

_REAL_SMOKE_INPUT = (
    "Call aearn_protocol_probe with attempt=1 and value='bounded'. "
    "If the tool returns repairable_invalid, call it again in this same turn with attempt=2. "
    "After the tool returns completed, finish with a brief acknowledgement."
)
_NOTIFICATIONS = ("thread/started", "turn/started", "item/started", "item/completed", "turn/completed")


class RealDeepSeekSmokeError(RuntimeError):
    """The approved real smoke did not satisfy the bounded rubric."""


@dataclass(frozen=True, slots=True)
class RealDeepSeekSmokeResult:
    status: str
    model: str
    model_provider: str
    endpoint: str
    tool_attempts: tuple[int, ...]
    input_sha256: str
    opaque_turn_sha256: str
    elapsed_ms: int
    configured_request_retries: int
    configured_stream_retries: int
    retained_raw_prompt: bool = False
    retained_raw_response: bool = False
    retained_isolated_home: bool = False


async def run_real_deepseek_smoke(*, approved: bool, root: Path, base_url: str, executable: str | Path | None = None, total_timeout_s: float = 90.0) -> RealDeepSeekSmokeResult:
    """Run one isolated turn only after the caller supplies explicit approval."""
    if not approved:
        raise PermissionError("real deepseek-flash smoke requires explicit approval")
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RealDeepSeekSmokeError("DEEPSEEK_API_KEY is not present in the process environment")
    probe = probe_codex_executable(executable)
    if probe.status != "ready" or probe.executable_path is None:
        raise RealDeepSeekSmokeError(f"Codex executable is not ready: {probe.error_code}")

    normalized_base_url = normalize_deepseek_base_url(base_url)
    isolated = build_isolated_codex_home(root, base_url=normalized_base_url)
    try:
        return await _execute_real_smoke(isolated=isolated, probe=probe, normalized_base_url=normalized_base_url, api_key=api_key, total_timeout_s=total_timeout_s)
    finally:
        await _remove_isolated_root(isolated.root)


async def _execute_real_smoke(*, isolated: IsolatedCodexHome, probe: CodexExecutableProbe, normalized_base_url: str, api_key: str, total_timeout_s: float) -> RealDeepSeekSmokeResult:
    if probe.executable_path is None:
        raise RealDeepSeekSmokeError("Codex executable path disappeared after preflight")
    env = os.environ.copy()
    env["CODEX_HOME"] = str(isolated.codex_home)
    host = ToolScenarioHost("repair")
    client = StdioJsonRpcClient([probe.executable_path, "app-server", "--stdio", "--strict-config"], cwd=isolated.workspace, env=env, notification_methods=_NOTIFICATIONS, server_request_handlers={"item/tool/call": host.handle}, request_timeout_s=15, server_request_timeout_s=5, secrets=(api_key,), path_roots=(isolated.root,))
    loop = asyncio.get_running_loop()
    started = loop.time()
    thread_id = ""
    turn_id = ""
    await client.start()
    try:
        async with asyncio.timeout(total_timeout_s):
            initialize = await client.request("initialize", {"clientInfo": {"name": "aearn-sidecar-real-smoke", "version": "0.1.0"}, "capabilities": {"experimentalApi": True}}, timeout_s=10)
            if Path(str(initialize.get("codexHome", ""))).resolve() != isolated.codex_home:
                raise RealDeepSeekSmokeError("App Server did not use the isolated Codex Home")
            await client.notify("initialized", {})
            thread = await client.request("thread/start", {"model": isolated.model, "modelProvider": isolated.model_provider, "cwd": str(isolated.workspace), "approvalPolicy": "never", "sandbox": "read-only", "ephemeral": True, "serviceName": "aearn_sidecar_real_smoke", "dynamicTools": [{"name": "aearn_protocol_probe", "description": "Return one repairable validation result, then one completed result.", "inputSchema": {"type": "object", "additionalProperties": False, "required": ["attempt", "value"], "properties": {"attempt": {"type": "integer", "minimum": 1, "maximum": 2}, "value": {"type": "string", "maxLength": 64}}}}]}, timeout_s=10)
            if thread.get("model") != isolated.model or thread.get("modelProvider") != isolated.model_provider:
                raise RealDeepSeekSmokeError("App Server rerouted the requested model or provider")
            thread_id = str((thread.get("thread") or {}).get("id", ""))
            turn = await client.request("turn/start", {"threadId": thread_id, "input": [{"type": "text", "text": _REAL_SMOKE_INPUT}]}, timeout_s=10)
            turn_id = str((turn.get("turn") or {}).get("id", ""))
            completed = await client.wait_for_notification("turn/completed", timeout_s=total_timeout_s)
            terminal_status = str((completed.params.get("turn") or {}).get("status", ""))
    except TimeoutError as exc:
        if thread_id and turn_id:
            try:
                await client.request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id}, timeout_s=3)
            except JsonRpcError:
                pass
        raise RealDeepSeekSmokeError("real smoke total timeout") from exc
    finally:
        await client.close()

    attempts = tuple(int(call["arguments"]["attempt"]) for call in host.calls)
    if terminal_status != "completed" or attempts != (1, 2):
        raise RealDeepSeekSmokeError(f"real smoke rubric failed: terminal={terminal_status}, attempts={attempts}")
    elapsed_ms = int((loop.time() - started) * 1000)
    return RealDeepSeekSmokeResult(status="completed", model=isolated.model, model_provider=isolated.model_provider, endpoint=deepseek_responses_url(normalized_base_url), tool_attempts=attempts, input_sha256=hashlib.sha256(_REAL_SMOKE_INPUT.encode("utf-8")).hexdigest(), opaque_turn_sha256=hashlib.sha256(turn_id.encode("utf-8")).hexdigest(), elapsed_ms=elapsed_ms, configured_request_retries=0, configured_stream_retries=0)


async def _remove_isolated_root(root: Path) -> None:
    last_error: OSError | None = None
    for _ in range(10):
        try:
            shutil.rmtree(root)
        except FileNotFoundError:
            return
        except OSError as exc:
            last_error = exc
            await asyncio.sleep(0.1)
            continue
        return
    raise RealDeepSeekSmokeError("isolated Codex Home cleanup failed") from last_error
