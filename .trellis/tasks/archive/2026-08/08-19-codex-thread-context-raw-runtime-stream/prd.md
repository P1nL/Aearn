# 重构 Codex Runtime 持久上下文与原始运行流

## 目标

修复计划制定会话在 fresh Aearn `TurnRun` 之间丢失自然对话上下文的问题，使一个 `TutorConversation` 复用一个持久 Codex thread、每个 fresh `TutorRun` 映射为该 thread 内的新 Codex turn；同时恢复服务端 typed planning request，并在 Desktop 单条 Tutor 消息中展示、恢复和回看真实 raw reasoning 与 raw final-answer delta。

## 用户价值

- 学习者回答了学习计划中某一项时，Tutor 必须记得前文已经确认的内容，不再重复询问，而是继续收集下一个缺失字段。
- 长计划会话由 Codex thread history 与 compaction 保持自然连续性，不依赖每轮手工拼接简化 transcript。
- 缺失规划字段通过精确 `question_key` 的 typed request 收集，服务端规划事实继续作为计划写入 authority。
- 当前轮可以看到模型实际发送的 reasoning 与最终回答增量；刷新、重连和历史回看后仍能看到已持久化的完成内容。

## 术语与边界

- 本 PRD 中未加限定的 **Codex**，统一指 **Aearn 控制的 Codex Runtime sidecar**：Aearn 启动 allowlisted `codex` 可执行文件，并以 `codex app-server --stdio --strict-config` 运行本地 App Server 进程。
- **Codex App Server** 是 Aearn 通过 stdio JSON-RPC 使用的 Runtime 控制面，提供 `thread/*`、`turn/*`、`item/*`、tool call、interrupt 与 compaction 生命周期；它不是 Aearn 的业务 authority。
- **Codex thread / turn / item** 是该 App Server 的持久会话、单次工作和运行输出对象，不是 Aearn 的公共 ID。
- **DeepSeek/provider** 才是实际完成模型推理的远程模型服务。当前固定目标仍是 `deepseek-v4-flash + aearn_deepseek + responses`；本任务不把 Codex 当成模型名、OpenAI 托管模型或新的业务后端。
- **Codex local compaction** 指 compaction 触发、摘要提示、history 选择与替换由本地 Codex Runtime 编排；生成语义摘要时仍通过普通 Responses 请求调用当前 DeepSeek provider，因此 local 不代表离线或不产生模型调用。
- **Codex remote compaction** 指 provider 明确支持并承担专用 compaction 协议，例如 legacy `/responses/compact` 或 capability-gated remote V2；当前 `aearn_deepseek` 不宣称支持。
- **raw reasoning / raw answer** 指 Codex App Server 已解析、规范化后的 item 文本，不是 provider HTTP/SSE 原始字节、token ID、raw response body、凭据或诊断。

## 背景与已确认事实

- 当前 `aearn/services/api/app/services/tutor/codex_dispatcher.py:116-195` 对每个 Aearn run 调用 `thread/start`，只把当前 learner message 发送给新 thread，导致 fresh turn 之间没有 Codex 原生历史连续性。
- 当前计划会话的实际数据出现两个 Aearn run 对应两个不同 external thread，且“我想学习python”“零基础”没有形成 confirmed planning facts，第二轮因此重新询问主题。
- Aearn 当前确实通过 `aearn/services/api/app/agents/runtime/codex_supervisor.py:153-188,269-272` 启动独立 Codex App Server，并在隔离 `CODEX_HOME` 下接入自定义 DeepSeek provider。
- Codex App Server 的正式模型是持久 `Thread -> Turn -> ThreadItem`：`thread/resume` 继续同一对话，`turn/start` 追加新请求，`thread/compact/start` 触发手动 compaction，`contextCompaction` item 表示压缩生命周期。
- Codex 的手动与自动 compaction 都按 `provider.capabilities().remote_compaction` 选择 local 或 remote 实现；`thread/compact/start` 只是触发接口，不等同于选择任何 remote compaction 协议。
- 当前 Aearn Runtime 使用自定义 `aearn_deepseek` provider、`wire_api = "responses"`，没有已验证的 remote compaction capability 或协议契约，因此当前基线不能宣称直接使用远程压缩。
- Codex local compaction 是有损语义压缩：模型生成摘要，Codex 保留 bounded 最近 user messages、摘要和必要初始上下文后替换旧 history；它不保证逐字保留全部对话。
- Codex App Server 提供 `item/agentMessage/delta`、`item/reasoning/textDelta`、`item/reasoning/summaryTextDelta` 和 reasoning item；是否存在 raw reasoning 取决于当前模型/provider 实际输出。
- 当前 Adapter 已接收 `item/agentMessage/delta`，但 projector 将 `MESSAGE_DELTA` 作为 non-public 忽略；当前 supervisor 没有订阅 reasoning delta 方法。
- 现有 Aearn typed planning request、planning fact、Queue、fresh TurnRun、LearningPlan draft/confirm、runtime generation/lease fence 与 conversation SSE 均应复用，不建立第二套领域 authority。

