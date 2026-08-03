# Technical Design: DeepSeek V4 Flash Responses 与 Tutor 决策契约

## Scope Boundary

本 child 只负责 provider adapter 和严格 `TutorDecision` contract。它提供经过验证的 `conversation_title` 候选及 explicit continuation 字段，但不写 conversation title、不创建 public-process 卡片、不更改 ordinary TurnRun 的创建规则。

## Exact-Model Protocol Selector

在 `OpenAICompatibleClient` 附近引入单一、可测试的 protocol selector：

```text
provider != deepseek                 → existing generic Responses path
provider == deepseek && model == v4  → DeepSeek Responses path
provider == deepseek && otherwise    → DeepSeek Chat Completions path
```

模型判断只允许统一 helper 中定义的无害配置规范化，不得用 `deepseek-v4*` 之类的宽松前缀。未来增加模型必须新增明确 catalog entry 与测试。selector 输出 protocol enum，驱动 URL、payload builder、stream parser 和 bounded diagnostic category；已选协议失败后绝不 fall through 到另一协议。

## Responses Adapter

实现前先将当前官方 `deepseek-v4-flash` Responses specification 中的非敏感协议事实固化到测试 fixture/comment：

- base URL/path、认证和 content headers；
- `model`、`input`、`instructions`、JSON format、streaming 等可用字段；
- visible-text delta/final object/completed/incomplete/failed 的事件名和 payload shape；
- 最终可见文本位置，以及不完整响应的表示方式。

若 generic Responses helper 与官方 DeepSeek contract 语义一致，应提取/参数化它而不是复制一份 SSE parser。若语义不同，保留清晰的 protocol-specific parser，但共享安全错误分类和 final-text boundary。

最终内容 helper 只能查看 final visible content，刻意不为 `reasoning`、`reasoning_content`、analysis segment、raw event 或任意第一个 output item 设置 fallback。

它只能产生以下安全结果之一：

```text
LLMJsonResponse(final_json_object, selected_model)
LLMInvalidResponseError(kind=CONTENT_MISSING)
LLMInvalidResponseError(kind=CONTENT_NOT_JSON_OBJECT)
LLMInvalidResponseError(kind=ENVELOPE_INVALID)
LLMCallError(selected transport failure)
```

provider body 与原始 exception 仅停留在 transport boundary，不能成为对上层返回的错误文本或 durable content。

## Strict Decision Envelope

使用一个 frozen Pydantic model（`extra="forbid"`）和一份共享 canonical example：

```json
{
  "public_message": "请从一个很小的练习开始。",
  "conversation_title": "函数基础练习",
  "skill_references": [],
  "capability_requests": [],
  "effect_proposals": [],
  "checkpoint_reason": null,
  "continuation_kind": null,
  "terminal_intent": "completed"
}
```

规则：

- `conversation_title` 可为 null；先过教学安全边界，再空白/Unicode 规范化，最多 48 个可见字符。它不是用户输入、raw model metadata 或 provider raw output 的 fallback。
- `continuation_kind` 是闭合 enum，例如 `approval`、`capability_result`、`external_result`；仅当与允许的 checkpoint 配对时有效。
- 普通直接回答必须 `terminal_intent="completed"` 且 `continuation_kind=null`；terminal 与 continuation 均为空的 nonterminal decision 是无效的。
- nested capability/effect payload 保持既有边界；内部字段黑名单同时适用于所有新文本字段。
- `TutorDecision` 增加 typed fields，不能塞入自由 metadata dict。

canonical example 由单一 helper/constant 生成，`_build_messages()` 与 repair reminder 必须都复用。测试需防止两个 prompt shape 随后分叉。

## Retry and Diagnostics

`PrimaryTutorProviderGateway` 只能调用同一已配置 client/model。发生 content/schema rejection 时最多附加一次 generic repair message。transport/auth/rate/timeout 不是跨 protocol retry，只直接映射到安全 diagnostics。

诊断仅是稳定 identifier，例如 envelope invalid、content missing、content not JSON、timeout、rate limited。它可在内部与 run 关联，但必须保持不出现在 learner-visible run payload、SSE、history、title 或 card。

## Compatibility and Test Design

- 非 DeepSeek provider 继续走既有 Responses 行为。
- DeepSeek 但非 `deepseek-v4-flash` 的模型继续走 Chat Completions。
- 下一 child 消费 `TutorDecision.conversation_title` 和 `continuation_kind`；本 child 不做数据库 migration。

所有测试使用 fake transports，记录 URL、payload、protocol 和 call count。至少覆盖：

1. exact V4 Flash Responses selector；
2. other DeepSeek Chat Completions selector；
3. selected adapter failure 后没有 protocol fallback；
4. final visible text 的 completed response；
5. reasoning-only/no-visible-text；
6. incomplete/failed/malformed SSE；
7. non-object/non-JSON final text；
8. strict title/continuation envelope；
9. repair 使用 canonical example 且不含 rejected payload；
10. 安全诊断分类无 secret/body leakage。
