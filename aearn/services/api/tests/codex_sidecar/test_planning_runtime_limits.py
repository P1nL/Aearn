"""Offline budget/stop protocol regressions; no process or model is started."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import replace
from pathlib import Path

import pytest

from app.agents.runtime import (
    CodexAppServerRuntime, CodexRuntimeConfig, CodexRuntimeSupervisor,
    LearningPlanRuntimeToolRegistry, LearningPlanToolBudget,
    RuntimeHealthSnapshot, RuntimeHealthStatus, RuntimeInput,
    RuntimeTerminalStatus, RuntimeThreadHandle, RuntimeToolCall,
    RuntimeToolRegistry, RuntimeToolResult, RuntimeTurnRequest,
)
from app.agents.runtime import codex_adapter
from app.agents.runtime.codex_connection import JsonRpcNotification, JsonRpcTimeoutError
from app.agents.runtime.codex_supervisor import RuntimeUnavailableError
from app.services.learning.plan_tools import PLANNING_CONTEXT_TOOL_NAME, LearningPlanToolStatus
from app.services.tutor.codex_dispatcher import _direction_server_terminalization_allowed
from app.agents.runtime.contracts import RuntimeTurnResult
from tests.codex_sidecar.test_codex_learning_plan_tools import (
    FakeService, _awaiting_data, _call, _result,
)


def _notification(method: str, **params: object) -> JsonRpcNotification:
    return JsonRpcNotification(method, {"threadId": "private-thread", "turnId": "private-turn", **params})


def _terminal(turn_id: str = "private-turn") -> JsonRpcNotification:
    return _notification("turn/completed", turn={"id": turn_id, "status": "interrupted"})


def _text(channel: str, length: int, *, completed: bool = False) -> JsonRpcNotification:
    item_type = "agentMessage" if channel == "message" else "reasoning"
    if completed:
        return _notification("item/completed", item={
            "id": channel, "type": item_type, "text": "字" * length, "phase": "final_answer",
        })
    method = {
        "message": "item/agentMessage/delta",
        "reasoning": "item/reasoning/textDelta",
        "summary": "item/reasoning/summaryTextDelta",
    }[channel]
    return _notification(method, itemId=channel, delta="字" * length, phase="final_answer")


class CountingRegistry:
    def __init__(self, *, fatal: bool = False) -> None:
        self.calls = 0
        self.fatal = fatal

    async def invoke(self, call: RuntimeToolCall) -> RuntimeToolResult:
        self.calls += 1
        return RuntimeToolResult(not self.fatal, '{"status":"fatal"}' if self.fatal else '{}',
                                 "tool_call_budget_exhausted" if self.fatal else None)


class FakeAppServer(CodexRuntimeSupervisor):
    """In-memory App Server boundary with independently controlled ACK/terminal."""

    def __init__(self, tmp_path: Path, notifications: list[JsonRpcNotification], *,
                 stop_mode: str = "terminal", tool_call: bool = False,
                 start_delay: float = 0.0, shutdown_fails: bool = False) -> None:
        super().__init__(CodexRuntimeConfig(
            enabled=False, executable_path=None, home_root=tmp_path, model="fake",
            model_provider="fake", base_url="https://invalid.example", env_key="FAKE",
            allowed_versions=frozenset(), startup_timeout_s=1, request_timeout_s=1,
            turn_timeout_s=1, shutdown_timeout_s=1, notification_queue_size=64,
        ))
        self.initial = notifications
        self.queue: asyncio.Queue[JsonRpcNotification] = asyncio.Queue()
        self.stop_mode = stop_mode
        self.tool_call = tool_call
        self.start_delay = start_delay
        self.shutdown_fails = shutdown_fails
        self.registry: RuntimeToolRegistry | None = None
        self.timeline: list[str] = []
        self.started = asyncio.Event()
        self.interrupted = asyncio.Event()
        self.stopped = False
        self.late_result: RuntimeToolResult | None = None

    def require_connection(self, generation=None):  # type: ignore[no-untyped-def]
        if self.stopped:
            raise RuntimeUnavailableError("runtime_stopped")
        return self

    def prepare_turn(self, thread_id, registry, generation):  # type: ignore[no-untyped-def]
        self.registry = registry

    def register_turn(self, thread_id, turn_id, registry, generation):  # type: ignore[no-untyped-def]
        self.registry = registry

    def unregister_turn(self, thread_id, turn_id):  # type: ignore[no-untyped-def]
        self.timeline.append("unregister")

    async def request(self, method, params, *, generation=None, timeout_s=None):  # type: ignore[no-untyped-def]
        self.timeline.append(method)
        if method == "turn/start":
            self.started.set()
            if self.start_delay:
                await asyncio.sleep(self.start_delay)
            for notification in self.initial:
                self.queue.put_nowait(notification)
            if self.tool_call:
                assert self.registry is not None
                await self.registry.invoke(_call(PLANNING_CONTEXT_TOOL_NAME, {}))
            return {"turn": {"id": "private-turn"}}
        if method == "turn/interrupt":
            self.interrupted.set()
            assert self.registry is not None
            self.late_result = await self.registry.invoke(_call(PLANNING_CONTEXT_TOOL_NAME, {}))
            if self.stop_mode == "error":
                raise JsonRpcTimeoutError("private failure")
            if self.stop_mode == "hang":
                await asyncio.sleep(10)
            if self.stop_mode == "terminal":
                self.queue.put_nowait(_terminal())
            elif self.stop_mode == "wrong_terminal":
                self.queue.put_nowait(_terminal("other-turn"))
            elif self.stop_mode == "delayed":
                asyncio.get_running_loop().call_later(.02, self.queue.put_nowait, _terminal())
            self.timeline.append("ack")
        return {}

    async def next_notification(self, *, generation, timeout_s=None):  # type: ignore[no-untyped-def]
        try:
            item = await asyncio.wait_for(self.queue.get(), timeout_s)
        except TimeoutError as exc:
            raise JsonRpcTimeoutError("poll") from exc
        if item.method == "turn/completed":
            self.timeline.append("terminal")
        return item

    async def shutdown(self) -> None:
        self.timeline.append("shutdown")
        if self.shutdown_fails:
            raise RuntimeError("private shutdown failure")
        self.stopped = True

    async def health(self) -> RuntimeHealthSnapshot:
        return RuntimeHealthSnapshot(RuntimeHealthStatus.STOPPED if self.stopped else RuntimeHealthStatus.READY, 1)


@pytest.fixture(autouse=True)
def bounded_fake_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(codex_adapter, "_TURN_STOP_TIMEOUT_SECONDS", .05)
    monkeypatch.setattr(codex_adapter, "_NOTIFICATION_POLL_SECONDS", .005)


def _request(tools: RuntimeToolRegistry | None = None, **kwargs: object) -> RuntimeTurnRequest:
    return RuntimeTurnRequest(RuntimeThreadHandle("private-thread", 1), (RuntimeInput("private-input"),),
                              tools or CountingRegistry(), **kwargs)  # type: ignore[arg-type]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reasoning,message,split,request_cap,global_cap,expected_error",
    [
        (3_000, 100, 16_000, 2_000, 2_000_000, False),
        (16_000, 2_000, 16_000, 2_000, 2_000_000, False),
        (16_001, 0, 16_000, 2_000, 2_000_000, True),
        (100, 2_001, 16_000, 2_000, 2_000_000, True),
        (4_900, 101, 16_000, 2_000, 5_000, True),
        # Compatibility: no opt-in means the old request cap is aggregate.
        (1_999, 1, None, 2_000, 2_000_000, False),
        (2_000, 1, None, 2_000, 2_000_000, True),
        (3_000, 100, None, None, 2_000_000, False),
    ],
)
async def test_split_caps_and_legacy_nonintake_aggregate(
    tmp_path, reasoning, message, split, request_cap, global_cap, expected_error,
):  # type: ignore[no-untyped-def]
    notifications = []
    for channel, count in (("reasoning", reasoning), ("message", message)):
        for offset in range(0, count, 1_000):
            notifications.append(_text(channel, min(1_000, count - offset)))
        notifications.append(_text(channel, count, completed=True))
    notifications.append(_notification("turn/completed", turn={"id": "private-turn", "status": "completed"}))
    server = FakeAppServer(tmp_path, notifications)
    server.config = replace(server.config, max_visible_text_chars=global_cap)
    result = await CodexAppServerRuntime(server).run_turn(_request(
        max_visible_text_chars=request_cap, max_reasoning_text_chars=split,
    ))
    assert (result.safe_error_code == "runtime_text_budget_exhausted") is expected_error
    if not expected_error:
        assert result.metrics.reasoning_text_chars == reasoning
        assert result.metrics.message_text_chars == message
        assert result.metrics.visible_text_chars == reasoning + message
        assert "turn/interrupt" not in server.timeline
    else:
        assert server.timeline.index("turn/interrupt") < server.timeline.index("unregister")
        assert result.metrics.termination_reason == "interrupt_terminal_confirmed"
    assert result.metrics.effective_max_total_text_chars == (global_cap if split else request_cap or global_cap)


@pytest.mark.asyncio
async def test_summary_separate_from_raw_completion_and_completion_calibration(tmp_path: Path) -> None:
    server = FakeAppServer(tmp_path, [
        _text("summary", 100), _text("reasoning", 100),
        _text("reasoning", 150, completed=True), _text("reasoning", 150, completed=True),
        _text("message", 200, completed=True), _text("message", 200, completed=True),
        _terminal(),
    ])
    result = await CodexAppServerRuntime(server).run_turn(_request(max_reasoning_text_chars=256, max_visible_text_chars=256))
    assert result.metrics.reasoning_text_chars == 250
    assert result.metrics.message_text_chars == 200
    assert result.metrics.visible_text_chars == 450
    assert result.safe_error_code is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["terminal", "delayed", "ack_only", "wrong_terminal", "error", "hang"])
async def test_budget_interrupt_requires_terminal_not_ack_and_fences_late_callbacks(tmp_path: Path, mode: str) -> None:
    registry = CountingRegistry()
    server = FakeAppServer(tmp_path, [_text("reasoning", 257)], stop_mode=mode)
    runtime = CodexAppServerRuntime(server)
    result = await asyncio.wait_for(runtime.run_turn(_request(registry, max_visible_text_chars=256)), 1)
    assert result.safe_error_code == "runtime_text_budget_exhausted"
    assert registry.calls == 0
    assert server.late_result is not None and not server.late_result.success
    assert server.timeline.count("turn/interrupt") == 1
    if mode in {"terminal", "delayed"}:
        assert result.metrics.termination_reason == "interrupt_terminal_confirmed"
        assert server.timeline.index("terminal") < server.timeline.index("unregister")
        assert not server.stopped
        # A confirmed stop is reusable, with an entirely new callback guard.
        server.initial = [_terminal()]
        second = await runtime.run_turn(_request())
        assert second.safe_error_code is None
    else:
        assert result.metrics.termination_reason == "owned_runtime_stopped"
        assert server.timeline.index("shutdown") < server.timeline.index("unregister")
        with pytest.raises(RuntimeUnavailableError):
            await runtime.run_turn(_request())


@pytest.mark.asyncio
async def test_unconfirmed_shutdown_blocks_health_and_normal_reuse(tmp_path: Path) -> None:
    server = FakeAppServer(tmp_path, [_text("message", 257)], stop_mode="ack_only", shutdown_fails=True)
    runtime = CodexAppServerRuntime(server)
    result = await runtime.run_turn(_request(max_visible_text_chars=256))
    assert result.metrics.termination_reason == "runtime_reuse_blocked"
    assert (await runtime.health()).status is RuntimeHealthStatus.UNAVAILABLE
    with pytest.raises(RuntimeUnavailableError, match="runtime_stop_unconfirmed"):
        await runtime.start()
    with pytest.raises(RuntimeUnavailableError, match="runtime_stop_unconfirmed"):
        await runtime.resume_thread("private-thread")
    with pytest.raises(RuntimeUnavailableError, match="runtime_stop_unconfirmed"):
        await runtime.run_turn(_request())
    server.shutdown_fails = False
    await runtime.shutdown()
    with pytest.raises(RuntimeUnavailableError, match="runtime_stop_unconfirmed"):
        await runtime.start()


@pytest.mark.asyncio
@pytest.mark.parametrize("start_delay", [0, .2])
async def test_deadline_includes_start_and_stops_unknown_turn(tmp_path: Path, start_delay: float) -> None:
    server = FakeAppServer(tmp_path, [], start_delay=start_delay)
    result = await CodexAppServerRuntime(server).run_turn(_request(timeout_seconds=.1))
    assert result.safe_error_code == "runtime_turn_time_exhausted"
    assert result.metrics.effective_timeout_seconds == .1
    assert ("turn/interrupt" in server.timeline) is (start_delay == 0)
    assert server.timeline[-1] == "unregister"
    if start_delay:
        assert server.stopped


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["delayed", "ack_only"])
async def test_external_and_repeated_cancellation_waits_for_bounded_cleanup(tmp_path: Path, mode: str) -> None:
    server = FakeAppServer(tmp_path, [], stop_mode=mode)
    runtime = CodexAppServerRuntime(server)
    task = asyncio.create_task(runtime.run_turn(_request()))
    await server.started.wait()
    await asyncio.sleep(.001)
    task.cancel()
    await server.interrupted.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert server.timeline[-1] == "unregister"
    assert ("terminal" in server.timeline) or server.stopped
    assert not runtime._turn_lock.locked()


@pytest.mark.asyncio
async def test_fatal_tool_immediately_stops_even_without_any_wire_notification(tmp_path: Path) -> None:
    registry = CountingRegistry(fatal=True)
    server = FakeAppServer(tmp_path, [], tool_call=True)
    result = await CodexAppServerRuntime(server).run_turn(_request(registry))
    assert result.terminal_status is RuntimeTerminalStatus.FAILED
    assert result.safe_error_code == "tool_call_budget_exhausted"
    assert result.metrics.termination_reason == "interrupt_terminal_confirmed"
    assert registry.calls == 1  # including pre-register callback, no late side effect


@pytest.mark.asyncio
async def test_cancellation_arriving_during_budget_cleanup_is_not_swallowed(tmp_path: Path) -> None:
    server = FakeAppServer(tmp_path, [_text("reasoning", 257)], stop_mode="delayed")
    runtime = CodexAppServerRuntime(server)
    task = asyncio.create_task(runtime.run_turn(_request(max_visible_text_chars=256)))
    await server.interrupted.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert server.timeline[-1] == "unregister"
    assert "terminal" in server.timeline
    assert not runtime._turn_lock.locked()


@pytest.mark.asyncio
async def test_cancel_during_start_stops_unknown_owned_turn(tmp_path: Path) -> None:
    server = FakeAppServer(tmp_path, [], start_delay=1)
    runtime = CodexAppServerRuntime(server)
    task = asyncio.create_task(runtime.run_turn(_request()))
    await server.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert server.stopped
    assert "turn/interrupt" not in server.timeline  # never invent a turn ID
    assert server.timeline[-1] == "unregister"


@pytest.mark.parametrize("cap", [0, 255, 8_000_001])
def test_reasoning_request_caps_are_bounded(cap: int) -> None:
    with pytest.raises(ValueError, match="reasoning text budget"):
        _request(max_reasoning_text_chars=cap)


@pytest.mark.parametrize("code", ["runtime_text_budget_exhausted", "runtime_turn_time_exhausted",
                                    "tool_call_budget_exhausted", "tool_repair_budget_exhausted",
                                    "tool_conflict_budget_exhausted", "tool_output_budget_exhausted"])
def test_budget_failure_cannot_masquerade_as_semantic_ambiguity_even_with_completed_wire_status(code: str) -> None:
    registry = LearningPlanRuntimeToolRegistry(
        FakeService(_result(LearningPlanToolStatus.COMPLETED, "unused"), _result(LearningPlanToolStatus.COMPLETED, "unused")),
    )
    result = RuntimeTurnResult(RuntimeThreadHandle("private-thread", 1), "private-turn", RuntimeTerminalStatus.COMPLETED, (), code)
    assert not _direction_server_terminalization_allowed(registry, result)
    registry.results.append(_result(LearningPlanToolStatus.FATAL, code))
    assert not _direction_server_terminalization_allowed(registry, replace(result, safe_error_code=None))


@pytest.mark.asyncio
async def test_budget_json_telemetry_contains_counts_caps_outcome_not_text(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    server = FakeAppServer(tmp_path, [_text("reasoning", 257)])
    await CodexAppServerRuntime(server).run_turn(_request(max_reasoning_text_chars=256, max_visible_text_chars=256))
    records = [json.loads(record.getMessage()) for record in caplog.records
               if '"event":"codex_runtime_turn_budget"' in record.getMessage()]
    assert len(records) == 1
    data = records[0]
    assert data["reasoning_chars"] == 257
    assert data["visible_chars"] == 0
    assert data["effective_max_reasoning_chars"] == 256
    assert data["effective_max_total_chars"] == 2_000_000
    assert data["termination_reason"] == "interrupt_terminal_confirmed"
    assert data["action_identifier"].startswith("sha256:")
    assert "private" not in json.dumps(data)
    assert "字" not in json.dumps(data, ensure_ascii=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("intake", [True, False])
async def test_one_order_repair_uses_existing_repair_budget_and_accepts_only_one_action(intake: bool) -> None:
    service = FakeService(_result(LearningPlanToolStatus.AWAITING_USER, "planning_facts_missing", data=_awaiting_data()),
                          _result(LearningPlanToolStatus.COMPLETED, "unused"))
    registry = LearningPlanRuntimeToolRegistry(service)
    if intake:
        registry.configure_direction_intake()
    wrong_order = await registry.invoke(_call(PLANNING_CONTEXT_TOOL_NAME, {"direction_action": "continue_mainline"}))
    assert wrong_order.success
    repair = json.loads(wrong_order.content)
    assert repair["status"] == "repairable_invalid"
    assert repair["retry_allowed"] is True
    assert "without direction_action" in repair["issues"][0]["hint"]
    assert registry.repair_count == 1
    assert not registry.direction_protocol_invalid
    assert service.read_inputs == []  # no authority granted by rejected action
    assert (await registry.invoke(_call(PLANNING_CONTEXT_TOOL_NAME, {}))).success
    assert (await registry.invoke(_call(PLANNING_CONTEXT_TOOL_NAME, {"direction_action": "continue_mainline"}))).success
    assert registry.call_count == 3
    assert registry.planning_direction_action is not None
    duplicate = await registry.invoke(_call(PLANNING_CONTEXT_TOOL_NAME, {"direction_action": "continue_mainline"}))
    assert not duplicate.success
    assert duplicate.safe_code == "planning_direction_action_duplicate"
    assert sum(item is not None and item.direction_action is not None for item in service.read_inputs) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("repairs", [0, 1])
async def test_wrong_order_never_gets_a_second_repair(repairs: int) -> None:
    registry = LearningPlanRuntimeToolRegistry(
        FakeService(_result(LearningPlanToolStatus.COMPLETED, "unused"), _result(LearningPlanToolStatus.COMPLETED, "unused")),
        budget=LearningPlanToolBudget(max_repairs=repairs),
    )
    for _ in range(repairs + 1):
        result = await registry.invoke(_call(PLANNING_CONTEXT_TOOL_NAME, {"direction_action": "continue_mainline"}))
    assert not result.success
    assert registry.direction_protocol_invalid
    assert registry.repair_count == repairs
    assert registry.planning_direction_action is None


@pytest.mark.asyncio
async def test_direction_intake_allows_five_bounded_repair_calls(monkeypatch) -> None:
    service = FakeService(
        _result(
            LearningPlanToolStatus.AWAITING_USER,
            "planning_facts_missing",
            data=_awaiting_data("language_id"),
        ),
        _result(LearningPlanToolStatus.COMPLETED, "unused"),
    )
    original_read_context = service.read_context
    direction_attempts = 0

    def repair_then_accept(tool_input=None):  # type: ignore[no-untyped-def]
        nonlocal direction_attempts
        if tool_input is not None and tool_input.direction_action is not None:
            direction_attempts += 1
            if direction_attempts <= 5:
                return _result(
                    LearningPlanToolStatus.REPAIRABLE_INVALID,
                    "planning_language_hint_invalid",
                    data=_awaiting_data("language_id"),
                )
        return original_read_context(tool_input)

    monkeypatch.setattr(service, "read_context", repair_then_accept)
    registry = LearningPlanRuntimeToolRegistry(service)
    registry.configure_direction_intake()

    assert (await registry.invoke(_call(PLANNING_CONTEXT_TOOL_NAME, {}))).success
    for expected_remaining in (4, 3, 2, 1, 0):
        repair = await registry.invoke(
            _call(
                PLANNING_CONTEXT_TOOL_NAME,
                {"direction_action": "continue_mainline"},
            )
        )
        payload = json.loads(repair.content)
        assert repair.success
        assert payload["status"] == "repairable_invalid"
        assert payload["remaining_repair_attempts"] == expected_remaining
        assert not registry.direction_protocol_invalid

    accepted = await registry.invoke(
        _call(
            PLANNING_CONTEXT_TOOL_NAME,
            {"direction_action": "continue_mainline"},
        )
    )
    assert accepted.success
    assert registry.call_count == 7
    assert registry.repair_count == 5
    assert registry.planning_direction_action is not None


def test_intake_timeout_is_configurable_and_bounded(monkeypatch):
    from app.core.config import Settings
    from pydantic import ValidationError
    monkeypatch.delenv("TUTOR_CODEX_INTAKE_TIMEOUT_SECONDS", raising=False)
    assert Settings().tutor_codex_intake_timeout_seconds == 180
    monkeypatch.setenv("TUTOR_CODEX_INTAKE_TIMEOUT_SECONDS", "240")
    assert Settings().tutor_codex_intake_timeout_seconds == 240
    with pytest.raises(ValidationError):
        Settings(tutor_codex_intake_timeout_seconds=601)
