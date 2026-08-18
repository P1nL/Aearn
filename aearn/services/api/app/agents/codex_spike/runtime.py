"""Spike-only tool scenarios built on the production JSON-RPC connection."""
from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping

from app.agents.runtime.codex_connection import (
    JsonObject,
    JsonRpcChildExitedError as JsonRpcChildExitedError,
    JsonRpcError as JsonRpcError,
    JsonRpcNotification as JsonRpcNotification,
    JsonRpcProtocolError as JsonRpcProtocolError,
    JsonRpcRemoteError as JsonRpcRemoteError,
    JsonRpcTimeoutError as JsonRpcTimeoutError,
    SanitizedProcessEvidence as SanitizedProcessEvidence,
    StdioJsonRpcClient as StdioJsonRpcClient,
    redact_protocol_value as redact_protocol_value,
)


class ToolScenarioHost:
    """Deterministic typed tool host for repair, fatal, and timeout cases."""

    def __init__(self, scenario: str = "repair", *, timeout_delay_s: float = 0.2) -> None:
        if scenario not in {"repair", "fatal", "timeout"}:
            raise ValueError("unsupported tool scenario")
        self.scenario = scenario
        self.timeout_delay_s = timeout_delay_s
        self.calls: list[JsonObject] = []

    async def handle(self, params: JsonObject) -> JsonObject:
        tool = params.get("tool")
        arguments = params.get("arguments")
        if tool != "aearn_protocol_probe" or not isinstance(arguments, dict):
            raise JsonRpcProtocolError("dynamic tool request did not match the typed probe")
        attempt = arguments.get("attempt")
        value = arguments.get("value")
        if not isinstance(attempt, int) or not isinstance(value, str) or len(value) > 64:
            raise JsonRpcProtocolError("dynamic tool arguments failed validation")
        self.calls.append(params)
        if len(self.calls) > 2:
            return _tool_response({"status": "fatal", "code": "tool_call_budget_exhausted", "retry_allowed": False}, success=False)
        if self.scenario == "timeout":
            await asyncio.sleep(self.timeout_delay_s)
        if self.scenario == "fatal":
            return _tool_response({"status": "fatal", "code": "fixture_fatal", "retry_allowed": False}, success=False)
        if len(self.calls) == 1:
            return _tool_response({"status": "repairable_invalid", "issues": [{"path": "attempt", "code": "must_increment"}], "retry_allowed": True}, success=True)
        return _tool_response({"status": "completed", "accepted_attempt": attempt, "retry_allowed": False}, success=True)


def _tool_response(payload: Mapping[str, object], *, success: bool) -> JsonObject:
    return {"contentItems": [{"type": "inputText", "text": json.dumps(payload, ensure_ascii=True, separators=(",", ":"))}], "success": success}
