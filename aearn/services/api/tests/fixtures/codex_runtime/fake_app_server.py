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


def read() -> dict[str, Any]:
    line = sys.stdin.readline()
    if not line:
        raise EOFError
    value = json.loads(line)
    if not isinstance(value, dict):
        raise ValueError("message must be an object")
    return value


def reply(request: dict[str, Any], result: dict[str, Any]) -> None:
    send({"id": request["id"], "result": result})


def main() -> int:
    scenario = argparse.ArgumentParser()
    scenario.add_argument("--scenario", required=True)
    mode = scenario.parse_args().scenario
    initialize = read()
    reply(initialize, {"userAgent": "fake-runtime/0.1", "codexHome": os.environ["CODEX_HOME"], "platformFamily": "windows", "platformOs": "windows"})
    read()
    account = read()
    reply(account, {"account": None, "requiresOpenAIAuth": False})
    if mode == "crash_after_preflight":
        time.sleep(0.05)
        os._exit(25)
    if mode == "invalid_after_preflight":
        sys.stdout.write("not-json\n")
        sys.stdout.flush()
        time.sleep(1)
        return 0
    if mode == "stderr_secret":
        sys.stderr.write(f"api_key={os.environ.get('DEEPSEEK_API_KEY', '')} prompt=hidden path={os.environ['CODEX_HOME']}\n")
        sys.stderr.flush()

    while True:
        try:
            request = read()
        except EOFError:
            return 0
        method = request.get("method")
        if method in {"thread/start", "thread/resume"}:
            thread_id = str((request.get("params") or {}).get("threadId") or "thr_runtime")
            reply(request, {"thread": {"id": thread_id, "sessionId": thread_id, "ephemeral": False}, "model": "deepseek-v4-flash", "modelProvider": "aearn_deepseek", "cwd": os.getcwd(), "approvalPolicy": "never", "approvalsReviewer": "user", "sandbox": {"type": "readOnly"}})
            send({"method": "thread/started", "params": {"thread": {"id": thread_id}}})
            continue
        if method == "turn/start":
            thread_id = str(request["params"]["threadId"])
            turn_id = "turn_runtime"
            reply(request, {"turn": {"id": turn_id, "status": "inProgress", "items": []}})
            send({"method": "turn/started", "params": {"threadId": thread_id, "turn": {"id": turn_id, "status": "inProgress", "items": []}}})
            if mode == "crash_on_turn":
                os._exit(26)
            if mode == "slow_turn":
                time.sleep(0.35)
            if mode == "repair":
                for attempt in (1, 2):
                    item = {"id": f"tool_{attempt}", "type": "dynamicToolCall", "tool": "aearn_runtime_probe", "arguments": {"attempt": attempt}, "status": "inProgress"}
                    send({"method": "item/started", "params": {"threadId": thread_id, "turnId": turn_id, "item": item}})
                    send({"id": 900 + attempt, "method": "item/tool/call", "params": {"threadId": thread_id, "turnId": turn_id, "callId": f"call_{attempt}", "tool": "aearn_runtime_probe", "arguments": {"attempt": attempt}}})
                    tool_result = read()
                    success = bool((tool_result.get("result") or {}).get("success"))
                    item["status"] = "completed" if success else "failed"
                    send({"method": "item/completed", "params": {"threadId": thread_id, "turnId": turn_id, "item": item}})
                    if not success:
                        send({"method": "turn/completed", "params": {"threadId": thread_id, "turn": {"id": turn_id, "status": "failed", "items": []}}})
                        break
            reasoning = {"id": "reasoning_1", "type": "reasoning", "text": "raw reasoning must stay hidden"}
            send({"method": "item/completed", "params": {"threadId": thread_id, "turnId": turn_id, "item": reasoning}})
            message = {"id": "message_1", "type": "agentMessage", "text": "safe final", "phase": "final_answer"}
            send({"method": "item/completed", "params": {"threadId": thread_id, "turnId": turn_id, "item": message}})
            send({"method": "turn/completed", "params": {"threadId": thread_id, "turn": {"id": turn_id, "status": "completed", "items": [message]}}})
            continue
        if method == "turn/steer":
            reply(request, {})
            continue
        if method == "turn/interrupt":
            reply(request, {})
            params = request.get("params") or {}
            send({"method": "turn/completed", "params": {"threadId": params.get("threadId"), "turn": {"id": params.get("turnId"), "status": "interrupted", "items": []}}})
            continue
        send({"id": request["id"], "error": {"code": -32601, "message": "unsupported"}})


if __name__ == "__main__":
    raise SystemExit(main())
