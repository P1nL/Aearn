# 复用 DeepSeek Harness UI 重构 Aearn Tutor 对话体验

## 目标

基于 `deepseek-ai/deepseek-harness` 的固定 MIT revision，近像素复用选定的 Tutor 会话 UI、布局几何、状态样式、动效和交互细节，并替换为 Aearn 品牌身份。首轮建立 Aearn-owned UI foundation，同时补齐受控 Typed Question、持久化 FIFO Queue 和当前 TurnRun 停止能力，使 Desktop 获得接近 Codex/DSH 的对话体验，而不引入 DSH 的 Cordis/plugin/runtime，也不削弱 Aearn 的教学、安全和服务端权威边界。

## 背景与事实

- Aearn 当前正式 Desktop 位于 `aearn/apps/desktop/src/`，使用 React 19、Vite、Tauri、Zustand、REST/SSE；Tutor 复杂交互集中在 `features/tutor/TutorConversationSurface.tsx` 和大型 `styles.css` 中。
- 当前 source of truth 为 `docs/README.md` 索引的运行时、API、数据库、用户流和 Desktop 交互文档。
- DSH Web UI 由多个 Cordis/plugin/slot package 组成，不能把完整运行时直接嵌入 Aearn；RC npm 包也不携带可直接消费的完整 CSS modules。
- 上游固定基线为 revision `47f943859bef60e4160492346772ded9b24f765a`，revision 时间 `2026-08-13T19:38:46+08:00`，目标源码许可证为 MIT。
- DSH `QueueDock`、`QuestionComposer`、`PlanReviewPanel`、`ReasoningRow`、`InputBar` 与 primitives 的 React/CSS 可以从固定 revision 派生为 Aearn-owned 组件。
- DSH `Stop generating` 会终止当前 turn、保留 Queue 并暂停消费；用户下一次正常发送会追加到队尾并唤醒 FIFO。证据见上游 `apps/web/tests/queue-actions.e2e.ts:153-178`。
- Aearn 已有内部 `PostgresTutorRepository.request_cancellation()` 和 run-loop 协作式取消检查，但 `routes/tutor.py` 尚无 learner-facing run-level cancel API。
- Aearn 原始工作树 `E:\codee\Aearn` 存在用户未提交的 prompt、`clarification` / `planning_input` enum、Desktop 类型和展示修改；本任务不得覆盖、撤销或整包搬运这些修改。

## 用户价值

- 减少 Composer、Queue、问题收集、计划审核、Disclosure、按钮、Tooltip、Toast 和状态反馈的重复手写。
- 将 DSH 已验证的交互矩阵转化为 Aearn 的自动化验收，降低边界遗漏。
- 保持 Aearn 的 REST/SSE/Zustand、Tutor Harness、教学流程和服务端权威，不引入第二套应用运行时。
- 建立可持续维护的来源映射和 semantic tokens，后续 UI 迁移可复用同一基础层。

## 范围内

1. Aearn-owned DSH-derived 白色浅色 UI foundation、semantic tokens、所需图标和许可证/来源记录。
2. Tutor Composer、QueueDock、QuestionComposer、PlanReviewPanel 内部结构和 Think disclosure 的近像素复用。
3. `clarification` / `planning_input` 的准确 enum、服务端受控 pending-input projection、question catalog/template 和结构化答案校验。
4. 服务端持久化、conversation-scoped、有界 FIFO Queue，以及创建、读取、编辑、删除、Steer、恢复和自动消费能力。
5. learner-facing run-level stop authority 与 DSH 一致的“停止当前 run、保留并暂停 Queue、下一次发送唤醒 FIFO”行为。
6. 右侧浮动计划草案检查器、Desktop 响应式适配、键盘/焦点/reduced-motion 和相关正式文档、测试、NOTICE。
7. 对原始工作树中重叠的 typed continuation 和 prompt contract 修改进行逐文件语义移植与冲突核对。

## 范围外

