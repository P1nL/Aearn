# 新鲜 C 来源预检与单次尝试（2026-09-27）

## GET 前可行性结论

**有条件可行，已在第一次真实 worker 调用前形成此检查点。** 旧 C 回执/暂存授权在 2026-09-26 13:26:59 UTC 到期；旧库、旧 root/policy/dispatch、capture、review、receipt、active 均未复制、续期或改写。主会话于 2026-09-27 独立查验官方 `https://www.sqlite.org/copyright.html`（页面更新 2026-01-12），其称 SQLite 代码和文档为 public domain；这仅是许可依据，不能替代本次来源授权、抓取或质量审核。

### 新部署和精确授权

- PowerShell Core 7.6.5、Docker Linux Engine 29.8.0 可用；没有重启/修改全局 Docker。旧 C 容器保持停止，旧卷只读检查。新库 `aearn_rag260_c_d_live_repair_01a0e0c7` 位于任务专属 PG 容器/数据卷，无发布端口。C/D DSN 分别读 `/run/operator/dsn` 或 `/etc/rag-c-control/dsn`（同一新 operator 卷，**秘密值未输出**），`SELECT current_database()` 均为新库。当时 39 个 schema fragment 连续 bootstrap 两次（之后因统计表名笔误又完整通过两次）；旧/业务库未写。schema 380 并行演进，D 运行前主会话须对**最终现行 manifest 再执行两次**，不可把本次当作最终版本。
- 新 root `root.c.dlive.repair.01a0e0c7`、policy `policy.c.dlive.repair.01a0e0c7`、generation 1、dispatch `0ffc109e-136b-4b99-b270-2896f8d92edd`，均仅在新库。root/policy 启用并在请求前实测当前有效；到期 2026-09-28 11:54:38 UTC。仅精确 `https://www.sqlite.org/lang_select.html`、`route.sql`/`sqlite-docs-v1`/`queries`、官方来源、`SQLite-Public-Domain`、`supplementary_explanation`、不可变历史许可和 8,388,608 bytes 上限。`schema`、`main_teaching`、`assessment_evidence` 未获授权。官方域名或许可不自行产生质量结论。
- 2026-09-27 对 1.1.1.1 新查 A 记录为 `194.195.208.62`；与旧实验 IP 巧合相同，但不是复用旧签名/pin。内部 Docker 网络仅含新 control/PG，外部 v6 网络仅含新 egress；egress 无 DB 凭据/路由、Docker socket、host network/PID、发布端口或宿主应用源码挂载。control/egress 只读 rootfs、非 privileged。旧已审核 worker 镜像固定 `sha256:1bfee54fb95dbad3f08ac216a1d7c36c0068d8031322bd397e930a35194c1a6c`，镜像内 worker 代码 SHA-256 `aec9e8c71c250692b9bb00b0c2dec8fd4e2dcb0e969bddb90d3cd14c44a02e46`。这不是新镜像构建或公开部署证明。

### 安全与信任门禁（均在 arm 前通过）

