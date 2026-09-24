# Package A 独立代码审查与自修（2026-09-24）

## Findings (fixed)

1. `app/services/grounding/autonomous/access_policy.py`, `contracts.py`, `source_policy.py`, `assessment_contracts.py`：原先只比 demand hash/scope，消费请求可换用途；候选未绑定需求；已授权发现路径只比摘要，不能识别同 hash 下换掉 node/plan/level 的需求。现将 request/snapshot 的用途及完整受信 demand 比对，候选绑定 exact demand/scope，binding/claim 对齐 request purpose；发现检查在同一次 authority resolve 内完成，不重复解析形成 TOCTOU。
2. `assessment_contracts.py`, `source_policy.py`：原 claim receipt 未绑定 demand/admission/purpose；独立来源只依赖 receipt 内的布尔值及不同 handle，未核当前来源 family/文档版本/撤权/用途；隔离执行只有 claim receipt 上自报 execution id/scope。现绑定 exact demand/purpose/admission，重新解析主来源和独立来源当前文档、family、generation、用途、许可状态；执行方法必须通过独立 `ExecutionReceiptResolver` 的精确 claim/demand/document/环境/input/语义 receipt 且未撤权。原 `check_source` 仍只是低层元数据检查；正式评分必须走 `authorize_assessment_claim`。
3. `source_policy.py`：调用方可以把同一文档的 blog/适读性自行改标为 official/advanced。当前 resolver metadata 新增 origin/reading_level/reviewed 并与 assessment 精确比对，不用来源标签授予权限。
4. `source_preferences.py`：超过八项偏好时静默截断；改为拒绝越界输入。
5. `tests/grounding/rag_material_helpers.py`, `test_rag_material_source_contracts.py`, `test_rag_source_access_policy.py`, `test_rag_source_usage_policy.py`, `test_rag_assessment_claims.py`：补充跨需求/用途/receipt、family 与当前独立源、实际执行 receipt、origin 替换、嵌套 copy、关闭 gate 零调用的对抗测试。新包相关五套测试由17个扩至44个。

## Findings (not fixed) / scope boundary

- A 的 resolver 协议和合成正例不能证明真实身份、签名、账本原子预留、来源真实性、独立家族实质可信、执行器结果真值、隐私查询分类、DNS/egress/许可，也不包含真实 Tavily 或 existing_only 消费路由。这些是 B/C/D/E 的真实实现及验收，不构成 A 内已上线证明。`QueryProjectionResolver` 必须由后续可信实现审核/脱敏；纯 DTO 字符约束无法单独识别学习者隐私文本。
- API 新增/收紧字段，main 需同步其所写 spec：`SourceCandidate.demand_hash/scope`、`AccessRequest.purpose`、`AuthoritySnapshot.demand/purpose`、`SourceAuthorization.lineage_family/origin/reading_level/reviewed`、`ClaimEvidenceReceipt.demand_hash/purpose/admission_receipt_id` 及独立来源文档/family 坐标；`authorize_assessment_claim` 的隔离执行正例须传 `ExecutionReceiptResolver`。本 reviewer 不改 main 持有的 spec。

## Verification

在 `aearn/services/api`、`PYTHON_DOTENV_DISABLED=1`、`LLM_TYPE=disabled`、`CODEX_RUNTIME_ENABLED=false`、非业务 `DATABASE_URL=postgresql+psycopg://rag:rag@127.0.0.1:1/rag_review` 下：

- 新合同五套定向 pytest：44 passed，0 skipped。
- `uv run ruff check app tests`：pass。
- `uv run mypy app`：pass（281 source files）。
- `uv lock --check`：pass（55 packages）。
- `git diff --check`：pass；仅有仓库现有 tracked 文件换行提示，不是 diff 错误。
- 未运行旧 grounding 74 测试/真实 DB/provider/browser；main 独立负责该 baseline、旧文件 hash 与最终复跑。本轮未联网、未访问凭据/DB、未提交。

修改文件（仅 reviewer 拥有写集）：`app/services/grounding/autonomous/{access_policy,contracts,source_policy,assessment_contracts,source_preferences}.py`，`tests/grounding/{rag_material_helpers,test_rag_material_source_contracts,test_rag_source_access_policy,test_rag_source_usage_policy,test_rag_assessment_claims}.py`，本报告。

## Main integration follow-up: repo coordinate coherence (2026-09-24)

- Confirmed the original equivalence condition admitted exactly one of `repo_commit` / `repo_path` on `document`, `landing`, or `repo_page`. Before the fix, the new matrix reproduced 12 failures (20 valid/existing-invalid combinations passed).
- Fixed only `SourceCandidate.coherent` in `contracts.py`: `repo_file` requires both fields; all other kinds require neither. No independent repository hints are accepted.
- Added 32 parametrized regression cases in `test_rag_material_source_contracts.py`: four candidate kinds x four coordinate combinations x direct construction/model_copy revalidation. This includes valid repo-file and non-repo cases, not only rejection cases.
- After fix: the five new-contract suites have **76 passed, 0 skipped** (previously 44; +32). The material-contract file now contains 37 test cases. Full `ruff check app tests`, `mypy app` (281 files), offline `uv lock --check`, and `git diff --check` pass.
- Main's separately reported 118 passed / 7 skipped integration run preceded this change; the reviewer did not rerun or relabel that legacy/integration result.
- Follow-up write set: `contracts.py`, `test_rag_material_source_contracts.py`, and this append-only report section. No broader re-audit, spec edits, runtime work, or commits.
