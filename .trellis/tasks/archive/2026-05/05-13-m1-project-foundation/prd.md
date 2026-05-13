# Implement Milestone 1 Foundation

## Goal

Implement Aearn Milestone 1 as a standalone foundation before Milestone 2. The result must make the desktop shell, API service, PostgreSQL schema, worker skeleton, and smoke tests runnable enough for later onboarding and learning-plan work.

## Background / Known Context

- Formal runtime lives under `aearn/`; historical tutorial directories `01_` through `07_` are reference only.
- `aearn/services/api/pyproject.toml` pins FastAPI, LangGraph, LangChain, psycopg, Redis, Celery, pytest, ruff, and mypy, but no API source files exist yet.
- `aearn/apps/desktop/` currently renders a static Milestone 0 shell and does not call the API.
- `aearn/infra/docker-compose.yml` already defines local PostgreSQL and Redis services.
- Milestone 1 in `docs/plans/learning-agent-implementation-plan.md` requires FastAPI health, desktop health integration, migration baseline, core learning/exercise tables, Celery worker skeleton, and smoke tests.
- Milestone 2 must not start until this foundation is implemented and verified.

## Requirements

- Implement a FastAPI app under `aearn/services/api/` with an importable `app` and `GET /health`.
- Implement configuration loading from environment variables using `.env.example` defaults.
- Implement a repeatable local database bootstrap/migration path for the M1 schema.
- Create required M1 tables or compatible MVP subsets for: `users`, preferences/profile fields, `runtime_profiles`, `language_courses`, `learning_plans`, `plan_modules`, `knowledge_points`, `exercises`, `attempts`, and `review_states`.
- Seed the first-version runtime/course catalog required by later milestones.
- Provide minimal insert/smoke helpers or tests proving plan, exercise, attempt, and review state rows can be created.
- Implement a Celery worker skeleton under `aearn/services/worker/` that can import/register a task and connect to Redis.
- Update the desktop app so it checks the local API health endpoint and visibly reports online/offline state.
- Add focused tests and verification commands for API health, DB bootstrap, smoke inserts, worker import, and desktop build.
- Keep M2-specific onboarding behavior out of this task except where seed data is needed by M1/M2.

## Acceptance Criteria

- [x] `GET /health` returns `ok` from the FastAPI service.
- [x] `docker compose -f .\aearn\infra\docker-compose.yml config --quiet` passes.
- [x] Database bootstrap can run repeatedly without corrupting existing local schema.
- [x] M1 core tables exist with compatible names and key fields from `docs/architecture/database-schema.md`.
- [x] Seed catalog includes runtime profiles and language courses for JavaScript, HTML/CSS, Python, Java placeholder, and C++ placeholder.
- [x] A smoke test can insert or verify a user/profile row.
- [x] A smoke test can insert or verify a learning plan, module, knowledge point, exercise, attempt, and review state relationship.
- [x] Worker skeleton imports successfully and exposes at least one registered smoke task.
- [x] Desktop shell calls `/health` and renders API online/offline status without crashing when the API is unavailable.
- [x] Backend lint/type/test commands pass for the new service code.
- [x] Desktop build/typecheck passes after health integration.

## Definition Of Done

- [x] Backend tests pass from `aearn/services/api`.
- [x] Backend lint/type checks pass from `aearn/services/api`.
- [x] Worker import smoke passes.
- [x] Desktop build/typecheck passes from `aearn/`.
- [x] No real secrets are added to `.env.example`, test data, logs, or docs.
- [x] M2 task remains planning-only and explicitly depends on this task being complete.

## Out Of Scope

- M2 onboarding UI, user profile APIs, `plan_draft` generation, and `POST /api/plans` confirmation behavior.
- M3 learning sessions, runner, generated exercise UI, Attempts from real run/submit operations, and scoring.
- Full FSRS scheduling algorithm and review queue.
- Full Alembic migration framework if a smaller repeatable local bootstrap is sufficient for M1.
- Production deployment or auth/login.

## Assumptions

- Local development uses PostgreSQL and Redis from `aearn/infra/docker-compose.yml`.
- A direct SQL bootstrap is acceptable for M1 if it is repeatable, documented in code, and compatible with future migration tooling.
- Desktop can use `http://127.0.0.1:8001` as the local API default.