- 引入整个 DSH Web 应用、Cordis、DSH runtime、model selector、permission mode、command menu 或 workspace/session hierarchy。
- 复制 `FishLogo`、`BrandWordmark`、DeepSeek 名称、品牌资产或使产品被误认为 DeepSeek 的文案。
- 首轮重做全局 AppFrame、Sidebar、Settings、Learning Home、Lesson、Review 或其他非 Tutor 页面。
- 首轮提供 `dark` / `system` 主题、主题持久化或设置入口。
- 将 Aearn 改造成 terminal/diff/search coding workspace，或渲染 DSH 的 coding-specific cards。
- 展示 provider-native reasoning、raw chain-of-thought、raw trace、未校验的 provider partial JSON、hidden tests、reference answer 或内部 rubric。
- 删除服务端 `TutorPublicProcess`、相关数据库/API/SSE projection 或兼容行为。
- 重做原始工作树中“只生成教学场景与候选代码、tests/rubric 由受控 DSL/template 构造”的既有实现；本任务只负责避免回退并处理必要的 typed-input 接缝。
- 删除或替换受保护的 `docs/design/learning-agent-claude-desktop-framework.html`。
- 在规划阶段修改产品代码、提交、部署或运行真实 provider smoke。

## 需求

### R1：固定来源与可维护派生

- 所有 substantial derived 文件必须标注上游仓库、路径、固定 revision 和 MIT 来源。
- 在 Desktop 范围内增加第三方 NOTICE 与 upstream mapping；后续升级只能对新 revision 做人工 diff 审核，不能跟随 npm RC 自动漂移。
- 生产依赖不得新增 Cordis 或 DSH runtime package。

### R2：视觉、品牌与主题

- 对选定 DSH 组件尽可能保留 React 结构、CSS modules、尺寸、间距、圆角、阴影、布局几何、动效和交互细节。
- 产品名称、Logo、可见文案和品牌身份统一替换为 Aearn。
- 首轮仅交付白色浅色主题：主背景和主要表面为白色，使用 DSH 浅色中性层级；Aearn 绿色只承担品牌强调、焦点、选中、主操作和正向状态。
- 品牌替换集中在 token/alias 层，不逐组件散落硬编码改色；公共 API 只暴露 `--aearn-*`，derived CSS 内部兼容变量由统一映射层提供。

### R3：Aearn-owned UI foundation

- 建立低耦合 primitives 和实际使用的非品牌图标，至少覆盖 `Button`、`Pill`、`Input`、`StateDot`、`DisclosureRow`、`Tooltip`、Toast 外观适配、`MessageText` 及 send/stop/queue/edit/delete/check/chevron 图标。
- primitives 不读取 Tutor store、API、session 或 DSH runtime，只接受 typed props、children 和 callbacks。
- 业务组件通过 controlled props/actions 使用 foundation；不在 `styles.css` 继续堆叠一套平行的按钮、Disclosure、Queue 和 Composer 样式。

### R4：Composer、默认 Queue 与停止生成

- 普通 Composer 近像素复用 DSH capsule、textarea、toolbar、主按钮和 Queue dock stack geometry；不复制 model/access/command/runtime 逻辑。
- 新 Desktop 默认使用 Queue delivery；旧客户端未声明 Queue delivery 时保留现有 latest-input-wins 兼容路径。
- run 正常处理中收到的普通消息进入服务端持久化 FIFO Queue，不立即写成公开 learner timeline message，也不触发竞争 run。
- Queue 是服务端 source of truth，按 conversation 隔离并限制为最多 20 个待处理项；单项内容继续遵守 16,000 字符上限。
- Queue 提供列表、创建、编辑、删除、`Steer`、幂等 mutation、版本冲突、active-run SSE snapshot、刷新/重连恢复和 busy/error 状态。
- `Steer` 将选中项原子转换为当前 run 的新 input revision，在下一个安全边界重建 context；其余 Queue 项保持原顺序。
- 当前 run 只有在 `completed` 时自动启动 FIFO 下一项对应的 fresh finite TurnRun；`cancelled`、`failed`、`model_unavailable`、`blocked_policy` 和 `budget_exhausted` 均保留并暂停 Queue。
- 当 Queue 已暂停且没有 active run 时，用户下一次普通发送先追加到队尾，再唤醒最早的 Queue 项。
- active interactive run 处于 `queued`、`leased`、`running` 或 `waiting_for_capability` 时，Composer 主按钮切换为方形 `Stop generating`；`waiting_for_input` 由 Typed Question 接管，`awaiting_effect_commit` 不提供可误导的停止按钮。
- stop 只取消当前 run，不取消 planning session，不删除 Queue；服务端必须做 user/run ownership、状态校验、幂等、终态 event 和 post-cancel public-write fencing。
- Aearn 当前不公开未校验的 provider partial；停止后保留任何已持久化 learner-safe 内容，但不得为了仿照 DSH 而暴露 raw streaming partial。provider 调用可能在后台完成，首轮不宣称 provider-side billing abort。

### R5：受控 Typed Question

