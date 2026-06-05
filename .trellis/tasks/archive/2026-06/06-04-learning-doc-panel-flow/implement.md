# 实施计划：学习页文档面板、流程改进与复习侧栏修复

## 执行原则

- 当前截图问题优先：先修复复习侧栏到期/未到期语义。
- 每个 phase 必须可独立验证。
- 不凭前端本地状态伪造 `ReviewState`、`due_at`、评分或完成态。
- 不新增历史教程目录引用；所有运行代码进入 `aearn/`。
- 后端命令从 `aearn/services/api` 运行，前端命令从 `aearn/` 或 `aearn/apps/desktop` 运行。

## Phase 0: 复习侧栏到期状态修复

### 目标

完成学习后，左侧复习栏可以显示该知识点，但如果 `due_at` 在未来，必须禁用点击并显示未到期状态。

### 后端步骤

1. 修改 `aearn/services/api/app/services/repositories/plan_repository.py`。
2. 在 `get_plan_detail()` 查询知识点时 LEFT JOIN 或额外查询 `review_states`。
3. 扩展 `_serialize_knowledge_point()`，返回可选字段：
   - `review_state.due_at`
   - `review_state.is_due`
   - `review_state.label`
4. 使用后端时钟计算 `is_due`，不要让前端自行判断。
5. 保持旧字段兼容，现有前端 `CreatedPlanResponse` 不应破坏。

### 前端步骤

1. 修改 `aearn/apps/desktop/src/types.ts`，为 `CreatedKnowledgePoint` 添加可选 `review_state`。
2. 修改 `aearn/apps/desktop/src/api.ts` 的 `isCreatedPlanResponse` / 知识点 guard，如有必要补 `isReviewStatePreview`。
3. 修改 `aearn/apps/desktop/src/components/SidebarNav.tsx`：
   - 复习项仍包含 `reviewing/mastered`。
   - `review_state.is_due === true` 才渲染为可点击按钮。
   - `is_due === false` 或缺少 `review_state` 渲染为禁用项。
   - 禁用项不调用 `onRouteChange("review")`。
4. 修改 `aearn/apps/desktop/src/styles.css`：
   - 添加 disabled/upcoming 样式。
   - 提供明显但不刺眼的状态文案。

### 验证

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_onboarding_m2.py tests/test_reviews_m4.py
pnpm --dir .\aearn desktop:check
```

手工验收：

- 刚学完知识点后，复习栏显示 `未到期 · 下次 MM-DD HH:mm`。
- 未到期项点击无跳转、无请求、无错误 toast。
- 到期项仍可点击进入复习页并开始复习。

## Phase 1: 学习文档读取 API

### 目标

为当前知识点提供结构化文档 payload，前端可在右侧面板展示。

### 后端步骤

1. 在 `aearn/services/api/app/models/learning_sessions.py` 添加：
   - `KnowledgePointDocumentationResponse`
   - `DocumentationSection`
   - `DocumentationCodeBlock`
   - `DocumentationReference`
2. 在 `aearn/services/api/app/services/repositories/learning_session_repository.py` 添加读取函数：
   - 校验 user/knowledge point 权限。
   - 读取 `knowledge_points`、`plan_modules`、`language_courses`、`lesson_outline_json`、`lesson_sources_json`。
   - 如果缺少 lesson outline，复用 `_ensure_lesson_content()` 或等价逻辑补齐。
   - 返回 5 个标准 section；MVP 可以由现有 lesson outline/chunks 组装，不强依赖 LLM。
3. 在 `aearn/services/api/app/routes/learning_sessions.py` 添加：
   - `GET /api/learning-sessions/knowledge-points/{knowledge_point_id}/documentation?user_id=...`
4. 如果实现 Redis 24h 缓存：
   - 新建窄作用域 cache helper，使用 `Settings.redis_url`。
   - 缓存不可用不应污染文档事实；按设计决定是无缓存继续生成，还是返回可恢复错误。
5. 如加入 LLM 润色：
   - 复用 `OpenAICompatibleClient` 或 Agents SDK runtime。
   - 模型不可用必须返回 `MODEL_UNAVAILABLE`。
   - 输出必须通过 teaching guardrails，不得泄露 prompt、hidden tests 或 secrets。

### 验证

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py
```

新增测试覆盖：

- 成功返回 5 个标准 section。
- 知识点不存在返回 `KNOWLEDGE_POINT_NOT_FOUND`。
- 其他用户不能读取不属于自己的知识点。
- 文档 payload 不包含 hidden tests、solution references、provider payload。

## Phase 2: 前端文档面板 MVP

### 前端步骤

1. 修改 `aearn/apps/desktop/src/types.ts`：
   - 添加文档 response 类型。
2. 修改 `aearn/apps/desktop/src/api.ts`：
   - 添加 `fetchKnowledgePointDocumentation(userId, knowledgePointId, signal?)`。
   - 添加 payload guard，失败时报明确错误。
3. 新建 `aearn/apps/desktop/src/components/DocumentationPanel.tsx`：
   - loading / ready / error 状态。
   - 目录导航。
   - 整体折叠按钮。
   - 独立滚动。
4. 新建 `aearn/apps/desktop/src/components/DocSection.tsx`：
   - 默认展开 `core_concept`、`syntax`、`examples`。
   - 默认折叠 `common_mistakes`、`best_practices`。
   - 渲染 Markdown-like 文本和代码块，先不引入新依赖。
