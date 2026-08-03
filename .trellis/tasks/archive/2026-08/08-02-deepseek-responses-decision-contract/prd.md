# DeepSeek V4 Flash Responses 与 Tutor 决策契约

## Goal

为精确配置为 `deepseek-v4-flash` 的 Tutor 模型增加经过官方文档核验的 Responses 适配；同时收紧 Tutor 的严格 JSON 决策协议，使普通回复、受控 continuation 与模型简述标题均可被服务端安全验证。该任务不改变 conversation 的普通 TurnRun 生命周期、历史 API 或 Desktop 导航。

## Dependencies

- 依赖父任务 `08-02-tutor-run-lifecycle-deepseek-responses` 的产品、安全与无 fallback 决策。
- 本 child 是 `08-02-tutor-conversation-turnrun-history` 的前置：后续 lifecycle child 依赖这里提供的 `conversation_title` 和 explicit-continuation 契约。

## Confirmed Facts

- `OpenAICompatibleClient.complete_json()` 当前在 `llm_provider_type == "deepseek"` 时固定调用 Chat Completions；generic 分支已有 Responses 请求/SSE 解析路径。
- 现有 provider gateway 使用 Pydantic `extra="forbid"` 验证 `TutorDecision`，但 allowed keys 中尚没有 `conversation_title` 和显式 continuation 语义。
- 当前 system prompt/repair prompt 中的 JSON shape 是分散文案，容易随字段演进产生不一致；必须收敛为单一 canonical JSON example。
- 当前最终内容提取边界只应读取可见最终输出；本 child 必须保持 reasoning 不可读、不可写、不可见的边界。
- 本任务的 provider 测试只能使用 fake transport/client，不能默认调用真实 DeepSeek 或其他 provider。

## Requirements

### R1. 精确模型的协议选择

- 仅在 provider 为 DeepSeek 且配置模型精确为 `deepseek-v4-flash` 时，使用实现当天官方文档确认的 Responses URL、请求字段、SSE 事件和终态解析。
- 其他已配置 DeepSeek 模型继续使用固定 Chat Completions 兼容路径；不得以模型展示名、模糊前缀或错误重试猜测 Responses 支持性。
- 任一 Responses/Chat Completions 失败都不得发起第二次跨 protocol、跨 provider 或跨 model fallback 请求。

### R2. 最终可见文本与错误分类

- Responses adapter 只可从文档化的最终可见文本字段构造 `LLMJsonResponse`；不得把 reasoning、`reasoning_content`、analysis item 或 provider raw body 当作内容。
- completed 但无最终可见文本、reasoning-only、incomplete、failed、malformed SSE/envelope、非 JSON final text 都必须归类到稳定的安全错误码。
- 最小诊断可关联协议模式和 run，但不得包含 response body、prompt、reasoning、headers、密钥、URL query、路径、命令、SQL 或 stack trace。

### R3. 严格 TutorDecision 扩展

- 将 `conversation_title: string | null` 加入 strict envelope、Pydantic allowlist、`TutorDecision` contract 和 canonical example。
- 将 `continuation_kind` 定义为闭合、服务端可授权的 enum；它只可与允许的 checkpoint 配对，不能表达任意“继续等用户输入”。
- 普通直接回复必须明确 terminal 完成；既无 terminal intent 又无有效 continuation 的 decision 必须拒绝。
- 标题候选必须经空白过滤、安全检查、规范化及最多 48 个可见字符限制。该 child 只产出验证后的候选，不负责数据库写入或 UI 展示。

### R4. 统一格式提示与有限 repair

- 系统提示和 repair 提示必须复用一份完整 canonical JSON example，列出所有 keys、空数组、`null` 和合法 enum 形状。
- 模型调用采用低随机性；同一已配置模型最多额外 repair 一次。
- repair prompt 不能回显被拒绝 JSON、具体校验失败信息、provider 原文、reasoning 或敏感信息。

### R5. 可测试性与兼容性

- 保持非 DeepSeek provider 的既有 Responses 行为，除非共享解析 bug 修复可由回归测试证明安全。
- 保持非 `deepseek-v4-flash` DeepSeek 配置的 Chat Completions 行为。
- safe diagnostic 不得透传到 learner-visible run API、SSE、标题或历史。

## Acceptance Criteria

- [ ] fake transport 证明 `deepseek-v4-flash` 请求走 Responses URL/契约，其他 DeepSeek 模型仍走 Chat Completions，且失败时没有第二协议请求。
- [ ] 有最终可见文本的完成 Responses 响应可以解析为严格 `TutorDecision`。
- [ ] reasoning-only/no-visible-text、incomplete、failed、malformed envelope 与非 JSON final text 均得到稳定安全分类，结果、日志断言和公共对象均不含 raw provider 内容。
- [ ] decision envelope 接受安全 `conversation_title` 和有效 continuation；拒绝未知字段、超长/不安全标题、无效 enum、模糊 nonterminal decision 及 internal/reasoning 字段。
- [ ] system prompt 和 repair prompt 使用同一份完整 canonical JSON example；一次无效候选只在同一模型上 repair 一次，repair 不回显被拒绝输出。
- [ ] 429、401/403、timeout 和 transport/adapter 错误映射到稳定安全诊断，且不会 fallback。
- [ ] focused provider/LLM tests 使用 fake client/transport 通过；不执行真实 provider 请求。
- [ ] `ruff`、`mypy` 和 `git diff --check` 通过。

## Out of Scope

- 不实现普通 TurnRun 每消息新建、latest-input-wins、history/list API、数据库 title 写入或 Desktop UI。
- 不实现 conversation 手动重命名。
- 不向客户端展示或持久化 reasoning/CoT、provider raw output 或内部协议字段。
- 不为响应适配增加自动 model/provider/protocol fallback。

## Open Questions

无产品开放问题。开始实现时必须把官方 `deepseek-v4-flash` Responses 文档的精确字段/SSE 形状记录到 child design/test fixtures；若文档与当前假设冲突，优先修订 implementation 设计，不默默猜测或 fallback。
