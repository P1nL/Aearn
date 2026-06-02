# SQL query runner 审核稿

## 目标

把 SQL 从 `sql_later` 的 planned/unsupported 状态推进为本地可执行的 L3 teaching runner。初版使用 SQLite，并在产品里明确披露为 `SQLite teaching dialect`。

## 范围

- 只支持教学型单题 SQL query execution。
- 每次运行创建隔离的 SQLite 数据库，使用 Aearn 模板提供的 fixture setup。
- learner SQL 初版只允许单条只读查询：`SELECT` 或 `WITH ... SELECT`。
- 结果支持 visible/hidden tests，并保留 hidden redaction。
- 更新 `language_capabilities.py`、`runner_registry.py`、`runtime_runner.py`、`schema.sql`、`seeds.py` 和 focused tests。

## 不做

- 不执行 PostgreSQL/MySQL/DuckDB。
- 不把 learner SQL 跑到 Aearn 的 PostgreSQL app database。
- 不支持任意项目数据库、migration、trigger、extension、stored procedure。
- 不自动安装数据库工具。
- 不公开 SQL course selection，除非另开内容/路线任务。

## 关键设计取舍

- 推荐 SQLite：它是本地、轻量、可隔离、适合教学 query validation。
- 代价是 dialect 与 PostgreSQL/MySQL 不完全一致，所以必须在 UI/API 中明确 `SQLite teaching dialect`。
- 安全优先：trusted setup SQL 和 learner SQL 分开处理，learner SQL 启用 read-only 限制和 timeout。

## 验收标准

- SQL capability 只在 adapter/tests/API/disclosure 一致后显示为 executable。
- valid `SELECT` 能通过 visible/hidden tests。
- SQL syntax/runtime error 映射到 learner-safe `runtime_error`。
- runaway query 映射到 `timeout`。
- DDL/DML/multi-statement/`ATTACH`/`PRAGMA` 等危险输入被拒绝。
- hidden test ids、hidden expected rows、hidden seed data、solution_reference 和内部异常不泄露。

## 执行顺序

1. 先写 focused failing tests。
2. 实现 `sql_query_runner.py`。
3. 接入 `runner_registry.py` 和 `runtime_runner.py`。
4. 更新 capability、schema/bootstrap seed、环境/设置披露。
5. 跑 focused tests、`ruff`、`mypy`、`task.py validate`、`git diff --check`。

## 风险

- SQL 安全边界如果放宽，可能误执行 mutation 或连接共享数据库。
- schema constraint 更新会影响 bootstrap，需要顺序验证 DB tests。
- capability 提前打开会导致产品 overclaim。

## 回滚点

- 把 SQL capability 恢复成 `sql_later`。
- 保留 `SQL_RUNNER` unsupported fallback。
- 移除或 archive SQL runtime profile seed。

## 待确认

- 默认 SQL dialect 使用 SQLite。我的建议是接受这个默认值，因为它最适合本地教学 runner 的安全边界。
