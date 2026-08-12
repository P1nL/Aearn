# Codex 源码基线

## 1. 固定范围

- 研究对象：`openai/codex`
- revision：`e20616d2650de6cde27e8513cbf266ed75851071`
- commit 时间：`2026-08-11T16:31:30Z`
- 证据优先级：固定 commit 源码与测试为 A 级；官方 Codex 手册为 B 级。
- 本文件只描述开源 runtime 和公开产品表面，不推断未开源云端内部实现。

## 2. Agent 执行模型

Codex 的核心不是一次 prompt-response，而是可持续的 session/turn/tool loop：模型输出可以触发工具调用，工具结果再次成为模型可见 item，直到产生终态消息、被取消、发生不可恢复错误或上层中断。

关键证据：

- `codex-rs/core/src/session/turn.rs:397-454` 在回合内部检查 context-window token 状态，并可在继续模型调用前触发自动压缩。
- `codex-rs/core/src/session/turn.rs:1172-1230` 集中执行 `run_auto_compact`，不是把压缩交给 UI 或下一次独立请求。
- `codex-rs/core/src/session/turn.rs:1315` 将模型是否支持 parallel tool calls 写入请求。
- `codex-rs/core/src/tools/parallel.rs:41-205` 把 tool dispatch 建模为可取消的 runtime，并区分并行与串行 admission。
- `codex-rs/core/src/tools/registry.rs:478-767` 对工具 dispatch、错误、trace 和 terminal outcome 进行统一处理。

其强项是通用、开放的循环与工具生态；停止条件更多由模型完成、用户中断、错误或外部 goal/thread 控制决定，不像 Aearn 那样为单个 Tutor run 固定 `max_iterations`、`max_model_calls`、`max_effects` 等领域预算。

## 3. 上下文生命周期

### 3.1 历史不是固定最近 N 条

`ContextManager` 持有模型可见 history、token usage 和上下文不变量：

- `codex-rs/core/src/context_manager/history.rs:42-123` 定义 history 与 token 状态。
- `codex-rs/core/src/context_manager/history.rs:279-329` 更新并读取 total/last token usage。
- `codex-rs/core/src/session/context_window.rs` 根据模型窗口和当前用量判断压缩或新窗口边界。

Codex 的关键策略是按模型上下文压力进行压缩和 history replacement，而不是无条件只选择最后几条消息。

### 3.2 压缩发生在当前执行循环内

- `codex-rs/core/src/session/turn.rs:397-454` 在 token limit 或显式新窗口请求出现时，在当前 loop 内执行压缩。
- `codex-rs/core/src/compact_remote_v2.rs:285-316` 构造新历史并调用 `replace_compacted_history`。
- `codex-rs/core/src/session/mod.rs:3312-3345` 持久化带 `replacement_history` 的 compaction item，替换内存 history，并保存建立该基线所需的 reference context。

这形成一个重要不变量：压缩结果先安装成新的模型可见 history，后续模型调用再继续。它不能保证摘要语义永远正确，但避免了“已经知道必须压缩，却仍用缺失关键历史的旧选择先回答一次”的结构性时序问题。

### 3.3 Resume 能重建压缩后的历史

- `codex-rs/core/src/session/rollout_reconstruction.rs:82-120` 将 surviving replacement-history checkpoint 视为完整 history base。
- `codex-rs/core/src/session/rollout_reconstruction.rs:318-354` 优先恢复 replacement history，并兼容早期没有 replacement-history 的 legacy compaction。

因此 compaction 不只是内存优化，还进入持久化和 resume 重建契约。

### 3.4 工具元数据进入后续上下文

- `codex-rs/core/src/tools/executed_tool_calls.rs:255-265` 将已执行工具元数据附加到模型可见 item，并对总量进行边界控制、优先保留较新调用。

这使模型能够区分“计划调用工具”和“工具已经真实执行”，减少重复执行，但仍依赖工具 handler 返回足够、正确且经过截断控制的结果。

### 3.5 外部上下文污染防护

- `codex-rs/core/src/session/turn.rs:2125` 在外部上下文进入时调用 memory-pollution 标记逻辑。
- rollout metadata tests 覆盖 memory mode 从普通状态变为 `polluted` 的持久化读取。

这说明 Codex 不把所有外部内容默认当成可安全沉淀的长期记忆。

## 4. 工具体系

### 4.1 Registry 与来源边界

