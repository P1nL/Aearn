# Quality Guidelines

> Code quality standards for frontend development.

---

## Overview

Frontend work targets the Tauri desktop app under `aearn/apps/desktop/`. The current quality gate is the package build command, which runs `tsc && vite build`; the root workspace exposes it as `pnpm desktop:check` from `aearn/`.

Every UI task must be checked against `docs/product/frontend-interaction-spec.md` and the acceptance plan.

---

## Forbidden Patterns

- Do not implement product UI in `docs/design/`; that directory is reference/prototype material.
- Do not expose `Attempt(run)`, `Attempt(submit)`, `review_submit`, or FSRS internals as ordinary user labels.
- Do not paste spec/runbook wording into the UI. Settings and diagnostics copy must use product-facing language such as "当前状态" and "复习节奏", not implementation terms like `Source of truth`, `MVP`, `ReviewState`, `due_at`, or "fixed backend rules".
- Do not calculate final score, result, `fsrs_rating`, `due_at`, or review scheduling in the frontend.
- Do not show unsupported Java/C++ sandbox capabilities as runnable.
- Do not add new UI libraries, routers, or state managers without task scope and verification.
- Do not rely on console output as the only user feedback.

---

## Required Patterns

- Run desktop commands from `aearn/` or `aearn/apps/desktop/`, not from the repository root.
- Keep loading, error, disabled, retry, and stale states visible for long operations.
- Keep generated exercise cards in the conversation flow, not as a separate fixed workbench unless the product spec changes.
- Use backend responses as source of truth for run/submit results.
- Preserve responsive behavior for narrow windows.
- Keep `src-tauri/icons/icon.ico` present for Windows Tauri checks.
- Runtime sidebar, conversation, and draft panels must render real user/plan/session data or explicit empty states. Do not use prototype fallback lesson titles, canned chat messages, or fake draft modules in `aearn/apps/desktop/src/`.

---

## Testing Requirements

- Run `pnpm desktop:check` from `aearn/` after desktop code changes.
- Run `pnpm --dir apps/desktop build` from `aearn/` when only the desktop package is in scope.
- For Tauri shell changes, run `cargo check` from `aearn/apps/desktop/src-tauri` when practical.
- For visible UI changes, open the local Vite or Tauri target and verify loading/error/responsive behavior.
- For API-connected UI, cover happy path, API error, offline, retry, stale result, and disabled unsupported runtime states.

---

## Code Review Checklist

- The component names and page flow match `frontend-interaction-spec.md`.
- The initial runtime conversation is empty until real user/session events exist; no demo `ConversationMessage` arrays or placeholder Agent bubbles are injected.
- Sidebar learning and note entries come from `CreatedPlanResponse.knowledge_points` or a visible empty state, not fixed DOM/Python example titles.
- UI labels avoid backend-internal Attempt and FSRS implementation terms.
- Settings page copy preserves the documented category boundary while staying user-facing rather than spec-facing.
- Async operations have user-visible state and do not allow duplicate writes while pending.
- Old run output cannot masquerade as current output after code changes.
- API errors branch on stable `error.code`, not free-form messages.
- Build/type-check commands were run from the correct workspace.

## Scenario: M2 Desktop Onboarding Flow

### 1. Scope / Trigger

- Trigger: implementing or changing the M2 desktop onboarding flow.
- Scope: `aearn/apps/desktop/src/App.tsx`, `api.ts`, `types.ts`, and `styles.css`.

### 2. Signatures

- `fetchLanguageCourses()` loads `GET /api/language-courses`.
- `createUser(displayName)` calls `POST /api/users`.
- `generatePlanDraft(input)` calls `POST /api/plans/generate`.
- `confirmPlan(userId, planDraft)` calls `POST /api/plans`.

### 3. Contracts

- The frontend may own onboarding form state, loading/error/disabled state, and local draft preview state.
- The backend remains source of truth for user IDs, plan IDs, persisted modules, knowledge points, and review initialization.
- Draft preview must show runtime capability metadata, source attribution, and non-skippable core modules.
- Workspace after confirmation is only a route summary entry in M2; it must not show generated exercise cards, run/submit actions, Attempt types, score, FSRS rating, or due scheduling.
- Java/C++ courses must display `compiled_sandbox_later` as unsupported/postponed execution capability.

