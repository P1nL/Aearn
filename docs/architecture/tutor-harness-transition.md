<a id="tutor-harness-transition-contract--historical-migration-evidence"></a>

# Tutor Harness 过渡契约：历史迁移证据

> **历史状态（2026-07-29）：** 本文保留功能关闭、增量建设阶段的 Child 00--07 迁移与清空重建设计证据。
> 它**不是**当前运行时契约，不能用于判断现行路由、调度器默认配置、包依赖、桌面端行为或发布就绪状态。
> 请先阅读 [Tutor Harness 运行时](./tutor-harness-runtime.md) 和 [`docs/README.md`](../README.md) 索引的当前权威文档。

<a id="status-authority-and-reading-rule"></a>

## 状态、权威来源与阅读规则

当前运行时为仅允许已验证用户进入的 Tutor Harness：服务端权威切换回执控制公共 Tutor API 和桌面端准入；旧 Graph/SDK 实现已退出现行源码树；仅面向已验证用户的主动投递采用受控默认配置。这些现行事实由其他文档规定；本文解释仓库如何演进到这一边界。

| 权威来源 | 现今用途 |
| --- | --- |
| [当前运行时契约](./tutor-harness-runtime.md) | 现行循环、Skill、模型提供方、持久化、调度器、执行器、切换与回滚边界。 |
| 当前路由、数据库结构、测试与配置 | 公共行为和安全准入的事实依据。 |
| 本过渡文档 | 仅作为历史迁移、切换证据与早期子任务契约。 |
| `docs/archive/2026-07-29/` | 有明确日期的 Graph/SDK 时代证据，不是现行运行时依据。 |

**阅读规则：** 下文以中文保留原设计含义。“当前”“功能关闭”“后续子任务”“旧版基线”“不暴露”等表述均描述对应章节写作时的状态，不覆盖当前运行时契约。2026-09-17 的中文整理仅核对本地源码，不构成重新执行历史测试、迁移或发布验收。

<a id="historical-legacy-baseline-explicit-non-changes"></a>

## 历史旧版基线：明确不变的范围

- `LANGGRAPH_ENABLED` 当时仍是旧 Graph 开关，不复用。
- 旧 `learning_stage` 路由、专家交接、Graph 检查点、路由、SSE 事件和桌面流程继续承接当时的产品流量。
- 既有提供方配置与同一已选提供方的重试仍由 `OpenAICompatibleClient` 负责。
- 产品持久化仍沿用旧数据库结构与仓储边界。Child 02 增量增加的 `tutor_*` 记录是隔离、功能关闭的目标状态；不迁移、删除或修改旧学习者记录。

`TUTOR_HARNESS_ENABLED=false` 当时仍是独立的未来集成接口。Child 02 完成后，当时的产品路由、Graph 路径、SSE 生产者、worker 和 UI 均不读取它。

<a id="target-run-and-input-contract"></a>

## 目标运行与输入契约

`TutorRunSnapshot` 不可变，包含不透明的运行、对话、用户 ID，单调递增的 `input_revision`，以及固定策略、租约和计数器数据。`TutorCheckpoint` 只保留脱敏后的来源与预算元数据，终态结果只公开对学习者安全的文本和稳定诊断码。这些契约均不包含提供方原始载荷、提示词、完整历史、隐藏测试、参考答案、提交代码或密钥。

```text
queued -> leased -> running
running -> waiting_for_input | waiting_for_capability | awaiting_effect_commit
running -> completed | model_unavailable | blocked_policy | budget_exhausted | cancelled | failed
```

每个已接受的 `TutorInputEvent` 都有不透明消息 ID 和单调修订号，以 `TutorRunStore.current_input_revision(run_id)` 为准。循环在每次模型调用前、能力分发前、能力返回后和副作用提交前重新加载该值。预期修订号不匹配时，副作用成为 `stale_rejected`，绝不调用其提交器。

固定策略限制迭代次数、模型/能力/副作用调用数、截止时间和上下文 token。Child 00 只提供端口、确定性替身及默认拒绝；后续持久化使同一协议具备持久性。

