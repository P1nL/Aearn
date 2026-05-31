# Aearn 前端交互规格

日期：2026-05-13  
状态：Draft V1.1  
适用范围：React + Tauri 桌面端第一版，承接 `user-flows.md`、`api-contract.md`、`code-completion-evaluation-spec.md` 和 `langgraph-state-machine.md`

## 目标

把产品 IA、用户流程、API 契约、评分规则和 LangGraph 状态机落成可实现的前端交互边界。第一版必须优先支撑下面的闭环：

```text
建档生成学习路线 -> 进入当前学习 -> 对话中生成练习 UI -> 编写/运行/预览 -> Agent hint / explain-error -> 记录笔记 -> FSRS 复习
```

前端不承担最终评分、FSRS 调度或 LangGraph 编排职责。前端负责把用户操作、代码编辑、运行结果、提示、解释检查和笔记内容清晰展示，并通过 API 与后端状态机对齐。

## 设计原则

1. 代码编辑器、预览和测试结果以对话中的生成式 UI 呈现，不做固定三栏工作台。
2. 所有能影响 `Attempt`、`code_completion_result`、`ReviewState` 的操作必须走 API，不允许前端本地伪造完成状态。
3. JS/HTML/CSS、Python、Java/C++ 按运行能力分层展示，不把“课程可见”误导成“实时运行可用”。
4. 前端 UI 不暴露 `Attempt(run)` 和 `Attempt(submit)` 两类内部概念，只展示运行、预览、测试和提交结果；后端仍保留两类事实记录。
5. 所有长耗时状态都必须有 loading、error、disabled、retry 或 confirm 反馈。

## 第一版明确不做

- 不做复杂拖拽式路线编辑，只允许按钮式 `skip`、`replace`、`adjust`。
- 不做多窗口自由停靠或复杂 dock layout。
- 不做外部渠道一键分发、账号登录、社区发布或平台适配改写。
- 不做 Java / C++ 完整在线编译沙箱，仅保留 `compiled_sandbox_later` 能力提示和禁用态。
- 不做项目级多文件调试、任意依赖安装、真实代码仓库深度导入。
- 不做独立复盘草稿流程、`publishDrawer` 用户路径、`CodeDraftPage` 一级页面或面试讲述草稿。

## 顶层组件树

```text
AppShell
  BootstrapBoundary
    AppTopBar
    PrimaryRouter
      OnboardingPage
      LearningWorkspacePage
      ReviewPage
      NotesPage
      SettingsPage
    NoteDrawer
    GlobalToastRegion
    GlobalConfirmDialog
    GlobalErrorBoundary
```

### `AppShell`

职责：

- 初始化 Tauri 壳能力、API base URL、当前用户与窗口状态。
- 提供全局导航、toast、confirm、error boundary。
- 不直接持有练习评分逻辑。

核心状态：

| 状态 | 字段 | 展示要求 |
|---|---|---|
| 初始化中 | `bootstrap_status=loading` | 全屏骨架屏，禁止用户进入工作台 |
| 初始化失败 | `bootstrap_status=error` | 显示错误、重试按钮和设置入口 |
| 无用户 | `user_state=empty` | 跳转 Onboarding |
| 有活动计划 | `active_plan_id` | 默认进入 LearningWorkspace |
| API 离线 | `api_status=offline` | 顶部警告，运行/提交/生成禁用 |

## 页面组件规格

## 页面 0：`OnboardingPage`

### 组件树

```text
OnboardingPage
  AssistantUIThread
    ConversationTimeline
      GeneratedLearningRouteCard
    Composer
```

### 核心数据

- `mode`：`goal_based` / `material_based`
- `goal_text`
- `materials`
- `language`
- `course_id`
- `target_level`
- `clarification_answers`
- `onboarding_session_id`
- `tool_calls.show_learning_route`
- `plan_draft`
- `modules`
- `source_attribution`
- `runtime_tier`：`browser_preview` / `python_stdout_test` / `compiled_sandbox_later`

### 主要按钮行为

