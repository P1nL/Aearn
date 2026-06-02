# Local User Data Boundary Implementation Plan

## Policy

- Keep this child in `planning` until the user reviews `prd.md`, `design.md`, `implement.md`, and `review.zh.md`.
- Do not start implementation until approved.
- Inline mode applies: the main session performs implementation and checking directly without implement/check sub-agents.
- Implementation must preserve existing non-destructive onboarding, learning, review, notes, dashboard, resume, settings, runner, and grounding flows.

## Pre-Implementation Checklist

- [ ] Re-read parent `.trellis/tasks/06-02-local-product-completion/prd.md`, `design.md`, and `implement.md`.
- [ ] Re-read `.trellis/spec/backend/index.md`, `database-guidelines.md`, `error-handling.md`, and `quality-guidelines.md`.
- [ ] Re-read `.trellis/spec/frontend/index.md`, `state-management.md`, and `quality-guidelines.md`.
- [ ] Re-read `docs/architecture/api-contract.md`, `docs/architecture/database-schema.md`, `docs/product/frontend-interaction-spec.md`, and `docs/product/user-flows.md` sections for users, settings, notes, learning sessions, reviews, dashboard, and resume.
- [ ] Confirm current git dirty state and exclude unrelated `.codex/config.toml`, `.trellis/tasks/.obsidian/workspace.json`, and `.claude/skills/grill-me/`.

## Implementation Order

1. Backend ownership audit and tests
   - Add focused tests that create two users with separate plans/notes/sessions.
   - Capture current cross-user gaps as failing tests where practical.
   - Cover plan detail, note update, learning session mutation, review session mutation, notes list/create, dashboard, and resume.

2. User data repository
   - Add a repository/service module for local user data summary, export, reset, delete, and user listing.
   - Centralize ownership helper queries so route files do not duplicate ad hoc joins.
   - Add deterministic serializer helpers for learner-safe export.

3. Schema and idempotency support
   - Add additive `idempotency_records.user_id` and invalidation support if needed.
   - Add indexes for data-summary and destructive lookup paths if tests show slow or complex scans.
   - Keep schema repeatable through `bootstrap_database()`.

4. API routes and docs
   - Add local user list, data summary, export, reset, and delete routes.
   - Harden existing user-context routes to require or validate active `user_id`.
   - Update `docs/architecture/api-contract.md` and `docs/architecture/database-schema.md` for new endpoint and schema contracts.

5. Desktop API/types/store
   - Add typed API helpers and type guards for user list, data summary, export, reset, and delete.
   - Extend app store with explicit clear-current-user-data and switch-user flows.
   - Ensure reset/delete clear `localStorage["aearn.bootstrap"]` or only `planId` according to backend result.

6. Desktop Settings UI
   - Extend privacy/records panel with profile identity, summary, export, reset, delete, and switch-user states.
   - Use confirmation UI and stable API error messages.
   - Keep settings copy product-facing and avoid backend-internal labels.

7. Regression and cleanup
   - Run focused backend tests for data boundary.
   - Run focused existing tests for onboarding, learning sessions, reviews, notes, dashboard/resume, and settings.
   - Run lint/type/build checks.
   - Run `task.py validate` and whitespace checks.

## Candidate Files

Backend:

- `aearn/services/api/app/db/schema.sql`
- `aearn/services/api/app/routes/users.py`
- `aearn/services/api/app/routes/plans.py`
- `aearn/services/api/app/routes/notes.py`
- `aearn/services/api/app/routes/learning_sessions.py`
- `aearn/services/api/app/routes/reviews.py`
- `aearn/services/api/app/services/user_repository.py`
- `aearn/services/api/app/services/plan_repository.py`
- `aearn/services/api/app/services/note_repository.py`
- `aearn/services/api/app/services/learning_session_repository.py`
- `aearn/services/api/app/services/review_repository.py`
- `aearn/services/api/app/services/dashboard_repository.py`
- `aearn/services/api/app/services/local_user_data_repository.py`

Frontend:

- `aearn/apps/desktop/src/api.ts`
- `aearn/apps/desktop/src/types.ts`
- `aearn/apps/desktop/src/lib/bootstrapStorage.ts`
- `aearn/apps/desktop/src/stores/useAppStore.ts`
- `aearn/apps/desktop/src/stores/useSettingsStore.ts`
- `aearn/apps/desktop/src/pages/SettingsPage.tsx`

Docs/tests:

- `docs/architecture/api-contract.md`
- `docs/architecture/database-schema.md`
- `docs/product/frontend-interaction-spec.md`
- `docs/product/user-flows.md`
- `aearn/services/api/tests/test_users_m2.py` or a new focused data-boundary test file
- Existing M3/M4/M5/M6 focused test files as regression inputs

## Validation Commands

Focused backend tests, adjusted after implementation:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_users_m2.py tests/test_dashboard_resume_m6.py tests/test_notes_m5.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py tests/test_reviews_m4.py -q
```

Quality gates:

```powershell
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
pnpm --dir .\aearn desktop:check
python .\.trellis\scripts\task.py validate .\.trellis\tasks\06-02-02-local-user-data-boundary
git diff --check
```

Manual/browser smoke when local services are available:

```powershell
pnpm --dir .\aearn dev:status
pnpm --dir .\aearn desktop:dev
```

Smoke cases:

- Cold start with no bootstrap enters onboarding/profile selection.
- Create two local users, create a plan for each, switch between them, and verify route/sidebar/dashboard/notes do not mix.
- Export active user and inspect that hidden tests and internal prompt/provider details are absent.
- Reset active user and verify same user returns to onboarding with no plan/session/note/review data.
- Delete active user and verify bootstrap is cleared and deleted user cannot be fetched.

## Risks and Mitigations

- FK deletion order risk: write repository tests around reset/delete with full user data before implementing desktop UI.
- Hidden data export risk: write redaction tests before shipping export.
- Stale idempotency replay risk: add explicit invalidation tests before destructive UI is exposed.
- Desktop stale state risk: implement store clearing as a named helper and call it before switching, reset, and delete.
- Existing API compatibility risk: update docs and tests together when adding `user_id` requirements to ID-only endpoints.

## Before `task.py start`

- [ ] User reviews and approves the planning artifacts.
- [ ] Any requested semantic changes to reset/delete/export are reflected in `prd.md`, `design.md`, `implement.md`, and `review.zh.md`.
- [ ] No parent task is started.
- [ ] No unrelated local dirty files are included.
