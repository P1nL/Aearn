# 技术设计

## 1. Coalescer 状态机

新增 `RuntimeDeltaCoalescer`，位于 runtime adapter 层。每个 active turn 仅维护一个 pending delta group：

```text
key = thread/turn/item/event-kind/channel/index/phase
text
source_sequence_start/end
source_delta_count
first_at/last_at
utf8_bytes/chars
```

`push(event)`：

- 同 key delta 且未越 size/time 阈值：追加。
- key 改变、非 delta、size/time 到期：先 flush pending，再处理新事件。
- completed/terminal/interrupt/exception/finally：必须 flush 或显式 discard pending。

## 2. Timer 与公平性

Runtime reader 不能只等下一条 notification 才 flush 稀疏流。实现使用 `next_notification` 与 flush deadline 的 await/select：

```text
wait(next notification, pending flush timer)
```

Timer 到期只 flush pending，不 terminalize turn。所有 await 保持事件循环公平，不能重新引入 `put_nowait` burst starvation。

## 3. Event contract

扩展内部 `RuntimeEvent` 安全字段：

```text
source_sequence_start
source_sequence_end
source_delta_count >= 1
projection_sequence
```

非 coalesced event 默认 count=1。文本 hash 对 coalesced chunk 计算；外部 item identity 仍只在 private adapter/binding 内使用，projection 前转换为 hash/Aearn item ID。

## 4. Persistence

`tutor_runtime_item_receipts` 增加 nullable source range/count 字段和 closed CHECK；不保存 source text。`tutor_runtime_text_items.last_event_sequence` 改为 projection sequence authority。

Projector 对一个 coalesced append 仍执行一次 cumulative append、hash 更新和 `turn_output`。Completed item 以全文校准，确保任意 flush 边界不改变最终内容。

## 5. 预算

建议首轮：

```text
raw notification runaway guard: 100,000
max pending chars: 4,096
flush chars: 1,024
flush delay: 25ms
per item cumulative chars: 1,000,000（沿用）
item/tool/time: 沿用并显式拆分
```

配置必须有 Pydantic 上下界；测试不依赖生产默认值。Runaway guard 只产生稳定 safe code，不映射成普通 UI lag。

## 6. Lag 与恢复

- Adapter→projector 内部队列短时满：bounded await；长期满才 safe fail。
- SSE/Desktop gap：停止局部 reducer，fresh snapshot；不影响 Runtime turn。
- terminal 前 pending 必须 flush；如果 terminal outcome 不允许公开 partial，则按现有 discard 规则清理。
- reconnect authority 始终是 PostgreSQL cumulative/completed projection。

## 7. 性能

首轮通过 coalescing 将同步 DB 调用从每个 source delta 降为每个 flush chunk。记录无文本指标验证 heartbeat drift。如仍超预算，后续任务再引入独立 DB writer；本 child 不在同一连接上并发 control reader 与 projector。

## 8. 兼容与回滚

- Internal event fields additive，fake App Server/tests 更新。
- Snapshot/SSE public version可保持不变，因为客户端仍接收 append/complete/discard 和 projection sequence。
- Feature off 可恢复逐 delta append，但必须使用新预算，不能恢复 2,000 source-event fatal。
- 已持久 receipts/text 不回写或重编号。
