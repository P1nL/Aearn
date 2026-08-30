# 技术设计

## 1. 设计目标

本任务把学习工作区建立为三个时间尺度协作的系统：长期 `LearningTrack` 继续拥有路线、进度与掌握度；中期 teaching session 保存一个知识点内可恢复的教学意图与焦点；短期 fresh finite `TurnRun` 每次只执行一个有边界的教学动作。状态机只约束 authority、合法动作、并发、恢复和终止，模型在服务端闭合动作集合内选择当前最合适的讲解方式。

设计必须同时满足：默认 Harness 主导、任意时刻可插问或切换自由阅读、Lesson/Gate/Review authority 不被聊天覆盖、数周后仍能恢复主线，以及没有新事件时绝不连续调用 provider。

## 2. Authority 与边界

| 层级 | Source of truth | 可以决定 | 不能决定 |
| --- | --- | --- | --- |
| LearningTrack / plan / progress / mastery | PostgreSQL 现有领域表与服务 | 当前路线、节点 availability、完成与解锁 | 根据聊天或阅读时长伪造掌握度 |
| LessonDocument / assignment | active frozen assignment 与 immutable document | 教材正文、block、citation、版本迁移 | 由模型自由创建 block 或静默换教材 |
| Gate / Attempt / ReviewSession | 现有领域服务 | 练习、评分、反馈、复习 evidence | 由 Desktop 或模型重算结果 |
| Teaching session | 新增 PostgreSQL authority | 模式、目标、焦点栈、未解决问题、覆盖摘要、停顿与允许动作 | 复制整份教材、完整聊天、provider reasoning |
| TurnRun | 现有 Harness runtime + 新 teaching scope | 一次 fresh finite 教学动作、receipt、终态 | 充当数周路线状态或静默创建下一 Turn |
| Desktop | 服务端 projection + 临时 presentation state | 布局、展开、滚动跟随暂停、草稿 | 推断 allowed action、mode、完成或下一节点 |

一条 LearningTrack 继续只使用一条 track-scoped `TutorConversation`。知识点 teaching session 是该 conversation 下的中期分段，不是第二套 conversation authority。

## 3. 持久化状态模型

### 3.1 `tutor_teaching_sessions`

建立 `user_id + track_id + conversation_id + knowledge_key` 范围内的 session 根，建议包含：

- `id`、owner/scope IDs；
- `status`: `active | paused | completed | blocked`；
- `mode`: `guided | free_reading`；
- active assignment/document identity 与版本/hash fence；
- current checkpoint/version；
- 创建、最后活动、暂停、完成时间；
- optimistic version 与幂等 mutation identity。

同一 owner/track/knowledge key 最多一个当前非终结 session；历史 session 保留 lineage，但不能同时成为 Composer scope。

### 3.2 `tutor_teaching_session_checkpoints`

使用 append-only、predecessor-linked checkpoint 保存可恢复的有界结构化状态：

- objective 与 active focus；
- bounded suspended focus stack；
- bounded unresolved questions；
- covered concepts 的安全摘要与 source handles；
- 最近 Gate/Review/progress evidence cursor；
- pause reason 与推荐下一动作；
- closed `allowed_actions` projection 的权威输入；
- track/plan/progress/assignment/session versions；
- source run、source trigger、policy/schema version 与安全 hash。

checkpoint 不保存完整 Lesson、完整消息、完整提交、hidden rubric/test、provider prompt/body/reasoning 或 raw tool result。

### 3.3 `tutor_run_teaching_scopes`

为每个 teaching `TurnRun` 建立 immutable one-to-one scope snapshot，固定：

- teaching session/checkpoint/version；
- conversation/track/knowledge key；
- mode；
- active assignment/document fence；
- trigger identity；
- action policy version 与允许的 Lesson/Gate/Review handles。

任何 scope、session version、assignment、progress 或 trigger 失配都使结果 stale/superseded，禁止提交教学 checkpoint 或公开陈旧动作。

### 3.4 生命周期与数据治理

新 user-owned 表必须加入 cutover target inventory、local export/reset/delete 与 exhaustive schema classification。删除按 child-to-root；export 只包含 learner-safe session summary、模式、状态和可理解的未解决问题，不输出内部 hash、prompt、reasoning、完整提交或私有测试。Schema additive-first，`bootstrap` 连续执行两次必须幂等。

## 4. 结构化 Turn stimulus

当前 `tutor_run_input_events` 绑定 learner `message_id`，不能用伪造 learner message 表示“进入知识点”“继续”“返回主线”或 Gate terminal event，也不能滥用 proactive origin。

新增 exact one-of `TutorTurnStimulus`：

```text
learner_message(message_id, input_revision)
  | teaching_control(control_key, client_action_id, expected versions, safe payload)
  | domain_event(event_kind, source_id, source_version, safe handles)
```

每个 interactive teaching run 必须且只能固定一个 current stimulus：

