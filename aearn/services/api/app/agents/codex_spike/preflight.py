"""Executable, schema, and isolated App Server preflight for Child 1."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .isolated_home import IsolatedCodexHome, build_isolated_codex_home
from .runtime import JsonObject, StdioJsonRpcClient, ToolScenarioHost

_REQUIRED_CLIENT_METHODS = frozenset({"initialize", "thread/start", "turn/start", "turn/interrupt"})
_REQUIRED_SERVER_METHODS = frozenset({"item/tool/call"})
_REQUIRED_NOTIFICATIONS = frozenset({"thread/started", "turn/started", "item/started", "item/completed", "turn/completed"})
_VERSION_PATTERN = re.compile(r"^codex-cli\s+(?P<version>\S+)$")


@dataclass(frozen=True, slots=True)
class CodexExecutableProbe:
    status: str
    executable_path: str | None
    version: str | None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class CodexProtocolPreflight:
    executable: CodexExecutableProbe
    codex_home_matched: bool
    platform_family: str | None
    model: str
    model_provider: str
    thread_model_matched: bool
    thread_provider_matched: bool
    client_methods: tuple[str, ...]
    server_methods: tuple[str, ...]
    notifications: tuple[str, ...]
    dynamic_tools_supported: bool
    config_fingerprint: str
    global_home_untouched_by_design: bool

    @property
    def ready(self) -> bool:
        return self.executable.status == "ready" and self.codex_home_matched and self.platform_family == "windows" and self.thread_model_matched and self.thread_provider_matched and _REQUIRED_CLIENT_METHODS.issubset(self.client_methods) and _REQUIRED_SERVER_METHODS.issubset(self.server_methods) and _REQUIRED_NOTIFICATIONS.issubset(self.notifications) and self.dynamic_tools_supported and self.global_home_untouched_by_design


def resolve_codex_executable(explicit: str | Path | None = None) -> Path | None:
    if explicit is not None:
        candidate = Path(explicit).expanduser()
        return candidate.resolve() if candidate.is_file() else None
    names = ("codex.exe", "codex.cmd", "codex") if os.name == "nt" else ("codex",)
    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found).resolve()
    return None


def probe_codex_executable(explicit: str | Path | None = None) -> CodexExecutableProbe:
    executable = resolve_codex_executable(explicit)
    if executable is None:
        return CodexExecutableProbe(status="missing", executable_path=None, version=None, error_code="codex_missing")
    try:
        completed = subprocess.run([str(executable), "--version"], capture_output=True, check=False, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return CodexExecutableProbe(status="error", executable_path=str(executable), version=None, error_code="version_probe_failed")
    match = _VERSION_PATTERN.fullmatch(completed.stdout.strip())
    if completed.returncode != 0 or match is None:
        return CodexExecutableProbe(status="incompatible", executable_path=str(executable), version=None, error_code="version_format_incompatible")
    return CodexExecutableProbe(status="ready", executable_path=str(executable), version=match.group("version"))


async def run_codex_protocol_preflight(*, root: Path, base_url: str = "http://127.0.0.1:9/v1", executable: str | Path | None = None) -> CodexProtocolPreflight:
    probe = probe_codex_executable(executable)
    if probe.status != "ready" or probe.executable_path is None:
        raise RuntimeError(f"Codex executable preflight failed: {probe.error_code}")
    isolated = build_isolated_codex_home(root, base_url=base_url)
    schema_root = isolated.root / "schema"
    _generate_schema(Path(probe.executable_path), isolated, schema_root)
    client_methods = _schema_methods(schema_root / "ClientRequest.json")
    server_methods = _schema_methods(schema_root / "ServerRequest.json")
    notifications = _schema_methods(schema_root / "ServerNotification.json")
    dynamic_tools_supported = "item/tool/call" in server_methods and _thread_start_has_dynamic_tools(schema_root)

    env = os.environ.copy()
    env["CODEX_HOME"] = str(isolated.codex_home)
    env[isolated.env_key] = "fixture-key-not-sent"
    host = ToolScenarioHost()
    client = StdioJsonRpcClient([probe.executable_path, "app-server", "--stdio", "--strict-config"], cwd=isolated.workspace, env=env, notification_methods=tuple(notifications), server_request_handlers={"item/tool/call": host.handle}, request_timeout_s=10, secrets=(env[isolated.env_key],), path_roots=(isolated.root,))
    initialize: JsonObject = {}
    thread: JsonObject = {}
    await client.start()
    try:
        initialize = await client.request("initialize", {"clientInfo": {"name": "aearn-sidecar-spike", "version": "0.1.0"}, "capabilities": {"experimentalApi": True}}, timeout_s=10)
        await client.notify("initialized", {})
        thread = await client.request("thread/start", {"model": isolated.model, "modelProvider": isolated.model_provider, "cwd": str(isolated.workspace), "approvalPolicy": "never", "sandbox": "read-only", "ephemeral": True, "serviceName": "aearn_sidecar_spike", "dynamicTools": [{"name": "aearn_protocol_probe", "description": "Validate bounded typed dynamic tool recovery.", "inputSchema": {"type": "object", "additionalProperties": False, "required": ["attempt", "value"], "properties": {"attempt": {"type": "integer", "minimum": 1, "maximum": 2}, "value": {"type": "string", "maxLength": 64}}}}]}, timeout_s=10)
    finally:
        await client.close()
    return CodexProtocolPreflight(executable=probe, codex_home_matched=Path(str(initialize.get("codexHome", ""))).resolve() == isolated.codex_home, platform_family=str(initialize.get("platformFamily")) if initialize else None, model=isolated.model, model_provider=isolated.model_provider, thread_model_matched=thread.get("model") == isolated.model, thread_provider_matched=thread.get("modelProvider") == isolated.model_provider, client_methods=tuple(sorted(client_methods)), server_methods=tuple(sorted(server_methods)), notifications=tuple(sorted(notifications)), dynamic_tools_supported=dynamic_tools_supported, config_fingerprint=isolated.config_fingerprint, global_home_untouched_by_design=isolated.codex_home != (Path.home() / ".codex").resolve())


def _generate_schema(executable: Path, isolated: IsolatedCodexHome, out: Path) -> None:
    env = os.environ.copy()
    env["CODEX_HOME"] = str(isolated.codex_home)
    env[isolated.env_key] = "fixture-key-not-sent"
    completed = subprocess.run([str(executable), "app-server", "generate-json-schema", "--experimental", "--out", str(out)], cwd=isolated.workspace, env=env, capture_output=True, check=False, text=True, timeout=30)
    if completed.returncode != 0:
        raise RuntimeError("Codex App Server schema generation failed")


def _schema_methods(path: Path) -> frozenset[str]:
    data: Mapping[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    methods: set[str] = set()
    for item in data.get("oneOf", []):
        if not isinstance(item, Mapping):
            continue
        properties = item.get("properties")
        if not isinstance(properties, Mapping):
            continue
        method = properties.get("method")
        if not isinstance(method, Mapping):
            continue
        values = method.get("enum")
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
            methods.update(str(value) for value in values)
    return frozenset(methods)


def _thread_start_has_dynamic_tools(schema_root: Path) -> bool:
    data = json.loads((schema_root / "v2" / "ThreadStartParams.json").read_text(encoding="utf-8"))
    properties = data.get("properties", {})
    return isinstance(properties, dict) and "dynamicTools" in properties
