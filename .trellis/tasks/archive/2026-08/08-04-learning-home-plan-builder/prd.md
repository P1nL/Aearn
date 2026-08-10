# 学习首页与对话式计划制定

## 目标

将 verified Tutor 的主入口从 conversation-first 导航转为 LearningTrack 首页，并提供居中的计划制定对话，使用户能创建、审阅、调整并确认一条结构化学习主线。

## 依赖

- `08-04-learning-track-plan-mastery-domain` 已完成并冻结 track/plan/API contract。
- `08-04-tutor-latest-input-teaching-relevance` 已完成，确保计划制定对话以当前输入为权威。

## 已确认事实

1. `GET /api/learning-tracks` 已能返回服务端权威的进度、当前节点、`review_due_count`、`execution_tier` 与 learner-safe disclosure；前端不需要也不得重算这些字段。
2. `POST /api/learning-tracks` 已能在一个事务内创建 track、active plan revision、路线结构、初始 progress，并将可选 conversation 绑定为 `learning_track` scope。
3. Tutor API 已支持 `plan_drafting` conversation/run scope；普通输入继续创建 fresh finite `TurnRun`，显式 continuation 语义不变。
4. 当前生产交互式 dispatcher 对 Skill/capability/effect 默认拒绝，现有 catalog 只有 `grounding.retrieve` capability；本 child 必须只为合法 `plan_drafting` run 开放精确能力。
5. 当前 Desktop verified 后直接进入 conversation-first `TutorWorkspacePage`，尚无 LearningTrack 首页、planning session、草案组件或 track 内部导航状态。
6. 当前前端没有独立组件测试 runner；本 child 的 UI 完成门仅使用 `http://127.0.0.1:1420` 网页端浏览器验证，覆盖真实渲染、交互、控制台、响应式与可访问性并记录精确证据，不把 Desktop build/typecheck 作为默认前端校验。
7. 受保护原型 `docs/design/learning-agent-claude-desktop-framework.html` 只能作为视觉参考，不恢复旧 onboarding、旧 Graph 路由或旧学习表。

## 需求

### R1 — LearningTrack 首页

- verified 用户进入产品后首先看到居中的三列响应式卡片网格。
- 每张卡片对应一个 LearningTrack，显示语言、目标、当前阶段/知识点、路线进度、最近学习时间、到期复习数量和真实 `execution_tier`。
- 卡片主操作为继续学习；存在到期复习时显示开始复习次操作。
- 网格最后一张固定为“添加学习语言/学习主线”，空状态仍保留该入口；点击后直接创建或恢复 planning session，不显示独立语言选择器。
- 前端不根据本地缓存自行计算掌握度、到期数、路线解锁或运行能力。
- 本 child 只负责把继续学习/开始复习动作转换成稳定的内部导航 intent；尚未交付的 Lesson/Review 页面必须显示真实的未就绪状态，不得伪造内容或执行结果。

### R2 — 对话式计划制定

- 添加入口直接进入 planning view：历史加载完成且尚无消息/run 的未激活状态只在可用区域中央显示一个圆角 Composer；首条消息被接受后才切换为 GPT 式消息流和底部 Composer。不得恢复旧 onboarding、语言选择页面、空状态说明/快捷建议、外层对话卡片或 Graph 路由。
- 语言选择与基础、目标、时间投入、经验和教学偏好全部由 Tutor 在对话中收集；每次只追问确实缺失的高价值信息。
- planning conversation 使用 server-persisted planning session、fresh finite `TurnRun` 和明确 `plan_drafting` task kind。
- 模型通过精确、类型化、默认拒绝的 `learning.plan.draft` capability 生成计划草案，不把聊天 Markdown 直接当正式计划。
- 同一用户同时最多有一条未完成 planning session；用户可以刷新恢复、显式取消后重开，或继续当前 session。

### R3 — 可审阅计划组件

- 进入 planning 页面时立即显示计划窗口展开/收起按钮，并默认展开与视口右缘保留明显留白、不挤占对话主列的独立浮动窗口；服务端尚未产出 `current_draft` 时，窗口只显示一个无业务含义的 emoji，不展示伪造计划字段。模型通过类型化 capability 产出 `current_draft` 后，同一窗口原位替换为计划路线，显示模块、核心知识点、预计节奏、权威来源摘要和运行能力边界。窗口四角必须完整圆角。
- 用户可以通过对话要求调整；新草案是 append-only 独立版本，旧草案不可确认。
- 只有用户明确点击确认后，服务端才原子创建 LearningTrack、首个 active plan revision、路线进度和 scoped Conversation。
- 确认请求必须携带当前草案版本与 content hash；重复同请求幂等返回同一 track，陈旧版本返回稳定 409。
- provider/草案质量门失败时保留 planning session，并显示可恢复错误，不使用隐藏模板冒充动态结果。

