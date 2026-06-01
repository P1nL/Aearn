# Design

## Scope

This task adds regression tests around the graph runtime boundary. It does not change graph routing, persistence behavior, public API shape, or desktop UI behavior unless the new tests expose an existing bug.

## Test Layers

Unit-level learning service tests cover the narrow service consumption contract:

- `invoke_orchestration()` may return a `GraphRunResult`.
- `validate_run_result_for_boundary()` must reject unscoped graph output before service execution.
- `_determine_transition_via_graph()` consumes only scoped stage and tool intents.
- `FEEDBACK_REQUEST -> human_checkpoint` remains accepted for boundary validation but does not become a public learning tool transition.

Existing route-level tests remain the source for end-to-end compatibility:

- learning message JSON/SSE graph-enabled paths
- onboarding route decision fallback
- review route decision fallback and not-due behavior

## Data Flow Under Test

```text
learning message request
  -> service loads safe context
  -> service injects GraphMemorySnapshot + GraphRagContext
  -> graph returns GraphRunResult
  -> service validates allowed targets
  -> service executes stage/tool intents only
  -> route maps safe runtime context to existing SSE frames
```

## Compatibility

- `LANGGRAPH_ENABLED=false` remains the default local compatibility path.
- Idempotency replay must not re-run graph decisions or synthesize graph status events.
- The tests must not require PostgreSQL unless they intentionally cover an existing route-level path that already requires it.

## Rollback

Rollback is removing the new tests and this task's planning artifacts. No database, API, or frontend rollback is expected.
