# Learning Graph Real Orchestration Implementation Plan

## Checklist

- [ ] Map current `learning_conversation.py` transition branches.
- [ ] Extend learning graph nodes to emit stage/tool intents.
- [ ] Add graph result adapter in the learning service.
- [ ] Switch graph-enabled path to primary learning orchestration.
- [ ] Add graph-enabled parity tests for learning message JSON and SSE.
- [ ] Run focused tests, ruff, mypy, and task validation.

## Verification

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_graph.py tests/test_learning_sessions_m3.py
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
python .\.trellis\scripts\task.py validate .\.trellis\tasks\05-31-learning-graph-real-orchestration
```
