# Implementation Plan

## Steps

1. Add typed boundary ownership metadata and validation helpers in `app/agents/graph_runtime_contracts.py`.
2. Wire learning graph service consumption through the boundary validator before applying intents.
3. Preserve fallback behavior: validation failures in the graph path fall back to the imperative transition path for now.
4. Add focused unit tests for boundary metadata and validation.
5. Add or extend learning message tests to prove unsupported graph intents are not blindly executed and do not leak into the public response.
6. Run focused tests first, then backend quality gates.

## Validation

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_graph_runtime_contracts.py tests/test_learning_graph.py tests/test_learning_sessions_m3.py
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
```

Run the full backend test suite before archiving if focused checks pass quickly.

## Review Gates

- No graph node imports repository modules or opens database connections.
- Boundary validation is service-side and does not change public response fields.
- Any new public/SSE-facing behavior is deferred to later child tasks unless already present.
