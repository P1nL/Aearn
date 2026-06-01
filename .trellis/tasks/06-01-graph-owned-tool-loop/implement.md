# Implementation Plan

## Steps

1. Extend the learning graph orchestration output with ordered `tool_names`.
2. Update `graph_result_to_run_result()` to emit ordered `TOOL_CALL` intents.
3. Extend `LearningConversationTransition` with ordered tool names while preserving `tool_name` compatibility.
4. Update learning service tool execution to honor ordered graph tool calls.
5. Add focused tests for graph-owned multi-tool order and route-level payload order.
6. Run focused graph/learning-session tests, then backend quality gates.

## Validation

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_graph.py tests/test_learning_sessions_m3.py -k "tool or langgraph"
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
uv --directory .\aearn\services\api run python -m pytest
pnpm --dir .\aearn desktop:check
```

## Review Gates

- Graph only emits tool decisions; service still builds tool payloads and persists state.
- Multi-tool execution order is deterministic and covered by tests.
- Public `tool_calls` payloads remain unchanged.
