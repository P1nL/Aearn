# Technical Design

## Selected Slice

Only review guidance text moves to SDK. Review queue selection, session creation, runtime execution, submit evaluation, and FSRS writes remain in `review_repository.py` and `review_scheduler.py`.

## Target Module Shape

```text
aearn/services/api/app/agents/
  sdk_runtime.py
  tools.py
  guardrails.py
  review_coach_agent.py
```

`review_coach_agent.py` should provide a bounded text-generation adapter for review session startup and variant rationale.

## Data Flow

1. `review_repository.py` loads due review context and creates or reuses the review session.
2. Aearn chooses the exercise using existing deterministic exercise selection.
3. SDK Review Coach receives a safe due-review summary and returns guidance text.
4. Guardrails validate the text.
5. Repository returns existing response fields with SDK or deterministic text.

## Non-Negotiable State Boundary

The SDK must not:

- query or update `review_states` directly;
- calculate FSRS intervals;
- decide whether a review is due;
- write `Attempt`;
- change `code_completion_result`.

Those operations remain in current services and tests.

## Safe Context

Allowed context includes:

- knowledge point title and description;
- weak points and mastery score;
- current due timestamp and forget-risk label;
- latest visible attempt summary;
- exercise title, prompt, runtime tier, and visible tests.

Disallowed context includes hidden tests, reference answers, full submitted code, raw provider events, and private keys.

## Fallback

The current deterministic `initial_agent_message` and `_variant_reason(...)` remain as fallback. SDK failures must not block review session creation if deterministic behavior can safely proceed.