### 4. Validation & Error Matrix

- API offline -> visible top status and generation disabled.
- Missing goal/material input -> disabled generate button with visible reason.
- API error envelope -> show stable `error.code` and `error.message`.
- Unsupported runtime -> show a capability boundary notice, not a runnable claim.

### 5. Good/Base/Bad Cases

- Good: select JavaScript, generate draft, inspect source attribution and core module lock, confirm, and see workspace route panel.
- Base: select Java or C++ and see the compile sandbox later notice.
- Bad: exposing `Attempt(run)` / `Attempt(submit)` labels, showing a Java/C++ run button, or locally marking review scheduling as complete.

### 6. Tests Required

- Run `pnpm --dir .\aearn desktop:check`.
- Browser smoke: open `http://127.0.0.1:1420`, verify API online, generate a JS draft, confirm it, and see workspace summary.
- Browser console should have no current errors after the latest reload and flow.

### 7. Wrong vs Correct

#### Wrong

```tsx
<button>Run Java sandbox</button>
```

This implies Java execution exists in M2.

#### Correct

```tsx
<div>Java/C++ 第一版只展示静态阅读和补全边界，不提供完整编译运行沙箱。</div>
```

M2 keeps course visibility separate from real runtime availability.

## Scenario: M3 Generated Exercise Workbench

### 1. Scope / Trigger

- Trigger: implementing or changing the in-conversation generated exercise workbench, run action bar, stale/error/retry UX, or explanation-assist panels.
- Scope: `aearn/apps/desktop/src/App.tsx`, `api.ts`, `types.ts`, and `styles.css`.

### 2. Signatures

- `startLearningSession({ userId, planId, knowledgePointId })`
- `runLearningExercise({ sessionId, exerciseId, code, filledBlanks, runtimeProfileId, runMode })`
- `requestLearningHint({ sessionId, exerciseId, attemptId, currentCode, blankId, hintLevel })`
- `explainLearningError({ sessionId, attemptId, errorMessage, stderr, failedTests, currentCode })`
- `checkLearningExplanation({ sessionId, attemptId, explanation, focus, round })`
- `submitLearningExercise({ sessionId, exerciseId, attemptId, code, filledBlanks, explanation, hintUsageCount, errorCount })`

### 3. Contracts

- The frontend may own editor text, blank inputs, stale flags, loading/error state, explanation draft text, selected hint target, and local retry intent.
- The backend remains source of truth for `runtime_status`, `test_results`, `hint_usage_count`, `error_cause`, `explanation_check_result`, `code_completion_result`, and `ReviewState`.
- The generated exercise card must expose natural actions (`运行预览`, `运行可见测试`, `获取提示`, `解释错误`, `检查解释`, `提交结果`) without exposing `Attempt(run)` / `Attempt(submit)` labels.
- `stale` must be visible as soon as code or blanks change after a run; old results may remain readable but cannot masquerade as current and cannot directly submit.
- `preview` and `visible_tests` are separate user actions. If submit depends on the visible-test Attempt, the UI must explain why a pure preview result is not enough.
- Explanation-check feedback and hint history must be rendered from API responses, not rederived from local heuristics.

### 4. Validation & Error Matrix

- API offline -> visible top status and disabled generation/run actions where appropriate.
- API error envelope -> show stable `error.code` / `error.message` plus retry affordance when `recoverable=true`.
- `compiled_sandbox_later` -> run-related actions disabled or boundary notice visible.
- Code changed after run -> stale banner visible and submit blocked until rerun.
- No run Attempt yet -> submit, hint, explain-error, and explanation-check actions show an inline prerequisite notice.

### 5. Good/Base/Bad Cases

- Good: complete onboarding, start a JS learning session, run visible tests, request a hint, check explanation, submit, and see preview/runtime/submit panels update from backend responses.
- Base: use preview first, then see submit still require a visible-test run before scoring.
- Bad: computing score or next action locally, hiding stale state after code changes, or using console output as the only error signal.

### 6. Tests Required

