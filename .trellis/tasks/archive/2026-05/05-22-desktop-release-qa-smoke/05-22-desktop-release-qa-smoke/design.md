# Technical Design

## Scope

This task is a release QA and repair pass for the desktop MVP. It should exercise the rendered desktop frontend through a browser target, verify the backend-backed user flow, and fully fix discovered P0/P1 release blockers within the current MVP scope before the final QA verdict.

## Runtime Topology

Local QA uses three processes/services:

1. PostgreSQL and Redis through `docker compose -f .\aearn\infra\docker-compose.yml up -d`.
2. FastAPI backend at `http://127.0.0.1:8001`, matching the hard-coded desktop `API_BASE_URL`.
3. Vite desktop frontend at `http://127.0.0.1:1420`.

The desktop app is tested via the browser target because this QA phase is focused on frontend flow correctness. Packaged Tauri installer validation is out of scope.

## QA Data Flow

Cold start:

```text
clear localStorage["aearn.bootstrap"]
  -> load frontend
  -> GET /health
  -> GET /api/language-courses
  -> onboarding route visible
```

Onboarding:

```text
POST /api/users
  -> POST /api/plans/generate
  -> POST /api/plans
  -> localStorage["aearn.bootstrap"] = { userId, planId }
  -> workspace/dashboard state
```

Returning user:

```text
reload
  -> GET /api/users/{user_id}
  -> GET /api/plans/{plan_id}
  -> GET /api/dashboard?user_id=...
  -> GET /api/learning-sessions/resume?user_id=...&plan_id=...
```

Learning loop:

```text
POST /api/learning-sessions/start
  -> POST /run visible_tests with flawed JS
  -> POST /explain-error
  -> edit code and verify stale UI
  -> POST /run visible_tests with fixed JS
  -> POST /check-explanation
  -> POST /submit
```

Settings boundary:

```text
open settings
  -> verify categories
  -> verify model config is diagnostic/guidance only
  -> verify no score/Attempt/FSRS/due_at mutation controls
```

## Observability

Use browser automation to collect:

- current page snapshot or visible text evidence
- console errors after latest reload
- relevant network requests for dashboard/resume and learning actions
- final UI state after submit

Use backend/API checks only as supporting evidence. Passing backend smoke alone is not sufficient for this task.

## Compatibility

- The QA should not require committed real secrets. LLM key values remain in the process environment only.
- If no model key is configured, record whether the UI still functions through deterministic fallback; do not block unless the task specifically requires model-backed UI output for the run.
- Existing local database may contain previous smoke users; QA should create a unique user for the pass to avoid relying on old state.

## Failure Handling

P0/P1 failures should be classified:

- release blocker: main flow cannot complete or state is written incorrectly
- fix-in-task: any frontend/backend defect inside current MVP scope that blocks a documented acceptance path
- follow-up: larger product/design issue or out-of-scope work

Do not hide a failing UI state behind API-only success. If the rendered UI cannot execute the path, the QA item fails even if equivalent HTTP calls work.

The default policy is to fix P0/P1 issues in this task, rerun the affected checks, and rerun the full browser QA path before calling the task complete. P2/UX observations can be recorded as known issues unless they mislead release capability or block a documented acceptance criterion.

## Rollback

If a targeted fix is attempted and destabilizes the flow, revert only the task-owned fix and keep the QA evidence. Do not revert prior completed LLM integration commits.
