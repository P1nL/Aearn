# Runner capability contract

## Goal

Define the shared runner interface, capability flags, result schema, unsupported-language response shape, and language runtime selection rules.

## Requirements

- Depend on `06-01-language-capability-contract`.
- Define the registry-facing runner interface for executable and non-executable runners.
- Define capability flags for execution, tests, preview, stdout, static analysis, compilation, timeout, memory limit, and sandbox policy.
- Define the normalized result schema that can preserve current `RuntimeExecutionResult` behavior.
- Define unsupported fallback shape for languages that can be taught or grounded but cannot be executed safely.
- Define selection rules from language capability, runtime profile, and exercise metadata.
- Keep runner code persistence-free and side-effect bounded.

## Acceptance Criteria

- [ ] Runner interface and result fields are documented before implementation starts.
- [ ] Selection rules cover Python, JavaScript/browser, HTML/CSS/browser, Java/C++ compiled-later, and future TypeScript/SQL/compiled categories.
- [ ] Unsupported fallback is product-safe and testable.
- [ ] Contract supports current run/submit result fields without forcing route rewrites.
- [ ] Contract explicitly prohibits durable writes from runner implementations.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
