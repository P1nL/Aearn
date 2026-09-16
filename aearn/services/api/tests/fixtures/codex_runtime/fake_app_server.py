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




def run_tool_calls(
    *,
    thread_id: str,
    turn_id: str,
    calls: tuple[tuple[str, dict[str, Any]], ...],
    request_id_start: int,
) -> bool:
    for index, (tool_name, arguments) in enumerate(calls, start=1):
        item = {
            "id": f"tool_{request_id_start}_{index}",
            "type": "dynamicToolCall",
            "tool": tool_name,
            "arguments": arguments,
            "status": "inProgress",
        }
        send({"method": "item/started", "params": {"threadId": thread_id, "turnId": turn_id, "item": item}})
        send(
            {
                "id": request_id_start + index,
                "method": "item/tool/call",
                "params": {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "callId": f"call_{request_id_start}_{index}",
                    "tool": tool_name,
                    "arguments": arguments,
                },
            }
        )
        tool_result = read()
        success = bool((tool_result.get("result") or {}).get("success"))
        item["status"] = "completed" if success else "failed"
        item["result"] = tool_result.get("result")
        send({"method": "item/completed", "params": {"threadId": thread_id, "turnId": turn_id, "item": item}})
        if not success:
            send(
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": thread_id,
                        "turn": {"id": turn_id, "status": "failed", "items": []},
                    },
                }
            )
            return False
    return True


