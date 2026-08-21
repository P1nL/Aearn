# 课程意图 taxonomy 与动态 Generated UI

## 目标

让计划制定流程根据学习者已明确表达的具体编程语言、多个候选语言或学习方向，确定性地自动确认 `language_id` 或生成受控课程 shortlist。课程方向关系必须来自 PostgreSQL 结构化 metadata，不依赖课程 title、description 或 Runtime 硬编码 course slug；Generated UI 不再固定展示全部课程，也不默认选中第一项。

## 背景

- 当前 `language_courses` 没有 frontend/backend/data_analysis 等 metadata。
- 当前 `build_planning_question_presentation()` 对语言字段直接返回全部未归档课程。
- `LanguageCapability` 已有语言 aliases 和 public course map，可作为明确语言归一化 source of truth。
- `tutor_planning_intake_facts.source_kind` 已支持 `deterministic_input`，可记录从 learner message 确定性识别的唯一语言。
- 用户要求：明确语言时不重复询问；只有方向时只显示适用技术栈；多语言时只显示提到的候选；无信号时才展示完整目录。

## 范围内

- 新增闭合 intent taxonomy 与课程关联表、seed/backfill、coverage gate。
- 新增 `PlanningIntentResolver` 和版本化 closed DTO。
- 确定性语言自动确认、方向 shortlist、多语言交集、冲突/unsupported 回退。
- 模型可选 closed intent tag hint，但不能定义语言、课程或事实。
- Typed request presentation 持久化 exact candidate options。
- Desktop 语言单选无默认值、提交门、刷新恢复。
- Backend/PostgreSQL/API/Desktop/browser 测试与文档。

## 范围外

- 课程管理后台和自由 taxonomy 编辑 UI。
- 从 title/description 猜方向。
- 模型直接确认 `language_id`、提交 course ID 或生成选项。
- 自动安装 runtime 或新增未发布课程。
- 已 confirmed language 的普通对话自动改写；显式纠正/reopen 另走现有 authority。

## 需求

### P0：Schema 与发布门

- 新增 `tutor_learning_intents` 和 `language_course_intent_tags`，使用 FK、closed state、rank、policy version 和 updated_at 约束。
- 现有 active courses 一次性 backfill；Runtime 查询只按 course ID + tag，不按 slug/title。
- 每个 active course 至少一个 tag；每个 active intent 至少一个 active course。
- 新课程发布必须在同一事务写 tags 并通过 coverage；漏标返回稳定错误，不让用户运行期发现。

### P0：Intent resolution

- 只使用 learner message、confirmed facts、active catalog 与 server policy；不读取 Tutor/model/reasoning 内容。
- 唯一明确语言且有 active course时写 `deterministic_input` confirmed fact，并跳过语言问题。
- 多个明确语言时 shortlist 仅包含对应 active courses。
- 只有方向时按 tags/rank shortlist；无可靠结果时回退完整 active catalog。
- 明确语言与方向冲突时不自动确认；候选必须有限且无默认选择。
- 模型 hint 只能提交 closed intent tags；未知、无 active course 或 extra fields 必须拒绝/忽略并安全回退。

### P0：Generated UI

- Language presentation 增加 `selection_scope`、`selection_reason_code`、`intent_policy_version`，不包含 learner 原文或分类推理。
- `recommended` 对语言问题允许为 `null`；Desktop 初始无选中项，未选择时提交 disabled。
- Durable request 创建后刷新、重连和 catalog 变化不能改变该 request 的 options。
- 选项只包含 active published courses，owner/session/question revision fence 不变。

### P1：可维护性

- Taxonomy、backfill、resolver aliases/tags 和 public DTO 进入 `.trellis/spec` 与 architecture docs。
- 增加 coverage doctor 或测试输出，列出缺 tag course ID/slug，仅供开发诊断，不进入用户响应。

## 验收标准

- [ ] “我想学 Python”写 confirmed `language_id=python`，下一问不是语言。
- [ ] “我想学前端”只显示 frontend/web 关联课程，无 C#/Go/Java/SQL 等无关项且无默认选择。
- [ ] “我想做后端”按 metadata 显示 Python、TypeScript Node、Java、Go、C# 等 active backend 课程。
- [ ] “Python 和 Go 哪个适合后端”只显示 Python 与 Go。
- [ ] 语言与方向冲突不自动确认，不静默改写用户表达。
- [ ] 修改课程 title/description 不改变 shortlist；新增漏标 active course 使 bootstrap/CI 失败。
- [ ] Typed request refresh/reconnect 后 options、顺序和选中草稿保持确定。
- [ ] focused/full backend、Desktop tests/check、browser smoke 与 `git diff --check` 通过。

## 依赖

- 依赖已归档的 `08-19-codex-thread-context-raw-runtime-stream` 提供 typed planning request、conversation thread 与 snapshot v3 基线。
- 本 child 完成后，`08-21-reasoning-delta-coalescing-runtime-budget` 使用其真实 UI 场景做最终长 reasoning 验收。
