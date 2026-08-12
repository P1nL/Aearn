# Codex 与 Aearn 十一维严格对比矩阵

## 1. 评分说明

- 评分范围：`0-5`。
- 加权得分：`维度权重 × 分数 ÷ 5`。
- Codex 与 Aearn 使用相同标尺；Codex 不预设满分。
- 评分绑定 `2026-08-11` 固定基线，不能直接外推后续 revision。
- Aearn 分数针对“通用 Agent Runtime 成熟度 + 2% 教学领域适配”，不是对当前 Tutor 产品价值的单一评分。

## 2. 总分

| 序号 | 维度 | 权重 | Codex 分数 | Codex 加权 | Aearn 分数 | Aearn 加权 | 差距 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | Agent 执行模型、循环与停止条件 | 12 | 4.6 | 11.04 | 4.2 | 10.08 | 0.96 |
| 2 | 上下文选择、预算、压缩与重建 | 16 | 4.5 | 14.40 | 2.5 | 8.00 | 6.40 |
| 3 | 会话状态、长期记忆与结构化领域状态 | 12 | 4.3 | 10.32 | 3.5 | 8.40 | 1.92 |
| 4 | 工具定义、发现、调用、结果反馈与恢复 | 14 | 4.8 | 13.44 | 3.1 | 8.68 | 4.76 |
| 5 | 工作区、文件系统、Git、shell、浏览器、MCP 与外部环境 | 10 | 4.8 | 9.60 | 1.8 | 3.60 | 6.00 |
| 6 | sandbox、审批、策略、安全和秘密边界 | 10 | 4.6 | 9.20 | 4.0 | 8.00 | 1.20 |
| 7 | 计划、任务分解、并发与多 agent | 5 | 4.5 | 4.50 | 2.0 | 2.00 | 2.50 |
| 8 | 持久化、checkpoint、幂等、取消、恢复与重放 | 9 | 4.7 | 8.46 | 4.2 | 7.56 | 0.90 |
| 9 | trace、日志、审计、指标和 evals | 6 | 4.3 | 5.16 | 3.9 | 4.68 | 0.48 |
| 10 | `AGENTS.md`、skills、plugins、hooks 和配置治理 | 4 | 4.8 | 3.84 | 3.1 | 2.48 | 1.36 |
| 11 | 教学领域适配与不应照搬的 Codex 机制 | 2 | 1.5 | 0.60 | 4.3 | 1.72 | -1.12 |
|  | **总分** | **100** |  | **90.56** |  | **65.20** | **25.36** |

上下文、记忆、工具三项合计：

- Codex：`38.16 / 42`，约 `90.9%`。
- Aearn：`25.08 / 42`，约 `59.7%`。

Aearn 的差距高度集中在上下文、通用工具和真实工作区，而不是 finite loop、持久化或基础安全。

## 3. 维度一：Agent 执行模型、循环与停止条件

### Codex

- **状态：已实现，成熟。**
- session/turn/tool loop 支持多轮模型调用、工具结果回灌、取消、并发和终态处理。
- token pressure 可在当前 turn 内触发 auto compaction。
- 证据：`codex-rs/core/src/session/turn.rs:397-454,1172-1230`；`tools/parallel.rs:41-205`；`tools/registry.rs:478-767`。

### Aearn

- **状态：已实现，成熟但领域化。**
- `TutorRunLoop` 有 lease、heartbeat、input revision、iteration/model/capability/effect budget、typed terminal outcome。
- provider 返回后和 effect/capability 边界前重新检查 revision/cancellation。
- 证据：`run_loop.py:77-278,529-586`；`test_tutor_run_loop.py:215,246,280,305,386,429,620,780`。

### 判断

Aearn 在“有限、受控、可拒绝”的单 run 生命周期上接近 Codex，甚至比通用 agent 更明确地拥有服务器停止条件。差距在于 Codex 的 loop 能围绕任意 workspace tool 持续执行和验证，而 Aearn 主要围绕少量教学 decision/capability/effect。

### 风险与建议

- 风险：未来若增加新 capability，只扩展 decision schema 而不扩展统一 tool lifecycle，会形成多个特殊循环。
- 建议：保留 `TutorRunLoop` 作为唯一 orchestration owner，把 capability/effect/execution 统一成可观测、可取消、可恢复的 action runtime，不另建旁路 agent loop。

