# B2传输与解析接缝（规划研究）

日期2026-09-24。只读仓库核对；没有读取密钥、调用provider、联网抓取、安装依赖或数据库操作。

- 旧grounding_fetcher.py:62起的HttpxGroundingHttpClient会逐跳检查已登记来源allowlist，但返回完整text；它是旧来源抓取流程，不是开放候选的有界流式抓取器。不能仅通过传入新URL就满足DNS/IP固定、响应/解压/重定向总限额。
- 旧GroundingFetchDocument绑定已登记source_id、版本与provenance。B2不能为了重用接口将未审博客标成官方来源，也不能先把候选插入正式registry或corpus。
- grounding_processing.py:52-125的HTMLParser接收标题、p/li/pre/code，但通过统一_normalize_text处理内容；B2需用保留缩进的代码块/列表/表格用例检验复用边界。不得先修改旧parser再假定fixture hash不变；优先独立B解析适配，必要时共享纯辅助函数但保持旧输出。
- API pyproject.toml中httpx直接位于dev组。若B的生产适配使用它，应显式声明运行时依赖并同步lock，而不是依赖开发环境巧合；不升级其他依赖，不引入Tavily SDK/Agent框架或动态浏览器。
- 新传输需HTTPS、无环境代理/用户cookie/token、每跳目标验证、可信DNS解析后连接已核验公网IP且保持原host的TLS/SNI证书验证、实际peer检查、总deadline/取消、内容类型及流式压缩前后限额。再次让默认客户端按域名DNS解析会破坏地址固定。
- 纯URL校验与单进程传输不等于独立网络egress隔离。真实运行前需具有可验证的隔离worker/受限出口配置；缺证据保持真实fetch关闭，不能以配置布尔值或mock冒充网络层证明。
- 初版HTML/Markdown/plaintext足够验证Python/SQLite及公开GitHub教材；不默认处理JS浏览器、PDF、整仓下载、登录页面或付费内容。repo file必须绑定commit/path，不跟随浮动分支当不可变文档。
- Tavily只负责Search：采用已实测basic固定参数、max_results=5、auto_parameters=false、include_answer/raw_content/images=false、include_usage=true。研究中单次receipt报告1 credit，账户聚合快照仍0；运行时按receipt和持久化预留核算，不据旧快照退款。实际API错误映射实现前再核官方文档，特别不能把普通429当账户额度耗尽。

本研究对应产品代码尚未实现。应用级和网络级的真实证明、材料存储许可、租约/预算接线均需B实施后独立验证。