- Run `pnpm --dir .\aearn desktop:check`.
- Browser smoke: open `http://127.0.0.1:1420`, create a JS plan, enter the workbench, run visible tests, check explanation, and submit once.
- Verify hint/explain/check buttons enable only after a run Attempt exists and that stale UI appears after editing code post-run.

### 7. Wrong vs Correct

#### Wrong

```tsx
<button disabled={lastRun === null}>提交结果</button>
```

This ignores stale state, preview-only runs, and unsupported runtime boundaries.

#### Correct

```tsx
const submitDisabled =
  runtimeUnsupported ||
  lastRun === null ||
  lastRunMode !== "visible_tests" ||
  isStale ||
  lastRun.runtime_status === "unsupported";
```

Submit follows the actual M3 contract instead of a single optimistic condition.

## Scenario: Active Learning Composer SSE Assistant Bubble

### 1. Scope / Trigger

- Trigger: implementing or changing the bottom composer behavior for active learning workspace messages.
- Scope: `aearn/apps/desktop/src/App.tsx`, `api.ts`, `appTypes.ts`, `components/ThreadMessages.tsx`, `hooks/useSSE.ts`, the app store message mutators, and composer CSS.

### 2. Signatures

- Frontend endpoint helper: `buildLearningMessageSSEUrl(sessionId)`
- POST body: `{ role: "user", content: string, client_message_id: string }`
- Headers from SSE hook: `Accept: text/event-stream`, `Content-Type: application/json`, and fresh `X-Request-Id`
- Stream events consumed: `agent_message`, `done`, and `error`
- Message UI state: `ConversationMessage.status?: "streaming" | "error" | "done"` and optional `statusText`

### 3. Contracts

- The composer calls `/api/learning-sessions/{session_id}/messages` only when `visibleRoute === "home"` and an active learning session is loaded.
- Review route composer behavior remains local unless a separate review-chat task expands scope.
- On send, append the learner message immediately, append one empty assistant placeholder, then update that same assistant message as `agent_message.content` grows.
- Duplicate sends are disabled while a stream is active.
- If no active session exists, show disabled guidance and do not call the backend.
- A stream that closes without `done` or `error` must become a visible recoverable error state.
- The frontend must not derive scoring, final exercise result, review scheduling, or hidden-test facts from conversation messages.

### 4. Validation & Error Matrix

- Empty composer input -> send button disabled and no request.
- Active home session missing -> composer disabled with guidance and no request.
- Stream in progress -> textarea/send disabled to prevent duplicate writes.
- `agent_message` event -> update the existing assistant bubble, not append a new assistant bubble per delta.
- `done` event -> mark the assistant bubble `done` and clear busy state.
- `error` event or incomplete close -> mark the assistant bubble `error`, show stable error copy, and allow retry.
- API offline or backend envelope error -> show visible state; do not rely on console output alone.

### 5. Good/Base/Bad Cases

- Good: learner asks a follow-up during an active session, sees one assistant bubble fill incrementally, then the streaming cursor disappears on `done`.
- Base: learner opens home without an active session and sees guidance to start a knowledge point before asking the Agent.
- Bad: using `EventSource` for this POST body, appending one message per delta, reusing a fixed `X-Request-Id`, or streaming review/global chatbot messages in this task.

### 6. Tests Required

- Run `pnpm --dir .\aearn desktop:check` after frontend changes.
- Browser smoke the active learning path only when current backend and Vite/Tauri processes are serving this checkout.
- Verify home composer sends `role=user`, `content`, and a fresh `client_message_id` only when an active session exists.
- Verify duplicate send prevention while streaming.
- Verify `agent_message` deltas update one assistant bubble and `done` clears the streaming state.
- Verify stream error or incomplete close renders an error bubble and allows retry.

### 7. Wrong vs Correct

#### Wrong

```tsx
events.forEach((event) => addHomeMessage(createMessage("agent", event.data.delta)));
```

This creates one bubble per chunk and makes incremental rendering unreadable.

#### Correct

```tsx
updateHomeMessage(assistantMessageId, {
  text: event.data.content || event.data.delta,
  status: "streaming",
});
```

The stream owns one assistant bubble that changes status as the request moves from connecting to streaming, done, or error.

