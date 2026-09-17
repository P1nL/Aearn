<a id="tutor-harness-runtime-architecture"></a>

# Tutor Harness 运行时架构

**状态：** 当前契约基线为 2026-09-16；2026-09-17 对照本地工作树整理中文并核对版本。
**权威来源：** 当前路由注册、`aearn/services/api/app`、`aearn/apps/desktop`、`aearn/services/worker`、`services/learning/`、按清单排序的 `app/db/schema/` 片段及其测试。过渡文档仅是历史迁移证据，不是日常运行时规范。
**阅读边界：** 带日期的章节保留对应日期的实现与验证证据；旧版本只作历史/兼容说明，现行版本以本地源码和文末当前契约为准。本次只做文档与源码静态核查，未重新运行模型、数据库、执行器或发布验收。

<a id="1-product-boundary"></a>

## 1. 产品边界

Aearn 是本地、受控的 Tutor 工作空间。学习者通过本地身份和服务端权威切换回执进入；现行运行时不是通向旧产品的兼容桥。

```text
local identity
  -> GET /api/harness/cutover
  -> verified receipt
  -> LearningTrack, Lesson/Gate/Review routes and Tutor conversation/activity/inbox/memory/preferences
```

切换状态缺失、待处理、阻断、失败或格式错误时，Tutor 与已移除的旧运行时均不可进入。客户端不能选择删除范围、绕过回执、恢复保存的旧计划 ID，或重建已删除的旧学习历史。

<a id="2-runtime-composition"></a>

## 2. 运行时组成

| 层次 | 责任模块 | 契约 |
| --- | --- | --- |
| 公共适配层 | `routes/tutor.py`、`services/tutor/public_api.py` | 校验用户作用域与幂等性，公开学习者安全投影，不承担 Graph/router 兼容工作。 |
| 学习领域 | `routes/learning_tracks.py`、`routes/exercise_gates.py`、`routes/learning_track_reviews.py`、`services/learning/` | 负责学习轨道域计划、进度/掌握度、不可变 LessonDocument/来源快照/学习分配、练习 Gate/Attempt/模块诊断权威、间隔复习日程/会话权威、执行等级投影、不可变作用域快照与只读 Tutor 上下文适配器。 |
| 交互分发 | `services/tutor/interactive_worker.py`、`services/tutor/interactive.py` | 提交后认领 PostgreSQL 持久任务，调用既有有界 Harness 分发器；唤醒/worker 失败映射为重试或 dead 状态，不在输入已接受响应中泄露提供方错误。 |
| Harness | `agents/harness/`、`services/tutor/run_loop.py` | 有界运行循环、租约所有权、输入修订重载、精确 Skill 选择、能力/副作用 Gate、检查点生命周期与类型化终态结果。 |
| 持久状态 | `services/tutor/persistence/`、`conversation_contracts.py`、`learner_state.py`、`proactive_repository.py` | PostgreSQL 负责协议版本、用户/运行/对话作用域、运行内与对话全局有序事件、快照、幂等性、持久分发租约、CAS 副作用、脱敏投影和后台队列。 |
| Worker | `services/worker/aearn_worker/worker_app.py` | 为 `health.ping`、高优先级 `tutor.interactive.dispatch/reconcile`、主动扫描/排空和低优先级整理提供薄 Celery 包装。Celery 仅负责唤醒/周期调度，不是交互权威。 |
| 桌面端 | `apps/desktop/src/` | 按 `loading -> welcome -> cutover -> tutor` 启动，只呈现服务端决策，不能覆盖。 |

<a id="3-interactive-tutor-conversation-and-finite-turnrun"></a>

## 3. 交互式 Tutor 对话与有限 TurnRun

学习者可见的 `TutorConversation` 是长期历史/上下文作用域；普通学习者消息对应一个**全新、有限**的交互 `TurnRun`：

```text
local draft
  -> POST /conversations/first-turn
  -> conversation + first TurnRun + learner input + public process (one transaction)

existing conversation + ordinary learner message
  -> POST /conversations/{conversation_id}/inputs
  -> idle: fresh TurnRun
  -> active/waiting/paused: pending FIFO Queue item

explicit control
  -> Steer: same active turn + next input revision
  -> Interrupt: public interrupted + optional Queue pause
  -> resume/execute: fresh claimed TurnRun
  -> Retry: fresh retry lineage

typed blocking request
  -> source TurnRun completes with awaiting_* reason
  -> POST /conversations/{conversation_id}/requests/{item_id}/responses
  -> fresh answer TurnRun + fresh dispatch job
```

1. 选择“新对话”只创建桌面本地草稿。首次非空提交调用 `POST /api/tutor/conversations/first-turn`，原子创建可见对话、新运行、学习者消息/输入事件和 `input_received` 公共过程投影。API 幂等性负责重放；回滚不得留下空对话或重复分发。
2. `POST /api/tutor/conversations/{conversation_id}/inputs` 不隐式替换或恢复存活运行。在对话锁下，仅空闲时创建新轮；否则追加带不可变输入元数据的待处理 `tutor_queued_inputs`（最多 10 项），递增 `control_version`。FIFO 认领原子创建学习者消息、输入事件、过程、新策略和分发任务。只有显式 `Steer` 可通过推进输入修订把一个待处理项认领到当前运行。
3. `thread_turn_v2` 续接决策不重开来源运行：原子创建一个 `tutor_interaction_requests` 行/条目，将来源轮以 `awaiting_user | awaiting_approval | awaiting_authority` 原因完成，释放租约并递增对话控制版本。学习者响应或已验证权威回执通过 CAS 解决该精确请求，创建新运行，带全新策略截止时间、归零计数器、修订 1、`response_to_request_id`、新过程和单行新分发任务。历史 `/runs/{run_id}/inputs` 曾仅供旧协议使用；当前全局切换后已为永久 410 墓碑接口（见 2026-08-14 章节）。
4. 学习者原文仅存于 `tutor_messages`；正常接受输入时追加有序安全事件并更新 `last_public_activity_at`。对话列表/历史读取不从事件、跟踪、提供方输出或诊断重建原文。
5. 每个全新、学习者可见轮明确使用 `thread_turn_v2`；历史、主动和内部运行保留 `legacy_v1`。接受事务只创建或重置一行 `tutor_interactive_dispatch_jobs`，并随所属变更追加初始对话事件。提交后 FastAPI 尽力发送 Celery 唤醒并进行本地低延迟认领。重复任务必须赢得 PostgreSQL 任务租约才能分发；Celery beat 的 `tutor.interactive.reconcile` 恢复过期租约和丢失唤醒。
6. 已认领分发器获取既有运行租约并执行有限 Harness 循环，提供方调用不处于隐式 PostgreSQL 事务内。提供方等待期间普通 Send 可排队而不使当前轮失效；显式 Steer 或 Interrupt 改变修订/取消权威。每次提供方返回后，以及决策、能力、副作用和终态写入前，循环立即刷新取消、租约和修订。陈旧修订/已中断运行不能发布消息/标题或提交能力/副作用。仅正常完成任务后由 worker 执行 FIFO 排空；失败、中断、待请求响应路径改为暂停。
7. 每次交互上下文加载从快照用户/运行/对话作用域内的精确 `tutor_run_input_events(run_id, input_revision).message_id` 证据解析权威学习者输入。Harness 将其与可选历史分开，在可选区段前预留有界 token 成本；最低安全表示仍放不下时不调用提供方。可选历史排除该精确消息，按稳定 `created_at, id` 保留最新有界后缀，再按时间正序展示。主动运行明确不需要学习者输入，不虚构聊天文本。
8. `GET /api/tutor/runs/{run_id}/events` 保留为使用非负 `Last-Event-ID` 的运行内增量兼容传输。`GET /api/tutor/conversations/{conversation_id}/snapshot` 的基础 Runtime 投影为 `tutor_conversation_snapshot_v3`；Artifact 状态按需升级 v4，有分支历史时增量升级 v5，桌面保留旧版读取兼容（不是一律返回 v3）。`/events` 重放基础 `tutor_conversation_event_v2` 与 Artifact 扩展 `tutor_conversation_event_v3`，使用签名、用户/对话域不透明游标 v2。`turn_output` 可携带 Harness 兼容 `tutor_public_thinking_stream_v1` 或仅 Codex 的 `tutor_runtime_item_stream_v1`；其他事件仍使快照失效。两种流均不调用提供方，心跳注释不推进持久序列。
9. 创建对话、首轮和普通轮请求可携带增量结构化 `learning_scope`。每个新运行写入一个不可变 `tutor_run_learning_scopes` 快照，包含 `scope_kind`、`task_kind`、可选轨道和知识键。缺省仍为 `general/general_tutor`，不凭自然语言给旧对话分类。类型化响应/权威轮将同一不可变对话作用域快照到新运行；响应契约没有作用域覆盖字段。

<a id="learningtrack-context-seam"></a>

### LearningTrack 上下文接口

LearningTrack 包提供只读 `TutorLearningContextAdapter`，将运行快照转换为有界来源：作用域/任务类型、轨道语言/目标/活动计划、当前节点进度/掌握度摘要。`PostgresTutorLearningContextLoader` 在上下文选择前组合该适配器与计划事实投影器；原始计划 JSON 和掌握度证据正文不进入适配器。

<a id="authoritative-planning-facts-and-snapshot-reconstruction"></a>

### 权威计划事实与快照重建

`plan_drafting` 学习者输入可贡献服务端规范化的类型化事实：`language_id`、`goal_text`、`target_level`、`weekly_minutes`、`experience_level`、`teaching_preferences`、`pace_constraints`。每个确认事实仅追加，并保留精确学习者消息/运行/输入修订证据；纠正追加后继，不改写旧值。问题生命周期也使用稳定字段键构成仅追加前驱链，当前状态沿真实叶子解析，不能按时间戳或 UUID 排序推测，因为 PostgreSQL `now()` 在事务内稳定。

每次提供方请求前，生产加载器与上下文评估均调用 `build_authoritative_context_snapshot()`，绑定运行/输入修订、计划会话、当前事实修订/指纹、必需事实来源、问题状态、确定性快照哈希和已确认问题重问计数。恢复与重放从持久权威重建同一快照，不从自由历史或异步摘要恢复事实。

`required_facts` 是不可驱逐上下文区段，紧随系统/策略和独立固定的 `current_input`；优先于可选历史、活动计划、摘要、记忆、活动、能力 schema 预留。全部确认事实若无法完整放入，以 `TUTOR_REQUIRED_FACTS_UNREPRESENTABLE` 默认拒绝，不静默丢弃字段。

