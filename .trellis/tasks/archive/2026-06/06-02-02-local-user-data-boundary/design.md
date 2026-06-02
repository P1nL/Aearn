# Local User Data Boundary Design

## Role of This Child Task

This child owns the local data-management boundary for Aearn's desktop product. It turns the existing lightweight `user_id` convention into a concrete local product contract across backend persistence, API ownership checks, desktop bootstrap state, settings visibility, and destructive actions.

It does not introduce public authentication. The target is preventing accidental local profile mixing and making reset/export/delete behavior predictable inside one local install.

## Architecture Boundaries

- Backend routes own public request/response shapes and stable error envelopes.
- Backend services validate ownership and orchestrate reset/export/delete transactions.
- Repositories own SQL, ordering of destructive operations, and serialization.
- Desktop stores own active user selection, bootstrap hydration, switch-user state, and stale state clearing.
- Desktop settings UI owns user-facing visibility and confirmation flows.
- Existing graph, runner, review, FSRS, note assist, and grounding code must not absorb data-management logic.

## Current Ownership Map

Direct `user_id` tables:

- `users`
- `learner_profiles`
- `learning_plans`
- `learning_sessions`
- `attempts`
- `review_states`
- `review_seed_banks`
- `review_logs`
- `notes`
- `onboarding_conversations`

Indirect user-owned tables:

- `plan_modules` through `learning_plans`
- `knowledge_points` through `plan_modules` and `learning_plans`
- `exercises`, `code_blanks`, and `test_cases` through `knowledge_points`
- `learning_messages` through `learning_sessions`
- `review_messages` through `learning_sessions`
- `onboarding_messages` through `onboarding_conversations`
- `teaching_chunks` through `knowledge_points`

Global or shared tables that must not be treated as user data:

- `runtime_profiles`
- `language_courses`
- official/trusted grounding source registries and global grounding chunks
- environment doctor static guidance templates

## API Contract

Proposed backend endpoints:

```text
GET /api/users
GET /api/users/{user_id}/data-summary
GET /api/users/{user_id}/export
POST /api/users/{user_id}/reset-data
DELETE /api/users/{user_id}
```

Existing endpoints that need ownership hardening:

- `GET /api/plans/{plan_id}` should require `user_id` or move to a user-scoped route. Desktop must call it with the active user.
- `PATCH /api/notes/{note_id}` should require active `user_id` and reject notes owned by another user.
- Learning session mutation endpoints should include or derive the active `user_id` and reject session mismatches before running, hinting, explaining, checking, submitting, or writing messages.
- Review session mutation endpoints should include or derive the active `user_id` and reject session mismatches before warmup, exercise submit, or review messages.
- Note agent draft already accepts `user_id`, but update paths and stream paths must keep the same ownership check.

Error mapping:

- Missing user: `USER_NOT_FOUND`.
- Missing plan/session/note after ownership filtering: existing `PLAN_NOT_FOUND`, `SESSION_NOT_FOUND`, `NOTE_NOT_FOUND`, `ATTEMPT_NOT_FOUND`, or `KNOWLEDGE_POINT_NOT_FOUND`.
- Cross-user mismatch may return the same not-found code to avoid making other local profile data visible through error details.
- Invalid destructive confirmation: `VALIDATION_ERROR` with `recoverable=false` only when the confirmation payload itself is malformed.
- Reset/delete transaction failure: `INTERNAL_ERROR` or a task-specific code only if API docs add it.

## Data Summary

Data summary should be cheap and learner-safe. It should return counts and high-level timestamps, not raw content:

- user id, display name, created/updated timestamps
- active plan count and archived/deleted plan count
- knowledge point count
- learning session count
- attempt count
- due review count and total review state count
- note count
- onboarding, learning, and review conversation/message counts
- last activity timestamp based on domain timestamps, not trigger-managed `updated_at` alone

## Export Contract

Export should be deterministic and learner-safe:

- Include `export_version`, `exported_at`, `user`, `preferences`, `plans`, `modules`, `knowledge_points`, `learning_sessions`, `attempt_summaries`, `review_state_summaries`, `review_log_summaries`, `notes`, and conversation summaries.
- Include code submissions only if they are learner-owned attempts and already visible through normal product flows.
- Include public runtime status, stdout/stderr summaries, and public test result summaries already exposed to the learner.
- Exclude hidden test case ids, hidden expected values, hidden failure messages, solution references, raw prompts, provider payloads, raw graph state, API keys, environment variables, and internal runner temp paths.
- Exclude global docs grounding chunks and runtime profile definitions except stable identifiers needed to interpret the export.

