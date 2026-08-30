# Harness 主导的长期自适应学习工作区

## 目标

将 verified 学习工作区的默认体验从“用户自行阅读 LessonDocument，右侧 Tutor 被动辅助”升级为“Harness 主导教学节奏，LessonDocument 提供可验证教材与证据，用户可随时切换自由阅读”。

系统需要在数周到数月的 LearningTrack 路线上维持稳定上下文，同时让每个知识点的教学由可中断、可恢复、目标导向的事件 Loop 驱动。学习者在讲解、示例、检查、练习或补救中的任何疑问都必须成为一等输入，而不是打断固定流程的异常。

## 用户价值

1. 进入知识点后，学习者不再需要自己判断“先读哪里、何时练习、下一步做什么”，Harness 会基于路线、掌握度、Lesson authority 和当前疑问给出明确的下一步。
2. 学习者可以随时提问、质疑、要求换一种解释、补前置知识、跳过、暂停或切换自由阅读，系统不会遗失原教学目标。
3. 刷新、重连、跨日恢复和长对话压缩后，系统仍能准确恢复当前知识点、教学目标、未解决问题与下一推荐动作。
4. 教学节奏可以自然变化，不被“讲解 → 提问 → 练习 → 总结”的固定话术和固定顺序绑死。
5. LessonDocument、Gate/Attempt、ReviewSession、掌握度和路线解锁继续由服务端权威状态决定，模型不能用聊天正文伪造教学事实。

## 背景与已确认事实

1. 当前长期学习 authority 已具备 `LearningTrack`、不可变计划 revision、稳定 `knowledge_key`、节点进度与可重算掌握度；模型不能直接写 mastery 或解锁节点。证据见 `docs/architecture/database-schema.md:124-166`、`aearn/services/api/app/services/learning/contracts.py:17-87`。
2. 当前 Lesson authority 已具备 immutable standard/personalized `LessonDocument`、active assignment、开始冻结、版本提案和显式迁移；开始课程只推进 `in_progress`，不会自动写完成或掌握度。证据见 `docs/product/user-flows.md:207-218`、`aearn/services/api/app/services/learning/lesson_service.py:47-179`。
3. 当前 Desktop 工作区只有 `lesson | review` 两种中栏模式，Lesson 正文是“课程阅读”，右侧 `TutorConversationSurface` 通过 `lesson_teaching | review_coaching | exercise_feedback | model_code_review` scope 被动接收用户消息或结构化引用。证据见 `aearn/apps/desktop/src/features/learning/TrackLearningWorkspace.tsx:24-31,133-142,223-249`、`aearn/apps/desktop/src/features/learning/LessonDocumentPage.tsx:365-399`。
4. 当前 Harness 已实现长期 `TutorConversation` + 每条普通输入一个 fresh finite `TurnRun`、有限 iteration/model/capability/effect budget、lease/revision fence、typed continuation 和安全终态；这适合作为短期教学执行单元，不适合直接充当数周路线状态。证据见 `docs/architecture/tutor-harness-runtime.md:40-113`、`aearn/services/api/app/services/tutor/run_loop.py:79-367`。
5. 当前 provider action 只包含 `turn_completed | select_skill | request_capability | propose_effect | wait_for_input`，尚未表达“解释一小段、回答插问、切换例子、检查理解、返回主线”等教学语义。证据见 `aearn/services/api/app/services/tutor/decision_protocol.py:117-200`。
6. 当前上下文已具备 `current_input`、required facts、action receipts、active plan、review、recent messages、working summary、learner memory 与 activity 的确定性优先级和预算驱逐规则；可复用为教学上下文底座，但尚无教学焦点栈、未解决问题、已覆盖概念和恢复游标。证据见 `aearn/services/api/app/agents/harness/contracts.py:84-108,481-544`、`aearn/services/api/app/agents/harness/context_builder.py:117-330`。
7. 当前 ReviewSession 会在创建时冻结 `AuthoritativeContextSnapshot`，证明 Aearn 已有“领域会话冻结权威上下文”的可复用模式。证据见 `aearn/services/api/app/services/learning/reviews/context_snapshot.py:14-175`。
8. 当前仓库没有 `teaching_session`、`focus_stack`、`active_focus`、`unresolved_questions`、`guided_learning` 或 `free_reading` 的后端持久化 contract，也没有专用的 Lesson 教学 Skill；现有发布 Skills 只覆盖 learner-state、计划草案、registry grounding 与 runner execution。
9. 当前通用教学策略已经要求最新输入优先、用户纠正/中断覆盖陈旧路径、直接回答建议类问题且最多追问一个必要问题；新教学 Loop 必须保留并具体化这些边界，而不是重建另一套相反策略。证据见 `aearn/services/api/app/agents/harness/provider_request.py:17-27`。

