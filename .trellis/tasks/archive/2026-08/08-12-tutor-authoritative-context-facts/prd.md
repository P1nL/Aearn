# Tutor 权威上下文事实与重建

## 目标

在现有 Tutor Harness、LearningTrack 和学习计划制定闭环上，为计划收集与教学 TurnRun 建立服务器权威、可追溯、可重建的结构化事实层，使语言、目标、每周时间、经验水平、教学偏好、用户 correction 和未解决问题不再只寄存在聊天历史或异步摘要中。

本任务重点修复真实对话中“用户已回答每周 30 小时，后续仍被重复询问”的上下文正确性缺口，同时保留当前 finite `TurnRun`、lease/revision、adaptive budget、structured summary、learner memory 和 safe projection 边界。

## 用户价值

1. 已确认的问题不会因为消息滑出 recent history 而被再次询问。
2. 用户更正目标、时间或经验后，新事实能够明确覆盖旧事实并留下 lineage。
3. 长对话压缩、恢复和 replay 后，模型仍获得同一份权威 planning/teaching facts。
4. 系统能够解释某个事实来自哪条消息、何时确认、是否已被替代。
5. Context eval 能直接检测“事实是否被模型请求携带”，而不只检测 token 与消息顺序。

## 依赖

必须已完成并继续复用：

- `08-04-tutor-context-governance-adaptive-budget` 及其已归档 children。
- `08-04-learning-track-plan-mastery-domain`。
- `08-04-learning-home-plan-builder`。

本任务完成后，以下 tasks 才能按新事实 contract 收口：

- `08-04-spaced-review-sessions`。
- `08-04-learning-workspace-context-references`。
- `08-04-learning-agent-integration-migration-qa-docs`。
- `08-12-tutor-controlled-action-runtime`。

## 已确认事实

1. `PostgresTutorContextLoader` 可以加载多于四条历史，但 `TutorContextBuilder` 默认只选择最后四条 `RECENT_MESSAGES`。
2. 真实失败样本中 loader 读取了八条 prior messages，包含“30小时”的消息在 builder 层被排除；当时 working summary 为空且 token 未达到 warning。
3. `tutor_learning_plan_sessions` 在 `collecting` 阶段只有 lifecycle、preferred language 和 draft pointer，没有 `weekly_minutes`、goal、experience 等权威 intake 字段。
4. draft 生成后，`tutor_learning_plan_drafts` 才保存这些字段；因此 draft 前的事实连续性仍依赖 history/summary。
5. 当前 structured context summary 已有 schema/policy、coverage、source hash、prior lineage、append-only 和 stale exclusion 契约，不能被绕开或替换为无版本自由文本。
6. 当前 `current_input`、input revision、provider boundary refresh 和 stale result fencing 必须保持不变。
7. 本任务不是简单把 recent message limit 从四调大；固定条数只能是安全上限，不能继续充当事实选择策略。
8. 研究依据位于 `.trellis/tasks/archive/2026-08/08-11-codex-aearn-agent-architecture-comparison/research/`。

## 需求

### R1 — Append-only intake fact authority

- 为 planning session 建立 append-only typed intake fact authority，至少支持：
  - `language_id`
  - `goal_text`
  - `target_level`
  - `weekly_minutes`
  - `experience_level`
  - `teaching_preferences`
  - `pace_constraints`
- 每条事实必须保存 user、session、conversation、field key、normalized value、source message、input revision、状态、创建时间和可验证 fingerprint。
- correction 通过新 row supersede 旧 row，不原地重写历史事实。
- 一个 field 在同一 active session 中只能有一个 current confirmed projection。
- 事实只能由服务器验证过的用户输入或明确确认动作产生，模型推断不能直接成为 confirmed fact。

### R2 — Question state 与重复询问防线

- planning session 必须区分 `unasked`、`asked`、`answered_unconfirmed`、`confirmed`、`superseded`。
- provider decision 中再次询问已 confirmed field 时，decision gate 必须能默认拒绝或转为 correction confirmation，而不是直接发布重复问题。
- 用户主动表示“不确定”“需要修改”或提交冲突值时，可以重新开启字段收集，但必须保留原因与 lineage。
- 不依赖文本完全匹配识别问题；使用稳定 field/question key。