- `codex-rs/core/src/tools/registry.rs:267-337` 定义 `ToolRegistry`，区分 trusted 与 external runtime，并处理 exposure。
- `codex-rs/core/src/tools/registry.rs:464-478` 查询工具是否允许并行，并进入统一 dispatch。
- `codex-rs/core/src/tools/router.rs:68-288` 将模型 tool call 路由到具体 runtime。

工具不是散落在 prompt 中的字符串约定，而是有 schema、runtime、exposure、来源和 dispatch 语义的注册系统。

### 4.2 并发、取消与终态原子性

- `codex-rs/core/src/tools/parallel.rs:104-205` 在 dispatch 前记录工具调用，依据 handler 能力选择读锁或写锁，并用 `CancellationToken` 处理取消。
- `codex-rs/core/src/tools/registry.rs:476-478` 明确要求 active-turn accounting 保持原子。
- `codex-rs/core/src/tools/registry.rs:764-767` 使用原子标志保证 terminal outcome 只由一个路径拥有。
- `codex-rs/core/src/tools/parallel.rs:315-355` 记录 dispatch、handler 与总耗时。

### 4.3 工具覆盖

固定 commit 中存在以下 handler/runtime 类别：

- 文件读取、搜索、patch 和 image inspection。
- shell/unified exec、持续会话和 stdin 交互。
- MCP tools/resources、dynamic tools、tool search。
- plan、request permissions、request user input。
- skills、plugins 与多 agent 控制工具。

这是一套通用 coding-agent workspace 工具，而非只服务某个领域 action catalog。

### 4.4 工具闭环仍依赖 agent policy

源码提供 dispatch、取消、trace、sandbox 和结果回灌，但“执行后必须运行哪些测试、遇到失败如何修复、何时认为完成”仍由 system/developer/`AGENTS.md`/skill/当前任务指令共同约束。Codex runtime 提供闭环基础设施，不等于每个 prompt 都自动拥有同等严格的 verify/recover 质量。

## 5. 工作区与环境

Codex 把真实代码工作区作为一等运行边界：

- app-server `thread/start`、`thread/resume`、`thread/fork` 可携带 cwd、runtime workspace roots、environment 和 permission overrides，见 `codex-rs/app-server/README.md:79-81,168-171`。
- `thread/fork` 能按 turn boundary 复制历史，并支持 ephemeral fork。
- shell、patch、Git、filesystem、browser/MCP 等工具在同一 thread/turn 上下文中协作。
- 官方产品表面公开提供 project、worktree 和并行 thread，但这些产品能力的全部内部实现不在本次开源源码断言范围内。

## 6. 权限、sandbox 与安全

### 6.1 Sandbox 与 approval 分离

- `codex-rs/core/src/tools/handlers/shell_spec.rs:298-337` 为单条命令暴露 `use_default`、additional permissions 和 `require_escalated` 等参数契约。
- `codex-rs/core/src/tools/handlers/unified_exec/exec_command.rs:285-317` 检查 sandbox override 与 approval policy 的兼容性；无法请求审批时直接拒绝越权命令。
- filesystem deny-read、network policy、managed network、平台 sandbox 和 exec policy 分布在独立 crates/config 中，并有针对 secret path、取消和网络边界的测试。

安全不是只靠 prompt 告诉模型“不要做危险操作”，而是工具执行路径中的强制边界。

### 6.2 已知边界

- app-server 的用户显式 `thread/shellCommand` 是 unsandboxed 特例，见 `codex-rs/app-server/README.md:200`；它与 agent 自主 tool call 的安全语义不同。
- MCP、plugins 和外部工具会扩大信任边界，需要独立 permission、认证和 workspace 管理，不能因为由 Codex 调用就视为内部可信。

## 7. 持久化、恢复与重放

### 7.1 Rollout recorder

- `codex-rs/rollout/src/recorder.rs:85-121` 定义异步 recorder 与 flush barrier。
- `codex-rs/rollout/src/recorder.rs:288` 支持 resume 已有 rollout。
- `codex-rs/rollout/src/recorder.rs:792-903` 对 resumed session 立即以 append 模式打开现有文件，并通过后台 writer 处理命令。
- `codex-rs/rollout/src/recorder.rs:942-978` 明确 `persist` 幂等，失败后保留 pending items，后续 `persist`/`flush` 可重试。
- `codex-rs/rollout/src/recorder.rs:1605-1668` 写入失败保留未写 suffix，重新打开文件后重试。
- `codex-rs/rollout/src/recorder_tests.rs:750-809` 覆盖 writer 错误后保留并重写 buffered items。

