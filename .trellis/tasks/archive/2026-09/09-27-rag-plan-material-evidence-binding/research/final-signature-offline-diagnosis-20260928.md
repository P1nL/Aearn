# live400 最终签名阶段离线诊断（2026-09-28）

范围：只读代码/已保存证据及一次新建隔离 Unix `SO_PEERCRED` 实验。没有调用真实 B signer nonce、C grant、DNS/来源 HTTP、live DB 或模型；没有代码修改或重试授权。原链三次 dispatch 已用尽，末次 `unknown/EGRESS_UNVERIFIED`，不得通过第四次派发或新授权机制绕行。

## 已证实的路径与边界

- `live400-worker-result-20260928.json` 记录 `stage=fetch code=EGRESS_UNVERIFIED fetch_stage=signature wire_bytes=0`；`live400-attempt-result-20260928.json` 记录累计三次、第三次 unknown、capture/review/admission/active 均为零、模型调用零。`worker_once.py:369-390` 的 stage/progress 是安全摘要，异常原始 cause 不打印。**不能单凭 wire_bytes=0 断言历史上未发送 HTTP**；就末次本进程而言，当前代码在 `safe_fetch.py:356-380` 先做首个 C grant→DNS→签名→第二个 C grant→`connector.open`，所以签名处抛出的此次调用尚未到本进程 TLS/HTTP 连接代码。无法据此否认前两次 unknown 尝试可能有过网络发送。
- `safe_fetch.py:360-377` 中签名阶段的 `EGRESS_UNVERIFIED` 来源：C 注册路径的 egress 类型不符、`attest_envelope` 抛错/返回错误类型，或收到签名后第二次 C grant 耗尽 4 秒 TTL，`pre_dial_unix_ms >= expires_unix*1000`。第二次 C grant 本身拒绝会是 `PROBE_POLICY_DENIED`，不是这个代码；DNS 公网校验失败在 `signature` progress 之前，通常为 DNS/地址错误。C worker 构造真实 `LiveEgressAttestor` (`worker_once.py:329-348`)，故类型不符仅是一般代码路径，不是当前最优先解释。
- `live_egress.py:75-143` 将一切同步/异步异常压为同一 `EGRESS_UNVERIFIED`：不合法 host/IP、worker UID/组、socket 或父目录 owner/mode、netns inode 读取、Unix 连接/写/读各 1 秒超时、空/超长/畸形回复、request 字段/隔离标志/整数 expiry 时间窗不符、Ed25519 不匹配或过期。B signer `attestor.py:279-360` 在 request deployment/namespace/policy/host-IP allowlist/nonce 不符、`_rules()` 与启动时 policy bytes 不同、nonce 重用、`SO_PEERCRED` 拒绝时直接不回签名，且不记录具体谓词。实际 pin/权限的已保存审计匹配（`live400-offline-pin-audit-20260928.json`），但不能回溯证明本次每个实时谓词；DNS 返回的 IP 未留痕，是否等于唯一白名单 IP 仍未知。
- B 的 `peer_allowed` (`attestor.py:327-339`) 明确要求 `pid>0`、精确 UID/GID 与 `os.stat('/proc/<pid>/ns/net').st_ino == self.namespace`；仅共享 network namespace **不保证**跨 PID namespace 的 SO_PEERCRED PID 在 signer 可见。既存操作员只读 Docker 证据称末次 worker/signer `PidMode=""`、network 共享；本 sidecar 未重复 Docker/live 服务调查，因此历史 peer PID **未观测，原因仍是强假设而非定论**。

## 单次本地无网络复现

使用已 pin 的 r2 image `sha256:0103…c580`，仅新建 `aearn-peercheck-20260928-01a0e6a2-server` 容器和 `…-sock` 空 socket 卷；服务端 `--network none`，两个一次性非 root 客户端均 `--network container:<server>`（共享该 **none** netns），均 `--cap-drop ALL --security-opt no-new-privileges --read-only`，只运行 Python stdlib AF_UNIX socket，UID/GID 65534。没有挂真实 socket、密钥或来源配置，也没有外部网络/DB。实验输出：

| 客户端 PID 模式 | signer 端 `SO_PEERCRED` | `/proc/<pid>/ns/net` 比较 | B 谓词 |
| --- | --- | --- | --- |
| 默认独立 PID | `pid=0 uid=65534 gid=65534` | false | false（**pid>0 已失败**） |
| `--pid=container:<server>` | `pid=13 uid=65534 gid=65534` | false | false |

首轮 cap-drop ALL signer 的共享 PID 后半谓词仍为 false，但该轮把 `/proc` 的 `OSError` 合并，不能据此判断是权限还是 inode 不同。下方补充实验已用生产相关的 root signer `NET_ADMIN`/`SYS_PTRACE` 能力进一步判别。两轮实验容器和 socket 卷均已按精确名称删除；忽略目录 `.runtime/rag-d-live-repair-01a0e0c7/peercheck-20260928/` 仅保留无密钥短脚本。