## Scenario: Desktop App Shell vs Page and Feature Boundaries

### 1. Scope / Trigger

- Trigger: refactoring or extending the desktop app after `App.tsx` has grown to hold multiple route screens, M3 workbench panels, and shared shell widgets at once.
- Scope: `aearn/apps/desktop/src/App.tsx`, `pages/`, `features/`, `components/`, `lib/`, and app-local UI types.

### 2. Signatures

- `App.tsx` remains the runtime shell entry.
- Route screens live in `pages/`.
- M3 workbench subtree lives in `features/learning/`.
- Shared shell/presentational widgets live in `components/`.
- Pure labels/content/helpers live in `lib/`.

### 3. Contracts

- `App.tsx` owns bootstrap, global route selection, drawers, and cross-page shared domain state.
- Page-local interaction state should move to the owning page once a screen has meaningful local workflow state, for example onboarding draft editing or learning workbench run/submit state.
- M3 result panes such as runtime feedback, hint history, error explanation, explanation check, and submit summary must not stay as inline component definitions inside `App.tsx` once they become reusable workbench subpanels.
- Shared helpers extracted from `App.tsx` must stay pure; they must not hide React state or mutate backend-owned facts.
- This structure refactor does not imply a router/store/library migration. Keep the existing runtime model unless task scope explicitly widens.

### 4. Validation & Error Matrix

- `App.tsx` still contains page/workbench component definitions after the refactor -> task incomplete.
- Page-local state remains trapped in `App.tsx` only because props were inconvenient -> ownership boundary regression.
- New shared helper duplicates an existing constant/label function -> code reuse failure.
- Refactor changes run/hint/explain/submit behavior -> behavior regression requiring fix before commit.

### 5. Good/Base/Bad Cases

- Good: `App.tsx` orchestrates the shell while `OnboardingPage`, `LearningWorkspacePage`, and `features/learning/*` own their local UI logic.
- Base: keep global CSS and local state routing, but still move pages and M3 panels into separate files.
- Bad: moving JSX into files while keeping all meaningful state and workflow ownership in one giant `App.tsx`, or using the refactor as an excuse to slip in router/store rewrites.

### 6. Tests Required

- Run `pnpm --dir .\aearn desktop:check`.
- For changes touching the M3 workbench wiring, browser smoke the onboarding -> learning session -> run visible tests -> check explanation -> submit path.
- Confirm `App.tsx` no longer defines page-level or workbench result-panel functions by direct file inspection.

### 7. Wrong vs Correct

#### Wrong

```tsx
function App() {
  const [editorCode, setEditorCode] = useState("");
  const [goalText, setGoalText] = useState("");
  return (
    <>
      <Onboarding JSX />
      <Learning JSX />
      <RuntimeFeedback JSX />
    </>
  );
}
```

This keeps the shell as the owner of unrelated page-local workflows and guarantees the file will bloat again.

#### Correct

```tsx
function App() {
  return <LearningWorkspacePage sessionState={sessionState} onOpenNoteDrawer={handleOpenNoteDrawer} />;
}
```

Keep the shell responsible for orchestration and let the page own the workbench workflow behind its own file boundary.

## Scenario: M4 Desktop ReviewPage Backend-Driven Review Loop

### 1. Scope / Trigger

- Trigger: implementing or changing the desktop review queue, review session start, review exercise submit, or review result rendering.
- Scope: `aearn/apps/desktop/src/pages/ReviewPage.tsx`, `api.ts`, `types.ts`, and the shell props passed from `App.tsx`.

### 2. Signatures

- `fetchTodayReviews(userId)` calls `GET /api/reviews/today?user_id=...`.
- `startReviewSession({ userId, knowledgePointId })` calls `POST /api/reviews/start`.
- `submitReviewExerciseResult({ sessionId, exerciseId, code, filledBlanks, explanation })` calls `POST /api/reviews/{session_id}/exercise-result`.
- `ReviewPage` receives `isActive`, `user`, `messages`, `lastSubmit`, and `lastRun`; it owns review-page queue/session/editor/result state.

### 3. Contracts

