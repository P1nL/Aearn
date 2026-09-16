from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from app.agents.codex_spike.deepseek_fixture import DeepSeekFixtureError, DeepSeekResponsesFixture
from app.agents.codex_spike.isolated_home import build_isolated_codex_home
from app.agents.codex_spike.preflight import probe_codex_executable, resolve_codex_executable, run_codex_protocol_preflight
from app.agents.codex_spike.real_smoke import _remove_isolated_root, run_real_deepseek_smoke
from app.agents.codex_spike.runtime import JsonRpcChildExitedError, JsonRpcProtocolError, JsonRpcTimeoutError, StdioJsonRpcClient, ToolScenarioHost, redact_protocol_value

KNOWN_NOTIFICATIONS = ("thread/started", "turn/started", "item/started", "item/completed", "turn/completed")
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "codex_sidecar" / "fake_app_server.py"


def _client(tmp_path: Path, scenario: str, *, host: ToolScenarioHost | None = None, request_timeout_s: float = 1.0, server_request_timeout_s: float = 0.1) -> StdioJsonRpcClient:
    codex_home = tmp_path / "codex-home"
    workspace = tmp_path / "workspace"
    codex_home.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)
    secret = "fixture-secret-value"
    env = os.environ.copy()
    env.update({"CODEX_HOME": str(codex_home), "FIXTURE_SECRET": secret})
    return StdioJsonRpcClient([sys.executable, str(FIXTURE), "--scenario", scenario], cwd=workspace, env=env, notification_methods=KNOWN_NOTIFICATIONS, server_request_handlers={"item/tool/call": (host or ToolScenarioHost()).handle}, request_timeout_s=request_timeout_s, server_request_timeout_s=server_request_timeout_s, secrets=(secret,), path_roots=(tmp_path,))


async def _initialize(client: StdioJsonRpcClient) -> None:
    result = await client.request("initialize", {"clientInfo": {"name": "aearn-test", "version": "0.1.0"}, "capabilities": {"experimentalApi": True}}, timeout_s=1)
    assert result["platformFamily"] == "windows"
    await client.notify("initialized", {})


async def _start_turn(client: StdioJsonRpcClient) -> None:
    thread = await client.request("thread/start", {"model": "deepseek-flash", "modelProvider": "aearn_deepseek", "dynamicTools": [{"name": "aearn_protocol_probe", "inputSchema": {"type": "object"}}]})
    assert thread["model"] == "deepseek-flash"
    await client.request("turn/start", {"threadId": "thr_fixture", "input": [{"type": "text", "text": "bounded fixture input"}]})


def test_isolated_home_uses_exact_deepseek_responses_contract(tmp_path: Path) -> None:
    isolated = build_isolated_codex_home(tmp_path / "isolation", base_url="https://api.deepseek.example/v1/")
    config = isolated.config_path.read_text(encoding="utf-8")
    assert 'model = "deepseek-flash"' in config
    assert 'model_provider = "aearn_deepseek"' in config
    assert 'wire_api = "responses"' in config
    assert 'requires_openai_auth = false' in config
    assert 'env_key = "DEEPSEEK_API_KEY"' in config
    assert 'base_url = "https://api.deepseek.example"' in config
    assert isolated.codex_home != Path.home() / ".codex"
    assert len(isolated.config_fingerprint) == 64


def test_isolated_home_rejects_global_codex_home() -> None:
    with pytest.raises(ValueError, match="global Codex Home"):
        build_isolated_codex_home(Path.home() / ".codex", base_url="http://127.0.0.1:9/v1")


def test_isolated_home_rejects_unsafe_toml_url(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsafe for strict TOML"):
        build_isolated_codex_home(tmp_path / "unsafe", base_url='https://example.test/\"\nprovider=\"bad')


@pytest.mark.asyncio
async def test_fake_app_server_repairs_in_same_turn_and_counts_unknown_notification(tmp_path: Path) -> None:
    host = ToolScenarioHost("repair")
    client = _client(tmp_path, "repair", host=host)
    await client.start()
    try:
        await _initialize(client)
        await _start_turn(client)
        completed = await client.wait_for_notification("turn/completed", timeout_s=2)
        assert completed.params["turn"]["status"] == "completed"
        assert [call["arguments"]["attempt"] for call in host.calls] == [1, 2]
        assert client.evidence().unknown_notifications == 1
    finally:
        evidence = await client.close()
    assert evidence.returncode == 0


@pytest.mark.asyncio
async def test_fatal_tool_result_is_distinct_from_repairable_result(tmp_path: Path) -> None:
    host = ToolScenarioHost("fatal")
    client = _client(tmp_path, "fatal", host=host)
    await client.start()
    try:
        await _initialize(client)
        await _start_turn(client)
        completed = await client.wait_for_notification("turn/completed", timeout_s=2)
        assert completed.params["turn"]["status"] == "failed"
        assert len(host.calls) == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_server_request_timeout_fails_closed(tmp_path: Path) -> None:
    host = ToolScenarioHost("timeout", timeout_delay_s=0.5)
    client = _client(tmp_path, "fatal", host=host, server_request_timeout_s=0.05)
    await client.start()
    try:
        await _initialize(client)
        await _start_turn(client)
        with pytest.raises(JsonRpcTimeoutError, match="server request timed out"):
            await client.wait_for_notification("turn/completed", timeout_s=1)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_turn_interrupt_produces_interrupted_terminal(tmp_path: Path) -> None:
    client = _client(tmp_path, "interrupt")
    await client.start()
    try:
        await _initialize(client)
        await _start_turn(client)
        await client.request("turn/interrupt", {"threadId": "thr_fixture", "turnId": "turn_fixture"})
        completed = await client.wait_for_notification("turn/completed", timeout_s=2)
        assert completed.params["turn"]["status"] == "interrupted"
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["crash_immediate", "crash_after_turn"])
async def test_child_crash_is_detected(tmp_path: Path, scenario: str) -> None:
    client = _client(tmp_path, scenario)
    await client.start()
    try:
        if scenario == "crash_immediate":
            with pytest.raises(JsonRpcChildExitedError):
                await _initialize(client)
        else:
            await _initialize(client)
            await _start_turn(client)
            with pytest.raises(JsonRpcChildExitedError):
                await client.wait_for_notification("turn/completed", timeout_s=1)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_invalid_json_and_unknown_server_request_fail_closed(tmp_path: Path) -> None:
    invalid = _client(tmp_path / "invalid", "invalid_json")
    await invalid.start()
    try:
        with pytest.raises(JsonRpcProtocolError, match="invalid JSON-RPC"):
            await _initialize(invalid)
    finally:
        await invalid.close()

    unknown = _client(tmp_path / "unknown", "unknown_server_request")
    await unknown.start()
    try:
        await _initialize(unknown)
        with pytest.raises(JsonRpcProtocolError, match="unknown server request"):
            await unknown.wait_for_notification("turn/completed", timeout_s=1)
    finally:
        await unknown.close()


