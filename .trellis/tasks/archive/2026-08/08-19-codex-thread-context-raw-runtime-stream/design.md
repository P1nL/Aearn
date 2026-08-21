# 技术设计：Codex Runtime 持久上下文与原始运行流

## 1. 设计目标

在不改变 Aearn 领域 authority 的前提下，把 `plan_drafting` 的 Codex 集成从“每个 run 一个新 thread”改为“每个 conversation 一个持久 thread、每个 run 一个新 turn”，并建立可恢复、可审计且 owner-scoped 的 raw reasoning / final-answer 流。

核心结果：

- 自然语言连续性由 Codex thread history 与 compaction 负责。
- 规划字段、LearningPlan、Queue、run/lease/version 与权限继续由 PostgreSQL/Aearn 负责。
- raw reasoning 与 final answer 通过明确 item/phase channel 投影，不再混用 `public_thinking_text`。
- 当前 DeepSeek provider 使用 Codex local compaction，remote compaction 保持关闭。

## 2. 运行时边界

```text
Desktop
  │ snapshot v3 + conversation SSE
  ▼
Aearn API / PostgreSQL
  ├─ TutorConversation / TutorRun / Queue / typed request / planning facts
  ├─ conversation-level Codex thread binding
  ├─ run-level Codex turn binding
  └─ owner-scoped runtime text projection
          │ durable job + lease/generation fence
          ▼
    tutor-codex worker
          │ stdio JSON-RPC
          ▼
    local Codex App Server sidecar
          │ Responses API
          ▼
    deepseek-v4-flash / aearn_deepseek
```

“Codex”在此层只代表本地 Runtime/harness：thread、turn、item、tool loop、context 与 compaction。它不拥有 Aearn 数据，不执行 LearningPlan confirm，不直接成为公共 API。

## 3. 持久 Thread 数据模型

### 3.1 新表：`tutor_conversation_runtime_threads`

建议字段：

- `id uuid`：Aearn 私有 identity。
- `user_id`、`conversation_id`：owner scope，复合 FK 指向 conversation。
- `runtime_kind`：固定 `codex_sidecar_v1`。
- `runtime_version`、`protocol_version`、`model`、`model_provider`：创建时冻结的 exact target。
- `external_thread_id`：私有，唯一，不进入公共 DTO。
- `state`：`active | unavailable | retired`。
- `migration_mode`：`native | adopted_legacy | legacy_reseed`。
- `created_at`、`updated_at`、`last_resumed_at`、`last_compacted_at`。

约束：

- `(user_id, conversation_id, runtime_kind)` 最多一个 `active` binding。
- `external_thread_id` 全局唯一。
- identity 与 frozen target 不可更新；只允许受控状态和时间字段变化。
- 删除受用户 conversation reset/delete 路径控制，不允许普通 runtime 流随意删除。

### 3.2 调整 `tutor_run_runtime_bindings`

- 新增 `conversation_runtime_thread_id`，引用 conversation-level binding。
- `external_turn_id` 继续由 run binding 拥有并保持唯一。
- 移除当前 `(runtime_kind, external_thread_id)` 的 run-level 唯一约束；同一 thread 必须允许被多个 run 引用。
- 为兼容既有审计，可暂时保留 `external_thread_id` 冗余列，但其值必须与 conversation binding 一致；后续版本再考虑移除。
- `connection_generation` 继续表示该 run 实际 dispatch 的 App Server generation，不放到 conversation binding 中冻结。

### 3.3 旧数据迁移

- 既有 run binding 和 receipt 原样保留，不重写 external IDs。
- 一个 conversation 若只有一个可恢复 legacy thread，可建立 `adopted_legacy` conversation binding。
- 若存在多个 legacy per-run thread，不静默任选一个。下一 fresh run 建立新的 canonical thread，并用 bounded learner-visible timeline + authoritative planning context 形成一次性 `legacy_reseed`；之后只沿 canonical thread 继续。
- `legacy_reseed` 是迁移接缝，不是每轮 transcript 拼接机制；必须有迁移状态、测试与审计 receipt。

## 4. Thread/Turn 生命周期

### 4.1 首轮

1. 锁定 conversation 和 run，验证 `runtime_kind=codex_sidecar_v1`、lease、input revision、exact readiness。
2. 原子查询或创建 conversation thread binding。
3. 无 binding 时调用 `thread/start`，持久化 `external_thread_id`。
4. 调用 `turn/start`，把 fresh run 绑定到返回的 external turn。
5. 进入事件循环并按 generation/lease fence 投影。

### 4.2 后续 fresh run

1. 加载 conversation thread binding。
2. 在当前 isolated `CODEX_HOME` 中调用 `thread/resume`。
3. resume 成功后调用 `turn/start`；每个 Aearn run 只创建一个新 external turn。
4. active turn 的 learner revision 仍通过 `turn/steer`；cancel/supersede/lease loss 仍通过 `turn/interrupt`。

### 4.3 恢复与失败

