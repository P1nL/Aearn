# Full product QA

## Goal

Run a full-product QA pass for the current Aearn local app baseline after the review warmup natural-conversation change. The pass should prove that the core user journeys still work end-to-end, that backend contracts and write timing remain safe, and that any P0/P1 defects are either fixed in this task or captured as explicit follow-up work.

## User Value

- The user gets a concrete release-quality view of whether Aearn's draft/onboarding, learning, review, notes, settings, and recovery flows are currently coherent.
- QA evidence is tied to real commands, real local app behavior, and source-of-truth docs instead of broad verbal confidence.
- Findings are triaged by severity so setup-shell work, product-flow fixes, and larger design changes do not get mixed together.

## Confirmed Facts

- Current Trellis state was clean before task creation: no active tasks and a clean `main` branch.
- `.trellis/workspace/index.md` requires a Simplified Chinese `review.zh.md` in the same task directory when planning artifacts need user review.
- Source-of-truth docs are indexed from `docs/README.md`.
- `docs/qa/acceptance-test-plan.md` defines the existing P0/P1/P2 acceptance vocabulary and core flow list.
- The desktop check command is `pnpm --dir .\aearn desktop:check`.
- The local dev scripts are `pnpm --dir .\aearn dev:test-data`, `dev:status`, `dev:restart`, and `dev:stop`.
- Backend tests are run with `uv --directory .\aearn\services\api run python -m pytest ...`.
- Aearn API pytest batches that share bootstrap DB state must run sequentially, not in parallel.
- Full QA may require browser smoke against `http://127.0.0.1:1420` and API health at `http://127.0.0.1:8001/health`.
- User decision: include direct live-model QA in this pass instead of making it optional.

## Scope

### In Scope

- Reconcile the current product flows against `docs/product/user-flows.md`, `docs/product/frontend-interaction-spec.md`, and `docs/qa/acceptance-test-plan.md`.
- Run deterministic backend/API/agent contract tests that cover onboarding, learning, review, notes, settings/resume, runners, FSRS/write timing, and model-unavailable boundaries.
- Run direct live-model QA for the model-backed learning/review/onboarding paths that are safe to exercise locally, using configured provider settings without exposing secrets.
- Run desktop type/build verification.
- Run local browser smoke for the high-value user journeys:
  - cold start/onboarding/plan confirmation
  - dashboard/resume
  - learning concept intro, answer judgement, generated exercise card, run/submit, feedback
  - review warmup, off-topic/natural-skip text boundary, guided exercise, completion feedback
  - notes drawer and notes page save states
  - settings seven-category shell and API/config boundary
- Verify QA-specific data-safety invariants:
  - warmup must not create `Attempt`, `review_logs`, FSRS evidence, or long-term `ReviewState` updates
  - formal review submit updates FSRS only at the intended completion boundary
  - frontend does not expose internal `Attempt` types or backend-only controls
- Produce a QA report artifact under this task with command results, browser smoke evidence, findings, and final verdict.
- Produce `review.zh.md` as the user-facing Chinese review summary for planning review and update it when the QA scope materially changes.
- Fix contained P0/P1 defects discovered during QA when the root cause is local and low-risk.

### Out of Scope

- Major redesigns of onboarding, learning, review, notes, or settings flows.
- Adding new product capabilities not required to pass current source-of-truth QA.
- Live production deployment or production data changes.
- Rewriting the whole QA plan unless source-of-truth drift is found and a small targeted doc update is needed.
- Printing, logging, committing, or reporting raw `.env` secrets, provider keys, raw prompts, hidden tests, provider reasoning, or raw provider error bodies.

## Requirements

- Use the current repository source of truth before judging behavior as a defect.
- Prefer deterministic tests and local browser evidence over model-quality impressions.
- For direct model QA, verify behavior through stable product/API outcomes and safety boundaries, not raw provider internals.
- Keep DB-sharing pytest batches sequential.
- Reset or seed local test data before browser smoke when needed, and record the reset command used.
- Classify every finding as P0, P1, P2, or follow-up.
- Do not mark the QA pass as complete while any P0 finding remains unresolved.
- P1 findings must be fixed, explicitly accepted as known issues, or split into follow-up Trellis tasks.
- P2 findings can be recorded without blocking completion.
- Keep QA artifacts and any fixes in this task's commit scope only.
- Keep `review.zh.md` aligned with `prd.md`, `design.md`, and `implement.md` whenever planning scope changes.

## Acceptance Criteria

- [ ] `prd.md`, `design.md`, `implement.md`, and `review.zh.md` exist and validate for this task before execution starts.
- [ ] `review.zh.md` summarizes the QA scope, execution order, non-goals, and remaining user decision in Simplified Chinese.
- [ ] Source-of-truth docs consulted during QA are named in the QA report.
- [ ] Backend deterministic tests are run sequentially and results are recorded.
- [ ] Direct live-model QA is run for configured model-backed paths, or the report records a concrete environment blocker such as missing provider configuration.
- [ ] Live-model QA evidence records stable behavior, safety checks, and error codes without exposing secrets, prompts, hidden tests, raw provider errors, or provider reasoning.
- [ ] `pnpm --dir .\aearn desktop:check` passes or any failure is triaged and fixed.
- [ ] Local browser smoke covers onboarding, dashboard/resume, learning, review, notes, and settings, or explicitly records why a flow could not be exercised.
- [ ] Warmup/review data-safety invariants are checked with either automated tests, API/database inspection, or browser/API evidence.
- [ ] A task-local `qa-report.md` records commands, evidence, findings, fixes, residual risks, and a final verdict.
- [ ] All P0 findings are resolved.
- [ ] P1 findings are resolved or converted into explicit follow-up tasks/known issues.
- [ ] `git diff --check` passes before closeout.
- [ ] `python .\.trellis\scripts\task.py validate .\.trellis\tasks\06-11-full-product-qa` passes.

## Decision

This QA pass includes direct live-model provider checks. If the local environment is missing required provider configuration or the provider is unavailable, the QA report must record that as a concrete blocker or finding instead of silently downgrading to mock-only coverage.
