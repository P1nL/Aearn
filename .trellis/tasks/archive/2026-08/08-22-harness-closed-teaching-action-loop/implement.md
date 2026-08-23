# 实施计划

## 1. 开始前

1. 确认 Child 1 已归档且其数据库/API contract 已进入当前工作树提交历史。
2. `task.py start 08-22-harness-closed-teaching-action-loop` 后用 `current --source` 验证。
3. 加载 `trellis-before-dev`，完整读取父任务、Child 1 handoff/文档和本 child 工件。

## 2. Skill、context 与 decision schema

1. 新增并发布 `tutor.lesson-teaching@1.0.0`。
2. 增加 `TEACHING_SESSION` required context section 与 budget/fail-closed tests。
3. 扩展 provider request/decision parser，新增 strict `teaching_step`。
4. 保持现有 non-teaching actions 与 provider compatibility。

## 3. Loop 与 reducer

1. 实现 closed action validation gate。
2. 实现 focus reducer、bounded stack/questions、纠正覆盖与 stale invalidation。
3. 将 message/checkpoint/receipt/pause/run terminal 放入一致事务。
4. 确保每个 stimulus 最多一个主要 teaching action，terminal 后无自动 admission。

## 4. Action Shelf 与控制事件

1. 实现服务端 `TeachingActionShelfV1` descriptor、排序与互斥。
2. 实现 continue/return-focus/change-example/pause/escalate/enter-next typed control policy。
3. 实现 free-reading reactive 与显式 Guided escalation。
4. 实现 completion pause、latest roadmap revalidation 与 conflict refresh。

## 5. 验证

```powershell
uv --directory .\aearn\services\api run python -m pytest `
  tests/test_tutor_context_builder.py `
  tests/test_tutor_context_budget.py `
  tests/test_tutor_provider_gateway.py `
  tests/test_tutor_run_loop.py `
  tests/test_tutor_action_runtime.py `
  tests/test_tutor_skill_catalog.py `
  tests/test_tutor_trace_redaction.py `
  tests/test_tutor_teaching_action_loop.py `
  tests/test_tutor_teaching_context.py `
  tests/test_tutor_teaching_focus_reducer.py -q
uv --directory .\aearn\services\api run python -m ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app --no-incremental
python .\.trellis\scripts\task.py validate .trellis\tasks\08-22-harness-closed-teaching-action-loop
git diff --check
```

使用 fake provider 覆盖不同教学路径、连续追问、stale result、provider unavailable 与无新事件调用数稳定。未经用户再次明确批准，不运行真实 provider。

## 6. 完成

1. 加载 `trellis-check`，修复后复验 focused/full backend gate。
2. Phase 3.3 更新 Harness/context/Skill/API spec 与 source-of-truth 文档。
3. Phase 3.4 创建本 child 工作提交并归档，记录 journal。
4. 停止，不自动启动 Desktop child；将 `08-22-guided-free-reading-workspace-ui` 作为下一步交给用户。
