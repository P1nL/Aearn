# Graph Shared Runtime Contracts Implementation Plan

## Checklist

- [ ] Inspect existing `learning_graph.py`, `learning_conversation.py`, onboarding, and review service contracts.
- [ ] Add shared runtime contract module.
- [ ] Add sanitizer/adapters for bounded graph input and safe fallback output.
- [ ] Add tests for safe state, intent shape, and leakage prevention.
- [ ] Run focused tests, ruff, mypy, and task validation.

## Verification

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_graph.py tests/test_llm_integration.py
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
python .\.trellis\scripts\task.py validate .\.trellis\tasks\05-31-graph-shared-runtime-contracts
```
