# Implementation Plan: RAG Plan Preflight and Migration Proposals

## 2026-09-22 后续自主治理接缝（本child仍为阶段I）

本child仍shadow/default-off，不自动激活计划或迁移历史；单纯题库取证不强依赖迁移服务。阶段IIcorpus自动激活不改变本child计划/学习进度权限。 统一增量见 `../09-03-rag-language-ecosystem-adaptive-retrieval/autonomous-corpus-extension.md`；本child原正文描述阶段I，不因新增方向自动扩大其写集、开启真实环境或跳过最终规划批准。

1. Start after Children 01, 02 and 04 are committed.
2. Add typed node requirement, preflight result and repair proposal contracts.
3. Implement capability composition across corpus coverage, Lesson, item bank and runtime facts.
4. Implement deterministic repair alternatives and canonical proposal hashing.
5. Implement existing-track planner that preserves all current authority and only creates an inactive successor proposal.
6. Add feature-gated/default-off shadow adapter and prove public plan confirmation is unchanged.
7. Add core/optional/fixture-only/stale/replay/`lc-overview` tests.
8. Run focused tests, Ruff, Mypy, Trellis check, commit/archive and stop.

## Expected Write Scope

- `aearn/services/api/app/services/learning/plan_coverage.py`
- `aearn/services/api/app/services/learning/plan_migration.py`
- strict supporting contracts near the owning learning package
- focused learning/grounding tests
- minimal config additions defaulting off

## Verification

```powershell
uv --directory .\aearn\services\api run pytest -q tests/learning/test_rag_plan_preflight.py tests/learning/test_rag_plan_migration.py tests/learning/test_learning_plan_service.py
uv --directory .\aearn\services\api run ruff check app/services/learning/plan_coverage.py app/services/learning/plan_migration.py tests/learning
uv --directory .\aearn\services\api run mypy app/services/learning/plan_coverage.py app/services/learning/plan_migration.py
```

## 2026-09-23 执行与验收结果

- 前置child04已提交a42f3e7并归档3a24362；均无推送。用户批准继续本child。未新增协调任务。
- GPT-6-Sol实现子代理、边界测试子代理及独立check子代理均已完成；主代理已复验，无运行中子代理。
- 新增严格节点要求/报告、真实只读PostgreSQL事实适配、默认关闭shadow adapter、server-owned修复builder及existing-track不可变proposal projection。没有public确认/激活/worker/Desktop接线或数据库schema变更。
- 独立check修复：disabled零事实读取；必需模块activation锚点与非空模块/前置依赖保护；Learning Item使用节点能力而非runtime profile名字筛选；检索request/result hash校验；before/after assessment要求纳入diff/hash。原始is_core与effective activation_required不混淆。
- 主代理最终联合批：191 passed，0 skipped，75.59s。覆盖grounding全部测试、3个新plan测试及既有plan session/draft/catalog/track回归；计划中test_learning_plan_service.py不存在，改用实际测试文件。
- 主代理独立PostgreSQL只读probe：35检查记录，包含10 Subjects×core/optional、2条真实immutable track、稳定replay、stale source/plan、省略节点、LangChain错误映射关闭和shadow开关。167张public表内容指纹及事务身份前后一致，2条Lesson失败记录保留。
- 主代理Ruff（2模块+3测试）、Mypy（2模块）、uv lock --check、git diff --check通过。原始回归编排问题及修正保留在research/main-verification.md；没有通过放宽断言规避失败。
- 主代理创建的probe/test两个临时数据库均已确认零活动连接后DROP（无FORCE），回执在output/rag-plan-preflight-20260923/runtime-isolation.json及test-runtime-isolation.json；原业务库未写入。
- 当前仅synthetic/default-off阶段I：真实数据库矩阵没有伪装supported release；supported分支使用显式离线controlled facts测试。不做真实source/provider/sandbox健康证明、不持久化/激活successor、不改变历史进度，不宣称端到端学习验收。
- 8个文件待窄提交；两批本地提交方案见research/commit-plan.md，待用户批准后提交归档，再进入既有child06。不推送。

## 2026-09-23 用户批准提交交接
用户批准两批本地提交及继续既有child06。实现提交8a6273c；不推送。191项最终测试和35条只读检查通过，两个临时数据库已清理。
