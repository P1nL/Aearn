# Learning Agent Side Effects Wiring Implementation Plan

## Checklist

- [x] Inventory the learning message route -> repository -> conversation call chain.
- [x] Identify the safest source of exercise/latest-attempt facts for `LearningToolContext`.
- [x] Instantiate `AgentSideEffects` per request.
- [x] Pass `side_effects` and `tool_context` into `start_learning_message_generation`.
- [x] Add safe draining/metadata behavior for accumulated side effects.
- [x] Add regression tests that assert tools are built with real context.
- [x] Run focused learning tests, ruff, mypy, and task validation.

## Verification

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
python .\.trellis\scripts\task.py validate .\.trellis\tasks\05-31-learning-agent-side-effects-wiring
```
