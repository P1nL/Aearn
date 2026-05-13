# 配置项目前置环境

## Technical Design

### Source Document

Use `docs/setup/development-environment.md` for Milestone 0 environment requirements, and use `docs/plans/learning-agent-implementation-plan.md` for the formal project directory layout. The old `06` and `07` directories are reference material only, not the target runtime.

### Directory Layout

Create a new formal project root:

```text
aearn/
  apps/
    desktop/
  services/
    api/
    worker/
  packages/
    shared/
  infra/
```

### Backend Environment

Use `uv` in `aearn/services/api/` with a `pyproject.toml` that pins the document's minimum dependency set:

- `fastapi==0.128.0`
- `uvicorn==0.40.0`
- `langchain==1.2.0`
- `langchain-openai==1.1.6`
- `langgraph==1.0.5`
- `langgraph-checkpoint-postgres==3.0.2`
- `psycopg[binary,pool]`
- `redis==7.1.0`
- `celery==5.5.3`
- `pydantic`
- `python-dotenv`

Development dependencies:

- `pytest`
- `pytest-asyncio`
- `httpx`
- `ruff`
- `mypy`

### Frontend / Desktop Environment

Use pnpm + Vite + React + TypeScript + Tauri in `apps/desktop/`. Prefer generated minimal scaffolding over hand-written Tauri internals where possible. Tauri CLI should be project-local through package scripts rather than global.

### Runtime Services

Create `aearn/infra/docker-compose.yml` with:

- PostgreSQL `postgres:15` on `5432`, user/password/db `postgres`
- Redis `redis:latest` on `6379`

Use named volumes scoped to the formal project to avoid colliding with historical sample compose files.

### Environment Variables

Create `aearn/.env.example` from the setup document. Do not create real secrets. If a local `.env` is useful for validation, create it only from non-secret local defaults and ensure it is ignored.

### Validation Strategy

Run checks that prove prerequisites are available without implementing product behavior:

- Toolchain version commands
- `uv sync` / dependency import checks
- `docker compose up -d` and service readiness checks
- Redis ping
- PostgreSQL connection check
- Tauri empty app startup/build/check where practical in a non-interactive CLI session

## Rollout / Rollback

- Rollout: create new formal project directory, add config/scaffold files, install dependencies, start Docker services, run checks.
- Rollback: stop Docker services with the new compose file and remove `aearn/` if the user wants to discard the setup.
