# 稳定 Tutor 多轮运行生命周期与 DeepSeek Responses 适配

## Goal

修复 interactive conversation 复用有界 run 导致多轮输入预算/超时耗尽的问题；为 DeepSeek V4 Flash 按官方 Codex/Responses 协议补充受控适配、严格 JSON 决策与无敏感诊断。

## Confirmed Facts

- 当前普通对话会复用同一条尚未终态的 interactive run；该 run 固定有 5 分钟 deadline、3 次模型调用和 4 次迭代上限，因此连续追问会耗尽旧 run 的预算。
- conversation 已是持久化上下文容器；当前 context loader 按 conversation 读取最近消息，因此新的 bounded run 可以继续利用同一对话历史。
- DeepSeek `deepseek-v4-flash` 的当前官方 Codex 接入以 Responses API 为主要协议；现有 Aearn DeepSeek 分支仍固定走 Chat Completions。
- 当前安全边界不得持久化或向桌面端暴露 raw provider body、prompt、reasoning、诊断细节、凭据或未授权工具参数。
- 当前公开 API 仅提供单一 run 的 SSE/event replay；尚无按 conversation 读取历史消息、关联 run 和公开处理卡片的 history endpoint，因此跨刷新/重启恢复需要新增受控的 conversation history read 契约。
- Desktop 的 `TutorWorkspacePage` 虽支持注入 `initialConversationId`，但 `App.tsx` 当前始终传入 `null`，且没有 conversation 列表或历史会话选择入口；要让用户实际重新打开同一 conversation，需要新增受控的会话发现/选择体验。
- 当前 Desktop 的首次发送先独立调用 `createTutorConversation()`，再调用 conversation input API；这不是单一原子操作，前者成功而后者失败时可能留下空 conversation。新方案必须将“新对话”保持为本地 draft，并在首个非空输入时通过同一个幂等服务操作原子创建 conversation、首个 TurnRun 与输入。
- 产品决定：conversation 标题采用模型对该对话生成的简短摘要命名，而非直接截取首条 learner 输入。系统在该 conversation 首次成功写入 learner-visible Tutor 回复时，使用同一次受控模型决策中可验证的 title 输出候选生成标题；标题经安全清洗、规范化与截断后最多保留 48 个可见字符，并仅在尚未命名时持久化一次，之后不自动更新。若候选缺失或不合格，则保持安全占位标题“新对话”，仅在后续正常 Tutor 决策中且标题仍为空时随该次决策重试；不得为命名单独调用模型或退回为直接暴露用户原文。不得使用或持久化 raw prompt、reasoning、provider raw response、工具参数或诊断。
- 产品决定：当一个 foreground Tutor run 正在处理时，新的普通用户消息默认取代该轮；旧轮只可在安全边界停止，之后不得继续输出 learner-visible 回复或提交 capability/effect。

## Requirements

### R1. Conversation 与普通 TurnRun 分离

- `TutorConversation` 必须长期存活，保存跨桌面重启可继续使用的对话历史和关联学习状态。
- 每条普通 learner 输入必须创建一个新的、具有独立 deadline、模型调用预算、迭代预算和 SSE 生命周期的 interactive TurnRun。
- 普通追问不得消耗此前普通 TurnRun 的模型调用或迭代预算。

### R2. Latest-input-wins foreground 语义

- 每个 conversation 同一时刻最多有一条 foreground TurnRun。
- 当新的普通输入到达且旧 foreground TurnRun 尚未安全结束时，系统必须请求旧轮停止，并优先安排最新输入对应的新 TurnRun。
- 旧轮一旦被取代，不得在后续安全边界持久化 learner-visible public message、capability dispatch 或 effect commit。
- 原始用户输入、run 状态转换和结果必须保持用户范围、顺序、幂等性与审计边界。

### R3. 显式 continuation 与普通追问区分

