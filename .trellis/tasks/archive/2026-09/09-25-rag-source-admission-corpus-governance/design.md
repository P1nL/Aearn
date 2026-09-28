# RAG C 技术设计草案：审核 → 用途准入 → 既有 corpus 权威

## 1. 权威与输入边界

C 接收两种**已获准**但仍未准入的材料：其一是 B 已实际暂存、带来源/内容 hash 和已结算发现凭据的候选；其二是父计划允许的 operator 预注册 source/Subject/version/精确 URL/path。后者用于本轮不调用 Tavily 的 SQLite SELECT 样本，必须有自己当前有效的来源访问/存储许可与持久一次性 GET 凭据，**不得伪造 B job、Tavily attempt 或 candidate receipt**。两路归一为同一受限 `CaptureEvidence`（exact final URL/request chain、hash、内容范围、时间、来源 lineage、license 和受限 body pointer），此对象仍不授用途权限。

部署 gate：operator source policy、版本/用途/保留 grant、费用/网络批准、签名 egress、四开关分别当前有效；未知/过期/撤销即 fail closed。预注册路径借用 B 的 pinned TLS、安全 DNS、逐跳限制、gzip/类型/超时/取消，但 live 策略只显式接受经审核的 registered-source hop policy 类型或 B CandidateHopPolicy；不把通用 `HopPolicy` 协议变成 production 放行。单页允许 host/path、上限 1 MiB、redirects=0、一次持久 dispatch CAS；响应非可接受完整正文、HTTP 3xx、许可不足或任何出口证明失败，停止且不重试。网络 I/O 位于事务外，正文不得进队列/日志/研究文件；临时保留与正式 corpus 留存 grant 分别裁决。

## 2. C 持久事实与状态

以 260 与 270–310 后的新增 manifest fragment（暂定 320 来源/审核、330 claim/验证）建立：
- operator 注册 source scope（Subject/version/facets、exact seed URL/path、source revision、policy generation、allowed captures、fetch 次数/字节、usage/retention），默认禁用；独立一次性 fetch obligation/lease 与 request/response hash 证明。
- 不可变 capture/document revision 与 lineage family、内容 hash/片段 hash、来源/许可证据；body 受许可和截止约束，失败样本和解析临时物同样受控。
- 文档质量 review facts（版本/方言、可靠性、适读性、覆盖、已知错误/争议、来源同源）与审核 receipt；`candidate | reviewed | quarantined | revoked` 状态单调。审核者只能是可信服务/受审查 operator，模型和网页文本不能自审。
- 分用途 admission receipt 与当前 `SourceAuthorization` 投影；`main_teaching`、`supplementary_explanation` 可分别批准，`assessment_evidence` 只对 exact claim 且独立 lineage 或真实受控执行 receipt 生效。缺可用 adapter 时 assessment 保持 blocked，不用布尔 `verified` 或模型自报绕过。
- corpus link/validation receipt 绑定 source/document/chunk hash、exact scope、policy/review generation、coverage、冲突、expected active generation 与 summary hash。历史 append-only，撤权改变当前资格，不删除已被历史引用的快照。

共享 source/corpus/审计与用户私有需求引用分开；历史内容是否能继续留存由独立 retention grant 决定，不能只凭 B 暂存许可复制进正式 corpus。新表须分类进相关 export/reset/cutover 清单，不导出共享正文/其他 actor 引用。

## 3. 审核和激活数据流

