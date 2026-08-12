# Aearn 当前工作树基线

## 1. 固定范围

- HEAD：`15587d1830f949bee5e17bd0a556b790038cd367`
- 分支：`main`
- 当前评估对象：上述 commit 加 tracked diff hash `f1fc432833e2aae6b21b83ec3d8e8a9d70becb86` 和 `research/baseline.md` 中记录的三个 untracked 文件。
- 记录时工作树：`35` 个 tracked 变更文件、`3` 个 untracked 文件。
- 本任务未修改任何 Aearn 产品源码。

## 2. 正式运行时组合

`docs/README.md:5-8` 明确当前正式产品 runtime 是 Tutor Harness，历史 Graph/router/SDK 产品路径已经移除。`docs/architecture/tutor-harness-runtime.md:28-38` 将组合根分成：

- public adapter；
- learning domain；
- interactive Tutor composition；
- Harness；
- PostgreSQL durable state；
- worker；
- desktop。

这意味着评估应从 `services/tutor/interactive.py` 和 `run_loop.py` 的生产组合开始，而不是从孤立测试、旧 Graph 文档或历史页面推断当前能力。

## 3. Agent 执行循环

### 3.1 Finite TurnRun

`aearn/services/api/app/services/tutor/run_loop.py:77-180` 展示了明确的有限循环：

1. 加载 run snapshot。
2. 获取 lease。
3. 检查取消、终态和预算。
4. heartbeat lease。
5. 读取最新 `input_revision`。
6. 重建 context。
7. 在 provider 边界前再次检查 revision。
8. 调用 provider。

`run_loop.py:193-278` 在 provider 返回后、decision gate 前以及 capability/effect 等 unsafe boundary 前再次刷新 lease/revision/cancellation。`max_iterations`、`max_model_calls`、`max_capability_calls` 和 `max_effects` 让循环有服务器拥有的停止条件。

### 3.2 Latest-input-wins 与 stale fencing

- `run_loop.py:141-177` 在 context load 和 provider call 之间检查 revision。
- `run_loop.py:193-205` 在 provider 返回后阻止 superseded result 继续写入。
- effect/capability receipt 还绑定 exact Skill、policy、revision 和 lease。
- `tests/test_tutor_input_merge.py:336` 覆盖 post-provider replacement 不能发布 stale message、title、capability 或 effect。

这是 Aearn 当前最成熟的 runtime 能力之一，比简单“对话请求进入一个 worker”更接近受控 agent transaction。

### 3.3 Terminal 与 checkpoint

- `run_loop.py:529-586` 把 terminal outcome 转换为 typed checkpoint、compaction request 和 durable result。
- `persistence.py:3106-3182` 对 checkpoint/event/outbox 做幂等写入和安全投影。
- `persistence.py:3848-3879` 强制 terminal、cancelled 和 active lease 不变量。

局限是 terminal compaction request 在 provider decision 之后才产生；它对下一轮可能有帮助，但不能修复本轮 provider 已经缺失的关键上下文。

## 4. 上下文生命周期

### 4.1 当前输入被强制保留

- `interactive.py:92-107` 从 exact input event/message 加载 authoritative current input。
- `context_builder.py:127-143` 在任何 optional section 之前先选择 current input。
- `context_builder.py:365-410` 在 current input 过大时做确定性截断，而不是直接丢弃。
- `provider_request.py:16` 明确冲突优先级：`current_input` 高于 history、summary 和 learner memory。

这一点对 latest-input-wins 很强，且已有 context builder/loader/input merge 测试覆盖。

### 4.2 历史加载与选择存在两层边界

- `interactive.py:122-147` 最多加载 `MAX_TUTOR_CONTEXT_COMPACTION_CANDIDATES` 条较早消息，并恢复成正序。
- `context_builder.py:34-42` 默认 `RECENT_MESSAGES` item limit 固定为 `4`。
- `context_builder.py:156-191` 只对最后四个 source 继续做 token fit；更早消息直接计入 skipped。

因此“loader 读取到了历史”不等于“provider 看到了历史”。固定 item cap 会在 token 仍充足时提前删除语义重要的信息。

### 4.3 Budget planner 比固定条数更先进，但无法补偿被固定 cap 排除的消息

