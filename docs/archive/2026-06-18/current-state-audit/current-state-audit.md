# Aearn 当前状态审计

> **历史快照，非当前 source of truth。** 本文生成于 2026-06-18，描述已经被 Tutor Harness 替代的旧运行时。当前事实请从 [`../../../README.md`](../../../README.md) 路由。

生成日期：2026-06-18
范围：当前 checkout 的 `aearn/` runtime、`docs/` source-of-truth、测试、脚本和 Trellis 任务 `06-18-current-project-docs-regeneration`。

本文是 2026-06-18 历史状态审计文档包入口。它不替代 `docs/README.md` 中列出的 source-of-truth 文档，只给出基于当前代码重读后的面试/接手视角。

## 文档包

| 文档 | 用途 |
|---|---|
| `project-overview-interview.md`（原审计清单曾引用，但当前归档中不存在） | 面试项目叙事、价值点、技术亮点和不能过度宣称的边界 |
| `architecture-current.md` | 当前前端、后端、Agent、数据库、runner、SSE 和运维结构 |
| `core-flows-current.md` | Onboarding、学习、复习、笔记、设置、dashboard/resume 的跨层流程 |
| `agent-evaluation-review-current.md` | Agent/LangGraph、代码运行与评分、FSRS/review batch 和能力边界 |
| `demo-qa-script.md` | 本地启动、演示脚本、验证命令和面试 Q&A 提纲 |

## 状态术语

| 术语 | 含义 |
|---|---|
| Implemented | 当前代码与测试能支撑该能力 |
| Partially implemented | 有当前代码支撑，但配置、覆盖、体验或运行条件有限 |
| Documented / planned | 文档有规格或计划，当前代码证据不足 |
| Stale risk | 现有文档与当前代码或配置存在漂移风险，需要后续单独治理 |
| Out of scope | 不属于本次文档包或当前产品边界 |

## 当前实现总览

| 领域 | 当前判断 | 证据 |
|---|---|---|
| Runtime 根目录 | Implemented | 正式运行代码集中在 `aearn/`，根目录用于 Git、Trellis、docs 和 agent 配置 |
| Backend API | Implemented | `aearn/services/api/app/main.py` 注册 `health`、`users`、`courses`、`environment`、`dashboard`、`plans`、`learning_sessions`、`reviews`、`onboarding`、`notes` |
| Desktop frontend | Implemented | `aearn/apps/desktop/src/pages/`、`features/learning/`、`components/`、`stores/`、`hooks/` 已拆分，不是静态 prototype |
| Shared package | Partially implemented | `aearn/packages/shared/README.md` 仍是 shared contracts placeholder，当前主要类型在 frontend `types.ts` 和 backend Pydantic models |
| 数据库 | Implemented | `aearn/services/api/app/db/schema.sql` 覆盖 users、plans、knowledge_points、exercises、attempts、review_states、review_logs、notes、grounding、conversation messages |
| Celery worker | Partially implemented | `aearn/services/worker/aearn_worker/worker_app.py` 有 `health.ping`、`review.refresh_due_counts`、`review.generate_seed_bank`，但 `services/worker/README.md` 仍写 placeholder |
| LangGraph | Partially implemented | onboarding/learning/review graph 模块和测试存在，但 `LANGGRAPH_ENABLED` 默认 `false`，服务层仍保留 imperative fallback |
| Agent SDK | Partially implemented | `aearn/services/api/app/agents/**` 覆盖 onboarding、learning、review、notes、runtime、tooling；真实模型依赖 `.env` LLM 配置 |
| SSE | Implemented | backend `services/streaming/` 和 frontend `hooks/useSSE.ts` 支持 `agent_message`、`tool_status`、`tool_call`、`runner_result`、`evaluation_result`、`done`、`error` |
| Runner registry | Implemented | `language_capabilities.py` 和 `runner_registry.py` 明确 public language 与 runtime tier |
| Review/FSRS | Implemented | `review_scheduler.py`、`review_repository.py`、`review_seed_bank.py` 负责 ReviewState、ReviewLog、review batch 和 seed bank |
| Local operations | Implemented | `aearn/scripts/start-dev.ps1` 管理 Docker、DB bootstrap、API、worker、desktop；`aearn/package.json` 暴露 `dev`、`dev:status`、`desktop:check` |

## 公开语言与运行能力边界

当前公开课程语言来自 Pydantic `Language`、DB CHECK 约束和 `PUBLIC_COURSE_LANGUAGE_MAP`：

| 公开语言 | 当前运行路径 | 状态 |
|---|---|---|
| `javascript` | `browser_preview` | Implemented |
| `python` | `python_stdout_test` | Implemented |
| `typescript` | `node_typescript_test` | Implemented，依赖本机 Node/TypeScript |
| `sql` | `sql_query_test`，SQLite 教学方言 | Implemented |
| `java` | `managed_compiled_test` | Partially implemented，本机 teaching-grade 单练习，不是 Maven/Gradle/项目级沙箱 |
| `go` | `managed_compiled_test` | Partially implemented，本机 teaching-grade 单练习 |
| `csharp` | `managed_compiled_test` | Partially implemented，本机 teaching-grade 单练习 |
| `html_css` | HTML/CSS browser preview | Implemented |

