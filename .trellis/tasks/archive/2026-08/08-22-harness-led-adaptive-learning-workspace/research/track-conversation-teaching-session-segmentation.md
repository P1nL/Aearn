# Track Conversation 与知识点 Teaching Session 分层

**记录日期：** 2026-08-22  
**状态：** 已确认产品方向，用于后续数据库、API、Harness context 与 Desktop 设计；不代表实现已获批准。

## 1. 决策

每条 LearningTrack 继续使用一条长期 track-scoped Tutor conversation，承载跨知识点的学习关系和公开消息 authority。在 conversation 内按知识点建立 teaching session，Desktop 默认只展开当前知识点 session，先前知识点/session 折叠为可展开只读历史。

该结构避免两个极端：

- 默认显示数周到数月完整 timeline，导致当前焦点被淹没；
- 每个知识点创建独立 conversation，导致跨知识点纠正、偏好和学习关系断裂。

## 2. 三层身份

```text
LearningTrack
└─ Track-scoped TutorConversation（长期）
   ├─ TeachingSession: python.variables
   │  ├─ TurnRun / messages / checkpoints
   │  └─ structured session summary
   ├─ TeachingSession: python.collections
   │  ├─ TurnRun / messages / checkpoints
   │  └─ structured session summary
   └─ TeachingSession: python.functions（当前）
      ├─ active focus / unresolved questions
      └─ fresh finite TurnRuns
```

- LearningTrack：路线、计划、进度、mastery 和 review authority。
- TutorConversation：长期 learner-visible conversation/event scope。
- TeachingSession：一个知识点的当前教学目标、焦点、模式、恢复与显示分段。
- TurnRun：一次有限教学动作或等待点。

## 3. Session 生命周期

进入 knowledge key 时：

1. 校验该节点属于 active plan 且可学习；
2. 读取或创建该 knowledge key 的 active teaching session；
3. 绑定 active assignment/document、track/plan/progress version；
4. 从 session checkpoint 恢复 guided/free-reading mode、focus 和 unresolved questions；
5. 必要时创建一次 system-triggered first/resume Turn。

切换知识点不会创建新的普通 conversation。历史 teaching session 可以 paused/completed/blocked，但其消息、summary 和 evidence lineage 保留。

## 4. Desktop 默认投影

Guided 中间教学区默认显示：

- 当前 teaching session 时间线；
- 当前目标和 active focus；
- bounded 恢复摘要；
- 与上一知识点的必要关系；
- 当前 typed controls 与 Composer。

先前 session 按知识点折叠，只显示 learner-safe 标题、状态、时间和短摘要。用户可以展开查看，但展开行为不切换 active session，也不改变 Composer/Turn scope。

## 5. 跨 Session 连续性

跨知识点连续性不依赖 UI 展开完整历史，而由以下来源组成：

1. 当前 track/plan/progress/mastery facts；
2. 当前 teaching session focus/objective；
3. 前一 session bounded completion/resume summary；
4. 相关先前 session summary；
5. 用户显式选择的 cross-session reference；
6. bounded recent conversation messages。

固定优先级仍是当前输入和当前 session authority高于旧 session summary。旧知识点的结论不能覆盖用户最新纠正或当前 Lesson/Gate 状态。

## 6. 历史引用

用户从先前 session 选择一条教学内容、问题或 learner-safe evidence 时，客户端发送 exact session/message/reference identity。服务端校验同 user、track、conversation 和可公开 projection 后生成 bounded cross-session reference。

不得：

- 把旧消息复制进当前 learner content；
- 因 UI 展开历史而自动把全部历史放入 provider context；
- 让旧 session 的 active focus 成为当前 focus；
- 从自由文本猜测用户指的是哪个先前知识点。

## 7. SSE 与消息分组

Conversation SSE 继续按同一 conversation 顺序提供 learner-safe events。Desktop reducer 按服务端提供的 teaching session identity 对 timeline item 分组，而不是开多条 SSE。

历史消息缺少 teaching session identity 时保持 legacy/ungrouped 兼容，不从文本猜 knowledge key；新教学 Turn 必须写 immutable teaching session scope。

## 8. 验收重点

- 一个 track 对应一个长期 conversation，多个知识点对应多个 teaching sessions。
- 当前 session 默认展开，历史 session 默认折叠。
- 展开历史不改变 active Turn、Composer、mode 或 focus。
- 切换知识点不会重复创建 conversation/SSE。
- 跨 session 引用经过 user/track/conversation/session/message scope 校验。
- 模型上下文能使用相关 summary/reference，但不会默认全量重放长期 conversation。
- 刷新、重连和跨日恢复后 session grouping 与当前 focus 一致。
