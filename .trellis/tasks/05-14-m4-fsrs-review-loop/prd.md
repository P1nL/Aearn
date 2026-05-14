# M4 FSRS 与复习闭环

## Goal

Implement Milestone 4 so submitted learning results and review-variant submissions update the same backend-owned FSRS review state, expose a due-review queue, allow the desktop ReviewPage to start and complete review sessions, and verify the P0 FSRS/review acceptance paths.

## Background / Known Context

- The live implementation lives under `aearn/`; historical tutorial directories are not runtime sources.
- `docs/plans/learning-agent-implementation-plan.md` defines M4 as `review_logs` plus due indexes, FSRS scheduler, due review worker task, review APIs, review graph behavior, ReviewPage, and UF-06 / FSRS-01..08 tests.
- Current M3 code already persists `Attempt(run)` and `Attempt(submit)` and updates `review_states` / `review_logs` inside `learning_session_repository._update_learning_records`.
- Current `review_states` schema uses legacy counters `reps` / `lapses` plus M4-compatible `last_fsrs_rating`, `scheduler_version`, and `suspended_at`; M4 must preserve compatibility while moving API responses toward `review_count` / `lapse_count`.
- The desktop already has a `ReviewPage.tsx`, but it is not backed by `/api/reviews/*`.

## Requirements

- Add a reusable review scheduling service for `submit` and `review_submit`.
- Ensure `Attempt(attempt_type=run)` never changes `ReviewState`.
- Ensure each successful `submit` or `review_submit` writes one `ReviewLog` and repeated scheduling with the same key does not increment counters again.
- Implement deterministic fallback scheduling for `Again` / `Hard` / `Good` / `Easy`, including backend-owned `due_at` and `forget_risk`.
- Add `GET /api/reviews/today`, `POST /api/reviews/start`, and `POST /api/reviews/{session_id}/exercise-result`.
- Start review sessions only for due, unsuspended review states; return `REVIEW_NOT_DUE` for early starts.
- Review variants must preserve the latest weak-point / error-cause context and return `variant_reason`.
- Add a Celery task that can compute due review counts without mutating `ReviewState`.
- Update desktop API/types/ReviewPage so due queue, start review, submit review result, empty/loading/error states, and backend-owned `due_at` / `forget_risk` are visible.
- Do not introduce settings that modify FSRS rules, Attempt policy, or direct `due_at`.
- Do not reintroduce `CodeDraftPage`, `publishDrawer`, independent retrospective drafts, or historical tutorial runtime directories.

## Acceptance Criteria

- [x] `GET /api/reviews/today?user_id=...` returns sorted due items and empty state correctly.
- [x] `POST /api/reviews/start` creates or reuses a `LearningSession(session_type=review)` for the same due item and returns a review exercise plus `variant_reason`.
- [x] `POST /api/reviews/{session_id}/exercise-result` writes `Attempt(review_submit)`, updates `ReviewState`, writes exactly one `ReviewLog`, returns `fsrs_rating`, `due_at`, `forget_risk`, and refresh-ready state.
- [x] Replaying the same review scheduling request returns the existing result and does not increment `review_count` / `lapse_count`.
- [x] Learning `submit` still updates review scheduling through the shared service and existing M3 tests pass.
- [x] `review.refresh_due_counts` is importable and returns due counts without modifying review state.
- [x] Desktop `ReviewPage` uses backend review APIs and does not compute or mutate `fsrs_rating`, `due_at`, or `ReviewState` locally.
- [x] Focused backend tests cover UF-06 and FSRS-01..FSRS-06, plus existing M2/M3 tests.
- [x] Frontend typecheck/build passes for the changed desktop code.

## Notes

- This is a complex Trellis task. `design.md` and `implement.md` are required before `task.py start`.
