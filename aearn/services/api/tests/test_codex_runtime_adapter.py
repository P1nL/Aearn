from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from app.agents.runtime import AgentRuntimePort, CodexAppServerRuntime, CodexRuntimeConfig, CodexRuntimeSupervisor, LearningPlanRuntimeToolRegistry, RuntimeBusyError, RuntimeEventKind, RuntimeHealthStatus, RuntimeInput, RuntimeTerminalStatus, RuntimeThreadRequest, RuntimeToolCall, RuntimeToolDefinition, RuntimeToolResult, RuntimeTurnRequest
from app.agents.runtime.codex_config import CODEX_ENV_KEY, resolve_codex_executable
from app.agents.runtime.codex_connection import ServerRequestHandler, StdioJsonRpcClient
from app.agents.runtime.codex_supervisor import RuntimeGenerationError, RuntimeProcessLock
from app.services.learning.plan_tools import LearningPlanAgentToolResult, LearningPlanDraftToolInput, LearningPlanToolStatus

FIXTURE = Path(__file__).parent / "fixtures" / "codex_runtime" / "fake_app_server.py"


def _config(tmp_path: Path, *, enabled: bool = True, allowed_versions: frozenset[str] = frozenset()) -> CodexRuntimeConfig:
    executable = resolve_codex_executable()
    if executable is None:
        pytest.skip("Codex executable is not installed")
    return CodexRuntimeConfig(enabled=enabled, executable_path=executable, home_root=tmp_path / "codex-runtime", model="deepseek-v4-flash", model_provider="aearn_deepseek", base_url="https://api.deepseek.example", env_key=CODEX_ENV_KEY, allowed_versions=allowed_versions, startup_timeout_s=3, request_timeout_s=2, turn_timeout_s=2, shutdown_timeout_s=2, notification_queue_size=64)


def _factory(scenario: str):  # type: ignore[no-untyped-def]
    def create(config, home, env, tool_handler: ServerRequestHandler):  # type: ignore[no-untyped-def]
        return StdioJsonRpcClient([sys.executable, str(FIXTURE), "--scenario", scenario], cwd=home.workspace, env=env, notification_methods=("thread/started", "turn/started", "item/agentMessage/delta", "item/started", "item/completed", "turn/completed", "warning"), server_request_handlers={"item/tool/call": tool_handler}, request_timeout_s=config.request_timeout_s, server_request_timeout_s=config.request_timeout_s, notification_queue_size=config.notification_queue_size, secrets=(env.get(config.env_key, ""),), path_roots=(home.root,))
    return create


class RepairRegistry:
    def __init__(self) -> None:
        self.calls: list[RuntimeToolCall] = []

    async def invoke(self, call: RuntimeToolCall) -> RuntimeToolResult:
        self.calls.append(call)
        attempt = call.arguments.get("attempt")
        status = "repairable_invalid" if attempt == 1 else "completed"
        return RuntimeToolResult(True, json.dumps({"status": status}), safe_code=status)


@pytest.mark.asyncio
async def test_runtime_is_disabled_and_does_not_start_child(tmp_path: Path) -> None:
    supervisor = CodexRuntimeSupervisor(_config(tmp_path, enabled=False), connection_factory=_factory("ready"))
    health = await supervisor.start()
    assert health.status is RuntimeHealthStatus.UNAVAILABLE
    assert health.safe_error_code == "runtime_disabled"
    assert health.generation == 0


@pytest.mark.asyncio
async def test_supervisor_preflight_restart_generation_and_single_owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CODEX_ENV_KEY, "fixture-secret")
    config = _config(tmp_path)
    first = CodexRuntimeSupervisor(config, connection_factory=_factory("ready"))
    second = CodexRuntimeSupervisor(config, connection_factory=_factory("ready"))

    first_health = await first.start()
    assert first_health.status is RuntimeHealthStatus.READY
    assert first_health.generation == 1
    assert first_health.model == "deepseek-v4-flash"
    assert "fixture-secret" not in json.dumps(first_health.metadata)

    conflict = await second.start()
    assert conflict.status is RuntimeHealthStatus.UNAVAILABLE
    assert conflict.safe_error_code == "ownership_conflict"

    await first.shutdown()
    second_health = await second.start()
    assert second_health.status is RuntimeHealthStatus.READY
    assert second_health.generation == 1
    await second.shutdown()
    restarted = await second.start()
    assert restarted.generation == 2
    await second.shutdown()


