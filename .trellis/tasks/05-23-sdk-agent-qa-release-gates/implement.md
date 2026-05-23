# Implementation Plan

## Status

This task is in `planning`. Do not implement until it is explicitly started with `task.py start`.

## Preconditions

Confirm these tasks are completed or explicitly deferred:

1. `05-23-sdk-teaching-tools-guardrails`
2. `05-23-sdk-exercise-coach-endpoints`
3. `05-23-sdk-note-assist-agent`
4. `05-23-sdk-review-coach-agent`
5. `05-23-sdk-onboarding-plan-agent`

Read:

- `.trellis/spec/backend/index.md`
- `.trellis/spec/backend/quality-guidelines.md`
- `docs/README.md`
- `docs/qa/acceptance-test-plan.md`
- `docs/setup/development-environment.md`

## Phase 1: Test Matrix

1. Inventory every SDK-backed path and its fallback.
2. Add missing fake-runner tests.
3. Add missing leakage/guardrail tests.
4. Add contract regression assertions where SDK wiring could affect JSON/SSE.

## Phase 2: Diagnostics And Docs

1. Add safe provider diagnostics only if current settings/debug surfaces need them.
2. Update backend Trellis specs for stable SDK conventions.
3. Update docs only for actual public behavior changes.

## Phase 3: Full Validation

Run:

```powershell
uv --directory .\aearn\services\api run python -m pytest
uv --directory .\aearn\services\api run python -m mypy app
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api lock --check
pnpm --dir .\aearn desktop:check
```

If `uv run mypy` hits the Windows trampoline issue, use:

```powershell
uv --directory .\aearn\services\api run python -m mypy app
```

## Phase 4: Release Readiness

1. Create or update an appropriate release/readiness note.
2. Include exact commands and results.
3. Call out residual risks:
   - no real provider quality benchmark unless separately run;
   - fake SDK tests prove integration behavior, not model pedagogy quality;
   - application-on-SDK still keeps Aearn-owned state outside SDK sessions.

## Rollback

This task should mostly add tests, docs, and diagnostics. Revert only new hardening changes that fail; do not revert earlier feature tasks unless a specific regression is traced to them.
