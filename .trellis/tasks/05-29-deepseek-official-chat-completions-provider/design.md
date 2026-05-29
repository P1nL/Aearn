# DeepSeek Official Chat Completions Provider Design

## Boundary

This task changes only backend model-provider plumbing and developer setup documentation. Aearn product services remain responsible for public API response shapes, SSE framing, idempotency, durable writes, and `MODEL_UNAVAILABLE` mapping.

The affected backend boundaries are:

- `app/core/config.py` for provider configuration and status.
- `app/agents/sdk_runtime.py` for Agents SDK provider selection.
- `app/services/llm_client.py` for direct JSON and text streaming calls.
- Feature-level agent wrappers only where constructor or model-property wiring needs to use the provider-neutral settings contract.
- `tests/test_llm_integration.py` and any narrow route tests needed to prove public contracts did not drift.
- `docs/setup/development-environment.md` for local DeepSeek setup.

## Provider Model

Introduce a provider decision that distinguishes:

- `LLM_TYPE=disabled` or equivalent: current disabled behavior.
- `LLM_TYPE=openai`: existing OpenAI-compatible Responses path, treated as legacy unless a later task removes it.
- `LLM_TYPE=deepseek`: official DeepSeek Chat Completions path.

DeepSeek primary env vars should be:

```env
LLM_TYPE=deepseek
DEEPSEEK_API_KEY=<local-secret>
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
LLM_TIMEOUT_SECONDS=20
```

`DEEPSEEK_BASE_URL` should normalize to the API root, not to `/v1`. If a user accidentally provides `/chat/completions`, strip that suffix before appending the endpoint. Do not apply current `normalize_openai_base_url()` behavior to DeepSeek.

## SDK Data Flow

For DeepSeek, `build_run_config(settings)` should create an `OpenAIProvider` with:

- `api_key=settings.deepseek_api_key`
- `base_url=normalize_deepseek_base_url(settings.deepseek_base_url)`
- `use_responses=False`
- `strict_feature_validation=False`
- `tracing_disabled=True`

`openai-agents==0.17.3` converts Chat Completions streaming chunks into Responses-style stream events internally, including `response.output_text.delta`, so the existing `extract_text_delta()` strategy can remain if tests prove it still receives deltas through fake Chat Completions-style events or SDK stream abstractions.

## Direct Client Data Flow

For `LLM_TYPE=deepseek`, `OpenAICompatibleClient` should use a Chat Completions request path:

```text
POST {normalized_deepseek_base_url}/chat/completions
```

JSON completions:

- Preserve role-based `messages` instead of flattening into Responses `input`.
- Include `response_format={"type":"json_object"}`.
- Ensure a JSON hint exists in a system or user message.
- Prefer non-streaming JSON completion unless tests show a strong reason to keep streaming JSON.
- Parse `choices[0].message.content`, strip code fences, and validate a JSON object.

Text streaming:

- Preserve role-based `messages`.
- Include `stream=true`.
- Parse SSE `data:` frames.
- Accumulate `choices[].delta.content`.
- Ignore empty content chunks and finish on `[DONE]`.
- Preserve the generator's final return value as the accumulated text.

The existing Responses parser can remain for the legacy `openai` path, but shared parsing helpers should avoid duplicating error handling and JSON extraction.

## Error And Security Contracts

Provider-specific exceptions must stay behind the local `LLMCallError`, `LLMConfigurationError`, and `LLMInvalidResponseError` exception family. Public routes must continue mapping them to `MODEL_UNAVAILABLE` without exposing raw provider response bodies, API keys, prompts, hidden tests, or SDK event names.

DeepSeek JSON mode can occasionally return empty content according to the official documentation. In Aearn that must be treated as `LLMInvalidResponseError` and therefore `MODEL_UNAVAILABLE`, not as a deterministic fallback.

## Compatibility

No public endpoint path, request body, response body, SSE event type, or database schema changes are intended.

The legacy `OPENAI_*` configuration can remain for the current Responses-compatible relay path. The DeepSeek path should be explicit enough that developer documentation no longer tells users to use a relay-specific `/v1/responses` assumption for official DeepSeek.

## Rollback

Rollback is configuration-safe:

- Set `LLM_TYPE=disabled` to return to model-unavailable behavior.
- Set `LLM_TYPE=openai` with the previous `OPENAI_*` variables to use the legacy Responses provider path if it remains implemented.
- Revert this task's provider plumbing and docs if DeepSeek Chat Completions proves incompatible during validation.
