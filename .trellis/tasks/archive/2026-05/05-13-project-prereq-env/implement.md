# 配置项目前置环境

## Implementation Checklist

- [x] Confirm task artifacts with user before `task.py start`.
- [x] Create `aearn/` directory structure.
- [x] Add `aearn/.gitignore`.
- [x] Add `aearn/.env.example`.
- [x] Add `aearn/infra/docker-compose.yml`.
- [x] Add backend `services/api/pyproject.toml` with pinned setup dependencies.
- [x] Add worker placeholder under `services/worker/`.
- [x] Add shared package placeholder under `packages/shared/`.
- [x] Create/sync backend virtual environment with `uv`.
- [x] Add or generate minimal desktop Tauri app under `apps/desktop/`.
- [x] Start PostgreSQL and Redis using the new compose file.
- [x] Verify toolchain versions.
- [x] Verify backend dependency imports.
- [x] Verify PostgreSQL connectivity.
- [x] Verify Redis connectivity.
- [x] Verify Tauri empty app can start/build/check in a practical non-interactive way.
- [x] Update `prd.md` acceptance checklist with evidence.

## Validation Commands

```powershell
pwsh --version
git --version
docker --version
docker compose version
node --version
corepack --version
pnpm --version
rustc --version
cargo --version
python --version
uv --version
```

```powershell
docker compose -f .\aearn\infra\docker-compose.yml up -d
docker compose -f .\aearn\infra\docker-compose.yml ps
```

```powershell
uv --directory .\aearn\services\api sync
uv --directory .\aearn\services\api run python -c "import fastapi, langgraph, langchain, redis, celery"
```

```powershell
pnpm --dir .\aearn\apps\desktop install
pnpm --dir .\aearn\apps\desktop tauri --version
```

## Review Gates

- Do not continue using the superseded `06`/`07` environment plan.
- Do not write real secrets.
- Do not modify historical tutorial directories for this setup.
- Do not implement business behavior in this task.
