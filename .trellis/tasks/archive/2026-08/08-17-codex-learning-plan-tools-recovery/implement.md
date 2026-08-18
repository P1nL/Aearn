# 实施计划

1. 盘点现有 PlanningFact、profile parser、LearningPlan validation、append repository 与 capability receipt。
2. 定义 typed planning context、module/node input、safe issue 和 `AgentToolResult` schema。
3. 实现服务端 profile builder 与 `aearn_planning_context_read`。
4. 实现 `aearn_learning_plan_draft`，复用现有 domain 校验和 append-only write。
5. 加入 revision/generation fence、idempotency receipt、payload与 repair budget。
6. 在 fake Codex loop 中覆盖 invalid -> repair -> completed、awaiting user、conflict、policy、timeout 和 duplicate replay。
7. 保持旧 Harness capability 测试通过，不接正式 admission。
8. 运行 focused pytest、ruff、mypy、domain/bootstrap tests、Trellis validate 与 `git diff --check`。

## 风险文件

- `aearn/services/api/app/agents/capabilities.py`
- `aearn/services/api/app/services/learning/plan_capability.py`
- PlanningFact、LearningPlan domain/repository/schema 文件
- 新 Runtime tool registry 与测试

## 回滚

Typed tool facade 在正式 cutover 前不可达；回滚不删除既有 LearningPlan 数据，关闭 registry registration 即可。
