# Multi-Agent Handoff Minimal Implementation Plan

## Checklist

- Extend `route_message()` with optional signal inputs.
- Add safe helpers for recent error, exercise/tool availability, and profile weak-signal detection.
- Pass learning conversation context into `route_message()`.
- Extend router tests for recent error, profile, and tool-context decisions.
- Run learning conversation tests that assert handoff targets are still sanitized.

## Validation

- `uv --directory .\aearn\services\api run python -m pytest tests/test_agent_router.py tests/test_learning_sessions_m3.py tests/test_llm_integration.py`
- `uv --directory .\aearn\services\api run ruff check .`
- `uv --directory .\aearn\services\api run python -m mypy app`
