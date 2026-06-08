# Review graph session state

## Goal

Introduce a backend-owned review batch session state and `current_node` API contract for review start/reuse and warmup progression.

This child moves the review session from the old `warmup + variant` state shape toward `review_batch_v1`, so the frontend can render the backend's current node and the backend can recover unfinished review sessions. It does not implement rolling multi-exercise submission, adaptive supplement generation, or final FSRS aggregation; those are owned by later child tasks.

## Confirmed Facts

- The parent task requires a graph/batch review flow: warmup -> diagnose -> candidate pool -> exercise loop -> finalization.
- Child `review-candidate-pool-generation` is completed and introduced `review_candidate_pool_v1` candidates in `review_seed_banks.seeds_json`.
- Current `POST /api/reviews/start` creates or reuses one active `learning_sessions(session_type=review)` row, selects one seed/candidate, materializes one `review_exercise`, stores `review_stage_state_json`, and returns `review_exercise`.
- Current session state still uses an older shape with `warmup` and `variant`, plus a single `seed_id` / `seed_bank_id`.
- Current `learning_sessions.review_stage` only permits `warmup`, `warmup_repair`, `variant_practice`, and `submitted`.
- Current warmup result writes only `LearningSession.review_stage_state_json` and does not write `Attempt`, `ReviewLog`, `ReviewState`, or long-term learner profile.
- Current formal exercise submit still immediately applies FSRS and finishes the session; changing that is out of scope for this child.

## Requirements

- Define a versioned `review_batch_v1` session state shape stored in `LearningSession.review_stage_state_json`.
- Keep active review sessions resumable by `POST /api/reviews/start` for the same user, plan, and knowledge point.
- Add backend-owned `current_node` to review start/reuse and warmup responses.
- Keep `review_exercise` as a compatibility field for the active formal exercise until the frontend child switches fully to `current_node`.
- Expand the DB review stage constraint to support batch stages: `warmup`, `warmup_repair`, `exercise`, `exercise_feedback`, `final_summary`, and `submitted`.
- Treat existing `variant_practice` state as a compatibility alias that can be upgraded or serialized without breaking existing tests during migration.
- Initialize batch state with:
  - `schema_version=review_batch_v1`
  - `knowledge_point_id`
  - batch min/target/max exercise counts
  - current exercise/candidate ids
  - warmup prompt/result/diagnosis
  - session-local diagnosis
  - pool metadata from `review_seed_banks`
  - an `exercise_plan` entry for the first materialized exercise
  - finalization status set to pending
- Normalize warmup outcomes into recall levels: `clear`, `fuzzy`, `wrong`, and `skipped`.
- Preserve the current rule that warmup never writes `Attempt`, `ReviewLog`, `ReviewState`, or long-term learner profile.
- Ensure `clear` enters formal `exercise` stage, `fuzzy` / `wrong` can use at most one `warmup_repair`, and `skipped` enters lower-difficulty formal review rather than returning to the learning page.
- Keep all response decisions backend-owned; the frontend must not infer score, due dates, FSRS rating, or final completion from local state.
- Keep cross-user session access returning `SESSION_NOT_FOUND`.
- Do not add hardcoded fallback review questions.
- Do not implement final batch FSRS scheduling or long-term profile merge in this child.

## Acceptance Criteria

- [ ] `POST /api/reviews/start` for a new due review returns `review_stage`, `review_stage_state`, `current_node`, `review_exercise`, and the existing compatibility fields.
- [ ] Starting the same due knowledge point again reuses the active unfinished review session and returns the same backend-owned current node.
- [ ] Legacy `variant` state can still be read or upgraded without losing the selected exercise.
- [ ] `review_stage_state_json.schema_version` is `review_batch_v1` for newly initialized review sessions.
- [ ] `current_node.type` can be `warmup`, `warmup_repair`, `exercise`, or later-compatible summary/feedback node types, with enough fields for frontend rendering.
- [ ] Warmup `clear`, `fuzzy`, `wrong`, and `skipped` branches update only session-local state.
- [ ] Warmup branch tests prove no `Attempt`, `ReviewLog`, `ReviewState.review_count`, `ReviewState.due_at`, or long-term learner profile writes occur.
- [ ] DB schema and tests allow the new review stages.
- [ ] Cross-user warmup/session access still returns `SESSION_NOT_FOUND`.
- [ ] Existing review candidate pool tests remain passing.
- [ ] The parent task validates after this child is added.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.

## Out Of Scope

- Splitting formal exercise submission from immediate FSRS update.
- Multi-exercise selection after each formal attempt.
- Adaptive supplement generation.
- Final batch rating aggregation.
- Frontend `ReviewPage` graph-node rendering refactor.
- Archiving or finishing the parent task.
