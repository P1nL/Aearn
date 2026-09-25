# B live 出口预检（现场，不等于业务验收）

- 用户另行批准：仅在专用隔离出口验证私网/metadata 阻断后，最多一次 Tavily 免费搜索和一个经许可的公开 HTTPS 文档抓取；未确保存储许可不保存正文。
- 使用本地 `python:3.12-slim` 衍生临时镜像 `aearn-rag-b-egress:local`，只在临时容器的 network namespace 授予 `NET_ADMIN`，初始化后 `iptables OUTPUT DROP`、`ip6tables OUTPUT DROP`，仅放行 Docker Desktop 配置的 DNS `192.168.65.7:53` 和本轮预先解析且确认公网的 `api.tavily.com`、`docs.python.org` 的 IPv4 TCP/443。容器挂载仓库只读，`no-new-privileges`、rootfs read-only、`/tmp` tmpfs。防火墙设置后转 `nobody`，`CapEff=0`。
- 同一脚本在防火墙生效后对 IPv4 loopback、Docker gateway、实际 Aearn PostgreSQL `172.19.0.3:5432`、10/8、172.16/12、192.168/16、169.254.169.254 以及 ::1、ULA、link-local 发起 TCP probe，均未连接；IPv4 DROP counter 为7，IPv6为1。私网/metadata失败为超时，部分IPv6因无路由立即拒绝。DNS 例外后，在 policy 内 `docs.python.org` 名称解析成功（非文档 GET）。
- 构建镜像期间安装 Debian iptables 与固定 Python依赖，属于搭建环境，不是 Tavily搜索/资料抓取。以上证据仅证明这个临时 namespace 的本轮规则，不能证明生产部署出口；防火墙脚本在被批准调用的同一容器中先验收再执行，不能跨另一无约束容器复用结论。
- 随后在**同一隔离容器**完成一次且仅一次真实 Tavily Search：HTTP 200，`request_id=2bc1d245-9715-4597-9b01-ba634f387633`，返回 usage `credits=1`、5 个结果，含本轮允许的 Python 官方文档结果。查询为去身份的 `Python tutorial introduction official documentation`。没有重试，也没有第二次 provider 调用。
- 随后一次且仅一次受控公开 HTTPS GET：`https://docs.python.org/3/tutorial/introduction.html`，`live_egress_attested`，1 hop、无重定向，最终地址相同，`text/html`，71,957 bytes，正文 SHA-256 `7965490e774a3f0ff0810537f07289b35d5cee2fb9d466c0b995a32c135b6c49`。正文仅驻留内存，**没有**写盘或暂存；不能凭此声称正式摄入或内容保留许可。
- 上述是真实 transport 和此临时 namespace 的限定出口 smoke，不是持久预算账本、生产 worker composition、正式隔离暂存、C 准入或生产出口的端到端验收。调用时的授权与精确来源策略由本地脚本在范围内注入；生产开关仍关闭。后续验证不得重复这一次 Tavily/文档 GET；剩余验收只使用本地测试、隔离 PG 和静态审查。
- 脚本位于忽略的 `output/rag-b-egress-lab/`，不提交到 Git；现有 Tavily 凭据仅从本机环境安全传入容器标准输入，未输出或写入日志/文件。安全结果日志不包含密钥或正文。