<a id="target-context-checkpoint-and-compaction-contract"></a>

## 目标上下文、检查点与压缩契约

`TutorContextBuilder` 只接收已限定作用域的事实，并按稳定顺序选择：系统/已选 Skill/策略描述；活动计划修订；复习/FSRS 快照；近期清洗后的消息；工作摘要；学习者可见记忆；活动/执行事实；允许的能力 schema。

每个区段都有明确条目与 token 预算。默认估算器确定且保守（按 UTF-8 字节数估算），选择前先清洗和运行时脱敏。检查点只保留区段计数、来源 ID/哈希与预算消耗元数据，绝不保存组装后的提示词或原始来源内容。

高水位输出是幂等、类型化的压缩*请求*，不是 Curator 调用。只在终态、安全检查点或配置的上下文高水位条件触发，不随每个流式 token 触发。

<a id="target-provider-and-decision-contract"></a>

## 目标提供方与决策契约

`PrimaryTutorProviderGateway` 是 Child 00 唯一模型边界，封装配置中的 `OpenAICompatibleClient`，保留已选提供方/模型，以及 DeepSeek Chat Completions 和旧 OpenAI 兼容 Responses 的有界重试行为。不修改配置，也不尝试跨提供方或模型回退。

严格 Harness 决策封装允许有界、学习者安全的公开文本、Skill 引用、能力请求、副作用提案、可选的安全检查点原因和终止意图。未知、格式错误或重复字段、推理/诊断字段以及不安全文本均被拒绝；通用教学输出护栏仍是文本安全边界。

配置、已选提供方调用、响应/schema 或护栏失败统一转为脱敏的 `MODEL_UNAVAILABLE`；提供方原始错误、提示词、密钥和载荷不得跨越此契约。

<a id="child-01-target-skill-catalog-policy-and-registry-grounding"></a>

## Child 01 目标：Skill 目录、策略与注册表事实检索

Child 01 仅增加隔离的内部目录/网关组合，不向产品流量开放 Harness，也不改变 `TUTOR_HARNESS_ENABLED=false` 的默认配置。

<a id="published-skill-catalog"></a>

### 已发布 Skill 目录

- 经审查的包位于 `aearn/services/api/app/agents/skills/<skill_id>/<semantic_version>/`，包含 `manifest.json`、UTF-8 审查指令和非空 JSON 评估套件，均由同一 Git 树管理。
- 编译器仅接受精确 SemVer 2 引用，校验包内相对资源名、内容哈希、已审查注册表引用和声明的描述符/副作用，并把完整集合编译为有序、不可变、带规范 SHA-256 摘要的快照。任一包无效即拒绝整个快照，不允许部分结果或 `current` 回退。
- 初始发布的 Skill 为 `tutor.registry-grounding@1.0.0`，只需要 `grounding.retrieve`，声明已审查资源 `registry:grounding_sources`，不声明任何允许的副作用类型。Skill 始终是指令/资源数据，不是模型编写的代码或可执行代码。

<a id="catalog-context-and-decision-boundary"></a>

### 目录上下文与决策边界

- 目录上下文加载器装饰既有有界上下文输入：选择前只提供策略允许的精确版本 Skill 摘要及 MCP 兼容 JSON schema；选择通过校验后提供该精确审查指令及 ID/版本/哈希事实。不公开旧工具注册表或任意目录文件正文。
- Child 01 的选择存储仅属于其隔离组合内的单次运行。Child 02 按 `(run_id, input_revision)` 持久化解析后的精确目录摘要、Skill ID/版本及清单/指令/评估哈希。可变 `current`、版本范围、通配符或指令正文都不是持久重放证据。新选 Skill 仍触发上下文重建，同一模型决策内不得分发能力或提议副作用。
- 目录决策 Gate 在严格提供方封装解析后、检查点/能力/副作用操作前执行。无版本、未知、策略不允许、格式错误或混合选择与动作的决策一律拒绝，不回退。默认未组合的 Gate 拒绝模型选择的 Skill、能力和副作用。

<a id="capability-policy-and-effect-boundary"></a>

