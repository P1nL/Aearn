# Managed Compiled Runners Implementation Plan

## Start Policy

- Keep this task in `planning` until the user reviews `prd.md`, `design.md`, `implement.md`, and `review.zh.md`.
- Do not start or archive the parent `06-02-local-product-completion`.
- Inline mode only: the main session implements and checks directly; do not dispatch implement/check sub-agents.
- Before code edits, re-run `trellis-before-dev` for backend/frontend specs if the session context has drifted.

## Phase 0: Contract Lock

- [x] Confirm the runtime tier name: `managed_compiled_test`.
- [x] Confirm result-category strategy: direct public categories for `missing_toolchain`, `compile_error`, `runtime_error`, `timeout`, `test_failure`, `unsupported`, and `success`.
- [x] Confirm exercise generation contract: follow P2 adaptive exercise rules with model-assisted candidates inside canonical templates, mandatory runner validation, and canonical fallback.
- [x] Decide whether this child enables Java executable course content in the same implementation or only adds runner capability plus honest static disclosure. Decision: Java course content now uses `managed_compiled_test` with a single-file teaching exercise.
- [x] Keep Go/C# non-public unless schema/catalog/course content expansion is explicitly accepted.

## Phase 1: Backend Runner Core

- [x] Add focused failing tests for managed compiled runner selection and Rust/C++ non-execution.
- [x] Add `app/services/managed_compiled_runner.py` or equivalent shared compiled runner service.
- [x] Implement Java harness with local `javac`/`java` detection, compile error mapping, success, test failure, runtime error, timeout, and hidden-test redaction.
- [x] Implement Go harness with local `go` detection, no module/project execution, and the same result matrix.
- [x] Implement C# harness with local `dotnet` detection and no arbitrary solution/package execution. If safe no-package execution is not practical, return `unsupported` and document the blocker before enabling C# claims.
- [x] Add temp-path redaction and bounded output tests.

## Phase 2: Registry, Runtime, and Persistence Contracts

- [x] Add `managed_compiled_test` to `ExecutionMode` and runtime profile schema/checks if direct runtime-profile persistence is used.
- [x] Update `RunnerCapability` for Java/Go/C# managed compiled execution.
- [x] Keep `compiled_sandbox_later` unsupported for Rust/C++ and any static-only compiled rows.
- [x] Update `RuntimeExecutionResult` mapping and DB/API/frontend type contracts for the chosen result-category strategy.
- [x] Ensure `runtime_status != "success"` still prevents passed/easy scoring and safe submit behavior.
- [x] Add route/service tests for learning run response shape when compiled runner succeeds, fails tests, times out, has compile errors, and has missing toolchain.

## Phase 3: Environment Doctor and Disclosure

- [x] Update environment doctor language runner statuses so Java/Go/C# distinguish product support from local toolchain readiness.
- [x] Preserve static/planned disclosure when a toolchain is detected but product support is not enabled.
- [x] Update static guidance copy for JDK, Go, and .NET to avoid automatic install or global PATH mutation.
- [x] Add tests proving detected JDK/Go/.NET alone does not enable Rust/C++ or public Go/C# course selection.

## Phase 4: API, Seeds, and Course Boundary

- [x] Update `docs/architecture/api-contract.md` and `docs/architecture/code-completion-evaluation-spec.md` for the managed compiled runtime tier and result categories.
- [x] Update `app/db/seeds.py` and runtime profile seeds additively where needed.
- [x] If Java executable course content is enabled, update Java runtime profile/course/exercise seeds and API tests together.
- [x] Do not enable public Go/C# selection unless language literals, DB checks, catalog seeds, course templates, onboarding, API docs, and acceptance tests are all updated in the same scope.
- [x] Keep the P2 adaptive template catalog contract unchanged in this child; future Java/Go/C# adaptive templates must remain model-candidate, canonical-envelope, runner-validated, and fallback-gated.

## Phase 5: Desktop Disclosure

- [x] Update frontend `RuntimeStatus`/runtime tier types and label helpers.
- [x] Update learning runtime feedback copy for compile error, missing toolchain, test failure, and timeout.
- [x] Update Settings diagnostics product status labels and guidance copy for Java/Go/C#.
- [x] Ensure run/submit buttons follow backend `supports_tests`, `supports_execution`, and `runtime_status` facts instead of hard-coded Java/C++ assumptions.
- [x] Keep UI copy user-facing; do not expose `Attempt(run)`, raw runner internals, temp paths, or backend enum names as ordinary labels.

## Phase 6: Verification

Run focused backend tests first:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_runner_registry.py tests/test_environment_doctor.py tests/test_language_capabilities.py -q
```

Add the new compiled runner tests to the focused batch, for example:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_managed_compiled_runner.py -q
```

Run quality gates before completion:

```powershell
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
pnpm --dir .\aearn desktop:check
python .\.trellis\scripts\task.py validate .\.trellis\tasks\06-02-managed-compiled-runners-java-go-csharp
git diff --check
```

If DB/API route tests touch `bootstrap_database()`, run them sequentially and do not parallelize M3/M4 batches.

### Verification Status

- [x] Focused backend tests passed for managed compiled runner, runner registry, environment doctor, language capabilities, onboarding, and C++ non-execution boundary.
- [x] Additional changed backend tests passed for LLM integration and teaching chunks.
- [x] `ruff check .` passed.
- [x] `mypy app` passed.
- [x] `pnpm --dir .\aearn desktop:check` passed with the existing Vite chunk-size warning.

## Risky Files

- `aearn/services/api/app/services/language_capabilities.py`
- `aearn/services/api/app/services/runner_registry.py`
- `aearn/services/api/app/services/runtime_runner.py`
- `aearn/services/api/app/services/environment_doctor.py`
- `aearn/services/api/app/db/schema.sql`
- `aearn/services/api/app/db/seeds.py`
- `aearn/services/api/app/models/*.py`
- `aearn/services/api/app/routes/learning_sessions.py`
- `aearn/apps/desktop/src/types.ts`
- `aearn/apps/desktop/src/lib/desktopLabels.ts`
- `aearn/apps/desktop/src/lib/learningHelpers.ts`
- `aearn/apps/desktop/src/pages/SettingsPage.tsx`
- `docs/architecture/api-contract.md`
- `docs/architecture/code-completion-evaluation-spec.md`
- `docs/product/frontend-interaction-spec.md`

## Rollback Points

- Revert Java/Go/C# `LanguageCapability.execution` to `compiled_later`.
- Revert new managed compiled runtime profiles or leave them unreferenced by course seeds.
- Keep `compiled_sandbox_later` unsupported as the fallback disclosure.
- Revert desktop label/type changes only after backend runtime-status contract is reverted.
- Disable C# independently if safe no-package execution is not reliable, while keeping Java/Go behind their own tests.
