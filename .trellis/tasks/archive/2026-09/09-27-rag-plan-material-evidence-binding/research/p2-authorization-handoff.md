# P2 授权与精确绑定交接（2026-09-27）

本代理仅负责 grounding evidence/current authorization 与专项测试；不改 C/schema/plan。调用方必须传入已开启短事务的同一个 psycopg Connection、显式 enabled、CorpusGovernance（同 conn、C 隔离门禁）、A actor AccessRequest/gates/AuthorityResolver。接口拟为 resolve_evidence(conn, demand, draft_scope, *, governance, request, gates, authority_resolver, enabled=False)；check_current_authorization(conn, binding, purpose, *, governance, request, gates, authority_resolver, enabled=False, claim_resolver=None, execution_resolver=None)；assert_publication_fence(..., exact_item_claims, expected_generation, ...)。均不自开连接/提交/联网，返回精确当前身份 receipt 或闭合集错误。

P1 当前 material_contracts_v2.py 的 EvidenceCoordinate.chunk_id 是 UUID 格式，但 260 表 chunk_id 为 ^[a-z0-9][a-z0-9._:-]{0,159}$ 的 text，需改为 bounded key；corpus_id 可用 subject_id、corpus_version_id 才是 UUID。260 只存 registry_digest，不存 registry_generation 整数；建议 V2 改用 registry_digest。validation_hash 应明确取 validation receipt/admission digest 而非模型字段。此为共享类型 blocker，P1 owner 修。

锁矩阵：C _verified 首先 version FOR UPDATE，_rows link/doc/source/admission/review FOR SHARE，SourceReviewRepository._resolve_scoped 再锁 review/admission 并重验 capture/policy、candidate grant/rules/root，最后 D pointer FOR SHARE + 重读 generation/event。registered root authority SELECT FOR SHARE；candidate grant resolver g/c/d/j/lease/policy/root、rules/settlement FOR SHARE。D 不可先锁 pointer 再等 version。不同来源按 canonical source/document/chunk 顺序。DB READ COMMITTED 锁等待后重新 SELECT，并在最终 fence 取 clock_timestamp 复验所有期限（不能只用 transaction_timestamp）。

注意：PostgresQualificationAuthority 对 assessment 直接 None；A ClaimReceiptResolver 和 ExecutionReceiptResolver 尚无受信 PG 实现。assessment 必须默认拒绝，不能把 rag_verified_claim_receipts 行当 verifier。C _transaction 只允许 aearn_rag260_c_*，不得在 D 放宽。过期的 C 真实两段样本不作 today's ready。直接 CorpusRepository pointer writer 的全局锁审计与 E 全 item 入口由主代理/后续包负责。

## Learning/P1 facade（更新）
`EvidenceSelection(conn, governance=real_C_governance, request_for=server_only_requirement_to_AccessRequest, selections=PostgresMaterialBindingRepository(conn), gates=AutonomousGates(evidence_consumer=True), authority_resolver=trusted_server_resolver, enabled=True)` 是同 conn 对象，提供 `resolve(conn, requirement, draft)->MaterialSelectionEntry`、`authorize_selection(conn,selection)->CurrentMaterialAuthorizationReceipt`、`authorize_binding(conn,binding)->CurrentMaterialAuthorizationReceipt`。无 `selections` 实例时 binding 拒绝；binding callback会从持久 selection 读 exact requirement/entry，校验handle+digest+evidence，再生成服务端 AccessRequest；callback不得由模型组装 AccessRequest。gap/partial selection receipt只确认当前actor/scope和当前已列证据，不能把缺口表述为来源ready。`resolve_evidence`（整稿）和 `freeze_binding` 是额外便利接口。C isolation and READ COMMITTED continue required; facade不会打开连接或提交。

## 本代理当前实现/验收界线
`EvidenceSelection` 已提供 learning-facing `resolve(conn, requirement, draft)`, `authorize_selection(conn, selection)`、`authorize_binding(conn,binding)`；后两者返回P1唯一 `CurrentMaterialAuthorizationReceipt`，从真实C current及A actor authority生成，先前内部细粒度 `AuthorizationReceipt` 只作聚合Hash/供publication fence使用，不作为repository callback返回。`authorize_binding`要求同连接`selections`仓储并读取持久selection的同node/goal/purpose/evidence，不能从binding payload自行重建模型authority。`request_for`必须是受信server-only requirement->AccessRequest adapter（不能从模型payload或URL组装），A AuthorityResolver须当前校验完整demand。`resolve_evidence`便利用途是整稿选择，不代替server draft CAS和P1 record。

已写离线测试/显式D库PG测试（尚未执行PG）：registered policy和root、capture retention、exact document/chunk/summary/coverage/retrieval/registry tamper、partial/用途/assessment否定，两连接先撤权/先fence与模拟publication+materialization同事务回滚。candidate grant/rule、指针并发及真实Item全入口仍需主代理串行隔离DB实跑/补矩阵；C direct pointer writer不能由本代理改。

## 竞态覆盖状态（以主会话PG实测为准）
两连接测试代码覆盖 registered policy 的“先撤权→fence整笔回滚”和“先fence持锁→撤权UPDATE lock_timeout→发布提交后撤权”，以及 root UPDATE 持锁跨deadline后以DB clock拒绝；后两项新增的 expiry 测试尚待主会话PG实测。active pointer/generation 变化是同连接串行负例，并未证实指针writer双连接竞态。candidate grant/rule、capture retention、root generation、doc/chunk/summary tamper也仅是串行负例；C既有FOR SHARE锁矩阵可复用，但不能宣称全部writer双连接实测passed。assessment缺真实可信claim/execution resolver仍默认拒绝；E题库全入口/供题再核验未接入。

## 主会话实测更新（2026-09-27）
主会话在fresh显式隔离D PostgreSQL库完成P2+P3组合：15 passed / 2 failed；两项失败均属于P3 fake provider违反 mixed_skill_selection_action，由P3处理。本P2三个专项文件合计11例，PG全部passed（包括registered policy两种双连接先后、root锁等待跨expiry、active pointer/generation变化、candidate grant/rule、捕获清除、精确坐标篡改）；没有P2 PG失败。这里的合成质量verifier/合成数据库只证明协议与锁，不证明真实C来源、生产部署或E公开题库consumer。

实测覆盖细分：双连接是registered policy fence-before/revoke-before与root行锁跨截止；pointer是同连接串行版本变化；candidate grant/rule、capture retention、root generation、document/chunk/summary/registry/retrieval/coverage是串行负例并复用C锁，不能写成全部writer双连接竞态已通过。生产业务库权限与C隔离guard未放宽，旧C真实回执过期不使用。
