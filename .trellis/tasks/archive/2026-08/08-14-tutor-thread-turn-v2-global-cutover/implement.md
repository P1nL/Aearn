# Tutor thread/turn v2 全局切换：实施计划

## 启动门

- `08-13-tutor-thread-turn-item-event-foundation`、`08-14-tutor-typed-request-authority-turns`、`08-13-tutor-queue-steer-interrupt-control` 已完成归档并冻结 contract。
- 父任务最终规划经后续消息批准后运行：
  `python .\.trellis\scripts\task.py start .trellis/tasks/08-14-tutor-thread-turn-v2-global-cutover`
- 加载 `trellis-before-dev`，读取 database/error/logging/quality/cross-layer specs 与四份 source-of-truth。

## 有序实施

1. 定义 cutover singleton schema、state/generation/idempotency contract 和 global advisory lock。
2. 让 legacy create/input/dispatch/lease/reconcile 入口读取 preparing freeze authority。
3. 实现 dry-run inventory 与 canonical summary/hash。
4. 实现 waiting rows recoverable failed migration，以及其他可取消 rows immediate cancel/lease clear + 普通 `interrupted` public mapping。
5. 实现 effect receipt proof 与 blocked/retry flow，禁止 force override。
6. 将旧 continuation POST 改为 service 前 410 tombstone 并增加 no-side-effect tests。
7. 实现 effective v2 gate、capability endpoint、worker/reconciler gate 与 ready/enable 操作。
8. 实现 rollback/read-only unavailable 与安全审计/metrics。
9. 更新 API/database/runtime/frontend interaction/acceptance 文档和 operator runbook。

## 验证

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_db_bootstrap.py tests/test_tutor_run_repository.py tests/test_tutor_run_loop.py tests/test_tutor_routes.py tests/test_tutor_sse.py tests/test_tutor_effect_commit.py tests/test_worker_import.py -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app
pnpm --dir .\aearn desktop:check
python .\.trellis\scripts\task.py validate .trellis/tasks/08-14-tutor-thread-turn-v2-global-cutover
git diff --check
```

新增 suites：advisory-lock concurrency、preparing freeze races、state-class migration idempotency、cutover-cancelled ordinary interrupted projection、late-write fencing、ambiguous-effect block/retry、410 no-side-effect、effective gate matrix 与 rollback no-legacy-reopen。

## 高风险文件

- `aearn/services/api/app/db/schema.sql`
- `aearn/services/api/app/core/config.py`
- `aearn/services/api/app/services/tutor/persistence.py`
- `aearn/services/api/app/services/tutor/public_api.py`
- `aearn/services/api/app/services/tutor/run_loop.py`
- `aearn/services/api/app/services/tutor/interactive_worker.py`
- `aearn/services/api/app/routes/tutor.py`
- `aearn/services/worker/aearn_worker/worker_app.py`
- cutover/route/run-loop/effect/bootstrap tests 与 docs/runbook。

## 完成门

- dry-run/preflight/prepare/enable/blocked-retry/rollback 均有自动化证据。
- 没有 legacy write 或 ambiguous effect 能跨越 enabled 边界。
- 未执行生产 cutover、数据删除或 route 物理移除。