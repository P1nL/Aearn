# Implementation Plan: RAG Shadow Integration Fixtures and Interview Evidence

## 2026-09-22 后续自主治理接缝（本child仍为阶段I）

本child阶段I的fixture/default-off回归不能证明真实来源可用。阶段II新增真实抓取/激活/RagEvidenceBinding/consumer逐scope启用验收，与既有fixture-only生态公开边界分开。 统一增量见 `../09-03-rag-language-ecosystem-adaptive-retrieval/autonomous-corpus-extension.md`；本child原正文描述阶段I，不因新增方向自动扩大其写集、开启真实环境或跳过最终规划批准。

1. Start only after Children 01-05 are archived.
2. Add complete deterministic route/ecosystem fixtures and validation tests.
3. Add default-off v2 Lesson/Tutor compatibility adapters and safe status projections.
4. Add integration tests proving fixture corpus lifecycle, retrieval, coverage, preflight and existing public behavior.
5. Add the repeatable interview demo and bounded expected output.
6. Update `docs/README.md` source links only if needed and revise architecture/database/API/user-flow/QA source-of-truth sections.
7. Run final serial backend, database, Desktop typed, no-route/no-schedule, link and hygiene gates.
8. Invoke Trellis check, address findings, commit/archive this child and return to parent final review.

## Expected Write Scope

- `aearn/services/api/app/services/grounding/fixtures_v2.py`
- `aearn/services/api/app/services/learning/grounding_adapters.py`
- relevant integration and compatibility tests
- optional deterministic demo script under `aearn/scripts/`
- current source-of-truth docs and QA evidence
- minimal Desktop types/tests only if a safe status field is added; no new management UI

## Verification

```powershell
uv --directory .\aearn\services\api run pytest -q tests/grounding tests/learning/test_rag_plan_preflight.py tests/learning/test_rag_plan_migration.py tests/integration/test_rag_v2_architecture.py tests/database/test_db_bootstrap.py tests/database/test_schema_manifest.py
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run mypy app
uv --directory .\aearn\services\api lock --check
pnpm --dir .\aearn desktop:check
git diff --check
```

Record focused and final evidence honestly: fixture/no-network success is not real corpus, public course, real embedding or deployment approval.

## 本轮执行与验收结果

- 前置child05实现8a6273c、归档5f1b58f；用户批准继续本child。未创建额外协调任务，未推送。
- 两个GPT-6-Sol实现子代理分别完成adapter/tests与scenario/demo/integration；独立GPT-6-Sol check完成修复与边界审查；所有子代理已完成并关闭。
- fixture_v2场景manifest复用已有不可变fixture-v1资料/摘要，覆盖4route/6ecosystem；未更改原语料政策。
- 默认关闭internal shadow引用adapter重验server-owned plan和全量有界sealed fixture行，生成明确synthetic/public-blocked的旧Lesson/Tutor形状。无公开consumer/route/worker接线。旧retrieval import边界仅为精确adapter路径增加例外，并新增对adapter的反向引用扫描；不能推广为其他learning模块放行。
- demo显式opt-in、精确临时库确认、本机实际连接身份与关闭态校验，拒绝libpq/query覆盖；不创建/bootstrap/drop库、不自动修复外来/部分corpus。真实CLI流程和重复回放已执行。
- 最终联合测试330 passed、0 skipped、105.57s。全app/tests/demo Ruff、Mypy276源文件、uv lock、Desktop tsc/Vite通过；48个本地Markdown文件链接目标有效，diff check通过。
- 双次demo共80实际CLI子进程，10Subjects，safe JSON完全一致。161张非corpus表不变，回放167表不变，含主代理合成track/Lesson失败标记。文档根目录命令另行执行成功且输出一致。
- 独立adapter真实数据库READ ONLY REPEATABLE READ探针：10Subjects×2stages×2profiles共40场景，逐条核对content/hash/URL，验证default-off、replay、伪造结果关闭；167表内容指纹与事务身份不变。
- 10项错误确认/远程/覆盖/开关组合的实际脚本进程安全拒绝，无凭据或DSN回显。
- 两个main创建的临时数据库均零活动连接后DROP，无FORCE；原始业务数据库未写入。cleanup回执在output/rag-shadow-integration-20260923/runtime-isolation.json。
- 修复过程保留在research/main-verification.md：policy摘要遗漏、服务端plan重验、inet地址CIDR解析、LangChain无源应提前关闭的真实测试断言；最终复跑覆盖这些修复，不以fake测试或skip替代。
- 仍是阶段Isynthetic/default-off工程验收，不声明真实source、embedding、sandbox健康、公开生态、完整学习闭环或deployment/release。
- 17个文件待窄提交，见research/commit-plan.md；用户批准后按实现/归档两批本地提交并返回父任务最终复核，不自动开启阶段II或推送。

## 用户批准提交交接
用户确认两批本地提交及父任务阶段I总复核。实现提交53cf28d；不推送，不开启阶段II。330项最终测试、CLI回放、40项只读适配和10项拒绝验证通过，两个临时数据库已清理。
