# Harness closed teaching action 与自然教学 Loop

## 目标

在 Child 1 的 durable teaching session/stimulus authority 上实现自然、可中断、可恢复且单步停止的教学执行 Loop。模型只能选择 closed teaching action 和 server-provided evidence handles；Aearn 负责验证、提交 checkpoint、公开 learner-safe output 与投影 Composer Action Shelf。

## 依赖与顺序

- 必须在 `08-22-harness-teaching-session-authority` 完成并归档后启动。
- 完成本 child 后才允许启动 Desktop child。

## 范围内

1. `tutor.lesson-teaching@1.0.0` 专用 Skill 与版本化 contract。
2. required teaching context 与 current structured stimulus。
3. closed teaching action、decision protocol、validation gate 和 safe receipt。
4. 单步主动、逐段停顿、焦点栈、未解决问题与纠正覆盖。
5. completion pause、free-reading reactive answer、显式 escalation 与 next-node control。
6. 服务端 Action Shelf projection 与 action endpoint policy。
7. fake provider deterministic tests、trace/redaction 与 provider unavailable recovery。

## 范围外

1. 新 teaching session schema 的重新设计。
2. Desktop 布局、样式、Action Shelf React 实现或文档滚动。
3. 重做 Lesson/Gate/Review/mastery authority。
4. 允许模型生成任意 UI、action label、数据库 ID 或路线节点。
5. 真实 provider 默认 smoke。

## 需求

### R1 — Required teaching context

- teaching run 必须固定 current stimulus、session/checkpoint/version、objective、active/suspended focus、unresolved questions、mode、assignment/document fence 与 exact evidence handles。
- required section 无法完整表达时 fail closed，不调用 provider。
- current learner input/纠正优先于旧 focus、summary、memory 和推荐动作。

### R2 — Closed teaching action

- 首版 action 至少包括 `orient`、`explain_concept`、`answer_question`、`show_example`、`compare_examples`、`check_understanding`、`recommend_practice`、`explain_feedback`、`remediate_prerequisite`、`summarize_progress`、`recommend_pause`、`wait_for_input`。
- 一次 provider decision 最多选择一个主要 teaching action。
- 模型只能引用 server-provided focus、Lesson block、Gate/Review evidence handle；未知/越权 handle、extra field、非法组合 fail closed。
- 模型不能定义 UI、Action Shelf label/target、mastery、完成、解锁或下一 knowledge key。

### R3 — 单步主动、逐段停顿

- 进入可学习知识点后允许一次首个教学 Turn；一次 Turn 只服务一个中心问题。
- 成功提交后写 checkpoint 并进入 `soft_pause|evidence_pause|authority_pause|session_pause|completion_pause`。
- 没有新 learner input、typed control、domain event、authority refresh 或显式恢复时，不创建下一 Turn。
- `continue` 等高频控制使用 typed stimulus，不从自由文本猜测控制意图。

### R4 — 中断与恢复

- 用户任何新输入先于旧教学计划处理，正在生成的旧路径可 interrupt/steer，stale 返回不得发布。
- 插问保存原 focus 并创建 bounded child focus；回答后明确恢复、调整或等待。
- 连续追问、纠正、拒绝、换例子、前置缺口、离题和返回主线都必须有受控结果。
- 焦点栈与问题队列有深度/数量/压缩上限，不允许无限增长。

### R5 — 模式与完成语义

- `free_reading` 普通问题只做 reactive finite answer，回答后仍停留 free reading。
- 模型最多提出 learner-safe escalation hint；只有用户显式 `转为引导讲解` 才修改 mode 并建立 guided focus。
- trusted evidence 使节点 completed 后进入 completion pause，投影完成摘要与最新 roadmap candidate，但不自动修改 workspace knowledge key 或发起 next Turn。
- 只有显式 `进入下一知识点` 才重新验证 roadmap 并 admission 下一 session 的首个 Turn。

### R6 — Action Shelf authority

- Aearn 根据 checkpoint/pause/runtime/request state 生成 closed `TeachingActionShelfV1`。
- 每个状态最多一个 primary、三个 visible secondary，其余 overflow。
- active Turn runtime controls、blocking typed request/Generated UI 与普通 shelf 互斥。
- mode switch 和 artifact-local mutation 不被重复投影为第二个提交入口。

### R7 — 可观测性与隐私

- trace 只记录 session/version、stimulus/action enum、source IDs/hashes、context selection、budget、interrupt type 与终态。
- 不记录 raw learner question、教学正文、prompt、reasoning、provider body、submission 或 hidden evidence。

## 验收标准

- [ ] entering knowledge 后只产生一个首个教学 Turn，完成后 provider 调用数保持稳定直到新事件。
- [ ] 同一 fixture 的不同 learner response 产生不同但合法的 closed action 序列，不被固定阶段流程绑死。
- [ ] 用户在解释、示例、理解检查、反馈期间插问，系统先回答并能恢复/调整/放弃原 focus。
- [ ] 用户纠正或拒绝后，旧 focus/action 立即失效且不重复被拒路径。
- [ ] invalid handle、extra field、missing required teaching context、stale version 全部 fail closed。
- [ ] free-reading 普通问题回答后不自动切 Guided；深度教学只出现显式 escalation action。
- [ ] completed 后停留当前 session；无显式 transition 时不改 knowledge key、不创建 provider Turn。
- [ ] Action Shelf descriptor 由服务端生成，满足唯一 primary、最多三个 secondary 与状态互斥。
- [ ] fake provider focused/full tests、Ruff、Mypy、Trellis validate 与 `git diff --check` 通过。

## 风险与控制

1. **模型变成工作流引擎**：模型只选 enum/handles，所有 mutation 和 UI descriptor 由 Aearn 生成。
2. **机械教学**：状态机不规定固定阶段，只限制合法动作、边界和停止条件。
3. **连续自动调用**：每次终态原子写 pause/checkpoint，下一 admission 必须有 durable 新 stimulus。
4. **上下文漂移**：current stimulus、focus 和 assignment fence 为 required，冲突 fail closed。