@pytest.mark.asyncio
async def test_supervisor_rejects_unsupported_version_and_missing_credential(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CODEX_ENV_KEY, raising=False)
    missing = CodexRuntimeSupervisor(_config(tmp_path / "missing"), connection_factory=_factory("ready"))
    missing_health = await missing.start()
    assert missing_health.safe_error_code == "provider_credential_missing"

    monkeypatch.setenv(CODEX_ENV_KEY, "fixture-secret")
    unsupported_config = replace(_config(tmp_path / "version"), allowed_versions=frozenset({"0.0.0-unsupported"}))
    unsupported = CodexRuntimeSupervisor(unsupported_config, connection_factory=_factory("ready"))
    unsupported_health = await unsupported.start()
    assert unsupported_health.safe_error_code == "unsupported_codex_version"


@pytest.mark.asyncio
async def test_adapter_maps_repair_events_without_exposing_tool_arguments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CODEX_ENV_KEY, "fixture-secret")
    supervisor = CodexRuntimeSupervisor(_config(tmp_path), connection_factory=_factory("repair"))
    runtime = CodexAppServerRuntime(supervisor)
    assert isinstance(runtime, AgentRuntimePort)
    thread = await runtime.start_thread(RuntimeThreadRequest(cwd=str(tmp_path), tools=(RuntimeToolDefinition("aearn_runtime_probe", "Validate runtime repair.", {"type": "object", "properties": {"attempt": {"type": "integer"}}}),)))
    registry = RepairRegistry()
    result = await runtime.run_turn(RuntimeTurnRequest(thread, (RuntimeInput("Use the runtime probe."),), registry))

    assert result.terminal_status is RuntimeTerminalStatus.COMPLETED
    assert [call.arguments["attempt"] for call in registry.calls] == [1, 2]
    assert any(event.kind is RuntimeEventKind.TOOL_STARTED for event in result.events)
    assert any(event.kind is RuntimeEventKind.MESSAGE_COMPLETED and event.visible_text == "safe final" for event in result.events)
    encoded_events = json.dumps([{"kind": event.kind.value, "safe_code": event.safe_code} for event in result.events])
    assert "attempt" not in encoded_events
    assert "fixture-secret" not in encoded_events
    resumed = await runtime.resume_thread(thread.thread_id)
    assert resumed.thread_id == thread.thread_id
    assert resumed.generation == thread.generation
    await runtime.steer(thread, "turn_control", (RuntimeInput("steer"),))
    await runtime.interrupt(thread, "turn_control")
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_adapter_rejects_concurrent_writer_and_stale_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CODEX_ENV_KEY, "fixture-secret")
    supervisor = CodexRuntimeSupervisor(_config(tmp_path), connection_factory=_factory("slow_turn"))
    runtime = CodexAppServerRuntime(supervisor)
    thread = await runtime.start_thread(RuntimeThreadRequest(cwd=str(tmp_path)))
    first = asyncio.create_task(runtime.run_turn(RuntimeTurnRequest(thread, (RuntimeInput("first"),), RepairRegistry())))
    await asyncio.sleep(0.05)
    with pytest.raises(RuntimeBusyError, match="writer_busy"):
        await runtime.run_turn(RuntimeTurnRequest(thread, (RuntimeInput("second"),), RepairRegistry()))
    assert (await first).terminal_status is RuntimeTerminalStatus.COMPLETED
    await runtime.shutdown()
    await runtime.start()
    with pytest.raises(RuntimeGenerationError, match="stale_runtime_generation"):
        await runtime.run_turn(RuntimeTurnRequest(thread, (RuntimeInput("stale"),), RepairRegistry()))
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_child_crash_invalidates_generation_and_pending_turn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CODEX_ENV_KEY, "fixture-secret")
    supervisor = CodexRuntimeSupervisor(_config(tmp_path), connection_factory=_factory("crash_on_turn"))
    runtime = CodexAppServerRuntime(supervisor)
    thread = await runtime.start_thread(RuntimeThreadRequest(cwd=str(tmp_path)))
    result = await runtime.run_turn(RuntimeTurnRequest(thread, (RuntimeInput("crash"),), RepairRegistry()))
    assert result.terminal_status is RuntimeTerminalStatus.UNAVAILABLE
    assert result.safe_error_code == "runtime_connection_failed"
    health = await runtime.health()
    assert health.status is RuntimeHealthStatus.UNAVAILABLE
    restarted = await runtime.start()
    assert restarted.status is RuntimeHealthStatus.READY
    assert restarted.generation == 2
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_runtime_event_backpressure_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CODEX_ENV_KEY, "fixture-secret")
    supervisor = CodexRuntimeSupervisor(_config(tmp_path), connection_factory=_factory("repair"))
    runtime = CodexAppServerRuntime(supervisor, event_queue_size=1)
    thread = await runtime.start_thread(RuntimeThreadRequest(cwd=str(tmp_path), tools=(RuntimeToolDefinition("aearn_runtime_probe", "Validate runtime repair.", {"type": "object"}),)))
    result = await runtime.run_turn(RuntimeTurnRequest(thread, (RuntimeInput("backpressure"),), RepairRegistry()))
    assert result.terminal_status is RuntimeTerminalStatus.UNAVAILABLE
    assert result.safe_error_code == "runtime_event_backpressure_exhausted"
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_formal_connection_redacts_stderr_and_ignores_reasoning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CODEX_ENV_KEY, "fixture-secret")
    supervisor = CodexRuntimeSupervisor(_config(tmp_path), connection_factory=_factory("stderr_secret"))
    runtime = CodexAppServerRuntime(supervisor)
    thread = await runtime.start_thread(RuntimeThreadRequest(cwd=str(tmp_path)))
    result = await runtime.run_turn(RuntimeTurnRequest(thread, (RuntimeInput("safe"),), RepairRegistry()))
    await asyncio.sleep(0.05)
    evidence = supervisor.require_connection(thread.generation).evidence()
    encoded = "\n".join(evidence.stderr)
    assert "fixture-secret" not in encoded
    assert str(tmp_path) not in encoded
    assert all(event.safe_code != "reasoning" for event in result.events)
    await runtime.shutdown()


