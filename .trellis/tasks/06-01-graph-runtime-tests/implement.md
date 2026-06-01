# Implementation Plan

## Checklist

- [x] Add focused unit coverage for learning service consumption of ordered graph intents.
- [x] Add focused unit coverage for invalid graph intents falling back to the imperative service transition.
- [x] Add focused unit coverage proving memory/RAG context is passed to the graph invocation.
- [x] Reuse existing graph event stream tests for safe SSE vocabulary and add assertions only if a gap is found.
- [x] Run targeted graph/runtime test files.
- [x] Run backend `ruff` and `mypy`.
- [ ] Validate and archive the Trellis task after checks pass.

## Validation Commands

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_graph.py tests/test_graph_runtime_contracts.py tests/test_graph_event_stream.py
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py tests/test_onboarding_m2.py tests/test_reviews_m4.py
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
```

## Risk Notes

- `tests/test_learning_sessions_m3.py`, `tests/test_onboarding_m2.py`, and `tests/test_reviews_m4.py` use the local bootstrap database; run these batches sequentially.
- Keep `.codex/config.toml` and `.claude/skills/grill-me/` out of staging.
