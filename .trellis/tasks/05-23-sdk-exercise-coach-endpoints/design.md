# Technical Design

## Selected Slice

Extend the learning exercise coaching path only. The route and repository layers continue to own request parsing, idempotency, DB writes, and error normalization. The SDK layer owns prompt/agent construction, safe read-only context packaging, output generation, and output validation helpers.

## Target Module Shape

```text
aearn/services/api/app/agents/
  sdk_runtime.py
  tools.py
  guardrails.py
  exercise_coach_agent.py
```

`exercise_coach_agent.py` should expose small methods or functions for:

- hint generation;
- error explanation;
- explanation checking.

The module should not import database connection types directly. It should accept already-sanitized context dictionaries from repository/service code.

## Data Flow

1. `learning_session_repository.py` loads the session, exercise, latest attempt, visible runtime facts, and request payload.
2. Repository code builds the deterministic response first or keeps deterministic builders available as fallback.
3. SDK client receives safe context and generates structured or semi-structured coaching output.
4. Guardrail and schema normalization converts SDK output into the existing API response shape.
5. Repository code performs the existing `Attempt` and `idempotency_records` writes.

## Safety Boundary

SDK context may include:

- knowledge point title/description/weak points;
- exercise title, prompt, visible blanks, visible tests, and runtime tier;
- bounded current code excerpts only when needed;
- runtime status, stderr summary, visible failed-test summaries, hint count, and error count.

SDK context must not include:

- hidden test IDs or hidden test source;
- solution reference;
- API keys, provider payloads, or raw SDK events;
- full submitted code when a bounded excerpt or blank-level context is sufficient.

## Compatibility

Keep the endpoint response contract unchanged. If SDK output cannot be normalized, return the current deterministic response and mark `generation_source` consistently with existing conventions where the endpoint already exposes source metadata.

Do not change `TextCompletionClient.complete_text_stream(...)` for this task unless the teaching tools task already introduced a shared interface that should be reused.

## Trade-Offs

The SDK agent should not be allowed to choose scoring or FSRS outcomes. That keeps coaching quality improvements independent from deterministic evaluation, but it means some responses remain constrained by existing response schemas.