- learner message 使用现有 `current_input`；
- teaching control/domain event 使用新 `current_teaching_event`；
- 两者不能同时存在，也不能都为空；
- server-created event 只允许 closed key 与 server-owned target；
- 重试复用同一 durable stimulus identity，不重放 mutation；
- 不把 control/event 文本写成 learner message。

## 5. Harness 教学执行 Loop

### 5.1 上下文顺序

新增 required `TEACHING_SESSION` section，教学 Turn 的确定性优先级为：

```text
SYSTEM/POLICY
CURRENT_INPUT 或 CURRENT_TEACHING_EVENT
TEACHING_SESSION
REQUIRED_FACTS
EXACT LESSON/GATE/REVIEW REFERENCES
ACTION_RECEIPTS
BOUNDED RECENT_MESSAGES
STRUCTURED TEACHING SUMMARY
LEARNER_MEMORY / ACTIVITY
CAPABILITY_SCHEMAS
```

teaching session、active focus、assignment fence 或 current stimulus 无法完整表示时 fail closed，不调用 provider 猜测。

### 5.2 Closed teaching action

扩展 typed provider decision，使模型最多选择一个教学语义动作，而不是定义 UI 或数据库 mutation。首版 closed enum：

- `orient`；
- `explain_concept`；
- `answer_question`；
- `show_example`；
- `compare_examples`；
- `check_understanding`；
- `recommend_practice`；
- `explain_feedback`；
- `remediate_prerequisite`；
- `summarize_progress`；
- `recommend_pause`；
- `wait_for_input`。

模型只引用服务端提供的 objective/focus IDs、Lesson block handles 和 evidence handles。Aearn 验证 active focus、action allowlist、scope/version、预算、幂等与 learner-safe public output，再持久化消息、checkpoint、pause state 和 Action Shelf projection。

### 5.3 单步主动、逐段停顿

每个新事件最多产生一个 fresh finite `TurnRun`。一次 Turn 可以输出一段解释、一个例子和必要引用，但只能服务一个中心问题。提交成功后必须进入以下一种停顿：

- `soft_pause`：可继续、换例子、提问或自由阅读；
- `evidence_pause`：等待理解检查、Gate/Review 等真实证据；
- `authority_pause`：等待 assignment/progress/migration/conflict 处理；
- `session_pause`：用户暂停或 mode 阻止主动推进；
- `completion_pause`：知识点 completed，等待显式 transition。

没有 learner input、typed control、domain terminal event、authority refresh 或显式恢复事件时，不创建下一 Turn。

### 5.4 中断与焦点恢复

最新 learner input 始终覆盖旧 plan、summary、memory 与推荐动作。用户插问时 checkpoint 保存原 focus，将问题放入 bounded child focus；回答后由 closed result 明确选择恢复主线、调整目标或等待用户。纠正、拒绝、目标变化或显式跳过会使陈旧 focus/action 失效。焦点栈和未解决问题都必须有深度、数量与压缩上限。

## 6. 服务端 Action Shelf contract

API 只投影 closed descriptor，不接受模型自由 label/target/payload：

```text
TeachingActionShelfV1(
  schema_version,
  teaching_session_id,
  session_version,
  checkpoint_id,
  state,
  primary_action?,
  secondary_actions[0..3],
  overflow_actions[],
)

TeachingActionDescriptor(
  key,
  label,
  emphasis,
  enabled,
  disabled_reason?,
  target_kind,
  target_id?,
  expected_versions,
)
```

服务端负责动作排序、唯一 primary、最多三个直接 secondary、目标校验和 conflict 刷新。`guided/free_reading` 顶栏切换可以复用 typed teaching mutation，但不进入 Action Shelf；Gate/Hint/Run/Submit 等 artifact-local mutation 不重复投影；active Turn runtime controls 与 blocking typed request/Generated UI 拥有 Composer 上方槽位，不能与普通 shelf 同时绕过约束。

## 7. API 与 projection

建议在 LearningTrack 范围提供 additive API：

- `GET /api/learning-tracks/{track_id}/teaching-sessions`：bounded session 列表与历史摘要；
- `GET /api/learning-tracks/{track_id}/teaching-sessions/{knowledge_key}`：当前 session、checkpoint、allowed actions、completion 与 follow target；
- `POST /api/learning-tracks/{track_id}/teaching-sessions/{knowledge_key}/open`：创建/恢复 session，并在合法时 admission 一个首个/恢复教学 Turn；
- `POST /api/learning-tracks/{track_id}/teaching-sessions/{session_id}/actions`：提交 closed typed control；
- 内部 domain-event admission：Gate/Review/progress/assignment terminal 事件以 durable source identity 触发一次有限 Turn。

所有 mutation 使用 `client_action_id`、expected session/track/progress/assignment versions 与 safe 404/409。`进入下一知识点` 必须提交服务端上次投影的 candidate key，但服务端重新读取最新 roadmap 验证其仍 available；不得使用 Lesson `next_steps` 文本或模型建议决定目标。

