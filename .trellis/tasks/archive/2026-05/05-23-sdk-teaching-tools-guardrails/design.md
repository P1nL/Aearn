# Technical Design

## Selected Slice

Use the existing learning conversation endpoint as the integration point and extend only the SDK-backed Teaching Agent path. The public route and `learning_conversation.py` service should continue to own:

- request validation;
- context loading;
- idempotency lookup and storage;
- deterministic fallback;
- SSE framing;
- error normalization;
- DB transaction boundaries.

The SDK layer should own only Agent construction, read-only tool definitions, guardrail configuration, and SDK stream normalization.

## Target Module Shape

```text
aearn/services/api/app/agents/
  sdk_runtime.py
  learning_conversation_agent.py
  tools.py
  guardrails.py
```

`tools.py` should expose read-only SDK function tools or tool factories. Prefer tools backed by the already-safe `LearningConversationContext` where practical, because the current service already minimizes hidden data before calling the model.

`guardrails.py` should expose small, testable guardrail helpers that can be used by SDK guardrail primitives or by Aearn-side adapters if SDK guardrail APIs make route-level fallback awkward.

## Tool Boundary

Initial tools:

1. Current learning context summary.
2. Latest visible attempt summary.
3. Optional note summary only if it can return a bounded, non-secret summary.

Tool outputs must be safe summaries, not raw DB rows.

Do not include:

- hidden test source;
- hidden case IDs;
- `solution_reference`;
- full submitted code;
- full note bodies;
- API keys or provider payloads.

## Guardrail Boundary

Guardrails should protect both prompt input and final output. Minimum checks:

- hidden case ID patterns such as `hidden_*`;
- `solution_reference` or reference-answer wording;
- provider/raw error signatures and key-like tokens;
- direct complete-answer language when the learner asks for the full solution.

If guardrails block before useful output, use deterministic guidance. If they block after partial streaming output, preserve the existing recoverable SSE error behavior and do not store a successful response.

## State Ownership

SDK tools must not write Aearn product state. The following remain outside SDK ownership:

- `idempotency_records`;
- `LearningSession`;
- `Attempt`;
- `ReviewState`;
- `ReviewLog`;
- `Note`;
- final evaluation and FSRS scheduling.

## Provider Compatibility

Keep current provider behavior:

- SDK path uses `OpenAIProvider(use_responses=True)`;
- base URLs without `/v1` are normalized before SDK client creation;
- tracing stays disabled by default;
- deterministic fallback remains the local default when no model config exists.

## Testing Strategy

Use fake SDK runner/tool events and direct guardrail helper tests. Do not require real model credentials.

Focused tests should assert:

- safe tool output shape;
- blocked hidden/test/reference leakage;
- deterministic fallback for guardrail failure before useful output;
- no SDK event or tool payload leaks through JSON/SSE API responses;
- M3 learning session tests continue passing.
