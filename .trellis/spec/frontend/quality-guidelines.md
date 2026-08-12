# Quality Guidelines

> Code quality standards for frontend development.

---

## Overview

Frontend work targets the current Tutor UI under `aearn/apps/desktop/`. The
current frontend completion gate is browser validation against the local web
target at `http://127.0.0.1:1420`; `pnpm --dir .\aearn desktop:check` is not a
default frontend validation step and must not be run unless the user explicitly
requests a Desktop build/typecheck. Current UI behavior is defined by
`docs/product/frontend-interaction-spec.md`, `docs/product/user-flows.md`, the
current API contract, and `aearn/apps/desktop/src/`.

> **Historical-scenario note (2026-07-29):** The older M2--M6, onboarding,
> learning-workbench, review, notes and Graph/SSE scenarios below are retained
> as historical implementation evidence. They do not authorize restoring old
> routes, bootstrap calls, state stores, components, or API types. The current
> top-level route set is `loading | welcome | cutover | tutor`.

---

## Forbidden Patterns

- Do not implement active product UI in `docs/design/` or reintroduce old
  Onboarding/Learning/Review/Notes pages, Graph-specific SSE parsers, dashboard
  or resume bootstrap calls.
- Do not let local storage, a stale `planId`, a client route or a checkbox turn
  `cutover` into `tutor`; only the server `verified` decision authorizes the
  workspace.
- Do not show provider keys/errors, provider-native reasoning, prompt/trace/checkpoint data,
  hidden tests, reference answers, complete learner code, container details,
  commands or paths.
- Do not calculate run terminal state, Skill/effect permission, plan rollback,
  memory mutation, scheduler policy or cutover deletion scope in the frontend.
- Do not turn background activity/inbox into a chat message or desktop
  notification, or expose a runner/subprocess action.
- Do not add UI libraries, routers, or state managers without task scope and
  verification.

---

## Required Patterns

- Serve the current checkout at `http://127.0.0.1:1420` and validate the
  changed flow in a real browser. Do not run `desktop:check` as a routine
  frontend gate unless the user explicitly asks for it.
- Bootstrap local `userId`, normalize `planId=null`, fetch user then server
  cutover decision, and route only to welcome/cutover/tutor from that decision.
- Keep loading, API error, disabled, retry and SSE terminal/incomplete states
  visible using stable public error codes.
- Parse Tutor SSE as unknown at the boundary; only a validated non-negative
  durable event ID advances `Last-Event-ID`. An id-less error remains terminal
  feedback and never changes the cursor.
- Render real Tutor conversation/activity/inbox/memory/plan/preference data or
  explicit empty states; keep narrow-window primary actions and Composer
  reachable.
- Treat the backend as authority for run status, terminal result, user scope,
  preference state and all mutations; generate only bounded client action IDs.

---

## Testing Requirements

- Validate frontend changes only through the local browser target unless the
  user explicitly requests an additional Desktop build/typecheck.
- For visible behavior, smoke the changed route and interaction at
  `http://127.0.0.1:1420`, including page identity, meaningful DOM, no framework
  overlay, console health, screenshot evidence, one real interaction, and a
  narrow viewport when the layout is responsive.
- Verify a stale bootstrap never produces legacy dashboard/resume/plan/session
  requests, and verified flow clears `planId` before mounting Tutor.
- Do not substitute a build or static search for rendered browser evidence;
  record any unavailable local process or untestable state explicitly.

---

## Code Review Checklist

- `App.tsx`, `useAppStore`, API validators/types, pages and hooks agree on the
  four current routes and server-authoritative cutover state.
- Tutor workspace sees only safe public projections; no internal fields are
  passed through `unknown` parsing or rendered as fallback text.
- Stream retry preserves the last valid numeric cursor and does not invent run
  completion locally.
- Activity/inbox, memory and plan controls use public IDs and idempotency action
  IDs without crossing user scope.
- The changed layout remains usable at narrow widths and does not rely on
  removed legacy components/state stores.

---

## Scenario: Current Frontend Browser-Only Validation

### 1. Scope / Trigger