近期历史先固定标记为 `confirmed_fact_source`、`correction` 或 `unresolved_question` 的来源，再按新近程度填充剩余硬条目上限。确认事实已是其来源的结构化替代；未解决或重开且没有替代事实的回答加入 `compaction_plan.protected_message_ids`，阻止退役并递增 `summary_blocked_by_unprojected_fact`。结构化摘要仅维持连续性，不覆盖类型化事实权威。

提供方续接意图是精确五分支枚举：`clarification` 只处理一处普通歧义；`planning_input` 只补齐一项计划事实；`approval` 只请求明确授权；`capability_result` 与 `external_result` 只等待已声明受信结果。只有 `planning_input` 必须携带白名单 `question_key`；提供方不能定义选项、schema、提案或权威回执。服务端 `tutor_planning_questions_v1` 为七字段构造不可变呈现，复用 `normalize_planning_fact()` 值契约。计划决策 Gate 记录 `asked`，拒绝无活动会话或重问已确认字段。类型化请求公开载荷不含提供方正文、原始推理、能力参数、签发方密钥或原始权威结果。每个请求在同一事务持久化一条 `tutor_messages` 正式回答和一个 elicitation/approval 条目；时间线先显示正式回答，再显示输入/审批栏，请求卡片不能替代正式回答。

学习者请求响应为闭合联合，以请求条目 ID、预期版本、响应哈希执行 CAS；审批还须匹配精确提案标识。权威回执没有学习者路由，由内部服务校验签发者、主体、作用域、请求哈希、结果哈希及回执标识；验证有歧义则保持待处理。新响应上下文固定包含来源请求标识、安全描述、学习者回答或已验证回执摘要及 `in_reply_to_item_id`，不凭自由文本猜测批准或权威成功。

<a id="queue-与显式-conversation-control2026-08-14"></a>

### 队列与显式对话控制（2026-08-14）

队列权威在 PostgreSQL，而非桌面本地数组或 Celery。所有 edit/delete/reorder/Steer/Interrupt/resume/execute/Retry 先锁对话并校验预期 `control_version`；条目变更另校验条目版本。待处理请求阻断所有执行型控制，但普通 Send 仍可排队。Interrupt 将当前轮投影为 `interrupted`，仍有待处理项时设置 `queue_paused`；失败完成使用 reason=`failed`，请求使用 reason=`pending_request`。普通 Send 不清除暂停。

`resume` 仅在空闲且无待处理请求时解除暂停并按 FIFO 认领；`execute` 可原子中断当前轮再认领指定项；`Steer` 不创建新运行，只将指定项原始元数据应用于相同作用域下一输入修订。仅完成后排空与重复 worker 通过对话锁、位置部分唯一约束、条目状态 CAS 和单前台运行不变量去重。Retry 创建新运行，沿稳定重试根对副作用逻辑动作回执去重；提议的权威不明确时禁止再次调用处理器。

<a id="public-conversation-history-and-process-projection"></a>

### 公共对话历史与过程投影

`GET /api/tutor/conversations` 只按公共活动顺序返回学习者可见对话摘要。旧 `/history` 端点保留既有消息/过程倒序形状。历史 v1 快照定义严格 `message | process | elicitation | approval | error` 联合、公开活动轮状态（`in_progress | completed | interrupted | failed`）、类型化待处理请求/条目、队列、控制/暂停权威及流游标；当前增量 v4/v5 另承载 Artifact/分支状态，见后文。当前过程状态为 `thinking`、`waiting_input`、`waiting_approval`、`waiting_authority`、`completed`、`interrupted`、`superseded`、`unavailable`、`failed`；标签受服务端白名单约束，耗时有界。旧版纯消息行仍可见，不补造卡片、事件或时长。

标题唯一来源是与学习者可见 Tutor 回复一起成功写入的 `TutorDecision.conversation_title`。它经规范化/校验后，仅在 `tutor_conversations.title IS NULL` 时写入一次；缺失显示“新对话”。没有学习者文本回退、仅生成标题的提供方调用或重命名接口。

交互运行的提供方载荷将 `current_input` 与可选 `context` 分开。初次/修复共享教学策略把当前输入作为权威请求：优先回答或确认，再考虑旧路径；纠正、拒绝和完成声明覆盖旧路径，不重复被拒步骤；先回答建议/比较问题，最多追问一个必要问题。这是确定性夹具支持的指令契约，不是关键词路由，也不意味着替身模型测试证明教学质量。

提供方边界只使用配置的主兼容提供方。响应缺失、格式错误、不安全或失败均映射为稳定学习者安全 `MODEL_UNAVAILABLE`，不回退模型/提供方。可修复的可见内容、JSON 或类型化条目拒绝后，最多一次同提供方替代重试；不完整、失败、错误外层封装及传输错误直接终止，不修复。替代请求从权威输入/上下文重建，只包含有界字段路径和验证类别，不回显被拒候选、提供方校验消息、提示词或凭据。

每次实际提供方尝试返回安全 `TutorProviderAttemptReceipt`。首次请求与可选同提供方修复各有独立 `attempt_index`；`tutor_runs.model_call_count` 仍计一次循环决策边界，不计原始 HTTP 请求。生命周期在提供方返回后、刷新取消/替换 Gate 前立即持久化尝试回执，因此保留陈旧运行已发生用量，但不授权其消息、标题、能力或副作用。

`LLMUsage` 规范化 Responses 与 Chat Completions 字段，不改变路由。提供方 `input_tokens`/`prompt_tokens` 已含缓存输入，因此 `uncached_input_tokens = input_tokens - cached_input_tokens`，不重复加缓存。提供方报告总量与输入加输出计算总量是独立事实。缺失/错误用量记不可用（`None`/SQL `NULL`），不是零用量成功，也不是 Tutor 失败。完整封装即使被可见内容、JSON、决策或安全校验拒绝，仍可保留数值用量；封装前传输失败不虚构用量。
持久运行可保留有界内部诊断码，分类配置、超时、认证/配额/限流、HTTP/传输、错误提供方封装、缺失内容、非 JSON 内容、类型化契约（动作字段缺失/额外/无效）、输出安全拒绝或适配器失败。公共运行读取与 API/SSE 仍只公开 `MODEL_UNAVAILABLE`，不返回内部码、提供方正文、提示词、推理、传输细节、诊断工件标识或凭据。

<a id="primary-typed-item-decision-protocol"></a>

### 主提供方的类型化条目决策协议

生成 JSON Tutor 决策前，`OpenAICompatibleClient.complete_json()` 按配置提供方与模型选择唯一协议，重试或失败均不更改选择：

- 非 DeepSeek 配置保留 Responses 路径，通过严格 `text.format=json_schema` 接收生成的 `TutorProviderItemsEnvelope`。
- DeepSeek 仅在模型为大小写精确匹配的 `deepseek-flash` 时使用 Responses，规范端点为 `/responses`，包含 `input`、可选 `instructions`、`stream=true` 和有界 Tutor 决策输出预算。官方兼容模式仍为 `text.format=json_object`；`TUTOR_DEEPSEEK_RESPONSES_JSON_SCHEMA_ENABLED=true` 仅供已验证兼容网关显式启用。本地配置中 DeepSeek Flash 物理窗口为 `1_000_000`；普通 Aearn 提供方调用输入最多 `131_072`、输出最多 `61_440` token，Tutor 内部请求预算封装因此为 `192_512`，不是替换模型物理窗口。狭窄决策任务默认输出 `16_384`，不继承 60K 硬上限。首次尝试保留提供方配置/默认思考行为；修复默认发送 `reasoning.effort=none`，把替代尝试约束为狭窄序列化任务（`TUTOR_DEEPSEEK_REPAIR_THINKING_DISABLED=false` 可退出此行为）。物理硬限是能力边界，不是每轮填充目标：自适应规划器先估算精确序列化系统/用户消息、协议预留和安全裕量，再把剩余可选预算给 ContextBuilder。
- 其他 DeepSeek 模型保留 `/chat/completions` Chat Completions 路径、`response_format=json_object` 和保守 `TUTOR_DECISION_MAX_OUTPUT_TOKENS` 预算。

<a id="learner-visible-public-thinking-text-stream"></a>

### 学习者可见的公开思考文本流

当前 Tutor 提供方生成 `tutor_provider_items_v5`，兼容读取 `tutor_provider_items_v4`；v4 引入的公开思考文本流契约继续沿用。成功 `agent_message` 在须经权威校验的答案 `text` 前包含一个有界 `public_thinking_text` 字符串。段落与换行由模型决定，客户端不得编号、排序或重释。旧 `public_thinking_steps_json` 仅作历史只读兼容，用 `"\n\n"` 拼接；新行不双写两种表示。

`OpenAICompatibleClient` 提供通用 `LLMVisibleOutputObserver`。Responses 适配器只转发 `response.output_text.delta`；提供方 `reasoning`、`reasoning_content`、提示词、原始事件、正文、跟踪和诊断均不进入观察器。`TutorProviderPublicTextProjector` 只增量解码精确 JSON 路径 `message.public_thinking_text`，处理任意分块和 JSON 转义，每个持久块最多 160 字符，发布学习者安全累积前缀。即使传输 EOF，这些 `append` 块仍是暂存；投影器仅在 EOF 关闭并刷新解析器，`PrimaryTutorProviderGateway` 必须等完整对象通过 schema/领域校验、公开输出安全和流/终态文本精确一致性后才发持久 `complete`。重复/无效字段、传输重启、累积安全失败、最终文本不匹配、租约丢失、陈旧修订、修复、中断或替换都会重置/丢弃当前代次并默认拒绝；被拒尝试没有 `complete`。

`tutor_turn_public_thinking_streams` 仅存批准前缀及精确运行/输入修订/决策迭代/代次/提供方尝试校验边界。每次变更和匹配的 `turn_output` 事件同属一个短 PostgreSQL 事务。v2 快照可将精确活动行投影为 `active_thinking`；终态 Tutor 消息，或正式消息与其类型化请求，仅在流文本等于已验证决策时原子接受已完成流。最终答案不从部分提供方 JSON 流出，须等正常决策、动作/副作用、陈旧权威和终态持久化 Gate 全通过后才可见。

桌面在活动轮运行时立即显示不可交互 `StateDot + Think`。实时 `append` 文本先缓存在 DOM 外，必须同时满足固定首文本稳定窗口和已验证 `complete` 才成为原生展开组件。完成快照可立即恢复文本，未完成活动快照仍缓存。组件默认展开、保留原始空白，每个视觉节拍显示一个字素；思考队列追上后才开始新持久答案，`Think` 保持展开到答案队列完成，然后仅自动收起一次。历史消息立即渲染且默认收起。减少动态效果模式不动画，只同步批准文本，但保留相同权威和一次收起语义。

