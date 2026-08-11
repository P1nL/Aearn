# 练习 Gate、模块诊断与受控执行解锁

## 目标

在已完成的 LearningTrack、掌握度投影和 LessonDocument authority 之上，实现可版本化、可审计、服务端权威的练习 Gate、append-only 尝试、模块级独立诊断、受控执行反馈和路线解锁，使学习者能够在当前已解锁知识点内完成练习并推进路线，同时只能通过整模块诊断申请跳过模块。

本任务必须复用现有 Tutor execution intent/job/executor 生命周期，不创建第二套执行队列；公开执行只允许 `container_verified`，开发 fixture 可显式使用 `teaching_local`，缺少受审镜像锁或兼容健康状态时必须诚实降级。

## 背景

已完成的 LessonDocument 只发布不可变 `exercise_gate` slot contract。该 contract 的 `gate_kind` 表示教学形态：`knowledge_check | guided_practice | independent_practice`，尚未绑定练习版本、required/recommended/diagnostic 要求、Attempt、评分、执行或解锁状态。

已完成的 LearningTrack 已提供：

- 不可变计划 revision、知识点进度、`diagnostic_skipped` 状态和显式计划激活；
- append-only `tutor_mastery_evidence` 与确定性掌握度投影；
- `teaching_local | container_verified | static_only | unavailable` execution tier；
- 服务端路线 prerequisite、current knowledge key、progress version 与 track version authority。

现有 Tutor 执行队列仍以 Tutor run、conversation、message、effect 和旧 `exercise_id` 为 owner/source。Gate 需要以私有 exercise attempt/submission 为 owner/source 复用同一队列，不能制造虚假 Tutor conversation/message，也不能把完整代码、hidden tests 或 private rubric 放入普通模型上下文。

## 依赖

- `08-04-learning-track-plan-mastery-domain` 已完成并归档。
- `08-04-lesson-document-authority-grounding` 已完成并归档。
- 产品父任务 `08-04-programming-language-learning-agent-product` 保持 `planning`，本任务不启动父任务。

## 范围内

### 练习版本与 Gate binding

- 新增不可变 `tutor_exercise_versions` 和 `tutor_exercise_private_rubrics`，服务端分别拥有公共练习内容与私有评分事实。
- 保留 `tutor_lesson_gate_slots.gate_kind` 的教学形态语义；新增不可变 Gate binding，并用独立 `requirement_kind=required | recommended | diagnostic` 表示是否阻塞路线。
- Gate binding 必须绑定 exact Lesson document/assignment、slot、exercise version、assessment contract、通过阈值、执行要求与 canonical contract hash。
- started Lesson assignment 冻结 Gate binding。Lesson 迁移只有在 slot、exercise、policy 与 contract hash 完全一致时才允许携带 Gate state；否则创建新 state，旧 Attempt 和结果继续保留。

### Gate 状态与恢复

- assignment-scoped Gate state 支持 `available | in_progress | passed | remediation_required`。
- `required` Gate 通过前阻止当前知识点完成和下游知识点解锁；`recommended` 与 `diagnostic` 不阻塞知识点完成。
- 失败后提供有界渐进提示、补救说明和更小练习，不允许永久不可恢复状态。
- 用户可在当前已解锁 Lesson 内滚动到 Gate；客户端不得通过滚动、URL、local state 或直接构造请求访问 locked 知识点。
- 单个知识点不提供“申请跳过” mutation。

### Attempt 与评分事实

