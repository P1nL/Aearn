# Node TypeScript Runner Design

## Boundary

This child adds a single-file teaching runner. It is not a general Node project runner.

Supported input shape:

- `runtime_profile.runtime_tier = "node_typescript_test"`
- `runtime_profile.language = "typescript"` or `javascript`
- `metadata_json.entry_function` names the callable function
- `test_cases[*].input_json.args` and optional `kwargs`
- `test_cases[*].expected_output_json.return`

## Service Design

Add `app/services/node_typescript_runner.py` with:

- `execute_node_typescript_with_tests(...)`
- typed result dataclasses mirroring the Python sandbox result boundary
- toolchain detection for `node` and `tsc`
- temporary workspace execution
- timeout handling
- bounded stdout/stderr/error text

The runner writes:

- `submission.ts`
- compiled JavaScript output
- a generated learner-safe harness

The harness should call the entry function for each test case and return JSON results. It must not expose hidden raw ids in public `RuntimeExecutionResult`; hidden sanitization happens at the Python adapter boundary.

## Registry and Runtime Flow

- Add `node_typescript_test` to the language capability execution modes.
- Change TypeScript capability from planned execution to executable runner support while keeping `enabled_for_public_selection=false`.
- Change `NODE_TYPESCRIPT_RUNNER` to `supports_execution=True`, `supports_tests=True`, `supports_stdout=True`.
- Add `RunnerRegistry.run_node_typescript(...)`.
- In `runtime_runner.run_exercise(...)`, dispatch `runner_key == "node"` to the Node/TypeScript runner.

## Missing Toolchain

If Node or TypeScript tooling is missing, return a stable non-crashing runner result. Because the current public frontend runtime status union does not yet include `missing_toolchain`, this child maps missing local tooling to `runtime_status="unsupported"` with a precise error message. The environment doctor remains the product surface that reports `missing`.

## Safety

- No network.
- No package installation.
- No writes outside the temporary workspace.
- No global PATH or system changes.
- Hidden test ids/messages are sanitized before public output.

## Compatibility

- Existing public course language IDs remain unchanged.
- Existing TypeScript public selection remains disabled.
- Java/Go/C#/Rust/SQL planned disclosures remain unchanged.
- Python runner behavior from the previous child must keep passing.
