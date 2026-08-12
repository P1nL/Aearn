# 编程语言教学 Agent 产品架构与学习体验

## 目标

在现有 Tutor Harness、有限 `TurnRun`、Skill/capability/effect、PostgreSQL 持久化、安全投影和独立执行器基础上，增量构建一个以用户指定编程语言为核心的长期教学产品。

Aearn 首先帮助用户制定并执行系统化学习路线，通过权威文档支撑的结构化教学内容、渐进练习、间隔复习和模型代码审核练习，让用户不仅会编写代码，还能独立判断模型生成代码是否满足需求、是否正确以及如何验证。

本任务不重建 Harness。Harness 继续负责一次 Agent 决策如何被安全、有限、可追踪地执行；新的教学领域层负责用户学习什么、当前学到哪里、展示什么教学内容、何时复习以及如何形成掌握度证据。

## 用户价值

1. 用户可以为不同编程语言或不同学习目标建立独立学习主线。
2. 用户不需要从无限增长的聊天历史中寻找课程内容和学习进度。
3. 教学内容由权威来源支撑，并以稳定、可恢复的结构化文档呈现。
4. 练习不仅检查用户能否写代码，还训练用户判断模型生成代码是否可信。
5. 复习和后续教学依据可验证的掌握度证据，而不是仅依据模型对聊天历史的猜测。

## 启动时已确认事实

1. 当前正式产品运行时是 Tutor Harness；旧 Graph/router/SDK 运行时不重新启用。
2. 当前 `TutorConversation` 支持长期历史，普通消息创建 fresh finite `TurnRun`，explicit continuation 才复用等待中的 run。
3. 现有 Harness 已具备 lease、revision、幂等、预算、checkpoint、Skill catalog、capability/effect gate、安全投影和 executor 基础，适合继续复用。
4. 任务启动时 Desktop 以 conversation 导航和 Tutor workspace 为主，尚未实现语言卡片首页、LearningTrack、路线图、LessonDocument、练习 Gate 和复习模式；该缺口已由本任务树补齐。
5. 现有 `08-04-tutor-context-governance-adaptive-budget` 任务树只负责权威 `current_input`、provider usage/cache、自适应预算、长对话摘要与 eval；该边界仍然有效。
6. `08-04-tutor-context-governance-adaptive-budget` 已作为本任务的基础能力子树挂接，保留原有五个 child 及执行顺序，不重复规划。
7. 仓库已有两层多语言执行能力：现有教学 runner 支持 Python、JavaScript/HTML/CSS、TypeScript、SQL，以及依赖本机工具链的 Java、Go、C#；Rust 和 C++ 仍为规划状态。这些 runner 多数是受限 subprocess、Node VM、临时目录或临时 SQLite，不等同于 container-grade 隔离。
8. 新的 standalone container executor 已为 Python、browser preview、TypeScript、SQLite、Java、Go 和 C# 建立 runtime catalog、固定协议与 Dockerfile，但 `image-locks.json` 当前为空、默认 `TUTOR_EXECUTOR_ENABLED=false`，因此尚没有可实际启用的 reviewed container runtime fleet。
9. 当前 active Tutor API/Harness 尚未把上述多语言执行能力作为普通教学闭环开放；交互式组合仍默认拒绝 capability/effect，执行必须经过 exact Skill/effect、proof、lease、revision、budget 和 executor availability。
10. 长期教学连续性由结构化学习主线与掌握度提供；单个无限增长 Conversation 不能成为唯一教学状态或每次模型调用的完整上下文。
11. 首个端到端 MVP 允许使用现有 teaching-grade 本机 runner 验证多语言教学闭环；面向公开用户开放的可执行练习必须使用经过审核并锁定镜像的 container-grade runtime。
12. 首期端到端 MVP 的核心验收语言为 Python、JavaScript、TypeScript 和 SQL；Java 与 HTML/CSS 作为扩展验证目标，不阻塞核心 MVP 验收；Go、C#、Rust 和 C++ 按实际 `execution_tier` 降级为 `static_only` 或 `unavailable`。

