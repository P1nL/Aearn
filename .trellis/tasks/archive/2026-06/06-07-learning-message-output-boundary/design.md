# Technical Design: Learning Message Public Output Boundary

## Scope

本设计只覆盖 `POST /api/learning-sessions/{session_id}/messages` 的 JSON/SSE 学习消息链路。目标是把内部控制、模型结构化候选和前端可见内容分成三个边界：

```text
Backend learning facts + typed directive
  -> model structured envelope stream
  -> backend incremental decoder + schema/guardrail validation
  -> public message
```

## Current Data Flow

```text
LearningConversationContext
  -> _response_policy()
  -> _build_messages() user JSON
  -> TextCompletionClient.complete_text_stream()
  -> free-text deltas
  -> route guardrail
  -> SSE agent_message
  -> final persistence
```

主要问题不是 provider reasoning 字段被错误读取，而是模型看见明显的内部策略字段后，把策略自述写进普通 `content`。自由文本链路没有协议级通道可以把该内容与正文分开。

## Proposed Boundaries

### 1. Internal reply directive

新增后端内部类型，例如：

```python
@dataclass(frozen=True)
class LearningReplyDirective:
    stage_action: Literal[
        "introduce_concept",
        "check_concept",
        "repair_concept",
        "offer_practice",
        "support_practice",
    ]
    question_budget: Literal[0, 1]
    direct_answer_mode: Literal["normal", "redirect_with_local_hint"]
    practice_unlock: bool
    learning_incomplete: bool
```

现有 `_response_policy()` 的决策逻辑迁移到该类型。模型输入不序列化这个对象，也不暴露字段名。

`compile_learning_reply_instructions()` 根据 directive 生成简短的当轮 instructions。该文本描述模型应该完成的公开任务，不解释“为什么存在这些策略”，也不使用 `policy`、`forbidden_outputs` 等内部治理词。

学习事实 JSON 继续包含知识点、课程事实、受限上下文、练习安全摘要和学习者消息，但删除内部策略对象。

### 2. Structured output envelope

定义服务拥有的 Pydantic schema：

```python
class LearningOutputReview(BaseModel):
    public_message_safe: bool
    no_internal_policy_reference: bool
    no_answer_leakage: bool
    no_forbidden_content: bool


class LearningPublicOutput(BaseModel):
    schema_version: Literal["1"]
    public_message: str
    internal_review: LearningOutputReview
```

约束：

- `public_message` 有长度上限且 trim 后非空。
- `internal_review` 只有固定布尔值，没有 `reason`、分析过程或自由文本。
- 任一 review 值不是 `true`，整个候选无效。
- `assert_safe_teaching_output()` 校验公开正文。

### 3. Provider adapters

本地 `TextCompletionClient` 边界扩展为结构化流式能力，而不是让 route 直接理解 provider：

```python
class StructuredTextCompletionClient(Protocol):
    @property
    def model(self) -> str: ...

    def complete_structured_text_stream(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        output_type: type[LearningPublicOutput],
        temperature: float | None = None,
    ) -> Iterable[str]: ...
```

OpenAI Agents SDK：

- `Agent(output_type=LearningPublicOutput)` 使用 SDK 原生 structured output。
- 保留现有 tools、handoffs、input/output guardrails。
- raw output deltas仍只进入 backend decoder。
- 完成时校验 `streamed.final_output`，并与 decoder 最终对象一致。

DeepSeek direct：

- Chat Completions 使用 `response_format={"type":"json_object"}` 和 `stream=true`。
- prompt 明确要求严格匹配 envelope。
- `reasoning_content` 继续由 transport parser 忽略。
- 完整流结束后使用同一个 Pydantic schema 校验。

provider adapter 只产生 raw structured text chunks，不直接产生公开 SSE。

### 4. Incremental public-message decoder

新增 provider-neutral decoder，例如 `LearningOutputStreamDecoder`：

