# Agent Handoff Runtime Routing Design

## Boundaries

- `app/agents/router.py` owns route decision rules.
- `app/agents/sdk_runtime.py` owns SDK agent construction with optional handoffs.
- Learning conversation service owns when to ask for routing and how to preserve fallback behavior.

## Data Flow

1. Learning message service builds a route input from current stage and user message.
2. Router returns default or specialized route target names.
3. Conversation client builds SDK agent with matching handoff targets.
4. If no route matches, existing default agent path runs unchanged.

## Compatibility

- Route decisions stay internal.
- Public response shapes and SSE event names are unchanged.

## Rollback

Skip route calls and pass `handoffs=None` to the SDK runtime.
