# LearningTrack、计划路线与掌握度领域基础

## 目标

建立新教学产品的长期权威状态：一个用户可以拥有多个独立 `LearningTrack`，每条主线具有不可变计划版本、路线节点、进度与掌握度证据，并能为 Tutor Conversation/TurnRun 提供明确的语言、任务类型和 track scope。

本任务只建立领域基础和最小读写 API，不实现首页、LessonDocument、练习 Gate、复习页面或模型代码审核题。

## 已确认事实

1. 当前 active runtime 是 Tutor Harness，旧 `learning_plans`、`knowledge_points`、`learning_sessions` 和 Graph 路由不得恢复为产品权威状态。
2. 现有 `tutor_plan_revisions` / `tutor_active_plans` 是 user-level outline，每个用户只有一个 active pointer，无法表示多个语言学习主线。
3. 现有 Conversation 长期存活、普通输入创建 fresh finite `TurnRun`；新的教学 scope 必须在此基础上增量增加。
4. PostgreSQL、user scope、idempotency、lease/revision 和 safe projection 继续是权威边界。
5. 本任务是新产品交付子树的第一条实现任务，不依赖其他新产品 child；后续首页、Lesson、Gate、复习和工作区均依赖本任务冻结的 ID 与版本 contract。

## 需求

### R1 — LearningTrack 根对象

- 新增 track-scoped Tutor 领域模型，至少包含用户、语言、学习目标、状态、当前路线节点、最近学习时间和版本字段。
- 同一用户可创建多个 track，同一语言也可因目标不同创建多个 track。
- 所有 track read/write 必须同时校验 `user_id + track_id`，禁止仅凭全局 UUID 跨用户读取。
- 语言使用稳定 registry key；显示名称和运行能力由服务端 capability projection 提供。

### R2 — 不可变计划版本与路线

- 每个 track 拥有不可变计划 revision 和唯一 active pointer。
- revision 保存 predecessor、生成策略版本、用户确认原因、内容 hash 和路线结构。
- 路线包含模块和知识点节点；节点使用跨计划版本稳定的 `knowledge_key`，不能依赖某一 revision 的行 ID 表示长期掌握度。
- 核心结构变化必须创建新 revision 和影响预览，用户确认后才切换 active pointer。
- 进行中和已完成节点的证据不得因 revision 切换被删除或原地改写。

### R3 — 路线进度与掌握度证据

- 节点进度是 track + `knowledge_key` 的权威投影，至少支持 `locked`、`available`、`in_progress`、`completed`、`review_due` 和后续模块诊断需要的 `diagnostic_skipped`。
- 掌握度采用 append-only evidence 与可重算 state 分离；evidence 记录来源类型、来源 receipt/hash、是否独立完成、提示使用和分数摘要。
- 本任务只提供 evidence contract 和基础 projection；具体练习、诊断与复习写入由后续 child 实现。
- 模型不能直接写 mastery state 或解锁节点，只能提出受控 proposal。

### R4 — Conversation 与 TurnRun 教学作用域

- 新建或扩展结构化 scope，使 Conversation 可明确属于 `general`、planning 或某个 LearningTrack；旧 Conversation 保持 `general`，不自动推断。
- `TurnRun` 增加受控 `task_kind`，至少预留计划制定、知识教学、练习反馈、复习、模型代码审核和补救教学。
- scope/task kind 是服务端权威字段，不从每次自由文本临时猜测。
- ContextBuilder 后续可通过此 contract 获取语言、active plan、当前节点和必要 mastery evidence。

### R5 — Execution Tier 权威投影

- 统一暴露 `teaching_local`、`container_verified`、`static_only` 和 `unavailable`。
- tier 由服务端结合语言 registry、composition、reviewed image lock 和 executor health 判定。
- 当前公开 composition 在没有 reviewed image lock 时不得把本机 runner 投影为 `container_verified`。
- 本任务只提供统一 projection contract，不接入实际练习执行。

### R6 — 最小公共 API

- 提供创建、列表、详情、读取路线和计划 revision/影响预览所需的类型化 API contract。
- 所有 mutation 使用 `Idempotency-Key` 或现有 bounded client action id，并绑定 request hash。
- version/predecessor 冲突返回稳定 409；用户、track 或 revision scope 不匹配返回不泄露其他用户存在性的 404。
- API 不暴露旧表名、内部 evidence payload、provider 信息或执行器细节。

### R7 — 兼容与迁移

- schema additive-first，不删除或重新开放旧 `learning_*` 表。
- 现有 user-level `tutor_plan_revisions` 保持原 API 与 rollback 行为；不得从自由文本 outline 自动生成 track。
- 允许后续显式导入设计，但不在本任务实现。
- cutover、conversation/history、memory、activity 和 proactive 行为不得回归。

## 验收标准

- [ ] 一个用户可创建多个 track，同语言不同目标不会互相覆盖；跨用户读取和 mutation 被拒绝。
- [ ] 每个 track 有唯一 active plan revision，结构变化创建 predecessor-linked 新版本并可展示影响预览。
- [ ] `knowledge_key` 在计划 revision 间稳定，已有 progress/mastery evidence 在切换 revision 后仍可读取。
- [ ] mastery evidence append-only，mastery state 可由确定性 projector 重算；模型 proposal 不能直接成为已验证 evidence。
- [ ] Conversation/TurnRun 具有服务端权威 learning scope 和 `task_kind`，旧 conversation 安全投影为 `general`。
- [ ] 服务端统一投影四种 `execution_tier`，当前无 image lock 的公开 composition 不会宣称 `container_verified`。
- [ ] API idempotency、version conflict、user/track scope、safe error 和 PostgreSQL FK/CHECK 均有聚焦测试。
- [ ] 现有 Tutor Harness、cutover、history、plan rollback、memory、activity 和 proactive 测试继续通过。
- [ ] Ruff、Mypy、相关 Pytest、任务校验和 `git diff --check` 通过。

## 范围外

- LearningTrack 首页和计划制定 UI。
- LessonDocument、练习、模块诊断、复习和模型代码审核题。
- 恢复旧 plans/learning/review 路由或迁移已删除的旧学习历史。
- 实际启用本机或 container 代码执行。
- commit、push、deploy 或生产数据迁移。
