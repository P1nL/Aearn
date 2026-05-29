# DeepSeek Official API Research

Date: 2026-05-29

## Official DeepSeek Facts

Sources:

- https://api-docs.deepseek.com/
- https://api-docs.deepseek.com/api/create-chat-completion
- https://api-docs.deepseek.com/guides/json_mode
- https://api-docs.deepseek.com/quick_start/pricing

Findings:

- The official OpenAI-format base URL is `https://api.deepseek.com`.
- Chat generation uses `POST /chat/completions`.
- Official examples use the OpenAI SDK `chat.completions.create(...)` surface, not the OpenAI Responses API.
- Current model names include `deepseek-v4-flash` and `deepseek-v4-pro`.
- `deepseek-chat` and `deepseek-reasoner` are compatibility names documented as future-deprecated aliases.
- JSON output uses `response_format={"type":"json_object"}` and requires the prompt to include a JSON instruction.
- The JSON guide warns that JSON mode may occasionally return empty content; Aearn should classify this as an invalid provider response.
- Streaming Chat Completions returns SSE `data:` frames with `choices[].delta.content` and terminates with `data: [DONE]`.

## Aearn Current State

- `app/core/config.py` currently treats `LLM_TYPE=openai` plus `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_MODEL` as the only configured model path.
- `app/agents/sdk_runtime.py` currently passes `use_responses=True` to `OpenAIProvider` and normalizes base URLs to `/v1`.
- `app/services/llm_client.py` currently posts direct JSON and text calls to `/v1/responses`.
- `app/services/llm_client.py` already contains partial Chat Completions parsing for `choices[].message.content` and `choices[].delta.content`, but the request construction and JSON stream parser are still Responses-first.
- `tests/test_llm_integration.py` asserts the current `/v1/responses` URL for direct client behavior, so tests must be updated or split by provider.
- `docs/setup/development-environment.md` currently documents the relay-specific Responses path and explicitly says not to change back to non-streaming `chat/completions`; this must be revised for the official DeepSeek path.

## Local SDK Check

Local inspection of `openai-agents==0.17.3` showed:

- `OpenAIProvider` accepts `use_responses: bool | None`.
- The Chat Completions stream handler converts Chat Completion chunks into Responses-style text delta events such as `response.output_text.delta`.
- This makes `use_responses=False` viable for SDK clients while keeping Aearn's SDK-facing delta extraction mostly unchanged, provided tests cover the behavior.

## Decision Implications

- Direct DeepSeek migration is not a `.env`-only change because Aearn currently builds `/v1/responses` payloads and URLs.
- DeepSeek should have provider-specific URL normalization because official docs show root base URL plus `/chat/completions`, not `/v1/responses`.
- Aearn should keep the public API contract stable and isolate provider differences inside config, SDK runtime, and direct client modules.
