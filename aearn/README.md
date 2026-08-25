# Aearn Runtime Workspace

`aearn/` contains the formal Aearn Tutor product runtime. The repository root is reserved for Git, Trellis, documentation, and agent configuration; historical tutorial projects are not runtime dependencies.

## Layout

```text
apps/desktop/       Tauri 2 + React + TypeScript desktop
services/api/       FastAPI, Tutor Harness, PostgreSQL, learning services
services/worker/    Celery wakeup and reconciliation workers
services/executor/  Standalone controlled container executor
packages/shared/    Pure versioned contracts shared by runtimes
infra/              PostgreSQL/Redis and reviewed executor image definitions
scripts/            Local workspace orchestration
```

## Authoritative documentation

Start from [`../docs/README.md`](../docs/README.md). It routes to the current runtime architecture, API, database, product-flow, setup, QA, and release-evidence documents. [`../docs/plans/learning-agent-implementation-plan.md`](../docs/plans/learning-agent-implementation-plan.md) is a historical implementation snapshot, not current runtime authority.

## Package managers

- Node/Desktop: `pnpm`, with the single authoritative lock at `aearn/pnpm-lock.yaml`.
- API and executor Python environments: `uv`, with service-local `pyproject.toml` and `uv.lock` files.
- Rust/Tauri: Cargo under `apps/desktop/src-tauri/`.

Do not run `npm install` in `apps/desktop/` or add a nested `package-lock.json`.

## Common commands

Run from the repository root on Windows:

```powershell
pnpm install --dir .\aearn
pnpm --dir .\aearn dev
pnpm --dir .\aearn dev:status
pnpm --dir .\aearn dev:stop
pnpm --dir .\aearn\apps\desktop test -- --run
pnpm --dir .\aearn desktop:check
uv --directory .\aearn\services\api lock --check
uv --directory .\aearn\services\api run python -m pytest -q
```

The one-command development runtime and its safety boundaries are documented in [`../docs/setup/development-environment.md`](../docs/setup/development-environment.md). Real provider, executor, deployment, and production actions require explicit approval and their dedicated runbooks.
