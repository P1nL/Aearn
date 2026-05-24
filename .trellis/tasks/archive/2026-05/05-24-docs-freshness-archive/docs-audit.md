# Docs Freshness Audit

日期：2026-05-24

## Summary

本轮审计没有发现需要整篇归档的 active source-of-truth 文档。需要处理的是两类局部过期内容：

- `docs/setup/development-environment.md` 仍保留早期规划里的 `migrations/`、`apps/api`、Alembic 和旧 worker 命令。
- `docs/setup/claude-frontend-handoff.md` 的推荐提示词仍带有一次性前端任务目标，不适合作为通用交接模板。

本轮处理方式：

- 保留所有 active/source-of-truth 文档。
- 修正局部过期段落。
- 不移动受保护原型或设计资产。

## Audit Table

| 文件 | 分类 | 结论 |
|---|---|---|
| `docs/README.md` | active-with-updates | 当前文档索引；需继续作为入口，并补充本轮新鲜度审计结果。 |
| `docs/architecture/api-contract.md` | active | API 契约仍是前后端对接 source-of-truth；其中非 MVP code-drafts 已明确标注为后置能力。 |
| `docs/architecture/code-completion-evaluation-spec.md` | active | 评分、runner、Attempt 判定仍被当前后端实现和测试引用。 |
| `docs/architecture/database-schema.md` | active | Schema 仍匹配当前 `schema.sql` 主体；关于 Alembic/SQL migration 的表述是迁移形态描述，不是当前运行命令。 |
| `docs/architecture/fsrs-scheduling-spec.md` | active | FSRS、ReviewState、ReviewLog 规则仍是复习实现 source-of-truth。 |
| `docs/architecture/langgraph-state-machine.md` | active | Agent 状态机、节点和写库时机仍是当前功能边界。 |
| `docs/design/learning-agent-claude-desktop-framework.html` | protected | 用户设计的受保护原型，必须保留原路径。 |
| `docs/design/assets/note.png` | protected | 原型依赖资产，保留。 |
| `docs/design/assets/sidebar.png` | protected | 原型依赖资产，保留。 |
| `docs/plans/learning-agent-implementation-plan.md` | active-with-updates | M0-M6 审查顺序仍是开发治理入口；已拆分旧路径检查命令里的 `superpowers` 字符串，避免 self-match。 |
| `docs/product/frontend-interaction-spec.md` | active | Desktop 页面、组件、状态和越界限制仍是前端 source-of-truth。 |
| `docs/product/user-flows.md` | active | 用户流程和 MVP 边界仍是产品 source-of-truth。 |
| `docs/qa/acceptance-test-plan.md` | active | P0/P1/P2 验收口径仍有效。 |
| `docs/qa/sdk-agent-release-readiness.md` | active | 2026-05-24 的 SDK Agent 收口记录；作为辅助发布门禁保留，不替代验收测试总计划。 |
| `docs/setup/claude-frontend-handoff.md` | active-with-stale-sections | 保留为外部前端助手交接模板，但把一次性任务目标改为占位符。 |
| `docs/setup/development-environment.md` | active-with-stale-sections | 保留为环境配置入口，但修正当前 runtime 目录、schema bootstrap、API/worker/desktop 命令。 |
| `docs/setup/newcomer-onboarding-guide.md` | active | 新人导读文档，已明确不替代 source-of-truth。 |

## Archive Decision

当前没有整篇归档对象，因此没有创建 `docs/archive/2026-05-24/`。如果后续出现整篇过期文档，按本任务 `design.md` 中的标准移动到 dated archive，并在 `docs/README.md` 标注替代入口。

## Validation Results

| 检查 | 结果 |
|---|---|
| `git diff --check` | 通过；仅有 Windows 工作区 CRLF 提示，无 whitespace error。 |
| stale marker scan | 通过；active docs 未命中旧项目、旧 runtime 路径或旧启动命令。 |
| active docs path check | 通过；README 中 active/auxiliary/protected 文档均存在。 |
| `git status --short` | 已检查；`.claude/settings.local.json` 是无关未跟踪本地文件，未触碰。 |
