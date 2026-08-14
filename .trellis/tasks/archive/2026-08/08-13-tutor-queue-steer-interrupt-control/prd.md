# Tutor 队列、引导、中断与重试控制

## 目标

在 Thread/Turn/Item/Event/dispatch 底座和 typed request authority 已冻结的前提下，实现运行中普通输入默认 Queue、显式 Steer、精确 Interrupt、Queue 编辑/删除/重排/立即执行、completed-only 自动 drain、显式恢复与 Retry/effect lineage，保证并发、崩溃和迟到结果场景下状态确定。

## 依赖与范围

- 父任务：`08-13-codex-like-tutor-conversation-experience`。
- 依赖 `08-13-tutor-thread-turn-item-event-foundation` 与 `08-14-tutor-typed-request-authority-turns` 完成归档。
- 本 child 实现正常 v2 运行控制，不拥有 typed request schema/response API，不拥有全局 cutover/legacy retirement，也不实现最终 Desktop UI。

## 需求

### R1：默认 Queue 与容量

- active turn 时普通 Send 默认持久化 Queue，不 supersede、不 steer。
- 每 conversation 固定最多 10 条 pending，每条最多 16,000 字符；claim 前不进入正式 timeline。snapshot 返回 `pending_count` 与 `max_pending=10`。
- Queue 支持 list/edit/delete/reorder/steer/execute；mutation 带 idempotency 与 expected control version。reorder 提交完整 pending ID 顺序。
- 只有正常 `completed` 且无 pending request、Queue 未暂停时自动 FIFO drain；`interrupted` 或 `failed` 保留并暂停 Queue。

### R2：显式 Steer

- 只接受精确 active turn 的 `expected_turn_id + expected_input_revision`。
- Steer 将选中 Queue 项转为当前 turn 的新 input revision 并共享剩余预算；旧 provider decision 在 capability/effect/public message 前被拒绝。
- stale/terminal/pending-request 状态返回 conflict，不静默 Queue。

### R3：Interrupt、暂停与立即执行

- Interrupt 形成 public `interrupted` 终态，旧 turn 不再产生公开回复或副作用；现有 Queue 保留并进入 `queue_paused`。
- Stop 后恢复必须调用独立 `queue/resume` mutation；下一次普通 Send 不得隐式恢复旧 Queue。
- “立即执行”是独立原子 mutation：interrupt 当前 turn 并 claim 指定 item 创建 fresh turn；Steer 与 execute 不得混用，pending request 时均拒绝。

### R4：消费 typed request 阻塞契约

- 本 child 只读取 `pending_request` authority 与 control state；pending 时禁止 drain、Steer 和 execute，不修改 request row。
- learner response/approval/authority receipt 由 typed-request child 创建 fresh turn；该 turn 正常 completed 后才可能继续 drain。
- Required Question 期间 Queue 保留且暂停；页面级取消规划不删除 Queue。

### R5：Retry 与副作用安全

- recoverable failed turn 可 Retry 为 fresh turn，记录 `retry_of_turn_id/retry_root_turn_id`。
- effect proposal 使用稳定 logical action key 和 authority receipt 去重；已提交 effect 不因新 turn 重复执行。
- effect 状态无法证明时 Retry fail closed，并返回稳定可解释错误。

### R6：持久调度与错误

- Queue claim、message、fresh turn、input event、dispatch job 与 events 同事务；重复 worker/reconciler 不重复创建。
- interrupted/failed/queue_paused 不会被后台扫描隐式恢复；completed-only drain 不依赖浏览器在线。
- learner-safe errors 至少覆盖 model unavailable、turn limit、dispatch delayed、stale mutation、queue full、interrupted 和 internal failure。

## 验收标准

- [ ] active turn 期间三条普通消息按 FIFO Queue，active turn/revision 不变，刷新后保持。
- [ ] completed 后离线自动 drain；Interrupt/failed 后 Queue 暂停，显式 resume 后恢复；重复 wakeup 不重复 turn/message/provider。
- [ ] edit/reorder/delete/Steer/execute 在 stale control version 下拒绝且不部分写入；Steer 保持当前 turn，execute 创建 fresh turn。
- [ ] Interrupt/provider-return race 下无 stale public message/capability/effect；普通 Send 不唤醒暂停 Queue。
- [ ] pending typed request 阻塞 drain/Steer/execute 且不被本 child 修改；解决后的 fresh turn 遵循正常 Queue 规则。
- [ ] Retry 不重复已提交 effect；receipt 不明确时 fail closed。
- [ ] Queue concurrency、crash recovery、run-loop fence、Ruff、Mypy 与文档一致性验证通过。

## 范围外

- typed request/approval/authority receipt schema 与 response API。
- 全局 v2 gate、legacy row migration、旧 POST `410 Gone` 与 cutover preflight。
- 最终 Desktop Queue/Composer/Stop/Retry UI。