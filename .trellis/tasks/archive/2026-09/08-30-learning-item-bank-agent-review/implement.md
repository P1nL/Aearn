# Learning Item Bank and Agent Review 实施计划

## Prerequisites

- 父任务与本 child 的最新 planning summary 已在后续用户消息中明确批准。
- 依赖 child 已满足本 PRD 声明的可用 contract。
- implement.jsonl/check.jsonl 已包含真实 spec/research context。

## Ordered Checklist

1. [ ] 定义item/blueprint/review/publish contracts
2. [ ] 选择repo source目录和compiler/import seam
3. [ ] 实现通用与kind-specific validators
4. [ ] 实现agent review job/report/adjudication
5. [ ] 实现risk/pilot/publish/retire
6. [ ] 创建最小HTML/knowledge/demo/review/SQL seed
7. [ ] 接入candidate query并覆盖gap/no-candidate行为
8. [ ] 补充review independence/quarantine/version tests

## Validation

- [ ] item schema/compiler/validator tests
- [ ] standard answer/runtime/event/scorer fixture tests
- [ ] agent review/adjudication/risk gate tests
- [ ] DB bootstrap/import/idempotency/cutover classification
- [ ] 离线fake agent，不调用真实provider默认路径

## Review Gates

- [ ] 逐条映射本 child Acceptance Criteria 到自动测试或 fixture/browser evidence。
- [ ] 检查 public/private、scope、idempotency、stale/replay、feature-off 和 rollback。
- [ ] 运行相关最小验证后，再运行所属 package 完整门。
- [ ] 需要 bootstrap 的 PostgreSQL 测试单进程串行。
- [ ] 不把 fake provider、本地 runner 或空 image-lock 证据描述为生产批准。

## Rollback Points

- 停止publish/candidate admission，保留published历史
- 退役有问题version，不原地修改
- agent review feature关闭时高风险全部停在machine_verified

## Stop Condition

若设计需要改变用户已确认行为、公共 contract 或 child 边界，停止实现并返回 planning；不得在代码中自行选择新产品策略。
