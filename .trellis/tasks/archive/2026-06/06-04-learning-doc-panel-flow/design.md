# 技术设计：学习页文档面板、学习流程与复习侧栏一致性

## 目标

本任务包含两个可独立验证的交付面：

1. 修复当前截图暴露的复习侧栏语义：未到期复习项可以展示，但必须禁用点击，并显示未到期或下次复习时间。
2. 改造学习页：新增知识点文档面板，让用户先阅读、提问，再主动触发概念检验，最后进入练习；同时修复练习反馈消息顺序。

当前仓库真实运行目录是 `aearn/`。所有实现必须以 `docs/architecture/api-contract.md`、`docs/product/frontend-interaction-spec.md` 和 `.trellis/spec/` 为准。

## 已确认代码事实

- 后端路由位于 `aearn/services/api/app/routes/`，学习会话路由是 `learning_sessions.py`，不存在 `routes/learning.py`。
- 学习会话持久化和响应组装位于 `aearn/services/api/app/services/repositories/learning_session_repository.py`。
- 当前 `learning_sessions.learning_stage` 数据库 CHECK 只允许 `concept_intro`、`concept_check`、`concept_repair`、`practice_offer`、`concept_qna`、`readiness_check`、`practice_support`。
- 当前新学习会话会立即生成 `show_concept_intro` 初始 tool call，并把 `learning_stage` 写为 `concept_check`。
- LLM 接入是 OpenAI-compatible/DeepSeek 抽象，入口为 `app/services/llm/llm_client.py`、`app/agents/runtime/sdk_runtime.py` 和 `Settings.openai_compatible_configured`；不得在代码或规划中写死 Claude 模型名。
- 课程提纲事实来源已存在：`knowledge_points.lesson_outline_json`、`lesson_sources_json`、`teaching_chunks`。
- `GET /api/plans/{plan_id}` 当前只返回知识点基本字段，不返回 `ReviewState.due_at`。
- 复习今日队列由 `GET /api/reviews/today` 提供，只返回 `review_states.due_at <= now()` 的到期项。
- 侧栏当前只基于 `knowledgePoint.status === "reviewing" || knowledgePoint.status === "mastered"` 展示复习项，无法区分未到期。

## 架构边界

### 后端

新增或修改位置：

- `app/models/learning_sessions.py`：新增请求/响应模型。
- `app/routes/learning_sessions.py`：新增文档读取和主动触发概念检验端点。
- `app/services/repositories/learning_session_repository.py`：新增文档 payload 组装、初始学习阶段调整、主动触发概念检验的持久化逻辑。
- `app/agents/learning/learning_concept_agent.py`：复用现有 `build_sdk_concept_intro` / concept agent 能力，不新增另一个固定模型客户端。
- `app/services/cache/` 或同等窄作用域模块：如实现 Redis 24h 缓存，必须通过 `Settings.redis_url` 接入，并在不可用时返回可诊断错误或回退为无缓存路径。
- `app/services/repositories/plan_repository.py`：为计划详情补充轻量 `review_state`，供侧栏区分到期/未到期。
- `app/db/schema.sql`：如果采用新 `documentation_reading` 阶段，必须同步更新 CHECK 约束。

### 前端

新增或修改位置：

- `aearn/apps/desktop/src/types.ts`：新增文档、触发概念检验、知识点 review_state 类型。
- `aearn/apps/desktop/src/api.ts`：新增 API 调用和运行时 payload guard。
- `aearn/apps/desktop/src/pages/LearningWorkspacePage.tsx`：集成文档面板、触发按钮、引用文本写入 composer、修复 `resumeExerciseMessage` 注入条件。
- `aearn/apps/desktop/src/components/DocumentationPanel.tsx`：新增文档面板。
- `aearn/apps/desktop/src/components/DocSection.tsx`：新增章节渲染、折叠、引用按钮。
- `aearn/apps/desktop/src/components/ConceptCheckTrigger.tsx`：新增主动触发概念检验的对话内卡片。
- `aearn/apps/desktop/src/components/SidebarNav.tsx`：复习项到期/未到期禁用态渲染。
- `aearn/apps/desktop/src/styles.css`：保持现有全局 CSS 体系，不引入 Tailwind/CSS-in-JS。

## 数据契约

### 知识点文档

端点：

`GET /api/learning-sessions/knowledge-points/{knowledge_point_id}/documentation?user_id=...`

推荐响应：

```json
{
  "knowledge_point_id": "kp_...",
  "title": "基本查询 SELECT",
  "summary": "本节解释 SELECT 如何读取表数据。",
  "sections": [
    {
      "id": "core_concept",
      "type": "core_concept",
      "title": "核心概念",
      "content_markdown": "SELECT 是从表中取出列和行的声明。",
      "code_blocks": []
    }
  ],
  "references": [
    { "title": "PostgreSQL SELECT", "url": "https://www.postgresql.org/docs/current/sql-select.html" }
  ],
  "generated_at": "2026-06-04T07:00:00Z",
  "cache_hit": false
}
```

设计约束：

- 文档内容可以先从 `lesson_outline_json`、`lesson_sources_json`、`teaching_chunks` 和知识点描述组装为稳定 MVP。
- 如加入 LLM 润色，必须走现有 OpenAI-compatible 配置，失败时按 API 规范返回 `MODEL_UNAVAILABLE`，不能退回伪装成模型输出的固定教学文案。
- 缓存键必须带知识点 ID；如文档与用户相关，必须带 `user_id`，避免多用户串数据。

