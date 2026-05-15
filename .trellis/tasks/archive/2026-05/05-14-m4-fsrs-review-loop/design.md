# M4 FSRS 与复习闭环 Design

## Technical Design

### Boundaries

- Backend remains the only source of truth for `Attempt`, `ReviewState`, `ReviewLog`, `due_at`, `fsrs_rating`, and `forget_risk`.
- Frontend only requests review queue/session/submission and renders backend results.
- Worker due-count tasks are read-only in M4; real `ReviewState` mutation still requires a persisted `Attempt`.

### Backend Data Flow

1. `submit_learning_session_exercise` creates `Attempt(submit)`.
2. Shared `review_scheduler.apply_attempt_review_update(...)` validates the attempt, computes next state, updates `knowledge_points`, updates `review_states`, and inserts or reuses `review_logs`.
3. `GET /api/reviews/today` queries unsuspended `review_states` with `due_at <= now()` and joins `knowledge_points`.
4. `POST /api/reviews/start` verifies due state, creates or reuses `LearningSession(session_type=review)`, selects or creates a variant exercise for the same knowledge point, and returns `variant_reason`.
5. `POST /api/reviews/{session_id}/exercise-result` evaluates the review exercise, inserts `Attempt(review_submit)`, calls the shared scheduler with `source=review_submit`, finishes the review session, and returns the new schedule.

### Scheduler

- Use deterministic fallback scheduling for M4 instead of adding a new FSRS dependency.
- Preserve existing columns `reps` / `lapses` as storage compatibility and serialize them as `review_count` / `lapse_count`.
- `Again`: short relearning interval and lapse increment when previous state was `review` or `relearning`.
- `Hard`: short consolidation interval.
- `Good`: normal interval.
- `Easy`: extended interval.
- `request_id` defaults to `review:update:{knowledge_point_id}:{attempt_id}:{rating}` and is unique through `review_logs.request_id`.
- Existing `review_logs` by `request_id` or `(attempt_id, rating, source)` return the persisted next state without applying a second update.

### Review API Shape

- Add `app/models/reviews.py`.
- Add `app/services/review_scheduler.py` for pure scheduling / serialization.
- Add `app/services/review_repository.py` for due queue, session start, review submit, and worker query helpers.
- Add `app/routes/reviews.py` and include it in `app/main.py`.

### Worker

- Add Celery config `timezone="Asia/Shanghai"` and `enable_utc=True`.
- Add task `review.refresh_due_counts` that returns due counts by user from `review_states`.
- The task must not write `ReviewState` or `ReviewLog`.

### Frontend

- Extend `src/types.ts` with review queue/session/result types.
- Extend `src/api.ts` with `fetchTodayReviews`, `startReviewSession`, and `submitReviewExerciseResult`.
- Refactor `ReviewPage.tsx` to fetch due queue, start selected due item, render the returned exercise, submit a review result, and show backend-returned metrics.
- Reuse existing learning exercise response concepts where practical; avoid local FSRS calculations.

## Compatibility / Rollback

- Existing M2/M3 endpoints must continue to pass tests.
- If the review API has issues, rollback can remove `app/routes/reviews.py` from `main.py` while preserving existing learning submit behavior.
- Schema changes should be additive or compatible with current bootstrap SQL; do not rename existing persisted columns during this milestone.
