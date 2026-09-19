<a id="aearn-数据库-schema-与持久化契约"></a>
# Aearn 数据库结构与持久化契约

**状态：** 当前数据库结构说明，2026-09-17。
**阅读说明：** 本次为 2026-09-17 本地源码静态核对；带日期的小节保留当时的契约演进与证据边界，较新修订优先，不代表本次执行了数据库、浏览器或真实提供方验收。
**权威来源：** `aearn/services/api/app/db/schema/__init__.py` 的显式清单、`aearn/services/api/app/db/schema/*.sql`、PostgreSQL 初始化、
Tutor/LearningTrack 数据仓储与数据库结构、受控切换测试。
**范围：** PostgreSQL 是 Tutor 运行、切换回执、后台队列和面向学习者的安全投影的唯一持久化权威来源；桌面端、Celery 和提供方不拥有并行
状态机或迁移账本。

<a id="1-bootstrap迁移与范围原则"></a>
## 1. 初始化、迁移与范围原则

- `python -m app.db.bootstrap` 按 `SCHEMA_FRAGMENT_NAMES` 的显式顺序重复执行 25 个数据库结构片段。数字前缀只帮助阅读，执行顺序不依赖目录自然排序。当前仓库没有另一个可与其竞争的 Alembic/Graph 迁移路径。
- 所有片段通过同一条由调用方管理的 PostgreSQL 连接执行，并由调用方统一提交事务；加载器不 `commit`。初始化使用事务级咨询锁，并对死锁或串行化失败做有界整事务重试，避免多进程启动或测试重复初始化留下部分数据库结构。
- `load_schema_text()` 只提供清单组合的只读视图；仓库不维护第二份聚合 `schema.sql`。
- `tutor_*` 与 `harness_cutovers` 是当前运行时的核心表族。所有可公开读取的
  内容必须从数据仓储的安全投影产生，不能直接把 JSONB、诊断轨迹或提供方
  数据返回到 API/SSE。
- 旧 `learning_*`、`review_*`、`notes`、`attempts`、`learning_plans` 等表仍在
  数据库结构中，以便服务器能够对已有本地用户做精确清点/删除、数据摘要、
  导出和已归档证据。它们不是当前桌面端/Tutor 运行时的写入目标。
- 服务器不把旧记录迁移到 `tutor_*`。经确认的清空式切换只删除精确界定的旧数据范围；回退只可能恢复代码，不会重建已删除历史。

## 2. 基础身份与课程表

| 表 | 当前作用 | 关键边界 |
| --- | --- | --- |
| `users` | 本地学习者身份、显示名称、时间段、通知偏好 | `id` 是所有按用户隔离的 Tutor 数据的根；身份和允许的通知偏好在受控切换中保留 |
| `language_courses`、`runtime_profiles` | 目录/环境安全读取模型 | 只通过课程/环境接口读取，不成为旧计划恢复入口 |
| `idempotency_records` | 历史业务的本地数据记录 | 受控切换按精确 `user_id` 删除；不与 Tutor API 幂等性混用 |

<a id="3-server-authoritative-cutover"></a>
## 3. 服务端权威切换

### `harness_cutovers`

主键是 `(user_id, cutover_version)`，当前版本为 `harness_clean_slate_v1`。

| 字段/状态 | 含义 |
| --- | --- |
| `state` | `required`、`summary_ready`、`verified`、`verification_failed`、`blocked_target_state` 或 `blocked_checkpoint_scope` |
| `summary_hash`、`summary_version`、`preview_nonce` | 服务器生成的可验证预览事实，不包含旧学习正文 |
| `confirmation_idempotency_key`、`confirmation_request_hash` | 一次性确认的安全重放/冲突检查 |
| `confirmed_at`、`verified_at` | 删除确认与可进入 Tutor 的时间事实 |
| `failure_code`、`failure_at` | 失败/阻塞的稳定安全码，非原始异常 |

只有 `verified` 状态才允许访问 `/api/tutor/*` 或执行要求切换已验证的后台工作。切换前存在任何用户所属的 `tutor_*` 行，都构成目标状态污染：服务器写
`blocked_target_state`，而不是删除或迁移新数据。

<a id="历史-scope-与-checkpoint"></a>
### 历史作用域与检查点

服务器只删除能证明归属当前用户的旧版行，并对
`aearn:learning:<learning_session_id>` 线程 ID 逐表检查
`checkpoints`、`checkpoint_blobs`、`checkpoint_writes`。未知表/命名空间、
`NULL` 线程 ID、未知学习线程或无法证明映射的记录都拒绝继续处理。

## 4. Tutor 对话、TurnRun、公开过程与可重放事件

| 表 | 责任 | 关键不变量 |
| --- | --- | --- |
| `tutor_conversations` | 按用户隔离的对话根记录，涵盖学习者可见对话与内部对话 | `visibility` 与 `kind` 区分公开交互和内部主动发起的对话；学习者对话的 `title` 只能保存安全模型简述，`NULL` 对外投影为“新对话”；`last_public_activity_at` 是列表排序权威来源；`next_public_event_sequence` 与 `control_version` 均从 1 开始 |
| `tutor_messages` | 规范的学习者/Tutor 公开消息正文及有长度上限的公开思考叙述 | 唯一允许存放原始学习者文本的 Tutor 表；新 Tutor 回复保存最多 1280 字符 `public_thinking_text`，旧版 `public_thinking_steps_json` 只读兼容，CHECK 禁止双表示同时非空；二者都不是提供方原生推理 |
| `tutor_message_context_references` | 学习者消息/运行修订的仅追加面向学习者的安全产物快照 | 复合 FK 固定用户/对话/运行/消息/输入修订；只保存有界安全投影/哈希，不复制学习者内容、提交内容、隐藏/私有产物或原始执行/提供方数据 |
| `tutor_catalog_snapshots` | 已审查 Skill 目录摘要快照 | 运行只能引用已持久化的摘要 |
| `tutor_codex_runtime_health` | 专用 `tutor-codex` 工作进程的共享就绪状态记录 | 仅保存有界状态/世代/版本/模型/提供方/协议/安全代码与心跳；新 Codex 准入必须读取身份精确匹配且足够新的健康状态行 |
| `tutor_runs` | 有限循环 / 公开回合的持久化快照 | `origin` 为 `interactive/proactive`；`runtime_kind` 在创建时冻结为 `harness_v1/codex_sidecar_v1` 且不可更新；`interaction_protocol_version` 区分 `legacy_v1/thread_turn_v2`；重试前任/根与 `response_to_request_id` 通过用户+对话限定作用域的 FK；租约、预算计数器、`input_revision`、终态结局、`completion_reason` 和 `next_event_sequence` 都由 DB 保护；新 v2 请求来源回合不持久化等待续接 |
| `tutor_interaction_requests` | 类型化学习者/权威来源阻塞请求与解决沿袭关系 | 种类/参与方闭合联合类型；部分唯一索引保证每个对话最多一条待处理请求；来源/答案回合与答案消息复合作用域；服务端管理的描述符/呈现、规划目录、批准身份、权威来源作用域/哈希、状态/版本/响应或回执哈希受 CHECK/FK/CAS 约束 |
| `tutor_provider_attempt_receipts` | 每个实际提供方 HTTP 尝试的仅追加用量事实 | 身份为 `(run_id,input_revision,decision_iteration,attempt_index)`；复合 FK 固定用户/运行/对话作用域；只保存受限提供方/模型/协议、结局/诊断和非负令牌数，不保存提示词、响应体、推理文本、URL/请求头或凭据 |
| `tutor_conversation_runtime_threads` | 对话限定作用域的 Codex App Server 线程权威来源 | 一个学习者对话/运行时至多一个活跃线程；外部身份不可变/私有；恢复/压缩只更新时间事实 |
| `tutor_run_runtime_bindings`、`tutor_runtime_item_receipts`、`tutor_runtime_public_errors` | 新运行/回合私有关联、仅追加安全回执与 Aearn 公开错误 | 外部线程/回合/条目身份不进入公共 DTO；绑定/回执受输入/租约/运行时世代隔离检查；回执不复制原始文本 |
| `tutor_runtime_text_items` | 按所属者隔离的原始推理/最终答案投影 | 推理与最终答案分通道；序号/哈希/状态/所属者/FK 受约束；过程说明/摘要不写入文本投影，只有安全最终答案关联正式 Tutor 消息 |
| `tutor_run_public_processes` | 一条新交互式运行对应一条服务端安全公开过程投影 | 只允许 `thinking/waiting_input/waiting_approval/waiting_authority/completed/interrupted/superseded/unavailable/failed`，只保留时间戳、关联公开 Tutor 消息和固定步骤键；不存推理、提供方载荷、提示词、诊断轨迹或工具参数 |
| `tutor_run_public_process_steps` | 仅追加公开过程步骤顺序 | `(run_id, ordinal)` 唯一；步骤键/状态均有 DB + 数据仓储允许清单；公开标签在读取投影映射而非存自由文本 |
| `tutor_run_skill_selections` | 精确 Skill 证据 | `(run_id, input_revision)` 唯一；保存 id/版本与清单/指令/评估哈希 |
| `tutor_run_input_events` | 已接受输入的修订/事件回执 | 普通消息与类型化响应/已验证权威来源回执都在新运行上从修订 1 开始；旧版续接才可能在旧运行增加修订；用于重放与过期副作用门禁 |
| `tutor_run_checkpoints` | 仅元数据的检查点 | 不保存组装后的提示词、原始历史或提供方载荷 |
| `tutor_run_events` | 单次运行内的有序事件日志 | `event_sequence` 在已锁定运行行上分配；SSE 只读取其安全后缀 |
| `tutor_conversation_events` | 面向学习者的安全对话全局仅追加事件日志 | 对话行锁分配严格递增序号；v2 种类包含有界 `turn_output`；`event_key` 幂等；回合/条目引用与载荷身份必须一致；普通 UPDATE/DELETE 被触发器拒绝 |
| `tutor_turn_public_thinking_streams` | 当前前台回合的可恢复公开思考前缀 | 每次运行仅一行；精确用户/对话/运行/修订/决策/世代/提供方尝试隔离检查；状态=`active|complete|discarded|accepted`；`active` 文本仅通过累计安全检查、仍是暂定内容，`complete` 表示完整提供方决策已验证并与流精确匹配；不保存原始提供方数据 |
| `tutor_interactive_dispatch_jobs` | 每次运行仅一行持久化交互式分发权威来源 | PostgreSQL 状态为 `pending/leased/retry_wait/completed/dead`；领取使用 `FOR UPDATE SKIP LOCKED`、所属者/世代/到期时间 CAS、有界重试/退避；Celery 仅是唤醒信号 |
| `tutor_queued_inputs` | 对话限定作用域的待处理输入权威来源 | `pending/claimed/cancelled` 闭合生命周期；待处理位置部分唯一；最多 10 项由对话锁保护；入队键、条目版本、已领取回合/修订/模式与原始结构化输入元数据可重放 |
| `tutor_capability_invocations`、`tutor_effects` | 能力/副作用回执 | 当前修订、租约、Skill 证据与策略必须同时通过；过期或已中断的副作用不调用处理器；副作用可保存重试根逻辑动作键，已提交语义动作全局唯一复用 |
| `tutor_run_traces` | 脱敏诊断轨迹 | 诊断轨迹写入和导出都再次走允许清单投影 |
| `tutor_api_idempotency_records` | 公开 Tutor / LearningTrack 写操作重放 | `(user_id, operation, idempotency_key)` 唯一；Tutor 输入与 `learning_track.*` 写操作都绑定请求哈希与安全响应 JSON |

