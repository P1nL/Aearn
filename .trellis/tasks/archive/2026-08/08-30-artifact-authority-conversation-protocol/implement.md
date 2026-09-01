# Artifact Authority and Conversation Protocol 实施计划

## Prerequisites

- 父任务与本 child 的最新 planning summary 已在后续用户消息中明确批准。
- 依赖 child 已满足本 PRD 声明的可用 contract。
- implement.jsonl/check.jsonl 已包含真实 spec/research context。

## Ordered Checklist

1. [ ] 定义 v1 contracts 与 protected-marker list
2. [ ] 设计/写 schema、FK、partial unique、trigger
3. [ ] 实现 repository/projection/action adapter seam
4. [ ] 扩展 snapshot v4 与 conversation item event
5. [ ] 实现 API routes/idempotency/error mapping
6. [ ] 补充 bootstrap/cutover/export/reset/API/SSE tests
7. [ ] 更新 source-of-truth 草案，等待 integration child 汇总

## Validation

- [ ] focused artifact contract/repository/API/SSE pytest
- [ ] test_db_bootstrap.py 与 cutover suite 串行
- [ ] Ruff、Mypy、API lock
- [ ] task.py validate 与 git diff --check

## Review Gates

- [ ] 逐条映射本 child Acceptance Criteria 到自动测试或 fixture/browser evidence。
- [ ] 检查 public/private、scope、idempotency、stale/replay、feature-off 和 rollback。
- [ ] 运行相关最小验证后，再运行所属 package 完整门。
- [ ] 需要 bootstrap 的 PostgreSQL 测试单进程串行。
- [ ] 不把 fake provider、本地 runner 或空 image-lock 证据描述为生产批准。

## Rollback Points

- feature flag 停止新 artifact admission
- 保留 additive tables 与只读 history
- snapshot v3 保持兼容，不执行 down migration

## Stop Condition

若设计需要改变用户已确认行为、公共 contract 或 child 边界，停止实现并返回 planning；不得在代码中自行选择新产品策略。
