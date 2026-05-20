# Technical Design

## Scope

This task adds a narrow OpenAI-compatible LLM boundary to the backend and wires it into the existing `explain-error` path. It does not add a desktop model settings editor, database secret storage, or new provider adapters.

## Current Flow

The existing path is:

1. Desktop calls `POST /api/learning-sessions/{session_id}/attempts/{attempt_id}/explain-error`.
2. `learning_sessions.py` validates `ExplainErrorRequest`.
3. `learning_session_repository.explain_learning_attempt_error(...)` loads the session, attempt, exercise, and related knowledge point.
4. The repository calls `build_error_explanation_response(...)` in `exercise_guidance.py`.
5. The response updates `attempts.error_cause` and is stored in `idempotency_records`.

The frontend accepts the required response fields:

- `error_cause`
- `explanation`
- `fix_suggestion`
- `related_knowledge_points`
- `next_action`
- optional `idempotency_replayed`

## Configuration

Extend `app.core.config.Settings` with:

- `llm_type`: default `disabled`
- `openai_api_key`: optional, loaded from `OPENAI_API_KEY`
- `openai_base_url`: optional, loaded from `OPENAI_BASE_URL`
- `openai_model`: optional, loaded from `OPENAI_MODEL`
- a helper such as `llm_enabled` or `openai_compatible_enabled`

Validation rules:

- `LLM_TYPE=disabled` or blank means no model calls.
- `LLM_TYPE=openai` requires `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_MODEL`.
- Missing OpenAI-compatible fields should not break app startup in local development; the feature should report disabled/unconfigured and use fallback.
- Secrets must never be returned in API responses, persisted in DB rows, or logged.

## Model Client Boundary

Add a backend service module such as `app/services/llm_client.py`.

Responsibilities:

- Own all direct provider calls.
- Hide API key and base URL handling from feature code.
- Expose a small typed method for JSON completions, for example `complete_json(messages, timeout_seconds)`.
- Convert provider-specific exceptions into internal exceptions such as `LLMConfigurationError`, `LLMCallError`, and `LLMInvalidResponseError`.
- Be mockable in tests without network access.

Implementation can use the existing `langchain-openai` dependency if it supports the needed OpenAI-compatible base URL cleanly. If that creates unnecessary coupling, use a direct HTTP client behind the same boundary.

## Explain-Error Integration

Add a feature-level wrapper such as `app/services/llm_explain_error.py`.

Inputs:

- exercise metadata and runtime profile
- sanitized failed test summaries
- `error_message`
- `stderr`
- current code
- related knowledge point summaries

Output must match the existing response contract and be validated before use:

```json
{
  "error_cause": "state_scope_error",
  "explanation": "short evidence-based explanation",
  "fix_suggestion": "specific next edit direction, not full answer",
  "related_knowledge_points": [
    {
      "id": "kp_dom_event_state",
      "title": "event listener state"
    }
  ],
  "next_action": "retry_same"
}
```

Allowed `next_action` values follow the API contract. `related_knowledge_points` should be server-controlled or reconciled against server-loaded knowledge points, not blindly trusted from the model.

## Fallback Strategy

The deterministic function `build_error_explanation_response(...)` remains the fallback and the default for unconfigured environments.

Use fallback when:

- LLM is disabled or incompletely configured.
- Provider request fails or times out.
- Provider returns non-JSON or schema-invalid JSON.
- Output violates safety constraints, such as hidden source leakage or full-answer style output.

Fallback must still update `attempts.error_cause` and store the response in `idempotency_records`.

## Idempotency

Current idempotency key shape is `explain-error:{attempt_id}:{payload_hash}`. Preserve this behavior.

If a stored response exists, return it without another LLM call. This avoids repeated charges and keeps retries stable.

## Observability

Add a non-secret signal so local smoke tests can prove the request chain:

- Either include optional response metadata such as `generation_source` and `generation_model`, or
- Emit structured server logs with `operation=explain-error`, `generation_source`, and `model`.

If response metadata is chosen, update frontend types and API docs as optional fields. Do not expose API keys, raw provider URLs with embedded credentials, or full provider error bodies.

## Documentation

Update the closest source-of-truth docs during implementation:

- `docs/setup/development-environment.md` for third-party API `.env` configuration and the current compose path.
- `docs/architecture/api-contract.md` if optional explain-error metadata is added.
- `docs/qa/acceptance-test-plan.md` for the model-backed explain-error smoke/rubric.

## Compatibility

Existing deterministic tests must keep passing without model configuration. New tests should mock the model boundary and should not require network access or a real third-party key.

