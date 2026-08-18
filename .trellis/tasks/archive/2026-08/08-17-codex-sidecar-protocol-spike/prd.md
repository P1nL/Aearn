# Codex Sidecar 协议可行性验证

## 目标

在不接入正式 Tutor Runtime、数据库 mutation 或 Desktop 的隔离环境中，证明 Aearn 能在 Windows 上可靠托管 `codex app-server --stdio`，并以自定义 provider 调用精确模型 `deepseek-v4-flash` 的 Responses 路径，完成 thread/turn/item、dynamic tools、错误回灌、interrupt 和崩溃收口验证。最终产出明确 Go/No-Go，作为后续所有 child 的前置条件。

## 依赖

- 父任务：`08-17-codex-runtime-sidecar-integration`。
- 无实现依赖；必须读取父任务 `research/codex-app-server-contract.md` 与 `research/aearn-integration-seams.md`。
- 兼容性决策已于 2026-08-18 确认：`deepseek-v4-flash` + Responses 是 mandatory Go 条件，不能用 OpenAI 模型、其他 DeepSeek 模型或 Chat Completions 代替验收。

## 需求

### R1：版本、协议与 DeepSeek 能力探测

- 解析 `codex --version`，记录 binary path、version 和 protocol compatibility 结果。
- 启动 app-server 后完成 initialize；检查必须的 thread/turn/item、experimental dynamic tools 和自定义 model provider 表面。
- 通过隔离 Codex Home 配置 `model_provider = "aearn_deepseek"`、`model = "deepseek-v4-flash"`、`wire_api = "responses"`、`requires_openai_auth = false`，API key 仅通过环境变量提供。
- Responses streaming、tool call、tool result continuation、terminal status 任一核心协议不兼容时返回稳定 No-Go，不尝试宽松猜测协议。
- 禁止为了通过 spike 改用 OpenAI 模型、其他 DeepSeek 模型、Chat Completions 或 provider/model/protocol fallback。

### R2：隔离状态与认证

- 使用测试专用 Codex Home/working directory；不写入仓库和用户全局 sessions/memory。
- 验证自定义 DeepSeek provider readiness、API key 环境变量存在性和目标模型配置；不打印、复制或持久化 credential。
- fake provider 自动化不需要真实 API key；任何真实 `deepseek-v4-flash` provider smoke 在执行前仍需单独获得明确批准。

### R3：stdio JSON-RPC

- Python spike client 支持 request/response、notification、server request、超时、取消和 stderr 分离。
- stdout 只接受 JSON-RPC；日志走 stderr 并执行 redaction。
- 未知通知可忽略并计数，未知 server request fail closed。

### R4：DeepSeek 工具恢复

- 注册至少一个 typed dynamic tool，并通过 fake DeepSeek Responses fixture 验证协议形状。
- 在获批的真实 smoke 中，第一次返回 safe `repairable_invalid`，`deepseek-v4-flash` 必须在同一 Turn 内重新调用并成功。
- 证明工具错误不等于 failed turn；同时验证 fatal/tool timeout 会产生明确失败。
- 若真实模型不能稳定产生 typed tool call 或不能根据 repair result 继续同 Turn，则 DeepSeek 路径为 No-Go。

### R5：中断与崩溃

- 验证 `turn/interrupt` 最终收到 interrupted。
- 验证 app-server child 异常退出、协议损坏和总超时均被宿主检测并终止，不悬挂进程或等待线程。
- DeepSeek provider timeout、stream 中断和不符合 Responses contract 的事件必须转换为可区分安全结果。

## 范围外

- 修改正式 API、DB、Tutor worker、LearningPlan 或 Desktop。
- 长期 supervisor、生产 feature gate、真实用户会话迁移。
- 安装、升级或修改用户 Codex 配置。
- 将其他 DeepSeek Chat Completions 模型作为本路线的兼容目标。
- 用 OpenAI 模型成功结果替代 DeepSeek Go 证据。

## 验收标准

- [ ] fake app-server 与 fake DeepSeek Responses fixture 可确定性覆盖 request、notification、server request、stream、tool call、timeout 和 child exit。
- [ ] 固定目标 binary 完成 initialize/version/custom-provider/capability preflight。
- [ ] 隔离 Codex Home 的有效配置精确选择 `deepseek-v4-flash`、Responses 和非 OpenAI auth，secret 仅来自环境变量。
- [ ] typed dynamic tool 能接收结构化参数并返回结果。
- [ ] 获批真实 smoke 证明 `deepseek-v4-flash` 在收到 `repairable_invalid` 后于同一 Turn 重新调用并最终完成；若用户未授权 smoke，结果必须记为 `not_run_requires_approval`，不得给出最终 Go。
- [ ] interrupt、fatal tool result、provider stream failure 和 child crash 分别产生可区分结果。
- [ ] 测试/日志不包含 raw prompt、完整模型回复、API key、access token、auth 文件或全局 Codex session 内容。
- [ ] 不发生 OpenAI 模型、其他 DeepSeek 模型或 Chat Completions fallback。
- [ ] `research/result.md` 给出 DeepSeek-specific Go/No-Go、Codex/协议/模型版本、剩余风险和 Child 2 前置条件。