### 能力策略与副作用边界

- `CapabilityPolicyContext` 绑定运行/用户作用域、来源、当前输入修订、目录摘要、同意状态、运行时可用性、剩余预算、策略标签、允许的精确 Skill 引用和已注册来源范围。默认解析器不发布任何 Skill、能力、副作用或来源。
- 仅解码有界提供方封装中描述符声明的字段。未知字段名、URL、路径、镜像、SQL 片段、shell 命令、任意用户标识和类似函数的目标在尝试查询前即拒绝。
- 副作用仍为携带 `expected_input_revision` 的类型化 `TutorEffectProposal`。初始目录没有副作用描述符或允许的副作用类型，因此提案在默认拒绝提交器前即被拒绝，不进入领域变更路径。

<a id="registry-only-grounding"></a>

### 仅限注册表的事实检索

- Child 01 唯一可执行能力为 `grounding.retrieve@1.0.0`，只接受有界的语言/查询/主题/数量字段，从 `grounding_sources.py` 推导允许的来源 ID，并返回有上限的片段及引用/来源元数据。
- 网关注入 `GroundingLookup` 适配器；其内存实现对给定索引块复用纯检索逻辑。目录、Harness 和网关不直接导入数据库连接、持久索引仓储、HTTP 抓取器、爬虫、shell、runner 或旧教学工具。
- Child 02 只持久化有界能力调用/副作用证据：已解析的目录/策略/修订/租约事实、安全状态码与哈希。不序列化任意目标、检索正文、提供方载荷、提示词或完整片段。本阶段不授权路由、SSE 帧、桌面组件、worker、提供方路由变更或旧 Graph/工具删除。

<a id="child-02-target-durable-state-replay-and-safe-curation-envelope"></a>

## Child 02 目标：持久状态、重放与安全整理封装

<a id="additive-schema-and-scoped-lifecycle"></a>

### 增量数据库结构与限定作用域的生命周期

Child 02 在可重复执行的 API 初始化 schema 上增量增加功能关闭的 `tutor_*` 表族：目标对话/消息、不可变目录快照、运行、精确 Skill 选择、已接受输入、仅元数据检查点、有序运行事件、能力/副作用回执、脱敏跟踪，以及整理 outbox/提案封装。不引入 Alembic 执行器或并行迁移机制。所有记录限定用户/运行/对话作用域，旧学习会话、消息、Attempt、计划、复习、FSRS 状态和笔记均不改动。

学习者输入在单个事务内接受：作用域与终态检查、运行域幂等键/正文哈希的重放或冲突处理、仅向 `tutor_messages` 写入规范学习者正文、分配单调输入修订、写入引用输入事件及一条安全 `input_accepted` 事件。诊断、事件、检查点、跟踪、outbox、提案和导出不是原始对话存储。

<a id="durable-ordering-lease-and-effect-cas"></a>

### 持久顺序、租约与副作用 CAS

锁定运行行后分配 `tutor_runs.next_event_sequence`，并在同一事务写入 `tutor_run_events`。内部重放游标是运行内单调递增整数 `event_sequence`，读取只返回 `event_sequence > after_sequence` 的有序后缀。这是内部仓储契约，不是 SSE `id`、`Last-Event-ID`、投递确认或公共重连承诺。

检查点/高水位/终态生命周期写入原子包含对应安全有序事件、脱敏跟踪和去重整理 outbox 行。事务失败时不暴露部分检查点、结果、事件、跟踪或 outbox。终态更新使用受保护的状态转换，竞争失败的写入方得到稳定终态/租约回执，不产生第二个终态序列。

副作用提交在同一事务内检查目标用户作用域、有效租约所有者/代次/到期时间、非终态和预期当前输入修订。陈旧或无效租约提案只持久化 `stale_rejected` 安全证据与事件，不调用领域提交器。实际领域副作用仍默认拒绝，直到责任子任务提供显式事务内处理器。

<a id="redaction-export-and-curation-boundaries"></a>

### 脱敏、导出与整理边界