`POST /conversations/first-turn` 的数据仓储写操作在一个事务内创建学习者
对话、新运行、首条学习者消息/输入事件和 `input_received` 过程；任何
中间失败都会回滚，不留下空对话。普通对话输入在对话锁
下仅在空闲时创建新运行；活跃、待处理请求或已暂停状态写入 `tutor_queued_inputs`。
部分唯一索引 `uq_tutor_runs_interactive_foreground` 继续保证每对话至多一个活跃
交互式前台运行，`uq_tutor_queued_inputs_pending_position` 保证待处理先进先出位置不重复。

历史与内部运行明确保持 `legacy_v1`；新建且学习者可见的回合显式写
`thread_turn_v2`。同一输入事务还会插入分发任务，并按回合创建、消息新增、
过程新增等所属写操作追加对话事件；任何一步失败都会连同消息/运行/任务/事件
整体回滚。v2 续接意图创建类型化请求并终结来源运行；响应/回执解决精确
请求后创建另一条新运行/任务。旧 `/runs/{run_id}/inputs` 的同一运行内的修订/任务重新激活属于历史兼容机制；当前该路由固定返回 HTTP 410，不得被新 v2 写操作调用。

队列编辑/删除/重排/领取与 `queue_paused/queue_pause_reason` 都在对话锁下执行。
领取事务才创建消息/运行/输入/过程/任务，并把条目写为已领取；重复队列排空因活跃运行
或条目状态 CAS 返回无操作。`logical_action_key` 由用户、对话、稳定重试根、副作用类型与
载荷哈希计算；同运行/副作用先走原回执重放，不同重试回合遇到已提交键复用提交 ID，
遇到已提议/含糊不明键拒绝继续处理。

对话事件载荷只保存回合或条目引用、控制版本、安全分发代码和
尝试，不复制学习者内容、Tutor 消息、提示词、推理、诊断轨迹、提供方响应正文或能力
参数。快照在学习者对话上持有共享锁，再读取活跃回合、类型化时间线与
当前序号；历史对话无事件回填时仍从消息/过程表投影，流游标
指向序号 0。分发任务最终 `dead` 时同事务终结运行、冻结失败过程、追加安全错误
条目投影与 `dispatch_dead` 事件。

终态约束：`tutor_runs.terminal_outcome` 与 `terminal_at` 必须同时为 `NULL` 或同时
存在。终态转换、安全事件、诊断轨迹与整理事务发件箱由同一事务维护，
避免暴露半完成状态。提供方返回后的生命周期写入再次检查取消/取代；
过期运行只能收敛到安全已取消/已取代投影，不能写 Tutor 消息、标题、
能力回执或副作用提交。
已经真实发生的提供方调用尝试是独立执行/成本事实：运行循环在提供方返回后、业务结果门禁前持久化其安全回执，因此已取代/已取消运行可以保留用量，但仍不能获得消息、标题、能力或副作用写权限。`input_tokens` 已包含缓存读取；`uncached_input_tokens = input_tokens - cached_input_tokens`，不得把已缓存再加回总输入。提供方报告的 `total_tokens` 与计算得到的 `input_tokens + output_tokens` 分列保存；用量缺失用 `usage_available=false` 与 `NULL` 表示，不能伪装成零。


<a id="2026-08-18codex-plan-drafting-受控切换"></a>
## 2026-08-18：Codex 计划起草受控切换

`tutor_codex_runtime_health` 是无学习者归属的共享基础设施。服务端策略只有在功能已启用且最新心跳对精确在允许清单中的运行时版本、`deepseek-flash`、`aearn_deepseek`、`responses`、世代和新鲜度全部通过时，才为全新 `plan_drafting` 对话冻结 `codex_sidecar_v1`。既有对话后续新回合与重试继承原运行时；队列条目只保存服务端冻结值，客户端字段不能影响。Harness/Codex 工作进程对同一持久化分发队列按 `runtime_kind` 精确领取，关闭准入不删除历史绑定/回执，也不让活跃运行跨运行时续跑。

<a id="5-learningtrack计划路线掌握度与教学-scope"></a>
## 5. LearningTrack、计划路线、掌握度与教学作用域

<a id="2026-09-13frozen-catalog-scope"></a>
### 2026-09-13：冻结目录作用域

增量片段 `220_plan_catalog_knowledge_scope.sql` 为 `tutor_track_plan_nodes`
增加可空 `catalog_knowledge_key`。INSERT 保护检查将非空映射与不可变修订
`plan_json` 中的同节点映射/能力对照，并验证同语言、能力兼容的已发布目录；
旧 null 行与其哈希不被回填改写。`tutor_plan_catalog_knowledge_key` 按
用户/学习路线/修订/节点精确解析，`tutor_artifact_catalog_knowledge_key` 经 Artifact
绑定的 TeachingSession 冻结修订解析。不存在或跨作用域时拒绝继续处理。
Artifact/Attempt 所属者保护检查只用映射检查内容身份，根 `knowledge_key`、会话/
分配/版本保护检查和正式 Gate 的进度所属者仍保持原路线节点身份。
修改映射必须发布新计划修订；不得重标已发布条目、复用其他节点成绩或
改写旧会话/Attempt。仅内容映射并不构成学习完成、真实执行或独立内容覆盖证据。

LearningTrack 是新增的按学习路线隔离的教学权威状态，与旧 `learning_*` 表以及
用户级别 `tutor_plan_revisions` 明确隔离：

| 表 | 责任 | 关键不变量 |
| --- | --- | --- |
| `tutor_learning_tracks` | 用户 + 语言 + 目标的长期主线根 | `(id,user_id)` 复合作用域；`version` 用于 CAS；当前节点 FK 只能指向同学习路线进度 |
| `tutor_track_plan_revisions` | 前任已关联完整计划版本 | 前任不得自指；规范 `plan_json` / SHA-256 不可普通 UPDATE/DELETE；状态转换与激活时间戳由触发器收口；每学习路线部分唯一活跃修订，延迟约束保证指针/修订一致 |
| `tutor_track_active_plans` | 学习路线唯一活跃指针 | 修订、学习路线、用户必须为同一复合作用域 |
| `tutor_track_plan_modules`、`tutor_track_plan_nodes` | 修订内不可变路线结构 | 稳定键/顺序唯一；模块/节点普通 UPDATE/DELETE 被触发器拒绝；前置条件 DAG 在应用契约验证 |
| `tutor_track_node_progress` | `(track_id,knowledge_key)` 长期进度 | 稳定键跨修订保留；来源修订必须在同学习路线/用户作用域内真实包含该知识键；状态与 started/已完成时间戳双向一致 |
| `tutor_track_plan_migrations` | 提案/激活影响与 CAS 回执 | 从/到修订同学习路线/用户；影响、预期版本、幂等性/请求哈希不可原地改写；生命周期触发器约束已提议/已确认/已拒绝/已应用与时间戳 |
| `tutor_mastery_evidence` | 仅追加可信证据 | 回执在学习路线 + 种类内唯一；普通 UPDATE/DELETE 均被触发器拒绝；不能由模型正文直接生成 |
| `tutor_mastery_states` | 投影器可重算的有界状态 | 只引用同进度/证据作用域；零证据与 `last_evidence_id=NULL` 一致 |
| `tutor_conversation_learning_scopes` | 对话的通用/规划/学习路线绑定 | 学习路线作用域必须引用同用户学习路线；无行的旧对话投影为通用 |
| `tutor_run_learning_scopes` | 新建 TurnRun 创建时的不可变任务/作用域快照 | 运行/用户/对话/学习路线/进度复合 FK；续接不得 UPDATE 快照 |
| `tutor_learning_plan_sessions`、`tutor_learning_plan_drafts` | 规划生命周期与不可变类型化草案 | 会话保存事实策略版本；草案保存生成时的事实指纹/修订，确认时必须仍匹配当前投影 |
| `tutor_planning_intake_facts` | 仅追加类型化接收事实权威来源 | 字段/值/修订/来源证据都受用户/会话/对话/运行/输入复合作用域；纠正追加后继，当前事实是没有 `supersedes_fact_id` 后继的已确认叶节点 |
| `tutor_planning_question_events` | 仅追加稳定问题状态沿袭关系 | `question_key=field_key`；`previous_event_id` 每个前任最多一个后继；当前状态从叶节点沿前任链解析，不能使用 `created_at` 或 UUID 猜测事务内顺序 |

