# Implementation Plan: Review Graph Adaptive Flow

## Parent Task Role

This task is a parent planning and integration task. Do not start implementation on the parent unless the scope is intentionally collapsed. Implementation should happen through independently verifiable child tasks.

Recommended child order:

1. `review-candidate-pool-generation`
2. `review-graph-session-state`
3. `review-rolling-adaptation-and-finalization`
4. `review-page-graph-node-ui`
5. `review-flow-tests-and-docs`

Each child must have its own PRD/design/implement artifacts before `task.py start` when its scope is complex.

## Child 1: Candidate Pool Generation

Scope:

- Extend `review_seed_bank.py` and worker/core validation to support `review_candidate_pool_v1`.
- Add candidate metadata fields: `capability`, `focus_tags`, `recommended_for`, `avoid_if`, `metadata.selection_reason`, `metadata.is_core`.
- Preserve no-fallback behavior on invalid model output.
- Keep baseline pool persisted in `review_seed_banks`.

Validation:

- `uv --directory .\aearn\services\api run python -m pytest tests/test_reviews_m4.py -k "seed_bank or candidate or review_start"`
- Add focused unit tests for candidate schema validation.

Rollback point:

- Generator version can fall back to existing `review_seed_bank_model_v2` if the new schema is rejected before API use.

## Child 2: Review Graph Session State

Scope:

- Extend `review_graph.py` from single-step routing to batch node decisions.
- Extend `learning_sessions.review_stage` constraint and frontend/backend type unions.
- Define `ReviewBatchState` parser/serializer helpers.
- Update `start_review_session(...)` to initialize or recover batch state and return `current_node`.
- Keep `review_exercise` compatibility field during transition.

Validation:

- Start/reuse tests prove active incomplete session is resumed.
- Warmup tests prove no `Attempt`, `ReviewLog`, `ReviewState`, or long-term profile update.
- Cross-user session tests remain passing.

Rollback point:

- Feature flag can route start/reuse back to existing single-exercise state shape.

## Child 3: Rolling Adaptation And Finalization

Scope:

- Split formal exercise submit from FSRS update.
- Persist each formal exercise attempt and update only session-local diagnosis.
- Implement selection from baseline pool and adaptive supplement only on coverage miss.
- Add finalization helper, for example `apply_review_batch_update(...)`, so final `ReviewState` update does not depend on a per-exercise attempt rating.
- Ensure exactly one `ReviewLog` and one `ReviewState.review_count` increment per completed batch.

Validation:

- Submit first and middle exercises without changing `ReviewState.review_count`, `due_at`, `last_attempt_id`, or `ReviewLog`.
- Final exercise updates schedule once.
- Idempotency replay does not create duplicate attempts, logs, or schedule increments.
- Aggregation tests cover flexible rating rules.

Rollback point:

- Keep old `submit_review_exercise_result(...)` path behind feature flag until finalization tests pass.

## Child 4: ReviewPage Graph Node UI

Scope:

- Update `types.ts` and `api.ts` response validation for `current_node`.
- Refactor `ReviewPage.tsx` to render backend node types.
- Reuse learning exercise workbench/card styling for formal exercises.
- Keep warmup as chat/model prompt, not a card.
- Keep loading state blank or centered spinner.
- Preserve review message history replay and note context wiring.

Validation:

- `pnpm --dir .\aearn desktop:check`
- Browser smoke when practical: start review, answer warmup, submit multiple exercises, navigate away/back, verify unfinished session resumes.

Rollback point:

- Compatibility `review_exercise` field allows ReviewPage to temporarily keep the old single-exercise UI.

## Child 5: Tests And Docs

Scope:

- Update source-of-truth docs:
  - `docs/architecture/langgraph-state-machine.md`
  - `docs/product/user-flows.md`
  - `docs/product/frontend-interaction-spec.md`
  - relevant QA release/readiness docs
- Update `tests/test_reviews_m4.py` and add focused tests for new batch behavior.
- Update Trellis spec if implementation teaches a stable new review contract.

Validation:

- `uv --directory .\aearn\services\api run python -m pytest tests/test_reviews_m4.py`
- `uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py tests/test_onboarding_m2.py tests/test_worker_import.py`
- `pnpm --dir .\aearn desktop:check`
- `python .\.trellis\scripts\task.py validate .\.trellis\tasks\06-08-review-graph-adaptive-flow`
- `git diff --check`

## High-Risk Files

- `aearn/services/api/app/agents/graphs/review_graph.py`
- `aearn/services/api/app/routes/reviews.py`
- `aearn/services/api/app/models/reviews.py`
- `aearn/services/api/app/services/repositories/review_repository.py`
- `aearn/services/api/app/services/repositories/review_seed_bank.py`
- `aearn/services/api/app/services/repositories/review_scheduler.py`
- `aearn/services/api/app/db/schema.sql`
- `aearn/services/api/tests/test_reviews_m4.py`
- `aearn/apps/desktop/src/pages/ReviewPage.tsx`
- `aearn/apps/desktop/src/api.ts`
- `aearn/apps/desktop/src/types.ts`
- `docs/architecture/langgraph-state-machine.md`
- `docs/product/user-flows.md`
- `docs/product/frontend-interaction-spec.md`

## Review Gates Before Starting Implementation

- Confirm parent PRD/design/implement with the user.
- Create the first child task and start only that child.
- Load `trellis-before-dev` for the child before code edits.
- Keep the parent open until all child deliverables are integrated and final verification passes.

## Non-Negotiable Checks

- No hardcoded fallback review questions.
- No per-question FSRS update.
- No long-term learner profile update before batch finalization.
- No frontend scheduling/scoring calculation.
- No cross-user session reuse.
- No hidden answer or `solution_reference` leakage in model-generated candidate content.
