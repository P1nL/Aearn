# DeepSeek Official Chat Completions Provider Implementation Plan

## Checklist

1. Re-read current task artifacts and backend/provider specs before editing.
2. Update `app/core/config.py` with explicit DeepSeek env fields, complete/incomplete status helpers, and provider selection that preserves existing disabled and legacy OpenAI behavior.
3. Add provider URL helpers:
   - keep existing OpenAI Responses normalization for `LLM_TYPE=openai`;
   - add DeepSeek root normalization for `LLM_TYPE=deepseek`;
   - add Chat Completions endpoint construction for the direct client.
4. Refactor `app/services/llm_client.py` so direct calls branch by provider:
   - Responses payload/parser for legacy `openai`;
   - Chat Completions payload/parser for `deepseek`;
   - shared exception wrapping and JSON content validation.
5. Refactor `app/agents/sdk_runtime.py` so SDK-backed clients use `OpenAIProvider(use_responses=False)` for DeepSeek and preserve `use_responses=True` for legacy OpenAI.
6. Update or add tests in `tests/test_llm_integration.py`:
   - settings status for `LLM_TYPE=deepseek`;
   - DeepSeek base URL normalization;
   - direct JSON Chat Completions URL, headers, payload, and response parsing;
   - direct text streaming SSE parsing for `choices[].delta.content` and `[DONE]`;
   - SDK run config provider selection without live credentials;
   - invalid/empty output remains `LLMInvalidResponseError`.
7. Run focused route-level tests if provider changes affect onboarding, learning, review, note assist, or exercise coach wrappers.
8. Update `docs/setup/development-environment.md` with the official DeepSeek example and legacy provider note.
9. Run validation commands and record exact results before asking to start finish-work or commit.

## Validation Commands

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_llm_integration.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py tests/test_onboarding_m2.py tests/test_reviews_m4.py -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app
uv --directory .\aearn\services\api lock --check
python .\.trellis\scripts\task.py validate .\.trellis\tasks\05-29-deepseek-official-chat-completions-provider
```

Run the M2/M3/M4 pytest batch sequentially as one command or in separate sequential commands. Do not run bootstrap-database API test batches in parallel.

## Risk Points

- `DEEPSEEK_BASE_URL` must not be normalized to `/v1` unless official docs or a live smoke proves that variant is required.
- DeepSeek JSON mode can return empty content; treat that as model unavailable.
- Chat Completions streaming emits empty first and final chunks; tests must assert those are ignored without producing blank public SSE deltas.
- Do not rename public feature classes or public response fields just because provider configuration changes.
- Existing dirty work from other tasks must not be reverted or included in this task unless the user explicitly asks.

## Review Gate

Do not run `task.py start` until the user confirms this planning scope. Creating the task is not implementation approval.