### R3 — Authoritative Context Snapshot

- 每个 interactive TurnRun 在 provider 调用前，从 current input、planning facts、track/plan/artifact、mastery、summary、memory 和 recent history 构建单一、版本化的 `AuthoritativeContextSnapshot`。
- confirmed facts 是 required section，优先级仅低于 system/policy/current input，高于普通 recent history、summary 和 recall memory。
- snapshot 保存 source IDs/hashes、fact revision、选中/跳过原因和缺失告警，但不保存 raw secret 或完整历史。
- resume、replay、context eval 和实际 provider request 必须调用同一 snapshot projector，禁止多套事实装载逻辑。

### R4 — 语义保留与压缩屏障

- recent message 选择同时考虑 token、消息角色和 semantic class；confirmed fact source、correction、未解决问题和最新交互可被 pin。
- 固定 item count 只能作为最终硬上限，不得在 token 富余时先于 semantic pinning 排除唯一事实来源。
- summary 未可用时，如果待退休 prefix 含尚未进入 authoritative facts 的唯一关键事实，compaction 必须暂停或同步生成 bounded fallback projection。
- structured summary 只补充非结构化连续性，不得覆盖 authoritative facts；冲突时记录 stale/conflict 并以事实 authority 为准。

### R5 — 安全、隐私与兼容

- 不将 raw conversation、provider reasoning、秘密、隐藏 rubric、完整提交代码复制到 intake fact 或 snapshot。
- schema additive-first；现有 planning sessions/drafts、context summary、memory 和 historical conversation 保持可读。
- 已存在的 collecting session 可以按懒迁移方式从后续用户确认开始建立 facts，不允许无证据批量推断历史字段。
- API/SSE 只公开 learner-safe fact/question status，不公开内部 source hash、gate reason 或模型 prompt。

### R6 — 指标与回归

- context receipt 至少增加：
  - `required_fact_count`
  - `required_fact_selected_count`
  - `required_fact_missing_count`
  - `confirmed_question_reasked_count`
  - `summary_blocked_by_unprojected_fact`
- 建立真实失败形态 fixture：回答每周时间后再经过超过四条消息，provider context 仍包含时间事实且不得重复询问。
- 覆盖 correction、同 timestamp、resume、replay、summary unavailable、summary stale、cross-user/session 和幂等场景。

## 验收标准

- [x] planning collecting 阶段能够持久化并读取 `weekly_minutes` 等 typed facts，无需先生成 draft。
- [x] confirmed fact 使用 append-only supersede lineage，不发生无审计原地覆盖。
- [x] “30小时”真实回归场景在超过四条后续消息、summary 为空且 token 富余时仍进入 provider context。
- [x] provider 不会再次询问已 confirmed field；用户显式 correction 可以重新开启并覆盖旧值。
- [x] actual provider、resume、replay 和 context eval 使用同一 `AuthoritativeContextSnapshot` projector。
- [x] required facts 始终优先于普通历史、summary 和 recall memory，并记录 selection receipt。
- [x] compaction 不会在无 replacement fact/summary 的情况下退休唯一关键事实来源。
- [x] 旧 collecting session 不被无证据回填；新 schema bootstrap 可重复且跨用户/session scope 受约束。
- [x] public API、SSE、trace、checkpoint 和 export 不泄露 raw history、secret 或内部 prompt。
- [x] PostgreSQL、context builder/loader、run loop、planning API、eval、redaction 和 replay 聚焦测试通过。

## 范围外

- 统一所有 capability/effect/execution action lifecycle；由 `08-12-tutor-controlled-action-runtime` 负责。
- 任意通用跨会话项目 memory 或向量检索平台。
- 恢复旧 Graph/router/SDK runtime。
- 仅通过扩大 recent-message limit 作为最终修复。
- 未经单独批准的 commit、push、deploy 或生产数据迁移。
