# Codex 对话模型源码基线

## 基线版本

- 仓库：`openai/codex`
- 固定 revision：`ef596c68ca35dcd42283a0014f9b7fb057147269`
- revision 时间：`2026-08-13T15:23:09Z`
- 本地只读参考目录：`C:\Users\PINKING\AppData\Local\Temp\openai-codex-aearn-reference`
- 研究范围：`codex-rs/app-server-protocol`、`codex-rs/app-server`、`codex-rs/core`、`codex-rs/protocol` 与当前 Codex manual。

## 核心对象

Codex app-server 将对话拆为三层：

1. `Thread`：持久化对话；可 start、resume、read、list、archive。
2. `Turn`：一次用户请求以及由该请求触发的 Agent 工作；状态为 `inProgress | completed | interrupted | failed`。
3. `ThreadItem`：turn 内可展示或可恢复的输入/输出单元；通过 started、delta、completed 等通知增量更新。

源码锚点：

- `codex-rs/app-server-protocol/src/protocol/v2/turn.rs:30`：`TurnStatus`。
- `codex-rs/app-server-protocol/src/protocol/v2/turn.rs:71`：`TurnStartParams`。
- `codex-rs/app-server-protocol/src/protocol/v2/item.rs:230`：`ThreadItem`。
- Codex manual `Codex App Server`：Thread 是 conversation，Turn 是单次请求及后续工作，Item 是输入/输出单元。

## 输入路径不是同一语义

### 1. `turn/start`

- 在 thread 中创建新的 turn。
- 每个 turn 有独立 ID 和终态。
- 用户的普通下一轮消息应通过该入口开始新的工作。

### 2. `turn/steer`

- 将新输入追加到当前仍在执行的 turn，不创建新 turn。
- 必须携带 `expected_turn_id`，服务端检查它仍是当前 active turn，防止客户端把输入投递到已经变化的运行。
- 只有普通可 steer turn 接受；review、manual compact 等特殊 turn 明确拒绝。
- 接受 steer 只代表输入进入当前 turn，不代表当前模型采样或动作已经成功。

源码锚点：

- `codex-rs/app-server-protocol/src/protocol/v2/turn.rs:175`。
- `codex-rs/app-server/src/request_processors/turn_processor.rs:920`。
- `codex-rs/core/src/session/turn_input.rs:478`。

### 3. Queue

- Codex 产品体验允许将 follow-up 保存到下一 turn，而不是改变当前 turn。
- Queue 是客户端/会话级待发消息语义，不等于 `turn/steer`，也不应伪装成当前 turn 的输入 revision。
- 用户可编辑、重排、立即发送或删除队列消息。

### 4. `request_user_input` / approval response

- Agent 主动要求用户回答时，app-server 发出 server request，而不是结束当前 turn 后把任意下一条聊天消息合并进旧 turn。
- 响应通过 request/call ID 精确关联当前阻塞项。
- 该机制适合 clarification、planning fact、approval 等结构化等待；它与普通 steer/queue 输入分离。
- Codex 当前实现还区分 blocking 与 non-blocking request；hidden reasoning 不作为用户输入请求的一部分。

源码锚点：

- `codex-rs/app-server-protocol/src/protocol/common.rs:1567`：`item/tool/requestUserInput`。
- `codex-rs/app-server-protocol/src/protocol/v2/item.rs:1618-1696`：问题、选项和回答结构。
- `codex-rs/app-server/src/bespoke_event_handling.rs:727-756`：server request 发送。

## 生命周期通知

稳定交互骨架为：

```text
thread/start or thread/resume
  -> turn/start
  -> turn/started
  -> item/started
  -> item delta/progress
  -> item/completed
  -> turn/completed(completed | interrupted | failed)
```

- `turn/interrupt` 使用 thread ID + turn ID 精确取消当前 turn。
- `turn/completed` 在正常完成或 interrupt 后都给出最终状态。
- UI 通过通知更新当前 turn/items，并通过 thread read/resume 恢复持久化历史。
- Codex 明确允许历史投影是 lossless/stream 和 persisted resume projection 的组合；客户端不能假设所有内部交互都进入持久化 transcript。

源码锚点：

- `codex-rs/app-server-protocol/src/protocol/v2/turn.rs:209`：interrupt。
- `codex-rs/app-server-protocol/src/protocol/v2/turn.rs:390`：started。
- `codex-rs/app-server-protocol/src/protocol/v2/turn.rs:407`：completed。

## 适合 Aearn 复用的原则

1. conversation/thread、turn、timeline item 三层分离。
2. 普通下一轮、运行中 steer、下一轮 queue、阻塞式 elicitation response 使用不同协议。
3. 每个 active turn 的 mutation 都带 expected turn/item identity，拒绝 stale input。
4. interrupt 是可解释终态，不是模糊失败。
5. 过程 UI 由 typed item/event 驱动，不依赖客户端从日志文本猜测。
6. 历史恢复从服务端投影；live delta 只是当前可见增量。
7. 公开 reasoning 只展示专门生成的摘要或计划，不暴露隐藏推理。

## 不应复制的部分

- Shell、文件变更、Git、workspace、sandbox 等 coding-specific item。
- Codex 品牌、文案和具体视觉像素。
- 未标稳定的实验字段或 Codex 私有后端耦合。
- 把 Codex 的长任务预算原样移植；Aearn 必须继续使用教学场景的受控预算和 capability policy。