PostgreSQL `now()` 在同一事务内稳定，因此同次输入写入的重新开启、取代和
已确认事件可以拥有相同 `created_at`。规划问题当前投影必须先找
`previous_event_id` 没有后继的真实叶节点，再沿显式沿袭关系回溯；
`uq_tutor_planning_question_events_previous` 阻止链分叉。`reasked_blocked` 是审计事件，
读取对外问题状态时跳过该节点并继续使用其前任状态。

计划激活先锁学习路线并校验 `expected_track_version`、直接前任与迁移
状态，再切换修订/指针。相同 `knowledge_key` 的进度/掌握度保留；新键
依据其前置条件的已完成状态初始化为可用或已锁定。移出活跃计划的旧
进度/证据不在激活时删除，路线图/进度汇总只读取活跃修订
节点。

`MasteryProjector` 只消费已持久化可信证据摘要，按独立性权重产生
`confidence`、`mastery_level`、优势/薄弱项与投影器版本。它不依赖提供方，
同一有序证据集可确定性重算。

本地数据摘要/导出包含 LearningTrack、修订、节点/进度与有界掌握度
状态，但不导出原始 `plan_json` 或证据正文/哈希。已确认重置/删除先将该
用户仍活跃的交互式运行安全终结，再在事务本地清理能力
下按运行/对话作用域 -> 掌握度 -> 进度/迁移 -> 节点/模块 -> 活跃指针 ->
子表优先修订 -> 学习路线的外键顺序清理，并删除该用户 API 幂等性；受控切换
清点将任一新学习路线/作用域/证据行视为目标状态污染，绝不在切换中删除。

<a id="6-skillscapabilityeffects-与执行器"></a>
## 6. 技能、能力、副作用与执行器

- Skills 以 Git-owned 目录的精确 `id@semantic-version` 选择，永久保存
  证据哈希。别名、范围、`current` 与未知 Skill 不能成为持久化证明。
- 能力/副作用描述符只允许声明字段；模型正文不能成为 URL、文件路径、
  shell/SQL、用户 ID、镜像、命令或数据库目标。
- `tutor_execution_intents`、`tutor_execution_jobs`、
  `tutor_execution_attempts`、`tutor_executor_health` 是显式仅
  容器执行器的持久化队列/健康状态事实。API、普通工作进程和
  桌面端不导入运行时客户端，也没有宿主子进程降级。
- Proactive 来源永远不允许 `runner.execute` 或学习者代码执行。

<a id="7-proactive-scheduler-与-curation-队列"></a>
## 7. 主动任务调度器与整理队列

| 表 | 责任 | 默认/安全边界 |
| --- | --- | --- |
| `tutor_proactive_preferences` | 每用户 `enabled` 与 `hard_paused` | 默认 `enabled=true`、`hard_paused=false`；初始化将旧的未暂停已禁用偏好恢复为已启用 |
| `tutor_proactive_signals` | 安全信号、来源哈希、去重/处置结果 | 交互式终态元数据仅含运行 ID/结局/时间哈希；不保存消息/提示词/代码/诊断轨迹/提供方诊断 |
| `tutor_proactive_candidates` | 持久化候选、租约、重试、不执行动作 | `(user_id, dedupe_key, dedupe_bucket_at)` 唯一；已验证门禁/暂停/预算/冷却期/并发/熔断必须通过 |
| `tutor_scheduler_audit` | 调度器决策证据 | 仅保存安全代码/详情，支持审计不泄露内容 |
| `tutor_memory_curation_outbox`、`tutor_curation_proposals` | 脱敏压缩/提案信封 | 非原始提供方载荷存储 |
| `tutor_curation_jobs` | 整理租约/重试生命周期 | 默认预算/输出令牌为 0，推断出的记忆默认关闭 |
| `tutor_curation_projection_receipts` | 正常策略/服务校验后的投影结果 | 只能记录已提交/不执行动作/过期/失败的安全事实 |

生产 `scan_due_signals` 的 `user_id=None` 语义是全局队列扫描。数据仓储支持
显式用户作用域仅供测试夹具/维护隔离；它不能改变正常工作进程的
全局行为。

<a id="8-learner-state-projections"></a>
## 8. 学习者状态投影

| 表 | 当前业务事实 | 不变量 |
| --- | --- | --- |
| `tutor_plan_revisions` | 不可变计划修订 | 修订含证据、差异与前任；不会写旧 `learning_plans` |
| `tutor_active_plans` | 唯一可变活跃指针 | 只能指向当前用户修订 |
| `tutor_plan_revision_actions` | 仅追加激活/回退动作 | 用户回退只可回到直接前任 |
| `tutor_memory_preferences` | 推断出的记忆设置/版本 | 设置版本使过期已排队工作失效 |
| `tutor_memory_entries` | 目标事实或推断 | 纠正追加替代；删除是受控状态转换 |
| `tutor_context_summaries` | 安全已压缩上下文投影 | v2 绑定对话、数据库结构/策略、结构化 JSON、覆盖、来源哈希与先前沿袭关系；UPDATE 被仅追加触发器拒绝，旧版短摘要可保留但不进入 v2 加载器 |
| `tutor_activity_records` | 仅追加面向学习者的安全活动 | 可从副作用/运行追溯，但不含内部载荷 |
| `tutor_inbox_items` | 一条活动对应的可读/隐藏投影 | `unread/read/dismissed` 生命周期与时间戳约束 |

### 8.1 长对话结构化摘要

`tutor_memory_curation_outbox.projection_kind` 区分旧的 `memory_or_summary` 与
`context_summary`。v2 事务发件箱必须同时具备精确数据库结构/策略版本、连续退休消息
ID/哈希、对话覆盖游标、来源哈希，以及成对的先前摘要
身份/哈希；相同语义证据在高水位与终态生命周期之间共用一个
整理幂等键。`tutor_curation_jobs.projection_kind` 必须与事务发件箱一致。

`tutor_context_summaries` 的 v2 行通过复合 FK 证明用户/运行/对话、
事务发件箱、已覆盖消息与先前摘要均在同一作用域。结构化列必须整组存在，
`source_hash`/`prior_summary_hash` 为 SHA-256，并使用
`(user_id, conversation_id, covered_through_created_at DESC,
covered_through_message_id DESC)` 检索最新覆盖。摘要内容不可原地 UPDATE；
纠正通过追加新行。用户级重置/删除可按既有依赖顺序物理删除摘要
投影，但不能因此删除或改写 `tutor_messages`。公开导出默认不暴露内部
`summary_json`。

## 9. 公开投影与删除规则

- 数据仓储是唯一可将表行转成 API/SSE 载荷的层；SQL/JSONB 不得被路由
  直接串行化为用户输出。
- `tutor_messages` 的原始学习者内容不复制到事件、诊断轨迹、事务发件箱、
  收件箱、活动、能力/副作用/提供方尝试回执或幂等响应。
- 所有按用户隔离的查询/写操作都显式带用户 ID；复合外键、唯一约束、
  租约世代、CAS 和 `FOR UPDATE SKIP LOCKED` 防止跨用户和重复工作进程写入。
- 删除本地用户是显式已确认用户数据操作。受控切换不是“重置”捷径，且
  切换前的目标状态不能用普通重置清空。

## 10. 历史表与当前读取规则

旧表仍可能包含 `learning_plans`、`plan_modules`、`knowledge_points`、
`exercises`、`attempts`、`review_states`、`review_logs`、`notes`、
`onboarding_*`、`learning_messages` 和 `review_messages`。在当前代码中：

- 它们不构成 `/api/tutor` 的输入、上下文、副作用或 UI 状态。
- `harness_cutovers` 只能把它们作为服务端清点/删除目标，
  并在成功后验证同一作用域已清空。
- 历史概念如 Attempt、FSRS、隐藏测试与来源归因不会被 Tutor
  API 重建、展示或静默写入；历史归档不会被当作当前运行时来源。

<a id="11-schema-验证"></a>
## 11. 数据库结构验证