Child 02 在诊断写入时和导出/读取时两次使用共享白名单安全投影。原始提示词/历史、提供方载荷/错误/推理、密钥/token、隐藏测试、解答/参考材料、完整代码、堆栈、主机/容器路径、shell 或 SQL 目标、带凭据 URL，即使嵌套或伪装于看似允许的字段内也会被移除。规范学习者原文只保留在 `tutor_messages`。

整理 outbox 存储脱敏、类型化压缩请求，包含闭合来源事件范围、来源 ID/哈希、策略和记忆设置版本、保留/陈旧状态、优先级与确定性幂等标识。每个 outbox 标识最多一个 `context_summary` 或 `memory_entry` 提案封装。Child 02 不认领队列、不重试任务、不调用模型、不做提案语义校验，也不投影到学习者记忆、计划、复习、FSRS、Attempt、活动或聊天。

<a id="deterministic-evaluation-boundary"></a>

### 确定性评估边界

版本控制下的 `tests/fixtures/tutor_evals/` 用例只使用固定时钟、提供方/网关/存储/提交器替身及精确目录/Skill 摘要和哈希标识。覆盖策略拒绝、严格提供方封装拒绝、有界循环退出、陈旧修订/副作用、仅主提供方的 `MODEL_UNAVAILABLE` 和脱敏泄漏，不使用真实模型、网络、worker 或墙上时钟。

<a id="child-03-target-isolated-container-executor"></a>

## Child 03 目标：隔离容器执行器

Child 03 增加功能关闭的持久执行基础，不向产品流量开放 Harness，也不改变旧 runner、路由、Graph、SSE、桌面端或通用 Celery worker 边界。

- `runner.execute` 是精确目录副作用，只接受服务端签发的不透明 `ExecutionIntentProofV1` 引用。证明绑定交互式用户/对话/运行/修订/消息/练习作用域、显式动作、目录/策略/预算证据和到期时间。主动来源、陈旧作用域、取消、缺少证据或额外模型字段均不创建任务。
- Child 02 事务内处理器仅记录或重放一行 `tutor_execution_jobs` 并消耗证明，不联系镜像仓库、运行时守护进程或旧 runner。持久 PostgreSQL 任务表是执行权威，后续 broker 投递仅可作为唤醒优化。
- 只有 `aearn/services/executor/` 拥有运行时客户端。它在提交后认领任务，外部动作前预留一个不可变启动 token，随后接管匹配标签的运行时或记录 `launch_uncertain`。不确定性为终态，不是二次启动的理由。
- Git 管理的目录列出七个审查协议项：Python、浏览器预览、TypeScript、SQLite、Java、Go 和 C#；Rust 和 C++ 当时不在其中。`image-locks.json` 只包含审查后的 `repository@sha256:<64-hex>` 锁；缺锁即不可用，不回退到标签、本地镜像、拉取或主机进程。
- `TUTOR_EXECUTOR_ENABLED=false` 独立于 `TUTOR_HARNESS_ENABLED` 和 `REAL_EXECUTION_ENABLED`。API 可用性只读取兼容执行器心跳与锁指纹，不联系运行时守护进程。
- 意图/任务/审计/事件/导出投影只保留不透明 ID、指纹、枚举、计数器和有上限的学习者安全结果事实，不含源码、隐藏测试、镜像细节、运行时标识、命令、挂载、路径、容器标识或运行时原始错误。

独立进程与运维流程见 [`../setup/container-sandbox-executor.md`](../setup/container-sandbox-executor.md)。

<a id="child-04-target-proactive-scheduler-and-curation-queue"></a>

## Child 04 目标：主动调度器与整理队列

Child 04 只增加功能关闭的持久调度机制，不公开路由、SSE 帧、桌面状态、通知、聊天消息、旧复习 worker 行为或产品领域投影。

