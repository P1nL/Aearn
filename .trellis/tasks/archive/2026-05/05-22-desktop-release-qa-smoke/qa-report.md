# Desktop release QA smoke report

Date: 2026-05-22
Status: Pass after two P1 fixes

## Environment

- Local infra: `docker compose -f .\aearn\infra\docker-compose.yml up -d`
- PostgreSQL / Redis: healthy
- Backend: `http://127.0.0.1:8001/health` returned `{"status":"ok","service":"aearn-api"}`
- Desktop frontend: `http://127.0.0.1:1420`
- LLM env: no `aearn/.env` file was present and the shell had no `LLM_TYPE`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, or `OPENAI_MODEL`; UI `explain-error` was therefore verified through deterministic fallback.

## Browser QA Result

- Cold start entered onboarding instead of a stale demo state.
- JavaScript course selection generated a JavaScript draft with `browser_preview` / DOM assertion capability.
- Confirming the plan entered the real learning workspace and wrote enough bootstrap state for reload restore.
- Failed JS visible tests produced `0 / 3` and enabled `explain-error`.
- `explain-error` rendered a non-secret user-facing explanation and did not expose API keys or hidden case IDs.
- Editing blanks after a run changed the exercise state to `dirty`, displayed the stale-results warning, disabled submit, and disabled stale explain/check actions.
- Rerunning fixed blanks produced `3 / 3`, `100%` browser preview, and `visible` / `hidden` / `preview_assertion` pass summaries.
- Explanation check passed with score `2 / 2`, `follow_up_required=false`, and next action `advance_next` / "继续下一步".
- Submit passed with score `7 / 8`, `FSRS Rating=Good`, and all gates `runtime_gate`, `test_gate`, `core_blank_gate`, `explanation_gate` as `pass`.
- Reload eventually restored the learning workspace through the bootstrap/dashboard/resume path instead of staying on onboarding.
- Settings showed exactly seven categories and model settings remained read-only guidance; no API key persistence, score rule, Attempt, FSRS, or raw `due_at` controls were exposed.
- Browser console error check returned zero errors.

## Fixed Findings

- Severity: P1
- Finding: generating a JavaScript draft after selecting the JavaScript course could render the draft under `C++ Basic Placeholder / 编译沙箱后置`.
- Root cause: `OnboardingPage` reset its local form state when `existingUser` changed. The first draft generation creates a user, which updated `existingUser` and reset `selectedCourseId` back to the first catalog entry while the JavaScript draft response was still rendered.
- Fix: the reset effect now resets onboarding local state only when `resetNonce` changes, and lets the existing course-selection guard initialize `selectedCourseId` when needed.
- Regression: after the fix, selecting JavaScript produced consistent Agent text, draft title, runtime capability, modules, and source attribution.

- Severity: P1
- Finding: the settings page regressed to only 3 categories, and the diagnostics card reported `连接异常` even while the backend was online.
- Root cause: the desktop settings implementation had been simplified to `learning` / `notifications` / `diagnostics`, drifting away from the 7-category product and QA spec. In the same area, `renderDiagnosticsPanel` still compared `apiStatus` against the old raw token `ok`, but `App.tsx` now passes the human-readable label `在线` / `离线: ...`.
- Fix: expanded `SettingsKey` and `SETTING_PANELS` back to the 7-category boundary (`外观` / `模型设置` / `学习偏好` / `复习` / `通知与提醒` / `记录与隐私` / `关于与诊断`), restored product-facing read-only model/review/privacy panels in `SettingsPage`, allowed the tab row to wrap, and changed diagnostics to render the actual online label.
- Regression: rerun QA confirmed all 7 settings categories were visible, the model settings page stayed read-only without asking for API keys, the visible copy avoided spec/runbook wording, and the diagnostics card showed `在线` with `API Base URL=http://127.0.0.1:8001`.

## Verification Commands

```powershell
docker compose -f .\aearn\infra\docker-compose.yml ps
uv --directory .\aearn\services\api run python -m pytest tests/test_health.py tests/test_llm_integration.py tests/test_onboarding_m2.py tests/test_learning_sessions_m3.py tests/test_reviews_m4.py tests/test_notes_m5.py tests/test_dashboard_resume_m6.py tests/test_worker_import.py
pnpm --dir .\aearn desktop:check
```

Results:

- Backend pytest: `40 passed, 2 warnings`
- Desktop check: `tsc && vite build` passed

## Evidence Files

- `evidence/backend.err.log`
- `evidence/frontend.out.log`
- `evidence/final-learning-submit.png`
- `evidence/onboarding-course-selection.png`
- `evidence/settings-boundary.png`
