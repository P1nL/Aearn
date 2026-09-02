# Knowledge Checks Hints and Remediation 实施计划

## Prerequisites

- 父任务与本 child 的最新 planning summary 已在后续用户消息中明确批准。
- 依赖 child 已满足本 PRD 声明的可用 contract。
- implement.jsonl/check.jsonl 已包含真实 spec/research context。

## Ordered Checklist

1. [x] 定义题型与response contract
2. [x] 实现difficulty validator/selector
3. [x] 实现immutable response/scorer/result projection
4. [x] 实现disclosure/remediation/transfer policy
5. [x] 实现Hint receipt和overlay horizontal pager
6. [x] 接入Tutor评价Turn
7. [x] 补充多题型/歧义/辅助/mastery测试

## Validation

- [x] contract/scorer/remediation pytest
- [x] PostgreSQL response/hint idempotency tests
- [x] Desktop keyboard/popover/scroll-snap tests
- [x] adaptive teaching evals和完整回归

## Review Gates

- [x] 逐条映射本 child Acceptance Criteria 到自动测试或 fixture/browser evidence。
- [x] 检查 public/private、scope、idempotency、stale/replay、feature-off 和 rollback。
- [x] 运行相关最小验证后，再运行所属 package 完整门。
- [x] 需要 bootstrap 的 PostgreSQL 测试单进程串行。
- [x] 不把 fake provider、本地 runner 或空 image-lock 证据描述为生产批准。

## Rollback Points

- 关闭dynamic knowledge artifact admission，保留现有Gate静态题
- 历史answer/hint receipts只读
- 不回填或重算旧mastery

## Stop Condition

若设计需要改变用户已确认行为、公共 contract 或 child 边界，停止实现并返回 planning；不得在代码中自行选择新产品策略。
