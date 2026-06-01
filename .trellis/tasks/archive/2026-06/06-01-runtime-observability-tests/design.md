# Runtime Observability Tests Design

## Observability Shape

The learning graph SSE adapter keeps the existing `tool_status` event and adds safe fields:

- `observability.memory_available`
- `observability.rag_retrieval_status`
- `observability.rag_chunk_count`
- `observability.fallback_used`
- `observability.next_action`

The payload remains bounded and redacted through graph contract helpers.

## Test Coverage

- `tests/test_graph_event_stream.py`: graph observability payload and redaction.
- `tests/test_agent_write_tools.py`: typed tool intents.
- `tests/test_learner_profile.py`: stable memory signal derivation.
- `tests/test_agent_router.py`: signal-aware handoff routing.
- Existing graph/runtime tests prove production orchestration still accepts the new metadata.

## Compatibility

- Existing clients that read only `node`, `tool`, `status`, and `message` continue to work.
- New observability fields are additive.
