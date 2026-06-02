# Local user data boundary

## Goal

Give Aearn a clear local-only user data boundary so one Windows desktop install can safely hold multiple local learner profiles without mixing routes, learning sessions, attempts, reviews, notes, settings, or local resume context.

This task plans the product and technical contract for local user isolation, data visibility, export, reset, delete, and desktop switching. Implementation must not start until the planning artifacts are reviewed.

## User Value

- A learner can see which local user profile is active and what data belongs to that profile.
- A learner can export their own learner-safe local data before destructive actions.
- A learner can reset learning data while keeping their local profile and settings.
- A learner can delete a local user profile and its owned data without leaving stale bootstrap state that reopens deleted plans or sessions.
- The desktop app does not accidentally show another local profile's route, session, review queue, note, or settings data after switching users.

## Confirmed Facts

- Aearn is local-only for this parent task. Deployment, SaaS multi-tenancy, public auth, payments, and production backup flows are out of scope.
- `docs/architecture/api-contract.md` says V1 uses local single-user or lightweight user mechanics and requires user-context APIs to pass `user_id` explicitly.
- `aearn/services/api/app/db/schema.sql` already stores `users.deleted_at`; most learner-owned tables already have `user_id`, plan ownership, or an ownership path through `learning_plans`.
- Current user APIs support create, read, and preferences update only: `POST /api/users`, `GET /api/users/{user_id}`, and `PATCH /api/users/{user_id}/preferences`.
- Current desktop bootstrap stores `{ userId, planId }` in `localStorage["aearn.bootstrap"]`.
- Current desktop settings has a privacy/records panel, but it only displays diagnostics such as local user id, active plan id, review count, and resume availability.
- Current implementation has no user list/switch API, no user data summary API, no export API, no reset API, and no delete API.
- Some existing endpoints are plan-id or note-id scoped without an explicit current `user_id` check. Planning must cover ownership hardening before exposing data-management UI.

## Product Semantics

- Local user boundary is product isolation for the desktop app and local API. It is not a public authentication or hostile-local-attacker security model.
- The active user is the selected local profile in desktop state plus `localStorage["aearn.bootstrap"].userId`.
- User switching changes the active desktop context and refetches user, plan, dashboard, resume, notes, and review data from backend facts. It must not reuse stale in-memory plan/session/note state from the previous user.
- Export produces learner-safe JSON for the active user. It may include user profile, preferences, plans, modules, knowledge points, sessions, attempts summaries, review state/log summaries, notes, onboarding/review/learning message summaries, and local product metadata. It must not include hidden test bodies, hidden expected values, solution references, raw prompts, provider payloads, API keys, or internal runner secrets.
- Reset keeps the `users` row and preference/settings fields, then removes or deactivates learning data owned by that user: plans, modules, knowledge points, generated exercises, sessions, attempts, review states/logs/seed banks, notes, learner profile signals, and conversation history. After reset, desktop clears `planId` and returns the same user to onboarding.
- Delete is a stronger destructive action. It deletes or marks deleted the user profile and all owned data, clears desktop bootstrap if the deleted user was active, and returns the app to local user selection or onboarding.
- Both reset and delete require a backend preview summary plus a desktop confirmation step. Export should be offered before delete.

## Requirements

- Add a backend-local user data management contract for list, summary, export, reset, and delete.
- Keep every user-context API explicitly scoped to `user_id`, or validate that the session/note/plan belongs to the provided active user before reading or mutating data.
- Add ownership checks for plan detail, note update, note agent draft, learning-session mutation, review-session mutation, and data-summary/export/reset/delete operations.
- Add a local profile list/switch flow so the desktop app can choose among non-deleted local users without creating duplicate bootstrap state.
- Add a data summary payload with counts and timestamps for user, plans, sessions, attempts, reviews, notes, and conversations.
- Add a learner-safe export payload and tests proving hidden tests, solution references, raw prompts, provider payloads, and secrets are omitted.
- Add reset behavior that preserves the user profile/preferences while clearing user-owned learning data and invalidating stale local bootstrap `planId`.
- Add delete behavior that removes or soft-deletes the user profile and all user-owned data without leaving readable rows through normal product APIs.
- Prevent stale idempotency records from replaying deleted or reset data after reset/delete.
- Update desktop Settings privacy/records panel to show current profile, local data summary, export, reset, delete, and switch-user affordances with visible loading/error/confirm states.
- Update API contract, database schema doc, and frontend interaction spec before or alongside implementation if public endpoint shapes change.
- Preserve existing onboarding, learning, review, notes, dashboard, resume, settings, runner, and grounding behavior for non-destructive flows.

