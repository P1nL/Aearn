# Teaching Demonstration Artifacts 实施计划

## Prerequisites

- 父任务与本 child 的最新 planning summary 已在后续用户消息中明确批准。
- 依赖 child 已满足本 PRD 声明的可用 contract。
- implement.jsonl/check.jsonl 已包含真实 spec/research context。

## Ordered Checklist

1. [x] 定义static/interactive descriptor和completion receipt
2. [x] 实现duration calculator和visible clock协议
3. [x] 实现只读代码/Preview演示UI
4. [x] 实现exact event validator和idempotency
5. [x] 接入continuation arbiter
6. [x] 覆盖后台/滚出/切会话/关闭/重复event测试

## Validation

- [x] contract/duration/event pytest
- [x] Desktop visibility/progress/reduced-motion Vitest
- [x] Preview event spoof tests
- [x] browser smoke和完整回归

## Review Gates

- [x] 逐条映射本 child Acceptance Criteria 到自动测试或 fixture/browser evidence。
- [x] 检查 public/private、scope、idempotency、stale/replay、feature-off 和 rollback。
- [x] 运行相关最小验证后，再运行所属 package 完整门。
- [x] 需要 bootstrap 的 PostgreSQL 测试单进程串行。
- [x] 不把 fake provider、本地 runner 或空 image-lock 证据描述为生产批准。

## Rollback Points

- 关闭demo candidate admission
- 已有演示只读展示但不自动继续
- 不将演示转换为评分练习

## Stop Condition

若设计需要改变用户已确认行为、公共 contract 或 child 边界，停止实现并返回 planning；不得在代码中自行选择新产品策略。