### 7.2 Thread 生命周期

`codex-rs/app-server/README.md:168-206` 暴露 start、resume、fork、archive、unarchive、compact、rollback、inject items、turn start 等线程生命周期操作。恢复不只依靠模型摘要，还依赖 durable rollout 和 reconstruction。

## 8. 长期记忆

Codex memory 与当前 session history 是不同层：

- `codex-rs/memories/README.md:38-77`：Phase 1 对 eligible rollout 做 per-thread extraction，生成结构化记录，并对输出字段做 secret redaction。
- `codex-rs/memories/README.md:79-152`：Phase 2 获取全局锁，选择 top-N memory，刷新 `rollout_summaries/`、`raw_memories.md`，并由 consolidation agent 维护 `MEMORY.md`、`memory_summary.md` 和 `skills/`。
- `codex-rs/memories/README.md:111-118`：consolidation agent 无审批、无网络、只允许本地 memory workspace 写入。
- `codex-rs/memories/write/src/phase1.rs:320-322`：对 raw memory、rollout summary 和 slug 做 secret redaction。
- app-server `thread/memoryMode/set` 与 `memory/reset` 分别控制 thread eligibility 和全局 memory reset，见 `codex-rs/app-server/README.md:185-186`。

优势是跨会话 recall、有来源工件、后台分阶段处理和污染控制；限制是它仍是模型提取/归并的 recall layer，不适合替代交易、权限、学习进度等结构化业务真相。

## 9. 计划、长任务与多 agent

- app-server thread/fork 与 goal continuation 提供长任务持久边界。
- `codex-rs/core/src/tools/handlers/multi_agents_v2/` 包含 spawn、send message、wait、list agents、follow-up 等工具。
- `multi_agents_v2/spawn.rs:168-174` 为 spawn 写入 telemetry，并支持隐藏/公开 agent metadata 配置。
- 官方手册 `Long-running work`（本地手册 `2747-2858`）公开 pause、resume、steer、goal 和 parallel 工作方式。

这些能力适合可并行、可隔离的代码研究和实现；共享 dirty worktree、数据库迁移或强顺序领域决策仍需要显式依赖与 workspace 隔离。

## 10. 可观测性与评测

- Tool dispatch 有 success/failure trace、dispatch/handler/total timing。
- app-server 持续输出 thread/turn/item events，并提供 process-local diagnostics。
- rollout JSONL 保留输入、输出、工具调用和状态事件，可用于复盘和恢复。
- OpenTelemetry、approval、network 与 MCP 事件属于官方公开治理面。
- 仓库包含大量 context、tool、sandbox、rollout、memory、MCP 和 multi-agent 测试。

本次未执行 Codex Rust test suite：固定 checkout 是研究用临时 clone，完整构建成本高且不影响静态架构判定。结论使用源码与已有测试定义作为 A 级证据，不把“测试文件存在”扩张成所有平台均已运行验证。

## 11. 配置与治理

- `AGENTS.md`：官方手册本地快照 `21080-21232` 描述 global 到 repo/cwd 的层级发现和 closer-file override。
- Skills：本地手册 `26828-26888` 将 `SKILL.md` 定义为可复用工作流，并说明 skills 用于教授工具顺序、错误处理和输出契约。
- MCP：本地手册 `23737-23963` 描述外部工具连接与权限表面。
- Plugins：公开产品将 skills、apps/MCP 和工作流打包，但其 workspace/admin 内部服务不是开源 runtime 事实。

## 12. 基线判断

Codex 的核心成熟度来自五个相互支撑的闭环：

1. history/token/compaction/reconstruction 形成上下文闭环。
2. registry/router/runtime/result feedback 形成工具闭环。
3. sandbox/approval/exec policy 形成权限闭环。
4. rollout/thread lifecycle 形成恢复闭环。
5. trace/tests/AGENTS/skills/plugins 形成治理闭环。

其主要局限不是缺少通用工具，而是：领域事实仍需项目自身建模；memory 与 compaction 都不能替代业务数据库；外部 MCP/plugin 增加新的信任与数据边界；最终 verify/recover 质量仍受任务指令、模型判断和项目测试可用性影响。
