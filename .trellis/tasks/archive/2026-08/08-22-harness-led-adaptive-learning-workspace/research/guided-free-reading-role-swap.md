# Guided 与自由阅读双区域主次换位

**记录日期：** 2026-08-22  
**状态：** 已确认产品方向，用于后续 Desktop 与教学会话技术设计；不代表实现已获批准。

## 1. 决策

学习工作区保留左侧路线，并让模型会话与学习文档在另外两块区域之间按模式交换主次。

### Guided 模式

- 中间主区域：模型与用户的对话教学区。
- 右侧辅助区域：当前 active frozen LessonDocument。
- Harness 按“单步主动、逐段停顿”主动教学。

### Free reading 模式

- 中间主区域：完整学习文档、引用与 Gate。
- 右侧辅助区域：同一模型会话，用于选区提问、疑问解答和返回引导。
- Harness 停止主动创建下一教学 Turn。

两种模式不是两个页面或两套状态，而是同一 conversation、Lesson assignment、teaching session 和 workspace scope 的 presentation role swap。

## 2. 切换入口

中间区域右上角放置小型双向转换箭头图标按钮。其含义是交换“教学主区”和“文档主区”，而不是刷新、重建或导航离开。

按钮需要：

- 根据当前模式提供明确 accessible name，例如“切换到自由阅读”或“返回引导教学”；
- tooltip 或可见辅助说明，避免只依赖图标猜测；
- `focus-visible`、键盘触发和足够的触控目标；
- mutation pending 时的 disabled/loading 状态；
- 切换失败时恢复原模式并显示 learner-safe 错误。

图标可以视觉上保持轻量，但交互热区不能过小。

## 3. 不能复制的状态

主次换位只能移动或重排 presentation，不能创建并行 authority。必须复用：

- 同一个 track-scoped Tutor conversation；
- 同一个 active Turn 和 conversation SSE；
- 同一个 teaching session/focus/checkpoint；
- 同一个 active Lesson assignment/document；
- 同一组 Gate、Attempt 与 Review authority；
- 同一个 draft references 集合；
- 同一份未发送 Composer 草稿。

React 实现不得因为位置变化同时挂载两个 `TutorConversationSurface` 或两个具有独立副作用的 `LessonDocumentPage`。

## 4. Guided 模式信息层级

中间教学区优先显示：

1. 当前知识点和教学目标；
2. 当前 active focus 与必要的父焦点提示；
3. 模型与用户的教学时间线；
4. 当前 typed controls 与下一推荐动作；
5. Composer；
6. 模式切换按钮。

右侧学习文档显示 active LessonDocument，可以阅读、选择引用和查看来源，并采用“默认跟随、尊重手动阅读”的混合策略。

### 4.1 默认跟随

当服务端当前 teaching action/focus 引用新的稳定 Lesson block handle，且 active assignment/document hash 匹配、用户尚未暂停跟随时，右侧文档定位到对应 block。定位是 presentation 行为，不产生教学事实或 mastery evidence。

### 4.2 暂停跟随

以下任一明确用户行为立即暂停自动跟随：

- 鼠标、触控或键盘滚动文档；
- 选择 Lesson 文本或代码；
- 展开/收起来源证据；
- 与 Gate、代码编辑器或文档内控件交互。

暂停后，新焦点只更新“当前讲解位置”提示，不移动文档、不清除选区、不改变键盘焦点。

### 4.3 返回当前讲解

文档偏离最新教学 block 时显示轻量、可键盘触发的“回到当前讲解”。点击后：

1. 校验当前 assignment/document/block identity；
2. 定位最新有效 block；
3. 恢复自动跟随；
4. 保持目标 block 的可见焦点反馈。

### 4.4 模式边界

进入 `free_reading` 后完全停止自动跟随。返回 `guided` 时保持暂停，避免突然跳离用户正在阅读的位置；只有用户显式点击“回到当前讲解”，或进入新的知识点/教学会话时才重新启用。刷新不从旧 DOM offset 推断教学状态，可以默认定位当前焦点，但必须以服务端 block identity 为依据。

## 5. Free reading 模式信息层级

中间文档区获得适合完整阅读和 Gate 操作的宽度。右侧模型面板继续显示同一 conversation 的上下文和 Composer，但不主动推进教学。

用户从文档选区提问时，引用仍进入同一 conversation 与 teaching session；返回 guided 后应保持问题、回答、active focus 和文档定位。

### 5.1 普通问题保持自由阅读

用户在右侧 Composer 提问或从中间文档发送选区引用时，系统创建同一 teaching session 下的 reactive finite Turn。模型在右侧回答，Turn 结束后 mode 仍为 `free_reading`，不交换面板、不自动恢复旧 guided focus，也不自动创建下一 Turn。

### 5.2 显式升级为 Guided

如果当前问题需要多步解释、补救、理解检查或练习，模型可以提出安全 escalation hint，但不能直接修改 mode。Aearn 根据当前 authority 投影 `转为引导讲解` typed control。用户触发后：

1. 以 expected teaching session version + idempotency 切换到 `guided`；
2. 将原问题与 exact Lesson selection 建为新的 active/sub focus；
3. 保留右侧回答和 message lineage；
4. 创建至多一个新的 guided teaching Turn；
5. 不要求用户重新输入问题。

用户不选择升级时继续自由阅读，系统不得在后台延伸该教学分支。

## 6. 模式切换事务语义

模式是长期恢复需要的 teaching session 状态，因此切换使用 typed mutation、expected session version 与 idempotency。Desktop 可以先进行受控的即时布局反馈，但服务器拒绝或 conflict 时必须回到权威模式。

模式 mutation 不得：

- 创建新的 Tutor message 或模型调用；
- 创建新的 conversation；
- 修改 progress/mastery；
- 重置 Lesson/Gate；
- 丢弃未发送输入；
- 把自由阅读误记为教学完成。

## 7. 响应式约束

- 宽屏：路线 + 中间主区 + 右侧辅助区。
- 中屏：保持主区，辅助区可以 drawer/可调整窄栏呈现，但切换按钮始终可达。
- 窄屏：一次显示一个主 panel，通过模式和 panel tabs 映射主次；不得同时挂载两份会话或文档。
- 模式切换不应引起页面级横向溢出、焦点丢失或屏幕阅读器上下文断裂。

## 8. 验收重点

- Guided 中间为教学、右侧为文档；free reading 中间为文档、右侧为同一模型会话。
- 模式切换后 conversation ID、active Turn、teaching session、assignment/document ID 与 Gate identity 不变。
- SSE 不重复订阅，历史不重新插入，Composer/reference 草稿不丢失。
- 刷新后从 PostgreSQL 恢复最后确认模式。
- provider unavailable 不妨碍进入自由阅读。
- 图标按钮具备可访问名称、键盘、焦点、loading/error 和 reduced-motion 行为。
- 默认跟随只在未发生手动文档交互时定位当前 block；手动滚动/选择/Gate 操作暂停跟随。
- 暂停后教学焦点变化不破坏 scroll、selection 或 focus；“回到当前讲解”可恢复最新 block 跟随。
- `free_reading` 不自动跟随，返回 `guided` 不突然跳转。
- 自由阅读普通提问在右侧回答且 mode 不变，回答完成后不自动创建下一教学 Turn。
- 深度问题只显示显式“转为引导讲解”；用户触发后保留原问题、引用和回答 lineage。