- `run`、`submit`、`diagnostic_submit` 均创建 append-only Attempt，绑定 exact user、track、active plan revision、progress version、Lesson assignment、Gate/diagnostic item、exercise version、代码/答案 hash、提示快照、幂等键和 request hash。
- 私有提交正文单独保存为 executor-only artifact；公共 Attempt、API、Conversation、trace、checkpoint 和普通模型上下文只保留 hash、引用和 learner-safe projection。
- `run` 只产生执行反馈，不改变 Gate、mastery、progress 或路线解锁。
- `submit` 的 terminal result 可在服务端事务中更新 Gate、mastery、progress 和路线解锁。
- 无提示完成、提示后完成、补救后完成和多次失败后完成产生不同 independence/attempt summary；前端和模型不得直接写 score、pass、evidence 或 unlock。
- 同一幂等键与相同 request hash 重放原 Attempt/结果；相同键不同请求返回冲突。

### 模块诊断

- 只有模块边界提供“申请跳过模块”，打开独立 diagnostic session，不复用知识点 Gate。
- 诊断版本冻结模块全部核心 capability、题目集合、exercise versions、通过阈值、cooldown 和 policy version。
- 默认版本化策略：每个核心 capability 独立评分且 `score >= 0.80`；全部核心 capability 均达到阈值、全部 Attempt 独立且无提示/补救时才算通过。
- 部分通过或失败不跳过任何知识点、不创建计划 revision；只写不降低既有掌握度的观察证据、薄弱项和个性化建议。
- 全部通过后先创建 predecessor-linked proposed plan revision 和 migration impact；只有用户明确确认后，服务端才激活 successor revision、把模块节点标为 `diagnostic_skipped` 并重算下游可用性。
- 诊断 session、item、Attempt、结果、cooldown、题目版本和确认操作均需幂等、scope-safe、可重放。

### 执行层级与队列复用

- `container_verified`：公开 API 可通过现有 PostgreSQL execution intent/job 队列运行或评分用户代码。
- `teaching_local`：只允许 development composition、测试 fixture 或显式 internal seam；绝不作为公开执行 fallback。
- `static_only`：不显示 Run，不声称已编译/运行/测试；只允许确定性结构化答案练习。
- `unavailable`：执行依赖型练习不提供 Run/Submit，返回稳定 unavailable disclosure。
- 复用并增量扩展现有 `tutor_execution_intents`、`tutor_execution_jobs`、shared execution contracts 和 executor trusted input；保留旧 Tutor-effect 路径的兼容性和安全约束。
- Gate 路径不得创建虚假 Tutor conversation、message 或 effect；使用严格 owner/source one-of 绑定 exercise attempt/submission。
- reviewed image lock 缺失、health 过期/不兼容、executor disabled、runtime profile 不匹配或队列不可用时 fail closed，不调用 host runner 或 legacy runner。

### 练习类型与核心 fixture

首版注册以下受控练习形态：

- `code_completion`
- `sql_query`
- `browser_preview`
- `static_choice` 或 `static_code_reasoning`

提供版本化、可测试的核心 fixture：

- Python：受控 stdout/test 练习。
- JavaScript：browser preview 练习。
- TypeScript：Node TypeScript 练习。
- SQL：SQLite 查询练习。

fixture 是显式 author/source，不是 provider 或 executor 失败时的动态 fallback。本任务不要求真实 provider 生成练习，也不批准构建或发布 reviewed image fleet。

### 数据生命周期与可观测性

- exercise version、private rubric、Attempt、submission、result、hint receipt、diagnostic version/item 和 migration receipt 均采用 append-only 或不可变语义。
- user export 只包含学习者可见的练习、提交摘要、safe feedback、分数、Gate/diagnostic 状态与计划影响；不导出 hidden tests、reference answer、private rubric、完整内部执行信息或 provider/executor diagnostic。
- reset/delete/cutover 必须按 child-to-root 顺序清理 exact user-owned 数据；共享 exercise/diagnostic versions 和 curated fixtures 不因单一用户删除而删除。
- 日志、trace 和错误响应只允许稳定 code、opaque IDs、hash、版本、计数和 learner-safe 摘要。

### 前端网页体验

