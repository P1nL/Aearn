from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from app.agents.runtime import AgentRuntimePort, CodexAppServerRuntime, CodexRuntimeConfig, CodexRuntimeSupervisor, LearningPlanRuntimeToolRegistry, RuntimeBusyError, RuntimeEvent, RuntimeEventKind, RuntimeHealthStatus, RuntimeInput, RuntimeTerminalStatus, RuntimeThreadRequest, RuntimeToolCall, RuntimeToolDefinition, RuntimeToolResult, RuntimeTurnRequest
from app.agents.runtime.codex_config import CODEX_ENV_KEY, resolve_codex_executable
from app.agents.runtime.delta_coalescer import (
    RuntimeDeltaBudgetError,
    RuntimeDeltaCoalescer,
    RuntimeDeltaCoalescingConfig,
    RuntimeDeltaFlushReason,
)
from app.agents.runtime.codex_connection import ServerRequestHandler, StdioJsonRpcClient
from app.agents.runtime.codex_supervisor import RuntimeGenerationError, RuntimeProcessLock
from app.agents.runtime.worker_host import RuntimeTurnControlDirective, _run_controlled_turn
from app.services.learning.plan_tools import LearningPlanAgentToolResult, LearningPlanDraftToolInput, LearningPlanToolStatus

FIXTURE = Path(__file__).parent / "fixtures" / "codex_runtime" / "fake_app_server.py"


def _config(tmp_path: Path, *, enabled: bool = True, allowed_versions: frozenset[str] = frozenset()) -> CodexRuntimeConfig:
    executable = resolve_codex_executable()
    if executable is None:
        pytest.skip("Codex executable is not installed")
    return CodexRuntimeConfig(enabled=enabled, executable_path=executable, home_root=tmp_path / "codex-runtime", model="deepseek-v4-flash", model_provider="aearn_deepseek", base_url="https://api.deepseek.example", env_key=CODEX_ENV_KEY, allowed_versions=allowed_versions, startup_timeout_s=3, request_timeout_s=2, turn_timeout_s=10, shutdown_timeout_s=2, notification_queue_size=64)