## 产品信息架构

### 语言学习首页

- 页面中间使用三列响应式网格展示用户的学习主线卡片。
- 每张卡片对应一个 `LearningTrack`，而不是仅对应语言名称；同一语言允许存在不同目标的学习主线。
- 卡片至少展示语言、学习目标、当前阶段/知识点、路线进度、最近学习时间和到期复习数量。
- 卡片提供“继续学习”主入口；存在到期复习时提供“开始复习”次入口。
- 网格最后一张固定为“添加学习语言/学习主线”。

### 学习计划制定页

- 点击添加后进入以居中对话为主体的制定页。
- Tutor 通过交互收集语言、基础、目标、时间投入、已有经验和教学偏好。
- 模型通过类型化计划能力生成学习计划草案，而不是把普通聊天 Markdown 当作正式计划。
- 学习计划以可审阅组件展示，支持用户要求调整；确认后生成版本化计划并创建 `LearningTrack`。

### 三栏学习页

- 左侧栏以学习路线为主，并提供“继续学习”“今日复习”和可选“综合训练”入口。
- 中间区域根据当前模式显示 `LessonDocument`、`ReviewSession` 或 `PracticeSession`。
- 右侧栏始终是当前学习上下文的 Tutor 对话、渐进提示、练习反馈和安全执行结果窗口。
- Conversation 退化为 track/lesson/review 范围内的互动历史，不再承担全部课程与掌握度状态。

## 核心领域要求

### P1 — LearningTrack 是长期教学根对象

- 一个用户可以拥有多个学习主线；每个主线绑定指定编程语言、目标、学习计划、路线、当前进度、掌握度和复习状态。
- 一门语言可拥有多个不同目标的主线，例如零基础、后端专项或面试复习。
- 学习状态必须结构化持久化，不能只从 Conversation 历史推断。
- Conversation、Lesson、Exercise、ReviewSession 和 CodeArtifact 必须明确归属一个 LearningTrack。

### P2 — 学习计划与路线图

- 计划生成是模型可调用的类型化能力，服务端负责 schema、范围和持久化校验。
- 正式学习计划必须版本化；模型不能静默覆盖已经确认的计划。
- 系统可以依据掌握度自动调整复习时间、推荐练习、补救内容和非必要节点的推荐顺序，这类轻量调度不要求逐次确认，但必须形成可解释的调度记录。
- 新增、删除或重排核心知识点、跳过模块、改变学习目标或前置依赖等结构变化，必须生成新的计划版本并由用户明确确认后生效。
- 产品不提供单个知识点的“申请跳过”操作；用户可以在当前已解锁知识点内直接滚动到该知识点末尾的练习 Gate，用通过 Gate 的方式证明掌握并继续。
- 只有模块级路线节点提供“申请跳过模块”操作；触发后在独立小窗中运行模块诊断，不复用正文中的单个知识点 Gate，也不要求用户离开当前学习页。
- 进行中和已完成节点不得被静默改写、删除或重新解释；计划迁移必须保留原版本、变更原因、影响预览及既有学习证据。
- 路线节点至少支持 `locked`、`available`、`in_progress`、`completed` 和 `review_due`。
- 路线解锁必须由服务端根据前置节点、必要练习和掌握度证据决定，前端隐藏不是安全边界。

### P3 — 权威来源支撑的 LessonDocument

