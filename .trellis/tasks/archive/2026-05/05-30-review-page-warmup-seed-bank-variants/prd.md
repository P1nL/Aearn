# Review Page Warmup And Seed-Bank Variant Exercises

## Goal

Turn the review page into a short recall plus variant practice flow that produces real FSRS evidence without overloading the learner.

The review page should not become another long teaching chat. Its job is:

```text
due review -> short warmup -> variant exercise -> Attempt(review_submit) -> ReviewState/FSRS update
```

## Background

The current review implementation already has a due queue, `POST /api/reviews/start`, review sessions, review coach text, exercise run/submit, and FSRS update through `Attempt(review_submit)`.

The product gap is that review content still depends too much on the current exercise path and short user history. Per-knowledge-point teaching sessions are intentionally brief, so user history and previously completed exercises are not enough to generate reliable review variety.

The agreed review-page boundary is:

- Short warmup to wake up the concept.
- Variant exercises as the required learner output.
- FSRS evidence comes only from the submitted review exercise.

## Requirements

- Review page scope is independent from the learning-page concept-intro/check flow.
- A review session starts from a due `ReviewState` item and remains bounded to one `KnowledgePoint`.
- The opening warmup is short. It asks the learner to recall or apply the concept, but it must not become a long teaching sequence.
- Warmup can be skipped. Skipping records `warmup_result=skipped`, but does not update FSRS.
- Wrong warmup gets at most one correction round. After that, the flow moves to guided variant practice instead of continuing conceptual teaching.
- Warmup success, failure, unclear answer, and skip are persisted in review session state for replay and diagnostics.
- Only a variant exercise submission creates FSRS evidence. `Attempt(attempt_type=review_submit)` remains the only review-page write that can update `ReviewState`.
- The review page must require learner output. It cannot be completed by only choosing an option.
- Supported core review exercise types are `code_blank`, `fix_bug`, `explain_code`, `implement_function`, and `review_ai_patch`.
- `review_ai_patch` is a core review exercise type, not a post-MVP side feature.
- `review_ai_patch` is bounded to the current knowledge point and active misconception. It is not a general code review workbench.
- `review_ai_patch` must require a short review conclusion from the learner with `verdict`, evidence from diff/test/requirement, current knowledge point risk, and next action.
- `review_ai_patch` scoring must use at least these dimensions: `verdict_correctness`, `evidence_grounding`, `knowledge_point_alignment`, and `actionability`.
- "Tests passed" alone is insufficient evidence for `review_ai_patch`.
- Correct conclusion with weak evidence must not map to `Easy`.
- Scoring and evidence for `review_ai_patch` are written into `Attempt(review_submit).code_completion_result`; do not add a dedicated review-patch result table for the first implementation.
- Review exercise type selection is driven by knowledge point, misconception, review state, runtime capability, and prior attempts. It is not a fixed ratio.
- Review material must not rely primarily on learner history because learning sessions are short.
- The main source of review material is a persisted `review_seed_bank` generated from official taxonomy, knowledge point goal, lesson outline, runtime capability, and common misconceptions.
- User history is only a personalization signal for selecting seed, difficulty, weak point, and guided hints.
- Normal knowledge points require 8-12 seeds.
- Core or high-risk knowledge points require 12-16 seeds.
- Seed bank generation runs asynchronously after plan or knowledge point creation.
- If the seed bank is unavailable when review starts, the review page may synchronously generate the same full seed bank as rescue.
- Normal async generation and synchronous rescue generation must use the same generator, schema, validation, safety checks, and persistence path. The only difference is timing.
- Rescue generation must persist the full seed bank before selecting a seed.
- Async generation failure marks the bank failed and retryable.
- Synchronous rescue failure returns `REVIEW_SEED_BANK_GENERATION_FAILED`; it must not display a low-quality fallback question.
- Seed bank validation rejects missing required type coverage, missing `review_ai_patch`, invalid option counts where options are used, duplicate seeds, missing current knowledge point link, too-long code, hidden tests, reference answers, raw prompt/provider errors/secrets, and difficulty mismatch.
- `review_ai_patch` seeds must include requirement, original code, AI diff, review focus, expected risk, and scoring rubric.
- Frontend must render warmup, variant exercise, `review_ai_patch`, loading, error, retry, and replay states without locally computing scores or FSRS.
- Existing review queue, metrics, note drawer context, and `GET /api/knowledge-points/{id}/review-metrics` behavior must continue working.

## Acceptance Criteria

- [ ] `POST /api/reviews/start` returns a persisted review session with warmup state and a selected persisted review seed.
- [ ] Warmup success, wrong, unclear, and skipped branches replay correctly after refresh.
- [ ] Wrong warmup gets at most one correction round, then moves to guided variant practice.
- [ ] Warmup outcomes never update `ReviewState` or write a `review_log`.
- [ ] Review submit writes `Attempt(attempt_type=review_submit)` and only then updates `ReviewState` and `review_logs`.
- [ ] Seed bank is generated asynchronously after plan or knowledge point creation.
- [ ] Missing seed bank at review start triggers the same full-bank generator synchronously, persists the result, and then selects a seed.
- [ ] Synchronous seed generation failure returns `REVIEW_SEED_BANK_GENERATION_FAILED` with no bad question display.
- [ ] Seed bank validation enforces 8-12 seeds for normal knowledge points and 12-16 seeds for core/high-risk knowledge points.
- [ ] Seed bank validation enforces required type coverage, including at least one valid `review_ai_patch` seed where runtime and knowledge point support it.
- [ ] `review_ai_patch` requires learner output with verdict, evidence, knowledge point risk, and next action.
- [ ] `review_ai_patch` scoring writes all required dimensions and evidence into `Attempt.code_completion_result`.
- [ ] FSRS mapping prevents weak evidence from becoming `Easy` even if the final verdict is correct.
- [ ] Frontend can complete `code_blank`, `fix_bug`, `explain_code`, `implement_function`, and `review_ai_patch` review flows.
- [ ] Frontend shows loading, retry, and error states for async/rescue seed generation and review submit failure.
- [ ] Backend tests cover seed generation success/failure, rescue generation, warmup branches, type selection, review_ai_patch scoring, FSRS update idempotency, and no hidden-answer leaks.
- [ ] Frontend checks cover review page rendering, warmup replay, exercise type switching, review_ai_patch input validation, and metrics refresh after submit.

## Out Of Scope

- General AI code review outside the current `KnowledgePoint`.
- Long-form reteaching on the review page.
- User-editable FSRS parameters or direct `due_at` edits.
- A separate review-patch result table.
- Changing seed counts beyond 8-12 normal and 12-16 core/high-risk.
- Replacing the learning-page concept-intro/check task.

## Open Questions

- None currently blocking planning. The user confirmed the review boundary, seed counts, rescue behavior, `review_ai_patch` as a core type, required learner output, scoring dimensions, and FSRS evidence rule.
