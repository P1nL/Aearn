# 01 Local stable startup

## Goal

Validate and productize Aearn's existing local stack startup workflow so a Windows-first local user can start, inspect, restart, and stop the complete local development product through one stable repo-level entrypoint.

This child does not invent a new startup model. It hardens the current `aearn/scripts/start-dev.ps1` and `pnpm --dir .\aearn dev*` command family into the product baseline for Phase 1.

## Parent Dependency

This task is a child of `.trellis/tasks/06-02-local-product-completion`.

It satisfies the parent requirement for a stable local startup/check workflow covering:

- PostgreSQL and Redis through `aearn/infra/docker-compose.yml`
- database schema bootstrap
- FastAPI on `127.0.0.1:8001`
- Celery worker
- Tauri desktop dev server on `127.0.0.1:1420`
- logs and tracked process state under `aearn/.logs/`

## Confirmed Facts

- `aearn/package.json` already exposes `dev`, `dev:restart`, `dev:stop`, and `dev:status`.
- `aearn/scripts/start-dev.ps1` already supports `-Restart`, `-Stop`, `-Status`, `-SkipDocker`, `-SkipBootstrap`, `-NoWorker`, and `-NoDesktop`.
- The script writes process state to `aearn/.logs/dev-processes.json`.
- The script starts Docker dependencies, bootstraps schema, starts API, starts worker, starts desktop, then prints status.
- The API health endpoint is `GET /health`, returning `{"status":"ok","service":"aearn-api"}`.
- Current Docker compose exposes PostgreSQL on `5432` and Redis on `6379`.
- Current focused smoke tests include `tests/test_health.py`, `tests/test_db_bootstrap.py`, and `tests/test_worker_import.py`.
- `docs/setup/development-environment.md` documents the same stable startup command family and manual fallback command sequence.

## User Value

- A learner or developer can start the local Aearn product without remembering five manual commands.
- A future environment doctor can depend on one known startup/status contract instead of reverse-engineering process state.
- Startup failures become diagnosable through consistent logs, status output, and recovery commands.
- Later child tasks can assume a reliable local baseline before changing learning UX, grounding, runners, or environment guidance.

## Requirements

- Keep `pnpm --dir .\aearn dev` as the primary local startup command.
- Keep `pnpm --dir .\aearn dev:status`, `dev:restart`, and `dev:stop` as the lifecycle command family.
- Ensure startup order remains Docker PostgreSQL/Redis, database bootstrap, API, worker, desktop.
- Preserve Windows-first behavior and use `python -m uvicorn` / `python -m celery` for backend processes.
- Ensure readiness checks cover API `/health` and desktop dev server `http://127.0.0.1:1420`.
- Ensure status output identifies Docker service state, API readiness, desktop readiness, and tracked PIDs.
- Ensure restart and stop behavior operate on tracked script-managed processes and do not require killing random user processes manually.
- Ensure logs are predictable and documented under `aearn/.logs/`.
- Ensure failures for missing `uv`, `pnpm`, `docker`, database bootstrap, API readiness, worker readiness, or desktop readiness are actionable enough for the next child task to build environment guidance on top.
- Keep documented manual fallback commands synchronized with the stable script.
- Add or update focused tests/checks where practical for startup-adjacent contracts that can be verified without launching an interactive Tauri window.

## Acceptance Criteria

- [x] `pnpm --dir .\aearn dev:status` reports Docker, API, desktop, and tracked process state without requiring manual command lookup.
- [x] `pnpm --dir .\aearn dev` starts or reuses Docker dependencies, bootstraps the database, starts API, starts worker, starts desktop, writes logs, and prints final status.
- [x] `pnpm --dir .\aearn dev:restart` stops tracked API/worker/desktop processes before starting a fresh stack.
- [x] `pnpm --dir .\aearn dev:stop` stops tracked API/worker/desktop processes and leaves Docker dependency visibility available through status.
- [x] Missing command or readiness failures surface a clear component name and next diagnostic location.
- [x] `aearn/.logs/` contains stable log filenames and `dev-processes.json` remains parseable after successful startup.
- [x] `docs/setup/development-environment.md` matches the implemented command family, startup order, ports, health endpoint, and manual fallback commands.
- [x] Existing focused checks still pass: `tests/test_health.py`, `tests/test_db_bootstrap.py`, `tests/test_worker_import.py`.
- [x] `pnpm --dir .\aearn desktop:check` still passes after any script or doc changes.

## Out of Scope

- Public deployment, production service management, installer packaging, Windows service registration, or system tray management.
- Automatically installing Docker, Node, pnpm, uv, Rust, WebView2, Python, or any language runtime.
- Mutating global PATH, Docker Desktop settings, WSL settings, or system registry.
- Replacing the later `05-environment-doctor-and-install-guidance` child. This child only provides startup/status facts and failure signatures.
- Adding cloud telemetry or external monitoring.

## Open Questions

- None blocking planning. Implementation should first verify current script behavior and only change code where real drift or usability gaps are found.
