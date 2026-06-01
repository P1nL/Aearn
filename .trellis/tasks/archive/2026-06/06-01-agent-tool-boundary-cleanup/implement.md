# Agent Tool Boundary Cleanup Implementation Plan

## Checklist

- Extend `AgentSideEffects` with a bounded typed intent list.
- Add a small helper to append `GraphIntent` objects safely.
- Emit intents from all write/tool-effect helper functions.
- Serialize typed intents in learning message metadata.
- Extend `tests/test_agent_write_tools.py` with intent and no-raw-code assertions.

## Validation

- `uv --directory .\aearn\services\api run python -m pytest tests/test_agent_write_tools.py tests/test_learning_sessions_m3.py`
- `uv --directory .\aearn\services\api run ruff check .`
- `uv --directory .\aearn\services\api run python -m mypy app`

## Rollback

- Remove the `typed_intents` field and helper calls; existing side-effect lists remain enough for current service behavior.
