# 对比研究基线

## 研究日期

- 基准日期：`2026-08-11`
- 本文只固定研究输入、证据等级和源码入口，不提前给出最终评分。

## 证据等级

| 等级 | 证据类型 | 可支持的结论 | 限制 |
| --- | --- | --- | --- |
| A | 固定 revision 的开源源码、测试、schema、构建配置 | 可确认具体机制、控制流、数据结构和测试覆盖 | 不能外推未开源云端内部实现 |
| B | OpenAI 官方 Codex 手册或官方产品文档 | 可确认公开产品行为、配置面和用户可见能力 | 若未有源码，不声称其内部实现方式 |
| C | Aearn 当前 revision 加未提交工作树、项目 source of truth 和测试 | 可确认当前待评估实现，包括尚未提交的变化 | 工作树会继续变化，结论必须绑定本快照 |
| D | 本地运行时日志、数据库记录、trace、真实对话复现 | 可确认实际运行行为与失效模式 | 单个样本不能自动代表所有路径 |
| E | PRD、设计稿、路线图、注释或未接通代码 | 只能证明规划意图或候选方案 | 不计为已实现能力 |

最终报告中的关键判断至少需要一个 A/C/D 级证据；仅有 B 级证据时必须标为“官方公开行为”；仅有 E 级证据时必须标为“规划中”。

## Codex 固定基线

### Revision

- 仓库：`openai/codex`
- 分支：`main`
- commit：`e20616d2650de6cde27e8513cbf266ed75851071`
- commit 时间：`2026-08-11T16:31:30Z`
- commit 标题：`Propagate MCP elicitation event delivery failures (#38035)`
- 截至基准日期核对到的最新 release：`rust-v0.147.0`，发布时间 `2026-08-07T01:41:49Z`
- 本地只读研究 checkout：`C:\Users\PINKING\AppData\Local\Temp\openai-codex-e20616d2`

commit 是最终引用边界；临时 checkout 仅用于本地定位，不作为长期可移植路径。

### 主要源码入口

| 主题 | 入口 |
| --- | --- |
| 回合执行与自动压缩 | `codex-rs/core/src/session/turn.rs`、`codex-rs/core/src/compact.rs`、`codex-rs/core/src/compact_remote_v2.rs` |
| 上下文历史与窗口 | `codex-rs/core/src/context_manager/history.rs`、`codex-rs/core/src/session/context_window.rs` |
| 恢复与历史重建 | `codex-rs/core/src/session/rollout_reconstruction.rs`、`codex-rs/rollout/src/recorder.rs` |
| 工具注册与路由 | `codex-rs/core/src/tools/registry.rs`、`codex-rs/core/src/tools/router.rs`、`codex-rs/core/src/tools/parallel.rs` |
| 工具处理器 | `codex-rs/core/src/tools/handlers/` |
| 会话与线程 API | `codex-rs/app-server/README.md`、`codex-rs/app-server-protocol/` |
| 长期记忆 | `codex-rs/memories/README.md`、`codex-rs/memories/read/`、`codex-rs/memories/write/` |
| 安全与审批 | `codex-rs/core/src/tools/`、`codex-rs/execpolicy/`、各平台 sandbox crates |
| skills、plugins、MCP | `codex-rs/skills/`、`codex-rs/plugins/`、MCP 相关 crates 与 tool handlers |

### 官方手册补充范围

官方 Codex 手册只用于补充以下公开表面：

- 长任务的 pause、resume、steer、parallel 和 goal mode。
- sandbox 与 approval 的关系及默认网络边界。
- `AGENTS.md` 的发现、层级覆盖和大小限制。
- Codex memories 与 ChatGPT memory 的边界。
- MCP、skills、plugins 的公开使用模型。

这些内容在最终矩阵中与开源源码证据分栏呈现；无法从固定 commit 验证的内部机制不得写成源码事实。

## Aearn 固定基线

### Revision 与工作树

