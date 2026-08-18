# 协议验证基线

实施前必须读取：

- `../08-17-codex-runtime-sidecar-integration/research/codex-app-server-contract.md`
- `../08-17-codex-runtime-sidecar-integration/research/aearn-integration-seams.md`
- `../08-17-codex-runtime-sidecar-integration/design.md`

固定开源基线为 `openai/codex@c6058ccaa91ab17159cf805bf4d6d4edd87fe5fc`；本机目标binary为 `codex-cli 0.142.0-cometix`。两者不等价，result必须分别记录源码协议预期与本机实测。

验证输出只能保存版本、capability、状态、次数、hash、耗时和安全错误码；不得保存credential、raw prompt、raw response、reasoning或全局Codex会话内容。