- Trigger: any user-visible React/CSS/frontend flow change in the current checkout.
- Scope: `aearn/apps/desktop/src/**` and the local web target served on port `1420`.

### 2. Signatures

- Target URL: `http://127.0.0.1:1420`.
- Required evidence: page URL/title, meaningful DOM, no framework overlay,
  browser console errors/warnings, screenshot, one changed-flow interaction,
  and responsive overflow checks when applicable.
- `pnpm --dir .\aearn desktop:check` is not part of the default frontend gate.

### 3. Contracts

- A frontend change is complete only after the changed behavior is rendered and
  observed in the browser against the current local API/fixture state.
- Use the Browser plugin first when available; keep validation read-only except
  for the exact local interaction needed to prove the flow.
- Do not create test users, planning sessions, tracks, or other persisted data
  merely to obtain a screenshot unless the task explicitly authorizes it.
- Run a Desktop build/typecheck only when the user explicitly requests it.

### 4. Validation & Error Matrix

- Page is blank or shows a framework overlay -> frontend validation fails.
- Relevant console error/warning -> explain and fix it before claiming success.
- Changed control cannot be exercised -> validation remains incomplete.
- Horizontal overflow at a required responsive viewport -> validation fails.
- Browser target or required fixture unavailable -> report the exact blocker; do
  not replace the missing browser evidence with `desktop:check`.

### 5. Good/Base/Bad Cases

- Good: load the changed page, verify the removed/added controls in the DOM,
  exercise one safe interaction, capture desktop and narrow screenshots, and
  confirm no relevant console errors.
- Base: a non-responsive copy change uses one normal viewport plus DOM/console
  checks and one relevant interaction when available.
- Bad: run only `tsc && vite build` or inspect source strings and claim the UI
  works without opening the page.

### 6. Tests Required

- Open `http://127.0.0.1:1420` in the Browser plugin.
- Assert the intended page identity and changed visible state.
- Exercise at least one safe target-flow interaction and observe the next state.
- Check console health and horizontal overflow; add a narrow viewport for
  responsive work.
- Capture screenshot evidence outside the repository.

### 7. Wrong vs Correct

#### Wrong

```powershell
pnpm --dir .\aearn desktop:check
# No browser verification.
```

A successful build does not prove the rendered behavior or responsive layout.

#### Correct

```text
open http://127.0.0.1:1420
-> verify page identity and changed DOM
-> exercise the target interaction
-> check console and overflow
-> capture desktop and narrow screenshots
```

The current frontend gate is rendered web behavior, not a Desktop build.

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
- Java/Go/C# courses must display `managed_compiled_test` as local teaching-grade single-exercise capability; C++ and Rust must not appear as public course choices.
- Generated onboarding route cards render from `show_learning_route` tool args; the card exposes only `开始学习`, displays optional `time_budget` as user-facing rhythm copy, and disables historical cards by latest tool-call id.

### 4. Validation & Error Matrix

- API offline -> visible top status and generation disabled.
- Missing goal/material input -> disabled generate button with visible reason.
- API error envelope -> show stable `error.code` and `error.message`.
- Unsupported runtime -> show a capability boundary notice, not a runnable claim.

### 5. Good/Base/Bad Cases

- Good: select JavaScript, generate draft, inspect source attribution and core module lock, confirm, and see workspace route panel.
- Base: select Java and see the managed compiled teaching-grade notice; select C++ and see the compile sandbox later notice.
- Bad: exposing `Attempt(run)` / `Attempt(submit)` labels, showing a runnable C++ button, presenting Java as Maven/Gradle/project execution, or locally marking review scheduling as complete.

### 6. Tests Required

- Validate the changed rendered flow at `http://127.0.0.1:1420` in a real browser.
- Browser smoke: open `http://127.0.0.1:1420`, verify API online, generate a JS draft, confirm it, and see workspace summary.
- Browser smoke onboarding route revisions: generate one route card, send a time-budget-only revision, verify the old `开始学习` is disabled and the latest card remains startable.
- Browser console should have no current errors after the latest reload and flow.

### 7. Wrong vs Correct

#### Wrong

