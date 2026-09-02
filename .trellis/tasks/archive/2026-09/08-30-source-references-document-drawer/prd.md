# Source References and Document Drawer

## Parent

- `08-30-tutor-conversation-learning-artifacts`
- 本 child 的实现必须遵守父任务 PRD/design 和 confirmed product decisions；若产生物质性冲突，先返回父任务规划。

## Goal

复用现有Lesson source/context reference authority，为对话和工件提供exact来源定位、右侧文档栏与窄屏覆盖抽屉。

## Scope

- SafeArtifactReference contract/adapter
- citation/source chips与artifact refs
- right document panel open/scroll/highlight
- dashed overlay animation
- narrow 88vw overlay drawer/collapse
- focus/scroll/version mismatch recovery

## Requirements

### R1

- 引用绑定document/version/block/hash，不按文本或DOM顺序猜测

### R2

- 点击后只滚动右栏，不改变对话位置

### R3

- highlight用overlay/pseudo-element不reflow

### R4

- narrow drawer覆盖右侧大部分，外部点击不关闭，按钮/Escape关闭

### R5

- 关闭后焦点回来源触发点，Artifact/Editor/Preview不重载

### R6

- reduced motion即时定位+静态虚线框

### R7

- 完整文档仍在右栏，工件只显示必要引用chip/摘录

## Acceptance Criteria

- [ ] closed/open drawer与重复引用定位正确
- [ ] 异步加载/virtualized block后才滚动和动画
- [ ] 版本变化加载历史或显示内容已更新，不误框相似段落
- [ ] keyboard/focus trap/scroll isolation/Escape通过
- [ ] 1440/900/390布局无溢出
- [ ] 跨用户/track/document/hash非法引用fail closed

## Out of Scope

- 开放网页导航/抓取
- 模型提供CSS selector或任意URL
- 把完整文档复制进Artifact/SSE
- 替换右栏为任务面板

## Dependencies and Ordering

- 依赖Child01 safe refs、03 shell；复用现有LessonSourcesPanel/context references

## Open Questions

无阻塞产品问题。实现中若发现仓库事实与本规划冲突，必须回到 planning 更新 artifact 并重新审阅。
