# Guided/自由阅读工作区与 Composer Action Shelf

## 目标

消费 Child 1/2 的 server-authoritative teaching session、mode、checkpoint、Action Shelf 与 conversation grouping projection，把 verified 学习工作区改为默认 Guided：中间是模型对话教学、右侧是 active Lesson 文档；用户可用中间右上角双向箭头切换 Free Reading，使中间变文档、右侧变同一模型会话辅助面板。

## 依赖与顺序

- 必须在 `08-22-harness-teaching-session-authority` 与 `08-22-harness-closed-teaching-action-loop` 完成后启动。
- 本 child 完成后才能启动最终集成/eval child。

## 范围内

1. Desktop API types、strict unknown parser 与 teaching workspace controller。
2. 单一 Tutor surface / Lesson document 挂载下的 Guided/Free Reading 主次换位。
3. 顶栏双向模式切换按钮与 pending/conflict recovery。
4. Guided 文档混合跟随、暂停与显式恢复。
5. 同一 conversation 按 teaching session 分段，当前展开、历史折叠只读。
6. Composer Action Shelf、runtime/request/artifact-local 互斥。
7. completion projection 与显式 next-node transition UI。
8. 三视口、键盘、focus、reduced-motion、SSE/reload 与 browser smoke。

## 范围外

1. 在前端计算 allowed action、mode、完成、next node、Gate result 或 mastery。
2. 创建第二条 conversation、第二份 LessonDocument、第二套 SSE reducer 或并行 session。
3. 让模型自由定义按钮 label/target/payload 或渲染任意 React/HTML。
4. 重做左侧 LearningTrack 路线或 Lesson/Gate authority。
5. 使用真实 provider/生产数据完成 UI smoke。

## 需求

### R1 — 单一 authority 与 controller

- `TrackLearningWorkspace` 通过一个 controller 加载 track/roadmap、teaching session、Lesson assignment、conversation snapshot 与 run state。
- 一份 `TutorConversationSurface` 和一份 `LessonDocumentPage` 在模式切换时保持 mounted/受控；禁止重复 SSE subscription。
- scope/mode/knowledge/session 变化中止过期请求，但不能误清除服务端 session、草稿或无关引用。

### R2 — Guided/Free Reading 主次换位

- Guided：左路线、中 Tutor 教学、右 Lesson 文档。
- Free Reading：左路线、中完整 Lesson 文档、右同一 Tutor conversation 辅助。
- 双向箭头固定在中间主区域右上角，具备 accessible name、tooltip、focus-visible、loading/disabled 与足够触控目标。
- 切换立即更新受控 pending UI；服务端失败/conflict 时恢复权威 mode并保留草稿、references、selection 与两块滚动位置。

### R3 — 文档混合跟随

- Guided 初始根据服务端 active Lesson block handle 定位。
- 用户滚动、键盘浏览、选择文本、展开 citation/source 或操作 Gate 后进入本地 `follow_paused`。
- paused 后新 focus 不抢滚动/选区，只更新“回到当前讲解”入口；显式恢复后定位最新有效 block。
- Free Reading 永不自动跟随；返回 Guided 仍保持 paused，除非进入新知识点/session 或用户显式恢复。
- exact block handle 与 active assignment/document hash 不匹配时不定位，显示可恢复 conflict。

### R4 — Teaching session 分段

- 当前 knowledge/session timeline 默认展开；历史 session 按知识点/时间折叠只读。
- 展开历史不改变 active scope、Composer、input revision、mode 或 next action。
- 引用旧 session 内容时发送 exact cross-session reference，不复制文本伪造当前 focus。
- 默认不渲染数周完整 timeline；当前 session 顶部显示 bounded 恢复摘要与前序关系。

### R5 — Composer Action Shelf

- interaction dock 顺序为 Action Shelf/占位、reference chips、Composer、send/runtime controls。
- 一个 shelf 只有一个 primary、最多三个 visible secondary，其余进入“更多”。
- desktop 次动作左/主动作右；390px 主动作全宽优先，低频项进入 overflow。
- shelf 只渲染服务端 descriptor；不自由改 label、target、payload、enabled 或 disabled reason。
- active Turn 时 runtime controls 接管；blocking typed request/Generated UI 占据槽位；Gate/Hint/Run/Submit 等留在 artifact 附近。
- shelf 更新不清空 draft/reference、不改变焦点、不自动触发或自动聚焦 primary。

### R6 — Free Reading 问答与 completion

- Free Reading 普通 Composer/选区问题在右侧回答，完成后仍保持 Free Reading。
- 只有显式 `转为引导讲解` 才切 Guided，且原问题、selection/reference 与回答 lineage 不丢失。
- completed 后当前 session 显示服务端 completion summary、真实 evidence、未解决问题和新解锁节点；不自动切知识点。
- `进入下一知识点` 只提交 server descriptor；409 时刷新 roadmap/shelf，不本地重放。

### R7 — 响应式与可访问性

- 1440×900、900×900、390×844 无页面级水平溢出，Composer、mode switch 与 primary action 始终可达。
- 中屏/窄屏通过 drawer/tab/segment 重排，但复用同一 controller 与 mounted authority。
- 键盘顺序、focus-visible、accessible labels、tooltip 与 reduced-motion 正确。

## 验收标准

- [ ] verified 用户进入可学习知识点，默认 Guided 中间出现同一 Tutor teaching session，右侧出现 active Lesson。
- [ ] 双向箭头切 Free Reading 后中间文档、右侧同一 conversation；conversation ID、run、draft、references 和 document assignment 不变。
- [ ] 两种模式始终只有一份 Tutor SSE subscription 和一份 Lesson/Gate state。
- [ ] 用户操作 Guided 文档后，新讲解不抢滚动/选区，并出现可键盘触发的“回到当前讲解”。
- [ ] Free Reading 无自动跟随；返回 Guided 不突然跳转。
- [ ] 当前 session 展开、历史折叠只读；展开历史不改变 Composer scope 或 next action。
- [ ] Action Shelf 唯一 primary、最多三个 secondary；active Turn、blocking request 和 artifact-local action 互斥正确。
- [ ] Free Reading 普通问题回答后不自动切 Guided；显式 escalation 保留原问题与引用。
- [ ] completed 后不自动导航；只有显式 next-node action 成功才进入下一 session。
- [ ] 1440×900、900×900、390×844、键盘与 reduced-motion browser smoke 通过，console 无相关 error/warning。
- [ ] Desktop Vitest、`desktop:check`、Trellis validate 与 `git diff --check` 通过；不调用真实 provider。

## 风险与控制

1. **双实例/重复 SSE**：组件保持单一挂载，模式只改变 layout role。
2. **服务端与本地 mode 漂移**：optimistic pending + authoritative response/conflict rollback。
3. **自动跟随打断阅读**：任意用户文档交互暂停，显式恢复。
4. **按钮泛滥**：服务端 closed shelf + 1 primary/3 secondary 上限。
5. **历史 timeline 膨胀**：session grouping + bounded current projection，历史按需加载。
