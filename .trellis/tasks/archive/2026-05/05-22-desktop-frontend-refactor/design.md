# Desktop 前端架构重构 — 技术设计

日期：2026-05-22

## 现有架构

```
aearn/apps/desktop/src/
├── App.tsx                          # 1326 行，集中所有状态和业务逻辑
├── api.ts                           # API 层，874 行，JSON fetch + 类型守卫
├── types.ts                         # 502 行，完整的 API 响应类型
├── appTypes.ts                      # 应用内部类型
├── main.tsx                         # 入口
├── styles.css                       # 全局样式
├── lib/
│   ├── appContent.ts                # 静态文案
│   ├── desktopLabels.ts             # 路由标签
│   └── learningHelpers.ts           # 练习辅助函数
├── components/
│   ├── ApiHealthChip.tsx
│   ├── SidebarNav.tsx
│   ├── SideContext.tsx
│   ├── SystemCard.tsx
│   ├── ThreadMessages.tsx
│   └── ReviewRecap.tsx
├── features/
│   ├── learning/
│   │   ├── ExerciseWorkbench.tsx     # 练习工作台（使用 textarea）
│   │   ├── RuntimeFeedback.tsx
│   │   ├── ErrorFeedbackPane.tsx
│   │   ├── ExplanationCheckPanel.tsx
│   │   ├── SubmissionSummary.tsx
│   │   └── HintHistoryCard.tsx
│   └── onboarding/
│       └── PlanDraftPanel.tsx
└── pages/
    ├── LearningWorkspacePage.tsx     # 393 行，练习操作逻辑
    ├── OnboardingPage.tsx
    ├── ReviewPage.tsx
    ├── NotesPage.tsx
    └── SettingsPage.tsx
```

### 当前问题分析

#### App.tsx 状态分布（30+ useState）

| 类别 | 状态数 | 说明 |
|---|---|---|
| 核心会话 | 6 | apiHealth, dashboardState, user, createdPlan, sessionState, bootstrapHydrated |
| 练习结果 | 2 | lastRun, lastSubmit |
| 导航 UI | 5 | activeRoute, sidebarOpen, openGroups, noteDrawerOpen, settingsTab |
| 对话 | 3 | composerInput, homeConversation, reviewConversation |
| 笔记 | 9 | notesLoadState, notesErrorMessage, notesList, notesByKnowledgePointId, noteDrafts, noteAssistBusy, noteDrawerContext, reviewNoteContext, notesPageSelection |
| 设置 | 4 | settingsForm, settingsSaveState, settingsSaveErrorMessage, resetNonce |

#### 代码编辑器现状

ExerciseWorkbench.tsx 内部使用 `<textarea>` 进行代码编辑，通过 props 接收 `code`/`onCodeChange` 和 `filledBlanks`/`onBlankChange`。当前已有 blank 导航和编辑状态管理逻辑，编辑器替换只需改组件内部实现。

#### 错误处理现状

- `api.ts` 的 `requestJson` 已正确解析 `ApiRequestError`
- `App.tsx` 的 `formatError` 将所有错误转为字符串
- `learningHelpers.ts` 的 `toActionError` 同样转字符串
- 后端返回的 `error.code`、`error.recoverable` 字段在前端被丢弃

## 目标架构

