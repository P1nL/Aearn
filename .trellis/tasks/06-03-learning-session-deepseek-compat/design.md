# Design: DeepSeek Learning Conversation Compatibility

## Architecture Boundary

This task changes the backend learning-session model-call boundary only.

- `aearn/services/api/app/services/llm/llm_client.py` remains the shared OpenAI-compatible transport layer for provider-specific Chat Completions and Responses calls.
- `aearn/services/api/app/agents/learning/learning_concept_agent.py` should use a direct OpenAI-compatible JSON client for DeepSeek concept intro/check generation.
- `aearn/services/api/app/agents/learning/learning_conversation_agent.py` should expose a provider-aware learning conversation client. DeepSeek should use direct streamed text completion; OpenAI can keep the current Agents SDK implementation.
- `aearn/services/api/app/services/conversations/learning_conversation.py` should select the provider-appropriate client without changing route handlers into model orchestration code.
- `aearn/services/api/app/routes/learning_sessions.py` should keep the existing SSE error envelope and success event order.

## Official Documentation Interpretation

DeepSeek official docs define the compatible surface as Chat Completions:

- request body uses `model`, `messages`, optional `stream`, optional `tools`, and optional `response_format`.
- JSON output is requested through `response_format: {"type":"json_object"}` and must be accompanied by an explicit JSON instruction in messages.
- function calling is supported as Chat Completions tool calls: provide `tools`, optionally control `tool_choice`, read assistant `tool_calls`, execute the function in application code, validate arguments, then append a `role: "tool"` message with `tool_call_id`.
- official tool calls are not the same as OpenAI Agents SDK handoff orchestration.

OpenAI Agents SDK official docs describe a higher-level orchestration layer:

- agents can stream outputs and events through SDK runners.
- handoffs are an agent-to-agent control mechanism represented through tools.
- models can be configured, but the SDK still owns tool and handoff runtime semantics.

Therefore, for DeepSeek the safer design is to use the plain documented Chat Completions surface for learning-session JSON/text generation and keep deterministic backend state transitions/tool events outside the provider's orchestration responsibilities.

## Data Flow

### Concept intro/check JSON

1. `learning_conversation.py` needs a concept intro/check result.
2. `learning_concept_agent.py` builds a JSON-only message payload.
3. For DeepSeek, use `OpenAICompatibleClient.complete_json()`.
4. The client sends Chat Completions with `messages` and `response_format: {"type":"json_object"}`.
5. Existing validation functions parse and validate `intro`, `check_result`, `judgements`, actions, and repair checks.

### Learning message text

1. `learning_sessions.py` prepares the message and transition.
2. If transition has `show_code_exercise`, `deterministic_learning_message_text()` produces deterministic text.
3. Otherwise, `start_learning_message_generation()` selects a client.
4. For DeepSeek, the client uses direct `OpenAICompatibleClient.complete_text_stream()` for normal text generation.
5. Route streams `agent_message` deltas, then stores final content and backend-generated tool calls.

### DeepSeek official tool calls

If model-selected tools are needed for DeepSeek, implement them as a direct Chat Completions tool loop instead of reusing Agents SDK handoffs:

1. Build a bounded list of official `tools` with `type: "function"` and JSON Schema `parameters`.
2. Send the current safe learning context and tools to DeepSeek Chat Completions.
3. If the assistant response has `tool_calls`, parse and validate `function.arguments`.
4. Execute only allowlisted local functions such as safe context lookup or teaching-material search.
5. Append `role: "tool"` messages with the matching `tool_call_id`.
6. Call Chat Completions again to produce the final assistant message.

For this task, `show_code_exercise` should not be converted into a model-selected tool call unless implementation evidence proves it is required. It is already a deterministic backend UI event tied to learning-stage state.

### Practice card

The exercise card remains a backend tool event:

1. Transition chooses `show_code_exercise`.
2. `_apply_practice_tool_loop()` calls `unlock_learning_session_practice()`.
3. `exercise_repository._exercise_template()` must select a language/runtime-appropriate deterministic fallback before adaptive variant generation. SQL must use `sql_query_test` metadata and SQL `SELECT` starter code, not the browser fallback template.
4. The SSE route emits `tool_call` with exercise data after text generation/storage.

The model should not be responsible for inventing the exercise card.

## Compatibility Plan

- Keep `AgentsSDKLearningConversationClient` for non-DeepSeek providers unless tests reveal a broader issue.
- Add or reuse a direct learning conversation client that wraps `OpenAICompatibleClient.complete_text_stream()`.
- Add or reuse a direct concept JSON client that wraps `OpenAICompatibleClient.complete_json()`.
- If adding DeepSeek tool calls, add them as an explicit direct Chat Completions tool loop with allowlisted tools and argument validation.
- Preserve existing protocols (`TextCompletionClient`, `ConceptClient`) so tests can still inject fakes.
- Avoid exposing provider internals in API responses; use existing `LLMCallError`, `LLMConfigurationError`, and `LLMInvalidResponseError`.
- Keep SQL practice-card fixes at the exercise-template boundary. Do not change `sql_query_runner.py` unless runner behavior itself is broken.

## Trade-Offs

- This reduces Agents SDK handoff expressiveness for DeepSeek learning conversation generation, but can still support official DeepSeek function calling where it is useful.
- Implementing full tool-call parity in the first fix increases scope. The recommended minimum is direct JSON/text plus deterministic backend tool events; add the official DeepSeek tool loop only for tools that are actually required to unblock learning flow.
- The route and service continue to own deterministic learning-stage transitions, which keeps practice-card display stable and testable.
- OpenAI and DeepSeek behavior will not be identical internally, but the user-facing SSE contract should remain the same.

## Rollback

- Revert provider selection to `AgentsSDKLearningConversationClient` for all providers.
- Revert any `learning_concept_agent.py` direct-client changes if they break JSON validation.
- Keep tests that describe the expected provider split so future rollback is explicit rather than accidental.

## Risks

- Some existing tests monkeypatch `AgentsSDKLearningConversationClient`; they may need provider-specific adjustments so they do not hide the DeepSeek path.
- Direct text streaming removes SDK handoff side effects for DeepSeek, so any behavior previously dependent on Agents SDK handoff events must be represented through deterministic routing/state instead.
- Fake transports must assert payload shape without leaking real provider payloads.
