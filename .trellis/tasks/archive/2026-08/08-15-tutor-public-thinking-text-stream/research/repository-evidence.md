# 仓库证据与约束

## 当前调用链

1. `aearn/services/api/app/services/tutor/run_loop.py:180-188` 在每次 decision iteration 同步调用 `provider.decide()`，provider 返回后才持久化 attempt receipt。
2. `aearn/services/api/app/services/tutor/provider_gateway.py:189-209` 调用 `complete_json()`，随后对完整 JSON 做原始公开文本安全检查、严格 schema 解析和最终 decision 安全检查；repair 最多进入下一 provider attempt。
3. `aearn/services/api/app/services/llm/llm_client.py:345-375` 的 Responses 路径已经发送 `stream=true`，但 `_parse_responses_stream()` 在 `:762-765` 只累积 `response.output_text.delta`，直到 completed envelope 才返回。
4. `aearn/services/api/app/services/tutor/decision_protocol.py:122-129` 当前 `agent_message` 同时包含最终回答 `text` 和一至四条 `public_thinking_steps[]`；`run_loop.py:302-327` 只在最终可发布分支把两者交给 terminal persistence。
5. `aearn/services/api/app/services/tutor/persistence.py:5131-5166` 在成功生命周期事务中一次性插入 Tutor message 与 `ITEM_ADDED` conversation event。

## 当前公开恢复链

1. `aearn/services/api/app/services/tutor/conversation_contracts.py:39-46` 的 conversation event kind 没有文本流事件；`:241-248` 对每种 payload 使用闭合 Pydantic adapter。
2. `aearn/services/api/app/services/tutor/persistence.py:2729-2825` 在 conversation row lock 下分配 event sequence，校验 payload/identity 并追加 append-only event。
3. `aearn/services/api/app/services/tutor/persistence.py:2221-2298` 的 snapshot 只返回 active turn、timeline、Queue/request/control 和 stream cursor，不含 active output。
4. `aearn/apps/desktop/src/hooks/useTutorConversationStream.ts:167-176` 验证 sequence、去重和 gap 后上送 event；`TutorConversationSurface.tsx:155-160` 当前对所有 event 只安排 snapshot refresh。
5. `docs/product/frontend-interaction-spec.md:139-141` 当前明确规定 event 只触发 snapshot refresh；本任务必须版本化更新这一规则，使新 output event 成为唯一允许局部消费的闭合例外。

## 当前持久化与兼容

1. `aearn/services/api/app/db/schema.sql:712-726` 的 `tutor_messages` 只有 `public_thinking_steps_json`，最多四项。
2. `aearn/services/api/app/services/tutor/persistence.py:1928-2084` 从该 JSONB 字段投影历史；`:6063-6076` 逐项安全归一化。
3. `aearn/apps/desktop/src/api.ts:2714-2732` exact-parse `public_thinking_steps[]`，未知或额外字段会拒绝整个 message。
4. `docs/architecture/api-contract.md:311-318` 与 `database-schema.md:60-73` 把步骤数组、成功消息原子持久化和 v1 event/snapshot 写成当前正式契约；必须同步迁移。

## 当前组件约束

1. `aearn/apps/desktop/src/ui/dsh-derived/primitives/DisclosureRow.tsx` 即使 `disabled=true` 仍渲染原生 button 和默认 chevron，只是禁用并降低透明度；不满足“无文本时隐藏展开按钮且没有可点击语义”。
2. 因此空 `Think` 必须由 Tutor feature adapter 渲染静态 heading；第一段文本到达后才切换为 `DisclosureRow`。
3. 当前工作树已经修改 `TutorConversationSurface.tsx`、相关测试、`styles.css`、前端交互规格和组件 spec，添加运行占位与高度适配；实施必须基于 scoped diff 融合，禁止 reset/restore。

## 设计结论

- 实时公开思考只能来自 provider visible `output_text` 中明确的 `message.public_thinking_text` 字段，不能消费 reasoning item。
- 正式回答在 decision gate、capability/effect 与 stale/lease 屏障之前仍不是权威；因此不提前透传 provider answer delta。成功消息持久化后，Desktop 才从权威 snapshot 获取回答并以字符队列逐字揭示。
- 为支持断线恢复，当前 active public thinking 必须有 PostgreSQL 短事务状态行和同一 conversation cursor 下的有界 append/reset/complete/discard event；仅保存在浏览器内存不足以满足 snapshot-first 恢复。
- output event 是 conversation SSE 唯一可局部消费的闭合 payload；其他事件继续只触发 snapshot refresh。
