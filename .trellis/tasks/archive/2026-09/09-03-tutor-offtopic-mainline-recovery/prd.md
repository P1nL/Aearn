# 引导偏题用户回归教学主线

## Goal

建立通用的 Tutor 对话方向恢复合同：当学习者的最新消息偏移当前讨论方向时，Tutor 应识别它与当前主线的关系，适当回应后引导回到主线；当学习者确实要切换方向时，则显式确认并停止旧路径。修复不能依赖“厨师”等特定关键词，回归测试必须覆盖多种用户聊天方向偏移场景。

## Background

- 截图中的“做网站 → 完全没有经验 → 我想做厨师”只是一个复现样例。缺陷本质是模型没有处理“最新消息与当前讨论方向不一致”，而不是缺少对“厨师”这个词的特殊判断。
- 当前 Harness 通用策略已经声明最新输入、纠正和目标变化优先，但没有完整规定：临时岔题应如何回答后回归、方向不明时如何澄清、明确切换时如何停止旧主线。
- `tutor.learning-plan-draft@1.0.2` 和 `tutor.lesson-teaching@1.2.0` 都强调当前输入优先，却缺少跨场景的方向偏移与回归主线测试。
- Codex 计划草拟 Runtime 复用持久会话线程；旧对话方向可能影响新 Turn 的问题补全，因此还需要明确“最新输入和服务端事实高于旧线程语境”。
- 2026-09-04 启动项目实测显示，`think` 中的 Codex reasoning 会围绕方向关系反复自我讨论，但最终仍可能直接沿用旧主线问题。问题不是 reasoning 被展示，而是方向判断没有被压缩为一个必需的 typed 决策，服务端也没有可验证的“已完成纠偏”标志来约束最终问题。

## Requirements

- **R1 — 通用方向判断：** Tutor 应基于语义关系而非特定关键词，判断最新输入是当前主线的正常延伸、临时岔题、方向不明，还是明确切换。
- **R2 — 当前输入优先：** 最新 learner input、当前服务端事实、TeachingSession/checkpoint 和显式用户控制优先于旧消息、摘要、持久线程联想和先前建议。
- **R3 — 临时岔题后回归：** 对可以简短回答的临时问题，Tutor 先回应当前消息，再明确连接回原讨论主线和下一步；不得只回答岔题后丢失主线，也不得完全忽略用户问题。
- **R4 — 不明确时澄清：** 当无法判断用户是在临时岔题、提供新主题素材还是想切换方向时，只问一个方向澄清问题，不直接替用户选择。
- **R5 — 明确切换：** 当用户明确否定旧方向并提出新方向时，Tutor 承认切换、停止旧路径，并在当前产品能力范围内进入新方向；不得反复把用户拉回已拒绝的旧主线。
- **R6 — 正常延伸不误判：** 与当前目标语义相关的补充、示例、实现约束或主题变化应继续当前流程，不额外插入回归主线询问。
- **R7 — 多模式一致：** 普通 Tutor 对话、`plan_drafting`、`lesson_teaching` 和已有 blocking Artifact clarification branch 应遵守一致的方向恢复语义；各模式继续使用现有服务端权威和交互合同。
- **R8 — 单问题约束：** 需要学习者决定方向时，Tutor 最多提出一个清晰、可回答的问题；不得同时展开多个新分支。
- **R9 — 权威边界：** 模型不得通过方向判断自行修改 LearningTrack、计划事实、进度、Artifact 或数据库状态；typed request、候选、checkpoint 和持久化仍由服务端控制。
- **R10 — 通用回归矩阵：** 测试以“用户聊天方向偏移”作为场景类别，覆盖不同主题、不同偏移程度和不同 Tutor 模式；“厨师”仅作为其中一个样例。
- **R11 — 已发布 Skill 不原地改写：** 需要修改已发布 Skill 时新增不可变语义版本，并同步 raw-byte SHA-256、选择策略和目录测试；旧版本保持不变。
- **R12 — 有界方向决策：** Codex 在读取一次当前 planning context 后，必须通过一个 closed typed direction action 在有限调用内选择 `continue_mainline / answer_and_refocus / clarify_direction / confirmed_switch`；不得只在 reasoning 中反复讨论后以“未设置任何方向信号”继续旧问题。
- **R13 — 可验证纠偏标志：** 服务端必须能从 validated tool result/registry state 判断当前 Turn 的方向动作已被接受；四类动作都必须有显式标志，不能继续以“没有 clarification/switch 布尔值”隐式代表正常主线。
- **R14 — 缺标志时安全纠偏：** 如果 Codex 在 completed Turn 前没有提交合法方向动作，dispatcher 必须忽略模型给出的旧主线问题，生成一个明确说明“当前输入可能与原方向不一致”的单一 server-owned direction clarification；不得静默回退到 `next_missing_fact`。
- **R15 — 保留 reasoning 展示：** 当前 Codex reasoning 的 Runtime projection、snapshot/SSE 和 Desktop `think` 展示保持原合同；本任务只通过更短的决策路径与 typed success marker 减少无效自我讨论，不把问题改写为隐藏思考链。

