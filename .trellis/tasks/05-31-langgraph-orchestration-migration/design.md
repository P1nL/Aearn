# LangGraph Orchestration Migration Design

## Architecture

Use one graph per main business flow instead of a single global graph:

- `learning_graph`: learning session stage orchestration.
- `onboarding_graph`: onboarding slot and route orchestration.
- `review_graph`: review-session orchestration and FSRS update coordination.

Shared graph contracts should live under `app/agents/` or a nearby service-neutral module. The contracts should normalize:

- graph input state from service-owned facts,
- graph output intents,
- error/fallback result shape,
- feature-flag gating behavior,
- public response adapter inputs.

## Ownership Boundaries

- Graph modules own node selection, state-machine transitions, and intent production.
- Service modules own loading facts, opening transactions, idempotency replay, durable writes, SSE/JSON envelopes, and model error mapping.
- Repository modules own SQL and persistence invariants.
- SDK agent modules own model/tool invocation and sanitized candidate generation.

## Rollout Shape

Each child first introduces graph invocation behind a flow-specific or shared feature flag, then promotes the graph path to the default only after route-level parity tests pass.

The parent is complete only when all three main flows use graph orchestration as their primary path and the old imperative orchestration is reduced to adapters, persistence, or deleted fallback code.

## Compatibility

Default API contracts must stay compatible. If a child must change a response shape, that change requires explicit PRD acceptance criteria and frontend tests.

## Rollback

Rollback is feature-flag based per flow. Disabling the relevant flag must route the flow through the last stable non-graph path until the parent final cleanup removes old paths.
