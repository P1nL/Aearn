# Technical Design: Real Code Execution

## Problem Analysis

`runtime_runner.py` never executes user code. It:
1. Python tier: `ast.parse(code)` for syntax check only
2. Browser tier: string searches for `addEventListener`, `output.textContent`, etc.
3. "Test results" are derived from regex matching against `acceptable_patterns_json`

This means all feedback is fabricated. A user could write syntactically valid but logically wrong code and still "pass" if it matches patterns.

## Architecture Decision

**Chosen approach: subprocess with timeout + restricted globals**

Rationale:
- Windows dev environment → nsjail/firejail (Linux-only) not available
- Docker cold start (~500ms) adds latency and complexity for MVP
- Pyodide has limited stdlib and no C extensions
- subprocess with `timeout` + restricted `__builtins__` is sufficient for MVP security
- Can upgrade to Docker containers for production later

### Security Model (MVP)

1. Execute in subprocess with `subprocess.run(timeout=...)` — process-level isolation
2. Restricted `__builtins__` — no `open`, `exec`, `eval`, `__import__` (except whitelisted modules)
3. No network access — don't pass env vars, restrict imports
4. Memory: subprocess inherits OS limits; for production, add Docker cgroups
5. Timeout: configurable per test case (default 10s total, 5s per case)

### Execution Flow

```
User submits code
    → API receives request
    → learning_session_repository calls run_exercise()
    → run_exercise() dispatches to sandbox_executor
    → sandbox_executor spawns subprocess per test case
    → subprocess: exec(user_code) in restricted namespace
    → subprocess: run assertion (call function with input, compare output)
    → collect results → build RuntimeExecutionResult
    → return to caller (unchanged contract)
```

## Module Design

### New: `app/services/sandbox.py`

Core execution engine. Responsibilities:
- Spawn subprocess to run user code
- Apply timeout and restricted environment
- Parse structured results from subprocess stdout (JSON protocol)
- Handle errors gracefully (syntax, runtime, timeout, sandbox violation)

```python
@dataclass
class SandboxResult:
    status: str          # "success" | "error" | "timeout" | "sandbox_error"
    stdout: str
    stderr: str
    return_value: object | None
    duration_ms: int

def execute_python(code: str, *, timeout_s: float = 10.0) -> SandboxResult:
    """Execute Python code in a subprocess with restricted globals."""

def execute_python_with_tests(
    code: str,
    test_cases: list[dict],
    *,
    timeout_s: float = 10.0,
) -> list[TestCaseResult]:
    """Execute code then run each test case against it."""
```

### New: `app/services/sandbox_runner.py` (subprocess entry point)

A standalone script that the subprocess executes. Protocol:
- Receives code + test cases via stdin (JSON)
- Executes code in restricted namespace
- Runs each test case (call function with input, compare output)
- Writes results to stdout (JSON)
- Exit code 0 = normal, non-zero = crash

### Modified: `app/services/runtime_runner.py`

- `run_exercise()` gains a new code path for `python_stdout_test` tier:
  - If `REAL_EXECUTION_ENABLED=true` (env var): use `sandbox.execute_python_with_tests`
  - Otherwise: fall back to existing pattern-matching behavior
- `browser_preview` tier: keep existing behavior for now (JS execution deferred to follow-up)
- `RuntimeExecutionResult` contract unchanged

### Modified: `app/agents/tools.py`

- `do_trigger_code_run` already calls `ctx.run_code_fn(ctx.exercise, code)`
- The `run_code_fn` will be wired to the new real execution path
- No changes needed in tools.py itself

## Test Case Execution Protocol

Given `test_cases` table schema:
```
input_json: {"args": [1, 2], "kwargs": {}}
expected_output_json: {"return": 3, "stdout": ""}
assertion_code: "assert result == expected"  (optional custom assertion)
```

Execution per test case:
1. `exec(user_code, restricted_globals)` — defines functions/variables
2. Determine entry point: look for function matching exercise metadata, or use `main()`
3. Call entry point with `input_json.args` and `input_json.kwargs`
4. Compare return value with `expected_output_json.return`
5. If `assertion_code` is provided, run it with `result` and `expected` in scope
6. Capture stdout during execution for `expected_output_json.stdout` comparison

## Restricted Globals

```python
SAFE_BUILTINS = {
    "abs", "all", "any", "bin", "bool", "chr", "dict", "divmod",
    "enumerate", "filter", "float", "format", "frozenset", "hash",
    "hex", "int", "isinstance", "issubclass", "iter", "len", "list",
    "map", "max", "min", "next", "oct", "ord", "pow", "print",
    "range", "repr", "reversed", "round", "set", "slice", "sorted",
    "str", "sum", "tuple", "type", "zip",
}

ALLOWED_IMPORTS = {
    "math", "random", "string", "collections", "itertools",
    "functools", "operator", "re", "json", "datetime",
}
```

## Feature Flag

`REAL_EXECUTION_ENABLED` env var (default: `"true"` for new installs).
When disabled, falls back to existing pattern-matching behavior — zero regression risk.

## SSE Compatibility

No changes. `RuntimeExecutionResult` is the same dataclass. The only difference is that `stdout`/`stderr` will contain real output instead of empty strings or canned messages.

## Files to Create

- `app/services/sandbox.py` — execution engine
- `app/services/sandbox_runner.py` — subprocess entry point script
- `tests/test_sandbox.py` — unit tests for sandbox execution

## Files to Modify

- `app/services/runtime_runner.py` — add real execution path
- `app/core/config.py` — add `REAL_EXECUTION_ENABLED` setting

## Risk Mitigation

- Feature flag allows instant rollback
- Existing pattern-matching tests continue to pass (they test the fallback path)
- Subprocess timeout prevents infinite loops from hanging the server
- Restricted globals prevent file/network access
- For production: upgrade to Docker-based execution (separate task)
