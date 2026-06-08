# Review rolling adaptation and finalization

## Goal

Replace the current one-formal-exercise review submit path with a backend-owned exercise loop and batch finalization path.

This child keeps the review page compatible while changing backend semantics:

- Each formal exercise submit records a traceable `Attempt(review_submit)`.
- Intermediate submits update only `LearningSession.review_stage_state_json`.
- The backend chooses the next exercise from the ready candidate pool when coverage is sufficient.
- `ReviewState`, `ReviewLog`, `KnowledgePoint`, FSRS, and long-term learner profile update exactly once, only when the review batch is finalized.

## Parent Dependency

Parent task: `.trellis/tasks/06-08-review-graph-adaptive-flow`

Completed prerequisites:

- `review-candidate-pool-generation` introduced `review_candidate_pool_v1` baseline candidate pools in `review_seed_banks.seeds_json`.
- `review-graph-session-state` introduced `review_batch_v1`, `current_node`, expanded review stages, warmup diagnosis, and resumable active sessions.

Inherited decisions:

- Review flow is graph/batch: warmup -> diagnose -> candidate pool -> exercise loop -> finalization.
- Formal review has minimum 3 exercises, target 3-4 normally, 4-5 for high risk, max 6.
- Per-exercise submit does not update FSRS or long-term learner profile.
- User exit keeps the active review session resumable and does not finalize the batch.
- Final `fsrs_rating` is backend-aggregated, flexible, and not model-decided.
- Core failures or repeated skips restrict high final ratings.
- No hardcoded fallback review questions.
- Frontend does not compute score, FSRS, due date, forget risk, or completion.

## Confirmed Facts

- `submit_review_exercise_result(...)` in `aearn/services/api/app/services/repositories/review_repository.py` currently inserts `Attempt(review_submit)`, calls `apply_attempt_review_update(...)`, calls `merge_stable_profile_signals(...)`, marks the session `finished/submitted`, and returns `ReviewState`, `due_at`, and `forget_risk` after a single formal exercise.
- `apply_attempt_review_update(...)` in `aearn/services/api/app/services/repositories/review_scheduler.py` computes scheduling from one attempt's `fsrs_rating`, updates `review_states`, updates `knowledge_points`, and inserts `review_logs`.
- `review_logs.attempt_id` is `NOT NULL`, so batch finalization should use the last completed formal attempt as the representative attempt for the first implementation.
- `review_batch_v1` state already contains `batch`, `session_diagnosis`, `pool`, `exercise_plan`, and `finalization` sections.
- Candidate provenance is available on materialized exercises under `exercise.metadata_json.review_seed`, including `candidate_id`, `capability`, `focus_tags`, `selection_reason`, and `is_core`.
- Existing route and tests still expect `POST /api/reviews/{session_id}/exercise-result` to return schedule fields after one submit; those expectations must be updated to batch semantics.
- The blocked explanation judgement path currently returns `judgement_ready=false`, `next_action=retry_same`, and writes no attempt. That boundary remains valid.

## Requirements

- Split formal exercise submission from final review scheduling.
- A submit is valid only when the active review session's current node is a formal `exercise` matching the submitted `exercise_id`.
- If explanation judgement is not ready, keep the existing no-attempt retry response and do not advance the batch.
- For a valid formal submit, insert or replay exactly one `Attempt(review_submit)` for the exercise payload and preserve existing `review_ai_patch` scoring behavior.
- Intermediate formal submits must not call `apply_attempt_review_update(...)`, must not insert `review_logs`, must not update `review_states`, must not update `knowledge_points`, and must not call `merge_stable_profile_signals(...)`.
- Intermediate formal submits must update `review_stage_state_json` with:
  - completed plan entry status and attempt facts
  - result, score, per-exercise `fsrs_rating`, and score breakdown
  - capability, focus tag, core/non-core, and evidence quality signals
  - `session_diagnosis` passed/failed focus tags, weak points, skip/core failure counts, and last result
  - batch completed count and whether finalization is now allowed
