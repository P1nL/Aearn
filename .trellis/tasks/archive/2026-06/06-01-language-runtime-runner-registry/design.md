# Language Runtime Runner Registry Design

## Purpose

The registry removes hard-coded runtime branches from learning and review flows. It receives an exercise, submitted code, filled blanks, and run mode, then selects a runner from capability metadata and returns a normalized result.

## Architecture

```text
LanguageCapabilityContract
        |
        v
RunnerCapabilityContract -----> RunnerRegistry
        |                           |
        |                           +--> PythonSandboxRunner
        |                           +--> BrowserPreviewRunner contract
        |                           +--> NodeTypeScriptRunner unsupported contract
        |                           +--> SqlRunner unsupported contract
        |                           +--> CompiledLanguageRunner unsupported contract
        v
Learning/review services consume normalized RuntimeExecutionResult
```

## Registry Boundary

- Input: runtime profile metadata, exercise metadata, submitted code, filled blanks, run mode, and optional request context.
- Output: existing-compatible runtime result with `runtime_status`, stdout/stderr, pass counts, test results, `preview_html`, `next_action`, and product-safe capability messages.
- No persistence, no request idempotency, no SSE event emission, and no graph state writes inside runners.

## Runner Categories

- Python sandbox: executable now, backed by the existing subprocess sandbox path.
- Browser preview: contract now, existing deterministic preview behavior can be adapted, no new browser automation or remote execution required.
- Node/TypeScript: contract and unsupported fallback now, implementation later.
- SQL: contract and unsupported fallback now, implementation later.
- Compiled languages: contract and unsupported fallback now, implementation later for Java, Go, C#, Rust, and C++.

## Compatibility

Existing `runtime_runner.run_exercise()` can remain as an adapter during migration. The implementation should prefer adding a registry entry point first, then gradually delegating existing branches through it. Route-level behavior must remain stable unless the task explicitly updates API docs and frontend types.

## Security

The registry must not hide sandbox limits. Python execution is subprocess-based, not container-grade isolation. Unsupported language runners should fail closed with `runtime_status="unsupported"` and product-facing disclosure.
