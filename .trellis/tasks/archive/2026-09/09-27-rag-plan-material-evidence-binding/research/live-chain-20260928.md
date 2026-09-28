# 2026-09-28 同库真实 C→D 全链 operator 检查点

## 批准边界：当前仅准备，尚未获得主会话的最终执行放行

主会话转达用户现在明确要求先运行真实全链，并确认本地日期为 2026-09-28（Asia/Shanghai）。本代理仅负责 C live operator；写集限本报告及 `.runtime/rag-d-live-repair-01a0e0c7/`。不修改 app/schema/其他 owner 源码，不调用模型。当前可只读核对同一库及历史证据、准备脚本；**在主会话独立审查并明确放行前，不应用390、不撤销旧授权、不登记替换授权/policy/root、不 arm、不 GET**。

## 已知历史与本次纠正含义

- 继续使用 `aearn_rag260_c_d_live_repair_01a0e0c7`，不创建新数据库躲避唯一性。首次 attempt `0ffc109e-136b-4b99-b270-2896f8d92edd` 是 unknown/DEADLINE_EXCEEDED；旧错误配置的 authorization `ecf3190a-31b7-43a5-b70d-f487abac1e36` 对应 dispatch `8b367845-9298-423a-8209-b911e944e3e7`，此前没有形成第二条 attempt。历史实际状态须下方只读核验，不能从旧记录直接推定当前状态。
- 上次失败是同 policy/generation/root 的 operator 配置与既有 supplemental 成功合同不兼容，**不是已证明的 schema350 bug**。既有测试正例明确新 policy/root；本轮拟由 Pauli 的390提供明确 append-only 的“撤销未使用错误授权＋精确一个替换授权”合同，仍关联同一 original unknown，保存旧授权/attempt 原字节，不把 quota 清零。
- Pascal 负责 C-only gzip 协商；B 默认不变，C压缩/展开独立8MiB、deadline30秒、zero redirects。主会话审查两份修复与测试后才可用于本轮 live。不能使用旧 immutable image 假称含有最终修复。

## 执行计划与停止门禁

1. **当前准备阶段**：只读核对 Docker/同库身份、original unknown、错误授权及实际期限、无对应 attempt、当前 source/corpus 计数和秘密路径权限；保存非秘密行指纹。旧服务私钥不导出，历史C容器/卷不改。已停止的 control/egress 旧 namespace/key 不再当作现时证明。
2. **等主会话放行**：冻结最终390、registered_source_repository、SafeFetcher/connector/worker源码 hash 与测试结论；按同库390精确纠正合同执行，而非 UPDATE/DELETE旧行或另建DB绕行。新 policy/generation/root只能来自主会话批准的有效替换合同，source/URL/purpose不变，不修改历史expiry。
3. **镜像与部署**：白名单上下文、固定已审base、本地构建新 immutable runtime，包含最终registered-source仓储＋安全抓取/connector/worker；核对镜像内源码hash、base layers。新root control与非root零capability worker；新的B/C signer public pins、真实namespace、Unix ownership/SO_PEERCRED、双网络无DB-egress、11项IPv4/IPv6 DROP-counter gates与目标443纯TCP检查全部重新验证。
4. **唯一一次新调用**：正式当前授权核验/DB幂等边界通过后才 root-only arm，携带经390纠正后的显式 supplemental UUID；最多一次新worker invocation/潜在GET，30秒fetch deadline、有界外层watchdog、无redirect/自动重试/curl旁路/Tavily/模型。失败保留终态并停，不再发grant。
5. **捕获成功才做C准入**：同库已settled capture、真实persisted provenance；既有固定可信SQLite自动审核服务从原key位置只读使用部署私钥，签新的限时receipt，正式review/admission/candidate/partial active同事务。只允许exact WHERE/LIMIT supplementary queries；schema/main/scoring保持gap/denied。
6. **交接D owner**：仅交新DB名、DSN secret路径、config/public pins、已提交receipt/capture/review/admission/corpus IDs及实际current verifier输入；不输出DSN值/私钥/正文。主会话负责最终schema双bootstrap及真实模型D链。C通过也不等于D或公开消费者通过。

**本检查点当前状态：等待主会话最终执行批准；本轮新增GET=0、provider=0、authority mutations=0。** 下面追加只读核验，不把计划写成实测。

## 只读核验结果（本地 2026-09-28 00:12:30 +08:00）