- worker/App Server 重启后，用持久 `external_thread_id` 调用 `thread/resume`。
- resume 不可用、thread 缺失或 config target 不一致时，当前 run 进入稳定 `unavailable`；不得偷偷 `thread/start` 丢失历史。
- 旧 generation 的 item/tool/terminal callback 只写 `ignored_stale` receipt，不更新 text/message/domain projection。
- Retry 创建 fresh Aearn run，继承相同 runtime kind 和 conversation thread，不重用旧 external turn。

## 5. Compaction 设计

### 5.1 配置来源

`ensure_codex_runtime_home` 从同一组 exact model capability 派生并写入 isolated Codex config：

- `model_context_window = 1_000_000`
- `model_auto_compact_token_limit = 616_000`
- `model_auto_compact_token_limit_scope = "total"`

数值必须来自 `Settings`/共享 capability helper，不在 Codex config 模块另写常量。`616_000` 是 `1_000_000 - 384_000` 的 verified input hard budget，不是每轮必须填满的目标。

### 5.2 当前 local compaction

Aearn 不调用摘要函数。Codex 到达阈值后自动执行或由 Aearn 受控调用 `thread/compact/start`：

1. Codex clone thread history。
2. 追加内置 `SUMMARIZATION_PROMPT`。
3. 通过普通 DeepSeek Responses 调用生成语义摘要。
4. 请求过大时从最旧 history item 开始裁剪。
5. 选择最近真实 user messages，Codex 当前上限约为 20K tokens，并加入 summary。
6. 按 pre-turn/mid-turn 规则重注入 initial context。
7. 原子替换 history、重算 token usage，发送 `contextCompaction` completed。

Aearn 只观察生命周期、记录 safe mode/status/timestamp，不读取或展示 compaction summary。

### 5.3 领域一致性

compaction 有损，因此每个 planning turn 必须：

- 通过 `aearn_planning_context_read` 获取最新 confirmed facts、missing fields、版本和 authority 状态。
- 在创建 typed request 或写 LearningPlan draft 前重新验证 run/input/lease/fact revision。
- Codex history 与工具结果冲突时以工具返回的 server facts 为准。

### 5.4 Remote capability 接缝

- 当前 custom provider 视为 `RemoteCompactionSupport::Unsupported`，只验收 local 路径。
- future remote enablement 需要 exact capability read、fake protocol contract 与 opt-in real-provider smoke。
- 不把 `thread/compact/start` 当作 remote feature flag。
- 不在本任务对 DeepSeek 未公开能力做探测性生产调用。

## 6. Runtime Item 规范化

### 6.1 内部 channel

Adapter 输出 closed union：

- `reasoning_started | reasoning_delta | reasoning_completed`
- `reasoning_summary_*`：保留独立内部类型，首轮不进入 raw reasoning UI。
- `agent_message_started | agent_message_delta | agent_message_completed`，必须携带 `phase=commentary|final_answer`。
- `context_compaction_started | context_compaction_completed`
- 既有 tool/turn/warning 生命周期。

每个事件携带：

- private external thread/turn/item identity；进入数据库/public 层前转换为 hash。
- `connection_generation`、run/input revision、event sequence、occurred_at。
- item kind、phase、status、text delta 或 completed text/content hash。

### 6.2 Supervisor allowlist

将 reasoning delta/summary/compaction 与 agent message lifecycle 加入 notification allowlist。未知 notification 继续计数并 fail closed，不能自动视为公开文本。

## 7. 私有文本 Projection

### 7.1 新表：`tutor_runtime_text_items`

建议字段：

- `id uuid`：Aearn item identity，可用于公共 DTO；不暴露 external item ID。
- `binding_id`、`conversation_runtime_thread_id`、`run_id`、`user_id`、`conversation_id`。
- `external_item_hash`。
- `channel`：`reasoning | final_answer`。
- `state`：`streaming | completed | discarded | blocked`。
- `text`：Codex-normalized文本；bounded，保留原换行和空白。
- `last_event_sequence`、`content_hash`、`connection_generation`。
- `public_message_id`：final answer 完成后关联正式 Tutor message；reasoning 同样可通过 run/message 关联历史 entry。
- `created_at`、`updated_at`、`completed_at`。

唯一性：

- `(binding_id, external_item_hash, channel)`。
- 事件 sequence 与 receipt 保持幂等，delta 只允许按单调 sequence 追加。

### 7.2 写入规则

- started：创建空 `streaming` row，但空 reasoning 不公开。
- delta：在同一事务中验证 generation/lease/input/sequence 后追加 text，更新 hash/sequence，并发布 `turn_output` 事件。
- completed：以 completed item 全文原子替换当前 text，校准 hash，状态改为 completed。
- final answer completed：完成 safety 检查后创建/校准 `tutor_messages`；把 text item 关联到 message。
- reasoning completed：关联同一 run 的 Tutor message；如果该 run 无最终消息，仍只保留私有 run projection，不生成空 message。
- discard/interrupt/stale：不得进入历史 Think；已持久 streaming row 标为 discarded 或由权威 terminal state清理。
- commentary：只记录 safe receipt/hash，不保存文本到 `tutor_runtime_text_items`。

