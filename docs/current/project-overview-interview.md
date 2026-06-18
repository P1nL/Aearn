# 面试向项目概览

生成日期：2026-06-18

## 一句话

Aearn 是一个本地优先的 AI 编程语言学习 Agent：它把“想学什么”转成可执行学习路线，在桌面端引导用户读文档、做代码练习、运行测试、解释错误，并把结果沉淀到复习调度和笔记里。

## 为什么这个项目有面试价值

| 维度 | 可讲点 | 当前状态 |
|---|---|---|
| 产品闭环 | Onboarding 生成学习路线，学习页完成文档阅读、概念检查、练习运行、提交评分，复习页按后端 ReviewState 拉起复习 | Implemented |
| Agent 工程 | Agent 输出不直接改库，而是通过 service/repository 和工具 intent 受控落地 | Partially implemented |
| 本地优先 | 本地 PostgreSQL/Redis、Tauri desktop、本地用户数据导出/重置/删除 | Implemented |
| 运行与评分 | 按语言能力选择 runner，记录 Attempt，隐藏测试只给安全反馈，评分和 FSRS 后端拥有 | Implemented |
| 复习系统 | ReviewState、ReviewLog、review seed bank、warmup、batch finalization、FSRS fallback scheduler | Implemented |
| 流式体验 | POST-based SSE 支持 Agent 消息、tool call、runner_result、evaluation_result、done/error | Implemented |
| 可观测边界 | graph/runtime context、safe redaction、model unavailable 映射、idempotency replay | Partially implemented |

## 推荐面试叙事

### 1. 问题

普通编程学习产品通常只给静态课程，AI 编程时代的问题是：学习者不仅要知道语法，还要学会读官方文档、验证 AI 生成代码、解释错误、识别边界条件，并在遗忘前复习。

### 2. 方案

Aearn 把学习拆成一个可追踪闭环：

| 阶段 | 用户感知 | 系统事实 |
|---|---|---|
| 建档 | 用自然语言说目标、方向和时间 | onboarding conversation、slot extraction、plan draft、source attribution |
| 确认路线 | 看到生成路线卡片并点击 `开始学习` | `LearningPlan`、`PlanModule`、`KnowledgePoint`、初始 `ReviewState` 写入 |
| 学习 | 读右侧文档，触发概念检查，做练习 | `learning_sessions`、`learning_messages`、tool calls、exercise materialization |
| 运行 | 预览或跑可见测试 | runner registry 选择 runtime，写入 `Attempt(run)` |
| 提交 | 后端评分并安排复习 | `Attempt(submit)`、`code_completion_result`、`ReviewState` 更新 |
| 复习 | 热身回忆、变体练习、最终调度 | `review_seed_banks`、review batch state、`ReviewLog` |
| 笔记 | 学习或复习中沉淀笔记 | `notes`、note agent draft |

### 3. 架构亮点

| 亮点 | 面试表述 |
|---|---|
| 前后端边界 | React/Tauri 负责页面状态、流式展示和可见交互；FastAPI/service/repository 是数据和业务 source of truth |
| Agent 安全边界 | Agent 可以生成教学内容、路线、提示和反馈，但评分、FSRS、ReviewState、hidden tests、写库都由后端确定性代码控制 |
| Runner 能力注册表 | 每种语言不是简单开关，而是有 `capability_state`、`execution`、`runner_key`、sandbox disclosure 和 public selection 边界 |
| SSE 体验 | 使用 fetch + readable stream 支持 POST body，不用浏览器 `EventSource`，所以能带 `client_message_id`、`user_id` 和幂等上下文 |
| Review batch | 复习不是一次提交就改长期状态，中间练习先写 session state，最终 batch 聚合后才写 `ReviewState` / `ReviewLog` |
| Local data boundary | 面试时可以强调这是本地学习 Agent，不做多租户 auth，把用户数据导出、重置、删除作为本地隐私功能 |

## 当前最强技术点

| 技术点 | 代码入口 |
|---|---|
| FastAPI 路由聚合 | `aearn/services/api/app/main.py` |
| Onboarding chat + route card + confirm plan | `aearn/services/api/app/routes/onboarding.py`、`aearn/apps/desktop/src/pages/OnboardingPage.tsx` |
| 学习会话和练习运行 | `aearn/services/api/app/routes/learning_sessions.py`、`aearn/services/api/app/services/repositories/learning_session_repository.py` |
| Runner registry | `aearn/services/api/app/services/runners/language_capabilities.py`、`runner_registry.py` |
| 复习候选池和调度 | `aearn/services/api/app/services/repositories/review_seed_bank.py`、`review_repository.py`、`review_scheduler.py` |
| LangGraph 可选编排 | `aearn/services/api/app/agents/graphs/` |
| Desktop app shell/store/pages | `aearn/apps/desktop/src/App.tsx`、`stores/useAppStore.ts`、`pages/` |
| SSE hook | `aearn/apps/desktop/src/hooks/useSSE.ts` |

## 不要过度宣称

| 不应说 | 准确说法 |
|---|---|
| “支持所有语言，包括 C++/Rust 编译运行” | 当前公开语言是 `javascript`、`python`、`typescript`、`sql`、`java`、`go`、`csharp`、`html_css`；C++/Rust 是 planned/non-public |
| “Java/Go/C# 是完整在线沙箱” | 它们是本机 teaching-grade `managed_compiled_test` 单练习 runner，不支持项目级依赖和包管理器 |
| “所有 Agent 流默认走 LangGraph” | Graph 模块和测试已存在，但 `LANGGRAPH_ENABLED` 默认 `false`，默认路径仍可走服务层编排 |
| “动态路线无需配置就可用” | 动态路线依赖 LLM provider、`PLAN_GENERATION_ENABLED`、可选 `EXA_API_KEY` 和 authoritative docs coverage |
| “前端负责评分/复习调度” | 前端只展示响应；评分、FSRS rating、due_at、forget_risk 和 ReviewState 都由后端返回 |

## 面试时可以主动说明的取舍

| 取舍 | 说明 |
|---|---|
| 本地优先而不是 SaaS 多租户 | 面试项目更聚焦 Agent 学习闭环、代码运行和本地隐私，暂不引入 auth/tenant complexity |
| 先做 teaching-grade runner | 能展示真实反馈、hidden test、unsupported boundary，同时避免把不安全的任意代码执行说成生产沙箱 |
| LangGraph 可开关 | 保留服务层稳定路径，graph 作为编排增强逐步接入，降低 Agent runtime 风险 |
| Source attribution | 动态路线和 grounding 强调可信来源，但不把 live web search 暴露成无限 Agent 浏览器 |
| Review batch | 牺牲一点实现复杂度，换来复习结果更稳定，避免一次错误提交立刻污染长期记忆 |
