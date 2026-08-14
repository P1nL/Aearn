# 建立 Tutor 持久化 Queue 与 Stop

## 目标

为 Tutor 普通消息建立 conversation-scoped、服务端持久化、有界 FIFO Queue，并提供编辑、删除、Steer、完成后自动消费、失败/停止后暂停及下一次发送唤醒能力；同时公开 learner-facing run-level stop authority，近似 DSH 的核心运行交互而不破坏 Aearn finite TurnRun 和安全 fencing。

## 依赖

- 依赖父任务需求和 DSH Queue/Stop 研究证据。
- 不依赖 UI foundation 或 Pending Input 代码，但实施前必须确认 `08-13-tutor-controlled-pending-inputs` 的 active/waiting contract 没有冲突。
- `08-13-tutor-dsh-conversation-integration` 必须在本 child 完成后才能接入 UI。

## 范围内

- Queue additive schema、repository、service、API、SSE/history projection、export/reset/cutover classification。
- 新 Desktop 使用的 `delivery_mode="queue"`，以及旧客户端缺省 latest-input-wins 兼容。
- queue create/list/edit/delete/Steer、20-item bound、16,000-char item、版本和幂等。
- completed auto-drain、非 completed 终态暂停、next send append-and-wake。
- run cancel endpoint、状态约束、idempotency、terminal event 和 post-cancel public-write fencing。
- Desktop type/API seam 和后端/contract tests；不实现最终视觉组件。

## 范围外

- QueueDock/Composer/stop button 的最终 React/CSS 集成。
- Typed Question catalog 与 pending projection。
- provider transport 硬 abort 或停止计费保证。
- Queue reorder、批量清空、优先级、跨 conversation 搬移、后台并行 run。
- 在 Queue item 消费前将其写入公开 conversation timeline。

## 需求

1. Queue 按 `user_id + conversation_id` 隔离，严格 FIFO，最多 20 个 queued items。
2. queue item 保存 content、hash、immutable learning scope snapshot/context references、sequence、version 和状态；消费前不创建 `tutor_messages`。
3. 新 Desktop 普通输入声明 `delivery_mode=queue`；缺省请求保持旧 latest-input-wins 语义。
4. active run 存在时 enqueue；无 active run 且 Queue 为空时直接 start；无 active run 但有暂停 Queue 时 append 新项后唤醒最早项。
5. edit/delete 使用 expected version；跨用户统一 404，stale 409，idempotency key body 变化冲突。
6. `Steer` 只允许 active interactive run 为 `queued/leased/running/waiting_for_capability`，原子将 item 转成当前 run 的新 input revision；其余 Queue 保序。
7. `waiting_for_input` 与 `awaiting_effect_commit` 不允许 Steer。
8. run `completed` 后服务端自动 claim FIFO head 创建 fresh finite run；其他终态保留并暂停 Queue。
9. run cancel 只允许 `queued/leased/running/waiting_for_capability`；不取消 planning session，不删除 Queue。
10. stop 立即持久化 cancelled、释放 lease、写 terminal SSE 并阻止后续 Tutor message/effect/public write；不宣称已发 provider request 被硬中断。
11. Desktop/consumer 从服务端 snapshot 恢复 Queue；不得建立仅前端内存 Queue。
12. Queue mutation 和 drain 对并发/重复 dispatch 可恢复，不丢 item、不重复 message/run。

## 验收标准

- [ ] PostgreSQL bootstrap twice 建立 Queue schema、索引、约束和 data lifecycle 分类。
- [ ] FIFO、20-item bound、concurrent enqueue、edit/delete version、idempotency 和跨用户测试通过。
- [ ] Queue item 消费前不出现在 public timeline；消费后只生成一次 learner message/input receipt/run。
- [ ] completed 自动推进；cancelled/failed/model_unavailable/blocked_policy/budget_exhausted 暂停。
- [ ] paused Queue 在下一次普通发送时 append 新项并启动最早旧项，最终消息顺序符合 FIFO。
- [ ] Steer 触发 input revision 更新与 context rebuild，其他 items 不丢失，waiting/effect-commit 被拒绝。
- [ ] cancel API 对允许状态成功，对 waiting/effect-commit fail closed，重复请求幂等。
- [ ] 取消后 provider late result、effect 或 Tutor public message 不可落库。
- [ ] 旧客户端不带 delivery mode 的 latest-input-wins 回归通过。
- [ ] Queue/read/mutation/cancel 的 REST/SSE/TS parser contract 一致。

## 风险

- Queue 改变当前 conversation input 的核心语义，必须以显式 delivery mode 保留兼容。
- 自动 drain 与后台 dispatch 存在重复执行风险；claim/run creation 必须事务化并可幂等恢复。
- stop 是协作式服务端取消，不等同 provider-side network abort。
