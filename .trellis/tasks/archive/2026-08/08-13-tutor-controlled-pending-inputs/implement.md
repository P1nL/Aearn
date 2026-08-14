# 实施计划

## 前置检查

- [ ] 加载 `trellis-before-dev`，读取 backend/frontend specs、父任务与本 child 工件。
- [ ] 对 `E:\codee\Aearn` 中 contracts、decision protocol、skills、planning facts、Desktop types/api/surface 做精确 diff。
- [ ] 记录要移植与不移植的 hunks；不应用整包 patch。

## 后端 contract 与 persistence

- [ ] 更新五种 continuation enum 和 kind/key gate。
- [ ] 新增 pending-input schema、constraints、repository 和 public dataclass/projection。
- [ ] 新增七字段 planning question catalog/template。
- [ ] waiting result 原子持久化 pending projection。
- [ ] typed answer 验证 pending identity/revision/value 并原子 resolve/resume。
- [ ] 更新 API model、route/service error mapping 和 SSE/history payload。

## Prompt 与测试

- [ ] 语义移植原始工作树受控 prompt 修改。
- [ ] 为 clarification/planning_input/approval 增加正例、反例、边界示例。
- [ ] 增加 catalog、decision gate、pending persistence、API、SSE、idempotency、cross-user、stale tests。
- [ ] 增加 Desktop types/parser contract tests，但不实现最终 Question UI。
- [ ] 更新 owning source-of-truth docs。

## 验证

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_run_loop.py tests/test_tutor_run_repository.py tests/test_tutor_routes.py tests/test_tutor_sse.py tests/test_learning_plan_sessions.py tests/test_db_bootstrap.py -q
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
pnpm --dir .\aearn desktop:check
python .\.trellis\scripts\task.py validate .\.trellis\tasks\08-13-tutor-controlled-pending-inputs
git diff --check
```

## Review gate

- [ ] 七字段全覆盖，无 model-authored schema。
- [ ] enum 不混用，confirmed fact 不重问。
- [ ] typed answer 不可绕过 pending identity/version。
- [ ] 原始工作树用户修改无回退。
- [ ] 不引入 Queue/Stop 或最终 UI 范围。