```
aearn/apps/desktop/src/
├── App.tsx                          # ≤400 行，布局 + 路由组合
├── api.ts                           # 不变
├── types.ts                         # 不变
├── appTypes.ts                      # 扩展 SSE 事件类型
├── main.tsx                         # 入口，添加 Toaster
├── styles.css                       # 不变
├── lib/
│   ├── appContent.ts                # 不变
│   ├── desktopLabels.ts             # 不变
│   ├── learningHelpers.ts           # 不变
│   └── errorMessages.ts             # [新增] 错误码映射 + getErrorInfo
├── stores/
│   ├── useAppStore.ts               # [新增] 核心状态：user, plan, session, route
│   ├── useNotesStore.ts             # [新增] 笔记状态 + 业务逻辑
│   └── useSettingsStore.ts          # [新增] 设置表单状态 + 保存逻辑
├── hooks/
│   ├── useBootstrap.ts              # [新增] 从 App.tsx 抽取初始化逻辑
│   ├── useLearningSession.ts        # [新增] 会话开启/恢复逻辑
│   ├── useAutoSave.ts              # [新增] 通用防抖自动保存 hook
│   └── useSSE.ts                    # [新增] SSE hook 框架（P2）
├── components/
│   ├── ApiHealthChip.tsx            # 不变
│   ├── SidebarNav.tsx               # 不变
│   ├── SideContext.tsx              # 不变
│   ├── SystemCard.tsx               # 不变
│   ├── ThreadMessages.tsx           # 不变
│   ├── ReviewRecap.tsx              # 不变
│   ├── ErrorCard.tsx                # [新增] 带错误码 + 重试按钮的错误卡片
│   └── NoteDrawer.tsx               # [新增] 从 App.tsx 抽取笔记抽屉
├── features/
│   ├── learning/
│   │   ├── ExerciseWorkbench.tsx     # 改造：textarea → Monaco Editor
│   │   ├── CodeEditor.tsx            # [新增] Monaco Editor 封装
│   │   ├── RuntimeFeedback.tsx       # 不变
│   │   ├── ErrorFeedbackPane.tsx     # 不变
│   │   ├── ExplanationCheckPanel.tsx # 不变
│   │   ├── SubmissionSummary.tsx     # 不变
│   │   └── HintHistoryCard.tsx       # 不变
│   └── onboarding/
│       └── PlanDraftPanel.tsx        # 不变
└── pages/                           # 不变（可能小幅调整为从 store 读取状态）
```

## 技术决策

### D1：状态管理选型 — Zustand

**选择 Zustand 而非 Redux / Jotai / useContext：**

- 零样板代码，一个 `create()` 即可
- 不需要 Provider 包裹
- 支持 selector 订阅，天然避免不必要的重渲染
- bundle 体积小（~1KB gzipped）
- 与现有 useState 模式迁移成本最低

**Store 拆分策略：**

```typescript
// useAppStore — 核心状态
interface AppStore {
  apiHealth: ApiHealthState;
  dashboardState: DashboardState;
  user: UserProfile | null;
  createdPlan: CreatedPlanResponse | null;
  sessionState: SessionState;
  lastRun: RunExerciseResponse | null;
  lastSubmit: SubmitExerciseResponse | null;
  activeRoute: AppRoute;
  sidebarOpen: boolean;
  openGroups: Record<NavGroupKey, boolean>;
  composerInput: string;
  homeConversation: ConversationMessage[];
  reviewConversation: ConversationMessage[];
  // actions
  setUser(user: UserProfile | null): void;
  setCreatedPlan(plan: CreatedPlanResponse | null): void;
  setSessionState(state: SessionState): void;
  goToRoute(route: AppRoute): void;
  resetGoal(): void;
  // ...
}

// useNotesStore — 笔记专属
interface NotesStore {
  notesLoadState: 'idle' | 'loading' | 'ready' | 'error';
  notesList: NoteRecord[];
  notesByKnowledgePointId: Record<string, NoteRecord>;
  noteDrafts: Record<string, NoteDraftState>;
  noteDrawerOpen: boolean;
  noteDrawerContext: NoteContext | null;
  // actions
  loadNotesIndex(userId: string): Promise<void>;
  saveDraft(knowledgePointId: string): Promise<boolean>;
  updateDraftContent(knowledgePointId: string, content: string): void;
  openDrawer(context: NoteContext): void;
  closeDrawer(): Promise<boolean>;
  // ...
}

// useSettingsStore — 设置专属
interface SettingsStore {
  settingsTab: SettingsKey;
  form: SettingsFormState;
  saveState: 'idle' | 'saving' | 'saved' | 'error';
  saveErrorMessage: string | null;
  // actions
  setTab(tab: SettingsKey): void;
  updateField(field: keyof SettingsFormState, value: string | boolean): void;
  save(userId: string): Promise<void>;
  syncFromUser(user: UserProfile): void;
}
```

### D2：代码编辑器 — Monaco Editor

**封装层设计：**

```typescript
// features/learning/CodeEditor.tsx
interface CodeEditorProps {
  language: Language;
  value: string;
  onChange: (value: string) => void;
  readOnly?: boolean;
  height?: string;
}
```

**语言映射：**

| API Language | Monaco Language |
|---|---|
| `javascript` | `javascript` |
| `python` | `python` |
| `html_css` | `html` |
| `java` | `java`（只读） |
| `cpp` | `cpp`（只读） |

