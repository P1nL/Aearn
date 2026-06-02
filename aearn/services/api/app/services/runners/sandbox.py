"""Sandbox execution engine.

Spawns a subprocess running sandbox_runner.py to execute user code
in an isolated environment with restricted globals and timeout.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


SANDBOX_RUNNER_PATH = Path(__file__).parent / "sandbox_runner.py"


@dataclass(slots=True)
class TestCaseResult:
    case_id: str
    case_type: str
    passed: bool
    weight: float
    is_critical: bool
    message: str
    duration_ms: int


@dataclass(slots=True)
class SandboxExecutionResult:
    status: str
    stdout: str
    stderr: str
    error: str | None
    test_results: list[TestCaseResult]
    total_duration_ms: int


def execute_python_with_tests(
    code: str,
    test_cases: Sequence[Mapping[str, object]],
    *,
    entry_function: str | None = None,
    timeout_s: float = 10.0,
) -> SandboxExecutionResult:
    """Execute Python code in a sandboxed subprocess and run test cases against it."""
    payload_dict: dict[str, object] = {
        "code": code,
        "test_cases": [dict(tc) for tc in test_cases],
    }
    if entry_function:
        payload_dict["entry_function"] = entry_function
    payload = json.dumps(payload_dict)

    start = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix="aearn-python-") as temp_dir:
            proc = subprocess.run(
                [sys.executable, str(SANDBOX_RUNNER_PATH)],
                input=payload,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                cwd=temp_dir,
                env=_sandbox_env(),
            )
    except subprocess.TimeoutExpired:
        elapsed = int((time.perf_counter() - start) * 1000)
        return SandboxExecutionResult(
            status="timeout",
            stdout="",
            stderr="",
            error="Execution timed out",
            test_results=[],
            total_duration_ms=elapsed,
        )
    except OSError as exc:
        elapsed = int((time.perf_counter() - start) * 1000)
        return SandboxExecutionResult(
            status="sandbox_error",
            stdout="",
            stderr="",
            error=f"Failed to start sandbox: {exc}",
            test_results=[],
            total_duration_ms=elapsed,
        )

    elapsed = int((time.perf_counter() - start) * 1000)

    if proc.returncode != 0 and not proc.stdout.strip():
        return SandboxExecutionResult(
            status="sandbox_error",
            stdout=proc.stdout[:4000],
            stderr=proc.stderr[:4000],
            error=f"Sandbox process exited with code {proc.returncode}",
            test_results=[],
            total_duration_ms=elapsed,
        )

    try:
        result = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        return SandboxExecutionResult(
            status="sandbox_error",
            stdout=proc.stdout[:2000],
            stderr=proc.stderr[:2000],
            error="Failed to parse sandbox output",
            test_results=[],
            total_duration_ms=elapsed,
        )

    status = str(result.get("status", "sandbox_error"))
    stdout = str(result.get("stdout", ""))
    stderr = str(result.get("stderr", ""))
    error = result.get("error")
    raw_results = result.get("test_results", [])

    test_results: list[TestCaseResult] = []
    for raw in raw_results:
        if not isinstance(raw, dict):
            continue
        test_results.append(TestCaseResult(
            case_id=str(raw.get("case_id", "unknown")),
            case_type=str(raw.get("case_type", "visible")),
            passed=bool(raw.get("passed", False)),
            weight=float(raw.get("weight", 1)),
            is_critical=bool(raw.get("is_critical", False)),
            message=str(raw.get("message", "")),
            duration_ms=elapsed // max(len(raw_results), 1),
        ))

    return SandboxExecutionResult(
        status=status,
        stdout=stdout,
        stderr=stderr,
        error=str(error) if error else None,
        test_results=test_results,
        total_duration_ms=elapsed,
    )


def _sandbox_env() -> dict[str, str]:
    env: dict[str, str] = {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    }
    for key in ("PATH", "SYSTEMROOT", "SystemRoot", "WINDIR", "TEMP", "TMP"):
        value = os.environ.get(key)
        if value:
            env[key] = value
    return env
