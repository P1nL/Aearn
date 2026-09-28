# C 真实双容器预检（2026-09-25；目标 GET 未执行）

## 本轮实际执行

- 6 Sol 两个实现子代理因服务额度不足返回 403；主会话没有换模型或重试收费请求，接管并验证了留下的 control/worker 入口代码。
- 基于已核对的本地 base image 构建不可变 runtime image：`sha256:2c77ad1b9fd9e9d82bfc8890945923393ef538c6d14801cc942b9f5d9ff5cb0a`。构建前后 base 身份一致，无软件包安装；启动按 image ID 固定、只读根文件系统，不挂宿主源码。
- 新建专用 PostgreSQL 容器及 `aearn_rag260_c_live_20260925_01a0d3d4` 数据库，不改原业务容器。核对 current_database 后按 manifest 执行 schema 两遍；仅写获准 SQLite SELECT 的 operator root/policy，未创建 dispatch。
- Control 位于独立 internal network，只有该 PG 为另一个网络成员，实际 OUTPUT 仅放行该 PG IP 的 TCP 5432；IPv6 OUTPUT DROP。egress 位于独立双栈网络，无 DB 凭据、无 operator/data secret mount、无 Docker socket、无 host network/PID。
- 首次探针失败不是安全放行：IPv4 八项和 IPv6 loopback 的 DROP counter 增加，ULA/link-local 因缺 route/scope 没有计数。改为有真实 IPv6 路由的隔离网络；link-local 使用唯一非 lo 接口 scope_id，仍要求每一探针 DROP counter 增加。未添加任何私网/IPv6 ACCEPT。
- 在最终保留的 runtime namespace 中重跑：11 项负向 TCP 探针全部满足 kernel DROP counter 增加、非 root CapEff=0/CapBnd=0/NoNewPrivs=1、两个 network namespace 不同、跨容器 Unix peer/group/mode 验证成功。没有连接目标公网 IP 的 443，也没有发送 HTTP。
- 用独立 root/operator 通道捕获 B 与 C 临时公钥指纹、政策 hash、namespace、最终镜像及 worker source hash，再写只读 worker pin 配置。C bridge key 的 0644 公钥权限曾被客户端误拒绝，已修正为允许公开读取但拒绝任何组/其他用户写权限，并补测试。
- 修复 SafeFetcher 在第二次 current grant 之后检查 B proof 是否过期：若过期必须在实际拨号前拒绝，不能等正文取回再拒绝。

## 实际停止点

未 root-arm，也未调用 worker `--once`。非 root 的 signer-only Unix 握手被 B 签名器拒绝；独立诊断得到 peer UID/GID 正确且 worker 三项权限检查合格，但 root 签名器 stat `/proc/<peer>/ns/net` 返回 EACCES（errno 13）。当前容器 capability 不足以完成该跨 UID proc namespace 检查。没有移除检查，也没有擅自增加 SYS_PTRACE。

停止前在专用数据库实际核对：`dispatches=0, captures=0, active_corpora=0`，arm 文件不存在。目标页 GET=0，Tavily/provider=0。停止了临时 egress/control/PG 容器；仅保留标记为本任务的隔离数据/配置 volume 及 ignored `.runtime/rag-c-live-01a0d3d4/` 非秘密 operator state。旧临时 key/pin 不可作为后续有效部署证明。

## 验证

- backend grounding/schema：695 passed、53 skipped（显式测试 C DB，合成 fixture）。
- control/worker/offline preflight 单元：25 passed。
- bridge 单元：12 tests，Windows 3 Linux-only skip；Ruff 与 mypy app 通过。
- 目标页面仍 not_executed；没有真实 capture、审核、入池或 active。没有 commit/push。

## 下一决策

保留 B 的真实 peer namespace 校验。需要 operator 明确审阅是否仅在临时 egress root signer 的 PID namespace 内增加 SYS_PTRACE 再验证；不使用 --privileged/host PID，worker 必须仍零 effective/bounding capabilities。若不批准，不能跳过 namespace 校验发起 GET；可另设计保持相同强度的 signer 身份/隔离证明。

## 2026-09-25 后续：获准 SYS_PTRACE 后的唯一 live invocation