## 已确认产品决策

1. **采用 Codex 原生上下文模型。** 一个 `TutorConversation` 对应一个持久 external Codex thread；首轮使用 `thread/start`，后续 fresh Turn 使用 `thread/resume + turn/start`。
2. **保留 Aearn fresh TurnRun。** 一个 Aearn `TutorRun` 对应一个 Codex turn，仍有独立 deadline、预算、lease、input revision、Retry 与终态。
3. **职责分层。** Codex thread 负责自然对话历史、reasoning/answer items、工具循环和 compaction；PostgreSQL 继续负责用户、conversation、run、Queue、规划事实、LearningPlan/LearningTrack 与权限 authority。
4. **恢复 typed planning request。** 缺失规划字段必须通过 exact `question_key` 的 durable request 收集；普通自由文本不能靠猜测冒充 typed response。
5. **显示 raw reasoning。** 只展示 Codex App Server 实际发送的 `reasoning` item / `item/reasoning/textDelta`；不总结、不模板化，也不以 commentary 或 answer 伪造。
6. **显示 raw answer delta。** `agentMessage` 中 `phase=final_answer` 的 delta 直接流式展示；`item/completed` 的完整 item是最终权威并负责校准。
7. **三路输出严格区分。** raw reasoning、`agentMessage phase=commentary` 与 `agentMessage phase=final_answer` 按 item ID/phase 独立处理；首轮 UI 不单独展示 commentary，也不得把它混入 Think 或 answer。
8. **前端布局固定。** 单条 Tutor 消息内先显示 `● think ▼` 与左边框 raw reasoning，留出间距后直接显示流式最终回答；当前轮默认展开，历史轮默认折叠。
9. **不伪造能力。** provider 未发送 raw reasoning 时终态不保留空 Think，也不从 summary/commentary/answer 推断 raw reasoning。
10. **Compaction 由 Codex 执行、模式由能力决定。** 当前 `aearn_deepseek` 按未支持 remote compaction 处理，自动与手动触发均走 Codex local compaction；只有 capability/preflight 与协议 smoke 证明 provider 支持后，才允许显式启用 remote compaction。
11. **持久化 raw reasoning。** Aearn PostgreSQL 保存 owner-scoped 私有 runtime text projection；运行期 delta 可恢复，`item/completed` 的规范化完整文本为终态权威，历史消息刷新后继续可见。
12. **最小化隐私面。** raw reasoning 不进入普通日志、trace、memory curation、规划事实、LearningPlan、工具审计参数或默认公共数据导出；用户 reset/delete 必须清理对应私有 projection。

## 范围内

- conversation-level Codex thread binding、首次 start、后续 resume、worker restart 恢复、single-writer ownership 与 generation fencing。
- run-level external turn binding、Steer、Interrupt、Retry、stale event 与 dispatch recovery 适配。
- Codex thread history、默认 local 的 automatic/manual compaction、受控 remote capability 接缝和 `contextCompaction` item 投影。
- typed planning question 的创建、展示、响应、confirmed fact 写入和 same-thread fresh response turn。
- reasoning/final-answer/commentary item 类型与 delta/completed 事件规范化、排序、去重、恢复和终态校准。
- raw reasoning 与 active final-answer 的私有 durable projection、owner-scoped snapshot/SSE 和历史关联。
- conversation snapshot/SSE 合约、Desktop reducer 与指定内嵌 Think/Answer UI。
- additive schema migration、旧 per-run thread binding 兼容或迁移、回滚和数据删除范围。
- fake App Server、PostgreSQL、API、worker、Desktop 和可选真实 DeepSeek 协议 smoke。

## 范围外

