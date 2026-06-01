# Browser preview runner contract

## Goal

Define the runner contract for HTML/CSS/browser preview execution and its no-test or visual-preview limitations.

## Requirements

- Depend on `06-01-runner-capability-contract`.
- Define how `javascript` and combined `html_css` map to browser preview capability.
- Preserve current deterministic preview/test inspection behavior until a real browser runner is introduced.
- Define preview output, DOM assertion, runtime error, timeout, and unsupported result semantics.
- State that browser preview is not arbitrary network-enabled web execution.
- Keep HTML and CSS split capability metadata compatible with the existing `html_css` public course language.

## Acceptance Criteria

- [ ] Browser preview runner capability exposes realtime preview support and DOM/preview assertion support.
- [ ] Contract states current limitations: no arbitrary internet access, no persistent filesystem, and no full browser automation sandbox in this task.
- [ ] JavaScript and `html_css` current behavior can be represented without changing public course enums.
- [ ] Later browser runner implementation has a testable result schema to target.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
