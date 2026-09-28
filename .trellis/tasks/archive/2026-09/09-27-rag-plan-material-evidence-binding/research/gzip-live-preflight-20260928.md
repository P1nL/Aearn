# C full GET gzip 传输预检（仅离线实现）

## 背景及边界
既有真实 C one-shot 在 10 秒 fetch deadline 内 `DEADLINE_EXCEEDED`；既有记录不能判定 HTTP GET 是否发出或完成，capture/review/admission 仍为 0。此改动只协商受支持的 gzip，不把慢来源换成 curl，不重试旧 dispatch，不扩大 deadline、正文 8 MiB 双限额、来源许可或用途，也不声称真实 C+D 验收通过。

## 改动
- `SafeFetcher(request_gzip=False)` 默认维持 B 请求；只有精确 `RegisteredSourceHopPolicy` 的 full GET 可选择 `Accept-Encoding: gzip`。C 仍为单 URL、零重定向、两次当前 grant、签名 egress、pin TLS。C worker one-shot 显式 opt-in；HEAD/range 无法走 C full-only scope。
- 连接器仅在无 Range 的 GET 接受精确 `accept-encoding: gzip`，发送的 wire header 与 `sent_headers` 一致；Range 仍只能 identity，HEAD 和其他任意字段在 dial 前拒绝。
- 完整正文仍先在 wire 层受独立 compressed cap，再由既有流式 gzip decoder 受 expanded cap；不完整、追加第二 member、炸弹和长度不符均拒绝，不返回部分 full body。SHA-256 与 capture body 为完整解码后的实体，wire_bytes 单独记录压缩字节数。默认超时与上限未改。

## 离线验证与后续
`uv --directory .\aearn\services\api run pytest -q ..\..\infra\rag-c-live\tests\test_worker_once.py tests/grounding/test_rag_b_safe_fetch.py tests/grounding/test_rag_b_pinned_tls_connector.py tests/grounding/test_rag_c_registered_source_policy.py`：141 passed、24 subtests。相应 Ruff 全过；`git diff --check` 无空白错误。测试使用假 TLS/authority/响应，无 DNS、GET、provider、DB 或费用调用。

主会话须独立审阅 diff，重建并 pin 新 worker 镜像与代码哈希，确认新的有效 C 授权及隔离环境后才能考虑一次受控真实 fetch；先前 unknown 和不可重放的授权不可修改/复用。若服务器不返回 gzip 或仍慢，此改动不会保证成功；严格门禁与来源缺口继续保留。
