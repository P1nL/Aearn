# 技术设计

## 1. 组件边界

保留现有 `TrackLearningWorkspace` 作为页面编排入口，新增 `useTeachingWorkspaceController` 或等价 controller，集中处理：

- current teaching session projection；
- server-authoritative mode/status/checkpoint/action shelf；
- open/action mutation 与 expected versions；
- track/roadmap/Lesson/conversation 加载协调；
- stale request abort 与 conflict refresh。

`TutorConversationSurface` 与 `LessonDocumentPage` 继续各自负责自身交互，但只能挂载一次。布局组件通过稳定 key 和 CSS grid areas 移动角色，不通过条件分支销毁重建。

## 2. Types 与 API parsing

在 `types.ts` 为 teaching session、checkpoint summary、stimulus metadata、Action Shelf、session groups、follow target 与 completion projection建立 exact union。`api.ts` 把响应视为 `unknown`，逐字段验证 schema version、enum、ID、数组上限和 nullable fields；invalid payload 进入可见 API error，不能部分渲染或 cast。

mutation 请求使用 bounded client action ID、expected session/checkpoint/track/progress/assignment versions。409 后 controller 读取新 projection并保留本地 draft/reference/selection，不自动重放 action。

## 3. Layout

```text
Guided
[Roadmap] [Tutor teaching primary] [Lesson secondary]

Free Reading
[Roadmap] [Lesson primary]         [Tutor assistant secondary]
```

中间区域拥有 `WorkspaceModeSwitch`。按钮视觉小但触控区域至少满足现有 DSH 规范；使用 bidirectional/swap icon，加可读 `aria-label` 与 tooltip。pending 时禁用重复 mutation，并展示非破坏性状态。

响应式：

- 宽屏：三栏；
- 900px：roadmap 保持窄栏，secondary surface 为可控窄栏或 drawer；
- 390px：roadmap、primary、secondary 使用 tab/segment，Composer 与 primary action 固定可达；
- 所有模式共享 controller/component state，不复制 DOM authority。

## 4. 文档跟随 state

`LessonFollowState` 是客户端 presentation state：

```text
following | follow_paused
latestTarget(blockHandle, documentHash, label)
```

触发暂停：wheel/touch/scroll intent、键盘导航、selection、citation/source disclosure、Gate interaction。程序性定位使用 guard 防止把自身 scroll 误判为用户暂停。

收到新 follow target：

- mode=guided、state=following、assignment/hash 匹配 -> 定位；
- 其余 -> 只更新“回到当前讲解”；
- mode=free_reading -> 始终不定位；
- new knowledge/session -> 可重置为 following，但不得从旧 scroll offset 推断教学事实。

reduced motion 关闭平滑滚动；显式恢复后将目标标题纳入 accessible status。

## 5. Session timeline grouping

conversation snapshot 提供 `teaching_session_id` / `knowledge_key` group metadata。前端使用稳定 group ID：

- active group 完整渲染并持有 Composer；
- historical groups 默认只显示标题、状态、时间、bounded summary；
- 展开后读取/显示只读 messages；
- historical selection 通过 existing reference system 增加 exact session/message reference。

不得通过 DOM 顺序、标题或消息正文推断 group。

## 6. Composer Action Shelf

新增受控 `ComposerActionShelf`：

```text
props = {
  projection,
  pendingActionKey,
  runtimeState,
  blockingRequest,
  onAction(descriptor),
}
```

优先级：blocking request > active runtime controls > ordinary shelf。mode switch 与 artifact-local actions 不进入该组件。组件不自行计算 enabled/target；只在提交时附带 descriptor expected versions 与新 client action ID。

布局：desktop secondary 左、primary 右；中屏可换行；390px primary 全宽第一，最多两个高频 secondary，其余 overflow。pending 只禁用冲突动作，保留 Composer draft/reference 与输入焦点。

## 7. Completion 与 free reading

completion summary 是 timeline item，Action Shelf 只显示下一步。free-reading reactive answer仍写入 active session group；若 server 投影 escalation，则显示 `转为引导讲解` primary，拒绝/忽略不改变 mode。next-node action 成功后 controller 更换 current knowledge/session并允许首个 teaching Turn；冲突仅刷新。

## 8. 测试设计

Vitest/RTL：

- strict parser good/bad；
- single mounted Tutor/Lesson 与单 SSE；
- mode pending/success/conflict rollback；
- follow pause/resume/hash mismatch/reduced motion；
- session grouping/read-only history/cross-session reference；
- shelf limit/order/overflow/runtime/request/artifact互斥；
- draft/reference/focus preservation；
- completion no auto navigation。

Browser：disposable fake App Server/provider，三视口，DOM/console/network/overflow/keyboard/screenshots；不创建真实用户/provider数据。
