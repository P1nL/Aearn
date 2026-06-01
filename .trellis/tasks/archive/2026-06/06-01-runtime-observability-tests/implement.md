# Runtime Observability Tests Implementation Plan

## Checklist

- Add safe observability metadata to `build_learning_graph_stream_events()`.
- Add focused event-stream tests for memory/RAG/fallback/redaction behavior.
- Ensure related tool/profile/router tests are part of final validation.
- Keep event names and core payload fields unchanged.

## Validation

- `uv --directory .\aearn\services\api run python -m pytest tests/test_graph_event_stream.py tests/test_graph_runtime_contracts.py tests/test_learning_graph.py tests/test_agent_write_tools.py tests/test_agent_router.py tests/test_learner_profile.py`
- `uv --directory .\aearn\services\api run ruff check .`
- `uv --directory .\aearn\services\api run python -m mypy app`