1. 建立完整当前 demand/Subject/version/facets/purpose 与许可快照；来源预注册或 B 证明经当前权限核验。对内容完整性、TLS/peer/链/hash、版本/适读性/技术事实、同源与保留许可分别审查，生成不可变 review receipt；失败保留有限安全理由，正文不越权持有。
2. 仅 reviewed 的 exact document/revision 依据用途政策生成 admission；校验 A 的 `SourceAssessment` / `SourceAuthorization` 合同并提供 C 实际 repository-backed resolver。模型建议与搜索摘要不进入 `covered_facets` 或 claim receipt。评分 claim 的独立来源须证明不同 lineage；隔离执行只证明所记录 environment/input/scope，不能证明未执行命题。
3. 把获准 document/fragment 通过既有 `CorpusRepository.create_candidate/add_source/add_document/add_chunk` 写入新的 candidate snapshot；v1 `trust_tier` 只作兼容投影，C origin/usage/lineage 留在新权威，第三方不伪称 official。旧 `CorpusService` 的 fixture-only `_audit/validate/activate` 原样保留；C 独立动态 validator 重读数据库、hash、FTS、exact facets/retention/admission 和冲突证据；每个 chunk 必须可追溯为完整捕获正文的精确 UTF-8 字节子串（未获准的 HTML 转换器不得发明片段）后，才在同一 caller-owned 短事务调用 `finalize_validation`，不接受外部 `passed=True`。
4. 激活/合法旧版回滚也由 C 包装既有 `CorpusRepository.activate/rollback`，在同一事务重核新审核/存储/用途/claim 策略、root/lease/开关、exact Subject/version、expected pointer generation/summary hash。先锁 current policy/目标/active，再 CAS；任一撤权、失租或不同操作人并发变更均无部分发布。更新后 C qualification port 才能凭当前 active + admission 返回 sufficient/gap；候选和 B staging 不可读。正式 D/E consumer 仍默认关闭。
5. 若已发布内容随后撤权，当前 source resolver 立即拒绝其用途，新的激活被阻止并触发受控 recovery/合法回滚；不删除历史 citation/成绩，也不把未审新版本默认为后继。

## 4. 单页真实样本与部分覆盖

用户已批准 SQLite 官方 SELECT 单页作为唯一 C 真实现场：预注册精确 host/path、`route.sql` 的 `queries` facet、禁重定向、一次 GET、1 MiB、无 Tavily；选一专用可丢弃 `aearn_rag260_c_*` 库，连接后核验 `current_database()`，schema bootstrap 两次。在短生命周期双进程/双网络边界中，由可信 control 容器只访问专用隔离库，由独立 egress namespace 阻断所有 loopback/私网/metadata TCP；二者仅以权限受限 Unix-domain socket 交换 exact scope/dispatch 的短时 grant 与有界完成证据。核验签名 attestor、严格出口、现行许可/用途 grant 后才触发一次 GET；任何失败不能第二次请求。只留安全 receipt/hash/受许可内容于专库，不写原文到任务日志/Git。

这页最多支撑 `queries`，不能凭它补全 `route.sql` 必需的 `schema` 或正式评分 claim。若源页质量与许可通过，可在专库对 queries 范围建 validated/active **部分 corpus**，同时完整 SQL coverage 保持 gap/not_ready、consumer 默认关闭；若不满足则停在隔离/拒绝并报告阻断，不为了演示强制激活。隔离库 CAS 成功不是生产 active，也不发布课程。

### 4.1 实施中发现的跨边界接线（现场前必须单独审阅）

B 的进程内 `SafeFetcher` 对象收据不能跨容器，也不能让出口 namespace 为查策略直接连私网 PostgreSQL。control 进程只持有专用 `aearn_rag260_c_*` 数据库连接；egress worker 只持有受限本地 socket、目标公网 HTTPS 和指定 DNS，无私网 TCP、无数据库凭据。一次性 dispatch 必须在网络调用前提交；worker 每次 DNS/拨号前用 nonce 请求 current policy，control 重读 policy/root/attempt 并约束精确 URL、body cap 和截止。带 body 的完成 envelope 绑定同一个 dispatch、请求链、响应摘要/字节、TLS/peer 与签名出口证明；control 核验 worker/socket 身份、nonce、envelope 与当下授权，再在专库同一短事务结算 capture。失联/未知标记终态，不产生第二次 GET；无桥、无法独立核验隔离/签名、许可不明则 `not_executed`。socket 不作为通用 HTTP 或数据库代理。

这是原单 namespace 草案的**实质变更**，用户已明确批准双容器方案。现场仍须先通过同进程一次性 permit、签名 pre-dial 证明、可信 worker/peer、原子结算、实际防火墙与许可/保留 gate，才可发起唯一真实 GET；不以宿主机网络/预填 body 降级替代。当前真实请求次数为零。

## 5. 兼容、回滚与责任

先 schema/authority、后审核与用途、最后动态 corpus/真实受控现场；单个 manifest/schema owner 串行，B 与 260 现有事实不重写。操作失效先关闭新 gate 并停止新 fetch/activation，保留已结算预算和审计；许可撤销须按授权清理原文/片段、切断当前用途，不删除历史版本或用户成绩。额外生产源、付费/网络、部署放行、公开 consumer 需另批。C 的真实一页验证有单独 evidence sheet，明确代码/离线/PG/live/生产不同层次。

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
