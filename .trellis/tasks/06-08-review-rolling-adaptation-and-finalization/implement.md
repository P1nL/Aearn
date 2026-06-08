# Implementation Plan: Review Rolling Adaptation and Finalization

## Preconditions

- Parent task `.trellis/tasks/06-08-review-graph-adaptive-flow` stays in `planning`.
- Work on this child only after artifact review and `task.py start` for this child.
- Before code edits, load `trellis-before-dev`.
- Do not dispatch sub-agents in Codex inline mode.
- Do not implement the frontend graph-node UI refactor in this child.

## Files To Inspect Before Editing

- `.trellis/spec/backend/index.md`
- `.trellis/spec/frontend/index.md` only if desktop API types are touched
- `aearn/services/api/app/services/repositories/review_repository.py`
- `aearn/services/api/app/services/repositories/review_scheduler.py`
- `aearn/services/api/app/services/repositories/review_seed_bank.py`
- `aearn/services/api/app/routes/reviews.py`
- `aearn/services/api/app/models/reviews.py`
- `aearn/services/api/app/agents/graphs/review_graph.py`
- `aearn/services/api/tests/test_reviews_m4.py`
- `docs/architecture/api-contract.md`
- `docs/architecture/langgraph-state-machine.md`
- `docs/architecture/database-schema.md`

## Ordered Checklist

1. Load Trellis implementation context.
   - Run `python .\.trellis\scripts\get_context.py`.
   - Load `trellis-before-dev`.
   - Read this child `prd.md`, `design.md`, and `implement.md`.

2. Add scheduler support for batch finalization.
   - Add `apply_review_batch_update(...)` in `review_scheduler.py`.
   - Reuse/refactor common validation and state update code from `apply_attempt_review_update(...)`.
   - Use the backend aggregate final rating, not the representative attempt's per-exercise rating.
   - Keep existing learning submit scheduling behavior unchanged.
   - Preserve review log idempotency through `request_id` and representative attempt.

3. Add batch state helpers in `review_repository.py`.
   - Complete/update current plan entry from a submitted attempt.
   - Update `session_diagnosis` from exercise result and candidate metadata.
   - Compute coverage and `batch.can_finalize`.
   - Select next baseline candidate from `review_seed_banks.seeds_json`.
   - Materialize next exercise and append an active plan entry.
   - Build `final_summary` current node.
   - Aggregate final rating and aggregate result.

4. Split submit behavior.
   - Keep existing request validation, blocked judgement path, scoring, and attempt insertion.
   - Add active-node/session conflict validation before writing attempts.
   - For intermediate submits, persist only `learning_sessions.review_stage_state_json` and return next exercise node.
   - For final submit, call `apply_review_batch_update(...)`, then call `merge_stable_profile_signals(...)`, mark session `finished`, and return final summary.

5. Implement recoverable coverage-miss behavior.
   - If no valid baseline candidate remains when another exercise is required, persist session state indicating supplement need.
   - Return `REVIEW_ADAPTIVE_SUPPLEMENT_FAILED` through the route without finalizing.
   - Do not generate or show fallback exercises.

6. Update route/graph wiring.
   - Make `/api/reviews/{session_id}/exercise-result` pass through intermediate/final response envelopes.
   - Map `SESSION_CONFLICT` and `REVIEW_ADAPTIVE_SUPPLEMENT_FAILED` to stable JSON errors.
   - Update graph action naming if tests require batch-aware intent names, keeping persistence in repository code.
   - Keep review message persistence idempotent with response keys that work for intermediate and final responses.

7. Update API/frontend compatibility types only as needed.
   - If desktop TypeScript types require new fields, add optional `current_node`, `final_result`, and broader `review_stage` union.
   - Do not refactor `ReviewPage.tsx` rendering in this child.

8. Update backend tests.
   - Update existing single-submit schedule tests to run through at least 3 formal submits.
   - Add assertions that intermediate submits do not change `ReviewState`, `ReviewLog`, `KnowledgePoint`, or learner profile.
   - Add finalization exactly-once assertions.
   - Add intermediate and final idempotency replay tests.
   - Add next candidate selection test using unused pool metadata.
   - Add coverage-miss error test.
   - Add final rating aggregation unit tests for `Easy`, `Good` with non-core miss, core failure not `Easy`, and repeated skip/high risk.
   - Preserve `review_ai_patch` evidence scoring and blocked explanation no-attempt tests.
   - Preserve cross-user `SESSION_NOT_FOUND` tests.

9. Update narrow docs.
   - API contract: intermediate vs final exercise-result responses.
   - LangGraph state machine: exercise loop and finalization write timing.
   - Database schema: batch finalization uses representative review attempt in `review_logs.attempt_id`.

10. Run validation and fix issues until green.

## Validation Commands

Focused backend tests first:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_reviews_m4.py -k "review_run_and_submit or review_ai_patch or blocked_explanation or final_rating or idempotency or current_node" -q
```

Full review backend batch:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_reviews_m4.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_worker_import.py -q
```

Lint and type checks:

```powershell
uv --directory .\aearn\services\api run ruff check app\agents\graphs\review_graph.py app\routes\reviews.py app\services\repositories\review_repository.py app\services\repositories\review_scheduler.py tests\test_reviews_m4.py
```

Run mypy from `aearn/services/api`:

```powershell
.\.venv\Scripts\python.exe -m mypy app
```

Desktop compatibility if TypeScript files change:

```powershell
pnpm --dir .\aearn desktop:check
```

Trellis validation:

```powershell
python .\.trellis\scripts\task.py validate .\.trellis\tasks\06-08-review-rolling-adaptation-and-finalization
python .\.trellis\scripts\task.py validate .\.trellis\tasks\06-08-review-graph-adaptive-flow
git diff --check
```

## Risky Files

- `aearn/services/api/app/services/repositories/review_repository.py`
- `aearn/services/api/app/services/repositories/review_scheduler.py`
- `aearn/services/api/app/routes/reviews.py`
- `aearn/services/api/tests/test_reviews_m4.py`
- `docs/architecture/api-contract.md`
- `docs/architecture/langgraph-state-machine.md`

## Rollback Points

- Keep `apply_attempt_review_update(...)` behavior intact for learning submits and old callers.
- Keep `review_exercise` response compatibility for active exercise nodes.
- Keep `variant_practice` accepted as a compatibility stage.
- If batch selector becomes unstable, finalization can require the existing first materialized exercise plus two additional ready-pool candidates without changing persistence schema.
- If coverage miss is encountered, return `REVIEW_ADAPTIVE_SUPPLEMENT_FAILED` and preserve active session instead of falling back.

## Non-Negotiable Checks

- No per-question FSRS update.
- No long-term learner profile merge before finalization.
- No hardcoded fallback review questions.
- No model-decided final FSRS rating.
- No frontend-owned schedule, score, due date, forget risk, or completion decisions.
- No nullable `review_logs.attempt_id` migration in this child.
