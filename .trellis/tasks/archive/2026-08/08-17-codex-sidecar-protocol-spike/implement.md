# 实施计划

1. 创建测试专用 spike 模块、fake app-server fixture 与 fake DeepSeek Responses fixture。
2. 实现 executable/version、initialize、custom provider 和 dynamic tools capability probe。
3. 实现 isolated Codex Home builder，固定 `deepseek-v4-flash`、`wire_api = "responses"`、`requires_openai_auth = false` 和环境变量认证。
4. 实现 stdio JSON-RPC client、server request、stream event 和 shutdown。
5. 添加 typed dynamic tool repair/fatal/timeout 场景。
6. 添加 DeepSeek Responses invalid event、provider timeout、interrupt、child exit、invalid JSON 和 unknown method 测试。
7. 在不调用真实 provider 的情况下运行全部 fake/contract 自动化；OpenAI 对照结果不得计入 Go。
8. 向用户展示真实 `deepseek-v4-flash` smoke 的模型、调用次数上限、隔离 Home、数据和日志边界；获得单独授权后执行。
9. 写 `research/result.md`，给出 DeepSeek-specific Go/No-Go；未授权或未执行真实 smoke 时写 `not_run_requires_approval`，不允许启动 Child 2。
10. 运行 focused pytest、ruff、mypy、Trellis validate 与 `git diff --check`。

## 回滚

该 child 不接正式 Runtime。失败时删除隔离 spike 代码/测试即可；不修改 DB 和产品 feature。DeepSeek No-Go 时停止父任务后续 children，不用 OpenAI 或 Chat Completions 继续正式路线。