@pytest.mark.asyncio
async def test_request_timeout_and_stderr_redaction(tmp_path: Path) -> None:
    hanging = _client(tmp_path / "hang", "hang_request", request_timeout_s=0.05)
    await hanging.start()
    try:
        await _initialize(hanging)
        with pytest.raises(JsonRpcTimeoutError, match="thread/start"):
            await hanging.request("thread/start", {})
    finally:
        await hanging.close()

    redacting = _client(tmp_path / "redact", "stderr_secret")
    await redacting.start()
    try:
        await _initialize(redacting)
        await _start_turn(redacting)
        await redacting.wait_for_notification("turn/completed", timeout_s=2)
    finally:
        evidence = await redacting.close()
    joined = "\n".join(evidence.stderr)
    assert "fixture-secret-value" not in joined
    assert str(tmp_path) not in joined
    assert "raw_prompt=hidden" not in joined


def test_recursive_redaction_removes_protocol_bodies_secrets_and_paths(tmp_path: Path) -> None:
    secret = "fixture-secret-value"
    raw = {"api_key": secret, "prompt": "private prompt", "safe": f"path={tmp_path} token={secret}", "nested": [{"reasoning": "hidden", "status": "completed"}]}
    encoded = json.dumps(redact_protocol_value(raw, secrets=(secret,), path_roots=(tmp_path,)))
    assert secret not in encoded
    assert str(tmp_path) not in encoded
    assert "private prompt" not in encoded
    assert "hidden" not in encoded
    assert "completed" in encoded


@pytest.mark.asyncio
async def test_fake_deepseek_responses_contract_maps_repair_fatal_and_failures() -> None:
    repair = await DeepSeekResponsesFixture("repair").collect()
    fatal = await DeepSeekResponsesFixture("fatal").collect()
    assert repair.terminal_status == "completed"
    assert [call["arguments"]["attempt"] for call in repair.tool_calls] == [1, 2]
    assert fatal.terminal_status == "failed"
    assert len(fatal.tool_calls) == 1
    with pytest.raises(DeepSeekFixtureError, match="provider_timeout"):
        await DeepSeekResponsesFixture("provider_timeout").collect(timeout_s=0.01)
    with pytest.raises(DeepSeekFixtureError, match="terminal"):
        await DeepSeekResponsesFixture("stream_interrupted").collect()
    with pytest.raises(DeepSeekFixtureError, match="unsupported Responses output item"):
        await DeepSeekResponsesFixture("invalid_event").collect()


def test_installed_codex_executable_probe_is_exact_when_available() -> None:
    executable = resolve_codex_executable()
    if executable is None:
        pytest.skip("Codex executable is not installed")
    probe = probe_codex_executable(executable)
    assert probe.status == "ready"
    assert probe.version is not None
    assert probe.executable_path == str(executable)


@pytest.mark.asyncio
async def test_isolated_root_cleanup_removes_all_state(tmp_path: Path) -> None:
    root = tmp_path / "cleanup"
    root.mkdir()
    (root / "state.jsonl").write_text("sensitive fixture", encoding="utf-8")
    await _remove_isolated_root(root)
    assert root.exists() is False


@pytest.mark.asyncio
async def test_real_smoke_refuses_to_run_without_explicit_approval(tmp_path: Path) -> None:
    with pytest.raises(PermissionError, match="explicit approval"):
        await run_real_deepseek_smoke(approved=False, root=tmp_path / "blocked", base_url="https://api.deepseek.example")


@pytest.mark.asyncio
async def test_installed_codex_offline_protocol_preflight(tmp_path: Path) -> None:
    executable = resolve_codex_executable()
    if executable is None:
        pytest.skip("Codex executable is not installed")
    result = await run_codex_protocol_preflight(root=tmp_path / "preflight", executable=executable)
    assert result.ready is True
    assert result.executable.version is not None
    assert result.codex_home_matched is True
    assert result.platform_family == "windows"
    assert result.model == "deepseek-flash"
    assert result.model_provider == "aearn_deepseek"
    assert result.thread_model_matched is True
    assert result.thread_provider_matched is True
    assert result.dynamic_tools_supported is True
    assert result.global_home_untouched_by_design is True
    assert "item/tool/call" in result.server_methods
    assert "turn/completed" in result.notifications
