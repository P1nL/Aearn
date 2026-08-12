# 三栏学习工作区与结构化上下文引用

## 目标

在 verified Tutor shell 内交付可恢复的 track-scoped 学习工作区：左侧路线与入口、中间 Lesson/Review/嵌入式 Practice、右侧 scoped Tutor；让课程选择、练习反馈、执行结果和复习反馈以服务端验证的结构化引用进入模型上下文并随 learner message 重放。

## 背景与已确认事实

- `LearningTrack`、路线、LessonDocument、Gate/受控执行、模型代码审核、ReviewSession、authoritative facts 与 Action Runtime 已由前置 child 交付。
- 当前 Desktop 仍把 Lesson 作为独立页面，并把 Review 导向“尚未交付”；Tutor 对话未携带 artifact 引用。
- 当前 Tutor 输入事务已经固定 learner message、fresh finite `TurnRun` 与 `input_revision`，适合在同一外层事务中追加不可变引用快照。
- 当前仓库没有独立的通用 `PracticeSession` 公共 API；本 child 的 Practice 主路径由 Lesson Gate、受控执行和模型代码审核练习承载，不新增虚假的客户端练习权威。

## 依赖

- `08-04-learning-home-plan-builder`。
- `08-04-lesson-document-authority-grounding`。
- `08-04-exercise-gates-execution-unlock`。
- `08-04-spaced-review-sessions`。
- `08-04-model-code-review-exercises`。
- `08-12-tutor-authoritative-context-facts`：右侧 Tutor 必须使用统一 authoritative facts/question snapshot。
- `08-12-tutor-controlled-action-runtime`：工具状态、verification、recovery 和 safe receipt 由统一 action projection 提供。

## 范围内

### R1 — 三栏工作区与恢复

- 左栏显示 active roadmap 的模块、知识点、当前节点、服务端进度、今日复习入口和可用练习入口。
- 中栏按当前模式显示 LessonDocument、ReviewSession 或 Lesson 内嵌 Practice，并保持独立滚动。
- 右栏显示绑定当前 track 的 Tutor conversation、当前 artifact scope、结构化引用预览和安全反馈。
- 宽屏使用三栏；中等宽度将路线折叠为 drawer；窄屏使用可键盘切换的 panel tabs，当前 Gate 和 composer 始终可达。
- 本地只保存版本化导航指针；刷新后必须重新向服务端读取并校验 track、roadmap、Lesson/Review、conversation history 与 pending attempt。

### R2 — Gate 可见性与滚动

- 中栏只渲染服务端返回的 Lesson blocks 与 Gate projection；locked 后续内容不能通过 CSS、DOM 或本地状态出现。
- 当前已解锁知识点可直接滚动到末尾 Gate。
- required Gate 通过后重新读取 Lesson/Gate 权威响应，扩展可见范围并保持合理阅读位置。

### R3 — 结构化引用契约

- 支持 `lesson_selection`、`exercise_feedback`、`execution_result`、`review_feedback` 四种严格 typed reference。
- `lesson_selection` 至少携带 track、knowledge key、document id/hash、block、选择范围和候选 excerpt；服务端从当前同用户同 track 的 Lesson artifact 验证并派生 safe excerpt。
- feedback/result 引用只接受同用户同 track 的真实 terminal Attempt/ReviewSession，并只快照 learner-safe projection。
- 引用在 composer 前可预览、去重和移除；发送后在同一 Tutor 输入事务内绑定 learner message、run 和 `input_revision`。
- 新建引用拒绝跨用户、跨 track、跨 artifact 和过期当前指针；已持久化的 frozen document/feedback 快照在后续迁移后仍可重放。
- 引用不得拼进 learner 正文；模型上下文通过独立、受限、可审计的 structured source 注入。

### R4 — Tutor 与反馈

- 每个 track 使用显式 conversation scope；普通消息继续创建 fresh finite `TurnRun`，artifact/task scope 固定到该 run。
- Lesson 使用 `lesson_teaching`，练习结果使用 `exercise_feedback` 或 `model_code_review`，Review 使用 `review_coaching`，补救使用 `remediation`。
- 提交前优先展示渐进提示，不直接泄露答案；提交后可引用评分、测试证据和补救路径。
- 运行结果只显示 learner-safe projection，不显示 hidden test body、命令、容器、路径或 raw stderr 内部信息。
- 切换 user、track、mode、knowledge key 或 session 时取消旧 SSE/请求并清空旧 references、stdout、feedback 与 composer scope。

### R5 — 可访问性与错误恢复

- 路线、drawer、tabs、引用 chips、Gate 和 Review 流程支持键盘、焦点可见、状态文本和 reduced-motion。
- API offline、model unavailable、stream incomplete、execution unavailable、Review blocked 和 version conflict 都提供稳定重试或返回路径。
- 不依赖 hover 才能理解状态，不使用任意 HTML 渲染。

## 验收标准

- [x] 宽屏三栏、中等宽度 drawer 与窄屏 panel tabs 均可完成继续 Lesson、Gate/练习、Review 和 scoped 提问主路径。
- [x] 路线和中栏只消费服务端进度/允许动作，locked 内容不能由前端绕过。
- [x] 文本/代码选择、练习反馈、执行结果和复习反馈以不同 typed reference 发送，绑定 message/run revision，并可从历史重放。
- [x] 新引用不能跨用户、track、document/version 或 attempt 冒用，也不能冒充 learner content；持久化 safe snapshot 不因后续 artifact 迁移失效。
- [x] track/session/artifact 切换不会残留旧 SSE、stdout、feedback、references 或 composer scope。
- [x] ReviewSession 的 warmup、hint、attempt、poll、finalize 与恢复路径使用服务端 version/idempotency contract。
- [x] 已确认 planning/learning facts 与 action safe projection 在切换、刷新和 resume 后保持一致，UI 不根据聊天文本自行推断事实、question state 或 action 状态。
- [x] 页面刷新、错误、离线、窄屏、键盘和焦点 smoke 通过。
- [x] `pnpm --dir .\aearn desktop:check`、相关 API/contract 测试、lint 与 typecheck 通过。

## 范围外

- 改变 cutover 权威或恢复旧页面/router。
- 新增尚无后端权威的通用 `PracticeSession`；本 child 复用 Lesson Gate 与 Model Code Review。
- 前端计算评分、掌握度、解锁、due、execution tier、question state 或 action 状态。
- 把引用文本直接拼进 learner content，或向模型暴露 hidden rubric、hidden tests、raw provider body、命令、容器和内部路径。
- 通用富文本编辑器或任意 HTML 渲染。
