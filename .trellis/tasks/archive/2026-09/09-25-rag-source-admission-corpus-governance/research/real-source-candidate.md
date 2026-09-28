# C 真实资料样本范围（用户已确认；规划中，非现场执行）

- 候选页：SQLite 官方 `https://www.sqlite.org/lang_select.html`，用于 SQLite SQL 基础 `SELECT`；本轮尚未通过 B 的受限 fetcher 对其发起 GET、保存正文或入池。
- 官方版权声明 `https://www.sqlite.org/copyright.html` 声称 SQLite 的代码和文档由作者献入公共领域。它是资料选型依据，不是本项目对某一抓取版本、所有嵌入资源、全球法域或用途授权的最终法律结论；现场前必须记录所抓取精确页面、时间、请求链/最终 URL/hash、原页许可及 operator 存储/使用 grant。
- 已有 B 真实 smoke 是 Tavily + Python 文档一次性传输结果，没有保存原文；不得复用它充作本 C 样本，也不得重复 B 批准的一次 Tavily/目标文档 GET。
- 用户确认的现场界限：单页公开 HTTPS；无需 Tavily/第二 provider；专用隔离 egress 每跳证明，最多一次 GET、压缩/解压限制最多 1 MiB；只在新建且 `current_database()` 核对的可丢弃 PostgreSQL 库暂存与激活，不触碰现有用户/生产 active；凭据/正文不进 Git、日志或任务研究记录。失败/许可不明即标 blocked/not_executed，不重试以规避一次调用上限。
- 本记录来自官方页面的规划期检索；未运行生产配置/网络出口、正式 storage grant 或 C 源审核。

- 覆盖说明：该 SELECT 页是 `route.sql` 的 queries 范围候选，不能推导 schema 必需 facet 或评分 claim。即便在隔离库验证并激活 queries 范围版本，完整 route.sql 仍应报告 coverage gap/not_ready；是否能够通过动态 corpus 验证仍取决于具体正文、质量和许可，不为演示伪造完整覆盖。
