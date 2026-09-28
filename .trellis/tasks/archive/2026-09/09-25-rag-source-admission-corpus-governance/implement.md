# RAG C 实施与验证清单（实施中；双容器方案已批准，真实 GET 待现场 gate）

## 0. 前置与所有权

- [ ] 复核 branch/脏树、父 A–E 文档、C PRD/design、`docs/README.md` 与 backend/database/corpus/A/B specs。锁定 B 基线提交 `07e1d6f`；不动历史 fixture-v1/旧 trust，不新增公开 route/beat，不接 D/E consumer。代码前完成 Trellis Phase 1.4 的最新规划审阅与用户明确批准。
- [ ] 单独 schema/manifest/docs owner 串行掌握新 fragment 与 source-of-truth；子代理在不相交模块/测试写集并行，主代理审方向和结果。真实网络/DB/费用/正文由主代理统一控制，不能由子代理私自调用或重试。C 的审核/用途、动态 corpus 与真实样本设三个串行 review gate，防止用“全都通过”的假数据越过前驱。

## 1. C 来源与审核权威

- [ ] 先实现 operator 预注册 source 的 exact Subject/version/host/path/用途/保留/预算义务，默认禁用；另接已结算 B staging 证明作为第二输入，不伪造 B receipt。为无 Tavily 的注册源新增持久一次性 fetch dispatch/CAS、当前授权与 byte/call cap；不在事务中联网。
- [ ] 对注册源显式接入 B 安全传输核心：真实入口只接受经过审查的 `RegisteredSourceHopPolicy` 和原 `CandidateHopPolicy` 的具体类型；每跳当前政策、DNS/公网绑定/peer/TLS、签名 egress、无 redirect、1 MiB 和取消。offline fake 端口独立标注，禁止把前缀/摘要当全文。
- [ ] 增量 schema 与仓储形成不可变 document capture/revision、lineage、review facts、用途 admission、撤权和 safe receipt；正文/片段只按合法保留期限持有。检查共享/私有映射、导出/reset/delete 分类，出错保留有界非秘密错误码。
- [ ] 审核拒绝错误/过时/适读性不符/许可不足/同源冒充独立来源，输出 A `SourceAssessment`/`SourceAuthorization` 当前 resolver；独立源或真实受控执行才能对 exact assessment claim 发有效 receipt。无 adapter 或未执行就保持 `assessment_evidence` blocked，不伪造 verifier。
- [ ] 此 gate 做单元、离线反例与隔离 PG schema/bootstrap 两次、并发首写/回放/撤权/失租/保留清理验证；检查旧 B 预算/staging 和 A 合同回归。未通过不做动态 corpus。

## 2. 复用 corpus 与动态治理

- [ ] 利用既有 `CorpusRepository` 唯一 lifecycle/pointer 写者创建 C candidate snapshot；新 C provenance/usage/lineage 决策与旧 v1 trust 兼容分离，禁止把第三方伪成 official。旧 `CorpusService` fixture-only validate/CLI 保持原样。
- [ ] 独立动态 validator 从数据库与当前 C authority 重新计算 hash、FTS、scope、版本/适读性/用途、许可期限、lineage/冲突、required/covered facets；不接受调用者 `passed` 布尔，验证 receipt 与 `finalize_validation` 同事务提交。`queries`-only 的 route.sql 可报告部分 coverage，但 `schema` 仍 gap/not_ready。
- [ ] C 激活/合法 rollback 包装现有 CAS，在一个短事务内重核 operator policy/root/lease/用途 generation、retention/许可、review/admission、source/corpus hash/summary、expected active generation。撤权时 fail closed 并受控回滚/替换；保留历史 citations/成绩，consumer 仍关闭。PostgresQualificationAuthority 从 current active+admission 投影 B 的 QualificationSnapshot，gap 与 sufficient 可区分，不读 B staging。
- [ ] 在独占可丢弃 PG 库跑两次 bootstrap、并发 first activation/replay、错误 review、不完整覆盖、撤权/失租/CAS/旧版 rollback；旧 corpus repository/CLI/retrieval、fixture-v1/hash 与用户数据回归。未通过不做真实单页。

## 3. 单页真实 SQLite 现场（one-shot）

