# Chat-first 对话体验改造 Review

## 目标

把 Aearn 的对话体验从“表单式槽位追问”调整为更像 Claude Code / Codex 的 chat-first 模式：先回答用户当前问题，再自然推动建档、学习或复习流程。

## 范围

本次优先修 Onboarding 页面。当前截图里的问题来自后端 `normalize_onboarding_agent_message()` 把模型可能生成的正常回答覆盖成固定 `missing_slot_question`。学习页不在本任务里重做成通用聊天助手，但会修正 composer SSE 错误文案，避免把不同错误都显示成“回答没有完成”。

## Claude Code / Codex 模式是什么

这个判断基于 Anthropic 官方 Claude Code 文档：

- `https://code.claude.com/docs/en/how-claude-code-works`
- `https://code.claude.com/docs/en/best-practices`
- `https://code.claude.com/docs/en/common-workflows`

目标不是“完全自由聊天”，也不是“按表单逐项提问”，而是分层 agentic conversation：

- 先收集上下文，再行动。
- 先回答、确认或执行用户当前意图，而不是马上套进表单字段。
- 复杂任务先探索和计划，再实现。
- 实现后要能验证结果，而不是只说“看起来完成”。
- 用户可以中途纠偏，Agent 应该调整方向，不应该要求重开流程。
- 把 slot、状态机、tool call、路线生成条件放在后台。
- 只有需要推动任务时才问一个高价值追问。
- 不把内部 checklist 暴露成可见对话。
- 遇到不支持或不安全的方向时，清楚说明边界，再给一个可走的替代路径。

套到 Aearn：Onboarding 仍然要收集 `language`、`goal_text`、`target_level`，但用户体验应该像一个学习教练在帮用户做选择，而不是每轮都被表单字段接管。

## 验收标准

- Onboarding 有明确的 chat-first 回复策略：slot extraction 是后台状态，不是可见对话本身。
- 咨询类问题要先回答建议，再自然追问。例子包括但不限于 `agent 一般用什么`、`agent 一般用什么语言`。
- 能力类问题要先解释能力或概念，例如 `你能做什么`、`Aearn 能帮我什么`、`agent 是什么`，不能直接变成语言槽位追问。
- 对比类问题要给出推荐路径和理由，例如 `Python 和 JavaScript 哪个更适合做 agent`，再最多追问一个下一步。
- 用户直接回答槽位时，仍然可以继续推进建档流程，例如 `Python`、`零基础`、`每天 1 小时`。
- 用户连续问咨询/概念/能力问题时，不能每轮都重复同一句 `您想用哪种编程语言学习 agent？目前支持 ...`。
- 必填槽位不明确时，仍不能生成 `show_learning_route`，也不能暂存 `plan_draft`。
- `TypeScript` / `TS` 不能按不支持或桥接处理：它现在是独立公开路线，并使用 Node/TypeScript teaching runner。
- `TypeScript` / `TS` 在必填槽位不明确时，仍不能生成 `show_learning_route`，也不能暂存 `plan_draft`。
- 用户明确选择 C++ 或 Rust 时，`LANGUAGE_NOT_SUPPORTED` 行为不变。
- 模型不可用时仍返回 `MODEL_UNAVAILABLE`，不新增关键词兜底解析。
- 支持语言边界必须分清：公开课程选择、teaching-grade runner 限制、暂不支持路线选择。
- 学习页错误气泡必须按稳定 `error.code` 展示原因：`MODEL_UNAVAILABLE` 说明模型服务或配置不可用，`STREAM_INCOMPLETE` 说明 SSE 流没有正常终止，连接类错误说明 API/SSE 可用性问题。

## 支持语言边界

当前不要把“能运行某类练习”和“能作为公开课程路线选择”混在一起：

- 公开课程 / route selection：`python`、`javascript`、`typescript`、`sql`、`html_css`、`java`、`go`、`csharp`。
- Teaching-grade executable runner：TypeScript / TS、SQL、Go、C# 可以直接作为公开路线，但只表示单文件/教学级 runner 能力，不等于任意项目执行。
- 暂不支持路线选择：C++、Rust 仍走 `LANGUAGE_NOT_SUPPORTED`，直到 catalog、content、onboarding、API、UI 和测试一起扩展。

## 学习页为什么显示“没有回答完成”

原因不是学习页已经拿到了半句回答，而是前端把所有 SSE 错误统一包成了固定文案。真实错误来自稳定 `error.code`：

- `MODEL_UNAVAILABLE`：后端模型配置不可用、模型调用失败、输出为空或 guardrail 拦截，所以不会写入成功的 assistant 响应。
- `STREAM_INCOMPLETE`：前端检测到 SSE 连接关闭了，但后端没有发 `done` 或 `error` 终止事件。
- `STREAM_ERROR` / `STREAM_UNAVAILABLE` / `STREAM_HTTP_ERROR`：连接、HTTP 或可读流层面失败。

本次修正只改显示解释，不新增模型兜底、不伪造 Agent 回复，也不改变后端学习状态机。

## 关键设计取舍

推荐改后端而不是前端，因为前端只是展示 SSE 返回的 `agent_message` 和 `tool_call`。后端要把两个责任拆开：安全阻止错误路线生成，但不要抹掉正常聊天回答。

核心改法是软化 `normalize_onboarding_agent_message()`：如果文本错误声称“信息够了/生成路线”，仍然替换成澄清问题；如果文本只是正常回答用户问题，就保留回答，并在需要时追加一个自然追问。

## 执行顺序

1. 读取后端规范和现有 Onboarding 测试。
2. 先补 chat-first advisory input 的失败测试。
3. 修改 Onboarding normalize 逻辑和系统 prompt。
4. 跑 `test_onboarding_m2.py`、`test_onboarding_graph.py`、`ruff`、`mypy`、Trellis validate 和 `git diff --check`。

## 风险

最大风险是改得太宽，导致必填槽位模糊时提前生成路线卡片。实现时必须保留现有 route-ready blocking、ambiguous slot blocking 和 unsupported language error 测试。

TypeScript 的风险是把“历史桥接规则”误带回来。本次必须保留独立 TypeScript 公开路线，并同步 `Language` enum、DB CHECK、catalog seed、Onboarding、API、UI 和测试。

## 回滚点

如果 route-card 安全边界失败，回滚 `normalize_onboarding_agent_message()` 的行为修改；如果只是文案不理想，可以保留安全逻辑，只调整 prompt。

## 待确认决策

默认采用推荐范围：先修 Onboarding 的 chat-first 体验，并保留学习/复习结构化评测边界；公开语言边界按 Python / JavaScript / TypeScript / HTML+CSS / Java / Go / C# / SQL 执行，C++ / Rust 暂不支持。