- The backend must select the next formal exercise from the ready baseline candidate pool when more review is needed and coverage can be satisfied without a new model call.
- Next-exercise selection must avoid already-used candidate IDs, avoid obvious `avoid_if` conflicts, prioritize failed focus tags and missing capability coverage, and avoid excessive repeated exercise types.
- If the baseline pool cannot cover the active weakness or minimum remaining coverage, this child must not synthesize a fallback question. It should keep the session active and return a stable recoverable error such as `REVIEW_ADAPTIVE_SUPPLEMENT_FAILED`.
- Full adaptive supplement model generation is out of scope for this child unless the implementation proves it is small enough to add safely; the state contract must keep `pool.adaptive_supplements` compatible for a later child.
- Finalization is allowed only after the minimum formal exercise count is met and required capability/core coverage is adequate, unless the batch reaches the max exercise count.
- Finalization must compute one backend aggregate `final_fsrs_rating` from the entire batch, not by averaging and not by asking the model.
- Final aggregation must consider warmup recall, formal pass/partial/fail results, capability coverage, difficulty, core failures, skip count, explanation quality, `review_ai_patch` evidence quality, and historical weak points.
- One non-core small miss can still produce `Good` when the rest of the batch is stable.
- Core capability failure prevents `Easy`.
- Multiple skips, repeated core failures, or unresolved high-risk weakness push the final rating to `Hard` or `Again`.
- Finalization must call a scheduler helper that validates the representative attempt and writes exactly one `ReviewState` update and one `ReviewLog`.
- Long-term learner profile merge must run only after finalization and use the representative attempt plus aggregate batch facts.
- A finalized session should return a `final_summary` current node with final rating, schedule result, completed count, weak points, and review state fields.
- An unfinished session must remain `status=active`; next `POST /api/reviews/start` for the same due knowledge point must return the current exercise and completed plan state without updating FSRS.
- Compatibility response fields such as `review_exercise`, per-exercise `fsrs_rating`, `result`, `feedback`, and `code_completion_result` may remain, but `ReviewState`, `due_at`, and `forget_risk` should appear only on final responses.
- Cross-user session access must continue to return `SESSION_NOT_FOUND`.

## Acceptance Criteria

- [ ] First and second formal submits in a normal batch create `Attempt(review_submit)` facts and return the next `current_node`, but do not change `ReviewState.review_count`, `ReviewState.due_at`, `ReviewState.last_attempt_id`, `review_logs`, `KnowledgePoint`, or long-term learner profile.
- [ ] Final submit in a normal batch updates `ReviewState`, `KnowledgePoint`, `review_logs`, and long-term learner profile exactly once.
- [ ] Idempotent replay of an intermediate submit returns the same next node and does not create duplicate attempts, duplicate exercises, or schedule writes.
- [ ] Idempotent replay of the final submit returns the same final summary and does not create a duplicate `ReviewLog`.
- [ ] The exercise plan records completed entries with `attempt_id`, candidate metadata, result, score, per-exercise rating, and status.
- [ ] Next exercise selection uses unused ready-pool candidates and prioritizes missing capability coverage or failed focus tags.
- [ ] If no valid baseline candidate remains, the response is a stable recoverable error and the session remains active; no fallback exercise is shown.
- [ ] Final rating aggregation tests cover: all stable performance can produce `Easy`, a single non-core miss can still produce `Good`, a core failure cannot produce `Easy`, repeated skips/high risk produce `Hard` or `Again`.
- [ ] `review_ai_patch` submissions continue to enforce structured answer scoring and evidence quality, but schedule only at finalization.
- [ ] Blocked explanation judgement still writes no attempt, no session advancement, and no schedule update.
- [ ] A user exiting after intermediate submits can restart the same review and recover current exercise, completed plan entries, and current node without FSRS changes.
- [ ] `POST /api/reviews/{session_id}/exercise-result` returns `current_node` for both intermediate and final responses.
- [ ] Existing warmup no-FSRS tests and candidate pool tests remain passing.
- [ ] Parent task validates after this child planning is added.

## Out Of Scope

- Full frontend `ReviewPage` graph-node rendering refactor.
- Full adaptive supplement model generation and prompt/schema implementation.
- Creating a new global candidate pool table.
- Changing `review_logs.attempt_id` to nullable.
- Changing not-due review protection.
- Implementing code directly in the parent task.

## Notes

- This is a complex child and requires `design.md` and `implement.md` before `task.py start`.
- In Codex inline mode, skip JSONL curation; Phase 2 must load `trellis-before-dev` before code edits.