- `clarification` 和 `planning_input` 必须是独立、准确的 `TutorContinuationKind`，不得继续用泛化 `approval` 表达。
- `waiting_for_input` 必须持久化并公开一个版本化、learner-safe `pending_input` contract；Desktop 不从文案猜测 input 类型。
- `clarification` 使用无选项文本回答卡，问题正文来自服务端已安全校验的 public message。
- `planning_input` 只接受 allowlisted `question_key`；服务端 question catalog/template 根据 `PlanningFactField` 和受控课程目录构造标题、说明、输入类型、选项、推荐项、限制和版本。
- question catalog 覆盖 `language_id`、`goal_text`、`target_level`、`weekly_minutes`、`experience_level`、`teaching_preferences`、`pace_constraints` 七个 required facts。
- provider 只能选择 continuation kind、allowlisted `question_key` 和 learner-safe question text；不能生成任意 UI schema、tests 或 rubric。
- required Typed Question 完全接管 Composer，不并列显示普通 Composer/Queue，也不显示 skip 或 close；用户退出整个规划使用页面顶部“取消计划”。
- Frontend 提交 pending-input identity、expected input revision、结构化 planning facts 与对应 learner-visible content；服务端验证 stale、scope、question key、值域和幂等后才能恢复原 run。
- 涉及 continuation enum 的 prompts/skill instructions 必须包含至少一组正例、反例和边界示例，并通过静态/contract 测试证明 `clarification`、`planning_input` 与 `approval` 不混用。

### R6：Think 与 Process authority

- Tutor message 只在 `public_thinking_steps[]` 非空时渲染 DSH `ReasoningRow` 形态的 disclosure，可见标题固定为英文 `Think`。
- `Think` 只消费成功 Tutor message 上经安全校验并持久化的最多四条 `public_thinking_steps[]`；不得接入 provider-native reasoning、raw trace 或 run-level process steps。
- legacy message 缺少 `public_thinking_steps[]` 时不合成 `Think`。
- Desktop 移除当前“公开处理过程”timeline row，不显示 `TutorPublicProcess` 的 steps、duration 或 terminal card。
- 服务端继续维护 `TutorPublicProcess` authority，用于生命周期、替换/失败审计、SSE/history 兼容、恢复和测试；本任务不删除相关后端 projection。

### R7：计划草案检查器

- 保留 Aearn 右侧浮动计划草案窗口及 `docs/product/frontend-interaction-spec.md:215`、`docs/product/user-flows.md:202` 的 planning flow，不让窗口挤压对话主列。
- 窗口内部近像素复用 DSH `PlanReviewPanel` 的 card/strip/body/footer/actions 结构，但正文继续渲染 Aearn typed plan artifact，不引入任意 Markdown authority。
- “讨论/调整”关闭审核焦点并将普通 Composer 聚焦；“批准”调用 Aearn 现有确认 API；取消整个规划继续使用页面顶部“取消计划”。
- 新 draft 自动展开，同一 draft 的手动收起在普通刷新中保持；窄屏使用受限高度底部浮动检查器。

### R8：兼容与迁移

- 原始工作树未提交修改必须先做精确 diff；只语义移植与本任务重叠的 continuation/type/prompt contract，不使用 blanket checkout、reset 或整包 patch 覆盖新工作树。
- `TutorConversationSurface.tsx:616-637` 当前 continuation 提示卡和手动切换 Composer mode 路径在 Typed Question 接管后删除，避免重复入口。
- `docs/product/frontend-interaction-spec.md:18-20,116-134` 的普通输入、Think/process 展示规则必须与新行为同步；API、数据库、runtime、user flow 和 acceptance 文档也必须从实际实现更新。
- migration 必须保持旧 history、旧客户端、旧 idempotency record 和 `TutorPublicProcess` 可读；新增字段采用 additive contract。

### R9：测试与质量

- 将 DSH Queue、Question Composer、Plan Review、Composer、stop、scroll 和 narrow-layout 行为矩阵重写为 Aearn fixture，不复制 DSH 业务 fixture 或品牌文案。
- 后端覆盖 PostgreSQL bootstrap twice、queue FIFO/边界/并发/跨用户/幂等、Steer、安全 dequeue、stop、terminal fencing、pending-input stale/validation、SSE replay 和旧客户端 latest-input-wins 回归。
- Desktop 增加可执行的组件交互测试基础，覆盖 Queue 单/多项、编辑/删除/Steer、Question radio/checkbox/custom/pager/required validation、Think disclosure、stop、plan inspector 和键盘/IME。
- 真实浏览器在 1440px、900px、390px 检查白色浅色主题、sticky Composer、Queue 几何、浮动 plan inspector、焦点、reduced motion、无横向溢出、无 console error/overlay。
- 默认验证不得访问真实 provider、启动生产 container fleet、部署或宣称 release approval。