| 按钮 | API / 行为 | 启用条件 | 成功后 |
|---|---|---|---|
| 发送建档回复 | `POST /api/onboarding/messages` SSE | API 在线且没有正在生成的回复 | 普通气泡继续引导，或以 `show_learning_route` 渲染路线卡片 |
| 修改路线 | 向 composer 输入自然语言修改要求 | 已有路线卡片 | 生成新路线卡片；时间预算变化会显示新的学习节奏，旧卡片 `开始学习` 禁用 |
| 开始学习 | `POST /api/onboarding/{session_id}/confirm_plan` | 当前最新路线卡片且草稿校验通过 | 创建 `plan` 并进入工作台 |

### 页面状态

| 状态 | 触发 | UI 反馈 |
|---|---|---|
| empty | 首次打开且无输入 | 引导用户输入模糊目标或粘贴资料 |
| loading | 生成草稿中 | 禁用生成/确认按钮，展示流式 Agent 文案或 skeleton |
| error | API 返回错误 | 展示 `error.code`、`error.message`、重试按钮 |
| disabled | 输入不足或 API 离线 | 按钮置灰并给出原因 |
| stale route | 新卡片已替换旧卡片 | 保留旧卡片内容，只禁用旧卡片的 `开始学习` |
| confirm | 重新生成、破坏主干调整、确认计划 | 弹出 `GlobalConfirmDialog` |
| unsupported language | `POST /api/onboarding/messages` 返回 `LANGUAGE_NOT_SUPPORTED` | 展示后端 `error.message` 和支持语言列表，不渲染路线卡片 |
| unsupported notice | `runtime_tier=compiled_sandbox_later` | 明确 Java/C++ 第一版不提供完整运行沙箱 |
| fallback notice | 动态路线生成失败但模板 fallback 成功 | 保持可确认路线卡片，展示简短来源说明，不暴露 provider 原始错误 |

## 页面 1：`LearningWorkspacePage`

### 组件树

```text
LearningWorkspacePage
  WorkspaceTopStatusBar
  RoutePanel
    ModuleTree
    KnowledgePointList
    RouteActionMenu
  ConversationTimeline
    GeneratedConceptIntroCard
    GeneratedConceptCheckResultCard
    AgentMessage
    GeneratedLearningHistoryCard
    GeneratedCodeExerciseCard
      ExercisePrompt
      CodeEditor
      BlankNavigator
      RunActionBar
      GeneratedRuntimeFeedback
        PreviewPane
        StdoutPane
        TestResultPane
        ErrorFeedbackPane
      ExplanationCheckPanel
      NoteDrawerToggle
  AssistantSidePanel
    KeyConceptsCard
    CommonErrorsCard
    HintHistoryCard
    StageBenefitCard
```

### 初始化流程

1. 页面加载 `GET /api/dashboard?user_id={user_id}`。
2. 普通打开默认进入当前学习入口；如果有到期复习，只展示应用内提示，不强制跳转。
3. 仅当后端判断“最近一次学习活动距当前超过 72 小时，且至少存在一条 `forget_risk=high` 的到期复习”时，优先进入 `ReviewPage`。
4. 如果 `resume_available=true`，展示恢复学习提示和 `next_entry_point`。
5. 用户点击当前知识点后调用 `POST /api/learning-sessions/start`。
6. 前端以 `session_id` 加载会话；如果 `learning_stage` 不是 `practice_support`，只展示概念优先对话，不展示练习卡片。
7. 新会话入口必须渲染 `initial_tool_calls` 中持久化的 `show_concept_intro`；刷新或恢复时不得重新生成不同内容。
8. Agent 通过 `show_concept_check_result` 展示自然语言判断结果，通过 `show_code_exercise` 工具调用在对话中生成练习 UI；通过 `show_learning_history` 工具调用展示知识点历史对话引用。

### `WorkspaceTopStatusBar`

展示字段：

- `active_goal`
- `current_stage`
- `current_language`
- `current_course`
- `today_learning_tasks`
- `today_review_count`
- `overall_progress`
- `resume_available`
- `next_entry_point`