- 用户明确批准仅临时 egress root signer 增加 CAP_SYS_PTRACE。容器没有 privileged、host PID 或 host network；worker 仍 CapEff=0、CapBnd=0、NoNewPrivs=1。控制容器未增加 SYS_PTRACE。
- 重建 egress、重新生成 B/C 公钥并通过独立 operator 通道重新绑定 pins；旧 pins 未复用。实际 11 项负向探针通过，signer-only 签名验证通过（该步骤没有 GET），worker 身份/镜像内代码 hash/公钥路径和 DNS 精确集合检查通过。
- arm 之前专用 DB 实测 attempts=0、captures=0、active=0；policy enabled、未 revoked、expires/retention 尚有效，最大 1048576 bytes。精确固定 runtime image 未改变。
- 创建短效 root arm 后，仅调用一次 worker --once，结果 WORKER_ONE_SHOT_DENIED，exit=1。没有第二次调用、没有 refetch、没有重新发放 grant。
- 调用后 DB 实测 attempts=1、captures=0、active=0。目标 TCP 443 ACCEPT counter 为 15 packets/2565 bytes；此计数只能证明目标出口流量，不能证明 TLS 验证、HTTP GET 发出/成功、正文完整或具体失败阶段。不得继续沿用上文 GET=0 的先前停止点结论，也不得声称完成了 GET。
- 经正式 repository.mark_unknown 将已派发尝试终态化：state=unknown、error_code=WORKER_ONE_SHOT_DENIED；response_bytes/response_sha256 均 NULL。不重置 URL 一次性约束，不创建替代 policy 绕过约束。
- 停止临时 egress/control/PG，删除本轮短效 arm。隔离 PG 数据卷保留终态证据；没有真实 capture 内容留存，没有审核、入池或激活。临时 signer 已停止，其 capability 不在运行中。
- 当前 worker CLI 仅输出总括失败码，缺少可信分阶段诊断，故具体根因未确认。后续可离线补充不含 URL/body/key/凭据的阶段码并以合成 transport 测试；不得为诊断擅自重复此次真实请求。若未来重试需先审阅一次性契约与重新授权，不能直接沿用本轮 arm/dispatch。
- 6 Sol 服务额度阻止新的独立复审；本轮由主会话监督执行，未切换子代理模型、未 commit/push。

### 同日最小修复（未重新抓取）

按用户“直接修复、不补太多测试”收窄本轮：worker 现在只输出固定 stage 与可信异常类型的白名单 code；TLS 证书、握手、连接失败分别映射为安全错误码，未知异常/SystemExit 仍泛化，不输出原始异常链。主会话复核时纠正 STATUS_DENIED 白名单遗漏；6 Sol 实现与独立检查均完成，检查追加修复异常链和 SystemExit 泄漏口。

最终仅运行 connector + worker 两个聚焦测试文件：51 passed、13 subtests passed；Ruff、connector Mypy、diff check 通过。离线容器检查 CA store 含 150 个 CA，排除了空 CA bundle，但不能据此确认历史 TLS 原因。本轮没有真实请求、DB 修改、容器重启或 image 重建；旧 runtime digest 不包含新修复。修复的是失败原因丢失/安全归类问题，历史 live 根因仍未知，不能宣称抓取故障已解决或 C 已验收。

### 后续镜像内离线验证（2026-09-25）

将错误归类修复构建为独立诊断镜像 `sha256:c87c528347c06e6a3621ab58d90f710dbc31ea105f7d83ca6be5ebbab38b1104`，不覆盖原运行记录或 operator pins。构建使用显式白名单 Python 源码上下文（5.50 MB）、本地既有 base、--network none / --pull=false；构建前后 base digest 一致，最终 RootFS base layer 前缀一致。没有复制凭据、.runtime、数据库或捕获正文。

在此精确镜像内以 --network none、只读 rootfs、cap-drop ALL、NoNewPrivs 执行三个合成连接失败场景：证书/握手/连接错误码均到达 worker 白名单，每个仅一次连接函数调用，格式化 traceback 不含敏感 sentinel。镜像 worker hash `fcbf40517a12464960dfd5ffd0e5a56c023b5f9fff2c6e02fd10171e84d7f88f` 与工作树一致。默认命令仍拒绝 `C_RUNTIME_DEFAULT_OFF`。未启动原 live 容器，没有 arm、DNS 或真实 HTTP 请求。此镜像为诊断候选，不是新的 live 部署批准或此前故障根因证明。