## 4. 维度二：上下文选择、预算、压缩与重建

### Codex

- **状态：已实现，成熟。**
- `ContextManager` 管理 history/token 状态。
- auto compaction 在当前 turn 继续模型调用前执行。
- compacted history 以 replacement-history 形式安装和持久化。
- resume 从 replacement checkpoint 重建。
- 证据：`context_manager/history.rs:42-123,279-329`；`session/turn.rs:397-454,1172-1230`；`compact_remote_v2.rs:285-316`；`session/mod.rs:3312-3345`；`rollout_reconstruction.rs:318-354`。

### Aearn

- **状态：部分实现。**
- current input 强制优先，budget mode、warning/critical、summary lineage 和 compaction outbox 已实现。
- 但 `RECENT_MESSAGES=4` 在 token 选择前硬截断；异步 summary 未准备好时，关键旧事实会在 token 富余情况下消失。
- 证据：`context_builder.py:34-42,127-220`；`interactive.py:92-153`；`context_budget.py:119-223,354-405`。
- D 级证据：真实 conversation `a13c83cb-e996-4ab9-be47-fff5875b754d` 中，loader 读到 8 条，provider 只看到最后 4 条，已确认“30小时”被排除并再次询问。

### 判断

这是 Aearn 当前最高风险缺口。系统拥有精细 token metadata，却先按固定条数做与语义无关的删除；terminal compaction 又晚于当前 provider call。该缺口直接破坏用户对“系统记得自己刚刚说过什么”的基本信任。

### 风险与建议

- P0：把 planning intake facts 建成 typed server state，在 collecting 阶段即持久化。
- P0：recent history selection 从固定四条升级为“必须保留事实 + correction + unresolved question + 最近交互”的语义 pinning。
- P0：在排除关键历史前，保证同步 replacement summary 已可用于当前 provider call；至少增加 compaction barrier/fallback snapshot。
- P0：加入真实失败形态回归测试，而非只测试 newest-four 和已有 summary。

## 5. 维度三：会话状态、长期记忆与结构化领域状态

### Codex

- **状态：已实现，成熟。**
- session history/compaction、rollout、跨会话 memories、`AGENTS.md`/project docs 分层。
- memory 采用 per-rollout extraction + global consolidation，并有 secret redaction、eligibility、pollution 和 reset。
- 证据：`codex-rs/memories/README.md:38-157`；`memories/write/src/phase1.rs:320-322`；app-server memory API `README.md:185-186`。

### Aearn

- **状态：已实现但不完整。**
- raw history、structured summary、objective/inferred memory、active plan/activity、LearningTrack/mastery evidence 分层。
- Aearn 的结构化学习真相比 Codex 通用 recall memory 更适合教学领域。
- 但 collecting intake 没有 structured fields；memory/summary retrieval 固定 limit，异步 curation 有可见延迟。
- 证据：`interactive.py:155-199`；`curation.py:213-331,430-480`；`learner_state.py:1816-1961`；`schema.sql:2891-2955`。

### 判断

Aearn 不是“没有记忆”，而是记忆层次不均衡：长期领域对象较强，短期 planning intake 反而仍依赖聊天历史。Codex 更擅长通用跨会话 recall；Aearn 更擅长可信业务状态，但需要补齐 draft 前的事实层。

### 风险与建议

- 不能用 Codex-style memory 替代 `weekly_minutes`、goal、experience、constraints 等 typed facts。
- 为每个 memory/context fact 保存 source message、confirmation state、revision 和 superseded lineage。
- retrieval 应综合当前 task relevance、confidence、recency、active status，而非只有 limit。

## 6. 维度四：工具定义、发现、调用、结果反馈与恢复

### Codex

- **状态：已实现，参考级。**
- trusted/external registry、schema、exposure、router、parallel runtime、cancellation、terminal ownership、trace 和 executed-tool metadata 完整。
- 动态工具、MCP、shell、patch、filesystem、browser、plan、permissions、user input 和 multi-agent 共享统一调用模型。
- 证据：`tools/registry.rs:267-337,464-767`；`tools/router.rs:68-288`；`tools/parallel.rs:41-355`；`executed_tool_calls.rs:255-265`。

### Aearn

