# 01 Local Stable Startup Implementation Plan

## Policy

- Keep this child in `planning` until the user reviews `prd.md`, `design.md`, and this file.
- Do not start the parent task.
- Do not dispatch implement/check sub-agents; this session implements and checks inline after approval.
- During implementation, first verify current behavior before changing the script.

## Implementation Checklist

- [x] Read relevant Trellis specs with `trellis-before-dev` before code edits.
- [x] Reconfirm current worktree and avoid unrelated dirty files: `.codex/config.toml`, `.claude/skills/grill-me/`, and `.trellis/tasks/.obsidian/*`.
- [x] Run or inspect `pnpm --dir .\aearn dev:status` to capture current status behavior.
- [x] Review `aearn/scripts/start-dev.ps1` for stale PID handling, corrupt state handling, command assertions, component-specific failures, log naming, and status readability.
- [x] Review `aearn/package.json` to ensure script names stay stable.
- [x] Review `docs/setup/development-environment.md` for drift against the script.
- [x] Make minimal script/doc/test changes only where current behavior fails the PRD acceptance criteria.
- [x] Preserve manual fallback startup commands.
- [x] Add focused tests or static checks where practical without forcing an interactive Tauri window.
- [x] Run focused backend smoke tests.
- [x] Run desktop check.
- [x] Re-run `dev:status` or a safe lifecycle subset to verify the command family after edits.

## Preferred Verification Commands

Use the focused subset first:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_health.py tests/test_db_bootstrap.py tests/test_worker_import.py -q
pnpm --dir .\aearn desktop:check
pnpm --dir .\aearn dev:status
```

If implementation changes startup orchestration, also run the relevant lifecycle command:

```powershell
pnpm --dir .\aearn dev
pnpm --dir .\aearn dev:restart
pnpm --dir .\aearn dev:stop
```

Use `dev:restart` and `dev:stop` carefully because they affect local API/worker/desktop processes started by the script.

## Expected Code and Doc Touch Points

- `aearn/scripts/start-dev.ps1`
- `aearn/package.json`
- `docs/setup/development-environment.md`
- `aearn/services/api/tests/test_health.py`
- `aearn/services/api/tests/test_db_bootstrap.py`
- `aearn/services/api/tests/test_worker_import.py`

Avoid broad changes outside this list unless the verified startup issue requires it.

## Risks

- `dev:stop` or `dev:restart` could stop user-needed local Aearn processes if stale PIDs point to reused process IDs.
- `dev` may launch an interactive Tauri desktop process; verification should be intentional and clearly reported.
- Docker Desktop may be unavailable, causing status/start checks to fail for environment reasons rather than code reasons.
- Database bootstrap tests depend on a reachable PostgreSQL instance and may skip when unavailable.
- Worker readiness based on log text can be brittle if Celery output changes.

## Rollback Points

- Revert startup script changes and continue using the documented manual command sequence.
- Keep `dev:status` available even if full `dev` startup fails.
- Keep logs under `aearn/.logs/` so failures can be diagnosed without changing application code.
- Avoid schema or business-logic changes in this child.

## Before `task.py start`

- [x] User has reviewed the child planning artifacts.
- [x] Any remaining scope decisions are resolved.
- [x] The implementation target is confirmed as startup/status hardening rather than a rewrite.
