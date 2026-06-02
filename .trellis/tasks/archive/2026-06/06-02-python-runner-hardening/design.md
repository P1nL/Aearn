# Python Runner Hardening Design

## Existing Boundary

Python execution currently flows through:

1. `runtime_runner.run_exercise(...)`
2. `runner_registry.get_runner_registry().select(...)`
3. `RunnerRegistry.run_python(...)`
4. `sandbox.execute_python_with_tests(...)`
5. `sandbox_runner.py` subprocess

This child keeps that route intact. It hardens the Python runner contract without adding a new adapter family.

## Design Changes

### Temporary Workspace

`execute_python_with_tests(...)` should create a temporary directory and run the sandbox subprocess with that directory as `cwd`. This prevents accidental project-directory dependence and establishes the future runner pattern.

The sandbox still uses restricted builtins and allowlisted imports. This is not container-grade isolation.

### Output Bounding

The sandbox already caps raw subprocess output in several paths. The runner adapter should also bound the public `stdout`, `stderr`, and error message fields before building `RuntimeExecutionResult`.

### Public Test Result Sanitization

Internal sandbox results may retain raw test case ids and messages. Public `RuntimeExecutionResult.test_results` must sanitize hidden cases:

- hidden case ids become deterministic generic ids such as `hidden_case_1`
- hidden pass/fail messages become generic learner-safe messages
- visible case ids/messages remain useful

### Stable Runtime Categories

The adapter should preserve these public categories:

- `success`: user code ran and test results are available without runtime exceptions
- `runtime_error`: syntax error, top-level execution error, or function-call exception
- `timeout`: sandbox process timeout
- `sandbox_error`: sandbox startup/import/protocol failure
- `unsupported`: unchanged, owned by registry fallback

Incorrect visible or hidden test assertions remain `success` with failed test results unless they are caused by runtime exceptions.

## Compatibility

- Keep existing `test_sandbox.py` behavior where the raw sandbox can report internal status and per-case failures.
- Update runner-level tests for learner-safe public results.
- Do not change API response field names.
- Do not change the Python capability matrix except preserving disclosure.

## Rollback

- Revert sandbox subprocess `cwd` and public-result sanitization helpers.
- Existing deterministic/mock runner behavior remains available through `REAL_EXECUTION_ENABLED=false`.
