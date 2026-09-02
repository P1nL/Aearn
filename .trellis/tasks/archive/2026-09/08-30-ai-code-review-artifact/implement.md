# AI Code Review Learning Artifact 实施计划

## Prerequisites

- 父任务与本 child 的最新 planning summary 已在后续用户消息中明确批准。
- 依赖 child 已满足本 PRD 声明的可用 contract。
- implement.jsonl/check.jsonl 已包含真实 spec/research context。

## Ordered Checklist

1. [x] 定义v2 taxonomy/contracts兼容
2. [x] 扩展publication/rubric和diff builder
3. [x] 实现finding matcher和result projection
4. [x] 实现Desktop code/diff/finding UX
5. [x] 接入Tutor评价/remediation
6. [x] 补充scenario/language/privacy/stale/false-positive测试

## Validation

- [x] model review focused contract/authoring/repository/API pytest
- [x] Desktop DiffEditor/finding tests
- [x] 完整API/executor/desktop回归
- [x] protected marker audit

## Review Gates

- [x] 逐条映射本 child Acceptance Criteria 到自动测试或 fixture/browser evidence。
- [x] 检查 public/private、scope、idempotency、stale/replay、feature-off 和 rollback。
- [x] 运行相关最小验证后，再运行所属 package 完整门。
- [x] 需要 bootstrap 的 PostgreSQL 测试单进程串行。
- [x] 不把 fake provider、本地 runner 或空 image-lock 证据描述为生产批准。

## Rollback Points

- feature关闭时继续使用v1 panel/history
- 不迁移旧submission
- v2 item退役不删除已完成attempt

## Stop Condition

若设计需要改变用户已确认行为、公共 contract 或 child 边界，停止实现并返回 planning；不得在代码中自行选择新产品策略。
