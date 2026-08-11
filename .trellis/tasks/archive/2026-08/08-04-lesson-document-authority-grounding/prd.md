# LessonDocument 与权威来源教学内容

## 目标

在已完成的 LearningTrack、计划路线、掌握度与学习首页基础上，建立可复用的标准 `LessonDocument`、带明确 lineage 的 track-scoped 个性化派生版本，以及开始学习后不可静默替换的 assignment。

该能力让用户从“继续学习”进入稳定、可恢复、可引用的结构化课程阅读面；每个事实性教学段落都能追溯到受信文档快照，来源更新或教学策略升级只创建新版本，不改写已经开始的课程、练习引用或未来掌握度证据。

## 用户价值

1. 用户看到的是稳定课程文档，而不是刷新后消失的一次性聊天 Markdown。
2. 用户可以查看教学结论来自哪个官方文档、规范或受信事实来源。
3. 同一知识点可复用高质量标准版本，同时按学习目标、经验、掌握度和偏好生成可追溯的个性化版本。
4. 课程开始后，正文顺序、引用、Gate slot 与评分 contract 不会被后台更新静默替换。
5. 来源或课程策略升级时，用户可以看到版本影响并显式迁移，旧学习记录仍可重放。

## 依赖与已确认事实

1. `08-04-learning-track-plan-mastery-domain` 已完成，当前已有 `tutor_learning_tracks`、不可变计划 revision、稳定 `knowledge_key`、进度/掌握度、`lesson_teaching` task kind 与只读 Tutor context adapter。
2. `08-04-learning-home-plan-builder` 已完成，verified 用户默认进入 LearningTrack 首页；“继续学习”目前只产生 `continue_learning` intent 并显示 Lesson 尚未交付。
3. 当前 grounding 已具备开发者治理的 source registry、allowlisted seed URL、抓取/清洗/分块、PostgreSQL `grounding_chunks`、检索、citation 与 registry-only `grounding.retrieve`；交互式 provider 不具备任意 URL fetch 权限。
4. 当前 grounding chunk 已保存 source、language、canonical URL、section、trust tier、`fetched_at` 和 chunk `content_hash`，但缺少显式 source version 与原始文档 hash 的稳定持久化字段。
5. 当前 active runtime 没有 `LessonDocument` 表、route、service、typed block renderer 或 lesson 页面；旧 `learning_sessions/.../documentation` 是历史 contract，不能恢复为新产品权威入口。
6. 当前前端完成门是 `http://127.0.0.1:1420` 网页端真实浏览器验证；除非用户另行要求，不运行 `desktop:check`、Tauri build 或 Desktop typecheck。
7. 本任务是父任务波次 2 的第二项；练习 Attempt、执行、模块诊断、路线解锁、完整三栏工作区和结构化选区进入 Tutor 由后续 child 负责。

## 范围内

- 注册且严格校验的 Lesson block union 与 canonical hash。
- 共享标准 LessonDocument、track-scoped 个性化版本、来源快照、block-citation 映射和 lineage。
- 可恢复的服务端 authoring run、严格 typed provider 输出、质量门、失败映射与无 fallback 规则。
- Lesson assignment、开始冻结、版本提案、影响摘要与显式迁移。
- verified-only Lesson API、幂等、user/track/knowledge scope、CAS 和安全公开投影。
- 从首页“继续学习”进入的单页 Lesson 阅读面、注册 block renderer、引用证据展示和真实 loading/error/retry 状态。
- local export/reset/delete、cutover target inventory、schema/bootstrap 和 source-of-truth 文档同步。

## 需求

### R1 — 注册 Block Contract

- `LessonDocument` 使用严格、版本化、拒绝未知字段的 block union；首版至少支持 `heading`、`learning_objectives`、`concept`、`authority_note`、`code_example`、`comparison`、`hint`、`exercise_gate`、`summary` 和 `next_steps`。
- 每个 block 必须有稳定 `block_id`、唯一 `order_index`、类型专属字段和显式 `citation_ids`；前端只能通过 exhaustive renderer 渲染已注册类型。
- block 内容使用有界纯文本、字符串数组和代码字段，不接受任意 HTML、React definition、脚本、样式、事件处理器或 `dangerouslySetInnerHTML`。
- `exercise_gate` 在本任务只冻结公开 gate slot：`gate_key`、`gate_kind`、`assessment_contract_version`、required capability 与 learner-safe 说明；不创建 Attempt、执行结果、隐藏 rubric 或路线解锁。
- block union、文档 schema、Gate slot 和引用集合都进入 canonical document hash。