- [ ] 现场前固定唯一精确页 `https://www.sqlite.org/lang_select.html`、当前页面许可/attribution 与本项目 storage/usage/retention grant、`route.sql`/`queries` scope、operator policy generation；确认不触碰真实用户/生产 DB。新建可丢弃 `aearn_rag260_c_*` 库并先运行 `SELECT current_database()`，bootstrap 两次，无 dotenv/LLM；不以预填正文冒充抓取。
- [ ] 现场前先让用户审阅双边界变更：可信 control 容器仅连专用可丢弃 PG；egress worker 的 namespace 不通任何私网 TCP（含 PG），仅通过受限 Unix socket 向 control 取 exact scope/dispatch 当前 grant 并提交绑定 body/hash/签名证明的有界完成 envelope。离线验证 socket peer/nonce/短时签名、失联终态、不可重放及仅目标公网 IP:443 和批准 DNS；再证明 IPv4/IPv6 loopback/RFC1918/ULA/link-local/metadata 不可达、非 root/无能力、签名 attestor 有效。查验 exact host/path、TLS/peer、无重定向、压缩/解压 <=1 MiB 和持久 dispatch CAS；任一缺失 `not_executed`，不得转宿主机网络或让出口连 PG。
- [ ] **最多一次**目标 GET（含任何错误，无自动 retry/二次 redirect），无 Tavily/其他 provider；只在允许的内存/可丢弃库保存正文，任务日志只记录时间/状态、最终地址、链和 hash/字节等非秘密证据。抓取→校验内容→审核→C admission→candidate corpus→动态验证→专库 CAS active 逐层记录；若错误/许可不明/质量不达标，停在对应 blocked 层，不为达成“passed”而补正文或放宽许可。
- [ ] 断言一页只覆盖 queries、schema/assessment 仍 gap/not_ready；公开 consumer 不启用、原业务库和旧指针不变。任何额外来源/访问/费用或生产部署须重新请示，不复用 B 的 Tavily/Python 一次性许可。

## 4. 最终审查和停止点

- [ ] `uv --directory .\aearn\services\api run python -m pytest tests/grounding tests/database/test_schema_manifest.py -q` 加 C 定向/隔离 PG 与 worker regression；旧 corpus CLI/service/retrieval 在各自专用库名测试。Ruff、Mypy app、`uv lock --check --offline`、`git diff --check`，另审无公开 route/beat/secret/raw body、新表隐私分类。
- [ ] `trellis-check` 独立复核 specs/PRD 与数据流，主代理复验，分清已执行、blocked、not_executed、只读静态与生产未运行。Spec 更新、窄提交/归档另按 Trellis Phase 3；不自动推送远端。若真实单页未获得许可/未通过，任务不能报告“真实 C 全链 passed”。

## 2026-09-25 已批准边界修订（覆盖旧1MiB与单次总预算表述）

- 正式 C 全文硬上限为 8 MiB（8,388,608 bytes），压缩传输与展开正文分别校验；来源级策略可更低，但不得超出硬上限。IPC base64 帧另计编码和固定元数据余量，不与正文上限混为一谈。
- 用户已批准本轮额外最多2次同页GET，定位调用已用1次（200响应声明2033807 bytes，在旧1MiB头部检查被拒），尚余1次供修复后验证；零重定向、隔离DB及原unknown记录保留不变。
- 不通过自动重试、删除旧attempt或换policy伪装首次请求。显式批准的新预算必须与旧记录及本轮调用次数一起审计；放大字节上限不自动授予额外请求。
- 先用合理余量完成链路，再依据实际使用收紧来源级参数；不把8MiB理解为每次必须下载8MiB，不截断正文冒充full capture。

## 2026-09-25 自动审核纠偏（用户明确要求执行）

正常流程不以真人签名为必经条件。可信独立审核服务负责自动检查并签发明确标识为service的机器回执；人工operator回执仅是可选干预，不再是唯一实现。不能把模型建议、网页自述或仅有关键词当已证实质量。

本轮使用有限、可审计的SQLite SELECT基础语义profile：读取已获准完整capture，复核当前provenance/许可，用严格受支持的完整原文语句与真实SQLite执行核验支持限定结论。只批准exact原文片段、queries范围、supplementary_explanation；不宣称完整页面/所有SQLite功能正确，不授main_teaching或assessment_evidence。无匹配、歧义或失败自动拒绝/隔离，不默认索要人工确认。

机器回执独立绑定service identity、profile/code版本、capture全文hash及provenance、exact片段hash/offset、执行环境/结果、允许用途和有效期；签名密钥由可信operator部署侧持有，来源worker和网页无权签发。验证端使用独立pin公钥，重新核对证据，不接受伪装人工回执。

SourceReviewRepository及CorpusGovernance在准入、动态读取、建库、验证、激活时限制为获审用途与exact片段，不能凭一段受审内容放行全文或任意子串。现有真人全量审核adapter兼容，但仅在自身可信回执有效时可用。

提供一次自动执行入口：已有capture→服务审核/签名→用途准入→candidate→validate→隔离CAS active。没有网络抓取、没有追加GET、没有Tavily/外部模型调用费用、不开D/E消费者。真实完成以实际服务回执、DBreview/admission/active及当前动态核验为准；未通过项不能伪造通过。
