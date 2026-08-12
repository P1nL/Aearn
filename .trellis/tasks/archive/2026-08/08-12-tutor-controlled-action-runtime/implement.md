# 实施计划

## 前置门

- 必须先完成并归档 `08-12-tutor-authoritative-context-facts`。
- 开始前确认 `08-04-exercise-gates-execution-unlock` 已归档且当前 execution intent/job contract 未漂移。
- 本任务处于 `planning`；用户再次审批后才允许 `task.py start`。

## 步骤一：冻结 Action contract

1. 定义 descriptor、invocation、execution result、verification result、receipt、recovery enum。
2. 定义 side-effect、retry、resource 和 public projection policy。
3. 定义 authority reference，禁止复制领域真相。
4. 添加 contract serialization/hash tests。

## 步骤二：Persistence 与状态机

1. additive 创建 action invocation/attempt/verification/receipt schema。
2. 实现 lifecycle CAS、terminal ownership、retry lineage、idempotency 和 stale fence。
3. 扩展 reset/delete/cutover/export inventory。
4. 添加 bootstrap、race、cross-user、replay 和 immutability tests。

## 步骤三：Runtime 与 adapter

1. 实现统一 admission、dispatch、cancel、timeout、retry 和 verification orchestration。
2. read-only/action serialization 规则由 descriptor 驱动。
3. 实现 bounded budgets 与 recovery directives。
4. 统一 trace correlation 和 safe error projection。

## 步骤四：第一批迁移

1. `grounding.retrieve`：包装现有 registry/allowlist/citation authority。
2. `learning.plan.draft`：绑定 authoritative facts fingerprint 和 DAG verifier。
3. `runner.execute`：引用现有 execution proof/intent/job/result，不直接执行进程。
4. 先 shadow receipt 比对，再切换 provider context projection。

## 步骤五：Context 与 UI contract

1. 将 verified/failed/recovery action items加入 `AuthoritativeContextSnapshot`。
2. 增加 stable action dedupe key，避免重复执行 current verified action。
3. API/SSE 输出统一安全状态、verification 和 recoverability。
4. 为 `learning-workspace-context-references` 提供 typed projection，不在本任务实现完整 UI。

## 步骤六：扩展点验证

1. 用测试 adapter 注册 `model_code_review.validate`，证明无需修改核心状态机。
2. 验证未来 connector/MCP adapter 必须声明 resource profile，默认拒绝动态 server。
3. 检查现有 Skill/capability/effect tests 无 authority 回归。

## 验证

至少执行：

```powershell
.venv\Scripts\python.exe -m pytest -q tests/test_tutor_capability_gateway.py tests/test_tutor_effect_commit.py tests/test_tutor_execution_effect.py tests/test_tutor_execution_repository.py tests/test_tutor_executor_job_store.py tests/test_learning_plan_draft_capability.py tests/test_tutor_run_loop.py
.venv\Scripts\python.exe -m pytest -q tests/test_tutor_event_replay.py tests/test_tutor_sse.py tests/test_tutor_trace_redaction.py tests/test_db_bootstrap.py
.venv\Scripts\python.exe -m ruff check app tests
.venv\Scripts\python.exe -m mypy app --no-incremental
python .\.trellis\scripts\task.py validate .\.trellis\tasks\08-12-tutor-controlled-action-runtime
git diff --check
```

executor adapter 变更时还需运行：

```powershell
uv --directory .\aearn\services\executor run python -m pytest -q
```

## 回滚

- 关闭 Action Runtime feature flag，恢复原专用 dispatch；保留 append-only receipt。
- 不删除现有 capability/effect/execution 表或改变其 authority。
- shadow mismatch 时停止切换，不尝试自动修补领域数据。
- 任何失败不得 fallback 到任意 host shell、未审核 runner 或动态外部工具。