- 累积有大小上限的 raw JSON。
- 在任意 chunk 边界中定位 `public_message` JSON string。
- 正确解码 `\"`、`\\`、`\n`、`\t`、`\uXXXX` 和跨 chunk escape。
- 只产出 `public_message` 的已解码字符。
- 不产出 key、标点或 `internal_review`。
- 字段顺序变化时仍可找到 `public_message`；如果字段较晚，只增加首 token 延迟，不回退到 raw text。
- 流完成后用标准 JSON parser + Pydantic 做完整校验。
- decoder 输出与最终 `public_message` 必须完全一致，否则候选无效。

服务层产生 typed events：

```python
LearningPublicDelta(delta: str)
LearningPublicCompleted(output: LearningPublicOutput)
```

JSON collector 和 SSE route 消费同一 typed stream，避免两条路径校验漂移。

### 5. Public API mapping

JSON 成功响应保持兼容：

```json
{
  "agent_message": {
    "id": "msg_...",
    "role": "assistant",
    "content": "公开正文"
  }
}
```

SSE：

- `LearningPublicDelta` 映射为现有 `agent_message.delta/content`。
- 不新增 raw reasoning 或 internal-review SSE event。
- 工具调用和 `done` 顺序保持不变。

持久化：

- `learning_messages.content` 只存 `public_message`。
- `internal_review` 丢弃，不持久化。
- 历史与幂等回放只恢复正式正文和工具调用。

### 6. Frontend rendering

渲染规则：

- 正文仍按现有 Agent 气泡显示。
- 不显示“导师判断”“思考过程”“思维链”或“内部推理”区域。
- 不允许前端从正文中猜测、拆分或正则提取诊断内容。
- 现有消息布局保持不变。

## Error and Failure Contract

- 模型未配置、provider 失败、空流 -> `MODEL_UNAVAILABLE`。
- raw structured stream 非法、超出大小、缺少字段、字段类型错误 -> `MODEL_UNAVAILABLE`。
- 任一 internal review flag 为 `false` -> `MODEL_UNAVAILABLE`。
- `public_message` guardrail 失败 -> `MODEL_UNAVAILABLE`。
- SSE 已发出部分公开正文后才失败 -> recoverable `error`，不落库、不写幂等成功记录。
- 不生成本地教学 fallback，不把 raw structured body 放入错误详情或日志。

## Compatibility

- 保留 endpoint、请求体、`agent_message.content`、tool call 名称、幂等 key 和 `done` 语义。
- 旧持久化消息按正式正文和工具调用正常回放。
- LangGraph 仍只决定阶段/意图；公开输出 schema 不改变状态机 ownership。

## Security and Privacy

- raw provider reasoning 字段继续忽略。
- raw structured envelope 仅存在于请求内存，不写普通日志。
- `internal_review` 不进入 public API、SSE、数据库或前端 store。
- 不创建或公开额外诊断摘要；provider reasoning、内部策略和 raw prompt 继续保持不可见。

## Trade-offs

### Preserved token streaming

第一阶段保留当前正文 token 流，因此仍存在“前半段已发送，后半段才触发 guardrail”的剩余风险。结构化 envelope 能隔离 internal fields，但不能撤回已发送的 `public_message`。

彻底解决需要第二阶段采用句子/短段缓冲，验证通过后再发 SSE；该方案会增加可感知延迟，本任务不实现。

### Structured stream complexity

增量 JSON string decoder 比自由文本流复杂，必须用细粒度单元测试覆盖 chunk 和 escape 边界。收益是 backend 获得协议级公开通道，而不是依赖无限扩张的关键词 guardrail。

## Rollback

- 保持现有 `TextCompletionClient.complete_text_stream()` 直到新结构化路径全部通过测试。
- 实施可在单一内部 feature flag 下切换，但 flag-off 仅用于开发回滚，不允许在模型结构化输出失败时自动 fallback。
- 回滚应恢复旧请求路径，不应保留前端依赖但缺失后端字段的中间状态。