5. 修改 `aearn/apps/desktop/src/pages/LearningWorkspacePage.tsx`：
   - active session 存在时显示文档面板。
   - 传入 userId 和 knowledgePointId。
6. 修改 `aearn/apps/desktop/src/styles.css`：
   - 两栏布局。
   - 文档面板宽度 420px。
   - 小屏幕至少不遮挡主对话。

### 验证

```powershell
pnpm --dir .\aearn desktop:check
```

手工验收：

- 进入知识点后右侧出现文档面板。
- 文档加载失败时有局部错误和重试。
- 切换知识点后文档刷新。

## Phase 3: 主动触发概念检验

### 后端步骤

1. 在 `aearn/services/api/app/models/learning_sessions.py` 添加 `TriggerConceptCheckRequest`。
2. 在 `learning_session_repository.py` 添加 `trigger_learning_session_concept_check()`：
   - 读取 active learn session。
   - 校验 user_id。
   - 基于 knowledge point、lesson outline、lesson sources 调用现有 `build_sdk_concept_intro()`。
   - 更新 `learning_stage='concept_check'`。
   - 写入 `learning_stage_state_json.active_concept_intro` / `active_concept_check`。
   - 写入或返回对应 `show_concept_intro` tool call。
3. 在 `routes/learning_sessions.py` 添加：
   - `POST /api/learning-sessions/{session_id}/trigger-concept-check`
4. 调整 `start_learning_session()`：
   - 新 session 不再自动生成 initial concept tool call。
   - 返回引导性 `initial_agent_message`。
   - 初始 stage 推荐设为 `documentation_reading`。
5. 如果使用 `documentation_reading`：
   - 更新 `aearn/services/api/app/db/schema.sql` 的 CHECK。
   - 更新后端/前端 `LearningStage` 类型。
   - 更新 docs/API contract。
   - 更新 learning graph/tool transition，确保可进入 `concept_check`。

### 前端步骤

1. 新建 `aearn/apps/desktop/src/components/ConceptCheckTrigger.tsx`。
2. 在 `LearningWorkspacePage.tsx` 中：
   - 文档未加载完成时禁用按钮。
   - 点击按钮调用 trigger API。
   - 把返回的 `tool_call` 注入对话流。
   - 防止重复触发。
3. 保持 existing `ConceptIntroToolUI` 作为渲染入口，不新增重复 tool UI。

### 验证

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py
pnpm --dir .\aearn desktop:check
```

手工验收：

- 进入知识点不自动显示概念判断卡。
- 文档加载完成后按钮可点。
- 点击后出现概念判断卡。

## Phase 4: 文档引用到对话

### 前端步骤

1. 在 `DocSection.tsx` 支持：
   - 文本选中。
   - 代码块引用按钮。
   - 最多引用 500 字符。
2. 在 `DocumentationPanel.tsx` 上抛 `onReference(text, source)`。
3. 在 `LearningWorkspacePage.tsx` 中将引用文本写入 composer。
   - 优先通过 assistant-ui 支持的受控输入能力。
   - 如果只能 DOM 填充，必须封装成窄函数并加注释说明限制。
4. 引用模板：

```text
引用文档：
> ...

我的问题是：
```

### 验证

- 选中文档文字后出现引用按钮。
- 点击后输入框获得焦点并填入引用。
- 引用不自动发送，用户仍可编辑。

## Phase 5: 练习反馈消息顺序修复

### 步骤

1. 修改 `aearn/apps/desktop/src/pages/LearningWorkspacePage.tsx`。
2. 将 `resumeExerciseMessage` 条件从：

```ts
session && session.exercise && !hasExerciseToolMessage
```

改为：

```ts
session && session.exercise && !hasExerciseToolMessage && messages.length === 0
```

3. 如发现新文档/触发按钮消息会影响恢复场景，补充更精确的 helper：
   - `shouldInjectResumeExerciseMessage(session, messages, hasExerciseToolMessage)`

### 验证

- 运行测试反馈显示在练习卡片下方。
- 提交反馈显示在练习卡片下方。
- 进入已解锁但无历史消息的会话仍能看到练习卡片。

## Phase 6: 收口验证

后端最小验证：

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py tests/test_reviews_m4.py
```

前端最小验证：

```powershell
pnpm --dir .\aearn desktop:check
```

Trellis 验证：

```powershell
python .\.trellis\scripts\task.py validate .\.trellis\tasks\06-04-learning-doc-panel-flow
git diff --check
```

手工 smoke：

1. 完成一个知识点学习。
2. 复习栏显示未到期禁用项，点击无跳转。
3. 进入新知识点学习页。
4. 文档面板加载并可折叠。
5. 引用文档到对话。
6. 主动触发概念检验。
7. 解锁练习后运行/提交，反馈顺序正确。

## 风险点

- `documentation_reading` 会触及 DB CHECK、前后端类型和 docs contract；实现时必须一次性补齐。
- 文档生成如直接依赖 LLM，会使本地未配置模型时无法进入学习页；推荐 MVP 先用现有 lesson outline/chunks 组装，LLM 作为后续增强或可恢复错误路径。
- 侧栏复习状态必须以后端 `review_states` 为事实来源，不能只用 `status`。
