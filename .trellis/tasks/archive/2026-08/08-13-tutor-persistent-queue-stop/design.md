# 技术设计

## Queue persistence

新增 `tutor_conversation_queue_items`：user/conversation、monotonic sequence、version、state、content/body hash、learning scope/context references snapshot、source action id 和时间戳。使用 conversation row lock 分配 sequence 和串行 mutation；partial unique/index 限制 queued 查询和幂等 identity。

## Delivery contract

Conversation input 增加：

```py
delivery_mode: Literal["legacy_replace", "queue"] = "legacy_replace"
```

新 Desktop 显式发送 `queue`。响应增加 `placement`：`started | queued | queued_and_woke` 与 Queue snapshot；旧字段保持 additive 兼容。

## Queue API

```text
GET    /conversations/{id}/queue
PATCH  /conversations/{id}/queue/{item_id}
DELETE /conversations/{id}/queue/{item_id}
POST   /conversations/{id}/queue/{item_id}/steer
```

mutation 使用 `TutorPublicService._mutate()`，body 含 user、expected version、client action id。服务端返回完整权威 queued snapshot，Desktop 不长期依赖 optimistic state。

## Enqueue/start/wake transaction

- active run -> insert queued item。
- no active + empty queue -> 复用 fresh turn transaction 直接 start。
- no active + existing queued -> insert new tail，然后原子 claim earliest item、创建 learner message + fresh run，将 head 标记 consumed。

学习 scope 和 context references 在 enqueue 时校验并冻结；消费时不根据当前页面重新猜测。

## Drain coordinator

interactive dispatch 完成后读取 terminal outcome：只有 `completed` 调用 `claim_next_queue_item()`。claim + message + run creation 同一事务并有 consumed item -> run 唯一关联。background dispatch 失败由 run lease/recovery 处理，不把 item 退回造成重复。

## Steer

锁 conversation + active run + item，校验状态后调用与 `accept_input` 共用的低层 transaction seam，递增 current run revision并写 learner message/input event，item -> steered。run-loop 现有 before-model、after-provider 和 unsafe-boundary revision checks 处理 stale work。

## Stop

`POST /runs/{run_id}/cancel` 通过 public service 幂等 mutation：

- ownership/origin/visibility/state check。
- 调用现有 repository cancellation transaction。
- 返回 current run + Queue snapshot。
- waiting_for_input/awaiting_effect_commit 返回稳定 conflict。

不增加 provider-side abort token；文档将其描述为立即持久化取消与协作式停止。

## Projection/SSE

active run SSE 增加 allowlisted `queue_state` event，数据为 count/revision/items safe projection。history active run 也返回 queue snapshot，确保刷新和 SSE 断线恢复。无 active run时 GET Queue 是恢复入口。

## 数据生命周期

- export 只暴露 learner-visible queued content 和状态所需最小字段，不暴露 hashes/internal events。
- reset/delete 按 item -> run/message root 的安全顺序删除用户 Queue。
- cutover inventory 把新表归为 user-owned target state。

## 回滚

保持旧 delivery default；代码回滚时 Queue 表和 rows 保留，不 drop。若新 Desktop 暂时回退，服务端 GET/mutations 仍可保留，旧客户端不受影响。