按钮：

| 按钮 | 行为 | 禁用条件 |
|---|---|---|
| 继续学习 | 进入当前 `next_entry_point` | 无活动计划 |
| 今日复习 | 跳转 `ReviewPage` | `today_review_count=0` 时仍可进入空态 |
| 设置 | 跳转 `SettingsPage` | 无 |
| 恢复上次 | `GET /api/learning-sessions/resume` | `resume_available=false` |

### `RoutePanel`

状态标签：

- 未开始
- 学习中
- 已完成
- 已跳过

按钮行为：

| 操作 | 行为 | 约束 |
|---|---|---|
| 点击模块 | 展示模块详情与知识点列表 | 不自动切换学习状态 |
| 进入知识点 | `POST /api/learning-sessions/start` | 需要活动 `plan_id` |
| 跳过模块 | `PATCH /api/plans/{plan_id}/modules/{module_id}` | 仅 `is_skippable=true` |
| 替换模块 | 调用模块调整接口或进入计划草稿调整态 | 第一版只做按钮式替换 |
| 调整模块 | 弹 confirm 后提交调整 | 风险提示必须说明可能破坏知识主干 |

### 概念优先会话阶段

职责：

- `LearningWorkspacePage` 必须接受 `exercise=null` 的会话响应，并保持 composer 可用。
- `show_concept_intro` 渲染概念总结、易懂例子和 2-4 个文本选项；选项只是可复制的回答提示，不是强制按钮。
- `show_concept_check_result` 渲染 `correct` / `incorrect` / `unclear` / `skipped` 结果、解释、下一步提示、可选 `repair_check` 和文本 quick replies。
- `concept_check`、`concept_repair` 和 `practice_offer` 只展示概念判断与修正，不直接固定展示练习卡片。
- `practice_support` 才能展示 `GeneratedCodeExerciseCard`；如果是跳过或修正上限后的引导练习，卡片说明内展示“当前学习进度尚未完成”和概念小结。
- `CONCEPT_INTRO_GENERATION_FAILED` 必须显示重试生成和返回路线动作，不展示破损 fallback 卡片。
- 用户主动回看历史时展示 `GeneratedLearningHistoryCard`，只引用学习页 AI/用户对话，不引用建档页或复习页内容。

状态来源：

| 字段 | 前端用途 |
|---|---|
| `learning_stage` | 决定 placeholder、quick replies 和是否可渲染练习卡 |
| `learning_stage_state.learning_incomplete` | 决定提前练习提示 |
| `lesson_outline` / `lesson_sources` | 展示概念提纲和来源归因 |
| `initial_tool_calls[]` | 新会话入口渲染持久化 `show_concept_intro` |
| `tool_calls[].name` | 选择 `show_concept_intro`、`show_concept_check_result`、`show_code_exercise` 或 `show_learning_history` 组件 |

### `GeneratedCodeExerciseCard`

职责：

- 作为对话中的生成式 UI 卡片展示题面、`starter_code`、`CodeBlank`、当前 `filled_blanks`。
- 只由 `show_code_exercise` 工具调用或已解锁的恢复状态创建，不由 `session.exercise` 在会话入口固定渲染。
- 管理本地编辑状态：`pristine`、`dirty`、`running`、`submitted`。
- 不计算最终 `result`、`score` 或 `fsrs_rating`。
- 不在 UI 上显示 `Attempt(run)` / `Attempt(submit)` 内部类型。

编辑器状态：

| 状态 | 触发 | UI 反馈 |
|---|---|---|
| `pristine` | 初次加载 | Run 可用，Submit 需先 run 或解释检查 |
| `dirty` | 用户修改代码 | 显示未运行变更，旧测试结果标记为 stale |
| `running` | 调用 `/run` 中 | 编辑器可读，运行按钮 loading |
| `unsupported` | `runtime_tier=compiled_sandbox_later` | 运行按钮禁用，展示能力边界 |
| `submitted` | `/submit` 返回 | 展示提交结果摘要，可继续开新一次练习尝试 |