- 本机 PowerShell Core 7.6.5；Get-Date 实测 2026-09-28 00:11:23 +08:00。PG 为主会话重启后的运行状态，任务 control/egress 仍停止；未由本代理重启它们。只读 helper 仅加入既有 internal 网络，DB事务显式 `transaction_read_only=on`，`current_database()` 精确匹配上述同一库。
- attempt=1，原始 attempt 保持 `unknown / DEADLINE_EXCEEDED`，response bytes/hash NULL；wrong authorization=1，其目标 dispatch不存在（count=0）；capture/review/admission/active均0。未执行390、没有撤销/替换/新登记。
- 错误授权期限为 **2026-09-28 00:22:39 +08:00**（UTC 2026-09-27 16:22:39）；在00:12:30观测时尚未到期，后续不得沿用该时点判断，也不能修改其expiry。旧policy/root期限为 **2026-09-28 19:54:38 +08:00**。是否准许对未用且届时已过期授权追加撤销/精确替换，必须按主会话审定的390合同核验，不猜测或用过期授权发起派发。
- 原attempt的 `SHA256(to_jsonb(row)::text)` 基线：`4d82c6b04029f3fc100f5b99f9ff66bd61bce85aea4e91eacb274f9781f931f5`；wrong authorization基线：`05dc4adccdf122e22382331dbd9eeec285bd03cd9e6ce94f79a20593cee80eac`。这是行内容表示的指纹，不宣称数据库物理页字节证明；后续应在同库同表示下复查，旧两行必须不变。
- DSN秘密文件root:0600，arm不存在；仅记录secret路径，未输出DSN值。原服务public key实读SHA-256仍为 `c3f7b56d5ccf7fa765ca6fabc50c9f519b18d8e5b0f032673cb1474906109e68`；本次没有读取/复制服务私钥。已停止control的config与B公钥/namespace仅属历史，不能直接重新使用。
- 本地只读脚本与结果：`.runtime/rag-d-live-repair-01a0e0c7/operator-readonly-20260928.py`、`operator-readonly-20260928.json`。预备部署/交接文件名见 `operator-plan-20260928.json`；这些是规划，不是生效配置/授权。

**停止点：准备与只读核验完成。等待Pauli/Pascal最终修复、主会话独立核验与明确live放行。本轮没有schema/authority写入、没有新image构建/新signer启动、没有GET/provider；不因旧wrong授权临近到期而抢跑。**

## 镜像和无 GET 部署复验完成（本地 2026-09-28 00:42 +08:00）

**部署预检 GO；live NO-GO（等待主会话明确授权）。** 主会话已报告 gzip 独立141 passed/24 subtests，Pauli21项及竞态细化、Meitner独立代码GO/noP1；这里不把这些报告改称本代理重跑。当前仅构建镜像、启动无arm的新隔离signer/control并执行无GET探针，未迁移390或登记任何source authority。

- 新 immutable runtime：`sha256:4d7567cdfb59f7f09d5aed19e9ec8bc1a6d025d5e386b3f6eab9520df15f7c98`。本地固定base `sha256:c06ac126cc7166c85a637af0192055f3990a4ce44192106be11f880a28425061`，`--network=none --pull=false`，仅COPY最终当前4个模块；base原13层为最终17层严格前缀。镜像内/上下文/工作树hash一致，预检末尾再次核对无漂移；若checker随后改任一文件，必须重新构建/重新pin后才可live。
  - registered_source_repository.py：`abb43b2c7893d0c4b4b2621654e07d2cf30c36c7dae796cb11d5cc9e8dff34bc`
  - safe_fetch.py：`2db987047841e1face81175b8a9753746c93ee906441fed0d3c6f822cc8f1b53`
  - pinned_tls_connector.py：`612e8d9304f66b4f3b99a674f37c152bdad312df829b80ab0c5781cd94cf17a7`
  - worker_once.py：`bff0c722234500b7433adfcdb152b0bf233cb84a182dd12c2414ba615aeb1002`