`context_budget.py:119-223` 根据 provider capability、required input、optional budget 和 compact/normal/complex/extended mode 构造 context；`context_budget.py:354-405` 生成 warning/critical metadata 和高水位 compaction request。它能按 token 压力缩减低优先级 section，并支持一次受控 `REBUILD_CONTEXT` 扩展。

但 builder 在 recent-message section 内先应用 item limit，再进行 token 选择，因此更大的 token budget 或 mode expansion 不会自动恢复第 5 条及更早历史。当前 bug 的主因不是总 token 不够，而是语义无关的固定条数上限先于 token/importance selection 生效。

### 4.4 Summary/compaction 已有严谨契约，但时序是异步投影

- `context_builder.py:301-330` 从未选中的连续 prefix 构建 retirement input。
- `interactive.py:108-121` 只加载通过 lineage、coverage、freshness 校验的最新 summary。
- `curation.py:213-331` 由独立 curator 将 redacted evidence 提交为 structured summary 或 memory projection。
- `learner_state.py:1816-1920` 校验 summary schema/policy、coverage、source hash、prior lineage 和结构化语义。
- `tests/test_tutor_context_summary.py:279,399,448,495,541` 覆盖 round-trip、source hash、stale exclusion、append-only 和 gateway schema。

优点是 summary 可审计、append-only、版本化且不允许旧摘要覆盖新 correction；缺点是它经过 outbox/curation/worker 后才成为可加载 projection，不是与当前 provider call 同步完成的 inline replacement。

## 5. 重复询问每周时间预算的真实样本

### 5.1 已确认事实

前置日志诊断记录：

- conversation：`a13c83cb-e996-4ab9-be47-fff5875b754d`
- offending run：`8e08aa29-d84f-4c3f-9241-c6d6e48ed6a3`
- 用户此前回答“30小时”并被 Tutor 确认。
- 后续 run 的 loader 读取到 `8` 条 prior messages。
- provider selection 只包含最后 `4` 条，包含时间预算的较早消息被跳过。
- 当时 `working_summary` 为空。
- checkpoint 估算约 `3049` input tokens，未达到 warning，因此不是物理窗口耗尽。
- terminal compaction outbox 尚未形成当前调用可用的 summary。

### 5.2 架构归因

这是“语义状态仍寄存在聊天历史 + 固定 item cap + 异步 compaction 时序”共同造成的上下文正确性缺口：

1. 持久化层没有丢消息。
2. loader 也读取了相关历史。
3. builder 按条数而非语义重要性排除了它。
4. token budget 仍富余，因此 high-water 机制没有保护该字段。
5. plan session 在 collecting 阶段没有结构化 intake 字段。

`schema.sql:2891-2931` 的 `tutor_learning_plan_sessions` 只保存 status、preferred language、current draft 和版本等生命周期字段；`weekly_minutes`、`goal_text`、`experience_level` 等直到 draft 生成后才进入 `tutor_learning_plan_drafts`，见 `schema.sql:2933-2955`。所以 draft 之前的每周时间预算没有 server-authoritative structured slot，只能依赖 history/summary/model recall。

### 5.3 不是哪类问题

- 不是 PostgreSQL message persistence 失败。
- 不是 loader 查询顺序错误。
- 不是总 context window 太小。
- 没有证据支持简单归因为模型随机幻觉。

### 5.4 Codex-like 基线映射

Codex 的 inline auto-compaction + replacement-history + resume reconstruction 能减少“先丢历史、之后才异步摘要”的时序窗口，但仍不能替代 Aearn 的 intake 状态机。最适合 Aearn 的修复方向是：

- collecting session 保存 typed intake facts 和 provenance；
- provider context 永远注入当前已确认 intake snapshot；
- history/summary 用于语言连续性和未结构化细节，而非唯一事实来源；
- compaction 在决定排除语义关键消息前同步保证 replacement 可用；
- 加入“已确认 weekly budget 不得再次询问”的真实回归 case。

## 6. Skill、capability 与 effect

### 6.1 强类型、deny-by-default