def _factory(scenario: str):  # type: ignore[no-untyped-def]
    def create(config, home, env, tool_handler: ServerRequestHandler):  # type: ignore[no-untyped-def]
        return StdioJsonRpcClient([sys.executable, str(FIXTURE), "--scenario", scenario], cwd=home.workspace, env=env, notification_methods=("thread/started", "turn/started", "item/agentMessage/delta", "item/reasoning/textDelta", "item/reasoning/summaryTextDelta", "item/started", "item/completed", "turn/completed", "warning"), server_request_handlers={"item/tool/call": tool_handler}, request_timeout_s=config.request_timeout_s, server_request_timeout_s=config.request_timeout_s, notification_queue_size=config.notification_queue_size, secrets=(env.get(config.env_key, ""),), path_roots=(home.root,))
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
    tool_events = [
        event
        for event in result.events
        if event.kind in {RuntimeEventKind.TOOL_STARTED, RuntimeEventKind.TOOL_COMPLETED}
    ]
    assert tool_events and all(event.tool_name == "aearn_runtime_probe" for event in tool_events)
    assert all(event.input_sha256 is not None for event in tool_events)
    assert all(
        event.result_sha256 is not None
        for event in tool_events
        if event.kind is RuntimeEventKind.TOOL_COMPLETED
    )
    message_events = [event for event in result.events if event.kind is RuntimeEventKind.MESSAGE_COMPLETED]
    assert [(event.phase, event.visible_text) for event in message_events] == [
        ("commentary", "private commentary"),
        ("final_answer", "safe final"),
    ]
    assert [event.sequence for event in result.events] == list(range(1, len(result.events) + 1))
    encoded_events = json.dumps([
        {
            "kind": event.kind.value,
            "safe_code": event.safe_code,
            "tool_name": event.tool_name,
            "input_sha256": event.input_sha256,
            "result_sha256": event.result_sha256,
        }
        for event in result.events
    ])
    assert "attempt" not in encoded_events
    assert "fixture-secret" not in encoded_events
    resumed = await runtime.resume_thread(thread.thread_id)
    assert resumed.thread_id == thread.thread_id
    assert resumed.generation == thread.generation
    await runtime.steer(thread, "turn_control", (RuntimeInput("steer"),))
    await runtime.interrupt(thread, "turn_control")
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_adapter_maps_local_compaction_and_raw_item_phases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CODEX_ENV_KEY, "fixture-secret")
    supervisor = CodexRuntimeSupervisor(
        _config(tmp_path),
        connection_factory=_factory("compaction"),
    )
    runtime = CodexAppServerRuntime(supervisor)
    thread = await runtime.start_thread(RuntimeThreadRequest(cwd=str(tmp_path)))
    await runtime.compact_thread(thread)
    result = await runtime.run_turn(
        RuntimeTurnRequest(thread, (RuntimeInput("Continue after local compaction."),), RepairRegistry())
    )

    assert result.terminal_status is RuntimeTerminalStatus.COMPLETED
    assert [event.kind for event in result.events].count(RuntimeEventKind.CONTEXT_COMPACTION_STARTED) == 1
    assert [event.kind for event in result.events].count(RuntimeEventKind.CONTEXT_COMPACTION_COMPLETED) == 1
    reasoning_deltas = [event for event in result.events if event.kind is RuntimeEventKind.REASONING_DELTA]
    assert [event.visible_text for event in reasoning_deltas] == [
        "先读取服务端事实。\n",
        "再确认缺失字段。",
    ]
    reasoning_completed = [event for event in result.events if event.kind is RuntimeEventKind.REASONING_COMPLETED]
    assert len(reasoning_completed) == 1
    assert reasoning_completed[0].visible_text is None
    assert reasoning_completed[0].content_sha256 is None
    assert [event.visible_text for event in result.events if event.kind is RuntimeEventKind.REASONING_SUMMARY_DELTA] == [
        "private summary"
    ]
    message_deltas = [event for event in result.events if event.kind is RuntimeEventKind.MESSAGE_DELTA]
    assert [event.phase for event in message_deltas] == ["final_answer"]
    assert [event.visible_text for event in message_deltas] == ["只询问学习目标。"]
    assert message_deltas[0].source_delta_count == 2
    completed = [event for event in result.events if event.kind is RuntimeEventKind.MESSAGE_COMPLETED]
    assert [(event.phase, event.visible_text) for event in completed] == [
        ("commentary", "private commentary"),
        ("final_answer", "只询问学习目标。"),
    ]
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_codex_request_user_input_is_declined_without_killing_the_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CODEX_ENV_KEY, "fixture-secret")
    supervisor = CodexRuntimeSupervisor(
        _config(tmp_path),
        connection_factory=_factory("request_user_input"),
    )
    runtime = CodexAppServerRuntime(supervisor)
    thread = await runtime.start_thread(RuntimeThreadRequest(cwd=str(tmp_path)))
    result = await runtime.run_turn(
        RuntimeTurnRequest(thread, (RuntimeInput("Collect planning facts safely."),), RepairRegistry())
    )

    assert result.terminal_status is RuntimeTerminalStatus.COMPLETED
    assert supervisor.require_connection(thread.generation).fatal_error is None
    assert [event.visible_text for event in result.events if event.kind is RuntimeEventKind.MESSAGE_COMPLETED][-1] == "safe final"
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
    event_stream = runtime.events()
    try:
        result = await runtime.run_turn(RuntimeTurnRequest(thread, (RuntimeInput("backpressure"),), RepairRegistry()))
    finally:
        await event_stream.aclose()  # type: ignore[attr-defined]
    assert result.terminal_status is RuntimeTerminalStatus.UNAVAILABLE
    assert result.safe_error_code == "runtime_event_backpressure_exhausted"
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_controlled_turn_event_subscription_drops_previous_turn_backlog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CODEX_ENV_KEY, "fixture-secret")
    supervisor = CodexRuntimeSupervisor(
        _config(tmp_path),
        connection_factory=_factory("burst_turns"),
    )
    runtime = CodexAppServerRuntime(supervisor, event_queue_size=16)
    thread = await runtime.start_thread(RuntimeThreadRequest(cwd=str(tmp_path)))

    def no_control(_turn_id: str, applied_revision: int) -> RuntimeTurnControlDirective:
        return RuntimeTurnControlDirective(applied_revision)

    first_observed: list[tuple[str | None, int]] = []

    def observe_first(event, sequence: int) -> None:  # type: ignore[no-untyped-def]
        time.sleep(0.001)
        first_observed.append((event.turn_id, sequence))

    first = await _run_controlled_turn(
        runtime,
        RuntimeTurnRequest(thread, (RuntimeInput("first burst"),), RepairRegistry()),
        control_reader=no_control,
        initial_input_revision=1,
        event_observer=observe_first,
        poll_interval_s=0.001,
    )
    resumed = await runtime.resume_thread(thread.thread_id)
    second_observed: list[tuple[str | None, int]] = []
    second = await _run_controlled_turn(
        runtime,
        RuntimeTurnRequest(resumed, (RuntimeInput("second burst"),), RepairRegistry()),
        control_reader=no_control,
        initial_input_revision=1,
        event_observer=lambda event, sequence: second_observed.append(
            (event.turn_id, sequence)
        ),
        poll_interval_s=0.001,
    )

    assert first.terminal_status is RuntimeTerminalStatus.COMPLETED
    assert second.terminal_status is RuntimeTerminalStatus.COMPLETED
    assert first.turn_id != second.turn_id
    assert first_observed
    assert second_observed
    assert {turn_id for turn_id, _sequence in second_observed if turn_id is not None} == {
        second.turn_id
    }
    assert len({sequence for _turn_id, sequence in second_observed}) == len(second_observed)

    other_thread = await runtime.start_thread(RuntimeThreadRequest(cwd=str(tmp_path)))
    third_observed: list[tuple[str | None, int]] = []
    third = await _run_controlled_turn(
        runtime,
        RuntimeTurnRequest(other_thread, (RuntimeInput("other conversation"),), RepairRegistry()),
        control_reader=no_control,
        initial_input_revision=1,
        event_observer=lambda event, sequence: third_observed.append(
            (event.turn_id, sequence)
        ),
        poll_interval_s=0.001,
    )
    assert third.terminal_status is RuntimeTerminalStatus.COMPLETED
    assert other_thread.thread_id != thread.thread_id
    assert {turn_id for turn_id, _sequence in third_observed if turn_id is not None} == {
        third.turn_id
    }
    assert len({sequence for _turn_id, sequence in third_observed}) == len(third_observed)
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


