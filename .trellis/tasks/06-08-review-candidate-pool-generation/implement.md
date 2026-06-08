# Implementation Plan: Review Candidate Pool Generation

## Preconditions

- Parent task `.trellis/tasks/06-08-review-graph-adaptive-flow` remains in `planning`.
- Do not run `task.py start` on the parent.
- Before code edits, load `trellis-before-dev` for backend/worker specs and inspect relevant current files.
- Work only on this child until its validation passes.

## Files To Inspect Before Editing

- `.trellis/spec/backend/index.md`
- `.trellis/spec/frontend/index.md` only if API response types become visible to desktop code.
- `docs/architecture/database-schema.md`
- `docs/architecture/langgraph-state-machine.md`
- `aearn/services/worker/aearn_worker/review_seed_bank_core.py`
- `aearn/services/api/app/services/repositories/review_seed_bank.py`
- `aearn/services/api/app/routes/reviews.py`
- `aearn/services/api/tests/test_reviews_m4.py`

## Ordered Checklist

1. Update shared worker contract.
   - Rename or introduce `GENERATOR_VERSION = "review_candidate_pool_v1"`.
   - Add candidate-pool count rules: normal 10-12, high-risk 12-16, hard cap 18.
   - Add allowed capability enum and capability-to-exercise-type validation.
   - Require `focus_tags`, `recommended_for`, `avoid_if`, `metadata.selection_reason`, and `metadata.is_core`.
   - Extend `quality_report` with candidate/capability/core/focus coverage.

2. Update API generation context and prompt.
   - Rename prompt version to `review_candidate_pool_prompt_v1`.
   - Keep runtime profile, supported exercise types, weak points, mastery, latest attempt, last FSRS and risk signals.
   - Add response shape for `candidate_pool.candidates`.
   - Keep temporary parser compatibility for old `seed_bank.seeds` only if needed for test migration.

3. Update normalization and leak checks.
   - Normalize model candidates to include `knowledge_point_id`, `runtime_tier`, `generator_version`, safe IDs and metadata aliases.
   - Reject forbidden material before persistence.
   - Keep failure messages stable and bounded.

4. Update materialization metadata.
   - Store `candidate_id`, `capability`, `focus_tags`, `selection_reason`, `is_core`, and `target_misconception` in `exercises.metadata_json.review_seed`.
   - Keep existing `review_seed` fields used by current tests unless intentionally renamed with test updates.

5. Upgrade compatibility selection.
   - Keep `select_review_seed(...)` callable for current `/api/reviews/start`.
   - Prefer new metadata when choosing a candidate.
   - Do not implement full batch selector or adaptive supplement generation here.

6. Add focused tests.
   - Valid candidate pool persists and returns a compatibility `review_exercise`.
   - Generated exercise metadata includes candidate selection fields.
   - Normal and high-risk count bounds are enforced.
   - Missing capability/metadata, unsupported type, duplicate prompt/code, wrong knowledge point and leakage are rejected.
   - `review_ai_patch` metadata/rubric validation still passes for valid candidates and rejects incomplete candidates.
   - Failed generation still records `review_seed_banks.status='failed'` and does not return `review_exercise`.

7. Update narrow docs if touched by this child.
   - `docs/architecture/database-schema.md`: `review_seed_banks.seeds_json` candidate-pool schema.
   - Optionally add a short compatibility note to `docs/architecture/langgraph-state-machine.md`.
   - Do not rewrite the full batch review user flow in this child.

## Validation Commands

Run the smallest focused backend checks first:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_reviews_m4.py -k "seed_bank or candidate or review_start"
```

Then run broader review smoke if the focused batch passes:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_reviews_m4.py
```

If frontend/API types were changed, also run:

```powershell
pnpm --dir .\aearn desktop:check
```

Always finish with:

```powershell
python .\.trellis\scripts\task.py validate .\.trellis\tasks\06-08-review-candidate-pool-generation
git diff --check
```

## Rollback Points

- If the new schema breaks current review start, temporarily route `GENERATOR_VERSION` back to `review_seed_bank_model_v2` before exposing `review_candidate_pool_v1`.
- If parser compatibility is risky, keep old `seed_bank.seeds` parsing behind tests but make new prompt use only `candidate_pool.candidates`.
- If API response changes ripple into frontend unexpectedly, keep `review_exercise` and `selected_seed_id` compatibility fields unchanged and defer `current_node` work to `review-page-graph-node-ui`.

## Follow-Up Dependencies

- `review-graph-session-state` depends on this child for candidate metadata and provenance in session state.
- `review-rolling-adaptation-and-finalization` depends on this child for candidate capability/core/focus metadata used by batch aggregation.
- `review-page-graph-node-ui` should not depend on model prompt internals; it should consume later backend node contracts only.
- `review-flow-tests-and-docs` will perform full product/API/user-flow doc reconciliation after graph and frontend children land.

## Non-Negotiable Checks

- No hardcoded fallback review questions.
- No hidden answer, hidden test body, raw prompt, provider error, API key or secret persistence.
- No per-question FSRS update in this child.
- No long-term learner profile update in this child.
- No frontend scheduling/scoring calculation.
