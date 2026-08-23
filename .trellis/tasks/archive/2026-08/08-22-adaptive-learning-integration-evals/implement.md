# 实施计划

## 1. 开始前

1. 确认前三个 child 已完成、提交、归档，读取各自 handoff 与最终 spec/docs。
2. 启动 `08-22-adaptive-learning-integration-evals` 并用 `current --source` 验证。
3. 加载 `trellis-before-dev`，读取父任务全部 artifacts/research 与本 child 文档。
4. 检查 git status，隔离既有用户修改。

## 2. Domain event 与 summary

1. 实现 Gate/Attempt、Review、progress、assignment adapters 和幂等 admission。
2. 实现 structured teaching summary、source lineage、stale detection/rebuild。
3. 扩展 context selection 与 protected compaction set。
4. 增加 exact cross-session reference/retrieval，禁止默认全量历史。

## 3. Evals 与集成

1. 建立 fake provider deterministic decision fixtures。
2. 覆盖父任务全部教学不变量和错误矩阵。
3. 扩展 Learning-Agent integration matrix、context eval、event replay、SSE 与 Desktop contract tests。
4. 对 provider call count、checkpoint lineage、no-auto-next、privacy markers 做精确断言。

## 4. 数据治理与文档

1. 完成 bootstrap twice、cutover exhaustive inventory、export/reset/delete/privacy。
2. 更新 source-of-truth docs 与 Trellis specs。
3. 清理已被新 contract 取代的重复说明，但不删除受保护前端原型。

## 5. Focused 验证

```powershell
uv --directory .\aearn\services\api run python -m pytest `
  tests/test_db_bootstrap.py `
  tests/test_harness_cutover.py `
  tests/test_learning_agent_integration_matrix.py `
  tests/test_tutor_context_eval_smoke.py `
  tests/test_tutor_context_summary.py `
  tests/test_tutor_context_references.py `
  tests/test_tutor_event_replay.py `
  tests/test_tutor_sse.py `
  tests/test_lesson_documents.py `
  tests/test_review_sessions.py `
  tests/test_tutor_adaptive_teaching_evals.py -q
pnpm --dir .\aearn\apps\desktop test -- --run
pnpm --dir .\aearn desktop:check
```

## 6. 完整质量门

```powershell
uv --directory .\aearn\services\api run python -m pytest -q
uv --directory .\aearn\services\api run python -m ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app --no-incremental
pnpm --dir .\aearn\apps\desktop test -- --run
pnpm --dir .\aearn desktop:check
python .\.trellis\scripts\task.py validate .trellis\tasks\08-22-adaptive-learning-integration-evals
git diff --check
```

在 disposable local PostgreSQL 对同一空 schema 连续 bootstrap 两次。使用 Browser plugin 对 fake App Server/provider 跑 Guided、插问、Free Reading、Gate/Review、completion、next node、reload/reconnect 与三视口 smoke，检查 DOM/console/network/protected markers。未经用户再次明确批准，不调用真实 provider。

## 7. 完成与父任务复核

1. 加载 `trellis-check`，发现问题直接修复并复验 focused/full gate。
2. Phase 3.3 完成 docs/spec 更新；Phase 3.4 创建本 child 工作提交。
3. 归档本 child 并记录 journal。
4. 复核父任务 PRD 全部验收映射、四个 child archive 状态和工作树范围。
5. 不自动启动或归档父任务；向用户报告最终集成证据并请求父任务收尾决定。