### R2 — 权威来源与不可变快照

- Lesson authoring 只能读取已持久化、registry-owned、allowlisted 的 grounding chunks；authoring turn 不直接调用 crawler，不接受模型提供 URL/source ID/path/command。
- source registry 与 grounding chunk 补充显式 `source_version_label`、`source_version_kind=fixed|rolling` 和原始文档 hash，使 Lesson 快照能区分内容标准版本与上游文档版本。
- 每个 source snapshot 至少保存 source ID、展示名、provider、trust tier、source type、版本、canonical URL、section path、chunk ID、文档 hash、chunk hash、`fetched_at`、snapshot time 和用于重放的 bounded evidence excerpt。
- source snapshot 不依赖后续仍存在的 `grounding_chunks` 行；reindex 可以替换索引，但不能破坏旧 Lesson 的引用重放。
- public projection 只返回 learner-safe citation metadata 和必要的短证据摘录，不返回抓取原文全集、provider prompt/body 或内部检索诊断。

### R3 — 标准 LessonDocument

- 标准版本以 `language_id + knowledge_key + content_standard_version` 为教学身份，并记录 schema/generator/policy/source-set version。
- 服务端为模型分配短 evidence handle；模型只能引用这些 handle，不能自行创建来源或 URL。
- 发布前质量门必须验证 block schema、stable IDs/order、核心 capability coverage、事实 block 的 citation coverage、语言一致性、代码示例静态安全、Gate slot 完整性、来源 trust policy、内容长度和敏感字段拒绝。
- 没有足够受信来源、provider 不可用、输出不合法或质量门失败时，authoring run 保持 failed，并返回稳定安全错误；不得使用静态模板或无来源内容冒充正式课程。
- 相同标准身份和完全相同 source/generator/policy evidence 幂等复用；来源或策略变化创建 predecessor-linked 新标准版本。

### R4 — 个性化派生

- 个性化版本必须引用一个已发布标准版本，并绑定当前 user、LearningTrack、active plan revision 与 `knowledge_key`。
- 个性化输入只包含 bounded track 目标、target level、已有经验/教学偏好、当前节点、必要 mastery summary、execution tier 和标准文档；不复制完整 Conversation、raw prompt/history 或 mastery evidence body。
- 个性化可以调整解释深度、示例、非核心顺序、提示和推荐内容，但不得删除标准版本要求的核心 capability、引用覆盖或 Gate slot contract。
- 个性化版本保存 `standard_document_id`、可选 predecessor、profile hash、生成策略版本、变更摘要和独立 content hash。
- provider 不可用或个性化质量门失败时不得静默把标准版本伪装成 personalized；前端显示可恢复失败，测试使用 fake author port。

### R5 — Assignment、冻结与迁移

- 每个 `track_id + knowledge_key` 最多一个 active assignment；assignment 指向同 user/track/key 的 personalized document，并保存 source plan revision、assignment version 与 predecessor。
- 首次开始学习使用幂等、CAS mutation 固定 document version、block 顺序、citation set、Gate slot contract 和 content hash，同时把节点从 `available` 安全推进到 `in_progress` 并更新 track `last_learned_at`。
- started assignment 不得被 source reindex、标准版本更新或重新个性化静默替换。
- 新版本先形成 proposed assignment 与 learner-safe impact：来源变化、block 增删/重排、示例变化、Gate contract 变化和保留项；用户显式激活后才切换 active assignment。
- 旧 assignment/document/source snapshot 永久可读，后续 ExerciseAttempt、解锁和 mastery evidence 必须引用其原始 document/assignment identity。

### R6 — API 与 authoring 生命周期

- 提供 verified-only、user/track/knowledge-scoped 的 Lesson read/prepare/start/update API；locked 或不属于 active plan 的节点不能准备或开始课程，跨用户对象统一返回不泄露 owner 的 404。
- `prepare` 创建或重放一个 durable authoring run，提交后由 post-commit dispatcher 在短事务之外调用 strict author port；GET 可读取 `missing | preparing | ready | failed` 安全状态。
- authoring run 具备 lease、attempt、retry、stale track/version/source recheck 和 terminal safe error；provider call 前后不持有长事务或 track row lock。
- mutation 使用现有 idempotency key 格式、request hash、expected track/assignment version；相同 key 不同请求返回稳定 409。
- 公共响应不暴露 provider/model diagnostics、raw source text、quality internal report、prompt、reasoning、hidden test、reference answer、命令、路径或凭据。

