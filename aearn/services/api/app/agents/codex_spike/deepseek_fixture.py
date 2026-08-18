"""Deterministic fake DeepSeek Responses stream contract used by the spike."""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any


class DeepSeekFixtureError(ValueError):
    """The fake provider stream violated the accepted Responses subset."""


@dataclass(frozen=True, slots=True)
class DeepSeekFixtureResult:
    response_id: str
    terminal_status: str
    tool_calls: tuple[dict[str, Any], ...]
    output_text_present: bool


class DeepSeekResponsesFixture:
    """Provide a bounded Responses-like event stream without network access."""

    def __init__(self, scenario: str = "repair") -> None:
        if scenario not in {"repair", "fatal", "provider_timeout", "stream_interrupted", "invalid_event"}:
            raise ValueError("unsupported DeepSeek fixture scenario")
        self.scenario = scenario

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        if self.scenario == "provider_timeout":
            await asyncio.sleep(60)
            return
        if self.scenario == "invalid_event":
            yield {"type": "response.output_item.added", "item": {"type": "unknown"}}
            return
        yield {"type": "response.created", "response": {"id": "resp_fixture", "status": "in_progress"}}
        yield {"type": "response.output_item.added", "item": {"id": "call_fixture_1", "type": "function_call", "name": "aearn_protocol_probe", "arguments": json.dumps({"attempt": 1, "value": "bounded"}), "call_id": "call_fixture_1"}}
        if self.scenario == "stream_interrupted":
            return
        if self.scenario == "repair":
            yield {"type": "response.output_item.added", "item": {"id": "call_fixture_2", "type": "function_call", "name": "aearn_protocol_probe", "arguments": json.dumps({"attempt": 2, "value": "bounded"}), "call_id": "call_fixture_2"}}
        terminal = "failed" if self.scenario == "fatal" else "completed"
        yield {"type": f"response.{terminal}", "response": {"id": "resp_fixture", "status": terminal}}

    async def collect(self, *, timeout_s: float = 0.1) -> DeepSeekFixtureResult:
        async def _collect() -> DeepSeekFixtureResult:
            response_id: str | None = None
            terminal: str | None = None
            tool_calls: list[dict[str, Any]] = []
            output_text_present = False
            async for event in self.events():
                event_type = event.get("type")
                if event_type == "response.created":
                    response = event.get("response")
                    if not isinstance(response, dict) or not isinstance(response.get("id"), str):
                        raise DeepSeekFixtureError("response.created missing response id")
                    response_id = response["id"]
                elif event_type == "response.output_item.added":
                    item = event.get("item")
                    if not isinstance(item, dict) or item.get("type") != "function_call":
                        raise DeepSeekFixtureError("unsupported Responses output item")
                    if not isinstance(item.get("name"), str) or not isinstance(item.get("arguments"), str):
                        raise DeepSeekFixtureError("function call missing name or arguments")
                    arguments = json.loads(item["arguments"])
                    if not isinstance(arguments, dict):
                        raise DeepSeekFixtureError("function call arguments must decode to an object")
                    tool_calls.append({"name": item["name"], "arguments": arguments})
                elif event_type == "response.output_text.delta":
                    output_text_present = True
                elif event_type in {"response.completed", "response.failed"}:
                    response = event.get("response")
                    if not isinstance(response, dict) or response.get("id") != response_id:
                        raise DeepSeekFixtureError("terminal response id mismatch")
                    terminal = str(response.get("status"))
                else:
                    raise DeepSeekFixtureError(f"unsupported Responses event: {event_type}")
            if response_id is None:
                raise DeepSeekFixtureError("stream missing response.created")
            if terminal is None:
                raise DeepSeekFixtureError("stream ended without terminal event")
            return DeepSeekFixtureResult(response_id=response_id, terminal_status=terminal, tool_calls=tuple(tool_calls), output_text_present=output_text_present)
        try:
            return await asyncio.wait_for(_collect(), timeout=timeout_s)
        except TimeoutError as exc:
            raise DeepSeekFixtureError("provider_timeout") from exc