<a id="adaptive-context-budget-planning"></a>

### 自适应上下文预算规划

每个新交互 TurnRun 在 `policy_json` 和策略指纹中冻结 `TutorContextBudgetPolicy`，包含明确提供方能力证据、可配置 `compact`/`normal`/`complex`/`extended` 目标、警告/临界比例、有界扩展次数及估算器/策略版本。精确 `deepseek-flash` 注册项当前使用普通调用输入 `131_072`、输出硬限 `61_440` 与内部封装 `192_512`；物理窗口仍为 `1_000_000`。早期 1M/384K 与 616K 剩余窗口表述属于旧预算，不能用作当前配置。其他模型采用显式保守 Settings，不因模糊模型名匹配获得大窗口。没有新策略的旧运行继续重放已持久化 `context_token_budget`。

规划器与网关共享确定性序列化器，因此预估覆盖真实系统教学策略、规范严格决策形状、当前输入、所选上下文、元数据、JSON 封装、协议预留和安全裕量。固定点元数据稳定化将仅必需请求估算作为保守下界，提示词/元数据长度变化不能使后续总估算低于必需请求下限。当前输入先选且不可驱逐，随后把确认计划事实预留为必需事实区段，再选择可选来源。可选来源有界且确定；越硬限前跳过活动和无关能力 schema。必需序列化请求仍放不下时，任何提供方调用前返回 `TUTOR_CONTEXT_REQUIRED_OVERFLOW`。

初始模式仅依据安全结构事实：当前输入长度/行结构、围栏代码量、候选来源数、长来源数、近期历史量和摘要可用性。只有受控内部 `REBUILD_CONTEXT / insufficient_context` Gate 能提升一级模式，同时受冻结扩展次数及迭代/模型调用预算约束。上下文高水位由“必需估算 + 所选模式可选目标比例”计算，不采用普通有界来源永远达不到的旧 616K 物理剩余窗口固定比例。检查点元数据仅存模式、估算、预算、计数、来源 ID/哈希、阈值及版本；公共 API/SSE 不变。提供方 `input_tokens` 已含缓存输入，因此预检物理用量不扣缓存，实际输入也不再加一次缓存。

<a id="long-conversation-summary-retrieval-and-compaction"></a>

### 长对话摘要检索与压缩

交互上下文保留三个有序保真层次：权威 `current_input`、最新先前原始消息后缀，以及最多一个概括更早退役消息的结构化 `working_summary`。加载器从对话时间线 `(created_at, message_id)` 解析三者。当前输入永不进入退役集合；相同时间戳用 UUID 键避免缺口、重复或后续行干扰。

非空连续退役前缀产生 `tutor_context_summary_v2` 证据，包含前一摘要标识/哈希、退役消息 ID、SHA-256 内容哈希和覆盖游标。检查点、跟踪与 `tutor_memory_curation_outbox` 只持久化该有界证据。取得租约的 `context_summary` 整理任务在同一用户/对话域重读精确 `tutor_messages` 行，重新校验顺序、覆盖连续性和哈希，仅把有界原文发往配置的主 Curator 请求。退役原文不复制到跟踪、outbox、提案、回执或摘要元数据封装。

提交投影为仅追加 `tutor_context_summaries` 行，包含有界学习者安全概览，以及版本化 JSON 字段：当前目标、确认事实、完成步骤、拒绝路径、开放问题和学习者偏好。检索只接受已提交、未过期、非陈旧、schema/策略版本精确且覆盖早于当前输入的行。旧 280 字符行保留存储兼容，但不当作 v2 展示。摘要格式错误或不可用时默认退回 `current_input + recent_messages`，不删除原消息。

提供方冲突优先级固定为 `current_input > required_facts > semantically pinned recent_messages > ordinary recent_messages > working_summary > learner_memory/activity`。较新纠正或完成覆盖陈旧摘要，下一增量摘要可记录修正事实。对话连续性独立于推断记忆开关；既有调度暂停、租约、重试、预算、熔断、有限 TurnRun、自适应请求预算和提供方硬限继续有效。

Responses 适配器仅从 `output_text` 接受最终学习者可见内容。仅推理、缺少可见文本、错误 SSE/封装、非对象 JSON 文本、`response.incomplete` 和 `response.failed` 以有界内部类别拒绝。已选提供方 HTTP `400` 同样为安全内部请求拒绝类别，不触发协议、模型或提供方回退。

**历史 v3 协议说明（不作为当前生成版本）：** 当时提供方契约为生成、冻结、`extra=forbid` 的 `tutor_provider_items_v3` 封装：一个 `agent_message` 加恰好一个类型化动作（`turn_completed`、`select_skill`、`request_capability`、`propose_effect` 或 `wait_for_input`）。`wait_for_input` 使用上述五类精确 `continuation_kind`，同时受生成 schema、规范分支示例和服务端配对校验器约束。消息携带一至四条有界 `public_thinking_steps`，是专门面向展示的学习者解释；措辞、语气、顺序、粒度由模型按当前请求决定，不要求固定句式或过渡序列。它们接受公开教学输出校验，与提供方原生隐藏推理分离，Responses 适配器仍不读取后者。能力参数和副作用载荷是有界 `{key,value}` 数组，不是开放 JSON 对象。提供方不选择 `request_id`、`effect_id`、`expected_input_revision`、检查点、输入修订或终态。服务端按运行/修订/模型调用边界派生确定性动作 ID，把当前修订复制到副作用，将类型化动作映射到领域 `TutorDecision` 后执行既有 Gate。可选 `conversation_title` 仍为 NFKC 规范化、单行、学习者安全、最多 48 字符候选；持久化与公共历史由生命周期边界负责。当时成功公开消息原子保存 `public_thinking_steps`；失败、拒绝、陈旧、被替换或无消息结果不发布，旧行投影空列表。当前 v5 生成、v4 兼容和 `public_thinking_text` 规则见前文，不再生成或双写旧步骤列表。

<a id="context-governance-eval-and-calibration"></a>

### 上下文治理评估与校准

上下文治理证据层离线且增量。版本化 `tutor_context_eval_v2` 夹具组合既有当前输入、提供方尝试用量、自适应预算、结构化摘要契约，不引入第二选择算法或改变在线默认值。每例使用固定能力/策略、确定性估算器、替身提供方、固定数值延迟与合成学习者安全内容。时间线顺序、作用域、仅追加回执、初始化与摘要持久化仍以 PostgreSQL 责任测试为准。

每例产生 `tutor_context_eval_receipt_v1`，字段限安全数值、布尔、枚举、版本、诊断码与不透明来源 ID。缓存输入仍为实际输入子集，修复尝试独立记录，提供方报告总量与计算输入加输出分开，不可用用量保持 `null`。原始提示词/历史、提供方正文、推理、凭据、路径、命令和可重建摘要文本不是回执字段。

`tutor_context_calibration_v1` 按提供方/协议/能力/预算模式/估算器/配置版本分组估算与实际证据。仅达配置样本阈值后给出 P50/P95；估算偏差过大只建议复核估算器或安全裕量，不自动更改生产配置。替身契约证据、可选真实提供方行为采样、人工发布批准是三种独立状态。

<a id="4-skills-capabilities-effects-and-grounding"></a>

## 4. Skill、能力、副作用与事实检索

- 已发布 Skill 为精确 `id@semantic-version` 包，包含已审查的清单、指令和评估哈希；别名、范围、`current` 与未知引用均拒绝。
- Skill 管理的动作分两阶段：提供方先选符合条件的精确 Skill，待服务端用审查指令重建上下文后再请求能力/副作用。如果跳过选择，只有描述符/载荷校验通过，且恰有一个策略允许的审查 Skill 覆盖全部请求动作时，Gate 才可恢复：只记录 Skill 选择并返回 `REBUILD_CONTEXT`，绝不执行同一决策中的动作。零匹配仍为 `skill_selection_required`，多匹配以 `action_skill_ambiguous` 拒绝。
- 一个决策可选择 Skill 或请求动作，但不能混合初次选择与能力/副作用。
- 能力 schema 由描述符拥有且默认拒绝；模型数据不能变成 URL、路径、shell 命令、SQL 片段、用户 ID 或数据库目标。
- 事实检索只读开发者治理的注册表和预索引事实，不授权开放网络搜索、任意抓取、爬虫或文件系统访问。
- 副作用要求已选 Skill 证据、策略权限、当前输入修订、有效租约和仓储事务；初始默认策略拒绝未声明动作。

<a id="controlled-action-runtime-2026-08-12"></a>

### 受控 Action Runtime（2026-08-12）

Harness 将获准的 `grounding.retrieve`、`learning.plan.draft`、`runner.execute` 纳入统一版本化 Action Runtime 生命周期。精确 `ActionDescriptor` 声明输入/输出 schema、责任适配器、允许来源/任务类型、资源配置、超时、重试策略、验证器、恢复策略和安全投影。运行时分别持久化 `requested -> admitted -> running -> succeeded_unverified -> verified`，以及拒绝、可重试/永久失败、取消、超时和被替换结果。

动作编排不取代领域权威：事实检索与计划能力继续写既有能力/草稿回执；runner 动作只读已创建持久执行任务，不在 API 事务启动进程。每个动作回执只存一个权威类型/ID/哈希引用，不复制原始结果。当前输入修订、精确租约所有者/代次、动作代次、幂等键、目录摘要、策略指纹和资源指纹约束每个持久转换。

资源准入默认拒绝：提供方参数不能授权描述符和服务端白名单外的 URL、路径、命令、镜像、环境变量、动态 MCP 服务、网络类别、来源或工件。单运行动作、重试、验证、可执行恢复预算由服务端拥有。处理器成功仅为 `succeeded_unverified`；独立验证器须证明当前能力、计划事实/DAG、检索引用作用域或终态执行任务证据，才成为 `verified`。

近期终态动作回执以有界元数据进入 `AuthoritativeContextSnapshot`：动作 ID/版本、输入/动作/重试代次、生命周期状态、安全摘要、权威句柄、验证状态和恢复提示。原始参数、命令/路径、提供方正文、私有测试/评分规约、学习者提交、内部异常和密钥均不进入提供方上下文、公共 SSE、本地导出或跟踪投影。当前已验证稳定动作键直接重放/去重，不再次调用责任模块。

<a id="5-privacy-diagnostics-and-persistence"></a>

## 5. 隐私、诊断与持久化

