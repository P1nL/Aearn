# Tutor 长对话摘要检索与压缩闭环

## 目标

把 Tutor 长对话上下文改造成“权威当前输入 + 最新既往原文 + 增量结构化摘要 + 相关可选事实”的稳定闭环。完整原始消息继续由数据库持久化；只有移出近期窗口的历史被压缩，摘要具备明确覆盖边界、版本、来源 hash、失效规则和冲突优先级，不能覆盖学习者最新纠正。

## 依赖

- 父任务：`08-04-tutor-context-governance-adaptive-budget`。
- 依赖 `08-04-tutor-latest-input-teaching-relevance` 提供 current input 与最新历史分离。
- 依赖 `08-04-tutor-adaptive-context-budget-planner` 提供近期窗口、动态预算和 high-water 决策。
- 复用 `08-04-tutor-provider-usage-cache-accounting` 的 usage receipt 做压缩成本和效果评估，但摘要正确性不依赖 usage 一定存在。

## 已确认事实

1. 当前已有 `WORKING_SUMMARY` context section、compaction request、durable curation outbox/job、curation provider 和 `tutor_context_summaries`。
2. 交互式 `PostgresTutorContextLoader` 当前未加载持久化 context summary，`working_summary` 实际为空。
3. 当前 `tutor_context_summaries.summary` 是最多 280 字符的纯文本，缺少 conversation scope、结构化字段和稳定历史覆盖游标。
4. 当前 curation outbox 只保存 source IDs/hashes 和安全 envelope，不含可用于语义摘要的原始消息；这是正确的持久化安全边界，但 worker 需要在处理时按 source identity 从权威数据库临时加载、校验和清理必要证据。
5. 普通新消息各自拥有新 run，`input_revision` 不是 conversation 级单调游标；摘要覆盖必须使用稳定 conversation timeline key，而不能只依赖 run-local revision。

## 压缩 Contract

### C1 — 近期原文窗口

- `current_input` 永远独立，不进入历史窗口和摘要。
- 从当前输入之前的 conversation 消息中按 `(created_at DESC, id DESC)` 选择最新候选，在 item/token 上限内保留；最终按 `(created_at ASC, id ASC)` 提供给模型。
- 近期窗口上限由预算 planner 决定，并保留配置的最大 item cap；不再固定依赖“取八条后取前四条”。

### C2 — 增量结构化摘要

- 新摘要只合并：上一版有效摘要 + 本次刚移出近期窗口且尚未覆盖的消息。
- 不反复摘要 current input 或仍保留在近期窗口中的原文。
- 结构化 schema 至少包含：
  - `schema_version`
  - `current_goal`
  - `confirmed_facts`
  - `completed_steps`
  - `rejected_paths`
  - `open_questions`
  - `learner_preferences`
  - `covered_through_created_at`
  - `covered_through_message_id`
  - `source_hash`
- 所有数组和文本有独立 item/字符上限；不得成为完整 history dump。

### C3 — 覆盖边界与幂等

- conversation 级覆盖游标使用稳定的 `(created_at, message_id)` timeline key；相同时间戳通过 ID 决定顺序。
- summary identity/fingerprint 绑定 conversation、前一摘要 hash、被压缩消息 ID/hash、schema/policy version 和覆盖游标。
- 重试相同输入必须复用同一摘要或得到同一内容 hash；不同证据不得复用相同 identity。

### C4 — 安全证据加载

- curation outbox/trace 继续只持久化 ID、hash、范围和安全 metadata。
- worker 在持有合法 job lease 时，从 `tutor_messages` 按 user/conversation/source IDs 临时加载被压缩消息，验证内容 hash、范围和未覆盖状态，再进行清理和摘要。
- 临时 provider 请求不得进入 trace/outbox；不得保存 raw conversation、prompt、reasoning、provider body、代码、路径、命令、SQL 或 credential。

### C5 — 检索与冲突优先级

- loader 只读取当前 user/conversation 下最新、未 stale、未过 retention、projection committed 且 schema/policy 兼容的摘要。
- 固定语义优先级：`current_input > recent_messages > working_summary > learner_memory/activity`。
- 当前输入或近期消息与摘要冲突时，不修改原始消息；provider instruction 明确以更高优先级为准，后续 compaction 生成纠正后的新摘要。

### C6 — 数据库与兼容性

- 采用 additive migration 扩展 `tutor_context_summaries`，保留现有短 `summary` 字段作为兼容/安全概览，并新增必要的 conversation scope、`summary_json`、coverage、schema version 和 source hash 字段。
- 旧 summary 行不伪造结构化字段；不兼容行不进入新 loader，可保留到 retention/delete 流程处理。
- reset/delete/export 遵守现有本地用户数据边界；公开 export 不暴露内部结构化摘要，除非 source-of-truth 明确允许 learner-safe projection。

### C7 — 触发与降级

- 触发包括近期窗口溢出、context high-water、成功终态、安全 checkpoint，以及目标/完成项/拒绝路径发生变化。
- 相同覆盖范围触发必须幂等去重。
- curation disabled、provider unavailable、摘要校验失败或 job stale 时，原始消息不删除；交互请求使用 current input、近期原文和其他安全上下文继续，或在必要信息不足时安全失败。
- context summary 是运行时上下文治理，不等同于 inferred learner memory；两者使用独立 policy/setting，不得因 memory opt-out 自动丢失必要对话连续性。

## 验收标准

- [ ] 对话超过近期窗口后，provider payload 包含最新既往原文和一份有效结构化摘要，不包含重复 current input。
- [ ] 摘要只覆盖移出窗口的消息，coverage cursor 在相同时间戳下仍稳定前进且不遗漏/重复。
- [ ] 用户说“我已经有了”后，旧摘要中的“尚未准备图片”不能覆盖当前输入；新摘要记录已完成事实和被拒绝路径。
- [ ] worker 只通过 source IDs/hash 临时加载必要消息；outbox、trace 和 receipt 不包含 raw message content。
- [ ] 相同前一摘要和相同退休消息集合重试时幂等，证据变化时生成不同 fingerprint。
- [ ] stale、过期、跨用户、跨 conversation 或 schema 不兼容摘要不会进入模型。
- [ ] summary provider/worker 失败不删除原始消息、不泄露内容，也不阻止下一条普通消息创建 fresh TurnRun。
- [ ] 旧 280 字符 summary 行保持数据库兼容，但不会被伪装成新结构化摘要。
- [ ] 聚焦数据库、curation、context builder/loader、run-loop 测试、Ruff、Mypy、任务验证和 `git diff --check` 通过。

## 范围外

- 删除或改写完整 `tutor_messages` 历史。
- 将摘要作为学习者可编辑记忆、conversation rename 或公开聊天消息展示。
- 把 inferred memory 与 context summary 合并为同一设置或数据表。
- 使用向量数据库或外部搜索服务作为本任务必需依赖。
- 对全部历史进行一次性全量重新摘要。
