# Inline Artifact Shell and Safe Markdown 技术设计

## Boundary

在唯一 TutorConversationSurface 中渲染安全 Markdown、对话内 Artifact 和可折叠单层答疑支线，并实现已确认的滚动、焦点、状态保留和响应式规则。

本 child 不拥有父任务中分配给其他 child 的业务 authority，不得为了局部便利复制 Artifact、Attempt、Teaching、Markdown、Result 或 Item Bank 状态机。

## Architecture

- TutorConversationSurface 保持唯一 snapshot/SSE/composer owner
- 静态 ArtifactRenderer registry 按 presentation discriminator 分发
- SafeMarkdown 采用 AST + sanitizer + controlled directive extension
- UIStateCache 仅进程内；server detail cache 以 artifact id/version 键控

## Data Flow

1. snapshot timeline -> group branches -> render message/artifact
2. item_updated -> snapshot refresh -> version compare -> preserve local UI state
3. new artifact -> auto expand + scrollIntoView without focus
4. learner mainline message -> collapse completed artifacts/branches

## Contracts and Invariants

- Artifact 与聊天有明显区分但无冗余小字
- 新 Artifact 自动滚动到起始位置且不抢焦点
- 完成后保持展开到下一 learner message
- 当前程序内保留 component/model/scroll/tab state，重开按需加载
- Markdown raw HTML disabled，size/color/url/contrast 校验
- 流式 partial Markdown 稳定，未闭合 code block 不造成 DOM 注入/跳动
- branch group 只从左缩进，用户气泡右边界保持一致
- resolved branch 默认折叠为答疑·N轮，可手动展开

## Affected Surfaces

- apps/desktop/src/features/tutor/TutorConversationSurface.tsx
- apps/desktop/src/features/tutor/artifacts/（新增）
- contracts/tutor.ts、api/tutor.ts
- styles/ artifact/markdown/branch CSS
- Vitest 与 browser fixture tests

## Compatibility

- 保持现有历史数据和旧 contract 读取；新行为通过 additive version/feature gate 引入。
- 所有未知 enum、extra field、stale identity、跨 scope 和受保护内容 fail closed。
- 不从历史归档恢复已移除 runtime，也不删除受保护前端原型。

## Security and Privacy

- 公共 API/SSE/Desktop/日志/导出不得包含完整 submission、private rubric/test、reference answer、provider body/reasoning、命令、路径、容器或 secret。
- 前端不能把本地 UI state 当作业务 authority。

## Rollback

- Desktop feature flag 回到现有 timeline renderer
- 未知 artifact 显示安全 unavailable，不执行任何 action
- 不删除 server artifact history
