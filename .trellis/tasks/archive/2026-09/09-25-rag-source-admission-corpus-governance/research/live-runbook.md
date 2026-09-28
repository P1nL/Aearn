# C 唯一真实请求现场接线与停止点（2026-09-25 草案）

## 三个相互独立的边界

1. control 容器：只持专用 `aearn_rag260_c_*` PostgreSQL 凭据，不具备外网 GET 代码路径；以 `current_database()` 核对数据库；在已审核的 root-owned Linux named volume 中创建 Unix socket，并以 peer UID/GID、签名、nonce、exact dispatch/scope、短期 grant 与当前库事务裁决。先持久 dispatch 再允许出口。
2. egress 容器：不持 DB 凭据，独立网络 namespace 和只读应用/配置；B 独立 signer 在每次拨号前证明输出规则、命名空间、目的公网 IP 与 TLS 连接目标。OUTPUT 默认 DROP；唯一例外是获准 DNS TCP/UDP 53、目标已审核公网 IP TCP 443。IPv6 全部 DROP。worker 仅通过共享 Unix socket 向 control 申请权限/交回正文；绝不通 PG 或 Docker socket。所有有效结果与错误均不触发第二次目标 GET。
3. audit：二者镜像、来源和哈希、挂载属主、Capabilities、UID/GID、iptables/ip6tables 与内核/iptables 后端独立核对；先做出站负向探针（loopback/RFC1918/link-local/metadata、IPv6、PG）与目标目的端口规则审查，不向 SQLite 页面发任何探测 GET；再查许可证据、收据真实性、独立质量审查/保留清理。现场证明通过后才打开唯一一次 GET 的 dispatch。不能以控制容器请求页面、或让出口连私网 PG 替代。

## 非联网预检（不构成现场证明）

在 Docker Desktop Linux VM 内，用一次性 named volume 与两个 `--network none` 容器验证跨容器 AF_UNIX socket：非 root 客户端 UID/GID `65534:23456` 连接 root 服务端并收到了 `b'ok'`，客户端 `SO_PEERCRED` 看到服务端 `(pid,uid,gid)=(0,0,0)`；结束后容器与 volume 已清理。这只证明该环境能做 Unix socket IPC/peer 查询，不证明最终 root-owned mount、signer、防火墙、DB 权限或目标 GET。随后以第二个一次性 volume/`--network none` 双容器重跑，服务端 `SO_PEERCRED` 实测客户端 `(pid,uid,gid)=(0,65534,23456)`，客户端见服务端 `(0,0,0)`，收到 `b'ok'`，测试后容器及 volume 已清理。跨 PID namespace 得到的 pid=0 因此身份判断只能依赖已映射 UID/GID/路径/签名，不能坚持 `pid>0`；正式现场仍须用最终镜像和 mount 复测。

## 已发现的实现缺口

- C bridge 只有协议/离线 fake callbacks；host-side DB resolver、attestor proof verifier、settlement 正在实施，尚无端到端 Docker compose/live runner。
- B signer 已签 canonical Ed25519 receipt，但应用客户端过去只返回 bool；必须在真实 fetch path 保留签名 envelope，而非事后伪造。
- B launcher/镜像是一轮实验产物，不可因本机有 `aearn-rag-b-egress:local` 就认定其来源/iptables backend 已审核适合 C；Docker Desktop Linux VM 的 named volume socket、SO_PEERCRED、root owner、DNS 与两网络隔离也需现场核验。
- 任何桥、proof、质量、许可、保留或原子落库不就绪，唯一 GET 为 `not_executed`；不运行普通 curl/宿主机 GET，不重试。