规范学习者消息正文仅存 `tutor_messages`。事件、跟踪、检查点、能力/副作用/提供方尝试回执、导出、outbox 与公共 SSE 两次经过学习者安全白名单投影，排除原始提示词/历史、提供方载荷/错误/推理、隐藏测试、参考答案、提交代码、文件系统/容器路径、shell/SQL 目标、凭据、诊断工件标识和检查点载荷。此处是 Harness 通用安全边界；受控 Codex 的仅所有者可见原始 reasoning 例外见 2026-08-20 章节，不能混入 Harness 思考流。

原始提供方响应捕获是独立本地运维边界，默认 `off`。通用 LLM 客户端只有在 Tutor 网关显式传入 `capture_provider_body=true` 并注入诊断存储时才捕获。`TUTOR_PROVIDER_DEBUG_CAPTURE_MODE=rejected` 要求有效随机 32 字节 base64 密钥，经 `KEY_BASE64` 或外部 `TUTOR_PROVIDER_DEBUG_CAPTURE_KEY_FILE` 提供（直接值优先）。每次最多缓存 `TUTOR_PROVIDER_DEBUG_CAPTURE_MAX_BYTES`；接受后清零/丢弃缓冲，被拒尝试在配置本地目录写 AES-GCM 工件，使用随机 96 位 nonce 和认证安全元数据。工件不成为数据库行或 API 字段，默认保留 24 小时，只在配置目录内清理。捕获/配置失败不泄露正文，也不改变学习者安全终态投影。

运维日志可公开经生成提供方 schema 验证的字段路径、schema 所属预期枚举值和规则指导，绝不公开被拒值或原始 Pydantic 消息；未知路径片段仍哈希化。每条被拒尝试日志与加密工件标识 `(run_id, input_revision, decision_iteration, attempt)`，其中 `decision_iteration` 与持久尝试回执一致，均为 `model_call_count + 1`。日志通过不透明 `artifact_id` 关联捕获，区分 saved/empty/not_captured/failed，并记录截断与字节数；工件 ID 不进入公共 API/SSE。本地 `provider_debug_cli` 默认列元数据，必须显式 `show <id> --body` 才解密内容，且不写明文文件。诊断命令见开发环境指南。

`event_sequence` 是运行内持久排序键，不是确认存储。API 幂等记录绑定操作、用户作用域、请求正文哈希和安全响应；复用幂等键但不可变输入不同是冲突，不是第二次写入。

<a id="6-learningtrack-authority-and-learner-controls"></a>

## 6. LearningTrack 权威与学习者控制

`/api/learning-tracks` 是多个独立语言/目标轨道的仅已验证用户可用 HTTP 边界。PostgreSQL 拥有前驱关联的不可变计划修订、每轨道单活动指针、稳定键进度、仅追加掌握度证据和确定性掌握度投影。激活校验预期轨道版本及直接前驱，为保留 `knowledge_key` 保留进度/掌握度，按已满足先修条件初始化新节点。

`ExecutionTierResolver` 是 LearningTrack 唯一能力投影。本地开发可公开 `teaching_local`；公共组合同时要求审查不可变镜像锁和兼容执行器健康状态才能给出 `container_verified`。静态教学/审查能力退为 `static_only`；其他情况为 `unavailable`。解析不启动 runner 或执行器。

LearningTrack 首页、响应式三栏学习工作区、不可变 LessonDocument 阅读器、服务端权威练习 Gate 绑定/评分、仅追加 Attempt、模块诊断确认、模型代码审查练习、轨道域间隔复习、结构化 Tutor 上下文引用和既有队列执行交接均已实现。审查后的生产容器镜像集群与真实提供方发布冒烟不在本地实现证据内，仍需独立运维批准。

既有用户级 Tutor 控制保持不变：

- 计划修订不可变，`tutor_active_plans` 是唯一活动指针；回滚只可移到已存前驱并写动作记录。
- 记忆项携带有界证据与保留事实，纠正追加替代项，删除是受保护状态转换。
- 活动与收件箱为学习者安全投影，已读/忽略为用户域幂等动作。
- 偏好只公开推断记忆控制和主动任务暂停，不公开提供方配置、全局预算或无限能力权限。

<a id="7-verified-only-proactive-delivery-and-curation"></a>

## 7. 仅面向已验证用户的主动投递与整理

主动调度器默认开启，但范围刻意收窄：`TUTOR_PROACTIVE_SCHEDULER_ENABLED=true`、`TUTOR_BACKGROUND_HARD_PAUSED=false`、`TUTOR_PROACTIVE_CUTOVER_ELIGIBLE=true`，每日主动预算 `1`、并发上限 `1`。用户偏好默认 `enabled=true`、`hard_paused=false`；可重复初始化把旧版未暂停的 `enabled=false` 默认恢复为启用，但不覆盖显式暂停。

默认可用**不等于**无限制后台执行。允许候选或运行前，调度器检查全局启用/硬暂停、切换资格、该精确用户当前 `verified` 回执、用户暂停/启用记录、每日预算、冷却、并发、租约/重试限制和熔断器。未验证用户候选记录 `cutover_unverified`，不调用提供方、不预留主动运行。

信号仅来自持久终态交互运行元数据：运行标识、终态结果、终态时间戳哈希成稳定安全来源事实。扫描器不读学习者消息、提示词/历史、代码、跟踪、检查点或提供方诊断。生产扫描为全局（`user_id=None`）；显式用户域只用于夹具和维护隔离，不能静默改变正常队列。

生产组合记录持久目录快照，加载精确 `TutorRunSkillSelection` 证据，只允许审查 `tutor.learner-state@1.0.0` 选择及 `tutor.activity.record`。后台决策剥离提供方公开文本。成功后台运行只可创建学习者安全活动/收件箱投影，不创建聊天消息或桌面通知，不执行 `runner.execute`/学习者代码，不启动子进程，不直接写 `tutor.memory.record`。

整理与推断记忆仍默认关闭：推断记忆为 false，整理每日预算 `0`，整理最大输出 token `0`。未来启用整理配置也不能削弱已验证、策略、租约、来源、保留或安全投影准入。

<a id="8-cutover-deletion-and-rollback"></a>

## 8. 切换、删除与回滚

`harness_cutovers` 记录服务端状态，包括 `required`、`summary_ready`、`verified`、`verification_failed`、`blocked_target_state` 和 `blocked_checkpoint_scope`。

确认时服务端重新计算精确旧版摘要、nonce、哈希，只删除已证明归属的旧数据，并验证同一范围，保留本地身份/显示名和允许的通知偏好，原子提交 `verified` 回执。切换前 `tutor_*` 行属于目标污染，阻断而不删除；未知检查点作用域默认拒绝。

显式确认前，只要旧行尚在，代码/配置回滚仍只能恢复代码。确认删除后，回滚不会重建、迁移或推断已删除的学习计划、会话、Attempt、FSRS 状态、笔记或消息。

<a id="9-optional-live-provider-smokes"></a>

## 9. 可选真实提供方冒烟

默认套件保持离线且仅用替身。开发者获得独立授权后，可针对已配置本地提供方有意运行受控最新输入场景：

```powershell
$env:AEARN_RUN_TUTOR_LATEST_INPUT_SMOKE = "1"
uv --directory .\aearn\services\api run python -m app.services.tutor.latest_input_smoke
```

命令使用正常配置/环境凭据处理，不打印凭据、提供方载荷、提示词、推理或传输诊断。仅输出有界学习者可见消息及布尔规约字段：最新轮相关性、纠正确认、被拒步骤重复、先回答、放弃陈旧路径。该冒烟只是可选模型行为证据，不是 CI、发布批准或确定性契约测试的替代。

集成上下文治理冒烟是独立五轮边界，未经明确批准并启用则保持关闭：

```powershell
$env:TUTOR_REAL_PROVIDER_SMOKE = "1"
uv --directory .\aearn\services\api run python -m pytest tests/smoke/test_tutor_real_provider_smoke.py -q -m real_provider
```

它使用验收计划固定的五个学习者轮次、生产规划器和主网关，以及有界合成用户/对话/运行 ID。输出限学习者安全回复、用量、缓存比例、预算模式、安全延迟、尝试次数和布尔规约；不打印或持久化提供方请求/响应正文、提示词/历史、推理、凭据、路径或命令。默认不运行，也不授权发布。

<a id="10-verification-and-release-non-claim"></a>

## 10. 历史验证记录与不构成发布批准的边界

<a id="latest-input-teaching-relevance-verification-2026-08-05"></a>

### 最新输入教学相关性验证（2026-08-05）

权威当前输入变更当时在本地真实 PostgreSQL 和完整 API 套件验证，未发布：

- 上下文/提供方/评估/冒烟专项批次：**71 通过**；
- 输入合并/运行循环/SSE 回归：**23 通过**；
- PostgreSQL 初始化/运行仓储/上下文加载器：**15 通过**；
- 完整 `python -m pytest -q`：**365 通过**；
- `ruff check app tests`、`python -m mypy app --no-incremental`（**109 个源文件**）、`uv lock --check`：通过；
- Trellis 任务校验和 `git diff --check`：通过（仅换行符警告）。

当时新增可选真实提供方冒烟但未执行，因为未获得独立真实提供方使用批准。这些检查只验证本地契约，不证明真实模型教学质量，不授权提交、推送、部署或生产数据变更。

<a id="learningtrack-foundation-verification-2026-08-05"></a>

### LearningTrack 基础验证（2026-08-05）

增量 LearningTrack 基础当时在本地真实 PostgreSQL 和完整 API 套件验证，未发布：

- `uv --directory .\aearn\services\api run python -m app.db.bootstrap` 执行两次：通过；
- LearningTrack/schema/Tutor/切换专项：**95 通过**；
- 完整 `python -m pytest -q`：**345 通过**；
- `ruff check app tests` 和 `python -m mypy app --no-incremental`：通过（**108 个源文件**）；
- `uv --directory .\aearn\services\api lock --check`、Trellis 校验、`git diff --check`：通过（仅换行符警告）。

当时验证契约、限定作用域 PostgreSQL 约束、进度合并、掌握度重放、本地数据清单及 Tutor 作用域兼容；该阶段不启用 Gate/Review/完整工作区/代码执行，不证明公共容器集群，不授权提交、发布、推送或部署。后续实现状态见相应日期章节。

<a id="prior-current-local-change-verification-2026-08-03"></a>

### 早期本地变更验证（2026-08-03）

TurnRun/历史与严格提供方决策变更当时在本地验证，未发布：

