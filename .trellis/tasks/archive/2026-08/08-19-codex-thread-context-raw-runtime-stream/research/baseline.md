# 当前差距与 Codex 契约基线

## 当前实现差距

- `aearn/services/api/app/services/tutor/codex_dispatcher.py:146-189`：每个 run 都 `start_thread`，只发送当前输入。
- `aearn/services/api/app/agents/runtime/codex_adapter.py:138-142`：已接收 `item/agentMessage/delta`。
- `aearn/services/api/app/services/tutor/runtime_projection.py:322-326`：`message_delta` 未投影。
- `aearn/services/api/app/agents/runtime/codex_supervisor.py:269-272`：notification allowlist 未包含 reasoning delta。
- `aearn/services/api/app/db/schema.sql:6424-6460`：当前 external thread/turn 绑定为 run-scoped。
- `aearn/apps/desktop/src/features/tutor/TutorConversationSurface.tsx:658-736`：现有 Think 只消费 Aearn `public_thinking_text`，未区分 Codex reasoning/commentary/final-answer item。

## Codex 官方契约

- Thread 是持久 conversation；`thread/start` 创建，`thread/resume` 继续，后续 `turn/start` 追加。
- ThreadItem 包含 `reasoning`、`agentMessage`、tool、`contextCompaction` 等类型。
- `agentMessage.phase` 区分 `commentary | final_answer`。
- delta 包含 `item/agentMessage/delta`、`item/reasoning/summaryTextDelta`、`item/reasoning/summaryPartAdded`、`item/reasoning/textDelta`。
- `item/completed` 是 item 的最终权威状态。
- `thread/compact/start` 通过标准 turn/item 生命周期投影 `contextCompaction`，但它只是手动触发接口，不指定 local 或 remote 实现。
- Codex 手动 compaction 在 `codex-rs/core/src/tasks/compact.rs:41-73`、自动 compaction 在 `codex-rs/core/src/session/turn.rs:1186-1238` 按 `provider.capabilities().remote_compaction` 选择 remote 或 local。
- Codex legacy remote compaction 使用独立 `/responses/compact` 路径；remote V2 通过常规 `/responses` 路径携带 remote-compaction capability/metadata；local compaction 则通过常规 `/responses` 路径和压缩提示词生成替代 history。
- Aearn 当前 `aearn/services/api/app/agents/runtime/codex_config.py:15-17,123-136` 只配置自定义 `aearn_deepseek` Responses provider，没有已验证的 legacy 或 V2 remote compaction capability，因此 MVP 基线必须是 Codex local compaction。
- raw reasoning 仅在模型/provider 支持并实际发送时存在，不能由客户端推断。

## 既有 Aearn 契约中需要保留的部分

- Aearn ID/DB 为业务 authority，external IDs 仅作私有 correlation。
- 一个 Aearn fresh TurnRun 保留独立预算、lease、input revision、Retry 与终态。
- Runtime kind 在 run 创建时冻结，禁止跨 Runtime fallback。
- Queue、Steer、Interrupt、typed request、LearningPlan confirm 与 LearningTrack 创建继续由 Aearn 拥有。
- dedicated `tutor-codex` worker、isolated Codex Home、单 writer 与 generation fence 不放宽。

## 规划建议

父任务拆为三个可独立验证的 child：

1. conversation-level Codex thread 生命周期与 compaction；
2. typed planning request 与 same-thread fresh response turn；
3. raw reasoning/raw answer stream、Desktop 与集成 QA。

Child 2 依赖 Child 1；Child 3 依赖 Child 1，并在 typed planning flow 验收时与 Child 2 做最终集成。
