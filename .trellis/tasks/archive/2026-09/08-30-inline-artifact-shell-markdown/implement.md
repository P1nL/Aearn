# Inline Artifact Shell and Safe Markdown 实施计划

## Prerequisites

- 父任务与本 child 的最新 planning summary 已在后续用户消息中明确批准。
- 依赖 child 已满足本 PRD 声明的可用 contract。
- implement.jsonl/check.jsonl 已包含真实 spec/research context。

## Ordered Checklist

1. [ ] 扩展 TS strict parser 和 item union
2. [ ] 实现 SafeMarkdown 与 sanitizer tests
3. [ ] 实现 shell/registry/header/actions/summary
4. [ ] 实现 branch grouping/rail/collapse
5. [ ] 实现 scroll/focus/state cache/lazy detail
6. [ ] 添加 container query/reduced motion/accessibility
7. [ ] 接入 placeholder artifact renderers 供后续 child 使用
8. [ ] 运行真实浏览器多视口 smoke

## Validation

- [x] desktop Vitest contracts/rendering/scroll/focus
- [x] desktop:check
- [x] browser 1440x900、900x900、390x844
- [x] DOM protected marker / raw HTML/script audit
- [x] console error/warning zero

## Review Gates

- [x] 逐条映射本 child Acceptance Criteria 到自动测试或 fixture/browser evidence。
- [x] 检查 public/private、scope、idempotency、stale/replay、feature-off 和 rollback。
- [x] 运行相关最小验证后，再运行所属 package 完整门。
- [x] 需要 bootstrap 的 PostgreSQL 测试单进程串行。
- [x] 不把 fake provider、本地 runner 或空 image-lock 证据描述为生产批准。

## Rollback Points

- Desktop feature flag 回到现有 timeline renderer
- 未知 artifact 显示安全 unavailable，不执行任何 action
- 不删除 server artifact history

## Stop Condition

若设计需要改变用户已确认行为、公共 contract 或 child 边界，停止实现并返回 planning；不得在代码中自行选择新产品策略。
