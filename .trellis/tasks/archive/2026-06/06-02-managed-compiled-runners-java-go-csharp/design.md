# Managed Compiled Runners Design

## Role of This Child Task

This child owns the Java, Go, and C# teaching-grade compiled runner rollout. It must keep execution, toolchain detection, API disclosure, and desktop disclosure synchronized before any language is presented as executable.

The task does not own Rust/C++ execution, general project execution, or automatic toolchain installation.

## Current Implementation Boundary

The relevant source of truth is:

- `app/services/language_capabilities.py` for language capability and public selection disclosure.
- `app/services/runner_registry.py` for runner capability selection and public `RuntimeExecutionResult` mapping.
- `app/services/runtime_runner.py` for exercise dispatch.
- `app/services/environment_doctor.py` for local toolchain detection and settings diagnostics.
- `app/db/schema.sql` and `app/db/seeds.py` for runtime profile/catalog availability.
- `aearn/apps/desktop/src/types.ts`, `api.ts`, `lib/desktopLabels.ts`, `lib/learningHelpers.ts`, and `pages/SettingsPage.tsx` for desktop disclosure.
- `docs/architecture/api-contract.md`, `docs/architecture/code-completion-evaluation-spec.md`, and `docs/product/frontend-interaction-spec.md` for cross-layer contracts.

## Recommended Runtime Contract

Add a runtime tier named `managed_compiled_test`.

This tier means:

- Server-generated single-exercise compilation and execution.
- Temporary workspace per run.
- No user project directories.
- No package manager, dependency resolver, or arbitrary build scripts.
- Bounded stdout/stderr/error output.
- Stable, learner-safe status categories.
- Hidden tests are summarized and redacted.
- The host toolchain is detected locally and never installed automatically.

The existing `compiled_sandbox_later` tier remains for Rust/C++ and any static-only compiled language disclosure.

## Exercise Generation Contract

This child inherits the P2 adaptive exercise decision. Java/Go/C# exercises should not be authored by an unconstrained model flow.

The allowed flow is:

1. A canonical compiled-language template defines the knowledge point, exercise type, runtime tier, harness shape, visible tests, hidden tests, scoring contract, fallback payload, and safety constraints.
2. The model may generate a candidate variant inside that template envelope. It may vary learner-facing wording, variable names, values, data rows, and scenario framing.
3. The model must not change the language/runtime contract, create Maven/Gradle/Go module/NuGet/.NET solution exercises, add external dependencies, expose hidden tests, expose solution references, or invent a different validation harness.
4. The matching managed compiled runner validates the candidate before materialization or learner display.
5. Failed generation or validation falls back to the stable canonical template.

The runner work in this task makes Java/Go/C# available as validation targets for the P2 adaptive system. It does not replace the P2 canonical-template and model-candidate architecture.

## Runner Architecture

Add a managed compiled runner service, preferably `app/services/managed_compiled_runner.py`, with shared primitives:

- `ManagedCompiledExecutionResult` with `status`, `stdout`, `stderr`, `error`, `test_results`, and `total_duration_ms`.
- `ManagedCompiledTestCaseResult` matching the public test-result conversion pattern used by Python, TypeScript, browser, and SQL runners.
- Toolchain probe helpers for `javac`/`java`, `go`, and `dotnet`.
- Workspace creation through `tempfile.TemporaryDirectory(prefix="aearn-compiled-")`.
- Output bounding constants aligned with `MAX_RUNNER_STDOUT_CHARS`, `MAX_RUNNER_STDERR_CHARS`, and `MAX_RUNNER_ERROR_CHARS`.
- Temp-path redaction before public error messages are returned.

`runner_registry.py` should own conversion from managed compiled results into `RuntimeExecutionResult`, including public hidden-test redaction and `next_action` mapping.

`runtime_runner.py` should dispatch to the registry for `runner_key="compiled"` and `runtime_tier="managed_compiled_test"`. It should keep `compiled_sandbox_later` unsupported.

## Language Harness Shapes

### Java

- Default source file: `Main.java`.
- Default entry shape: `public class Main` with metadata-defined function or `main` harness.
- Compile command: `javac Main.java`.
- Run command: `java -cp <temp_workspace> Main` or a generated harness class.
- No Maven or Gradle.
- Adaptive variants may alter prompt framing, identifiers, literals, and visible values, but the canonical template must own class/harness expectations and hidden tests.

### Go

- Default source file: `main.go`.
- Generated harness should stay single-package and avoid modules.
- Use `GO111MODULE=off` where practical for no-module teaching exercises.
- Compile/run through `go test` or `go run` against the temporary workspace only.
- No `go get`, external imports, or module downloads.
- Adaptive variants may alter function names only when the canonical template metadata and generated harness are updated together before validation.

### C#

