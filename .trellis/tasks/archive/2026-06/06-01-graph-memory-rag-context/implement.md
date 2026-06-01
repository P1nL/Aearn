# Implementation Plan

## Steps

1. Add typed memory and RAG context contracts with bounding/redaction tests.
2. Extend `AgentState` and `OrchestrationInput` with `rag_context` and typed `memory_snapshot`.
3. Build service-owned graph context from learner profile summary and current-KP teaching chunks.
4. Pass bounded memory/RAG context into orchestration graph and learning graph invocations.
5. Add route-level tests that capture graph state/input and verify no public response leakage.
6. Run focused graph/session tests, then backend and desktop quality gates.

## Validation

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_graph_runtime_contracts.py tests/test_learning_graph.py tests/test_learning_sessions_m3.py -k "memory or rag or langgraph"
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_graph.py tests/test_learning_sessions_m3.py
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
uv --directory .\aearn\services\api run python -m pytest
pnpm --dir .\aearn desktop:check
```

## Review Gates

- Graph input context is bounded and redacted before graph invocation.
- Retrieval stays scoped to the active `knowledge_point_id`.
- Public API responses do not expose internal graph memory/RAG details.
- Durable writes remain service/repository owned.
