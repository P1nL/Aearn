# Compiled language runner contract

## Goal

Define compiled-language runner expectations for Java, Go, C#, Rust, and C++, including compile/test phases and compiled_sandbox_later fallback.

## Requirements

- Depend on `06-01-runner-capability-contract`.
- Define compiled runner capability as planned for Java, Go, C#, Rust, and C++.
- Preserve current Java/C++ `compiled_sandbox_later` placeholder semantics.
- Define future phases: prepare source, compile, run tests, capture stdout/stderr, enforce timeout/memory, cleanup, and map diagnostics.
- Require safe process/container boundary before enabling execution.
- Define product-safe fallback for compiled languages until the safe runner exists.

## Acceptance Criteria

- [ ] Compiled-language runner contract exists as planned/unsupported capability metadata.
- [ ] Java and C++ current placeholder behavior remains compatible.
- [ ] Go, C#, and Rust are represented as planned capability without widening public course support.
- [ ] Contract requires compile/test diagnostic redaction and no hidden test leakage.
- [ ] No compiled execution is claimed as available in this task.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