### R4 — 语言范围

- 核心 MVP 可选择 Python、JavaScript、TypeScript 和 SQL。
- Java 与 HTML/CSS 可显示为扩展验证能力；Go、C#、Rust、C++ 按服务端 selectability 与 `execution_tier` 清晰降级。
- 语言是否可选择、是否可生成教学内容、是否可执行和是否仅静态教学是不同字段，不能合并成一个模糊的“支持”。
- 计划草案的来源摘要只能来自现有受信 registry；模型不能提供任意 URL、source ID、执行目标、路径、命令或镜像。

### R5 — 导航与恢复

- planning session、conversation 绑定、草案版本、当前草案指针和确认状态由服务端持久化，刷新后可恢复。
- 已确认后返回 LearningTrack 首页并突出新卡片，或按用户动作进入后续学习页 intent。
- Desktop 不再提供独立 general conversation / 对话历史页面或导航入口；既有服务端 conversation 数据与 API 仅为兼容和 planning conversation 复用而保留。
- App 顶层 `loading | welcome | cutover | tutor` 状态机与 server-authoritative cutover gate 不变；首页/规划页是 verified `tutor` shell 内部视图。

### R6 — 隐私、可观测性与失败语义

- planning session/draft 可以保存确认所需的结构化目标与计划，但不得复制 raw prompt/history、provider body、reasoning、credential 或 transport body。
- 通用 capability invocation 只保存 request/result hash 和安全元数据；完整草案只进入 user-scoped learning draft 表与其安全 API 投影。
- capability、provider、quality gate、stale confirmation 和 idempotency conflict 使用稳定 learner-safe error code；日志与 release evidence 不包含用户原始对话或草案正文。
- 默认验证使用 fake provider、固定 clock 和本地 PostgreSQL fixture；真实 provider smoke 不属于本 child 的必需验收，也不因本地通过而获得发布批准。

## 验收标准

- [ ] 首页在宽屏显示三列卡片，窄屏响应式降列，添加卡始终位于网格末尾且点击后直接进入 planning conversation，不渲染语言选择器。
- [ ] 卡片展示服务端权威 progress、review due 与 execution tier，不使用前端推断。
- [ ] planning session 可创建、恢复和取消；每条普通 planning 输入创建 fresh finite TurnRun 且 scope/task kind 不漂移。
- [ ] `learning.plan.draft` 仅对当前用户的 active `plan_drafting` run 可用，精确 Skill、policy、budget、lease 和 revision gate 全部生效。
- [ ] planning 页面无应用左侧栏和对话 hero/外层卡片；未激活状态只有屏幕中央的圆角 Composer，不显示空状态文案、建议按钮或底部提示；首条消息/run 出现后才切换为 Tutor 左侧正文、学习者右侧气泡和底部 Composer 的 GPT 式布局。收集阶段保持单列，进入页面即显示右缘展开/收起按钮和默认展开的四角圆角独立浮动窗口；`current_draft` 为空时只显示 emoji，服务端返回草案后原位替换为紧凑计划路线。窗口必须与视口右缘保留明显留白，不得表现为贴边侧栏、挤压居中对话区或占满整个右侧，并能修订和确认 append-only 类型化计划。
- [ ] 确认操作幂等且原子创建 track、active revision、route progress 与 scoped conversation。
- [ ] provider/质量门失败不会创建半成品 track，也不会静默使用模板；刷新后仍能继续原 session。
- [ ] 核心、扩展和降级语言展示与父任务矩阵及服务端 registry/tier 一致。
- [ ] Desktop 不再渲染 general conversation / 对话历史页面或入口；planning conversation 的 history/SSE 与 current-input contract 不回归，既有服务端数据不删除。
- [ ] capability receipt、trace、API、SSE、日志和文档证据不包含 raw prompt/history、provider body、reasoning、credential 或任意执行目标。
- [ ] 网页端浏览器验证、API/DB focused tests、完整相关回归、可访问性和响应式 smoke、Ruff、Mypy、Trellis validate 与 diff hygiene 通过；除非用户明确要求，不运行 Desktop build/typecheck。

## 范围外

- LessonDocument 正文、练习 Gate、复习 session、模型代码审核题和完整三栏学习工作区。
- 恢复旧 onboarding/plan 页面、旧 Graph SSE 或旧 `learning_*` API。
- 在前端生成计划、掌握度、到期数量、路线解锁或执行 tier。
- 扩大全局 Tutor capability payload 上限，或把完整草案复制进通用 trace/event/capability receipt。
- 使用隐藏静态模板冒充 provider 生成结果。
- 公开启用没有 reviewed image lock 的执行能力。
- 未经单独批准的真实 provider smoke、commit、push、deploy 或生产数据迁移。