def _source_delta(
    *,
    sequence: int,
    kind: RuntimeEventKind = RuntimeEventKind.REASONING_DELTA,
    item_id: str = "reasoning-1",
    text: str = "x",
    phase: str | None = None,
    item_index: int = 0,
) -> RuntimeEvent:
    digest = __import__("hashlib").sha256(text.encode("utf-8")).hexdigest()
    return RuntimeEvent(
        kind,
        "thread-coalescer",
        "turn-coalescer",
        item_id=item_id,
        visible_text=text,
        content_sha256=digest,
        item_type="reasoning" if kind is RuntimeEventKind.REASONING_DELTA else "agentMessage",
        phase=phase,
        item_index=item_index,
        source_sequence_start=sequence,
        source_sequence_end=sequence,
        source_delta_count=1,
        source_content_sha256=digest,
    )


def test_runtime_delta_coalescer_preserves_text_and_all_boundaries() -> None:
    coalescer = RuntimeDeltaCoalescer(
        RuntimeDeltaCoalescingConfig(
            flush_delay_ms=25,
            flush_chars=32,
            flush_bytes=128,
            max_pending_bytes=256,
        )
    )
    projected: list[RuntimeEvent] = []
    projected.extend(coalescer.push(_source_delta(sequence=1, text="A"), now=0.0))
    projected.extend(coalescer.push(_source_delta(sequence=2, text="🙂"), now=0.001))
    projected.extend(
        coalescer.push(
            _source_delta(sequence=3, item_id="reasoning-2", text="B"),
            now=0.002,
        )
    )
    projected.extend(
        coalescer.push(
            _source_delta(
                sequence=4,
                kind=RuntimeEventKind.MESSAGE_DELTA,
                item_id="answer-1",
                text="C",
                phase="final_answer",
            ),
            now=0.003,
        )
    )
    projected.extend(coalescer.flush(RuntimeDeltaFlushReason.TERMINAL))

    assert [event.visible_text for event in projected] == ["A🙂", "B", "C"]
    assert [event.source_delta_count for event in projected] == [2, 1, 1]
    assert [event.source_sequence_start for event in projected] == [1, 3, 4]
    assert [event.source_sequence_end for event in projected] == [2, 3, 4]
    assert [event.projection_sequence for event in projected] == [1, 2, 3]