### `RunActionBar`

按钮：

| 按钮 | API / 行为 | 启用条件 | 结果展示 |
|---|---|---|---|
| 运行预览 | `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/run`，`run_mode=preview` | `runtime_tier=browser_preview` | `PreviewPane`、console、运行结果摘要 |
| 运行可见测试 | 同上，`run_mode=visible_tests` | `supports_tests=true` | `TestResultPane`、stdout/stderr |
| 提交答案 | `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/submit` | 有 `attempt_id`，或后端允许 submit 时自动 run | `code_completion_result` |
| 获取提示 | `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/hint` | 有当前代码，未超过提示策略限制 | `HintHistoryCard` |
| 解释错误 | `POST /api/learning-sessions/{session_id}/attempts/{attempt_id}/explain-error` | 最近 Attempt 有错误或失败测试 | `ErrorFeedbackPane` |
| 检查解释 | `POST /api/learning-sessions/{session_id}/attempts/{attempt_id}/check-explanation` | 有 `attempt_id` 和用户解释 | `ExplanationCheckPanel` |
| 打开笔记 | 打开 `NoteDrawer` | 当前会话可追溯到知识点 | 当前知识点 Markdown 笔记 |
| 结束会话 | `POST /api/learning-sessions/{session_id}/finish` | 有 active session | 返回摘要与 `next_entry_point` |

### 生成式运行反馈边界

`GeneratedRuntimeFeedback` 位于对话生成的练习卡片内，必须把不同反馈拆开：

| 区域 | 展示内容 | 不展示内容 |
|---|---|---|
| `PreviewPane` | JS/HTML/CSS 实时预览、DOM 断言摘要、console 输出 | Python stdout、隐藏测试细节 |
| `StdoutPane` | Python stdout、stderr、进程退出状态 | DOM 预览 |
| `TestResultPane` | 可见测试、隐藏测试数量摘要、通过率、失败用例名称 | 隐藏测试源码或完整答案 |
| `ErrorFeedbackPane` | `runtime_error`、`timeout`、`unsupported`、`error_cause`、`fix_suggestion` | 最终评分替代品 |
| `ExplanationCheckPanel` | 用户解释输入、`result`、`follow_up_required`、反馈 | 长篇聊天式追问 |

错误反馈区必须区分三类来源：

- runner 事实：`runtime_status`、`stdout`、`stderr`、`test_results`、`error_message`
- Agent 解释：`error_cause`、`explanation`、`fix_suggestion`
- 评分结果：`result`、`score_breakdown`、`weak_points`、`fsrs_rating`

运行或提交接口成功返回后，桌面端必须基于后端返回的 `RunExerciseResponse` / `SubmitExerciseResponse` 追加一条短 Agent 对话反馈，避免练习卡片已更新但对话区停留在上一条提问。该反馈是确定性 UI 文案，不额外调用模型，也不能本地计算评分或调度结论。

### 语言运行能力分层

| `runtime_tier` | 技术范围 | 前端能力 | API 依赖 | 第一版限制 |
|---|---|---|---|---|
| `browser_preview` | JS / HTML / CSS | 实时预览、console 捕获、DOM 断言摘要、可见测试反馈 | `/run`、`/submit`、`/hint`、`/explain-error` | 不支持任意 npm 依赖、不支持多文件项目调试 |
| `python_stdout_test` | Python | 代码编辑、stdout/stderr、函数测试和可见测试结果 | `/run`、`/submit`、`/hint`、`/explain-error` | 不承诺本地 GUI、网络访问或任意第三方包 |
| `compiled_sandbox_later` | Java / C++ | 静态阅读、补全练习、能力边界提示 | `/run` 返回 `runtime_status=unsupported` 或不展示运行按钮 | 不提供完整编译、运行、资源隔离沙箱 |

## 页面 2：`ReviewPage`

### 组件树

```text
ReviewPage
  ReviewQueuePanel
  ReviewExercisePanel
    ReviewPromptCard
    ReviewWarmupCard
    GeneratedCodeExerciseCard
    ReviewAIPatchPanel
  ReviewMetricPanel
    ForgetRiskCard
    LastReviewCard
    MasteryCard
    NextDueAtCard
    WeakPointsCard
```

