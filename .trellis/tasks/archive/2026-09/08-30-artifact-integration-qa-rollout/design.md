# Artifact Integration QA and Rollout 技术设计

## Boundary

完成全部Artifact child的跨层集成、迁移、文档、攻击面、响应式和回滚验收，并形成可审阅但不自动发布的最终证据。

本 child 不拥有父任务中分配给其他 child 的业务 authority，不得为了局部便利复制 Artifact、Attempt、Teaching、Markdown、Result 或 Item Bank 状态机。

## Architecture

- Integration fixtures组合fake provider、disposable PostgreSQL、fake/local runner、isolated preview harness
- Contract matrix逐层比较Python/JSON/SSE/TS discriminator
- Release gates按P0/P1分类，任何P0失败阻止归档
- Rollout先server contracts/admission，再Desktop renderer/Preview，rollback反序关闭

## Data Flow

1. seed published item -> Teaching candidate -> artifact -> Desktop action -> Attempt -> result Turn -> continuation
2. reload/reconnect/duplicate/gap/branch/user-priority交叉验证
3. feature off/preview off/model unavailable/executor unavailable验证安全降级

## Contracts and Invariants

- 所有child使用同一Artifact/Result/Markdown/Branch contract
- HTML vertical slice完整通过
- knowledge/demo/review/SQL/source各有happy+bad path
- 无duplicate authority或public private leak
- 所有新表inventory/export/reset/delete分类完整
- feature关闭时模型不发不可执行指令
- source-of-truth docs与代码/route/schema一致
- 真实provider/container/deploy保持独立批准

## Affected Surfaces

- 跨API/Desktop/Tauri/executor tests
- docs/README及五个source-of-truth
- qa acceptance/readiness ledger
- feature config与release audit scripts

## Compatibility

- 保持现有历史数据和旧 contract 读取；新行为通过 additive version/feature gate 引入。
- 所有未知 enum、extra field、stale identity、跨 scope 和受保护内容 fail closed。
- 不从历史归档恢复已移除 runtime，也不删除受保护前端原型。

## Security and Privacy

- 公共 API/SSE/Desktop/日志/导出不得包含完整 submission、private rubric/test、reference answer、provider body/reasoning、命令、路径、容器或 secret。
- 前端不能把本地 UI state 当作业务 authority。

## Rollback

- 任何P0失败停止rollout并关闭artifact admission
- 先停止model candidate，再禁Desktop/Preview
- 保留additive history，无破坏性down migration
- 文档不得把fixture或local preview写成生产批准
