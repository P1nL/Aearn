# Technical Design: Review Graph Session State

## Summary

This child introduces the stable state and response envelope that later review-batch children will build on.

The implementation keeps the current persistence model:

- `learning_sessions.review_stage` remains the compact public stage.
- `learning_sessions.review_stage_state_json` becomes the source of truth for `review_batch_v1`.
- `review_seed_banks.seeds_json` remains the baseline candidate pool.
- The active formal exercise is still materialized as an `exercise` row and returned as `review_exercise` for compatibility.

It does not change final review scheduling. The current `submit_review_exercise_result(...)` path can continue to perform immediate FSRS until the later rolling-adaptation/finalization child replaces it.

## State Contract

New sessions store `review_stage_state_json` like:

```json
{
  "schema_version": "review_batch_v1",
  "review_stage": "warmup",
  "knowledge_point_id": "kp_xxx",
  "batch": {
    "status": "active",
    "min_exercise_count": 3,
    "target_exercise_count": 4,
    "max_exercise_count": 6,
    "completed_count": 0,
    "current_exercise_id": "exercise_xxx",
    "current_candidate_id": "candidate_001",
    "can_finalize": false
  },
  "warmup": {
    "question": "...",
    "expected_focus": "...",
    "result": null,
    "recall_level": null,
    "repair_count": 0,
    "last_answer": null,
    "feedback": null,
    "diagnosis": {
      "recall_level": null,
      "confidence": null,
      "evidence": [],
      "missing_points": [],
      "misconception": "",
      "suggested_focus": []
    }
  },
  "session_diagnosis": {
    "recall_level": null,
    "weak_points": [],
    "passed_focus_tags": [],
    "failed_focus_tags": [],
    "skip_count": 0,
    "core_failure_count": 0,
    "last_result": null
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
      "candidate_id": "candidate_001",
      "exercise_id": "exercise_xxx",
      "status": "active",
      "capability": "basic_application",
      "exercise_type": "code_blank",
      "focus_tags": [],
      "is_core": true
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

`variant_practice` remains a compatibility alias for the old single-exercise formal stage. New responses should prefer `exercise`.

## Current Node Contract

Add `current_node` to review start/reuse and warmup responses:

```json
{
  "type": "warmup",
  "stage": "warmup",
  "can_pause": true,
  "warmup": {},
  "position": 0,
  "target_count": 4
}
```

Formal exercise node:

```json
{
  "type": "exercise",
  "stage": "exercise",
  "can_pause": true,
  "exercise": {},
  "position": 1,
  "target_count": 4,
  "completed_count": 0,
  "candidate_id": "candidate_001"
}
```

Compatibility response fields remain:

- `review_exercise`
- `selected_seed_id`
- `seed_bank`
- `warmup`
- `review_stage`
- `review_stage_state`

## Warmup Mapping

Existing warmup evaluator returns older values:

- `correct`
- `incorrect`
- `unclear`
- `skipped`

Map these into batch recall levels:

- `correct` -> `clear`
- `unclear` -> `fuzzy`
- `incorrect` -> `wrong`
- `skipped` -> `skipped`

Stage rules:

- `clear`: set `review_stage=exercise`.
- `fuzzy` / `wrong`: if `repair_count < 1`, set `review_stage=warmup_repair`; otherwise set `review_stage=exercise`.
- `skipped`: increment `skip_count`, set `review_stage=exercise`, and bias `session_diagnosis.weak_points` / failed tags from warmup focus.

Warmup must keep its existing persistence boundary: only `learning_sessions` session-local state changes.

## Data Flow

`POST /api/reviews/start`:

1. Load due review context and active review session if present.
2. Ensure candidate pool via existing `ensure_ready_review_seed_bank(...)`.
3. Select/materialize the first exercise when no valid active exercise exists.
4. Build or upgrade `review_batch_v1` state.
5. Persist `review_stage` and `review_stage_state_json`.
6. Return `current_node` plus compatibility fields.

`POST /api/reviews/{session_id}/warmup-result`:

1. Validate user/session ownership.
2. Load `review_batch_v1` or upgrade legacy state.
3. Normalize warmup result and diagnosis.
4. Persist the next stage and session-local state.
5. Return `current_node` for warmup repair or formal exercise.

## Code Boundaries

Preferred implementation location:

- Keep DB write orchestration in `app/services/repositories/review_repository.py`.
- Add small pure helpers in the same module first unless the file becomes unwieldy; later children can extract `review_batch_state.py` when submit/finalization logic grows.
- Keep `review_graph.py` as a decision graph. It should name batch-aware actions but should not perform persistence.
- Keep route response envelopes in `app/routes/reviews.py`.

## DB Migration

Update both the create-table check and the idempotent `DO $$` constraint refresh in `aearn/services/api/app/db/schema.sql`.

Allowed stages:

- `warmup`
- `warmup_repair`
- `variant_practice`
- `exercise`
- `exercise_feedback`
- `final_summary`
- `submitted`

Keeping `variant_practice` avoids breaking existing rows during transition.

## Compatibility And Rollback

- Old sessions with `warmup` + `variant` should still recover by deriving `batch`, `pool`, `exercise_plan`, and `current_node`.
- If graph-node UI is not implemented yet, the frontend can keep using `review_exercise`.
- Rollback is data-safe because state remains JSONB and attempts/schedules are untouched by this child.
