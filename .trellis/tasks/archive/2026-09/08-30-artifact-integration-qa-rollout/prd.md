# Artifact Integration QA and Rollout

## Parent

- `08-30-tutor-conversation-learning-artifacts`
- 本 child 的实现必须遵守父任务 PRD/design 和 confirmed product decisions；若产生物质性冲突，先返回父任务规划。

## Goal

完成全部Artifact child的跨层集成、迁移、文档、攻击面、响应式和回滚验收，并形成可审阅但不自动发布的最终证据。

## Scope

- cross-child contract reconciliation
- end-to-end fixture matrix
- SSE/snapshot/reload/branch race tests
- Preview/Markdown/SQL/item-bank security audit
- responsive/accessibility/browser/Tauri smoke
- feature flags/rollback/cutover inventory/docs/ledger

## Requirements

### R1

- 所有child使用同一Artifact/Result/Markdown/Branch contract

### R2

- HTML vertical slice完整通过

### R3

- knowledge/demo/review/SQL/source各有happy+bad path

### R4

- 无duplicate authority或public private leak

### R5

- 所有新表inventory/export/reset/delete分类完整

### R6

- feature关闭时模型不发不可执行指令

### R7

- source-of-truth docs与代码/route/schema一致

### R8

- 真实provider/container/deploy保持独立批准

## Acceptance Criteria

- [x] 父任务AC1-AC20全部有可复现证据
- [x] 完整API串行suite、Ruff、Mypy、lock通过
- [x] executor suite与shared contract通过
- [x] Desktop test/check、Tauri cargo、安全smoke通过
- [x] 1440/900/390 console zero error/warning且无overflow
- [x] bootstrap twice/cutover exhaustive inventory通过
- [x] task validate/diff hygiene/docs link audit通过
- [x] 残余风险与非声明写入readiness ledger

## Out of Scope

- 生产部署/推送
- 真实provider smoke
- reviewed container image build/sign/publish
- 生产数据迁移或release批准

## Dependencies and Ordering

- 等待Child01-11完成；本child不重写其业务实现

## Open Questions

无阻塞产品问题。实现中若发现仓库事实与本规划冲突，必须回到 planning 更新 artifact 并重新审阅。
