from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


MAX_NODE_OUTPUT_CHARS = 4000
MAX_NODE_ERROR_CHARS = 2000
HARNESS_FILENAME = "harness.js"
SOURCE_FILENAME = "submission.ts"


@dataclass(slots=True)
class NodeTestCaseResult:
    case_id: str
    case_type: str
    passed: bool
    weight: float
    is_critical: bool
    message: str
    duration_ms: int


@dataclass(slots=True)
class NodeExecutionResult:
    status: str
    stdout: str
    stderr: str
    error: str | None
    test_results: list[NodeTestCaseResult]
    total_duration_ms: int


def execute_node_typescript_with_tests(
    code: str,
    test_cases: Sequence[Mapping[str, object]],
    *,
    entry_function: str | None = None,
    timeout_s: float = 10.0,
    node_command: str | None = None,
    tsc_command: str | None = None,
    detect_commands: bool = True,
) -> NodeExecutionResult:
    start = time.perf_counter()
    node = node_command or (_find_node_command() if detect_commands else None)
    tsc = tsc_command or (_find_tsc_command() if detect_commands else None)
    if node is None or tsc is None:
        return NodeExecutionResult(
            status="missing_toolchain",
            stdout="",
            stderr="",
            error="Node.js and TypeScript compiler are required for node_typescript_test.",
            test_results=[],
            total_duration_ms=_elapsed_ms(start),
        )

    with tempfile.TemporaryDirectory(prefix="aearn-node-") as temp_dir:
        workspace = Path(temp_dir)
        source_path = workspace / SOURCE_FILENAME
        source_path.write_text(code, encoding="utf-8")

        compile_result = _compile_typescript(tsc, source_path, workspace, timeout_s)
        if compile_result.returncode != 0:
            return NodeExecutionResult(
                status="compile_error",
                stdout=_bound_text(compile_result.stdout, MAX_NODE_OUTPUT_CHARS),
                stderr=_bound_text(compile_result.stderr, MAX_NODE_ERROR_CHARS),
                error=_bound_text(compile_result.stderr or compile_result.stdout or "TypeScript compile failed.", MAX_NODE_ERROR_CHARS),
                test_results=[],
                total_duration_ms=_elapsed_ms(start),
            )

        compiled_path = workspace / "dist" / "submission.js"
        if not compiled_path.exists():
            return NodeExecutionResult(
                status="sandbox_error",
                stdout="",
                stderr="",
                error="TypeScript compiler did not produce submission.js.",
                test_results=[],
                total_duration_ms=_elapsed_ms(start),
            )

        harness_path = workspace / HARNESS_FILENAME
        harness_path.write_text(
            _build_harness(compiled_path, tuple(dict(test_case) for test_case in test_cases), entry_function),
            encoding="utf-8",
        )
        return _run_harness(node, harness_path, timeout_s, start)


def _compile_typescript(tsc: str, source_path: Path, workspace: Path, timeout_s: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            tsc,
            str(source_path),
            "--target",
            "ES2020",
            "--module",
            "commonjs",
            "--strict",
            "--skipLibCheck",
            "--noEmitOnError",
            "true",
            "--outDir",
            str(workspace / "dist"),
        ],
        capture_output=True,
        text=True,
        timeout=timeout_s,
        cwd=str(workspace),
        env=_node_env(),
        check=False,
    )


