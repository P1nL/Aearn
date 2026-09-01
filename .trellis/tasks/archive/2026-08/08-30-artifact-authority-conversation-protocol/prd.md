# Artifact Authority and Conversation Protocol

## Parent

- `08-30-tutor-conversation-learning-artifacts`
- 本 child 的实现必须遵守父任务 PRD/design 和 confirmed product decisions；若产生物质性冲突，先返回父任务规划。

## Goal

建立 Learning Artifact 的数据库、领域、公共投影、API、Snapshot/SSE 和 Attempt 归属基础，使其他工件 child 共享同一 authority。

## Scope

- 严格 TutorPublicArtifactItem 与 presentation/action union
- Artifact lifecycle/event/reference/attempt-link persistence
- snapshot v4 与 item_added/item_updated recovery
- scoped artifact read/action/attempt API facade
- cutover inventory、export/reset/delete、bootstrap twice

## Requirements

### R1

- 新增 artifact 到 TutorPublicItem 和 item reference，保持 extra-forbid

### R2

- 每个 artifact 绑定 user/conversation/TeachingSession/checkpoint/owner/version

### R3

- 每个 conversation/session 至多一个 blocking active artifact

### R4

- action 使用 client_action_id + expected_version + owner-specific payload

### R5

- Artifact facade 委派 Gate/Review/teaching practice，不写第二套 mastery

### R6

- SSE 只发安全引用，完整详情由 snapshot/API 恢复

### R7

- 旧 snapshot v3、历史 item 和无 artifact 会话继续可读

## Acceptance Criteria

- [ ] 数据库拒绝跨用户、非法 lifecycle、重复 active artifact 和 stale CAS
- [ ] artifact create/update 与 conversation event 同事务
- [ ] duplicate/gap/cursor invalid/reconnect 恢复相同 projection
- [ ] 公共 payload 受 protected-marker 测试保护
- [ ] bootstrap twice、cutover exhaustive inventory、reset/export 通过

## Out of Scope

- Desktop 组件
- Teaching provider prompt/decision
- 具体 Monaco/SQL/Review UI
- 题库 authoring/review pipeline

## Dependencies and Ordering

- 无实现前置；它是其他 child 的基础
- 需要复用现有 Gate/Review/TeachingSession/Attempt contracts

## Open Questions

无阻塞产品问题。实现中若发现仓库事实与本规划冲突，必须回到 planning 更新 artifact 并重新审阅。
