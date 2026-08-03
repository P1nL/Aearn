# Tutor Conversation TurnRun 生命周期与公开历史体验

## Goal

将普通 Tutor 对话从“复用未终态 interactive run”的模式改为“长期 conversation + 每条普通消息独立、有限的 TurnRun”。实现 latest-input-wins、首条消息的原子创建、跨刷新恢复的安全公开处理过程，以及 Desktop 会话导航。该任务依赖 DeepSeek/decision contract child 先提供经过验证的 `conversation_title` 与 explicit continuation 语义。

## Dependencies

- 依赖父任务 `08-02-tutor-run-lifecycle-deepseek-responses` 的产品和安全边界。
- 必须等待 `08-02-deepseek-responses-decision-contract` 通过 review/archive 后才启动，因为本 child 需要消费它的严格 `conversation_title` 与 `continuation_kind` contract。

## Confirmed Facts

- 当前 `find_or_create_interactive_run()` 会在 conversation row lock 下复用 non-terminal interactive run；普通新输入随即写入旧 run，造成旧 deadline、模型调用预算和迭代预算被复用。
- 当前 run loop 在 provider 返回后会继续 decision/capability/effect/terminal message 路径；现有 cancellation check 主要位于部分 unsafe boundary，不能单独保证 latest-input-wins 的 post-provider 竞态安全。
- 当前 Desktop 首次发送先调用 `createTutorConversation()`，再发送 input；任一后续调用失败会留下空 conversation 风险。
- 当前 `POST /api/tutor/runs/{run_id}/inputs` 仍可作为普通追问路径；本任务必须将它限制为明确 continuation。
- 当前 public SSE 只重放单一 run 的安全 event；没有 conversation history、列表、cursor 或持久化 process-card read contract。
- 当前前端“正在思考”由当前 run 临时派生，完成后消失，且视觉是大面积三步面板；它不能跨刷新/重启恢复，也不是用户要求的紧凑 disclosure。
- 当前 `App.tsx` 不保存或传递可选择的 conversation；`TutorWorkspacePage` 也不负责服务端 history hydration。
- 用户已确认：公开卡片只能显示 allowlisted 的“公开处理过程”，不能展示 raw CoT、provider reasoning、tool trace、prompt、参数、路径、命令、SQL、headers、diagnostic 或密钥。
- 用户已确认：标题来自同一次成功 Tutor decision 的模型简述，服务端校验后最多 48 个可见字符；成功后固定。**本期不支持手动重命名 conversation**，不得创建 rename API、UI 或由原始用户输入生成标题的 fallback。

## Requirements

### R1. 普通消息独立 TurnRun

- 每条普通 learner 输入都创建一个新的 interactive `TurnRun`，具有独立 deadline、模型调用预算、迭代预算、lease、SSE lifecycle 与安全诊断。
- 同一个 `TutorConversation` 保持长期存活并继续作为上下文/历史根；新 run 可读取该 conversation 的安全历史，但不得继承旧 run 的 budget/counter/deadline。
- 普通 Tutor 回复完成后，该 run 必须 terminal completed。只有持久化为 explicit, server-authorized continuation 的 run 才可以进入可继续输入的等待状态。
- `POST /runs/{run_id}/inputs` 必须验证 continuation kind；普通 completed/cancelled/superseded/normal-chat run 一律拒绝。

### R2. Latest-input-wins 与竞态安全

- 同一 conversation 同时最多一条 interactive foreground run。
- 新的普通输入到达时，服务端在同一 transaction 内安全标记旧 foreground run 为 superseded/cancelled，并创建新 run；新 run 是后续唯一 foreground run。
- 旧 run 在 provider 返回后、decision gate/capability/effect/terminal write 前均必须重新检查取消/取代状态。
- superseded run 不得写 learner-visible Tutor message、conversation title、capability invocation 或 effect commit；持久化层必须拒绝这种写入，即使 run loop 的检查发生竞态。
- 被取代的旧 run 的公开过程必须停止动态态并显示安全的“已根据你的新消息更新本轮处理”。

### R3. 原子首发、幂等与标题固定

- 点击“新对话”只建立本地 draft：不创建 database conversation、run、message 或侧栏项。
- draft 中首个非空普通输入必须在一个幂等、原子服务操作内创建 conversation、first run、learner input、初始 public-process projection；失败/取消/同 key 重放不得留下空 conversation 或重复写入。
- 同一 first-turn idempotency replay 返回同一 `conversation_id` 和 `run_id`。
- 在首次成功写入 learner-visible Tutor reply 时，只能从同次严格 decision 的安全 `conversation_title` 写入 conversation title；`UPDATE` 必须是 title-null guard，既有标题不得被任何后续普通 run 改写。
- 标题缺失或无效时，服务端投影为“新对话”；后续正常成功 decision 且 title 仍为空时可顺带尝试。不得单独为了命名调用模型，也不得从 learner 原文退回生成标题。
- 不支持任何手动重命名 API、mutation、键盘快捷键或编辑控件。

