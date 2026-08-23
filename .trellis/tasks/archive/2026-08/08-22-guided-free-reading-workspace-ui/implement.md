# 实施计划

## 1. 开始前

1. 确认 Child 1/2 均已完成、提交、归档。
2. 启动 `08-22-guided-free-reading-workspace-ui` 并用 `current --source` 验证。
3. 加载 `trellis-before-dev`，读取父任务、前序 child handoff 与本 child 工件。
4. 检查 Desktop 相邻组件、测试和当前 browser fixture；保护用户工作树。

## 2. API/types/controller

1. 增加 exact teaching session/shelf/group/follow/completion types。
2. 扩展 `api.ts` strict unknown parser 与 action client。
3. 新增 teaching workspace controller，协调 load/open/action/conflict/abort。
4. 保持现有 conversation/references/SSE reducer authority。

## 3. Layout 与交互

1. 重构 `TrackLearningWorkspace` 为单一 Tutor/Lesson 挂载的角色换位布局。
2. 实现中间右上角 `WorkspaceModeSwitch`。
3. 实现 Guided document follow、pause 与“回到当前讲解”。
4. 实现 session grouping、bounded history 展开和 exact cross-session reference。
5. 实现 `ComposerActionShelf`、overflow 与 runtime/request/artifact 互斥。
6. 实现 completion 与 free-reading escalation UI，不自动导航/切 mode。
7. 完成 1440/900/390 响应式、键盘、focus 与 reduced-motion。

## 4. 自动化验证

```powershell
pnpm --dir .\aearn\apps\desktop test -- --run src/features/tutor/tests/TutorConversationSurface.test.tsx
pnpm --dir .\aearn\apps\desktop test -- --run
pnpm --dir .\aearn desktop:check
python .\.trellis\scripts\task.py validate .trellis\tasks\08-22-guided-free-reading-workspace-ui
git diff --check
```

新增/扩展 tests 覆盖 parser、controller、single mount/SSE、mode conflict、follow pause、session groups、Action Shelf、completion 与 responsive state。

## 5. Browser smoke

使用 Browser plugin 优先验证 `http://127.0.0.1:1420`，后端使用 disposable fake App Server/provider 与本地 PostgreSQL：

1. Guided 首个教学单元与可见停顿。
2. 双向切换，conversation/document/run/draft/reference 保持。
3. 文档用户滚动/选择后不被抢位，显式恢复。
4. Free Reading 普通问题与显式 escalation。
5. current/history session grouping。
6. active runtime、blocking request、completion 三种 Action Shelf 状态。
7. next-node conflict refresh，不自动重放。
8. 1440×900、900×900、390×844 的 `scrollWidth <= clientWidth`、键盘、focus、reduced motion、console 0 相关 error/warning。

截图放仓库外，结束后停止临时服务。真实 provider 不执行。

## 6. 完成

1. 加载 `trellis-check`，修复并复验自动化与 browser gate。
2. Phase 3.3 更新 frontend state/component/type-safety/quality spec 与产品交互文档。
3. Phase 3.4 创建本 child 工作提交，归档并记录 journal。
4. 停止，不自动启动最终 child；把 `08-22-adaptive-learning-integration-evals` 交给用户。