- `uv --directory .\aearn\services\api lock --check && uv --directory .\aearn\services\api run python -m pytest -q`：**321 通过**；
- `uv --directory .\aearn\services\api run ruff check app tests`：通过；
- `uv --directory .\aearn\services\api run python -m mypy app`：**99 个源文件**无问题；
- `pnpm --dir .\aearn desktop:check`：`tsc && vite build` 通过；
- `git diff --check`：通过（仅换行符警告）。

专项覆盖新普通 TurnRun、首轮幂等、提供方返回后替换抑制、标题/过程/历史投影、游标作用域、严格 DeepSeek 决策和注入时钟的主动租约/CAS。只确认本地契约，不证明真实提供方教学质量、延迟、配额、浏览器交互流程或生产镜像集群行为。

<a id="historical-release-readiness-matrix-2026-07-29"></a>

### 历史发布就绪矩阵（2026-07-29）

早期最终本地验证矩阵于 2026-07-29 串行运行：API **275 项测试**通过，API Ruff/Mypy 通过（Mypy：**99 个源文件**），API 锁检查通过，独立执行器 **9 项测试**通过，桌面 `tsc && vite build` 通过，当前源码/依赖审计无旧版匹配，任务校验和 `git diff --check` 通过。完整命令/输出、夹具配置及已解决测试回归见 [`../qa/tutor-harness-release-readiness.md`](../qa/tutor-harness-release-readiness.md)。

各次本地检查与历史矩阵均不构成部署、发布批准、提交、推送或任务归档授权；本次文档整理未重跑这些历史命令。

<a id="adaptive-context-budget-verification-2026-08-08"></a>

### 自适应上下文预算验证（2026-08-08）

自适应规划器变更当时仅在本地验证，未使用真实提供方、未发布、未变更生产数据：

- 上下文/构建器/提供方/循环/输入合并专项：**101 通过**；
- PostgreSQL 初始化/约束与运行策略往返：**12 通过**；
- 完整串行 `python -m pytest -q`：**390 通过**；
- `ruff check app tests`、`python -m mypy app --no-incremental`（**112 个源文件**）、`uv lock --check`：通过；
- Trellis 校验和 `git diff --check`：通过。

这些检查证明确定性本地契约、策略持久化、硬限预检、有界重建、安全元数据和缓存记账语义，不声称与真实模型分词完全一致，不授权提交、推送、部署或生产数据变更。

<a id="context-governance-eval-verification-2026-08-10"></a>

### 上下文治理评估验证（2026-08-10）

版本化评估/可观测性补丁当时在本地执行，未调用真实提供方、未提交、推送、部署或变更生产数据。首轮跨契约批次 **130 通过、1 跳过**，跳过项是显式准入的 `real_provider` 冒烟。覆盖 v1 兼容、v2 夹具校验、安全回执、PostgreSQL 当前输入/历史排序、用量/缓存/修复尝试、全部预算模式与硬限、摘要退役/纠正/陈旧行为、运行循环和网关回归、运行持久化、重复初始化。最终矩阵 **404 通过、1 跳过，耗时 33.41s**；Ruff 通过，Mypy **114 个源文件**通过，`uv lock --check` 通过，桌面 `tsc && vite build` 通过（**46 个模块转换**），Trellis/diff 整洁检查通过。这些结果仍不授权真实提供方调用、提交、推送、部署、任务归档或发布。

<a id="2026-08-10-learning-plan-drafting-composition"></a>

## 2026-08-10：学习计划草拟组合

交互分发器仍默认拒绝。PostgreSQL 策略解析器在该阶段只给当前、非终态、未被替换且对话拥有活动计划会话的交互 `plan_drafting` 运行授权 `tutor.learning-plan-draft@1.0.2` 和 `learning.plan.draft@1.0.0`（当前 Skill 已为 1.0.3，旧包不变，见 2026-09-04 章节）。能力校验紧凑嵌套 JSON、服务端语言/来源/运行时事实和冻结 LearningPlan DAG，再追加一个类型化草稿。通用能力回执仅含草稿 ID/版本/哈希/状态。副作用仍拒绝，计划检查器 HTTP 确认是唯一创建轨道动作。草稿能力成功后，已选 Skill 须以 `turn_completed` 返回学习者可见审阅消息，不能为计划确认创建通用 `approval` 续接，以保留普通计划输入框供修改请求使用。只有精确运行拥有活动 `plan_drafting` 会话时，交互网关才将误出的 `approval` 转为普通完成；其他作用域的通用审批保持不变，仍适用于无关受控操作。学习上下文装饰器追加有界作用域/会话/当前草稿描述，不改变当前输入固定、自适应预算顺序、用量/缓存记账或摘要压缩。

修正后的 Skill 与导出能力 schema 都声明完整不透明 JSON 契约。`profile_json` 使用 `language_id`、`goal_text`、`target_level`、`weekly_minutes`、`experience_level`、`teaching_preferences`、`pace_summary`、`title`；每个模块包含类型化 `nodes` 而非缩写别名。无效嵌套输入跨 Psycopg 事务仍是类型化能力拒绝，回滚后记录安全会话错误，不创建草稿；终态持久化输出学习者安全重试消息，避免已完成思考流成为唯一可见输出。仅精确 `blocked_policy/capability_denied` 或 `budget_exhausted/deadline_exhausted` 诊断允许新 Turn 重试，让修正目录/Skill 或新有限截止时间恢复同一来源输入，不重开无关策略或预算拒绝。

能力结果字段是有界原始字符串，因此 Action 适配器先直接映射草稿 ID/版本/哈希，再构造 `plan_draft` 权威，不能复用 JSON 参数解码器。结构化上下文摘要整理键包含精确运行/输入标识，防止相同退役历史的新重试与另一运行冲突，同时仍对单运行内高水位/终态触发去重。

<a id="lessondocument-authoring-boundary-2026-08-11"></a>

### LessonDocument 编写边界（2026-08-11）

课件编写是独立服务端工件流程，不扩张通用 Tutor 能力载荷。分发前先创建并提交持久运行；分发器认领租约，只读持久化注册表所属事实来源，分配短证据句柄，通过严格 JSON 端口调用配置主提供方，执行确定性 schema/引用/覆盖/Gate 质量检查，复核轨道/进度/来源版本，最终在同一事务发布标准与个性化文档、快照、分配和运行终态。

不回退提供方/模型，也不回退静态课件模板。提供方调用不占用长 PostgreSQL 事务；尝试回执仅含安全提供方/模型/协议/结果/用量/哈希元数据。交互 Tutor 上下文限制与 `12 × 360` 通用能力封装不变，普通 Tutor 上下文不接收完整 Lesson 块或来源摘录。

<a id="exercise-gate-execution-reuse-boundary-2026-08-11"></a>

### 练习 Gate 执行复用边界（2026-08-11）

练习 Gate 是独立学习工件流程，不是通用 Tutor 能力/副作用调用。API 接受限定作用域 Attempt 和私有提交，把需执行工作映射到既有 `tutor_execution_intents` / `tutor_execution_jobs` 生命周期，使用 `source_kind=exercise_submission`、`owner_kind=exercise_attempt`；不创建 Tutor 对话、消息、运行或副作用。既有 Tutor 执行仍用 `tutor_message` / `tutor_effect`，数据库互斥检查禁止同一行混合两种归属模型。

执行器认领同一租约/启动 token 任务，但受信输入加载器须匹配用户、Attempt、提交、练习版本、私有评分规约和运行时配置引用后才解析 Gate 输入。公共 API 不接收受信输入或私有工件。终态执行输出先收敛成不可变学习者安全 Attempt 结果，学习服务才可投影 Gate/掌握度/进度；执行器自身不写通过、掌握度或解锁权威。

`container_verified` 仍默认拒绝，不因路由存在而授予。公共执行要求审查不可变镜像锁及兼容健康/配置证据。`teaching_local` 仅开发使用；`static_only` 采用服务端确定性评估并标记 `execution_claim=not_run`；`unavailable` 不创建执行任务，不回退主机子进程、旧 runner 或第二队列。本子任务当时未构建、签名、发布、批准审查镜像集群，也未调用真实提供方。

<a id="model-code-review-authoring-and-controlled-validation-2026-08-12"></a>

### 模型代码审查编写与受控验证（2026-08-12）

`model_code_review` Gate 可从有界学习事实创建用户/轨道/知识域草稿候选。服务端先选版本化受控模板；提供方只可返回严格 `model_review_author_candidate_v2={schema_version,title,learner_instruction,candidate_code}`，即教学场景文案与候选代码，不能选择 `template_id`，不能生成需求、测试、隐藏测试、预期结果、评分规约、问题发现、匹配器/证明或评分策略。服务端从受控模板和私有测试 DSL 构造公开需求、私有测试、预期结果、问题评分规约、可达性/覆盖证明和评分策略，并将完整模板标识/哈希写入私有规约。只有内部主动 Tutor 运行调用精确 `model-code-review.validate@1.0.0` 并得到已验证 `model_review_validation` 权威后，候选才可选择。

适配器在 Action Runtime 仅存不透明候选/验证 ID，复用既有执行意图/任务队列；API 和编写 worker 不启动主机进程或第二队列。解析、编译/类型检查、可见/隐藏测试、问题可达性、规约一致性、覆盖、脱敏均为版本化检查；还要求精确运行时 ID、测试数、可见/隐藏顺序和服务端预期通过/失败结果全部匹配。执行器只在认领后读私有 DSL，入沙箱前剥离模板测试 ID、`candidate_expected_pass`、`proof_ids`。证据缺失、失败或陈旧均阻止发布。该 Lesson Gate 提交仍采用静态、确定性评分；模型教学反馈只消费学习者安全评分证据，不改评分、掌握度或解锁。对话原生 model-code-review v2 的提交前绑定语义审查另见当前契约，不能与提交后讲评分混同。

<a id="track-scoped-spaced-review-and-finite-reviewsession-2026-08-12"></a>

### 轨道域间隔复习与有限 ReviewSession（2026-08-12）

现行复习权威属于 `services/learning/reviews/` 与 `routes/learning_track_reviews.py`，不重开已移除顶层 `/api/reviews` 运行时。日程按 `user_id + track_id + knowledge_key` 唯一限定，跨计划修订使用稳定知识键，仅由受信掌握度证据播种。已确认模块诊断跳过使用低频初始日程；计划激活保留匹配键，并为移除键写显式暂停事件。

`GET /api/learning-tracks/{track_id}/reviews` 返回服务端可操作队列。普通到期项不阻断课程进度；持久 `critical` 风险项若为当前节点直接或传递先修，即使未到下次普通 `due_at` 也立即纳入，且唯有此类项投影为 `critical_prerequisite_gate`。`review_due_count` 使用相同可操作定义：普通到期日程加即时 critical 恢复 Gate。

