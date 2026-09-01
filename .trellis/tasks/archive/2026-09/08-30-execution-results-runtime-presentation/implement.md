# Execution Results and Runtime Presentation 实施计划

## Prerequisites

- 父任务与本 child 的最新 planning summary 已在后续用户消息中明确批准。
- 依赖 child 已满足本 PRD 声明的可用 contract。
- implement.jsonl/check.jsonl 已包含真实 spec/research context。

## Ordered Checklist

1. [x] 定义v2兼容策略和table result bounds
2. [x] 扩展shared/executor/API adapters
3. [x] 实现result artifact projector
4. [x] 实现evaluation Turn/fallback/idempotency
5. [x] 实现Desktop简洁结果UI/返回修改
6. [x] 补充redaction/duplicate/model-failure/SQL table tests

## Validation

- [x] shared/executor contract tests
- [x] API attempt/result/redaction tests
- [x] Desktop result rendering tests
- [x] 完整 API/executor/desktop gates

## Review Gates

- [x] 逐条映射本 child Acceptance Criteria 到自动测试或 fixture/browser evidence。
- [x] 检查 public/private、scope、idempotency、stale/replay、feature-off 和 rollback。
- [x] 运行相关最小验证后，再运行所属 package 完整门。
- [x] 需要 bootstrap 的 PostgreSQL 测试单进程串行。
- [x] 不把 fake provider、本地 runner 或空 image-lock 证据描述为生产批准。

## Rollback Points

- 保留v1 adapter，feature关闭时旧Gate结果继续可读
- 停用evaluation Turn不删除Attempt/result
- 禁止模型输出替代服务器result

## Stop Condition

若设计需要改变用户已确认行为、公共 contract 或 child 边界，停止实现并返回 planning；不得在代码中自行选择新产品策略。