### R7 — 前端阅读与证据展示

- 首页“继续学习”进入 `lesson_document` surface，不再显示课程未就绪占位；本任务不提前实现左侧路线 + 中间内容 + 右侧 Tutor 的完整三栏工作区。
- Lesson 页面必须展示真实准备中、失败、重试、可开始、已开始和可迁移状态，并保留返回学习首页的稳定路径。
- typed renderer 展示标题、目标、概念、权威说明、代码、对比、提示、Gate slot、总结与后续建议；未知 block/API shape 进入可见 contract error，不做宽松 cast 或 HTML fallback。
- 事实 block 提供 inline citation marker；来源面板展示来源名称、provider、trust label、版本、章节、抓取/快照时间、canonical URL 和短证据摘录。
- 未绑定真实 Exercise 的 Gate slot 明确显示“练习能力将在后续任务开放”，不伪造运行、评分、通过或解锁事实。
- 后续三栏工作区必须复用本任务的 `LessonDocumentView`/block renderer，不复制第二套文档解析或引用逻辑。

### R8 — 数据生命周期、安全与兼容

- schema additive-first；不恢复旧 `teaching_chunks`/learning documentation route 作为 active authority，也不删除现有 grounding、LearningTrack、planning 或 Tutor 数据。
- 共享标准 document 不属于单个用户的 cutover target；personalized document、assignment 与 authoring run 必须纳入 user target inventory、summary/export/reset/delete。
- 本地 export 可以包含用户可见的 personalized Lesson blocks、assignment 与 citation metadata，但必须省略 authoring prompt/body/reasoning、内部 quality report 和完整抓取原文。
- authoring attempt 只持久化 safe provider/model/protocol/outcome/usage metadata；missing usage 保持 unknown，不伪造为零。
- 真实 provider smoke、commit、push、deploy 和生产数据迁移均需单独批准，不属于本任务默认执行。

## 验收标准

- [ ] 标准与 personalized LessonDocument 均通过严格 block union、canonical hash 和 PostgreSQL round-trip；未知/HTML/script block 被拒绝。
- [ ] 标准 document 可按语言、knowledge key、内容标准和 source set 幂等复用；来源或策略变化只创建 predecessor-linked 新版本。
- [ ] 每个要求 citation 的事实 block 至少引用一个属于该 document 的受信 source snapshot；无来源、跨语言、非 allowlisted URL、hash/version 不一致无法发布。
- [ ] personalized document 保留标准版本、track/profile/plan lineage、核心 capability、引用覆盖与 Gate slot contract。
- [ ] prepare authoring run 可重放、可恢复、可失败关闭；provider call 不持有长事务，stale track/source/version 不能提交 document。
- [ ] 首次 start 冻结 assignment 并安全推进节点到 `in_progress`；重复请求幂等，陈旧 version 返回稳定 409。
- [ ] started assignment 在 reindex、标准更新和重新个性化后仍读取原 document；新版本只作为 proposal，显式迁移后才切换。
- [ ] Desktop 从 Learning Home 进入真实 Lesson 阅读面，按注册类型渲染，并显示 inline citation 与来源证据；Gate slot 不伪造后续能力。
- [ ] 跨用户/跨 track/locked node、敏感字段、任意 URL/source target、provider failure、quality failure 和未知 API shape 均有聚焦拒绝测试。
- [ ] local export/reset/delete、cutover target inventory、schema/bootstrap、grounding regression 与现有 LearningTrack/Tutor contract 不回归。
- [ ] 前端仅通过 `http://127.0.0.1:1420` 的 normal/narrow 网页端浏览器验证；不运行 Desktop build/typecheck。
- [ ] 聚焦 Pytest、完整 API suite、Ruff、Mypy、lock check、Trellis validate 与 `git diff --check` 通过，或记录精确阻塞。

## 范围外

- 练习提交、Attempt、运行/编译、隐藏测试、private rubric、Gate 评分、模块诊断和路线解锁。
- 间隔复习、ReviewSession、模型代码审核练习。
- 完整三栏学习工作区、Lesson 文本选择加入右侧 Tutor、exercise/execution/review structured reference。
- 开放式网页搜索、任意 URL 抓取、provider turn 直接 crawler、模型生成 React/HTML。
- 一次性预制全部语言和知识点课程库。
- 真实 provider 教学质量证明、公开 container fleet 证明、发布、部署或提交授权。