- 普通聊天输入通过 conversation 路径创建新的 TurnRun。
- 仅当 run 处于明确的审批、外部 capability 结果或其他受控 checkpoint 时，才允许通过 run 级 continuation 恢复同一条 run。
- 客户端必须能基于公开状态区分“本轮已结束、可以继续聊天”和“本轮等待指定 continuation”。

### R4. DeepSeek V4 Flash Responses 适配

- 对已声明支持的 `deepseek-v4-flash` 使用受控的 Responses API 请求与最终输出解析路径。
- 对不支持该协议的已配置模型保留固定的兼容协议路径；不得在错误时跨 provider 或跨 model fallback。
- Tutor 决策必须继续使用严格 JSON 契约、完整 canonical JSON 示例、同模型有界 repair 和 Pydantic allowlist 校验。
- 适配器只可读取文档化的最终可见文本字段；不得把 reasoning 作为 answer、日志、持久化记录或前端输出。

### R5. 安全可观测性

- 为 provider 失败和协议形状记录可关联 `run_id`、`input_revision`、协议模式与安全诊断码的最小化诊断。
- 诊断不得包含原始 response、reasoning、prompt、headers、路径、命令、密钥或其他敏感内容。

### R6. DeepSeek 风格的公开“正在思考”交互

- 每条 foreground TurnRun 在 conversation 历史中拥有一张与其 Tutor 回复关联的、跨页面刷新、桌面重启和重新打开同一 conversation 后仍可恢复的公开处理卡片；运行中显示“正在思考”，完成后保留并显示“已处理 <安全计算的耗时>”。
- 完成或被最新输入取代的 TurnRun 必须持久化一份可重建的公开处理记录：关联的 run、可见 Tutor 回复、受控公开执行摘要、安全状态/工具活动投影、终态/取代状态及安全计算的耗时。该记录必须具有用户和 conversation 范围，支持幂等重放与按历史顺序查询。
- 新增受控 conversation-history read 契约：首次按时间线降序读取最近 40 条公开历史项，Desktop 按正序渲染；存在更早记录时可通过不透明 cursor 请求更早的 40 条并前置到时间线。客户端时间戳、本地缓存和原始 run event 不得作为分页或历史权威。
- 持久化记录只保存 allowlisted 的公开摘要和安全投影；不得把 raw trace、provider body、reasoning、prompt、诊断、工具参数、路径、命令或凭据作为历史卡片内容写入数据库。
- 兼容旧版历史：在本版本创建公开处理记录之前已经存在的 learner/Tutor 消息必须正常显示，但不得根据消息、run、trace 或时间戳伪造处理卡片或处理耗时；仅新版本创建的 TurnRun 产生可恢复的公开处理卡片。
- 卡片视觉必须采用用户提供的 DeepSeek 网页端参考的**紧凑行内 disclosure**，而不是当前大面积绿色三步面板：一行状态文本、轻量动态点或 spinner、处理耗时和可操作的下拉箭头；展开内容位于其下方，以细分割线与正文区分，不使用渐变、厚边框、阴影或独立 dashboard-card 外观。
- 用户点击整行状态或箭头后可展开/收起“公开处理过程”；默认折叠。展开内容仅由公开 run status、已确认 input revision 与安全 SSE status 派生。
- 展开内容由每轮受控的公开执行摘要与服务器生成的安全状态/工具活动投影构成：例如“已接收你的问题”“已整理最近的对话与学习目标”“已查阅已授权的学习资料”“已核对当前学习计划”“已完成一次受控学习建议生成”。运行中可更新当前步骤，完成后冻结为本轮可见处理摘要。
- 公开执行摘要只能从 allowlisted 的状态、类别、结果和受控的 learner-facing 摘要字段生成；不得由前端猜测，也不得直接复制 raw trace。
- 展开内容不得声称是或包含模型原始思维链、`reasoning_content`、provider response、prompt、诊断、工具参数或其他内部文本；视觉仿照 DeepSeek，但文本必须明确为“公开处理过程”。
- 当最新输入取代旧 foreground TurnRun 时，旧卡片必须停止动态运行态并显示安全的“已根据你的新消息更新本轮处理”结果；新 TurnRun 显示自己的“正在思考”卡片。
- 折叠/展开控制必须可键盘操作、具有可读标签、尊重 reduced-motion，并不得破坏时间线局部滚动或 Composer 可见性。