- 首次新 egress 配置遗漏 C bridge 挂载，随后在**无 arm/dispatch/GET** 时替换本任务 control/egress；第二轮外部网络未启 IPv6，`fc00::1` 虽被拒绝却没有 DROP 计数，正确停止。再次在**无 arm/dispatch/GET** 时启用本任务独有 IPv6 外部网络 `fdc0:01a0:e0c7:1::/64`，重新生成 B/C 临时密钥及独立 pin。前两轮 pin 全部作废；没有碰旧 C 部署。
- 当前 B 签名器公钥 SHA-256 `49616fdf987199fadf8710af0a8ae2998abf7e09830cd67889a2596e6ce67fb8`、policy SHA-256 `15267f8c94cf1389005bf5406f8e565e0b56f106f2db09f99e1cc13243b5df27`、netns inode `4026532490`；通过新 B socket 卷只读通道独立比对。当前 C bridge 公钥 SHA-256 `2a6be5d5e9192719237019bb97089c11a1a24a671b7deb1a88929c46f34ed7f3`，Unix peer UID/GID/权限与跨 netns PID=0 检查通过。真实 B signer 在无 GET 挑战上产生签名并由非 root worker 验证；**这不是本次 GET 的 transport proof**。
- `iptables`/`ip6tables` 均为 nf_tables 后端、OUTPUT DROP，IPv4 仅开放 DNS 1.1.1.1 TCP/UDP 53 和目标公网 IP TCP 443。11 个非 root、CapEff/CapBnd=0、NoNewPrivs=1 的负向探针分别让对应 DROP 计数增长（loopback/RFC1918/新 PG/metadata/DNS:5432/目标:80、8443、IPv6 `::1`、`fc00::1`、带接口 scope 的 `fe80::1`）。目标:443 正向 TCP 成功但**没有 HTTP**。worker 在真实 egress 容器内 `_identity`、`_pins`、固定 `_ports` 检查通过；只会由既有 worker `--once` 使用两次 C grant、零 redirect、独立压缩/展开 8 MiB 限额和 10 秒 fetch deadline。
- 既有独立自动审核镜像固定 `sha256:442da66e41c22299c7e338d980414a46dc5de9b6da0ed183ddf6d4d01d1349e0`。通过原历史 operator 卷的 `automated-review` 子目录**只读挂载**，在该镜像执行 `_inputs`，确认未改动服务私/公钥配对、当前新控制配置/B pin，以及外部固定公钥 SHA-256 `c3f7b56d5ccf7fa765ca6fabc50c9f519b18d8e5b0f032673cb1474906109e68`；未输出私钥、未复制或伪造审核服务、未签新回执。
- arm 前新库再检查：尝试/捕获/review/admission/active 均为 0；root/policy/许可/期限和 B/C pin 均匹配。用户没有叫停；本代理无付费搜索/模型调用。

## 单次 worker 运行及终态（不得重试）

- 仅创建一个短效 root-only arm，启动**一次**非 root worker `--once`（外层 45 秒 watchdog；实际于约 12.5 秒返回）。固定输出：`WORKER_ONE_SHOT_DENIED stage=fetch code=DEADLINE_EXCEEDED`，exit=1。**没有第二次 worker 调用、没有重新授权、没有抓取旁路、没有 C 审核。** stage=fetch 无法证明 HTTP GET 是否已发出或收到多少 body；不能写成 GET=0 或成功抓取。目标 TCP 443 ACCEPT 计数含预检流量，只能证明出站流量，不能证明完整 HTTP/TLS/body。
- 实库精确一行 attempt `0ffc109e-136b-4b99-b270-2896f8d92edd`，先 `dispatched`，无 response hash/bytes、无 capture。随后使用正式 `PostgresRegisteredSourceRepository.mark_unknown` 终态化为 `unknown / DEADLINE_EXCEEDED`；再次只读核查 attempt=1、capture=0、review=0、admission=0、active=0。一次性 URL/dispatch 不再可用，不换 policy/root 或新库规避。短效 arm 已从**本任务卷**删除；审计行未删改。历史容器/卷未改。
- 自动审核服务没有运行 `admit_existing_capture`：缺少真实 settled capture，不能伪造可信回执或让 provisional 文件冒充数据库准入。C 实际验收与 D 同链真实来源均 **blocked**，没有 source capture/corpus ID、没有当前 material authorization/binding 可交给 D。仅有新注册 policy/root（且 dispatch 终态 unknown）绝不是 `ready`。

## 保留与交接

- 保留新任务 PG、control、egress 容器/全部任务卷，不停、不清理；主会话需要先消费失败证据。新库名、内部网络与 DSN secret **路径**见上；公有 scope/pin/request hash 可从 `.runtime/rag-d-live-repair-01a0e0c7/{registration,b-public-pin,worker-public-state}.json` 读取。DSN 秘密仅在 `aearn-d-live-repair-01a0e0c7-operator` 卷。`source_capture_id=null`、`corpus_id=null`、当前受信审核/授权 adapter 输入**不存在**。无当前 C 来源时真实 D E2E 不能宣称通过；可以分开做真实 provider/合成资料测试，但不能合并成同一真实链。
- 不进行第二个 SELECT 请求；需主会话/用户另行决定新的独立授权和故障诊断。当前失败具体位置只能界定为 worker fetch 的 10 秒 deadline，不能猜作 DNS/TLS/HTTP/body 某单一环节。费用：本代理 Tavily=0、provider=0；整个项目账单未对账，不能据此写项目总费用 0。