## 任务拆分与依赖

父任务只拥有总需求、跨子任务契约和最终集成复核，不直接作为实现目标。执行顺序如下：

1. `dsh-derived-ui-foundation`：UI tokens、primitives、icons、NOTICE 和组件测试基础；无前置依赖。
2. `tutor-controlled-pending-inputs`：准确 continuation enum、受控 pending-input/question catalog、prompts/examples 和 API projection；依赖原始工作树重叠 diff 已完成语义核对，不依赖 Child 1 代码。
3. `tutor-persistent-queue-stop`：持久化 FIFO Queue、Steer、dequeue、stop API/SSE/DB；不依赖 Child 1/2 代码，但执行前必须确认其 API contract 未发生冲突。
4. `tutor-dsh-conversation-integration`：Desktop Composer/Queue/Question/Think/Plan integration、文档与浏览器 QA；依赖 Child 1、2、3 全部完成并通过各自验证。

## 验收标准

### 规划验收

- [x] 固定 DSH revision、时间、许可证和本地审计基线。
- [x] 用户确认 Tutor-first + shared foundation、完整复用选定 UI、Aearn 品牌、绿色 token、白色浅色首轮主题。
- [x] 用户确认右侧浮动 plan inspector、Typed Question 接管 Composer、required question 无 skip/close、完整服务端 Queue authority。
- [x] 用户确认 UI 只保留 `Think`，服务端 `TutorPublicProcess` authority 继续存在但 Desktop 不渲染。
- [x] 用户确认 DSH 风格 stop：取消当前 run、保留并暂停 Queue、下一次发送唤醒 FIFO。
- [ ] `design.md`、`implement.md` 与四个子任务工件完整、中文、依赖显式。
- [ ] 父任务和全部子任务通过 `task.py validate`，状态保持 `planning`。

### 后续实施验收

- [ ] Aearn 生产依赖中不存在 Cordis 或 DSH runtime package；DeepSeek 品牌资产和可见名称搜索为零。
- [ ] substantial derived source、NOTICE 和 upstream mapping 指向固定 revision，许可证信息完整。
- [ ] 白色浅色 Tutor UI 在 1440/900/390 近像素匹配选定 DSH surface，Aearn 绿色只通过 token 层使用。
- [ ] Queue 在刷新、重连、编辑、删除、Steer、正常完成、stop、失败和唤醒场景中保持服务端 FIFO authority；跨用户与 stale mutation 失败关闭。
- [ ] stop 主按钮、run cancel API、终态 SSE 和 public-write fence 可观察且幂等；不声称 provider-side 硬中断。
- [ ] `clarification` / `planning_input` 使用受控 pending-input contract，七个 required facts 全覆盖，prompt examples/contract tests 通过。
- [ ] `Think` 只读取 `public_thinking_steps[]`；Desktop 不渲染 run-level process，且不泄露 raw reasoning/trace/partial。
- [ ] 右侧 plan inspector、Typed Question takeover、Composer/Queue/stop 和窄屏行为符合键盘、焦点、IME、滚动及 reduced-motion 要求。
- [ ] 原始工作树用户修改未被覆盖；重叠语义已逐文件核对并记录。
- [ ] 相关 backend tests、Ruff、Mypy、Desktop component tests、`desktop:check`、浏览器 smoke、Trellis validate 和 `git diff --check` 全部通过。

## 风险与延后项

- DSH 的视觉结构可近像素复用，但 Aearn 不公开未校验 provider partial；停止后的 partial 行为只能保留已持久化 learner-safe 内容。
- 首轮 stop 是立即持久化取消 + public-write fence + run-loop 协作式停止，不保证已经发出的 provider 请求停止计费。
- Queue 与当前 latest-input-wins 语义跨数据库、服务、SSE 和 Desktop，必须分子任务落地并在父任务做完整回归。
- dark/system theme、全局 AppFrame/Sidebar 迁移、optional question skip、独立 wait-cancel、消息 branch/retry 和 coding-specific cards 延后到独立任务。

## 研究索引

- `research/dsh-ui-reuse-audit.md`：固定 revision、package 形态、复用矩阵、测试资产和决策后修正。
