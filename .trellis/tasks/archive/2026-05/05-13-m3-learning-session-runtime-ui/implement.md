# Implementation Checklist

- [x] Reconfirm the task has expanded from M3 minimal slice to full M3.
- [x] Load `trellis-before-dev` and relevant backend/frontend spec indexes before code edits.
- [x] Keep all implementation inside `aearn/services/api/` and `aearn/apps/desktop/`.
- [x] Extend backend models/routes for `hint`, `explain-error`, and `check-explanation`.
- [x] Add a deterministic guidance layer for hints, error explanations, and explanation checks.
- [x] Expand runner behavior so JS hidden-summary failures and Python runtime errors can drive the new assist flows.
- [x] Persist `Attempt(run)` guidance facts without mutating `ReviewState`.
- [x] Update submit evaluation to consume stored explanation-check results and carried-forward hint/error counters.
- [x] Extend desktop API/types for the new M3 endpoints.
- [x] Expand the learning workbench UI with preview/test split actions, hint controls, error explanation, explanation check, retry, and stale handling.
- [x] Expand M3 backend tests beyond the minimal happy path.
- [x] Run backend tests, backend lint, desktop build, and browser smoke.
- [x] Update task docs and Trellis specs to reflect full M3 instead of the earlier minimal-slice scope.

## Validation

- Backend lint:
  - `.\.venv\Scripts\ruff.exe check app tests`
- Backend tests:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_learning_sessions_m3.py tests\test_onboarding_m2.py -q`
- Desktop build:
  - `pnpm --dir .\aearn desktop:check`
- Browser smoke:
  - run local API on `http://127.0.0.1:8001`
  - run Vite on `http://127.0.0.1:1420`
  - open the desktop shell, generate a JS draft, confirm it, run visible tests, check explanation, submit once

## Validation Results

- Passed: `docker compose -f .\aearn\infra\docker-compose.yml config --quiet`
- Passed: `docker exec aearn_postgres pg_isready -U postgres -d postgres`
- Passed: `docker exec aearn_redis redis-cli ping`
- Passed: `.\.venv\Scripts\ruff.exe check app tests`
- Passed: `.\.venv\Scripts\python.exe -m pytest tests\test_learning_sessions_m3.py tests\test_onboarding_m2.py -q`
- Passed: `pnpm --dir .\aearn desktop:check`
- Passed: browser smoke on `http://127.0.0.1:1420` with live API on `http://127.0.0.1:8001`

## Residual Notes

- Current backend test suite still emits the existing FastAPI deprecation warning for `HTTP_422_UNPROCESSABLE_ENTITY`; this task did not widen that behavior.
- Dashboard/resume remains a later M6 concern; browser smoke here verifies the learning-session loop, not the final default app entry policy.

## Review Gates

- Before Phase 3.4 commit: backend regression and desktop build must remain green after task/spec doc updates.
- Before `/trellis:finish-work`: confirm the final dirty set excludes unrelated local config and includes only task-relevant code/spec/task-doc changes.