- 新容器：`aearn-d-live-repair-01a0e0c7-{control,egress}-20260928`；旧task control/egress仍停止、未删除，PG始终同一库。新config-only卷 `...-config-20260928`，新worker/B-run/bridge卷同后缀；旧DSN卷只读挂到control `/etc/rag-c-dsn/dsn`。新config中的scope只是**未登记计划**，无arm；其`approved`只指部署配置通过，绝非DB来源grant。
- 实际 B namespace inode `4026532490`，C `4026532718`；不同namespace，按新容器当前事实验证，不能把inode数字当跨生命周期唯一身份。B key SHA-256 `4fdefa8be26274c3fe22ec2d9f2921aa5ad7075d52706c04750efdc3ab4c0e3e`；C key SHA-256 `6e7a74afd192f58b83671eb6e3af2b4fd40165a1e2d1fe4b7f4216668efae79d`；B policy digest `15267f8c94cf1389005bf5406f8e565e0b56f106f2db09f99e1cc13243b5df27`。B key/policy经只读volume独立比对；fresh DNS pin仍194.195.208.62。
- 11项负向探针全部有实际IPv4/IPv6 DROP-counter增量；双网络成员检查只允许新control+同PG、独立新egress。nf_tables OUTPUT DROP仅DNS53/目标443例外；非root worker UID65534、CapEff/Bnd=0、NoNewPrivs=1，控制只有CHOWN，SYS_PTRACE仅新egress的root signer。C Unix socket/peer/key、B签名无GET挑战、目标443纯TCP正向均通过，未发送HTTP。
- 固定审核服务镜像 `sha256:442da66e41c22299c7e338d980414a46dc5de9b6da0ed183ddf6d4d01d1349e0` 在network=none/capdrop/read-only容器中，对新的控制配置和原位只读service key执行 `_inputs` 配对/pin检查，公钥仍 `c3f7b56d5ccf7fa765ca6fabc50c9f519b18d8e5b0f032673cb1474906109e68`；没有签名review/来源IO。
- 00:42:21+08只读live复验：390 revocation表不存在；原attempt/错误授权原350列fingerprint均匹配00:12基线。原授权现已过期（原00:22:39期限未改变）。新计划policy/root/dispatch/replacement的DB计数均0；旧attempt=1、wrongauth=1，capture/review/admission/active=0，arm仍不存在。

### 待批准的精确计划（目前仅本地配置，非生效grant）

同库、新 `policy.c.dlive.corrected.20260928.01a0e0c7`、generation2、新 `root.c.dlive.corrected.20260928.01a0e0c7`，来源handle/URL/version/purpose不变；拟dispatch `9ab67b2d-4d62-47be-8ae0-4df576b099e9`，拟replacement UUID `54b8e946-d29d-45cd-a611-97e23c2da363`，仍精确关联原unknown与错误未消费授权。新policy/root拟期限不超过现有19:54:38+08；替换授权实际期限在获准调用时取 **min(DB clock+2小时，新policy/retention/root期限)**，不复用/修改过期wrongauth期限，不新增fetch额度。

390获准后必须用最终现行manifest（不要用本镜像内base的旧schema文件）做同库bootstrap/核验。`correct_unused_supplemental` 原子追加撤销与精确一个替换，绝不手写UPDATE/DELETE旧行。迁移新增的 `replaces_authorization_id` 对旧行必须NULL；旧行保持检查使用 `to_jsonb(old_auth)-'replaces_authorization_id'` 对原350列hash，而不是误将JSON多NULL字段视作历史修改。拟执行仍仅一个新worker invocation，30秒/C-only gzip/独立8MiB/零redirect；失败停、不重试；成功才审核入池。

详情文件均在同一private runtime目录：`live390-image-manifest-20260928.json`、`live390-schema-inputs-20260928.json`、`live390-{scope-plan,b-public-pin,worker-public-state,preflight-result,prep-authority-audit}-20260928.json`。本次改动只有这些任务脚本/配置/报告，业务源文件由其他owner维护。**等待主会话对390 live＋登记新policy/root＋原子纠正＋唯一一次GET＋自动审核准入作最终明确批准。**

## 主会话明确批准后的实际执行与失败停止（本地 2026-09-28 00:48–00:54 +08:00）

授权引用为 **`aearn-development-20260927/main-20260928-unused-correction`**，对应本线程主会话在用户要求先跑通真实全链和既有开发政策下的明确live委托；这不是捏造用户签名。`live390-operator-approval-20260928.json` 为operator行动记录。执行前重新核对4个源文件、镜像、全部最终schema输入hash、当前非root/B+C pin/无arm、同库原行值；均匹配。

### 已成功执行的 authority 修复（不是来源抓取成功）

