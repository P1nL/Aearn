# 知识点完成与下一节点显式过渡

**记录日期：** 2026-08-22  
**状态：** 完成后不自动推进与统一 Composer Action Shelf 均已确认。

## 1. 已确认行为

required Gate 或其他 trusted evidence 将当前知识点推进为 completed 后：

1. 当前 teaching session 停留在完成位置；
2. 不自动切换 workspace `knowledge_key`；
3. 不自动创建下一 teaching session；
4. 不自动发起下一次 provider Turn；
5. 显示 learner-safe 完成总结、真实 evidence 概览、未解决问题和新解锁节点；
6. 用户可以继续提问、查看反馈、复习、返回路线或暂停；
7. 只有用户显式触发 `进入下一知识点` 才推进。

## 2. 下一知识点 authority

`进入下一知识点` 不能采用模型自由文本或 Lesson `next_steps` 作为目标 authority。Desktop 只消费最新 roadmap projection 中 server-authorized next available node，并提交：

- current track/session/progress expected version；
- current knowledge key；
- target knowledge key；
- client action/idempotency identity。

服务端重新验证 active plan、prerequisite、availability 和版本。目标 stale、locked、removed 或 plan 已切换时 fail closed，刷新路线并保留当前完成 session。

## 3. 成功过渡

显式 transition 成功后：

1. 当前 session 保持 completed；
2. workspace pointer 改为新 knowledge key；
3. 创建或恢复目标 teaching session；
4. 读取/准备其 active Lesson assignment；
5. 按“单步主动、逐段停顿”创建至多一个首个/恢复教学 Turn；
6. 新 Turn 完成后再次停顿。

## 4. Completion projection

完成投影至少需要：

- 当前知识点 title/key 与 completed status；
- learner-safe evidence kind、结果摘要和 independence；
- 仍未解决的问题；
- review due/critical 状态；
- 最新 roadmap 中新解锁节点；
- 推荐 next node；
- server-allowed transition actions；
- track/progress/session version。

模型可以生成自然语言总结，但不能定义 evidence、completed、unlock 或 next knowledge key。

## 5. 动作位置候选

### 方案 A：总结卡内部

主次动作紧跟完成证据，语义关联最强；但长总结后按钮可能滚出视口，Composer 与继续提问入口容易分离。

### 方案 B：总结卡后、Composer 上方的 session action dock

完成总结作为 timeline 内容，动作区紧接其后并位于 Composer 上方。主动作清晰、继续提问仍然自然，移动端可改为纵向按钮。动作区只在当前 session 处于 completion pause 时出现，不做全局永久 sticky。

### 方案 C：固定面板底部

始终可达，但容易与 Composer 竞争空间、遮挡内容或产生误触，并让动作与具体完成 evidence 脱离。

所有 session-level 主次动作已确认统一为 Composer 上方组件；该通用方案见 `composer-action-shelf.md`，并取代 completion-only dock。

## 6. 推荐的动作层级

- 主动作：`进入下一知识点`，filled/high-emphasis。
- 次动作：`查看练习反馈`、`开始复习`、`返回路线`，outline/quiet。
- 继续提问：Composer 本身承担，不需要再放一个重复的“继续提问”按钮；可提供一条低对比提示。
- 暂停/稍后继续：text/overflow action，不与主动作同等强调。

桌面横向布局中，次动作在左、主动作在右；窄屏按 DOM 顺序先主动作、再次动作纵向或换行。顶栏右上角继续只放 Guided/Free Reading 双向转换，不放路线推进。

## 7. 验收重点

- completed 后没有自动 navigation/provider call。
- next node 来自最新 roadmap，stale control fail closed。
- 继续提问不会被 next-node CTA 阻断。
- 动作与 completion evidence 视觉相关，但不永久遮挡 Composer。
- 桌面、900px 和 390px 下主次层级清晰、键盘顺序合理、无误触或横向溢出。
