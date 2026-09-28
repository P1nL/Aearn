# C 接缝核对（规划证据，未修改业务代码）

- `aearn/services/api/app/services/grounding/corpus_repository.py:163-258,274-339` 是唯一既有 source/document/chunk snapshot、validation event 与 Subject 单 active CAS/rollback 写者；`finalize_validation(passed=True)` 仅证明行存在/计算 hash，不足以证明 C 的用途审核和语义质量，必须有 C 的独立验证服务在同一 caller-owned transaction 中先行核查并写 receipt。
- `aearn/services/api/app/services/grounding/corpus_service.py:261-347,421-447` 的 `_audit/validate/activate/rollback` 是 **fixture-only** 审核，摘要 `fixture_only=True` 且验证精确 fixture 源/内容；不得把真实 SQLite 文档喂入这个 CLI 后用 `mode=fixture` 假装通过。C 需在既有 `CorpusRepository` 之上添加独立动态审计/激活编排，不重解释旧 fixture-v1。
- `aearn/services/api/app/services/grounding/corpus_contracts.py:45-126` 现有 `CorpusSource.trust_tier` 限 `official|trusted_de_facto`；C origin/purpose/lineage 必须在版本化新表/合同中表达，旧 `trust_tier` 只是兼容投影，第三方不得伪装官方。
- `aearn/services/api/app/services/grounding/autonomous/contracts.py:157-177` 的 `SourceAssessment` 需要 storage/admission receipt 且 status reviewed 才可声明 allowed usages；`source_policy.py:16-65` 比较 exact scope、revision/hash、origin/reading level、policy generation；`assessment_contracts.py:20-110` 的 claim/execution resolver 需 C 的真实持久权威，模型文本不能授予 claim。
- B 已有 SafeFetcher/签名 egress/concrete CandidateHopPolicy、B staging/receipt 和预算；现有 B intake lease 的 claim 仅接受 **completed B1 job + settled Tavily attempt/reservation**，本轮明确不调用 Tavily。因此 SQLite SELECT 的真实样本应走父计划允许的 **operator 预注册精确 URL/Subject/path** 通道，复用安全传输核心而不伪造 B 发现收据；需为此通道添加独立当前授权/一次性访问义务及严格 hop policy，而不是放宽 B 候选仓储。
- `SafeFetcher.live_ready` 目前只认可 exact CandidateHopPolicy；如复用，需显式审查加入专属 registered-source policy 类型及其 per-hop 当前授权/出口证据，不能把任意 duck-typed HopPolicy 当 production 许可。单页 GET 如果返回 3xx，不跟随第二请求，按本轮上限停下。
- `subject_registry.py:46-52` 的 `route.sql` required facets 是 `queries` 与 `schema`。仅一份 SELECT 文档最多证明 queries 的审核范围，不能宣称全 route.sql ready 或 assessment_evidence；若在可丢弃库以部分 coverage 验证/激活，也须保留 schema gap/not_ready 和默认关闭的消费者。
- 尚未执行当前任务的数据库 bootstrap、真实资料 GET、C admission 或激活；这些均是实施及现场阶段，在本轮最终方案再次获批前不得启动。
