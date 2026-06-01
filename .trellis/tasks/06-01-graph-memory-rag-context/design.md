# Design

## Context Ownership

Memory and RAG context are service-owned inputs to graph execution.

The service layer owns:

- Loading the learner profile summary for the active `user_id`.
- Ensuring and searching persisted teaching chunks for the active `knowledge_point_id`.
- Bounding and redacting the payload before graph invocation.
- Falling back to empty-but-valid context when profile or chunks are absent.

The graph layer owns:

- Consuming `memory_snapshot` and `rag_context` as read-only context.
- Producing routing decisions and typed intents only.

The graph layer does not own database connections, chunk indexing, profile writes, or public API/SSE payload rendering.

## Contract Shape

Add shared typed contracts to `graph_runtime_contracts.py`:

- `GraphMemorySnapshot`: bounded learner profile summary plus source metadata.
- `GraphRagChunk`: bounded current-KP teaching chunk fields.
- `GraphRagContext`: scoped retrieval payload with `knowledge_point_id`, query, retrieval status, and chunks.

Builder helpers apply the existing graph redaction rules so sensitive keys or marker strings are not passed into graph state.

## Data Flow

```text
learning service request
  -> load LearningConversationContext
  -> build GraphMemorySnapshot from learner profile summary
  -> ensure/search teaching_chunks for current knowledge_point_id
  -> build GraphRagContext
  -> invoke orchestration graph with memory_snapshot + rag_context
  -> later invoke learning graph with memory_snapshot + rag_context
  -> service validates intents and writes durable state
```

`LANGGRAPH_ENABLED=false` keeps the prior path and does not invoke graph runtime.

## Retrieval Fallback

Retrieval is bounded and deterministic:

- No profile summary produces an empty memory snapshot.
- No chunks after ensure/search produces `retrieval_status="empty"` and an empty chunk list.
- Empty user text or no full-text hit still uses the existing `search_chunks()` fallback behavior for current-KP chunks.
- Graph exceptions still fall back to the existing service-owned transition logic.

## Compatibility

Public response shape remains unchanged. Memory/RAG context may be used internally by graph state and prompts, but it must not appear in learning message API responses.

## Rollback

Rollback is removing the new context contracts and invocation arguments. No database migration or data cleanup is required.