```tsx
<button>Run Java sandbox</button>
```

This implies Java execution exists in M2.

#### Correct

```tsx
<div>Java / Go / C# 只支持本机教学级单练习运行；C++ / Rust 当前不支持公开路线。</div>
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

- Validate the changed rendered flow at `http://127.0.0.1:1420` in a real browser.
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

## Scenario: Learning Documentation Panel and Concept Trigger

### 1. Scope / Trigger

- Trigger: implementing or changing the learning-page documentation panel, `documentation_reading` display flow, document-to-composer references, or concept-check trigger card.
- Scope: `LearningWorkspacePage.tsx`, `DocumentationPanel.tsx`, `DocSection.tsx`, `ConceptCheckTrigger.tsx`, `AssistantUIThread.tsx`, `SidebarNav.tsx`, `api.ts`, `types.ts`, and `styles.css`.

### 2. Signatures

- `fetchKnowledgePointDocumentation(userId, knowledgePointId, signal?)` calls `GET /api/learning-sessions/knowledge-points/{knowledge_point_id}/documentation?user_id=...`.
- `triggerLearningConceptCheck({ sessionId, userId })` calls `POST /api/learning-sessions/{session_id}/trigger-concept-check`.
- `LearningStage` includes `documentation_reading`.
- `CreatedKnowledgePoint.review_state` is optional and contains backend-computed `due_at`, `is_due`, and `label`.
- Composer prefill must use the assistant-ui composer runtime, for example `useComposerRuntime().setText(...)`, not raw DOM value mutation.

### 3. Contracts

- A documentation-reading session shows the right-side document panel and an in-conversation concept-check trigger instead of auto-rendering the concept intro card.
- The documentation panel owns loading/error/retry/collapsed state locally and must not block normal conversation rendering on a documentation fetch error.
- Code-block and selected-text references prefill the composer with an editable quote template and must not auto-send the message.
- The concept-check trigger is disabled until documentation is loaded and while the trigger request is pending.
- Sidebar review entries are clickable only when `review_state.is_due === true`; future or unknown review states render as disabled preview rows.
- Exercise resume cards are injected only before real conversation messages exist, so run/submit feedback remains below the exercise card.

### 4. Validation & Error Matrix

- Documentation loading -> visible panel skeleton and disabled concept trigger.
- Documentation error -> panel-level error and retry without clearing the active learning session.
- Trigger API error -> visible inline error on the trigger card; do not synthesize a concept tool call locally.
- Future `review_state.due_at` -> disabled sidebar item with backend label and no route change.
- Missing `review_state` on a reviewing/mastered point -> disabled sidebar item; never infer due status in TypeScript.
- Composer runtime unavailable -> reference action should fail visibly or no-op safely; do not write brittle DOM selectors as the primary path.

### 5. Good/Base/Bad Cases

- Good: entering a knowledge point opens documentation, references code into the composer, then clicking the trigger renders the backend `show_concept_intro` tool call.
- Good: collapsing the documentation panel frees layout space while keeping a clear reopen affordance.
- Base: documentation fetch fails; the learner can still ask in the normal composer and retry the panel.
- Bad: `document.querySelector("textarea").value = ...`, local due-date computation, or an enabled future review item that navigates to an empty review queue.

### 6. Tests Required

- Validate the changed rendered flow at `http://127.0.0.1:1420` in a real browser.
- Browser smoke the learning page at the current local target when practical: document panel visible, disabled future review item, reference prefill, trigger concept check, collapse/reopen.
- Backend M3 tests must pass for `LearningStage` and trigger payload shape; M2/M4 tests must pass for plan-detail review state and review not-due behavior.

### 7. Wrong vs Correct

#### Wrong

```tsx
textarea.value = referenceText;
knowledgePoint.status === "reviewing" && onRouteChange("review");
```

This bypasses assistant-ui state and makes future review items look startable.

#### Correct

```tsx
composer.setText(referenceText);
if (knowledgePoint.review_state?.is_due) onRouteChange("review");
```

Composer state stays controlled by assistant-ui and review navigation follows the backend-computed due flag.

## Scenario: Active Learning Composer SSE Assistant Bubble

