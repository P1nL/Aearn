# Implementation Checklist

## Pre-Development

- [ ] Confirm `.trellis/tasks/05-13-m1-project-foundation` is completed or explicitly accepted as the active prerequisite.
- [ ] Read `.trellis/spec/backend/index.md` and all backend guides referenced by this task.
- [ ] Read `.trellis/spec/frontend/index.md` and all frontend guides referenced by this task.
- [ ] Re-check `docs/architecture/api-contract.md` for M2 endpoint shapes.
- [ ] Re-check `docs/architecture/database-schema.md` for required M2 writes.
- [ ] Re-check `docs/product/frontend-interaction-spec.md` for onboarding UI behavior.

## Backend M2 APIs

- [ ] Implement user repository and `POST /api/users`.
- [ ] Implement `GET /api/users/{user_id}`.
- [ ] Implement preference update with forbidden field rejection.
- [ ] Implement seed catalog service and `GET /api/language-courses`.
- [ ] Implement deterministic JS/HTML/CSS/Python course templates and Java/C++ placeholders.
- [ ] Implement `POST /api/plans/generate` with `goal_based` and `material_based` support.
- [ ] Implement `POST /api/plans` transaction with `LearningPlan`, `PlanModule`, `KnowledgePoint`, `ReviewState`, and idempotency.
- [ ] Implement `GET /api/plans/{plan_id}` if desktop needs to reload confirmed plan.

## Backend Tests

- [ ] Add user create/get/preference tests.
- [ ] Add forbidden preference update test for scoring/Attempt/FSRS fields.
- [ ] Add course catalog test.
- [ ] Add plan generation tests for goal mode, material mode, insufficient input, unknown user, unknown course, and Java/C++ capability notice.
- [ ] Add plan confirmation tests for valid draft, invalid draft, unknown user/course, and idempotency replay.

## Frontend

- [ ] Add typed API wrapper and shared frontend types.
- [ ] Extend health-aware shell with onboarding/workspace app state.
- [ ] Implement goal/material mode tabs and basic user profile fields.
- [ ] Load course catalog and render runtime capability boundaries.
- [ ] Implement plan draft generation with loading/error/disabled states.
- [ ] Render plan draft modules and knowledge points with non-skippable core indicators.
- [ ] Implement confirm plan action and workspace summary view.
- [ ] Preserve responsive layout.

## Validation

- [ ] `uv --directory .\aearn\services\api run pytest`
- [ ] `uv --directory .\aearn\services\api run ruff check .`
- [ ] `uv --directory .\aearn\services\api run mypy app`
- [ ] `pnpm --dir .\aearn desktop:check`
- [ ] Browser/manual smoke: open Vite desktop shell, generate a draft, confirm, and see workspace summary.

## Review Gates

- [ ] Confirm M1 remained the foundation source and M2 did not duplicate it.
- [ ] Confirm M2 does not write Attempts or update FSRS scheduling beyond initial ReviewState rows.
- [ ] Confirm frontend never exposes `Attempt(run)` / `Attempt(submit)` user labels.
- [ ] Confirm Java/C++ are visibly unsupported for runtime execution.
- [ ] Confirm no real secrets are introduced.
