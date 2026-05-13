# Implementation Checklist

## Pre-Development

- [x] Read `.trellis/spec/backend/index.md` and backend guides.
- [x] Read `.trellis/spec/frontend/index.md` and frontend guides.
- [x] Check `docs/plans/learning-agent-implementation-plan.md` Milestone 1.
- [x] Check `docs/architecture/database-schema.md` for M1-compatible table names and fields.

## Backend API

- [x] Create `app.main:app`.
- [x] Add environment/config loader.
- [x] Add `/health` route.
- [x] Add API package test setup.

## Database

- [x] Add DB connection helper.
- [x] Add repeatable schema SQL for M1 tables.
- [x] Add seed upsert SQL/Python for runtime profiles and language courses.
- [x] Add bootstrap command module.
- [x] Add smoke test for bootstrap and core insert/query relationships.

## Worker

- [x] Create Celery app skeleton.
- [x] Register `health.ping` smoke task.
- [x] Add import/registration smoke test.

## Frontend

- [x] Add health API helper.
- [x] Update desktop shell to check `/health`.
- [x] Render online/offline/loading state and retry.
- [x] Preserve current responsive shell layout.

## Validation

- [x] `docker compose -f .\aearn\infra\docker-compose.yml config --quiet`
- [x] `uv --directory .\aearn\services\api run python -m app.db.bootstrap`
- [x] `uv --directory .\aearn\services\api run python -m pytest`
- [x] `uv --directory .\aearn\services\api run ruff check .`
- [x] `uv --directory .\aearn\services\api run python -m mypy app`
- [x] `uv --directory .\aearn\services\api run python -c "from app.main import app; print(app.title)"`
- [x] `uv --directory .\aearn\services\api run python -c "from aearn_worker.worker_app import celery_app; print(celery_app.main)"`
- [x] `pnpm --dir .\aearn desktop:check`

## Review Gates

- [x] M1 does not implement M2 onboarding or `plan_draft` behavior.
- [x] M1 creates the DB/API/desktop foundation M2 can consume.
- [x] No real secrets are committed.