- 已提交领域事实或有界时间扫描记录类型化信号，包含稳定生产者标识、来源哈希、去重键/窗口、安全引用字段及可审计处置。候选创建记录每次允许、不动作或重复窗口判定；PostgreSQL 负责去重、租约、重试和 broker 重投恢复。
- 调度策略默认拒绝：调用运行或 Curator 处理器前检查全局启用、硬暂停、切换已验证、用户偏好/暂停、独立每日预算、并发、冷却和熔断限制。当时默认禁用调度器并硬暂停后台工作。
- 主动候选先预留一个内部 `tutor_conversations` 记录（`visibility=internal`、`kind=proactive`）和一个 `origin=proactive` 的 `tutor_runs`，再运行既有有限 `TutorRunLoop`。后台组合永久拒绝 `runner.execute` 和 `tutor.memory.record`；只可在正副作用预算下获得策略明确组合的 `tutor.plan.activate`、`tutor.plan.rollback` 或 `tutor.activity.record` 权限。默认组合仍为空，没有正常成功后的聊天/桌面投递路径。
- 每个 Child 02 待处理 outbox 标识仅生成一个低优先级整理任务。outbox 继续作为脱敏语义封装，处理前复核来源修订/策略/记忆设置/保留事实。Child 04 注入的默认实现不动作；Child 05 仅在全部调度准入通过且 `TUTOR_CURATION_MAX_OUTPUT_TOKENS > 0` 时组合仅主提供方的 Curator。不能直接写聊天、计划、复习、FSRS、Attempt、文件系统或任意提供方/模型目标。
- worker 暴露有限目标任务名 `tutor.proactive.scan_due_signals`、`tutor.proactive.drain_candidates`、`tutor.curation.drain`，委派给 API 侧策略/仓储服务；默认功能关闭时不调用模型、能力或领域。

<a id="child-05-target-learner-state-curator-projection-and-user-controls"></a>

## Child 05 目标：学习者状态、Curator 投影与用户控制

Child 05 增加功能关闭的目标领域状态，不改变旧 `learning_plans`、学习者档案、复习、FSRS、Attempt、路由、SSE、桌面端或 Graph 边界。

- 审查目录增加 `tutor.plan.activate`、`tutor.plan.rollback`、`tutor.memory.record`、`tutor.activity.record` 的精确描述符；审查 Skill `tutor.learner-state@1.0.0` 只声明这些副作用，默认策略仍不授权。`PostgresTutorRepository.commit_effect_if_current()` 调用事务内处理器前，重新校验描述符载荷和已选 Skill 证据。
- `tutor_plan_revisions` 不可变，`tutor_active_plans` 是唯一可变指针，`tutor_plan_revision_actions` 仅追加。激活增加修订、证据及前驱；回滚只允许移动到活动修订记录的前驱。两者均不写旧计划、复习、FSRS、Attempt 或学习者档案。
- `tutor_memory_entries` 区分 `objective_fact` 与 `inference`。客观事实可来自有证据的副作用或受信/用户控制记录；推断需要 Curator 来源、置信度、策略和记忆设置版本、保留/陈旧信息以及脱敏 outbox/提案作用域。纠正追加关联替代项，删除是受保护状态转换而非原始数据改写。`tutor_memory_preferences` 版本化使陈旧排队工作失效。
- `tutor_activity_records` 是仅追加的学习者安全证据，`tutor_inbox_items` 是其可选、用户域已读/忽略投影。两者不存提示词、跟踪、提供方推理、代码、路径、命令、SQL、隐藏测试或密钥。
- `PrimaryCurationGateway` 只看到 Child 02 脱敏封装，并单次调用配置的主 `OpenAICompatibleClient`，不回退提供方/模型。默认 `TUTOR_CURATION_MAX_OUTPUT_TOKENS=0` 不调用。类型化结果恰好创建一个上下文摘要或推断投影；`tutor_curation_projection_receipts` 记录 `committed`、`no_action`、`stale` 或 `failed`，不把通用提案行变成提供方原始载荷存储。
- Child 05 当时仍不承接产品流量；Child 06 负责公共 API、SSE、桌面适配，Child 07 负责切换与旧版退役。

<a id="child-06-target-public-api-cursor-sse-and-pre-cutover-desktop"></a>

## Child 06 目标：公共 API、游标 SSE 与切换前桌面端