- 中间教学内容是持久化、版本化、结构化的 `LessonDocument`，不是一次性聊天回复或任意 HTML。
- 文档由受信来源检索、教学编排和服务端校验共同生成；优先使用语言官方文档、规范和正式提案。
- 每个“语言 + 知识点 + 内容标准版本”先生成并校验可复用的标准 `LessonDocument`；为具体 LearningTrack 创建课程时，再依据用户目标、先验经验、掌握度和教学偏好生成带 lineage 的个性化派生版本。
- 用户开始学习某个派生版本后，该版本的 block 顺序、练习 Gate、引用快照和评分契约必须冻结；官方文档更新、教学模板改进或重新个性化只能创建新版本，不得静默改写进行中的课程。
- 新版本需要保留父版本、生成策略版本、来源快照和变更原因；已经产生的 ExerciseAttempt、解锁和掌握度证据继续引用原版本，用户可在明确迁移后进入新版本。
- 来源应保留名称、URL/标识、文档版本、章节、检索时间和内容 hash，并在教学内容中提供用户可见引用。
- 前端只渲染已注册 block 类型，例如标题、概念、引用、代码示例、对比、练习 Gate 和总结。
- 模型不能直接生成任意 React 组件或可执行 HTML。

### P4 — 练习 Gate

- 练习可嵌入两个知识点之间，并通过持久化状态控制后续内容解锁。
- Gate 至少区分 `required`、`recommended` 和 `diagnostic`；LessonDocument 内的知识点 Gate 仍属于当前知识点完成机制，模块跳过诊断则是独立的 `placement_diagnostic` 会话。
- 用户可在当前已解锁知识点内自由滚动并直接完成末尾 Gate；尚未通过前序 required Gate 的后续知识点仍不可访问，不能通过滚动绕过服务端解锁状态。
- `required` Gate 未通过时提供渐进提示、补救讲解和更小练习，不能只有永久阻断。
- 练习提交、执行、评估、提示使用和解锁结果必须成为可重放的结构化事实。
- 用户代码的编译、测试或运行通过受控 executor 和版本化 runtime profile 完成；不允许模型自由指定命令、路径、镜像或网络目标。
- 每种语言或练习必须暴露服务端判定的 `execution_tier`：`teaching_local`、`container_verified`、`static_only` 或 `unavailable`。
- `teaching_local` 仅用于受控本地开发、内部演示和 MVP 验证，不作为公开运行任意用户代码的安全承诺；公开可执行练习必须达到 `container_verified`。
- `static_only` 可以提供知识教学、代码阅读和模型代码审核练习，但不得向用户伪装为已经运行、编译或测试过；`unavailable` 不生成依赖执行结果才能成立的练习。
- 模块诊断结果必须形成结构化掌握度证据；只有模块全部核心能力达到服务端版本化阈值时，才能跳过整个模块。
- 部分通过不得把任何知识点标记为已跳过，也不得形成变相的知识点跳过；其证据只用于压缩已掌握内容的讲解、调整推荐练习和强化薄弱部分，用户仍按模块路线完成各知识点 Gate。
- 模块诊断失败不得改写既有已证明的掌握度，也不产生惩罚；系统应展示薄弱能力摘要并回到模块学习，重试受明确 cooldown、题目版本和幂等规则约束。

### P5 — 间隔复习

- 复习是 LearningTrack 下的动态队列，不是学习路线中只执行一次的固定章节。
- 首页卡片显示到期数量，学习页左侧提供“今日复习”入口，复习内容在中间主区域呈现。
- 普通到期复习不强制阻止新课程；关键前置知识明显遗忘时，可以成为依赖节点的短 Gate。
- 复习优先测试回忆、迁移和应用，不默认完整重播原教学文档。
- 复习结果更新掌握度证据和下一次复习时间；使用提示后的完成与独立完成必须区别记录。

### P6 — 模型代码审核练习

- 模型代码审核练习是统一练习类型，不是“用户提交代码让模型代审”的独立产品。
- 系统根据语言、当前知识点、掌握度和历史误区生成需求与模型代码，让用户完成审核。
- 审核练习可以出现在课程 Gate、间隔复习和阶段综合考核中。
- 用户需要逐步训练需求判断、结果预测、代码定位、触发条件、语言原理、验证方法和修改建议。
- 审核交互必须支持结构化 finding，而不是只提交一段自由文本。
- 题目必须包含有错误、多个错误、只有改进项、完全正确和表面可疑但实际正确等情况，并对误报进行评分。
- 模型生成的题目发布前必须经过静态解析、编译/typecheck、可见或隐藏测试及 rubric 校验，证明预期问题真实且不存在意外阻断问题。
- 预期 finding、隐藏测试和评分 rubric 不得暴露给用户或进入公开对话上下文。