1. 同一 DB `aearn_rag260_c_d_live_repair_01a0e0c7` 应用最终 **40片段完整manifest两遍，每遍完整事务提交**（含390），使用现行已指纹核验的schema文件而非runtime旧base内schema。两次均验证原unknown与wrongauth原350列hash不变、wrongauth新增 `replaces_authorization_id` 为NULL。结果见 `live390-bootstrap-result-20260928.json`。
2. 按批准精确计划登记 `policy.c.dlive.corrected.20260928.01a0e0c7`/generation2及`root.c.dlive.corrected.20260928.01a0e0c7`；原source handle/URL/version/facets/用途保持不变；新policy/root期限为原 **2026-09-28 19:54:38 +08**，不延长/改写任何旧期限。
3. 用最终 `correct_unused_supplemental` 在同一短事务追加原wrongauth撤销和一个精确替换 `54b8e946-d29d-45cd-a611-97e23c2da363`，关联同一 original unknown；未手工改旧行。新授权期限由DB clock+2小时及root/policy期限取小，实际 **2026-09-28 02:51:19 +08**（UTC 2026-09-27 18:51:19）；不是沿用旧00:22期限。通过正式repository验证旧revoked授权返回 `SUPPLEMENTAL_DENIED`，没有插入attempt；再核验替换当前/未撤销/未消费、原350列保持。结果见 `live390-authority-result-20260928.json`。

### 唯一一次纠正后的 worker 尝试：fetch deadline失败

- 00:52:49 +08 建立带精确replacement UUID的短效root arm并启动**本次批准范围内唯一一次新worker invocation**。固定镜像4d756…、C-only gzip、30秒deadline、独立压缩/展开8MiB、零redirect；外层70秒watchdog只作最终边界，无自动重试。
- 00:53:20 +08 返回 **`WORKER_ONE_SHOT_DENIED stage=fetch code=DEADLINE_EXCEEDED`，exit=1**。配置了gzip不能证明远端实际协商gzip；固定阶段码不能单独断言具体失败在DNS/TLS/HTTP或body读取。目标443计数包含纯TCP探针及本次尝试，只是流量观测，不是完整HTTP或正文证明。**压缩/展开实际字节数均为NULL/unknown，不记0或虚构完整body hash。**
- 本次与先前同代配置失败不同：**纠正后的派发实际插入成功**，ID `9ab67b2d-4d62-47be-8ae0-4df576b099e9`，绑定replacement UUID并在授权仍当前有效时派发。后验为dispatched、无response bytes/hash、capture=0。按正式 `mark_unknown` 终态化 `unknown / DEADLINE_EXCEEDED`；没有第二次本轮调用、没有再签发授权/绕行。
- 终态实库计数：attempt=2（首次原unknown及本次纠正unknown）；旧错误dispatch `8b367845-…` 仍无attempt。authorization=2、append-only revocation=1；capture=0、review=0、admission=0、active=0。原始unknown hash、wrongauth原350列hash仍等于最初基线，新NULL字段未被利用改历史。短效arm仅从本轮新config卷移除。

### 交接与停止

**真实完整来源捕获未成功，可信SQLite自动审核/入池与D同一真实来源全链仍not_executed。** 由于没有settled FULL capture，不运行审核器、不制作provisional receipt、不借历史/fixture材料冒充同链成功。`capture_id/review_id/admission_id/corpus_id` 全部null，当前材料授权adapter输入不存在；不发送模型请求。本次纠正机会已经真实派发并终态unknown，不能重新arm或再建root/DB给同一URL加机会。

安全失败证据：`live390-{invocation-started,worker-result,attempt-result,d-handoff}-20260928.json`；完整执行脚本均为task-owned private文件。`live390-d-handoff-20260928.json` 明确blocked且没有可消费receipt，禁止D模型容器挂服务私钥；因无可消费来源/receipt，没有创建D public-only key副本。保留同一PG、新control/egress及所有历史卷/记录供主会话读取，arm不存在；旧历史C部署未改。**到此停止来源网络动作；provider/Tavily=0，后续诊断/任何新授权须由主会话另行决定，不能自动重试。**

## 失败后的有界非HTTP定位（主会话另行明确准许；没有补抓）

在**同一实际egress容器、非root65534/CapEff=Bnd=0/NoNewPrivs**下，每阶段仅调用一次；内部阶段上限≤8秒，非root外层9秒TERM/1秒kill上限。每阶段开始前写一次性marker；没有C grant请求、没有HTTP HEAD/GET/任何HTTP请求字节、没有proxy/CA豁免/环境放宽/规则修改。诊断前后IPv4/IPv6 OUTPUT DROP精确规则、B/C public pins保持，arm始终不存在；spent attempt没有被重开。