Child 06 可在持久目标记录上公开版本化 `/api/tutor` 适配器，但不让 Harness 成为正常产品路径：`TUTOR_HARNESS_ENABLED=false` 时，所有目标路由在读写目标领域前返回稳定 `CUTOVER_REQUIRED` 封装。设置该路由组合开关不等于切换确认，不删除旧数据，也不授权 Graph 退役；这些准入由 Child 07 负责。

| 接口面 | Child 06 状态 | 兼容规则 | 移除条件 |
| --- | --- | --- | --- |
| 既有学习/引导/复习/笔记路由与 Graph SSE 流 | 旧版 | 保留当时请求、事件与桌面行为，不隐式改道。 | Child 07 与 Child 08 替代证明。 |
| `POST /api/tutor/conversations`、输入/运行/活动/记忆/计划/偏好路由 | 新增 | 仅使用用户域 `tutor_*` 目标记录与稳定封装。 | 保留的目标接口面。 |
| `GET /api/tutor/runs/{run_id}/events` | 新增 | 将有序持久事件适配为 SSE ID 和 `Last-Event-ID`，流式传输时绝不调用提供方。 | 保留的目标接口面。 |
| 旧端点到 Tutor 转换 | 适配器 | 仅允许显式、版本化、经测试的转换；Child 06 不增加自动适配器。 | 替代消费者通过验证后方可移除。 |
| Harness 桌面组件 | 新增、切换准入 | 编译类型化 UI/契约，不改变旧应用默认入口。 | Child 07 服务端切换状态。 |

所有目标变更需要客户端幂等键。适配器只持久化操作/键/正文哈希与学习者安全响应投影；重放返回原投影，不同正文返回 `IDEMPOTENCY_CONFLICT`。当时，对话输入仅在不存在兼容非终态运行时创建一个交互运行，否则调用持久输入接受事务并返回单调输入修订；不会因第二条学习者消息取消运行或启动竞争的旧流。

公共 SSE 游标为单运行域的非负十进制 `Last-Event-ID`。适配器读取 `event_sequence > cursor` 的有序持久后缀，以序列作为公共 SSE `id`，仅映射学习者安全事件事实。适用时保留既有兼容事件名；新增可选 `input_accepted`、`run_state`、`activity`。不能关联到单个持久事件的路由/重放错误为终态但无 SSE `id`；桌面必须表示为 `id: null`，保留最后数值游标，绝不把错误帧用作 `Last-Event-ID`。原始学习者消息、跟踪、Curator 提示词/来源片段/理由、提供方载荷/错误、代码、路径、隐藏测试、Attempt 和 FSRS 详情当时均不是 API/SSE/桌面字段。

学习者控制读取不可变计划谱系/差异、学习者安全记忆来源/保留事实和活动/收件箱状态。用户回滚只能移到活动修订记录的前驱，并追加有审计的用户控制动作；不能选择任意目标修订或修改旧计划、复习、FSRS、Attempt、档案。记忆纠正追加关联替代项，删除仍是受保护状态转换。偏好路由可公开推断记忆启用和用户主动任务暂停，但不能启用后台工作、放宽硬暂停/预算或公开提供方配置。

<a id="child-07-target-verified-clean-slate-cutover-gate"></a>

## Child 07 目标：已验证的清空重建切换准入

Child 07 负责从旧学习运行时到公共 Tutor 的一次性切换。不迁移旧学习历史，也不在首次切换变更中物理移除 Graph、路由、工具、依赖或文档代码。

