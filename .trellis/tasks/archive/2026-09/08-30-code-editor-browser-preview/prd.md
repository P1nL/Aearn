# Code Editor and Isolated Browser Preview

## Parent

- `08-30-tutor-conversation-learning-artifacts`
- 本 child 的实现必须遵守父任务 PRD/design 和 confirmed product decisions；若产生物质性冲突，先返回父任务规划。

## Goal

交付单文件 Monaco 与真实实时 Browser Preview 的对话内练习工件，并确保任意学习代码不能控制或卡死主 Tauri WebView。

## Scope

- Monaco 单文件编辑器
- 固定宽屏50:50/窄屏上下布局
- 300-500ms 防抖实时 Preview
- 隔离 Tauri preview host/capability/CSP/nonce bridge
- Preview console/runtime error/recreate
- 显式 Run 接入 Artifact action

## Requirements

### R1

- Preview 自动更新但不创建 Attempt或完成任务

### R2

- 用户点击 Run 才发送当前 source

### R3

- Preview 无网络、导航、popup、download、form、parent/Tauri access

### R4

- hang/timeout/crash 只重建 preview，编辑器/Composer/对话保持

### R5

- 新工件滚动但不聚焦 Monaco

### R6

- 终态只读，保持展开到下一 learner message

### R7

- 不提供文件树、终端、包管理器、真实路径

### R8

- Preview unavailable 不回退 A3a 或 main-DOM JS

## Acceptance Criteria

- [ ] HTML/CSS/JS Starter 实时预览并可交互
- [ ] 恶意脚本矩阵不能影响主应用
- [ ] Preview source/event nonce、artifact/session/version mismatch 被拒绝
- [ ] resize 宽窄切换保留 model/cursor/scroll/preview
- [ ] 显式 Run 发送 exact latest draft，stale result 标记正确
- [ ] cargo check、desktop tests/check、安全 smoke 通过

## Out of Scope

- SafeExecutionResult/test-result 设计（Child 05）
- 多文件/终端/依赖安装
- 生产 container fleet
- 服务器草稿历史

## Dependencies and Ordering

- 依赖 Child 03 shell/Markdown
- 依赖 Child 01 action API
- 依赖 Child 05 result/Run contract

## Open Questions

无阻塞产品问题。实现中若发现仓库事实与本规划冲突，必须回到 planning 更新 artifact 并重新审阅。
