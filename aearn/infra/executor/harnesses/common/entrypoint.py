#!/usr/bin/env python3
"""Fixed in-image bridge for the versioned sandbox protocol.

A reviewed production image supplies `/opt/aearn/runtime-adapter`.  The bridge
never accepts a command, image, path, mount, network setting, or user runtime
flag from stdin.  Without that prebuilt adapter, it returns a safe unavailable
result; this prevents an unreviewed local build from becoming executable merely
because it exists on a machine.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


MAX_INPUT_BYTES = 98_304


def main() -> int:
    payload = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(payload) > MAX_INPUT_BYTES:
        return _emit("failed", "sandbox_input_too_large")
    try:
        request = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _emit("failed", "sandbox_protocol_invalid")
    runtime_id = os.environ.get("AEARN_RUNTIME_ID", "")
    if (
        not isinstance(request, dict)
        or request.get("schema_version") != "sandbox-input-v1"
        or request.get("runtime_id") != runtime_id
        or request.get("action") not in {"run", "test", "debug", "explain"}
    ):
        return _emit("failed", "sandbox_protocol_invalid")

    adapter = Path("/opt/aearn/runtime-adapter")
    if not adapter.is_file() or not os.access(adapter, os.X_OK):
        return _emit("unavailable", "runtime_adapter_not_enabled")

    try:
        completed = subprocess.run(
            [str(adapter)],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd="/work",
            env={
                "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "HOME": "/tmp",
                "AEARN_RUNTIME_ID": runtime_id,
                "AEARN_MAX_OUTPUT_BYTES": os.environ.get("AEARN_MAX_OUTPUT_BYTES", "8192"),
            },
            timeout=max(1, int(os.environ.get("AEARN_WALL_CLOCK_SECONDS", "15"))),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _emit("timeout", "runtime_wall_clock_exceeded")
    raw = completed.stdout[: int(os.environ.get("AEARN_MAX_OUTPUT_BYTES", "8192"))]
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _emit("failed", "sandbox_protocol_invalid")
    if not isinstance(result, dict) or result.get("schema_version") != "sandbox-result-v1":
        return _emit("failed", "sandbox_protocol_invalid")
    sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


def _emit(status: str, code: str) -> int:
    sys.stdout.write(
        json.dumps(
            {
                "schema_version": "sandbox-result-v1",
                "status": status,
                "stdout": "",
                "stderr": "",
                "test_feedback": [],
                "passed_test_count": 0,
                "total_test_count": 0,
                "duration_ms": 0,
                "diagnostic_code": code,
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