| 实际阶段 | 本轮测量结果 | 可支持的结论 |
|---|---|---|
| 当前镜像 `PublicDnsResolver.resolve`（真正system `getaddrinfo(AF_UNSPEC, SOCK_STREAM, IPPROTO_TCP)`，一次调用覆盖A/AAAA） | **7.431 ms**；A=`194.195.208.62`，AAAA为空，1个合格地址 | 此刻不是系统DNS解析卡死；未换resolver或缓存mock |
| B独立signer真实nonce挑战＋固定公钥验签 | **5.715 ms**；128字符signature验证通过，一次nonce | 此刻Unix签名路径、namespace/policy检查正常；没有C grant |
| 固定公网IP:443纯TCP后真实TLS，SNI=`www.sqlite.org`，默认CA `CERT_REQUIRED/check_hostname=True` | TCP **6.614 ms**；TLS完成总计 **1954.364 ms**，TLSv1.3，peer匹配固定IP、证书校验通过 | 不是把TCP通当TLS通：实际完成了校验证书的TLS握手；程序没有write/drain/HTTP parser/body read |

TLS公开证书SHA-256为 `5cb2703599be05409718b2c202497e017455a861f29269797e3be69bc2d52310`；不是来源body hash。握手之后仅close，不发送HTTP。

### 能收敛到哪里，不能冒称什么

- 当前诊断未复现**持续性DNS/B signer/TLS卡死**，三阶段合计约2秒；因此不支持为了修复此失败继续盲目延长DNS/TLS timeout或放松证书/egress。重点嫌疑已转为**HTTP响应首部等待、正文传输未在剩余期限内完成，或原请求时的瞬时延迟**。
- 被动读数：该新egress `eth0` 累计RX=1,531,112 bytes /1,341 packets，TX=60,418 bytes /854 packets；容器这段生命周期只做有限DNS/TCP/TLS探针和这一真实worker请求。这与大量响应数据已到达、但完整响应未在30秒内结束的推断相符，**比“只有TCP通”更有指向性**。然而它是网卡累计计数，包含TLS/链路/可能重传和诊断，**绝不是HTTP compressed/expanded body字节数**，不能用它认证gzip协商、完整page或准确吞吐。HTTP计数字段继续NULL。
- 现有受审worker只输出总括`fetch`阶段，不持久化“DNS完成/TLS完成/响应头完成/body进度”分阶段计数；无complete捕获，亦无transport-proof落库。虽然上述当前探针收敛嫌疑，**不能从事后探针严格证明原请求是在header还是body阶段超时，也不能完全排除当时暂态TLS延迟**。本轮不以再发HTTP来填这个证据洞。
- C实际permit发放次数与原捕获B nonce事件数**不可得**：control日志0行，egress仅1行`EGRESS_ATTESTOR_READY`；该固定部署无per-grant/nonce持久事件或安全计数端口。只读源码可见C `_permits/_issued` 与B `_seen_nonces`为进程内短效状态；没有做会暴露签名私钥的进程内存/ptrace检查，更没有额外C grant探测。不能把预期“两次grant”写成已观测实际次数。本轮新B诊断nonce=1、C grant=0有独立调用记录。

后续如需精确根因，应由owner先**离线**加入安全的阶段码/耗时/限定Content-Encoding和已读字节计数、分别模拟慢TLS/慢首部/慢body及取消，独立审查后再由主会话决定任何新live授权；这不是本次自动重试许可。本代理不改app、不再做DNS/TLS/HTTP探针。诊断文件：`live390-nonhttp-diagnostics-20260928.py`、三组 `live390-diagnostic-{dns,signer,tls}-{started,result}-20260928.json`、`live390-nonhttp-passive-audit-20260928.json`、汇总 `live390-nonhttp-diagnostic-summary-20260928.json`。

## 后续唯一HEAD诊断及最终阶段交接（依据现有回执补录，不再联网）

主会话在上述非HTTP诊断结束后，**另行明确批准一次HEAD而非GET**，仅用于检查响应首部；它不是registered capture，不使用C grant、不读body、不入池。实际回执本地时间为2026-09-28 01:09:24–01:09:25 +08；同一固定egress、同一非root/零capabilities、固定公网IP、真实SNI/默认CA校验、保持DROP规则。请求为精确SQLite SELECT URL的HEAD，带`Accept-Encoding: gzip`；总限时8秒（外层9秒TERM/1秒kill）、首部16KiB上限、无redirect/retry。仅读取到首部结束，未读取正文；使用一次新的B本地签名挑战验证当前egress，没有请求C grant或写DB。

