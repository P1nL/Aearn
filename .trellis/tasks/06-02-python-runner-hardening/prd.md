# Python Runner Hardening

## Goal

Harden Aearn's existing Python teaching runner so it satisfies the Phase 1 L3 baseline for safe local exercises: temporary workspace execution, bounded outputs, stable runtime categories, hidden-test redaction, and honest non-container disclosure.

## User Value

- Learners get reliable Python run feedback without hidden test leakage.
- Runtime errors, syntax errors, timeouts, and test failures are distinguishable for Agent guidance and scoring.
- Aearn can truthfully call Python executable while still disclosing that the sandbox is subprocess-based, not container-grade isolation.

## Dependencies

- Depends on `runner_registry.py`, `runtime_runner.py`, `sandbox.py`, and `sandbox_runner.py`.
- Depends on `environment_doctor.py` for settings disclosure but does not change toolchain detection.
- Depends on `docs/architecture/code-completion-evaluation-spec.md` for runtime/test/result semantics.

## Requirements

- Run Python code in a temporary workspace rather than the project directory.
- Preserve the existing subprocess sandbox and allowed-import behavior.
- Keep stdout/stderr/error payloads bounded.
- Map Python syntax errors, top-level execution errors, function-call runtime errors, timeouts, sandbox errors, test failures, and success to stable learner-safe `RuntimeExecutionResult` categories.
- Redact hidden test case ids and hidden failure messages from public runner results.
- Keep visible test feedback useful.
- Keep `sandbox_policy["is_container_grade"]` false and do not claim OS/container isolation.
- Do not introduce Docker/container execution in this child.

## Acceptance Criteria

- [ ] Python sandbox subprocess runs from a temporary workspace.
- [ ] Python stdout/stderr/error payloads remain bounded.
- [ ] Python function-call exceptions return `runtime_status="runtime_error"` rather than a misleading success.
- [ ] Hidden case ids such as `hidden_*` do not appear in public `test_results` or error messages.
- [ ] Visible failures still include useful learner-safe messages.
- [ ] Existing sandbox blocked-import behavior still passes.
- [ ] Focused sandbox and runner tests pass with `ruff`, `mypy`, and desktop check.

## Out of Scope

- Node/TypeScript, SQL, browser, Java, Go, C#, Rust, or C++ runner implementation.
- Docker/container-grade sandboxing.
- Database schema changes.
- UI redesign beyond existing runner disclosure surfaces.
