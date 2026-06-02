# 06 Language L3 Runner Contracts

## Goal

Coordinate the L3 teaching-runner rollout for Python, Node/TypeScript, browser HTML/CSS, SQL, and managed compiled languages while keeping product capability disclosures honest.

## Requirements

- Keep the runner domain parent in planning; do not start it for concrete adapter work.
- Implement each runner family in its own child task with focused acceptance criteria and validation.
- Preserve the existing capability matrix and runner registry as the canonical disclosure boundary.
- Do not present a language as executable until its adapter, tests, API behavior, and UI disclosure agree.
- Preserve local-only safety boundaries: temporary workspaces, timeouts, bounded stdout/stderr, no network by default, no project-directory writes, hidden-test redaction, and stable failure categories.

## Child Task Order

1. `python-runner-hardening` (archived)
2. `node-typescript-runner` (archived)
3. `browser-html-css-runner` (archived)
4. `sql-query-runner` (archived)
5. `managed-compiled-runners-java-go-csharp` (deferred to Phase 3; not selected for P2 implementation)

## Deferred Runner Families

- Java, Go, and C# teaching runners remain planned for Phase 3.
- They must not be disclosed as executable until their own runner adapters, tests, environment doctor behavior, API behavior, and UI disclosures agree.
- Rust and C++ remain out of scope for L3 execution.

## Acceptance Criteria

- [x] Each selected runner child is archived or explicitly deferred with a reason.
- [x] Capability matrix, runner registry, environment doctor, API responses, and desktop disclosures remain consistent.
- [x] Runner result contracts distinguish success, syntax/compile error, runtime error, timeout, test failure, unsupported, and missing toolchain where applicable.
- [x] Hidden tests, raw hidden ids, solution references, prompts, and internal runner details are not exposed to learners.

## Out of Scope

- Starting this parent task directly.
- Rust and C++ L3 execution.
- Arbitrary project execution or package installation.
