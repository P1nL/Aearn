# Technical Design: Review Rolling Adaptation and Finalization

## Summary

This child turns `POST /api/reviews/{session_id}/exercise-result` into a batch-aware endpoint.

Current behavior:

- One formal submit writes `Attempt(review_submit)`.
- The same call immediately updates `ReviewState`, `KnowledgePoint`, `ReviewLog`, long-term learner profile, and finishes the session.

Target behavior:

- Every formal submit records an attempt fact.
- Intermediate attempts update only `LearningSession.review_stage_state_json`.
- The backend chooses and materializes the next exercise from `review_seed_banks.seeds_json`.
- The final attempt triggers exactly one aggregate scheduler update.

The frontend can keep using compatibility fields until the later graph-node UI child lands.

## State Additions

Extend the existing `review_batch_v1` shape without changing its top-level schema version.

Completed plan entries should become:

```json
{
  "position": 1,
  "candidate_id": "candidate_001",
  "exercise_id": "exercise_xxx",
  "status": "completed",
  "attempt_id": "attempt_xxx",
  "capability": "basic_application",
  "exercise_type": "code_blank",
  "focus_tags": ["state_scope_error"],
  "is_core": true,
  "result": "partial",
  "score": 6,
  "fsrs_rating": "Hard",
  "score_breakdown": {},
  "evidence_quality": "weak",
  "completed_at": "2026-06-08T10:00:00Z"
}
```

Active next-entry shape remains compatible with the previous child:

```json
{
  "position": 2,
  "candidate_id": "candidate_004",
  "exercise_id": "exercise_yyy",
  "status": "active",
  "capability": "concept_explanation",
  "exercise_type": "explain_code",
  "focus_tags": ["state_scope_error"],
  "is_core": false,
  "selection_reason": "Repair weak state-scope explanation."
}
```

`batch` additions:

```json
{
  "completed_count": 2,
  "current_exercise_id": "exercise_yyy",
  "current_candidate_id": "candidate_004",
  "can_finalize": false,
  "coverage": {
    "required_capabilities": ["basic_application", "concept_explanation", "debugging"],
    "covered_capabilities": ["basic_application", "concept_explanation"],
    "failed_core_capabilities": [],
    "unresolved_focus_tags": ["state_scope_error"]
  }
}
```

`finalization` additions:

```json
{
  "status": "pending",
  "representative_attempt_id": null,
  "final_fsrs_rating": null,
  "aggregate_result": null,
  "applied_review_log_id": null
}
```

## Submit Flow

`submit_review_exercise_result(...)` should become a batch orchestration function:

1. Build the existing idempotency key from session, exercise, attempt/code hash, and submit version.
2. Return stored idempotency response on exact replay.
3. Load and lock the review session, state, current exercise, and due review context.
4. Validate `state.review_stage == "exercise"` and `state.batch.current_exercise_id == exercise_id`.
5. Preserve the blocked explanation judgement branch: return retry response, store idempotency response, write no attempt, and do not advance state.
6. Build `code_completion_result` using existing scoring paths, including `review_ai_patch`.
7. Insert `Attempt(review_submit)` with per-exercise `fsrs_rating`.
8. Update the current plan entry to `completed` with attempt facts.
9. Update `session_diagnosis` and batch coverage.
10. If finalization is not allowed, select/materialize the next exercise, persist `review_stage_state_json`, and return an `exercise` current node.
11. If finalization is allowed, aggregate final rating, call the batch scheduler helper, merge long-term learner profile, mark session finalized, persist state, and return a `final_summary` node.
12. Store the full response in `idempotency_records`.

Important boundary: steps 8-10 do not write `ReviewState`, `ReviewLog`, `KnowledgePoint`, or long-term learner profile.

## Next Exercise Selection

Add a pure selector helper in `review_repository.py` first. Extract later only if the file becomes unwieldy.

Inputs:

- `review_batch_v1` state
- ready `review_seed_banks.seeds_json`
- current `session_diagnosis`
- runtime profile
- due review context

Filtering:

- Reject already-used candidate IDs from `exercise_plan`.
- Reject unsupported exercise types.
- Reject `avoid_if.recent_candidate_ids` matches.
- Reject candidates whose `avoid_if.already_passed_focus_tags` are fully passed unless a core failure requires repair.

Scoring:

- Prefer candidates matching `failed_focus_tags`, unresolved weak points, or warmup suggested focus.
- Prefer missing required capability coverage before repeating a covered capability.
- Prefer core candidates when a core capability is unresolved.
- Prefer lower difficulty after skipped/wrong warmup or repeated failed results.
- Penalize repeated exercise type from the immediately previous entry.

Materialization:

- Use existing `materialize_review_seed_exercise(...)`.
- Append a new active `exercise_plan` entry.
- Update `batch.current_exercise_id`, `batch.current_candidate_id`, and `review_stage="exercise"`.
- Return `current_node.type="exercise"` with compatibility `review_exercise`.

Coverage miss:

- If no candidate can satisfy remaining minimum or unresolved weakness, do not synthesize a question.
- Set session state to indicate supplement is needed, for example `pool.adaptive_supplement_status="needed"`.
- Return stable `REVIEW_ADAPTIVE_SUPPLEMENT_FAILED` and keep `LearningSession.status='active'`.

## Finalization Rules

Finalization may happen when:

- `completed_count >= min_exercise_count`
- Required capability coverage is satisfied or enough evidence shows no further useful baseline candidate is needed
- No unresolved core failure requires another available baseline candidate

Finalization must happen when:

- `completed_count >= max_exercise_count`

Normal target behavior:

