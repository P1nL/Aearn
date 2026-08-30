# Codex Runtime 术语与 Compaction 算法研究

## 结论

本任务中的 `Codex` 是 Aearn 启动并控制的本地 Codex App Server sidecar，不是模型名，也不是 OpenAI 托管业务 authority。模型推理由 `deepseek-v4-flash` 通过自定义 `aearn_deepseek` Responses provider 完成。

当前 provider 没有 remote compaction 能力证明，因此 MVP 应显式依赖 Codex local compaction。这里的 local 仅表示 compaction 编排与 history 替换发生在本地 Codex Runtime；语义摘要仍需一次普通 Responses 模型调用。

## Aearn 当前集成证据

- `aearn/services/api/app/agents/runtime/codex_supervisor.py:153-188`：校验 allowlisted Codex 可执行文件、隔离 `CODEX_HOME`、初始化 App Server。
- `aearn/services/api/app/agents/runtime/codex_supervisor.py:269-272`：实际启动 `codex app-server --stdio --strict-config`。
- `aearn/services/api/app/agents/runtime/codex_connection.py:125-139`：通过子进程 stdio 发送 JSON-RPC。
- `aearn/services/api/app/agents/runtime/codex_config.py:103-144`：生成 isolated Codex config，固定 `deepseek-v4-flash + aearn_deepseek + responses`。
- `docs/setup/codex-sidecar-runtime.md:5-14`：仓库正式运维边界同样把 Codex 定义为 controlled sidecar Runtime，而非数据 authority。

## Codex Thread/Turn/Item 契约

- `thread/start` 创建持久 conversation；`thread/resume` 恢复；`turn/start` 在同一 thread 内追加工作。
- `thread/compact/start` 只是手动触发入口，返回后通过标准 `turn/*`、`item/*` 生命周期发送 `contextCompaction`。
- reasoning、agentMessage、tool 和 contextCompaction 都是 ThreadItem；`item/completed` 是最终权威。

## 自动 Compaction 触发

Codex 根据活跃上下文 token 使用量与 `model_auto_compact_token_limit` 判断是否触发：

1. pre-turn：新 turn 开始前已达到阈值时先压缩；见 `codex-rs/core/src/session/turn.rs:1009-1023`。
2. mid-turn：模型仍需继续工作且上下文达到阈值时压缩后继续；见 `codex-rs/core/src/session/turn.rs:406-467`。
3. model switch/downshift 或 compaction hash 变化也可能触发 pre-turn compaction；见 `codex-rs/core/src/session/turn.rs:1091-1153`。
4. 手动触发由 `thread/compact/start` 进入 compact task。

Aearn 当前 exact model capability 是 context window `1_000_000`、最大 output reserve `384_000`、可用 input budget `616_000`。实现应把这些设置注入 isolated Codex config，使 Codex 的 auto-compact limit 与持久 run policy 使用同一 source of truth。

## Local Compaction 算法

当前 Codex local compaction 不是 gzip、向量检索或固定规则摘句，而是模型驱动的有损语义摘要：

1. 从 thread clone 当前 history。
2. 追加 Codex 内置 `SUMMARIZATION_PROMPT` 或显式 `compact_prompt`；见 `codex-rs/core/src/compact.rs:111-139`。
3. 通过当前 provider 的普通 Responses stream 调用模型生成摘要；见 `codex-rs/core/src/compact.rs:240-289,719-739`。
4. 如果 compaction 请求仍超过 context window，Codex 从最旧 history item 开始移除，优先保留近期内容；见 `codex-rs/core/src/compact.rs:309-318`。
5. 取 compaction turn 的最后一个 assistant message 作为 summary，添加 summary prefix；见 `codex-rs/core/src/compact.rs:347-354`。
6. 从真实 user messages 末尾向前选择，最多保留约 `20_000` tokens；最后一条可按剩余额度截断；见 `codex-rs/core/src/compact.rs:639-683`。
7. replacement history 由选中的 user messages、summary 和必要 initial context 构成；pre-turn/manual 在下一正常 turn 完整重注入上下文，mid-turn 在最后真实 user message 前重注入；见 `codex-rs/core/src/compact.rs:59-73,354-383,685-716`。
8. 原子替换 thread history、重算 token usage，并发送 `contextCompaction` completed；见 `codex-rs/core/src/compact.rs:374-393`。

因此 compaction 可能遗漏细节。Aearn 的 planning facts、LearningPlan 状态与权限不能只依赖摘要，必须每轮通过 typed tool 从 PostgreSQL 重新读取，并在 mutation 前重新 fencing。

## Local 与 Remote 的区别

- local：Codex client 组织 summary prompt、调用普通 Responses、选择保留项并替换 history。
- legacy remote：provider 的 `/responses/compact` 返回 provider-normalized replacement items。
- remote V2：通过普通 `/responses` 携带 capability/metadata，返回 compaction item。
- manual/automatic 只表示触发方式；local/remote 表示实现位置，两组概念彼此独立。
- Codex 在 `codex-rs/core/src/tasks/compact.rs:41-73` 和 `codex-rs/core/src/session/turn.rs:1186-1238` 按 provider capability 选择实现。

## Raw Reasoning 持久化决定

- 用户已确认 completed raw reasoning 写入 Aearn PostgreSQL 私有 runtime projection。
- active delta 需要可恢复 projection，支持 snapshot/SSE reconnect；completed item 原子覆盖为终态权威。
- final answer completed 后继续进入正式 Tutor message；reasoning 通过 Aearn item/run 关联历史消息。
- commentary 首轮不公开，也不作为 reasoning/answer 文本持久化。
- raw reasoning 不进入普通日志、trace、memory、facts、tool audit 或默认公共 export；reset/delete 必须清理。
