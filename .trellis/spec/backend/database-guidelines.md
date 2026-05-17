# Database Guidelines

> Database patterns and conventions for this project.

---

## Overview

The formal MVP runtime lives under `aearn/`, not under the historical `01_` through `07_` tutorial directories. Local backend prerequisites use Docker Compose from `aearn/infra/docker-compose.yml`.

---

## Query Patterns

- First implement database behavior from `docs/architecture/database-schema.md`; do not infer table names or enums from historical tutorial code.
- Use PostgreSQL as the source of truth for persisted API state.
- Use explicit SQL or migration-defined schema contracts. Avoid ORM-only behavior that is not reflected in migration files.
- Use UUID primary keys and stable `slug` fields only where the schema document defines them.
- Use `timestamptz` for persisted timestamps and expose API timestamps as ISO 8601 UTC strings.
- When implementing resume / inactivity heuristics, do not treat trigger-managed `updated_at` columns as user activity. Use domain timestamps such as `learning_sessions.started_at`, `learning_sessions.ended_at`, and `attempts.created_at`.
- Use cursor pagination for list APIs where the API contract requires `page_info`.

---

## Migrations

- Milestone 1 must establish a repeatable migration baseline before features write business data.
- Migration order must follow `docs/plans/learning-agent-implementation-plan.md`: base tables first, then learning/exercise core tables, then review and notes tables.
- Use `CREATE EXTENSION IF NOT EXISTS pgcrypto;` before relying on `gen_random_uuid()`.
- Add `set_updated_at()` triggers for mutable business tables.
- Do not create PostgreSQL enum types for MVP enums. The schema currently specifies `text CHECK (...)` to keep enum changes migration-friendly.
- Append-only tables such as `attempts` and `review_logs` should be corrected by new records or explicit status fields, not by soft deletion.

---

## Naming Conventions

- Table names are plural `snake_case`: `learning_plans`, `knowledge_points`, `review_states`.
- Columns are `snake_case` and should match API fields unless the API contract explicitly uses a derived field.
- JSONB columns use a `_json` suffix where the schema uses it, such as `skill_tags_json` and `supported_exercise_types_json`.
- Index names should be descriptive and stable: `idx_<table>_<columns>`.
- Unique constraints for active records should include `WHERE deleted_at IS NULL` or `WHERE archived_at IS NULL` when the schema requires soft-delete or archive semantics.
- Idempotency storage must preserve both `Idempotency-Key` and request body identity when implemented.

---

## Scenario: Local PostgreSQL and Redis Prerequisite Services

### 1. Scope / Trigger

- Trigger: any backend, worker, checkpoint, store, session, queue, or cache work for Aearn.
- Scope: local development only; do not treat the historical tutorial project compose files as the formal runtime.

### 2. Signatures

- Compose command: `docker compose -f .\aearn\infra\docker-compose.yml up -d`
- PostgreSQL health command: `docker exec aearn_postgres pg_isready -U postgres -d postgres`
- Redis health command: `docker exec aearn_redis redis-cli ping`
- Python PostgreSQL smoke check: `psycopg.connect("postgresql://postgres:postgres@127.0.0.1:5432/postgres?sslmode=disable", connect_timeout=10)`
- Python Redis smoke check: `redis.from_url("redis://127.0.0.1:6379/0").ping()`

### 3. Contracts

- `DATABASE_URL`: `postgresql://postgres:postgres@127.0.0.1:5432/postgres?sslmode=disable`
- `REDIS_URL`: `redis://127.0.0.1:6379/0`
- `CELERY_BROKER_URL`: `redis://127.0.0.1:6379/0`
- `CELERY_RESULT_BACKEND`: `redis://127.0.0.1:6379/1`
- PostgreSQL image: `postgres:15`
- Redis image: `redis:latest`
- Container names: `aearn_postgres`, `aearn_redis`

### 4. Validation & Error Matrix

- Docker daemon not running -> start Docker Desktop before running Compose.
- `postgres:15` image missing or pull is slow -> run `docker pull postgres:15` separately, then retry Compose.
- Python PostgreSQL `localhost` connection hangs on Windows -> use `127.0.0.1` in env defaults and smoke checks.
- Port `5432` or `6379` already bound -> inspect `docker ps -a --format "table {{.Names}}\t{{.Ports}}"` before changing ports.

### 5. Good/Base/Bad Cases

- Good: both containers are `healthy`, `pg_isready` accepts connections, Redis returns `PONG`, and Python clients connect through `127.0.0.1`.
- Base: Compose starts but health is still `starting`; wait and rerun `docker compose ps`.
- Bad: reusing `06_` or `07_` compose files as the formal runtime, or committing a real `.env` with secrets.

### 6. Tests Required

- Run `docker compose -f .\aearn\infra\docker-compose.yml config --quiet`.
- Run container health commands for PostgreSQL and Redis.
- Run Python client smoke checks for PostgreSQL and Redis from `services/api` via `uv`.
- Verify `.env.example` contains only local defaults and no real LLM keys.

### 7. Wrong vs Correct

#### Wrong

```powershell
uv --directory .\aearn\services\api run python -c "import psycopg; psycopg.connect('postgresql://postgres:postgres@localhost:5432/postgres?sslmode=disable')"
```

#### Correct

```powershell
uv --directory .\aearn\services\api run python -c "import psycopg; conn = psycopg.connect('postgresql://postgres:postgres@127.0.0.1:5432/postgres?sslmode=disable', connect_timeout=10); print(conn.execute('select 1').fetchone()[0]); conn.close()"
```