执行顺序必须串行，避免共享 PostgreSQL 初始化测试夹具并发导致死锁或
`tuple concurrently updated`：

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/database/test_db_bootstrap.py tests/learning/test_learning_track_repository.py tests/integration/test_harness_cutover.py
uv --directory .\aearn\services\api run python -m pytest tests/tutor/test_tutor_run_repository.py tests/tutor/test_tutor_proactive_default_delivery.py
```

完整命令、结果和残留风险以
[发布就绪记录](../qa/tutor-harness-release-readiness.md) 为准。

## 2026-08-10：计划制定持久化

`tutor_learning_plan_sessions` 是用户/对话限定作用域的规划根，同一用户最多一条 `collecting | draft_ready` 会话；它保存当前草案指针、确认学习路线、版本、事实策略版本与在允许清单中的安全错误，不保存原始提示词/历史/提供方响应正文/推理。`tutor_learning_plan_drafts` 保存确认所需的资料、规范计划、注册表管理的来源摘要、内容哈希、来源运行/修订，以及生成时的事实指纹/修订；草案仅追加，`(session_id,draft_version)` 与 `(source_run_id,source_input_revision)` 唯一。当前指针使用可延迟复合 FK 保证草案属于同一用户/会话。

`tutor_planning_intake_facts` 与 `tutor_planning_question_events` 增量地补足草案前的
规划权威来源。事实纠正和问题转换都追加行，不原地改写；复合 FK
把来源消息/运行/输入修订锁定到同一用户/会话/对话。本地导出仅
输出规范化值、沿袭关系/来源身份与安全状态，显式省略值/事件哈希和
门禁原因；重置/删除按问题叶节点到根、事实修订从高到低、草案、
会话的顺序清理。受控切换目标清点已将四张规划表全部视为目标状态。

<a id="2026-08-11lessondocument-authority"></a>
## 2026-08-11：LessonDocument 权威

`tutor_lesson_documents` 保存共享不可变标准文档与用户/按学习路线隔离的
个性化文档。标准行没有用户/学习路线所属者；个性化行必须引用匹配语言和 `knowledge_key` 的标准文档、活跃计划修订、资料哈希和可选前任。规范块、覆盖、Gate 槽位和引用集合进入内容哈希。

`tutor_lesson_source_snapshots` 在发布事务中复制注册表/版本/URL/章节、依据定位分块 ID、原始文档哈希、分块哈希、抓取/冻结时间和有界摘录；它不对可替换的 `grounding_chunks` 建立删除阻塞 FK。`tutor_lesson_block_citations` 和 `tutor_lesson_gate_slots` 冻结块到来源与公开 Gate 契约。

`tutor_lesson_assignments` 保证每个 `track_id + knowledge_key` 最多一个活跃分配。开始后 `started_at`、文档身份与激活沿袭关系不可改写；更新先创建直接已提议后继。`tutor_lesson_authoring_runs` 保存待处理/已领取/运行中/终态、租约、预期版本、来源集合、安全失败和结果身份；`tutor_lesson_authoring_attempt_receipts` 只保存仅追加提供方/模型/协议/结局/用量/哈希元数据。

本地导出包含个性化块、分配与引用元数据，但省略证据摘录全文、提示词/正文/推理和内部质量详情。重置/删除在事务本地清理能力下从子级到根级删除用户拥有的 Lesson 行；共享标准文档与其来源快照保留。受控切换目标清点只统计个性化文档、分配和编写运行，不把共享标准内容归给某个用户。

<a id="2026-09-08lesson-attempt-安全诊断"></a>
### 2026-09-08：Lesson 尝试安全诊断

`tutor_lesson_authoring_attempt_receipts.diagnostic_json` 为 `jsonb NOT NULL DEFAULT '{}'`，数据库 CHECK 要求对象。新建创建和增量 `ADD COLUMN IF NOT EXISTS` 同时维护；历史行保持空对象兼容，无新增用户拥有的表或删除顺序变更。

2026-09-08：应用侧私有诊断继续读取空对象和 `lesson_author_attempt_diagnostic_v1`；新响应元数据使用 `lesson_author_attempt_diagnostic_v2`，增加封闭的 `provider_response`（状态、截断原因枚举、请求输出额度/思考强度、可见输出字符数）与可空的 `reasoning_tokens`。未知用量保留 NULL；推理是输出的子集，不再次累加总用量。不得存入原始响应、思考正文或任意提供方错误文本；公共 API/SSE/用户导出不投影这些诊断。复用现有 JSONB 列，不需要新增数据库迁移或回填历史记录。

新诊断只允许版本、标准/个性化文档种类、文档内尝试索引、失败阶段、稳定问题代码/位置和反馈哈希。约束文本、提示词、提供方响应正文、推理、原始候选、凭据不持久化。回执的成功只在解析/身份/质量全部通过后记录；每次失败仍单独记录，`(run_id, attempt_index)` 身份、仅追加触发器和用量缺失时 NULL 语义保留。

<a id="2026-08-11练习-gateattempt-与模块诊断-authority"></a>
## 2026-08-11：练习 Gate、Attempt 与模块诊断权威

新练习权威来源由十二张增量表组成：`tutor_exercise_versions`、`tutor_exercise_private_rubrics`、`tutor_lesson_gate_bindings`、`tutor_lesson_gate_states`、`tutor_module_diagnostic_versions`、`tutor_module_diagnostic_sessions`、`tutor_module_diagnostic_items`、`tutor_exercise_attempts`、`tutor_exercise_attempt_submissions`、`tutor_exercise_attempt_results`、`tutor_exercise_hint_receipts` 和 `tutor_exercise_execution_links`。共享练习/诊断版本与私有量规不属于单个用户；绑定/状态、Attempt、提交内容/结果/提示、诊断会话/条目和执行关联通过复合 FK 固定精确用户/学习路线/计划/Lesson/诊断作用域。

`gate_kind=knowledge_check | guided_practice | independent_practice` 继续描述 Lesson 教学形态；`requirement_kind=required | recommended | diagnostic` 单独控制路线阻塞。绑定和练习/量规由规范哈希/版本冻结。Gate 状态只允许 `available | in_progress | passed | remediation_required` 的受控生命周期；Attempt、提交内容、结果、提示与执行关联为仅追加/不可变，普通 UPDATE/DELETE 被触发器拒绝。

`tutor_exercise_attempts` 使用所属者结构 CHECK 分离 Lesson `run | submit` 与模块 `diagnostic_submit`。完整提交只保存在 `tutor_exercise_attempt_submissions.content_text`，公共读取和导出只投影哈希/摘要。终态 `tutor_exercise_attempt_results` 每个 Attempt 最多一条；必需提交的结果、掌握度证据、Gate CAS、进度完成和解锁在同一数据库事务内恰好一次投影。`run` 结果不进入 Gate/掌握度/进度。

现有 `tutor_execution_intents` 通过 `source_kind=tutor_message | exercise_submission` 扩展，`tutor_execution_jobs` 通过 `owner_kind=tutor_effect | exercise_attempt` 扩展；两者使用精确多选一 CHECK 和复合 FK 保留旧 Tutor 作用域，同时允许 Gate 复用同一领取/租约/启动令牌/终态队列。Gate 路径不创建 Tutor 对话/消息/副作用。`tutor_exercise_execution_links` 固定 Attempt 到既有意图/任务的一对一关系。

`tutor_mastery_evidence.evidence_effect` 区分 `reinforcing` 与 `observational_non_degrading`。失败或部分通过的模块诊断只追加观察/薄弱项，不降低既有置信度；全部核心能力独立达到版本化阈值后，会话才可引用前任已关联已提议计划修订。只有确认事务可把会话置为 `confirmed`、激活后继、写 `diagnostic_skipped` 并重算下游可用性。

本地导出省略完整提交内容、隐藏/私有量规/参考答案和内部执行信息；重置/删除/受控切换在事务本地清理能力下按执行关联/结果/提示/提交内容/Attempt/Gate/诊断从子级到根级清理用户拥有的行。共享经整理的练习/诊断版本与私有量规保留。初始化两次必须重复成功，并断言所属者/来源多选一、作用域 FK、唯一性、不可变性/生命周期触发器和索引存在。


<a id="2026-08-12受控-action-runtime-持久化"></a>
## 2026-08-12：受控操作运行时持久化

`tutor_action_invocations` 保存统一动作编排身份、精确描述符/适配器、
运行/输入修订、租约所属者/世代、动作世代、幂等性/稳定键、目录/策略
证据与资源指纹；不保存原始参数。其生命周期由数据库触发器与应用同一
迁移表约束，终态不可更新或普通删除。`tutor_action_attempts`、
`tutor_action_verifications`、`tutor_action_receipts` 都是仅追加证据；只保存安全状态、
权威来源引用/哈希、结果/验证哈希、稳定诊断/恢复代码与有界安全 JSON。

Action 表不复制领域事实：`capability_invocation` 指向现有能力回执，`plan_draft`
指向不可变计划草案，`execution_job` 指向现有执行任务/结果，未来副作用仍指向
原副作用回执。`(run_id,idempotency_key)` 防止同键重复执行；当前已验证部分
唯一索引 `(run_id,input_revision,stable_action_key)` 防止同修订的语义重复动作。
复合外键固定调用/回执的运行、用户、对话作用域，父级/重试沿袭关系只能
留在同一运行。

Action 预留必须匹配当前 `tutor_runs` 的输入修订、精确活跃租约所属者/世代、
未过期租约、目录摘要、策略指纹与非终态/已取消/已取代状态。
本地导出只返回有界动作摘要，不返回原始结果/哈希；已确认重置使用既有
事务本地清理能力按回执 -> 验证 -> 尝试 -> 调用顺序删除。
受控切换清点将四张动作表视为目标状态，不会在切换中静默清除。


<a id="2026-08-12模型代码审核-authoring-与发布-authority"></a>
## 2026-08-12：模型代码审核编写生成与发布权威

`tutor_model_review_authoring_runs`、`tutor_model_review_authoring_attempt_receipts`、
`tutor_model_review_candidates`、`tutor_model_review_validation_runs`、
`tutor_model_review_validation_checks`、`tutor_model_review_publications` 与
`tutor_model_review_evidence_receipts` 保存用户/学习路线/Gate 限定作用域的的生成、受控验证、发布和
学习者辅助事实。候选公共题面与私有量规/测试载荷分列并各自哈希；
提供方候选只保存教学标题、学习者说明和候选代码，服务端管理的私有载荷保存
受控测试 DSL、预期结局、发现项/量规/证明、分数策略以及完整
`template_id + template_version + template_contract_hash`。只有
`model-code-review.validate@1.0.0` 的已验证权威来源才能原子发布
`tutor_exercise_versions` / `tutor_exercise_private_rubrics` 与精确 Gate 绑定。

共享执行队列新增 `source_kind=model_review_candidate` 与
`owner_kind=model_review_validation`，仍复用既有意图/任务/尝试、已审查运行时锁、
租约、重试、取消与终态契约。可信输入解析器只在精确已领取作用域读取
私有 DSL，并在沙箱传输载荷中剥离模板测试 id、`candidate_expected_pass` 和
`proof_ids`；这些元数据只用于 API 侧验证结果与服务端模板预期是否一致。学习者提交为
`structured_answer`，完整 JSON 只
保存在私有提交内容表；导出只投影判定与用户发现项的 id/种类/行/类别/
严重程度摘要。私有候选、量规、测试、匹配器、证明与提交内容自由文本均省略。

Authoring 对候选/校验/发布的环形引用使用 `ON DELETE NO ACTION
DEFERRABLE INITIALLY IMMEDIATE`。`RESTRICT` 即使标记 `DEFERRABLE` 仍会立即检查，不能用于
事务本地从子级到根级清理。已确认重置先终结内部主动发起的运行，
删除证据/动作/执行/检查/发布/校验/候选/作者回执/编写，
再删除该编写独占的内部运行/对话；去个性化的不可变已发布
练习/量规保留。受控切换清点将上述七张用户拥有的表显式计为目标状态。

<a id="2026-08-12track-scoped-reviewsession-与调度-authority"></a>
## 2026-08-12：路线作用域的 ReviewSession 与调度权威

正式复习由七张增量用户拥有的表组成：`tutor_review_schedule_states`、
`tutor_review_schedule_events`、`tutor_review_sessions`、
`tutor_review_warmup_receipts`、`tutor_review_items`、
`tutor_review_hint_receipts` 和 `tutor_review_finalizations`。调度状态对
`track_id + knowledge_key` 唯一，并用复合 FK 固定用户/学习路线/计划修订；事件、热身、
提示和终结是仅追加回执。会话生命周期为
`blocked | active | ready_to_finalize | finalized | cancelled`，被阻塞保持可恢复且不会占用
第二个活跃会话身份。

`tutor_exercise_attempts` 的所属者结构增加 `review_submit`：必须同时绑定精确
`review_session_id + review_item_id + track_id + plan_revision_id + knowledge_key`，并保存预期
复习会话/条目版本。每个复习条目最多一个 Attempt；提交内容/结果继续使用既有
私有产物和不可变终态结果。执行依赖题复用 `tutor_execution_intents`、
`tutor_execution_jobs` 与 `tutor_exercise_execution_links`，不新增队列或 Tutor 对话。

热身/提示/中间 Attempt 不更新长期掌握度/调度。唯一终结在一个事务中锁定
会话、学习路线、调度和终态 Attempts，写一条 `tutor_review_finalizations`、一条
`tutor_review_schedule_events`、一条 `tutor_mastery_evidence(evidence_kind='review')` 并 CAS 更新
`tutor_review_schedule_states`。计划修订激活按稳定 `knowledge_key` 写保留的/已暂停
迁移事件；确认的模块诊断跳过建立低频调度。actionable 到期数量查询包括普通
`due_at <= now()` 和 `risk_level='critical'`，后者仅在其为当前节点前置知识时投影短 Gate。

本地导出只包含调度/会话/终结的有界摘要和 Attempt 所属者 ID，不导出
上下文快照/哈希、selection 原因、完整提交内容、私有量规/测试或事件状态 JSON。
重置/删除使用既有事务本地清理能力，按终结/事件/提示/结果/
提交内容/Attempt/条目/热身/会话/调度的 FK 逆序清理。受控切换清点显式统计七张
复习表；初始化两次必须断言所属者 CHECK、复合 FK、唯一索引、生命周期/不可变触发器
和可重复增量迁移。


<a id="2026-08-12tutor-message-context-reference-authority"></a>
## 2026-08-12：Tutor 消息上下文引用权威

`tutor_message_context_references` 是用户拥有的仅追加表。每行保存精确
`user_id + conversation_id + run_id + message_id + input_revision + reference_index`，并用复合 FK 确保学习者
消息、运行和输入事件属于同一作用域。`(run_id,input_revision,reference_index)` 与
`(message_id,reference_index)` 唯一；`reference_kind` 只允许 `lesson_selection | exercise_feedback |
execution_result | review_feedback`。普通 UPDATE/DELETE 由不可变触发器拒绝，用户级已确认清理才能按
从子级到根级路径删除。

表中的 `safe_payload_json` 必须符合 `tutor_context_reference_v1`，`safe_payload_hash` 是规范 JSON SHA-256。
产物身份列只保存必要的学习路线/知识/文档/尝试/复习会话/练习版本/来源版本/哈希；
公开读取会重新校验安全载荷哈希。Lesson 安全快照保存服务端重建的有界摘录；Attempt/Review 快照
只保存终态结局、分数、辅助、安全反馈、能力 scores 和公开时间；执行快照只增加安全
任务身份/状态。不得存学习者消息的副本、完整提交内容、私有量规/测试/参考答案、原始 stdout/stderr、
命令/路径/容器、提供方响应正文、推理、凭据或密钥。

Tutor 输入在外层事务中先创建/锁定消息、运行输入事件与不可变运行作用域，再验证来源产物并插入全部
引用行；任何来源/作用域/版本/哈希/终态校验失败都回滚整条输入。History 按消息 + 引用索引
重放，上下文加载器按运行 + 输入修订读取，因此后续 Lesson 迁移、Review 调度更新或产物指针变化
不会改写既有快照语义。

本地导出仅输出安全引用投影与哈希；重置/删除在删除 Tutor 消息/运行前先删除引用。受控切换目标
清点把该表视为 验证前的目标状态。初始化两次必须断言复合 FK、唯一索引、种类 CHECK、不可变触发器
和可重复增量数据库结构均存在。

<a id="2026-08-12最终-schema-与迁移清单审计"></a>
## 2026-08-12：最终数据库结构与迁移清单审计

`HarnessCutoverService` 的目标清点现在逐表列出每个用户拥有的 `tutor_*` 表，包括运行/消息/运行事件/对话事件/交互式分发任务/诊断轨迹/检查点、Action、执行尝试、Lesson 来源/引用/Gate 槽位/编写回执、Review 与上下文引用 descendants。只有无学习者归属的 `tutor_catalog_snapshots`、`tutor_executor_health`、去个性化 `tutor_exercise_versions` / `tutor_exercise_private_rubrics` 与 `tutor_module_diagnostic_versions` 被显式归类为共享。

`test_cutover_inventory_explicitly_classifies_every_tutor_table` 读取真实 PostgreSQL `information_schema.tables`，要求数据库结构中所有 `tutor_*` 表恰好等于目标清点与共享允许清单的并集；新增表若未分类会直接失败。目标任一行存在都会阻断清空式切换，防止把当前 Tutor/LearningTrack 状态与旧数据混合删除。

迁移策略保持非转换：旧 `learning_*`、用户级别 Tutor 计划、旧复习/notes、旧检查点只参与精确清点/deletion，不会生成 LearningTrack、Lesson、Attempt、掌握度或 ReviewSession。普通重置/删除清理当前用户拥有的学习状态和私有提交，但保留共享不可变练习/目录；功能回退不执行数据删除，也不把已验证回执回退为旧运行时入口。


## 2026-08-14：类型化请求与权威续轮

`tutor_interaction_requests` 使用 `(id,user_id,conversation_id)` 与 `(item_id,user_id,conversation_id)`
复合身份，`source_turn_id`、`answer_turn_id`、`answer_message_id` 和
`tutor_runs.response_to_request_id` 不能跨用户/对话。`state=pending` 时响应/回执哈希、
答案沿袭关系与 `resolved_at` 必须为空；已解决状态必须有 `resolved_at`。部分唯一索引
`uq_tutor_interaction_requests_pending_conversation` 保证同一对话最多一个阻塞请求。

`planning_input` 只能保存七个在允许清单中的键与 `tutor_planning_questions_v1`；批准必须保存
服务端管理的提案身份/权威来源键/风险；权威来源请求必须保存精确请求哈希，回执
则绑定签发方/主体/作用域/请求/结果哈希与验证结果。公开投影从类型化 columns 和
在允许清单中的 JSON serializer 构造，不直接回放提供方 JSON。受控切换目标清点已显式包含该表。


<a id="2026-08-14threadturn-v2-全局-cutover-authority"></a>
## 2026-08-14：线程/轮次 v2 全局切换权威

`tutor_thread_turn_cutovers` 保存单例状态/世代/摘要哈希/安全数量/块代码/operator 幂等性/时间戳；`tutor_thread_turn_cutover_events` 是仅追加安全审计。两表是共享基础设施。preparing 下旧版等待运行失败并要求新建 v2 回合，其他可取消活跃运行立即已取消/清租约；含糊不明副作用/动作回执保持原状并使 singleton 被阻塞。enable 只允许就绪的精确世代+摘要，回退只回到就绪/读取仅，不恢复旧版写操作或数据。

<a id="2026-08-15tutor-公开思考文本流-authority"></a>
## 2026-08-15：Tutor 公开思考文本流权威

`tutor_messages` 增量新增 `public_thinking_text text NOT NULL DEFAULT ''` 与
`char_length <= 1280` CHECK；`chk_tutor_messages_public_thinking_single_representation` 要求
新文本非空时 `public_thinking_steps_json` 必为空。旧 步骤 不回填、不改写，读取层以
`"\n\n"` 连接为统一纯文本；新消息只写文本列。

`tutor_turn_public_thinking_streams` 以 `run_id` 为主键，并通过
`(run_id,user_id,conversation_id)` 复合 FK 固定作用域。`input_revision`、
`decision_iteration`、`generation`、`provider_attempt` 建立过期隔离检查；状态仅为
`active | complete | discarded | accepted`，时间戳 CHECK 保证状态与
`completed_at/discarded_at/accepted_at` 一致。`thinking_text` 最多 1280 字符，
`next_chunk_sequence >= 1`，可选 `last_public_event_sequence` 复合 FK 指向同对话事件。

begin/追加/重置/完整/丢弃每次都锁定当前运行/流，验证前台、租约、修订、
世代后，在同一短事务更新文本并追加 `turn_output`。`append` 只写累计安全的暂定内容
前缀；提供方传输 EOF 只结束投影器解析，不得把流置为 `complete`。只有完整决策
通过数据库结构/领域/安全校验并与流式输出的文本精确匹配后，gateway 才调用完整。成功终态消息
或类型化请求必须在同一事务比较最终决策文本、写规范公开条目、把流置为
`accepted` 并追加所属对话事件；任一步失败全部回滚。repair、上下文 rebuild、Interrupt、
取代、过期修订、租约丢失或失败路径只能重置/丢弃，不得接受旧世代。

该表纳入受控切换目标清点、本地导出/重置/删除子表优先清单与初始化两次
验证。公共表只保存面向学习者的安全文本；原始 JSON、提供方推理/正文/事件、提示词、诊断轨迹、
诊断、凭据和密钥禁止落入该表、消息列或对话事件。

<a id="2026-08-20conversation-runtime-thread-与-raw-text-projection"></a>
## 2026-08-20：会话运行时线程与原始文本投影

| 表 | 责任 | 关键不变量 |
| --- | --- | --- |
| `tutor_conversation_runtime_threads` | 一个学习者对话对应的持久 Codex App Server 线程 | 所属者/对话限定作用域的 FK；每对话/运行时最多一个活跃行；固定 `deepseek-flash` + `aearn_deepseek`；外部身份不可变/私有；记录原生/adopted 旧版/reseed 沿袭关系与恢复/压缩时间 |
| `tutor_run_runtime_bindings` | 新建 TutorRun 到同对话线程内一个新 Codex 回合的绑定 | 增加对话线程 FK；运行仍唯一，外部回合唯一；不再要求外部线程在运行绑定中唯一；输入/租约/连接世代隔离检查仍控制投影 |
| `tutor_runtime_text_items` | 按所属者隔离的原始推理与最终答案当前/历史投影 | `(binding, external item hash, channel)` 唯一；通道/状态/序号/哈希/连接世代闭合；流式可追加，已完成/discarded/被阻塞终态不可变；已完成条目仅允许一次关联同对话正式消息 |

`reasoning` 和 `final_answer` 原始文本只存在 `tutor_runtime_text_items`，不得复制进运行时回执。阶段校正为过程说明或任意回合终态遇到未完成条目时，必须把行转为 `discarded`，同时将 `text=''`、`content_hash=NULL` 并写入终态时间，禁止留下可恢复的过程说明或永久 `streaming` 行。`tutor_runtime_item_receipts` 仍只保存事件/条目种类、序号、哈希、安全代码、投影状态和 Aearn 公开引用；过程说明/摘要只能形成 nonpublic 回执。新表纳入初始化两次、受控切换清点、所属者作用域 FK 和事务本地清理保护检查。删除顺序必须先文本条目/回执/错误，再运行绑定，再对话线程，最后才允许删除所属运行/对话。

<a id="2026-08-21-course-intent-taxonomy"></a>
## 2026-08-21: 课程意图分类

| 表 | 用途 | 边界 |
| --- | --- | --- |
| `tutor_learning_intents` | 共享、闭合的规划方向分类 | `intent_key`、状态、显示名称及策略版本；归类为共享 Tutor 元数据 |
| `language_course_intent_tags` | 课程 UUID 与意图键的关联 | 复合主键、`0..100` 排序值、主标签标记、策略版本以及限制删除的外键 |

`assert_language_course_intent_coverage()` 要求每个已启用课程都有生效标签，每个已启用意图都有生效课程。延迟约束触发器在事务最终状态检查课程发布、意图启用和标签变更。只有初始化过程可按 slug 回填，并校验覆盖完整性，且支持重复执行。运行时短名单查询关联已启用课程 UUID 与生效标签，不检查课程 slug、标题或说明。

<a id="2026-08-21runtime-sourceprojection-sequence-与合并审计"></a>
## 2026-08-21：运行时来源/投影序列与合并审计

`tutor_runtime_item_receipts.event_sequence` 保留为兼容列并与新增 `projection_sequence` 严格相等；所有 PostgreSQL 归约器、`tutor_runtime_text_items.last_event_sequence`、对话 `turn_output.chunk_sequence` 与桌面端归约器都以投影序号为顺序权威来源。提供方规范化来源序号不进入公共 DTO。

每个有来源证据的回执必须同时保存 `source_sequence_start`、`source_sequence_end`、`source_delta_count` 与 `source_content_hash`。四者要么全部为空（仅允许本地 synthetic 控制/恢复事件），要么形成闭合连续范围且数量精确等于范围长度。字段只保存数字与 SHA-256；原始增量、推理/final 文本、提供方响应正文、外部身份和工具参数仍禁止进入回执。`tutor_runtime_text_items` 是按所属者隔离的文本权威来源，已完成条目继续校准全文。

<a id="2026-08-23teachingsession-durable-authority-与-action-receipt"></a>
## 2026-08-23：TeachingSession 持久化权威与操作回执

一条 LearningTrack 继续只绑定一条长期学习者可见的 Tutor 对话；知识点教学分段由 `tutor_teaching_sessions` 持久化，不创建并行聊天根。会话冻结精确 `user_id + track_id + conversation_id + knowledge_key`，以及学习路线版本、活跃计划修订、进度版本、活跃 Lesson 分配/版本、LessonDocument/内容哈希。部分唯一只约束 `active | paused` 当前会话；权威来源变化时旧会话追加 `authority_pause` 检查点并置为 `blocked`，新会话通过 `predecessor_session_id` 形成不可变后继沿袭关系。旧对话/历史不从聊天正文猜测或回填会话。

`tutor_teaching_session_checkpoints` 是前任已关联仅追加 CAS 链。`session_version=1` 必须没有前任，后继版本必须引用唯一前任；会话的 `current_checkpoint_id` 与 `version` 一起推进。检查点的有界类型化状态只包含目标、活跃/已暂停焦点、未解决问题摘要、已覆盖 concept、证据游标、暂停原因与 recommended 动作；原始提示词、提供方推理/正文、完整题目/提交、私有测试/量规、命令/路径/密钥不进入公共投影或导出。

`tutor_run_stimulus_events` 对每个教学限定作用域的新运行保存且只保存一个精确触发输入：`learner_message | teaching_control | domain_event`。学习者触发输入必须复合引用精确 `tutor_run_input_events(run_id,message_id,input_revision)`；控制/领域触发输入不创建伪学习者消息，运行来源仍为 `interactive`，不能滥用主动发起的。`tutor_run_teaching_scopes` 不可变冻结会话/检查点/触发输入与学习路线/计划/进度/分配/文档隔离检查。副作用提交、等待结果和终态结果持久化前重新读取当前权威来源；任一作用域/版本/指针已变化都拒绝继续处理，不能写副作用或学习者可见的终态输出。

`tutor_teaching_action_receipts` 每个运行最多一条，复合引用精确运行/会话/new 检查点/触发输入。v2 行在既有闭合动作、目标/焦点身份、焦点解决、暂停种类、有界来源 handles、公开消息 SHA-256 与已选上下文 IDs/哈希上，新增 `teaching_moves_json`、`learner_response_mode`、`schema_version=teaching_action_receipt_v2` 与 `policy_version=lesson_teaching_policy_v2`；不保存公开消息正文、提供方响应正文、提示词或推理。DB CHECK 要求 v2 有 2--4 个闭合、互不重复的转移，并约束输入区/动作兼容；v1 默认空转移/无以兼容历史行。回执与消息/检查点/会话/运行终态在同一事务提交，普通 UPDATE/DELETE 由仅追加触发器拒绝。

五张用户拥有的表全部属于受控切换穷举目标清点，并进入本地摘要/导出/重置/删除。删除在事务本地清理能力下按 `action receipt -> run teaching scope -> stimulus -> checkpoint -> session` 执行，再清 Lesson/学习路线根；会话当前检查点、检查点前任/来源触发输入与回执沿袭关系使用延迟 `NO ACTION`，使同一事务从子级到根级清理可验证且初始化两次幂等。早期本地 `RESTRICT` 来源触发输入 FK 必须在初始化时 drop/recreate 为延迟 `NO ACTION`，否则已有动作检查点的重置会在中途失败。

<a id="2026-08-23domain-event-admission-与-checkpoint-backed-teaching-summary"></a>
## 2026-08-23：领域事件准入与基于检查点的教学摘要

Gate/Attempt 终态、Review 终结、进度完成与 Lesson 分配迁移不新增第二套业务事实表。各所属者先提交既有结果/证据/调度/进度/分配权威来源，`TeachingDomainEventAdapter` 再以持久化来源 ID/版本生成 `domain_event` 触发输入。`uq_tutor_run_stimuli_domain(teaching_session_id,domain_event_kind,source_id,source_version)` 与准入前精确回执查找共同保证重复事件返回同一运行，而不是依赖唯一 violation 创建孤儿运行。

长期教学摘要复用 `tutor_teaching_session_checkpoints` 的仅追加前任 链，不新增 可变的 摘要表。`teaching_session_summary_v1` 是受控投影：目标、活跃/已暂停焦点、未解决 问题、已覆盖 概念、证据 游标、暂停/完成与来源检查点/权威来源哈希。加载器每次重新验证当前检查点/会话版本、权威来源快照与规范来源哈希；任一失配都不进入提供方上下文。当前摘要进入可选 工作摘要章节，必需教学上下文使用 紧凑的 权威来源投影；最多选择一个精确前任摘要，默认不全量重放长期对话。

<a id="2026-08-27teaching-action-receipt-v2"></a>
## 2026-08-27：教学操作回执 v2

`080_lesson_teaching_practice.sql` 对既有 `tutor_teaching_action_receipts` 做增量初始化：`teaching_moves_json JSONB NOT NULL DEFAULT '[]'::jsonb`、`learner_response_mode TEXT NOT NULL DEFAULT 'none'`、`schema_version TEXT NOT NULL DEFAULT 'teaching_action_receipt_v1'` 与 `policy_version TEXT NOT NULL DEFAULT 'lesson_teaching_policy_v1'`。历史 v1 行因默认值继续可读；新提交只能写 v2 数据库结构/策略。

可重复初始化先删除旧同名自动 CHECK，再建立稳定命名的转移、响应模式与版本结构约束。v2 转移必须是长度 2--4 的 JSON string array，值属于闭合 enum且位置不重复；输入区只与 `check_understanding | wait_for_input` 共存，无禁止这两个动作。回执仍仅追加，本地导出只增加安全转移/模式，不增加公开消息、提示词、提供方响应正文或推理。

<a id="2026-09-01teaching-artifact-commitbranch-lineage-与-continuation-intent"></a>
## 2026-09-01：教学 Artifact 提交、分支沿革与续接意图

`tutor_teaching_action_receipts` 增量支持 `teaching_action_receipt_v3 / lesson_teaching_policy_v3`。v3 仅在学习者响应模式为 Artifact 时保存精确交互意图、`li:<sha256>` 句柄、Artifact id、Artifact 事件 id 与序号；无/输入区继续使用 v2 结构。回执、Tutor 消息、下一步检查点/会话 CAS、Learning Artifact/事件、对话 `item_added` 和来源回合 terminalization由同一事务提交，任一 FK/CHECK/CAS/事件失败整体回滚。

由 Learning Item 支撑的 Artifact 所属者固定不可变版本 id 与最新已发布状态版本。实体化必须匹配公开/内容哈希、Practice 练习/量规回执、能力集合、运行时资料和当前 TeachingSession 隔离校验；表约束不允许把 Learning Item 外观封装误绑定为 Gate/Review 权威来源，也不产生 Attempt、分数、掌握度或进度行。

`tutor_conversation_branches` 保存一个阻塞 Artifact 下的持久化 深度为一的分支根、前任分支、当前事件、版本/轮次、最新处置结果与已解决回合。`tutor_conversation_branch_events` 是前任已关联仅追加 CAS 沿袭关系；`tutor_conversation_branch_items` 显式记录学习者/Tutor 消息与过程 归属；`tutor_run_branch_scopes` 冻结来源输入、分支轮次、Artifact、TeachingSession/检查点与闭合 分类/控制。部分唯一与作用域 FK 禁止同一 Artifact 多活跃分支、嵌套 分支、跨对话/用户/学习路线绑定和条目重归属。

`tutor_continuation_intents` 保存精确 Artifact/会话/检查点/学习路线/进度/分配隔离检查、来源种类/id/版本、fixed priority、幂等性哈希、not-before、状态/版本、领取所属者/世代/到期时间与 consumed 运行；`tutor_continuation_intent_events` 保存仅追加转换证据。一个对话同时最多一条已领取意图。领取前必须确认没有活跃前台运行、待处理学习者输入或活跃分支，并重新验证 Artifact/会话版本与检查点 ancestry；过期意图转已取消，过期领取按世代 release。生产者 只写意图，不创建运行或调用提供方。

分支/续接六张表属于用户拥有的受控切换目标。本地导出只能输出有界状态/数量/身份摘要；重置/删除按事件/条目/运行作用域/意图从子级到根级清理。对话快照仅在分支历史存在时投影 v5。重复初始化必须保留早期片段 110 对已持久化 `tutor_conversation_event_v3` 行的兼容，否则数据库结构 120 之前会因投影版本 CHECK 失败。

<a id="2026-09-13branch-authority-retirement"></a>
### 2026-09-13：分支权威退役

增量片段 `210_tutor_branch_supersession.sql` 增加分支 `superseded` 终态、`superseded_by_session_id` 与 `superseded_at`；它不表示正常答疑完成，`resolved_turn_id/resolved_at` 必须为空。旧 `active/resolved` 行不被迁移改写。`authority_superseded` 是仅追加分支事件，保存 `superseding_session_id`，不带来源输入、提供方响应、处置结果或辅助回执；已有事件类型仍必须拥有完整来源输入。

TeachingSession 所属者在一个由调用方管理的事务/savepoint 内阻塞陈旧会话、建立真实后继、调用分支所属者追加事件并推进分支 CAS。数据库与所属者都验证直接前任、相同用户/对话/学习路线/知识、不同权威来源快照、旧会话已被阻塞且没有未终态运行；终态根不可再改。分支轮次、条目、旧处置结果、Attempt 与学习进度均不重写。Python/SQL 活跃分支保护检查不放宽；旧 Artifact 的内容保持不变，生命周期退役遵循下节独立合同。

历史修复必须使用明确范围、有限且无环的前任链，先只读 试运行，再核对当前权威来源与预期版本，通过所属者处理；不得直接 UPDATE 状态或顺便调度陈旧意图。本地导出保留新的退役身份/时间戳，不把空来源输入补成旧学习者/回合来源。

<a id="2026-09-15blocked-teachingsession-artifact-retirement"></a>
### 2026-09-15：阻塞TeachingSession 的 Artifact 退役

增量片段 `230_artifact_authority_supersession.sql` 不改写数据。正常 TeachingSession 开放在对话锁和同一事务内，仅沿同用户/对话/学习路线/节点、最多 32 层且全部被阻塞的祖先链，通过 Artifact 所属者将最多 64 个非终态旧工件置为 `superseded`。正在运行或有未终态 Attempt 的工件必须先完成或取消，不可退役绕过。重复开放不增加事件或版本。

数据库的历史例外仅允许 `pending/ready/active → superseded`、版本 +1、清空动作并设置终态时间戳；其余冻结字段必须逐项保持不变。它要求真实且匹配当前学习路线/计划/进度/分配的后继、同范围检查点；教学所属者的冻结会话版本对照原检查点而非已经被阻塞后的新版本。Gate/Review 所属者保留身份和范围，退役不要求其可变版本仍为当前版本；Learning Item 仍校验原已发布回执、Practice 实体化、种类和 difficulty，回合/Attempt 作用域不豁免。

延迟约束触发器在 COMMIT 验证对应版本、作用域、确定事件键、前任/后继及原因代码的仅追加终态事件。缺回执、篡改题面或冻结所属者的直接 UPDATE 均失败。正常所属者同时发布对话 `item_updated`；退役不生成 Attempt、分数、掌握度、进度或模型调用。

<a id="2026-09-01terminal-execution-result-projection"></a>
## 2026-09-01：终态执行结果投影

本增量不增加新的业务权威来源表。`tutor_execution_jobs.result_json` 对新完成任务保存严格 `safe-execution-result-v2`；历史无版本 v1 行继续由 reader 适配器转成 v2 `presentation=none`。`tutor_exercise_attempt_results.safe_feedback_json` 保存同一面向学习者的安全 v2 JSON，Attempt 结果哈希、结局、分数与策略仍由 Gate/Review 评分器权威来源生成。

每个终态 Artifact 关联的 Attempt 通过现有 `tutor_learning_artifacts / events / references / attempt_links` 投影：来源 Artifact 追加精确 `execution-result:<attempt_id>` 所属者事件；结果 Artifact 使用 确定性 `execution-result:<attempt_id>` 创建 键，固定 `artifact_kind=test_result,purpose=result,state=completed,blocking=false`，并引用来源 Artifact 的新版本以及精确 Attempt 结果哈希。该持久化结果行在评价回合完成前不进入对话时间线；回合终态事务先追加 Tutor Markdown 消息条目，再追加精确结果 Artifact 条目，二者同事务提交或回滚。数据仓储在重放时同时验证来源事件与结果 Artifact；只存在一侧视为部分持久化并拒绝继续处理。多个 Attempt 保留独立结果 Artifact，来源 Artifact 只投影最新 Attempt。

结果评估复用 `tutor_continuation_intents`。意图的 Artifact 是结果 Artifact，来源 ID/版本是其精确创建事件，幂等键为 `result-evaluation:<event-id>`；调度和 Teaching 上下文重新验证用户/对话/学习路线/知识/会话、Artifact 种类/状态/呈现、Attempt 身份与事件序号后才消费。待处理 Attempt 不写结果 Artifact 或意图。以上写入由由调用方管理的事务包含；提供方失败不修改或删除已提交的 Attempt/结果。


### `tutor_demonstration_completion_receipts`

该表保存单个已完成 `demonstration_v2` Artifact 的仅追加、用户作用域回执，将 Artifact 版本和描述符哈希绑定到精确的隔离预览事件证据或有界可见时钟证据。它支持受控清理，导出时仅提供脱敏摘要，不拥有 Attempt、掌握度或进度权威。

<a id="2026-09-02knowledge-check-receipt-authority"></a>
## 2026-09-02：知识检查回执权威

数据库结构片段 `180_knowledge_checks.sql` 新增用户拥有的仅追加 `tutor_knowledge_check_response_receipts` 与 `tutor_knowledge_check_assistance_receipts`。响应每 Artifact 最多一条，绑定精确用户/对话/学习路线/知识/TeachingSession/检查点/Learning Item/Artifact 版本、闭合响应种类、响应/结果哈希、结局、辅助种类与评分器策略。数据库 CHECK 只允许 `outcome=correct AND assistance_kind=independent` 标记 independent 掌握度 符合条件的；直接答案响应固定为安全 marker 结构，不保存公开答案权威来源。

辅助回执对每个 Artifact 的 H1/H2/H3 与直接答案分别恰好一次。作用域触发器要求 Artifact 仍是精确活跃/就绪 Learning Item 知识检查；普通 UPDATE/DELETE 以 `23514` 拒绝，事务本地用户清理才允许删除。通用触发器必须先按 `TG_TABLE_NAME` 分支再读取响应表专属字段，避免在辅助触发器 record 上解析不存在列。

两张表属于受控切换目标，并进入本地摘要、安全导出、重置/删除的从子级到根级顺序。片段 170 提前兼容增量 `request_direct_answer` 动作，片段 110 继续在数据库结构 120/180 前接受已持久化 `tutor_conversation_event_v3`；显式初始化两次回归验证既有 v3 行、default 与 v1/v2/v3 CHECK 均保留。


<a id="2026-09-02对话内模型审查-artifact-receipt"></a>
## 2026-09-02：对话内模型审查 Artifact 回执

`190_model_review_artifacts.sql` 增量扩展 Learning Artifact 呈现种类，使
`model_code_review_v1 | model_code_review_v2` 同时可读，并把呈现 JSON 上限提高到
196,608 bytes 以容纳服务端构造的代码/差异行 map。早期 `120_learning_artifacts.sql` 与
`170_teaching_demonstrations.sql` 已提前接受 v2 种类，保证已有数据重复初始化在抵达片段
190 之前不会暂时违反 CHECK；`110_thread_turn_codex.sql` 继续接受持久化
`tutor_conversation_event_v3`。

`tutor_model_review_artifact_receipts` 是用户拥有的仅追加私有权威来源，一条 Artifact 最多
一条回执。复合 FK 固定产物/用户/对话/TeachingSession/学习路线，普通 FK 固定精确
Learning Item 版本与 Practice 练习版本；触发器在插入前锁定并复核活跃/就绪 v2
Artifact、知识/检查点/所属者/版本/实体化。表保存完整提交内容 JSON/哈希、判定、
结局/分数、辅助、安全反馈、结果/补救/策略/回执哈希；CHECK 要求失败必有
`li:<sha256>` 补救、已通过必无后继，提交内容数据库结构/哈希必须匹配呈现。
普通 UPDATE/DELETE 由既有 Artifact 仅追加保护检查拒绝；只有事务本地用户清理可
子表优先删除。

该表进入穷举受控切换目标清点、本地摘要数量、安全导出与重置/删除。导出
只列作用域、判定、结局、分数、辅助、后继、策略和时间；省略完整提交内容、
安全反馈正文、呈现/提交内容/结果/回执哈希、私有量规/测试/证明。删除顺序在
Artifact 事件/根之前清理回执，不能因新增私有 child 破坏已确认重置。

<a id="2026-09-02sql-learning-workspace-attempt-owner"></a>
## 2026-09-02：SQL 学习工作区的 Attempt 所属权威

`200_sql_learning_workspace.sql` 增量允许 `sql_workspace_v1 | sql_workspace_v2` 呈现，
为 `tutor_exercise_attempts` 增加 可空的 `learning_item_version_id`、FK 和部分索引，并扩展
所属者结构/`tutor_learning_artifact_attempt_owner_matches`。Learning Item SQL Run 必须是 `attempt_type=run`、
绑定当前课程分配/文档与 materialized ExerciseVersion、没有 Gate/诊断/复习绑定，且精确
Learning Item 最新发布状态为 `published`。普通 Gate/Review/Teaching Attempt 必须保持
`learning_item_version_id IS NULL`。

重复初始化在抵达片段 200 前会重新应用早期约束，因此片段 100 已提前声明该列并接受后来
合法的 Learning Item-owned Run，片段 160 允许 Learning Item 来源的 `test_result/purpose=result`
投影，片段 170/190 提前接受持久化 `sql_workspace_v2`。片段 110 的
`tutor_conversation_event_v3` 投影版本兼容保持不变。初始化两次与数据库结构
清单测试必须同时覆盖已有 SQL v2 Artifact/Attempt 和完整显式片段顺序。


<a id="2026-09-02learning-artifact-platform-final-schema-reconciliation"></a>
## 2026-09-02：Learning Artifact 平台最终数据库结构核对

截至 2026-09-02，显式清单包含从 `000_foundation.sql` 到 `200_sql_learning_workspace.sql` 的 21 个片段。片段 110 是 `tutor_conversation_events` 的早期归属片段，必须在后续 Artifact 片段执行前接受 `tutor_conversation_event_v1/v2/v3`；对已持久化 v3 行重复初始化属于发布检查项。片段 120-200 增加共享 Artifact、Learning Item/治理、分支/续接、教学提交、演示、知识检查、模型审查和 SQL 所属权威契约，没有第二份聚合数据库结构来源。

用户拥有的 Artifact、分支、续接、完成、辅助及私有回执记录均明确归为切换目标状态；确认重置/删除后，按子表优先顺序清理。共享不可变 Learning Item 版本、来源/发布/治理证据、私有评估模板和目录基础设施保留在共享白名单。`test_cutover_inventory_explicitly_classifies_every_tutor_table` 要求真实 `information_schema` 中的 `tutor_*` 集合等于互不相交的目标/共享集合之并；新表若缺少分类，最终检查必须失败。

来源文档抽屉不新增表。它通过已验证且范围受控的读取，解析不可变 Lesson 分配/文档/来源快照、持久化 `tutor_message_context_references` 及当前来源检查 Artifact 的来源链。回退保留全部新增行和历史，按依赖逆序关闭准入/呈现；不存在破坏性向下迁移或虚构 Artifact 回填。

<a id="2026-09-16learning-artifact-current-schema-reconciliation"></a>
## 2026-09-16：Learning Artifact 当前数据库结构核对

显式 `SCHEMA_FRAGMENT_NAMES` 清单包含 **25 个片段**，从 `000_foundation.sql` 到 `240_deepseek_flash_runtime_cutover.sql`。完整顺序及文件存在性由 `tests/database/test_schema_manifest.py` 和 `schema_fragment_paths()` 检查。

平台集成检查固定 **120-240** 有序区段，并要求片段 110 在其之前执行；缺失、重排或重复片段都必须被拒绝。后续仅追加片段时，不应仅因另一份测试复制了总数或倒数偏移而失败。新增片段仍须明确审查清单、数据库测试与文档。

- `210_tutor_branch_supersession.sql`：为旧分支记录显式权威退役历史，不虚构正常解决状态。
- `220_plan_catalog_knowledge_scope.sql`：分离稳定的计划节点身份与目录知识身份。
- `230_artifact_authority_supersession.sql`：在阻塞祖先导致退役时保留冻结内容、所属权威、检查点和 Attempt，并要求精确终态回执。
- `240_deepseek_flash_runtime_cutover.sql`：接受历史/当前模型身份，并退役仍活跃的旧模型运行时线程。实际应用时会改变数据；阅读本文或通过源码契约测试，都不能证明它已在任何数据库运行。

上文 2026-09-02 的核对记录保留当时的 21 个片段及历史测试结果。本次整理不针对真实验收数据执行初始化或迁移。
