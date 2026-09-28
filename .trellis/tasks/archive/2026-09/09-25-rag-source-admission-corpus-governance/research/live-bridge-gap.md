# C 真实现场接缝：隔离出口与当前 PostgreSQL 权威

- 已实现的 B 临时出口证明要求 egress network namespace 不能向任何 loopback/私网/metadata 建 TCP；C 的新注册源 `RegisteredSourceHopPolicy` 又要求每次 DNS/拨号前从现行 DB 策略和一发即锁的 attempt 获取 fresh grant。不能为方便连库就在该 namespace 放行 Aearn PG 私网 IP，否则私网阻断证明失效。
- 正确分层候选：可信控制进程位于另一个可访问**仅隔离 C 测试库**的 Linux 容器/namespace，egress worker 仅通过挂载的 root-owned Unix socket 请求 exact scope/dispatch 的短时 grant；控制进程从 PG 重读并签名，socket 客户端核验 peer/签名/nonce/范围。桥只回答权限并接收有界完成证据，不转发任意 TCP/HTTP；egress firewall 仍仅放行目标公网 IP:443 与 DNS。
- B `SafeFetcher.consume_live_receipt` 是进程内一次性对象，不能把 Python 对象跨容器当真凭据。真实 C capture 必须经受审查的跨进程完成 envelope：同一批准 scope/dispatch、单 hop/final URL、body <=1MiB、sha256、TLS/peer、已有 signed egress attestation、worker 身份；控制端重核现行 DB 后在专库提交。进程/签名/容器限制不构成恶意 worker 代码的完全证明，需在 live 报告中写明信任边界。
- 这是实施中发现的实质接线复杂度，单纯的离线 fake resolver、直接宿主机 GET、允许 egress 连 PG，或预填 body 均不能声称真实端到端通过。当前没有进行本 C 目标 GET，也没有改变防火墙/生产网络。若控制桥无法建立或独立验证，按 PRD `not_executed`，不能通过重试或降级绕过一次 GET 上限；现场前需重新向用户展示具体双容器隔离接线供确认。
