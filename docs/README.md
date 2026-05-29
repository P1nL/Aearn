# Aearn 文档索引

本目录保留第一版稳定基线和 post-MVP / v1.1 增强所需文档。第一版 MVP 已在 `../.trellis/tasks/archive/2026-05/05-18-05-18-release-readiness/release-report.md` 判定为 `ready to release`；后续功能可以脱离最小 MVP 切片，但不得破坏 `Attempt`、FSRS、hidden tests、模型失败映射、source attribution 和文档 source-of-truth 边界。

修改流程或产品边界时，先改 `product/user-flows.md`，再同步交互、API、状态机、数据库、验收和实施计划。新功能文档必须明确标注它属于第一版基线修复，还是 post-MVP / v1.1 增强。

## 必要文档

| 类型 | 文档 | 用途 |
|---|---|---|
| 产品源文档 | `product/user-flows.md` | 用户流程、第一版基线和 post-MVP 边界的 source of truth |
| 前端规格 | `product/frontend-interaction-spec.md` | React + Tauri 页面、组件、状态和交互边界 |
| API 契约 | `architecture/api-contract.md` | 前后端、runner service、LangGraph 和 mock/契约测试对接 |
| 数据库 | `architecture/database-schema.md` | PostgreSQL 表、约束、索引和 migration 顺序 |
| Agent 状态机 | `architecture/langgraph-state-machine.md` | LangGraph 图、节点、条件边和写库时机 |
| 评分规则 | `architecture/code-completion-evaluation-spec.md` | 代码补全评分、Prompt、Attempt 判定和 FSRS rating 映射 |
| 复习调度 | `architecture/fsrs-scheduling-spec.md` | FSRS 调度、ReviewState、ReviewLog 和 Celery 任务 |
| 验收测试 | `qa/acceptance-test-plan.md` | API、Agent 输出、FSRS、前端手工 QA 的完成标准 |
| 环境配置 | `setup/development-environment.md` | 本机环境、模型配置、动态路线生成配置、依赖服务和验收命令 |
| 实施计划 | `plans/learning-agent-implementation-plan.md` | 第一版基线、post-MVP 工作队列、开发顺序和审查步骤 |
| 主原型 | `design/learning-agent-claude-desktop-framework.html` | 用户设计的受保护前端原型，不能删除；作为 UI 视觉和桌面端布局参考 |

## 辅助对接文档

| 类型 | 文档 | 用途 |
|---|---|---|
| 新人接手指南 | `setup/newcomer-onboarding-guide.md` | 面向首次接手仓库或学习项目的人，串联项目定位、代码地图、运行命令、验证入口和常见坑；不替代 source of truth |
| Claude 前端对接模板 | `setup/claude-frontend-handoff.md` | 给外部代码助手执行 desktop 前端改造时使用的任务入口；不替代上方 source of truth |
| SDK Agent 发布门禁 | `qa/sdk-agent-release-readiness.md` | SDK Agent 收口矩阵、验证命令结果和剩余风险；不替代验收测试总计划 |

## 当前阶段

- 第一版基线：已完成 release readiness，结论见 `../.trellis/tasks/archive/2026-05/05-18-05-18-release-readiness/release-report.md`。
- Post-MVP / v1.1 当前增强：动态学习路线生成、官方 DeepSeek provider 接入、练习卡 UI 直观性优化。
- 新增强不再受“只能做最小 MVP 闭环”的限制，但仍必须保留第一版基线契约：`PlanDraft` 结构、latest-card-wins、前端不暴露内部 `Attempt` 类型、后端拥有评分/FSRS 决策、模型失败不泄露 provider 细节。
- 动态路线生成不能单独承诺任意语言公开支持；新增语言必须同步扩展 `Language` 枚举、数据库约束、课程 catalog、runtime boundary、API 示例和验收用例。

## 文档新鲜度

2026-05-24 已完成一轮 `docs/` 新鲜度审计：当前没有需要整篇归档的 active 文档；`setup/development-environment.md` 和 `setup/claude-frontend-handoff.md` 已修正局部过期内容。后续如出现整篇过期文档，应移动到 `docs/archive/<date>/`，并在本索引标注替代入口。

## 已移除的重复文档

- `specs/2026-04-25-learning-agent-design-v1.md`：母版草案，已由 `user-flows.md`、`frontend-interaction-spec.md` 和实施规格承接。
- `architecture/api-design.md`：API 草案，已由 `api-contract.md` 承接。
- `architecture/data-model.md`：概念数据模型，已由 `database-schema.md` 和 `api-contract.md` 承接。
- `architecture/agent-memory-design.md`：概念记忆设计，已由 `langgraph-state-machine.md` 承接。
- `product/desktop-ia-and-layout.md`：IA 草案，已由 `frontend-interaction-spec.md` 承接。
- `documentation-roadmap.md`：文档补齐路线图，当前阶段已完成，后续以本索引和实施计划为准。
