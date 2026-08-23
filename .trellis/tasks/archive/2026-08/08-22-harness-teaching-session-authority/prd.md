# 教学会话 authority 与结构化 Turn 触发

## 目标

在现有 LearningTrack、track-scoped Tutor conversation 与 fresh finite `TurnRun` 之间建立 PostgreSQL teaching session authority，并为 learner message、typed teaching control 与可信 domain event 提供不伪造消息的统一 Turn stimulus。该 child 只建立持久状态、版本边界、基础 API 与数据治理，不实现模型教学策略和 Desktop 角色换位。

## 依赖与顺序

- 父任务：`08-22-harness-led-adaptive-learning-workspace`。
- 本 child 是第一个实现目标，无前置 child。
- 完成并归档后才能启动 `08-22-harness-closed-teaching-action-loop`。

## 范围内

1. `tutor_teaching_sessions`、append-only checkpoints 与 immutable run teaching scope。
2. session 生命周期、mode、assignment/document/progress/version fence。
3. learner message / teaching control / domain event exact one-of stimulus。
4. 创建、恢复、读取与 typed mutation admission 的 repository/service/API 基础。
5. current teaching session 与 conversation/message/run 的可验证绑定和只读历史 lineage。
6. cutover inventory、export/reset/delete、bootstrap twice、cross-user 与隐私覆盖。
7. additive snapshot/SSE metadata 的最小基础 contract，供后续 child 扩展。

## 范围外

1. closed teaching action 的模型决策与专用 Lesson teaching Skill。
2. 自然教学策略、焦点恢复算法或 Action Shelf 排序。
3. Guided/Free Reading Desktop 布局、文档跟随和响应式 UI。
4. Gate/Review 的完整教学反馈策略和长期质量 eval。
5. 真实 provider、部署、生产数据迁移或历史消息批量推断。

## 需求

### R1 — Teaching session 根

- 每个 `user_id + track_id + conversation_id + knowledge_key` 建立 owner-scoped session 根。
- 一条 LearningTrack 继续只有一条长期 conversation；session 只作为知识点分段。
- session 保存 `active|paused|completed|blocked`、`guided|free_reading`、active assignment/document identity、current checkpoint、optimistic version 和时间信息。
- 同一知识点最多一个当前非终结 session；历史 session 保留 lineage，不能同时拥有 Composer scope。

### R2 — Append-only checkpoint

- checkpoint predecessor-linked，保存 objective、active/suspended focus、unresolved questions、covered concept summary、evidence cursor、pause reason、推荐动作输入与 authority versions。
- checkpoint 不保存完整 Lesson、完整聊天、完整提交、hidden tests/rubric、provider prompt/body/reasoning 或 raw tool result。
- stale predecessor、跨 owner、跨 track、跨 conversation、assignment/progress/version 冲突全部拒绝。

### R3 — Immutable run teaching scope

- 每个 teaching run 固定 session/checkpoint/version、track/knowledge、mode、assignment/document fence、stimulus identity 和 policy/schema version。
- teaching run 结果提交前重新校验 scope；stale/superseded/interrupt 结果不能推进 checkpoint。
- 现有 non-teaching run 行为保持兼容。

### R4 — Structured Turn stimulus

- 定义 exact one-of `learner_message | teaching_control | domain_event`。
- learner message 继续使用现有 durable `message_id + input_revision`。
- `open_session`、`continue`、`return_focus`、`switch_mode`、`enter_next_knowledge` 等使用 closed control key 与 server-owned target。
- Gate/Review/progress/assignment 事件使用 durable source ID/version；不得伪装成 learner message，不得滥用 proactive origin。
- 重试复用同一 stimulus identity，并通过幂等键阻止重复 admission。

### R5 — API 与错误边界

- 提供 current/list/open/action 的 additive service/API contract。
- mutation 必须带 `client_action_id` 与 expected versions；错误使用 stable 404/409/422 public envelope。
- public projection 不泄漏内部 hash、完整问题、submission、provider body/reasoning 或私有测试。
- 历史 conversation 没有 teaching scope 时保持 read-only legacy projection，不做猜测型 backfill。

### R6 — 数据治理

- 新 user-owned 表加入 exhaustive cutover target inventory，并保持与 shared catalog 集合互斥。
- export 返回 learner-safe bounded session summary；reset/delete 按 child-to-root 清理。
- schema bootstrap 连续两次幂等，非法插入与约束都有 PostgreSQL regression。

## 验收标准

- [ ] 同一 owner/track/knowledge key 无法创建两个并行 current session，历史 lineage 可读取。
- [ ] 刷新后仅凭 PostgreSQL 可恢复 mode、assignment fence、current checkpoint/version 和 session status。
- [ ] 一个 teaching run 恰好绑定一个 durable stimulus；learner message 与 teaching control/domain event 不会混用或同时为空。
- [ ] `continue`、`switch_mode`、Gate terminal event 不产生伪造 learner message，也不进入 proactive scheduler。
- [ ] stale session/checkpoint/assignment/progress/stimulus 不能写入新 checkpoint或公开成功结果。
- [ ] cross-user、cross-track、cross-conversation ID 均返回安全错误，不泄漏存在性。
- [ ] 旧 conversation/history/run 在无 teaching metadata 时继续可读，未被批量重写。
- [ ] 新表全部进入 cutover inventory、export/reset/delete，bootstrap twice 与 child-to-root 删除测试通过。
- [ ] focused Pytest、Ruff、Mypy、Trellis validate 与 `git diff --check` 通过；不调用真实 provider。

## 风险与控制

1. **第二套 conversation authority**：session 必须引用现有 track-scoped conversation，数据库约束和 service guard 同时阻止孤立 conversation。
2. **状态复制过量**：只保存 bounded structured state 与 source identity，正文继续留在原 authority。
3. **触发模型混乱**：exact one-of stimulus 与 durable idempotency 将控制事件和 learner message 分离。
4. **迁移遗漏**：exhaustive `tutor_*` schema classification 和 bootstrap twice 作为硬门。
