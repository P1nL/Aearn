# M6 设置、恢复与发布前硬化 Design

## Technical Design

### Boundaries

- M6 is a cross-layer feature, but it should stay inside the current Aearn MVP boundary:
  - no auth system;
  - no cloud sync;
  - no new standalone profile/settings service;
  - no score / Attempt / FSRS rule editing UI.
- Backend remains the source of truth for persisted user profile/preference data, active plan state, review counts, and resume routing decisions.
- Desktop may persist only the minimum local bootstrap context needed to find the current user and active plan after reopen. Because the current desktop package has no configured Tauri store plugin or existing persistence layer, the recommended MVP implementation is `window.localStorage`.
- Settings persistence stays within the already documented `GET /api/users/{user_id}` and `PATCH /api/users/{user_id}/preferences` contract. Categories without backed fields remain read-only summaries or diagnostics in M6.
- M6 should avoid new schema work unless implementation proves a documented contract cannot be met with current tables. The preferred design is route/service additions plus desktop refactor, not database expansion.

### Backend Architecture

#### New / Changed Routes

- Add `app/routes/dashboard.py` with `GET /api/dashboard`.
- Extend `app/routes/learning_sessions.py` with `GET /api/learning-sessions/resume`.
- Keep `app/routes/users.py` as the settings persistence backend for allowed preference fields.

#### Repository / Service Shape

- Add a dedicated backend service module for dashboard/resume assembly, for example `app/services/dashboard_repository.py`, instead of overloading `plan_repository.py` or `learning_session_repository.py` with unrelated route concerns.
- Reuse existing repository logic where it already owns the source data:
  - `plan_repository.py` for active plan/module/knowledge-point ordering;
  - `review_repository.py` for due review counts / review-risk inputs;
  - `learning_session_repository.py` for session lookup primitives where useful;
  - `user_repository.py` for validating the user exists.

### Dashboard Data Flow

1. Validate `user_id` and load the active learning plan for that user.
2. Load:
  - current plan goal and progress;
  - current module title;
  - course/runtime metadata;
  - ordered knowledge points for the active plan;
  - active learning session, if any;
  - most recent learning session, if no active learning session exists;
  - due review count plus at least the highest available `forget_risk` signal among due reviews.
3. Build `today_learning_tasks` from the current plan/knowledge-point ordering rather than introducing a new task table.
4. Compute `resume_available` from either:
  - an active learning session; or
  - a recently interrupted / previously started learning session that can still resolve to a valid `next_entry_point`.
5. Compute `next_entry_point`:
  - normal case: `learning_session` or `resume`;
  - high-risk case: `review`;
  - fallback case: first valid current-plan knowledge point.
6. Return only the contract fields the frontend needs to render top status, notices, and route choice.

### Resume Data Flow

1. Validate `user_id` and `plan_id`.
2. Look up the most recent relevant learning session for that user + plan.
3. If the session already has `summary_text` and a usable `next_entry_point`, return them directly.
4. If `summary_text` is absent, synthesize a deterministic fallback summary from current knowledge point, last known stage/module, and latest attempt/review facts already in the database.
5. If no resumable session exists, return a clean `resume_available=false` response shape instead of forcing the frontend to infer from a 500-like failure.

### High-Risk Resume Rule

- The docs require “普通打开默认进入当前学习；仅中断多日且复习高风险时优先进入复习”, but do not define the exact threshold.
- Recommended M6 heuristic:
  - inactivity threshold: latest learning activity older than 72 hours;
  - risk threshold: at least one due review item currently evaluates to `forget_risk = "high"`.
- Implementation effect:
  - if both conditions are true, dashboard returns a review-first `next_entry_point`;
  - otherwise dashboard keeps learning/resume as the primary entry and exposes review count/notice only.
- This rule is intentionally easy to test and easy to narrow or widen later through docs/spec updates.

### Desktop Persistence and Bootstrap

- Persist a minimal local record such as:
  - `userId`
  - `activePlanId`
  - optionally `lastKnownRoute` for UX polish, but route choice must still be overridden by dashboard semantics.
- On app boot:
  - if bootstrap context is missing, keep current onboarding-first behavior;
  - if bootstrap context exists, fetch dashboard before choosing the initial route;
  - fetch user profile for settings/editable preference hydration;
  - fetch resume only when the user explicitly requests “恢复上次” or when dashboard indicates resume is the best primary learning entry.

### Settings Strategy

- `SettingsPage` should be refactored from static cards into seven categories that match the docs exactly:
  - appearance
  - model settings
  - learning preference
  - review
  - notification settings
  - records/privacy
  - about/diagnostics
- M6 should separate these into two classes:
  - persisted editable sections:
    - display/profile text fields;
    - learning style / teaching preference / encouragement preference;
    - background/profession;
    - `preferred_time_slots`;
    - `reminder_preference`.
  - read-only or non-persisted diagnostic sections under current contract:
    - model-setting explanation cards;
    - review-priority policy description;
    - records/privacy boundary summary;
    - diagnostics such as API base URL, health status, and runtime capability.
- This avoids inventing undocumented backend fields while still delivering the seven-category Settings page required by M6.

### Frontend Refactor

- Extend `src/types.ts` with dedicated DTOs for:
  - dashboard response;
  - resume response;
  - editable preference payloads;
  - any typed `next_entry_point` union needed for route selection.
- Extend `src/api.ts` with:
  - `fetchDashboard`
  - `fetchResumeContext`
  - `fetchUserProfile`
  - `updateUserPreferences`
- Refactor `App.tsx` to:
  - persist and hydrate bootstrap context;
  - load dashboard before setting the initial route for returning users;
  - store dashboard state separately from the created-plan onboarding response;
  - surface review notice / resume affordance in the shell;
  - keep onboarding, learning, review, notes, and settings flows coherent after the new bootstrap path.
- Refactor `SettingsPage.tsx` and related desktop content/types so the tab model matches the documented seven categories instead of the current six placeholder groups.

### Compatibility / Rollback

- M2/M3/M4/M5 APIs must remain compatible.
- No schema migration is preferred for M6; rollback should therefore mostly be route and frontend wiring removal rather than data rollback.
- If local bootstrap persistence causes startup regressions, rollback can:
  - ignore the stored bootstrap key;
  - fall back to the current onboarding-first behavior;
  - leave backend dashboard/resume routes in place without breaking existing flows.

### Doc Backfill Expectation

- If the implementation ships with the recommended 72-hour + `forget_risk="high"` heuristic, M6 should backfill that exact rule into the closest product/QA/spec docs so the acceptance boundary stops being implicit.
