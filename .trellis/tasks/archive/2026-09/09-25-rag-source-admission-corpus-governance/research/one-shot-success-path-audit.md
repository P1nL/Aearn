# 一次性来源抓取成功路径专项审查

日期：2026-09-25。6 Sol 静态审查，主会话复核；没有真实请求、数据库修改或 live 容器重启。

## 结论

未发现可证实的、必然阻止合规完整 HTTP 200 响应结算的代码不兼容，也未确定历史失败根因。不能因此声称远端响应符合当前约束。

- worker 使用两次 grant、单次完整 fetch、零重定向和压缩/展开各 1 MiB 上限（`aearn/infra/rag-c-live/worker_once.py:305-340`）。SafeFetcher 在拨号前重验 grant 与 B proof 期限，并检查状态、类型及正文大小（`aearn/services/api/app/services/grounding/autonomous/safe_fetch.py:320-425`）。
- 连接器接受带 Content-Length 或 chunked framing 的 HTTP/1.1 响应，同时检查 TLS 和 pinned peer（`aearn/services/api/app/services/grounding/autonomous/pinned_tls_connector.py:108-227`）。没有历史响应头，不能将特定协议差异当作已证实根因。
- 1 MiB 正文的 base64 最多 1,398,104 bytes，请求帧上限 1,410,000；其余 metadata/proof 仍须共同满足帧上限，proof 自身另有 2,048-byte 上限。未发现本轮精确短 URL/scope 的必然溢出证据（`aearn/infra/rag-c-source-control/client.py:199-213`、`aearn/infra/rag-c-source-control/server.py:164-278`）。
- report、nonce、签名、peer 和 DB scope 的逐层绑定以及原子结算在静态路径上相容（`aearn/services/api/app/services/grounding/autonomous/registered_source_bridge_host.py:167-259,311-332,391-495`）。现有合成 fixture 不等于真实200响应复现。

## 未知项与边界

原尝试只有总括错误码。目标443的15包/2565 bytes不能证明TLS完成、GET已发出、收到200或已进入结算。慢响应、过期proof、非支持framing或超限等均只是可能的拒绝条件，不是已确认根因。新诊断镜像只能解释未来获准执行，不能追溯还原历史失败，也不能据此重新派发。