- Clear/stable sessions usually finish after 3 exercises.
- Fuzzy/wrong/skipped/high-risk sessions may continue to 4 or 5.
- The hard maximum is 6.

## Final Rating Aggregation

Add a backend pure helper such as `_aggregate_review_batch_rating(state, review_state)`.

Signals:

- Warmup recall: `clear`, `fuzzy`, `wrong`, `skipped`.
- Formal result counts: passed/easy, partial, failed.
- Per-exercise `fsrs_rating`.
- Completed required capabilities.
- Candidate `is_core`.
- Core failure count.
- Skip count and guided repair count.
- Explanation check score.
- `review_ai_patch` evidence quality.
- Historical weak points and current `ReviewState.last_fsrs_rating`.

Required behavior:

- `Easy`: requires stable pass/easy results across required capabilities, no core failures, low skip count, and strong explanations/evidence.
- `Good`: allows one small non-core partial/fail when required capabilities are otherwise stable.
- `Hard`: used for partial recovery, unresolved weakness, multiple partials, or one core failure with enough completed work to avoid `Again`.
- `Again`: used for repeated fails, repeated skips, no required capability recovery, or severe core failure.

The helper should also produce an aggregate payload:

```json
{
  "result": "partial_recovery",
  "final_fsrs_rating": "Hard",
  "completed_count": 4,
  "pass_count": 2,
  "partial_count": 1,
  "fail_count": 1,
  "core_failure_count": 1,
  "unresolved_focus_tags": ["state_scope_error"],
  "rating_reason": "Core weakness still appears in debugging exercise."
}
```

## Scheduler Helper

Add a helper in `review_scheduler.py`, for example:

```python
def apply_review_batch_update(
    conn,
    *,
    knowledge_point_id: str,
    representative_attempt_id: str,
    final_rating: str,
    aggregate_result: Mapping[str, object],
    source: str,
    request_id: str | None,
) -> dict[str, object]:
    ...
```

Behavior:

- Load and validate the representative attempt belongs to the user, session, knowledge point, and has `attempt_type='review_submit'`.
- Use `final_rating` for scheduling instead of the representative attempt's per-exercise rating.
- Preserve existing idempotency semantics through `review_logs.request_id`.
- Update `review_states` once.
- Update `knowledge_points` from `aggregate_result`, not from only the representative attempt.
- Insert one `review_logs` row with the representative attempt ID.
- Return serialized `KnowledgePoint`, `ReviewState`, `due_at`, and `forget_risk`.

Implementation can refactor shared internals from `apply_attempt_review_update(...)`, but learning submit behavior must remain unchanged.

## Response Contract

Intermediate response:

```json
{
  "attempt_id": "attempt_001",
  "result": "partial",
  "fsrs_rating": "Hard",
  "code_completion_result": {},
  "review_stage": "exercise",
  "current_node": {
    "type": "exercise",
    "exercise": {},
    "position": 2,
    "target_count": 4,
    "completed_count": 1,
    "can_pause": true
  },
  "review_stage_state": {},
  "next_action": "next_exercise",
  "final_result": null
}
```

Final response:

```json
{
  "attempt_id": "attempt_003",
  "result": "passed",
  "fsrs_rating": "Good",
  "final_result": {
    "final_fsrs_rating": "Good",
    "aggregate_result": {},
    "due_at": "2026-06-10T00:00:00Z",
    "forget_risk": "low"
  },
  "ReviewState": {},
  "KnowledgePoint": {},
  "review_stage": "final_summary",
  "current_node": {
    "type": "final_summary",
    "completed_count": 3,
    "final_fsrs_rating": "Good",
    "due_at": "2026-06-10T00:00:00Z"
  },
  "next_action": "schedule_review"
}
```

Compatibility:

- Keep per-exercise `fsrs_rating` in intermediate responses because tests and current UI may inspect it as exercise feedback.
- Do not include `ReviewState`, `due_at`, or `forget_risk` in intermediate responses.
- Keep `review_exercise` for the active next exercise until frontend fully consumes `current_node.exercise`.

## Idempotency

The existing `idempotency_records` approach can remain:

- Intermediate response replay must not materialize another next exercise.
- Final response replay must not write a second `ReviewLog`.
- Blocked judgement replay must still return the no-attempt retry response.
- Same idempotency key with a different request body must keep returning `IDEMPOTENCY_CONFLICT`.

## Session Recovery

Unfinished sessions remain `LearningSession.status='active'`.

`POST /api/reviews/start` should continue to reuse the active session and return:

- current node
- current exercise
- completed exercise plan entries
- session-local diagnosis
- no schedule changes

Finalized sessions should be `status='finished'` with `review_stage='final_summary'`. `submitted` remains an accepted compatibility alias but new code should return `final_summary`.

## Error Handling

Stable errors:

- `SESSION_NOT_FOUND`: missing or cross-user session.
- `SESSION_CONFLICT`: submitted exercise does not match active current node.
- `REVIEW_ADAPTIVE_SUPPLEMENT_FAILED`: ready pool cannot cover the remaining need and no supplement implementation is available.
- `VALIDATION_ERROR`: malformed request.
- `IDEMPOTENCY_CONFLICT`: same operation key with different request body.

Errors must keep the session recoverable unless finalization has already succeeded.

## Docs Boundary

This child should update narrow backend/API docs that are directly made false by implementation:

- `docs/architecture/api-contract.md`: exercise-result intermediate vs final response.
- `docs/architecture/langgraph-state-machine.md`: review exercise loop and finalization write timing.
- `docs/architecture/database-schema.md`: review log representative attempt and batch state notes if needed.

Full product/front-end wording remains for later `review-page-graph-node-ui` and `review-flow-tests-and-docs`.
