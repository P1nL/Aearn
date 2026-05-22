# Desktop 前端架构重构 — 实施计划

日期：2026-05-22

## 实施阶段

### Phase 1：P0 — 核心体验改进（不改变 App.tsx 结构）

#### Step 1.1：安装依赖

```bash
cd aearn/apps/desktop && npm install @monaco-editor/react zustand sonner
```

**验证：** `npm ls @monaco-editor/react zustand sonner` 确认安装成功

---

#### Step 1.2：创建错误码映射模块

**文件：** `src/lib/errorMessages.ts`（新增）

**内容：**
- 定义 `ErrorInfo` 类型：`{ code: string; message: string; recoverable: boolean }`
- 定义 `ERROR_MESSAGES` 映射表，覆盖以下错误码：
  - RUNNER_TIMEOUT → "代码运行超时，请简化代码后重试"
  - RUNNER_UNAVAILABLE → "运行服务暂时不可用，请稍后重试"
  - RUNTIME_UNSUPPORTED → "当前语言第一版不支持完整运行"
  - SESSION_NOT_FOUND → "学习会话不存在，请重新开始"
  - ATTEMPT_NOT_FOUND → "运行记录不存在"
  - ATTEMPT_STATE_CONFLICT → "当前状态不允许此操作"
  - IDEMPOTENCY_CONFLICT → "请求冲突，请刷新页面后重试"
  - EVALUATION_CONFLICT → "评分结果冲突"
  - NOTE_NOT_FOUND → "笔记不存在"
  - VALIDATION_ERROR → "请求参数不合法"
  - USER_NOT_FOUND → "用户不存在"
  - PLAN_NOT_FOUND → "学习计划不存在"
  - PLAN_DRAFT_INVALID → "计划草稿校验失败"
  - RATE_LIMITED → "操作过于频繁，请稍后重试"
  - INTERNAL_ERROR → "服务端错误，请稍后重试"
- 导出 `getErrorInfo(error: unknown): ErrorInfo` 函数：
  - `ApiRequestError` → 从映射表取友好提示 + 保留 `recoverable`
  - 普通 `Error` → `{ code: 'UNKNOWN_ERROR', message: error.message, recoverable: false }`
  - 其他 → `{ code: 'UNKNOWN_ERROR', message: fallback, recoverable: false }`

**验证：** `tsc --noEmit`

---

#### Step 1.3：集成错误处理到现有代码

**修改文件：**

1. `src/lib/learningHelpers.ts`：
   - 修改 `toActionError` 函数，调用 `getErrorInfo`
   - `AsyncActionState` 的 error 分支增加 `code?: string` 和 `recoverable?: boolean` 字段

2. `src/appTypes.ts`：
   - 更新 `AsyncActionState` 类型定义，error 分支增加 `code` 和 `recoverable`

3. `src/App.tsx`：
   - 导入 `getErrorInfo`，在 `formatError` 中使用（保持函数签名不变，内部逻辑优化）

4. `src/features/learning/ExerciseWorkbench.tsx`：
   - 错误展示区域：如果 `actionState.recoverable === true`，显示重试按钮

**验证：** `tsc --noEmit && npx vite build`

---

#### Step 1.4：创建 CodeEditor 组件

**文件：** `src/features/learning/CodeEditor.tsx`（新增）

**内容：**
- `CodeEditorProps`：`language`, `value`, `onChange`, `readOnly?`, `height?`
- 内部使用 `@monaco-editor/react` 的 `Editor` 组件
- 语言映射：javascript→javascript, python→python, html_css→html, java→java, cpp→cpp
- 配置：minimap 关闭, fontSize 14, lineNumbers 开启, scrollBeyondLastLine 关闭, automaticLayout 开启, tabSize 2
- 使用 `React.lazy` + `Suspense` 包裹，fallback 为 "加载编辑器..."
- readOnly 模式用于 compiled_sandbox_later

**验证：** `tsc --noEmit`

---

#### Step 1.5：将 CodeEditor 集成到 ExerciseWorkbench

**修改文件：** `src/features/learning/ExerciseWorkbench.tsx`