### 7.3 隐私与删除

- public query 必须 join conversation owner scope。
- 普通日志、trace、provider receipt、tool audit、memory、facts 不包含 text。
- user reset/delete transaction 显式清理 text projection，再处理 conversation/run 关联；对应测试必须覆盖。
- 默认公共 export 不读取该表；未来导出需独立版本化隐私契约。

## 8. Typed Planning Request

- Codex 每轮通过工具读取 `confirmed_facts`、`missing_fields` 和 exact catalog。
- 当一个字段缺失时，tool handler 创建 existing `tutor_interaction_requests` row，返回 exact `request_id/question_key/version/presentation`。
- Tutor 的 final answer 只负责自然语言提问；Desktop composer 由 durable request descriptor 接管。
- learner 提交 typed response 后，现有 authority 写 confirmed fact，然后创建 fresh run；dispatcher resume 同一 Codex thread 开始新 turn。
- 已 confirmed 字段只在显式 correction/reopen 时改变。

## 9. Public API 与 SSE

### 9.1 Snapshot 版本

引入 `tutor_conversation_snapshot_v3`，迁移窗口 Desktop 同时接受 v2/v3：

- v3 增加 `active_runtime_output`，包含 owner-safe Aearn item ID、turn ID、input revision、generation、reasoning/answer text、各自状态与 last sequence。
- historical Tutor message 增加 `reasoning_text` 或版本化 `runtime_output`，不复用容易与旧 authored `public_thinking_text` 淆的字段。
- Harness v1 snapshot 可继续投影旧 `public_thinking_text`；Codex raw reasoning 只走新字段。

### 9.2 SSE

`turn_output` 增加 closed payload `tutor_runtime_item_stream_v1`：

- `channel = reasoning | final_answer`
- `operation = reset | append | complete | discard`
- `item_id` 为 Aearn opaque projection ID。
- 包含 input revision、generation、chunk sequence。
- 不包含 external IDs、phase 以外的 provider metadata 或 raw protocol。

SSE 仍只作为刷新/低延迟提示；snapshot/DB 是 reconnect authority。sequence gap、cursor invalid 或 item mismatch 时停止本地追加并刷新 snapshot。

## 10. Desktop 状态机

- 每个 active Codex turn 建立一个 Tutor entry shell。
- reasoning 到达后显示 `● think ▼`；保留 whitespace，使用左边框。
- current turn 默认展开；历史 completed reasoning 默认折叠。
- final answer delta 紧接 Think 下方追加，无 `Answer` 标题和独立卡片。
- completed item 与 live text 不一致时无闪烁替换为 completed authority。
- commentary 不渲染。
- terminal 时 reasoning 为空则删除 Think；存在 completed reasoning 则与 final Tutor message 一起进入 timeline。
- 保留键盘展开、focus、reduced motion、窄屏和滚动锚点行为。

目标结构：

```text
● think ▼
  │ 用户已经确认 Python……
  │ 当前新增事实是零基础……
  │ 下一步只需要确认学习目标……

  好的，已确认你是零基础，学习主题仍然是 Python。
  接下来想确认一下：你学习 Python 主要想做什么？
```

## 11. 兼容与回滚

- schema 全部 additive；bootstrap 可重复。
- Desktop 在迁移窗口解析 snapshot v2/v3，旧 Harness 行为不被迫切换到 raw reasoning。
- feature/admission off 只阻止新的 Codex conversation；既有 Codex lineage、text projection 和审计不跨 Runtime fallback。
- 出现 P0 回归时可关闭新 admission、停止 `tutor-codex` worker；不删除 thread binding 或已完成消息。
- raw reasoning UI 可以通过 server projection feature gate 暂停公开，但数据库与 receipt 保持一致，恢复时不需重跑模型。

## 12. 验证设计

### 后端

- conversation thread create/resume/concurrent get-or-create。
- multi-run same-thread、fresh-turn、Retry、Steer、Interrupt、restart、stale generation。
- local auto/manual compaction、threshold config、`contextCompaction` receipt、无 remote request。
- reasoning/answer item started/delta/completed、phase isolation、sequence gap/replay、completed calibration。
- text projection owner scope、reset/delete、export/log/receipt redaction。
- typed request exact question key、confirmed fact 与 same-thread answer turn。

### Desktop

- current reasoning expanded、historical collapsed、whitespace、keyboard/a11y。
- answer delta 直接位于 Think 下方。
- commentary 不渲染、无 reasoning 时无空 Think。
- snapshot/SSE reconnect、duplicate/gap/reset/discard/completed mismatch。
- v2/v3 compatibility、narrow viewport、reduced motion、scroll anchor。

### 集成

- fake App Server 证明两轮 Python/零基础使用同一 thread。
- fake long-context 触发 local compaction 并保持 authority facts。
- worker/App Server restart 后 resume。
- 可选真实 DeepSeek smoke 只验证已批准的普通 Responses/local-compaction 兼容，不探测未声明 remote endpoint。
