# Inline Artifact Shell and Safe Markdown

## Parent

- `08-30-tutor-conversation-learning-artifacts`
- 本 child 的实现必须遵守父任务 PRD/design 和 confirmed product decisions；若产生物质性冲突，先返回父任务规划。

## Goal

在唯一 TutorConversationSurface 中渲染安全 Markdown、对话内 Artifact 和可折叠单层答疑支线，并实现已确认的滚动、焦点、状态保留和响应式规则。

## Scope

- SafeMarkdown renderer 与受控字号/颜色扩展
- InlineArtifactMessage shell/registry
- Artifact header/body/actions/terminal summary
- branch rail、用户右对齐、Tutor 左对齐、resolved collapse
- active/completed 展开规则、scroll/focus anchors、lazy detail
- container-query 响应式与 reduced motion

## Requirements

### R1

- Artifact 与聊天有明显区分但无冗余小字

### R2

- 新 Artifact 自动滚动到起始位置且不抢焦点

### R3

- 完成后保持展开到下一 learner message

### R4

- 当前程序内保留 component/model/scroll/tab state，重开按需加载

### R5

- Markdown raw HTML disabled，size/color/url/contrast 校验

### R6

- 流式 partial Markdown 稳定，未闭合 code block 不造成 DOM 注入/跳动

### R7

- branch group 只从左缩进，用户气泡右边界保持一致

### R8

- resolved branch 默认折叠为答疑·N轮，可手动展开

## Acceptance Criteria

- [x] 普通消息、Markdown、自定义颜色字号和代码块安全渲染
- [x] 未知 Artifact/presentation fail closed 为 contract error
- [x] artifact/branch snapshot reload 和 SSE update 原地更新无重复卡片
- [x] 更新 result/status 不抢滚动/焦点
- [x] 1440/900/390 无水平溢出，键盘和 reduced motion 通过
- [x] 终态重量组件可折叠且恢复数据一致

## Out of Scope

- 具体 Monaco/Preview/SQL/Review/Hint 内容组件
- 后端 artifact/branch authority
- 右侧文档 drawer

## Dependencies and Ordering

- 依赖 Child 01 public contracts
- 依赖 Child 02 branch/priority projection

## Open Questions

无阻塞产品问题。实现中若发现仓库事实与本规划冲突，必须回到 planning 更新 artifact 并重新审阅。