### 获准的单次 TLS-only 诊断（2026-09-25 20:31 北京时间）

用户单独批准仅一次 TLS 握手，不发 HTTP、不新建派发、不下载正文。使用诊断镜像 `sha256:c87c528347c06e6a3621ab58d90f710dbc31ea105f7d83ca6be5ebbab38b1104` 创建独立临时容器，沿用精确 DNS/目标443的 OUTPUT 白名单并核对实际规则。无 DB/operator/arm/bridge mount、无 privileged/host PID/network；非 root 诊断进程 CapEff=0、CapBnd=0、NoNewPrivs=1。6 Sol 静态复核发现并经主会话修复了 assert 可被优化掉及未捕获异常路径，复核通过后主会话仅调用一次；独占本地 invocation marker 防止误重复。

真实结果：`TLS_VERIFIED`，TLSv1.3，目标 TCP connect calls=1、handshake calls=1、HTTP requests=0。使用默认 CA 与主机名验证，没有 application send/recv、GET/HEAD 或重试。证书有效期为 2026-08-01 01:03:35 UTC 至 2026-10-30 01:03:34 UTC；证书 SHA256 `5cb2703599be05409718b2c202497e017455a861f29269797e3be69bc2d52310`。fresh DNS 精确匹配既有获准 IP；DNS 为单独网络 I/O，不计入目标 TCP 连接次数。

结束后立即停止诊断容器；原三个 live 容器始终未启动，没有数据库读写、root-arm 或二次 HTTP。仅证明当前隔离环境到该目标的 TLS 可验证，不能追溯确认历史 TLS 是否成功，更不能确认历史 HTTP/正文/结算失败阶段。原 unknown 派发不被重置，本次不构成再次 GET 批准。

### 新增 GET 预算 2 次：第 1 次定位（2026-09-25）

用户批准最多额外2次同一页面GET用于定位/修复验证，仍单次压缩与展开1MiB、零重定向、隔离环境。原 unknown 记录不重置。第1次使用独立临时容器、精确固定诊断镜像及既有严格目标出口，非root零cap进程调用实际 PinnedTlsConnector.open 一次；仅拦截并记录有限非敏感响应头事实，不作为 C capture/签名结算证据。调用前创建不可覆盖 invocation marker。

结果：HTTP/1.1 200；Content-Type=text/html;charset=utf-8；Content-Length=2033807；无重复响应头。连接器在解析响应头时因 Content-Length 超过固定1048576上限而拒绝 BODY_DENIED，未完整消费或保存正文。该结果明确复现当前大小限制阻断；不能严格追溯证明历史第一次失败收到同样响应。

临时容器已停止；无DB读写、无正式capture、无policy/unknown重置。新增GET预算已用1/2，剩余1次尚未执行。仅gzip不能解决展开后正文仍超过1MiB的问题；不得擅自截断却标 full，也不得自行提高获准上限。要以本页完成真实full capture，需要用户批准最小范围的上限调整（建议压缩与展开各3MiB），并同步 connector hard cap/worker/scope/bridge 相关上限后使用剩余第2次验证；或保留现有约束并诚实标记此样本不适合full capture。

### 正式8MiB容量已落地（2026-09-25）

用户明确将正式正文硬上限定为8MiB。两名6 Sol分别完成backend/schema与infra bridge/worker；另一名6 Sol独立检查未发现阻断问题。压缩/展开硬上限分别8MiB，来源级低上限仍有效，B默认及B最大fetch限制保持不变；bridge completion采用base64最坏长度+16KiB元数据，普通grant/proof限制不扩大。同步SQLite质量/来源review读取上限，避免抓取通过后仍卡旧1MiB。

新增340_rag_c_capture_capacity.sql，保留历史320，用后续幂等迁移升级三项CHECK约束。主会话核对current_database后在唯一获准隔离live DB实际执行340两遍，每遍事务成功；查询确认三项上限8388608，旧policy仍1048576，原attempt仍unknown/WORKER_ONE_SHOT_DENIED，capture仍0。之后停止PG。未重置策略/旧attempt、没有新GET。