## 已确认产品决策

1. 默认学习体验改为 Harness 主导教学节奏。
2. 用户可随时切换到自由阅读模式，也可从自由阅读返回 Harness 引导。
3. `LessonDocument` 继续作为可验证教材和事实来源，不把一次性模型聊天内容升级为课程 authority。
4. 用户在任意教学阶段产生的疑问、纠正、质疑、跳过或换例子需求必须被正常处理，不能要求用户等待固定流程结束。
5. 产品不采用僵硬的线性教学工作流；状态机负责约束 authority、恢复、并发和终止，模型在受控动作集合内决定当前最合适的教学动作。
6. 默认主动性采用“单步主动、逐段停顿”：进入可学习知识点后 Harness 自动完成一个有边界的教学单元，持久化 checkpoint 后停止；除非收到用户输入、typed `continue`、Gate/Review 结果或其他受控事件，不自动连续发起下一次模型 Turn。
7. 学习工作区采用双区域主次换位：`guided` 模式中间区域是模型对话教学区、右侧是学习文档；点击中间区域右上角的小型双向转换箭头后进入 `free_reading`，中间区域切换为完整学习文档、右侧切换为同一模型会话的辅助面板。
8. `guided` 模式右侧学习文档采用混合跟随：教学焦点或 Lesson block 引用变化时默认定位到对应位置；用户手动滚动、选择文本或操作文档后暂停自动跟随，后续只显示“回到当前讲解”，由用户显式恢复跟随；`free_reading` 模式完全停止自动跟随。
9. 每条 LearningTrack 继续使用一条长期 track-scoped conversation authority，但 UI 和教学状态按知识点 teaching session 分段：当前知识点 session 默认展开，先前知识点/session 折叠为可展开只读历史；不为每个知识点创建互相孤立的 conversation，也不默认渲染数周到数月的完整 timeline。
10. `free_reading` 中的普通选区提问或 Composer 提问继续在右侧同一模型会话中回答，不自动切回 `guided`；需要连续讲解、补救或练习时只提供显式“转为引导讲解”，由用户确认后才交换主次并恢复 Harness 主动教学。
11. 当前知识点被 trusted evidence 推进为 completed 后，工作区停留在当前 teaching session 展示完成总结、未解决问题和新解锁节点；不自动切换 knowledge key 或发起下一教学 Turn。只有用户显式触发 `进入下一知识点`，服务端重新验证最新 roadmap 后才创建/恢复下一 session。
12. 所有 session-level 主次动作统一进入 Composer 上方的动态 `Action Shelf`：每个状态最多一个主动作和三个直接次动作，其余进入更多；全局 Guided/Free Reading 切换保留在顶栏，Gate/Hint/Run/Submit 等 artifact-local 动作保留在对应文档或练习附近。

## 基本原则

### 双时间尺度

