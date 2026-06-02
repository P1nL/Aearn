# 01 Local Stable Startup Design

## Scope

This child owns the repo-level local lifecycle contract for the complete Aearn stack. It makes the existing startup path reliable and reviewable enough for later product-completion children to depend on.

Owned files are expected to stay close to:

- `aearn/package.json`
- `aearn/scripts/start-dev.ps1`
- `aearn/infra/docker-compose.yml`
- `docs/setup/development-environment.md`
- focused API tests under `aearn/services/api/tests/`

The task may inspect desktop and API code for health/readiness facts, but it should not change core learning behavior.

## Existing Startup Architecture

The current command family is:

| Command | Purpose |
|---|---|
| `pnpm --dir .\aearn dev` | Start Docker dependencies, bootstrap DB, API, worker, and desktop |
| `pnpm --dir .\aearn dev:status` | Print dependency/readiness/process status |
| `pnpm --dir .\aearn dev:restart` | Stop tracked processes, then start again |
| `pnpm --dir .\aearn dev:stop` | Stop tracked API/worker/desktop processes |

`aearn/scripts/start-dev.ps1` is the orchestration layer. It uses:

- `docker compose -f .\aearn\infra\docker-compose.yml up -d`
- `uv --directory .\aearn\services\api run python -m app.db.bootstrap`
- `uv --directory .\aearn\services\api run python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload`
- `uv --directory .\aearn\services\api run python -m celery -A aearn_worker.worker_app:celery_app worker --loglevel=info --pool=solo`
- `pnpm --dir .\aearn desktop:dev`

## Startup State Flow

1. Ensure `aearn/.logs/` exists.
2. Assert required commands.
3. For `-Stop`, read `dev-processes.json`, stop tracked process trees, remove state, and show status.
4. For `-Restart`, stop tracked process trees before normal startup.
5. Start or reuse Docker dependencies unless `-SkipDocker` is set.
6. Bootstrap database unless `-SkipBootstrap` is set.
7. Reuse API if `GET /health` is ready; otherwise start API and wait for readiness.
8. Reuse worker if a Celery worker command is present; otherwise start worker and wait for a ready log pattern.
9. Reuse desktop if `http://127.0.0.1:1420` is ready; otherwise start desktop and wait for readiness.
10. Save tracked PIDs and print status.

## Readiness Contracts

- API readiness is `http://127.0.0.1:8001/health`.
- Desktop readiness is `http://127.0.0.1:1420`.
- Worker readiness is currently inferred from Celery log output containing `ready`.
- Docker readiness is delegated to `docker compose ps` and service healthchecks in `aearn/infra/docker-compose.yml`.

Implementation should prefer clearer component-specific failures over silent retries or generic PowerShell exceptions.

## Failure and Recovery Contracts

The startup workflow should map common failures to the component that failed:

- missing `uv`, `pnpm`, or `docker`
- Docker compose startup failure
- database bootstrap failure
- API readiness timeout
- worker readiness timeout
- desktop readiness timeout
- stale or corrupt `dev-processes.json`

Recovery should stay local and explicit:

- `dev:status` for inspection
- `dev:restart` for tracked process recovery
- `dev:stop` for stopping script-managed API/worker/desktop processes
- documented manual fallback commands for debugging

This task must not auto-install tools or mutate global machine configuration.

## Data and File Contracts

`aearn/.logs/` is the local runtime artifact directory:

- `dev-processes.json`
- `api-dev.out.log`
- `api-dev.err.log`
- `worker-dev.out.log`
- `worker-dev.err.log`
- `desktop-dev.out.log`
- `desktop-dev.err.log`

These files are runtime artifacts and should not be committed.

`dev-processes.json` should remain best-effort state, not the only source of truth. Status should still report API/desktop readiness even if the state file is missing or corrupt.

## Compatibility Notes

- Keep PowerShell as the default Windows command path.
- Keep API port `8001` and desktop port `1420` unless a broader configuration task changes them.
- Keep Docker services named `aearn_postgres` and `aearn_redis`.
- Preserve manual startup commands documented in `docs/setup/development-environment.md`.
- Do not make this child depend on future environment doctor UI; later environment doctor can consume this contract.

## Trade-Offs

- A single PowerShell entrypoint is preferred over cross-platform startup wrappers because the current user environment and docs are Windows-first.
- Script-managed local processes are preferred over always killing by port because they reduce the chance of stopping unrelated user processes.
- Docker is kept as a local dependency manager for PostgreSQL and Redis; this child does not replace it with embedded services.
- Desktop startup remains part of `dev` because the parent goal is a complete local product, not API-only development.
