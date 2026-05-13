# Implement Milestone 2 Onboarding And Learning Plan

## Goal

Implement Aearn Milestone 2 after `.trellis/tasks/05-13-m1-project-foundation` is complete so a local user can create a profile, choose a language course, generate a deterministic `plan_draft`, confirm it into a persisted learning plan, and see the desktop onboarding flow move into a basic learning workspace entry.

## Background / Known Context

- Formal runtime lives under `aearn/`; historical `01_` through `07_` directories are reference only.
- This task depends on the M1 FastAPI app, health integration, database bootstrap, seed catalog, worker skeleton, and smoke-test foundation.
- Milestone 2 in `docs/plans/learning-agent-implementation-plan.md` requires `POST /api/users`, `PATCH /api/users/{user_id}/preferences`, fixed course templates, `POST /api/plans/generate`, `POST /api/plans`, onboarding UI, and UF-01 / UF-02 tests.
- M2 must not recreate M1 foundation. If M1 is incomplete, return to `.trellis/tasks/05-13-m1-project-foundation` first.

## Requirements

- Reuse the M1 FastAPI service, DB bootstrap path, and seed catalog.
- Implement user profile creation and preference update APIs matching `docs/architecture/api-contract.md`.
- Reject attempts to update backend-fixed scoring, Attempt persistence, or FSRS rule fields through preferences.
- Implement deterministic fixed course templates for JS/HTML/CSS and Python beginner paths; Java/C++ must show `compiled_sandbox_later` capability boundaries instead of runnable claims.
- Implement `POST /api/plans/generate` that returns a valid `plan_draft` without creating a formal `LearningPlan`.
- Implement `POST /api/plans` that validates a confirmed `plan_draft`, persists `LearningPlan`, `PlanModule`, `KnowledgePoint`, and initializes `ReviewState` for each knowledge point.
- Implement idempotency for confirmed plan creation using `user_id + plan_draft.draft_id`.
- Implement an onboarding UI in the desktop app with goal/material mode, language/course selection, plan draft preview, unsupported runtime notice, loading/error/disabled states, and confirmation.
- After confirmation, the desktop UI must show a basic learning workspace entry with created plan/modules/knowledge points; full M3 learning session and generated exercise card are out of scope.
- Add automated tests for API success/failure paths and frontend build/typecheck coverage.

## Acceptance Criteria

- [ ] M1 task is complete and its validation commands pass.
- [ ] `POST /api/users` creates a local user profile and returns a stable `user_id`.
- [ ] `PATCH /api/users/{user_id}/preferences` updates allowed profile fields and rejects scoring/Attempt/FSRS fixed-rule fields.
- [ ] `GET /api/language-courses` returns the M1 seeded course/runtime catalog, including visible `compiled_sandbox_later` entries for Java/C++.
- [ ] `POST /api/plans/generate` supports `goal_based` and `material_based`, rejects insufficient input, and returns `plan_draft` with modules and knowledge points.
- [ ] Generated `plan_draft` includes runtime capability metadata and at least one MVP-runnable `browser_preview` or `python_stdout_test` path for JS/HTML/CSS/Python.
- [ ] `POST /api/plans` persists a formal plan from a valid draft and initializes `ReviewState` rows without creating Attempts.
- [ ] Repeating `POST /api/plans` with the same idempotency key returns the existing plan instead of duplicating rows.
- [ ] Invalid `plan_draft`, unknown user, and unknown course return the documented error envelope and stable error codes.
- [ ] Desktop onboarding prevents empty generation, shows loading/error states, previews modules, blocks non-skippable core modules, shows Java/C++ capability boundary, and transitions to a basic workspace view after confirmation.
- [ ] UF-01 P0 is covered by automated or documented smoke flow: input goal -> generate plan draft -> confirm -> plan created -> workspace route panel visible.
- [ ] UF-02 P1 is covered enough to distinguish user-provided material from generated/agent-added plan content.

## Definition Of Done

- [ ] M1 task is completed first.
- [ ] Backend lint/type/test commands pass from `aearn/services/api` after M2 changes.
- [ ] Frontend build/typecheck passes from `aearn/` after M2 changes.
- [ ] API contract tests cover success, validation error, not found, forbidden preference fields, invalid draft, and idempotent plan confirmation.
- [ ] No real secrets are added to `.env.example`, tests, seed data, or logs.
- [ ] Documentation is updated only if implementation intentionally deviates from existing contracts.

## Out Of Scope

- M1 API health, database bootstrap, seed catalog, worker skeleton, and desktop health integration.
- M3 learning sessions, run/preview runner, generated code exercise card, `Attempt(run)`, `Attempt(submit)`, and score evaluation.
- Full LangGraph LLM orchestration. M2 uses deterministic plan generation shaped like the onboarding graph contract.
- Full FSRS algorithm. M2 only initializes `ReviewState` rows for future scheduling.
- Notes, review sessions, dashboard high-risk resume decisions, settings page, Java/C++ real sandbox, auth/login, and external deployment.

## Assumptions

- M1 provides the required base tables and seed catalog before this task starts.
- Local development can use deterministic templates instead of LLM calls for `plan_draft` generation.
- Desktop can call the API at `http://127.0.0.1:8001` during local development.
