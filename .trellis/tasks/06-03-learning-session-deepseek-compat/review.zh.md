# 中文 Review: learning-session DeepSeek 兼容修复

## 目标

修复学习对话中 DeepSeek/OpenAI-compatible 调用不稳定导致的 SSE `MODEL_UNAVAILABLE`。这不是前端在线状态问题，也不是练习卡片本身生成失败，而是学习对话在概念判断或 Agent 回复生成阶段仍走 OpenAI Agents SDK 的 `tools` / `handoffs` / streaming 编排，和 DeepSeek 官方 Chat Completions 兼容边界不完全一致。

## 范围

- 修改后端学习会话模型调用链。
- DeepSeek 路径按官方 Chat Completions 文档走直接 `messages`、`stream`、`response_format`。
- 练习卡片继续由后端 `show_code_exercise` tool event 解锁和展示，不让模型现场生成卡片。
- 本次实施中顺手修复同一练习解锁路径暴露出的 SQL 模板错配：`language=sql` / `runtime_tier=sql_query_test` 不应落到 browser/JavaScript fallback。
- OpenAI provider 尽量保留现有 Agents SDK 行为。
- 不改 notes、review、onboarding、runner、无关前端 UI。

## 官方依据

- DeepSeek Chat Completion API 支持 `messages`、`stream`、`tools`、`response_format`。
- DeepSeek JSON Output 要用 `response_format: {"type":"json_object"}`，并在消息中明确要求 JSON。
- DeepSeek Tool Calls 支持官方 `tools` / `tool_choice` / assistant `tool_calls` / follow-up `role: "tool"` 消息；函数由应用自己执行，参数必须由应用校验。
- OpenAI Agents SDK 的 `handoffs` 是 SDK 编排层能力，会通过 tool/agent runtime 进行转交；它不是 DeepSeek 官方 Chat Completions 的原生保证。

## 关键设计取舍

- DeepSeek 学习对话改用直接 OpenAI-compatible client，稳定性优先。
- 如果确实需要 DeepSeek 模型选择工具，则按官方 Tool Calls 协议实现，而不是复用 Agents SDK `handoffs`。
- OpenAI provider 暂保留 Agents SDK，避免无必要重构。
- `show_code_exercise` 保持 deterministic/backend-generated，避免练习卡片依赖模型工具调用。
- SQL 练习卡片的边界放在 `exercise_repository._exercise_template()`，只补 SQL deterministic template，不改 `sql_query_runner.py` 合同。
- 仍保留现有 `MODEL_UNAVAILABLE` 错误合同，但正常 DeepSeek 学习流程不应因 Agents SDK handoff/tool 兼容问题触发它。

## 执行顺序

1. 在 `learning_concept_agent.py` 增加或改造 DeepSeek direct JSON client。
2. 在 `learning_conversation_agent.py` 增加或改造 DeepSeek direct text stream client。
3. 在 `learning_conversation.py` 做 provider-aware client selection。
4. 如实现需要模型选择工具，增加 DeepSeek 官方 Tool Calls loop：`tools`、`tool_calls`、`role: "tool"`、参数校验。
5. 增加 `test_llm_integration.py` payload/stream/tool-call 回归测试。
6. 增加 `test_learning_sessions_m3.py` 概念修复到练习解锁的回归测试。
7. 增加 SQL 练习模板/学习会话回归，确保 SQL 不再展示 `document.querySelector` / `addEventListener` / `count += 1`。
8. 跑 focused tests、`ruff`、`mypy`、`desktop:check`。

## 验收标准

- `llm_type=deepseek` 的概念判断使用 direct JSON Chat Completions。
- `llm_type=deepseek` 的学习回复使用 direct streamed Chat Completions。
- DeepSeek 路径不实例化 Agents SDK handoffs。
- 如果本任务加入 DeepSeek 工具调用，它必须走官方 `tools` / `tool_calls` / `role: "tool"` 协议，并校验参数。
- 截图对应的“修复判断后继续流程”不再因为兼容问题出现 SSE `MODEL_UNAVAILABLE`。
- `show_code_exercise` 仍能由后端发出并展示练习卡片。
- SQL 课程解锁出的练习卡片必须是 `sql_query_test`、SQLite metadata 和 SQL `SELECT` starter code。
- 不泄露密钥、完整 prompt、hidden tests、solution_reference 或 provider payload。

## 风险

- 现有测试里有 monkeypatch `AgentsSDKLearningConversationClient` 的地方，需要改成 provider-aware，否则会掩盖 DeepSeek 新路径。
- DeepSeek direct path 不再有 SDK handoff 事件，所以所有需要的学习阶段转换必须由现有 deterministic routing/state 负责。
- 如果本地 DB 或服务状态不稳定，部分学习会话测试可能需要顺序运行。

## 回滚点

- 如果 JSON 概念判断回归，回滚 `learning_concept_agent.py`。
- 如果学习回复生成回归，回滚 `learning_conversation_agent.py` 和 `learning_conversation.py` 的 provider selection。
- 不触碰 `.claude/skills/grill-me/`，它是无关未跟踪本地状态。

## 实施结果

已进入实施并完成：

- DeepSeek 概念 intro/check 改为 direct `OpenAICompatibleClient.complete_json()`。
- DeepSeek 学习回复改为 direct `OpenAICompatibleClient.complete_text_stream()`。
- `learning_conversation.py` 按 `llm_provider_type` 选择 client；DeepSeek 不再实例化 `AgentsSDKLearningConversationClient`，OpenAI 仍保留 Agents SDK 路径。
- 未新增 DeepSeek model-selected tool-call loop；`show_code_exercise` 仍由后端 deterministic tool event 发出。
- 增加 DeepSeek direct client、provider selection、concept repair SSE no-`MODEL_UNAVAILABLE` 回归测试。
- 补齐 SQL deterministic exercise template，避免 SQL 知识点落到 browser/JavaScript fallback。
- 增加 SQL adaptive template 和 SQL learning-session unlock/run 回归测试。
- 已同步 `.trellis/spec/backend/quality-guidelines.md`，把 DeepSeek 学习会话 direct Chat Completions 边界和 exercise template runtime alignment 固化为后续规则。

已验证：

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_llm_integration.py tests/test_learning_sessions_m3.py -q
uv --directory .\aearn\services\api run python -m ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app
pnpm --dir .\aearn desktop:check
uv --directory .\aearn\services\api run python -m pytest tests/test_adaptive_exercise_templates.py tests/test_sql_query_runner.py tests/test_learning_sessions_m3.py::test_sql_learning_session_unlocks_query_exercise -q
uv --directory .\aearn\services\api run python -m pytest tests/test_llm_integration.py tests/test_learning_sessions_m3.py tests/test_adaptive_exercise_templates.py tests/test_sql_query_runner.py -q
python .\.trellis\scripts\task.py validate .\.trellis\tasks\06-03-learning-session-deepseek-compat
git diff --check
```
