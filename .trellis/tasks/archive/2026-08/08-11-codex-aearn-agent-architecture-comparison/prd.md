# Codex 与 Aearn Agent 架构严格对比评估

## 目标

基于 `openai/codex` 的最新可验证源码、官方 Codex 手册，以及 Aearn 当前工作树的真实代码、数据库契约、测试和文档，对两者进行严格、可追溯、非营销式的架构对比，明确 Aearn 在上下文、工具、记忆、工作区、执行循环、权限、安全、恢复、可观测性和评测体系上的真实成熟度、优势、缺口与优先级。

## 用户价值

1. 区分 Aearn 已经具备的 Harness 能力、仅存在于设计或测试中的能力，以及尚未具备的 Codex-like 能力。
2. 避免仅根据产品印象、README 或模型记忆给出泛化结论。
3. 形成可用于后续架构规划的分层差距模型，而不是简单罗列功能。
4. 明确哪些 Codex 机制适合 Aearn 教学 Agent，哪些属于通用 coding-agent 或 OpenAI 产品基础设施，不应机械照搬。

## 已确认事实

1. Aearn 当前正式运行时是 Tutor Harness，采用 finite `TurnRun`、lease/revision、Skill/capability/effect、PostgreSQL 持久化、安全投影和受控 executor 边界。
2. Aearn 的长期教学状态正在从无限聊天历史迁移到 `LearningTrack`、计划版本、LessonDocument、Exercise、mastery evidence 和 ReviewSession 等结构化领域对象。
3. 最近一次真实对话日志已经暴露出上下文窗口与摘要时序之间的断层：消息持久化正确，但 provider selection 只携带最近四条历史，导致较早计划字段丢失并重复询问。
4. 本次评估必须检查 Aearn 当前未提交工作树，不得只以 `main` 或历史文档代表当前实现。
5. `openai/codex` 必须固定到本次研究时实际核对的 commit/revision；涉及当前产品行为时仅使用官方 Codex 手册或 OpenAI 官方资料补充。
6. 本任务是研究与评估任务，不直接修改 Aearn 产品代码；未经另行批准，不启动实现、提交、push 或部署。
7. 用户已确认采用混合基线：以开源 `openai/codex` CLI/runtime 源码为主要证据，以官方 Codex 手册补充 Desktop、cloud、plugins、MCP、memory 等产品能力；两类证据必须分栏，不把未开源内部实现当作源码事实。
8. Codex 源码基线固定为 `openai/codex@e20616d2650de6cde27e8513cbf266ed75851071`；基准日期核对到的 release 为 `rust-v0.147.0`。
9. Aearn 基线固定为 `main@15587d1830f949bee5e17bd0a556b790038cd367` 加当前未提交工作树；tracked diff blob hash 为 `f1fc432833e2aae6b21b83ec3d8e8a9d70becb86`，并单独记录三个 untracked 文件 hash。
10. 详细证据等级、源码入口与工作树边界见 `research/baseline.md`。

## 评估维度

1. Agent 执行模型与停止条件。
2. 上下文来源、优先级、预算、截断、压缩与重建。
3. 短期会话状态、长期记忆、结构化领域状态与跨会话连续性。
4. 工具定义、发现、参数契约、调用循环、结果反馈与错误恢复。
5. 文件系统、Git、shell、浏览器、MCP、外部连接器和受控工作区。
6. 权限、sandbox、审批、策略、秘密保护与危险操作边界。
7. 计划、任务分解、长任务延续、并发和多 agent 协作。
8. 持久化、checkpoint、幂等、取消、恢复、重放和失败诊断。
9. trace、日志、用户可见过程、审计、指标和评测体系。
10. 配置、AGENTS/skills/plugins/hooks 等可扩展性和治理面。
11. 产品领域适配：Codex 的 coding-agent 机制与 Aearn 教学 Agent 的适用边界。

## 需求

- 对每个维度分别给出 Codex 机制、Aearn 机制、证据位置、差距、风险和建议。
- 明确区分：已实现、部分实现、仅有规划、仅测试可用、运行时未接通、完全缺失。
- 对 Aearn 给出严格评分，并公开评分标准与权重。
- 对关键结论提供 `path:line`、commit、官方文档章节或运行时证据。
- 重点复核上下文、工具和记忆，不以功能数量代替执行质量。
- 对差距按“基础正确性、可靠性、安全性、智能性、产品体验”分层，不把多 agent 数量当作智能程度代理。
- 最终给出近期、中期、长期改造顺序，并说明依赖关系和不建议照搬的部分。

## 验收标准

- [x] 固定并记录 `openai/codex` 的实际 revision、研究日期和主要源码入口。
- [x] 固定并记录 Aearn 当前 revision、工作树状态和 source-of-truth 文档入口。
- [x] 完成至少十一项评估维度的逐项证据矩阵。
- [x] 上下文评估覆盖 current input、历史窗口、摘要/compaction、token budget、工具结果回灌和跨轮连续性。
- [x] 工具评估覆盖 registry/schema、文件读写、搜索、patch、shell、Git、浏览器/MCP、审批和 verify/recover loop。
- [x] 记忆评估覆盖会话历史、摘要、结构化 learner state、项目级持久指令和跨会话记忆边界。
- [x] 明确说明最近重复询问问题在 Codex-like 基线下暴露出的具体架构缺口。
- [x] 每项评分均可追溯到源码、测试、文档或运行时证据，不使用未验证的产品印象。
- [x] 给出 Aearn 相对 Codex 的总体定位、分项分数、最高风险缺口与分阶段路线图。
- [x] 研究工件使用简体中文，代码、路径、字段、命令和模型名保持原文。

## 范围外

- 直接修改 Aearn 产品代码或数据库 schema。
- 把 Codex 云端未开源内部实现当作已知源码事实。
- 用模型规模、品牌或 UI 完整度替代架构评估。
- 未经批准创建实现 child、启动任务、提交、push、部署或修改生产数据。




