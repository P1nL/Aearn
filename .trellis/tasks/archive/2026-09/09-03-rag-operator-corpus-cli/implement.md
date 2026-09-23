# Implementation Plan: RAG Operator Corpus CLI

## 2026-09-22 后续自主治理接缝（本child仍为阶段I）

本child阶段I只交付手工CLI，不暗中加入scheduler。后续自动作业复用domain治理service，以独立v2授权驱动，不让模型执行任意CLI。旧manual路径和权限保持；新增worker属于阶段II实施包。 统一增量见 `../09-03-rag-language-ecosystem-adaptive-retrieval/autonomous-corpus-extension.md`；本child原正文描述阶段I，不因新增方向自动扩大其写集、开启真实环境或跳过最终规划批准。

1. Start after Children 01-02 are committed.
2. Implement corpus lifecycle service using repository transactions and existing fetch/process components behind explicit mode selection.
3. Implement validation and active-corpus diff reports with canonical hashes.
4. Add the local CLI with structured JSON and stable exit behavior.
5. Add replay, stale generation, wrong hash, invalid state, partial source failure, rollback and active-retire tests.
6. Audit FastAPI routes, worker schedules and startup code for absence of automatic control paths.
7. Run focused tests, Ruff, Mypy, Trellis check, commit/archive and stop.

## Expected Write Scope

- `aearn/services/api/app/services/grounding/corpus_service.py`
- `aearn/services/api/app/services/grounding/corpus_cli.py`
- minimal extensions to fixture/reindex services
- focused grounding/CLI tests
- operator setup documentation only if needed by this child

## Verification

```powershell
uv --directory .\aearn\services\api run pytest -q tests/grounding/test_grounding_corpus_service.py tests/grounding/test_grounding_corpus_cli.py
uv --directory .\aearn\services\api run ruff check app/services/grounding/corpus_service.py app/services/grounding/corpus_cli.py tests/grounding
uv --directory .\aearn\services\api run mypy app/services/grounding/corpus_service.py app/services/grounding/corpus_cli.py
```


## 2026-09-23 执行启动

- 用户批准既定两批本地提交并继续。child01 Subject 提交 `3d54036`，child02 corpus authority 提交 `eab2c58`，归档/日志提交 `f606629`；均未推送。提交后工作树干净。
- 本child已启动。核心代理仅拥有 corpus_service/corpus_cli/corpus_fixtures 及 service/CLI tests；边界代理仅拥有 operator boundary tests；主代理负责 docs/spec、环境和最终验证。均使用 GPT-6-Sol。
- 核心代理独占临时数据库 `aearn_rag260_cli_20260923_7ed5ed9d20`，从template0创建，未bootstrap既有学习库。显式DATABASE_URL、LLM_TYPE=disabled、PYTHON_DOTENV_DISABLED=1及statement/lock timeout。
- 验收仅fixture模式，fetch测试只能fake transport；父design §7允许fetch路径尚未就绪时显式unsupported，不能静默回退fixture或伪造真实来源。实现中最终行为必须在报告和操作文档明确。
- 版本/来源/facet选择由server registry约束；六生态保持fixture_only、路线shadow，不自动激活公开消费者。
- 本轮新增实现未经另行批准不自动提交；本地隔离回执位于 `output/rag-corpus-cli-20260923/runtime-isolation.json`。


## 2026-09-23 工程验收完成（未提交）

- 实现及独立GPT-6-Sol检查结束，子代理全部完成并关闭；不存在提前结束运行中的代理。
- 主代理fresh bootstrap twice PASS；12文件批次114 passed；实际CLI 60子进程断言通过，覆盖10 Subject fixture矩阵、两版本发布/回滚/退役、跨状态重放、冲突和错误脱敏。
- 文档PowerShell样例AST与实际执行均通过；首次包装将bootstrap banner计入操作对象，是验收包装错误而非产品bug，已区分后重跑通过。
- Ruff（6新Python文件）、Mypy（3source files）、lock、whitespace及context validate通过。两自建临时库已无连接后删除。
- 独立修复operator校验资格/回执校验、跨pass/fail validation key、diff基线锁、真实GIN索引属性与bounded status，未修改前child已提交repository/SQL。
- 七项工程AC已勾选；status为只读，不伪造mutation幂等或CAS回执。fetch只返回FETCH_NOT_READY，真实摄入未实现。
- 当前9个源码/测试/规范/文档文件仍未提交，task保持in_progress；待用户批准提交后归档并进入child04。
- 完整证据位于output/rag-corpus-cli-20260923/acceptance-status.md、cli-subprocess-proof.json、documented-powershell-proof.json和runtime-isolation.json。

## 2026-09-23 用户批准提交与交接

用户确认本轮两批本地提交并继续。9个实现/测试/规范文件已提交 `4b9a9fe`（feat: add local RAG corpus operator CLI），未推送；随后归档并记录journal。114 tests、60实际CLI子进程、10 Subject fixture与PowerShell样例证据保留。此前未提交描述为当时状态。