- 修改或 Fork `openai/codex`。
- 更换 `deepseek-v4-flash`、`aearn_deepseek` 或 Responses 路由。
- 在 provider capability 与真实协议 smoke 未证明支持前，强制调用或宣称支持任何 remote compaction 协议。
- 由 Aearn 实现第二套摘要算法、手工拼接摘要 history 或把规划事实复制成 Codex transcript 替代品。
- 把 provider HTTP 原始 body、凭据、token、内部异常或协议诊断暴露到 Desktop。
- 将 Codex thread ID、turn ID 或 item ID 作为公共 Aearn ID。
- 将 Codex 变成 LearningPlan confirm、LearningTrack 创建、Queue 或规划事实写入 authority。
- 首轮公开展示 commentary，或提供 provider/raw protocol 调试面板。
- 将 raw reasoning 纳入默认公共 export；未来如需导出必须另设显式隐私契约。
- 同时切换 general Tutor、LearningTrack teaching、proactive、Lesson、Gate 或 Review 到 Codex Runtime。
- 生产部署、生产迁移、Git push。

## 功能需求

### R1：Conversation 级 Codex Thread

- 每个 `codex_sidecar_v1 + plan_drafting` conversation 最多拥有一个 active persistent thread binding。
- 首轮原子建立 conversation/runtime binding；后续 fresh run 必须 resume 精确 thread 后再 start turn。
- 同一 thread 在任意时刻只有一个 Aearn Runtime writer；worker restart 后通过持久 binding 与隔离 Codex Home 恢复，旧 generation callback fail closed。
- Aearn run 与 external turn 精确关联，外部 ID 保持私有。
- 已存在但无法 resume 的 thread 不得静默新建并丢失历史；当前 run 进入稳定 unavailable/retry 路径。

### R2：Codex 上下文与 Compaction

- 后续 turn 依赖同一 Codex thread 的持久 history，不重新创建空 thread，也不把简化 transcript 当作主连续性机制。
- automatic compaction 的阈值和生命周期交给 Codex；Aearn 从 exact model capability 配置注入 context window 与 auto-compact limit，不维护独立摘要器。
- 当前 `deepseek-v4-flash` 的 context window 为 `1_000_000`、最大输出保留为 `384_000`；Codex auto-compact limit 必须与 Aearn 已验证的 `616_000` input budget 对齐并由配置生成，不另写魔法常量。
- manual `thread/compact/start` 只作为受控触发接缝，不把该 RPC 等同于 remote compaction，也不由 Aearn 固定选择 remote endpoint。
- 当前 `aearn_deepseek` 必须走 Codex local compaction：通过普通 Responses 推理生成语义摘要，由 Codex 选择 bounded 最近 user messages、摘要与必要初始上下文并替换 thread history。
- compaction 是有损的；server-authoritative planning facts 必须通过工具重新读取，并在 domain mutation 前重新 fencing，以防摘要遗漏或漂移。
- 仅当 provider capability/preflight 与真实协议 smoke 明确证明 remote compaction 可用时，才允许切换到 Codex remote 分支；能力缺失或不确定时 fail closed 到 local。
- `contextCompaction` item 可审计但不冒充 Tutor answer；内部审计可记录 local/remote 模式，公共 Tutor DTO 不暴露 provider 协议细节或 compaction summary。

### R3：Typed Planning Request

- context tool 返回缺失字段时，Runtime 必须创建一个 exact field/question-key 的 durable planning request，首轮一次只询问一个必要字段。
- learner response 使用现有 closed union、request item ID、expected version 和 catalog version；成功后写 confirmed fact，并在同一 Codex thread 创建 fresh answer turn。
- 已确认字段不得重复询问，除非 learner 显式 reopen/correct。
- Codex history 与 planning facts 冲突时，以服务端 confirmed fact 为 authority，并通过工具结果约束本轮回答。

### R4：Raw Runtime 输出与持久化

- Adapter 订阅并规范化 reasoning、reasoning summary、commentary、final answer 的 started/delta/completed 生命周期。
- 每个 delta 绑定 conversation、Aearn run、external thread/turn/item hash、item type/phase、connection generation 和单调顺序。
- `reasoning/textDelta` 原样进入 raw reasoning channel；`agentMessage/delta` 仅在已知 `phase=final_answer` 时进入 answer channel。
- active reasoning 与 active final answer 使用 owner-scoped PostgreSQL runtime text projection 支持 snapshot/SSE 重连；不得把文本写入只应保存 hash/safe facts 的 receipt 表。
- `item/completed` 的规范化完整 item 为终态权威：原子校准 projection 文本、状态和 content hash；随后将 final answer 投影到正式 Tutor message，并把 completed reasoning 关联到该 message/run。
- commentary 可分类、排序和记 receipt，但首轮不保存或公开 commentary 文本；不得误路由到 reasoning/final-answer projection。
- 丢包、重放、跨 item、跨 generation、stale turn、sequence gap 与 completed mismatch 必须恢复或 fail closed。

### R5：Desktop 展示

