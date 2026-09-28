# RAG C：分用途来源审核与正式语料准入

## Goal

让 B 隔离候选与 operator 预注册来源的**具体文档与不可变版本**经过质量、许可和用途审核，只有合格来源才能进入正式来源池并经现有 corpus 单 active 权威验证与激活；主教材与正式评分证据分别裁决，不能由已抓取、官方域名或模型推荐直接变成可授课/可评分材料。

## Confirmed Background

- 父任务阶段 II 的顺序为 A → B1 → B2 → C → D → E。C 负责分用途审核、来源池、corpus 验证/CAS 激活与撤权/合法回滚；D/E 才负责规划反馈、消费者与逐 scope 联合启用。参照父任务 `phase-ii-implement.md:51-63`、`phase-ii-design.md:56-66`、`phase-ii-prd.md:30-50`。
- A 已有严格的 `SourceAssessment`、`SourceAuthorization`、claim/execution receipt 合同与默认拒绝校验；这些合同尚不是 C 的持久审核事实。旧 v1 corpus repository 有候选、验证、激活/回滚的单 active CAS，不应并行建立第二套公开来源权威。
- B 已归档：发现候选与捕获位于正式 corpus 之外。那次获准的真实搜索/HTTPS 只是同一临时隔离出口的传输 smoke，正文没有落盘或获准正式入池。生产 operator 配置仍关闭；不能把这份现场结果作为 C 的存储/用途许可。
- 现有 Python 核心与 SQLite SQL 是首批基础覆盖优先对象；六生态 fixture 与旧 trust/文档哈希语义不得重写。父任务仍处于规划态；本子任务 C 已获编码实施批准，且用户随后批准双容器隔离修订，但不等于生产部署放行。

## Requirements

1. 对 exact Subject/version/facets、文档或仓库精确 revision/hash、来源 lineage、适读性、覆盖、技术正确性、存储许可和用途政策分别给出可审计事实。模型自述、站点热度、官方域名与 B 搜索摘要均不能直接授予可靠性或用途权限；已知错误/恶意/不适用材料隔离，未决争议不当确定事实教授。
2. 合格第三方可按明确政策获得 `main_teaching` 或 `supplementary_explanation` 用途；`assessment_evidence` 必须针对 exact claim 有独立来源（非镜像/转载/同源）或实际受控执行/查证 receipt。缺可靠验证 adapter 的 claim 保持 blocked，不能因为教材整体合格就允许正式评分。
3. 审核、存储、用途 admission、corpus validated 与 active pointer 是分离的状态及凭据。正式来源池记录冻结版本和当前撤权状态；构建 candidate corpus 需沿用既有六张 corpus 表、事件幂等和单 active CAS，而不是让 B staging/fixture 直接供正式检索、计划或题库读取。
4. 提交、激活和合法旧版回滚均重新核对当前 lease、预算 root、访问/存储/用途授权 generation、policy/开关、exact scope、expected active generation 与 summary hash；并发 operator、撤权、失租、冲突或预算状态不明 fail closed。不能删除既有引用、引用历史或学习成绩。
5. 隐私/保留政策覆盖审核中间物、失败样本、claim 证据和日志；仅持有获准内容与最小非秘密审计事实。共享来源事实与用户私有引用分离，不经 C 权限的普通用户导出或读取不得看到其他用户或未准入正文。
6. 默认关闭，无新增公开 route、全局 beat、第二联网 provider 或自动公开课程开关。生产联网、真实来源全文留存、用途许可、执行环境及发布需要各自独立审批；开发批准不等于现场许可。
7. 用户已批准**至少一份真实资料检验**及明确边界：唯一候选为 SQLite 官方 SELECT 单页 `https://www.sqlite.org/lang_select.html`；专用隔离出口最多一次该页 HTTPS GET（任何重定向不得追加第二请求）、无 Tavily、压缩/解压正文上限 1 MiB；只在新建并以 `current_database()` 核对的可丢弃 PostgreSQL 库暂存、审核、建候选 corpus 和验证激活，不触碰现有用户/生产 active，不推送。必须先逐页核对许可及本项目存储/使用 grant，缺项停止并标 blocked/not_executed；不得重用 B 的一次传输 smoke 或伪造 B 搜索 receipt。此批准不等于 `task.py start` 的实施审批，也不授权生产运行。

## Acceptance Criteria

- [x] 错误/过时/适读性或覆盖不足、许可缺失、同源多篇、伪造执行 receipt、用途错配和撤权材料均不得得到对应 admission；合格非官方来源可按用途成为主教材，但仅具解释用途的内容不能支撑正式评分。
- [x] Exact 文档/revision/hash 与 source lineage/政策 generation 贯穿审核、claim 证据、catalog、candidate corpus 和 active 指针；未获准 B 候选和未决争议仍与正式消费者隔离。
- [x] 基于现有 corpus 权威的验证、summary/expected-generation CAS、并发/重放、撤权与合法回滚行为在隔离 PostgreSQL 中可复验；已有 fixture-v1、旧 retrieval/API 和引用兼容性不回退。
- [x] 评分 claim 有精确适用范围和真实独立佐证或受控执行 receipt；缺 adapter/证据时对应用途标 blocked，不把 fake/模型自报写成已证实。
- [x] 唯一 SQLite SELECT 真实样本经独立 egress namespace 私网阻断和可信 control 容器 Unix socket/签名完成证据的双边界证明后，一次且仅一次 GET 产生可复核的请求/证据链、许可 grant、正文与片段 hash、分用途质量审核、正式来源记录，以及隔离 DB 中的 validated corpus/CAS active（若精确 `queries` 范围质量可通过）；不得补造收据、重复请求或利用 B smoke。若许可/质量不满足，诚实记录 blocked/not_executed，不为凑激活而降标准。
- [x] 单页 SELECT 不证明 `route.sql` 的 `schema` 必需 facet，也不证明 assessment claim：即使隔离库中有 `queries` 范围 active，完整 SQL 基础资料仍报告 coverage gap/not_ready；不得因单页激活而开放消费者或发布课程。
- [x] 显式区分代码/离线 fixture/隔离 DB、真实获准来源、生产网络/存储/发布证据；Ruff/Mypy/lock/diff 和相关旧 corpus 回归通过，未运行项标 not_executed。

## Out of Scope

D 的模型教材选择/规划反馈和冻结 binding 消费者、E 的公开教学/题库供给联合启用、Tutor Gate 或学习进度变更；私有仓库、登录/付费绕过、未知脚本安装、第二搜索商、无限制全文抓取或未经批准的生产部署。

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

## 2026-09-25 C 验收完成

上述AC勾选依据最新自动审核纠偏和明确追加GET预算修订：真实capture已由独立自动服务审核，只有WHERE/LIMIT两个exact片段授予supplementary用途，完成真实review/admission/validated及隔离active；全SQL缺schema、主教材/评分用途拒绝均已实测。参见 research/c-acceptance-2026-09-25.md；这是C隔离验收，不是D/E生产启用。代码待单独授权提交，工作流未自动归档。
