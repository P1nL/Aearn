# Implementation Plan

## Steps

1. Add `GraphHumanCheckpoint` and `build_graph_human_checkpoint()` with bounding/redaction tests.
2. Extend learning orchestration output with optional `human_checkpoint` metadata.
3. Convert valid checkpoint metadata to a scoped `feedback_request` intent in `graph_result_to_run_result()`.
4. Allow `feedback_request -> human_checkpoint` in the learning service boundary.
5. Add graph tests for early-practice approval, readiness clarification, direct-answer safety, and redaction.
6. Add a route-level fake graph test that a scoped checkpoint intent is accepted without leaking raw checkpoint metadata.
7. Run focused graph/session tests plus backend lint/type checks.

## Validation

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_graph_runtime_contracts.py tests/test_learning_graph.py tests/test_learning_sessions_m3.py -k "checkpoint or human or langgraph"
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
```

## Review Gates

- Checkpoint metadata is bounded and redacted before graph results leave the graph adapter.
- Checkpoints are represented as service-consumed feedback intents, not graph-owned durable writes.
- Public responses do not expose raw `human_checkpoint` or graph diagnostics.
- `LANGGRAPH_ENABLED=false` remains unchanged.
