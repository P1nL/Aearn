# 实施计划

## 前置门槛

- [ ] Child 1、2、3 均 completed/archived 且验证记录可读。
- [ ] 加载 `trellis-before-dev`、frontend specs、父任务/三 child 工件和研究。
- [ ] 复核原始 dirty worktree重叠文件与已移植语义。

## Component refactor

- [ ] 抽出 TutorComposer、TutorQueueDock、TutorQuestionComposer、TutorThinkRow、TutorPlanReviewPanel。
- [ ] 保持 History/SSE controller 以 server history 为唯一 timeline authority。
- [ ] 删除 continuation card/manual mode switch，接入 pending-input takeover。
- [ ] 接入 Queue delivery/mutations/Steer 和 authority snapshot。
- [ ] 接入 run cancel 与 send/stop primary action。
- [ ] 忽略 process timeline item，只渲染 Think。
- [ ] 迁移 plan inspector 内部视觉并保留 Aearn actions。

## Styling/tests

- [ ] 使用 Child 1 tokens/CSS modules 完成白色浅色近像素样式。
- [ ] 更新/补全 component tests、IME、keyboard、focus、reduced motion。
- [ ] 确认无引用后窄范围删除旧 Tutor CSS。
- [ ] 更新 frontend/user-flow/API/DB/runtime/acceptance docs 最终一致性。

## 验证

```powershell
pnpm --dir .\aearn\apps\desktop test
pnpm --dir .\aearn desktop:check
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_routes.py tests/test_tutor_sse.py tests/test_tutor_conversation_history.py tests/test_tutor_run_loop.py tests/test_learning_plan_sessions.py -q
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
python .\.trellis\scripts\task.py validate .\.trellis\tasks\08-13-tutor-dsh-conversation-integration
git diff --check
```

## 浏览器验证

- [ ] 1440/900/390，普通对话、active queue、stop、paused wake、clarification、planning input、plan review。
- [ ] keyboard/IME/focus/reduced motion。
- [ ] console warning/error、Vite overlay、horizontal overflow 均为零。
- [ ] 记录截图或可复核的 browser evidence，不把 fake fixture 称为真实 provider 证据。

## Review gate

- [ ] 不改写 Child 2/3 authority；发现 contract 缺陷则返回 owning child。
- [ ] 无 DeepSeek brand/runtime/Markdown authority 泄漏。
- [ ] 非 Tutor 页面无视觉回归。
- [ ] 原始工作树用户修改无覆盖或回退。
