# 新线程执行交接

## 目标任务树

Parent：`.trellis/tasks/08-21-tutor-planning-intent-runtime-stream-reliability`

执行顺序：

1. `.trellis/tasks/08-21-planning-course-intent-dynamic-generated-ui`
2. `.trellis/tasks/08-21-reasoning-delta-coalescing-runtime-budget`

Parent 只作为跨 child 规划和最终验收 map，不启动为实现任务。当前新线程只启动 Child 1。

## 新线程必须先执行

```powershell
cd E:\codee\Aearn
python .\.trellis\scripts\task.py start 08-21-planning-course-intent-dynamic-generated-ui
python .\.trellis\scripts\task.py current --source
```

第二条命令必须指向：

```text
.trellis/tasks/08-21-planning-course-intent-dynamic-generated-ui
```

不得启动、恢复或改写 stale fallback `08-13-codex-like-tutor-conversation-experience`，不得启动 parent，也不得自行重建任务树。

## 读取顺序

启动 Child 1 后加载 `trellis-before-dev`，然后完整读取：

1. Parent `prd.md`
2. Parent `design.md`
3. Parent `implement.md`
4. Parent `research/current-evidence.md`
5. Child 1 `prd.md`
6. Child 1 `design.md`
7. Child 1 `implement.md`
8. Child 1 `research/course-intent-current-state.md`

按 Child 1 `implement.md` 顺序直接实施，不重新规划。Codex inline 模式，不派发 implement/check sub-agent。

## 关键批准决策

- 唯一明确且有发布课程的语言以 `deterministic_input` confirmed fact 写入，跳过语言问题。
- 方向/多语言只影响 shortlist，不自动写 `language_id`。
- 课程方向 source of truth 是 PostgreSQL taxonomy/tag relation；Runtime 不按 title、description 或 slug 硬编码匹配。
- 模型只可提出 closed intent tag hint；Aearn 验证后仅用于 shortlist，不能定义课程、course ID、选项或 planning fact。
- Language Generated UI 初始无默认选中项；未选择时不能提交。
- 新 active course 未标注 intent tags 时发布/CI gate 失败。
- Child 1 完成、检查、提交并归档后，再进入 Child 2。

## 验证与边界

完成代码后加载 `trellis-check`，运行 Child 1 focused tests、full pytest、Ruff、Mypy、Desktop tests/check、bootstrap twice、browser smoke、Trellis validate 与 `git diff --check`。发现问题直接修复并复验。

未经用户再次明确批准，不调用真实 provider。可以使用 fake App Server 和本地 PostgreSQL。禁止 push、部署和修改生产数据；工作提交仅在 Phase 3.4 质量门通过后创建。

必须保护，不覆盖或提交：

- `.trellis/tasks/.obsidian/plugins/translate/data.json`
- `.trellis/tasks/.obsidian/workspace.json`