def test_runtime_delta_coalescer_flushes_sparse_delta_on_timer() -> None:
    coalescer = RuntimeDeltaCoalescer(
        RuntimeDeltaCoalescingConfig(
            flush_delay_ms=25,
            flush_chars=32,
            flush_bytes=128,
            max_pending_bytes=256,
        )
    )
    assert coalescer.push(_source_delta(sequence=1, text="sparse"), now=1.0) == ()
    assert coalescer.flush_due(now=1.024) == ()
    flushed = coalescer.flush_due(now=1.025)
    assert len(flushed) == 1
    assert flushed[0].visible_text == "sparse"
    assert dict(coalescer.metrics().flush_reasons) == {"timer": 1}


def test_runtime_delta_coalescer_feature_off_keeps_source_and_projection_separate() -> None:
    coalescer = RuntimeDeltaCoalescer(
        RuntimeDeltaCoalescingConfig(
            enabled=False,
            flush_delay_ms=25,
            flush_chars=32,
            flush_bytes=128,
            max_pending_bytes=256,
        )
    )
    projected = [
        coalescer.push(_source_delta(sequence=index, text=str(index)), now=float(index))[0]
        for index in range(1, 4)
    ]
    assert [event.visible_text for event in projected] == ["1", "2", "3"]
    assert [event.source_sequence_start for event in projected] == [1, 2, 3]
    assert [event.projection_sequence for event in projected] == [1, 2, 3]


def test_runtime_delta_coalescer_rejects_one_oversized_pending_delta() -> None:
    coalescer = RuntimeDeltaCoalescer(
        RuntimeDeltaCoalescingConfig(
            flush_delay_ms=25,
            flush_chars=4_096,
            flush_bytes=16_000,
            max_pending_bytes=16_000,
        )
    )
    with pytest.raises(RuntimeDeltaBudgetError, match="runtime_pending_bytes_exhausted"):
        coalescer.push(_source_delta(sequence=1, text="界" * 6_000), now=0.0)


