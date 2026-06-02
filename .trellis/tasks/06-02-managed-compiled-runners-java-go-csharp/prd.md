# Managed compiled runners for Java, Go, and C#

## Goal

Implement teaching-grade L3 managed compiled runners for Java, Go, and C# while preserving Aearn's local-only safety boundary and honest capability disclosure.

This task turns Java, Go, and C# from planned/static compiled-language slots into capability-gated local exercise runners. It is not a general IDE, project runner, package manager, or arbitrary build-system executor.

## User Value

- Learners can run small single-file Java, Go, and C# teaching exercises locally when the matching local toolchain is installed.
- Learners get stable, learner-safe feedback for missing toolchains, compile errors, runtime errors, timeouts, failed visible/hidden tests, and successful runs.
- Settings and language disclosures stay honest: a language appears executable only when the runner adapter, tests, environment doctor, API contract, and desktop UI agree.
- Rust and C++ remain clearly non-executable in this phase, avoiding overclaims from the shared compiled-language registry.

## Dependencies

- Parent planning task: `.trellis/tasks/06-02-local-product-completion`.
- Archived runner coordination contract: `.trellis/tasks/archive/2026-06/06-02-06-language-l3-runner-contracts/prd.md`.
- Existing P2 runner baselines: `python-runner-hardening`, `node-typescript-runner`, `browser-html-css-runner`, and `sql-query-runner` are already archived.
- Existing adaptive exercise validation can consume runner results but must not generate Java/Go/C# executable variants until this runner contract is validated.
- P2 adaptive exercise decision remains in force: model-assisted generation is the primary path for candidate variants, but only inside a canonical template envelope and only after matching runner validation passes.
- Existing environment doctor already detects `javac`, `go`, and `dotnet`; this task must change their product disclosure only after compiled runner tests pass.
- Existing backend contracts in `.trellis/spec/backend/quality-guidelines.md`, `docs/architecture/api-contract.md`, and `docs/architecture/code-completion-evaluation-spec.md`.
- Existing frontend contracts in `.trellis/spec/frontend/quality-guidelines.md` and `docs/product/frontend-interaction-spec.md`.
- Inline execution mode: the main session implements and checks directly; do not dispatch implement/check sub-agents.

## Confirmed Facts

- `app/services/language_capabilities.py` currently has Java, Go, and C# on `execution="compiled_later"` and `runner_key="compiled"`; Rust and C++ also share the compiled planned boundary.
- `app/services/runner_registry.py` currently has `COMPILED_LANGUAGE_RUNNER` with `supports_execution=False`.
- `app/services/environment_doctor.py` already probes `javac`, `go`, and `dotnet`, but reports Java as `static_review` and Go/C# as `planned`.
- The DB runtime profile CHECK currently allows `compiled_sandbox_later` but not a real managed compiled runtime tier.
- The public course CHECK currently includes Java and C++, but not Go or C#.
- Go and C# must not become public selectable just because a runner exists; they need separate route/catalog/content work before public course selection is enabled.
- Java is already a public course language, but its course/exercise disclosure must remain static until this task updates runtime profiles, tests, and UI/API disclosure together.
- TypeScript and SQL provide useful implementation patterns: local toolchain detection, temporary workspaces, bounded output, hidden-test redaction, and non-public executable capability.
- P2 `adaptive-exercise-template-system` established that the model may propose learner-facing wording, names, values, data rows, and scenario framing; it must not invent unsupported runtime contracts, bypass required fields, expose solutions, or change hidden-test semantics outside allowed template knobs.
- User confirmed the P3 runtime decision: use `managed_compiled_test` plus expanded public runner result categories.

## Requirements

- Add a managed compiled runtime contract for Java, Go, and C# teaching exercises.
- Use local toolchain detection only; do not install JDK, Go, .NET, packages, PATH entries, SDK workloads, or system settings automatically.
- Run in a temporary workspace, never in the repository or user project directory.
- Support single-file or server-generated harness exercises only:
  - Java: single `Main.java` or metadata-defined public class/function harness.
  - Go: single-package teaching file or server-generated test harness without module/project support.
  - C#: single-file/temporary SDK project or server-generated harness without arbitrary solution support.
