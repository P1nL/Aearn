# LangGraph Runtime Rollout Implementation Plan

## Checklist

- [x] Inspect `learning_graph.py`, settings, and learning message orchestration.
- [x] Add feature-flag branch at a real service boundary.
- [x] Build sanitized `AgentState` adapter and response adapter.
- [x] Preserve default path and failure handling.
- [x] Add tests for flag-off and flag-on invocation.
- [x] Run focused tests, ruff, mypy, and task validation.

## Verification

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_graph.py tests/test_learning_sessions_m3.py
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
python .\.trellis\scripts\task.py validate .\.trellis\tasks\05-31-langgraph-runtime-rollout
```
