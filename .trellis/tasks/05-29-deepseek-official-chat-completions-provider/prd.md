# DeepSeek official Chat Completions provider

## Goal

Migrate Aearn's model-backed runtime from the current Responses-only OpenAI-compatible provider assumptions to the official DeepSeek Chat Completions API, so manual testing can use DeepSeek directly with fewer third-party relay failures.

## Confirmed Facts

- Aearn currently reads model configuration from backend environment settings, not the desktop UI or database.
- Current `app/agents/sdk_runtime.py` builds an `OpenAIProvider` with `use_responses=True` and normalizes provider base URLs to a `/v1` OpenAI Responses base.
- Current `app/services/llm_client.py` sends direct JSON and text calls to `/v1/responses`.
- Existing model-backed product paths include onboarding conversation and plan generation, onboarding slot extraction, learning conversation, exercise coaching, note assist, review coaching, review conversation, and LLM explain-error.
- The public API contract requires `MODEL_UNAVAILABLE` when model configuration is disabled, incomplete, unreachable, empty, invalid, unsafe, or schema-invalid.
- DeepSeek's official OpenAI-format API uses `https://api.deepseek.com` as the base URL, `POST /chat/completions` for chat generation, `response_format={"type":"json_object"}` for JSON output, and streaming chunks with `choices[].delta.content`.
- Current official model names include `deepseek-v4-flash` and `deepseek-v4-pro`; legacy `deepseek-chat` and `deepseek-reasoner` are documented as future-deprecated compatibility names.

## Requirements

- Add an explicit DeepSeek provider configuration path for the backend, using `LLM_TYPE=deepseek` and DeepSeek-specific environment variables as the primary configuration surface.
- Use official DeepSeek Chat Completions for both SDK-backed agent clients and direct `OpenAICompatibleClient` JSON/text clients when `LLM_TYPE=deepseek`.
- Preserve existing public JSON response shapes, SSE event types, idempotency behavior, and `MODEL_UNAVAILABLE` mapping.
- Preserve model-key-free local tests by using fake transports and fake SDK runners.
- Keep raw provider errors, provider payloads, API keys, raw prompts, hidden test identifiers, hidden test source, and complete reference answers out of public responses and logs.
- Update developer documentation so local manual testing points to official DeepSeek configuration instead of the unstable third-party relay path.
- Keep the current `LLM_TYPE=openai` path either unchanged or explicitly marked legacy; do not silently break existing disabled/model-key-free development.

## Acceptance Criteria

- [ ] Backend settings can report a complete `deepseek` configuration with DeepSeek-specific env vars and continue reporting disabled/incomplete states correctly.
- [ ] SDK-backed agent clients use Chat Completions for DeepSeek, with `use_responses=False`, official DeepSeek base URL normalization, tracing disabled, and no public contract changes.
- [ ] Direct JSON completion for DeepSeek posts to `/chat/completions`, sends role-preserving `messages`, requests JSON output with `response_format`, and parses `choices[0].message.content`.
- [ ] Direct text streaming for DeepSeek posts to `/chat/completions`, sends `stream=true`, parses `choices[].delta.content`, ignores empty keepalive chunks, and treats `[DONE]` as terminal.
- [ ] All model failure, timeout, invalid JSON, empty output, and guardrail failure paths still map to `MODEL_UNAVAILABLE` through existing service boundaries.
- [ ] Updated tests cover DeepSeek URL normalization, JSON payload shape, streaming chunk parsing, SDK provider selection, and existing fake-client route behavior without live credentials.
- [ ] Source-of-truth setup docs include a DeepSeek official API configuration example and clarify any remaining legacy Responses provider behavior.
- [ ] Validation passes with backend focused tests, `ruff`, `mypy`, lock check, and task validation.

## Out of Scope

- No live DeepSeek credential, benchmark, or cost test is required for completion.
- No frontend settings page redesign is required.
- No multi-provider routing, automatic fallback, or load balancing is required.
- No database migration is required unless implementation discovers that persisted settings are already in use.

## Open Decision

- Config naming: should DeepSeek use only `DEEPSEEK_*` env vars or accept `OPENAI_*` aliases for transition?
- Recommended answer: make `LLM_TYPE=deepseek` use `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, and `DEEPSEEK_MODEL` as primary names, while leaving the existing `LLM_TYPE=openai` path as the legacy compatibility path. This avoids confusing DeepSeek's root base URL with the current `/v1/responses` normalization.
