# Implementation Plan

## Preconditions

- Do not start execution until the user approves this planning artifact.
- After approval, run `python .\.trellis\scripts\task.py start 05-22-desktop-release-qa-smoke`.
- Load `trellis-before-dev` before making any code changes.
- If the run only records QA evidence and no code changes, still keep the task evidence in this directory before finishing.

## Ordered Checklist

1. Start and verify local infrastructure.
   - Run `docker compose -f .\aearn\infra\docker-compose.yml up -d`.
   - Confirm `docker compose -f .\aearn\infra\docker-compose.yml ps` shows healthy PostgreSQL and Redis.

2. Start backend API on the desktop client port.
   - Ensure required LLM env variables are available only in the process environment if model-backed UI verification is needed.
   - Start backend from `aearn/services/api` on `127.0.0.1:8001`.
   - Verify `GET http://127.0.0.1:8001/health`.

3. Start desktop frontend.
   - Run `pnpm --dir .\aearn\apps\desktop dev`.
   - Open `http://127.0.0.1:1420`.
   - Clear `localStorage["aearn.bootstrap"]`.

4. Run baseline build gate.
   - Run `pnpm --dir .\aearn desktop:check`.

5. Browser QA: cold start and onboarding.
   - Confirm cold start enters onboarding.
   - Confirm API online state is visible.
   - Create a unique JavaScript learning plan.
   - Confirm persisted bootstrap includes `userId` and `planId`.

6. Browser QA: returning-user bootstrap.
   - Reload the page.
   - Confirm user/plan/dashboard/resume request chain via network inspection.
   - Confirm route/state is based on real backend data.

7. Browser QA: learning loop.
   - Start a learning session from the UI.
   - Run visible tests with intentionally flawed JS and capture failing state.
   - Trigger `explain-error` and verify non-secret user-facing output.
   - Edit code after run and verify stale state appears.
   - Rerun fixed JS and verify tests pass.
   - Check explanation and submit.

8. Browser QA: settings boundary.
   - Open Settings.
   - Verify seven categories: appearance, model settings, learning preference, review, notifications, records/privacy, about/diagnostics.
   - Verify model page does not persist real API keys.
   - Verify no controls claim to edit score rules, Attempt facts, FSRS parameters, or raw `due_at`.

9. Classify findings.
   - P0/P1 pass/fail/blocked with evidence.
   - P2/UX observations as known issues, not blockers unless they mislead core runtime capability.
   - Implement full fixes for all P0/P1 defects inside current MVP scope.
   - Rerun affected checks after each fix cluster.
   - Rerun the full desktop QA path before final verdict.
   - If a P0/P1 defect is outside current MVP scope or cannot be fixed locally, record it as release-blocking instead of passing the task.

10. Finish.
    - Save QA evidence in the task directory.
    - Run any relevant verification commands after fixes.
    - Update docs/spec only if a reusable QA convention or bug pattern was discovered.
    - Commit code/evidence changes if any, then finish/archive task.

## Verification Commands

```powershell
docker compose -f .\aearn\infra\docker-compose.yml up -d
docker compose -f .\aearn\infra\docker-compose.yml ps
uv --directory .\aearn\services\api run python -m pytest tests/test_health.py tests/test_llm_integration.py
pnpm --dir .\aearn desktop:check
```

For browser targets:

```powershell
uv --directory .\aearn\services\api run uvicorn app.main:app --host 127.0.0.1 --port 8001
pnpm --dir .\aearn\apps\desktop dev
```

## Risky Files

- `aearn/apps/desktop/src/App.tsx`
- `aearn/apps/desktop/src/api.ts`
- `aearn/apps/desktop/src/types.ts`
- `aearn/apps/desktop/src/pages/*`
- `aearn/apps/desktop/src/features/learning/*`

## Rollback Points

- If browser QA reveals only evidence gaps, do not change runtime code.
- If a P0/P1 UI or backend fix is needed, keep it inside current MVP scope and rerun `desktop:check` plus the affected browser flow.
- If backend state becomes polluted, create a new unique QA user instead of mutating existing user data manually.