- **状态：已实现但范围窄。**
- exact Skill、immutable capability/effect descriptors、Pydantic schema、policy tags、两阶段 selection/action、receipt 和 default deny 很强。
- 当前 capability catalog 只有少量领域操作；不存在通用动态 discovery、MCP、filesystem、Git、shell 和浏览器工具。
- 证据：`capabilities.py:191-282,565-640`；`skill_catalog.py:206-317`；`capability_gateway.py:40-99`；`execution.py:398-605`。

### 判断

Aearn 的“工具安全质量”高于其“工具 runtime 成熟度”。它是强约束领域 command bus，不是 Codex 式通用 tool operating system。

### 风险与建议

- 不要直接把任意 MCP/tool 接入 provider schema；先建立统一 `ActionRuntime`：descriptor、resource scope、permission、timeout、cancel、receipt、public projection、retry class。
- 增加 executed-action metadata 回灌，明确模型何时已经调用、结果属于哪个 revision、是否可重试。
- 为每类 action 定义 verify step 与 recover policy，避免“handler 返回 committed 即认为业务完成”。

## 7. 维度五：工作区与外部环境

### Codex

- **状态：已实现，参考级。**
- thread 绑定 cwd/environment/runtime workspace roots；支持 filesystem、patch、shell、Git、worktree、browser/MCP 和远程环境。
- thread resume/fork 与 workspace 配合支持长任务隔离。
- 证据：`codex-rs/app-server/README.md:79-81,168-206`；shell/filesystem/MCP handlers。

### Aearn

- **状态：部分实现，领域边界明显。**
- 有 Tutor workspace UI 和 teaching runners/temp workspace。
- 没有 agent 可读写的项目文件系统、patch、Git、通用 shell、worktree、browser automation 或 MCP environment。
- `runner_registry.py:122-245` 的 sandbox 是练习执行能力，不等于 agent workspace。

### 判断

如果目标只是学习 Tutor，这个差距部分是有意的安全取舍；如果目标是“像 Codex 的高度智能 agent”，这是与上下文并列的最大结构差距。

### 风险与建议

- 先定义教学专用 workspace：lesson artifacts、submission、test result、grounding handles、temporary code workspace，不要直接开放仓库全读写。
- 通用 coding workspace 应作为独立 target adapter，不应污染 learner-facing Tutor capability surface。

## 8. 维度六：sandbox、审批、策略、安全与秘密边界

### Codex

- **状态：已实现，成熟。**
- OS/platform sandbox、approval policy、per-command escalation、filesystem/network permissions、exec policy 和 secret path 测试形成强制执行层。
- 证据：`shell_spec.rs:298-337`；`unified_exec/exec_command.rs:285-317`；config/exec sandbox tests。

### Aearn

- **状态：已实现，成熟但模型不同。**
- 通过缩小 action catalog、server-owned IDs、lease/revision/CAS、safe projection 和 execution tier fail-closed 限制风险。
- learner-facing runtime 没有通用 approval UX；本地 teaching runner 不等价于 production container sandbox。
- 证据：`capability_gateway.py:64-99`；`execution.py:437-605`；`persistence.py:3867-3879`；runner disclosure tests。

### 判断

Codex 是“广工具面 + sandbox/approval”；Aearn 是“窄工具面 + policy/receipt”。Aearn 当前模型适合产品，但未来扩大工具面时必须补资源级 sandbox 和审批，不能只依赖 Skill review。

## 9. 维度七：计划、任务分解、并发与多 agent

### Codex

- **状态：已实现，成熟。**
- plan、goal、pause/resume/steer、thread fork、并行 thread、spawn/send/wait/list agent。
- 证据：app-server thread API；`tools/handlers/multi_agents_v2/`；官方手册 `2747-2858`。

### Aearn

- **状态：部分实现。**
- 有 learning plan、LearningTrack revision、proactive scheduler，但这是领域计划，不是 agent 自主任务分解。
- 没有 subagent、forked execution context、并行 workspace 或 agent messaging。
- 证据：`proactive_worker.py:95-150`；learning plan session/draft/confirm tables/services。

### 判断

Aearn 现在不需要优先增加多 agent。单 agent 的 context invariant 尚有 P0 缺口，多 agent 只会放大状态、权限、成本和可观测复杂度。

## 10. 维度八：持久化、checkpoint、幂等、取消、恢复与重放

### Codex

