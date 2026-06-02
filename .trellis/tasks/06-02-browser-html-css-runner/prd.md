# Browser HTML CSS runner

## Goal

Implement and productize the browser HTML/CSS teaching runner contract for local L3 exercises.

## User Value

- JavaScript, HTML, and CSS browser-preview exercises use an explicit runner adapter instead of ad-hoc logic inside `runtime_runner.py`.
- HTML/CSS static preview exercises are validated honestly without requiring JavaScript event-binding rules.
- Browser-preview capability disclosures, registry behavior, runtime results, and tests stay aligned with the local-only product boundary.

## Requirements

- Add a browser-preview teaching runner service for local deterministic preview checks.
- Preserve the existing `browser_preview` runtime tier and public course ids.
- Support JavaScript event-flow exercises with event binding, output sync, shared state checks, preview HTML, visible tests, and hidden tests.
- Support HTML/CSS static preview exercises with required patterns, blank gates, preview assertions, preview HTML, visible tests, and hidden tests.
- Keep the runner local and deterministic: no network, no package installation, no arbitrary browser automation, no project-directory writes.
- Return stable learner-safe categories for success, runtime error, timeout, test failure, and unsupported fallback behavior.
- Redact hidden test case ids, hidden expected values, and hidden failure details from public runtime output.
- Keep existing Python, Node/TypeScript, SQL, and compiled-language runner behavior unchanged.

## Acceptance Criteria

- [ ] `browser_preview` selects the browser runner and exposes execution/tests/stdout/preview support.
- [ ] JavaScript event exercises still pass/fail according to event binding, output sync, shared state, and preview assertion rules.
- [ ] HTML/CSS static exercises can pass without `addEventListener` or `output.textContent`.
- [ ] Browser runtime-error and timeout cases return stable `runtime_error` / `timeout` results.
- [ ] Hidden browser test ids and expected values do not appear in public `test_results`.
- [ ] Existing Python, Node/TypeScript, SQL, compiled fallback, M3, and M4 behavior continues to pass.

## Notes

- This child does not add real headless-browser execution, arbitrary JS project execution, npm package installs, or network access.
- This child does not change public language selection.