def _run_harness(node: str, harness_path: Path, timeout_s: float, start: float) -> NodeExecutionResult:
    try:
        completed = subprocess.run(
            [node, str(harness_path)],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=str(harness_path.parent),
            env=_node_env(),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return NodeExecutionResult(
            status="timeout",
            stdout="",
            stderr="",
            error="Node/TypeScript execution timed out.",
            test_results=[],
            total_duration_ms=_elapsed_ms(start),
        )
    except OSError as exc:
        return NodeExecutionResult(
            status="sandbox_error",
            stdout="",
            stderr="",
            error=f"Failed to start Node runner: {exc}",
            test_results=[],
            total_duration_ms=_elapsed_ms(start),
        )

    stdout = _bound_text(completed.stdout, MAX_NODE_OUTPUT_CHARS)
    stderr = _bound_text(completed.stderr, MAX_NODE_ERROR_CHARS)
    if completed.returncode != 0 and not stdout.strip():
        return NodeExecutionResult(
            status="sandbox_error",
            stdout=stdout,
            stderr=stderr,
            error=f"Node runner exited with code {completed.returncode}.",
            test_results=[],
            total_duration_ms=_elapsed_ms(start),
        )

    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return NodeExecutionResult(
            status="sandbox_error",
            stdout=stdout,
            stderr=stderr,
            error="Failed to parse Node runner output.",
            test_results=[],
            total_duration_ms=_elapsed_ms(start),
        )

    raw_results = payload.get("test_results", [])
    test_results: list[NodeTestCaseResult] = []
    if isinstance(raw_results, list):
        for raw in raw_results:
            if not isinstance(raw, dict):
                continue
            test_results.append(
                NodeTestCaseResult(
                    case_id=str(raw.get("case_id", "unknown")),
                    case_type=str(raw.get("case_type", "visible")),
                    passed=bool(raw.get("passed", False)),
                    weight=float(raw.get("weight", 1)),
                    is_critical=bool(raw.get("is_critical", False)),
                    message=str(raw.get("message", "")),
                    duration_ms=int(raw.get("duration_ms", 0)),
                ),
            )

    status = str(payload.get("status", "sandbox_error"))
    error = payload.get("error")
    return NodeExecutionResult(
        status=status,
        stdout=_bound_text(str(payload.get("stdout", "")), MAX_NODE_OUTPUT_CHARS),
        stderr=stderr,
        error=_bound_text(str(error), MAX_NODE_ERROR_CHARS) if error else None,
        test_results=test_results,
        total_duration_ms=_elapsed_ms(start),
    )


def _build_harness(compiled_path: Path, test_cases: Sequence[Mapping[str, object]], entry_function: str | None) -> str:
    compiled_json = json.dumps(compiled_path.read_text(encoding="utf-8"))
    tests_json = json.dumps([dict(test_case) for test_case in test_cases])
    entry_json = json.dumps(entry_function or "main")
    return f"""
const vm = require("node:vm");
const util = require("node:util");

const compiledCode = {compiled_json};
const testCases = {tests_json};
const entryName = {entry_json};
const logs = [];
const moduleObject = {{ exports: {{}} }};
const context = {{
  console: {{
    log: (...args) => logs.push(args.map((value) => String(value)).join(" ")),
    error: (...args) => logs.push(args.map((value) => String(value)).join(" ")),
  }},
  exports: moduleObject.exports,
  module: moduleObject,
  Math,
  JSON,
  Date,
  RegExp,
  Array,
  Object,
  String,
  Number,
  Boolean,
  Set,
  Map,
  Promise,
  parseInt,
  parseFloat,
  isNaN,
  isFinite,
}};
context.globalThis = context;

function safeString(value) {{
  try {{
    return util.inspect(value, {{ depth: 3, breakLength: 120 }}).slice(0, 500);
  }} catch (_error) {{
    return "<unrepresentable>";
  }}
}}

function getEntryFunction() {{
  if (typeof context[entryName] === "function") return context[entryName];
  if (typeof moduleObject.exports[entryName] === "function") return moduleObject.exports[entryName];
  return null;
}}

function deepEqual(a, b) {{
  return JSON.stringify(a) === JSON.stringify(b);
}}

async function main() {{
  try {{
    vm.createContext(context);
    vm.runInContext(compiledCode, context, {{ timeout: 1000 }});
  }} catch (error) {{
    process.stdout.write(JSON.stringify({{
      status: "runtime_error",
      stdout: logs.join("\\n").slice(0, 4000),
      error: `${{error.name}}: ${{error.message}}`,
      test_results: [],
    }}));
    return;
  }}

  const fn = getEntryFunction();
  if (!fn) {{
    process.stdout.write(JSON.stringify({{
      status: "runtime_error",
      stdout: logs.join("\\n").slice(0, 4000),
      error: `Function '${{entryName}}' not defined in user code`,
      test_results: [],
    }}));
    return;
  }}

  const results = [];
  let hasRuntimeError = false;
  for (let index = 0; index < testCases.length; index += 1) {{
    const testCase = testCases[index] || {{}};
    const input = testCase.input_json && typeof testCase.input_json === "object" ? testCase.input_json : {{}};
    const expected = testCase.expected_output_json && typeof testCase.expected_output_json === "object" ? testCase.expected_output_json : {{}};
    const args = Array.isArray(input.args) ? input.args : [];
    const expectedReturn = Object.prototype.hasOwnProperty.call(expected, "return") ? expected.return : undefined;
    const started = Date.now();
    let passed = false;
    let message = "Passed";
    try {{
      const actual = await fn(...args);
      if (expectedReturn === undefined || deepEqual(actual, expectedReturn)) {{
        passed = true;
      }} else {{
        message = `Expected ${{safeString(expectedReturn)}}, got ${{safeString(actual)}}`;
      }}
    }} catch (error) {{
      hasRuntimeError = true;
      message = `${{error.name}}: ${{error.message}}`;
    }}
    results.push({{
      case_id: String(testCase.id || `case_${{index + 1}}`),
      case_type: String(testCase.case_type || "visible"),
      passed,
      weight: Number(testCase.weight || 1),
      is_critical: Boolean(testCase.is_critical),
      message,
      duration_ms: Math.max(0, Date.now() - started),
    }});
  }}

  process.stdout.write(JSON.stringify({{
    status: hasRuntimeError ? "runtime_error" : "success",
    stdout: logs.join("\\n").slice(0, 4000),
    error: null,
    test_results: results,
  }}));
}}

main().catch((error) => {{
  process.stdout.write(JSON.stringify({{
    status: "sandbox_error",
    stdout: logs.join("\\n").slice(0, 4000),
    error: `${{error.name}}: ${{error.message}}`,
    test_results: [],
  }}));
}});
"""


def _find_node_command() -> str | None:
    return shutil.which("node")


def _find_tsc_command() -> str | None:
    candidates: list[str] = []
    if os.name == "nt":
        candidates.extend(filter(None, [shutil.which("tsc.cmd"), shutil.which("tsc.exe"), shutil.which("tsc")]))
    else:
        found = shutil.which("tsc")
        if found:
            candidates.append(found)
    candidates.extend(str(path) for path in _local_tsc_candidates())
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _local_tsc_candidates() -> tuple[Path, ...]:
    aearn_root = Path(__file__).resolve().parents[4]
    suffix = "tsc.CMD" if os.name == "nt" else "tsc"
    return (
        aearn_root / "node_modules" / ".pnpm" / "node_modules" / ".bin" / suffix,
        aearn_root / "apps" / "desktop" / "node_modules" / ".bin" / suffix,
    )


def _node_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for key in ("PATH", "SYSTEMROOT", "SystemRoot", "WINDIR", "TEMP", "TMP"):
        value = os.environ.get(key)
        if value:
            env[key] = value
    return env


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _bound_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3] + "..."
