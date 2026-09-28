# D 有界真实资源验证（2026-09-27）

## 已执行与边界
- 用户已选择开发期人工监控费用；不再以先建统一计费系统阻断调用。累计300元政策不变，本次没有开新provider、付费搜索、自动充值或生产开关。
- SQLite SELECT原页：一次httpx诊断因耗时过长由主会话停止（没有可验证完整结果）；一次curl返回HTTP200但20秒仅收163840/2033807字节，记录为prefix，不冒充full capture。
- 随后直接抓取SQLite官方Quick Start：HTTP200、7842bytes、4.127544s；full SHA256见real-source-diagnostic.json。正文仅存私有临时目录，原计划在收尾清理；清理命令受工具策略拒绝，实际尚保留，不写入语料或仓库。此为真实公开资料获取，不是C签名capture/质量准入。
- 使用项目原有OpenAICompatibleClient和当前已配置deepseek-flash/api.deepseek.com，调用方同步等待，具体线协议沿既有client；不另建模型账号。每次最多1个HTTP尝试、2048输出tokens，临时进程关闭自动重试、未改产品默认设置；95秒外层上限。本次两次实际请求均完成。

## 结果
1. 第一笔输入256、输出292、总548 tokens；结构、目标和节点保留，但where_details被误解为学习位置。该响应不能算语义验证通过；保留原JSON作为审计，不删除失败证据。
2. 第二笔明确SQL WHERE/表结构与来源审核的缺口含义后，输入304（其中缓存128）、输出825、总1129 tokens；返回合格的有界pace_summary修订，保留goal、全部节点/前置和缺口，ready=false。结果为“暂定每周四次聚焦学习；但资料审核、WHERE 条件过滤材料与表结构材料仍缺失，尚不能视为完整课程安排。”
3. 两笔合计1677 tokens，reasoning已包含在供应商输出用量中，不另加。实际人民币费用未换算、余额未知，由用户看账单；授权登记追加两个usage事件，未把unknown记成零。

## 不作的声明
此探测用公开短摘录和合成草案，只实际调用模型提出pace_summary变更，再用现有capability/profile合同核验，未写入真实用户计划/DB。它不是“真实provider+当前C正式准入+完整D消费”端到端验收，也不是主教材/评分资格、公开consumer或E发布。完整D代码组合另用真实PostgreSQL和C服务、确定性provider完成隔离验收。两类证据严格分开。

第一次子进程stdout因Windows编码导致终端显示失败，但UTF-8证据文件完整；第二次输出也以文件为准。这是本地显示问题，不把它当provider失败或因此重试API。第二次请求用于修正实际语义歧义，而不是为修终端显示重复收费。