| 本次唯一HEAD可返回字段 | 实际值 |
|---|---|
| status | **200** |
| Content-Length | **2,033,807 bytes** |
| Content-Encoding | **null：响应未提供该字段** |
| time-to-header（含该次TCP/TLS） | **901.178 ms** |

证据：private目录 `live390-single-head-diagnostic-20260928.py`、`live390-single-head-started-20260928.json`、`live390-single-head-result-20260928.json`。未保存完整响应headers或body。`Content-Encoding=null`说明这次HEAD没有声明压缩编码（可描述为未编码/identity元数据），**不是远端明确返回了字符串identity，也不是此前GET实际Content-Encoding的证据**。带gzip请求不保证服务端采用gzip。

### 合并诊断结论（事实与推断分开）

- **已观察事实**：唯一纠正registered尝试在30秒fetch deadline失败并终态unknown；之后一次系统DNS为7.431ms、一次B nonce验签为5.715ms、一次真实TLS握手约1.954秒且证书通过；另获准一次HEAD在约0.901秒返回200及2,033,807字节长度、无Content-Encoding。当前非HTTP前置及HEAD首部路径均可快速完成。
- **有依据的下一排查方向**：完整大响应的传输/读取预算相对30秒偏紧，比持续性DNS/签名/TLS/HEAD首部卡死更值得优先关注；网卡累计RX约1.53MB亦与部分大响应传输相容。
- **尚未证明**：历史失败GET是否完整收到首部、当时Content-Encoding、各段耗时、已读压缩/展开正文的准确字节数，以及是否由慢body单独导致。事后HEAD和网卡计数不能补成历史body读数/完整capture，**不得写成“已证明历史body慢”**。C审核、admission、partial corpus和D真全链均仍未执行。
- **nonce/permit记录边界**：保留已有日志、public pins、metadata和诊断回执，不主动清理或重启；该部署没有历史per-grant/nonce持久事件接口，因此原抓取实际C permit数量/B nonce事件仍不可得。已知本地额外B挑战分别是非HTTP signer诊断一次、HEAD诊断前一次；都不是新增C grant。没有私钥/进程内存转储，不能承诺已有记录包含完整nonce历史。

### 主会话声明的下一阶段：仅规划交接，不是本代理现在可执行

主会话已透明声明拟提供**最后一个独立fetch credit**：同一original链总共最多**3次实际registered dispatch**，现有两条unknown均计作已花费；未形成attempt的同代误配dispatch不伪算成一次GET。下一credit不是用390撤销已消费授权：390 replacement已被真实派发且unknown，不可重新打开、撤销为未使用或改历史expiry。

按主会话转述，Pauli正在构建待审400显式allowance，关联**同一original unknown `0ffc109e-136b-4b99-b270-2896f8d92edd`＋最新已消费timeout `9ab67b2d-4d62-47be-8ae0-4df576b099e9`**，总数max3、仅一个allowance、不自动发grant；Pascal正在构建待审C-only deadline300秒/bridge completion360秒与安全progress计数，grant TTL4秒与B默认30秒不变。此处仅记录主会话的后续工作安排，**不声称patch已经落地/检查通过/获准live**。

交接目标仍为同一DB `aearn_rag260_c_d_live_repair_01a0e0c7`。最后实库核验是：两条terminal unknown、旧误配授权原350列不变、新列NULL、append-only撤销1条、授权2条；capture/review/admission/active均0，已移除arm。现有审计镜像4d756…不能假装包含后续400/300秒修复。下一operator阶段必须等最终补丁、独立检查及主会话**新的明确live批准**，重新确认已审镜像/源码/pins/当前授权后才讨论操作；不预先apply400/写allowance/新授权/arm。

**本次交接动作只有阅读现有本地回执和更新本报告；所有网络现已停止：不再HEAD/GET/DNS/TLS/B nonce/C grant，不触碰DB/旧行/容器状态，也不执行任何后续operator准备或真实模型调用。已有任务证据原位保留。**

## 13:49 +08 接续：live400/gen3 仅本地准备，仍未获独立复核与主会话live GO

