# Implementation Plan

## Phase 1: Contracts And Schema

- Update API/docs enums to include `review_ai_patch`.
- Add `review_seed_banks` persistence.
- Add review session stage fields or equivalent persisted review-stage state for `learning_sessions`.
- Add structured review warmup request/response models.
- Add structured `review_ai_patch` answer and scoring models.
- Add error mapping for `REVIEW_SEED_BANK_GENERATION_FAILED`.

Validation focus:

- Schema bootstrap still works on a fresh database.
- Existing review tests keep passing before new behavior is enabled.
- API contracts reject invalid exercise types, invalid warmup payloads, and invalid review patch answers.

## Phase 2: Seed Bank Generator

- Implement a shared seed-bank generator service used by both async generation and synchronous rescue.
- Build safe bounded generator context from taxonomy, knowledge point lesson outline/sources, runtime capability, common misconceptions, and summarized user history.
- Validate full-bank count, type coverage, duplicate seeds, safety, code length, difficulty, and `review_ai_patch` required fields.
- Persist `ready`, `failed`, and retryable status.
- Add worker entrypoint for post-plan or post-knowledge-point seed generation.

Validation focus:

- Normal knowledge point produces 8-12 valid seeds.
- Core/high-risk knowledge point produces 12-16 valid seeds.
- Invalid generator output is rejected and persisted as failed for async path.
- Rescue path returns `REVIEW_SEED_BANK_GENERATION_FAILED` and persists no malformed ready bank.

## Phase 3: Review Start And Warmup

- Extend `POST /api/reviews/start` to ensure a ready seed bank.
- Select a seed based on knowledge point, `ReviewState`, weak points, runtime capability, and recent attempts.
- Materialize or reuse a review exercise from the selected seed.
- Persist `review_stage='warmup'` and warmup state before returning.
- Add warmup result endpoint or extend review message handling with a structured warmup action.
- Enforce skip, correct, incorrect, unclear, and one-repair-limit branches.
- Ensure warmup never updates FSRS.

Validation focus:

- Start replays same active seed and warmup.
- Missing bank triggers rescue generation.
- Warmup skip records state and moves to variant practice.
- Wrong warmup gets only one repair round.
- No warmup branch inserts `Attempt` or `review_log`.

## Phase 4: Variant Submit And `review_ai_patch`

- Add frontend/backend support for `review_ai_patch` exercise rendering and submission.
- Evaluate structured review conclusion using required dimensions.
- Store result in `Attempt.code_completion_result`.
- Map score/evidence to `fsrs_rating` with evidence gates.
- Preserve existing run/submit behavior for code exercise types.
- Keep `ReviewState` updates idempotent by attempt/rating/source.

Validation focus:

- `review_ai_patch` requires verdict, evidence, knowledge point risk, and next action.
- Correct verdict with weak evidence maps to at most `Hard`.
- Major verdict error maps to `Again`.
- Strong review maps to `Good` or `Easy` only when all dimensions justify it.
- Repeated submit does not duplicate `review_count` or `review_logs`.

## Phase 5: Frontend Review Page

- Add warmup card and warmup result rendering.
- Add seed/rescue loading and failure states.
- Add exercise type switching for all core review types.
- Add dedicated `review_ai_patch` input UI.
- Keep metrics panel and note drawer context in sync with the active review session.
- Refresh due queue and review metrics after successful submit.

Validation focus:

- Review page handles empty, loading, ready, error, disabled, retry, and submitted states.
- Refresh/replay keeps same warmup and selected exercise.
- Frontend never computes score, FSRS rating, `due_at`, or `forget_risk`.

## Phase 6: Regression And Documentation

- Update source-of-truth docs only where contracts change.
- Add backend tests for seed generation, rescue generation, warmup branches, type selection, scoring, idempotency, and safety leaks.
- Add frontend checks for warmup UI, review patch UI, replay, loading/error, and metrics refresh.
- Run backend and desktop verification.

## Suggested Validation Commands

```powershell
python .\.trellis\scripts\task.py validate .\.trellis\tasks\05-30-review-page-warmup-seed-bank-variants
uv --directory .\aearn\services\api run pytest tests/test_reviews_m4.py
uv --directory .\aearn\services\api run pytest tests/test_review_seed_bank.py tests/test_review_ai_patch.py
pnpm --dir .\aearn desktop:check
git diff --check
```

Some test filenames above may be new and should be created during implementation.

## Risky Files And Rollback Points

- `aearn/services/api/app/db/schema.sql`: enum and table changes must stay additive and bootstrap-safe.
- `aearn/services/api/app/services/review_repository.py`: review start/submit behavior must preserve existing due-state and idempotency semantics.
- `aearn/services/api/app/services/review_scheduler.py`: do not let warmup update FSRS.
- `aearn/apps/desktop/src/pages/ReviewPage.tsx`: avoid mixing frontend score calculation into UI state.
- `docs/architecture/api-contract.md`, `docs/architecture/database-schema.md`, `docs/architecture/fsrs-scheduling-spec.md`: update only if implementation changes public contracts.

Rollback strategy:

- If seed generation is not ready, keep existing review start path behind a feature flag or compatibility branch.
- If `review_ai_patch` UI is incomplete, keep it disabled in selection while preserving schema/tests for other types.
- Do not roll back `attempts` or `review_logs` data; fix scoring mistakes through new attempts or manual review-state adjustment as required by FSRS docs.
