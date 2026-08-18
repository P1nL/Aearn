# 实施计划

1. 定义 runtime selection/cutover config、health snapshot和稳定 reason codes。
2. 在 TutorRun创建事务中冻结 `runtime_kind`，Retry继承root。
3. 拆分或包装现有 dispatcher，新增 `TutorRuntimeDispatchRouter` 与 Codex dispatcher。
4. 接 Codex input、tool registry、event projector和terminal persistence。
5. 接 Queue/revision steer、cancel/supersede interrupt、lease loss与 retry行为。
6. 保持 LearningPlan confirm/LearningTrack事务不变，补全 Desktop/API兼容测试。
7. 添加 feature off/on、scope矩阵、unhealthy admission、no-fallback和rollback tests。
8. 运行 Harness/Codex并列 focused tests、ruff、mypy、Desktop tests/check、Trellis validate 与 `git diff --check`。

## 风险文件

- `aearn/services/api/app/services/tutor/interactive.py`
- `aearn/services/api/app/services/tutor/interactive_worker.py`
- Tutor run creation、retry、control、queue和public API文件
- feature/settings与 worker routes
- Desktop conversation与 plan confirmation tests

## 回滚

关闭 Codex cohort/admission，停止 `tutor-codex` worker；不修改历史 runtime kind，不删除 binding/receipt，不让 active run跨 Runtime续跑。


## 实施结果

- 已新增默认开启但独立受控的 `TUTOR_CODEX_PLAN_DRAFTING_ENABLED=true` 与 90 秒 readiness freshness。
- 已新增 shared `tutor_codex_runtime_health`，由 dedicated `tutor-codex` health task 持久化 bounded exact readiness。
- 已在 first-turn、ordinary input、Queue claim、interaction response 与 Retry 边界冻结或继承 `runtime_kind`；客户端和公开 DTO 不新增 Runtime 字段。
- 已新增 `TutorRuntimeDispatchRouter`、Runtime-filtered durable claim、`tutor.codex.dispatch/reconcile` 与 `CodexTutorRunDispatcher`；Codex 路径不组合 `TutorRunLoop`。
- 已接 typed LearningPlan tools、private binding、Runtime event projector、lease heartbeat、revision steer、cancel/supersede/lease-loss interrupt 与 existing-binding fail-closed recovery。
- 已保持 LearningPlan confirm/LearningTrack transaction、Harness scope、SSE/history/Desktop contract 不变。

## 验证结果

- `pytest -q`：`660 passed, 2 skipped`。
- focused Codex/Harness/Queue/LearningPlan tests：`95 passed`。
- `ruff check app tests ../worker/aearn_worker`：通过。
- `python -m mypy app --no-incremental`：`192 source files` 通过。
- `python -m compileall -q app ../worker/aearn_worker`：通过。
- `uv lock --check`：通过，`54 packages`。
- 数据库 bootstrap 连续执行两次：通过。
- `pnpm --dir .\aearn desktop:check`：通过。
- 默认测试未调用真实 provider，未启动项目、未修改全局 Codex Home。