def test_runtime_process_lock_rejects_second_os_owner(tmp_path: Path) -> None:
    first = RuntimeProcessLock(tmp_path / "runtime.lock")
    second = RuntimeProcessLock(tmp_path / "runtime.lock")
    assert first.acquire() is True
    assert second.acquire() is False
    first.release()
    assert second.acquire() is True
    second.release()


class FakeLearningPlanToolService:
    def __init__(self) -> None:
        self.drafts: list[LearningPlanDraftToolInput] = []

    def read_context(self) -> LearningPlanAgentToolResult:
        return LearningPlanAgentToolResult(
            status=LearningPlanToolStatus.COMPLETED,
            code="planning_context_ready",
            data={"facts_revision": 7, "missing_facts": []},
        )

    def draft(self, tool_input: LearningPlanDraftToolInput) -> LearningPlanAgentToolResult:
        self.drafts.append(tool_input)
        return LearningPlanAgentToolResult(
            status=LearningPlanToolStatus.COMPLETED,
            code="learning_plan_draft_completed",
            data={"draft_id": "draft-safe", "draft_version": 1, "content_hash": "a" * 64},
        )


@pytest.mark.asyncio
async def test_runtime_learning_plan_tool_repairs_typed_input_in_same_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CODEX_ENV_KEY, "fixture-secret")
    supervisor = CodexRuntimeSupervisor(
        _config(tmp_path),
        connection_factory=_factory("learning_plan_repair"),
    )
    runtime = CodexAppServerRuntime(supervisor)
    service = FakeLearningPlanToolService()
    registry = LearningPlanRuntimeToolRegistry(service)
    thread = await runtime.start_thread(
        RuntimeThreadRequest(cwd=str(tmp_path), tools=registry.definitions)
    )
    result = await runtime.run_turn(
        RuntimeTurnRequest(
            thread,
            (RuntimeInput("Read planning context and create a typed draft."),),
            registry,
        )
    )

    assert result.terminal_status is RuntimeTerminalStatus.COMPLETED
    assert [item.status for item in registry.results] == [
        LearningPlanToolStatus.COMPLETED,
        LearningPlanToolStatus.REPAIRABLE_INVALID,
        LearningPlanToolStatus.COMPLETED,
    ]
    assert registry.repair_count == 1
    assert len(service.drafts) == 1
    assert [module.stable_key for module in service.drafts[0].modules] == [
        "foundations",
        "automation",
    ]
    await runtime.shutdown()


