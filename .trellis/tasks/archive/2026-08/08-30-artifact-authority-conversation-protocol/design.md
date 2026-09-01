# Artifact Authority and Conversation Protocol 技术设计

## Boundary

建立 Learning Artifact 的数据库、领域、公共投影、API、Snapshot/SSE 和 Attempt 归属基础，使其他工件 child 共享同一 authority。

本 child 不拥有父任务中分配给其他 child 的业务 authority，不得为了局部便利复制 Artifact、Attempt、Teaching、Markdown、Result 或 Item Bank 状态机。

## Architecture

- 在 services/learning 下建立 artifacts 子域，Tutor persistence 只负责 conversation projection
- Repository 是 DB row 到 learner-safe DTO 的唯一出口
- Artifact action service 以 owner adapter registry 委派现有业务 authority
- snapshot projector 在 conversation share lock 下读取 timeline、active artifact 和 branch safe summary

## Data Flow

1. Teaching/Gate service 创建 artifact -> DB lifecycle/event -> conversation item_added
2. Desktop action -> artifact route -> owner adapter -> Attempt/response -> artifact item_updated
3. terminal Attempt -> artifact terminal -> continuation intent（后续 child 处理）

## Contracts and Invariants

- 新增 artifact 到 TutorPublicItem 和 item reference，保持 extra-forbid
- 每个 artifact 绑定 user/conversation/TeachingSession/checkpoint/owner/version
- 每个 conversation/session 至多一个 blocking active artifact
- action 使用 client_action_id + expected_version + owner-specific payload
- Artifact facade 委派 Gate/Review/teaching practice，不写第二套 mastery
- SSE 只发安全引用，完整详情由 snapshot/API 恢复
- 旧 snapshot v3、历史 item 和无 artifact 会话继续可读

## Affected Surfaces

- aearn/services/api/app/db/schema/ manifest 与新 fragment
- aearn/services/api/app/services/learning/artifacts/（新增）
- aearn/services/api/app/services/tutor/conversation_contracts.py
- Tutor persistence/public_api/routes/snapshot/SSE tests
- local user export/reset/cutover inventory

## Compatibility

- 保持现有历史数据和旧 contract 读取；新行为通过 additive version/feature gate 引入。
- 所有未知 enum、extra field、stale identity、跨 scope 和受保护内容 fail closed。
- 不从历史归档恢复已移除 runtime，也不删除受保护前端原型。

## Security and Privacy

- 公共 API/SSE/Desktop/日志/导出不得包含完整 submission、private rubric/test、reference answer、provider body/reasoning、命令、路径、容器或 secret。
- 前端不能把本地 UI state 当作业务 authority。

## Rollback

- feature flag 停止新 artifact admission
- 保留 additive tables 与只读 history
- snapshot v3 保持兼容，不执行 down migration
