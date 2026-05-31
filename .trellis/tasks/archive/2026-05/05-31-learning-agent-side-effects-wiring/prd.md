# Learning Agent Side Effects Wiring

## Goal

Instantiate and pass real `AgentSideEffects` and `LearningToolContext` through the learning-message production path so SDK teaching tools can request bounded agent actions without directly mutating durable state.

## Confirmed Current State

- `app/agents/tools.py` defines `AgentSideEffects`, `LearningToolContext`, and write-intent tools.
- `learning_conversation.py` accepts optional `side_effects` and `tool_context`, but the route/repository call path does not instantiate them.
- Durable writes must remain owned by learning services/repositories; SDK tools may only append intents to the side-effect accumulator.

## Requirements

- Build `AgentSideEffects` and `LearningToolContext` in the real learning message route/service call chain.
- Keep tools bounded to the current user/session/knowledge point/exercise facts.
- Drain or surface supported side effects through existing response metadata without changing public API/SSE contracts unless strictly necessary.
- Do not let SDK tools write `Attempt`, `LearningSession`, `ReviewState`, profile, or chunk rows directly.
- Preserve deterministic fallback behavior when SDK/model tooling is unavailable.

## Acceptance Criteria

- [x] Learning message handling constructs non-null `AgentSideEffects` and `LearningToolContext` for real requests.
- [x] Tool construction is active in the SDK-backed learning conversation path.
- [x] Side effects are accumulated and safely drained or exposed by service-owned code.
- [x] Tests fail if the route path stops passing side-effect/tool context again.
- [x] Existing learning message response shape remains compatible.
- [x] Focused backend tests, lint, mypy, and task validation pass.
