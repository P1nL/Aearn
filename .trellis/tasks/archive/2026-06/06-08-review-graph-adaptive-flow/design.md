# Technical Design: Review Graph Adaptive Flow

## Summary

The target flow replaces the current single-exercise review path with a backend-owned review batch graph.

Current behavior:

- `POST /api/reviews/start` creates or reuses one active review session, selects one seed from `review_seed_banks`, materializes one `review_exercise`, and returns `review_stage=warmup`.
- `POST /api/reviews/{session_id}/warmup-result` only updates `LearningSession.review_stage_state_json`.
- `POST /api/reviews/{session_id}/exercise-result` writes one `Attempt(review_submit)`, immediately calls `apply_attempt_review_update(...)`, updates `ReviewState` / `ReviewLog`, and finishes the session.

Target behavior:

- Review is a resumable batch for one due knowledge point.
- Warmup diagnoses recall before formal exercises.
- Baseline candidate pool is model-generated and validated before formal exercise selection.
- Each formal exercise submit writes an attempt and updates session-local diagnosis only.
- Graph selects the next exercise from the candidate pool without calling the model when coverage is sufficient.
- Adaptive supplement generation happens only when the current pool cannot cover the session-local weakness.
- Final `ReviewState` / FSRS update happens exactly once at batch finalization.

## Architecture

```text
ReviewPage
  -> /api/reviews/today
  -> /api/reviews/start
       -> review graph start/reuse decision
       -> load due review state
       -> ensure baseline candidate pool
       -> initialize/recover review batch state
       -> return current review node
  -> /api/reviews/{session_id}/warmup-result
       -> diagnose warmup
       -> update session-local state
       -> select first formal exercise when ready
  -> /api/reviews/{session_id}/exercise-result
       -> run/evaluate submitted exercise
       -> insert Attempt(review_submit)
       -> update session-local diagnosis
       -> choose next exercise or finalize batch
       -> only finalization updates ReviewState / ReviewLog
  -> /api/reviews/{session_id}/messages
       -> persisted review conversation replay and coach messages
```

The graph owns routing and state transitions. Repository/services own database writes, idempotency, validation, and API envelopes. The frontend owns only interaction state and rendering.

## Review State Model

Use `LearningSession.review_stage` as a compact public stage and `LearningSession.review_stage_state_json` as the batch state source of truth.

Recommended stages:

- `warmup`: first recall question.
- `warmup_repair`: one short correction question after fuzzy/wrong warmup.
- `exercise`: a formal exercise is active.
- `exercise_feedback`: last exercise result is recorded and next action is available.
- `final_summary`: batch finalized and schedule updated.
- `submitted`: compatibility alias for a completed review session.

`schema.sql` currently constrains review stages to `warmup | warmup_repair | variant_practice | submitted`. Implementation must migrate the check constraint before returning new stages. A compatibility phase may map `exercise` to existing `variant_practice` while frontend/types are being migrated, but final docs and API should expose the batch stages above.

Session state shape:

```json
{
  "schema_version": "review_batch_v1",
  "review_stage": "exercise",
  "knowledge_point_id": "kp_xxx",
  "batch": {
    "status": "active",
    "min_exercise_count": 3,
    "target_exercise_count": 4,
    "max_exercise_count": 6,
    "completed_count": 1,
    "current_exercise_id": "exercise_xxx",
    "current_candidate_id": "candidate_003",
    "can_finalize": false
  },
  "warmup": {
    "question": "...",
    "result": "fuzzy",
    "repair_count": 1,
    "last_answer": "...",
    "diagnosis": {
      "recall_level": "fuzzy",
      "confidence": 0.62,
      "evidence": ["..."],
      "missing_points": ["state_scope_error"],
      "misconception": "state_scope_error",
      "suggested_focus": ["state", "event_callback"]
    }
  },
  "session_diagnosis": {
    "recall_level": "fuzzy",
    "weak_points": ["state_scope_error"],
    "passed_focus_tags": [],
    "failed_focus_tags": ["state_scope_error"],
    "skip_count": 0,
    "core_failure_count": 0,
    "last_result": "partial"
  },
  "pool": {
    "seed_bank_id": "bank_xxx",
    "generator_version": "review_candidate_pool_v1",
    "candidate_count": 12,
    "adaptive_supplements": []
  },
  "exercise_plan": [
    {
      "position": 1,
      "candidate_id": "candidate_003",
      "exercise_id": "exercise_xxx",
      "status": "completed",
      "attempt_id": "attempt_xxx",
      "capability": "basic_application",
      "exercise_type": "code_blank",
      "result": "partial",
      "score": 5,
      "fsrs_rating": "Hard"
    }
  ],
  "finalization": {
    "status": "pending",
    "representative_attempt_id": null,
    "final_fsrs_rating": null,
    "aggregate_result": null
  }
}
```