- **状态：已实现，成熟。**
- append-only rollout、pending item retry、flush recovery、replacement history、resume reconstruction、thread fork/archive/compact/rollback。
- 证据：`rollout/src/recorder.rs:85-121,288,792-978,1605-1668`；`rollout_reconstruction.rs:82-120,318-354`。

### Aearn

- **状态：已实现，成熟。**
- PostgreSQL receipts、lease generation、revision、idempotency、event replay、checkpoint/outbox、execution/curation queue recovery。
- 证据：`persistence.py:3106-3182,3555-3576,3848-3879`；相关 repository/event/effect/curation tests。

### 判断

两者都强，但持久化对象不同：Codex 持久化通用会话/工具轨迹；Aearn 持久化强类型领域事实。Aearn 的主要差距是模型上下文重建没有完全复用其 durable facts，而不是数据库恢复能力差。

## 11. 维度九：trace、日志、审计、指标和 evals

### Codex

- **状态：已实现，成熟。**
- tool dispatch success/failure/timing、OpenTelemetry、thread/turn/item events、rollout、diagnostics 与广泛测试。
- 但本次未运行完整 Rust suite，不能声称所有平台实测通过。

### Aearn

- **状态：已实现但真实模型治理不足。**
- safe trace、SSE replay、provider usage、capability/effect/checkpoint receipt、versioned context evals。
- 本次运行 87 个聚焦测试全部通过。
- eval 仍以 deterministic/fake-only 为主，没有线上重复提问率、事实召回率、context-loss SLO 和真实 provider 趋势。

### 判断

Aearn 已有很好的审计骨架，但需要从“测试某个契约”升级到“持续衡量模型是否保持关键事实和成功恢复”。

## 12. 维度十：配置与扩展治理

### Codex

- **状态：已实现，参考级。**
- `AGENTS.md` 层级覆盖、skills、plugins、MCP、hooks、profiles 和 feature flags 构成用户/项目/组织多层治理。
- 证据：官方手册本地快照 `21080-21232,23737-23963,26828-26888`；对应开源 skills/plugins/MCP crates。

### Aearn

- **状态：已实现但开发者封闭。**
- Git-owned Skill catalog、exact SemVer、hash evidence、policy version 和 Trellis/docs source of truth 很强。
- 扩展通常需要开发者改代码、catalog 和组合根；没有面向用户/项目的动态 skill/plugin/MCP 加载层。

### 判断

Aearn 的治理更像“审核后的产品 capability 发布”，Codex 更像“可组合 agent platform”。二者都合理，但目标不同。

## 13. 维度十一：教学领域适配

### Codex

- **状态：通用能力可复用，领域模型缺失。**
- 能读写代码、执行测试、使用 docs/MCP 和记忆，但没有 Aearn 的 LearningTrack、LessonDocument、Exercise Gate、mastery evidence、learner memory controls。

### Aearn

- **状态：已实现，方向正确。**
- 领域状态、server-authoritative plan/track/exercise/evidence 和 safe learner projection 是核心优势。
- review、完整 workspace、真实 provider 教学质量和 production container fleet 仍未全部完成。

### 判断

Aearn 不应该试图成为 Codex 的复制品。正确方向是保留教学领域 authority，并选择性吸收 Codex 的 context、tool runtime、workspace isolation、recovery 和 governance 机制。

## 14. 严格结论

1. **Aearn 已拥有可靠的 agent transaction core。** finite loop、lease/revision、typed gate、receipt、checkpoint 和 PostgreSQL authority 不是原型级能力。
2. **Aearn 当前智能上限主要受上下文正确性限制。** 重复询问不是小 UX 问题，而是关键事实没有成为 server-owned state、固定 recent cap 先于语义选择、compaction 晚于当前调用的共同结果。
3. **工具差距是“运行时模型”而非简单数量。** Aearn 的工具安全强，但缺统一的动态 discovery、permission、cancel、result feedback、verify/recover operating model。
4. **工作区差距最大，但不能直接照搬。** learner-facing Tutor 不应获得任意 shell/Git；应先建立教学专用受控 workspace，再把通用 coding target 独立出来。
5. **记忆不是单向落后。** Codex 的跨会话 recall 更强；Aearn 的结构化学习事实更可信。真正缺口是 draft 前 intake 与模型上下文之间的桥。
6. **多 agent 不是近期优先级。** 在上下文不变量和工具 recovery 完成前增加并发，只会扩大漂移。