有限 `ReviewSession` 冻结活动计划修订、预期轨道/日程版本、不可变练习版本和有界 `AuthoritativeContextSnapshot`。热身、提示回执只是仅追加会话事实，不更新掌握度或日程。每个正式条目恰好创建一个 `Attempt(review_submit)`，按服务端解析执行等级复用静态/模型审查评分或既有执行队列。所有条目均有终态结果后，才可在单个收尾事务追加复习掌握度证据、日程事件、更新日程投影并终态化会话。重放返回已存结果，请求哈希冲突或陈旧版本默认拒绝。

候选不足时同一会话保留可恢复 `blocked`，诊断 `REVIEW_CANDIDATE_UNAVAILABLE`，不合成未经验证的备用练习。公共投影省略完整提交、私有规约/测试、提供方正文、执行内部信息和上下文哈希。本地导出只含有界复习摘要；重置/删除和切换清单按子到根包含全部用户所属复习行。

<a id="final-learning-agent-integration-audit-2026-08-12"></a>

### 学习 Agent 最终集成审计（2026-08-12）

当时最终集成边界采用确定性、仓库事实依据：

- Python、JavaScript、TypeScript、SQL 各有真实 PostgreSQL 夹具，创建轨道、发布有来源的不可变 LessonDocument、开始分配、绑定 Gate、记录终态学习者安全结果、投影掌握度/进度、创建到期 ReviewSession，并最终提交一个复习证据/日程事件。
- 同一夹具证明 `image-locks.json` 为空时，需执行 Gate 的公共组合仍为 `unavailable`。开发执行明确为 `teaching_local`，不提升为 `container_verified`。
- Java、HTML/CSS 仍是具 runner 级测试的扩展能力，不声称通过四语言核心端到端课程矩阵。Go、C# 为部分本地托管编译能力；Rust 公共 `unavailable`，C++ 公共 `static_only`。均无审查公共容器锁。
- 切换把每个 `tutor_*` 表分类为用户目标状态或显式共享目录/健康/私有练习表；未来任何 Tutor 表未分类都会使 schema 对齐测试失败。
- 旧 `learning_*`、用户级 Tutor 计划、复习、笔记及 Graph/运行时数据不静默转换为 LearningTrack 证据。清空重建切换只删精确确认旧范围；普通重置/删除清理当前用户学习状态；功能回滚保留证据且不能绕过已验证切换准入。
- 计划、Review、代码审查验证和右侧 Tutor 消费持久权威快照或已验证 Action 回执。执行完成与验证成功仍不同；陈旧/被替换权威不能发布副作用、掌握度事实、解锁或消息。

这是本地集成证据，不是发布批准、提供方质量结论、镜像供应链批准、推送、部署或生产数据迁移。

<a id="global-threadturn-v2-cutover-2026-08-14"></a>

### 全局 thread/turn v2 切换（2026-08-14）

v2 生效条件是 `TUTOR_THREAD_TURN_V2_ENABLED` 与 PostgreSQL 单例状态 `enabled` 同时成立。准备阶段在清单收敛前冻结公共变更与 worker 认领。安全旧等待轮以要求新轮的迁移码失败；其他可取消活动轮投影为普通中断并清理租约/任务。副作用有歧义会阻断激活。读取保留，旧续接 POST 为永久 410 墓碑；回滚是只读禁用，不复活旧版。运维命令见 `docs/setup/tutor-thread-turn-v2-cutover.md`。

<a id="controlled-codex-plan-drafting-cutover-2026-08-18"></a>

## 受控 Codex 计划草拟切换（2026-08-18）

一般对话、学习轨道、主动、历史及功能关闭流量仍默认使用 Harness。服务端仅在新 TurnRun 创建时冻结 `runtime_kind`。新 `plan_drafting` 对话只可依据新鲜共享 worker 就绪证据选择 `codex_sidecar_v1`，该证据须匹配白名单 Runtime 版本及精确 `deepseek-flash` / `aearn_deepseek` / `responses`。已启用群组就绪失败返回安全不可用，不回退 Harness。已有对话和重试根继承原 Runtime。

持久交互任务表仍是权威。Harness/Codex worker 用互斥 Runtime 过滤认领，`TutorRuntimeDispatchRouter` 只按持久运行快照路由。Codex 分发器不包装 `TutorRunLoop`，而是负责 Runtime thread/turn、类型化 LearningPlan 工具注册表、租约心跳、steer/interrupt 监视和持久 Runtime 投影器。LearningPlan 确认与 LearningTrack 创建仍在 Codex 外的既有 Aearn HTTP/领域事务内。

<a id="2026-08-20codex-conversation-threadlocal-compaction-与原始运行流"></a>

## 2026-08-20：Codex 对话线程、本地压缩与原始推理流

`codex_sidecar_v1` 的长期上下文边界从 run 提升为 learner conversation：每个 `TutorConversation` 最多拥有一个 active `tutor_conversation_runtime_threads` 记录和一个持久 Codex App Server thread；每个 fresh `TutorRun` 只在该 thread 内执行新的 `turn/start`。worker/App Server 重启后必须用持久 external thread identity 执行 `thread/resume`，但 external thread/turn/item identity 始终是 private correlation，不进入公共 DTO。旧 run-level binding 只有在一个 conversation 恰好对应一个 legacy thread 时才可自动采用；歧义历史创建新 thread，并用一次性 bounded learner-visible timeline + confirmed planning facts reseed，随后仍须重新调用 Aearn planning context tool。

当前 `aearn_deepseek` 只允许本地 Codex 上下文压缩。`CodexRuntimeConfig` 写入 `model_context_window=1_000_000`、`model_max_output_tokens=61_440` 和 `model_auto_compact_token_limit=950_000`，并使用 `model_auto_compact_token_limit_scope="total"`。Codex 持久线程不受普通 LLM 客户端 128K 单次输入限制；达到 950K 累计上下文时先执行本地压缩。950K 到物理窗口只余 50K，因此 60K 是允许的最大输出而非临界点上的保证输出。`thread/compact/start` 与回合内 `contextCompaction` 生命周期都由本地 App Server 控制；当前提供方不声明、不发送远程压缩请求，也不以远程压缩作为降级路径。

Codex item stream 使用闭合 phase/channel 规则：raw `reasoning` text 进入 private owner-scoped reasoning projection；`agentMessage phase=final_answer` 进入 answer projection；`commentary` 只留下 nonpublic safe receipt；reasoning summary 保持独立内部事件，不冒充 raw reasoning。delta 先经 run input revision、lease owner/generation、Runtime connection generation、thread/turn identity 和单调 sequence fence，再写入 `tutor_runtime_text_items` 并发布版本化 `turn_output`。completed item 用完整 text/hash 原子校准；若 completed phase 把先前 provisional `final_answer` 校正为 `commentary`，服务端必须清空并 discard 该暂存 item，发布无 text 的 discard 事件。任何 turn terminal 都必须清空并 discard 剩余 streaming item，避免刷新后残留卡住状态；final answer 仍必须通过 teaching safety 后才能关联正式 Tutor message。Runtime publisher 对短时队列饱和使用有界异步背压，只有 subscriber 在等待窗口后仍未释放容量时才以 `runtime_event_backpressure_exhausted` fail closed。

planning context tool 返回 confirmed facts、missing fields、facts revision/fingerprint 和 server question catalog version。出现 `awaiting_user` 时，Aearn 还会返回 `next_missing_fact {field_key, meaning, exact_question, wording_policy, response_authority}`；当 `language_id` 缺失时 additive 返回 bounded `language_candidates`，只含 canonical language、course title、level、capability state 与 execution family。Codex 先执行一次不含 action 的只读调用，再立即执行一次包含唯一 closed `direction_action` 的调用；只有 `continue_mainline` 可同时携带 strict `planning-intent-hint-v2` 的 1..3 个当前 language IDs，证据不足则选择 `clarify_direction`。服务端 gate 仅从 accepted marker 构造 exact fact question、bounded answer/refocus、固定方向澄清或 append-only switch reopen；缺失/非法 marker 不得回退到 primed `next_missing_fact`。typed response 创建 fresh run 并 resume 同一 Codex conversation thread。PostgreSQL planning facts、typed request、LearningPlan、Queue、权限和 effect commit 继续是 Aearn authority。

该 Codex raw-runtime contract 仅替代 `codex_sidecar_v1` 对 provider-native reasoning 一律禁止公开的旧规则。Harness `tutor_public_thinking_stream_v1` 与 legacy `public_thinking_text` 继续作为兼容路径，不得把二者和 raw Runtime reasoning 混写、拼接或互相推导。

<a id="2026-09-03-explicit-language-authority-and-semantic-shortlist-confirmation"></a>

## 2026-09-03：显式语言权威与语义候选确认

`PostgresPlanningFactRepository.record_input()` 对已接受 `plan_drafting` 输入调用 `planning-language-intent-v2`。解析器使用精确学习者消息、当前确认语言、活动课程/能力、确定性 PostgreSQL 意图标签和可选已验证语义提示。单一显式活动语言仍是唯一自动确认路径；确定性方向/冲突结果可构造候选短名单，语义提示不追加事实且限 1..3 个活动规范值。

Harness 在计划上下文公开紧凑服务端候选描述，仅在 `planning_input + language_id` 接受 v2 提示；Gate 记录问题前复核当前输入修订和活动候选。Codex 使用类型化计划上下文工具，不用 Harness 提供方动作：首次读取后必须恰好一个 `direction_action`，同一提示只可随 `continue_mainline`。分发器只把已验证状态转为既有持久请求；缺失/非法动作使用固定方向澄清，非方向 Runtime 失败仍是失败。两路径在持久化不安全边界均执行最终重新解析。

功能启用时的歧义、无效/陈旧提示和无活动语义匹配不能构造语言选择器或扩大到全目录，必须澄清或默认拒绝；只有关闭功能才能回退完整目录。一旦持久化，精确呈现与顺序不可变，下一新 TurnRun 只记录学习者从该已存呈现选择的公开值。

<a id="2026-08-21codex-runtime-delta-合并与语义预算"></a>

## 2026-08-21：Codex Runtime 增量合并与语义预算

Codex adapter 为每个 turn 建立独立 `RuntimeDeltaCoalescer`。仅连续同 `thread/turn/item/kind/channel/index/phase` 的 reasoning/final-answer delta 可合并；默认 25ms、1,024 字符或 4KB flush，任意 item/phase/summary/tool/compaction/completed/terminal 边界强制 flush。合并后的文本必须逐字等于 source delta 串联，`item/completed` 仍是最终文本校准 authority，commentary、reasoning summary 与 terminal discard 规则不变。