All per-question adaptation is session-local. It must not write long-term `learner_profile`, `ReviewState`, `ReviewLog`, or `KnowledgePoint` summary fields until finalization.

## Candidate Pool

The existing `review_seed_banks` table remains the baseline candidate pool persistence layer. Do not create a new global pool table for the first implementation unless a child task proves the existing table cannot carry the contract.

Baseline pool:

- Stored in `review_seed_banks.seeds_json`.
- Generated by the model under a new generator/prompt/schema version.
- Normal target: 10-12 candidates.
- High-risk target: 12-16 candidates.
- Hard cap: 18 candidates unless future validation proves cost and quality are acceptable.

Adaptive supplements:

- Generated only when baseline pool cannot cover current `session_diagnosis`.
- Stored in `LearningSession.review_stage_state_json.pool.adaptive_supplements`.
- Materialized to `exercises` only when selected.
- Scoped to the current session so temporary adaptation does not pollute long-lived baseline pools.

Candidate schema:

```json
{
  "id": "candidate_001",
  "exercise_type": "code_blank",
  "difficulty": 2,
  "capability": "basic_application",
  "target_misconception": "state_scope_error",
  "focus_tags": ["state", "event_callback", "scope"],
  "recommended_for": {
    "recall_levels": ["fuzzy", "wrong", "skipped"],
    "weak_points": ["state_scope_error"],
    "after_result": ["failed", "partial"]
  },
  "avoid_if": {
    "already_passed_focus_tags": ["state_scope_error"],
    "recent_candidate_ids": ["candidate_001"]
  },
  "prompt_markdown": "...",
  "starter_code": "...",
  "code_blanks": [],
  "test_cases": [],
  "metadata": {
    "selection_reason": "Confirm state persistence across event callbacks.",
    "is_core": true
  }
}
```

Required capability coverage:

- `basic_application`: code blank or small implementation.
- `concept_explanation`: explain code or explain behavior.
- `debugging`: fix bug or inspect failing behavior.
- `transfer_or_review`: implement function in a changed context or review an AI patch.

Selection algorithm:

1. Build a required coverage blueprint from due state, weak points, warmup diagnosis, runtime profile, and history.
2. Filter invalid or already-used candidates.
3. Prefer candidates matching current weak points and missing capability coverage.
4. Avoid repeating the same `focus_tags` after a pass unless it is a core failure repair.
5. Avoid too many consecutive exercises of the same `exercise_type`.
6. If no candidate covers the current weakness and remaining minimum count, request adaptive supplement.
7. If supplement generation fails, return a recoverable model/seed-bank error and keep the session active.

The model generates candidates. The backend owns blueprint, count limits, validation, selection, and final schedule decisions.

## Warmup Diagnosis

The model may evaluate warmup answer semantics, but backend must normalize the result.

Diagnosis contract:

```json
{
  "recall_level": "clear",
  "confidence": 0.85,
  "evidence": ["..."],
  "missing_points": [],
  "misconception": "",
  "suggested_focus": ["state_scope_error"]
}
```

Backend normalization:

- Blank, explicit skip, or "完全忘了" -> `skipped`.
- Invalid enum -> `fuzzy`.
- Low confidence -> `fuzzy`.
- Many missing core points -> `wrong`.

Warmup rules:

- `clear`: enter formal review.
- `fuzzy` / `wrong`: one `warmup_repair`, then enter formal review.
- `skipped`: enter lower-difficulty formal review with more basic coverage.
- Warmup never writes `Attempt`, `ReviewLog`, `ReviewState`, or long-term learner profile.

## Exercise Submit And Adaptation

Formal exercise submission still uses runtime/evaluation code paths from learning/review exercises.

Per formal exercise submit:

- Validate active session and active current exercise.
- Run/evaluate the exercise or validate `review_ai_patch_answer`.
- Insert `Attempt(attempt_type=review_submit)` with per-exercise `code_completion_result`.
- Persist idempotency record keyed by session, exercise, attempt/code hash, submit version, and user.
- Update only `review_stage_state_json` with exercise result and session-local diagnosis.
- Return either a next exercise node or a final summary node.

Important scheduler boundary:

- Intermediate `review_submit` attempts must not call `apply_attempt_review_update(...)`.
- Finalization should use a new scheduler helper, for example `apply_review_batch_update(...)`, that validates a representative attempt belongs to the session/knowledge point/user but computes schedule from backend aggregate batch rating.
- `review_logs.attempt_id` can reference the last completed formal attempt as the representative attempt.
- Per-exercise ratings remain diagnostic. The final batch `fsrs_rating` is written to `review_logs.rating` and `ReviewState.last_fsrs_rating` exactly once.

