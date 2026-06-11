# Full product QA Design

## Approach

This task is a cross-layer QA pass, not a new feature. The work should preserve the current source-of-truth contracts, exercise the app through realistic local flows, and create a task-local QA report that can support either release confidence or targeted follow-up tasks.

## Source-of-Truth Boundary

Use these documents as the first reference before calling behavior a bug:

- `docs/README.md` for the authoritative document map and post-MVP boundary.
- `docs/product/user-flows.md` for product journeys and user-facing expectations.
- `docs/product/frontend-interaction-spec.md` for desktop interaction and UI boundaries.
- `docs/architecture/api-contract.md` for API request/response contracts.
- `docs/architecture/database-schema.md` for write timing and persistence invariants.
- `docs/architecture/fsrs-scheduling-spec.md` for review scheduling behavior.
- `docs/qa/acceptance-test-plan.md` for QA priority and acceptance vocabulary.
- `docs/setup/development-environment.md` for local startup and dependency assumptions.

## QA Layers

### L0/L1 Deterministic Test Gate

Run backend pytest batches without parallelism. Prefer milestone/contract batches first so failures are easier to localize, then expand if the environment is stable.

Focus areas:

- onboarding and plan confirmation
- learning session graph/messages/exercise run/submit
- review warmup, off-topic, exercise submit, FSRS update timing
- notes API
- dashboard/resume/settings preferences
- language/runtime boundaries
- LLM integration failure handling with mocks

### Desktop Build Gate

Run `pnpm --dir .\aearn desktop:check`. Treat Vite chunk-size warnings as non-blocking unless they are new and tied to a regression.

### Direct Live-Model QA Gate

Direct model-backed paths are part of this QA pass. Use the local app/API behavior and stable response contracts as evidence, not raw provider internals.

Coverage targets:

- onboarding or plan-generation model path when enabled by local configuration
- learning concept intro, answer judgement, and exercise unlock/generation paths
- review warmup judgement, off-topic steering, and model-unavailable behavior
- error handling when the model returns invalid output or is unavailable, using existing safe failure paths

If required provider configuration is absent, record the exact missing capability at a high level in `qa-report.md` without printing secret values.

### Local Runtime Smoke

Use local startup scripts rather than ad hoc service commands unless they fail:

- `pnpm --dir .\aearn dev:test-data` to reset and seed local data when browser smoke needs a known state.
- `pnpm --dir .\aearn dev:status` to confirm API/desktop status.
- API health should be checked at `http://127.0.0.1:8001/health`.
- Desktop browser smoke should target `http://127.0.0.1:1420`.

### Browser Smoke Flow

Exercise the UI as a user:

- cold start/onboarding to plan confirmation
- dashboard/resume state
- learning flow through concept intro, answer judgement, exercise run/submit, and feedback
- review flow through natural warmup, off-topic behavior, exercise card, submit, and completion feedback
- notes drawer/page save state
- settings category navigation and model/config boundary

Record visible behavior, network/API errors, and any data-safety evidence in `qa-report.md`.

## Defect Triage

- P0: breaks onboarding/learning/review/resume core flow, writes incorrect learning/review state, leaks hidden tests/secrets/internal reasoning, or violates Attempt/FSRS persistence timing.
- P1: important UX/API stability problem, misleading user state, broken notes/settings/resume behavior, stale result handling issue, or non-blocking model-unavailable boundary issue.
- P2: visual polish, copy consistency, low-frequency edge case, non-blocking warning, or deferred product refinement.

Contained P0/P1 fixes can be implemented inside this task after `task.py start`. Larger product or architecture changes should be split into follow-up Trellis tasks and referenced from the QA report.

## Data and Safety

- QA runs may reset local dev/test data, but must not touch production data.
- Do not read, print, or commit secrets from `.env` files.
- Direct live-model QA is required for this task, but evidence must stay at the product/API contract level.
- Record only high-level result, stable response shape, safety verdict, and stable error code behavior; never record API keys, raw provider errors, raw prompts, provider reasoning, or hidden test content.

## Deliverables

- Updated planning artifacts: `prd.md`, `design.md`, `implement.md`.
- A user-facing Simplified Chinese planning review: `review.zh.md`.
- A task-local `qa-report.md` created during execution.
- Code/doc fixes only if QA finds contained defects.
- Optional follow-up task list for larger issues.
