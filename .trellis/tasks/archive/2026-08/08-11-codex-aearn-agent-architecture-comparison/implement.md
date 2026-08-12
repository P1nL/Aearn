# 实施计划

## 执行原则

本任务的“实施”是研究、证据整理和评估报告编写，不包含 Aearn 产品代码修改。所有结论先落到可审计的研究工件，再形成最终摘要。

## 步骤一：重新确认冻结点

1. 复核 `openai/codex` 的固定 commit `e20616d2650de6cde27e8513cbf266ed75851071` 可读取。
2. 复核 Aearn HEAD、branch、tracked diff hash 和 untracked 文件 hash。
3. 若 Aearn 工作树已变化，在 `research/aearn-baseline.md` 记录新旧快照差异，不覆盖用户修改。
4. 记录研究命令、日期和证据等级。

## 步骤二：完成 Codex 源码基线

1. 沿 `session/turn`、context manager、compaction 和 rollout reconstruction 追踪上下文生命周期。
2. 沿 tool registry、router、parallel runtime 和 handlers 追踪工具发现、调用、并发、取消、错误和结果回灌。
3. 检查 rollout recorder、thread resume/fork/compact/inject 和状态存储，确认恢复边界。
4. 检查 memories 两阶段管线、读取资格、污染防护、重置和本地工件。
5. 检查 exec policy、sandbox、approval、skills、plugins、MCP 和多 agent 入口。
6. 使用官方 Codex 手册补充开源源码之外的公开产品行为，并单独标注证据类型。
7. 写入 `research/codex-baseline.md`，保留 `path:line` 与 commit。

## 步骤三：完成 Aearn 当前工作树基线

1. 从 `docs/README.md` 和 `docs/architecture/tutor-harness-runtime.md` 确认正式组合根。
2. 沿 `interactive.py`、`context_builder.py`、`context_budget.py` 和 provider request 追踪上下文装载与预算。
3. 沿 `run_loop.py`、`persistence.py`、`public_api.py` 追踪 TurnRun、lease/revision、checkpoint、取消和恢复。
4. 沿 Skill/capability/effect、decision gate、execution 和 runner registry 追踪工具与副作用边界。
5. 沿 curation、learner state、LearningTrack、proactive worker 追踪会话记忆和结构化领域状态。
6. 核对生产组合根是否真正接通候选能力，避免把测试孤岛计为已实现。
7. 读取相关测试、fixtures、trace 和真实对话证据，写入 `research/aearn-baseline.md`。

## 步骤四：复盘重复询问样本

1. 重建 conversation `a13c83cb-e996-4ab9-be47-fff5875b754d` 与 run `8e08aa29-d84f-4c3f-9241-c6d6e48ed6a3` 的上下文时间线。
2. 对齐 loader 输入、ContextBuilder 选择、token 估算、working summary、provider request 和 terminal compaction。
3. 明确哪些信息只存在于聊天历史，哪些应进入结构化 intake/plan state。
4. 与 Codex 的 inline compaction、history replacement、resume reconstruction 和 memory 分层进行机制对比。
5. 形成可测试的不变量与风险，不在本任务内直接写修复代码。

## 步骤五：建立十一维矩阵与评分

1. 对每一维填写 Codex 机制、Aearn 机制、证据等级、实现状态、失效行为、差距和建议。
2. 依据 `design.md` 的 `0-5` 标尺评分。
3. 用权重计算通用 Agent Runtime 总分。
4. 单独给出 Aearn 教学领域适配判断，避免与通用 runtime 分数混淆。
5. 对没有直接证据的判断标记为“推断”或“未找到”，不得补写想象中的机制。
6. 写入 `research/comparison-matrix.md`。

## 步骤六：形成严格评估结论

1. 总结 Aearn 已具备、部分具备、未接通和缺失的能力。
2. 给出最高风险缺口，优先覆盖上下文正确性、工具闭环、恢复与安全。
3. 将建议分为近期、中期、长期，并标明依赖关系。
4. 明确不建议机械照搬的 Codex 机制，以及 Aearn 应保留的教学领域优势。
5. 写入 `research/final-assessment.md`，再向用户提供精炼摘要。

## 验证

计划阶段：

- 运行 `python ./.trellis/scripts/task.py validate .trellis/tasks/08-11-codex-aearn-agent-architecture-comparison`。
- 搜索并清除英文初始骨架、占位内容和示例 JSONL 记录。
- 验证权重合计为 `100`。
- 检查所有日期使用 `2026-08-11` 基准，不受本机跨时区日期影响。

正式执行阶段：

- 检查所有 `path:line` 路径在对应 revision 或当前工作树存在。
- 抽样反向验证每个评分的证据链。
- 对工作树变化重新计算 hash。
- 对矩阵分数执行自动复算。
- 运行 `git diff --check`，但不暂存、不提交。
- 若运行时数据或依赖环境不可读取，明确记录未执行项和阻塞原因。

## 风险与控制

| 风险 | 控制 |
| --- | --- |
| Codex 上游持续变化 | 绑定固定 commit；当前产品行为另用官方手册标注日期 |
| Aearn dirty worktree 继续变化 | 记录 diff/hash；执行前复核；不覆盖用户修改 |
| 把产品手册当作开源内部实现 | 强制证据等级与分栏 |
| 不同领域导致错误一一映射 | 以能力闭环比较，并单列教学领域适配 |
| 文件数量或测试数量造成成熟度错觉 | 检查生产组合根、异常路径、恢复和运行证据 |
| 过早形成结论 | 基线文件不评分；完成双边证据后再填写矩阵 |
| 研究任务意外扩展到代码修改 | 本任务只写 `.trellis/tasks/**` 研究工件；代码修复另立任务并单独批准 |

## 回滚

本任务不修改产品代码。若规划工件需要撤销，只删除或恢复本任务目录中的新增研究文件；不得使用破坏性 Git 命令，也不得影响当前用户工作树。