source sequence 与 projection sequence 分离。Runtime result、PostgreSQL text reducer、conversation SSE 与 Desktop 只按 projection sequence 工作；append-only receipt 保存安全 source range/count/hash。关闭 `CODEX_RUNTIME_DELTA_COALESCING_ENABLED` 时恢复逐 delta projection，但不会恢复 `len(events) >= 2000` 或 `runtime_event_budget_exhausted` 正常失败。

Runtime 资源限制现在是独立语义预算：100,000 raw notification runaway guard、item、tool、累计可见文本、turn time 与 pending bytes。普通日志只记录 source delta/projection/flush 数、maximum pending bytes、duration 与 safe code，不记录文本。UI/SSE gap、refresh 和 reconnect 继续通过 fresh snapshot 恢复，不 terminalize 模型 turn。

<a id="2026-08-23knowledge-scoped-teachingsession-与-closed-teaching-action-loop"></a>

## 2026-08-23：知识域 TeachingSession 与闭合教学动作循环

LearningTrack learner conversation 仍是长期 history/context scope；TeachingSession 是其中一个知识点的 durable authority segment，不是新 conversation，也不改变“普通 learner message = fresh finite TurnRun”的全局模型。server 在 open/resume 时读取 active plan node、progress、唯一 track-scoped learner conversation、active Lesson assignment 与 immutable LessonDocument，冻结 session authority 并创建首个 append-only checkpoint。旧 conversation 没有 session 时保持可读，不扫描聊天正文做猜测型 backfill。

每个 teaching-scoped fresh run 额外冻结 `tutor_run_teaching_scopes`，并关联一个 exact `TutorTurnStimulus`：真实 learner message、显式 teaching control 或 server-owned domain event。control/event 不伪造 learner message、不使用 proactive origin。authority version 变化时，旧 current session 追加 `authority_pause` checkpoint 并置为 blocked，successor 通过 `predecessor_session_id` 冻结新 authority；partial unique 只允许 exact scope 同时存在一条 `active | paused` session。

**历史教学协议说明（后续已由 v3/1.2.1 替代）：** Harness 为 teaching run 注入 required `TEACHING_SESSION` section，并只授权 `tutor.lesson-teaching@1.1.0`。`tutor.lesson-teaching@1.0.0` 的 manifest、instructions 与 evals 保持不可变，仅作为历史 catalog evidence。provider 先选择 exact Skill，context rebuild 后只能返回一个 strict `tutor.teaching-step-decision.v2`：closed action、exact objective/focus/source handles、closed focus resolution、一个 pause kind、2--4 个互不重复的 `teaching_moves`、显式 `learner_response_mode` 和 learner-safe public message。unknown handle/focus、extra field、missing/duplicate move、response/action 不兼容、Free Reading 越权主动控制、伪造 completion 或 next node 均在 durable commit 前 fail closed。

一次成功 Turn 在同一 PostgreSQL transaction 内 append next checkpoint、CAS session、insert `tutor_teaching_action_receipts`、写 Tutor public message、outbox/event 并 terminalize run。v2 receipt 只保存 action/focus/pause、safe handles、`teaching_moves`、`learner_response_mode`、schema/policy version、context IDs/hashes 与 public-message hash；最近四个 v2 单元以这些安全字段进入下一次 `TEACHING_SESSION`，不复制消息正文。provider unavailable、stale/superseded/lease loss 不写 checkpoint/receipt/message；provider 返回后 authority 失效的 teaching run durable cancel 为 `teaching_authority_stale`。

Aearn 根据 checkpoint/pause/runtime/request/mode/completion 与最近已提交教学单元生成 `TeachingActionShelfV1`，最多一个 primary 与三个 visible secondary；active runtime、blocking request 和普通 shelf 互斥。只有 `recommended_action_key=continue` 时才投影主操作“继续”，需要学习者回答的单元改投影 `respond_in_composer`，不存在真实 descriptor 时 shelf 为空。Free Reading 普通问题只产生 reactive finite answer，只有显式 `escalate_guided` 才切 Guided 并 admission 一个新 Turn。completed progress 只接受 `summarize_progress + completion_pause`，不自动改 workspace knowledge key；只有显式 `enter_next_knowledge` 才重新验证最新 roadmap/availability、复用同一 conversation、推进 track pointer并 admission 下一 session 的 first-unit run。

Harness 在 effect commit、waiting result 和 terminal result 前重新验证 current session/checkpoint、track/active plan/progress、active assignment/document 与 stimulus scope。conversation snapshot/API additive 返回 bounded session/checkpoint/Action Shelf metadata；trace/export 不包含 raw checkpoint/authority JSON、prompt、reasoning、provider body、完整题目/提交、hidden test/rubric、command/path 或 secrets。五张 user-owned teaching 表全部进入 cutover exhaustive inventory 与 local export/reset/delete；删除 action receipt 后再按 run scope/stimulus/checkpoint/session 清理，deferred `NO ACTION` lineage FK 保证同一事务 child-to-root reset 与 bootstrap twice 可重复。

<a id="2026-08-23三时间尺度恢复summary-precedence-与-domain-event-turn"></a>

## 2026-08-23：三时间尺度恢复、摘要优先级与领域事件轮次

长期 track conversation、知识点 TeachingSession 与单次 TurnRun 继续是三个不同时间尺度。owner domain event 只触发一个 fresh interactive Turn；每个 Turn提交一个 closed teaching action 后必须停顿。authority 变化时旧 session 写 `authority_pause` 并 blocked，successor 冻结新 progress/assignment/document；重复事件复用既有 run，stale source 被忽略。

教学 context 优先级为 current input/typed stimulus → current session compact authority → exact references → bounded recent current-session messages → current checkpoint-backed summary → 至多一个 exact predecessor summary → generic conversation summary/memory/activity。`teaching_control | domain_event` 不伪造 current learner input，但 context loader 仍按 frozen `teaching_session_id + session_version + scope chronology` 读取当前 run 之前的 same-session learner-visible messages；legacy group、其他 session/knowledge 与未来消息不进入该窗口。`continue/resume` 必须在最新教学消息之后推进，不能仅凭相同 objective/checkpoint 重启或近义复述已讲解内容；`change_example`、remediation 与 summary authority 例外。active/suspended focus 中的 exact message handle、unresolved question source message 与当前 session 最新 learner input进入 compaction protected set。summary source hash、checkpoint cursor或 authority snapshot失配时 provider 前 fail closed，不允许旧 summary 覆盖最新纠正或完成事实。

<a id="2026-08-27teaching-skill-v11-与教学单元推进门"></a>

## 2026-08-27：Teaching Skill v1.1 与教学单元推进准入

**历史 v1.1 契约（2026-08-27）：** exact `tutor.lesson-teaching@1.1.0` 使用 `tutor.teaching-step-decision.v2`。每个教学单元必须选择 2--4 个互不重复的 closed `teaching_moves`：`targeted_explanation`、`worked_example`、`counterexample`、`misconception_contrast`、`guided_derivation`、`prediction`、`error_detection`、`micro_transfer` 或 `learner_feedback`。`learner_response_mode=composer` 只允许搭配 `check_understanding | wait_for_input`，并且必须包含至少一个诊断性 move；`none` 不允许这两个 action。`change_example` 必须实际包含 `worked_example | counterexample`。

下一次 teaching run 的 required projection 包含最近四个已提交 v2/v3 单元的 action、focus、moves、response mode、public-message hash 与 schema version。投影主动删除重复 summary/UI 字段并保持既有 1,200 字符 required-section 上限，不通过提高全局 context budget 掩盖溢出。`continue` 若与最近单元 public-message hash 完全相同，decision gate 以 `teaching_unit_not_advanced` fail closed。普通 learner Continue 的同 focus/moves/response mode 策略签名重复也拒绝；只有 owner 通过 consumed intent、Artifact event 与 immutable response receipt 的 exact join 证明新知识检查结果时，反馈可以复用同一策略签名。此 server-only 证据标记不能由模型或 learner control 提供，不豁免 exact text、source handle、completion pause 或正式 Gate 规则。

Teaching request 保留完整通用协议规则与 canonical teaching-step example，但不再重复附带该上下文不允许的普通 direct-reply / generic wait-for-input examples；非 teaching request 仍包含完整普通示例。此去重不截断 required authority/question/receipt，也不提高输入硬上限、输出预留或物理上下文容量。若完整 required request 仍超限，必须在调用 provider 前以 `TUTOR_CONTEXT_REQUIRED_OVERFLOW` 失败；无公开评价消息的早期失败不发布结果工件，也不能被二次发布错误改写成 `teaching_authority_stale`。

checkpoint reducer 先尊重 session/evidence/completion/authority 状态，再解释 response mode。需要学习者作答时推荐 `respond_in_composer`；只有明确推荐继续才显示 Continue。这个决策只改变 server-owned projection，不增加新的客户端状态机、provider 控件或自动 next run。

<a id="2026-09-01artifact-aware-teachingclarification-branch-与-continuation-arbiter"></a>

## 2026-09-01：工件感知教学、澄清分支与续接仲裁器

**历史选择版本（2026-09-01）：** 新 teaching run exact 选择 `tutor.lesson-teaching@1.2.0` 与 strict decision v3。server 在 provider 前从 current TeachingSession/checkpoint、最新 published Learning Item、capability set、Practice materialization、runtime readiness 和 feature flags 构建 bounded `teaching_artifact_candidates_v1`；provider 只能返回 `none/none/null`、`composer/text_answer/null` 或 `artifact/<closed intent>/li:<sha256>` 三类 exact pairing，不能发明题目、owner、payload 或 runtime identity。`TUTOR_ARTIFACT_TEACHING_MODE_ENABLED` 默认关闭；关闭时候选为空且 Artifact decision fail closed，历史 Artifact/Teaching read 不受影响。 当前新运行改用不可变 `tutor.lesson-teaching@1.2.1`，本段 1.2.0 仅保留当日证据。

合法 Artifact teaching decision 在一个 caller-owned PostgreSQL transaction 内提交 Tutor message、next checkpoint/session CAS、`teaching_action_receipt_v3`、Learning Artifact、Artifact event、conversation `item_added` 与 source Turn terminalization。materializer 在 commit 前重新验证 publication state/version、public content hash、capability、Practice/runtime 与全部 session/track/progress/assignment fence；任一变化或 event append 失败都会回滚所有 public write。Artifact facade 不创建 Attempt、score、Gate/Review completion、mastery 或 progress authority。

