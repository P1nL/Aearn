# 技术设计

## Component composition

```text
TutorConversationSurface
  HistoryController
    TutorMessage
      TutorThinkRow
  ActiveRunController
  TutorQueueDock
  ComposerSeat
    TutorQuestionComposer | TutorComposer(send/stop)
  FloatingPlanInspector
    TutorPlanReviewPanel
```

`TutorConversationSurface` 只协调 conversation selection、history refresh、SSE subscription 和 controlled action handlers；业务组件不直接读 DSH runtime。

## Composer seat state

优先级：

1. `pending_input` 且 kind 为 clarification/planning_input -> Question takeover。
2. 否则普通 Composer；active run 若 cancellable -> primary stop，否则 primary send/queue。
3. `awaiting_effect_commit` 显示不可中断状态反馈，不伪造 stop。

Typed takeover 时 QueueDock 与普通 textarea 不渲染，防止普通消息和 typed answer 歧义。

## Queue UI

从 DSH `QueueDock` 派生 controlled props：items、running、mutable、busy item、onEdit/onRemove/onSteer/notify。response/SSE/history 全部替换本地 snapshot；local state 只持 editing text、collapsed 和 pending action。

## Question UI

根据 `TutorPendingInput.presentation` 渲染：

- text -> textarea。
- single_select -> radiogroup + optional custom。
- multi_select -> checkbox group + custom + max selected。

local drafts keyed by `pending_input_id`。移除 upstream close/skip handler和按钮；提交 handler始终带 pending identity/revision。

## Think

派生 DSH `ReasoningRow` 结构，只传 `public_thinking_steps`。标题硬编码产品决策 `Think`，正文为纯文本列表。process item 在 timeline switch 中 `return null`，不改后端 parser。

## Plan inspector

保留现有 placement/open persistence。内部 card/strip/body/footer/actions CSS/markup 派生 PlanReviewPanel；plan body 使用现有 typed route/module renderer。Discuss 聚焦普通 Composer，Approve 调现有 confirm action，page top Cancel 保持独立。

## CSS migration

- 新组件 CSS modules 使用 Child 1 tokens。
- 页面 layout/root 仍可在 `styles.css`，但 Tutor-specific duplicated controls逐个迁移。
- 每删除一组旧 class 前先搜索引用并跑浏览器 regression；不做全文件格式化。

## Testing/browser

- Testing Library：controlled action calls、aria、keyboard、IME、pending identity reset、Queue edit lifecycle。
- fake API browser fixture：持久化 Queue、stop、Typed Question、plan draft。
- viewport 1440/900/390、prefers-reduced-motion、console/overlay/overflow assertions。

## 回滚

保留旧 Tutor renderer/CSS 到新 integration 完整通过；切换应集中在一个可恢复的 feature-level diff。后端 Child 2/3 authority 不随 UI rollback 删除。
