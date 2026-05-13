# Technical Design

## Scope Boundary

This task implements Milestone 2 only after `.trellis/tasks/05-13-m1-project-foundation` is complete. It extends the M1 runtime foundation and must not implement M3 runner/session/Attempt behavior.

The implementation target is `aearn/` only:

- Backend: `aearn/services/api/`
- Desktop: `aearn/apps/desktop/`

Historical tutorial directories remain untouched.

## Backend Shape

Extend the M1 FastAPI app with M2 route and service modules:

```text
aearn/services/api/
  app/
    models/
      onboarding.py
    routes/
      users.py
      courses.py
      plans.py
    services/
      catalog.py
      plan_generator.py
      plan_repository.py
      user_repository.py
```

Use the M1 database connection/bootstrap pattern and add only M2-specific repository/service code where needed.

## API Contracts

Implement these endpoints:

- `POST /api/users`
- `GET /api/users/{user_id}`
- `PATCH /api/users/{user_id}/preferences`
- `GET /api/language-courses`
- `POST /api/plans/generate`
- `POST /api/plans`
- `GET /api/plans/{plan_id}` if needed by the desktop confirmation flow

All non-2xx responses use the M1 error envelope and stable error codes from `docs/architecture/api-contract.md`.

## Data Model

Reuse these M1 tables:

- `users`
- `runtime_profiles`
- `language_courses`
- `learning_plans`
- `plan_modules`
- `knowledge_points`
- `review_states`

Add `idempotency_records` in M2 only if M1 did not already create it and confirmed-plan idempotency needs persistence.

For M2, `review_states` only receives initial card state rows. No FSRS scheduling algorithm runs yet.

## Seed Catalog

Use M1 seeded runtime profiles and courses:

- `rt_browser_js` + JavaScript DOM beginner
- `rt_browser_html_css` + HTML/CSS interaction beginner
- `rt_python_stdout` + Python basic beginner
- `rt_compiled_later_java` + Java basic placeholder
- `rt_compiled_later_cpp` + C++ basic placeholder

JS/HTML/CSS/Python can generate runnable-ready learning plans. Java/C++ return course options and capability notices but do not promise runnable behavior.

## Plan Draft Generation

Plan generation is deterministic:

1. Validate user exists.
2. Validate mode and minimum input:
   - `goal_based`: non-empty `goal_text`
   - `material_based`: at least one material with content
3. Resolve course by `course_id` or language/default beginner course.
4. Build `plan_draft` from course template and user input.
5. Include source attribution:
   - user goal/material source
   - template-generated module source
   - runtime capability notice
6. Validate every module has at least one knowledge point.
7. For JS/HTML/CSS/Python, require at least one supported MVP runtime tier.

`POST /api/plans/generate` must not write formal plan rows.

## Confirm Plan

`POST /api/plans`:

1. Validate user and course.
2. Validate `plan_draft` structure and non-skippable core modules.
3. Check idempotency key from `Idempotency-Key` header or `user_id + plan_draft.draft_id`.
4. Insert `learning_plans`, `plan_modules`, `knowledge_points`.
5. Set `current_module_id` to the first module.
6. Initialize one `review_states` row per knowledge point.
7. Store idempotency result if idempotency storage exists.
8. Return plan/modules/knowledge points and `next_entry_point`.

Use a single database transaction for the confirm path.

## Frontend Shape

Extend the M1 health-aware desktop shell with a lightweight app state machine:

- `booting`: API health check
- `onboarding`: user profile + plan generation form
- `workspace`: created plan summary and route panel
- `error/offline`: visible banner and retry

No router dependency is required for this milestone.

Suggested source layout:

```text
aearn/apps/desktop/src/
  App.tsx
  api.ts
  types.ts
  styles.css
```

## Frontend Behavior

- Default user can be created lazily from display name or first onboarding submit.
- Generate button is disabled until goal/material input is sufficient.
- Draft preview shows modules, knowledge points, course/runtime tier, and source notes.
- Core modules (`is_skippable=false`) must be visibly non-skippable.
- Java/C++ show `compiled_sandbox_later` notice.
- Confirmation calls backend and then shows created plan/module/knowledge point summary.
- UI labels must not expose backend-internal Attempt types.

## Rollback

- Backend rollback: remove M2 routes/services and drop only M2-added idempotency storage if created.
- Frontend rollback: restore M1 health shell.
- Data rollback: delete local test plans/users if no user data matters; preserve M1 seed catalog.

## Risks

- `target_level` has a doc mismatch: API examples use `beginner_to_intermediate`, while database schema lists `beginner` / `intermediate` / `advanced`. Implementation should normalize to supported DB values and return clear validation errors for unsupported values.
- Without M3, "enter current learning" can only mean a basic workspace entry, not a runnable learning session.