class StatusLearningPlanToolService(FakeLearningPlanToolService):
    def __init__(self, status: LearningPlanToolStatus, *, replayed: bool = False) -> None:
        super().__init__()
        self._status = status
        self._replayed = replayed

    def read_context(self) -> LearningPlanAgentToolResult:
        return LearningPlanAgentToolResult(
            status=self._status,
            code=f"safe_{self._status.value}",
        )

    def draft(self, tool_input: LearningPlanDraftToolInput) -> LearningPlanAgentToolResult:
        self.drafts.append(tool_input)
        return LearningPlanAgentToolResult(
            status=self._status,
            code=f"safe_{self._status.value}",
            data={"draft_id": "draft-safe", "receipt": "b" * 64},
            replayed=self._replayed,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "terminal"),
    [
        (LearningPlanToolStatus.AWAITING_USER, RuntimeTerminalStatus.COMPLETED),
        (LearningPlanToolStatus.CONFLICT, RuntimeTerminalStatus.COMPLETED),
        (LearningPlanToolStatus.POLICY_BLOCKED, RuntimeTerminalStatus.FAILED),
        (LearningPlanToolStatus.UNAVAILABLE, RuntimeTerminalStatus.FAILED),
        (LearningPlanToolStatus.FATAL, RuntimeTerminalStatus.FAILED),
    ],
)
async def test_runtime_learning_plan_tool_status_controls_fake_turn_terminal(
    status: LearningPlanToolStatus,
    terminal: RuntimeTerminalStatus,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CODEX_ENV_KEY, "fixture-secret")
    supervisor = CodexRuntimeSupervisor(
        _config(tmp_path),
        connection_factory=_factory("learning_plan_context"),
    )
    runtime = CodexAppServerRuntime(supervisor)
    registry = LearningPlanRuntimeToolRegistry(StatusLearningPlanToolService(status))
    thread = await runtime.start_thread(
        RuntimeThreadRequest(cwd=str(tmp_path), tools=registry.definitions)
    )
    result = await runtime.run_turn(
        RuntimeTurnRequest(thread, (RuntimeInput("Read context."),), registry)
    )
    assert result.terminal_status is terminal
    assert registry.results[0].status is status
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_runtime_learning_plan_tool_timeout_fails_fake_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CODEX_ENV_KEY, "fixture-secret")
    supervisor = CodexRuntimeSupervisor(
        _config(tmp_path),
        connection_factory=_factory("learning_plan_context"),
    )
    runtime = CodexAppServerRuntime(supervisor)
    moments = iter((0.0, 31.0))
    registry = LearningPlanRuntimeToolRegistry(
        StatusLearningPlanToolService(LearningPlanToolStatus.COMPLETED),
        clock=lambda: next(moments),
    )
    thread = await runtime.start_thread(
        RuntimeThreadRequest(cwd=str(tmp_path), tools=registry.definitions)
    )
    result = await runtime.run_turn(
        RuntimeTurnRequest(thread, (RuntimeInput("Read context."),), registry)
    )
    assert result.terminal_status is RuntimeTerminalStatus.FAILED
    assert registry.results[0].code == "tool_deadline_exhausted"
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_runtime_learning_plan_tool_duplicate_replay_keeps_one_safe_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CODEX_ENV_KEY, "fixture-secret")
    supervisor = CodexRuntimeSupervisor(
        _config(tmp_path),
        connection_factory=_factory("learning_plan_duplicate"),
    )
    runtime = CodexAppServerRuntime(supervisor)
    service = StatusLearningPlanToolService(
        LearningPlanToolStatus.COMPLETED,
        replayed=True,
    )
    registry = LearningPlanRuntimeToolRegistry(service)
    thread = await runtime.start_thread(
        RuntimeThreadRequest(cwd=str(tmp_path), tools=registry.definitions)
    )
    result = await runtime.run_turn(
        RuntimeTurnRequest(thread, (RuntimeInput("Replay the same draft."),), registry)
    )
    assert result.terminal_status is RuntimeTerminalStatus.COMPLETED
    assert len(service.drafts) == 2
    assert registry.results[0].content() == registry.results[1].content()
    assert all(item.replayed for item in registry.results)
    await runtime.shutdown()
