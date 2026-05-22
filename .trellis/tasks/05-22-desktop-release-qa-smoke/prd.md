# Desktop release QA smoke

## Goal

Run release-readiness desktop QA against the real local Aearn app, not only backend API scripts. The pass should verify that the MVP can be opened from a cold desktop/web shell, complete onboarding, enter the learning loop, use model-backed error explanation, submit a successful attempt, reload into resume/dashboard state, and keep Settings within the documented safety boundary.

## Confirmed Facts

- Formal runtime is under `aearn/`.
- Desktop frontend dev server uses `pnpm --dir .\aearn\apps\desktop dev` and serves `http://127.0.0.1:1420`.
- Desktop API client currently uses `API_BASE_URL = "http://127.0.0.1:8001"`.
- Backend local API server should run on `127.0.0.1:8001` for desktop QA.
- PostgreSQL and Redis are provided by `aearn/infra/docker-compose.yml`.
- Bootstrap storage key is `localStorage["aearn.bootstrap"]`.
- The release acceptance source of truth is `docs/qa/acceptance-test-plan.md`.
- Relevant frontend code-spec scenarios are M2 onboarding, M3 generated exercise workbench, M4 review page, and M6 bootstrap/dashboard/resume.
- Existing live LLM API smoke script verifies the backend `explain-error` model path but does not verify rendered desktop UI behavior.

## Requirements

- Start or verify local PostgreSQL and Redis.
- Start or verify backend API on `http://127.0.0.1:8001` with local LLM env if available.
- Start or verify desktop frontend on `http://127.0.0.1:1420`.
- Run `pnpm --dir .\aearn desktop:check` before browser QA.
- Use a real browser automation pass to inspect rendered UI, not only HTTP API responses.
- Clear `localStorage["aearn.bootstrap"]` for cold-start QA.
- Verify cold start enters onboarding and does not jump to stale demo state.
- Verify onboarding can create a JavaScript plan and write bootstrap context after confirmation.
- Verify returning-user reload calls dashboard/resume flow and restores a real state.
- Verify learning workbench can start a session, run visible tests, explain a failing run, edit/rerun, check explanation, and submit.
- Verify `explain-error` displays or propagates non-secret model/fallback diagnostics when available; it must not expose API keys or hidden case IDs.
- Verify stale state appears after code changes following a run, and submit is blocked until rerun.
- Verify Settings page categories and boundary: seven categories visible, model settings are diagnostic/config guidance only, and there are no controls for scoring rules, Attempt facts, FSRS parameters, or raw `due_at`.
- Record each QA result as pass/fail/blocked with concrete evidence.
- Discover release-impacting defects through the browser QA pass, then fully fix all P0/P1 defects that are within the current MVP scope before the task can pass.
- Treat P2/UX issues as recorded known issues unless they misrepresent core runtime capability or block a documented acceptance path.

## Acceptance Criteria

- [ ] `docker compose -f .\aearn\infra\docker-compose.yml ps` shows PostgreSQL and Redis healthy or an equivalent health check passes.
- [ ] Backend `/health` returns `status=ok` on `127.0.0.1:8001`.
- [ ] Desktop frontend loads at `127.0.0.1:1420` without current console errors after the latest reload.
- [ ] `pnpm --dir .\aearn desktop:check` passes.
- [ ] Cold start with cleared `aearn.bootstrap` lands on onboarding.
- [ ] Onboarding plan generation and confirmation succeed for JavaScript.
- [ ] `aearn.bootstrap` is written with `userId` and `planId`.
- [ ] Reload with bootstrap performs or reflects real user/plan/dashboard/resume state instead of a demo shortcut.
- [ ] Learning path can run a flawed JavaScript visible-test attempt and show a failure.
- [ ] `explain-error` works from the rendered UI and the user-facing output stays non-secret.
- [ ] Editing code after a run shows stale state, and rerun clears it.
- [ ] Fixed JavaScript visible tests pass, explanation check passes, and submit succeeds.
- [ ] Settings page exposes the documented categories and does not expose score/Attempt/FSRS/due-date mutation controls.
- [ ] Any failed P0/P1 item within current MVP scope is fixed in this task, with affected checks rerun.
- [ ] Final QA is rerun after P0/P1 fixes and has concrete pass/fail/blocked evidence.
- [ ] Any remaining unfixed blocker is explicitly marked as release-blocking, not accepted as pass.

## Out Of Scope

- Adding new product features.
- Reworking the desktop design system.
- Persisting model API keys in the desktop UI or database.
- Full packaged installer QA.
- Cross-platform QA outside the local Windows development environment.
- Load, cost, or rate-limit testing beyond the live LLM smoke needed for release readiness.

## Open Question

- Resolved: fix discovered P0/P1 release blockers in-task before final QA pass; record only non-blocking P2/UX follow-ups unless they affect core MVP runtime truth.