## Acceptance Criteria

- [ ] **AC1:** 参数化回归至少覆盖：非编程岔题、编程领域内跨主题岔题、疑似换目标、明确换目标、同主题延伸五类消息，不能依赖单一词汇匹配。
- [ ] **AC2:** 对临时岔题，Tutor 的可见回答同时包含对当前消息的适当回应和明确的主线恢复连接，并继续当前可执行下一步。
- [ ] **AC3:** 对疑似方向切换，Tutor 不静默延续旧方向或擅自采用新方向，只提出一个回归/切换澄清问题。
- [ ] **AC4:** 对明确切换，Tutor 停止旧路径，不重复已拒绝步骤，也不再要求用户确认是否切换。
- [ ] **AC5:** 对同主题延伸，例如“做网站”后补充“做一个厨师作品展示网站”，Tutor 继续当前讨论，不错误判定为偏题。
- [ ] **AC6:** 截图场景仍作为一个回归样例：Tutor 不得直接从“我想做厨师”跳到“静态网站还是动态网站”，而应先处理方向关系。
- [ ] **AC7:** 普通 Tutor provider policy、当前 LearningPlan Skill、当前 LessonTeaching Skill，以及 Codex plan-drafting 基础指令都包含一致、可测试的方向偏移规则。
- [ ] **AC8:** blocking Artifact 分支继续遵守现有 `answer_and_refocus / offer_switch / confirmed_switch` 权威，不新增或复制第二套分支状态机。
- [ ] **AC9:** 正常语义语言候选、教学步骤、Artifact 候选和 plan draft 流程保持原有非回归行为。
- [ ] **AC10:** 旧 Skill 版本及内容哈希保持不变；新版本资源使用 LF，manifest raw-byte SHA-256 全部匹配。
- [ ] **AC11:** 相关 focused tests、Ruff、Mypy、`desktop:check`、Trellis validate 与 `git diff --check` 通过；不调用真实 provider，不宣称真实模型端到端验证。
- [ ] **AC12:** Codex planning tool schema 暴露一个 closed direction action；fake App Server 覆盖四类动作，并断言 registry/result 中存在可机读的 accepted marker。
- [ ] **AC13:** 缺失、冲突或非法 direction action 时，服务端只创建一个明确的 direction clarification，不持久化模型生成的旧 `next_missing_fact` 问题，也不提交 draft。
- [ ] **AC14:** 截图类模糊偏航输入在最终 UI 中出现明确纠偏提示，而不是继续询问旧主线中的编程经验、网站静态/动态等问题。
- [ ] **AC15:** reasoning Runtime item、snapshot/SSE parser、Desktop `think` renderer 和历史 reasoning 回放保持修改前行为；回归测试证明撤回的隐私修复没有残留。

## Out of Scope

- 不实现针对“厨师”或其他单词的硬编码关键词列表、正则分类器或前端判断。
- 不改造 Desktop 视觉布局、消息左右对齐或类型化请求组件。
- 不复制 Artifact clarification branch 的数据库结构，也不新增第二套计划、教学或进度权威。
- 不在缺乏失败证据时重构所有 planning fact 的确认/撤回生命周期或新增数据库 migration。
- 不执行真实 DeepSeek/Codex provider smoke、Docker conformance、push、deploy 或发布操作。
- 不隐藏、删除、过滤或重新定义当前 Codex reasoning 的公开 Runtime/Desktop 展示合同；思考链隐私不属于本次缺陷。

## Risks and Deferred Items

- 提示词、Skill eval 和 fake-provider 测试可以验证合同与管线，但不能等价于真实 provider 的统计稳定性；真实模型评测需要单独授权。
- “相关延伸”和“方向偏移”存在语义边界，测试必须使用多个正反样例，避免用过度强制的回归提示误伤正常对话。
- 工作区已有大量与本任务无关的未提交修改；实施和提交必须只暂存本任务拥有的文件。
- typed marker 仍由模型提出语义分类，不能被当成事实值或持久业务权威；服务端只接受 closed action 并控制实际 request、fact reopen 与最终问题。