- Default source file: `Program.cs`.
- Use the local `.NET SDK` only.
- Prefer a generated temporary project with no external package references or a direct SDK compiler path if the local SDK supports it reliably.
- No arbitrary `.sln`, NuGet package restore, workload install, or user project execution.
- If the SDK cannot execute a no-package teaching harness without restore/network risk, the adapter must return `unsupported` with a clear safe message rather than silently widening scope.
- Adaptive variants must not add package references or SDK project features outside the canonical template envelope.

## Result Categories

Compiled runner internals and public mapping must distinguish:

- `missing_toolchain`: required command is absent or unusable.
- `unsupported`: language or exercise shape is outside this teaching runner.
- `compile_error`: compiler rejects the learner code.
- `runtime_error`: compiled code starts but raises/exits unexpectedly.
- `timeout`: compile, test, or run exceeds the configured timeout.
- `test_failure`: code executes but visible or hidden tests fail.
- `success`: all required tests pass.

Confirmed public contract: update `RuntimeExecutionResult.runtime_status`, DB CHECKs, API docs/types, SSE payloads, and frontend labels to carry these categories directly.

## Safety and Redaction

Required redactions:

- Hidden case ids become stable public ids such as `hidden_case_2`.
- Hidden expected values are never serialized.
- Hidden failure messages are replaced with generic edge-case guidance.
- Temp workspace paths are removed from `stdout`, `stderr`, and `error_message`.
- Toolchain raw output is bounded before it reaches routes or UI.

Runner environment:

- Inherit only minimal safe environment variables needed on Windows and common local hosts.
- Do not write outside the temp workspace.
- Do not install packages or mutate global configuration.
- Treat this as teaching-grade local execution, not OS-container isolation.

## Capability Disclosure Flow

The cross-layer disclosure flow is:

1. `LanguageCapability` marks Java/Go/C# execution as `managed_compiled_test` only after the adapter and tests exist.
2. `RunnerRegistry.select()` returns a compiled runner that supports execution for Java/Go/C# only.
3. Rust/C++ selection stays `compiled_sandbox_later` or unsupported.
4. Environment doctor combines product capability with toolchain status:
   - product executable + toolchain ready -> current local execution available
   - product executable + toolchain missing/error -> missing toolchain guidance
   - product planned/static -> no executable claim even if the toolchain is installed
5. API course/runtime profiles expose managed compiled execution only where course/content support exists.
6. Desktop labels and settings copy render user-facing availability without backend-internal terms.

## Public Course Boundary

Java is already public selectable. This task may move Java from static-review disclosure to executable Java teaching exercises only after runtime profile, seed/course exercises, tests, and desktop copy are aligned.

Go and C# should remain `enabled_for_public_selection=False` unless this child explicitly expands:

- Pydantic language literals.
- DB CHECK constraints for `language_courses` and `learning_plans`.
- Catalog seeds.
- Course templates/content.
- API examples.
- Onboarding slot extraction and unsupported-language guidance.
- Frontend course selection and acceptance tests.

Runner readiness alone is not enough to make Go or C# public courses.

## Compatibility and Migration Notes

- Additive runtime profiles are safer than mutating old rows in place. Prefer adding `rt_managed_compiled_java`, `rt_managed_compiled_go`, and `rt_managed_compiled_csharp` where persisted runtime profiles are needed.
- Keep `compiled_sandbox_later` rows available for static-only disclosures.
- Runtime status enum expansion touches DB, Python models, frontend TypeScript types, SSE parsing, label helpers, and docs.
- Existing `runtime_status != "success"` hard-gate logic should continue to fail scoring for all new non-success categories.
- Existing P2 adaptive generation and cache behavior should not be forked; extend its canonical template catalog and runner validation target list after Java/Go/C# runner tests are green.
- Existing Python/browser/TypeScript/SQL runner tests should continue passing.

## Rollback Considerations

- Disable Java/Go/C# executable disclosure by reverting `language_capabilities` execution states and runtime profile seeds to planned/static values.
- Keep the managed compiled runner isolated behind `runner_key="compiled"` and `runtime_tier="managed_compiled_test"` so it can be disabled without touching Python/browser/TypeScript/SQL adapters.
- If DB enum expansion causes issues, revert public course/runtime profile seeds before removing code paths.
- If C# no-package execution cannot be made reliable without network/package restore, keep C# as planned and ship Java/Go first only if the user explicitly approves a partial task split.

## Key Trade-Offs

- One shared managed compiled runner reduces duplicate harness code, but each language still needs language-specific command and test harness behavior.
- Direct runtime-status enum expansion improves UI clarity, but increases migration and frontend typing work.
- Keeping Go/C# non-public while executable mirrors TypeScript/SQL and avoids premature course-selection scope.
- Native toolchains keep local setup light, but cannot provide container-grade isolation; the UI and docs must say this honestly.
