# 本地提交计划（待用户确认）

## 第一批：feat: integrate guarded RAG shadow adapters and fixture demo

以下17个文件相对于D:\works\Aearn\Aearn：

- `.trellis/spec/backend/index.md`
- `.trellis/spec/backend/grounding-shadow-integration.md`
- `aearn/scripts/rag_v2_demo.py`
- `aearn/services/api/app/services/grounding/fixtures_v2.py`
- `aearn/services/api/app/services/learning/grounding_adapters.py`
- `aearn/services/api/tests/grounding/test_grounding_fixtures_v2.py`
- `aearn/services/api/tests/grounding/test_grounding_retrieval_boundary.py`
- `aearn/services/api/tests/integration/test_rag_v2_architecture.py`
- `aearn/services/api/tests/learning/test_rag_grounding_adapters.py`
- `docs/README.md`
- `docs/architecture/rag-v2-interview-guide.md`
- `docs/architecture/tutor-harness-runtime.md`
- `docs/architecture/database-schema.md`
- `docs/architecture/api-contract.md`
- `docs/product/user-flows.md`
- `docs/qa/acceptance-test-plan.md`
- `docs/qa/tutor-harness-release-readiness.md`

## 第二批：chore: archive RAG shadow integration verification

- `.trellis/tasks/archive/2026-09/09-03-rag-shadow-integration-fixtures-docs`（第一批后生成）
- `.trellis/workspace/pinl/index.md`
- `.trellis/workspace/pinl/journal-1.md`

只窄暂存，不推送，不提交output/.env/缓存/构建产物。两库已清理，独立check与主代理最终验证完成。提交归档后返回现有RAG父任务进行阶段I总验收，不创建新协调任务，不自行开启阶段II真实来源或公开consumer。