## 漏检与最小方向（未实施）

- `live400-gen3-isolation-gates-20260928-r2.py:36-67` 核对静态 pins、socket 存在、非 root、netns、capabilities；`negative_only` 只测 DROP。`live400-gen3-prep-20260928-r2.py:67-139` 校验公钥/规则摘要并生成 config；都不作为真实非 root worker 请求一个 B 签名，也不测试 signer 对该 worker 的 `SO_PEERCRED`。现有 `test_attestor.py` 在同进程 mock `getsockopt/os.stat`，`test_rag_b_live_egress.py` 和 `test_rag_c_signed_egress_proof.py` 用 fake Unix reader/writer 签名，验证协议拒绝而不是 Docker sibling PID/proc 的功能性签名。故全部静态 gate/test 通过仍可能在第一次真实签名时卡死。
- **最小部署/预检建议（未实施）**：在将来独立获准且有合法额度的新隔离部署中，worker 启动同时指定现有 signer 的 `--network=container:<signer>` 与 `--pid=container:<signer>`；保留非 root 65534、零 CapEff/CapBnd、NoNewPrivs、原 socket/镜像/政策 pins 和 4 秒签名 TTL。部署前在同一镜像、UID/GID、实际能力与挂载拓扑下，用独立无密钥 Unix 测试 socket 检查 signer 看到 `SO_PEERCRED pid>0,uid/gid=65534`、`/proc/<pid>/ns/net` 与自身 inode 精确相等，并记录安全 errno；该预检不能借真实 B nonce、C grant 或现有已耗尽链执行。B signer 若生产配置原本带 signer-only `SYS_PTRACE`，维持其经审阅配置；**不要给 worker 加权限、不要为本问题另给 signer 新权限，也不删除 `pid>0`、UID/GID/netns 核验**。仅加 PID 拓扑仍需验证真实签名闭环与 DNS 白名单 IP；本实验既不证明历史根因唯一，也不授予第四次派发。

## 补充判别实验：同网不同 PID vs 同网同 PID（本链无访问）

仅新建 `aearn-peercheck-20260928-01a0e6a2-v2-server`、同名前缀 socket 卷及两个 `--rm` 客户端，均基于上述 r2 image。服务端 `--network none`、UID/EUID 0，`--cap-drop ALL --cap-add NET_ADMIN --cap-add SYS_PTRACE --security-opt no-new-privileges --read-only`；客户端通过 `--network container:<server>` 共享仍然封闭的 none netns，UID/GID 65534、capdrop ALL、NoNewPrivs=1。此 signer 能力组合对应已记录的 signer-only `SYS_PTRACE` 和设置 OUTPUT DROP 所需 `NET_ADMIN`；**没有从旧 live 容器重新读取其实际 CapEff，故不把本实验称为旧实例能力的直接观测**。脚本仅读写独立 socket 和自身 `/proc`，不导入/运行 B signer、不触发真实挑战；服务端捕获 `SO_PEERCRED`、`/proc/<peer_pid>/ns/net`、errno、双方 netns、身份和 dumpable。

服务端自身：UID/EUID=0，CapEff=CapBnd=`0000000000081000`（NET_ADMIN+SYS_PTRACE），NoNewPrivs=1，`PR_GET_DUMPABLE=1`，`yama/ptrace_scope=1`，netns inode=`4026532641`。两名客户端 `PR_GET_DUMPABLE=1`，UID/GID 四元组皆 65534，CapEff=CapBnd=0，NoNewPrivs=1；客户端自读 netns inode 同为 `4026532641`。

| 无外网客户端拓扑 | signer 端 `SO_PEERCRED` | signer 访问 `/proc/<pid>/ns/net` | B `peer_allowed` 的完整布尔表达式 |
| --- | --- | --- | --- |
| 共享 netns，独立 PID ns | `pid=0, uid=65534, gid=65534` | `/proc/0/ns/net`: `FileNotFoundError`, errno **2**，`/proc/0` 不存在 | **false** |
| 共享 netns，`--pid=container:<server>` | `pid=12, uid=65534, gid=65534` | `stat` 成功：peer inode **4026532641** = signer inode **4026532641**；`stat_error=null`，peer `/proc` 的 UID/GID 与 client 匹配 | **true** |

这在给定隔离拓扑和生产相关 signer 能力下**消除了共享 PID 实验的“权限拒绝还是 inode 不同”歧义**：没有 PermissionError，且 inode 实际相等；独立 PID 的确切阻断是 peer PID=0，强行 stat `/proc/0` 则 errno 2。但旧 live worker 的实际 `SO_PEERCRED` 没被记录，DNS 可能与白名单不符，签名器实际 CapEff 的当时快照也未由本 sidecar采集；不能把复现偷换为已证明历史单一根因。复现实验容器/卷已核验名称后删除；无新网络/DB/授权/密钥/来源请求。脚本保留于前述本地忽略目录。
