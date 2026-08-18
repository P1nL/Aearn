# DeepSeek 目标兼容性决策

## 决策

用户于 2026-08-18 确认：Child 1 必须以精确模型 `deepseek-v4-flash` 的 Responses 路径作为 mandatory Go/No-Go 验收目标。

不得使用以下结果替代：

- OpenAI 模型成功；
- 其他 DeepSeek 模型成功；
- DeepSeek Chat Completions 成功；
- provider、model 或 protocol 自动 fallback。

## 当前 Aearn 证据

- `aearn/services/api/app/core/config.py:9-15` 定义 `deepseek-v4-flash` 及其预算常量。
- `aearn/services/api/app/core/config.py:349-353` 对该精确模型启用 Responses 路径。
- `aearn/services/api/app/services/llm/llm_client.py:84-95` 只为该精确模型选择 `DEEPSEEK_RESPONSES`，其他 DeepSeek 保持 Chat Completions。
- `aearn/services/api/app/services/llm/llm_urls.py:35-38` 构造 DeepSeek `/responses` endpoint。

## Codex 约束

Codex 自定义 model provider 可以配置 base URL、环境变量认证、wire API 和非 OpenAI auth。由于 Chat Completions 已进入弃用路径，本路线只接受 Responses 作为正式 DeepSeek sidecar 协议。

## 证据门

fake fixture 只能证明协议实现，不能证明真实模型行为。最终 Go 必须包含经用户单独授权的真实 `deepseek-v4-flash` tool-repair smoke；未授权或未执行时记录 `not_run_requires_approval`，Child 2 保持阻塞。