- **长期 LearningTrack 状态**：路线、计划 revision、节点进度、掌握度、复习调度和当前知识点继续由现有领域 authority 管理。
- **中期教学会话状态**：记录当前知识点的教学目标、模式、活动焦点、被中断焦点、未解决问题、已覆盖概念、最近权威证据和恢复位置。
- **短期 TurnRun**：每次用户输入或受控系统教学触发创建一个有限 TurnRun，只完成一个有边界的教学动作或一个明确的等待点。

### 事件 Loop，而非阶段流水线

- 教学 Loop 不把学习者锁进固定阶段序列。
- 当前事件可以来自用户输入、自由阅读切换、练习结果、Review 结果、Lesson/Gate authority 变化或系统恢复。
- 模型只能从服务端注册的 closed teaching action 中提出下一动作；Aearn 验证 scope、版本、前置条件、预算和 authority 后执行或公开。
- 每次动作完成后都留下可恢复 checkpoint；疑问是普通事件，不是跳出状态机的异常。

### Authority 分层

- Harness 负责教学编排、焦点管理、上下文选择、下一动作和恢复。
- `LessonDocument` 负责教材正文、引用、block 与 assignment version。
- Gate/Attempt 负责练习输入、评分和安全结果。
- ReviewSession 负责复习批次和 finalization。
- LearningTrack/mastery 负责路线、进度、解锁与长期证据。
- Desktop 只渲染服务端 projection、发送 typed intent 和保存非权威导航指针。

## 范围内

1. 长期路线之上的持久化教学会话与恢复 contract。
2. 可中断、可恢复、自然变化的知识点教学 Loop。
3. 教学焦点栈、未解决问题、已覆盖概念与下一推荐动作的安全投影。
4. Harness 主导模式与自由阅读模式的显式切换、刷新恢复和跨设备/跨日一致性。
5. Lesson block、Gate/Attempt、Review 结果与结构化引用进入教学上下文的统一规则。
6. 专用教学 Skill、closed teaching action、decision gate、版本/lease/CAS 和 safe receipt。
7. 长上下文选择、结构化教学摘要、压缩保护和冲突优先级。
8. Desktop 学习工作区的信息架构、状态反馈、键盘/窄屏与 reduced-motion 行为。
9. 离线 fake provider + 本地 PostgreSQL 的确定性 eval、浏览器 smoke 与 source-of-truth 文档更新。
10. 作为父任务收敛跨层 contract，并在规划完成后按依赖拆分可独立实施的 children。

## 范围外

1. 重做 LearningTrack 计划生成、课程方向识别或语言选择闭环。
2. 取消或弱化 LessonDocument、Gate/Attempt、ReviewSession、mastery 的现有 authority。
3. 通过阅读时长、滚动位置、停留时间或模型主观判断直接写 mastery/完成/解锁。
4. 允许模型生成任意 React/HTML、任意工具、任意教学状态字段或数据库 target。
5. 自动切换 provider/model/protocol，或把真实 provider smoke 加入默认 CI。
6. 恢复旧 Graph、旧 learning session、旧 Review/Notes 页面或 general conversation 主导航。
7. 未经单独批准的真实 provider 调用、提交、推送、部署或生产数据迁移。

## 需求

### R1 — 持久化教学会话 authority

- 每条 LearningTrack 继续绑定一条长期 track-scoped Tutor conversation；在该 conversation 内为 `user_id + track_id + knowledge_key` 建立可恢复、带版本的 teaching session 根，同一知识点最多一个当前活动 session，历史 session 保留安全 lineage。
- knowledge key 或 active plan context 变化时创建/恢复对应 teaching session，而不是创建新的普通 conversation；Turn/message 需要带可验证 session scope，确保当前教学时间线可按 session 投影。
- 会话至少记录 active Lesson assignment/document identity、教学模式、当前教学目标、当前焦点、暂停焦点栈、未解决问题、已覆盖概念摘要、最近 Gate/Review evidence cursor、下一推荐动作、会话版本和最后有效活动时间。
- 会话状态不得复制完整 LessonDocument、完整聊天历史、完整提交、hidden rubric/test、provider reasoning 或 raw tool result。
- 刷新、重连、跨日恢复先从 PostgreSQL 读取并校验 track/plan/assignment/progress 版本；本地导航指针不得成为教学状态 authority。

