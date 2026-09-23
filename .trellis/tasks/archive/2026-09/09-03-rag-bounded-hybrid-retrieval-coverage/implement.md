# Implementation Plan: Bounded Hybrid Retrieval and Coverage

## 2026-09-22 后续自主治理接缝（本child仍为阶段I）

本child仍只对exact已准入corpus检索与计算资料coverage，不自行抓取。后续题库用只读RagEvidenceBinding消费Subject/version/corpus/receipt，不把相似度当coverage；新后台摄入属于另一owner。 统一增量见 `../09-03-rag-language-ecosystem-adaptive-retrieval/autonomous-corpus-extension.md`；本child原正文描述阶段I，不因新增方向自动扩大其写集、开启真实环境或跳过最终规划批准。

1. Start after Children 01-02 are committed.
2. Add strict retrieval, budget and coverage contracts.
3. Implement exact-scope PostgreSQL FTS repository queries.
4. Add optional embedding protocol, disabled adapter and deterministic fake.
5. Implement candidate revalidation, deterministic fusion and facet/diversity selection.
6. Add canonical result/report hashing and bounded safe projections.
7. Add simple/complex, cross-language, wrong-version, stale, fallback, budget and embedding-degradation tests.
8. Run focused PostgreSQL tests, Ruff, Mypy, Trellis check, commit/archive and stop.

## Expected Write Scope

- `aearn/services/api/app/services/grounding/retrieval_contracts.py`
- `aearn/services/api/app/services/grounding/retrieval_planner.py`
- `aearn/services/api/app/services/grounding/hybrid_retrieval.py`
- `aearn/services/api/app/services/grounding/coverage.py`
- focused grounding tests
- narrow repository query additions owned by Child 02 contract

## Verification

```powershell
uv --directory .\aearn\services\api run pytest -q tests/grounding/test_grounding_retrieval_v2.py tests/grounding/test_grounding_coverage.py
uv --directory .\aearn\services\api run ruff check app/services/grounding tests/grounding/test_grounding_retrieval_v2.py tests/grounding/test_grounding_coverage.py
uv --directory .\aearn\services\api run mypy app/services/grounding/retrieval_contracts.py app/services/grounding/retrieval_planner.py app/services/grounding/hybrid_retrieval.py app/services/grounding/coverage.py
```


## 2026-09-23 执行启动

- 用户已批准CLI两批本地提交并继续。CLI实现提交4b9a9fe，归档journal提交121f7d6；此前Subject3d54036、corpus eab2c58。未推送，启动前工作树干净。
- 当前child04 in_progress。核心代理拥有4个retrieval模块及2个核心测试；边界代理只拥有test_grounding_retrieval_boundary.py；主代理负责环境、文档/规范和最终探针。均GPT-6-Sol。
- 独占临时库aearn_rag260_cli_retrieval_20260923_1182bcd9从template0创建，core先使用，后续checker和主代理依次接管，不并行bootstrap。名称兼容已有corpus/CLI测试的安全前缀。
- 每进程显式DATABASE_URL、AEARN_CORPUS_TEST_DATABASE_URL、LLM_TYPE=disabled、PYTHON_DOTENV_DISABLED=1及statement/lock timeout。仅fixture-published corpus与disabled/fake embedding，不接真实provider、pgvector、fetch或公开consumer。
- 新schema没有production embedding receipt持久化authority；phaseI fake receipt只能是server-owned且绑定exact immutable corpus/hash的synthetic证据，不得相信adapter自报身份或宣称真实索引就绪。
- 不修改旧v1检索和公共路径，不加载所有language chunks在Python排；required facets、trust/diversity和预算由服务端约束，framework不得退回base-language corpus。
- 本轮新实现未经另行批准不自动提交/归档；隔离回执：output/rag-retrieval-v2-20260923/runtime-isolation.json。


## 2026-09-23 工程验收完成（未提交）

- 七项工程AC已勾选；177项集成最终通过，0 skipped。首轮176 passed/1 failed的operator依赖边界已通过纯policy提取修复，未豁免测试。
- 除原写集外，经主代理明确限定授权新增corpus_fixture_policy并调整corpus_fixtures兼容重导出；10 Subject的既有内容/digest及类/函数API一致性已由主代理对照4b9a9fe验证。
- fresh DB bootstrap twice通过。实际READ ONLY+REPEATABLE READ探针跑100配置、100hash replay和对抗场景，共224条结果记录；正文scope/hash/facets和预算独立核对，7表行数不变。
- 矩阵61 satisfied/39 partial，39项均为明确预算耗尽缺facet，不冒充全部覆盖满足。fake embedding不是真实provider或生产索引。
- 最终Ruff、Mypy8source files、lock、whitespace、context验证通过。所有子代理已结束；两个临时库已无连接后删除。
- 文档同步内部未接线边界、纯fixture policy、正文预算统计与未来完整prompt预算责任。
- 当前12文件仍未提交，task保持in_progress；完整证据见output/rag-retrieval-v2-20260923/acceptance-status.md及同目录JSON回执。

## 2026-09-23 Approved handoff
User approved the scoped two-batch local commit plan and continuing existing child05. Implementation commit: a42f3e7. No push. Final evidence: 177 tests passed; 100 readonly cases and 100 replay checks, 224 result records total; synthetic-only and no public cutover. Both owned temporary databases removed.
