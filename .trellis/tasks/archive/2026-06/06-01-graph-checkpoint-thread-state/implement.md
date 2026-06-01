# Implementation Plan

## Steps

1. Add `GraphCheckpointThreadState` and `build_checkpoint_thread_state()` to `graph_runtime_contracts.py`.
2. Add unit tests for deterministic thread ids, namespace bounding, optional checkpoint ids, and metadata redaction.
3. Wire thread config into `invoke_orchestration()`.
4. Wire thread config into `_context_with_langgraph_runtime()`.
5. Update existing fake graph tests to accept and assert config where useful.
6. Run focused graph and learning-session tests, then backend quality gates.

## Validation

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_graph_runtime_contracts.py tests/test_learning_graph.py tests/test_learning_sessions_m3.py -k "langgraph or checkpoint or GraphRuntime"
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
uv --directory .\aearn\services\api run python -m pytest
pnpm --dir .\aearn desktop:check
```

## Review Gates

- No new database table, migration, or checkpointer rollout in this task.
- Thread config must be service-derived and deterministic.
- Durable learning state remains owned by services/repositories.