- Do not support Maven, Gradle, Go modules, external packages, NuGet packages, `.sln` files, arbitrary project folders, or user-provided build scripts.
- Enforce timeouts, bounded stdout/stderr/error output, hidden-test redaction, and learner-safe temp-path redaction.
- Keep network access disabled by policy. If the host toolchain cannot enforce OS-level isolation, disclose the boundary as local teaching-grade execution, not container-grade sandboxing.
- Stabilize result categories for Java/Go/C#:
  - `missing_toolchain`
  - `unsupported`
  - `compile_error`
  - `runtime_error`
  - `timeout`
  - `test_failure`
  - `success`
- Map runner categories into API, persistence, SSE, and desktop labels without leaking hidden tests, hidden expected values, solution references, raw prompts, provider payloads, API keys, or temp paths.
- Update `language_capabilities`, `runner_registry`, `runtime_runner`, environment doctor, relevant API docs/types, desktop runtime labels, and settings disclosure in the same task.
- Gate Java/Go/C# executable claims until the matching adapter and focused tests pass.
- Keep adaptive exercise generation aligned with P2:
  - model generates candidate Java/Go/C# variants only from canonical compiled-language templates
  - canonical templates own exercise type, runtime tier, scoring contract, harness shape, visible tests, hidden tests, fallback payload, and safety constraints
  - runner validation must compile and run the canonical solution/validator before learner use
  - invalid model output, unsafe content, missing toolchain, unsupported runner, compile failure, runtime failure, timeout, or failed tests must fall back to a stable canonical template
- Keep Rust and C++ out of L3 execution; they may keep documentation grounding/static review disclosure only.
- Preserve existing Python, JavaScript/browser, TypeScript, SQL, review, notes, and adaptive exercise behavior unless a contract change is required and covered by tests.

## Acceptance Criteria

- [ ] Java, Go, and C# have managed compiled runner coverage for success, missing toolchain, compile error, runtime error, timeout, visible test failure, hidden test failure redaction, and unsupported language.
- [ ] Java/Go/C# adaptive variants remain P2-style model-assisted candidates inside canonical template envelopes; no unvalidated model-generated exercise reaches the learner.
- [ ] Rust and C++ still return non-executable disclosure and cannot be accidentally dispatched through the Java/Go/C# managed runner path.
- [ ] Compiled runner adapters run only in temporary workspaces with bounded stdout/stderr/error messages and no project-directory writes.
- [ ] Runner output never exposes hidden test ids, hidden expected values, solution references, raw prompts, provider payloads, API keys, or temp workspace paths.
- [ ] Environment doctor reports Java/Go/C# executable capability only when product and runner contracts are complete; detected toolchains alone do not create public claims.
- [ ] Public course/language capability disclosure stays honest: Java can become executable only with updated Java runtime/course/exercise disclosure; Go/C# remain not public selectable unless schema/catalog/content are explicitly updated and tested.
- [ ] API/runtime docs and frontend labels understand the managed compiled result categories.
- [ ] Settings diagnostics display Java/Go/C# availability using user-facing copy and do not claim Maven/Gradle/Go modules/.NET solution support.
- [ ] Existing focused runner tests for Python, browser, TypeScript, and SQL keep passing.
- [ ] `ruff`, `mypy`, `desktop:check`, task validation, and whitespace checks pass before completion.

## Out of Scope

- Rust and C++ L3 execution.
- General IDE/project execution.
- Maven, Gradle, Go module, NuGet, `.sln`, or arbitrary package installation support.
- Model-generated Java/Go/C# project exercises, package-manager exercises, or arbitrary build scripts.
- Automatic toolchain installation or global PATH/system mutation.
- Cloud execution, Docker-required execution, or remote sandbox service rollout.
- Public Go/C# course selection unless this task explicitly adds the required schema, catalog, content, API examples, and acceptance tests.

## Resolved Planning Decisions

- Use `managed_compiled_test` as the new runtime tier for Java/Go/C#.
- Expand the public runner result categories to distinguish `missing_toolchain`, `compile_error`, and `test_failure` instead of collapsing them into `unsupported` or `runtime_error`.
- Keep the P2 adaptive exercise decision: model-assisted candidate generation is allowed and preferred, but canonical templates and runner validation remain mandatory gates.

## Open Questions

- None blocking planning. Implementation can start after the user approves these reviewed artifacts.

## Notes

- This is a complex child task. Keep it in `planning` until `prd.md`, `design.md`, `implement.md`, and `review.zh.md` are reviewed.
- Do not start or archive the parent `local-product-completion` task for this work.