**改动：**
- 导入 CodeEditor
- 将现有的代码 `<textarea>` 替换为 `<CodeEditor>`
- props 映射：
  - `language` = `exercise.runtime_profile.language`
  - `value` = `code`
  - `onChange` = `onCodeChange`
  - `readOnly` = `actionState.status === 'loading'` 或 `exercise.runtime_profile.runtime_tier === 'compiled_sandbox_later'`
- blank 填空的 input 字段保持不变（在 CodeEditor 外部）
- 确保 stale 标记逻辑不受影响

**验证：** `npx vite build` + 手动启动 dev server 检查编辑器渲染

---

#### Step 1.6：创建 useAutoSave hook

**文件：** `src/hooks/useAutoSave.ts`（新增）

**内容：**
- `useAutoSave<T>(value: T, onSave: (value: T) => Promise<boolean>, options?: { delay?: number; enabled?: boolean })`
- 返回 `{ status: 'idle' | 'saving' | 'saved' | 'error', flush: () => Promise<boolean> }`
- 使用 `useRef` 实现 isSaving 并发锁
- 使用 `useRef` 缓存 lastSavedValue，避免重复保存相同内容
- `flush()` 方法：清除 timeout，立即执行保存（如果有未保存内容）

**验证：** `tsc --noEmit`

---

#### Step 1.7：优化笔记自动保存逻辑

**修改文件：** `src/App.tsx`

**改动：**
- 替换现有的 `useEffect` 自动保存逻辑（约 760-766 行）为 `useAutoSave` hook
- `closeDrawers()` 函数中：调用 `flush()` 而非手动判断 + 保存
- 保存失败时：保留抽屉打开状态，显示错误提示

**验证：** `tsc --noEmit && npx vite build`

---

### Phase 1 检查点

- [ ] `tsc --noEmit` 通过
- [ ] `npx vite build` 通过
- [ ] Monaco Editor 在学习页正确渲染，支持 JS/Python 语法高亮
- [ ] 错误提示显示中文友好信息
- [ ] 笔记抽屉关闭时不丢失未保存内容

---

### Phase 2：P1 — 架构重构 + Toast

#### Step 2.1：创建 Zustand stores

**文件（新增）：**

1. `src/stores/useAppStore.ts`：
   - 从 App.tsx 迁移：apiHealth, dashboardState, user, createdPlan, sessionState, lastRun, lastSubmit, activeRoute, sidebarOpen, openGroups, composerInput, homeConversation, reviewConversation, bootstrapHydrated, resetNonce
   - 包含 actions：setUser, setCreatedPlan, setSessionState, goToRoute, toggleSidebar, toggleGroup, resetGoal, handleComposerSubmit

2. `src/stores/useNotesStore.ts`：
   - 从 App.tsx 迁移：notesLoadState, notesErrorMessage, notesList, notesByKnowledgePointId, noteDrafts, noteAssistBusyByKnowledgePointId, noteDrawerContext, reviewNoteContext, notesPageSelection, noteDrawerOpen
   - 包含 actions：loadNotesIndex, ensureNoteForContext, saveDraft, updateDraftContent, updateDraftTitle, requestAgentDraft, openDrawer, closeDrawer, syncNoteRecord

3. `src/stores/useSettingsStore.ts`：
   - 从 App.tsx 迁移：settingsTab, settingsForm, settingsSaveState, settingsSaveErrorMessage
   - 包含 actions：setTab, updateField, save, syncFromUser
   - 迁移辅助函数：emptySettingsForm, settingsFormFromUser, buildSettingsPayload, isSettingsDirty

**验证：** `tsc --noEmit`

---

#### Step 2.2：创建业务逻辑 hooks

**文件（新增）：**

1. `src/hooks/useBootstrap.ts`：
   - 从 App.tsx 迁移 `bootstrap()` 和 `refreshDashboard()` 函数
   - 使用 useAppStore 的 actions
   - 导出 `useBootstrap()` 返回 `{ bootstrap, refreshDashboard }`

2. `src/hooks/useLearningSession.ts`：
   - 从 App.tsx 迁移 `openLearningSession()`, `handlePlanCreated()`, `handleKnowledgePointUpdate()`, `handleResumeShortcut()`, `handleStartCurrentLearning()`
   - 导出 `useLearningSession()` 返回上述函数

**验证：** `tsc --noEmit`

---

#### Step 2.3：添加 Toast 通知

**修改文件：**

