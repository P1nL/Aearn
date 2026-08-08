# Tutor 长对话摘要检索与压缩闭环实施计划

## 开始前置条件

- Child 1、Child 2、Child 3 已完成。
- curation/summary implementation 开始前，重新读取 schema、learner state、curation、proactive repository/worker、context loader/builder 和重叠 diff。
- 确认 context summary 与 inferred memory 的产品设置边界，不因后者默认关闭而禁用必要 conversation continuity。

## 有序实施清单

### 1. 冻结 Summary v2 Schema

- 定义结构化 summary dataclass/Pydantic schema。
- 固定字段、数组/字符上限、schema version、coverage 和 source hash。
- 定义 legacy v1 短 summary 兼容规则。

### 2. 增加 Additive 数据库字段

- 扩展 `tutor_context_summaries` conversation scope、summary JSON、coverage、prior identity 和 source hash。
- 添加 composite constraints/indexes 和 guarded bootstrap。
- 更新数据库文档和 reset/delete/export contract。

### 3. 计算 Recent Window 与 Retirement Set

- 基于 Child 1 的 exact current message 查询 prior timeline。
- 使用 Child 3 budget plan 选择最新 recent window。
- 计算上一 coverage 后、recent window 前的连续退休消息。
- 加入相同时间戳、当前行非最后和空退休集合测试。

### 4. 扩展 Compaction Request

- compaction identity 包含 prior summary hash、retired message IDs/hashes、coverage 和 schema/policy version。
- outbox/trace 仍只保存安全 evidence，不保存正文。
- 高水位、终态和显式纠正触发去重。

### 5. Worker 临时加载 Evidence

- 在 lease/job scope 下按 source IDs 加载消息。
- 验证 user/conversation、coverage continuity 和 content hash。
- 读取 prior valid summary。
- 清理和有界化临时 provider input。
- 任何 mismatch 进入 stale/no_action，不调用 curator 或不写 projection。

### 6. 升级 Curator Strict JSON

- 增加 summary v2 proposal schema。
- initial/repair prompt 共享 schema 和冲突规则。
- 保持 primary-only、无 fallback、无 raw data persistence。
- 更新 fake provider/curation tests。

### 7. 持久化与检索

- 原子写 proposal、structured summary、coverage 和 projection receipt。
- 实现最新 valid summary 查询。
- `PostgresTutorContextLoader` 填充 `working_summary`。
- builder/provider 保持 current > recent > summary > memory/activity。

### 8. 降级与数据生命周期

- curation disabled/unavailable 时继续 recent-window 路径。
- stale/expired/incompatible summary 不加载。
- reset/delete 清理用户 summary；export 只遵守明确定义的 learner-safe contract。
- 不删除或改写 `tutor_messages`。

### 9. 测试与文档

覆盖：

- recent + summary 长对话；
- 相同时间戳 coverage；
- current input 排除；
- retirement set 只覆盖一次；
- idempotent retry；
- source hash mismatch；
- stale/cross-user/cross-conversation；
- user correction override；
- curator unavailable/invalid；
- trace/outbox/proposal 不含 raw content；
- legacy v1 compatibility。

## 预期实施范围

- `aearn/services/api/app/db/schema.sql`
- `aearn/services/api/app/agents/harness/contracts.py`
- `aearn/services/api/app/agents/harness/context_builder.py`
- `aearn/services/api/app/services/tutor/interactive.py`
- `aearn/services/api/app/services/tutor/persistence.py`
- `aearn/services/api/app/services/tutor/learner_state.py`
- `aearn/services/api/app/services/tutor/curation.py`
- `aearn/services/api/app/services/tutor/proactive_repository.py`
- `aearn/services/api/app/services/tutor/proactive_worker.py`
- `aearn/services/api/app/services/tutor/safe_projection.py`
- `aearn/services/api/tests/test_tutor_context_builder.py`
- `aearn/services/api/tests/test_tutor_memory_curator.py`
- `aearn/services/api/tests/test_tutor_memory_curation_outbox.py`
- `aearn/services/api/tests/test_tutor_memory_curation_scheduler.py`
- 相关 loader/persistence/bootstrap 测试
- `docs/architecture/database-schema.md`
- `docs/architecture/tutor-harness-runtime.md`
- `docs/qa/acceptance-test-plan.md`
- `.trellis/spec/backend/quality-guidelines.md`

## 必需验证

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_context_builder.py tests/test_tutor_memory_curator.py tests/test_tutor_memory_curation_outbox.py tests/test_tutor_memory_curation_scheduler.py tests/test_db_bootstrap.py -q
uv --directory .\aearn\services\api run python -m pytest -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app --no-incremental
uv --directory .\aearn\services\api lock --check
python .\.trellis\scripts\task.py validate .\.trellis\tasks\08-04-tutor-context-summary-retrieval-compaction
git diff --check
```

## 风险与回滚

- 不要把 run-local revision 当 conversation coverage。
- 不要让 worker 的 raw evidence 进入 durable envelope。
- 不要把 context summary 绑定到 inferred-memory opt-in。
- 不要重叠加载多份 summary。
- 如 v2 检索有风险，可关闭 v2 loader，回退 current + recent；保留结构化数据和原始消息。

## `task.py start` 前审查门

- 前三个 child 已完成。
- summary schema、coverage cursor、worker evidence 加载和 memory preference 边界已最终确认。
- 展示最终计划并等待单独实施批准。