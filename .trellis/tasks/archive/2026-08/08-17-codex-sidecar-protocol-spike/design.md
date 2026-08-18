# 技术设计

## 设计目标

用最小 Python harness 验证 Codex App Server 与 `deepseek-v4-flash` Responses 的真实兼容性，不提前形成正式 Runtime 架构债务，也不允许用其他模型成功掩盖 DeepSeek 不兼容。

## 组件

~~~text
CodexSpikeRunner
  -> CodexExecutableProbe
  -> IsolatedCodexHomeBuilder
  -> JsonRpcStdioClient
  -> DynamicToolTestHost
  -> FakeAppServerFixture / FakeDeepSeekResponsesFixture
  -> optional real deepseek-v4-flash
  -> SanitizedEvidenceWriter
~~~

### `IsolatedCodexHomeBuilder`

生成临时、Git 外的最小配置：

~~~toml
model = "deepseek-v4-flash"
model_provider = "aearn_deepseek"

[model_providers.aearn_deepseek]
name = "Aearn DeepSeek"
base_url = "<operator-provided DeepSeek base URL>"
env_key = "DEEPSEEK_API_KEY"
wire_api = "responses"
requires_openai_auth = false
~~~

配置构造器不读取或复制用户全局 `auth.json`、sessions、memory、plugins 或 provider token。结果证据只记录配置指纹和 readiness 布尔值。

### `JsonRpcStdioClient`

- async subprocess，stdin/stdout/stderr 分离；
- 单调 request id 和 pending future map；
- reader task 区分 response、notification、server request；
- bounded line size、JSON parse 和 method allowlist；
- timeout 时发送 interrupt 或终止 child；
- shutdown 先请求取消，再关闭 stdin，最后终止 process tree。

### 测试工具

工具输入为 `attempt` 与一个 bounded string。第一次返回 `repairable_invalid`，第二次返回 `completed`。工具不访问 DB、不执行命令、不使用路径或 secret。

## 测试层级

1. 纯 fake app-server protocol 单测：不调用模型。
2. fake DeepSeek Responses contract：验证 stream/tool-call/tool-result 形状和错误映射。
3. 本机 app-server + isolated custom provider handshake：不要求生成完整学习回答。
4. opt-in real `deepseek-v4-flash` recovery smoke：另行授权，只输出布尔 rubric、opaque id hash、状态和耗时，不输出正文。

OpenAI 模型可以用于开发期对照定位“Codex 协议问题还是 DeepSeek provider 问题”，但其结果不能计入验收，也不能把 DeepSeek No-Go 改写为 Go。

## Go 条件

最终 Go 必须同时满足：

- 固定 Codex binary/revision 在 Windows stdio 下稳定；
- isolated custom provider 精确选择 `deepseek-v4-flash` + Responses；
- DeepSeek Responses stream 能被 Codex 解析为完整 turn/item 生命周期；
- dynamic tool 能收到 typed input 并返回 structured result；
- 真实模型在 `repairable_invalid` 后能继续同 Turn 并成功；
- interrupt、timeout、provider stream failure 和 child crash 可被 Aearn 收口；
- 不产生 secret/raw output/global Codex state 污染；
- 不发生 model/provider/protocol fallback。

以下任一技术失败为 No-Go：目标模型/provider 不可用、只支持 Chat Completions、dynamic tools 不可用、同 Turn repair 不成立、Windows child 无法可靠终止，或者无法保证 redaction。真实 smoke 未获授权或尚未执行时状态为 pending approval，不是 Go，也不是技术 No-Go。
