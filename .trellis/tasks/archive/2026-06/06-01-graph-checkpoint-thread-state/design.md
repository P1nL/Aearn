# Design

## Thread Strategy

The service layer owns graph thread identity. A graph thread is derived from durable Aearn session facts rather than from graph-internal state:

```text
thread_id = aearn:<session_type>:<session_id>
checkpoint_ns = <graph namespace>
```

For the learning page:

- The learning graph context path uses namespace `learning`.
- The single-step orchestration graph uses namespace `learning_orchestration`.
- The same `session_id` and `session_type` always produce the same thread id.
- Different `session_type` values produce different thread ids even when the row id is the same.

## Persistence Boundary

LangGraph checkpointing is not product persistence. It can resume graph execution details once a checkpointer is introduced, but Aearn durable state remains in:

- `learning_sessions`
- `learning_messages`
- `attempts`
- `knowledge_points`
- `review_states`
- `idempotency_records`

This task only establishes thread/config plumbing. It does not introduce a Postgres checkpointer, migration, or graph-owned write path.

## Contract Shape

Add a `GraphCheckpointThreadState` contract and helpers to `graph_runtime_contracts.py`:

- `build_checkpoint_thread_state(session_id, user_id, session_type, checkpoint_ns, checkpoint_id=None, metadata=None)`
- `GraphCheckpointThreadState.to_config() -> {"configurable": {"thread_id": ..., "checkpoint_ns": ...}, "metadata": ...}`

The metadata is optional, bounded, and redacted through existing graph redaction helpers.

## Invocation Wiring

Update the learning graph call sites:

- `invoke_orchestration()` builds thread config from session facts and passes it to `compiled.invoke(input_state, config)`.
- `_context_with_langgraph_runtime()` builds thread config for the full learning graph and passes it to `compile_learning_graph().invoke(graph_state, config)`.

Tests use fake compiled graphs that accept an optional config argument and assert the thread config is passed. Existing fake graph tests are updated without changing public response shapes.

## Rollback

Rollback is removing the config argument and helper use. Since this task does not add durable checkpointer storage, rollback does not require database migration cleanup.
