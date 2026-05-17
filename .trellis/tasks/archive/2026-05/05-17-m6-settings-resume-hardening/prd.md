# M6 设置、恢复与发布前硬化

## Goal

Implement Milestone 6 so an existing Aearn user can reopen the desktop app into the correct learning context, see review risk without being forced off the main flow unless the risk is truly high, and use a real `SettingsPage` that respects the current backend preference boundary instead of static placeholder content.

## Background / Known Context

- `docs/plans/learning-agent-implementation-plan.md` defines M6 as `GET /api/dashboard`, `GET /api/learning-sessions/resume`, `SettingsPage`, resume entry behavior, final acceptance verification, and doc backfill.
- `docs/product/user-flows.md` and `docs/product/frontend-interaction-spec.md` require the normal app-open path to prefer current learning, show review notice in-app, and only prioritize review when the backend decides the user is both interrupted and high-risk.
- `docs/product/frontend-interaction-spec.md` defines seven settings categories: appearance, model settings, learning preference, review, notification settings, records/privacy, and about/diagnostics.
- `docs/architecture/api-contract.md` already defines `GET /api/users/{user_id}` and `PATCH /api/users/{user_id}/preferences`, plus the contract shapes for `GET /api/dashboard` and `GET /api/learning-sessions/resume`.
- `docs/architecture/database-schema.md` shows that current persisted user preference fields are limited to profile text fields, `preferred_time_slots`, and `reminder_preference`; there is no documented persisted schema for model-selection settings or visual theme settings.
- The current implementation still has major M6 gaps:
  - backend has no `GET /api/dashboard` route;
  - backend has no `GET /api/learning-sessions/resume` route;
  - desktop `SettingsPage.tsx` is static text and exposes only six tabs whose names do not match the spec;
  - `App.tsx` boots from health + course catalog only and defaults to onboarding instead of a persisted resume/dashboard flow;
  - desktop code has no visible persisted `user_id` / `plan_id` bootstrap context for reopen behavior;
  - there are no focused M6 API tests yet.

## Requirements

- Add `GET /api/dashboard` following the documented response shape for active goal, current stage, course, today learning tasks, review count, overall progress, `resume_available`, and `next_entry_point`.
- Add `GET /api/learning-sessions/resume` following the documented minimal resume shape and keep it read-only / safely retryable.
- Keep M6 backend within the current MVP contract and current schema where practical:
  - use existing `users`, `learning_plans`, `plan_modules`, `knowledge_points`, `learning_sessions`, `review_states`, and `runtime_profiles`;
  - do not introduce unrelated auth, account, or multi-device sync work;
  - if `summary_text` / `StageSummary` data is missing, synthesize the smallest deterministic resume summary needed for the API contract rather than blocking M6 on a larger unfinished workflow.
- Persist the minimum desktop bootstrap context needed to reopen the app for an existing user and active plan.
- Refactor desktop initialization so it can:
  - enter onboarding when there is no persisted user or no active plan;
  - load dashboard when persisted user context exists;
  - default to current learning on normal open;
  - show review notice when due reviews exist;
  - enter review first only when the backend returns a high-risk resume decision.
- Implement `SettingsPage` to match the seven documented categories and distinguish between:
  - fields that are truly editable and backed by `GET/PATCH /api/users/{user_id}/preferences`;
  - informational or diagnostic sections that are intentionally read-only under the current backend contract.
- Preserve the hard boundary that settings must not modify scoring rules, Attempt fact logging, FSRS fixed rules, or direct `due_at` writes.
- Add frontend API/types/state for dashboard loading, resume loading, reading user preferences, and saving allowed preference fields.
- Add focused backend and frontend verification for UF-09 / UF-11 and any related dashboard/resume contract coverage.
- Backfill docs only where the implementation necessarily clarifies or narrows an under-specified M6 rule.

## Acceptance Criteria

- [ ] `GET /api/dashboard` returns active goal, current stage, course metadata, today learning tasks, today review count, overall progress, `resume_available`, and a deterministic `next_entry_point` for an existing user with an active plan.
- [ ] `GET /api/dashboard` preserves the normal-open rule: current learning remains the default path unless the backend explicitly classifies the situation as interrupted + high-risk review.
- [ ] `GET /api/learning-sessions/resume` returns a minimal resume payload for an interrupted user, and degrades cleanly when no resumable context exists.
- [ ] Desktop startup can reopen into the correct experience for a previously created local user instead of always starting from a fresh in-memory onboarding state.
- [ ] Desktop home flow shows review notice / resume affordance without forcing review on every due item.
- [ ] Desktop `SettingsPage` exposes all seven documented categories and only persists fields that are allowed by the current `users/preferences` contract.
- [ ] Settings save rejects or omits forbidden backend-rule fields and does not create fake persistence for score / Attempt / FSRS controls.
- [ ] Focused automated checks cover dashboard/resume behavior plus settings preference boundaries, and the desktop build still passes after the M6 refactor.

## Open Question

- Pending review: the exact rule for “中断多日且复习高风险” is not numerically defined in the docs. Recommended implementation is: prioritize review only when the latest learning activity is older than 72 hours and at least one due review currently evaluates to `forget_risk = "high"`.

## Notes

- This is a complex Trellis task. `design.md` and `implement.md` are required before `task.py start`.
