# Tutor 会话/轮次/条目与统一事件底座：实施计划

## 开始前

- 仅在父任务最终规划获批后执行：
  `python .\.trellis\scripts\task.py start .trellis/tasks/08-13-tutor-thread-turn-item-event-foundation`
- 加载 `trellis-before-dev`；阅读 backend database/error/quality/logging、frontend type contract（若修改共享 DTO）、cross-layer guide 与四份 architecture docs。
- 检查当前 `schema.sql`、`persistence.py`、`public_api.py`、`routes/tutor.py`、worker 和 tests 的未提交 diff。

## 有序实施

1. 定义 v2 protocol、public turn/item/event/snapshot/dispatch DTO 与 safe allowlist。
2. 添加 conversation/run 字段、conversation events、dispatch jobs、索引/check/trigger 与 legacy projection 所需协议标记。
3. 实现 sequence allocator、event append/replay、snapshot projection 与 opaque cursor。
4. 让 fresh turn mutation 原子插入 dispatch job 与 initial public events；保留兼容 response 字段。
5. 实现 dispatch job claim/lease/retry/dead repository 与 API-side worker service。
6. 注册 Celery dispatch/reconcile、beat schedule，更新 `start-dev.ps1` 的 worker/beat 管理。
7. 新增 conversation snapshot/SSE routes；保持旧 history/run SSE 测试绿色。
8. 更新 API/database/runtime 文档的底座部分。

## 针对性验证

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_db_bootstrap.py tests/test_tutor_run_repository.py tests/test_tutor_conversation_history.py tests/test_tutor_sse.py tests/test_tutor_routes.py tests/test_worker_import.py -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app
python .\.trellis\scripts\task.py validate .trellis/tasks/08-13-tutor-thread-turn-item-event-foundation
git diff --check
```

新增测试：conversation event 并发/幂等/cursor；snapshot legacy projection；turn+job 原子回滚；job duplicate wakeup、lease expiry、retry/dead；worker/beat import 与安全日志。

## 高风险文件

- `aearn/services/api/app/db/schema.sql`
- `aearn/services/api/app/services/tutor/persistence.py`
- `aearn/services/api/app/services/tutor/public_api.py`
- `aearn/services/api/app/services/tutor/interactive.py`
- `aearn/services/api/app/routes/tutor.py`
- `aearn/services/worker/aearn_worker/worker_app.py`
- `aearn/scripts/start-dev.ps1`
- Tutor route/SSE/repository/bootstrap tests 与 architecture docs。

## 完成门

- 新 contract 可供 typed-request、Queue/control 与 cutover children 使用且已冻结；无后续产品行为越界实现。
- Celery 丢消息/worker crash 可由 PostgreSQL reconciler 恢复。
- 旧 history/run SSE 兼容，public event 无敏感 payload。
