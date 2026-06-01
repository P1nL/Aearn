# Sandbox security boundary hardening

## Goal

Document and harden the sandbox boundary, including timeout behavior, allowed imports, output limits, process isolation limits, and explicit non-goals versus container isolation.

## Requirements

- Depend on `06-01-python-sandbox-adapter`.
- Document the current Python sandbox boundary as subprocess isolation, not OS-container isolation.
- Make timeout, restricted imports, output caps, process count assumptions, network behavior, filesystem behavior, and error redaction testable.
- Fail closed for blocked imports, timeout patterns, excessive output, and sandbox setup errors.
- Ensure user-facing messages do not expose raw internal paths, secrets, provider errors, or hidden test details.
- Keep stronger container isolation as a future runner/security task, not an implied current capability.

## Acceptance Criteria

- [ ] Sandbox boundary and non-goals are documented in task/design artifacts or source-adjacent docs.
- [ ] Tests cover blocked imports, timeout, output cap, and redacted sandbox error behavior where practical.
- [ ] Registry capability metadata says Python sandbox is not container-grade isolation.
- [ ] Unsupported or unsafe execution paths produce `unsupported`, `timeout`, `runtime_error`, or `sandbox_error` style results instead of crashing.
- [ ] No new permissions are granted to Python execution.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
