# 实施计划

1. 设计并评审 `runtime_kind`、binding、receipt schema 与索引/约束。
2. 更新 bootstrap、repository/model 和数据库兼容测试。
3. 实现 Aearn-owned Runtime event projector 与 terminal mapping。
4. 接入 final message safety、lease/revision/generation fence 和 idempotency。
5. 接 conversation event/snapshot/SSE，保持 public union向后兼容。
6. 添加 duplicate replay、late event、crash、unsafe final、domain commit/message分离测试。
7. 验证 DB/API/SSE/Desktop fixtures 不含 prohibited raw fields。
8. 运行 bootstrap、focused pytest、ruff、mypy、Desktop contract tests、Trellis validate 与 `git diff --check`。

## 风险文件

- `aearn/services/api/app/db/schema.sql`
- `aearn/services/api/app/services/tutor/persistence.py`
- Tutor run/repository/conversation event/public API 文件
- `aearn/apps/desktop/src/api.ts`
- `aearn/apps/desktop/src/types.ts`
- `aearn/apps/desktop/src/hooks/useTutorConversationStream.ts`

## 回滚

关闭 Codex admission并停止新 binding；保留 additive schema和已有 evidence。若 projector 回归，Codex feature保持 off，Harness仍走原投影。

## 实施结果（2026-08-18）

- 已新增不可变 `tutor_runs.runtime_kind`，默认 `harness_v1`，并新增 Runtime binding、safe item receipt 与 Aearn 公开错误表。
- 已实现 `PostgresTutorRuntimeProjectionRepository` 与 `TutorRuntimeEventProjector`：验证 user/conversation/run scope、lease owner/generation、input revision、connection generation、turn identity 和 terminal 状态。
- 只允许 `phase = "final_answer"` 的 `agentMessage` 进入 final-message 安全门；reasoning、commentary、command/path、tool raw arguments/results 不进入公开投影。
- 已覆盖 completed、interrupted、failed、unavailable、unsafe/missing final、duplicate replay、sequence conflict、stale generation、receipt append-only 和 runtime kind immutable。
- Harness run 继续默认 `harness_v1`；公开 Tutor snapshot/history/event/SSE 与 Desktop 类型保持兼容。

### 验证

- `pytest -q -m "not real_provider"`：`652 passed, 2 deselected`。
- Focused Runtime/DB/architecture：`29 passed`。
- `ruff check app tests`：通过。
- `mypy app`：`Success: no issues found in 190 source files`。
- `pnpm --dir .\aearn desktop:check`：通过（TypeScript + Vite production build）。
- `python ./.trellis/scripts/task.py validate 08-17-codex-tutor-durable-projection`：通过。
- `git diff --check`：通过。

本 Child 不调用真实 provider；未新增或执行真实 `deepseek-v4-flash` turn。