### R7. Conversation 导航、延迟创建与重新打开

- Tutor 路由下的左侧栏必须提供一个主操作“新对话”、最近对话列表和“查看全部”入口；不在 cutover 或 welcome 路由显示或操作 learner conversation。
- 点击“新对话”只切换 Desktop 到本地空白 draft：关闭当前页面的本地 SSE 订阅、清空该草稿时间线与 Composer 上下文，但不得立即写入 conversation、run、消息或列表项。
- 在本地 draft 中首次提交非空普通输入时，服务端必须通过单一幂等的原子创建操作创建 learner-visible interactive conversation、首个 TurnRun 与首条 learner 输入；成功响应返回同一组 `conversation_id`、`run_id` 与可订阅的公开状态。创建任一部分失败、请求取消或重试不得遗留没有可见消息的空 conversation。相同 idempotency replay 必须返回同一 conversation/run，而不是创建重复记录。
- 最近对话列表只返回当前用户范围内的 learner-visible interactive conversations，按最后一条公开 learner/Tutor/process 活动的服务端顺序降序排列，最多显示 8 条；超过 8 条时才显示“查看全部”。
- 点击最近对话或查看全部中的项目后，Desktop 必须切换到该 `conversation_id`，取消旧页面的本地 SSE 订阅，读取新 conversation 的受控历史并只呈现其关联的当前/历史公开状态。
- “查看全部”使用轻量的可键盘操作列表/面板与 cursor 分页，不将全部对话或完整历史卡片塞入侧栏。
- conversation 标题必须由同一 conversation 的受控模型输出生成简短概述，而非直接截取首条 learner 输入。系统只在尚未命名的 conversation **首次成功写入 learner-visible Tutor 回复**时，从该次受控 Tutor 决策的可验证 `conversation_title` 候选生成并持久化一次；后续轮次不得自动改写既有标题。候选缺失或未通过校验时，侧栏保持安全占位标题“新对话”，并仅在后续正常 Tutor 决策中、且标题仍为空时随该次决策重试；不得为命名单独调用模型或退回为直接展示用户原文。候选标题必须经过服务端 Pydantic allowlist 校验、安全清洗、规范化与截断后最多保留 48 个可见字符；标题、时间和预览只能通过服务端安全投影提供。不得直接透传原始输入，也不得将 raw prompt、reasoning、provider raw response、工具参数或诊断作为标题或预览。

## Acceptance Criteria