### P7 — 右侧上下文 Tutor

- 用户可选择 LessonDocument 中的文本或代码块，并以结构化引用加入右侧对话。
- 引用必须区分用户正文与 `lesson_selection`、`exercise_feedback`、`execution_result`、`review_feedback` 等系统事实。
- 审核或练习提交前，Tutor 默认使用渐进提示而不是直接泄露答案；提交后才提供完整解释、验证证据和补救路径。
- 右侧对话不能成为 Lesson、Exercise、掌握度或 CodeArtifact 的第二份权威存储。

### P8 — Harness 增量扩展

- 保留现有 finite `TurnRun`、lease/revision、primary-provider-only、strict decision、Skill/capability/effect、safe projection 和 executor 边界。
- 为运行增加明确的教学任务语义，例如计划制定、知识教学、练习评估、复习、模型代码审核和补救教学；不得只依赖自由文本推断任务类型。
- ContextBuilder 必须将权威当前输入、语言、任务类型、当前知识点、当前 Lesson/Exercise/CodeArtifact 和必要 mastery evidence 置于可选聊天历史之前。
- 模型可以提出计划、掌握度、路线解锁和教学 artifact 变更，但最终写入必须经过服务端 policy、证据和事务校验。

## 任务树策略

### 复用的基础子树

- `08-04-tutor-context-governance-adaptive-budget`
  - 权威当前输入与最新意图；
  - provider usage/cache；
  - 自适应 context budget；
  - 长对话摘要；
  - eval 与可观测性。

该子树继续按自身依赖顺序实施，不吸收 LearningTrack、Desktop 信息架构或练习领域职责。

### 已创建的并列交付子树

1. `08-04-learning-track-plan-mastery-domain`
   - LearningTrack、不可变计划版本、路线进度、掌握度证据、Conversation/TurnRun scope 和 `execution_tier` 权威 contract。
2. `08-04-learning-home-plan-builder`
   - 三列学习主线首页、添加入口、计划制定对话和可确认计划组件。
3. `08-04-lesson-document-authority-grounding`
   - 标准/个性化/frozen LessonDocument、注册 block、来源快照和质量门。
4. `08-04-exercise-gates-execution-unlock`
   - 知识点 Gate、模块诊断、Attempt、受控执行与服务端路线解锁。
5. `08-04-spaced-review-sessions`
   - track-scoped 复习队列、ReviewSession、FSRS/掌握度调度和关键前置短 Gate。
6. `08-04-model-code-review-exercises`
   - 结构化 finding、误报评分、private rubric 和模型生成题预发布验证。
7. `08-04-learning-workspace-context-references`
   - 三栏工作区、响应式交互、结构化文档选择与练习/执行/复习引用。
8. `08-12-tutor-authoritative-context-facts`
   - planning collecting typed facts、question state、`AuthoritativeContextSnapshot`、语义 history、compaction barrier 和重复询问回归。
9. `08-12-tutor-controlled-action-runtime`
   - 统一 Action descriptor/invocation/receipt、resource policy、取消、重试、verification、recovery 和安全结果回灌。
10. `08-04-learning-agent-integration-migration-qa-docs`
   - Harness 集成、旧导航收敛、迁移审计、语言矩阵、QA 和 source-of-truth 文档。

父任务只拥有跨 child 需求、依赖与最终集成验收，不直接承担业务实现。以上 11 个 child 已按显式依赖顺序独立完成、验证并归档；最后的 integration child 已完成跨层语言矩阵、迁移审计、全量质量门和 source-of-truth 收敛。

## 验收标准

