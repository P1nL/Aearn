# Full product QA Implementation Plan

## Phase 0: Planning Gate

- [ ] Validate task artifacts.
- [ ] Create or update `.trellis/tasks/06-11-full-product-qa/review.zh.md` for user-facing Chinese review.
- [x] Confirm the live-model scope decision from the user: direct live-model QA is required.
- [ ] Do not start execution until planning is approved and `task.py start 06-11-full-product-qa` is run.

## Phase 1: Source-of-Truth Review

- [ ] Read current source docs:
  - `docs/README.md`
  - `docs/product/user-flows.md`
  - `docs/product/frontend-interaction-spec.md`
  - `docs/architecture/api-contract.md`
  - `docs/architecture/database-schema.md`
  - `docs/architecture/fsrs-scheduling-spec.md`
  - `docs/qa/acceptance-test-plan.md`
  - `docs/setup/development-environment.md`
- [ ] Create `.trellis/tasks/06-11-full-product-qa/qa-report.md`.
- [ ] Add a matrix of flows, commands, expected results, actual results, and findings.

## Phase 2: Deterministic Backend Gate

Run pytest sequentially. Initial milestone batches:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_onboarding_m2.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_reviews_m4.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_notes_m5.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_dashboard_resume_m6.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_llm_integration.py -q
```

Expanded contract/runtime batches if the initial gate is stable:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_plan_generation_agent.py tests/test_plan_generator.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_graph.py tests/test_review_graph.py tests/test_graph_runtime_contracts.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_language_capabilities.py tests/test_runner_registry.py tests/test_browser_preview_runner.py tests/test_node_typescript_runner.py tests/test_managed_compiled_runner.py tests/test_sql_query_runner.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_local_user_data_boundary.py tests/test_environment_doctor.py -q
```

Lint/type checks:

```powershell
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run mypy app
```

If `mypy app` is too broad or fails due to pre-existing debt, record the failure and narrow to changed/critical paths rather than hiding it.

## Phase 3: Desktop Gate

```powershell
pnpm --dir .\aearn desktop:check
```

Record warnings separately from failures. Vite chunk-size warnings are expected unless tied to a new regression.

## Phase 4: Local Browser Smoke

Prepare local test data:

```powershell
pnpm --dir .\aearn dev:test-data
pnpm --dir .\aearn dev:status
```

Smoke targets:

- API health: `http://127.0.0.1:8001/health`
- Desktop: `http://127.0.0.1:1420`

Manual/browser checks:

- [ ] cold start and onboarding route card
- [ ] plan confirmation and dashboard
- [ ] learning concept intro and answer judgement
- [ ] generated exercise UI, run/preview/test, submit feedback
- [ ] review warmup natural wording, typed `跳过` / `skip` as ordinary text, off-topic behavior
- [ ] review exercise one-card flow and completion feedback
- [ ] notes drawer save states
- [ ] notes page create/edit/save
- [ ] settings seven categories and no backend scoring/Attempt/FSRS controls
- [ ] API offline/error states if feasible without destabilizing the run

## Phase 5: Direct Live-Model QA

- [ ] Confirm local model provider capability at a high level without printing secrets.
- [ ] Exercise one configured onboarding or plan-generation model path if enabled.
- [ ] Exercise learning concept intro / judgement / exercise unlock with model-backed output.
- [ ] Exercise review warmup judgement and off-topic steering with model-backed output.
- [ ] Verify model unavailable / invalid-output paths return stable user-safe errors and do not expose provider internals.
- [ ] Record product/API-level evidence in `qa-report.md`, not raw prompts, provider reasoning, hidden tests, API keys, or raw provider errors.

## Phase 6: Data-Safety Checks

- [ ] Confirm warmup-only branches do not create `Attempt`.
- [ ] Confirm warmup-only branches do not write `review_logs`.
- [ ] Confirm warmup-only branches do not update long-term `ReviewState`.
- [ ] Confirm final review submit updates FSRS only at the final completion boundary.
- [ ] Confirm frontend does not expose internal `Attempt(run)` / `Attempt(submit)` labels.

Use tests, API responses, or local DB inspection. Record the exact method in `qa-report.md`.

## Phase 7: Fix or Split Findings

- [ ] Fix contained P0/P1 defects in this task.
- [ ] Add or update tests for any fix.
- [ ] For large changes, create follow-up Trellis tasks instead of expanding this QA task indefinitely.
- [ ] Record P2 findings as known issues or future polish.

## Phase 8: Final Verification and Closeout

Required before closeout:

```powershell
git diff --check
python .\.trellis\scripts\task.py validate .\.trellis\tasks\06-11-full-product-qa
```

If code changes are made, re-run affected backend/frontend checks before commit.

Closeout sequence:

- [ ] Commit QA artifacts and any fixes.
- [ ] Archive task with `python .\.trellis\scripts\task.py archive 06-11-full-product-qa`.
- [ ] Record journal with `python .\.trellis\scripts\add_session.py`.
- [ ] Push only after the worktree is clean and commits are scoped to this task.