### 1. Scope / Trigger

- Trigger: implementing or changing the bottom composer behavior for active learning workspace messages.
- Scope: `aearn/apps/desktop/src/App.tsx`, `api.ts`, `appTypes.ts`, `components/AssistantUIThread.tsx`, `hooks/useSSE.ts`, the app store message mutators, and composer CSS.

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
- The frontend must not render "导师判断", provider-native chain-of-thought/reasoning, or inferred hidden thinking; do not regex-split assistant text or parse prompt-policy markers from normal content. A separately typed, server-persisted `public_thinking_steps[]` field is allowed only as an explicitly learner-visible public explanation and must never be relabeled as hidden/internal reasoning.
- Public frontend types and render paths must ignore/drop `internal_review`; that field is backend-private and must never appear in the UI or app store.

### 4. Validation & Error Matrix

- Empty composer input -> send button disabled and no request.
- Active home session missing -> composer disabled with guidance and no request.
- Stream in progress -> textarea/send disabled to prevent duplicate writes.
- `agent_message` event -> update the existing assistant bubble, not append a new assistant bubble per delta.
- `done` event -> mark the assistant bubble `done` and clear busy state.
- `error` event or incomplete close -> mark the assistant bubble `error`, show stable error copy, and allow retry.
- Error copy must branch on stable `error.code`: `MODEL_UNAVAILABLE` explains model service/config unavailability, `STREAM_INCOMPLETE` explains a stream that ended without `done` or `error`, and synthetic stream errors explain connection/SSE availability instead of using one generic "answer incomplete" message.
- API offline or backend envelope error -> show visible state; do not rely on console output alone.

### 5. Good/Base/Bad Cases

- Good: learner asks a follow-up during an active session, sees one assistant bubble fill incrementally, then the streaming cursor disappears on `done`; no separate diagnostic or thinking panel appears.
- Base: learner opens home without an active session and sees guidance to start a knowledge point before asking the Agent.
- Bad: using `EventSource` for this POST body, appending one message per delta, reusing a fixed `X-Request-Id`, streaming review/global chatbot messages in this task, displaying backend-private `internal_review`, or trying to detect thoughts by matching `_policy`, JSON keys, or prompt-like text in the assistant content.

### 6. Tests Required

- Validate the changed rendered flow at `http://127.0.0.1:1420` in a real browser.
- Browser smoke the active learning path only when current backend and Vite/Tauri processes are serving this checkout.
- Verify home composer sends `role=user`, `content`, and a fresh `client_message_id` only when an active session exists.
- Verify duplicate send prevention while streaming.
- Verify `agent_message` deltas update one assistant bubble and `done` clears the streaming state.
- Verify stream error or incomplete close renders an error bubble and allows retry.
- Verify no frontend code renders a mentor-judgement/thinking container or attempts to extract one from message text.

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

The stream owns one assistant bubble that changes status as the request moves from connecting to streaming, done, or error; no separate thinking or diagnostic panel is inferred.

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

- Validate the changed rendered flow at `http://127.0.0.1:1420` in a real browser.
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
- `ReviewPage` receives `isActive`, `user`, and review conversation `messages`; it owns review-page queue/session/editor/result state.

### 3. Contracts

- Frontend may own queue loading/error state, selected review session, editor text, blank inputs, explanation draft, and submit button state.
- Backend remains source of truth for due queue membership, `ReviewState`, final result, `fsrs_rating`, `due_at`, `forget_risk`, and next action.
- ReviewPage must not compute final score, `fsrs_rating`, `due_at`, `forget_risk`, or review counters locally.
- ReviewPage must not read learning-page `lastSubmit` / `lastRun` for recap cards; those belong to the learning workspace and can make stale learning results look like review results.
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

- Validate the changed rendered flow at `http://127.0.0.1:1420` in a real browser.
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

- Validate the changed rendered flow at `http://127.0.0.1:1420` in a real browser.
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

- Validate the changed rendered flow at `http://127.0.0.1:1420` in a real browser.
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

## Scenario: Desktop Server-Authoritative Harness Cutover Bootstrap