## Final Rating Aggregation

The final rating is backend computed and flexible, not model-decided and not a simple average.

Signals:

- Formal exercise pass/partial/fail results.
- Exercise difficulty and capability.
- Core vs non-core candidate metadata.
- Warmup diagnosis.
- Explanation quality.
- `review_ai_patch` evidence quality.
- Skip count and repair count.
- Historical weak points and prior `ReviewState`.

Expected behavior:

- One non-core small miss can still yield `Good` if the rest of the batch is stable.
- Core capability failure prevents `Easy`.
- Multiple skips, repeated core failures, or high-risk unresolved weakness push toward `Hard` or `Again`.
- `Easy` requires stable results across required capabilities and strong explanation/evidence.

## API Contract

`POST /api/reviews/start`

- Reuse active incomplete review session for the same user, plan, and knowledge point.
- Return the current review node from session state.
- If no active session exists, create a batch session and baseline candidate pool.

`POST /api/reviews/{session_id}/warmup-result`

- Accept `user_id`, `action`, and optional `answer`.
- Return updated current node.
- Does not update FSRS.

`POST /api/reviews/{session_id}/exercise-result`

- Accept current exercise payload.
- Return one of:
  - next exercise node,
  - final summary node with schedule update,
  - validation/model error while session remains active.

Recommended response envelope additions:

```json
{
  "session_id": "session_xxx",
  "review_stage": "exercise",
  "current_node": {
    "type": "exercise",
    "exercise": {},
    "position": 2,
    "target_count": 4,
    "can_pause": true
  },
  "review_stage_state": {},
  "last_result": {},
  "final_result": null
}
```

Compatibility:

- During migration, continue returning `review_exercise` for the active exercise until the frontend fully switches to `current_node`.
- Keep `GET /api/reviews/{session_id}/messages` response shape stable.
- Keep all write requests scoped by active `user_id`.

## Frontend Contract

ReviewPage should render backend nodes:

- `warmup`: chat-style prompt and quick replies, no exercise card.
- `warmup_repair`: chat-style correction prompt.
- `exercise`: learning-page-style exercise workbench for the current exercise.
- `exercise_feedback`: concise feedback and next button if backend requires an explicit continue.
- `final_summary`: schedule, weak points, and next review status.
- `loading`: blank or centered spinner only.

Frontend must not:

- Compute `fsrs_rating`, `due_at`, `forget_risk`, final result, or minimum exercise count.
- Treat local hidden state as completed review state.
- Drop unfinished session state on navigation.

Frontend should:

- Restore review history via existing message API.
- Restore active incomplete session by calling `reviews/start` for the selected due knowledge point.
- Reuse learning exercise card/workbench styling where possible.
- Keep editor/input state local and update server-owned facts from API responses.

## Error Handling

Stable errors:

- `REVIEW_NOT_DUE`: selected knowledge point is not currently due.
- `SESSION_NOT_FOUND`: cross-user or missing session.
- `SESSION_CONFLICT`: request does not match current active review node.
- `REVIEW_SEED_BANK_GENERATION_FAILED`: baseline pool validation/generation failed.
- `REVIEW_ADAPTIVE_SUPPLEMENT_FAILED`: supplement generation failed and no valid candidate can cover the current weakness.
- `VALIDATION_ERROR`: malformed request or candidate/exercise mismatch.
- `IDEMPOTENCY_CONFLICT`: same operation key with different request body.

Errors must preserve stable JSON envelope or SSE error events. A failed adaptive supplement keeps the session active and recoverable.

## Compatibility And Migration

- Update `docs/architecture/langgraph-state-machine.md`, `docs/product/user-flows.md`, and `docs/product/frontend-interaction-spec.md` after implementation design is accepted.
- Keep `review_seed_banks` semantics compatible by versioning generator/schema rather than renaming the table.
- Migrate `learning_sessions.review_stage` check constraint before returning new stages.
- Do not break existing not-due protections or cross-user session checks.
- Existing single-exercise review tests should be updated to assert batch semantics rather than removed.

## Rollback

Feature-level rollback path:

- Keep `LANGGRAPH_ENABLED=false` service fallback until the batch graph is stable.
- Add a backend feature flag if needed, for example `review_batch_enabled`.
- If batch flow fails, route `/api/reviews/start` and `/exercise-result` back to existing single-exercise path while preserving already-created active batch sessions as recoverable or abandoned only by explicit migration.

Data rollback considerations:

- Intermediate attempts are append-only facts; do not delete them.
- Unfinished sessions can remain `status=active`.
- Failed seed/supplement generations should stay as failed rows/state for traceability.
