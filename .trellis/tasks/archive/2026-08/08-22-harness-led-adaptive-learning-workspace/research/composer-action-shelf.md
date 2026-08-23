# Composer Action Shelf 统一动作方案

**记录日期：** 2026-08-22  
**状态：** 已确认产品决策，用于后续 Desktop/API/Harness 技术设计；不代表实现已获批准。

## 1. 核心方案

所有与当前 teaching session 下一步有关的主动作和次动作统一渲染为 Composer 上方组件 `Composer Action Shelf`。它与 Composer 共同构成底部 interaction dock，并随服务端当前 pause/action projection 动态变化。

```text
教学时间线 / 完成总结 / 回答
────────────────────────────
Composer Action Shelf
- 次动作      次动作      主动作
Draft reference chips
Composer textarea + Send
```

这样用户无论处于解释停顿、自由阅读提问、练习反馈、完成停顿或恢复状态，都在同一位置寻找“下一步可以做什么”。

## 2. 进入 Action Shelf 的动作

只收纳 session-level、navigation-level 或教学编排级 typed actions，例如：

- `继续`；
- `换个例子`；
- `返回主线`；
- `转为引导讲解`；
- `查看练习反馈`；
- `开始复习`；
- `进入下一知识点`；
- `返回路线`；
- `暂停 / 稍后继续`；
- `重新恢复当前教学`。

这些动作共同特点是会改变 teaching focus、session mode、workspace pointer 或下一 Turn admission。

## 3. 不进入 Action Shelf 的动作

### 3.1 全局或视图动作

Guided/Free Reading 双向转换箭头继续固定在中间主区域右上角。它是 presentation mode switch，不应随着教学动作列表移动或进入 overflow。

### 3.2 Artifact-local 动作

以下动作继续放在对应 Lesson/Gate/Review artifact 附近：

- `Hint`；
- `Run`；
- `Submit`；
- 展开/收起 citation；
- 编辑答案或 finding；
- 查看 validation evidence；
- Lesson migration confirmation。

把这些动作移到 Composer 上方会破坏其与具体输入、版本和 evidence 的空间关联。Action Shelf 可以提供“前往当前 Gate”之类导航，但不能复制第二个 Submit。

### 3.3 Turn runtime control

正在运行的 Turn 的 Stop/Steer/Retry 沿用 Tutor runtime control contract，可以占用 Action Shelf 的 runtime state 或 Composer control 区，但不能与普通教学主动作同时可执行。

### 3.4 Typed request / Generated UI

当存在 blocking elicitation、approval 或 authority request 时，该 request 的 exact durable presentation 占据 Composer 上方交互槽位。普通 Action Shelf 隐藏或只保留不冲突的安全导航，不能同时显示会绕过 request 的教学主动作。

## 4. 动作数量和层级

每个 shelf 状态：

- 最多一个 primary action；
- 最多三个直接可见 secondary actions；
- 更低优先级动作进入 `更多`；
- 不显示模型自由生成的按钮 label、target 或 payload；
- 所有动作来自服务器 closed descriptor 与 `allowed_actions` projection。

推荐顺序：

- 桌面端：次动作在左，主动作在右；
- 900px：允许换行，但主动作保持最高视觉层级；
- 390px：主动作全宽置顶，最多两个常用次动作在下方，其余进入更多菜单。

## 5. 状态示例

### 5.1 普通教学软停顿

```text
[换个例子] [自由阅读] [暂停]                 [继续 →]
Composer
```

### 5.2 插问回答完成

```text
[继续追问] [返回主线]                    [按推荐继续 →]
Composer
```

其中“继续追问”通常可由 Composer 自身承担；如果动作过多，优先移除该重复按钮。

### 5.3 自由阅读深度问题

```text
[继续阅读]                         [转为引导讲解 →]
Composer
```

### 5.4 知识点完成

```text
[查看反馈] [开始复习] [返回路线]      [进入下一知识点 →]
Composer
```

完成总结仍留在 timeline，Action Shelf 只投影下一步，不复制完成 evidence。

### 5.5 Active Turn

普通 next actions 隐藏，显示受现有 Runtime authority 约束的 Stop/Steer 等控制；Turn terminal 后再恢复对应 pause shelf。

## 6. 与 Draft References 的顺序

推荐 interaction dock 自上而下为：

1. Action Shelf；
2. draft reference chips / exact typed request presentation；
3. Composer；
4. send/runtime controls。

Reference chips 距离输入框更近，因为它们属于下一条 learner message；Action Shelf 属于当前 session 的可用控制。切换 shelf 不得清空 references 或 Composer draft。

## 7. Sticky 语义

Action Shelf 跟随 Composer 的现有底部可达布局，可以保持可见，但不作为独立覆盖内容的全局 floating bar。

需要控制：

- 不遮挡最后一条消息；
- shelf 高度变化不造成 timeline 大幅跳动；
- 用户输入时不自动触发主动作；
- primary action 不获得自动焦点；
- action pending 时精确 disabled，并保留 Composer draft；
- stale/conflict 后刷新 shelf，不重放 mutation。

## 8. Completion 场景的变化

原“总结卡后、Composer 上方的 completion-only dock”扩展为统一的 Composer Action Shelf。知识点完成时只是 shelf 的一种状态：

- completion summary 继续进入 timeline；
- shelf 持续提供 `进入下一知识点` 和次动作；
- 用户继续提问时 active Turn 暂时替换 shelf；
- 回答结束后若 session 仍 completed，completion shelf 恢复；
- 不自动进入下一知识点。

## 9. 验收重点

- 所有 session-level 主次动作在 Composer 上方同一位置出现。
- 一个状态只有一个 primary，最多三个直接 secondary。
- 模式切换、artifact-local submit 和 blocking request 不被错误并入。
- action shelf 变化不丢 Composer/reference，不重复 mutation。
- active Turn、pending request、completion 和 free-reading escalation 状态互斥正确。
- 1440px、900px、390px 下无横向滚动，键盘顺序、accessible label 和 focus-visible 正确。
