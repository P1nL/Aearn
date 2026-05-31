# Implementation Plan: Real Code Execution

## Ordered Steps

1. Add `REAL_EXECUTION_ENABLED` setting to `app/core/config.py`.

2. Create `app/services/sandbox_runner.py` — the subprocess entry point script:
   - Reads JSON from stdin: `{"code": "...", "test_cases": [...], "entry_function": "..."}`
   - Executes code in restricted namespace (SAFE_BUILTINS, controlled `__import__`)
   - Runs each test case: call entry function with inputs, compare outputs
   - Writes JSON results to stdout
   - Handles errors gracefully (SyntaxError, RuntimeError, timeout, import violations)

3. Create `app/services/sandbox.py` — the execution engine:
   - `execute_python_with_tests(code, test_cases, *, entry_function, timeout_s)` → list of per-case results
   - Spawns subprocess running `sandbox_runner.py`
   - Passes input via stdin, reads structured JSON from stdout
   - Handles subprocess timeout (returns timeout status)
   - Handles subprocess crash (returns sandbox_error status)

4. Modify `app/services/runtime_runner.py`:
   - Import sandbox module
   - In `run_exercise()`, for `python_stdout_test` tier:
     - If `REAL_EXECUTION_ENABLED`: call `sandbox.execute_python_with_tests`
     - Map sandbox results to `RuntimeExecutionResult` (same contract)
     - Fall back to existing pattern-matching if sandbox is disabled
   - Keep all existing helper functions for fallback path

5. Create `tests/test_sandbox.py`:
   - Test: simple function executes and returns correct result
   - Test: syntax error returns runtime_error status
   - Test: infinite loop returns timeout status
   - Test: import os/subprocess/socket raises sandbox_error
   - Test: open() is blocked
   - Test: multiple test cases run independently
   - Test: stdout capture works
   - Test: function with multiple args works
   - Test: assertion_code custom assertion works

6. Verify existing tests still pass (pattern-matching fallback path).

7. Run full validation.

## Validation Commands

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_sandbox.py -v
uv --directory .\aearn\services\api run python -m pytest tests/ -v
uv --directory .\aearn\services\api run ruff check app/services/sandbox.py app/services/sandbox_runner.py app/services/runtime_runner.py
uv --directory .\aearn\services\api run python -m mypy --follow-imports=skip app/services/sandbox.py app/services/sandbox_runner.py app/services/runtime_runner.py
```

## Review Gates

- `RuntimeExecutionResult` contract unchanged — no frontend changes needed
- Existing tests pass without modification (fallback path)
- Sandbox tests prove real execution works
- Security tests prove restricted access works
- Feature flag allows instant rollback

## Rollback Points

- Set `REAL_EXECUTION_ENABLED=false` to revert to pattern-matching behavior
- No schema changes, no migration needed
- No dependency additions needed (subprocess is stdlib)