### 初始化与按钮

| 操作 | API | 成功后 |
|---|---|---|
| 加载今日复习 | `GET /api/reviews/today?user_id={user_id}` | 展示待复习列表 |
| 开始复习 | `POST /api/reviews/start` | 展示短热身、`review_stage`、`review_exercise`、`selected_seed_id` 和 `variant_reason` |
| 提交热身答案 | `POST /api/reviews/{session_id}/warmup-result` | 更新 `warmup.result` 和 `review_stage`；不显示 FSRS 变化 |
| 跳过热身 | `POST /api/reviews/{session_id}/warmup-result`，`action=skip` | 记录 `warmup_result=skipped`，直接进入变体练习 |
| 运行复习练习 | 复用学习会话 `/run` 能力或 review runner | 展示运行结果 |
| 提交复习结果 | `POST /api/reviews/{session_id}/exercise-result` | 更新 `fsrs_rating`、`due_at`、`forget_risk` |
| 下一条 | 刷新列表 | 当前项完成后启用 |

`review_ai_patch` 题型不展示代码编辑提交框，而展示结构化审核表单：`verdict`、`evidence`、`knowledge_point_risk`、`next_action`。提交前必须要求用户填写证据和风险说明；前端只做必填校验，不本地计算 `score_breakdown`、`fsrs_rating`、`due_at` 或 `forget_risk`。

### 状态

- empty：今日无待复习项，提示继续学习或查看历史表现。
- loading：列表加载、seed bank rescue、变体生成、热身提交和复习提交均显示局部 skeleton；首次加载可 skeleton，后台刷新保留旧卡片。
- warmup：展示短热身问题、跳过按钮和一句话回答输入。
- warmup_repair：热身错误或不明确后最多展示一次短修正提示，然后进入变体练习。
- variant_practice：展示 `code_blank`、`fix_bug`、`explain_code`、`implement_function` 或 `review_ai_patch` 变体题。
- error：队列加载失败不影响工作台；seed bank rescue 失败展示 `REVIEW_SEED_BANK_GENERATION_FAILED` 和重试入口；提交失败不得把复习项标记完成。
- disabled：未选择复习项时禁用运行/提交。
- confirm：退出未提交复习时确认是否保留当前编辑内容。

## 页面 3：`NotesPage`

### 组件树

```text
NotesPage
  NotesLanguageTree
    LanguageGroup
    KnowledgePointNoteItem
  MarkdownNoteEditor
    NoteTitleBar
    MarkdownTextarea
    NoteSaveStatus
  NoteContextPanel
    KnowledgePointSummaryCard
    RelatedSessionCard
    AgentAssistCard
```

### 核心行为

- 按学习目标语言组织一级标题，按笔记创建时所在学习会话标题组织二级标题。
- 读取和编辑当前知识点的 Markdown 笔记。
- 学习会话和复习会话引用同一份知识点笔记。
- Agent 只能辅助补全笔记，不自动生成完整笔记。
- 不创建独立复盘草稿、题解草稿或面试讲述草稿流程。

### 按钮行为

| 按钮 | API / 行为 | 约束 |
|---|---|---|
| 新建笔记 | `POST /api/notes` | 当前知识点允许创建空笔记 |
| 保存笔记 | `PATCH /api/notes/{note_id}` | Markdown 内容可为空但必须绑定知识点 |
| Agent 辅助补全 | 后端笔记辅助能力或会话内 Agent 消息 | 必须基于当前会话、代码、测试结果和用户已有笔记 |
| 返回学习 | 跳回来源学习或复习会话 | 不丢失未保存内容 |

## 全局组件：`NoteDrawer`

### 组件树

```text
NoteDrawer
  NoteDrawerHeader
  MarkdownNoteEditor
  AgentAssistNoteAction
  NoteSaveStatus
```

### 行为边界

