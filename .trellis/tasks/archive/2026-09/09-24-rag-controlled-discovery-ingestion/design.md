# RAG B 技术设计（B1 → B2）

## 边界与数据流
- A 合同/权限检查是入口，但其 resolver/预算余额是待实现端口；B 不把 `budget_active`、模型提供 root 或布尔开关当授权。B1 在可信服务端解析 actor/full demand/scope/purpose/policy generation 与当前 delegation，先查已准入资料，再签发 canonical root。基础 campaign 与按需需求共享同一 job/ledger。
- 短事务内创建/认领作业并按 root/period 原子预留额度，带 operation key 和 lease generation；事务外对受控 Tavily SearchPort 调用。尝试前持久化 attempt，取得权威用量证据后幂等结算；调用结果不明则占用额度待受控对账，不以重试退款。失租者不得提交候选或结算作业。先解析权限后预留，提交时再次校验当前授权/开关。
- `existing_only` 只在权威账户耗尽证据下返回，并保留 root、未明费用与取消/结算义务；B 不伪造 D 的教材选择或单元 ready。普通 429、401、超时标记分别处理，不触发另一供应商。
- B2 从 B1 的候选 receipt 发起，逐候选检查 DiscoveryAccessPolicy 与 StorageRetentionPolicy。独立受限 fetcher 逐跳检验 DNS、公网固定连接与实际 peer、TLS/SNI、redirect 和网络出口；流式累计压缩/解压上限、类型/超时/取消，网络 I/O 不置于 DB 长事务。解析器保留代码/列表/表格必要结构，旧 fetcher/processing 只在兼容验证后共享纯辅助函数。
- 暂存仅存 candidate 与 captured document/fragment 的 bounded provenance/内容指针；真实请求链、最终 URL、capture 范围/hash、license/revision/同源信息与留存决定分开记录。未获保存许可只记允许的最小事实，不保存原文；过期/撤权清理内容而不删除必要非秘密审计凭据；临时文件、失败样本、队列载荷、解析缓存和日志适用同一留存约束。共享候选与用户私有引用分离，以双用户导出/清理反例验证。候选无 active-corpus FK，不新增正式检索读取口；C 后续自行审核并写既有 corpus。

## 数据库/兼容
- B1、B2 各一增量 schema fragment，单人持有 `app/db/schema/__init__.py`、`test_schema_manifest.py` 与 `docs/architecture/database-schema.md`，按 B1 后 B2 串行；不改既有 260 corpus authority/fixture hash。共享 root/账本/作业与个人引用分离；私有映射受权限及用户清理约束，公共收据不含用户文本。
- worker queue 默认 off、无全局 beat/公开路由；启动和 lease 提交均查开关。Tavily/httpx 若进入运行路径必须列运行时依赖并更新锁文件；外部传输、隔离出口的具体 API 先用固定接口和假实现测试，live 证据另列。B1 与题库预算义务协调同一 root 而非相互透支。
- 应用级 URL 检查不能替代出口层隔离。缺生产批准的 egress、搜索费用/网络或 retention policy 时运行时 fail closed；允许离线协议测试，但不得声称 live 验收。

## 事务与失败恢复
- 唯一 operation/attempt identity 保证并发首写与重复投递只预留一次；lease owner+generation fencing 控制候选写入。provider 成功但响应丢失保留未知消耗直至有权威对账，额度耗尽不会把未知预留释放。记录有界错误码与脱敏 receipt，不记录 query 中的私密字段/密钥。
- 不执行候选页面脚本、仓库脚本、动态浏览器，不能把搜索摘要混入正文。撤权/版本变化阻止新抓取和暂存提交，不能把 staged 数据转为已准入。旧路径回归失败则回滚新增启用/迁移，保留已结算账本和审计事实供调查。

## 设计依据与未执行现场
- 父计划 `phase-ii-design.md:44-54`、`phase-ii-implement.md:31-49`；本任务 `research/persistence-seams.md`、`research/transport-seams.md`。具体表约束/传输实现需在编码前依现行规范细化；真实 Tavily/PG/egress 检验须分别留证，当前规划没有执行它们。
