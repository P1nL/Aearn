# Implementation Plan

## Steps

1. Add `app/services/graph_event_stream.py` with typed safe graph stream events.
2. Unit-test adapter output, redaction, bounding, and disabled/empty cases.
3. Hook learning message SSE after graph-enabled context preparation and before agent text streaming.
4. Add route-level SSE tests for graph-enabled ordering and flag-off compatibility.
5. Run focused SSE/session tests plus backend lint/type checks.

## Validation

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_graph_event_stream.py tests/test_learning_sessions_m3.py -k "stream or graph"
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
```

## Review Gates

- No new frontend event types.
- No graph diagnostics or sensitive values in SSE payloads.
- Existing replay and JSON paths stay unchanged.
- `LANGGRAPH_ENABLED=false` emits the same stream sequence as before.