- Frontend may own queue loading/error state, selected review session, editor text, blank inputs, explanation draft, and submit button state.
- Backend remains source of truth for due queue membership, `ReviewState`, final result, `fsrs_rating`, `due_at`, `forget_risk`, and next action.
- ReviewPage must not compute final score, `fsrs_rating`, `due_at`, `forget_risk`, or review counters locally.
- API guards must validate `ReviewState.review_count` / `lapse_count` and still accept compatibility fields `reps` / `lapses`.
- ReviewPage should not fetch due reviews before a user exists or while the page is inactive.
- UI labels should use natural product language such as "开始复习" and "提交复习结果", not `review_submit` or internal Attempt labels.

### 4. Validation & Error Matrix

- No user -> visible prerequisite state and no review API call.
- Due queue empty -> visible empty state.
- API error envelope -> display stable `error.code` and `error.message`.
- Start review failure with `REVIEW_NOT_DUE` -> show recoverable inline error.
- Submit pending -> disable duplicate submit until response returns.
- Submit done -> render backend `fsrs_rating`, `due_at`, and `forget_risk` from the response.

### 5. Good/Base/Bad Cases

- Good: open ReviewPage with an existing user, load due items, start one item, submit code and blanks, then render backend scheduling metrics.
- Base: no due items returns a calm empty state without local fake cards.
- Bad: deriving `Easy` from local blank values, calculating a due date in TypeScript, or showing `Attempt(review_submit)` as a user-facing concept.

### 6. Tests Required

- Run `pnpm --dir .\aearn desktop:check` after changing ReviewPage or review API types.
- Backend M4 tests must pass because the ReviewPage depends on `/api/reviews/*` response shapes.
- For browser smoke, create or reuse a user with due review state, open review route, start review, submit once, and verify visible `due_at` / `forget_risk`.

### 7. Wrong vs Correct

#### Wrong

```tsx
const dueAt = addDays(new Date(), rating === "Easy" ? 7 : 3);
```

This duplicates backend scheduling and can drift from persisted `ReviewState`.

#### Correct

```tsx
setReviewResult(await submitReviewExerciseResult(payload));
```

Render `reviewResult.due_at`, `reviewResult.forget_risk`, and `reviewResult.ReviewState` exactly as returned by the API.

## Scenario: Prototype-Free Dialogue Runtime

### 1. Scope / Trigger

- Trigger: changing desktop shell, sidebar navigation, onboarding draft panels, or learning conversation rendering.
- Scope: `aearn/apps/desktop/src/App.tsx`, `components/SidebarNav.tsx`, `components/SideContext.tsx`, `features/onboarding/PlanDraftPanel.tsx`, `pages/OnboardingPage.tsx`, `pages/LearningWorkspacePage.tsx`, `lib/appContent.ts`, and `lib/learningHelpers.ts`.

### 2. Signatures

- Sidebar source: `CreatedPlanResponse.knowledge_points`.
- Route source: `CreatedPlanResponse.modules` plus matching first `knowledge_point`.
- Composer source: active `LearningSessionResponse.session_id`.
- SSE endpoint: `POST /api/learning-sessions/{session_id}/messages`.

### 3. Contracts

- No plan: sidebar shows explicit empty states and no fixed lesson buttons.
- No plan draft: draft panel shows an empty state and no fake module sequence.
- No active learning session: home composer is disabled and does not call the backend.
- Active learning session: composer can send `{ role: "user", content, client_message_id }` to the session SSE endpoint.
- Streaming assistant text updates one existing assistant bubble; `delta` chunks append, while full `content` replaces the bubble text.

### 4. Validation & Error Matrix

- Empty composer input -> send disabled.
- Missing active session -> guidance visible and no network request.
- Stream in progress -> duplicate sends disabled.
- `agent_message.delta` only -> append to current assistant bubble.
- `agent_message.content` present -> replace assistant bubble with authoritative content.
- No generated plan -> no hard-coded DOM/Python/C++ fallback route cards.

### 5. Good/Base/Bad Cases

- Good: cold start shows no message article in the conversation area and sidebar says generated route items appear after onboarding.
- Base: returning user with a plan sees knowledge point titles from the backend in learning and notes navigation.
- Bad: adding `HOME_BASE_MESSAGES`, fallback draft modules, or hard-coded lesson buttons to make the UI look populated before backend data exists.