@pytest.mark.asyncio
async def test_adapter_coalesces_five_thousand_single_character_reasoning_deltas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CODEX_ENV_KEY, "fixture-secret")
    supervisor = CodexRuntimeSupervisor(
        _config(tmp_path),
        connection_factory=_factory("five_thousand_deltas"),
    )
    runtime = CodexAppServerRuntime(supervisor)
    thread = await runtime.start_thread(RuntimeThreadRequest(cwd=str(tmp_path)))
    result = await runtime.run_turn(
        RuntimeTurnRequest(
            thread,
            (RuntimeInput("Generate a long safe planning trace."),),
            RepairRegistry(),
        )
    )

    assert result.terminal_status is RuntimeTerminalStatus.COMPLETED
    assert result.safe_error_code != "runtime_event_budget_exhausted"
    assert result.metrics.source_delta_count == 5_000
    reasoning = [
        event for event in result.events
        if event.kind is RuntimeEventKind.REASONING_DELTA
    ]
    assert "".join(event.visible_text or "" for event in reasoning) == "思" * 5_000
    assert sum(event.source_delta_count for event in reasoning) == 5_000
    assert len(reasoning) < 20
    assert [event.projection_sequence for event in result.events] == list(
        range(1, len(result.events) + 1)
    )
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_adapter_timer_flushes_sparse_reasoning_without_waiting_for_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CODEX_ENV_KEY, "fixture-secret")
    supervisor = CodexRuntimeSupervisor(
        _config(tmp_path),
        connection_factory=_factory("sparse_deltas"),
    )
    runtime = CodexAppServerRuntime(supervisor)
    thread = await runtime.start_thread(RuntimeThreadRequest(cwd=str(tmp_path)))
    observed: list[str] = []

    async def consume() -> None:
        stream = runtime.events().__aiter__()
        try:
            while True:
                event = await anext(stream)
                if event.kind is RuntimeEventKind.REASONING_DELTA:
                    observed.append(event.visible_text or "")
                if event.kind is RuntimeEventKind.TURN_COMPLETED:
                    return
        finally:
            await stream.aclose()  # type: ignore[attr-defined]

    consumer = asyncio.create_task(consume())
    result = await runtime.run_turn(
        RuntimeTurnRequest(thread, (RuntimeInput("Stream sparse reasoning."),), RepairRegistry())
    )
    await consumer
    assert result.terminal_status is RuntimeTerminalStatus.COMPLETED
    assert observed == ["first", "second"]
    assert dict(result.metrics.flush_reasons)["timer"] >= 1
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_adapter_feature_off_projects_every_delta_without_restoring_legacy_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CODEX_ENV_KEY, "fixture-secret")
    config = replace(_config(tmp_path), delta_coalescing_enabled=False)
    supervisor = CodexRuntimeSupervisor(
        config,
        connection_factory=_factory("five_thousand_deltas"),
    )
    runtime = CodexAppServerRuntime(supervisor)
    thread = await runtime.start_thread(RuntimeThreadRequest(cwd=str(tmp_path)))
    result = await runtime.run_turn(
        RuntimeTurnRequest(thread, (RuntimeInput("Project raw deltas safely."),), RepairRegistry())
    )

    assert result.terminal_status is RuntimeTerminalStatus.COMPLETED
    assert result.safe_error_code != "runtime_event_budget_exhausted"
    assert len(
        [event for event in result.events if event.kind is RuntimeEventKind.REASONING_DELTA]
    ) == 5_000
    await runtime.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenario", "config_overrides", "safe_code"),
    [
        (
            "five_thousand_deltas",
            {"max_raw_notifications": 5_000},
            "runtime_raw_notification_runaway",
        ),
        (
            "many_items",
            {"max_items": 16},
            "runtime_item_budget_exhausted",
        ),
        (
            "repair",
            {"max_tools": 1},
            "runtime_tool_budget_exhausted",
        ),
        (
            "text_budget",
            {"max_visible_text_chars": 16_000},
            "runtime_text_budget_exhausted",
        ),
        (
            "slow_turn",
            {"turn_timeout_s": 0.05},
            "runtime_turn_time_exhausted",
        ),
    ],
)
async def test_adapter_semantic_runtime_budgets_have_independent_safe_codes(
    scenario: str,
    config_overrides: dict[str, object],
    safe_code: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CODEX_ENV_KEY, "fixture-secret")
    config = replace(_config(tmp_path), **config_overrides)
    supervisor = CodexRuntimeSupervisor(config, connection_factory=_factory(scenario))
    runtime = CodexAppServerRuntime(supervisor)
    tools = (
        RuntimeToolDefinition(
            "aearn_runtime_probe",
            "Validate semantic Runtime budgets.",
            {"type": "object"},
        ),
    )
    thread = await runtime.start_thread(RuntimeThreadRequest(cwd=str(tmp_path), tools=tools))
    result = await runtime.run_turn(
        RuntimeTurnRequest(thread, (RuntimeInput("Exercise a bounded Runtime."),), RepairRegistry())
    )

    assert result.terminal_status is RuntimeTerminalStatus.UNAVAILABLE
    assert result.safe_error_code == safe_code
    assert result.safe_error_code != "runtime_event_budget_exhausted"
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_learning_plan_tool_repair_can_continue_through_more_than_two_thousand_deltas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CODEX_ENV_KEY, "fixture-secret")
    supervisor = CodexRuntimeSupervisor(
        _config(tmp_path),
        connection_factory=_factory("long_learning_plan_repair"),
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
            (RuntimeInput("Repair the draft, then continue reasoning."),),
            registry,
        )
    )

    assert result.terminal_status is RuntimeTerminalStatus.COMPLETED
    assert registry.repair_count == 1
    assert result.metrics.source_delta_count == 2_500
    assert result.safe_error_code != "runtime_event_budget_exhausted"
    assert "".join(
        event.visible_text or ""
        for event in result.events
        if event.kind is RuntimeEventKind.REASONING_DELTA
    ) == "r" * 2_500
    await runtime.shutdown()
