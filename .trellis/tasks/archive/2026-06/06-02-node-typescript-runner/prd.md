# Node TypeScript Runner

## Goal

Implement the teaching-grade Node/TypeScript runner contract for local L3 exercises without opening TypeScript public course selection yet.

## User Value

- Aearn can validate TypeScript-style function exercises locally when an exercise explicitly targets the Node/TypeScript runner.
- Environment doctor and capability disclosures can move TypeScript from planned-runner to implemented-runner honestly.
- The product still avoids overclaiming a complete TypeScript course until route/content/UI work exists.

## Dependencies

- Depends on `runner_registry.py` and `runtime_runner.py`.
- Depends on the environment doctor for Node/TypeScript toolchain visibility.
- Depends on the Python runner hardening patterns for temporary workspaces, bounded output, stable categories, and hidden redaction.

## Requirements

- Add a Node/TypeScript teaching runner for single-file exercises.
- Run in a temporary workspace and never write into the project directory.
- Compile TypeScript through local TypeScript tooling when available.
- Execute compiled JavaScript with Node under timeout and bounded output.
- Support visible/hidden test cases using `metadata_json.entry_function`.
- Map success, compile/syntax error, runtime error, timeout, test failure, missing toolchain, and sandbox/protocol error to stable learner-safe results.
- Redact hidden test case ids and hidden failure messages from public runner results.
- Keep TypeScript `enabled_for_public_selection=false` until a future course/content task explicitly enables it.

## Acceptance Criteria

- [ ] `node_typescript_test` runtime tier selects the Node runner and supports execution/tests/stdout.
- [ ] TypeScript function exercises can pass visible/hidden tests locally.
- [ ] Compile/syntax errors return learner-safe runtime errors.
- [ ] Function-call runtime exceptions return `runtime_error`.
- [ ] Hidden case ids and expected values do not appear in public `test_results`.
- [ ] TypeScript capability shows execution support but remains disabled for public selection.
- [ ] Existing Python/browser/compiled fallback runner behavior continues to pass.

## Out of Scope

- Public TypeScript course selection.
- Arbitrary npm projects, package installation, ESM package resolution, `npm install`, or network access.
- SQL, browser HTML/CSS, Java, Go, C#, Rust, or C++ runners.
- Full IDE/project execution.