- 同一 Tutor entry 内呈现可折叠小写 `think` 与下方无标题 answer，不建立两个独立卡片。
- raw reasoning 保留换行和空白，使用视觉左边框；当前轮默认展开，历史轮默认折叠。
- raw answer delta 实时追加；completed item 到达后无重复字符、无闪烁地校准最终内容。
- 刷新、SSE 重连、应用重启与历史分页后，completed reasoning 必须从 Aearn snapshot 恢复。
- raw reasoning 不可用时，运行期可以显示静态 `think` 状态，终态移除空 Think。
- commentary 首轮不显示，也不能被误路由到 Think 或 answer。

### R6：兼容、安全与治理

- additive 迁移保留现有 Aearn conversation/run/message/domain 数据，不删除旧 history。
- 旧 Harness `public_thinking_text` 继续按兼容路径展示；新的 Codex raw item projection 使用显式版本化 DTO，Desktop 在迁移窗口兼容旧/新 snapshot。
- runtime kind freeze、dedicated worker、isolated Codex Home、lease/generation fence、Queue/Steer/Interrupt/Retry 和 LearningPlan confirmation authority 保持有效。
- raw runtime 内容不得进入普通日志、trace、安全错误、provider capture、memory curation、LearningPlan facts、工具参数审计字段或默认公共 export。
- raw reasoning 的公开读取必须受 conversation owner scope 约束；external IDs、provider body、credential 和 raw protocol bytes 不进入公共 DTO。
- 用户 reset/delete 必须覆盖新增 runtime text projection；关闭 admission 或代码 rollback 不删除既有合法 history，除非用户执行对应删除动作。

## 验收标准

- [ ] “我想学习 Python”后回答“零基础”，第二轮使用同一 external Codex thread 的新 turn，回答明确保留 Python 主线且不重新询问主题。
- [ ] 连续至少五个 fresh Aearn turn 均映射为同一 thread 内不同 external turn；每个 Aearn run 仍拥有 fresh budget、lease 与终态。
- [ ] worker/App Server 重启后可 resume 同一 thread；旧 generation 的 reasoning、answer、tool 或 terminal callback 不产生公开覆盖。
- [ ] 隔离 Codex config 从 exact `1_000_000 / 384_000 / 616_000` capability 派生 context window 与 auto-compact limit；不得出现另一组手写阈值。
- [ ] 当前 `aearn_deepseek` 的长会话触发 Codex local compaction 后继续保持 Python、零基础和未决规划问题；不向未验证的 remote compaction endpoint/模式发请求。
- [ ] manual `thread/compact/start` 与 automatic compaction 均产生可审计的 `contextCompaction` 生命周期，但 compaction summary 不显示成 Tutor 回答。
- [ ] 缺少 `experience_level` 时出现 exact typed request；提交 `new` 后形成 confirmed fact，后续 turn 不再询问该字段。
- [ ] Desktop 按指定布局流式显示真实 raw reasoning 与 raw final-answer delta，并按 item ID/phase 严格隔离。
- [ ] active reasoning/answer 在 snapshot/SSE 重连后无重复恢复；completed reasoning 在刷新、重启和历史分页后保持逐字一致并默认折叠。
- [ ] provider 不发送 raw reasoning 时不伪造内容；终态不存在空 Think。
- [ ] commentary 不显示、不持久化为公开文本，也不进入 reasoning 或 final answer。
- [ ] `item/completed` 与已显示 delta 不一致时以 completed item 为权威并确定性校准。
- [ ] reset/delete 后对应 raw runtime projection 不可再读取；默认公共 export、普通日志、trace、facts 和 tool audit 中不存在 raw reasoning。
- [ ] external thread/turn/item ID、provider body、credential、raw protocol bytes 与内部错误不进入公共 Aearn DTO。
- [ ] schema bootstrap 可重复；focused/full pytest、Ruff、Mypy、Desktop tests/check、browser smoke 和 `git diff --check` 通过。

## 风险与延期项

- compaction 是模型驱动的有损语义摘要，不能替代 PostgreSQL planning facts；必须依赖工具重新读取和 mutation fence 降低摘要漂移风险。
- raw reasoning 会增加数据库体积和隐私面；本任务采用私有 projection、owner scope、删除覆盖和默认 export 排除，不在本任务引入独立 retention policy UI。
- remote compaction 只保留 capability 接缝；当前 MVP 不启用，未来需独立协议证明与回归验收。
- 当前任务没有未决的产品阻塞问题；进入实现前仍需用户审核本 PRD、`design.md` 与 `implement.md` 的最终汇总。