- 仓库：`E:\codee\Aearn`
- 分支：`main`
- HEAD：`15587d1830f949bee5e17bd0a556b790038cd367`
- commit 时间：`2026-08-11T18:42:16+08:00`
- commit 标题：`chore: record exercise gate session`
- 当前评估对象：上述 HEAD 加本地未提交工作树。
- 记录时工作树包含 `35` 个 tracked 变更文件和 `3` 个 untracked 文件。
- tracked diff blob hash：`f1fc432833e2aae6b21b83ec3d8e8a9d70becb86`

未跟踪文件快照：

| SHA-1 | 路径 |
| --- | --- |
| `4e9691b62239d8d9c2fad2ca186f2c1a114fb3ae` | `aearn/services/api/app/services/llm/provider_diagnostics.py` |
| `dcc7cb75b13c7de2327aea0588168c4f082c170a` | `aearn/services/api/app/services/tutor/decision_protocol.py` |
| `7591fba683497aaa7aa7908f4cf831fdb2b1cebf` | `aearn/services/api/tests/test_provider_diagnostics.py` |

本任务不得改写、清理或回滚上述用户工作树。正式评估若发现工作树继续变化，需要重新记录 diff hash 并说明变化范围。

### Source of truth

- `docs/README.md`
- `docs/architecture/tutor-harness-runtime.md`
- `docs/architecture/api-contract.md`
- `docs/architecture/database-schema.md`
- `docs/setup/development-environment.md`

### 主要源码入口

| 主题 | 入口 |
| --- | --- |
| 上下文构建与预算 | `aearn/services/api/app/agents/harness/context_builder.py`、`context_budget.py`、`contracts.py`、`provider_request.py` |
| Tutor 上下文加载 | `aearn/services/api/app/services/tutor/interactive.py`、`learner_state.py` |
| TurnRun 循环 | `aearn/services/api/app/services/tutor/run_loop.py` |
| 持久化与公开 API | `aearn/services/api/app/services/tutor/persistence.py`、`public_api.py` |
| Skill 与 capability | `aearn/services/api/app/agents/harness/skill_catalog.py`、`capabilities.py` |
| 决策与 capability 网关 | `aearn/services/api/app/services/tutor/decision_gate.py`、`capability_gateway.py`、`capability_policy.py` |
| 执行边界 | `aearn/services/api/app/services/tutor/execution.py`、`aearn/services/api/app/services/runners/runner_registry.py` |
| 记忆与主动学习 | `aearn/services/api/app/services/tutor/curation.py`、`learner_state.py`、`proactive_repository.py`、`proactive_worker.py` |
| 评测与回归 | `aearn/services/api/tests/`、Tutor context/harness fixtures |

## 已知真实失效样本

- conversation：`a13c83cb-e996-4ab9-be47-fff5875b754d`
- offending run：`8e08aa29-d84f-4c3f-9241-c6d6e48ed6a3`
- 现象：用户已经回答每周时间预算并被确认，后续又被重复询问。
- 已确认链路：历史消息已持久化且 loader 读取到 `8` 条 prior messages；`ContextBuilder` 默认只选择最近 `4` 条，较早的时间预算被排除；当时 `working_summary` 为空；terminal compaction 在 provider 调用后才发生，且该轮未形成可供当前调用使用的摘要。
- 初步性质：上下文选择与压缩时序缺口，不是消息未写入，也不能简单归因于模型幻觉。

正式评估必须把该样本映射到“上下文不变量、结构化 intake 状态、压缩触发时机、回归测试和恢复策略”，并判断 Codex 的机制哪些能直接借鉴、哪些不能替代 Aearn 的领域状态建模。

## 基线限制

1. Codex 的云端编排、托管服务和未开源 Desktop 内部实现不在源码可验证范围内。
2. Aearn 是教学 Agent，Codex 是通用 coding agent；评分采用共同的 agent runtime 能力，不按功能数量或产品 UI 直接排名。
3. Aearn 当前 dirty worktree 是用户指定的比较对象；主分支历史不能替代当前实现。
4. 当前文件不包含最终结论和分数，避免在完整证据矩阵完成前形成锚定偏差。