## Reset Contract

Reset is for "keep my profile, restart learning".

Recommended backend behavior:

1. Validate the user exists and is not deleted.
2. Build a preview summary before mutating data.
3. In one transaction, clear user-owned learning data and conversation state.
4. Preserve `users` preferences.
5. Reset or remove `learner_profiles` signals because those are derived from learning history.
6. Invalidate idempotency records that could replay reset plan/session/note data.
7. Return a post-reset summary showing zero active plans/sessions/notes/reviews for the user.

Recommended desktop behavior:

1. Offer export before reset.
2. Require a typed confirmation or explicit confirm dialog.
3. On success, clear `localStorage["aearn.bootstrap"].planId` while keeping `userId`.
4. Clear created plan, session, run, submit, review, notes, dashboard, conversations, and note drawer state.
5. Route to onboarding for the same user.

## Delete Contract

Delete is for "remove this local profile".

Recommended backend behavior:

1. Validate the user exists and is not already deleted.
2. Build a preview summary before mutating data.
3. In one transaction, delete or soft-delete all user-owned rows in dependency order.
4. Mark `users.deleted_at` or physically delete the user only after owned rows are no longer visible or blocking FKs.
5. Invalidate idempotency records that could replay deleted data.
6. Ensure normal APIs treat deleted users as not found.

Recommended desktop behavior:

1. Offer export before delete.
2. Require a stronger confirmation than reset.
3. If the deleted user is active, clear `localStorage["aearn.bootstrap"]`.
4. Clear all app stores for the deleted user.
5. Route to local profile selection or onboarding.

## Idempotency Considerations

Existing `idempotency_records` do not have an explicit `user_id`. This task should add a user scoping strategy before reset/delete:

- Prefer adding nullable `user_id` and `expires_at` or `invalidated_at` columns for user-owned operations.
- New user-owned writes should persist the active `user_id` in idempotency records.
- Reset/delete must invalidate matching records so old plan/session/note responses cannot be replayed after destructive actions.
- If backfill is impractical, reset/delete must conservatively invalidate idempotency records whose keys or response payloads reference the user-owned ids being removed.

## Desktop State Flow

Active user bootstrap flow:

```text
read localStorage -> fetch user -> fetch plan/dashboard/resume -> open selected route
```

Switch-user flow:

```text
select user -> clear current stores -> write userId/planId -> fetch selected user's facts -> render selected user's route
```

Reset flow:

```text
confirm reset -> backend reset -> clear plan/session/note/review stores -> write userId with null planId -> onboarding
```

Delete flow:

```text
confirm delete -> backend delete -> clear all bootstrap/store state -> profile selection or onboarding
```

## Compatibility Notes

- Current `localStorage["aearn.bootstrap"]` shape can remain `{ userId, planId }`. The task should add switch/reset/delete semantics around it rather than replacing it prematurely.
- Existing tests that call `GET /api/plans/{plan_id}` may need `user_id` once ownership hardening is added.
- Existing desktop helpers should be extended instead of duplicating request/response validation.
- Settings copy must stay product-facing and must not expose `Attempt`, `ReviewState`, `FSRS`, `due_at`, hidden tests, or internal runner details as editable settings.

## Risks

- Deleting rows in the wrong order can violate `ON DELETE RESTRICT` constraints.
- Soft-deleting only top-level rows can leave stale sessions, attempts, notes, or idempotency replays visible through ID-only endpoints.
- Export can accidentally expose hidden tests or solution references if it dumps exercise/test tables directly.
- Desktop switch/reset/delete can leak previous user state if stores are not cleared before refetch.
- Adding user-scoped checks to existing endpoints can break tests that currently call by id only.

## Rollback Points

- Keep schema changes additive until tests prove reset/delete behavior.
- Gate desktop destructive actions behind backend readiness and confirmation UI.
- If hard delete proves too risky in first implementation, use soft-delete plus strict visibility filters as an intermediate state, but document that physical deletion is deferred.
- Keep old bootstrap shape and API helpers while adding scoped parameters to minimize frontend churn.
