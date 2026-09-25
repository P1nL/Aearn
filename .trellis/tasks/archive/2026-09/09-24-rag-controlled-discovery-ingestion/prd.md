# RAG B：受控发现、持久化预算与隔离摄入

## Goal
在既有合格教材不足或不适读时，以受控且可追责的方式发现、抓取并暂存公开候选资料；未经审核的候选不进入正式教学、检索或评分。B1 与 B2 均完成后才报告本包完成。

## Background
A 已交付合同和默认关闭的来源开关，未交付实际搜索、账本、抓取及持久化。父计划 `phase-ii-implement.md:31-49` 与 `phase-ii-design.md:12-21,44-54` 冻结 B1/B2 顺序和四层权限。A 的 `research/final-fallback-decision.md` 确认 Tavily 免费档和额度耗尽路径。

## Requirements
1. 基础 campaign 与按需缺口共用引擎。先查已有且版本、用途、适读性匹配的教材；真正缺口才启动受控 Tavily Search。模型 URL 和搜索摘要是不可信候选；查询不含身份、对话、密钥或私有资料。不接第二搜索商或模型原生联网。
2. 服务端解析可信 actor、完整 demand、scope、purpose、policy generation 和 canonical budget root。跨 query、URL、job、profile、候选族累计限额；持久化预留、尝试凭据、结算/不确定用量、去重、租约和 fencing。重启、重放、失租不能释放未知用量或越权执行。
3. 仅确证账户额度耗尽时产生 `existing_only` 信号，供后续 D 对已有合格教材再次检索；普通超时、401/限流不冒充额度耗尽。该信号不授予用途权限或解除已发作业的账务义务。
4. B2 仅对当前有发现、存储/保留许可及预算和出口条件的公开 HTTPS 候选受限抓取；逐跳重定向、DNS/实际连接地址和公网范围、压缩前后大小、类型、时限、取消均受控；无用户 token/cookie、网页指令执行、私网/metadata 或登录付费绕过。
5. 保存真实发现/抓取链、最终地址、采集范围/hash、解析片段结构、许可/版本/作者/仓库精确 revision 与同源转载线索。内容按保留政策限量存放及过期清理；审计凭据不泄密。搜索摘要/模型记忆不得伪装已抓取正文。
6. 候选隔离暂存且不可由正式 corpus、active pointer、retrieval、plan 或题库读取；C 才负责用途审核、claim 验证和正式激活，D/E 才负责消费者。沿用既有 corpus authority，不开公开 route、全局 beat 或自动准入。
7. 共享/私有数据分类和用户清理/导出语义明确，保持旧 fixture-v1 与公开行为兼容。生产联网、费用、存储及隔离出口需另获部署授权；开发审批不等于现场许可。

## Acceptance Criteria
- [ ] 资料充足不搜索；覆盖、版本或适读性缺口可启动有界作业；权限/开关、敏感查询、预算缺失时 fail closed。
- [ ] 跨 query/URL/job/profile 的累计预留、并发首写、重放、重启、失租及未知用量无超支或错放；确证耗尽与普通故障可区分。
- [ ] SearchPort 只产候选和发现凭据，不把 snippet/模型 URL 当教材；不引入替代 provider。
- [ ] 安全 fetch 的逐跳 DNS→核验公网 IP 实连/peer、重定向、压缩前后大小、类型、取消和权限拒绝有应用层测试；受限部署出口独立证明不能到 loopback/私网/link-local/metadata（含 IPv6 和重定向）。获准后代表性真实 HTTPS 抓取另证请求链、TLS、最终地址和内容 hash；mock 不替代出口或真实现场，无隔离时 live fetch 关闭并标 `not_executed`。
- [ ] 隔离暂存区分 none/prefix/full 捕获及各自 hash，搜索摘要不冒充正文、同源镜像不冒充独立来源；正式检索/计划/题库及 active corpus 不可见。保留策略分别检验全文、片段、仅 hash/定位、到期与撤权；临时文件、失败样本、队列、日志和解析缓存不能绕过留存禁令。双用户共享候选的私有引用、导出和清理互不泄漏或误删共享事实。
- [ ] 隔离 PG 两次 bootstrap、并发/回放测试、既有 corpus 回归、Ruff/Mypy/lock/diff 通过。未运行的 DB、Tavily、egress 各自标为未执行，不以模拟冒充。

## Out of Scope
C 来源准入/claim/激活，D/E 选择与供题、Tutor Gate；其他搜索商、模型联网、全站爬取、动态浏览器/PDF、陌生脚本执行、私有库/登录绕过、生产开关和付费扩容。