替换先前错误模型中止的operator，先检查其r1镜像/脚本/只读回执，未重复早前GET、390或许可操作。r1固定镜像`sha256:6a12dd215b0c36f33e83eac946a0b516ce811c32c23e2c9fe728829bdb68951f`包含当时14个源码快照；准备期间发现并行owner把C bridge client的complete回合限时从2秒有界改为30秒，导致r1源码漂移。保留r1证据，停止其两个已启动的staging服务，不得再用于live。随后用原base、`--pull=false --network=none --no-cache`构建r2固定镜像`sha256:0103b7bce00513d954560e81c9228eafb24b1ac80acf93d5b69952107225c580`；14个文件逐项对宿主源码/镜像做hash验证，base layer 17→31、前缀相同，离线导入检查final allowance/C300/completion360/TTL4。13:49重新核算r2全部14项source drift=0；后来如果再变，重新构建/独立复核/新key pin，不能拿此快照冒充现行。

在**新且仅gen3-r2**卷/容器中，准备了egress config及固定root控制/worker config，没有arm。当前`aearn-d-live-repair-01a0e0c7-egress-gen3-r2`在external-v6网络、`...control-gen3-r2`与同一PG在internal网络；worker容器未启动。当前独立B公钥SHA-256=`810d7100477dbef24f1f62f530a1b774fee182ac6586b0592b44ae98772e0283`、namespace inode=`4026532793`、OUTPUT策略SHA-256=`15267f8c94cf1389005bf5406f106f2db09f99e1cc13243b5df27`，C公钥SHA-256=`9c4ce704bdd511086355350dcc704981f8e8d28b3abdb6cbe0c0e6d9582e5420`。两者仅对当前运行实例成立，重启即重pin。没有把历史C reviewer私钥复制/挂给D模型；原operator DSN卷仅控制端只读挂载。r1第一次signer缺显式default-off环境导致启动退出、另两个r1服务已停止，保留卷与容器作历史，不作为当前pin。

r2本地门禁实测：B精确IPv4/IPv6 OUTPUT DROP规则/摘要、公钥/Unix socket、无arm/egress秘密挂载；非root65534+supplementary23456、零CapEff/CapBnd、NoNewPrivs=1的worker前置identity/pin检查；11项禁止的TCP目标DROP计数均增长。门禁只做被拒TCP SYN，不对来源发HTTP或允许的443请求，不证明真实fetch。初次非root探测因Docker额外primary group失败，改为`setpriv`精确组/丢弃bounding caps通过；初次fe80探测缺link-local scope失败，补eth0 scope后11项通过，失败事实保留。专用脚本、配置、pin及状态在private目录`live400-gen3-operator-20260928.md`列明。

最新只读DB核验的DB时钟为**2026-09-28 05:43:22.803853 UTC**，同一`aearn_rag260_c_d_live_repair_01a0e0c7`、事务read_only=on；两条历史attempt仍unknown/DEADLINE_EXCEEDED，capture/review/admission/active=0，schema400 final allowance表不存在，原policy/root到期上界**2026-09-28 11:54:38.657105 UTC**。只读回执为`live400-gen3-readonly-after-staging-20260928.json`，结果有时间性，实施前须重查。**本接续：live schema写入0、allowance0、新注册dispatch0、worker0、来源HTTP0、模型/付费API0；独立审查及主会话新的明确live批准仍未获得。本代理不会进入授权、ARM、GET或C审核/准入。**

## 14:07 +08 主会话明确LIVE GO后唯一final dispatch实况（终态失败，停止）

主会话传达独立source codeGO并明确source-only live执行许可。实际执行前复核r2 14项镜像源码hash无漂移、control/egress镜像ID均为`sha256:0103b7bce00513d954560e81c9228eafb24b1ac80acf93d5b69952107225c580`且运行；重新执行静态B exact OUTPUT DROP、公钥/Unix socket、无arm及非root65534/补充组23456/零capability worker identity+pin门禁，均通过。未增加HEAD/TLS诊断或付费模型调用。

在同一`aearn_rag260_c_d_live_repair_01a0e0c7`库，以严格源文件hash固定的**完整41-fragment manifest（末尾400）两次独立事务bootstrap**通过；原两条attempt的to_jsonb SHA-256及旧两条授权的原列SHA-256逐次匹配，新增`explicit_followup_id=NULL`。随后在旧政策/root **2026-09-28 11:54:38.657105 UTC上界内**，登记generation3 exact新policy/root（相同SQLite SELECT URL、route.sql/sqlite-docs-v1/queries、supplementary_explanation、8MiB），通过正式`authorize_final_followup`登记**唯一**allowance`fe22de46-4e42-462f-9087-f2f945d26420`及授权`badfd787-1acf-4081-9a1c-28b35d87592e`，审批标识`aearn-development-20260927/main-20260928-final-single-fetch`，未撤销/重开已消耗的390授权。检查DB时钟、current policy/root/allowance/auth精确关联及两条原attempt仍不变后，创建一次root-only ARM。