### 1. Scope / Trigger

- Trigger: changing desktop bootstrap, `aearn.bootstrap`, Tutor cutover API
  types/validators, `HarnessCutoverPage`, or the special `cutover`/`tutor`
  routes.
- Scope: `src/{App,api,types,appTypes}.ts(x)`, `stores/useAppStore.ts`,
  `stores/useSettingsStore.ts`, `pages/HarnessCutoverPage.tsx`, and cutover
  CSS.
- This replaces neither the normal onboarding flow while rollout is inactive
  nor the server authority over destructive scope and runtime authorization.

### 2. Signatures

- Read: `fetchHarnessCutover(userId) -> GET /api/harness/cutover?user_id=...`.
- Confirm: `confirmHarnessCutover({ userId, cutoverVersion, summaryVersion,
  previewNonce, summaryHash, clientActionId })`.
- Bootstrap storage remains
  `localStorage["aearn.bootstrap"] = { userId, planId: string | null }`.
- App routes include `cutover` for a pending/blocked decision and `tutor` only
  for a verified decision.

### 3. Contracts

- After a local user identity is loaded, fetch the server cutover decision
  before reading a stored `planId` or calling plan, dashboard, resume, legacy
  learning, review, notes, or Tutor-conversation restoration APIs.
- An active `summary_ready` or blocked decision retains `userId`, writes
  `planId: null`, clears user-scoped legacy app/settings/notes state, and
  mounts only `HarnessCutoverPage`. It must not auto-confirm.
- An active `verified` decision writes `planId: null`, clears legacy state, and
  mounts a fresh `TutorWorkspacePage` with `initialConversationId=null`.
- The page displays only server-projected deletion/retention categories and
  stable errors. Confirmation requires a visible learner checkbox plus an
  explicit button; the browser never computes or sends deletion scope/counts.
- Preserve unrelated local UI storage. Clear the legacy bootstrap plan and
  recognized user-scoped stores only; never blanket-clear browser storage.
- UI error branches use stable API `error.code`, keep refresh/retry feedback
  visible, and block duplicate confirmation while a request is pending.

### 4. Validation & Error Matrix

- `rollout_inactive` -> retain the legacy bootstrap path; do not mount cutover
  or Tutor special routes.
- `summary_ready` -> show server summary; confirmation button is disabled until
  the learner checks the irreversible-action acknowledgement.
- `blocked_target_state` or `blocked_checkpoint_scope` -> show a blocking
  explanation and refresh affordance; expose no legacy navigation escape hatch.
- Confirmation stale/failure -> retain the blocking page and show stable error
  feedback; do not locally claim that data was cleared.
- Invalid cutover API payload -> visible API error; do not cast it into a route
  decision or restore a legacy plan.

### 5. Good / Base / Bad Cases

- Good: a returning legacy user calls health/catalog/user/cutover, clears stale
  `planId`, shows the exact summary, checks the acknowledgement, and only then
  enables the explicit confirm button.
- Good: a verified user opens an empty Tutor conversation rather than old
  dashboard, session, review, note, or plan state.
- Base: the rollout is inactive, so the existing dashboard/resume bootstrap
  remains unchanged.
- Bad: restoring dashboard/resume before cutover, using a client route to enter
  Tutor without the decision, treating a checkbox/reload as confirmation, or
  clearing all `localStorage` keys.

### 6. Tests Required

- Validate any type, store, page, or CSS change through the local web browser
  target; do not use a Desktop build as the default frontend gate.
- Render the cutover flow against a disposable mock API: verify page identity,
  nonblank summary, no framework overlay, clean console, preserved `userId` /
  cleared `planId`, no dashboard/resume request before the decision, and
  acknowledgement-controlled confirmation enablement.
- Check a narrow viewport for readable categories, full-width action controls,
  and no horizontal clipping. Do not use a real user, live provider, worker,
  executor, or enabled production flag for the smoke.

### 7. Wrong vs Correct

#### Wrong

```ts
const stored = readBootstrapContext();
await fetchDashboard(stored.userId);
setActiveRoute("tutor");
```