def valid_plan_modules() -> list[dict[str, Any]]:
    return [
        {
            "stable_key": "foundations",
            "title": "Foundations",
            "nodes": [
                {
                    "stable_key": "python.variables",
                    "title": "Variables",
                    "required_capabilities": ["python"],
                }
            ],
        },
        {
            "stable_key": "automation",
            "title": "Automation",
            "nodes": [
                {
                    "stable_key": "python.files",
                    "title": "Files",
                    "prerequisites": ["python.variables"],
                    "required_capabilities": ["python"],
                }
            ],
        },
    ]


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

    thread_count = 0
    turn_count = 0
    while True:
        try:
            request = read()
        except EOFError:
            return 0
        method = request.get("method")
        if method in {"thread/start", "thread/resume"}:
            if method == "thread/start":
                thread_count += 1
                thread_id = f"thr_runtime_{thread_count}"
            else:
                thread_id = str((request.get("params") or {}).get("threadId") or "")
            reply(request, {"thread": {"id": thread_id, "sessionId": thread_id, "ephemeral": False}, "model": "deepseek-flash", "modelProvider": "aearn_deepseek", "cwd": os.getcwd(), "approvalPolicy": "never", "approvalsReviewer": "user", "sandbox": {"type": "readOnly"}})
            send({"method": "thread/started", "params": {"thread": {"id": thread_id}}})
            continue
        if method == "turn/start":
            turn_count += 1
            thread_id = str(request["params"]["threadId"])
            turn_id = f"turn_runtime_{turn_count}"
            reply(request, {"turn": {"id": turn_id, "status": "inProgress", "items": []}})
            send({"method": "turn/started", "params": {"threadId": thread_id, "turn": {"id": turn_id, "status": "inProgress", "items": []}}})
            if mode == "crash_on_turn":
                os._exit(26)
            if mode == "slow_turn":
                time.sleep(0.35)
            if mode == "request_user_input":
                send(
                    {
                        "id": 940,
                        "method": "item/tool/requestUserInput",
                        "params": {
                            "threadId": thread_id,
                            "turnId": turn_id,
                            "itemId": "request_input_1",
                            "questions": [
                                {
                                    "id": "experience_level",
                                    "header": "经验",
                                    "question": "你的经验如何？",
                                    "options": [
                                        {"label": "零基础", "description": "没有相关经验"},
                                    ],
                                }
                            ],
                        },
                    }
                )
                response = read()
                expected = {"experience_level": {"answers": []}}
                if (response.get("result") or {}).get("answers") != expected:
                    return 31
            turn_succeeded = True
            if mode == "repair":
                turn_succeeded = run_tool_calls(
                    thread_id=thread_id,
                    turn_id=turn_id,
                    calls=tuple(
                        ("aearn_runtime_probe", {"attempt": attempt})
                        for attempt in (1, 2)
                    ),
                    request_id_start=900,
                )
            if mode in {"learning_plan_repair", "long_learning_plan_repair"}:
                turn_succeeded = run_tool_calls(
                    thread_id=thread_id,
                    turn_id=turn_id,
                    calls=(
                        ("aearn_planning_context_read", {}),
                        (
                            "aearn_planning_context_read",
                            {"direction_action": "continue_mainline"},
                        ),
                        (
                            "aearn_learning_plan_draft",
                            {
                                "modules": [
                                    {
                                        "stable_key": "foundations",
                                        "title": "Foundations",
                                        "nodes": [
                                            {
                                                "stable_key": "python.variables",
                                                "title": "Variables",
                                            }
                                        ],
                                    }
                                ]
                            },
                        ),
                        ("aearn_learning_plan_draft", {"modules": valid_plan_modules()}),
                    ),
                    request_id_start=950,
                )
            if mode == "learning_plan_context":
                turn_succeeded = run_tool_calls(
                    thread_id=thread_id,
                    turn_id=turn_id,
                    calls=(("aearn_planning_context_read", {}),),
                    request_id_start=970,
                )
            if mode == "learning_plan_duplicate":
                arguments = {"modules": valid_plan_modules()}
                turn_succeeded = run_tool_calls(
                    thread_id=thread_id,
                    turn_id=turn_id,
                    calls=(
                        ("aearn_planning_context_read", {}),
                        (
                            "aearn_planning_context_read",
                            {"direction_action": "continue_mainline"},
                        ),
                        ("aearn_learning_plan_draft", arguments),
                        ("aearn_learning_plan_draft", arguments),
                    ),
                    request_id_start=980,
                )
            if not turn_succeeded:
                continue
            if mode == "long_learning_plan_repair":
                reasoning = {"id": f"reasoning_{turn_count}", "type": "reasoning", "index": 0}
                send(
                    {
                        "method": "item/started",
                        "params": {
                            "threadId": thread_id,
                            "turnId": turn_id,
                            "item": reasoning,
                        },
                    }
                )
                for _index in range(2_500):
                    send(
                        {
                            "method": "item/reasoning/textDelta",
                            "params": {
                                "threadId": thread_id,
                                "turnId": turn_id,
                                "itemId": reasoning["id"],
                                "index": 0,
                                "delta": "r",
                            },
                        }
                    )
                send(
                    {
                        "method": "item/completed",
                        "params": {
                            "threadId": thread_id,
                            "turnId": turn_id,
                            "item": reasoning,
                        },
                    }
                )
                message = {
                    "id": f"message_{turn_count}",
                    "type": "agentMessage",
                    "text": f"safe final {turn_count}",
                    "phase": "final_answer",
                }
            elif mode == "many_items":
                for index in range(17):
                    reasoning = {
                        "id": f"reasoning_{turn_count}_{index}",
                        "type": "reasoning",
                        "index": index,
                    }
                    send(
                        {
                            "method": "item/started",
                            "params": {
                                "threadId": thread_id,
                                "turnId": turn_id,
                                "item": reasoning,
                            },
                        }
                    )
                    send(
                        {
                            "method": "item/completed",
                            "params": {
                                "threadId": thread_id,
                                "turnId": turn_id,
                                "item": reasoning,
                            },
                        }
                    )
                message = {
                    "id": f"message_{turn_count}",
                    "type": "agentMessage",
                    "text": f"safe final {turn_count}",
                    "phase": "final_answer",
                }
            elif mode == "text_budget":
                reasoning = {"id": f"reasoning_{turn_count}", "type": "reasoning", "index": 0}
                send(
                    {
                        "method": "item/started",
                        "params": {
                            "threadId": thread_id,
                            "turnId": turn_id,
                            "item": reasoning,
                        },
                    }
                )
                send(
                    {
                        "method": "item/reasoning/textDelta",
                        "params": {
                            "threadId": thread_id,
                            "turnId": turn_id,
                            "itemId": reasoning["id"],
                            "index": 0,
                            "delta": "x" * 16_001,
                        },
                    }
                )
                message = {
                    "id": f"message_{turn_count}",
                    "type": "agentMessage",
                    "text": f"safe final {turn_count}",
                    "phase": "final_answer",
                }
            elif mode == "five_thousand_deltas":
                reasoning = {"id": f"reasoning_{turn_count}", "type": "reasoning", "index": 0}
                send(
                    {
                        "method": "item/started",
                        "params": {
                            "threadId": thread_id,
                            "turnId": turn_id,
                            "item": reasoning,
                        },
                    }
                )
                for _index in range(5_000):
                    send(
                        {
                            "method": "item/reasoning/textDelta",
                            "params": {
                                "threadId": thread_id,
                                "turnId": turn_id,
                                "itemId": reasoning["id"],
                                "index": 0,
                                "delta": "思",
                            },
                        }
                    )
                send(
                    {
                        "method": "item/completed",
                        "params": {
                            "threadId": thread_id,
                            "turnId": turn_id,
                            "item": reasoning,
                        },
                    }
                )
                message = {
                    "id": f"message_{turn_count}",
                    "type": "agentMessage",
                    "text": f"safe final {turn_count}",
                    "phase": "final_answer",
                }
            elif mode == "sparse_deltas":
                reasoning = {"id": f"reasoning_{turn_count}", "type": "reasoning", "index": 0}
                send(
                    {
                        "method": "item/started",
                        "params": {
                            "threadId": thread_id,
                            "turnId": turn_id,
                            "item": reasoning,
                        },
                    }
                )
                send(
                    {
                        "method": "item/reasoning/textDelta",
                        "params": {
                            "threadId": thread_id,
                            "turnId": turn_id,
                            "itemId": reasoning["id"],
                            "index": 0,
                            "delta": "first",
                        },
                    }
                )
                time.sleep(0.08)
                send(
                    {
                        "method": "item/reasoning/textDelta",
                        "params": {
                            "threadId": thread_id,
                            "turnId": turn_id,
                            "itemId": reasoning["id"],
                            "index": 0,
                            "delta": "second",
                        },
                    }
                )
                send(
                    {
                        "method": "item/completed",
                        "params": {
                            "threadId": thread_id,
                            "turnId": turn_id,
                            "item": reasoning,
                        },
                    }
                )
                message = {
                    "id": f"message_{turn_count}",
                    "type": "agentMessage",
                    "text": f"safe final {turn_count}",
                    "phase": "final_answer",
                }
            elif mode == "burst_turns":
                reasoning = {"id": f"reasoning_{turn_count}", "type": "reasoning"}
                send(
                    {
                        "method": "item/started",
                        "params": {
                            "threadId": thread_id,
                            "turnId": turn_id,
                            "item": reasoning,
                        },
                    }
                )
                for index in range(180):
                    send(
                        {
                            "method": "item/reasoning/textDelta",
                            "params": {
                                "threadId": thread_id,
                                "turnId": turn_id,
                                "itemId": reasoning["id"],
                                "delta": f"{turn_count}:{index};",
                            },
                        }
                    )
                send(
                    {
                        "method": "item/completed",
                        "params": {
                            "threadId": thread_id,
                            "turnId": turn_id,
                            "item": reasoning,
                        },
                    }
                )
                message = {
                    "id": f"message_{turn_count}",
                    "type": "agentMessage",
                    "text": f"safe final {turn_count}",
                    "phase": "final_answer",
                }
            elif mode == "turn_profile":
                effort = str((request.get("params") or {}).get("effort") or "unset")
                message = {
                    "id": f"message_{turn_count}",
                    "type": "agentMessage",
                    "text": f"effort:{effort}",
                    "phase": "final_answer",
                }
            elif mode == "compaction":
                compaction = {"id": "compact_1", "type": "contextCompaction"}
                send({"method": "item/started", "params": {"threadId": thread_id, "turnId": turn_id, "item": compaction}})
                send({"method": "item/completed", "params": {"threadId": thread_id, "turnId": turn_id, "item": compaction}})
                reasoning = {"id": "reasoning_1", "type": "reasoning"}
                send({"method": "item/started", "params": {"threadId": thread_id, "turnId": turn_id, "item": {"id": "reasoning_1", "type": "reasoning"}}})
                send({"method": "item/reasoning/textDelta", "params": {"threadId": thread_id, "turnId": turn_id, "itemId": "reasoning_1", "delta": "先读取服务端事实。\n"}})
                send({"method": "item/reasoning/summaryTextDelta", "params": {"threadId": thread_id, "turnId": turn_id, "itemId": "reasoning_1", "delta": "private summary"}})
                send({"method": "item/reasoning/textDelta", "params": {"threadId": thread_id, "turnId": turn_id, "itemId": "reasoning_1", "delta": "再确认缺失字段。"}})
                send({"method": "item/completed", "params": {"threadId": thread_id, "turnId": turn_id, "item": reasoning}})
                message = {"id": "message_1", "type": "agentMessage", "text": "只询问学习目标。", "phase": "final_answer"}
                send({"method": "item/started", "params": {"threadId": thread_id, "turnId": turn_id, "item": {"id": "message_1", "type": "agentMessage", "phase": "final_answer"}}})
                send({"method": "item/agentMessage/delta", "params": {"threadId": thread_id, "turnId": turn_id, "itemId": "message_1", "delta": "只询问"}})
                send({"method": "item/agentMessage/delta", "params": {"threadId": thread_id, "turnId": turn_id, "itemId": "message_1", "delta": "学习目标。"}})
            else:
                reasoning = {"id": "reasoning_1", "type": "reasoning", "text": "raw reasoning for the owner Think projection"}
                send({"method": "item/completed", "params": {"threadId": thread_id, "turnId": turn_id, "item": reasoning}})
                message = {"id": "message_1", "type": "agentMessage", "text": "safe final", "phase": "final_answer"}
            commentary = {"id": "commentary_1", "type": "agentMessage", "text": "private commentary", "phase": "commentary"}
            send({"method": "item/completed", "params": {"threadId": thread_id, "turnId": turn_id, "item": commentary}})
            send({"method": "item/completed", "params": {"threadId": thread_id, "turnId": turn_id, "item": message}})
            send({"method": "turn/completed", "params": {"threadId": thread_id, "turn": {"id": turn_id, "status": "completed", "items": [message]}}})
            continue
        if method == "thread/compact/start":
            reply(request, {})
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