### R2 — 有界教学 Turn 与 closed teaching action

- 进入一个可学习知识点时，服务端允许创建一次受控 system-triggered fresh finite `TurnRun`，主动完成首个教学单元；恢复已有会话时先校验 checkpoint 与 authority，再决定恢复说明或下一动作。
- 每次教学推进固定当前 teaching session、track、knowledge key、assignment/version、模式和 input revision；一个 TurnRun 只承担一个主要教学目的或一个明确等待点。
- “一个教学单元”可以包含一段解释、一个例子和必要的 Lesson 引用，但只能解决一个中心问题；不得一次输出整节课程并预先决定用户尚未响应的后续路径。
- 首版 closed action 至少覆盖：定位目标、解释一个有界概念块、回答当前疑问、换例子或做对比、发起理解检查、建议/发起练习、解释练习反馈、补救前置知识、总结当前进展、建议暂停、等待用户输入。
- 每个教学单元完成后必须提交 durable checkpoint，并进入软停顿、理解证据停顿、authority 停顿或会话停顿之一；停顿不等于每段强制考试。
- `continue`、返回主线、换例子、进入/退出自由阅读等高频动作使用服务端 typed event，不要求模型从“继续”等自由文本猜测控制意图；Composer 在所有阶段保持可用。
- 默认禁止一个教学单元完成后静默自动创建下一次模型 Turn；下一 Turn 必须由新用户输入、typed control、Gate/Review terminal result、authority refresh 或显式恢复事件触发。
- 模型不能定义 action schema、数据库 ID、Lesson block、Gate、评分、mastery 或下一路线节点；它只能引用服务器已投影的稳定 handle。
- Aearn 在公开或执行动作前校验 active focus、允许动作、authority version、lease、budget、幂等和安全输出；stale/superseded/interrupt 后的结果不得写入会话。
- required Gate 或其他 trusted evidence 将节点推进为 completed 时，当前 teaching session 进入完成停顿；Aearn 读取最新 roadmap 投影 next available node，但不得自动修改 workspace knowledge key 或创建 system-triggered next-node Turn。
- `进入下一知识点` 是显式 typed control，提交 expected track/progress/session version 与 next knowledge key；服务端重新验证节点仍属于 active plan 且 available，成功后创建/恢复下一 teaching session，并只自动完成其首个教学单元。
- 完成后仍允许继续提问、查看反馈、进入复习、返回路线或暂停；这些动作不得因存在推荐 next node 而被阻断。

### R3 — 一等中断与焦点恢复

- 用户在任何时刻发送消息时，当前输入始终高于既有教学计划、working summary、memory 和旧推荐动作；正在生成的旧 Turn 可被显式 Interrupt/Steer，返回后的 stale 结果不能发布。
- 系统将中断投影为受控类型，例如：局部澄清、深入追问、质疑/纠正、前置知识缺口、换例子、导航变化、跳过/暂停、自由阅读切换或离题请求。
- 处理中断时保存原 active focus，将新问题作为子焦点；回答或处理后明确恢复原焦点、调整目标或等待用户选择，不能默默遗失主线。
- 多个连续追问允许形成有界焦点栈或问题队列，但必须有深度/数量上限、压缩规则和安全降级。
- 用户明确纠正、拒绝、已完成声明或目标变化时，陈旧焦点与推荐动作立即失效，不重复被拒绝路径。

### R4 — 自然且不教条的教学策略