- `TUTOR_HARNESS_ENABLED=false` 当时保留旧产品路径，并使 `/api/tutor/*` 保持关闭。开关仅用于部署组合，不证明本地学习者已切换。
- 启用开关后，用户域旧运行时路由和 Tutor 路由检查同一 `harness_cutovers(user_id, cutover_version)` 回执。仅 `verified` 允许 Tutor 流量；`summary_ready`、`required`、`verification_failed`、`blocked_target_state`、`blocked_checkpoint_scope` 拒绝两类运行时，但保留狭窄的切换状态/确认端点。不能识别 UUID 用户域的旧路由默认拒绝，不退化为仅按会话/路径读旧数据。`verified` 只授权 Tutor，不重开旧路由。
- `GET /api/harness/cutover?user_id=...` 由服务端裁决，计算规范安全摘要/哈希，且只对需要破坏性确认的旧数据签发预览 nonce。桌面可显示摘要，但不能选择表名、数量、检查点线程或删除范围。
- `POST /api/harness/cutover/confirm` 要求精确版本、摘要版本、nonce、哈希、`confirm=true` 和稳定客户端幂等键。陈旧摘要、跨用户请求、正文变化的重放、目标状态行或未解析检查点作用域均不删除任何数据。
- 事务锁定活动用户行，在删除会话前只推导 `aearn:learning:<learning_session_id>` 检查点线程；按精确 `idempotency_records.user_id` 删除而非 JSON/文本匹配；清理五个旧学习者偏好字段，验证同一作用域并原子提交 `verified`。身份、显示名、时段、提醒偏好、共享 `tutor_catalog_snapshots` 和 `checkpoint_migrations` 不在删除范围。
- 切换前任何用户域 `tutor_*` 行或 `tutor_api_idempotency_records` 行均为目标状态污染，只阻断、不删除或迁移。缺失检查点表可视为安全的零记录；未知 schema、命名空间、`NULL` 线程 ID 或无法证明的线程映射均阻断，绝不宽泛删除。
- 部署开关关闭时，普通 `POST /api/users/{user_id}/reset-data` 仍执行旧重置；启用后必须先取得相同已验证回执。待确认摘要不能借 reset 删除旧行再隐式成为空状态切换。
- 删除或验证异常时回滚破坏性事务，并用独立安全 `CUTOVER_VERIFICATION_FAILED` 回执阻断两类运行时。确认切换后回滚代码不代表学习者数据可恢复。

桌面启动先读取本地用户身份，在恢复 `aearn.bootstrap.planId` 或发出 dashboard/resume/旧请求之前查询切换端点，只挂载阻断式确认页或全新 `TutorWorkspacePage`。验证成功保留 `userId`、写入 `planId=null`，清空旧内存和设置表单状态，不清除无关本地 UI 存储。

物理移除旧版是后续证据关卡：删除 Graph/运行时代码或依赖前，必须具备启用功能后的切换与全新 Tutor 入口覆盖、无旧启动调用的已验证桌面默认路由、旧 worker 写入准入控制、限定作用域调用方搜索无残留，以及 Child 08 权威来源对齐。

<a id="target-loop-and-future-ownership"></a>

## 目标循环与后续职责

有限循环认领租约、加载状态、检查固定预算/取消、构建有界上下文、请求主提供方给出一个决策，并在每个不安全边界前重查修订与策略。默认能力/副作用端口拒绝或报告不可用，不执行工具、不写产品状态。

安全检查点与压缩候选仅因终态、安全检查点或高水位通过注入端口发出。Child 00 不创建 Curator、worker、事务 outbox、后台循环，也不直接变更记忆、计划、复习、FSRS、Attempt、消息或活动。

| 后续子任务 | Child 00 之后的职责 |
| --- | --- |
| Child 01 | Skill 目录、能力策略、已注册能力实现。 |
| Child 02 | 增量目标 SQL 仓储、精确目录重放证据、持久内部事件/检查点、生命周期事务、脱敏跟踪/导出、整理封装及仅替身评估。 |
| Child 04 | 持久 outbox 工作的队列租约/重试/熔断；Child 02 不运行任务。 |
| Child 05 | 功能关闭准入下的目标学习者状态副作用、不可变计划修订/回滚、记忆/活动/收件箱投影及仅主提供方 Curator 校验。 |
| Child 06 | Tutor API/SSE `Last-Event-ID` 适配、投递确认、功能公开与桌面去重。 |
| Child 07/08 | 切换、旧版退役与权威来源对齐。 |

本历史文档在写作时未授权产品流量。现今产品流量遵循当前仅已验证用户可用的运行时契约；保留这句话仅用于保存早期迁移边界。
