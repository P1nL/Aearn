# Node TypeScript runner contract

## Goal

Define the future Node and TypeScript runner shape, including transpilation boundary, timeout, test format, and unsupported fallback until implemented.

## Requirements

- Depend on `06-01-runner-capability-contract`.
- Define Node JavaScript and TypeScript runner capability as planned, not executable in the first registry pass.
- Define future inputs for source files, transpilation or typecheck phase, test cases, stdout/stderr, timeout, and dependency policy.
- Define unsupported fallback for TypeScript and Node-specific execution until a safe runner exists.
- Avoid adding npm package execution, network access, or project filesystem access in this task.

## Acceptance Criteria

- [ ] Node/TypeScript runner contract exists as planned/unsupported capability metadata.
- [ ] TypeScript public support is not widened unless enum/catalog/frontend changes are also ready.
- [ ] Unsupported fallback explains that Node/TypeScript execution is not available yet while allowing lesson/grounding/static review planning.
- [ ] Future implementation requirements include dependency allowlist, timeout, transpilation/typecheck boundary, and output caps.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