**14:05:18 +08仅启动一次**固定r2 nonroot worker，dispatch=`c3cae434-cd25-47b9-b26a-1459e2dc3aa3`已由C control持久插入，累计exact registered dispatch=3。worker约一秒退出，安全输出为`WORKER_ONE_SHOT_DENIED stage=fetch code=EGRESS_UNVERIFIED fetch_stage=signature wire_bytes=0 content_length=unknown encoding=unknown`，exit=1。根据受审`safe_fetch.py`阶段顺序，它在B签名验证阶段、`connector.open`之前失败，未建立可证明的来源HTTP请求或取得body；不能把失败提升为FULL capture。错误码不能单独证明是B key、nonce、签名、时钟或DNS中哪一环，不另作网络诊断或补抓。

先以只读事务核验第三条是精确generation3/授权、`dispatched`、response bytes/hash NULL，capture/review/admission/active仍全0；再只对这条调用既有`mark_unknown(..., error_code='EGRESS_UNVERIFIED')`一次。终态同库3条attempt均`unknown`：前两条`DEADLINE_EXCEEDED`原内容hash不变；第三条`EGRESS_UNVERIFIED`，response bytes/hash NULL；allowance=1、authorization=3、revocation历史不变、capture/review/admission/active=0。源内容的compressed/expanded字节数未知，不能记0。没有调用自动SQLite审核（无settled capture）、没有生成review/准入/partial corpus、没有模型请求。

已记录`live400-{schema-applied,authority-result,pre-arm-result,invocation-started,worker-result,postworker-readonly,attempt-result,arm-retired,d-handoff}-20260928.json`及所有对应private脚本；`live400-d-handoff-20260928.json`明确blocked/null材料IDs。终态后安全移除spent ARM，**14:07:44 +08由本operator主动停止r2 control/egress**，保留卷/容器/旧源证据。主会话14:08看到仅PG运行是预期的主动停机，不是到期或意外崩溃。**不重启/复用旧pins、不第四派发、不换库重试、不合成质量回执；真实C→D全链未通过。**

### 14:15 +08 离线/只读签名阶段定位及通知时序纠正

失败当时应先即时通知主会话再查库；实际在14:05:19 worker结束后先进行了只读DB核验，直到后续催报才发第一条阶段消息，通知偏晚，已向主会话明确承认。14:07:44 control/egress的退出由本operator在第三attempt终态化、spent ARM移除后**主动执行docker stop**，不是到期或崩溃；没有blind restart。`wire_bytes=0`仅为worker安全进度字段，**不能单独证明网络上零HTTP**；代码阶段顺序显示错误发生在`connector.open`之前，但没有独立packet capture。

离线查现存安全logs：B signer只有`EGRESS_ATTESTOR_READY`，control无输出；B的`handle`对peer/receipt拒绝静默关闭，不持久记录拒绝谓词。Docker inspect：r2 signer和最终worker均`PidMode=""`，worker仅用`NetworkMode=container:<signer>`共享网络，**未共享PID namespace**。B `attestor.py:327-339`要求`SO_PEERCRED pid>0`且能stat同netns `/proc/<pid>/ns/net`；跨PID容器可映射pid=0，因而这是与快速签名失败相符的强嫌疑，**不是已观测实际peer pid的确证**。C单独处理pid=0不代表B已处理。离线只读卷核验B/C公钥与policy hash均吻合准备pin、B socket为root:23456/0660目录root:23456/0750、worker supplementary group配置`[23456]`，既有门禁当时通过；这不能补证明失败瞬间的每个谓词。整个worker不到1秒，4秒签名TTL没有收到过期receipt证据。DNS解析后的实际IP没有安全持久记录，DNS与固定IP不一致或其他签名端拒绝原因仍不能排除。先前成功signer-only诊断属于另一容器/启动配置，不能证明本轮worker PID拓扑。

只建议另获全新范围/额度且独立审查后，离线验证同时共享signer PID与network namespace可保留非root零capability、positive SO_PEERCRED PID和`/proc/<pid>/ns/net`检查；或单独评审B跨PID身份绑定方案，不能直接去掉netns核验。**本轮未修改源码、未重启、未加grant/nonce探测、未再发网络请求、未授权第四dispatch。** 详证仅在private `live400-offline-signature-analysis-20260928.md`与`live400-offline-pin-audit-20260928.json`；历史与安全日志原位保留。
