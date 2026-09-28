
## 2026-09-25 自动审核纠偏（用户明确要求执行）

正常流程不以真人签名为必经条件。可信独立审核服务负责自动检查并签发明确标识为service的机器回执；人工operator回执仅是可选干预，不再是唯一实现。不能把模型建议、网页自述或仅有关键词当已证实质量。

本轮使用有限、可审计的SQLite SELECT基础语义profile：读取已获准完整capture，复核当前provenance/许可，用严格受支持的完整原文语句与真实SQLite执行核验支持限定结论。只批准exact原文片段、queries范围、supplementary_explanation；不宣称完整页面/所有SQLite功能正确，不授main_teaching或assessment_evidence。无匹配、歧义或失败自动拒绝/隔离，不默认索要人工确认。

机器回执独立绑定service identity、profile/code版本、capture全文hash及provenance、exact片段hash/offset、执行环境/结果、允许用途和有效期；签名密钥由可信operator部署侧持有，来源worker和网页无权签发。验证端使用独立pin公钥，重新核对证据，不接受伪装人工回执。

SourceReviewRepository及CorpusGovernance在准入、动态读取、建库、验证、激活时限制为获审用途与exact片段，不能凭一段受审内容放行全文或任意子串。现有真人全量审核adapter兼容，但仅在自身可信回执有效时可用。

提供一次自动执行入口：已有capture→服务审核/签名→用途准入→candidate→validate→隔离CAS active。没有网络抓取、没有追加GET、没有Tavily/外部模型调用费用、不开D/E消费者。真实完成以实际服务回执、DBreview/admission/active及当前动态核验为准；未通过项不能伪造通过。