### R4. 安全公开处理过程与历史

- 为本版本新创建的 interactive run 持久化专用 public-process projection：只存 allowlisted 状态/步骤 key、工具类别投影、状态、关联公开 message、server timestamps 和 schema version。
- 运行时卡片显示“正在思考”；完成时保留“已处理 <server-safe duration>”；取代时显示安全取代结果。展开内容标题必须是“公开处理过程”。
- 过程步骤由服务端安全 projection 输出，例如“已接收你的问题”“已整理最近的对话与学习目标”“已查阅已授权的学习资料”“已完成一次受控学习建议生成”。前端不得猜测、拼接或从 raw SSE/trace 反推步骤。
- 新增 history endpoint：首次返回最近 40 条、服务端时间线倒序；Desktop 正序渲染。“加载更早记录”使用服务器签发的不透明 cursor，每次最多 40 条。
- 旧版历史 learner/Tutor messages 正常呈现，但不得伪造 process card、step 或 duration。

### R5. 会话列表、Desktop 选择和局部滚动

- Tutor route 侧栏提供“新对话”、最多 8 条按服务端 `last_public_activity_at` 倒序的最近会话；多于 8 条才显示“查看全部”。
- “查看全部”是可键盘操作的轻量面板，使用 cursor 分页；不把全部数据塞入侧栏。
- 选择历史 conversation 时先关闭旧 SSE，清空旧本地 timeline，读取服务端 history；只有服务器返回 active public foreground run 时才订阅其 SSE。
- process card 是紧凑行内 disclosure：整行和箭头可操作、默认折叠、`aria-expanded`/可读 label 完整、尊重 reduced motion。不得使用厚边框、渐变、大面积绿色三栏 dashboard 或伪造模型思考。
- conversation timeline 是局部滚动区域；composer 在桌面视图保持可见。`useTutorSSE` 保持 transport-only，不承担 history rebuild/navigation。

### R6. 文档、测试与数据隔离

- 新表/字段/index 均为 additive；不删除旧 Tutor 数据，不迁移或补造旧 process card。
- API/list/history/title/process read/write 均按 user + conversation scope enforced；cursor 不得跨用户或跨 conversation 使用。
- 测试使用 fake provider；不得因 UI/history test 产生真实 provider 调用。
- 同步 `docs/architecture/api-contract.md`、`docs/architecture/database-schema.md`、`docs/architecture/tutor-harness-runtime.md` 和 `docs/product/frontend-interaction-spec.md`。

## Acceptance Criteria

- [ ] 在同一 conversation 连续接受至少 10 条普通输入时，每条都获得不同 `run_id`，保留同一 `conversation_id`，且第 4 条之后不继承旧 budget/deadline。
- [ ] 新普通输入在旧 foreground run provider 调用期间到达时，旧 run 在返回后的安全边界被终止；不能再写 public message/title、dispatch capability 或 commit effect。
- [ ] 同一 conversation 永远不存在两条 active foreground interactive run；并发/idempotency 测试覆盖该 index/transaction 不变量。
- [ ] 首个 draft submit 的正常、失败和同 key replay 路径均不会留下空 conversation 或重复 run/message/process；成功 replay 返回相同 IDs。
- [ ] 普通 run 完成后不能通过 run-input 继续；只有 persisted explicit continuation 可接受 run-input。
- [ ] title 只从同次安全 decision 写入一次、最多 48 visible characters；之后固定；无手动 rename surface；无标题时只投影“新对话”，不显示原始 learner input。
- [ ] 刷新、桌面重启或重新选择 conversation 后，history 按顺序恢复新版本消息、process card 和 Tutor reply；legacy messages 显示但没有伪造 card/duration。
- [ ] 公开 process card 默认折叠、可键盘打开、仅含 server allowlisted 公开步骤；不含 CoT/reasoning/provider/trace/工具参数/诊断；取代卡片展示安全文案。
- [ ] 左侧最近 8 条、查看全部 cursor panel、history cursor、switch cleanup 和 active SSE selection 都有 backend/frontend test 覆盖。
- [ ] timeline 局部滚动和 composer visibility 在 desktop check/相关 UI test 中不回归。
- [ ] focused backend tests、`ruff`、`mypy`、`pnpm --dir .\aearn desktop:check` 和 `git diff --check` 通过。

## Out of Scope

- 不修改 DeepSeek Responses URL/payload/SSE parser 或 strict decision schema；这些属于 Child 1。
- 不支持手动 conversation rename 或直接用首条 learner 文本作为标题。
- 不暴露/持久化 raw reasoning/CoT/provider response/prompt/trace/tool parameters/diagnostics。
- 不将 ordinary run 改为桌面窗口生命周期的无限后台任务，不引入 Temporal 或跨 provider/model fallback。

## Open Questions

无阻塞产品问题。实现时以 Child 1 已归档的 typed decision contract 为唯一输入；若该 contract 未完成，不得通过临时自由字段或前端猜测绕开依赖。