- 学习或复习会话中均可打开，且必须能追溯到当前知识点。
- 关闭抽屉前自动保存，展示 `未保存`、`保存中`、`已保存` 或 `保存失败`。
- 保存失败时不静默关闭，必须保留本地编辑内容并提示重试。
- Agent 可基于当前会话辅助补全笔记，但不得虚构测试结果或替用户生成完整笔记。

## 页面 4：`SettingsPage`

### 组件树

```text
SettingsPage
  SettingsCategoryTabs
  AppearanceSettingsPanel
  ModelSettingsPanel
  LearningPreferencePanel
  ReviewSettingsPanel
  NotificationSettingsPanel
  RecordsPrivacyPanel
  AboutDiagnosticsPanel
  SettingsActionBar
```

### 设置分类

| 分类 | 第一版功能 |
|---|---|
| 外观 | 主题、视觉密度、侧栏、字号或动效 |
| 模型设置 | 用户 API 配置、提示模型、错因解释模型、笔记辅助模型 |
| 学习偏好 | 讲解深度、提示风格、是否鼓励先自己尝试 |
| 复习 | 高风险阈值、普通打开是否只提示、复习优先策略说明 |
| 通知设置 | 学习提醒、复习提醒、桌面通知开关 |
| 记录与隐私 | 展示、导出、清理本地记录；不控制 Attempt 是否写入 |
| 关于与诊断 | 版本、API base URL、后端状态、runner 状态、诊断日志 |

### API

- 读取：`GET /api/users/{user_id}`
- 保存：`PATCH /api/users/{user_id}/preferences`

### 禁止配置

- 设置页不允许修改后端固定评分规则。
- 设置页不允许关闭或改变 `Attempt` 必填事实记录。
- 设置页不允许修改 FSRS 固定规则或直接写入 `due_at`。

### 状态

- dirty：表单修改未保存。
- saving：保存中禁用重复提交。
- saved：展示保存成功时间。
- error：字段级错误优先展示，未知错误进入全局 toast。

## Tauri 与 API 边界

### Tauri 负责

- 窗口创建、窗口尺寸、系统托盘或基础菜单。
- 本地文件选择、复制到剪贴板、导出用户笔记或诊断日志。
- 安全存储轻量本地配置，如 API base URL、最近窗口尺寸。
- 承载 webview/iframe 预览容器和基础 CSP。

### API / 后端负责

- `LearningPlan`、`KnowledgePoint`、`Exercise`、`Attempt`、`ReviewState` 的事实写入。
- `learning_stage`、`learning_stage_state`、`learning_messages` 和学习历史过滤由后端负责。
- LangGraph 状态机编排：Onboarding / Learning / Review / Resume / Notes Assist。
- runner service：运行、测试、stdout/stderr、timeout、unsupported。
- `code_completion_result` 评分、JSON 校验、FSRS Rating 映射。
- `due_at`、`forget_risk`、复习队列计算。

### 前端禁止越界

- 不直接调用 LLM API 生成最终评分。
- 不本地修改 `fsrs_rating`、`due_at` 或 `ReviewState`。
- 不根据 warmup 结果、本地测试通过或 `review_ai_patch` 表单内容本地计算 score、FSRS 或复习完成态。
- 不把本地预览成功当作 `/submit` 通过。
- 不在 Java/C++ 上展示“可运行”按钮，除非后端明确返回可用 `runtime_profile`。

## 全局状态与错误处理

| 状态类型 | 使用位置 | 规范 |
|---|---|---|
| loading | 页面初始化、生成计划草稿、运行、提交、笔记辅助补全 | 局部 skeleton 优先，避免整页阻塞 |
| empty | 无计划、无复习、无笔记 | 给出下一步按钮 |
| error | API、runner、LLM 输出校验、写库失败 | 显示 `error.code` 和可恢复动作 |
| disabled | 输入不足、API 离线、runtime unsupported、提交中 | tooltip 或行内说明原因 |
| confirm | 破坏主干调整、离开未保存笔记、结束未提交会话、清理记录 | 明确后果与取消路径 |
| stale | 代码修改后旧测试结果仍显示 | 标记“结果来自上一次运行” |
| autosaving | 知识点 Markdown 笔记 | 展示保存中/已保存/失败重试 |

