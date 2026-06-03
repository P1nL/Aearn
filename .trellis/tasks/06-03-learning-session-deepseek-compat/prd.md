# Fix DeepSeek learning conversation compatibility

## Goal

Make the learning-session conversation flow reliable with the configured DeepSeek OpenAI-compatible provider by following the provider's official Chat Completions contract instead of relying on OpenAI Agents SDK orchestration for DeepSeek-only runtime paths.

The user-visible issue is an SSE `MODEL_UNAVAILABLE` error after a learner answers a concept repair choice. The backend service is online, but the learning conversation's model-generation step fails before the next agent message or practice card events can be completed.

## Confirmed Facts

- The project is currently configured for an OpenAI-compatible DeepSeek provider, and recent diagnostics showed the model settings are present rather than missing.
- `POST /api/learning-sessions/{session_id}/messages` can return HTTP `200 OK` while the SSE stream emits an `error` event with `MODEL_UNAVAILABLE`.
- `aearn/services/api/app/routes/learning_sessions.py` wraps safe generation exceptions and empty model output into the same SSE `MODEL_UNAVAILABLE` event.
- `aearn/services/api/app/services/conversations/learning_conversation.py` still creates `AgentsSDKLearningConversationClient` for learning-message generation.
- `aearn/services/api/app/agents/learning/learning_conversation_agent.py` builds an Agents SDK agent with `tools`, `handoffs`, guardrails, and `stream_text_deltas`.
- Official OpenAI Agents SDK docs describe handoffs as agent-to-agent transfers represented through the SDK tool/agent orchestration layer; this is more than a plain Chat Completions request.
- Official DeepSeek docs document an OpenAI-compatible Chat Completions API with `messages`, `stream`, `tools`, and `response_format: {"type":"json_object"}`. They do not make OpenAI Agents SDK orchestration a DeepSeek-native compatibility guarantee.
- Official DeepSeek Tool Calls docs support function calling through Chat Completions `tools`, `tool_choice`, assistant `tool_calls`, and follow-up `role: "tool"` messages. The application must execute the function itself and validate generated arguments.
- `aearn/services/api/app/services/llm/llm_client.py` already contains a direct `OpenAICompatibleClient` path for DeepSeek JSON and streamed text.
- `aearn/services/api/app/agents/onboarding/plan_generation_agent.py` recently moved dynamic route generation to a direct OpenAI-compatible JSON client pattern.
- A SQL learning-session screenshot showed a `sql_query_test` practice card rendering JavaScript DOM code (`document.querySelector`, `addEventListener`, `count += 1`) because `exercise_repository._exercise_template()` lacked a `language == "sql"` branch and fell through to the browser fallback template.

## Requirements

- Replace DeepSeek learning conversation model calls with an official-doc-aligned direct Chat Completions path.
- Keep OpenAI provider behavior compatible with the current Agents SDK path unless an existing test proves the path must be generalized.
- Use DeepSeek Chat Completions `response_format: {"type":"json_object"}` for concept intro/check JSON calls.
- Use DeepSeek Chat Completions streaming for normal learning-agent text deltas.
- Do not rely on Agents SDK `handoffs` for DeepSeek learning-session text generation.
- If DeepSeek needs model-selected tool calls, implement them through the official Chat Completions function-calling protocol rather than through Agents SDK handoff/tool orchestration.
- Preserve deterministic practice-card unlock behavior: `show_code_exercise` should continue to be emitted from backend state/tool events, not generated ad hoc by model text.
- Preserve existing SSE error contract: real provider failures may still surface as `MODEL_UNAVAILABLE`, but known DeepSeek compatibility failures should no longer occur on normal concept repair or practice-unlock flows.
- Do not log API keys, raw `.env`, full prompts, full user code submissions, hidden tests, solution references, or provider payloads.
- Add focused regression tests that prove the DeepSeek path uses direct OpenAI-compatible requests and avoids Agents SDK handoff/tool orchestration for learning conversation generation.
- Fix the SQL practice-card template mismatch inside the deterministic `show_code_exercise` path without changing the SQL runner contract.
- Keep the task scoped to learning-session DeepSeek compatibility and the SQL practice-card mismatch discovered during this flow; do not refactor notes, review, onboarding, runtime runners, or unrelated frontend UI.

## Acceptance Criteria

- [x] Learning concept intro/check calls under `llm_type=deepseek` use direct OpenAI-compatible JSON completion with `response_format: {"type":"json_object"}`.
- [x] Learning conversation text generation under `llm_type=deepseek` uses direct OpenAI-compatible streamed text completion and does not instantiate Agents SDK handoffs.
- [x] No DeepSeek model-selected tool-call support was introduced by this task; if added later, it must use official Chat Completions `tools` / `tool_calls` / `role: "tool"` messages and validate tool arguments before execution.
- [x] The concept-repair scenario matching the screenshot can progress without SSE `MODEL_UNAVAILABLE` when a fake DeepSeek direct client returns valid content.
- [x] Practice unlock still emits deterministic text plus `show_code_exercise` tool events and does not require the model to generate the exercise card.
- [x] SQL learning-session practice unlock materializes a `sql_query_test` exercise with SQL `SELECT` starter code and SQLite metadata, not the browser/JavaScript fallback template.
- [x] Existing OpenAI-oriented Agents SDK tests remain valid and continue to cover provider-specific behavior.
- [x] Focused backend tests pass for learning sessions and LLM integration.
- [x] No real secrets or provider payloads are printed, logged, or committed.

## Notes

- Official references to use during implementation:
  - DeepSeek Chat Completion API: `https://api-docs.deepseek.com/api/create-chat-completion`
  - DeepSeek Function Calling guide: `https://api-docs.deepseek.com/guides/function_calling/`
  - DeepSeek Tool Calls guide: `https://api-docs.deepseek.com/guides/tool_calls`
  - DeepSeek JSON Output guide: `https://api-docs.deepseek.com/guides/json_mode`
  - OpenAI Agents SDK Handoffs: `https://openai.github.io/openai-agents-python/handoffs/`
  - OpenAI Agents SDK Streaming: `https://openai.github.io/openai-agents-python/streaming/`
  - OpenAI Agents SDK Models: `https://openai.github.io/openai-agents-python/models/`