- `agents/harness/capabilities.py:191-282` 定义 immutable descriptor、Pydantic schema、stable id/SemVer、policy tags 和 MCP-compatible schema export。
- `agents/harness/skill_catalog.py:206-263` 检查 duplicate capability/effect，`SkillCatalogCompiler` 只接受 reviewed descriptors/resource refs。
- `capability_gateway.py:40-99` 按 policy freshness、mode、runtime、budget、selected Skill 和 schema 逐层拒绝。
- `decision_gate.py:19` 是 catalog-aware gate，要求先选择 exact Skill，再在重建上下文后调用 action。
- `execution.py:398-605` 在事务内创建 durable execution job，消费 server-owned proof，并拒绝缺失、重复或 stale evidence。

相较于很多简单 agent 的“模型输出 tool name 就执行”，Aearn 的 capability/effect 安全边界非常严格。

### 6.2 工具广度有限

当前 approved generic capability 主要是 learning-plan draft 和 registry grounding，effect 主要是 plan、learner state、activity、memory 与 runner execution。Aearn 没有作为 Tutor runtime 工具暴露：

- 通用文件读取/搜索/patch；
- Git 操作；
- 任意 shell；
- 通用浏览器控制；
- 动态 MCP server/tool discovery；
- request-user-permission；
- agent-to-agent 控制。

这不是单纯缺陷：对于 learner-facing Tutor，缩小工具面显著降低风险。但如果目标是“像 Codex 的高度智能通用 agent”，当前 capability catalog 仍是窄领域 action system，而非通用 tool runtime。

## 7. 工作区与执行环境

Aearn 的“workspace”是产品级 Tutor workspace，不是 Codex 式代码仓库工作区。

已实现：

- Python、browser preview、TypeScript、SQL、Java/Go/C# teaching-grade runners。
- temp workspace、timeout、输出上限、hidden-test redaction。
- `runner_registry.py:122-245` 明确 runtime tier、timeout 和 sandbox disclosure。
- execution intent/job 使用 durable queue、lease、launch token、result receipt。

限制：

- `teaching_local` 不等于 OS-enforced production container sandbox。
- `container_verified` 仍要求 reviewed immutable image lock 和健康证据，不能因路由存在而声明可用。
- 没有 Git worktree、project filesystem、patch/apply、repo search 或 agent browser workflow。

## 8. 安全与审批

Aearn 当前安全模型偏“预先缩小能力 + 服务器所有权”，不是“允许广泛工具，再在每次危险动作前请求用户审批”。

强项：

- exact Skill evidence、catalog digest、policy fingerprint。
- server-owned request/effect IDs。
- lease generation、input revision、CAS 与 stale fencing。
- capability/effect 默认拒绝。
- safe projection、trace redaction、private rubric/hidden test 隔离。
- public executor fail-closed，不向 host subprocess 隐式回退。

不足：

- 没有 Codex 式统一 approval UX 和 per-command permission profile，因为 Tutor 没有通用任意命令工具。
- 本地 teaching runners 的隔离强度低于生产容器边界。
- 若未来扩展 MCP、文件或网络工具，现有 capability policy 需要升级为资源级 permission/sandbox 模型，不能只增加 descriptor。

## 9. 持久化、幂等与恢复

这是 Aearn 的第二个突出优势：

- PostgreSQL 保存 run snapshot、input event、ordered event、provider attempt、Skill selection、capability/effect receipt、checkpoint、compaction outbox 和 execution queue。
- `persistence.py:3106-3182` checkpoint/event/outbox 事务化并防重复。
- `persistence.py:3555-3576` 实现 lease acquire/heartbeat、revision 和 cancellation 查询。
- `persistence.py:3867-3879` stale lease 不能提交。
- event replay、same-request replay、effect CAS、expired lease recovery 和 curation backoff 均有测试。

与 Codex rollout 不同，Aearn 的 durable facts 是领域数据库表和 receipt；它更适合强一致的 learner/effect 状态。短板主要是对话语义 compaction 尚未成为同步 history replacement，因此“事务事实可靠”与“模型看到完整关键事实”之间仍有断层。

## 10. 记忆与领域状态

Aearn 将记忆拆成多层：

- raw conversation history；
- structured context summary；
- objective/inferred learner memory；
- active plan/activity；
- LearningTrack、LessonDocument、Exercise、Attempt、mastery evidence 等领域真相。

