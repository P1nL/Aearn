# Teaching Orchestration and Branch Scheduling 实施计划

## Prerequisites

- 父任务与本 child 的最新 planning summary 已在后续用户消息中明确批准。
- 依赖 child 已满足本 PRD 声明的可用 contract。
- implement.jsonl/check.jsonl 已包含真实 spec/research context。

## Ordered Checklist

1. [x] 发布新 Skill/strict schema/evals
2. [x] 实现 available artifact candidate builder
3. [x] 实现 impossible-instruction pairing validator
4. [x] 实现 atomic artifact teaching commit
5. [x] 实现 continuation intent/priority arbiter
6. [x] 实现 branch classification/control transition/refocus policy
7. [x] 覆盖竞态、repair、stale authority、idempotency evals
8. [x] 更新 runtime/API/docs 设计

## Validation

- [x] teaching action loop/context/provider/gate focused pytest
- [x] branch/timer/user-message concurrency PostgreSQL tests
- [x] prompt contract/eval tests
- [x] 完整 API 回归、Ruff、Mypy

## Review Gates

- [x] 逐条映射本 child Acceptance Criteria 到自动测试或 fixture/browser evidence。
- [x] 检查 public/private、scope、idempotency、stale/replay、feature-off 和 rollback。
- [x] 运行相关最小验证后，再运行所属 package 完整门。
- [x] 需要 bootstrap 的 PostgreSQL 测试单进程串行。
- [x] 不把 fake provider、本地 runner 或空 image-lock 证据描述为生产批准。

## Completion Evidence — 2026-09-01

- Focused Child 02 PostgreSQL/API matrix: `88 passed in 90.55s`.
- Complete API suite, serial: `813 passed, 2 skipped in 381.48s`.
- Ruff: `All checks passed!`.
- Mypy: `Success: no issues found in 240 source files`.
- Dependency lock: `Resolved 55 packages` with `uv lock --check`.
- Trellis task context validation: passed.
- `git diff --check`: passed; only expected local LF/CRLF checkout warnings were emitted.
- Artifact package import smoke: passed with contracts-only package exports.
- No live provider, Docker conformance, production image build/sign/release, push/deploy, or production migration was executed.

## Rollback Points

- 关闭 artifact teaching flag 后候选为空且 artifact intent 被拒绝
- 切回 Skill 1.1.0
- 保留 branch/artifact rows 只读，不重放自动 continuation

## Stop Condition

若设计需要改变用户已确认行为、公共 contract 或 child 边界，停止实现并返回 planning；不得在代码中自行选择新产品策略。
