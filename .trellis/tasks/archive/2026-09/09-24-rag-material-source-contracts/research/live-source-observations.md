# 关键公开来源核对：真实检索/页面读取，不是语料准入

## 授权与方式

用户于2026-09-24批准关键真实搜索/抓取。本轮先通过网页工具检索/读取公开内容，再对四个明确URL做一次性HTTPS诊断探查。没有连接业务DB、启动RAG摄入worker或写corpus。

直接HTTP探查：无cookie/token/代理认证，不跟随重定向、不绕过访问限制；每响应最多保留256KiB的哈希输入前缀，另读至多1byte判定截断，timeout15秒；只保存状态/类型/字节数/捕获范围哈希等元数据，不保存正文。这个限制是本次诊断预算，不是产品runtime的固定参数。DNS预检不是IP pinning，不能据此声称B的SSRF/egress隔离验收通过。

## 观察

| 位置 | 网页观察 | 独立直连探查 | 仍缺的证据 |
| --- | --- | --- | --- |
| https://docs.python.org/3.12/tutorial/datastructures.html | 指定3.12系列教程的结构/示例可读取，可作为版本化source候选 | HTTP200，96467bytes，完整本次响应 | 实际执行profile匹配、scope/facet审核、正式用途准入 |
| https://sqlite.org/lang_select.html | 官方SELECT语法/语义说明可读取 | HTTP200，达到256KiB截断 | 完整内容未捕获，不能拿prefix hash当整篇document hash；尚无用途/版本/facet准入 |
| https://www.runoob.com/sqlite/sqlite-tutorial.html | SQLite教程入口可读取，存在分章节导航 | HTTP200，67076bytes，完整本次响应 | 教学适读性与具体claim核验、实际版本、保留/使用政策；首页不代表全站已抓取 |
| https://github.com/swaroopch/byte-of-python | 公开教材仓库页面及说明可读取 | HTTP200，达到256KiB截断 | HTML入口不是教材文件；尚未固定commit、挑选内容文件、核验各文件许可/版本/claim |
| https://www.zhihu.com/tardis/bd/art/554755399 | 网页工具可读到以资料汇总/领取为主的页面 | 未做独立直连探查 | 不能从推荐标题/页数或领取说明推断获得了教材正文；不追随领取/登录/付费渠道 |

网页工具搜索结果也是候选发现，不是RAG runtime生成的search/fetch receipt；直连元数据见bounded-public-probes.json。两类证据不混写。完整响应只表示完成读取这次HTTP返回体，未证明它是所需教材、最新版本或允许全文复用的材料。

## 对A合同的影响

1. Candidate必须区分landing/index、正文、repo页面与具体文件/revision；候选元数据不得宣称body已取得。
2. 内容摘要要标captured范围和complete状态；截断抓取不能满足整篇hash/provenance。
3. 对网页声明版本、课程适用版本与执行profile分别建字段，不用页面“Python教程”标签判等。
4. 存储/使用政策和教材/评分用途仍各自审核，不能从HTTP200、官方域名、仓库存在或宣传文字自动授予准入。
5. 真实抓取许可不改变A业务写集，也不把本次调查算作B/C实现或任何公开教材已上线。