## Dependency Contracts

- Depends on parent `.trellis/tasks/06-02-local-product-completion` for local-only product scope, Phase 2 order, and explicit exclusion of cloud/SaaS auth.
- Depends on completed `01-local-stable-startup` for reliable local API/database startup before destructive data-management checks.
- Depends on completed `03-desktop-learning-experience-completion` because reset/delete must clear route/session/review/note/settings UI state consistently.
- Depends on existing M2-M6 backend flow contracts for users, plans, learning sessions, attempts, reviews, notes, dashboard, and resume.
- Does not depend on `sql-query-runner` or `07-adaptive-exercise-template-system`, but new reset/delete/export code must be extensible enough for future runner attempts and adaptive variant tables.

## Acceptance Criteria

- [ ] `GET /api/users` or an equivalent local profile list returns only non-deleted local users and enough summary data for desktop switching.
- [ ] `GET /api/users/{user_id}/data-summary` or equivalent returns counts for active/deleted plans, sessions, attempts, review states/logs/seed banks, notes, and conversations owned by that user.
- [ ] User-scoped read/mutation endpoints reject cross-user plan, note, session, attempt, review, and bootstrap mismatches with stable learner-safe errors.
- [ ] `GET /api/users/{user_id}/export` or equivalent returns a deterministic learner-safe JSON payload and excludes hidden test details, solution references, raw prompts, provider payloads, and secrets.
- [ ] Reset preserves the user profile and preferences, clears user-owned learning data, invalidates stale idempotency records, clears desktop `planId`, and returns the current user to onboarding.
- [ ] Delete removes or soft-deletes the user and user-owned data, invalidates stale idempotency records, clears desktop bootstrap if needed, and prevents normal APIs from reading the deleted user's data.
- [ ] Desktop user switching clears previous user in-memory state before loading the selected user's profile/dashboard/resume data.
- [ ] Desktop Settings privacy/records UI exposes profile identity, summary, export, reset, delete, and switch-user states with confirm/error/loading feedback.
- [ ] Existing settings still cannot modify score rules, Attempt persistence rules, FSRS scheduling rules, `due_at`, or runner internals.
- [ ] Backend tests cover same-user success, cross-user rejection, export redaction, reset effects, delete effects, stale idempotency replay prevention, and user list behavior.
- [ ] Desktop type/build checks cover new API types and state transitions.
- [ ] Focused M2/M3/M4/M5/M6 regression tests continue passing for normal non-destructive flows.

## Out of Scope

- Public authentication, login sessions, tokens, RBAC, password management, OAuth, and cloud multi-tenancy.
- Production backup/restore, encrypted vault storage, and off-machine sync.
- Automatic migration of deleted data into external archives.
- Admin-level access to other local users' hidden tests, prompts, provider payloads, or raw internal runner material.
- Changes to scoring, FSRS, runner result semantics, grounding indexing, or adaptive exercise generation unless needed to keep reset/delete/export ownership correct.

## Open Questions

- No blocking product question for planning. Recommended semantics are: reset keeps the profile/preferences and clears learning data; delete removes the profile and all owned data; export is learner-safe and redacted.

## Notes

- Keep this task in planning until `prd.md`, `design.md`, `implement.md`, and `review.zh.md` are reviewed.
- Do not start this child until the user approves the planning artifacts or explicitly asks to implement.
- In inline mode, implementation and checking should happen in the main session without implement/check sub-agents.
