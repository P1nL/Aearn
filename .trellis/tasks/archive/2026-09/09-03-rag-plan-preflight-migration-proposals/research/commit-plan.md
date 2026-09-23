# 本地提交计划（验收完成后待用户确认）

## 第一批：feat: add shadow RAG plan preflight and migration proposals

- `.trellis/spec/backend/index.md`
- `.trellis/spec/backend/plan-preflight-migration.md`
- `aearn/services/api/app/services/learning/plan_coverage.py`
- `aearn/services/api/app/services/learning/plan_migration.py`
- `aearn/services/api/tests/learning/test_rag_plan_preflight.py`
- `aearn/services/api/tests/learning/test_rag_plan_migration.py`
- `aearn/services/api/tests/learning/test_rag_plan_shadow_boundary.py`
- `docs/architecture/tutor-harness-runtime.md`

## 第二批：chore: archive RAG plan preflight verification

- `.trellis/tasks/archive/2026-09/09-03-rag-plan-preflight-migration-proposals`（第一批提交后归档生成）
- `.trellis/workspace/pinl/index.md`
- `.trellis/workspace/pinl/journal-1.md`

以上路径均相对于D:\works\Aearn\Aearn。窄暂存、无推送，不提交output、.env或无关文件。第一批仅在最终独立检查、主代理复跑与数据库清理完成且用户批准后执行。之后进入既有child06集成/shadow/文档验收，不创建联合协调任务。
