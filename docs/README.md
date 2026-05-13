# Aearn 文档索引

本目录只保留实施 MVP 所需文档。修改流程或产品边界时，先改 `product/user-flows.md`，再同步交互、API、状态机、数据库、验收和实施计划。

## 必要文档

| 类型 | 文档 | 用途 |
|---|---|---|
| 产品源文档 | `product/user-flows.md` | 用户流程和 MVP 边界的 source of truth |
| 前端规格 | `product/frontend-interaction-spec.md` | React + Tauri 页面、组件、状态和交互边界 |
| API 契约 | `architecture/api-contract.md` | 前后端、runner service、LangGraph 和 mock/契约测试对接 |
| 数据库 | `architecture/database-schema.md` | PostgreSQL 表、约束、索引和 migration 顺序 |
| Agent 状态机 | `architecture/langgraph-state-machine.md` | LangGraph 图、节点、条件边和写库时机 |
| 评分规则 | `architecture/code-completion-evaluation-spec.md` | 代码补全评分、Prompt、Attempt 判定和 FSRS rating 映射 |
| 复习调度 | `architecture/fsrs-scheduling-spec.md` | FSRS 调度、ReviewState、ReviewLog 和 Celery 任务 |
| 验收测试 | `qa/acceptance-test-plan.md` | API、Agent 输出、FSRS、前端手工 QA 的完成标准 |
| 环境配置 | `setup/development-environment.md` | Milestone 0 前置环境、依赖服务和验收命令 |
| 实施计划 | `plans/learning-agent-implementation-plan.md` | 任务级实施计划、开发顺序和审查步骤 |
| 主原型 | `design/learning-agent-claude-desktop-framework.html` | 用户设计的受保护前端原型，不能删除；作为 UI 视觉和桌面端布局参考 |

## 已移除的重复文档

- `specs/2026-04-25-learning-agent-design-v1.md`：母版草案，已由 `user-flows.md`、`frontend-interaction-spec.md` 和实施规格承接。
- `architecture/api-design.md`：API 草案，已由 `api-contract.md` 承接。
- `architecture/data-model.md`：概念数据模型，已由 `database-schema.md` 和 `api-contract.md` 承接。
- `architecture/agent-memory-design.md`：概念记忆设计，已由 `langgraph-state-machine.md` 承接。
- `product/desktop-ia-and-layout.md`：IA 草案，已由 `frontend-interaction-spec.md` 承接。
- `documentation-roadmap.md`：文档补齐路线图，当前阶段已完成，后续以本索引和实施计划为准。
