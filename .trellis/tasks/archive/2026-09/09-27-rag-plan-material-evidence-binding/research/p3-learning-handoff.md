# P3/P4 学习侧接线交接（2026-09-27）

## 已接路径与使用方式

- `build_internal_material_planning_dispatcher(settings, server_opt_in=True, requirements=<server-only RequirementResolver>, evidence_factory=<same-connection EvidenceSelection factory>, provider_factory=...)`：同时要求 Settings.rag_evidence_consumer_enabled、显式opt-in、受信节点映射和带 `selections.conn` 的 C/current `EvidenceSelection`；缺任何一个仍按普通dispatcher构造，零D factory调用。不新增route/DTO、不会自动为公开factory接线。
- 显式下一条持久 `plan_drafting` run 创建后、provider前调用 `PostgresMaterialPlanningConsumer.assign_parent_feedback(parent=DraftScope, target_run_id, target_input_revision, expected_session_version)`。仓库对 parent/current session、新run及一次关联做CAS；同一target幂等重放读取已有snapshot，新run不能复用旧关联。新run revision=1合法，关键是新的run/revision tuple。
- 已注入 dispatcher 的 `PostgresTutorLearningContextLoader` 从精确 `(user,conversation,run,input_revision)` 的持久assignment读取；不查询latest。只把 bounded node/purpose/status/gap/facets 和至多2条 exact source/document handle+revision 投给模型，至多8个entry；无网页正文/原始搜索词。capability handler在 append 前于短事务再验parent/session+完整node目标hash/依赖，append后对 successor 整稿重做selection，ready项用 successor handle 和同连接current receipt冻结。provider IO仍在 autocommit=True 的IDLE边界；材料短事务临时切False并在成功/异常/取消路径恢复。
- `RequirementResolver.resolve(draft, immutable_profile, immutable_nodes)` 只允许 server-only 显式批准的 scope/version/facets/purpose/reading-level/language映射，不使用模型或当前pointer猜版本。返回全部节点的1..N用途需求；无法映射时 `MaterialScopeUnsupported(nodes)` 明确不创建虚假的正式demand/ready selection。`_dependency_entries`是P1唯一`apply_material_dependencies`的薄委托，P2在严格Result构造前也调用同一个helper；不保留第二套图算法。

## 尚需主会话串行验收/关注

1. guarded PG `tests/learning/test_rag_d_planning_consumer.py` 两条用例：首条使用 **synthetic typed authorization receipts**，第二条调用P2 `setup_ready` 的synthetic registered C corpus、真实SourceReview/CorpusGovernance/EvidenceSelection facade，均以deterministic provider贯穿真实dispatcher/context/gateway/capability/plan repo/新selection/binding；第二条断言exact document/chunk/purpose。两者都不是真实来源/真实模型验收。首稿现在也由普通dispatcher合法终结，确保第二input产生新run。只有 `AEARN_RAG_D_TEST_DATABASE_URL` 指向当前 `aearn_rag260_c_d_*` 且服务默认DB为同一个时运行；本代理没有运行PG，main须串行。P2整合用例先提交synthetic C seed以供dispatcher另连接读取，只在专用可丢弃库运行；测试若因现有Gateway policy触发未调用capability，请回传具体失败再修，不得把skip算passed。
2. 真正当前C evidence factory需由 server-only caller构造同conn `CorpusGovernance`、A actor gates/authority、`PostgresMaterialBindingRepository` 并交给 `EvidenceSelection(selections=...,enabled=True)`；本文件不注册公开调用路径、不能把synthetic fixture提升为live凭据。
3. P1契约没有“无canonical映射”的占位需求类型；当前以 typed unsupported 拒绝进入模型反馈而非伪造Subject。若业务希望无映射节点也能进持久selection+模型反馈，需要P1新增版本化 unsupported entry；本代理未擅自改他人合同/schema。
4. default-off只保留旧路径，旧 v1/hash/DTO无修改；PG schema/purge/manifest归P4，实际C当前源/真实provider/publication/E不由本测试证明。

## 2026-09-27 串行PG首轮故障与修复

- main于隔离库报告P2+P3初轮15passed/2failed：两条dispatcher用例首run在`mixed_skill_selection_action`被既有gate拒绝，capability_count=0；此前另一次测试的第二输入因首run未合法终结而无新run。两处均属本代理测试序列，不是允许放宽gate/singleton的理由。
- 测试已改首run经过普通dispatcher合法终结；确定性provider现在三次独立decision（只选Skill→只调capability→终结），符合现行4 iterations/3 model calls。main待在fresh `aearn_rag260_c_d_*`库重跑，当前**不可声称PG链passed**。
- 真实C facade用例调用P2 `setup_ready` 的唯一synthetic registered URL、source/capture/review/corpus，commit后由另连接真实`EvidenceSelection`+同conn `SourceReviewRepository/CorpusGovernance`消费。其quality/actor仍测试替身；assert successor binding exact document/chunk/main_teaching。测试只写可丢弃隔离库，不抓网、不续历史真实回执；seed唯一URL可重跑但历史行保留至该可丢弃库整体清理。
