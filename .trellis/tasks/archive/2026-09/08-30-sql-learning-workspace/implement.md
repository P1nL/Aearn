# SQL Learning Workspace 实施计划

## Prerequisites

- 父任务与本 child 的最新 planning summary 已在后续用户消息中明确批准。
- 依赖 child 已满足本 PRD 声明的可用 contract。
- implement.jsonl/check.jsonl 已包含真实 spec/research context。

## Ordered Checklist

1. [x] 定义 SQL presentation/table bounds
2. [x] 扩展 runner 保留 columns/rows
3. [x] 实现 readonly policy 和 public/hidden datasets
4. [x] 实现 Editor/Schema/Result 布局和 copy
5. [x] 接入 Run/result Turn/completion
6. [x] 补充注入/泄漏/bounds/responsive 测试

## Validation

- [x] SQL runner/practice/API pytest
- [x] shared/executor tests
- [x] Desktop SQL component/Vitest
- [x] browser 多视口和大表格 smoke

## Review Gates

- [x] 逐条映射本 child Acceptance Criteria 到自动测试或 fixture/browser evidence。
- [x] 检查 public/private、scope、idempotency、stale/replay、feature-off 和 rollback。
- [x] 运行相关最小验证后，再运行所属 package 完整门。
- [x] 需要 bootstrap 的 PostgreSQL 测试单进程串行。
- [x] 不把 fake provider、本地 runner 或空 image-lock 证据描述为生产批准。

## Evidence — 2026-09-02

- Focused backend/PostgreSQL matrix：单进程串行 **71 passed in 41.95s**，覆盖 SQL runner、Item Bank compiler/repository、Teaching Artifact commit、Result projection、Artifact routes、bootstrap 与 governance。
- Full API gate：首次运行暴露 schema manifest 预期未登记新 fragment；主线程补齐 `test_schema_manifest.py` 后，单进程重跑（`LLM_TYPE=disabled`、排除 real-provider marker）为 **865 passed, 2 deselected in 426.02s**。
- Backend static gates：Ruff 全通过；Mypy **246 source files**；`uv lock --check` 与 `compileall` 通过。
- Shared/Executor：SafeExecutionResult shared contract **34 passed**；Executor 非 Docker conformance 范围 **11 passed**。未运行未经批准的 Docker conformance。
- Desktop：完整 Vitest **21 files / 146 tests passed**；TypeScript `--noEmit` 通过；approved Desktop Vite build 通过。
- Chromium fixture 使用真实 `SqlWorkspaceArtifact` 与 Monaco：
  - 1440x900：Editor/Schema **574px / 574px**；result client/scroll height **318/839**，内部 `overflow:auto`；无页面横向溢出。
  - 900x900：Editor/Schema **434px / 434px**；result client/scroll height **132/1238**；无页面横向溢出。
  - 390x844：上下 pane **358x319.7px / 358x319.7px**；result client/scroll **354/412px、128/1637px**，水平和垂直溢出均留在结果容器；无页面横向溢出。
  - 复制 `learners.mentor_id` 后 Monaco 文本、selection 数量与焦点保持不变，clipboard 为精确 qualified name；等待期间没有 Run，点击后只提交最新完整 query。
  - reduced-motion media query 命中；新页面无相关 console warning/error。临时 fixture/Vite 已停止并删除。
- 唯一一次有界原生 `trellis-check` 在 10 分钟边界内未返回报告，已按约束强制终止且未改文件；未启动第二个 check。主线程随后完成 manifest 修复、完整 API/Desktop/static/package 门与 diff 审计。
- Trellis context：`task.py validate 08-30-sql-learning-workspace` 通过（implement 5 entries / check 1 entry）。

## Rollback Points

- 关闭 SQL artifact 候选，保留现有 Gate SQL 路径。
- table presentation 缺失时显示安全无表格结果，不解析 stdout 伪表格。

## Stop Condition

若设计需要改变用户已确认行为、公共 contract 或 child 边界，停止实现并返回 planning；不得在代码中自行选择新产品策略。