Tutor conversation snapshot/SSE projection additive 增加 teaching session grouping metadata、current session、checkpoint、pause、Action Shelf 和 exact cross-session reference identity。旧 conversation/history 保持可读；未具备 teaching session 的历史不批量推断，只投影为 legacy/unscoped read-only history。

## 8. Desktop 架构

### 8.1 单一挂载与角色换位

`TrackLearningWorkspace` 增加 teaching workspace controller，但继续只挂载一份 `TutorConversationSurface` 和一份 `LessonDocumentPage`。通过 CSS grid area、尺寸和可见角色交换主次，禁止复制 SSE reducer、conversation、document assignment 或 Gate state。

- `guided`：左路线 / 中 Tutor 教学 / 右 Lesson 文档；
- `free_reading`：左路线 / 中 Lesson 文档 / 右同一 Tutor 会话；
- 中间主区域右上角固定双向转换箭头，有 accessible name、tooltip、focus-visible、pending/disabled；
- mutation 失败恢复原模式，保留 Composer draft、references、selection 与滚动位置。

### 8.2 文档跟随

Guided 初始根据服务端 exact Lesson block handle 定位。用户滚动、键盘浏览、选择文本、展开来源或操作 Gate 后，本地 view state 进入 `follow_paused`；后续 focus 变化只更新“回到当前讲解”目标，不抢夺滚动。进入 free reading 无条件暂停；返回 guided 仍暂停，直到用户显式恢复或进入新 knowledge/session。reduced motion 使用无动画定位。

### 8.3 Conversation 分段

UI 按 teaching session grouping 同一长期 conversation：当前 session 展开、历史 session 折叠只读。展开历史不改变 active scope、Composer、input revision 或 next action；引用旧 session 内容时生成 exact cross-session reference，而不是复制文本伪造当前 focus。

### 8.4 Interaction dock

中间模型表面底部顺序为：

1. `Composer Action Shelf` 或当前 runtime/request 占位；
2. draft reference chips；
3. Composer；
4. send/runtime controls。

普通 shelf 最多一个 primary、三个 visible secondary，更多进入 overflow；desktop 次动作左/主动作右，390px 主动作全宽优先。shelf 更新不清空草稿、引用或焦点，不自动聚焦、不重复 mutation。

### 8.5 响应式

1440px 使用三栏；约 900px 保持主区域并把次要面板变为受控 drawer/窄栏；390px 使用可访问 tab/segment 切换。所有形态复用相同 mounted authority/controller，不创建第二套状态。

## 9. 长期上下文、摘要与检索

当前 session required focus/objective 和最新纠正始终高于旧 session summary。checkpoint 生成 bounded structured teaching summary；压缩只退休已被摘要覆盖且不受 active focus、未解决问题、纠正或唯一 evidence 保护的消息。跨知识点默认只选择前序/相关 session 的 frozen summary 或 exact reference，不全量重放数周 conversation。summary 的 source IDs/hashes 与版本失配时标记 stale 并重建，不能覆盖最新 authority。

## 10. 兼容、发布与回滚

- Schema、API 和 snapshot additive-first；旧 track conversation 和 Lesson reader 数据保持可读。
- 新 teaching session 功能可由 server feature gate 停止 admission；关闭时保留已有 session/checkpoint，工作区降级为自由阅读 + reactive Tutor，不删除数据。
- closed teaching action 协议不支持时 fail closed 到普通 reactive answer，不启用连续主动教学。
- UI rollout 异常时可关闭角色换位与 Action Shelf，继续读取旧 conversation/document；不能回滚数据库 authority 为客户端 localStorage。
- 不对历史消息批量 backfill session/focus，不修改生产数据，不调用真实 provider 作为默认验证。

## 11. 可观测性与隐私

trace/receipt 仅记录 session/version、stimulus/action enum、focus/evidence source IDs 或 hash、context selection、预算、interrupt type 与终态。不得记录完整问题、教学正文、submission、prompt、reasoning、provider body、命令、路径、容器或 secrets。公开 API/export 同样只返回 learner-safe projection。

## 12. 子任务边界与顺序

1. `08-22-harness-teaching-session-authority`：先建立 DB authority、immutable run scope、结构化 stimulus、基础 repository/service/API 与治理边界。
2. `08-22-harness-closed-teaching-action-loop`：依赖 Child 1，加入 closed teaching action、专用 Skill、context/decision gate、单步停顿、中断恢复和服务端 Action Shelf projection。
3. `08-22-guided-free-reading-workspace-ui`：依赖 Child 1/2，消费服务端 projection，实现角色换位、session 分段、文档跟随和 Composer Action Shelf。
4. `08-22-adaptive-learning-integration-evals`：依赖前三个 child，完成 Gate/Review/long-context 集成、跨层 eval、bootstrap/cutover/privacy 覆盖与 source-of-truth 文档。

父任务没有直接产品代码；只拥有总需求、跨 child contract、顺序和最终集成验收。