- [x] 用户可以从三列网格首页创建和进入多个独立 LearningTrack。
- [x] Python、JavaScript、TypeScript 和 SQL 分别通过至少一条“计划制定 → LessonDocument → 练习 Gate → 结果反馈 → 进度持久化”的端到端核心验收；Java 与 HTML/CSS 作为扩展验证且失败不阻断核心 MVP，Go、C#、Rust 和 C++ 根据权威 `execution_tier` 明确降级。
- [x] 添加流程通过对话生成可审阅、可调整、版本化的学习计划并创建路线。
- [x] 掌握度驱动的复习、推荐练习、补救内容和非必要节点排序可以自动调整并留下可解释记录；核心知识点、目标和前置依赖的结构变化必须生成影响预览，经用户确认新计划版本后生效，且不改写既有学习证据。
- [x] 单个知识点不显示“申请跳过”；用户可在当前已解锁知识点内直接滚动到末尾 Gate，但不能滚动进入尚未解锁的后续知识点。
- [x] 只有模块提供“申请跳过模块”；点击后在当前学习页上方打开独立诊断小窗，诊断状态、结果和掌握度证据独立于 LessonDocument 的知识点 Gate 持久化。
- [x] 仅当模块诊断的全部核心能力达到版本化阈值时才跳过整个模块；部分通过不跳过任何知识点，只驱动讲解压缩、推荐练习和薄弱点强化，失败不降低既有已证明掌握度。
- [x] 学习页左侧显示路线、当前节点和今日复习，中间显示结构化教学/复习/训练内容，右侧承载上下文 Tutor 与反馈。
- [x] LessonDocument 引用可追溯的受信来源，并以注册 block contract 持久化和渲染。
- [x] 同一知识点具有经过校验的标准 LessonDocument 和可追溯的个性化派生版本；用户开始学习后内容、Gate、引用快照与评分契约冻结，更新只能创建新版本且旧尝试仍可重放。
- [x] required 练习通过服务端持久化 Gate 控制解锁，失败后存在提示和补救路径。
- [x] 语言与练习的 `execution_tier` 由服务端权威判定；本地/MVP 可使用 `teaching_local`，公开可执行练习仅在 `container_verified` 时开放，并对 `static_only` / `unavailable` 给出真实、清晰的能力反馈。
- [x] 复习队列依据掌握度证据生成，到期数量可见，完成后更新下一次复习状态。
- [x] 模型代码审核练习由系统主动生成，用户提交结构化 findings，系统能评分真实发现、遗漏和误报。
- [x] 审核题在发布前通过静态/编译/测试/rubric 验证，并且隐藏答案不泄露。
- [x] 文档选择、练习结果和审核反馈以结构化引用进入右侧对话，不能冒充用户正文。
- [x] 现有 Tutor Harness 安全边界和 context-governance 子树继续有效，不恢复旧 Graph runtime。
- [x] planning collecting 阶段的已确认语言、目标、每周时间、经验与偏好具有服务器权威 typed facts；超过 recent history 上限、summary 暂不可用或 resume/replay 后不得重复询问已确认字段。
- [x] grounding、plan drafting 和 runner execution 共享统一受控 Action Runtime，具备 resource policy、cancel、retry、verification、recovery、receipt 和安全上下文回灌，同时不复制现有领域 authority。
- [x] 每个 child 具备独立验收、聚焦测试、Trellis validation 和 source-of-truth 文档更新。
- [x] 最终集成通过相关 API、数据库、worker/executor、Desktop、lint、typecheck、测试和 diff hygiene 验证；通过不等于发布或部署批准。

## 范围外

- 推倒重写 Tutor Harness 或恢复旧 LangGraph/SDK 产品运行时。
- 允许模型生成任意前端组件、HTML、shell、SQL、文件路径、镜像或执行目标。
- 把完整 Conversation、raw prompt、provider reasoning、隐藏测试或答案作为公开教学内容或 trace 保存。
- 第一阶段为所有编程语言、框架和运行时同时交付完整课程库；但产品 Contract 必须支持按已验证 runtime capability 分阶段开放多语言。
- 未经单独批准的 commit、push、deploy 或生产数据迁移。

