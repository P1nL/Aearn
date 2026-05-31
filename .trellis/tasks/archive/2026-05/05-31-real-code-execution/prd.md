# Real Code Execution

## Goal

Replace the fake `runtime_runner.py` (which only does `ast.parse` + regex pattern matching) with a real code execution sandbox. Users' code must actually run, produce real stdout/stderr, and pass/fail real test assertions.

This is the single most important capability gap for a programming learning product. Without real execution, all feedback is fabricated.

## Context

- Current `runtime_runner.py`:
  - Python tier: `ast.parse(code)` for syntax check only, never executes
  - Browser tier: string searches for specific patterns (`addEventListener`, `output.textContent`, etc.)
  - "Test results" are derived from regex matching against `acceptable_patterns_json`
  - `RUNNER_COMPILED_SANDBOX_ENABLED=false`, compiled tier returns "unsupported"
- Infrastructure available: Docker (via docker-compose), Celery + Redis (for async execution)
- Frontend already renders `runner_result` SSE events with stdout/stderr/test_pass_rate/test_results
- Exercise types: `code_blank`, `fix_bug`, `implement_function`, `explain_code`, `review_ai_patch`
- `test_cases` table exists with expected inputs/outputs per exercise
- No security sandbox currently exists

## Requirements

### Python Execution
- Execute user Python code in an isolated sandbox with:
  - No filesystem access beyond a temp working directory
  - No network access
  - Memory limit (128MB)
  - Time limit (10 seconds)
  - No access to environment variables or secrets
- Run test cases against user code: import user's function/module, execute test inputs, compare outputs
- Return structured results: stdout, stderr, per-test pass/fail with actual vs expected, overall pass rate
- Support the existing `test_cases` table schema (input_json, expected_output_json, is_hidden)

### Browser/JS Execution
- Execute user JavaScript in an isolated context with:
  - No access to Node.js APIs (fs, net, child_process)
  - DOM simulation for browser-tier exercises (jsdom or similar)
  - Time limit (5 seconds)
- Validate DOM state assertions for browser-tier exercises
- Return structured results matching the same schema as Python execution

### Integration
- Execution must be async (via Celery task or subprocess with timeout) — do not block the API request thread
- Results must flow back through the existing `runner_result` SSE event with unchanged payload shape
- `runtime_status` values: `success`, `error`, `timeout`, `sandbox_error`
- Existing `attempts` table records must store real execution results
- The `trigger_code_run` tool from `agent-write-tools` must invoke this real runner when available

### Security
- User code must never be able to:
  - Read/write files outside its sandbox
  - Make network requests
  - Access other users' data
  - Consume unbounded resources
  - Execute system commands
- Sandbox escape must result in `sandbox_error` status, not a server crash

## Acceptance Criteria

- [ ] Python code submitted by users actually executes and produces real stdout/stderr.
- [ ] Test cases from the `test_cases` table are run against user code with real input/output comparison.
- [ ] JavaScript code executes in an isolated context with DOM simulation.
- [ ] Execution respects time limits (10s Python, 5s JS) and returns `timeout` status when exceeded.
- [ ] Memory limits are enforced; OOM returns `sandbox_error`.
- [ ] No filesystem/network access from sandboxed code (verified by test).
- [ ] `runner_result` SSE event payload shape is unchanged — frontend renders results without modification.
- [ ] Execution is async — API response time is not blocked by code execution duration.
- [ ] At least one integration test runs real Python code through the full pipeline (submit → execute → result).
- [ ] At least one test verifies sandbox security (attempts to read files, make network calls, etc. all fail safely).
- [ ] Existing exercise flow (run → feedback → submit → evaluate) works end-to-end with real execution.

## Out of Scope

- Compiled language support (Java, C++, Rust) — deferred to future work.
- Custom test frameworks or complex multi-file projects.
- Remote execution service (cloud sandbox) — local Docker/subprocess is sufficient for MVP.
- Changing exercise types or test case schema.
- Frontend changes (existing `runner_result` rendering is sufficient).

## Technical Options (to be decided in design.md)

1. **Docker-based**: spin up a container per execution with resource limits via cgroups. Secure but ~500ms cold start.
2. **Pyodide (WASM)**: run Python in WebAssembly. Fast, inherently sandboxed, but limited stdlib and no C extensions.
3. **RestrictedPython + subprocess**: restricted AST transform + subprocess with ulimit. Lighter than Docker but weaker isolation.
4. **Celery worker with nsjail/firejail**: execute in the existing worker with syscall filtering. Good balance of security and performance.

## Dependencies

- Independent of Layer 1 agent work — can start immediately.
- Enables: `agent-write-tools` `trigger_code_run` tool returns real results instead of heuristic matches.
- Uses: existing Celery + Redis infrastructure, existing `test_cases` table, existing `attempts` table.

## Risks

- Docker cold start latency may frustrate users. Mitigation: pre-warm containers or use Pyodide for Python.
- Sandbox escape vulnerabilities. Mitigation: defense in depth (container + seccomp + resource limits).
- Pyodide limitations (no threading, limited stdlib). Mitigation: document unsupported patterns, fall back to Docker for complex cases.
