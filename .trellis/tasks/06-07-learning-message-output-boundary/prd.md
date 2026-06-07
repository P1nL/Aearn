# Harden learning message public output boundary

## Goal

为学习页模型回复建立明确的公开输出边界，降低模型把内部策略、自检字段或类似思考文本写进 Agent 正文的概率，同时保留当前 SSE 流式体验。

本任务是第一阶段，只处理：

- 减少 prompt 中容易被模型复述的内部策略表达。
- 让学习消息使用统一的结构化输出 envelope。
- 后端只向前端公开 `public_message`。
- 保留并强化 guardrail 作为最后一道兜底。

本任务不通过前端猜测或正则拆分普通正文，也不向用户展示 raw chain-of-thought。

## Confirmed Facts

- 当前学习消息同时支持 OpenAI Agents SDK 和 DeepSeek direct Chat Completions。
- 两条路径当前都向服务层返回自由文本 delta。
- SSE 路由会对累计文本执行 guardrail，然后立即发送 `agent_message`。
- provider 单独返回的 `reasoning_content` 不会被当前 parser 当作正文。
- 用户截图中的 `_policy...符合policy要求` 是模型写入正式 `content` 的内部策略泄漏，不是后端主动渲染独立 reasoning 字段。
- 当前 prompt 的用户 JSON 明确包含 `response_policy.stage_strategy` 等内部控制字段，增加了模型复述内部策略的诱因。
- 当前 API 仍需保持 `agent_message.content`、工具调用、幂等回放和 SSE 基本事件顺序兼容。

## Requirements

### 1. Generic prompt boundary

- 学习导师 system prompt 保持跨知识点、跨语言、跨阶段通用，不为 `_policy` 等单次泄漏词编写业务特化流程。
- 不允许仅把 `response_policy` 重命名成另一个同义 JSON 字段作为修复。
- 后端应把阶段策略、追问预算、答案请求处理和练习解锁约束编译为内部 typed directive，再渲染进模型 instructions。
- 用户消息 JSON 只包含生成教学回复所需的学习事实，不包含 `response_policy`、`stage_strategy`、`forbidden_outputs`、`allowed_outputs` 等内部策略结构。
- 模型仍可获得完成当前阶段回复所需的约束，但不应看到内部策略对象、字段名或策略解释。

### 2. Structured model output

- 所有学习消息阶段使用同一个版本化结构化输出 envelope：

```json
{
  "schema_version": "1",
  "public_message": "直接展示给学习者的正文",
  "internal_review": {
    "public_message_safe": true,
    "no_internal_policy_reference": true,
    "no_answer_leakage": true,
    "no_forbidden_content": true
  }
}
```

- `public_message` 必填、非空，是唯一允许进入 `agent_message.content` 的模型正文。
- `internal_review` 只允许固定布尔字段，不允许自由文本 reasoning。
- `internal_review` 永不返回前端、永不作为聊天正文持久化、永不记录到普通日志。
- 任一必需自检字段为 `false`、schema 非法、正文为空或公开字段 guardrail 失败，都返回 `MODEL_UNAVAILABLE`，不做固定文案 fallback。

### 3. Public API and frontend boundary

- JSON 模式继续只返回兼容的 `agent_message.content`。
- SSE 模式只把 `public_message` 的解包内容作为 `agent_message.delta/content` 发送；不得发送 JSON envelope 语法、字段名或 `internal_review`。
- 前端只渲染正式正文和工具卡，不展示“导师判断”、raw thinking 或其他诊断摘要。
- 历史回放和幂等回放必须保持正文一致。

### 4. Streaming compatibility

- 第一阶段保留当前 token 级 SSE 公开正文体验，不引入句子/段落缓冲。
- 后端必须增量解析结构化 envelope，只转发 `public_message` 字符串内容。
- 增量解析必须正确处理任意 chunk 边界、JSON escape、Unicode escape、字段顺序变化和完整结束校验。
- 如果结构化流在完成前非法、断流或缺字段，返回 recoverable `MODEL_UNAVAILABLE`，不持久化成功回复或幂等成功记录。
- 第一阶段接受一个明确剩余风险：公开正文前半段可能已发送，后半段才触发 guardrail。彻底消除该风险属于第二阶段的句子/段落缓冲。

### 5. Guardrail defense in depth

- guardrail 继续校验增量和最终 `public_message`。
- guardrail 不作为区分正文与内部输出的主要机制；结构化通道隔离才是主要边界。
- 已知内部字段词、内部策略自述、raw prompt、provider error、hidden test、参考答案和完整答案泄漏仍必须被阻断。
- 正常课程术语中的 `policy`，例如 `same-origin policy`，不得被误拦。

## Acceptance Criteria

- [ ] `_build_messages()` 或等价 prompt builder 不再把 `response_policy` 对象及其内部字段写入模型用户 JSON。
- [ ] 阶段行为由后端 typed directive 编译为 instructions，不是把内部 policy 对象换名后继续传给模型。
- [ ] OpenAI Agents SDK 和 DeepSeek direct 路径都生成并校验同一个结构化学习输出 envelope。
- [ ] JSON API 保持 `agent_message.content` 兼容，不增加诊断摘要或思考字段。
- [ ] SSE 只发送解包后的 `public_message` delta，不出现 `{`、`schema_version`、`internal_review` 等 envelope 内容。
- [ ] `internal_review` 不进入 API、SSE、持久化聊天正文、历史响应或普通日志。
- [ ] 前端只展示正式正文和工具卡，不展示诊断摘要或 raw thinking。
- [ ] 截图场景 `_policy...符合policy要求` 不能作为成功正文返回或落库。
- [ ] provider 的独立 reasoning 字段继续被忽略，不进入结构化公开输出。
- [ ] 非法 schema、自检失败、公开字段不安全或流式 JSON 不完整时返回 `MODEL_UNAVAILABLE`，无固定文案 fallback。
- [ ] 测试覆盖 chunk 分割、转义字符、Unicode、字段乱序、DeepSeek、Agents SDK、JSON、SSE、回放和前端类型/渲染。
- [ ] 现有学习页工具调用顺序、练习解锁、幂等语义和 `agent_message.content` 消费方保持兼容。

## Out of Scope

- 不展示 raw chain-of-thought、provider reasoning token 或模型内部策略文本。
- 不在第一阶段实现句子/段落缓冲、整段生成后再展示或撤回已发送 SSE 文本。
- 不把同一套结构化输出立即扩展到 onboarding、review、notes 或其他 Agent 接口。
- 不重构 LangGraph 状态机、练习评分、FSRS 或 runner。
- 不增加确定性教学文案或模型不可用 fallback。

## Open Questions

- None blocking. 技术路径与剩余风险见 `design.md`。
