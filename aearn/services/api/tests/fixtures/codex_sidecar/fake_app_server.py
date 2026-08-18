from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any


def send(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def response(request: dict[str, Any], result: dict[str, Any]) -> None:
    send({"id": request["id"], "result": result})


def read() -> dict[str, Any]:
    line = sys.stdin.readline()
    if not line:
        raise EOFError
    value = json.loads(line)
    if not isinstance(value, dict):
        raise ValueError("request must be an object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True)
    scenario = parser.parse_args().scenario
    if scenario == "crash_immediate":
        os._exit(23)
    if scenario == "invalid_json":
        sys.stdout.write("not-json\n")
        sys.stdout.flush()
        time.sleep(2)
        return 0

    initialize = read()
    response(initialize, {"userAgent": "fake-app-server/0.1", "codexHome": os.environ.get("CODEX_HOME", ""), "platformFamily": "windows", "platformOs": "windows"})
    read()
    if scenario == "hang_request":
        read()
        time.sleep(60)
        return 0
    if scenario == "unknown_server_request":
        send({"id": 900, "method": "dangerous/request", "params": {}})
        time.sleep(2)
        return 0
    if scenario == "stderr_secret":
        sys.stderr.write(f"authorization: bearer {os.environ.get('FIXTURE_SECRET', '')} path={os.environ.get('CODEX_HOME', '')} raw_prompt=hidden\n")
        sys.stderr.flush()

    thread_start = read()
    response(thread_start, {"thread": {"id": "thr_fixture", "sessionId": "thr_fixture", "ephemeral": True}, "model": "deepseek-v4-flash", "modelProvider": "aearn_deepseek", "cwd": os.getcwd(), "approvalPolicy": "never", "approvalsReviewer": "user", "sandbox": {"type": "readOnly"}})
    send({"method": "thread/started", "params": {"thread": {"id": "thr_fixture"}}})
    send({"method": "fixture/unknown", "params": {"safe": True}})
    turn_start = read()
    response(turn_start, {"turn": {"id": "turn_fixture", "status": "inProgress", "items": []}})
    send({"method": "turn/started", "params": {"threadId": "thr_fixture", "turn": {"id": "turn_fixture", "status": "inProgress", "items": []}}})

    if scenario == "interrupt":
        interrupt = read()
        response(interrupt, {})
        send({"method": "turn/completed", "params": {"threadId": "thr_fixture", "turn": {"id": "turn_fixture", "status": "interrupted", "items": []}}})
        return 0
    if scenario == "crash_after_turn":
        os._exit(24)

    calls = 2 if scenario == "repair" else 1
    for attempt in range(1, calls + 1):
        item = {"id": f"item_{attempt}", "type": "dynamicToolCall", "tool": "aearn_protocol_probe", "arguments": {"attempt": attempt, "value": "bounded"}, "status": "inProgress"}
        send({"method": "item/started", "params": {"threadId": "thr_fixture", "turnId": "turn_fixture", "item": item}})
        send({"id": 100 + attempt, "method": "item/tool/call", "params": {"threadId": "thr_fixture", "turnId": "turn_fixture", "callId": f"call_{attempt}", "tool": "aearn_protocol_probe", "arguments": {"attempt": attempt, "value": "bounded"}}})
        tool_result = read()
        success = bool((tool_result.get("result") or {}).get("success"))
        completed = dict(item)
        completed["status"] = "completed" if success else "failed"
        completed["success"] = success
        send({"method": "item/completed", "params": {"threadId": "thr_fixture", "turnId": "turn_fixture", "item": completed}})
        if not success:
            send({"method": "turn/completed", "params": {"threadId": "thr_fixture", "turn": {"id": "turn_fixture", "status": "failed", "items": [completed]}}})
            return 0
    send({"method": "turn/completed", "params": {"threadId": "thr_fixture", "turn": {"id": "turn_fixture", "status": "completed", "items": []}}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