### 主动触发概念检验

端点：

`POST /api/learning-sessions/{session_id}/trigger-concept-check`

请求：

```json
{
  "user_id": "user_..."
}
```

响应：

```json
{
  "session_id": "sess_...",
  "learning_stage": "concept_check",
  "learning_stage_state": {},
  "tool_call": {
    "id": "tc_...",
    "name": "show_concept_intro",
    "args": {}
  }
}
```

设计约束：

- 新端点必须校验 session 属于当前用户。
- 触发后才持久化 `active_concept_intro` / `active_concept_check`，并把 `learning_stage` 推进到现有 `concept_check`。
- 如果决定引入 `documentation_reading` 初始阶段，必须同步更新后端模型、前端 `LearningStage`、DB CHECK、API contract 和相关测试。
- 为降低变更面，推荐初始实现新增 `documentation_reading`，但触发后仍复用现有 `concept_check` 阶段和 tool UI。

### 计划详情中的复习状态

扩展 `CreatedKnowledgePoint`：

```json
{
  "id": "kp_...",
  "title": "什么是 SQL",
  "status": "reviewing",
  "review_state": {
    "due_at": "2026-06-05T12:00:00Z",
    "is_due": false,
    "label": "未到期 · 下次 06-05 20:00"
  }
}
```

设计约束：

- `is_due` 必须由后端用同一时钟语义计算，前端只消费事实。
- 前端不得仅凭 `status` 推断可点击。
- 未到期项必须禁用点击，不发送 `POST /api/reviews/start`，不跳转复习页。

## 学习状态机

推荐状态流：

```text
documentation_reading
  -> concept_qna
  -> concept_check
  -> concept_repair
  -> practice_support
```

实现说明：

- `documentation_reading`：首次进入知识点，展示引导文本和文档面板，不自动发送概念判断 tool call。
- `concept_qna`：用户围绕文档提问时可由现有学习对话进入。
- `concept_check`：用户点击「开始概念检验」后进入，返回 `show_concept_intro` tool call。
- `practice_support`：沿用现有练习解锁逻辑。

如实现阶段判断新增 DB 阶段成本过高，允许退化为 `concept_intro` 初始阶段但 `initial_tool_calls=[]`。这种退化必须在 `design.md` 和 tests 中明确，避免把阶段语义误写成已经新增。

## 前端布局

学习页采用两栏布局：

```text
LearningWorkspacePage
  conversation / exercise area
  documentation panel 420px
```

行为：

- 文档面板在有 active learning session 时自动展示。
- 文档面板可整体折叠。
- 文档区域独立滚动，不影响 conversation scroll。
- 文档加载失败显示局部错误和重试，不阻断学习对话。
- 小屏幕本轮只需不崩溃；完整移动抽屉可后续迭代。

## 消息顺序修复

当前问题点在 `LearningWorkspacePage.tsx`：

```ts
const resumeExerciseMessage =
  session && session.exercise && !hasExerciseToolMessage
```

修复设计：

```ts
const resumeExerciseMessage =
  session && session.exercise && !hasExerciseToolMessage && messages.length === 0
```

目的：

- 只在恢复已有 `practice_support` 会话且没有对话消息时注入练习卡片。
- 用户运行/提交后产生的反馈消息不再被练习卡片重新插到末尾上方。

## 复习侧栏设计

侧栏复习项分三类：

- `due`：`review_state.is_due === true`，可点击，进入复习页。
- `upcoming`：有 `review_state.due_at` 但 `is_due === false`，显示但禁用。
- `unknown`：状态为 `reviewing/mastered` 但无 `review_state`，默认禁用并显示「已安排，等待同步」，不能点击。

文案：

- 推荐：`未到期 · 下次 MM-DD HH:mm`
- 降级：`已安排，未到期`

## 测试策略

后端：

- `tests/test_learning_sessions_m3.py`：覆盖新学习会话不自动下发概念 tool call、主动触发后返回 `show_concept_intro`。
- `tests/test_onboarding_m2.py` 或 plan repository 专项：覆盖 `GET /api/plans/{id}` 返回 `review_state`。
- `tests/test_reviews_m4.py`：保留未到期 start 返回 `REVIEW_NOT_DUE`。
- 新增文档端点测试：覆盖 5 个章节、404、模型不可用或缓存路径。

前端：

- `pnpm --dir .\aearn desktop:check`。
- 为 `SidebarNav` 增加可测试 helper 或组件测试：未到期项禁用、到期项可点击。
- 手工 smoke：完成第一个知识点后，侧栏显示未到期禁用项；到期项能从侧栏进入复习页。

## 风险与降级

- 最大风险是一次性改动面过大。实现时应先落 Phase 0 复习侧栏修复，再做学习页文档面板。
- 如 LLM 文档生成不稳定，MVP 可以先使用课程提纲和教学 chunks 组装结构化文档，再将 LLM 润色列为后续增强。
- 新增 `documentation_reading` 会触及 DB CHECK 和 docs contract；若实现成本超过本轮，应明确采用 `concept_intro + no initial_tool_calls` 的兼容路径。
