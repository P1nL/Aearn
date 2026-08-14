# Tutor 队列、引导、中断与重试控制：实施计划

## 启动门

- `08-13-tutor-thread-turn-item-event-foundation` 与 `08-14-tutor-typed-request-authority-turns` 已完成归档，相关 contract 已冻结。
- 父任务最终规划经后续消息批准后运行：
  `python .\.trellis\scripts\task.py start .trellis/tasks/08-13-tutor-queue-steer-interrupt-control`
- 加载 `trellis-before-dev` 并检查 run loop、effect receipt 和共享 DTO scoped diff。

## 有序实施

1. 添加 Queue/lineage schema、indexes/checks 与 repository DTO。
2. 实现 Queue add/list/edit/delete/reorder/claim，接入 control version 和 conversation events。
3. 修改普通 input：idle fresh turn，running 默认 Queue；移除 v2 supersede 默认行为。
4. 实现 Steer 专用 API/service 与 revision write fences。
5. 实现 Interrupt、public interrupted、Queue pause 与显式 resume。
6. 实现 Queue execute 的 interrupt+claim 原子路径。
7. 接入 pending request 阻塞契约，不修改 request authority。
8. 实现 Retry lineage、logical effect receipt 复用和 safe errors。
9. 扩展 worker completed/reconcile hook 做 completed-only drain，验证 crash/duplicate/race。
10. 更新 runtime/API/database 文档与 focused tests。

## 验证

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_run_loop.py tests/test_tutor_run_repository.py tests/test_tutor_routes.py tests/test_tutor_sse.py tests/test_tutor_effect_commit.py tests/test_tutor_action_runtime.py -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app
python .\.trellis\scripts\task.py validate .trellis/tasks/08-13-tutor-queue-steer-interrupt-control
git diff --check
```

新增 suites：Queue concurrency/drain、Steer stale revision、Interrupt race、pause/resume/execute、pending request block、Retry/effect lineage 与 duplicate worker。

## 高风险文件

- `aearn/services/api/app/db/schema.sql`
- `aearn/services/api/app/services/tutor/run_loop.py`
- `aearn/services/api/app/services/tutor/persistence.py`
- `aearn/services/api/app/services/tutor/public_api.py`
- `aearn/services/api/app/services/tutor/interactive.py`
- `aearn/services/api/app/routes/tutor.py`
- `aearn/services/worker/aearn_worker/worker_app.py`
- Tutor lifecycle/effect/action/route tests 与相关 docs。

## 完成门

- Queue、Steer、Interrupt、resume、execute、Retry contract 冻结，可供 cutover 与 Desktop 消费。
- interrupted/failed/pending request 不会自动 drain，普通 Send 不隐式 resume。
- stale/ambiguous effect 状态 fail closed。