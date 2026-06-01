# Python sandbox adapter

## Goal

Adapt the existing Python subprocess sandbox into the language runner registry without regressing current Python execution behavior.

## Requirements

- Depend on `06-01-runner-capability-contract`.
- Wrap the current `execute_python_with_tests()` path behind a Python runner adapter.
- Preserve current handling for syntax errors, runtime errors, timeouts, sandbox errors, stdout, visible/hidden test summaries, and next action mapping.
- Keep `REAL_EXECUTION_ENABLED` behavior compatible with existing deterministic fallback behavior.
- Do not broaden Python sandbox permissions while adapting it.
- Ensure adapter output matches the normalized registry result schema.

## Acceptance Criteria

- [ ] Python exercises can be routed through the registry to the existing subprocess sandbox.
- [ ] Existing Python success, syntax error, runtime error, timeout, and sandbox error paths remain covered.
- [ ] The adapter exposes capability metadata showing stdout/test support and no realtime preview.
- [ ] The adapter does not introduce persistence, network access, or filesystem write assumptions.
- [ ] Current learning/review run behavior remains compatible.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
