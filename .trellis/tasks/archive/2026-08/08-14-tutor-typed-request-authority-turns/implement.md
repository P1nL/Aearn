# Tutor 类型化请求与权威续轮：实施计划

## 启动门

- `08-13-tutor-thread-turn-item-event-foundation` 已完成归档，item/event/snapshot/dispatch contract 已冻结。
- 父任务最终规划已经后续消息批准，才运行：
  `python .\.trellis\scripts\task.py start .trellis/tasks/08-14-tutor-typed-request-authority-turns`
- 加载 `trellis-before-dev`，检查原始 continuation/prompt/planning facts 修改并逐文件融合。

## 有序实施

1. 冻结 request/response/receipt DTO、error code、event payload 与 completion reason。
2. 添加 request schema、partial unique/index/FK、`response_to_request_id` 与 bootstrap twice tests。
3. 实现 request repository、public item/snapshot/event projection。
4. 修改 decision gate：创建 typed request 并终结来源 turn，不再持久化新 `waiting_for_input` continuation run。
5. 实现 clarification/planning response CAS 与 fresh answer turn/job。
6. 实现 approval proposal/approve/deny fresh turn 与 action authority 重验。
7. 实现 capability/external 内部 receipt 验证、幂等与 fresh authority turn。
8. 建立七字段 planning question catalog，融合 prompt 正反例/边界例。
9. 更新共享 TypeScript seam、API/runtime/database/acceptance 文档和 focused tests。

## 验证

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_db_bootstrap.py tests/test_tutor_run_repository.py tests/test_tutor_run_loop.py tests/test_tutor_routes.py tests/test_tutor_sse.py tests/test_learning_plan_sessions.py tests/test_tutor_action_runtime.py -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app
pnpm --dir .\aearn desktop:check
python .\.trellis\scripts\task.py validate .trellis/tasks/08-14-tutor-typed-request-authority-turns
git diff --check
```

新增 suites：request concurrency/idempotency、fresh budget、planning catalog、approval identity、authority receipt scope/hash、pending Queue block、public payload allowlist。

## 高风险文件

- `aearn/services/api/app/db/schema.sql`
- `aearn/services/api/app/agents/harness/contracts.py`
- `aearn/services/api/app/services/tutor/decision_protocol.py`
- `aearn/services/api/app/services/tutor/run_loop.py`
- `aearn/services/api/app/services/tutor/persistence.py`
- `aearn/services/api/app/services/tutor/public_api.py`
- `aearn/services/api/app/services/learning/planning_facts.py`
- `aearn/services/api/app/routes/tutor.py`
- Tutor request/planning/action tests 与四份 source-of-truth 文档。

## 完成门

- request/receipt contract、fresh-turn lineage 与 error/events 已冻结，可供 Queue/control 与 Desktop 消费。
- 新路径不存在恢复旧 run 预算的 mutation。
- learner 不能伪造 approval 或 authority receipt，public payload 无敏感内容。