- 状态机只定义合法动作、authority、恢复和终止，不规定每个知识点必须按固定顺序走完全部教学动作。
- 模型根据当前目标、学习者输入、掌握度、Lesson blocks、最近 evidence 和教学偏好选择下一动作；相同知识点可因用户反应走不同路径。
- 每次解释保持有界，优先解决当前疑问，并根据证据决定继续解释、换例子、检查理解、练习或暂停。
- 避免重复固定话术、每段都提问、机械编号或为了“走流程”强制用户回答已确认内容。
- 没有足够 evidence 时表达不确定并请求一个必要澄清；不得自行把推断升级为 confirmed learner fact。

### R5 — Harness 主导与自由阅读双模式

- 教学会话显式保存 `guided` 与 `free_reading` 模式；切换模式是服务端 typed mutation，并使用 expected version + idempotency。
- `guided` 模式下，中间主区域承载同一 track-scoped 模型会话、当前教学单元、焦点提示、typed controls 与 Composer；右侧区域展示同一 active frozen LessonDocument 的学习文档。
- Guided 右侧文档默认跟随服务端当前教学焦点引用的稳定 Lesson block handle；自动定位只能发生在 active assignment/document hash 匹配且用户没有暂停跟随时。
- 用户手动滚动、键盘浏览、选择文本、展开来源或操作 Gate 后，当前客户端 view session 立即进入 `follow_paused`；后续焦点变化不得抢夺滚动位置或破坏选区，只显示可键盘触发的“回到当前讲解”。
- 点击“回到当前讲解”后定位到最新有效 block 并恢复跟随；切换到 `free_reading` 时无条件暂停跟随，返回 `guided` 后仍保持暂停，直到用户显式恢复或进入新的知识点/教学会话。
- `free_reading` 模式下，两块区域交换主次：中间主区域展示完整学习文档、引用与 Gate，右侧区域展示同一模型会话的辅助面板。
- 模式切换只改变 presentation role、panel width/priority 和 Harness 主动推进策略，不创建第二条 conversation、第二份 LessonDocument、第二套 SSE reducer 或并行教学会话。
- 双向切换入口固定放在中间区域右上角，使用小型双向转换箭头图标；按钮必须有可读 accessible name、tooltip、focus-visible、disabled/loading 状态和足够触控目标，不能只依赖图形含义。
- 自由阅读仍使用同一 active frozen LessonDocument、引用和 Gate authority；切换不会重置进度、丢失教学焦点或修改 mastery。
- 自由阅读模式下 Harness 停止主动创建后续教学 Turn，但用户仍可在右侧辅助面板提问、发送选区引用、引用 Gate/Review 结果或请求恢复引导。
- 自由阅读中的普通问题创建同一 teaching session 下的 reactive finite Turn，回答完成后保持 `free_reading`，不得因存在 learner message、Lesson selection 或模型判断“适合教学”而自动切换模式。
- 当问题需要多步解释、补救、理解检查或练习时，模型只能提出 learner-safe escalation hint；Aearn 投影显式 `转为引导讲解` typed control，只有用户触发后才把 mode 改为 `guided` 并建立下一教学 focus。
- `转为引导讲解` 必须保存原问题、Lesson selection 和回答 lineage，切换后不要求用户重新提问，也不把切换动作本身伪装成 mastery 或完成 evidence。
- 从自由阅读恢复时，中间区域重新成为教学区；Harness 根据持久化焦点、未解决问题、已覆盖摘要和最新 authority 给出短恢复说明与下一推荐动作，不要求重读整课。
- 阅读 receipt 如需加入，只能记录安全、可选的定位事实；停留/滚动不能单独成为 mastery evidence。

### R6 — 长期上下文与压缩

