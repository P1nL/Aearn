# Code Editor and Isolated Browser Preview 技术设计

## Boundary

交付单文件 Monaco 与真实实时 Browser Preview 的对话内练习工件，并确保任意学习代码不能控制或卡死主 Tauri WebView。

本 child 不拥有父任务中分配给其他 child 的业务 authority，不得为了局部便利复制 Artifact、Attempt、Teaching、Markdown、Result 或 Item Bank 状态机。

## Architecture

- Monaco model 按 artifact id/version 建立并 lazy load
- PreviewHostManager 在 Rust/Tauri 创建低权限 child webview 或经验证的等价隔离宿主
- 固定 host 接收 source bundle，执行区域与主 UI 进程隔离
- Bridge 只接受 ready/console/runtime_error/interaction_event，所有 payload bounded

## Data Flow

1. editor change -> in-memory/session draft -> debounce -> preview host reload
2. Preview interaction -> safe event（仅 demo descriptor需要）
3. Run click -> artifact action API -> running state -> result child pipeline

## Contracts and Invariants

- Preview 自动更新但不创建 Attempt或完成任务
- 用户点击 Run 才发送当前 source
- Preview 无网络、导航、popup、download、form、parent/Tauri access
- hang/timeout/crash 只重建 preview，编辑器/Composer/对话保持
- 新工件滚动但不聚焦 Monaco
- 终态只读，保持展开到下一 learner message
- 不提供文件树、终端、包管理器、真实路径
- Preview unavailable 不回退 A3a 或 main-DOM JS

## Affected Surfaces

- apps/desktop/src/features/tutor/artifacts/CodeEditorArtifact.tsx
- BrowserPreviewArtifact.tsx、preview bridge hook
- apps/desktop/src-tauri/src/preview_host.rs
- tauri.conf.json、独立 capabilities/CSP
- Desktop/Tauri security tests

## Compatibility

- 保持现有历史数据和旧 contract 读取；新行为通过 additive version/feature gate 引入。
- 所有未知 enum、extra field、stale identity、跨 scope 和受保护内容 fail closed。
- 不从历史归档恢复已移除 runtime，也不删除受保护前端原型。

## Security and Privacy

- 公共 API/SSE/Desktop/日志/导出不得包含完整 submission、private rubric/test、reference answer、provider body/reasoning、命令、路径、容器或 secret。
- 前端不能把本地 UI state 当作业务 authority。

## Rollback

- 独立关闭 Preview feature，保留编辑器但禁止 model 发要求预览的候选
- 绝不在 main DOM 执行任意 source
- 保留 artifact state为安全 unavailable