- [ ] 在同一个 conversation 内连续发送至少 10 条普通消息时，每条消息对应不同 `run_id`，并保留同一 `conversation_id`。
- [ ] 第 4 条及之后的普通输入不会因前几轮的 `max_model_calls`、`max_iterations` 或旧 deadline 而进入 `budget_exhausted`。
- [ ] 等待超过旧的 5 分钟窗口后继续发言会创建新 TurnRun，且可基于同一 conversation 历史正常处理。
- [ ] 新输入在旧 foreground run 运行期间到达时，旧 run 在下一安全边界停止；它不能再写入 public message、能力调用或 effect 提交；最新输入对应的新 run 被优先处理。
- [ ] 同一输入的 idempotency 重放不会重复创建 run、消息、效果或 SSE 事件。
- [ ] 前端只订阅并展示当前 TurnRun 的公开 SSE 状态；终态、取代和明确 continuation 的交互可被安全区分。
- [ ] 重新加载页面、重启桌面端或重新打开同一 conversation 后，按历史顺序恢复 learner 输入、关联的公开处理卡片与 Tutor 回复；已完成卡片默认收起，且不含原始 reasoning 或其他内部文本。
- [ ] 本版本创建公开处理记录之前的旧版历史消息正常显示但不伪造处理卡片、处理耗时或执行步骤；本版本后新创建的 TurnRun 才显示可恢复的公开处理卡片。
- [ ] 点击“新对话”只进入本地 draft，不创建数据库 conversation、run、消息或侧栏列表项；首次非空提交通过一个幂等原子操作创建 conversation、首个 run 与首条输入，失败、取消或重放不会留下空 conversation 或重复记录。
- [ ] 首次创建请求的同一 idempotency replay 返回相同的 `conversation_id` 和 `run_id`；仅在该 conversation 首次成功写入 learner-visible Tutor 回复时，从同一次受控模型决策的 `conversation_title` 候选生成一次简短概述，并经服务端 allowlist 校验、安全清洗与截断至最多 48 个可见字符后持久化。后续轮次不得自动改写该标题；候选缺失或不合格时保留“新对话”占位，并只在后续正常 Tutor 决策且标题仍为空时重试。侧栏不得直接透传原始输入、raw prompt、reasoning 或 provider raw response。
- [ ] Tutor 路由的侧栏显示“新对话”、最多 8 条按服务端最后活动排序的最近对话，以及超过 8 条时的“查看全部”；只返回当前用户的 learner-visible interactive conversations。
- [ ] 选择任一历史 conversation 后，旧 SSE 订阅关闭，Desktop 用受控 history endpoint 恢复对应对话；“查看全部”和“加载更早记录”均使用不透明 cursor 分页。
- [ ] 公开非终态的 foreground TurnRun 在时间线底部显示默认折叠的“正在思考”卡片；用户可点击或通过键盘展开/收起 DeepSeek 风格的公开处理摘要，且摘要不含原始 reasoning 或其他内部文本。
- [ ] 最新输入取代旧 foreground run 时，旧卡片在安全边界停止为运行中状态，新 TurnRun 独立显示自己的“正在思考”卡片；布局保持时间线局部滚动和 Composer 可见。
- [ ] `deepseek-v4-flash` 的官方 Responses 完成形状中含最终 `output_text` 时，可解析为严格 TutorDecision。
- [ ] 仅含 reasoning、无最终文本的 Responses 响应被安全归类为内容缺失，不展示、不持久化 reasoning。
- [ ] 非 JSON、额外字段、无效枚举、超时、限流和不完整 Responses 响应都映射为稳定的安全结果；不会发生跨 provider/model fallback。
- [ ] 相关后端测试、桌面 typecheck、规格一致性检查与 `git diff --check` 通过。

## Child Task Map

1. `08-02-deepseek-responses-decision-contract`：为精确支持的 `deepseek-v4-flash` 实现官方 Responses 分流、最终可见文本解析、严格 JSON 决策、模型简述标题候选、受控 continuation 和安全诊断。该 child 不改变普通 conversation 的 TurnRun 生命周期。
2. `08-02-tutor-conversation-turnrun-history`：在 Child 1 的决策契约完成后，实现每条普通消息独立 TurnRun、latest-input-wins、原子首发、标题持久化、公开处理过程、history/list API 与 Desktop 会话导航。

父任务只维护跨子项的需求、集成验收和文档一致性；不直接作为业务代码实现目标。

## Out of Scope

- 不把普通 Tutor 对话改成以桌面窗口生命周期为依据的无限运行。
- 不向客户端暴露模型 raw Chain-of-Thought、reasoning_content、provider diagnostics 或 prompt。
- 本任务不引入 Temporal、任意 agent 工具权限、无界后台执行或跨 provider/model 自动 fallback。
- 本期不支持用户手动重命名 conversation；模型简述标题一旦成功生成即固定，不新增标题编辑 API、并发合并、幂等重放或审计分支。
- 不为旧版消息、旧 run、trace 或时间戳逆向生成或伪造公开处理过程卡、步骤或处理耗时。

## Open Questions

无阻塞的产品开放问题。Child 1 开始实现前仍必须按当日官方文档核验 `deepseek-v4-flash` 的 Responses 请求字段、SSE 事件与终态字段；这属于协议验证门，不重新打开已经确认的产品范围。
