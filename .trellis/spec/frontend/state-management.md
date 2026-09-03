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

## Lesson Gate 临时状态与服务端权威（2026-08-11）

- editor 文本、当前 hint 展示、poll timer、modal open 和 stale 标记属于页面临时状态。
- Gate status/version、`allowed_actions`、Attempt/result、score/pass、mastery、route change、diagnostic state/impact/cooldown 全部来自 API。
- 提交后只能合并服务器返回 projection；不得先乐观写 passed/unlock。发生 conflict、路由变化或 confirm 后重新读取 Lesson/Gate authority。
- 页面卸载、track/key 改变或新 Attempt 替换旧 Attempt 时清理 poll timer，旧 callback 不得覆盖新 scope。


## Tutor Queue 服务端权威（2026-08-14）

- Queue item/order/version、active turn、pending request、pause reason、control version 全部是 server state；Desktop 不得乐观重排、推算 pending count 或本地 resume。
- Composer 普通 Send 的返回可能是 accepted turn 或 queued item；queued 分支只合并服务器响应并触发 snapshot/Queue refresh。
- edit/delete/reorder/Steer/Interrupt/resume/execute/Retry mutation 必须携带最后一次服务器读取的 expected version；409 后重读 authority，不重放本地猜测状态。
- 最终 Desktop migration 可为 Queue 增加临时编辑/drag state，但 mutation 成功前不得覆盖 authoritative items；SSE reconnect 或 snapshot rebuild 应替换而非拼接 Queue。


## Tutor v2 capability 服务端权威（2026-08-14）

- Desktop bootstrap/恢复必须把 thread-turn capability 当服务器状态；`effective_enabled=false` 时 mutation 进入只读 unavailable，不回退 legacy continuation。
- capability refresh 替换本地 projection；不得本地推进 generation/state、恢复已收口 legacy run 或绕过 blocked。

## 场景：Guided/自由阅读工作区 authority（2026-08-23）

### 1. 适用范围与触发条件

- 触发：修改 `TrackLearningWorkspace`、`useTeachingWorkspaceController`、教学 mode/session、Lesson follow 或历史 session 引用。

### 2. 状态签名

`useTeachingWorkspaceController` 独占 current teaching session、server mode/status/checkpoint、Action Shelf、pending action、conflict/error 与 abort；Tutor draft/reference/stream、Lesson selection/Gate/scroll 分别留在原组件内。

### 3. 契约

- Guided/Free Reading 通过一份稳定挂载的 Tutor 与一份稳定挂载的 Lesson 做 CSS grid-area 主次换位，不复制组件、conversation、document 或 SSE reducer。
- `mode/status/checkpoint/action_shelf` 是 server state；切换成功后采用 mutation projection，409 只刷新 authority，不自动重放。
- `following | follow_paused` 是本地展示状态。用户滚动、键盘阅读、选区、citation/Gate 交互或进入 Free Reading 都暂停跟随；返回 Guided 保持 paused，只有新 knowledge/session 或显式“回到当前讲解”恢复。
- historical teaching reference 不改变 active `knowledge_key`、task kind、mode、Composer draft 或 panel；历史引用自己的 source knowledge 仅存在于 exact reference DTO。

### 4. 验证与错误矩阵

- stale session/checkpoint/version -> 显示 `TEACHING_AUTHORITY_CONFLICT`，保留 draft/reference/selection/scroll，刷新不重放。
- assignment/document/block handle 不匹配 -> 暂停 follow 并显示可恢复 conflict，不猜测 block。
- current session identity 变化 -> follow 可重置；普通 snapshot refresh 不重置。

### 5. 正常、基础与错误案例

- 正常：Free Reading 切回 Guided 后仍停在用户阅读位置，显式恢复才滚到最新 exact block。
- 基础：历史分段无当前 bounded messages 时只显示加载更早记录提示。
- 错误：用 mode 切换 key 强制 remount Tutor/Lesson，或在 409 后重放 mutation。

### 6. 必须测试

- single mount/SSE、draft/reference/scroll 保持、mode success/conflict、follow pause/resume/new-session reset。
- exact historical reference 不能改 active scope，发送成功后才清空 reference chips。

### 7. 错误与正确写法

- 错误：`key={teachingMode}` 重建 Tutor/Lesson，或本地先写 server mode。
- 正确：controller 接受 server projection；DOM 保持 mounted，仅用 role class/grid area 换位。

## Planning language request replay authority (2026-09-03)

- Semantic language options, order, safe reason metadata, recommendation, request version, and pending state are server state. Desktop must not infer or expand candidates from labels or a local language catalog.
- One-option semantic requests still begin with no local selection. A draft lives only under exact request ID/version and is restored only if the persisted option set still contains its value.
- Clarification remains the existing text-request state. Refresh, SSE reconnect, and history replace local request state from the persisted projection and never rewrite an older full-catalog request into v2 behavior.