- 扩展现有 `LessonDocumentPage` 和 registered renderer，不实现后续完整三栏 workspace。
- `LessonDocumentPage` 拥有 Gate server state、prepare、hint、run、submit、poll/replay、stale 与 error；`LessonBlockRenderer` 保持纯展示，通过 typed Gate view/render seam 接收能力面板。
- 新增可复用 `LessonGatePanel`；模块诊断使用独立 `ModuleDiagnosticModal`。
- 首版编辑区使用有界、可访问的 textarea/editor shell，不引入新编辑器依赖。
- 明确显示 execution tier、运行能力和降级原因；代码改变后旧运行结果必须标记 stale 或清除。
- 前端不计算 score、pass、mastery、Gate completion、diagnostic pass 或路线解锁。
- 前端只进行 `http://127.0.0.1:1420` 网页端真实浏览器验证，不执行 Desktop build 校验。

## 范围外

- 间隔复习调度、Review page 改造和模型代码审核题专项生成。
- 完整三栏学习工作区、右侧 Tutor 对话、selection reference 和工作区重组。
- reviewed container image fleet 的构建、签名、发布、运维和生产批准。
- 真实 provider 练习生成、自动题目变体服务和无人工政策的动态 authoring。
- 单个知识点跳过申请。
- 恢复旧 `exercises`/`attempts` 公共 authority 或旧课程 route。
- 新建第二套执行队列、API/ Harness 直接导入 Docker、公开 host subprocess fallback。

## 验收标准

- [x] 已发布 Lesson slot 通过不可变 binding 关联 exact exercise version；`gate_kind` 与 `requirement_kind` 语义分离且有 contract test。
- [x] 当前已解锁 Lesson 可滚动到 Gate，locked 知识点不能通过前端操作或跨 scope API 绕过。
- [x] required/recommended/diagnostic Gate 的状态、提示、失败补救、重放和 stale 行为稳定；只有 required Gate 阻塞知识点完成。
- [x] `run`、`submit`、`diagnostic_submit` Attempt append-only，严格绑定 user/track/plan/assignment/exercise/code hash/hint/idempotency scope。
- [x] `run` 不写 Gate/mastery/progress；terminal `submit` 的 result、evidence、Gate、progress 和 unlock 在同一事务内一致或可安全重试。
- [x] 完整代码、hidden tests、reference answer、private rubric、容器/命令/路径和内部异常不进入公共响应、Conversation、trace、checkpoint 或普通模型上下文。
- [x] 模块诊断只在所有核心 capability 达到 versioned threshold 时产生 proposed plan revision；部分通过不跳过任何节点。
- [x] 诊断失败/部分通过不降低既有 proven mastery；通过后仍需用户确认才激活 `diagnostic_skipped`。
- [x] `container_verified` 是唯一公开代码执行层级；`teaching_local` 仅 development/fixture；`static_only` 无 Run；`unavailable` 不伪造执行能力。
- [x] Gate 路径复用现有 execution intent/job/executor 生命周期，没有第二套队列，也没有虚假 Tutor conversation/message/effect。
- [x] 旧 Tutor execution effect 路径、claim/lease/launch token、redaction 和 recovery 回归测试继续通过。
- [x] Python、JavaScript、TypeScript、SQL 各有一条版本化 Gate fixture；static/unavailable 降级行为有测试。
- [x] API 返回稳定 404/409/422/503 learner-safe errors，跨用户/track/version scope 不泄露存在性。
- [x] PostgreSQL bootstrap twice、constraint/trigger、幂等、并发、executor、API、数据生命周期和回归测试通过。
- [x] Lesson Gate 与模块诊断在 1440px、900px、390px 网页端真实浏览器中可操作、无相关 console error/warning、无 overlay、无水平溢出、键盘焦点可见。

## 完成定义

只有在业务代码、数据库、shared contract、executor、API、前端、source-of-truth 文档和上述验证证据全部完成后，才能将本子任务标记为完成。`task.py validate` 只验证规划工件结构，不代表实施完成或发布批准。

