# State Management

> How state is managed in this project.

---

## Overview

The desktop shell uses **Zustand** for global state management, split into domain-specific stores:

- `useAppStore` — bootstrap, routing, user, plan, session, dashboard, conversations
- `useNotesStore` — notes CRUD, drawer state, agent draft, auto-save coordination
- `useSettingsStore` — settings form, save state, dirty detection

State must respect the contract boundary: frontend owns interaction state, while backend owns scoring, Attempts, ReviewState, FSRS scheduling, and durable notes.

Toast notifications use **sonner** (`<Toaster>` in `main.tsx`); stores call `toast.success()` / `toast.error()` directly after async operations.

---

## State Categories

- Local UI state: editor content, dirty/pristine flags, open drawers, selected panel, disabled reasons, loading state.
- Server state: user, plan, modules, knowledge points, sessions, exercises, attempts, review queue, notes.
- Derived display state: progress labels, stale result badges, retry visibility, unsupported runtime notices.
- Tauri/window state: shell readiness, API base URL, native capability status.
- URL/router state: page selection when routing is introduced; do not encode sensitive content in route state.

---

## When to Use Global State

- Use component-local state by default.
- Promote to app-level state only when multiple pages need the same source: current user, active plan, API health, global toast, confirm dialog, and note drawer.
- Do not create a global store just to pass props through one or two levels.
- Do not keep backend-owned facts only in frontend memory; refetch or update from API responses after writes.
- For persisted bootstrap state such as `localStorage` user/plan context, do not clear storage on first render before the initial restore attempt finishes. Gate write-back or cleanup behind an explicit hydration-complete flag.

---

## Server State

- Server state must use the API contract as source of truth.
- After run/submit operations, update UI from the returned operation result, not from locally recomputed score.
- `Attempt(run)` creates a fact record but must not advance ReviewState in the UI.
- `Attempt(submit)` or `review_submit` may update ReviewState only after the backend confirms it.
- Stale run results must be invalidated or clearly marked when editor content changes.
- Idempotent retries should show the existing server result when the backend returns it.

---

## Examples

- `aearn/apps/desktop/src/App.tsx` currently renders static Milestone 0 readiness state and does not need global state.
- `docs/product/frontend-interaction-spec.md` defines future app-level state such as `bootstrap_status`, `user_state`, `api_status`, `active_plan_id`, and `resume_available`.
- Exercise editor text is local UI state; `Attempt`, `code_completion_result`, and `ReviewState` are server state.

---

## Common Mistakes

- Duplicating backend scheduling or scoring rules in the desktop app.
- Showing old stdout/preview/test output after the code changed without a stale marker.
- Showing learning-page run/submit state inside ReviewPage. Review route state should come from `/api/reviews/*` responses and its own local `reviewResult`.
- Treating "today review count > 0" as automatic navigation to review. Product flow says normal open defaults to current learning unless backend flags high-risk resume.
- Making settings toggles for fixed backend rules such as Attempt persistence, scoring dimensions, or FSRS mapping.

## Scenario: Local User Switching And Data Actions

### 1. Scope / Trigger

- Trigger: changing desktop local profile list/switch, data summary/export/reset/delete actions, or active-user request wiring.
- Scope: `useAppStore`, `api.ts`, `SettingsPage`, `LearningWorkspacePage`, `ReviewPage`, `useNotesStore`, and `bootstrapStorage`.

### 2. Signatures

- Storage key: `localStorage["aearn.bootstrap"]`
- Storage value: `{ userId: string; planId: string | null }`
- API helpers: `fetchLocalUsers()`, `fetchUserDataSummary(userId)`, `exportLocalUserData(userId)`, `resetLocalUserData(userId)`, `deleteLocalUser(userId)`.
- Store actions: `clearUserScopedState()`, `switchLocalUser(item)`, `exportActiveUserData()`, `resetActiveUserData()`, and `deleteActiveUser()`.
- Active-user payload fields: learning/review message, run, hint, explain, check, submit, warmup, and review submit calls include active `user_id`.

### 3. Contracts

- Switching local users must clear route, session, review, notes, dashboard, conversation, run, submit, and composer state before showing the selected user's facts.
- Switch writes `{ userId, planId: null }` first so a reload cannot return to the previous user, then writes the selected plan id after plan/dashboard validation succeeds.
- Reset writes `{ userId, planId: null }`, preserves the user in state, clears user-scoped stores, and routes to onboarding.
- Delete clears `localStorage["aearn.bootstrap"]`, clears the active user and all user-scoped stores, and routes to onboarding/profile selection.
- Settings privacy copy may expose product-facing local data actions, but must not expose editable `Attempt`, `ReviewState`, FSRS, `due_at`, score rules, hidden tests, or runner internals.
- Learning and review page mutations must use the active `user.id` from app state; a session mismatch error must not keep reusing stale session state as if it still belongs to the user.

### 4. Validation & Error Matrix

- No active user -> summary/export/reset/delete buttons disabled or no-op.
- Local user list load fails -> visible Settings error using stable API error formatting.
- Data summary load fails -> visible Settings error; do not render stale counts as current.
- Switch user fails before profile validation -> keep current bootstrap unchanged.
- Switch user has a stale `active_plan_id` -> persist user-only bootstrap rather than previous user context.
- Reset succeeds -> current `planId` is cleared and route/session/note/review/dashboard stores are reset.
- Delete succeeds -> bootstrap is removed and normal UI shows no active user facts.

### 5. Good/Base/Bad Cases

- Good: switching from user A to user B immediately clears A's sidebar/session/review/notes before B's plan or empty onboarding state renders.
- Good: reset leaves B selected but with `planId=null`, so reload returns to onboarding for B.
- Base: a user with no active plan can still be selected; the app stores user-only bootstrap and opens onboarding.
- Bad: switching only updates React state but does not update `localStorage["aearn.bootstrap"]`, causing reload to restore the previous user.
- Bad: Settings renders raw backend table labels such as `Attempt`, `ReviewState`, `due_at`, or hidden-test details.

### 6. Tests Required

- Run `pnpm --dir .\aearn desktop:check` after changing store, API helpers, Settings, LearningWorkspacePage, or ReviewPage.
- Backend-focused smoke must prove cross-user mutations return stable not-found codes before exposing destructive UI.
- Browser smoke when practical: create two users, switch users, reload, and verify sidebar/dashboard/notes/review belong to the selected user.
- Browser smoke reset: reset active user, reload, and verify same `userId` with no `planId` returns to onboarding.
- Browser smoke delete: delete active user, reload, and verify bootstrap is cleared and no deleted user data appears.

### 7. Wrong vs Correct

#### Wrong

```ts
set({ user: loadedUser, createdPlan: plan });
```

This changes memory only; a reload can restore the previous `localStorage["aearn.bootstrap"]` user.

#### Correct

```ts
writeBootstrapContext({ userId: loadedUser.id, planId: null });
clearUserScopedState({ keepUser: loadedUser, route: "onboarding" });
writeBootstrapContext({ userId: loadedUser.id, planId: plan.LearningPlan.id });
```

Persist the user boundary before rendering new facts, then persist the plan only after backend validation succeeds.