`interactive.py:155-199` 将 active plan、memory 和 activity 作为独立 context section 注入；`curation.py:430-480` 明确只允许使用 redacted evidence，不允许 raw prompt、runner/provider internal payload；learner controls 可禁用 inferred memory 并保留 lineage。

相较 Codex memory，Aearn 的优势是能把学习进度和 mastery 作为结构化 authoritative state；不足是：

- 尚无通用跨项目 recall workspace。
- summary 与 inferred memory 依赖异步 curation。
- collecting intake facts 尚未结构化。
- memory retrieval 当前主要按固定 limit，而非相关性、recency、confidence 和当前任务联合排序。

## 11. 计划、主动任务与多 agent

Aearn 已有 learning-plan session/draft/confirm、LearningTrack revision、proactive signal/candidate/curation scheduler。这些是领域计划和后台任务，不是通用 agent task graph 或多 agent orchestration。

- `proactive_worker.py:95-150` 明确 proactive composition 只启用一个 reviewed learner-state Skill，且没有 executable capability。
- 计划确认由 HTTP/server transaction 完成，模型不能自行创建最终 track。
- 当前没有 spawn-agent、fork-thread、agent message、并行 worktree 或 worker specialization 等通用多 agent能力。

## 12. 可观测性与评测

已实现：

- safe ordered events 与 SSE replay。
- provider attempt usage/cache accounting。
- redacted trace、checkpoint、capability/effect/execution receipts。
- `context_evals.py` 的 versioned context governance fixture、replay stability、correction 和 calibration receipt。
- `evals.py:1-159` 的 deterministic fake-only Harness eval。

局限：

- 评测主要是 fake-only/deterministic，不能证明真实模型教学质量。
- 已有 fixture 覆盖“newest history”“summary correction”“stale summary”，但没有覆盖本次“关键已确认 intake 位于第 5 条之外且 token 富余”的真实失败形态。
- 缺少面向线上行为的 SLO、重复提问率、上下文事实召回率、tool recovery 成功率和跨版本趋势面板。

## 13. 本次实际验证

由于 `uv run` 在当前 Windows 环境报 `uv trampoline failed to canonicalize script path`，改用项目现有 `.venv\Scripts\python.exe` 执行：

```powershell
.venv\Scripts\python.exe -m pytest -q \
  tests/test_tutor_context_builder.py \
  tests/test_tutor_context_budget.py \
  tests/test_tutor_run_loop.py \
  tests/test_tutor_capability_gateway.py \
  tests/test_tutor_evals.py
```

结果：`56 passed in 2.22s`。

第二组 PostgreSQL/持久化相关测试：

```powershell
.venv\Scripts\python.exe -m pytest -q \
  tests/test_tutor_context_loader.py \
  tests/test_tutor_context_summary.py \
  tests/test_tutor_run_repository.py \
  tests/test_tutor_effect_commit.py \
  tests/test_tutor_memory.py \
  tests/test_tutor_memory_curator.py \
  tests/test_tutor_event_replay.py \
  tests/test_tutor_trace_redaction.py
```

结果：`31 passed in 7.36s`。

合计 `87 passed`。这些结果确认当前实现与既有契约一致，但不会自动否定真实日志暴露的未覆盖 failure mode。

## 14. 基线判断

Aearn 已不是“LLM 包一层聊天 UI”，而是具备 finite loop、lease/revision、typed decision、exact Skill、capability/effect receipt、safe persistence、domain memory 和 eval fixture 的受控 Tutor Harness。

它与 Codex 的主要差距不在模型 API，而在：

1. context selection 尚未把语义关键事实和结构化 intake 置于固定条数 cap 之上；
2. compaction 是异步投影，不是当前 loop 的同步 history replacement；
3. tool runtime 仍是窄领域 catalog，缺少通用 workspace 工具、动态发现、permission 和 verify/recover 机制；
4. 没有通用 thread/fork/multi-agent/task continuation；
5. evals 尚未以真实失效样本、线上指标和长期趋势形成治理闭环。

Aearn 最不应放弃的优势是领域状态与强一致 receipt；最不应照搬的是把教学关键事实重新退化为通用聊天 memory。