blocking Artifact 等待期间的普通 learner message 仍创建 fresh finite Turn，但额外绑定一条 durable depth-one clarification branch。branch anchor 固定 Artifact、TeachingSession、checkpoint lineage 与 explicit item membership；nested branch、跨 scope 或 stale ancestry fail closed。response disposition 只有 `answer_and_refocus | offer_switch | confirmed_switch`；topic switch 必须先 offer 再接受 typed confirmation。hint/direct answer 必须携带同 scope 的 authoritative Hint/Teaching receipt，不能从自由文本推断 assistance。

Artifact 动作/事件、静态计时器与后台工作只追加持久化续接意图，不直接调用提供方。单回合仲裁器固定按“学习者消息 > 显式 Artifact 动作 > 预期交互事件 > 静态展示计时器 > 后台续接”排序；活跃前台运行、待处理学习者输入或活跃分支会阻止自动续接，计时器/后台续接只允许在 Guided 模式运行。领取世代、租约、权威版本与检查点祖先关系共同保证并发领取者最多创建一条主线回合；分支解决后，结果续接才回到主线。有分支历史时，重连使用增量快照 v5；原 v3/v4 对话的兼容规则保持不变。

<a id="2026-09-02conversation-native-model-review-v2"></a>

## 2026-09-02：对话原生模型审查 v2

已发布模型审查 Learning Item 增量物化为对话 Artifact，而非恢复或绕过既有 Lesson Gate/Review 运行时。服务端把不可变发布代码转为确定性 `model_code_review_artifact_v2` 代码/diff 目标，带稳定哈希、hunk、side、行键。桌面只负责只读 Monaco 展示与结构化问题发现编辑，不执行代码、不拥有评分。

`complete_review` 由 Learning Item 责任适配器在当前 TeachingSession/发布校验边界内处理。服务校验精确呈现/hunk/范围标识，把既有私有 v1 规约升级为闭合 v2 分类，执行服务端确定性评分，写一个不可变私有提交回执并完成 Artifact，不创建 Attempt，不写掌握度/进度。当前提交前还存在绑定语义审查，可在保存结果前拒绝结构合法但语义不符的提交（详见 2026-09-16 当前契约）；这不等于让提交后 Tutor 修改结果。失败结果要求不同、已发布、未用的 D(n-1)/D(n) 补救项，范围更小/难度更低；缺权威则回滚完整动作。

一个精确 Artifact 事件/回执续接准入新教学 Turn。上下文只含 `reason_code=model_review_evaluation`、来源 Artifact 句柄、有界安全评价和至多一个持久补救句柄。提供方可解释已保存结果，但不能改变评分、结果、后继、回执、Gate、Review、掌握度或进度。完整提交、私有评分规约/测试/证明和提供方内部信息仍不进入 API/SSE/桌面/上下文/导出。

<a id="2026-09-02conversation-native-sql-workspace"></a>

## 2026-09-02：对话原生 SQL 工作区

已发布结构化 SQL Learning Item 物化为 `sql_workspace_v2` Artifact。公共描述符仅含 SQLite 教学 schema 和一个公共数据集；私有可见/隐藏测试保留独立数据集与精确预期。Learning Item 责任适配器不在 Artifact 锁内执行 runner，只准入一个精确待处理 Attempt。提交后，路由观察器为每个数据集新建内存 SQLite 数据库，应用只读授权器/资源限制，保留公共查询列/行，脱敏隐藏标识/值，并通过既有评分器收尾同一 Attempt。

标准执行结果投影器仍是唯一 Artifact 结果路径。全部测试通过直接完成 SQL 来源；任意运行时/测试失败保留可编辑状态，创建一个不可变结果 Artifact，并准入一次结果评价续接。本地 runner 和 Tutor 模型均不能创建 Gate、覆盖评分、写掌握度/进度、公开私有数据集、连接 Aearn PostgreSQL 或声称容器验证。桌面仅负责草稿/查看/复制/陈旧状态，显式 Run 时提交最新查询。

<a id="2026-09-02tutor-conversation-learning-artifact-platform-final-composition"></a>

## 2026-09-02：Tutor 对话学习工件平台最终组合

运行时使用统一服务端权威 Learning Artifact 协议，不让每个小组件自建权威。`tutor_learning_artifact_v1` 拥有稳定公开标识、状态/版本、闭合呈现/动作联合、安全来源引用、可选 Attempt 摘要和分支摘要。Gate、Review、Attempt、TeachingSession、掌握度/进度及 Learning Item 发布仍归既有领域负责。Artifact 路由是领域门面；桌面本地状态不改变结果、评分、发布状态、续接优先级或进度。

闭合呈现矩阵为 `exercise_workspace_v1`、`browser_preview_v1`、`test_result_v1`、`knowledge_check_v1`、`model_code_review_v1/v2`、`sql_workspace_v1/v2`、`demonstration_v1/v2`、`source_inspector_v1`。Artifact 动作为 `request_hint`、`request_direct_answer`、`run`、`respond`、`complete_review`、`cancel`、`acknowledge_demo_event`、`complete_demo`。`TutorPublicItem` 包含 `artifact`；Artifact 扩展对话事件使用 `tutor_conversation_event_v3`，基础事件仍兼容 v2；后端快照支持 v3/v4/v5，桌面保留 v2-v5 兼容。大详情通过限定作用域读取，SSE 只携稳定条目引用和有界安全增量。

已发布 Learning Item 句柄是唯一在线候选来源。两个写入/准入开关 `TUTOR_LEARNING_ARTIFACTS_ENABLED`、`TUTOR_ARTIFACT_TEACHING_MODE_ENABLED` 和离线审查开关 `LEARNING_ITEM_BANK_AGENT_REVIEW_ENABLED` 默认 false。准入关闭时候选投影为空，Artifact 交互决策在公开 Tutor 消息前失败，已有行仍可读取。回滚先关闭候选/准入，再关闭桌面/Preview 呈现，保留增量历史，不执行破坏性降级迁移。

HTML 编辑采用进程内 Monaco 草稿和应用所有的隔离 Preview；实时 Preview 不具权威，只有显式 Run 创建 Attempt。终态执行、知识、审查、SQL、演示证据都只进入一个既有领域/结果/续接路径。阻断 Artifact 只可锚定深度一澄清分支；仲裁器将学习者消息置于显式动作、预期事件、计时器和后台续接之上。精确 Lesson 来源按用户/对话/轨道/文档/版本/块/哈希解析，在隔离右抽屉显示，不文本搜索、不滚动对话、不重新挂载组件。

该 Artifact 领域的公共 API/SSE/桌面/导出/就绪证据不含完整提交、私有规约/测试/参考答案、隐藏 SQL 数据、提供方正文/推理、命令、路径、容器标识、凭据或密钥。这里不覆盖受控 Codex 仅所有者可见的原始 Runtime reasoning 例外。本地替身提供方、SQLite、浏览器、WebView2、空镜像锁证据仅是工程验证，不是提供方质量、生产沙箱、镜像、部署或发布批准。

<a id="2026-09-04-codex-planning-direction-candidate-gate-and-receipt"></a>

## 2026-09-04：Codex 计划方向候选、准入与回执

Codex 计划草拟把方向判断与计划事实权威分开。一次只读计划上下文调用后，模型必须提交恰好一个内部闭合方向动作。服务端校验并映射到既有精确计划问题、有界回答/回归主线消息、固定方向澄清，或既有四字段仅追加切换重开。方向解析缺失/无效绝不落入预载的旧 `next_missing_fact`。2026-09-08 修复后，预算/时间/致命 Runtime 失败保持可见失败，不误报为语义歧义；真正方向澄清保留既有服务端映射。

预载等待用户轮使用低推理强度和 45 秒，消息上限 2,000 字符、推理上限 16,000 字符，聚合硬限不变。一次错序工具调用可使用既有单次修复额度，实际调用最多三次，但只接受一个方向动作。预算、超时、致命工具和取消清理约束回调，要求有界中断加匹配终态确认；只有 ACK 不足，停止未确认则关闭所属运行时。事实完整草稿轮保留正常质量配置。成功映射后置条件在 `tutor_run_events` 追加一个闭合、幂等 `planning_direction_resolved` 回执，无需迁移；回执仅内部使用，只含哈希/闭合元数据。公共快照/SSE/桌面不新增方向字段。Codex 原始推理仍通过 Runtime 输出、快照/历史/SSE 和桌面 `think` 对所有者可见；commentary、推理摘要和未知通道排除。Harness 计划草拟继续选择不可变 `tutor.learning-plan-draft@1.0.3`，1.0.2 和更早版本保持不变。

<a id="2026-09-16artifact-platform-current-contract"></a>

## 2026-09-16：工件平台当前契约

焦点准入的 provider 前置校验与最终 Gate 共用 `teaching_focus_resolution_error`。当前 typed TeachingSession 的焦点集合是唯一依据：空/缺失 suspended_focuses 不允许 `resolve_and_resume_parent`，工件完成和 learner 文本也不创建父焦点。模型非法选择只通过原有有界同模型修正处理，不自动改写 action、不放宽最后的权威/版本校验。工件正确回执与后续教学成功是两条独立验收证据。

当前教学运行精确选择 `tutor.lesson-teaching@1.2.1` 与严格 `tutor.teaching-step-decision.v3`；1.0.0/1.1.0/1.2.0 包和历史回执不变。`TUTOR_LEARNING_ARTIFACTS_ENABLED`、`TUTOR_ARTIFACT_TEACHING_MODE_ENABLED` 仍默认关闭；每个所选 Artifact 均要求精确当前已发布句柄、Practice 物化、能力/运行时就绪及 TeachingSession/检查点校验边界。

schema 权威为排序清单，当前截至片段 240。阻断祖先分支/Artifact 退役由所属领域在保留内容的事务内处理，不是评分或完成事件。以回执为依据的知识检查反馈可复用教学策略；普通 Continue 和完全重复公开文本仍遵守防循环 Gate。正式 Gate/进度权威绝不从学习者声明或 Artifact 结果推断。

model-code-review v2 必须区分提交前绑定语义审查与提交后 Tutor 讲评：已实现语义 Gate 可在不可变结果保存前拒绝结构合法提交，后续教学文本不能修订结果。详细当前契约位于 `.trellis/spec/backend/model-review-artifacts.md`，此次文档对齐不改变评分行为。

早期带日期章节描述其自身日期的运行时。当前源码对齐、隔离回归、真实提供方可用性和执行器/容器就绪是独立证据边界，任何一个都不单独构成发布批准。
