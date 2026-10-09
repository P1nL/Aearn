#!/usr/bin/env python3
"""P6-only parent-protected fixed sandbox protocol entrypoint.

Only a successful fixed adapter may emit facts. Same-UID candidate children
cannot read trusted parent process FDs/memory through proc/ptrace.
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
from pathlib import Path

MAX_INPUT_BYTES = 98_304


def _protect_parent() -> bool:
    """Fail closed if Linux parent process protection cannot be installed."""
    if sys.platform != "linux" or os.getuid() != 10001:
        return False
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl.restype = ctypes.c_int
        # prctl is variadic: pass its arguments as the specified C long.
        return libc.prctl(4, ctypes.c_long(0), ctypes.c_long(0), ctypes.c_long(0), ctypes.c_long(0)) == 0
    except (OSError, AttributeError):
        return False


def main() -> int:
    if not _protect_parent():
        return _emit("failed", "runtime_parent_protection_unavailable")
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
    except OSError:
        return _emit("failed", "runtime_adapter_unavailable")
    if completed.returncode != 0:
        return _emit("failed", "runtime_adapter_failed")
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