- 教学 Turn 的上下文优先级为：system/policy → current input 或受控 system trigger → teaching session focus/objective → confirmed learner/track facts → exact Lesson/Attempt/Review references → bounded recent messages → structured teaching summary → evidence-backed learner memory/activity → capability schema。
- teaching session 的 required 部分无法完整表示时 fail closed，不调用 provider 猜测当前目标。
- 压缩只退休已被结构化教学摘要覆盖且不受未解决问题、纠正、活动焦点或唯一 evidence 保护的消息。
- 持久化结构化摘要和安全 source IDs/hashes，不保存 provider prompt/body、reasoning 或完整历史副本。
- 最新用户纠正、最新 authority 和当前 focus 必须覆盖旧 summary/memory；冲突产生 stale 标记并触发重建。
- 跨知识点连续性通过 track facts、当前/前序 teaching session summary、明确的跨 session reference 和相关性检索提供；不得因为 UI 折叠历史而丢失模型所需 authority，也不得把整条 conversation 全量重放作为默认连续性机制。
- 当前 session 的 required focus/objective 优先于旧 session summary；用户明确引用先前知识点时，可以选择相关历史片段或 frozen summary，但旧 session 不能覆盖当前纠正或当前知识点目标。

### R7 — Desktop 工作区

- 保留左侧路线 authority；右侧两块学习表面由 `guided/free_reading` 决定主次，不再固定为“中栏 Lesson + 右栏 Tutor”。
- `guided` 模式的中间教学区以模型与用户的对话教学为主，显示当前教学动作、焦点、被暂停主线、未解决问题、下一推荐动作和 Composer；右侧学习文档支持阅读 active Lesson 与必要 Gate。
- 中间教学区默认只展开当前 knowledge key 的 active teaching session；顶部显示 bounded 恢复摘要和与上一知识点的关系，不把整条 track conversation 默认铺成长 timeline。
- 先前 teaching sessions 按知识点和完成/暂停时间折叠为只读历史入口；展开历史不改变 active session、Composer scope、当前 input revision 或 Harness 下一动作。
- 历史 message 仍属于同一 conversation authority；UI 分段只改变 projection/grouping。用户从旧 session 引用内容时必须生成 exact cross-session reference，不能通过复制文本伪造当前输入或当前 focus。
- 右侧文档跟随状态属于临时 presentation state，不改变 teaching session、Lesson assignment、progress 或 mastery；刷新后默认可重新跟随当前焦点，但不得从旧 DOM scroll offset 推断教学事实。
- 自动定位尊重 `prefers-reduced-motion`，使用无动画或短距离受控滚动；“回到当前讲解”必须说明目标 block/章节并保持焦点可见。
- `free_reading` 模式将完整学习文档放入中间主区域，模型会话移动到右侧辅助角色；两种模式复用同一 conversation history、active Turn、draft references、document assignment、Gate state 和各自滚动位置。
- 右侧辅助回答保持适合窄栏的 bounded 表达，但不能通过截断隐藏必要结论；需要更大教学空间时显示显式“转为引导讲解”，而不是自动交换面板或在右栏连续自动推进。
- 用户拒绝升级或继续阅读时，问题保持已回答/待跟进状态，原 guided focus 不被自动恢复，Harness 不在后台继续该教学分支。
- 中间区域右上角始终提供双向转换箭头；切换时不销毁或重新挂载权威会话，不重复订阅 SSE，不丢失未发送 Composer、结构化引用、选区和当前教学 checkpoint。
- 模式切换应立即改变布局并显示服务器确认中的受控状态；失败时恢复原模式并保留全部临时输入，不留下前后端模式漂移。
- 用户可以在讲解中直接提问、请求换例子、查看教材原文、开始允许的 Gate、暂停或返回路线；前端不自行推断允许动作。
- 当前节点完成后，中间主区域显示服务端 learner-safe completion projection：本节完成摘要、真实 evidence 概览、未解决问题、新解锁节点和允许的 transition actions；右侧文档/Gate 结果保持可查看。
- 中间模型表面的底部 interaction dock 自上而下为：`Composer Action Shelf`、draft reference chips 或 exact typed request presentation、Composer、Send/runtime controls；shelf 更新不得清空草稿、引用或改变输入焦点。
- Action Shelf 只消费服务端 closed `allowed_actions` projection，不接受模型自由生成 label/target/payload；每个状态最多一个 primary、三个直接 secondary，更低优先级进入 `更多`。
- 普通 pause、插问回答、free-reading escalation、completion、Review/恢复分别投影不同 shelf；active Turn 时普通 shelf 被 Stop/Steer 等 runtime control 替换，blocking typed request/Generated UI 占据交互槽位并阻止绕过动作。
- Guided/Free Reading 双向箭头继续固定在中间顶栏；Hint/Run/Submit、citation、答案编辑、validation evidence 和 Lesson migration 等 artifact-local 动作保持就地，Action Shelf 不复制第二个 mutation 入口。
- 下一节点标题、顺序和 availability 只来自刷新后的 roadmap，不从当前 Lesson 的 `next_steps` 文本或模型推荐推断；陈旧 next-node control 返回 conflict 并刷新。
- 宽屏、中屏和窄屏都必须保留模式切换入口，但具体 drawer/tab 重排由响应式设计在不复制状态的前提下完成。
- scope、mode、knowledge key、assignment 或 teaching session 切换时中止不再属于当前 scope 的旧请求并清理临时 UI；服务端持久化状态不被误清除。

