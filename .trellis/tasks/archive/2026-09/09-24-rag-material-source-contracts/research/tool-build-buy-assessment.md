# RAG联网及其他tool：复用/选型边界

日期：2026-09-24。仅本地代码核对与供应方官方文档研究；未安装新依赖、注册账户、获取凭据或调用商业搜索/抓取API，未做效果或成本benchmark，不代表选型已定。

## 已有代码

- app/services/grounding/grounding_fetcher.py：httpx传输、登记source/URL检查、逐跳allowlist检查、content hash与provenance。
- grounding_processing.py：已有HTMLParser正文分段、标题层级、代码/列表文本及chunk处理；不是从零没有抓取/解析。
- 不能据此声称满足第三方开放候选的全部DNS/IP pinning、压缩/响应限额、保留和动态页面隔离要求；B2仍须按新版政策逐项审计。
- pyproject.toml直接将httpx列在dev组；实际生产依赖是否由其他包提供需在B2打包时核对，不能现在单凭此行宣布运行故障。

## 候选与官方依据

| 层 | 候选 | 本次文档核对 | 建议 |
| --- | --- | --- | --- |
| 搜索 | Tavily Search | 查询、域名范围、搜索/内容结果相关接口 | 与Brave用相同中文/英文教学查询小样比较后择一，A只保留可替换SearchPort |
| 搜索 | Brave Web Search | title/URL/snippet、语言/时间等参数；另有LLM Context提取接口 | 优先独立候选结果模式，provider摘要不当原文 |
| 普通HTTP | 现有httpx fetcher | 当前仓库实际代码已核对 | 复用可用逻辑，补stream上限/权限/provenance及网络隔离，不重写完整HTTP库 |
| 正文/元数据 | Trafilatura | 主文、标题/作者/日期、结构/代码和可选表格等提取能力 | 与现有parser对同批教程比对；优先本地解析已获准的HTML，不默认调用其自带抓取器绕broker |
| 托管抓取/动态页面 | Firecrawl Scrape | Markdown/HTML/结构化输出、动态页面；API成功与目标page status分开 | 可选后备，费用/数据流/证据充分性先审；不宣称所有网站都能读取 |
| 浏览器采集 | Crawl4AI | AsyncWebCrawler、浏览器配置、Markdown/结构化提取 | 若需要自托管动态页面再评估；页面JS带来单独隔离/资源门禁，不默认全部页面用浏览器 |
| 公开仓库文件 | GitHub REST Contents/README | 公开资源读取与ref参数 | 只读具体path，先解析并固定commit，不把repo网页或浮动branch视为教材不可变版本 |

官方文档（本次已读取）：
- https://docs.tavily.com/documentation/api-reference/endpoint/search
- https://api-dashboard.search.brave.com/app/documentation/web-search
- https://api-dashboard.search.brave.com/documentation/services/llm-context
- https://trafilatura.readthedocs.io/en/latest/
- https://docs.firecrawl.dev/features/scrape
- https://docs.crawl4ai.com/core/quickstart/
- https://docs.github.com/en/rest/repos/contents

## 必须自有的业务工具与权限

模型侧候选工具：查已有教材(find_materials)、提交去身份化发现建议(discover_candidates)、读取已获探查许可candidate(read_candidate)、查看版本/来源元数据(inspect_candidate)、请求受限claim核验(request_claim_check)、查询准备状态(material_status)。名字为候选合同，不是已实现端点。

SourceDiscoverySuggestion由模型提出，实际SourceDiscoveryDemand仍由服务端签发。工具外壳始终经过actor/scope/用途/预算检查；第三方SDK的参数不直接全部暴露给模型。

admit_source、activate_corpus、publish_item是受信服务及原owner动作，不作为模型任意可调用tool。评分用途、同源独立性、授权generation、内容完整性、隐私、费用去重与发布fence不能交给搜索排名或通用crawler决定。

## 统一返回与证据规则

保留provider/adapter版本、request receipt、requested/final URL、时间语义、目标页面状态、content type、raw/derived类别、完整/截断、hash对象范围、费用及错误。收到时间不是原站抓取时间；供应方缓存/抽取不能伪装为我们自己观察到的DNS/redirect链。

搜索snippet、LLM答案、抽取JSON、Markdown和原始页面是不同证据层。不能对转换后Markdown计算hash却叫原始响应hash；不能把截断前缀当全文；remote provider没有提供的provenance字段必须unknown，不伪造。

Firecrawl文档特别区分API的HTTP200/success与metadata.statusCode目标页面状态，后者403/404不能因API成功而准入。

## 最小选型验证（属于B前置/B1/B2，不扩大A）

同一组Python/SQLite中英文需求，覆盖官方页、菜鸟/博客、GitHub具体文件、公开知乎文章、动态页、登录/拒绝页和超长页。记录候选相关性/多样性/重复来源、代码缩进/表格保真、真实版本/provenance/截断标记、延迟/请求成本、错误/访问限制处理及隐私数据流。

首版建议仅选一个搜索provider，保留本地受控HTTP+parser/GitHub读取；动态采集按实际失败样本再选Firecrawl或Crawl4AI，不把所有工具都装成强依赖。不新建搜索引擎，也不为使用工具重建一套RAG/agent框架。

供应方API密钥、计费和托管内容处理权限若未获准，不进行相应真实API benchmark；公开官方文档研究不等于已验过搜索召回/中文适配/费用。A只定义Search/Fetch/Extract/Repo/ClaimCheck等port和权限合同，B才落具体SDK/工具适配。