**与 ExerciseWorkbench 的集成：**

- ExerciseWorkbench 当前接收 `code` + `onCodeChange` props
- 直接将内部 textarea 替换为 CodeEditor 组件
- 不改变 ExerciseWorkbench 对外的 props 接口
- blank 填空仍使用独立的 input 字段（不在 Monaco 内部处理）

### D3：错误处理层设计

```typescript
// lib/errorMessages.ts
interface ErrorInfo {
  code: string;
  message: string;
  recoverable: boolean;
}

function getErrorInfo(error: unknown): ErrorInfo;
```

**集成点：**

- `LearningWorkspacePage.tsx` 的 `toActionError` → 改用 `getErrorInfo`
- `App.tsx` 的 `formatError` → 改用 `getErrorInfo`
- `SystemCard` 增加可选的 `recoverable` prop 控制重试按钮显示
- 新增 `ErrorCard` 组件，用于带错误码的标准化错误展示

### D4：笔记自动保存优化

```typescript
// hooks/useAutoSave.ts
interface UseAutoSaveOptions {
  delay?: number;       // 默认 800ms
  enabled?: boolean;    // 控制是否启用
}

interface UseAutoSaveReturn {
  status: 'idle' | 'saving' | 'saved' | 'error';
  flush(): Promise<boolean>;  // 立即保存（关闭抽屉时调用）
}
```

**并发保护：**
- 使用 `useRef` 保存 isSaving 标志
- 新的保存请求到来时，如果正在保存，等上一次完成后再发起
- `flush()` 方法用于关闭抽屉前的强制保存

### D5：Toast 通知 — sonner

**集成方式：**
- `main.tsx` 中添加 `<Toaster position="top-right" richColors />`
- 在 store action 和 hook 中使用 `toast.success()` / `toast.error()`
- 不替换 SystemCard 等现有内联反馈

### D6：SSE Hook 预设

```typescript
// hooks/useSSE.ts（框架代码，当前不接入真实 SSE）

type SSEEventType = 'agent_message' | 'tool_status' | 'runner_result' | 'evaluation_result' | 'done' | 'error';

interface SSEEvent<T = unknown> {
  type: SSEEventType;
  id?: string;
  data: T;
}

interface UseSSEOptions<T> {
  onEvent?: (event: SSEEvent) => void;
  onDone?: (result: T) => void;
  onError?: (error: ApiError) => void;
}

function useSSE<T>(endpoint: string | null, options?: UseSSEOptions<T>): {
  events: SSEEvent[];
  status: 'idle' | 'connecting' | 'streaming' | 'done' | 'error';
  close(): void;
};
```

**SSE 事件类型定义添加到 `appTypes.ts`：**

```typescript
export type SSEAgentMessage = {
  request_id: string;
  session_id: string;
  message_id: string;
  delta: string;
  content: string;
  next_action: NextAction;
};

export type SSERunnerResult = {
  request_id: string;
  session_id: string;
  attempt_id: string;
  runtime_status: RuntimeStatus;
  // ... 与 RunExerciseResponse 类似
};

export type SSEEvaluationResult = {
  request_id: string;
  session_id: string;
  attempt_id: string;
  code_completion_result: CodeCompletionResult;
};
```

## 兼容性与迁移策略

### 渐进式迁移

1. **Phase 1（P0）**：在现有架构上添加 CodeEditor、errorMessages、useAutoSave — 不改变 App.tsx 结构
2. **Phase 2（P1）**：引入 Zustand store + Toast — 渐进替换 App.tsx 中的 useState
3. **Phase 3（P2）**：SSE hook 框架 — 纯新增，不影响现有代码

### 回退计划

- 每个 Phase 独立可测试、独立可回退
- Phase 1 的改动完全局部化（ExerciseWorkbench 内部、lib 新增文件）
- Phase 2 如果 Zustand 迁移出问题，可以保留部分 useState 混合使用
- Phase 3 纯框架代码，不接入真实逻辑

## 新增依赖

| 包名 | 版本 | 用途 | 大小 |
|---|---|---|---|
| `@monaco-editor/react` | ^4.6.0 | 代码编辑器 | ~15KB（按需加载 Monaco） |
| `zustand` | ^5.0.0 | 状态管理 | ~1KB gzipped |
| `sonner` | ^1.7.0 | Toast 通知 | ~5KB gzipped |
