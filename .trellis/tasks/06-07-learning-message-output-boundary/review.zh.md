# 学习消息公开输出边界 Review

## 你需要审核的结论

这个任务不再依赖 guardrail 猜测所有泄漏变体，而是给学习消息增加协议级公开通道：

- 内部阶段策略不再作为 `response_policy` JSON 对象传给模型。
- 模型统一输出结构化 envelope。
- 后端只把 `public_message` 交给前端。
- `internal_review` 只包含固定布尔自检，永不展示、持久化或记录到普通日志。
- guardrail 保留为最后一道兜底。

## 第一阶段范围

1. 通用 prompt 去除明显内部策略对象和字段名。
2. 后端 typed directive 编译当轮 instructions。
3. OpenAI Agents SDK 与 DeepSeek 使用同一个结构化输出 schema。
4. SSE 增量解包并只发送 `public_message`。
5. 前端只显示正式正文和工具卡，不显示“导师判断”或“思考过程”。
6. 非法或不安全输出返回 `MODEL_UNAVAILABLE`，不做固定文案 fallback。

## 结构化输出

```json
{
  "schema_version": "1",
  "public_message": "展示给学习者的正文",
  "internal_review": {
    "public_message_safe": true,
    "no_internal_policy_reference": true,
    "no_answer_leakage": true,
    "no_forbidden_content": true
  }
}
```

前端永远看不到整个 JSON，也看不到 `internal_review`。SSE 只发送解包后的正文 token。

## 为什么不是简单改字段名

把 `response_policy` 改成 `reply_plan` 仍然可能被模型复述。本方案让后端保留 typed directive，并把它编译为当轮 instructions；学习事实 JSON 不再携带 policy 对象。

prompt 主体仍然是通用学习导师 prompt，不会针对 `_policy` 单独设计业务流程。

## 前端不展示诊断文本

- 不显示 provider reasoning token。
- 不显示 chain-of-thought。
- 不显示内部 policy。
- 不从正文正则猜测或拆分诊断文本。

## 明确剩余风险

第一阶段保留 token 级流式正文。若模型在 `public_message` 前半段输出正常内容、后半段才泄漏，前半段可能已经显示，之后流以错误结束。

彻底消除这个风险需要第二阶段的句子/短段缓冲，会增加首段延迟，本任务不做。

## 验收重点

- 模型输入不再含 `response_policy` 对象。
- SSE 不出现 envelope key、JSON 语法或 internal review。
- `_policy...符合policy要求` 不能作为成功正文返回或落库。
- DeepSeek `reasoning_content` 继续被忽略。
- `internal_review` 不进入 API、数据库、历史和日志。
- 前端只显示正文和正式工具卡。
- 工具调用、练习解锁、幂等回放和现有 `agent_message.content` 保持兼容。

## 不做

- 不展示原始思考链。
- 不让前端猜测思考/正文边界。
- 不做句子或段落缓冲。
- 不扩展到 onboarding、review、notes。
- 不增加模型不可用 fallback。