## API 到组件映射

| API | 主要组件 | 前端使用方式 |
|---|---|---|
| `GET /api/dashboard` | `WorkspaceTopStatusBar` | 初始化当前学习、复习提示与恢复入口 |
| `POST /api/onboarding/messages` | `OnboardingPage`、`GeneratedLearningRouteCard` | 多轮引导；信息足够时流式输出 `show_learning_route` 卡片 |
| `POST /api/onboarding/{session_id}/confirm_plan` | `GeneratedLearningRouteCard` | 仅由最新卡片的 `开始学习` 确认正式计划 |
| `PATCH /api/plans/{plan_id}/modules/{module_id}` | `RoutePanel` | 跳过、替换、调整模块 |
| `POST /api/learning-sessions/start` | `LearningWorkspacePage`、`GeneratedConceptIntroCard` | 创建或恢复学习会话；概念阶段允许 `exercise=null`，新会话返回持久化 `initial_tool_calls` |
| `POST /api/learning-sessions/{session_id}/messages` | `ConversationTimeline`、`GeneratedConceptCheckResultCard`、`GeneratedCodeExerciseCard`、`GeneratedLearningHistoryCard` | 概念判断、修正追问、练习确认和学习页工具卡片 |
| `GET /api/learning-sessions/history` | `GeneratedLearningHistoryCard` | 按知识点读取所有学习页会话历史，不包含建档页或复习页 |
| `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/run` | `RunActionBar`、`GeneratedRuntimeFeedback` | 展示运行、预览或测试反馈；前端不暴露内部 Attempt 类型 |
| `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/submit` | `RunActionBar`、`ExplanationCheckPanel` | 获取 `code_completion_result`；前端不暴露内部 Attempt 类型 |
| `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/hint` | `AssistantSidePanel` | 获取分层提示 |
| `POST /api/learning-sessions/{session_id}/attempts/{attempt_id}/explain-error` | `ErrorFeedbackPane` | 获取错因解释 |
| `POST /api/learning-sessions/{session_id}/attempts/{attempt_id}/check-explanation` | `ExplanationCheckPanel` | 检查用户解释 |
| `GET /api/reviews/today` | `ReviewQueuePanel` | 获取待复习列表 |
| `POST /api/reviews/start` | `ReviewWarmupCard`、`ReviewExercisePanel` | 创建或恢复复习会话；渲染热身、阶段状态、seed 变体和 rescue 错误 |
| `POST /api/reviews/{session_id}/warmup-result` | `ReviewWarmupCard`、`ReviewExercisePanel` | 记录热身结果并切换到修正或变体练习；不更新 FSRS 展示 |
| `POST /api/reviews/{session_id}/exercise-result` | `ReviewAIPatchPanel`、`ReviewMetricPanel` | 提交变体练习或 AI 补丁审核，使用后端返回更新 FSRS 展示 |
| `GET /api/notes` | `NotesPage`、`NoteDrawer` | 读取知识点 Markdown 笔记 |
| `POST /api/notes` | `NotesPage`、`NoteDrawer` | 创建知识点笔记 |
| `PATCH /api/notes/{note_id}` | `NotesPage`、`NoteDrawer` | 保存知识点笔记 |

## 完成标准

- 五个一级页面均有组件树、核心按钮、状态与 API 边界：Onboarding、Learning、Review、Notes、Settings。
- 工作台明确对话生成式代码编辑器、实时预览、stdout/test、错误反馈区边界。
- JS/HTML/CSS、Python、Java/C++ 的运行能力分层不会误导用户。
- loading、empty、error、disabled、confirm、stale、autosaving 状态均有统一处理。
- 前端不会越权承担评分、FSRS 或 LangGraph 状态机职责。
- 复习页能展示短热身、热身修正、seed rescue 失败、五类核心复习题型和 `review_ai_patch` 结构化提交。
