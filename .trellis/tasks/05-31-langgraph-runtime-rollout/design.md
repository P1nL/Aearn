# LangGraph Runtime Rollout Design

## Boundaries

- `app/agents/learning_graph.py` owns graph construction and node-level orchestration skeleton.
- Learning conversation service owns public response mapping and durable writes.
- `LANGGRAPH_ENABLED` controls whether graph execution is attempted.

## Data Flow

1. Learning message service checks `settings.langgraph_enabled`.
2. Flag off: existing service path runs unchanged.
3. Flag on: service builds sanitized `AgentState` and invokes compiled graph.
4. Graph output is adapted back into the same public response contract.
5. On graph failure, service falls back safely or returns a normalized recoverable error.

## Compatibility

- Default flag-off path is the release-safe behavior.
- Flag-on path must be testable without live model credentials.

## Rollback

Set `LANGGRAPH_ENABLED=false`.