1. `src/main.tsx`：
   - 导入 `Toaster` from `sonner`
   - 在 `<App />` 同级添加 `<Toaster position="top-right" richColors />`

2. `src/stores/useNotesStore.ts`：
   - 保存成功时 `toast.success('笔记已保存')`
   - 保存失败时 `toast.error(message)`
   - Agent 补全成功/失败时 toast

3. `src/stores/useSettingsStore.ts`：
   - 保存成功时 `toast.success('设置已保存')`
   - 保存失败时 `toast.error(message)`

4. `src/hooks/useBootstrap.ts`：
   - API 恢复在线时 `toast.success('API 服务已恢复')`

**验证：** `tsc --noEmit && npx vite build`

---

#### Step 2.4：重构 App.tsx

**修改文件：** `src/App.tsx`

**改动：**
- 删除所有迁移到 store 的 useState
- 删除所有迁移到 hook 的业务函数
- 删除迁移到 store 的辅助函数（emptySettingsForm, settingsFormFromUser 等）
- 保留：localStorage 辅助函数（readBootstrapContext, writeBootstrapContext, clearBootstrapContext）可迁移到 `lib/` 或留在 App.tsx
- 保留：JSX 布局和组件组合逻辑
- 从 store/hook 读取状态和调用 actions
- 目标行数：≤400 行

**验证：** `tsc --noEmit && npx vite build`

---

#### Step 2.5：抽取 NoteDrawer 组件

**文件：** `src/components/NoteDrawer.tsx`（新增）

**改动：**
- 从 App.tsx JSX 中抽取笔记抽屉的整段渲染逻辑（约 1035-1097 行）
- NoteDrawer 内部从 useNotesStore 读取状态
- App.tsx 中只保留 `<NoteDrawer />` 一行

**验证：** `tsc --noEmit && npx vite build`

---

### Phase 2 检查点

- [ ] `tsc --noEmit` 通过
- [ ] `npx vite build` 通过
- [ ] App.tsx ≤ 400 行
- [ ] Toast 通知在笔记保存、设置保存场景正常展示
- [ ] 所有现有功能不回归

---

### Phase 3：P2 — SSE 预设

#### Step 3.1：定义 SSE 事件类型

**修改文件：** `src/appTypes.ts`

**新增类型：**
- `SSEEventType`
- `SSEAgentMessage`
- `SSEToolStatus`
- `SSERunnerResult`
- `SSEEvaluationResult`
- `SSEDone`
- `SSEError`
- `SSEEvent` 联合类型

**验证：** `tsc --noEmit`

---

#### Step 3.2：创建 useSSE hook

**文件：** `src/hooks/useSSE.ts`（新增）

**内容：**
- `useSSE<T>(endpoint: string | null, options?: UseSSEOptions<T>)`
- 内部使用 `EventSource` API
- 注册 6 种事件监听器
- 返回 `{ events, status, close }`
- 完整的类型安全

**验证：** `tsc --noEmit`

---

#### Step 3.3：在 api.ts 预留 SSE 路径

**修改文件：** `src/api.ts`

**新增：**
- `buildSSEUrl(path: string, params?: Record<string, string>): string` 辅助函数
- 注释标记哪些接口未来需要支持 SSE（不修改现有函数）

**验证：** `tsc --noEmit && npx vite build`

---

### Phase 3 检查点

- [ ] `tsc --noEmit` 通过
- [ ] `npx vite build` 通过
- [ ] SSE 类型和 hook 代码可被导入使用
- [ ] 现有功能不受影响

---

## 完成标准总览

| # | 验收项 | Phase |
|---|---|---|
| AC1 | ExerciseWorkbench 使用 Monaco Editor，支持 JS/Python/HTML 语法高亮 | 1 |
| AC2 | 笔记抽屉关闭时不丢失未保存内容 | 1 |
| AC3 | RUNNER_TIMEOUT 等关键错误显示友好中文提示和重试按钮 | 1 |
| AC4 | App.tsx 行数 ≤ 400 行 | 2 |
| AC5 | Toast 通知在笔记保存、设置保存等场景正常展示 | 2 |
| AC6 | `tsc --noEmit` 和 `vite build` 通过 | 1,2,3 |
| AC7 | 现有功能（建档、学习、练习、复习、笔记、设置）不回归 | 1,2,3 |
