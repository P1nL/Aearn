# P2 独立复核与修正（2026-09-27）

范围仅限 `current_authorization.py`、`evidence_binding_v2.py` 与三个 P2 测试文件；未操作数据库、provider、网络、真实来源或题库。主会话最新报告 fresh `aearn_rag260_c_d_final_20260927` 的完整 D 专项 45 passed / 0 skipped，manifest 两遍；本代理未独立运行 PG。该结果仍只是隔离合成协议/真实 dispatcher+provider 替身，不是实料或公开 E 验收。

## 已修正

1. `EvidenceSelection.authorize_binding` 原本在检查 D 默认关闭/同连接/事务之前读取持久 selection，导致关闭路径可能产生额外表读取。改为在 `get_selection` 之前执行 `require_transaction`；加入 NoIO 离线回归。
2. `CurrentAuthorization.require_transaction` 原本允许 READ ONLY transaction 获得 publication-fence receipt，尽管该 receipt 必须与 publication/materialization 写入同一事务。新增 `transaction_read_only=off` 检查；纯测试覆盖只读拒绝。
3. `authorize_selection` 原本只按模型/选择快照声明的 `covered_facets` 判 ready，虽逐块验证身份和当前来源授权，却没比对**exact chunk rows 的实际 facets**。可把缺失 facet 的部分证据标记成全需求 ready。内部 `AuthorizationReceipt.covered_facets` 现在由同事务锁住的 chunks 得出；选择、持久 binding 回调及便利冻结方法均要求声明覆盖与真正 chunks 匹配，ready 需完整 demand facets。对于 chunk 的合法额外 facet，只投影实际 chunk facets 与当前需求 facets 的交集；不把额外 facet 当作需求，也不因此拒绝已覆盖的窄需求。加入 queries 需求/queries+schema chunk 的纯正例（仅校验投影与消费比较，非真实来源准入），以及纯负例与隔离 PG 回归（主会话已在 fresh D 专项执行）。receipt 的聚合摘要也纳入该覆盖集合。

## 同 scope 窄需求复用追加（2026-09-27）

按主会话已定的 R1 复用边界，仅在 D adapter 从同连接 C `SourceReviewRepository.resolve` 取得完整 current review、经 C `assess_document` 当前重验，且原 A source admission 对目标用途可用后，才构造临时 demand-scoped `SourceAssessment` / `SourceAuthorization` 视图给 A 原 exact-check；必须同 subject/version、requested facets 为原 scope 与质量审核 `covered_facets` 的严格子集或相等集，且原source/document revision/hash、policy generation、storage/admission receipt和用途不变。原 `review_receipt_hash` 与**原完整 authorization**摘要纳入 P2 current receipt；未写回/修改 C/A grant 或原合同。exact chunk 的覆盖仍以所选 chunk facets ∩ 当前 demand facets 核算；若 source 审核覆盖了 schema、实际 chunk 只有 queries，则 schema-only 需求仍 gap。

新增隔离 PG synthetic fixture 的 broadened C review/chunk（queries+schema）→ narrow queries ready + current binding receipt，及另一条 broadened review 但 chunk 只有 queries、schema 窄需求仍 gap 的反例；这使用真实 C PG repository/锁/审核流程，但质量 verifier 与正文仍是合成替身，不是实料验收。`setup_ready` 在 candidate 创建前读取 prior active pointer generation，并在创建后读取新 candidate version generation；validate 使用候选自身代次，activate 使用创建前的指针代次，各自保持生产 CAS。第二次 seed 及同一 disposable 库顺序重跑不再把两种 generation 混为一谈，也不放宽生产 unique。主会话已报告这些 PG 正/反例包含在 fresh D 专项 45 passed / 0 skipped；本代理未重复执行。

只读跨层复核：P3/P4 双开关只在明确 server-only factory 创建 D consumer；未注入时仍普通 dispatcher。`required_facts` 中的材料反馈是至多8项、每项至多2个 source/document handle+revision/status/facets/gap，不含 capture/body/URL/search；REQUIRED_FACTS item/字符/token 超限由既有 builder fail closed，不再由 SYSTEM 三项限额静默挤掉。P3 `model_validate_json` 严格接收 JSON对象、binding digest 包含 contract_version，composition 调用 P2 `(conn,binding)` 同连接接口。未改 P3 代码；新增 `parent_snapshot_sources` 由持久 parent profile/plan 生成完整节点/goal hash 并用真实 Builder 序列化对比防截断，只在 D feedback 存在时进 required_facts，现有 item/token 上限不变；pure/provider-visible 断言已由 main 补。最终只读复核原 P1 跨事务窗口已关闭：`context_for_run()` 在一个外层 `material_transaction` 中成对取得 feedback/parent sources；原 helper 的嵌套 savepoint 锁保持至外层结束，interactive 仅调这一成对方法；feedback 非空但 parent 为空明确 `MaterialBindingStale`，`test_rag_d_parent_context.py` 新交错边界 pure 回归覆盖。主会话报告 P3 PG+pure 11 passed（含两条真实 dispatcher 的 provider-visible parent/feedback、COMPLETED、C exact binding），最终完整 D 46 项与静态收尾仍由 main 执行；不宣称公开consumer/E或真实来源通过。

## 复核边界

- 仍按 C `_verified` 的 version→links/docs/reviews/admissions→capture/policy/grant/root 锁链，最后 pointer `FOR SHARE`；没有修改 C 原权威。最终以 DB `clock_timestamp()` 重验；没有增加连接/commit/网络 I/O。
- 当前评分 claim/execution 缺可信 resolver，保持默认拒绝。gap/partial 的 receipt 只确认已列当前证据及 actor，不把缺口伪装 ready。
- 较宽 C review→窄 demand 已在 D 的 `_ScopedCurrentSource` / `_source_view` 实现：完整 current C review/授权先验真，再只对同 subject/version、请求 facets 被原 scope 与已审覆盖包含的情形投影临时 A exact-view，保留原 review receipt hash 与完整 authorization digest；不修改原 C/A grant。新增隔离 PG `test_broader_current_c_review_reuses_only_exact_requested_chunk_facets` 正例与 `test_broader_review_cannot_fill_missing_exact_chunk_facet` 反例；主会话报告两例已在 fresh D 专项通过；本代理未独立执行，且合成 PG 不等于 live 来源通过。
- 仅 P2 registered-policy 两种次序和 root expiry-wait 有主会话双连接证据；active pointer、candidate rule/grant、capture、坐标等为串行负例，不能称 all-writer 并发矩阵。
- `assert_publication_fence` 是 D 原子授权断言，不替题库 E 全入口验证冻结行、保存 publication receipt 或实现供题再核验。正式发布前须由主会话/题库 owner 审计所有入口及 direct pointer writer；本轮不扩共享 API/DTO。

## 验证

- 离线 `test_rag_d_contracts.py` + 三个 P2 文件：12 passed，12 skipped（无显式 disposable D PG URL）。
- scoped Ruff：pass；Mypy 两个 P2 source：pass；`git diff --check`：pass（新增未跟踪文件不由 git diff 覆盖）。
- 主会话最新报告 fresh D 专项 45 passed / 0 skipped、schema manifest 两遍，含 broad→narrow PG 正/反例、parent snapshot 3 pure 及两条完整 dispatcher（其中一条 C facade，provider 为替身）；本代理未独立重跑，广回归仍由 main 收尾。真实来源、真实模型/provider、E 公开 consumer：未执行。