### 6. Tests Required

- Run `pnpm --dir .\aearn desktop:check`.
- Browser smoke cold start with `localStorage["aearn.bootstrap"]` cleared: assert `.conversation` has `overflow-y: auto`, no `.message` article, and sidebar empty-state copy.
- Browser smoke returning-user or generated-plan state: assert sidebar entries match backend knowledge point titles.

### 7. Wrong vs Correct

#### Wrong

```tsx
const homeMessages = [...HOME_BASE_MESSAGES, ...app.homeConversation];
```

This makes the runtime look populated even when no real session message exists.

#### Correct

```tsx
const homeMessages = app.homeConversation;
```

Only user actions and backend/session events create runtime conversation messages.

## Scenario: M6 Release Smoke for Bootstrap, Dashboard, and Resume

### 1. Scope / Trigger

- Trigger: release validation, changes to app bootstrap, `localStorage` persistence, dashboard routing, resume routing, or SettingsPage boundary behavior.
- Scope: `aearn/apps/desktop/src/App.tsx`, onboarding confirmation flow, dashboard/resume API wiring, and settings-route smoke checks.

### 2. Signatures

- Bootstrap storage key: `localStorage["aearn.bootstrap"]`
- Bootstrap payload: `{ userId: string; planId: string | null }`
- Cold-start API bootstrap:
  - `GET /health`
  - `GET /api/language-courses`
- Returning-user bootstrap:
  - `GET /api/users/{user_id}`
  - `GET /api/plans/{plan_id}`
  - `GET /api/dashboard?user_id=...`
  - `GET /api/learning-sessions/resume?user_id=...&plan_id=...`
  - `POST /api/learning-sessions/start`

### 3. Contracts

- Cold start with no bootstrap key must enter onboarding instead of jumping into demo learning/review/notes routes.
- Confirming onboarding must write `userId` and `planId` to `localStorage["aearn.bootstrap"]`.
- Returning-user reload must fetch real user/plan/dashboard/resume data before deciding the landing route.
- `dashboard` / `resume` remain the source of truth for `home` vs `review` vs resumable learning decisions; the frontend must not hard-code a review-first route on every reload.
- Settings smoke must verify all seven categories are visible and that no visible control claims to edit `Attempt`, `FSRS`, score rules, or raw `due_at`.

### 4. Validation & Error Matrix

- No bootstrap key -> onboarding route visible.
- Invalid bootstrap user/plan -> frontend clears bootstrap and falls back to onboarding.
- Bootstrap exists but dashboard/resume requests are skipped -> release smoke fails.
- Settings page shows rule-edit controls for score / Attempt / FSRS / `due_at` -> release smoke fails.

### 5. Good/Base/Bad Cases

- Good: cold reload enters onboarding, confirm plan writes bootstrap, second reload requests `users` + `plans` + `dashboard` + `resume`, then restores the learning route.
- Base: returning user with no resumable context still loads dashboard and lands on the correct non-review route.
- Bad: passing `desktop:check` while the app still opens a stale demo route, or calling only `/health` + `/api/language-courses` on a supposed returning-user reload.

### 6. Tests Required

- Run `pnpm --dir .\aearn desktop:check`.
- Browser smoke cold start with `localStorage["aearn.bootstrap"]` cleared.
- Browser smoke onboarding confirm -> bootstrap write -> reload -> request-chain verification.
- Browser smoke SettingsPage category visibility and forbidden-rule-boundary check.

### 7. Wrong vs Correct

#### Wrong

```tsx
const stored = readBootstrapContext();
if (stored.userId) {
  setActiveRoute("home");
}
```

This trusts local storage alone and skips the real dashboard/resume decision path.

#### Correct

```tsx
const loadedUser = await fetchUserProfile(stored.userId, signal);
const [plan, dashboardResponse] = await Promise.all([
  fetchPlanDetail(stored.planId, signal),
  fetchDashboard(stored.userId, signal),
]);
```

Reload decisions come from validated backend state, not from a local optimistic shortcut.
