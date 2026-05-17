# M6 设置、恢复与发布前硬化 Implementation Plan

## Implementation Checklist

- [x] Add focused backend tests for `GET /api/dashboard` and `GET /api/learning-sessions/resume`, including:
  - empty / missing-user paths;
  - normal open preferring learning;
  - due review notice without forced review;
  - high-risk review-first routing;
  - resumable vs non-resumable session context.
- [x] Add or refactor backend service code for dashboard/resume assembly using existing plan/session/review tables.
- [x] Add `GET /api/dashboard` route and `GET /api/learning-sessions/resume` route, then register the dashboard router in `app/main.py`.
- [x] Extend desktop `types.ts` and `api.ts` for dashboard, resume, user-read, and preferences-update calls.
- [x] Add minimal local bootstrap persistence for `userId` / `planId` and wire app initialization to use dashboard-first boot for returning users.
- [x] Refactor shell/home startup behavior in `App.tsx` so review notice, resume affordance, and high-risk review-first routing follow the backend decision instead of hard-coded onboarding-first state.
- [x] Replace the current static six-tab `SettingsPage` model with the documented seven-category structure.
- [x] Wire editable settings fields to `GET /api/users/{user_id}` and `PATCH /api/users/{user_id}/preferences`, while keeping unsupported categories read-only / diagnostic.
- [x] Update any closest source-of-truth docs if the high-risk resume heuristic or fallback resume summary behavior needs to be made explicit.
- [x] Run backend tests, desktop checks, Trellis validation, and a final diff sanity check.

## Validation Snapshot

- `uv --directory .\aearn\services\api run python -m pytest tests/test_dashboard_resume_m6.py`
- `uv --directory .\aearn\services\api run python -m pytest tests/test_onboarding_m2.py tests/test_learning_sessions_m3.py tests/test_reviews_m4.py tests/test_notes_m5.py tests/test_worker_import.py`
- `pnpm --dir .\aearn desktop:check`
- `python .\.trellis\scripts\task.py validate .\.trellis\tasks\05-17-m6-settings-resume-hardening`
- `git diff --check`

## Validation Notes

- API pytest batches use the shared bootstrap database and should be run sequentially, not in parallel.
- After the desktop refactor, run a manual smoke of the returning-user bootstrap path as well as the empty onboarding path.
- The returning-user + settings smoke was verified with headless Edge against `http://127.0.0.1:1420` and `http://127.0.0.1:8001`, including `localStorage` bootstrap restoration for `userId` / `planId`.
- If a browser smoke is needed, prefer `pnpm --dir .\aearn desktop:dev` plus local verification against `http://127.0.0.1:1420` and `http://127.0.0.1:8001/health`.

## Review Gates

- Planning gate: `prd.md`, `design.md`, and `implement.md` exist before `task.py start`.
- Product gate: the “interrupted + high-risk review” heuristic is explicitly approved or documented before implementation starts.
- Boundary gate: settings do not introduce score / Attempt / FSRS rule editing and do not fake persistence for fields with no backend contract.
- Bootstrap gate: returning-user startup works without breaking the current first-run onboarding path.
- Contract gate: dashboard/resume responses stay aligned with `docs/architecture/api-contract.md`, or the relevant docs are updated in the same M6 change.