### R8 — 可观测性与评估

- trace/receipt 只记录 teaching session/version、focus/action enum、source IDs/hashes、interrupt type、context selection、budget、终态与安全 diagnostic；不得记录 raw 教学正文、完整问题、提交、prompt、reasoning 或 provider body。
- 确定性 fixtures 至少覆盖：跨日恢复、连续追问后回到主线、用户纠正覆盖旧焦点、自由阅读往返、Lesson migration conflict、Gate/Review authority 更新、summary stale、provider unavailable、stale TurnRun fencing 和窄屏交互。
- 教学质量 eval 至少检查：是否先回答当前疑问、是否保留主目标、是否避免重复已确认内容、是否在证据不足时澄清、是否避免固定流程话术、是否在无 mastery evidence 时拒绝自动推进。

## 验收标准

- [ ] verified 用户进入一个可学习知识点时，Harness 自动完成且只完成一个首个教学单元，给出当前目标和下一推荐动作，然后进入可见停顿；没有新事件时 provider 调用次数不继续增长。
- [ ] 学习者在解释、示例、检查、练习反馈或补救期间连续提出不同类型问题，系统均先处理当前输入，并能恢复、调整或显式放弃原焦点。
- [ ] 教学路径不是固定阶段列表；同一 fixture 中不同 learner response 会产生不同但合法的 closed teaching action 序列，`continue`、插问、换例子和自由阅读不会被误当成同一动作。
- [ ] 一个教学单元结束后写入 checkpoint 并停止；软停顿不强制答题，理解证据停顿和 authority 停顿分别等待真实 learner/领域事件。
- [ ] 刷新、SSE 重连、Desktop 重启和跨日恢复后，当前知识点、模式、assignment、active focus、未解决问题和下一推荐动作与 PostgreSQL authority 一致。
- [ ] 一条 LearningTrack 只有一条长期 conversation authority；切换知识点创建/恢复 teaching session scope，但不会创建互相孤立的普通 conversation。
- [ ] Guided 默认只展开当前知识点 session，并显示 bounded 恢复摘要；先前知识点按 session 折叠，展开只读历史不会改变 active focus、Composer scope 或当前 Turn。
- [ ] 明确引用先前知识点时，provider context 可获得受 scope/hash 约束的跨 session reference 或 summary；未展开 UI 历史不会导致连续性丢失，整条 conversation 也不会被默认全量重放。
- [ ] `guided` 模式中间区域显示同一模型会话的对话教学、右侧显示学习文档；点击中间右上角双向转换箭头后，`free_reading` 模式中间显示完整文档、右侧显示同一模型会话。
- [ ] 主次换位不会创建第二条 conversation、第二份 LessonDocument、第二套 SSE subscription 或重复 Gate state；conversation history、active Turn、Composer、references、教学 checkpoint 和文档滚动位置可恢复。
- [ ] Guided 初始教学焦点可将右侧文档定位到对应 active Lesson block；用户手动滚动、选择或操作文档后，后续模型讲解不会抢夺位置，并提供“回到当前讲解”恢复入口。
- [ ] `free_reading` 中无自动跟随；返回 `guided` 后不会突然跳转，只有用户显式恢复跟随或进入新知识点/新教学会话时才重新启用。
- [ ] 自由阅读中的普通选区/Composer 提问在右侧回答并保持 `free_reading`；回答结束后不会自动交换面板或创建下一教学 Turn。
- [ ] 需要连续教学时显示 `转为引导讲解` typed control；只有用户显式触发才切换 Guided，且原问题、引用和回答 lineage 完整保留。
- [ ] 节点 completed 后停留在当前 teaching session，显示完成总结、真实 evidence、未解决问题和新解锁节点；没有用户 transition event 时 conversation/knowledge key/provider 调用不继续推进。
- [ ] 只有用户触发 `进入下一知识点` 后才重新验证 roadmap、创建/恢复下一 teaching session 并发起其首个有限教学单元；陈旧或不再 available 的目标 fail closed。
- [ ] 所有 session-level 主次动作统一出现在 Composer 上方 Action Shelf；一个状态只有一个 primary、最多三个直接 secondary，低频动作进入更多，1440px/900px/390px 下无水平滚动。
- [ ] Action Shelf 与 mode switch、artifact-local Gate actions、active runtime controls 和 blocking typed request 的职责互斥；状态变化不丢 Composer/reference，不重复 mutation，也不自动聚焦主动作。
- [ ] 自由阅读与 Harness 引导可双向切换；自由阅读不会丢失状态、伪造 mastery、自动完成节点或创建并行课程 authority。
- [ ] Lesson block、Gate/Attempt、ReviewSession、mastery 和路线解锁继续使用现有 source of truth；模型文本和客户端状态无法越权写入。
- [ ] teaching session required context 不可表示、scope/version 冲突、stale TurnRun、provider unavailable 和 action denied 均 fail closed，并提供 learner-safe 恢复路径。
- [ ] 上下文压缩后仍保留 active objective、被暂停焦点、用户纠正、未解决问题和必要 evidence；旧 summary/memory 不能覆盖最新输入。
- [ ] 1440×900、900×900 和 390×844 下默认引导、自由阅读、提问、Gate、Review 与恢复路径无页面级横向溢出，键盘焦点和 reduced-motion 行为正确。
- [ ] fake provider + 本地 PostgreSQL 的 focused/full Pytest、Ruff、Mypy、Desktop tests/check、bootstrap twice、browser smoke、Trellis validate 与 `git diff --check` 通过；默认不调用真实 provider。

## 风险与控制

1. **Harness 过度控制**：如果连续自动推进，用户会失去掌控且成本不可预测。通过有限 Turn、可见 checkpoint、随时中断和自由阅读控制。
2. **状态过度复杂**：如果把每句话都建模为 durable 状态，恢复和迁移会失控。只持久化教学目标、焦点、未解决问题、覆盖摘要与 authority identity；正文留在原始 authority。
3. **上下文膨胀**：连续追问可能无限增长。使用有界焦点栈、结构化摘要、protected evidence 与预算驱逐。
4. **伪掌握**：自然对话容易被误当学习证据。只有现有 trusted Gate/Review/diagnostic evidence 能更新 mastery。
5. **教材与讲解漂移**：模型可能偏离 LessonDocument。事实性解释必须引用 active assignment 的稳定 block/citation handle；新事实需走 approved grounding。
6. **旧工作区兼容**：新增模式与教学会话必须 additive-first；旧 track-scoped conversation/history/reference 保持可读，不从历史聊天批量推断教学状态。