`cpp` 和 `rust` 当前不是公开课程选择。它们在 runtime/capability 层是 planned/non-public 边界，不能在面试或文档里说成“当前支持 C++/Rust 编译运行”。

## 旧文档归档/回写决策

结论：本轮没有发现需要整篇移动到 `docs/archive/<date>/` 的 active 文档。旧文档问题主要是局部漂移，优先回写仍在被引用的 source-of-truth；带日期的 demo/release 文档按历史快照保留。

| 文档 | 决策 | 当前证据 | 处理状态 |
|---|---|---|---|
| `docs/setup/development-environment.md` | 回写，不归档 | `.env.example`、`core/config.py`、`start-dev.ps1` 和 worker 默认值都使用 `127.0.0.1`，旧文档仍有 `localhost` 连接串 | 已回写为 `127.0.0.1`，日期更新到 2026-06-18 |
| `aearn/services/worker/README.md` | 回写，不归档 | `worker_app.py` 已注册 `health.ping`、`review.refresh_due_counts`、`review.generate_seed_bank`，旧 README 仍写 placeholder | 已回写当前 worker 任务表 |
| `docs/README.md` | 回写，不归档 | 文档新鲜度仍停在 2026-05-24，当前已有 6 月 language boundary、runner、review batch、graph hardening 和 2026-06-18 状态审计包 | 已补 2026-06-18 current audit 记录 |
| `docs/architecture/api-contract.md` | 后续局部回写，不整篇归档 | 文档体量大，既包含已实现接口，也包含未注册或后置接口，例如 `GET /api/language-courses/{course_id}/exercises`、`POST /api/learning-sessions/{session_id}/finish`、`GET /api/knowledge-points/{id}/review-metrics`；`/api/code-drafts/*` 已在文内标为不属于 Draft V1.1 主流程 | 暂不改动；后续应拆清 Implemented 与 Documented / planned |
| `docs/product/frontend-interaction-spec.md` | 后续局部回写，不整篇归档 | 仍有结束会话等 API 交互描述需要和当前 route registry 对账，但主要页面和交互边界仍可作为 source-of-truth | 暂不改动；应与 API contract 同步刷新 |
| `docs/qa/learning-graph-runtime-demo-story.md` | 保留，不归档 | 文档已明确 `LANGGRAPH_ENABLED=false` 时不调用 graph；它是 demo story，不是默认 runtime 承诺 | 保留 |
| `docs/qa/agent-capability-hardening-demo-story.md` | 保留，不归档 | 作为 Agent capability demo 快照仍有用，Java/Go/C# teaching-grade 边界与当前能力一致 | 保留 |
| `docs/qa/sdk-agent-release-readiness.md` | 保留为历史门禁，不回写成当前态 | 文件日期是 2026-05-24，更适合作为当时 SDK Agent 收口证据 | 保留；若未来不再引用，再归档 |
| `docs/setup/claude-frontend-handoff.md` | 保留，不归档 | 这是外部代码助手 handoff 模板，不替代 source-of-truth；当前命令已使用 `127.0.0.1` | 保留 |
| `docs/plans/learning-agent-implementation-plan.md` | 保留，不归档 | 仍承接基线和 post-MVP 工作队列；不应因为局部状态漂移整篇归档 | 后续路线变更时更新 |
| `docs/design/learning-agent-claude-desktop-framework.html` | 受保护保留，不归档 | 用户设计的主原型，不是 runtime 代码；仓库规则要求不能删除或替换 | 保留 |
| `aearn/packages/shared/README.md` | 保留 placeholder，不归档 | shared package 还未成为真实跨 runtime contract source；当前合同仍主要在 docs、backend models 和 frontend types | 等 shared contracts 真正落地后再回写 |

## 仍需跟踪的 Stale Risk

| 风险点 | 当前证据 | 建议 |
|---|---|---|
| API contract 与 route registry 不是一一对应 | 当前 route 文件没有若干文档中出现的 planned/deferred endpoint | 做一次 API source-of-truth 刷新，按 Implemented / Documented / planned 分组 |
| Dynamic plan generation 与 fallback 边界复杂 | `PLAN_GENERATION_ENABLED`、LLM provider、`EXA_API_KEY`、authoritative docs coverage 共同影响行为 | Demo 前明确是否配置真实模型；无模型时只演示 deterministic/local flow |

## 面试项目理解优先级

1. 产品闭环：本地桌面 Agent 帮用户从建档、生成学习路线、概念学习、代码练习、运行反馈、复习调度到笔记沉淀。
2. 架构边界：frontend 展示和交互，FastAPI/service/repository 写库和响应，runner registry 处理语言能力，Agent/LangGraph 只输出受控 intent。
3. 可靠性设计：hidden tests 不泄露、idempotency、SSE terminal event、unsupported runtime 明示、review/FSRS 后端拥有。
4. 当前限制：C++/Rust 不公开，Java/Go/C# 不是项目级沙箱，LangGraph 默认关闭，真实 LLM/动态路线需要 `.env` 配置。
