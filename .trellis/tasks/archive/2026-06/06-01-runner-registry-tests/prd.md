# Runner registry tests

## Goal

Add focused tests proving language-to-runner selection, Python sandbox adapter behavior, unsupported fallbacks, and capability metadata.

## Requirements

- Depend on the implementation tasks in `06-01-language-runtime-runner-registry`.
- Add tests for registry selection from runtime profile/capability metadata.
- Add tests for Python sandbox adapter success, syntax error, runtime error, timeout, and sandbox error behavior where practical.
- Add tests for unsupported fallback for Node/TypeScript, SQL, and compiled-language planned runners.
- Add tests proving browser preview and current `html_css` mapping remain represented.
- Add tests that prevent capability metadata from drifting away from public enum/catalog behavior.

## Acceptance Criteria

- [ ] Tests fail if Python no longer routes through the registry adapter.
- [ ] Tests fail if unsupported planned runners pretend to execute.
- [ ] Tests cover product-safe fallback messages and normalized result fields.
- [ ] Tests cover current public languages and future planned categories.
- [ ] Tests can run with existing backend pytest command and no live model credentials.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