实现方报告173项聚焦backend测试通过；独立检查报告backend102passed/3skipped与48passed/7skipped、infra桥16项/3Linuxskip及worker9passed；Ruff和mypy316文件通过。Windows跳过不当成Linux运行证明。尚未用新8MiB代码重建live镜像、尚未执行剩余最后一次GET；显式新增请求预算如何接入旧URL一次性约束仍需独立实现，不能删除旧unknown或静默绕过唯一性来取得派发。

### 真实抓取闭环通过：最后获准GET已结算（2026-09-25）

- 用户批准继续后，新增350_rag_c_supplemental_dispatch.sql与显式补充授权。授权绑定新dispatch、policy/root、generation=2、精确URL/request hash、原terminal attempt与期限；一行仅准许一次新派发，不复活旧unknown，也不允许补充授权链式扩张。主会话纠正了最初遗漏的 control ARM→repository UUID透传，6 Sol补实现，独立6 Sol复核无阻断。
- 新8MiB镜像固定为 `sha256:1bfee54fb95dbad3f08ac216a1d7c36c0068d8031322bd397e930a35194c1a6c`。精确白名单源码构建，无联网安装；全新signer/bridge key、namespace/policy/image/source hash独立绑定。原live容器重建为此镜像，11项隔离探针、worker零cap、DNS和signer-only预检均通过；无privileged/host PID/network，worker无DB秘密。
- 新policy/root只对应已批准扩容与最后一次补充请求；原1MiB policy及unknown记录未变。首次克隆源策略时generation唯一约束拒绝，整个事务回滚；随后使用显式generation2成功，没有派发发生在失败事务中。
- 最后追加GET（额外预算slot2）只调用一次 worker，输出 `WORKER_ONE_SHOT_SETTLED`，exit=0。数据库：原attempt=unknown，追加attempt=settled；capture=1、quality reviews=0、active corpus=0。
- 真实capture ID `f36a8496-cb49-4b0c-a8db-f84c3fa1b528`，完整正文2033807 bytes，SHA256 `a6d38ca170dff62177e74e63297b44e567f673e7d2111de923e33b481560c140`；transport proof hash `a813bda1db57986b825abefe5a09881ccdfa5428b345c7d5761ceb2ff08e585b`。通过生产代码 PostgresCurrentCaptureProvenanceResolver 再验当前授权、正文、外部pins和签名证明，结果verified；这不等于独立技术质量审核。
- 暂存保留截止2026-09-26 13:26:59 UTC（北京时间21:26:59）；正文仅在专用PG，不输出到日志/仓库。停止control/egress/PG并删除arm。新增2次GET额度已耗尽（slot1诊断BODY_DENIED、slot2成功），不再请求网站。
- 对含真实settled和原unknown的隔离库，事务内按320→340→350重放两遍，均成功；再次读取仍为1settled/1unknown、相同正文长度及hash、1补充授权。说明旧bootstrap不会重新施加全局唯一索引阻断显式补充记录，也未改写历史正文。
- 下一实际工作是基于已留存正文完成可信质量审核及用途准入，再构建/验证/激活隔离corpus；不能将capture成功冒充C全部验收或直接开放D/E。未commit/push。


### C 全面收尾检查（2026-09-25）
详见 research/c-acceptance-2026-09-25.md：补齐 B 候选正式用途授权及 corpus 路径，最终专用 fixture PG 测试189passed/1skip；真实SQLite7项执行核验通过、私有未签名审核draft已生成。可信质量回执缺失，真实review/admission/active仍0，不把任务标completed或归档。


## 2026-09-25 C 验收完成

上述AC勾选依据最新自动审核纠偏和明确追加GET预算修订：真实capture已由独立自动服务审核，只有WHERE/LIMIT两个exact片段授予supplementary用途，完成真实review/admission/validated及隔离active；全SQL缺schema、主教材/评分用途拒绝均已实测。参见 research/c-acceptance-2026-09-25.md；这是C隔离验收，不是D/E生产启用。代码待单独授权提交，工作流未自动归档。