This restores or authorizes a runtime from local state before the server has
made the one-time cutover decision.

#### Correct

```ts
const cutover = await fetchHarnessCutover(loadedUser.id, signal);
if (cutover.rollout_active) {
  writeBootstrapContext({ userId: loadedUser.id, planId: null });
  clearUserScopedState({ keepUser: loadedUser, route: cutover.state === "verified" ? "tutor" : "cutover" });
  return;
}
```

The server decision is the first runtime-routing fact; legacy restoration is
only reachable through the inactive rollout branch.

## Scenario: Lesson Reader Web Validation

### 1. Scope / Trigger

Run this gate after any Lesson page, renderer, API parser, navigation, citation interaction, assignment state, or Lesson CSS change.

### 2. Signatures

```text
Frontend target: http://127.0.0.1:1420
API fixture: disposable verified user + stateful mock/fake author
Required viewports: normal desktop, 900px, 390px
```

### 3. Contracts

- Validate the rendered application in a real browser; static search or a Desktop build is not a substitute for this child.
- Learning Home continue enters the server-owned current knowledge key.
- Required state flow is `missing -> prepare -> preparing -> ready` plus `failed -> retry -> ready`.
- All ten registered block types, inline citations, source trust/version/section/time/URL/excerpt, start freeze, update proposal, and explicit migration must be observable.
- Gate controls must exactly match server `allowed_actions`; score/pass/unlock remain server projections, and static/unavailable tiers must hide disallowed execution actions.
- Use fixture/fake infrastructure only; do not call a real provider or mutate real learner data.

### 4. Validation & Error Matrix

| Observation | Gate result |
| --- | --- |
| Vite/framework overlay | fail |
| Related console error or warning | fail |
| Horizontal overflow at required viewport | fail |
| Unknown payload renders partial content | fail |
| Refresh silently replaces a started document | fail |
| Gate action exceeds server `allowed_actions`, static shows Run, or unavailable shows Run/Submit | fail |
| In-app browser screenshot capture alone times out | interactions/DOM/console remain valid; use standalone Playwright only for screenshot fallback and record the boundary |

### 5. Good / Base / Bad Cases

- Good: start freezes the current assignment; refresh displays impact while the old title remains; explicit activation switches versions.
- Base: source panel remains readable in one column at 390px and Gate shows only the actions returned by the fixture.
- Bad: claim frontend completion from `tsc`, source inspection, or a mocked component snapshot without a browser flow.
- Bad: use a real provider or production user to make the smoke look realistic.

### 6. Tests Required

- Page identity, meaningful content, no overlay, and clean console.
- Ten `.lesson-block` nodes, expected source count, and Gate controls matching `allowed_actions` for all four execution tiers.
- Failed/retry and missing/preparing/ready state transitions.
- Start freeze, refresh proposal without replacement, and explicit migration.
- Normal, 900px, and 390px DOM overflow checks, keyboard source access, visible focus, and reduced-motion compatibility.
- Preserve screenshots outside the repository and stop temporary validation services after the run.

### 7. Wrong vs Correct

#### Wrong

```text
pnpm desktop:check passed, therefore the Lesson reader is accepted.
```

#### Correct

```text
Open http://127.0.0.1:1420 with a disposable stateful API fixture, exercise the full state machine, inspect DOM and console at all required viewports, then record exact evidence and non-claims.
```

## Gate 与模块诊断网页完成门（2026-08-11）

- 必走流程：unprepared→prepare、hint、container pending→same Attempt poll、editor stale、submit terminal、teaching-local disclosure、static no-Run、unavailable no Run/Submit。
- 诊断必须分别验证 fail/partial 不跳过与 pass→impact→explicit confirm→route refresh。
- 检查 protected markers 不出现在 DOM/network public payload：private test、reference answer、rubric hash、container/image、Docker socket、command/path。
- 1440px、精确 900px、390px 均检查 `scrollWidth <= clientWidth`、modal viewport fit、键盘 focus、console 0 error/warning、无 framework overlay。
- Desktop/Tauri build 不是此完成门；独立 `tsc --noEmit` 可作为类型补充，但不能代替真实浏览器交互。
